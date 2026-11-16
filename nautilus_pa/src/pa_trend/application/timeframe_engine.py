"""统一的单周期引擎（规格 V1.4.8 第 2.1 节）。

七个周期使用**同一套算法实现**，但各自持有完全独立的状态：ATR、SMA、ZigZag、
SwingPoint、保护点、N 结构、Zone 以及趋势状态。

该引擎不产生订单，也不做 Setup/Signal 判定；它只负责把一个周期的完成 Bar 转换成
可被上层读取的事实与状态。

``ATR_MA22`` 在规格 V1.4.8 第 4.1 节中不存在，因此本引擎**不计算**该指标
（SACW V1.1.2 第 17.1 节）；前端统一显示 ``N/A / SPEC_AMBIGUITY``。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum

from pa_trend.config.models import PaTrendConfig
from pa_trend.domain.errors import DataIntegrityError
from pa_trend.domain.indicators.atr import WilderAtr
from pa_trend.domain.indicators.sma import SimpleMovingAverage
from pa_trend.domain.models.bar import Bar
from pa_trend.domain.models.swing import SwingPoint
from pa_trend.domain.models.timeframe import Timeframe
from pa_trend.domain.state.enums import (
    DayState,
    H1State,
    H4State,
    MonthState,
    StateParams,
    TimeframeFacts,
    WeekState,
    compute_swing_relations,
)
from pa_trend.domain.state.intraday import compute_h1_state, compute_h4_state
from pa_trend.domain.state.macro import (
    compute_day_state,
    compute_month_state,
    compute_week_state,
)
from pa_trend.domain.structure.levels import ProtectedLevels, ProtectedLevelTracker
from pa_trend.domain.structure.n_structure import NStructure, NStructureDetector
from pa_trend.domain.structure.zone import ZoneEngine, ZoneEvent, ZoneParams
from pa_trend.domain.zigzag.detector import ZigZagCandidateView, ZigZagConfig, ZigZagDetector

#: 规格第 4.6 节与第 8 章要求的最少已确认高低点数量。
_MIN_SWINGS_PER_SIDE = 2

#: ATR_MA22 的支持状态：V1.4.8 未定义该指标（SACW V1.1.2 第 17.1 节）。
ATR_MA_STATUS = "N/A / SPEC_AMBIGUITY"


@dataclass(slots=True)
class TimeframeUpdate:
    """一根完成 Bar 送入单周期引擎后的结果。"""

    bar: Bar
    atr: Decimal | None
    sma: Decimal | None
    swing_point: SwingPoint | None = None
    new_structures: tuple[NStructure, ...] = ()
    invalidated_structures: tuple[NStructure, ...] = ()
    levels: ProtectedLevels = field(default_factory=ProtectedLevels)
    state: StrEnum | None = None
    zigzag_direction: str = "UNKNOWN"
    zigzag_candidate: ZigZagCandidateView | None = None
    zone_events: tuple[ZoneEvent, ...] = ()
    n_structure_invalidation_status: str = "SPEC_AMBIGUITY"

    @property
    def is_warm(self) -> bool:
        """该 Bar 上 ATR 与 SMA 是否都已就绪。"""
        return self.atr is not None and self.sma is not None


class TimeframeEngine:
    """单周期引擎：指标 + ZigZag + 保护点 + N 结构 + Zone + 状态机。"""

    def __init__(self, *, config: PaTrendConfig, timeframe: Timeframe) -> None:
        """初始化某个周期的引擎。"""
        self.timeframe = timeframe
        self.instrument_id = config.instrument_id
        self.atr = WilderAtr(config.indicators.atr_period)
        self.sma = SimpleMovingAverage(config.indicators.ma_period)
        self.zigzag = ZigZagDetector(
            instrument_id=config.instrument_id,
            timeframe=timeframe,
            config=ZigZagConfig(
                reversal_atr_multiple=config.zigzag.reversal_atr_multiple,
            ),
        )
        # 规格第 5.5 节：n_structure_break_buffer_atr 的交易性失效判定仅适用于
        # 15M；其余周期的 N 结构为 RESEARCH_ONLY，不得共用该交易参数做失效判定。
        # 失效判定使用的 ATR 时点尚未裁定（SACW 27.6），因此默认不产出失效价。
        self.structures = NStructureDetector(
            instrument_id=config.instrument_id,
            timeframe=timeframe,
            break_buffer_atr=config.n_structure.break_buffer_atr,
            trading_enabled=(timeframe.value == config.n_structure.trading_timeframe),
            invalidation_enabled=False,
        )
        self.levels = ProtectedLevelTracker(
            timeframe=timeframe,
            break_buffer_atr=config.protected.break_buffer_atr,
        )
        self.zones = ZoneEngine(
            instrument_id=config.instrument_id,
            timeframe=timeframe,
            tick_size=config.tick_size,
            params=ZoneParams(
                merge_distance_atr=config.zone.merge_distance_atr,
                max_cluster_width_atr=config.zone.max_cluster_width_atr,
                half_width_atr=config.zone.half_width_atr,
                min_half_width_ticks=config.zone.min_half_width_ticks,
                test_tolerance_atr=config.zone.test_tolerance_atr,
                break_buffer_atr=config.zone.break_buffer_atr,
                max_age_weeks=config.zone.max_age_weeks,
                min_anchor_count=config.zone.min_anchor_count,
            ),
        )
        self.params = StateParams(
            protected_break_buffer_atr=config.protected.break_buffer_atr,
            pullback_min_atr_1d=config.pullback.min_atr_1d,
            pullback_min_atr_4h=config.pullback.min_atr_4h,
            pullback_min_atr_1h=config.pullback.min_atr_1h,
            pullback_min_atr_15m=config.pullback.min_atr_15m,
            range_boundary_tolerance_atr=config.range.boundary_tolerance_atr,
        )

        self.bar_count = 0
        self.last_bar: Bar | None = None
        self.swings: list[SwingPoint] = []
        self._state: StrEnum | None = None

    # ------------------------------------------------------------------ 只读

    @property
    def state(self) -> StrEnum | None:
        """返回该周期当前状态；15M/3M 无状态机，返回 ``None``。"""
        return self._state

    @property
    def confirmed_highs(self) -> tuple[SwingPoint, ...]:
        """已确认 SwingHigh。"""
        return tuple(point for point in self.swings if point.is_high)

    @property
    def confirmed_lows(self) -> tuple[SwingPoint, ...]:
        """已确认 SwingLow。"""
        return tuple(point for point in self.swings if not point.is_high)

    @property
    def zigzag_direction(self) -> str:
        """返回 ZigZag 对外方向：SEEK_HIGH / SEEK_LOW / UNKNOWN。"""
        return self.zigzag.reported_direction.value

    @property
    def zigzag_candidate_price(self) -> Decimal | None:
        """返回 ZigZag 当前候选极值价格。"""
        return self.zigzag.candidate_price

    @property
    def zigzag_candidate_atr(self) -> Decimal | None:
        """返回候选极值形成时冻结的 ATR（atr_snapshot）。"""
        return self.zigzag.candidate_atr

    @property
    def zigzag_reversal_threshold(self) -> Decimal | None:
        """返回候选极值对应的反转阈值价格。"""
        return self.zigzag.reversal_threshold_price

    @property
    def zigzag_candidate(self) -> ZigZagCandidateView | None:
        """返回候选极值的最小完整快照。"""
        return self.zigzag.candidate_view

    @property
    def is_warm(self) -> bool:
        """ATR 与 SMA 是否都已就绪。"""
        return self.atr.is_ready and self.sma.is_ready

    @property
    def structure_ready(self) -> bool:
        """是否已具备判定 HH/HL 或 LH/LL 的条件。"""
        return (
            self.is_warm
            and len(self.confirmed_highs) >= _MIN_SWINGS_PER_SIDE
            and len(self.confirmed_lows) >= _MIN_SWINGS_PER_SIDE
        )

    @property
    def facts(self) -> TimeframeFacts:
        """返回最新的事实快照，供状态机与上层读取。"""
        close = self.last_bar.close if self.last_bar is not None else Decimal(0)
        return TimeframeFacts(
            timeframe=self.timeframe,
            close=close,
            atr=self.atr.value,
            sma=self.sma.value,
            relations=compute_swing_relations(self.confirmed_highs, self.confirmed_lows),
            levels=self.levels.snapshot,
            highs=self.confirmed_highs,
            lows=self.confirmed_lows,
            warm=self.is_warm,
        )

    # ------------------------------------------------------------------ 更新

    def on_bar(self, bar: Bar) -> TimeframeUpdate:
        """处理一根完成 Bar。"""
        if bar.timeframe is not self.timeframe:
            raise DataIntegrityError(
                f"bar timeframe {bar.timeframe} does not match {self.timeframe}",
            )
        if self.last_bar is not None:
            if bar.ts_close_ns == self.last_bar.ts_close_ns:
                # 同一根完成 Bar 的重放：幂等，不重复计算。
                return self._snapshot_update(bar)
            if bar.ts_close_ns < self.last_bar.ts_close_ns:
                raise DataIntegrityError(
                    f"out-of-order {self.timeframe.name} bar: "
                    f"{bar.ts_close_ns} < {self.last_bar.ts_close_ns}",
                )

        self.atr.update(bar.high, bar.low, bar.close)
        atr_value = self.atr.value
        self.sma.update(bar.close)

        invalidated = self.structures.on_bar(bar, atr_value)

        swing = self.zigzag.update(bar, atr_value)
        new_structures: tuple[NStructure, ...] = ()
        if swing is not None:
            self.swings.append(swing)
            self.levels.on_swing(swing)
            structure = self.structures.on_swing_point(swing)
            if structure is not None:
                structure.activate(bar.ts_close_ns)
                new_structures = (structure,)
            # Zone 聚类只使用已确认 SwingPoint（规格第 6.1、6.3 节）。
            self.zones.on_swing_point(swing, atr_value)

        # 保护点失效只使用完成 Bar 的收盘价。
        self.levels.on_bar(bar, atr_value)
        zone_events = self.zones.on_bar(bar, atr_value)

        self.bar_count += 1
        self.last_bar = bar
        self._state = self._evaluate_state()

        return TimeframeUpdate(
            bar=bar,
            atr=atr_value,
            sma=self.sma.value,
            swing_point=swing,
            new_structures=new_structures,
            invalidated_structures=invalidated,
            levels=self.levels.snapshot,
            state=self._state,
            zigzag_direction=self.zigzag_direction,
            zigzag_candidate=self.zigzag.candidate_view,
            zone_events=zone_events,
            n_structure_invalidation_status=self.structures.invalidation_status,
        )

    def _snapshot_update(self, bar: Bar) -> TimeframeUpdate:
        return TimeframeUpdate(
            bar=bar,
            atr=self.atr.value,
            sma=self.sma.value,
            levels=self.levels.snapshot,
            state=self._state,
            zigzag_direction=self.zigzag_direction,
            zigzag_candidate=self.zigzag.candidate_view,
            n_structure_invalidation_status=self.structures.invalidation_status,
        )

    def _evaluate_state(self) -> StrEnum | None:
        """按周期类型调用对应状态机；只使用已确认数据。"""
        if self.timeframe is Timeframe.MONTH:
            previous = self._state if isinstance(self._state, MonthState) else None
            return compute_month_state(self.facts, self.params, previous)
        if self.timeframe is Timeframe.WEEK:
            previous = self._state if isinstance(self._state, WeekState) else None
            return compute_week_state(self.facts, self.params, previous)
        if self.timeframe is Timeframe.DAY:
            previous = self._state if isinstance(self._state, DayState) else None
            return compute_day_state(self.facts, self.params, previous)
        if self.timeframe is Timeframe.HOUR4:
            previous = self._state if isinstance(self._state, H4State) else None
            return compute_h4_state(self.facts, self.params, previous)
        if self.timeframe is Timeframe.HOUR1:
            previous = self._state if isinstance(self._state, H1State) else None
            return compute_h1_state(self.facts, self.params, previous)
        # 15M / 3M：只维护结构与指标，不产生趋势状态。
        return None
