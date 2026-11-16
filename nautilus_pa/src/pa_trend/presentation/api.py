"""SACW V1.1.2 第 6 章的 HTTP API（标准库实现，无第三方框架）。

统一响应信封：

.. code-block:: json

   {"data": ..., "meta": {"request_id": "..."}, "error": null}

错误时 ``data`` 为 ``null``、``error`` 为 ``{"code", "message"}``。

路由分组：

- ``/api/v1/market/*``：K 线、数据集、覆盖情况与看板快照；
- ``/api/v1/indicators/series``：指标序列（``atr_ma22`` 固定返回
  ``N/A / SPEC_AMBIGUITY``）；
- ``/api/v1/annotation-projects/*``、``/api/v1/annotations/*``：标注与修订；
- ``/api/v1/zones/preview``：ANCHOR_ONLY 后端几何计算（SACW 21.2）；
- ``/api/v1/golden-datasets``：黄金样本冻结；
- ``/api/v1/regression-*``：PB 回归工作台；
- ``/api/v1/comparisons/*``：人工与程序差异匹配。
"""

from __future__ import annotations

import json
import re
import traceback
import uuid
from collections.abc import Callable
from decimal import Decimal
from http import HTTPStatus
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import parse_qs, urlparse

from pa_trend.application.annotation_store import (
    GROUND_TRUTH_SOURCES,
    GROUND_TRUTH_STATUSES,
    SacwStore,
    StoreError,
)
from pa_trend.application.data_service import DataService
from pa_trend.application.matching import (
    MatcherConfig,
    SwingCandidate,
    match_swings,
    match_zones,
)
from pa_trend.application.regression import RegressionRunner, load_cases, validate_cases
from pa_trend.application.snapshot import build_snapshot, replay_and_snapshot
from pa_trend.config.validation import Stage, validate_startup
from pa_trend.domain.errors import ConfigurationError, PaTrendError
from pa_trend.domain.models.bar import Bar
from pa_trend.domain.models.timeframe import Timeframe, expected_close_ns

JSON = dict[str, Any]
Route = tuple[str, re.Pattern[str], Callable[..., Any]]


class HandlerLike(Protocol):
    """``read_body`` 需要的最小请求处理器协议。"""

    headers: Any
    rfile: Any


class ApiError(PaTrendError):
    """带 HTTP 状态码的接口错误。"""

    def __init__(
        self,
        code: str,
        message: str,
        status: HTTPStatus = HTTPStatus.BAD_REQUEST,
    ) -> None:
        """初始化错误。"""
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def _parse_timeframe(value: str | None) -> Timeframe:
    if not value:
        raise ApiError("MISSING_TIMEFRAME", "timeframe is required")
    for timeframe in Timeframe:
        if timeframe.value == value.upper():
            return timeframe
    raise ApiError("UNKNOWN_TIMEFRAME", f"unknown timeframe: {value}")


def _timeframe_duration_ns(timeframe: Timeframe) -> int:
    start = 1_704_067_200_000_000_000  # 2024-01-01T00:00:00Z
    return expected_close_ns(start, timeframe) - start


def _iso_to_ns(value: str) -> int:
    from datetime import datetime

    text = value.replace("Z", "+00:00")
    return int(datetime.fromisoformat(text).timestamp() * 1_000_000_000)


def _ns_to_iso(value: int) -> str:
    from pa_trend.domain.models.timeframe import ns_to_dt

    return ns_to_dt(value).isoformat().replace("+00:00", "Z")


