"""宏观趋势状态机与方向权限（规格 V1.4.8 第 8 节）。

三个宏观周期各自独立判定，且必须按规格给出的优先级顺序求值：

- 1MONTH：``UNKNOWN → DOWNTREND → WEAKENING → UPTREND``
- 1W：``UNKNOWN → BEARISH → TRANSITION → WEAKENING → BULLISH``
- 1D：``UNKNOWN → BEARISH → TRANSITION → PULLBACK → BULLISH``

``CanOpen`` 只允许明确列举的组合；``CanHold`` 与 ``CanOpen`` 语义分离，不得互相
推导（规格第 8.5 节）。
"""

from __future__ import annotations

from decimal import Decimal

from pa_trend.domain.state.enums import (
    DayState,
    MonthState,
    StateParams,
    TimeframeFacts,
    WeekState,
)


def compute_month_state(
    facts: TimeframeFacts,
    params: StateParams,
    previous: MonthState | None = None,
) -> MonthState:
    """判定 1MONTH 状态（第 8.2 节）。

    参数
    ----
    facts : TimeframeFacts
        月线的推理输入。
    params : StateParams
        状态机参数。
    previous : MonthState 或 None
        上一根完成月线时的状态，用于 WEAKENING 的「原多头结构失去延续」判定。

    返回
    ----
    MonthState
        按优先级求得的状态。
    """
    relations = facts.relations

    # 第一步：UNKNOWN
    if not facts.ready or not relations.known:
        return MonthState.UNKNOWN

    # 第二步：DOWNTREND —— LH + LL 且 ProtectedHigh 有效
    if relations.bearish and facts.levels.has_protected_high:
        return MonthState.DOWNTREND

    # 第三步：WEAKENING
    protects_low = facts.levels.has_protected_low
    if relations.bullish and facts.sma is not None and facts.close < facts.sma and protects_low:
        return MonthState.WEAKENING
    if (
        previous in {MonthState.UPTREND, MonthState.WEAKENING}
        and not protects_low
        and not relations.bearish
    ):
        return MonthState.WEAKENING

    # 第四步：UPTREND —— HH + HL 且 Close > SMA22 且 ProtectedLow 有效
    if relations.bullish and facts.sma is not None and facts.close > facts.sma and protects_low:
        return MonthState.UPTREND

    # 第五步：其余
    return MonthState.UNKNOWN


def compute_week_state(
    facts: TimeframeFacts,
    params: StateParams,
    previous: WeekState | None = None,
) -> WeekState:
    """判定 1W 状态（第 8.3 节）。"""
    relations = facts.relations

    if not facts.ready or not relations.known:
        return WeekState.UNKNOWN

    # BEARISH：LH + LL 且 ProtectedHigh 有效（SMA22 不是必要条件）
    if relations.bearish and facts.levels.has_protected_high:
        return WeekState.BEARISH

    # TRANSITION：原多头 ProtectedLow 失效，且空头结构未完整确认
    if (
        not facts.levels.has_protected_low
        and not relations.bearish
        and previous in {WeekState.BULLISH, WeekState.WEAKENING, WeekState.TRANSITION}
    ):
        return WeekState.TRANSITION

    # WEAKENING：多头结构仍在但收盘跌破 SMA22
    if (
        relations.bullish
        and facts.sma is not None
        and facts.close < facts.sma
        and facts.levels.has_protected_low
    ):
        return WeekState.WEAKENING
    if (
        previous in {WeekState.BULLISH, WeekState.WEAKENING}
        and facts.sma is not None
        and facts.close < facts.sma
        and facts.levels.has_protected_low
    ):
        return WeekState.WEAKENING

    # BULLISH
    if (
        relations.bullish
        and facts.sma is not None
        and facts.close > facts.sma
        and facts.levels.has_protected_low
    ):
        return WeekState.BULLISH

    return WeekState.UNKNOWN


def compute_day_state(
    facts: TimeframeFacts,
    params: StateParams,
    previous: DayState | None = None,
) -> DayState:
    """判定 1D 状态（第 8.4 节）。"""
    relations = facts.relations

    if not facts.ready or not relations.known:
        return DayState.UNKNOWN

    if relations.bearish and facts.levels.has_protected_high:
        return DayState.BEARISH

    if (
        not facts.levels.has_protected_low
        and not relations.bearish
        and previous in {DayState.BULLISH, DayState.PULLBACK, DayState.TRANSITION}
    ):
        return DayState.TRANSITION

    pullback = _in_pullback(
        facts,
        previous_is_bullish=previous is DayState.BULLISH,
        min_atr_multiple=params.pullback_min_atr_1d,
        buffer=params.protected_break_buffer_atr,
    )
    if pullback:
        return DayState.PULLBACK

    if (
        relations.bullish
        and facts.sma is not None
        and facts.close > facts.sma
        and facts.levels.has_protected_low
    ):
        return DayState.BULLISH

    return DayState.UNKNOWN


def _in_pullback(
    facts: TimeframeFacts,
    *,
    previous_is_bullish: bool,
    min_atr_multiple: Decimal,
    buffer: Decimal,
) -> bool:
    """判断是否处于合规回撤（第 8.4 节 1D 与第 9.3 节 4H 共用口径）。"""
    origin = facts.levels.pullback_origin_high
    protected_low = facts.levels.protected_low
    atr = facts.atr
    if not previous_is_bullish or origin is None or protected_low is None or atr is None:
        return False
    if atr <= 0:
        return False
    if facts.close >= origin:
        return False
    if facts.close <= protected_low - buffer * atr:
        return False
    return origin - facts.close >= min_atr_multiple * atr


def can_open(month: MonthState, week: WeekState, day: DayState) -> bool:
    """新开多头权限（第 8.5 节）。

    只有明确允许的组合才返回 True：

    - ``UPTREND + BULLISH + BULLISH``
    - ``UPTREND + BULLISH + PULLBACK``

    参数
    ----
    month : MonthState
        1MONTH 状态。
    week : WeekState
        1W 状态。
    day : DayState
        1D 状态。

    返回
    ----
    bool
        是否允许新开仓。
    """
    if month is not MonthState.UPTREND or week is not WeekState.BULLISH:
        return False
    return day in {DayState.BULLISH, DayState.PULLBACK}


def can_hold(position_exists: bool, forced_exit_triggered: bool) -> bool:
    """已有持仓许可（第 8.5 节）。

    ``CanHold = PositionExists AND NOT ForcedExitTriggered``。宏观状态禁止新开仓
    并不自动推导为必须平仓。

    参数
    ----
    position_exists : bool
        当前是否存在多头持仓。
    forced_exit_triggered : bool
        是否已触发强制退出（硬止损、结构强制失效、风险异常等）。

    返回
    ----
    bool
        是否允许继续持有。
    """
    return position_exists and not forced_exit_triggered
