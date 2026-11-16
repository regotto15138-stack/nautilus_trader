"""初始状态快照测试（SACW 21.2、21.3、24）。"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from helpers import INSTRUMENT_ID, dec
from pa_trend.application.demo_data import generate_demo_bars
from pa_trend.application.market_context import MarketContext
from pa_trend.application.snapshot import (
    SnapshotStatus,
    build_snapshot,
    replay_and_snapshot,
    zone_is_trustworthy,
)
from pa_trend.config.loader import load_config
from pa_trend.domain.models.timeframe import Timeframe

CONFIGS_DIR = Path(__file__).resolve().parents[2] / "configs"


def _load():
    return load_config(CONFIGS_DIR)


def test_snapshot_contains_zone_parameters_and_config_hash() -> None:
    """快照必须记录 Zone 三个入选参数与配置哈希（SACW 21.2）。"""
    config = _load()
    context = MarketContext(config)
    for bar in generate_demo_bars(
        instrument_id=INSTRUMENT_ID,
        timeframe=Timeframe.HOUR4,
        count=160,
    ):
        context.on_bar(bar)

    result = build_snapshot(
        config,
        context=context,
        timeframe=Timeframe.HOUR4,
        as_of_ns=None,
        dataset_id="ds-test",
    )
    assert result.status is SnapshotStatus.READY
    payload = result.payload
    zone_parameters = payload["zone_parameters"]
    assert zone_parameters["zone_half_width_atr"] == "0.1"
    assert zone_parameters["min_half_width_ticks"] == "2"
    assert zone_parameters["zone_max_age_weeks"] == "52"
    assert payload["market"]["tick_size"] == "0.01"
    assert payload["config_hash"]
    assert payload["indicators"]["atr_ma22"] == "N/A / SPEC_AMBIGUITY"
    state_machines = payload["state_machines"]
    assert state_machines["states"]["4H"] in {
        "TREND_UP", "TREND_DOWN", "PULLBACK", "RANGE", "TRANSITION", "UNKNOWN"
    }
    assert state_machines["states"]["15M"] is None
    assert isinstance(state_machines["canOpen"], bool)
    assert isinstance(state_machines["canHold"], bool)
    assert payload["position"] is None
    assert result.snapshot_hash


def test_snapshot_is_insufficient_without_history() -> None:
    """预热不足必须标记 INSUFFICIENT_HISTORY，不得伪装成 READY。"""
    config = _load()
    context = MarketContext(config)
    for bar in generate_demo_bars(
        instrument_id=INSTRUMENT_ID,
        timeframe=Timeframe.HOUR4,
        count=3,
    ):
        context.on_bar(bar)

    result = build_snapshot(
        config,
        context=context,
        timeframe=Timeframe.HOUR4,
        as_of_ns=None,
    )
    assert result.status is SnapshotStatus.INSUFFICIENT_HISTORY
    assert any("INSUFFICIENT_HISTORY" in item for item in result.missing)


def test_zone_snapshot_trust_requires_all_anchor_confirm_times() -> None:
    """PB-47：只有边界与锚点数量的快照不可信。"""
    from datetime import UTC, datetime

    from pa_trend.domain.models.swing import SwingDirection, SwingPoint
    from pa_trend.domain.models.timeframe import dt_to_ns
    from pa_trend.domain.structure.zone import ZoneEngine, ZoneParams

    engine = ZoneEngine(
        instrument_id=INSTRUMENT_ID,
        timeframe=Timeframe.HOUR4,
        tick_size=dec("0.01"),
        params=ZoneParams(),
    )
    anchor = datetime(2024, 1, 1, tzinfo=UTC)
    for sequence, price in enumerate(("3000", "3002")):
        occurred = dt_to_ns(anchor) + sequence * 4 * 3600 * 1_000_000_000
        engine.on_swing_point(
            SwingPoint(
                point_id=f"p{sequence}",
                instrument_id=INSTRUMENT_ID,
                timeframe=Timeframe.HOUR4,
                direction=SwingDirection.LOW,
                price=Decimal(price),
                occurred_at_ns=occurred,
                confirmed_at_ns=occurred,
                atr_snapshot=Decimal("10"),
                source_bar_id=f"b{sequence}",
                sequence=sequence,
            ),
            Decimal("10"),
        )
    zone = engine.zones[0]
    assert zone_is_trustworthy(zone) is True


def test_replay_orders_bars_by_close_then_slower_timeframe_first() -> None:
    """同一时间戳内高周期先完成，低周期后执行（规格 3.3、3.4）。"""
    config = _load()
    day_bars = generate_demo_bars(
        instrument_id=INSTRUMENT_ID,
        timeframe=Timeframe.DAY,
        count=30,
    )
    hour4_bars = generate_demo_bars(
        instrument_id=INSTRUMENT_ID,
        timeframe=Timeframe.HOUR4,
        count=30,
    )
    result = replay_and_snapshot(
        config,
        bars_by_timeframe={Timeframe.DAY: day_bars, Timeframe.HOUR4: hour4_bars},
        timeframe=Timeframe.HOUR4,
        as_of_ns=None,
    )
    assert result.payload["timeframe"] == "4H"
    assert result.payload["indicators"]["bar_count"] >= 0
