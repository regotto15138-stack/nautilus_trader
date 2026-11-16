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
from collections.abc import Callable, Sequence
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
from pa_trend.application.market_context import MarketContext
from pa_trend.application.matching import (
    MatcherConfig,
    SwingCandidate,
    match_n_structures,
    match_state_intervals,
    match_swings,
    match_zones,
)
from pa_trend.application.regression import RegressionRunner, load_cases, validate_cases
from pa_trend.application.snapshot import build_snapshot, replay_and_snapshot
from pa_trend.config.validation import Stage, validate_startup
from pa_trend.domain.errors import ConfigurationError, PaTrendError
from pa_trend.domain.models.bar import Bar
from pa_trend.domain.models.timeframe import Timeframe, expected_close_ns
from pa_trend.domain.state.enums import DayState, H1State, H4State, MonthState, WeekState

JSON = dict[str, Any]
Route = tuple[str, re.Pattern[str], Callable[..., Any]]

#: 允许人工标注的状态枚举（SACW 3.4E）。
_STATE_INTERVAL_STATES: dict[str, set[str]] = {
    Timeframe.MONTH.value: {item.value for item in MonthState},
    Timeframe.WEEK.value: {item.value for item in WeekState},
    Timeframe.DAY.value: {item.value for item in DayState},
    Timeframe.HOUR4.value: {item.value for item in H4State},
    Timeframe.HOUR1.value: {item.value for item in H1State},
}


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
        add(
            "POST",
            r"/api/v1/annotation-projects/(?P<project_id>[\w\-]+)/comparisons/n-structures",
            self.compare_n_structures,
        )
        add(
            "POST",
            r"/api/v1/annotation-projects/(?P<project_id>[\w\-]+)/comparisons/state-intervals",
            self.compare_state_intervals,
        )
        add("GET", r"/api/v1/comparisons", self.list_comparisons)
        add(
            "GET",
            r"/api/v1/comparisons/(?P<comparison_id>[\w\-]+)",
            self.get_comparison,
        )

        add("GET", r"/api/v1/annotations/(?P<annotation_id>[\w\-]+)", self.get_annotation)
        add("PATCH", r"/api/v1/annotations/(?P<annotation_id>[\w\-]+)", self.revise_annotation)
        add("DELETE", r"/api/v1/annotations/(?P<annotation_id>[\w\-]+)", self.delete_annotation)
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
        add(
            "GET",
            r"/api/v1/golden-datasets/(?P<golden_dataset_id>[\w\-]+)",
            self.get_golden,
        )
        add(
            "POST",
            r"/api/v1/golden-datasets/(?P<golden_dataset_id>[\w\-]+)/validate",
            self.validate_golden,
        )
        add(
            "POST",
            r"/api/v1/golden-datasets/(?P<golden_dataset_id>[\w\-]+)/split",
            self.split_golden,
        )
        add(
            "GET",
            r"/api/v1/market/datasets/(?P<dataset_id>[\w\-]+)/splits",
            self.list_dataset_splits,
        )

        add("GET", r"/api/v1/snapshots", self.build_snapshot_view)
        add("GET", r"/api/v1/snapshots/artifacts", self.list_snapshot_artifacts)
        add("POST", r"/api/v1/snapshots/artifacts", self.save_snapshot_artifact)

        add("POST", r"/api/v1/replay-runs", self.create_replay_run)
        add("GET", r"/api/v1/replay-runs", self.list_replay_runs)
        add("GET", r"/api/v1/replay-runs/(?P<run_id>[\w\-]+)", self.get_replay_run)
        add(
            "GET",
            r"/api/v1/replay-runs/(?P<run_id>[\w\-]+)/events",
            self.list_replay_events,
        )
        add(
            "GET",
            r"/api/v1/replay-runs/(?P<run_id>[\w\-]+)/snapshots",
            self.list_replay_snapshots,
        )
        add(
            "POST",
            r"/api/v1/replay-runs/(?P<run_id>[\w\-]+)/cancel",
            self.cancel_replay_run,
        )

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

        # 分页锚点：带 ``to`` 时返回紧邻该时刻之前的最后一页，供前端“向左加载”
        # 逐页回溯；``cursor`` 始终是相对该锚点的偏移。此前一律从最早一根开始
        # 截取，导致第二页与第一页之间跳过整段历史（图表上表现为一年以上的错断）。
        anchor = self._bars_page_anchor(selected, limit=limit, from_end=bool(end))
        window = selected[anchor + cursor : anchor + cursor + limit]
        next_cursor = (
            anchor + cursor + limit if anchor + cursor + limit < len(selected) else None
        )
        return {
            "timeframe": timeframe.value,
            "bars": [_bar_payload(bar, self.service.source) for bar in window],
            "nextCursor": next_cursor,
            "datasetId": self.service.dataset_info().dataset_id,
            "dataHash": self.service.dataset_info().data_hash,
        }

    @staticmethod
    def _bars_page_anchor(selected: Sequence[Bar], *, limit: int, from_end: bool) -> int:
        """返回本次分页的起点下标。

        带 ``to``（``from_end`` 为真）时取「末尾一页」的起点，使返回的窗口恰好
        紧邻 ``to`` 之前；否则从最早一根开始。
        """
        if not from_end or not selected:
            return 0
        return max(0, len(selected) - limit)

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

        if entity_type == "STATE_INTERVAL":
            allowed_states = _STATE_INTERVAL_STATES.get(timeframe.value)
            if not allowed_states:
                raise ApiError(
                    "STATE_INTERVAL_TIMEFRAME_NOT_ALLOWED",
                    "STATE_INTERVAL is defined only for 1M/1W/1D/4H/1H",
                )
            state = str(payload.get("state") or "").upper()
            if state not in allowed_states:
                raise ApiError(
                    "INVALID_STATE_VALUE",
                    f"{timeframe.value} state must be one of {sorted(allowed_states)}",
                )
            payload["state"] = state

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
        if existing["entity_type"] == "STATE_INTERVAL":
            allowed_states = _STATE_INTERVAL_STATES.get(existing["timeframe"])
            state = str(payload.get("state") or "").upper()
            if not allowed_states or state not in allowed_states:
                raise ApiError(
                    "INVALID_STATE_VALUE",
                    f"{existing['timeframe']} state is not valid for STATE_INTERVAL",
                )
            payload["state"] = state
        expected_revision = body.get("expected_revision")
        if expected_revision is not None:
            try:
                expected = int(expected_revision)
            except (TypeError, ValueError) as exc:
                raise ApiError("INVALID_REVISION", "expected_revision must be an integer") from exc
            if int(existing["revision"]) != expected:
                raise ApiError(
                    "REVISION_CONFLICT",
                    f"expected revision {expected}, current {existing['revision']}",
                    HTTPStatus.CONFLICT,
                )
        return self.store.revise_annotation(
            annotation_id=params["annotation_id"],
            payload=payload,
            actor=str(body.get("actor") or "web"),
            reason=str(body.get("reason") or "revised from web workbench"),
            expected_revision=None if expected_revision is None else expected,
        )

    def delete_annotation(self, *, body: JSON, params: JSON, **_: object) -> JSON:
        """软删除标注；FROZEN 标注拒绝删除。"""
        self.store.soft_delete_annotation(
            annotation_id=params["annotation_id"],
            actor=str(body.get("actor") or "web"),
            reason=str(body.get("reason") or "deleted from web workbench"),
        )
        return {"annotation_id": params["annotation_id"], "deleted": True}

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
        required: bool = True,
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
        if required and not rows:
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

    def _persist_comparison(
        self,
        *,
        golden: JSON,
        replay_run_id: str,
        report: JSON,
        matches: list[JSON],
    ) -> JSON:
        summary = {
            key: value
            for key, value in report.items()
            if key not in {"matches", "results"}
        }
        saved = self.store.save_comparison_run(
            golden_dataset_id=str(golden["golden_dataset_id"]),
            replay_run_id=replay_run_id,
            matcher_version=str(report.get("matcher_version") or ""),
            summary=summary,
            matches=matches,
        )
        report["comparisonId"] = saved["comparison_id"]
        return report

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
        return self._persist_comparison(
            golden=golden,
            replay_run_id=replay_run_id,
            report=report,
            matches=list(report.get("matches") or []),
        )

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
        return self._persist_comparison(
            golden=golden,
            replay_run_id=replay_run_id,
            report=report,
            matches=list(report.get("results") or []),
        )

    def compare_n_structures(
        self,
        *,
        query: dict[str, list[str]],
        params: JSON,
        **_: object,
    ) -> JSON:
        """把冻结 Ground Truth 的 N 结构按四锚点映射与程序结构匹配。"""
        timeframe = _parse_timeframe(_first(query, "timeframe"))
        golden = self._frozen_golden_dataset(
            params["project_id"],
            _first(query, "golden_dataset_id"),
        )
        replay_run_id = self._comparison_baseline(golden)
        rows = self._ground_truth_rows(
            params["project_id"],
            entity_type="N_STRUCTURE",
            timeframe=timeframe.value,
            golden=golden,
        )
        # 先用冻结的人工 Swing 与程序 Swing 建立映射；N 结构匹配要求
        # 四个锚点全部映射到同一程序摆动点。
        swing_rows = self._ground_truth_rows(
            params["project_id"],
            entity_type="SWING_POINT",
            timeframe=timeframe.value,
            golden=golden,
            required=False,
        )
        human_swings = [
            SwingCandidate(
                swing_id=row["annotation_id"],
                timeframe=timeframe.value,
                direction=str(row["payload"].get("direction")),
                price=_dec(row["payload"].get("price")),
                occurred_at_ns=_iso_to_ns(str(row["payload"]["occurred_at"])),
                confirmed_at_ns=_iso_to_ns(str(row["payload"]["confirmed_at"])),
            )
            for row in swing_rows
        ]
        program_swings = [
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
        swing_report = match_swings(
            human_swings,
            program_swings,
            timeframe_duration_ns=_timeframe_duration_ns(timeframe),
            reference_atr=engine.atr.value,
            config=MatcherConfig(),
        )
        mapping = {
            str(match.human_id): str(match.program_id)
            for match in swing_report.matches
            if match.human_id is not None and match.program_id is not None
        }
        human = []
        for row in rows:
            payload = row["payload"]
            human.append(
                {
                    "structure_id": row["annotation_id"],
                    "l1": payload.get("l1_swing_id"),
                    "h1": payload.get("h1_swing_id"),
                    "l2": payload.get("l2_swing_id"),
                    "h2": payload.get("h2_swing_id"),
                    "confirmed_at_ns": _iso_to_ns(str(payload["confirmed_at"])),
                    "status": "CONFIRMED"
                    if payload.get("validation_status", "VALID") == "VALID"
                    else str(payload.get("validation_status")),
                },
            )
        program = [
            {
                "structure_id": structure.n_structure_id,
                "l1": structure.l1.point_id,
                "h1": structure.h1.point_id,
                "l2": structure.l2.point_id,
                "h2": structure.h2.point_id,
                "confirmed_at_ns": structure.confirmed_at_ns,
                "status": structure.status.value,
            }
            for structure in engine.structures.structures
        ]
        report = match_n_structures(
            human,
            program,
            swing_mapping=mapping,
            config=MatcherConfig(),
            timeframe_duration_ns=_timeframe_duration_ns(timeframe),
        )
        report.update(self._comparison_meta(golden, rows))
        report["replayRunId"] = replay_run_id
        return self._persist_comparison(
            golden=golden,
            replay_run_id=replay_run_id,
            report=report,
            matches=list(report.get("results") or []),
        )

    def _program_state_intervals(self, timeframe: Timeframe) -> list[JSON]:
        """重放单周期 Bar，输出状态区间历史（SACW 7.5）。"""
        bars = self.service.bars(timeframe)
        if not bars:
            return []
        context = MarketContext(self.service.config)
        intervals: list[JSON] = []
        current_state: str | None = None
        start_ns: int | None = None
        last_bar = bars[-1]
        for bar in bars:
            context.on_bar(bar)
            state = context.engine(timeframe).state
            if state is None:
                continue
            name = str(state)
            if current_state is None:
                current_state = name
                start_ns = bar.ts_open_ns
                continue
            if name != current_state and start_ns is not None:
                intervals.append(
                    {
                        "interval_id": f"STATE-{timeframe.value}-{start_ns}-{current_state}",
                        "state": current_state,
                        "valid_from_ns": start_ns,
                        "valid_to_ns": bar.ts_open_ns,
                        "known_at_ns": bar.ts_close_ns,
                    },
                )
                current_state = name
                start_ns = bar.ts_open_ns
        if current_state is not None and start_ns is not None:
            intervals.append(
                {
                    "interval_id": f"STATE-{timeframe.value}-{start_ns}-{current_state}",
                    "state": current_state,
                    "valid_from_ns": start_ns,
                    "valid_to_ns": last_bar.ts_close_ns,
                    "known_at_ns": last_bar.ts_close_ns,
                },
            )
        return intervals

    def compare_state_intervals(
        self,
        *,
        query: dict[str, list[str]],
        params: JSON,
        **_: object,
    ) -> JSON:
        """比较冻结的人工状态区间与程序状态区间（SACW 7.5 基础版）。"""
        timeframe = _parse_timeframe(_first(query, "timeframe"))
        if timeframe.value not in _STATE_INTERVAL_STATES:
            raise ApiError(
                "STATE_INTERVAL_TIMEFRAME_NOT_ALLOWED",
                "state interval comparison is defined only for 1M/1W/1D/4H/1H",
            )
        golden = self._frozen_golden_dataset(
            params["project_id"],
            _first(query, "golden_dataset_id"),
        )
        replay_run_id = self._comparison_baseline(golden)
        rows = self._ground_truth_rows(
            params["project_id"],
            entity_type="STATE_INTERVAL",
            timeframe=timeframe.value,
            golden=golden,
        )
        human: list[JSON] = []
        for row in rows:
            payload = row["payload"]
            if not payload.get("valid_to"):
                continue
            human.append(
                {
                    "interval_id": row["annotation_id"],
                    "state": str(payload["state"]),
                    "valid_from_ns": _iso_to_ns(str(payload["valid_from"])),
                    "valid_to_ns": _iso_to_ns(str(payload["valid_to"])),
                    "known_at_ns": _iso_to_ns(str(payload["known_at"])),
                },
            )
        if not human:
            raise ApiError(
                "EMPTY_GROUND_TRUTH",
                "frozen STATE_INTERVAL annotations need valid_to",
                HTTPStatus.CONFLICT,
            )
        program = self._program_state_intervals(timeframe)
        report = match_state_intervals(human, program)
        report.update(self._comparison_meta(golden, rows))
        report["replayRunId"] = replay_run_id
        return self._persist_comparison(
            golden=golden,
            replay_run_id=replay_run_id,
            report=report,
            matches=list(report.get("results") or []),
        )

    def list_comparisons(self, **_: object) -> JSON:
        """列出已持久化的比较运行。"""
        items = self.store.list_comparison_runs()
        return {"comparisons": items, "count": len(items)}

    def get_comparison(self, *, params: JSON, **_: object) -> JSON:
        """读取一次比较及其逐项匹配结果。"""
        item = self.store.get_comparison_run(params["comparison_id"])
        if item is None:
            raise ApiError(
                "UNKNOWN_COMPARISON",
                f"unknown comparison: {params['comparison_id']}",
                HTTPStatus.NOT_FOUND,
            )
        return item

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

    def get_golden(self, *, params: JSON, **_: object) -> JSON:
        """读取黄金样本。"""
        golden = self.store.get_golden_dataset(params["golden_dataset_id"])
        if golden is None:
            raise ApiError(
                "UNKNOWN_GOLDEN_DATASET",
                f"unknown golden dataset: {params['golden_dataset_id']}",
                HTTPStatus.NOT_FOUND,
            )
        golden["annotation_ids"] = self.store.list_golden_annotation_ids(
            golden["golden_dataset_id"],
        )
        return golden

    def validate_golden(self, *, params: JSON, **_: object) -> JSON:
        """校验黄金样本成员、状态、来源和 baseline replay（SACW 6.3）。"""
        golden = self.get_golden(params=params)
        annotation_ids = golden["annotation_ids"]
        issues: list[str] = []
        if not annotation_ids:
            issues.append("golden dataset has no annotation membership")
        for annotation_id in annotation_ids:
            annotation = self.store.get_annotation(annotation_id)
            if annotation is None:
                issues.append(f"{annotation_id}: annotation not found")
                continue
            if annotation["status"] not in GROUND_TRUTH_STATUSES:
                issues.append(f"{annotation_id}: status {annotation['status']} is not Ground Truth")
            if annotation["label_source"] not in GROUND_TRUTH_SOURCES:
                issues.append(
                    f"{annotation_id}: label_source {annotation['label_source']} is not human",
                )
            if annotation.get("deleted_at") is not None:
                issues.append(f"{annotation_id}: annotation is deleted")
        if not golden.get("baseline_replay_run_id"):
            issues.append("golden dataset is not bound to a baseline replay run")
        if not golden.get("baseline_config_hash"):
            issues.append("golden dataset has no baseline config hash")
        return {
            "valid": not issues,
            "issues": issues,
            "goldenDatasetId": golden["golden_dataset_id"],
            "annotationCount": len(annotation_ids),
            "annotationHash": golden["annotation_hash"],
            "dataHash": golden["data_hash"],
            "baselineReplayRunId": golden.get("baseline_replay_run_id"),
        }

    def split_golden(self, *, body: JSON, params: JSON, **_: object) -> JSON:
        """登记黄金样本的数据切分（SACW 5.3）。

        采集数据没有可自动推断的训练/验证边界，因此区间必须由调用方显式传入，
        服务端只做一致性与哈希绑定，不擅自切分。
        """
        golden = self.get_golden(params=params)
        split = str(body.get("split") or golden["split"]).upper()
        range_start = str(body.get("range_start") or "")
        range_end = str(body.get("range_end") or "")
        if not range_start or not range_end:
            raise ApiError(
                "MISSING_RANGE",
                "range_start and range_end are required for an explicit data split",
            )
        if range_end <= range_start:
            raise ApiError("INVALID_RANGE", "range_end must be after range_start")
        dataset_id = str(body.get("dataset_id") or golden.get("dataset_id") or "")
        if not dataset_id:
            raise ApiError("MISSING_DATASET", "golden dataset has no dataset_id")
        return self.store.save_dataset_split(
            dataset_id=dataset_id,
            split=split,
            range_start=range_start,
            range_end=range_end,
            data_hash=str(golden["data_hash"]),
            annotation_hash=str(golden["annotation_hash"]),
        )

    def list_dataset_splits(self, *, params: JSON, **_: object) -> JSON:
        """列出数据集切分。"""
        return {"splits": self.store.list_dataset_splits(params["dataset_id"])}

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

    def save_snapshot_artifact(self, *, body: JSON, **_: object) -> JSON:
        """构建并保存一份初始状态快照元数据（SACW 6.3、24）。"""
        timeframe = str(body.get("timeframe") or "4H")
        query: dict[str, list[str]] = {"timeframe": [timeframe]}
        if body.get("as_of"):
            query["as_of"] = [str(body["as_of"])]
        result = self.build_snapshot_view(query=query)
        dataset_id = (
            result["payload"].get("dataset_id")
            or self.service.dataset_info().dataset_id
        )
        return self.store.save_snapshot_artifact(
            dataset_id=str(dataset_id),
            snapshot_hash=str(result["snapshotHash"]),
            status=str(result["status"]),
            path=body.get("path"),
            detail={
                "timeframe": timeframe,
                "asOfNs": result["asOfNs"],
                "missing": result["missing"],
                "payload": result["payload"],
            },
        )

    def list_snapshot_artifacts(self, *, query: dict[str, list[str]], **_: object) -> JSON:
        """列出快照 artifact 元数据。"""
        items = self.store.list_snapshot_artifacts(
            dataset_id=_first(query, "dataset_id"),
        )
        return {"snapshots": items, "count": len(items)}

    # ------------------------------------------------------------- 程序回放

    def _program_events_for(self, timeframe: Timeframe) -> list[tuple[str, JSON, str, str]]:
        """把一个周期的当前结构事实转成可持久化回放事件（SACW 6.4）。"""
        engine = self.service.context.engine(timeframe)
        events: list[tuple[str, JSON, str, str]] = []

        for point in engine.swings:
            events.append(
                (
                    "SWING_POINT",
                    {
                        "swing_id": point.point_id,
                        "direction": point.direction.value,
                        "price": str(point.price),
                        "occurred_at": _ns_to_iso(point.occurred_at_ns),
                        "confirmed_at": _ns_to_iso(point.confirmed_at_ns),
                        "atr_snapshot": str(point.atr_snapshot),
                        "source_bar_id": point.source_bar_id,
                        "sequence": point.sequence,
                    },
                    point.source_bar_id,
                    _ns_to_iso(point.confirmed_at_ns),
                ),
            )

        for structure in engine.structures.structures:
            events.append(
                (
                    "N_STRUCTURE",
                    {
                        "structure_id": structure.n_structure_id,
                        "status": structure.status.value,
                        "l1": structure.l1.point_id,
                        "h1": structure.h1.point_id,
                        "l2": structure.l2.point_id,
                        "h2": structure.h2.point_id,
                        "retracement": str(structure.retracement_ratio),
                        "retracement_class": structure.retracement_class.value,
                        "confirmed_at": _ns_to_iso(structure.confirmed_at_ns),
                        "invalidation_status": engine.structures.invalidation_status,
                    },
                    structure.h2.source_bar_id,
                    _ns_to_iso(structure.confirmed_at_ns),
                ),
            )

        for zone in engine.zones.zones:
            events.append(
                (
                    "ZONE",
                    {
                        "zone_id": zone.zone_id,
                        "zone_type": zone.zone_type.value,
                        "status": zone.status.value,
                        "version": zone.version,
                        "center": str(zone.center),
                        "lower": str(zone.lower),
                        "upper": str(zone.upper),
                        "half_width": str(zone.half_width),
                        "half_width_basis": zone.basis.value,
                        "anchor_swing_ids": [anchor.swing_id for anchor in zone.anchors],
                        "anchor_count": zone.anchor_count,
                    },
                    None,
                    _ns_to_iso(zone.updated_at_ns),
                ),
            )

        if engine.state is not None:
            events.append(
                (
                    "STATE",
                    {
                        "state": str(engine.state),
                        "bars": engine.bar_count,
                        "as_of": _ns_to_iso(engine.last_bar.ts_close_ns)
                        if engine.last_bar is not None
                        else None,
                    },
                    engine.last_bar.bar_id if engine.last_bar is not None else None,
                    _ns_to_iso(engine.last_bar.ts_close_ns)
                    if engine.last_bar is not None
                    else _iso_now(),
                ),
            )
        return events

    def create_replay_run(self, *, body: JSON, **_: object) -> JSON:
        """创建并执行一次确定性程序回放，持久化结构事件（SACW 6.4）。"""
        mode = str(body.get("mode") or "BATCH_DETERMINISTIC").upper()
        if mode != "BATCH_DETERMINISTIC":
            raise ApiError("INVALID_REPLAY_MODE", "only BATCH_DETERMINISTIC is supported")
        project_id = str(body.get("project_id") or "")
        if not project_id:
            projects = self.store.list_projects()
            if not projects:
                raise ApiError("MISSING_PROJECT", "project_id is required")
            project_id = str(projects[0]["project_id"])
        golden = self._frozen_golden_dataset(project_id, body.get("golden_dataset_id"))
        replay_run_id = self._comparison_baseline(golden)
        raw_timeframes = body.get("timeframes") or [
            timeframe.value for timeframe in Timeframe
        ]
        timeframes = [_parse_timeframe(str(item)) for item in raw_timeframes]
        dataset = self.service.dataset_info()
        run = self.store.create_replay_run(
            code_commit=body.get("code_commit"),
            config_hash=self.service.config_hash,
            dataset_hash=dataset.data_hash,
            notes=(
                f"golden={golden['golden_dataset_id']} baseline={replay_run_id} "
                f"mode={mode}"
            ),
        )
        counts: dict[str, int] = {}
        try:
            for timeframe in timeframes:
                events = self._program_events_for(timeframe)
                counts[timeframe.value] = len(events)
                for event_type, payload, bar_id, at in events:
                    self.store.append_program_event(
                        run_id=run["run_id"],
                        event_type=event_type,
                        timeframe=timeframe.value,
                        payload=payload,
                        bar_id=bar_id,
                        at=at,
                    )
        except Exception:
            self.store.finish_replay_run(run_id=run["run_id"], status="FAILED")
            raise
        finished = self.store.finish_replay_run(run_id=run["run_id"])
        return {
            **finished,
            "goldenDatasetId": golden["golden_dataset_id"],
            "baselineReplayRunId": replay_run_id,
            "mode": mode,
            "timeframes": sorted({timeframe.value for timeframe in timeframes}),
            "eventCounts": counts,
            "eventCount": sum(counts.values()),
        }

    def _replay_run(self, run_id: str) -> JSON:
        run = self.store.get_replay_run(run_id)
        if run is None:
            raise ApiError(
                "UNKNOWN_REPLAY_RUN",
                f"unknown replay run: {run_id}",
                HTTPStatus.NOT_FOUND,
            )
        return run

    def list_replay_runs(self, **_: object) -> JSON:
        """列出全部程序回放。"""
        runs = self.store.list_replay_runs()
        return {"runs": runs, "count": len(runs)}

    def get_replay_run(self, *, params: JSON, **_: object) -> JSON:
        """读取一次程序回放。"""
        return self._replay_run(params["run_id"])

    def list_replay_events(self, *, query: dict[str, list[str]], params: JSON, **_: object) -> JSON:
        """列出回放事件，可按周期/类型过滤。"""
        self._replay_run(params["run_id"])
        timeframe = _first(query, "timeframe")
        event_type = _first(query, "event_type")
        events = self.store.list_program_events(params["run_id"])
        if timeframe:
            events = [item for item in events if item["timeframe"] == timeframe]
        if event_type:
            events = [item for item in events if item["event_type"] == event_type]
        return {"events": events, "count": len(events)}

    def list_replay_snapshots(self, *, params: JSON, **_: object) -> JSON:
        """返回当前数据集相关的快照 artifact。"""
        run = self._replay_run(params["run_id"])
        items = self.store.list_snapshot_artifacts()
        return {
            "snapshots": items,
            "count": len(items),
            "replayRunId": run["run_id"],
            "note": (
                "snapshot artifacts are dataset-scoped; "
                "replay snapshots share the current dataset"
            ),
        }

    def cancel_replay_run(self, *, params: JSON, **_: object) -> JSON:
        """取消仍在运行的 replay；已完成的结果保持不可变。"""
        run = self._replay_run(params["run_id"])
        if run.get("status") == "RUNNING":
            return self.store.finish_replay_run(run_id=run["run_id"], status="CANCELED")
        return run

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