class ApiRouter:
    """把请求分发到具体处理器。"""

    def __init__(
        self,
        *,
        service: DataService,
        store: SacwStore,
        regression: RegressionRunner,
        configs_dir: Path | None = None,
    ) -> None:
        """初始化路由表。"""
        self.service = service
        self.store = store
        self.regression = regression
        self.configs_dir = configs_dir
        self._routes: list[Route] = []
        self._register()

    # ------------------------------------------------------------------ 路由

    def _add(self, method: str, pattern: str, handler: Callable[..., Any]) -> None:
        self._routes.append((method, re.compile(f"^{pattern}$"), handler))

    def _register(self) -> None:
        add = self._add

        add("GET", r"/api/v1/meta", self.meta)
        add("GET", r"/api/v1/market/snapshot", self.snapshot_payload)
        add("GET", r"/api/v1/market/live", self.market_live)
        add("GET", r"/api/v1/market/bars", self.market_bars)
        add("GET", r"/api/v1/market/datasets", self.market_datasets)
        add("GET", r"/api/v1/market/coverage", self.market_coverage)
        add("GET", r"/api/v1/indicators/series", self.indicator_series)
        add("POST", r"/api/v1/zones/preview", self.zone_preview)

        add("GET", r"/api/v1/annotation-projects", self.list_projects)
        add("POST", r"/api/v1/annotation-projects", self.create_project)
        add(
            "GET",
            r"/api/v1/annotation-projects/(?P<project_id>[\w\-]+)/annotations",
            self.list_annotations,
        )
        add(
            "POST",
            r"/api/v1/annotation-projects/(?P<project_id>[\w\-]+)/annotations",
            self.create_annotation,
        )
        add(
            "GET",
            r"/api/v1/annotation-projects/(?P<project_id>[\w\-]+)/ground-truth-hash",
            self.ground_truth_hash,
        )
        add(
            "POST",
            r"/api/v1/annotation-projects/(?P<project_id>[\w\-]+)/comparisons/swings",
            self.compare_swings,
        )
        add(
            "POST",
            r"/api/v1/annotation-projects/(?P<project_id>[\w\-]+)/comparisons/zones",
            self.compare_zones,
        )

        add("GET", r"/api/v1/annotations/(?P<annotation_id>[\w\-]+)", self.get_annotation)
        add("PATCH", r"/api/v1/annotations/(?P<annotation_id>[\w\-]+)", self.revise_annotation)
        add(
            "POST",
            r"/api/v1/annotations/(?P<annotation_id>[\w\-]+)/status",
            self.set_annotation_status,
        )
        add(
            "POST",
            r"/api/v1/annotations/(?P<annotation_id>[\w\-]+)/"
            r"(?P<action>submit|review|approve|freeze)",
            self.annotation_action,
        )
        add(
            "GET",
            r"/api/v1/annotations/(?P<annotation_id>[\w\-]+)/revisions",
            self.list_revisions,
        )
        add("GET", r"/api/v1/audit-logs", self.audit_logs)

        add("GET", r"/api/v1/boundary-overrides", self.list_overrides)
        add("POST", r"/api/v1/boundary-overrides", self.create_override)
        add(
            "POST",
            r"/api/v1/boundary-overrides/(?P<override_id>[\w\-]+)/review",
            self.review_override,
        )

        add("GET", r"/api/v1/golden-datasets", self.list_golden)
        add("POST", r"/api/v1/golden-datasets", self.freeze_golden)

        add("GET", r"/api/v1/snapshots", self.build_snapshot_view)

        add("GET", r"/api/v1/regression-cases", self.list_regression_cases)
        add("GET", r"/api/v1/regression-cases/(?P<case_id>[\w\-]+)", self.get_regression_case)
        add(
            "POST",
            r"/api/v1/regression-cases/(?P<case_id>[\w\-]+)/runs",
            self.run_regression_case,
        )
        add(
            "POST",
            r"/api/v1/regression-suites/v1-4-8/run",
            self.run_regression_suite,
        )
        add("GET", r"/api/v1/regression-runs", self.list_regression_runs)
        add(
            "GET",
            r"/api/v1/regression-runs/(?P<run_id>[\w\-]+)/assertions",
            self.list_regression_assertions,
        )
        add("GET", r"/api/v1/regression-runs/(?P<run_id>[\w\-]+)", self.get_regression_run)

    def dispatch(
        self,
        *,
        method: str,
        path: str,
        query: dict[str, list[str]],
        body: JSON | None,
    ) -> tuple[HTTPStatus, JSON]:
        """执行路由并返回 ``(status, envelope)``。"""
        request_id = uuid.uuid4().hex
        for route_method, pattern, handler in self._routes:
            if route_method != method:
                continue
            match = pattern.match(path)
            if match is None:
                continue
            try:
                data = handler(query=query, body=body or {}, params=match.groupdict())
            except ApiError as exc:
                return exc.status, _error_envelope(request_id, exc.code, exc.message)
            except (StoreError, ConfigurationError, ValueError) as exc:
                return (
                    HTTPStatus.BAD_REQUEST,
                    _error_envelope(request_id, "VALIDATION_ERROR", str(exc)),
                )
            except Exception as exc:
                traceback.print_exc()
                return (
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    _error_envelope(
                        request_id,
                        "INTERNAL_ERROR",
                        f"{type(exc).__name__}: {exc}",
                    ),
                )
            return HTTPStatus.OK, _ok_envelope(request_id, data)
        return (
            HTTPStatus.NOT_FOUND,
            _error_envelope(request_id, "NOT_FOUND", f"no route for {method} {path}"),
        )

    # ------------------------------------------------------------- 市场数据

    def meta(self, **_: object) -> JSON:
        """返回接口与引擎元信息。"""
        from pa_trend.application.timeframe_engine import ATR_MA_STATUS

        dataset = self.service.dataset_info()
        return {
            "instrumentId": self.service.instrument_id,
            "source": self.service.source,
            "sessionOffsetHours": self.service.session_offset_hours,
            "specVersion": "V1.4.8",
            "sacwVersion": "V1.1.2",
            "configHash": self.service.config_hash,
            "dataset": {
                "datasetId": dataset.dataset_id,
                "dataHash": dataset.data_hash,
                "timeframes": list(dataset.timeframes),
            },
            "atrMaStatus": ATR_MA_STATUS,
            "nStructureInvalidationStatus": "SPEC_AMBIGUITY",
            "timeframes": [
                {"code": timeframe.value, "label": timeframe.label} for timeframe in Timeframe
            ],
            "regressionCaseCount": (
                len(load_cases(self.configs_dir)) if self.configs_dir is not None else None
            ),
        }

    def snapshot_payload(self, **_: object) -> JSON:
        """返回看板载荷。"""
        return self.service.payload()

    def market_live(self, *, query: dict[str, list[str]], **_: object) -> JSON:
        """返回采集器新落盘 K 线的增量视图（实时刷新，SACW 6.1）。

        工作台只在启动时构建一次视图；采集器持续写入 Parquet，因此前端轮询
        本接口：

        - 服务端先检测新 K 线并按需重建视图；
        - ``changed`` 为真时按周期下发 ``since_close_ns`` 之后的 K 线与指标点，
          前端只追加这些增量；
        - 增量超过 :data:`~pa_trend.application.data_service.MAX_LIVE_BARS` 根
          时下发 ``reload``，前端改为整页重载，避免在前端拼接过长历史。
        """
        status = self.service.refresh()
        since_ns = _parse_since(query)
        changes = status["changesByTimeframe"]
        timeframes: list[JSON] = []
        for timeframe in Timeframe:
            label = timeframe.value
            changed = bool(changes.get(label))
            count = int(changes.get(label, 0))
            reload_required = changed and count > status["maxLiveBars"]
            payload: JSON = {
                "timeframe": label,
                "changed": changed,
                "added": count,
                "reload": reload_required
                or (changed and since_ns is not None and label not in changes),
                "bars": [],
                "series": None,
            }
            if changed and not reload_required:
                bars = self.service.bars_since(timeframe, since_close_ns=since_ns)
                timeframes.append(
                    payload
                    | {
                        "bars": [_bar_payload(bar, self.service.source) for bar in bars],
                        "series": self.service.timeframe_section_view(timeframe),
                    },
                )
                continue
            timeframes.append(payload)

        dataset = self.service.dataset_info()
        return {
            "changed": status["changed"],
            "addedBars": status["addedBars"],
            "changesByTimeframe": changes,
            "refreshIntervalSecs": status["refreshIntervalSecs"],
            "maxLiveBars": status["maxLiveBars"],
            "buildCount": status["buildCount"],
            "buildMillis": status["buildMillis"],
            "refreshMillis": status["refreshMillis"],
            "lastBarAt": _ns_to_iso(status["lastBarAtNs"])
            if status["lastBarAtNs"] is not None
            else None,
            "generatedAt": _iso_now(),
            "datasetId": dataset.dataset_id,
            "dataHash": dataset.data_hash,
            "timeframes": timeframes,
        }

    def market_bars(self, *, query: dict[str, list[str]], **_: object) -> JSON:
        """按周期与时间范围查询 K 线（SACW 6.1）。"""
        timeframe = _parse_timeframe(_first(query, "timeframe"))
        bars = self.service.bars(timeframe)

        start = _first(query, "from")
        end = _first(query, "to")
        limit = int(_first(query, "limit") or 1000)
        cursor = int(_first(query, "cursor") or 0)

        selected = list(bars)
        if start:
            start_ns = _iso_to_ns(start) if "-" in start else int(start)
            selected = [bar for bar in selected if bar.ts_open_ns >= start_ns]
        if end:
            end_ns = _iso_to_ns(end) if "-" in end else int(end)
            selected = [bar for bar in selected if bar.ts_open_ns < end_ns]

        window = selected[cursor : cursor + limit]
        next_cursor = cursor + limit if cursor + limit < len(selected) else None
        return {
            "timeframe": timeframe.value,
            "bars": [_bar_payload(bar, self.service.source) for bar in window],
            "nextCursor": next_cursor,
            "datasetId": self.service.dataset_info().dataset_id,
            "dataHash": self.service.dataset_info().data_hash,
        }

    def market_datasets(self, **_: object) -> JSON:
        """返回数据集列表（当前只有一个活动数据集）。"""
        dataset = self.service.dataset_info()
        return {
            "datasets": [
                {
                    "datasetId": dataset.dataset_id,
                    "instrumentId": dataset.instrument_id,
                    "source": dataset.source,
                    "dataHash": dataset.data_hash,
                    "rangeStart": None
                    if dataset.range_start_ns is None
                    else _ns_to_iso(dataset.range_start_ns),
                    "rangeEnd": None
                    if dataset.range_end_ns is None
                    else _ns_to_iso(dataset.range_end_ns),
                    "timeframes": list(dataset.timeframes),
                },
            ],
            "stored": self.store.list_market_datasets(),
        }

    def market_coverage(self, **_: object) -> JSON:
        """返回多周期数据覆盖与完整性。"""
        coverage = self.service.coverage()
        return {
            "datasetId": self.service.dataset_info().dataset_id,
            "timeframes": coverage,
            "allClean": all(item["clean"] for item in coverage),
        }

    def indicator_series(self, *, query: dict[str, list[str]], **_: object) -> JSON:
        """返回指标序列。"""
        timeframe = _parse_timeframe(_first(query, "timeframe"))
        fields = [
            item.strip()
            for item in (_first(query, "fields") or "sma22,atr14,atr_ma22").split(",")
            if item.strip()
        ]
        return self.service.indicator_series(timeframe=timeframe, fields=fields)

    def zone_preview(self, *, body: JSON, **_: object) -> JSON:
        """按锚点计算 ANCHOR_ONLY Zone 几何（SACW 21.2）。"""
        timeframe = _parse_timeframe(str(body.get("timeframe", "")))
        anchors = body.get("anchorSwingIds") or body.get("anchor_swing_ids") or []
        if not isinstance(anchors, list):
            raise ApiError("INVALID_ANCHORS", "anchorSwingIds must be a list")
        return self.service.zone_preview(
            timeframe=timeframe,
            anchor_swing_ids=[str(item) for item in anchors],
        )

    # --------------------------------------------------------------- 标注

    def list_projects(self, **_: object) -> JSON:
        """列出标注项目。"""
        projects = self.store.list_projects()
        if not projects:
            projects = [self.store.ensure_project()]
        return {"projects": projects}

    def create_project(self, *, body: JSON, **_: object) -> JSON:
        """创建标注项目。"""
        name = str(body.get("name") or "").strip()
        if not name:
            raise ApiError("MISSING_NAME", "name is required")
        return self.store.create_project(
            name=name,
            actor=str(body.get("actor") or "web"),
        )

    def list_annotations(self, *, query: dict[str, list[str]], params: JSON, **_: object) -> JSON:
        """列出项目下的标注。"""
        project_id = params["project_id"]
        if self.store.get_project(project_id) is None:
            raise ApiError(
                "UNKNOWN_PROJECT",
                f"unknown project: {project_id}",
                HTTPStatus.NOT_FOUND,
            )
        rows = self.store.list_annotations(
            project_id,
            entity_type=_first(query, "entity_type"),
            timeframe=_first(query, "timeframe"),
            status=_first(query, "status"),
        )
        return {"annotations": rows, "count": len(rows)}

    def create_annotation(self, *, body: JSON, params: JSON, **_: object) -> JSON:
        """创建标注；新标注一律为 DRAFT，Zone 边界按后端公式计算。"""
        project_id = params["project_id"]
        if self.store.get_project(project_id) is None:
            raise ApiError(
                "UNKNOWN_PROJECT",
                f"unknown project: {project_id}",
                HTTPStatus.NOT_FOUND,
            )

        entity_type = str(body.get("entity_type") or "").strip().upper()
        timeframe = _parse_timeframe(str(body.get("timeframe") or ""))
        payload = dict(body.get("payload") or {})

        # SACW 4.3：人工标注先保存为 DRAFT，不能由客户端直接伪造终态。
        requested_status = str(body.get("status") or "DRAFT").upper()
        if requested_status != "DRAFT":
            raise ApiError(
                "INVALID_INITIAL_STATUS",
                "new annotations must start as DRAFT",
            )
        label_source = str(body.get("label_source") or "HUMAN_PRIMARY").upper()
        if label_source not in GROUND_TRUTH_SOURCES:
            raise ApiError(
                "INVALID_LABEL_SOURCE",
                "annotation projects accept HUMAN_PRIMARY or HUMAN_REVIEWED only",
            )
        # 15M 不维护独立 ProtectedLow（V1.4.8 第 8 章）。
        if entity_type == "PROTECTED_POINT" and timeframe is Timeframe.MIN15:
            raise ApiError(
                "PROTECTED_POINT_15M_NOT_ALLOWED",
                "15M has no independent ProtectedLow; reference the valid NStructure.L2",
            )

        if entity_type == "ZONE":
            mode = str(payload.get("annotation_mode") or "ANCHOR_ONLY").upper()
            payload["annotation_mode"] = mode
            if mode == "ANCHOR_ONLY_WITH_OVERRIDE":
                raise ApiError(
                    "OVERRIDE_WORKFLOW_REQUIRED",
                    "create an ANCHOR_ONLY Zone first, then request a boundary override",
                )
            anchors = payload.get("anchor_swing_ids") or []
            if not isinstance(anchors, list) or len(anchors) < 2:
                raise ApiError(
                    "INSUFFICIENT_ANCHORS",
                    "Zone requires at least two anchor swing ids",
                )
            preview = self.service.zone_preview(
                timeframe=timeframe,
                anchor_swing_ids=[str(item) for item in anchors],
            )
            payload["anchors"] = preview["anchors"]
            payload["atr_snapshot"] = preview["atrSnapshot"]
            payload["tick_size"] = preview["tickSize"]
            payload["tick_size_version"] = preview["tickSizeVersion"]
            payload["zone_parameters"] = preview["zoneParameters"]
            payload["config_hash"] = preview["configHash"]
            payload["zone_type"] = preview["zoneType"]
            if mode == "ANCHOR_ONLY":
                # 后端计算值覆盖任何前端传入值，禁止前端重写公式。
                payload["center"] = preview["center"]
                payload["lower"] = preview["lower"]
                payload["upper"] = preview["upper"]
                payload["half_width"] = preview["halfWidth"]
                payload["half_width_basis"] = preview["halfWidthBasis"]
                payload["formula_version"] = preview["formulaVersion"]
            else:
                # HUMAN_BOUNDARY：人工边界与程序边界分开保存（SACW 21.3）。
                payload["program_center"] = preview["center"]
                payload["program_lower"] = preview["lower"]
                payload["program_upper"] = preview["upper"]
                payload["program_half_width"] = preview["halfWidth"]
                payload["program_half_width_basis"] = preview["halfWidthBasis"]
                payload["program_formula_version"] = preview["formulaVersion"]

        dataset = self.service.dataset_info()
        return self.store.create_annotation(
            project_id=project_id,
            entity_type=entity_type,
            timeframe=timeframe.value,
            payload=payload,
            instrument_id=self.service.instrument_id,
            actor=str(body.get("actor") or "web"),
            label_source=label_source,
            status="DRAFT",
            dataset_id=str(body.get("dataset_id") or dataset.dataset_id),
            config_hash=self.service.config_hash,
            reason=str(body.get("reason") or "created from web workbench"),
        )

    def get_annotation(self, *, params: JSON, **_: object) -> JSON:
        """读取标注。"""
        annotation = self.store.get_annotation(params["annotation_id"])
        if annotation is None:
            raise ApiError("UNKNOWN_ANNOTATION", "annotation not found", HTTPStatus.NOT_FOUND)
        return annotation

    def revise_annotation(self, *, body: JSON, params: JSON, **_: object) -> JSON:
        """追加标注修订。"""
        payload = body.get("payload")
        if not isinstance(payload, dict):
            raise ApiError("MISSING_PAYLOAD", "payload is required")
        existing = self.store.get_annotation(params["annotation_id"])
        if existing is None:
            raise ApiError("UNKNOWN_ANNOTATION", "annotation not found", HTTPStatus.NOT_FOUND)
        if (
            existing["entity_type"] == "PROTECTED_POINT"
            and existing["timeframe"] == Timeframe.MIN15.value
        ):
            raise ApiError(
                "PROTECTED_POINT_15M_NOT_ALLOWED",
                "15M has no independent ProtectedLow; reference the valid NStructure.L2",
            )
        return self.store.revise_annotation(
            annotation_id=params["annotation_id"],
            payload=payload,
            actor=str(body.get("actor") or "web"),
            reason=str(body.get("reason") or "revised from web workbench"),
        )

    def set_annotation_status(self, *, body: JSON, params: JSON, **_: object) -> JSON:
        """迁移标注状态。"""
        status = str(body.get("status") or "").upper()
        if not status:
            raise ApiError("MISSING_STATUS", "status is required")
        return self.store.transition_annotation(
            annotation_id=params["annotation_id"],
            status=status,
            actor=str(body.get("actor") or "web"),
            reason=body.get("reason"),
        )

    def annotation_action(self, *, body: JSON, params: JSON, **_: object) -> JSON:
        """按 SACW 6.2 的显式动作推进标注状态。"""
        target = {
            "submit": "SUBMITTED",
            "review": "REVIEWED",
            "approve": "APPROVED",
            "freeze": "FROZEN",
        }[params["action"]]
        return self.store.transition_annotation(
            annotation_id=params["annotation_id"],
            status=target,
            actor=str(body.get("actor") or "web"),
            reason=body.get("reason"),
        )

    def list_revisions(self, *, params: JSON, **_: object) -> JSON:
        """列出标注修订历史。"""
        return {"revisions": self.store.list_revisions(params["annotation_id"])}

    def ground_truth_hash(self, *, params: JSON, **_: object) -> JSON:
        """返回项目正式 Ground Truth 的标注哈希。"""
        project_id = params["project_id"]
        rows = self.store.list_annotations(project_id)
        usable = [row for row in rows if row["status"] in {"APPROVED", "FROZEN"}]
        return {
            "projectId": project_id,
            "annotationHash": self.store.annotation_hash(project_id),
            "annotationCount": len(usable),
            "statuses": sorted({row["status"] for row in usable}),
        }

    def audit_logs(self, *, query: dict[str, list[str]], **_: object) -> JSON:
        """返回审计日志。"""
        limit = int(_first(query, "limit") or 200)
        return {"logs": self.store.list_audit_logs(limit=limit)}

    # ------------------------------------------------------------- 差异比较

    def _frozen_golden_dataset(
        self,
        project_id: str,
        golden_dataset_id: str | None,
    ) -> JSON:
        """取本次比较使用的冻结黄金样本（SACW 6.3、6.5）。

        差异比较只能在黄金样本冻结之后进行；未显式指定时使用该项目最新的
        黄金样本，避免把当前 DRAFT 标注直接拿去和程序输出比较。
        """
        if golden_dataset_id:
            golden = self.store.get_golden_dataset(golden_dataset_id)
            if golden is None:
                raise ApiError(
                    "UNKNOWN_GOLDEN_DATASET",
                    f"unknown golden dataset: {golden_dataset_id}",
                    HTTPStatus.NOT_FOUND,
                )
            if golden.get("project_id") != project_id:
                raise ApiError(
                    "GOLDEN_DATASET_PROJECT_MISMATCH",
                    "golden dataset does not belong to this project",
                    HTTPStatus.CONFLICT,
                )
        else:
            candidates = [
                item
                for item in self.store.list_golden_datasets()
                if item.get("project_id") == project_id and item.get("status") == "FROZEN"
            ]
            if not candidates:
                raise ApiError(
                    "GOLDEN_DATASET_REQUIRED",
                    "freeze a golden dataset before comparing with program output",
                    HTTPStatus.CONFLICT,
                )
            golden = candidates[-1]
        if golden.get("status") != "FROZEN":
            raise ApiError(
                "GOLDEN_DATASET_REQUIRED",
                "comparison requires a FROZEN golden dataset",
                HTTPStatus.CONFLICT,
            )
        return golden

    def _ground_truth_rows(
        self,
        project_id: str,
        *,
        entity_type: str,
        timeframe: str,
        golden: JSON,
    ) -> list[JSON]:
        """只读取黄金样本冻结清单中的 APPROVED/FROZEN 人工标注。"""
        golden_ids = set(self.store.list_golden_annotation_ids(str(golden["golden_dataset_id"])))
        rows = [
            row
            for row in self.store.list_annotations(
                project_id,
                entity_type=entity_type,
                timeframe=timeframe,
            )
            if row["annotation_id"] in golden_ids
            and row["status"] in GROUND_TRUTH_STATUSES
            and row["label_source"] in GROUND_TRUTH_SOURCES
        ]
        if not rows:
            raise ApiError(
                "EMPTY_GROUND_TRUTH",
                "no frozen human annotations for this object type/timeframe",
                HTTPStatus.CONFLICT,
            )
        return rows

    def _comparison_baseline(self, golden: JSON) -> str:
        """比较必须复用冻结时的同一数据、配置和 baseline replay。"""
        dataset = self.service.dataset_info()
        if golden.get("data_hash") and golden["data_hash"] != dataset.data_hash:
            raise ApiError(
                "DATASET_MISMATCH",
                "golden dataset was frozen on different market data",
                HTTPStatus.CONFLICT,
            )
        baseline_config = golden.get("baseline_config_hash") or self.service.config_hash
        if baseline_config != self.service.config_hash:
            raise ApiError(
                "CONFIG_MISMATCH",
                "current config differs from the frozen golden baseline",
                HTTPStatus.CONFLICT,
            )
        replay_run_id = golden.get("baseline_replay_run_id")
        if not replay_run_id:
            raise ApiError(
                "BASELINE_REPLAY_REQUIRED",
                "golden dataset is not bound to a baseline replay run",
                HTTPStatus.CONFLICT,
            )
        return str(replay_run_id)

    def _comparison_meta(self, golden: JSON, rows: list[JSON]) -> JSON:
        return {
            "goldenDatasetId": golden["golden_dataset_id"],
            "replayRunId": golden.get("baseline_replay_run_id"),
            "configHash": golden.get("baseline_config_hash"),
            "datasetHash": golden.get("data_hash"),
            "groundTruthCount": len(rows),
            "includedStatuses": sorted({row["status"] for row in rows}),
            "note": (
                "差异匹配用于人工复核，不自动判定标注对错；"
                "MATCHED / HUMAN_ONLY / PROGRAM_ONLY / AMBIGUOUS_MATCH 均需人工解释。"
            ),
        }

    def compare_swings(self, *, query: dict[str, list[str]], params: JSON, **_: object) -> JSON:
        """把冻结 Ground Truth 的 SWING_POINT 与程序 SwingPoint 做一对一匹配。"""
        timeframe = _parse_timeframe(_first(query, "timeframe"))
        golden = self._frozen_golden_dataset(
            params["project_id"],
            _first(query, "golden_dataset_id"),
        )
        replay_run_id = self._comparison_baseline(golden)
        rows = self._ground_truth_rows(
            params["project_id"],
            entity_type="SWING_POINT",
            timeframe=timeframe.value,
            golden=golden,
        )
        human: list[SwingCandidate] = []
        for row in rows:
            payload = row["payload"]
            human.append(
                SwingCandidate(
                    swing_id=row["annotation_id"],
                    timeframe=timeframe.value,
                    direction=str(payload.get("direction")),
                    price=_dec(payload.get("price")),
                    occurred_at_ns=_iso_to_ns(str(payload["occurred_at"])),
                    confirmed_at_ns=_iso_to_ns(str(payload["confirmed_at"])),
                    atr_snapshot=_dec(payload["atr_snapshot"])
                    if payload.get("atr_snapshot") is not None
                    else None,
                ),
            )

        program = [
            SwingCandidate(
                swing_id=point.point_id,
                timeframe=timeframe.value,
                direction=point.direction.value,
                price=point.price,
                occurred_at_ns=point.occurred_at_ns,
                confirmed_at_ns=point.confirmed_at_ns,
                atr_snapshot=point.atr_snapshot,
            )
            for point in self.service.swings(timeframe)
        ]

        engine = self.service.context.engine(timeframe)
        report = match_swings(
            human,
            program,
            timeframe_duration_ns=_timeframe_duration_ns(timeframe),
            reference_atr=engine.atr.value,
            config=MatcherConfig(),
        ).as_dict()
        report.update(self._comparison_meta(golden, rows))
        report["replayRunId"] = replay_run_id
        return report

    def compare_zones(self, *, query: dict[str, list[str]], params: JSON, **_: object) -> JSON:
        """把冻结 Ground Truth 的 Zone 与程序 Zone 做锚点匹配。"""
        timeframe = _parse_timeframe(_first(query, "timeframe"))
        golden = self._frozen_golden_dataset(
            params["project_id"],
            _first(query, "golden_dataset_id"),
        )
        replay_run_id = self._comparison_baseline(golden)
        rows = self._ground_truth_rows(
            params["project_id"],
            entity_type="ZONE",
            timeframe=timeframe.value,
            golden=golden,
        )
        human = [dict(row["payload"], zone_id=row["annotation_id"]) for row in rows]
        program = self.service.zone_program_snapshots(timeframe)
        report = match_zones(human, program)
        report.update(self._comparison_meta(golden, rows))
        report["replayRunId"] = replay_run_id
        return report

    # ------------------------------------------------------- 边界覆盖与黄金

    def list_overrides(self, *, query: dict[str, list[str]], **_: object) -> JSON:
        """列出人工边界覆盖。"""
        return {
            "overrides": self.store.list_boundary_overrides(
                zone_annotation_id=_first(query, "zone_annotation_id"),
            ),
        }

    def create_override(self, *, body: JSON, **_: object) -> JSON:
        """创建人工边界覆盖。"""
        required = ("zone_annotation_id", "override_lower", "override_upper", "reason")
        for field in required:
            if not body.get(field):
                raise ApiError("MISSING_FIELD", f"{field} is required")
        lower = _dec(body["override_lower"])
        upper = _dec(body["override_upper"])
        if lower >= upper:
            raise ApiError("INVALID_BOUNDARY", "override_lower must be below override_upper")
        center = _dec(body.get("override_center") or ((lower + upper) / 2))
        return self.store.create_boundary_override(
            zone_annotation_id=str(body["zone_annotation_id"]),
            override_lower=str(lower),
            override_upper=str(upper),
            override_center=str(center),
            operator=str(body.get("operator") or "web"),
            reason=str(body["reason"]),
            config_hash=self.service.config_hash,
        )

    def review_override(self, *, body: JSON, params: JSON, **_: object) -> JSON:
        """审核人工边界覆盖。"""
        decision = str(body.get("decision") or "").upper()
        if decision not in {"APPROVED", "REJECTED"}:
            raise ApiError("INVALID_DECISION", "decision must be APPROVED or REJECTED")
        return self.store.review_boundary_override(
            override_id=params["override_id"],
            decision=decision,
            reviewer=str(body.get("reviewer") or "web"),
            reason=body.get("reason"),
        )

    def list_golden(self, **_: object) -> JSON:
        """列出黄金样本。"""
        return {"goldenDatasets": self.store.list_golden_datasets()}

    def freeze_golden(self, *, body: JSON, **_: object) -> JSON:
        """冻结黄金样本。"""
        project_id = str(body.get("project_id") or "")
        if not project_id:
            raise ApiError("MISSING_PROJECT", "project_id is required")
        split = str(body.get("split") or "HOLDOUT").upper()
        dataset = self.service.dataset_info()
        return self.store.freeze_golden_dataset(
            project_id=project_id,
            split=split,
            data_hash=dataset.data_hash,
            actor=str(body.get("actor") or "web"),
            dataset_id=dataset.dataset_id,
            baseline_replay_run_id=body.get("baseline_replay_run_id"),
            baseline_code_commit=body.get("baseline_code_commit"),
            baseline_config_hash=self.service.config_hash,
        )

    def build_snapshot_view(self, *, query: dict[str, list[str]], **_: object) -> JSON:
        """构建初始状态快照视图。

        指定 ``as_of`` 时**必须重放**到该时点：直接用最新上下文会把
        ``as_of`` 之后才确认的结构写进快照，属于未来信息泄漏（规格 3.4）。
        """
        timeframe = _parse_timeframe(_first(query, "timeframe") or "4H")
        as_of = _first(query, "as_of")
        dataset_id = self.service.dataset_info().dataset_id
        if as_of:
            as_of_ns = _iso_to_ns(as_of)
            bars_by_timeframe = {
                item: tuple(bar for bar in self.service.bars(item) if bar.ts_close_ns <= as_of_ns)
                for item in Timeframe
            }
            result = replay_and_snapshot(
                self.service.config,
                bars_by_timeframe=bars_by_timeframe,
                timeframe=timeframe,
                as_of_ns=as_of_ns,
                dataset_id=dataset_id,
            )
        else:
            result = build_snapshot(
                self.service.config,
                context=self.service.context,
                timeframe=timeframe,
                as_of_ns=None,
                dataset_id=dataset_id,
            )
        return {
            "status": result.status.value,
            "missing": list(result.missing),
            "asOfNs": result.as_of_ns,
            "snapshotHash": result.snapshot_hash,
            "payload": result.payload,
        }

    # --------------------------------------------------------------- 回归

    def _cases(self) -> list[JSON]:
        return self.store.list_regression_cases()

    def list_regression_cases(self, **_: object) -> JSON:
        """列出 PB 样本。"""
        cases = self._cases()
        return {
            "cases": cases,
            "count": len(cases),
            "problems": validate_cases(cases),
        }

    def get_regression_case(self, *, params: JSON, **_: object) -> JSON:
        """读取单个 PB 样本。"""
        case = self.store.get_regression_case(params["case_id"])
        if case is None:
            raise ApiError("UNKNOWN_CASE", "regression case not found", HTTPStatus.NOT_FOUND)
        return case

    def run_regression_case(self, *, params: JSON, **_: object) -> JSON:
        """运行单个 PB 样本。"""
        return self.regression.run(case_ids=[params["case_id"]])

    def run_regression_suite(self, **_: object) -> JSON:
        """运行全套 PB-01 至 PB-51。"""
        return self.regression.run()

    def list_regression_runs(self, **_: object) -> JSON:
        """列出回归运行。"""
        return {"runs": self.store.list_regression_runs()}

    def get_regression_run(self, *, params: JSON, **_: object) -> JSON:
        """读取回归运行。"""
        run = self.store.get_regression_run(params["run_id"])
        if run is None:
            raise ApiError("UNKNOWN_RUN", "regression run not found", HTTPStatus.NOT_FOUND)
        return run

    def list_regression_assertions(self, *, params: JSON, **_: object) -> JSON:
        """列出某次运行的断言结果。"""
        return {"assertions": self.store.list_assertions(params["run_id"])}


