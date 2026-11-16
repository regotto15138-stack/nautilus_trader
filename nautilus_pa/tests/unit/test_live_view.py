"""实时视图测试：采集器新落盘的 K 线必须能被工作台发现并按需重建。

工作台与采集器是两个进程，工作台只在启动时构建一次视图。这里用临时的
Parquet 目录模拟「采集器继续写盘」：

- ``refresh()`` 检测到新 K 线后重建视图，``/api/v1/market/live`` 只下发增量；
- 没有新数据时不重建，也不下发任何 K 线；
- 增量超过上限时下发 ``reload``，让前端整页重载；
- 合成数据（``--demo``）不受影响。
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from nautilus_trader.model import Bar, BarType, Price, Quantity
from nautilus_trader.persistence import ParquetDataCatalog

from pa_trend.adapters.nautilus.bar_converter import to_domain_bar
from pa_trend.application.annotation_store import SacwStore
from pa_trend.application.data_service import (
    LIVE_REFRESH_INTERVAL_SECS,
    MAX_LIVE_BARS,
    DataService,
)
from pa_trend.application.regression import RegressionRunner, load_cases
from pa_trend.domain.models.bar import Bar as DomainBar
from pa_trend.domain.models.timeframe import (
    Timeframe,
    dt_to_ns,
    expected_close_ns,
    ns_to_dt,
)
from pa_trend.presentation.api import ApiRouter

CONFIGS_DIR = Path(__file__).resolve().parents[2] / "configs"
INSTRUMENT_ID = "ETH-USDT-SWAP.OKX"
# 2026-01-05 是周一，UTC 零点同时是日、周、15M 周期的合法边界。
ANCHOR = dt_to_ns(datetime(2026, 1, 5, tzinfo=UTC))

NATILUS_BAR_TYPE = f"{INSTRUMENT_ID}-15-MINUTE-LAST-EXTERNAL"


def _write_15m_bars(catalog_path: Path, start_index: int, count: int) -> list[int]:
    """向临时 catalog 写入 ``count`` 根 15M K 线，返回它们的开盘时刻。"""
    catalog = ParquetDataCatalog(str(catalog_path))
    bar_type = BarType.from_str(NATILUS_BAR_TYPE)
    period = 15 * 60 * 1_000_000_000
    opens = [ANCHOR + (start_index + offset) * period for offset in range(count)]
    bars = [
        Bar(
            bar_type,
            Price.from_str(f"{3000 + index}.5"),
            Price.from_str(f"{3010 + index}.0"),
            Price.from_str(f"{2990 + index}.0"),
            Price.from_str(f"{3005 + index}.0"),
            Quantity.from_str("10.00"),
            ts_open,
            ts_open + 1,
        )
        for index, ts_open in enumerate(opens)
    ]
    catalog.write_bars(
        bars,
        start=opens[0],
        end=expected_close_ns(opens[-1], Timeframe.MIN15, session_offset_minutes=480),
        skip_disjoint_check=True,
    )
    return opens


def _catalog_with_history(tmp_path: Path, count: int = 40) -> Path:
    catalog_path = tmp_path / "catalog"
    catalog_path.mkdir()
    _write_15m_bars(catalog_path, 0, count)
    return catalog_path


@pytest.fixture
def service(tmp_path: Path) -> DataService:
    instance = DataService(
        instrument_id=INSTRUMENT_ID,
        configs_dir=CONFIGS_DIR,
        catalog_path=_catalog_with_history(tmp_path),
        demo=False,
        session_offset_hours=8,
    )
    instance.ensure_built()
    return instance


def test_refresh_reports_no_change_without_new_bars(service: DataService) -> None:
    status = service.refresh()

    assert status["changed"] is False
    assert status["addedBars"] == 0
    assert status["changesByTimeframe"] == {}
    assert status["buildCount"] == 1
    assert status["refreshIntervalSecs"] == LIVE_REFRESH_INTERVAL_SECS
    assert status["maxLiveBars"] == MAX_LIVE_BARS


def test_refresh_rebuilds_after_collector_writes(service: DataService, tmp_path: Path) -> None:
    before = len(service.bars(Timeframe.MIN15))
    before_dataset = service.dataset_info().dataset_id

    _write_15m_bars(tmp_path / "catalog", 40, 2)
    status = service.refresh()

    assert status["changed"] is True
    assert status["addedBars"] == 2
    assert status["changesByTimeframe"] == {"15M": 2}
    assert status["buildCount"] == 2
    assert status["lastBarAtNs"] is not None
    assert len(service.bars(Timeframe.MIN15)) == before + 2
    # 数据集哈希随内容变化，标注与快照能据此判断版本。
    assert service.dataset_info().dataset_id != before_dataset

    follow_up = service.refresh()
    assert follow_up["changed"] is False
    assert follow_up["buildCount"] == 2


def test_bars_since_returns_only_new_bars(service: DataService, tmp_path: Path) -> None:
    last_close = service.bars(Timeframe.MIN15)[-1].ts_close_ns
    assert service.bars_since(Timeframe.MIN15, since_close_ns=last_close) == []

    _write_15m_bars(tmp_path / "catalog", 40, 1)
    service.refresh()

    incremental = service.bars_since(Timeframe.MIN15, since_close_ns=last_close)
    assert len(incremental) == 1
    assert incremental[0].ts_open_ns == last_close


def test_timeframe_section_view_matches_payload_shape(service: DataService) -> None:
    section = service.timeframe_section_view(Timeframe.MIN15)
    payload_section = service.payload()["series"]["15M"]

    assert set(section) == set(payload_section)
    assert section["candles"][-1] == payload_section["candles"][-1]


def test_demo_mode_never_rebuilds(tmp_path: Path) -> None:
    instance = DataService(
        instrument_id=INSTRUMENT_ID,
        configs_dir=CONFIGS_DIR,
        catalog_path=None,
        demo=True,
        demo_bars=120,
        session_offset_hours=0,
    )
    instance.ensure_built()

    status = instance.refresh()

    assert status["changed"] is False
    assert status["buildCount"] == 1


@pytest.fixture
def router(service: DataService, tmp_path: Path) -> ApiRouter:
    store = SacwStore(tmp_path / "live.sqlite3")
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


def _get(router: ApiRouter, path: str) -> dict:
    parsed = urlparse(path)
    status, envelope = router.dispatch(
        method="GET",
        path=parsed.path,
        query=parse_qs(parsed.query),
        body=None,
    )
    assert status == 200
    assert envelope["error"] is None
    return envelope["data"]


def test_market_live_reports_unchanged_view(router: ApiRouter) -> None:
    data = _get(router, "/api/v1/market/live")

    assert data["changed"] is False
    assert {item["timeframe"] for item in data["timeframes"]} == {
        timeframe.value for timeframe in Timeframe
    }
    assert all(item["bars"] == [] for item in data["timeframes"])
    assert all(item["series"] is None for item in data["timeframes"])


def test_market_live_delivers_increment_and_overlay(router: ApiRouter, tmp_path: Path) -> None:
    last_close = router.service.bars(Timeframe.MIN15)[-1].ts_close_ns
    _write_15m_bars(tmp_path / "catalog", 40, 1)

    data = _get(router, f"/api/v1/market/live?since_close_ns={last_close}")

    assert data["changed"] is True
    assert data["addedBars"] == 1
    section = next(item for item in data["timeframes"] if item["timeframe"] == "15M")
    assert section["reload"] is False
    assert len(section["bars"]) == 1
    assert section["bars"][0]["openTime"] == _iso(last_close)
    assert section["bars"][0]["isClosed"] is True
    # 叠加层与整页载荷同构，前端可以直接替换。
    assert section["series"]["candles"][-1]["time"] == last_close // 1_000_000_000
    assert "swingMarkers" in section["series"]
    unaffected = next(item for item in data["timeframes"] if item["timeframe"] == "4H")
    assert unaffected["changed"] is False
    assert unaffected["reload"] is False


def test_market_live_delivers_increment_when_client_is_behind(
    router: ApiRouter,
    tmp_path: Path,
) -> None:
    """前端游标早于新增区间时，按游标之后的全部 K 线补齐（仍属增量）。"""
    _write_15m_bars(tmp_path / "catalog", 40, 1)

    data = _get(router, f"/api/v1/market/live?since_close_ns={ANCHOR}")

    section = next(item for item in data["timeframes"] if item["timeframe"] == "15M")
    assert section["changed"] is True
    assert section["reload"] is False
    assert len(section["bars"]) == 41
    assert all(bar["isClosed"] for bar in section["bars"])


def test_market_live_requests_reload_beyond_increment_limit(
    router: ApiRouter,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """增量超过上限时不下发 K 线，改为要求前端整页重载。"""
    monkeypatch.setattr(
        "pa_trend.application.data_service.MAX_LIVE_BARS",
        1,
    )
    _write_15m_bars(tmp_path / "catalog", 40, 3)

    data = _get(router, "/api/v1/market/live")

    assert data["maxLiveBars"] == 1
    section = next(item for item in data["timeframes"] if item["timeframe"] == "15M")
    assert section["changed"] is True
    assert section["added"] == 3
    assert section["reload"] is True
    assert section["bars"] == []
    assert section["series"] is None


def test_market_live_rejects_invalid_since(router: ApiRouter) -> None:
    parsed = urlparse("/api/v1/market/live?since_close_ns=not-a-time")
    status, envelope = router.dispatch(
        method="GET",
        path=parsed.path,
        query=parse_qs(parsed.query),
        body=None,
    )

    assert status == 400
    assert envelope["error"]["code"] == "INVALID_SINCE"


def test_market_bars_payload_unchanged(router: ApiRouter) -> None:
    data = _get(router, "/api/v1/market/bars?timeframe=15M&limit=2")

    assert len(data["bars"]) == 2
    assert set(data["bars"][0]) == {
        "barId",
        "openTime",
        "closeTime",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "isClosed",
        "source",
    }


def test_timeframe_section_builds_domain_view(service: DataService) -> None:
    """叠加层与引擎读取同一份状态：最新一根 K 线的指标必须一致。"""
    section = service.timeframe_section_view(Timeframe.MIN15)
    updates = service.updates(Timeframe.MIN15)

    assert section["sma"][-1]["value"] == float(updates[-1].sma)
    assert section["atr"][-1]["value"] == float(updates[-1].atr)
    assert section["candles"][-1]["time"] == updates[-1].bar.ts_open_ns // 1_000_000_000


def _iso(ns: int) -> str:
    return ns_to_dt(ns).isoformat().replace("+00:00", "Z")


def test_domain_bar_roundtrip_matches_catalog(service: DataService, tmp_path: Path) -> None:
    """新增 K 线的领域价格必须精确（不做浮点往返）。"""
    _write_15m_bars(tmp_path / "catalog", 40, 1)
    service.refresh()
    bar: DomainBar = service.bars(Timeframe.MIN15)[-1]

    catalog = ParquetDataCatalog(str(tmp_path / "catalog"))
    raw = catalog.query_bars(identifiers=[NATILUS_BAR_TYPE])[-1]
    expected = to_domain_bar(raw, Timeframe.MIN15, session_offset_minutes=480)

    # 最后一根写入的 K 线是 3005.0；比较的是「视图值与重新读取的值」一致。
    assert bar.close == expected.close == Decimal("3005.0")
    assert bar.ts_close_ns == dt_to_ns(expected.ts_close)
