"""保护点与回撤起点（规格 V1.4.8 第 5 节）。

维护每个周期独立的：

- ``ProtectedLow``：当前有效多头趋势中承担保护作用的 HL 低点。
- ``ProtectedHigh``：当前有效空头趋势中承担保护作用的 LH 高点。
- ``PullbackOriginHigh``：当前多头结构回撤开始前的最高确认 SwingHigh。

三者的失效与更新规则严格按第 5 节实现：只使用已确认 SwingPoint、只允许单方向
更新、失效后不得复活。
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from decimal import Decimal

from pa_trend.domain.models.bar import Bar
from pa_trend.domain.models.swing import SwingPoint
from pa_trend.domain.models.timeframe import Timeframe


@dataclass(frozen=True, slots=True)
class ProtectedLevels:
    """某个周期上保护点的不可变快照。"""

    protected_low: Decimal | None = None
    protected_low_swing_id: str | None = None
    protected_high: Decimal | None = None
    protected_high_swing_id: str | None = None
    pullback_origin_high: Decimal | None = None
    pullback_origin_swing_id: str | None = None
    pullback_started_at_ns: int | None = None

    @property
    def has_protected_low(self) -> bool:
        """是否存在有效的 ProtectedLow。"""
        return self.protected_low is not None

    @property
    def has_protected_high(self) -> bool:
        """是否存在有效的 ProtectedHigh。"""
        return self.protected_high is not None


class ProtectedLevelTracker:
    """按规格第 5 节维护保护点。

    ``break_buffer_atr`` 对应参数表中的 ``Protected Break Buffer ATR``（初始 0.1）。
    """

    def __init__(
        self,
        *,
        timeframe: Timeframe,
        break_buffer_atr: Decimal = Decimal("0.1"),
    ) -> None:
        """初始化跟踪器。"""
        self._timeframe = timeframe
        self._buffer = break_buffer_atr
        self._highs: deque[SwingPoint] = deque(maxlen=2)
        self._lows: deque[SwingPoint] = deque(maxlen=2)

        self._protected_low: Decimal | None = None
        self._protected_low_id: str | None = None
        self._protected_high: Decimal | None = None
        self._protected_high_id: str | None = None
        self._origin_high: Decimal | None = None
        self._origin_id: str | None = None
        self._origin_started_ns: int | None = None

        self._high_relation: str | None = None
        self._low_relation: str | None = None

    @property
    def snapshot(self) -> ProtectedLevels:
        """返回当前不可变快照。"""
        return ProtectedLevels(
            protected_low=self._protected_low,
            protected_low_swing_id=self._protected_low_id,
            protected_high=self._protected_high,
            protected_high_swing_id=self._protected_high_id,
            pullback_origin_high=self._origin_high,
            pullback_origin_swing_id=self._origin_id,
            pullback_started_at_ns=self._origin_started_ns,
        )

    def on_swing(self, point: SwingPoint) -> None:
        """接收一个已确认 SwingPoint 并按结构关系更新保护点。"""
        if point.instrument_id and point.timeframe is not self._timeframe:
            raise ValueError(
                f"swing timeframe {point.timeframe} does not match {self._timeframe}",
            )

        if point.is_high:
            self._highs.append(point)
            if len(self._highs) == 2:
                older, newer = self._highs[0], self._highs[1]
                if newer.price > older.price:
                    self._high_relation = "HH"
                elif newer.price < older.price:
                    self._high_relation = "LH"
                else:
                    self._high_relation = "EQ"
        else:
            self._lows.append(point)
            if len(self._lows) == 2:
                older, newer = self._lows[0], self._lows[1]
                if newer.price > older.price:
                    self._low_relation = "HL"
                elif newer.price < older.price:
                    self._low_relation = "LL"
                else:
                    self._low_relation = "EQ"

        self._apply_structure()

    def _apply_structure(self) -> None:
        if len(self._highs) < 2 or len(self._lows) < 2:
            return

        # 多头结构：HH + HL，建立/更新 ProtectedLow 与回撤起点。
        if self._high_relation == "HH" and self._low_relation == "HL":
            latest_low = self._lows[-1]
            latest_high = self._highs[-1]
            if self._protected_low != latest_low.price:
                self._protected_low = latest_low.price
                self._protected_low_id = latest_low.point_id
            # 新的有效趋势阶段才允许刷新回撤起点（第 5.4 节）。
            if self._origin_id != latest_high.point_id:
                self._origin_high = latest_high.price
                self._origin_id = latest_high.point_id
                self._origin_started_ns = latest_high.confirmed_at_ns
            return

        # 空头结构：LH + LL，建立/更新 ProtectedHigh（严格更低才更新）。
        if self._high_relation == "LH" and self._low_relation == "LL":
            candidate = self._highs[-1]
            if self._protected_high is None or candidate.price < self._protected_high:
                self._protected_high = candidate.price
                self._protected_high_id = candidate.point_id

    def on_bar(self, bar: Bar, atr_value: Decimal | None) -> None:
        """用完成 Bar 的收盘价检查保护点是否失效（影线不算）。"""
        if atr_value is None or atr_value <= 0:
            return
        buffer = self._buffer * atr_value

        if self._protected_low is not None and bar.close < self._protected_low - buffer:
            # 失效后不得复活；等待新的多头结构重新建立。
            self._protected_low = None
            self._protected_low_id = None
            self._origin_high = None
            self._origin_id = None
            self._origin_started_ns = None

        if self._protected_high is not None and bar.close > self._protected_high + buffer:
            self._protected_high = None
            self._protected_high_id = None
