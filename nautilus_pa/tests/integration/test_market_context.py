"""多周期上下文集成测试（规格 V1.4.8 第 2.1、3.3 节）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from helpers import INSTRUMENT_ID, make_bar
from pa_trend.application.demo_data import generate_demo_bars
from pa_trend.application.market_context import MarketContext
from pa_trend.config.loader import load_config
from pa_trend.domain.errors import DataIntegrityError
from pa_trend.domain.models.timeframe import ALL_TIMEFRAMES, Timeframe
from pa_trend.domain.state.enums import MonthState

CONFIGS_DIR = Path(__file__).resolve().parents[2] / "configs"


@pytest.fixture
def context() -> MarketContext:
    return MarketContext(load_config(CONFIGS_DIR))


def _feed(context: MarketContext, timeframe: Timeframe, count: int) -> None:
    for bar in generate_demo_bars(
        instrument_id=INSTRUMENT_ID,
        timeframe=timeframe,
        count=count,
    ):
        context.on_bar(bar)


def test_seven_independent_engines_exist(context: MarketContext) -> None:
    """七个周期各有一个独立引擎。"""
    for timeframe in ALL_TIMEFRAMES:
        assert context.engine(timeframe).timeframe is timeframe


def test_timeframes_do_not_share_state(context: MarketContext) -> None:
    """只喂日线时，其它周期不应被更新。"""
    _feed(context, Timeframe.DAY, 30)
    assert context.engine(Timeframe.DAY).bar_count == 30
    for other in ALL_TIMEFRAMES:
        if other is not Timeframe.DAY:
            assert context.engine(other).bar_count == 0


def test_states_are_computed_for_five_timeframes_only(context: MarketContext) -> None:
    """1M/1W/1D/4H/1H 有状态机；15M/3M 只有结构与指标。"""
    for timeframe in ALL_TIMEFRAMES:
        _feed(context, timeframe, 120)

    assert context.engine(Timeframe.MONTH).state is not None
    assert context.engine(Timeframe.WEEK).state is not None
    assert context.engine(Timeframe.DAY).state is not None
    assert context.engine(Timeframe.HOUR4).state is not None
    assert context.engine(Timeframe.HOUR1).state is not None
    assert context.engine(Timeframe.MIN15).state is None
    assert context.engine(Timeframe.MIN3).state is None


def test_snapshot_reports_market_and_permissions(context: MarketContext) -> None:
    """快照应包含宏观状态、结构状态与两项权限。"""
    for timeframe in ALL_TIMEFRAMES:
        _feed(context, timeframe, 150)
    snapshot = context.snapshot()

    assert snapshot.month is MonthState.UPTREND
    assert len(snapshot.per_timeframe) == len(ALL_TIMEFRAMES)
    assert isinstance(snapshot.can_open, bool)
    assert snapshot.can_hold is False


def test_snapshot_can_hold_requires_position(context: MarketContext) -> None:
    """没有持仓时 CanHold 为 False；有持仓且未强制退出时为 True。"""
    for timeframe in ALL_TIMEFRAMES:
        _feed(context, timeframe, 60)
    assert context.snapshot().can_hold is False
    assert context.snapshot(position_exists=True).can_hold is True
    assert context.snapshot(position_exists=True, forced_exit_triggered=True).can_hold is False


def test_out_of_order_bar_is_rejected(context: MarketContext) -> None:
    """时序倒退的 K 线必须报错。"""
    context.on_bar(make_bar(index=1))
    with pytest.raises(DataIntegrityError, match="out-of-order"):
        context.on_bar(make_bar(index=0))


def test_replayed_bar_is_idempotent(context: MarketContext) -> None:
    """同一根 K 线重放不重复计数。"""
    context.on_bar(make_bar(index=0))
    context.on_bar(make_bar(index=0))
    assert context.engine(Timeframe.DAY).bar_count == 1


def test_view_exposes_protected_levels(context: MarketContext) -> None:
    """视图需暴露保护点，供前端与后续 Setup 使用。"""
    _feed(context, Timeframe.DAY, 150)
    view = context.view(Timeframe.DAY)
    assert view.bars == 150
    assert view.warm is True
    assert view.swings > 0
