"""HTTP API 集成测试（SACW V1.1.2 第 6 章）。

直接调用路由层，不启动真实端口：``ApiRouter.dispatch`` 返回
``(status, envelope)``，与 HTTP 处理器使用同一套逻辑。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pa_trend.application.annotation_store import SacwStore
from pa_trend.application.data_service import DataService
from pa_trend.application.regression import RegressionRunner, load_cases
from pa_trend.domain.models.timeframe import Timeframe
from pa_trend.presentation.api import ApiRouter

CONFIGS_DIR = Path(__file__).resolve().parents[2] / "configs"


@pytest.fixture(scope="module")
def service() -> DataService:
    instance = DataService(
        instrument_id="ETH-USDT-SWAP.OKX",
        configs_dir=CONFIGS_DIR,
        catalog_path=None,
        demo=True,
        demo_bars=260,
        session_offset_hours=0,
    )
    instance.ensure_built()
    return instance


@pytest.fixture
def router(service: DataService, tmp_path: Path) -> ApiRouter:
    store = SacwStore(tmp_path / "api.sqlite3")
    store.ensure_project()
    regression = RegressionRunner(
        store=store,
        config=service.config,
        config_hash=service.config_hash,
        code_commit="test",
        configs_dir=CONFIGS_DIR,
    )
    regression.sync_cases(load_cases(CONFIGS_DIR))
    router = ApiRouter(
        service=service,
        store=store,
        regression=regression,
        configs_dir=CONFIGS_DIR,
    )
    yield router
    store.close()


def _get(router: ApiRouter, path: str) -> tuple[int, dict]:
    from urllib.parse import parse_qs, urlparse

    parsed = urlparse(path)
    return router.dispatch(
        method="GET",
        path=parsed.path,
        query=parse_qs(parsed.query),
        body=None,
    )


def _post(router: ApiRouter, path: str, body: dict | None = None) -> tuple[int, dict]:
    from urllib.parse import parse_qs, urlparse

    parsed = urlparse(path)
    return router.dispatch(
        method="POST",
        path=parsed.path,
        query=parse_qs(parsed.query),
        body=body or {},
    )


def test_meta_reports_spec_and_ambiguities(router: ApiRouter) -> None:
    """元信息必须声明规格版本与两个歧义状态。"""
    status, envelope = _get(router, "/api/v1/meta")
    assert status == 200
    assert envelope["error"] is None
    data = envelope["data"]
    assert data["specVersion"] == "V1.4.8"
    assert data["sacwVersion"] == "V1.1.2"
    assert data["atrMaStatus"] == "N/A / SPEC_AMBIGUITY"
    assert data["nStructureInvalidationStatus"] == "SPEC_AMBIGUITY"
    assert data["regressionCaseCount"] == 51
    assert len(data["timeframes"]) == 7


def test_snapshot_has_seven_timeframes_and_no_atr_ma(router: ApiRouter) -> None:
    """看板载荷含七个周期，且不下发 ATR_MA22 曲线。"""
    status, envelope = _get(router, "/api/v1/market/snapshot")
    assert status == 200
    data = envelope["data"]
    assert len(data["timeframes"]) == 7
    for code, section in data["series"].items():
        assert section["atrMa"] is None, code
        assert section["atrMaStatus"] == "N/A / SPEC_AMBIGUITY"
        assert "zones" in section
        assert "candidates" in section


def test_market_bars_returns_decimal_text_and_pagination(router: ApiRouter) -> None:
    """K 线接口返回十进制文本并支持 limit/cursor。"""
    status, envelope = _get(router, "/api/v1/market/bars?timeframe=4H&limit=3")
    assert status == 200
    data = envelope["data"]
    assert len(data["bars"]) == 3
    assert data["nextCursor"] == 3
    bar = data["bars"][0]
    assert isinstance(bar["open"], str)
    assert bar["isClosed"] is True
    assert bar["source"] == "demo"

    status, envelope = _get(router, "/api/v1/market/bars?timeframe=4H&limit=3&cursor=3")
    assert envelope["data"]["bars"][0]["barId"] != bar["barId"]


def test_market_bars_rejects_unknown_timeframe(router: ApiRouter) -> None:
    """非法周期返回结构化错误。"""
    status, envelope = _get(router, "/api/v1/market/bars?timeframe=7H")
    assert status == 400
    assert envelope["error"]["code"] == "UNKNOWN_TIMEFRAME"


def test_coverage_reports_clean_series(router: ApiRouter) -> None:
    """合成数据应全部通过完整性检查。"""
    status, envelope = _get(router, "/api/v1/market/coverage")
    assert status == 200
    data = envelope["data"]
    assert len(data["timeframes"]) == 7
    assert data["allClean"] is True
    assert all(item["bars"] > 0 for item in data["timeframes"])


def test_indicator_series_marks_atr_ma22_unsupported(router: ApiRouter) -> None:
    """请求 atr_ma22 时只返回 N/A / SPEC_AMBIGUITY，不返回数值。"""
    status, envelope = _get(
        router,
        "/api/v1/indicators/series?timeframe=1H&fields=sma22,atr14,atr_ma22",
    )
    assert status == 200
    series = envelope["data"]["series"]
    assert series["sma22"]["points"]
    assert series["atr14"]["points"]
    assert series["atr_ma22"]["status"] == "N/A / SPEC_AMBIGUITY"
    assert series["atr_ma22"]["points"] == []
    point = series["sma22"]["points"][0]
    assert point["sourceBarId"]
    assert point["asOfBarTime"] >= point["time"]


def test_zone_preview_uses_backend_geometry(router: ApiRouter, service: DataService) -> None:
    """ANCHOR_ONLY 几何由后端计算，并带配置哈希与 tick size 版本。"""
    swings = [point for point in service.swings(Timeframe.HOUR4) if not point.is_high][:2]
    assert len(swings) == 2
    status, envelope = _post(
        router,
        "/api/v1/zones/preview",
        {
            "timeframe": "4H",
            "anchorSwingIds": [point.point_id for point in swings],
        },
    )
    assert status == 200
    data = envelope["data"]
    assert data["zoneType"] == "SUPPORT"
    assert data["halfWidthBasis"] in {"MIN_TICKS", "ATR", "ANCHOR_SPAN"}
    assert data["formulaVersion"] == "V1.4.8-6.4"
    assert data["configHash"] == service.config_hash
    assert data["tickSize"] == "0.01"
    assert float(data["lower"]) <= float(data["center"]) <= float(data["upper"])
    assert data["zoneParameters"]["min_half_width_ticks"] == "2"


def test_zone_preview_rejects_mixed_directions(router: ApiRouter, service: DataService) -> None:
    """锚点必须同向，混选必须被拒绝（规格 6.1）。"""
    highs = [point for point in service.swings(Timeframe.HOUR4) if point.is_high][:1]
    lows = [point for point in service.swings(Timeframe.HOUR4) if not point.is_high][:1]
    status, envelope = _post(
        router,
        "/api/v1/zones/preview",
        {"timeframe": "4H", "anchorSwingIds": [highs[0].point_id, lows[0].point_id]},
    )
    assert status == 400
    assert envelope["error"]["code"] == "VALIDATION_ERROR"


def test_annotation_lifecycle_via_api(router: ApiRouter) -> None:
    """创建 → 列表 → 状态迁移 → 黄金冻结全流程可用。"""
    status, envelope = _get(router, "/api/v1/annotation-projects")
    project_id = envelope["data"]["projects"][0]["project_id"]

    status, envelope = _post(
        router,
        f"/api/v1/annotation-projects/{project_id}/annotations",
        {
            "entity_type": "SWING_POINT",
            "timeframe": "4H",
            "payload": {
                "direction": "LOW",
                "price": "2400.0",
                "occurred_at": "2026-01-01T00:00:00Z",
                "confirmed_at": "2026-01-01T04:00:00Z",
            },
            "actor": "test",
        },
    )
    assert status == 200, envelope
    annotation = envelope["data"]
    assert annotation["status"] == "DRAFT"
    assert annotation["revision"] == 1

    status, envelope = _get(
        router,
        f"/api/v1/annotation-projects/{project_id}/annotations?timeframe=4H",
    )
    assert envelope["data"]["count"] == 1

    for target in ("SUBMITTED", "REVIEWED", "APPROVED"):
        status, envelope = _post(
            router,
            f"/api/v1/annotations/{annotation['annotation_id']}/status",
            {"status": target, "actor": "test"},
        )
        assert status == 200, envelope
        assert envelope["data"]["status"] == target

    status, envelope = _post(
        router,
        "/api/v1/golden-datasets",
        {"project_id": project_id, "split": "HOLDOUT", "actor": "test"},
    )
    assert status == 200, envelope
    golden = envelope["data"]
    assert golden["annotation_count"] == 1
    assert golden["annotation_hash"]


def test_zone_annotation_gets_backend_bounds(router: ApiRouter, service: DataService) -> None:
    """通过 API 创建 ANCHOR_ONLY Zone 时，边界必须由后端覆盖写入。"""
    status, envelope = _get(router, "/api/v1/annotation-projects")
    project_id = envelope["data"]["projects"][0]["project_id"]
    lows = [point for point in service.swings(Timeframe.HOUR4) if not point.is_high][:2]

    status, envelope = _post(
        router,
        f"/api/v1/annotation-projects/{project_id}/annotations",
        {
            "entity_type": "ZONE",
            "timeframe": "4H",
            "payload": {
                "annotation_mode": "ANCHOR_ONLY",
                "anchor_swing_ids": [point.point_id for point in lows],
                # 故意传入错误边界，后端必须覆盖。
                "center": "1",
                "lower": "1",
                "upper": "2",
            },
        },
    )
    assert status == 200, envelope
    payload = envelope["data"]["payload"]
    assert payload["zone_type"] == "SUPPORT"
    assert payload["center"] != "1"
    assert payload["config_hash"] == service.config_hash
    assert payload["half_width_basis"]
    assert len(payload["anchors"]) == 2


def test_annotation_requires_two_zone_anchors(router: ApiRouter) -> None:
    """单锚点 Zone 必须被拒绝（规格 6.5）。"""
    status, envelope = _get(router, "/api/v1/annotation-projects")
    project_id = envelope["data"]["projects"][0]["project_id"]
    status, envelope = _post(
        router,
        f"/api/v1/annotation-projects/{project_id}/annotations",
        {
            "entity_type": "ZONE",
            "timeframe": "4H",
            "payload": {"annotation_mode": "ANCHOR_ONLY", "anchor_swing_ids": ["sw-1"]},
        },
    )
    assert status == 400
    assert envelope["error"]["code"] == "INSUFFICIENT_ANCHORS"


def test_regression_endpoints_and_assertions(router: ApiRouter) -> None:
    """回归接口可列出样本、运行全套并读取断言。"""
    status, envelope = _get(router, "/api/v1/regression-cases")
    assert status == 200
    assert envelope["data"]["count"] == 51
    assert envelope["data"]["problems"] == []

    status, envelope = _post(router, "/api/v1/regression-suites/v1-4-8/run")
    assert status == 200, envelope
    summary = envelope["data"]
    assert summary["total"] == 51
    assert summary["failed"] == 0
    run_id = summary["run_id"]

    status, envelope = _get(router, f"/api/v1/regression-runs/{run_id}/assertions")
    assert status == 200
    assert envelope["data"]["assertions"]

    status, envelope = _get(router, f"/api/v1/regression-runs/{run_id}")
    assert status == 200
    assert envelope["data"]["status"] == "PASSED"


def test_snapshot_endpoint_reports_status(router: ApiRouter) -> None:
    """快照接口返回可信度状态、哈希与缺失原因。"""
    status, envelope = _get(router, "/api/v1/snapshots?timeframe=4H")
    assert status == 200
    data = envelope["data"]
    assert data["status"] in {"READY", "INSUFFICIENT_HISTORY", "INVALID_ATR"}
    assert data["snapshotHash"]
    assert data["payload"]["zone_parameters"]["zone_max_age_weeks"] == "52"


def test_snapshot_as_of_replays_only_until_that_time(
    router: ApiRouter,
    service: DataService,
) -> None:
    """指定 as_of 时快照不得包含该时刻之后才确认的结构（因果性）。"""
    bars = service.bars(Timeframe.HOUR4)
    assert len(bars) > 60
    cutoff = bars[40].ts_close_ns
    from pa_trend.domain.models.timeframe import ns_to_dt

    as_of = ns_to_dt(cutoff).isoformat().replace("+00:00", "Z")
    status, envelope = _get(router, f"/api/v1/snapshots?timeframe=4H&as_of={as_of}")
    assert status == 200, envelope
    payload = envelope["data"]["payload"]
    assert payload["as_of_ns"] == cutoff
    for structure in payload["n_structures"]:
        assert structure["confirmed_at_ns"] <= cutoff
    for zone in payload["zones"]:
        assert zone["anchors"]
        assert all(anchor["confirmed_at_ns"] <= cutoff for anchor in zone["anchors"])


def test_unknown_route_returns_not_found(router: ApiRouter) -> None:
    """未知路径返回 404 与结构化错误。"""
    status, envelope = _get(router, "/api/v1/does-not-exist")
    assert status == 404
    assert envelope["error"]["code"] == "NOT_FOUND"


def _create_swing(router: ApiRouter, project_id: str, *, price: str = "2400.0") -> dict:
    status, envelope = _post(
        router,
        f"/api/v1/annotation-projects/{project_id}/annotations",
        {
            "entity_type": "SWING_POINT",
            "timeframe": "4H",
            "payload": {
                "direction": "LOW",
                "price": price,
                "occurred_at": "2026-01-01T00:00:00Z",
                "confirmed_at": "2026-01-01T04:00:00Z",
            },
            "actor": "test",
        },
    )
    assert status == 200, envelope
    return envelope["data"]


def test_comparison_requires_frozen_golden_ground_truth(router: ApiRouter) -> None:
    """DRAFT 不得直接参与程序比较；必须先冻结黄金样本（SACW 4.3、6.5）。"""
    status, envelope = _get(router, "/api/v1/annotation-projects")
    project_id = envelope["data"]["projects"][0]["project_id"]

    approved = _create_swing(router, project_id, price="2400.0")
    _create_swing(router, project_id, price="2500.0")  # 保持 DRAFT

    status, envelope = _post(
        router,
        f"/api/v1/annotation-projects/{project_id}/comparisons/swings?timeframe=4H",
    )
    assert status == 409
    assert envelope["error"]["code"] == "GOLDEN_DATASET_REQUIRED"

    for target in ("SUBMITTED", "REVIEWED", "APPROVED"):
        status, envelope = _post(
            router,
            f"/api/v1/annotations/{approved['annotation_id']}/status",
            {"status": target, "actor": "test"},
        )
        assert status == 200, envelope

    status, envelope = _post(
        router,
        "/api/v1/golden-datasets",
        {"project_id": project_id, "split": "HOLDOUT", "actor": "test"},
    )
    assert status == 200, envelope
    golden = envelope["data"]

    status, envelope = _post(
        router,
        f"/api/v1/annotation-projects/{project_id}/comparisons/swings"
        f"?timeframe=4H&golden_dataset_id={golden['golden_dataset_id']}",
    )
    assert status == 200, envelope
    report = envelope["data"]
    assert report["goldenDatasetId"] == golden["golden_dataset_id"]
    assert report["replayRunId"] == golden["baseline_replay_run_id"]
    assert report["groundTruthCount"] == 1
    assert report["human_count"] == 1
    assert report["includedStatuses"] == ["FROZEN"]
    assert "人工复核" in report["note"]


def test_15m_protected_point_is_rejected(router: ApiRouter) -> None:
    """15M 不允许独立 ProtectedLow（V1.4.8 第 8 章）。"""
    status, envelope = _get(router, "/api/v1/annotation-projects")
    project_id = envelope["data"]["projects"][0]["project_id"]
    status, envelope = _post(
        router,
        f"/api/v1/annotation-projects/{project_id}/annotations",
        {
            "entity_type": "PROTECTED_POINT",
            "timeframe": "15M",
            "payload": {
                "direction": "LOW",
                "price": "2400.0",
                "valid_from": "2026-01-01T00:00:00Z",
            },
            "actor": "test",
        },
    )
    assert status == 400
    assert envelope["error"]["code"] == "PROTECTED_POINT_15M_NOT_ALLOWED"
