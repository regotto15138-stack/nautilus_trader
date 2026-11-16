"""多周期状态机测试（规格 V1.4.8 第 8、9 节）。"""

from __future__ import annotations

from decimal import Decimal

from helpers import dec, make_swing
from pa_trend.domain.models.swing import SwingDirection
from pa_trend.domain.models.timeframe import Timeframe
from pa_trend.domain.state.enums import (
    DayState,
    H1State,
    H4State,
    MonthState,
    StateParams,
    SwingRelations,
    TimeframeFacts,
    WeekState,
)
from pa_trend.domain.state.intraday import compute_h1_state, compute_h4_state
from pa_trend.domain.state.macro import (
    can_hold,
    can_open,
    compute_day_state,
    compute_month_state,
    compute_week_state,
)
from pa_trend.domain.structure.levels import ProtectedLevels

PARAMS = StateParams()


def _facts(
    *,
    timeframe: Timeframe = Timeframe.DAY,
    close: object = "100",
    atr: object | None = "10",
    sma: object | None = "95",
    hh: bool = False,
    hl: bool = False,
    lh: bool = False,
    ll: bool = False,
    data_ready: bool = True,
    protected_low: object | None = "90",
    protected_high: object | None = None,
    pullback_origin: object | None = "120",
    warm: bool = True,
    highs: tuple = (),
    lows: tuple = (),
) -> TimeframeFacts:
    """构造状态机输入。"""
    levels = ProtectedLevels(
        protected_low=None if protected_low is None else dec(protected_low),
        protected_high=None if protected_high is None else dec(protected_high),
        pullback_origin_high=None if pullback_origin is None else dec(pullback_origin),
    )
    relations = SwingRelations(
        hh=hh,
        hl=hl,
        lh=lh,
        ll=ll,
        data_ready=data_ready,
    )
    return TimeframeFacts(
        timeframe=timeframe,
        close=dec(close),
        atr=None if atr is None else dec(atr),
        sma=None if sma is None else dec(sma),
        relations=relations,
        levels=levels,
        highs=highs,
        lows=lows,
        warm=warm,
    )


# --------------------------------------------------------------- 1MONTH


def test_month_uptrend_needs_hh_hl_close_above_sma_and_protected_low() -> None:
    """HH + HL + Close > SMA22 + ProtectedLow 有效 → UPTREND。"""
    facts = _facts(timeframe=Timeframe.MONTH, hh=True, hl=True, close="100", sma="95")
    assert compute_month_state(facts, PARAMS) is MonthState.UPTREND


def test_month_weakening_when_close_below_sma_but_protected_low_holds() -> None:
    """多头结构仍在但收盘跌破 SMA22 → WEAKENING。"""
    facts = _facts(timeframe=Timeframe.MONTH, hh=True, hl=True, close="90", sma="95")
    assert compute_month_state(facts, PARAMS) is MonthState.WEAKENING


def test_month_downtrend_needs_lh_ll_and_protected_high() -> None:
    """LH + LL 且 ProtectedHigh 有效 → DOWNTREND（SMA22 非必要条件）。"""
    facts = _facts(
        timeframe=Timeframe.MONTH,
        lh=True,
        ll=True,
        protected_high="110",
        close="100",
        sma="50",
    )
    assert compute_month_state(facts, PARAMS) is MonthState.DOWNTREND


def test_month_unknown_when_not_warmed_up() -> None:
    """指标未预热 → UNKNOWN。"""
    facts = _facts(timeframe=Timeframe.MONTH, hh=True, hl=True, warm=False)
    assert compute_month_state(facts, PARAMS) is MonthState.UNKNOWN


def test_month_downtrend_has_priority_over_uptrend() -> None:
    """同时满足空头条件时，DOWNTREND 优先于 UPTREND。"""
    facts = _facts(
        timeframe=Timeframe.MONTH,
        hh=True,
        hl=True,
        lh=True,
        ll=True,
        protected_high="110",
        close="100",
        sma="95",
    )
    assert compute_month_state(facts, PARAMS) is MonthState.DOWNTREND


# --------------------------------------------------------------- 1W