def _first(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key)
    return values[0] if values else None


def _parse_since(query: dict[str, list[str]]) -> int | None:
    """解析 ``since_close_ns``：纳秒整数，或以 ``-`` 分隔的 ISO 时间。"""
    raw = _first(query, "since_close_ns") or _first(query, "sinceCloseNs")
    if not raw:
        return None
    try:
        return _iso_to_ns(raw) if "-" in raw else int(raw)
    except ValueError as e:
        raise ApiError("INVALID_SINCE", f"invalid since_close_ns: {raw}") from e


def _iso_now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _bar_payload(bar: Bar, source: str) -> JSON:
    return {
        "barId": bar.bar_id,
        "openTime": _ns_to_iso(bar.ts_open_ns),
        "closeTime": _ns_to_iso(bar.ts_close_ns),
        "open": str(bar.open),
        "high": str(bar.high),
        "low": str(bar.low),
        "close": str(bar.close),
        "volume": str(bar.volume),
        "isClosed": True,
        "source": source,
    }


def _dec(value: object) -> Decimal:
    from decimal import Decimal

    if value is None:
        raise ApiError("MISSING_VALUE", "numeric value is required")
    return Decimal(str(value))


def _ok_envelope(request_id: str, data: object) -> JSON:
    return {"data": data, "meta": {"request_id": request_id}, "error": None}


def _error_envelope(request_id: str, code: str, message: str) -> JSON:
    return {
        "data": None,
        "meta": {"request_id": request_id},
        "error": {"code": code, "message": message},
    }


def validate_boot(service: DataService) -> None:
    """启动前校验配置门禁，失败时抛出 ``ConfigurationError``。"""
    validate_startup(service.config, Stage.RESEARCH_STRUCTURE)


def parse_query(raw: str) -> dict[str, list[str]]:
    """解析查询字符串。"""
    return parse_qs(raw)


def read_body(handler: HandlerLike) -> JSON | None:
    """从请求处理器读取并解析 JSON 请求体。"""
    length = int(handler.headers.get("Content-Length") or 0)
    if length == 0:
        return None
    raw = handler.rfile.read(length)
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ApiError("INVALID_JSON", f"invalid JSON body: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ApiError("INVALID_BODY", "JSON body must be an object")
    return parsed


def route_path(raw_path: str) -> tuple[str, dict[str, list[str]]]:
    """把 URL 拆成路径与查询参数。"""
    parsed = urlparse(raw_path)
    return parsed.path, parse_query(parsed.query)


__all__ = [
    "ApiError",
    "ApiRouter",
    "read_body",
    "route_path",
    "validate_boot",
]
