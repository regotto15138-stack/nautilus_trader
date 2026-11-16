"""多周期上下文与市场快照（规格 V1.4.8 第 2.2、8、9 节）。

把七个周期的独立引擎聚合为：

- 各周期的状态、保护点与结构统计（``TimeframeStateView``）；
- 宏观方向权限 ``CanOpen``；
- 持仓许可 ``CanHold``；
- 4H/1H 结构状态。

执行链 ``MarketContext → Setup4H → Setup1H → Signal15M → Execution3M → RiskManager``
中，本模块只实现第一环 ``MarketContext``；后续环节尚未实现。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from pa_trend.application.timeframe_engine import (
    ATR_MA_STATUS,
    TimeframeEngine,
    TimeframeUpdate,
)
from pa_trend.config.models import PaTrendConfig
from pa_trend.domain.models.bar import Bar
from pa_trend.domain.models.timeframe import (
    ALL_TIMEFRAMES,
    Timeframe,
)
from pa_trend.domain.state.enums import DayState, H1State, H4State, MonthState, WeekState
from pa_trend.domain.state.macro import can_hold, can_open


@dataclass(frozen=True, slots=True)
class TimeframeStateView:
    """单个周期的对外视图。"""

    timeframe: Timeframe
    state: str | None
    bars: int
    warm: bool
    structure_ready: bool
    swings: int
    swing_highs: int
    swing_lows: int
    structures: int
    active_structures: int
    structure_scope: str
    n_structure_invalidation_status: str
    zigzag_direction: str
    zigzag_candidate_id: str | None
    zigzag_candidate_price: Decimal | None
    zigzag_candidate_atr: Decimal | None
    zigzag_candidate_occurred_at_ns: int | None
    zigzag_candidate_bar_id: str | None
    zigzag_reversal_threshold: Decimal | None
    zones: int
    open_zones: int
    atr_ma_status: str
    close: Decimal | None
    atr: Decimal | None
    sma: Decimal | None
    protected_low: Decimal | None
    protected_high: Decimal | None
    pullback_origin_high: Decimal | None


@dataclass(frozen=True, slots=True)
class MarketSnapshot:
    """一次市场快照，供前端与后续环节读取。"""

    per_timeframe: dict[Timeframe, TimeframeStateView]
    month: MonthState
    week: WeekState
    day: DayState
    h4: H4State
    h1: H1State
    can_open: bool
    can_hold: bool


class MarketContext:
    """七个独立周期的聚合器（共享算法、不共享状态）。"""

    def __init__(self, config: PaTrendConfig) -> None:
        """初始化全部七个周期引擎。"""
        self._config = config
        self._engines: dict[Timeframe, TimeframeEngine] = {
            timeframe: TimeframeEngine(config=config, timeframe=timeframe)
            for timeframe in ALL_TIMEFRAMES
        }

    @property
    def config(self) -> PaTrendConfig:
        """返回配置。"""
        return self._config

    def engine(self, timeframe: Timeframe) -> TimeframeEngine:
        """返回指定周期的引擎。"""
        return self._engines[timeframe]

    def on_bar(self, bar: Bar) -> TimeframeUpdate:
        """把完成 Bar 送入其所属周期。"""
        return self._engines[bar.timeframe].on_bar(bar)

    def _state_value(self, timeframe: Timeframe) -> str | None:
        state = self._engines[timeframe].state
        return None if state is None else str(state)

    def _state_enum(self, timeframe: Timeframe, fallback: str) -> object:
        state = self._engines[timeframe].state
        if state is None:
            return fallback
        return state

    def view(self, timeframe: Timeframe) -> TimeframeStateView:
        """构造单个周期的视图。"""
        engine = self._engines[timeframe]
        levels = engine.levels.snapshot
        structures = engine.structures.structures
        candidate = engine.zigzag_candidate
        return TimeframeStateView(
            timeframe=timeframe,
            state=self._state_value(timeframe),
            bars=engine.bar_count,
            warm=engine.is_warm,
            structure_ready=engine.structure_ready,
            swings=len(engine.swings),
            swing_highs=len(engine.confirmed_highs),
            swing_lows=len(engine.confirmed_lows),
            structures=len(structures),
            active_structures=len(engine.structures.active_structures),
            structure_scope=engine.structures.scope,
            n_structure_invalidation_status=engine.structures.invalidation_status,
            zigzag_direction=engine.zigzag_direction,
            zigzag_candidate_id=None if candidate is None else candidate.candidate_id,
            zigzag_candidate_price=engine.zigzag_candidate_price,
            zigzag_candidate_atr=engine.zigzag_candidate_atr,
            zigzag_candidate_occurred_at_ns=(
                None if candidate is None else candidate.occurred_at_ns
            ),
            zigzag_candidate_bar_id=None if candidate is None else candidate.bar_id,
            zigzag_reversal_threshold=engine.zigzag_reversal_threshold,
            zones=len(engine.zones.zones),
            open_zones=len(engine.zones.open_zones),
            atr_ma_status=ATR_MA_STATUS,
            close=engine.last_bar.close if engine.last_bar is not None else None,
            atr=engine.atr.value,
            sma=engine.sma.value,
            protected_low=levels.protected_low,
            protected_high=levels.protected_high,
            pullback_origin_high=levels.pullback_origin_high,
        )

    def snapshot(
        self,
        *,
        position_exists: bool = False,
        forced_exit_triggered: bool = False,
    ) -> MarketSnapshot:
        """生成市场快照。

        参数
        ----
        position_exists : bool
            当前是否存在多头持仓（暂未实现持仓管理，默认 False）。
        forced_exit_triggered : bool
            是否已触发强制退出条件（默认 False）。

        返回
        ----
        MarketSnapshot
            含七个周期视图与方向权限的快照。
        """
        month = self._engines[Timeframe.MONTH].state
        week = self._engines[Timeframe.WEEK].state
        day = self._engines[Timeframe.DAY].state
        h4 = self._engines[Timeframe.HOUR4].state
        h1 = self._engines[Timeframe.HOUR1].state

        month_state = month if isinstance(month, MonthState) else MonthState.UNKNOWN
        week_state = week if isinstance(week, WeekState) else WeekState.UNKNOWN
        day_state = day if isinstance(day, DayState) else DayState.UNKNOWN
        h4_state = h4 if isinstance(h4, H4State) else H4State.UNKNOWN
        h1_state = h1 if isinstance(h1, H1State) else H1State.UNKNOWN

        return MarketSnapshot(
            per_timeframe={tf: self.view(tf) for tf in ALL_TIMEFRAMES},
            month=month_state,
            week=week_state,
            day=day_state,
            h4=h4_state,
            h1=h1_state,
            can_open=can_open(month_state, week_state, day_state),
            can_hold=can_hold(position_exists, forced_exit_triggered),
        )