def test_week_bullish() -> None:
    """HH + HL + Close > SMA22 + ProtectedLow 有效 → BULLISH。"""
    facts = _facts(timeframe=Timeframe.WEEK, hh=True, hl=True, close="100", sma="95")
    assert compute_week_state(facts, PARAMS) is WeekState.BULLISH


def test_week_transition_when_protected_low_lost_without_bearish_structure() -> None:
    """ProtectedLow 失效且空头结构未确认 → TRANSITION。"""
    facts = _facts(
        timeframe=Timeframe.WEEK,
        hh=True,
        hl=True,
        protected_low=None,
        close="100",
        sma="95",
    )
    assert compute_week_state(facts, PARAMS, WeekState.BULLISH) is WeekState.TRANSITION


def test_week_bearish_does_not_require_sma() -> None:
    """BEARISH 只看 LH + LL 与 ProtectedHigh。"""
    facts = _facts(
        timeframe=Timeframe.WEEK,
        lh=True,
        ll=True,
        protected_high="110",
        close="200",
        sma="50",
    )
    assert compute_week_state(facts, PARAMS) is WeekState.BEARISH


# --------------------------------------------------------------- 1D


def test_day_bullish() -> None:
    """HH + HL + Close > SMA22 → BULLISH。"""
    facts = _facts(timeframe=Timeframe.DAY, hh=True, hl=True, close="100", sma="95")
    assert compute_day_state(facts, PARAMS) is DayState.BULLISH


def test_day_pullback_requires_previous_bullish_and_min_atr_distance() -> None:
    """前态 BULLISH、回撤达到 0.5 ATR 且未破 ProtectedLow → PULLBACK。"""
    facts = _facts(
        timeframe=Timeframe.DAY,
        hh=True,
        hl=True,
        close="100",
        sma="105",
        atr="10",
        pullback_origin="120",
        protected_low="90",
    )
    assert compute_day_state(facts, PARAMS, DayState.BULLISH) is DayState.PULLBACK


def test_day_pullback_rejected_when_retracement_too_small() -> None:
    """回撤幅度不足 0.5 ATR 时不算 PULLBACK。"""
    facts = _facts(
        timeframe=Timeframe.DAY,
        hh=True,
        hl=True,
        close="118",
        sma="105",
        atr="10",
        pullback_origin="120",
        protected_low="90",
    )
    assert compute_day_state(facts, PARAMS, DayState.BULLISH) is not DayState.PULLBACK


def test_day_pullback_rejected_when_protected_low_breached() -> None:
    """收盘跌破 ProtectedLow 缓冲时不是回撤，而是失效。"""
    facts = _facts(
        timeframe=Timeframe.DAY,
        hh=True,
        hl=True,
        close="89",
        sma="105",
        atr="10",
        pullback_origin="200",
        protected_low="90",
    )
    assert compute_day_state(facts, PARAMS, DayState.BULLISH) is not DayState.PULLBACK


# --------------------------------------------------------------- 4H


def test_h4_trend_up() -> None:
    """HH + HL + Close > SMA22 → TREND_UP。"""
    facts = _facts(timeframe=Timeframe.HOUR4, hh=True, hl=True, close="100", sma="95")
    assert compute_h4_state(facts, PARAMS) is H4State.TREND_UP


def test_h4_range_when_boundaries_are_stable() -> None:
    """高点点近似相等、低点近似相等，且无趋势结构 → RANGE。"""
    highs = (
        make_swing(sequence=0, direction=SwingDirection.HIGH, price=110, occurred_index=0),
        make_swing(sequence=1, direction=SwingDirection.HIGH, price=111, occurred_index=2),
    )
    lows = (
        make_swing(sequence=2, direction=SwingDirection.LOW, price=90, occurred_index=1),
        make_swing(sequence=3, direction=SwingDirection.LOW, price=91, occurred_index=3),
    )
    facts = _facts(
        timeframe=Timeframe.HOUR4,
        close="100",
        sma="100",
        atr="10",
        protected_low=None,
        data_ready=True,
        highs=highs,
        lows=lows,
    )
    assert compute_h4_state(facts, PARAMS) is H4State.RANGE


