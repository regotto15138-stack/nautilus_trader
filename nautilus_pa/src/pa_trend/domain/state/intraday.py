"""4H 与 1H 状态机（规格 V1.4.8 第 9 节）。

4H 优先级：``UNKNOWN → TREND_DOWN → TRANSITION → PULLBACK → TREND_UP → RANGE``。

1H 优先级：``UNKNOWN → BEARISH → TRANSITION → REVERSAL_CANDIDATE → PULLBACK →
BULLISH → RANGE``。

RANGE 只有在不存在有效趋势结构时才允许成立，不得覆盖有效的趋势或回撤状态。
"""

from __future__ import annotations

from decimal import Decimal

from pa_trend.domain.state.enums import (
    H1State,
    H4State,
    StateParams,
    TimeframeFacts,
)
from pa_trend.domain.state.macro import _in_pullback


def compute_h4_state(
    facts: TimeframeFacts,
    params: StateParams,
    previous: H4State | None = None,
) -> H4State:
    """判定 4H 状态（第 9.2 至 9.7 节）。"""
    relations = facts.relations

    if not facts.ready or not relations.known:
        return H4State.UNKNOWN

    if relations.bearish and facts.levels.has_protected_high:
        return H4State.TREND_DOWN

    if (
        not facts.levels.has_protected_low
        and not relations.bearish
        and previous in {H4State.TREND_UP, H4State.PULLBACK, H4State.TRANSITION}
    ):
        return H4State.TRANSITION

    if _in_pullback(
        facts,
        previous_is_bullish=previous is H4State.TREND_UP,
        min_atr_multiple=params.pullback_min_atr_4h,
        buffer=params.protected_break_buffer_atr,
    ):
        return H4State.PULLBACK

    if (
        relations.bullish
        and facts.sma is not None
        and facts.close > facts.sma
        and facts.levels.has_protected_low
    ):
        return H4State.TREND_UP

    if _is_range(facts, params.range_boundary_tolerance_atr):
        return H4State.RANGE

    return H4State.UNKNOWN


def compute_h1_state(
    facts: TimeframeFacts,
    params: StateParams,
    previous: H1State | None = None,
) -> H1State:
    """判定 1H 状态（第 9.8 与 9.9 节）。"""
    relations = facts.relations

    if not facts.ready or not relations.known:
        return H1State.UNKNOWN

    if relations.bearish and facts.levels.has_protected_high:
        return H1State.BEARISH

    if (
        not facts.levels.has_protected_low
        and not relations.bearish
        and previous
        in {
            H1State.BULLISH,
            H1State.PULLBACK,
            H1State.REVERSAL_CANDIDATE,
            H1State.TRANSITION,
        }
    ):
        return H1State.TRANSITION

    if _is_reversal_candidate(facts, previous):
        return H1State.REVERSAL_CANDIDATE

    if _in_pullback(
        facts,
        previous_is_bullish=previous is H1State.BULLISH,
        min_atr_multiple=params.pullback_min_atr_1h,
        buffer=params.protected_break_buffer_atr,
    ):
        return H1State.PULLBACK

    if (
        relations.bullish
        and facts.sma is not None
        and facts.close > facts.sma
        and facts.levels.has_protected_low
    ):
        return H1State.BULLISH

    if _is_range(facts, params.range_boundary_tolerance_atr):
        return H1State.RANGE

    return H1State.UNKNOWN


def _is_reversal_candidate(facts: TimeframeFacts, previous: H1State | None) -> bool:
    """1H 反转候选：前态 PULLBACK、形成新的 HL，且收盘突破最近确认 SwingHigh。

    规格第 9.8 节要求该 SwingHigh 来自当前 PULLBACK 开始之后。实现取「最近一个已
    确认 SwingHigh」，它必然位于回撤起点之后，符合该要求。
    """
    if previous is not H1State.PULLBACK:
        return False
    if not facts.relations.hl:
        return False
    protected_low = facts.levels.protected_low
    if protected_low is None:
        return False
    if not facts.highs:
        return False
    latest_high = facts.highs[-1]
    # 回撤低点必须高于原 ProtectedLow；最近确认低点若低于 ProtectedLow 则不成立。
    if facts.lows and facts.lows[-1].price <= protected_low:
        return False
    return facts.close > latest_high.price


def _is_range(facts: TimeframeFacts, tolerance_atr: Decimal) -> bool:
    """区间判定（第 9.6 节）：最近两个高点、两个低点分别在容差内。"""
    atr = facts.atr
    if atr is None or atr <= 0:
        return False
    if len(facts.highs) < 2 or len(facts.lows) < 2:
        return False

    sh1, sh2 = facts.highs[-2].price, facts.highs[-1].price
    sl1, sl2 = facts.lows[-2].price, facts.lows[-1].price

    if abs(sh2 - sh1) > tolerance_atr * atr:
        return False
    if abs(sl2 - sl1) > tolerance_atr * atr:
        return False

    upper = (sh1 + sh2) / Decimal(2)
    lower = (sl1 + sl2) / Decimal(2)
    return upper > lower
