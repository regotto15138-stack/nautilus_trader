"""目录新鲜度审计与按需补齐的测试。

工作台与采集器是两个独立进程。这里覆盖三件事：

- 审计能按当前 UTC 算出「尾部欠根」与「中间缺口」，且未收盘的蜡烛不计入；
- ``MarketSyncService`` 在目录已新鲜时不做任何补齐，在落后时才拉起采集器；
- HTTP 层的 ``/market/freshness`` 与 ``/market/sync`` 在合成数据下明确拒绝。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from nautilus_trader.model import Bar, BarType, Price, Quantity
from nautilus_trader.persistence import ParquetDataCatalog

from pa_trend.application.annotation_store import SacwStore
from pa_trend.application.catalog_audit import (
    audit_catalog,
    count_missing_between,
    count_tail_missing,
    summarize,
)
from pa_trend.application.data_service import DataService
from pa_trend.application.market_sync import MarketSyncService, SyncResult
from pa_trend.application.regression import RegressionRunner, load_cases
from pa_trend.domain.models.timeframe import Timeframe, dt_to_ns, expected_close_ns
from pa_trend.presentation.api import ApiError, ApiRouter

CONFIGS_DIR = Path(__file__).resolve().parents[2] / "configs"
INSTRUMENT_ID = "ETH-USDT-SWAP.OKX"
HOUR_NS = 3_600 * 1_000_000_000


def _write_1h_bars(catalog_path: Path, opens: list[int]) -> None:
    """把给定开盘时刻的 1H K 线写入目录。"""
    catalog = ParquetDataCatalog(str(catalog_path))
    bar_type = BarType.from_str(f"{INSTRUMENT_ID}-1-HOUR-LAST-EXTERNAL")
    bars = [
        Bar(
            bar_type,
            Price.from_str("3000.0"),
            Price.from_str("3010.0"),
            Price.from_str("2990.0"),
            Price.from_str("3005.0"),
            Quantity.from_str("10.00"),
            ts_open,
            ts_open + 1,
        )
        for ts_open in opens
    ]
    catalog.write_bars(
        bars,
        start=opens[0],
        end=expected_close_ns(opens[-1], Timeframe.HOUR1, session_offset_minutes=480),
        skip_disjoint_check=True,
    )


def _hour_opens(start: datetime, count: int) -> list[int]:
    return [dt_to_ns(start + timedelta(hours=index)) for index in range(count)]


# ---------------------------------------------------------------- 计数函数


def test_count_tail_missing_excludes_unclosed_candle() -> None:
    """最后一根之后尚未收盘的蜡烛不计入缺失。"""
    last_open = dt_to_ns(datetime(2026, 1, 5, tzinfo=UTC))
    # 最后一根在 01:00 收盘；此刻 00:30，还没有任何一根新蜡烛该出现。
    now = datetime(2026, 1, 5, 0, 30, tzinfo=UTC)
    assert (
        count_tail_missing(
            last_open,
            timeframe=Timeframe.HOUR1,
            session_offset_minutes=480,
            now_utc=now,
        )
        == 0
    )


def test_count_tail_missing_counts_closed_gap() -> None:
    """已经收盘但缺失的每一根都要计入。"""
    last_open = dt_to_ns(datetime(2026, 1, 5, tzinfo=UTC))
    now = datetime(2026, 1, 5, 4, 30, tzinfo=UTC)
    # 最后一根 00:00 在 01:00 收盘；此后 01:00、02:00、03:00 三根已收盘。
    # 04:00 那根要到 05:00 才收盘，此刻还不该出现。
    assert (
        count_tail_missing(
            last_open,
            timeframe=Timeframe.HOUR1,
            session_offset_minutes=480,
            now_utc=now,
        )
        == 3
    )


def test_count_missing_between_detects_interior_gap() -> None:
    """中间隔开 3 根时缺失数为 3。"""
    previous = dt_to_ns(datetime(2026, 1, 5, tzinfo=UTC))
    current = previous + 4 * HOUR_NS
    assert (
        count_missing_between(
            previous,
            current,
            Timeframe.HOUR1,
            session_offset_minutes=480,
        )
        == 3
    )


def test_count_missing_between_adjacent_returns_zero() -> None:
    """相邻的两根之间没有缺失。"""
    previous = dt_to_ns(datetime(2026, 1, 5, tzinfo=UTC))
    assert (
        count_missing_between(
            previous,
            previous + HOUR_NS,
            Timeframe.HOUR1,
            session_offset_minutes=480,
        )
        == 0
    )


# ---------------------------------------------------------------- 目录审计


def test_audit_reports_clean_when_caught_up(tmp_path: Path) -> None:
    """目录追平当前 UTC 时不报落后。"""
    catalog_path = tmp_path / "catalog"
    catalog_path.mkdir()
    start = datetime(2026, 1, 5, tzinfo=UTC)
    _write_1h_bars(catalog_path, _hour_opens(start, 4))

    rows = audit_catalog(
        catalog_dir=catalog_path,
        configs_dir=CONFIGS_DIR,
        instrument_id=INSTRUMENT_ID,
        session_offset_hours=8,
        now_utc=datetime(2026, 1, 5, 4, 10, tzinfo=UTC),
    )
    hour = next(row for row in rows if row.timeframe is Timeframe.HOUR1)
    assert hour.count == 4
    assert hour.tail_missing_closed == 0
    assert not hour.behind


def test_audit_reports_tail_lag(tmp_path: Path) -> None:
    """目录落后时算出尾部欠根。"""
    catalog_path = tmp_path / "catalog"
    catalog_path.mkdir()
    start = datetime(2026, 1, 5, tzinfo=UTC)
    _write_1h_bars(catalog_path, _hour_opens(start, 2))

    rows = audit_catalog(
        catalog_dir=catalog_path,
        configs_dir=CONFIGS_DIR,
        instrument_id=INSTRUMENT_ID,
        session_offset_hours=8,
        now_utc=datetime(2026, 1, 5, 6, 10, tzinfo=UTC),
    )
    hour = next(row for row in rows if row.timeframe is Timeframe.HOUR1)
    assert hour.tail_missing_closed == 4
    assert hour.behind


def test_audit_detects_interior_gap(tmp_path: Path) -> None:
    """中间缺口要被识别成独立的一段。"""
    catalog_path = tmp_path / "catalog"
    catalog_path.mkdir()
    start = datetime(2026, 1, 5, tzinfo=UTC)
    opens = _hour_opens(start, 2) + _hour_opens(start + timedelta(hours=5), 2)
    _write_1h_bars(catalog_path, opens)

    rows = audit_catalog(
        catalog_dir=catalog_path,
        configs_dir=CONFIGS_DIR,
        instrument_id=INSTRUMENT_ID,
        session_offset_hours=8,
        now_utc=datetime(2026, 1, 5, 8, 10, tzinfo=UTC),
    )
    hour = next(row for row in rows if row.timeframe is Timeframe.HOUR1)
    assert len(hour.gaps) == 1
    assert hour.gaps[0].missing == 3
    assert hour.missing_in_gaps == 3
    assert hour.behind


def test_summarize_flags_stale_timeframes(tmp_path: Path) -> None:
    """汇总只把真正落后的周期列进 staleTimeframes。"""
    catalog_path = tmp_path / "catalog"
    catalog_path.mkdir()
    start = datetime(2026, 1, 5, tzinfo=UTC)
    _write_1h_bars(catalog_path, _hour_opens(start, 2))

    rows = audit_catalog(
        catalog_dir=catalog_path,
        configs_dir=CONFIGS_DIR,
        instrument_id=INSTRUMENT_ID,
        session_offset_hours=8,
        now_utc=datetime(2026, 1, 5, 6, 10, tzinfo=UTC),
    )
    summary = summarize(rows)
    assert summary["stale"] is True
    assert "1H" in summary["staleTimeframes"]
    assert summary["worstTailMissingClosed"] == 4


# ---------------------------------------------------------------- 补齐服务


def _make_service(catalog_path: Path) -> MarketSyncService:
    return MarketSyncService(
        catalog_dir=catalog_path,
        configs_dir=CONFIGS_DIR,
        instrument_id=INSTRUMENT_ID,
        session_offset_hours=8,
    )


def test_sync_skips_collector_when_up_to_date(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """目录已新鲜时不得拉起采集器子进程。"""
    catalog_path = tmp_path / "catalog"
    catalog_path.mkdir()
    start = datetime(2026, 1, 5, tzinfo=UTC)
    _write_1h_bars(catalog_path, _hour_opens(start, 4))

    service = _make_service(catalog_path)
    called: list[list[str]] = []

    def _fake_run(command: list[str], **_kwargs: object) -> object:
        called.append(command)
        raise AssertionError("目录已新鲜，不应启动采集器")

    monkeypatch.setattr("pa_trend.application.market_sync.subprocess.run", _fake_run)
    monkeypatch.setattr(
        service,
        "audit",
        lambda: audit_catalog(
            catalog_dir=catalog_path,
            configs_dir=CONFIGS_DIR,
            instrument_id=INSTRUMENT_ID,
            session_offset_hours=8,
            now_utc=datetime(2026, 1, 5, 4, 10, tzinfo=UTC),
        ),
    )

    result = service.sync()
    assert result.status == "up-to-date"
    assert result.ok
    assert result.added_bars == 0
    assert called == []


def test_sync_runs_collector_when_stale(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """落后时启用 ``--backfill-only`` 采集器。"""
    catalog_path = tmp_path / "catalog"
    catalog_path.mkdir()
    start = datetime(2026, 1, 5, tzinfo=UTC)
    _write_1h_bars(catalog_path, _hour_opens(start, 2))

    service = _make_service(catalog_path)
    captured: list[list[str]] = []

    def _fake_run(command: list[str], **_kwargs: object) -> object:
        captured.append(command)

        class _Completed:
            returncode = 0
            stdout = ""
            stderr = ""

        return _Completed()

    monkeypatch.setattr("pa_trend.application.market_sync.subprocess.run", _fake_run)
    monkeypatch.setattr(
        service,
        "audit",
        lambda: audit_catalog(
            catalog_dir=catalog_path,
            configs_dir=CONFIGS_DIR,
            instrument_id=INSTRUMENT_ID,
            session_offset_hours=8,
            now_utc=datetime(2026, 1, 5, 6, 10, tzinfo=UTC),
        ),
    )
    monkeypatch.setattr(
        "pa_trend.application.market_sync._POST_SYNC_POLL_ATTEMPTS",
        0,
    )

    result = service.sync()
    assert captured, "落后时必须启动采集器"
    assert "--backfill-only" in captured[0]
    assert "--catalog" in captured[0]
    # 采集器退出码为 0，但模拟目录没变，因此结果应是「未追平」的 partial。
    assert result.status == "completed"
    assert result.partial


def test_collector_command_carries_proxy(tmp_path: Path) -> None:
    """配了代理就必须出现在采集器命令行里，未配置则不带该参数。"""
    proxied = MarketSyncService(
        catalog_dir=tmp_path,
        configs_dir=CONFIGS_DIR,
        instrument_id=INSTRUMENT_ID,
        session_offset_hours=8,
        proxy_url="http://172.21.192.1:7890",
    )
    command = proxied._collector_command()
    assert command[command.index("--proxy-url") + 1] == "http://172.21.192.1:7890"

    direct = _make_service(tmp_path)
    assert "--proxy-url" not in direct._collector_command()


def test_sync_reports_collector_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """采集器非零退出要变成 failed，且带上原因。"""
    catalog_path = tmp_path / "catalog"
    catalog_path.mkdir()
    start = datetime(2026, 1, 5, tzinfo=UTC)
    _write_1h_bars(catalog_path, _hour_opens(start, 2))

    service = _make_service(catalog_path)

    def _fake_run(_command: list[str], **_kwargs: object) -> object:
        class _Completed:
            returncode = 1
            stdout = ""
            stderr = "Failed to connect data client OKX: connection failed"

        return _Completed()

    monkeypatch.setattr("pa_trend.application.market_sync.subprocess.run", _fake_run)
    monkeypatch.setattr(
        service,
        "audit",
        lambda: audit_catalog(
            catalog_dir=catalog_path,
            configs_dir=CONFIGS_DIR,
            instrument_id=INSTRUMENT_ID,
            session_offset_hours=8,
            now_utc=datetime(2026, 1, 5, 6, 10, tzinfo=UTC),
        ),
    )
    monkeypatch.setattr(
        "pa_trend.application.market_sync._POST_SYNC_POLL_ATTEMPTS",
        0,
    )

    result = service.sync()
    assert result.status == "failed"
    assert not result.ok
    assert "connection failed" in result.message


def test_sync_reports_busy_when_already_running(tmp_path: Path) -> None:
    """并发补齐要返回 busy，而不是再起一个进程写同一个目录。"""
    catalog_path = tmp_path / "catalog"
    catalog_path.mkdir()
    service = _make_service(catalog_path)

    # 手动持有锁，模拟正在进行的补齐。
    assert service._lock.acquire(blocking=False)
    try:
        result = service.sync()
    finally:
        service._lock.release()
    assert result.status == "busy"
    assert not result.ok


def test_sync_result_serializes() -> None:
    """SyncResult 能安全序列化为 JSON 结构。"""
    result = SyncResult(
        status="completed",
        message="已补齐 3 根 K 线",
        started_at_ns=0,
        finished_at_ns=1_500_000_000,
        stale_before=True,
        stale_timeframes=("1H",),
        added_bars=3,
    )
    payload = result.as_dict()
    assert payload["ok"] is True
    assert payload["addedBars"] == 3
    assert payload["durationSecs"] == 1.5


# ---------------------------------------------------------------- HTTP 层


def _build_router(tmp_path: Path, *, demo: bool, sync: MarketSyncService | None) -> ApiRouter:
    catalog_path = tmp_path / "catalog"
    catalog_path.mkdir(exist_ok=True)
    service = DataService(
        instrument_id=INSTRUMENT_ID,
        configs_dir=CONFIGS_DIR,
        catalog_path=None if demo else catalog_path,
        demo=demo,
        demo_bars=40,
    )
    store = SacwStore(tmp_path / "sacw.sqlite3")
    regression = RegressionRunner(
        store=store,
        config=service.config,
        config_hash=service.config_hash,
        code_commit=None,
        dataset_hash="demo",
        configs_dir=CONFIGS_DIR,
    )
    return ApiRouter(service=service, store=store, regression=regression, sync=sync)


def test_freshness_endpoint_rejects_demo(tmp_path: Path) -> None:
    """合成数据没有采集目录，接口要明确拒绝而不是返回空表。"""
    router = _build_router(tmp_path, demo=True, sync=None)
    with pytest.raises(ApiError) as excinfo:
        router.market_freshness()
    assert excinfo.value.code == "SYNC_UNAVAILABLE"


def test_sync_endpoint_rejects_demo(tmp_path: Path) -> None:
    """合成数据不能触发真实采集。"""
    router = _build_router(tmp_path, demo=True, sync=None)
    with pytest.raises(ApiError) as excinfo:
        router.market_sync()
    assert excinfo.value.code == "SYNC_UNAVAILABLE"


def test_sync_endpoint_maps_busy_to_conflict(tmp_path: Path) -> None:
    """已有补齐在跑时返回 SYNC_BUSY / 409。"""
    catalog_path = tmp_path / "catalog"
    catalog_path.mkdir()
    sync_service = _make_service(catalog_path)
    router = _build_router(tmp_path, demo=False, sync=sync_service)

    assert sync_service._lock.acquire(blocking=False)
    try:
        with pytest.raises(ApiError) as excinfo:
            router.market_sync()
    finally:
        sync_service._lock.release()
    assert excinfo.value.code == "SYNC_BUSY"


def test_live_endpoint_exposes_stale_flag(tmp_path: Path) -> None:
    """``/market/live`` 要带上 stale，前端才能区分「新数据」与「采集器停了」。"""
    catalog_path = tmp_path / "catalog"
    catalog_path.mkdir()
    start = datetime(2026, 1, 5, tzinfo=UTC)
    _write_1h_bars(catalog_path, _hour_opens(start, 4))

    sync_service = _make_service(catalog_path)
    router = _build_router(tmp_path, demo=False, sync=sync_service)
    payload = router.market_live(query={})
    assert "stale" in payload
    assert "freshness" in payload
    assert payload["freshness"] is not None


def test_load_cases_smoke() -> None:
    """配置目录应当能加载回归样本（防止测试改了配置路径却没人发现）。"""
    assert isinstance(load_cases(CONFIGS_DIR), list)