def test_h4_transition_when_protected_low_lost() -> None:
    """ProtectedLow 失效且未确认空头 → TRANSITION。"""
    facts = _facts(
        timeframe=Timeframe.HOUR4,
        hh=True,
        hl=True,
        protected_low=None,
        close="100",
        sma="95",
    )
    assert compute_h4_state(facts, PARAMS, H4State.TREND_UP) is H4State.TRANSITION


# --------------------------------------------------------------- 1H


def test_h1_pullback() -> None:
    """前态 BULLISH、回撤达到 0.3 ATR → PULLBACK。"""
    facts = _facts(
        timeframe=Timeframe.HOUR1,
        hh=True,
        hl=True,
        close="100",
        sma="105",
        atr="10",
        pullback_origin="110",
        protected_low="90",
    )
    assert compute_h1_state(facts, PARAMS, H1State.BULLISH) is H1State.PULLBACK


def test_h1_reversal_candidate_breaks_latest_swing_high() -> None:
    """前态 PULLBACK、形成新 HL 且收盘突破最近确认 SwingHigh → REVERSAL_CANDIDATE。"""
    highs = (
        make_swing(sequence=0, direction=SwingDirection.HIGH, price=120, occurred_index=0),
        make_swing(sequence=1, direction=SwingDirection.HIGH, price=105, occurred_index=2),
    )
    lows = (
        make_swing(sequence=2, direction=SwingDirection.LOW, price=95, occurred_index=1),
        make_swing(sequence=3, direction=SwingDirection.LOW, price=98, occurred_index=3),
    )
    facts = _facts(
        timeframe=Timeframe.HOUR1,
        close="106",
        sma="100",
        atr="10",
        hh=False,
        hl=True,
        protected_low="95",
        pullback_origin="120",
        highs=highs,
        lows=lows,
    )
    assert compute_h1_state(facts, PARAMS, H1State.PULLBACK) is H1State.REVERSAL_CANDIDATE


# --------------------------------------------------------------- 权限


def test_can_open_only_allows_explicit_combinations() -> None:
    """只有 UPTREND + BULLISH + (BULLISH|PULLBACK) 才允许新开仓。"""
    assert can_open(MonthState.UPTREND, WeekState.BULLISH, DayState.BULLISH)
    assert can_open(MonthState.UPTREND, WeekState.BULLISH, DayState.PULLBACK)

    assert not can_open(MonthState.UPTREND, WeekState.BULLISH, DayState.UNKNOWN)
    assert not can_open(MonthState.UPTREND, WeekState.WEAKENING, DayState.BULLISH)
    assert not can_open(MonthState.WEAKENING, WeekState.BULLISH, DayState.BULLISH)
    assert not can_open(MonthState.DOWNTREND, WeekState.BULLISH, DayState.BULLISH)
    assert not can_open(MonthState.UPTREND, WeekState.BEARISH, DayState.BULLISH)
    assert not can_open(MonthState.UPTREND, WeekState.TRANSITION, DayState.BULLISH)
    assert not can_open(MonthState.UPTREND, WeekState.BULLISH, DayState.BEARISH)
    assert not can_open(MonthState.UPTREND, WeekState.BULLISH, DayState.TRANSITION)
    assert not can_open(MonthState.UNKNOWN, WeekState.BULLISH, DayState.BULLISH)


def test_can_hold_is_independent_from_can_open() -> None:
    """CanHold 只取决于持仓与强制退出，不由宏观权限推导。"""
    assert can_hold(True, False) is True
    assert can_hold(True, True) is False
    assert can_hold(False, False) is False


def test_state_params_defaults_match_parameter_table() -> None:
    """默认参数应与参数表初始值一致。"""
    assert PARAMS.protected_break_buffer_atr == Decimal("0.1")
    assert PARAMS.pullback_min_atr_4h == Decimal("0.5")
    assert PARAMS.pullback_min_atr_1h == Decimal("0.3")
    assert PARAMS.pullback_min_atr_1d == Decimal("0.5")
    assert PARAMS.range_boundary_tolerance_atr == Decimal("0.5")
