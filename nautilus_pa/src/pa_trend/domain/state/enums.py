"""多周期状态机的枚举与判定输入（规格 V1.4.8 第 8、9 节）。"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from pa_trend.domain.models.swing import SwingPoint
from pa_trend.domain.models.timeframe import Timeframe
from pa_trend.domain.structure.levels import ProtectedLevels


class MonthState(StrEnum):
    """1MONTH 宏观状态（规格第 8.2 节）。"""

    UPTREND = "UPTREND"
    WEAKENING = "WEAKENING"
    DOWNTREND = "DOWNTREND"
    UNKNOWN = "UNKNOWN"


class WeekState(StrEnum):
    """1W 中期状态（规格第 8.3 节）。"""

    BULLISH = "BULLISH"
    WEAKENING = "WEAKENING"
    BEARISH = "BEARISH"
    TRANSITION = "TRANSITION"
    UNKNOWN = "UNKNOWN"


class DayState(StrEnum):
    """1D 短期状态（规格第 8.4 节）。"""

    BULLISH = "BULLISH"
    PULLBACK = "PULLBACK"
    BEARISH = "BEARISH"
    TRANSITION = "TRANSITION"
    UNKNOWN = "UNKNOWN"


class H4State(StrEnum):
    """4H 状态（规格第 9.1 节）。"""

    TREND_UP = "TREND_UP"
    TREND_DOWN = "TREND_DOWN"
    PULLBACK = "PULLBACK"
    RANGE = "RANGE"
    TRANSITION = "TRANSITION"
    UNKNOWN = "UNKNOWN"


class H1State(StrEnum):
    """1H 状态（规格第 9.8 节）。"""

    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    PULLBACK = "PULLBACK"
    RANGE = "RANGE"
    REVERSAL_CANDIDATE = "REVERSAL_CANDIDATE"
    TRANSITION = "TRANSITION"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class SwingRelations:
    """最近两个已确认高低点之间的结构关系（规格第 5.1 节）。"""

    hh: bool = False
    hl: bool = False
    lh: bool = False
    ll: bool = False
    data_ready: bool = False

    @property
    def bullish(self) -> bool:
        """HH + HL。"""
        return self.hh and self.hl

    @property
    def bearish(self) -> bool:
        """LH + LL。"""
        return self.lh and self.ll

    @property
    def known(self) -> bool:
        """结构关系是否可判定。

        注意：判据是「两组高低点都已确认」，而不是「HH/HL/LH/LL 中某个为真」。
        区间（RANGE）中高低点可能近似相等，四者皆为 False，但结构仍可判定。
        """
        return self.data_ready


def compute_swing_relations(
    highs: tuple[SwingPoint, ...],
    lows: tuple[SwingPoint, ...],
) -> SwingRelations:
    """由最近两个已确认高低点计算 HH/HL/LH/LL。

    参数
    ----
    highs : tuple of SwingPoint
        按确认顺序排列的已确认 SwingHigh，取最后两个。
    lows : tuple of SwingPoint
        按确认顺序排列的已确认 SwingLow，取最后两个。

    返回
    ----
    SwingRelations
        结构关系；数据不足时全部为 False。
    """
    if len(highs) < 2 or len(lows) < 2:
        return SwingRelations()

    h_old, h_new = highs[-2], highs[-1]
    l_old, l_new = lows[-2], lows[-1]
    return SwingRelations(
        hh=h_new.price > h_old.price,
        hl=l_new.price > l_old.price,
        lh=h_new.price < h_old.price,
        ll=l_new.price < l_old.price,
        data_ready=True,
    )


@dataclass(frozen=True, slots=True)
class TimeframeFacts:
    """某周期在最新完成 Bar 上的判定输入。

    状态机只读取本结构，保证「共享算法实现、不共享周期状态」。
    """

    timeframe: Timeframe
    close: Decimal
    atr: Decimal | None
    sma: Decimal | None
    relations: SwingRelations
    levels: ProtectedLevels
    highs: tuple[SwingPoint, ...] = ()
    lows: tuple[SwingPoint, ...] = ()
    warm: bool = False

    @property
    def ready(self) -> bool:
        """指标与结构是否足以判定状态。"""
        return self.warm and self.atr is not None and self.sma is not None


@dataclass(frozen=True, slots=True)
class StateParams:
    """状态机使用的 RESEARCH 参数（参数表第 19 章初始值）。"""

    protected_break_buffer_atr: Decimal = Decimal("0.1")
    pullback_min_atr_1d: Decimal = Decimal("0.5")
    pullback_min_atr_4h: Decimal = Decimal("0.5")
    pullback_min_atr_1h: Decimal = Decimal("0.3")
    pullback_min_atr_15m: Decimal = Decimal("0.3")
    range_boundary_tolerance_atr: Decimal = Decimal("0.5")
