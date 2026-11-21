"""ATR 反转 ZigZag 识别器（规格第 4 节）。"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from pa_trend.domain.models.bar import Bar
from pa_trend.domain.models.swing import SwingDirection, SwingPoint
from pa_trend.domain.models.timeframe import Timeframe


class ZigZagDirection(StrEnum):
    """识别器当前正在寻找的极值方向。

    枚举名与 SACW 第 33 章映射表一致：``SEEK_HIGH / SEEK_LOW / UNKNOWN``。
    ``UNKNOWN`` 表示该周期尚未建立任何候选极值（ATR 预热未完成或尚无完成 Bar），
    此时不应对外声称方向。
    """

    SEEK_HIGH = "SEEK_HIGH"
    SEEK_LOW = "SEEK_LOW"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class ZigZagCandidateView:
    """某一根完成 Bar 之后的 ZigZag 候选快照（SACW 17.5）。

    属性
    ----
    candidate_id : str
        候选极值的确定性标识。
    direction : ZigZagDirection
        ``SEEK_HIGH`` 或 ``SEEK_LOW``。
    price : Decimal
        候选极值价格。
    atr_snapshot : Decimal
        候选极值形成时冻结的 ATR。
    occurred_at_ns : int
        候选极值所在 Bar 的 open_time，与蜡烛图时间键一致。
    bar_id : str
        候选极值来源 Bar 的稳定 ID。
    reversal_threshold_price : Decimal
        反转阈值价格，使用冻结 ATR 计算。
    status : str
        固定为 ``UNCONFIRMED``：候选点尚未成为已确认 SwingPoint。
    """

    candidate_id: str
    direction: ZigZagDirection
    price: Decimal
    atr_snapshot: Decimal
    occurred_at_ns: int
    bar_id: str
    reversal_threshold_price: Decimal
    status: str = "UNCONFIRMED"


@dataclass(frozen=True, slots=True)
class ZigZagConfig:
    """冻结的 ZigZag 参数（规格第 4.1 节）。

    属性
    ----
    reversal_atr_multiple : Decimal
        ``Close <= H_candidate - k * ATR`` 中的 ``k``；规格初始值为 2.0，
        且属于可调研究参数（TUNABLE）。
    """

    reversal_atr_multiple: Decimal = Decimal("2.0")

    def __post_init__(self) -> None:
        """校验反转倍数。"""
        if self.reversal_atr_multiple <= 0:
            raise ValueError(
                f"reversal_atr_multiple must be positive, was {self.reversal_atr_multiple}",
            )


class ZigZagDetector:
    """基于已完成 K 线、以 ATR 反转确认来识别摆动点。

    状态机实现规格第 4.4 节的确定性单遍规则：

    - 每根已完成 K 线只做一次状态更新。
    - 先更新候选极值，再判断反转确认。
    - 确认 K 线不用于初始化下一方向的候选极值，交由下一根已完成 K 线负责。
    - 从不根据同一根 K 线的高低价推断盘中先后顺序。

    文档未定义初始方向。本实现从 ``SEEK_HIGH`` 起、在第一根 ATR 有效的 K 线上
    播种候选极值。该选择是显式且确定性的，并记录在此，因为规格第 0.2 节禁止
    隐式启用文档未定义的行为。
    """

    def __init__(
        self,
        *,
        instrument_id: str,
        timeframe: Timeframe,
        config: ZigZagConfig | None = None,
        initial_direction: ZigZagDirection = ZigZagDirection.SEEK_HIGH,
    ) -> None:
        """初始化识别器。

        参数
        ----
        instrument_id : str
            K 线所属合约。
        timeframe : Timeframe
            被分析的周期。
        config : ZigZagConfig 或 None
            反转参数；缺省使用规格初始值。
        initial_direction : ZigZagDirection
            首次确认之前要寻找的方向。
        """
        self._instrument_id = instrument_id
        self._timeframe = timeframe
        self._config = config or ZigZagConfig()
        self._direction = initial_direction
        self._sequence = 0

        self._candidate_price: Decimal | None = None
        self._candidate_atr: Decimal | None = None
        self._candidate_occurred_ns: int | None = None
        self._candidate_bar_id: str | None = None

        self._swings: list[SwingPoint] = []

    @property
    def direction(self) -> ZigZagDirection:
        """返回当前正在寻找的极值方向（内部状态）。"""
        return self._direction

    @property
    def reported_direction(self) -> ZigZagDirection:
        """返回可对外展示的方向。

        尚未建立候选极值时返回 ``UNKNOWN``（SACW 17.1 要求展示
        ``SEEK_HIGH / SEEK_LOW / UNKNOWN``）。
        """
        if self._candidate_price is None:
            return ZigZagDirection.UNKNOWN
        return self._direction

    @property
    def candidate_price(self) -> Decimal | None:
        """返回当前候选极值价格，无候选时为 ``None``。"""
        return self._candidate_price

    @property
    def candidate_atr(self) -> Decimal | None:
        """返回候选极值形成时冻结的 ATR。"""
        return self._candidate_atr

    @property
    def candidate_occurred_at_ns(self) -> int | None:
        """返回候选极值所在 Bar 的完成时刻；无候选时为 ``None``。

        规格第 4.3 节要求 SwingPoint 记录来源 Bar，SACW 17.1 进一步要求候选
        标记展示候选 Bar，因此候选自身也必须暴露该时刻。
        """
        return self._candidate_occurred_ns

    @property
    def candidate_bar_id(self) -> str | None:
        """返回候选极值来源 Bar 的稳定 ID。"""
        return self._candidate_bar_id

    @property
    def candidate_id(self) -> str | None:
        """返回候选极值的确定性标识；无候选时为 ``None``。"""
        if self._candidate_bar_id is None:
            return None
        return f"C-{self._instrument_id}-{self._timeframe.value}-{self._candidate_bar_id}"

    @property
    def reversal_atr_multiple(self) -> Decimal:
        """返回当前生效的反转倍数 ``k``。"""
        return self._config.reversal_atr_multiple

    @property
    def reversal_threshold_price(self) -> Decimal | None:
        """返回反转阈值价格。

        规格第 4.2 节：寻找高点时为 ``CandidateHigh - k * CandidateATR``，
        寻找低点时为 ``CandidateLow + k * CandidateATR``。ATR 必须使用候选
        形成时冻结的快照，不能用当前最新 ATR 替代（SACW 17.1）。
        """
        if self._candidate_price is None or self._candidate_atr is None:
            return None
        offset = self._config.reversal_atr_multiple * self._candidate_atr
        if self._direction is ZigZagDirection.SEEK_HIGH:
            return self._candidate_price - offset
        return self._candidate_price + offset

    @property
    def candidate_view(self) -> ZigZagCandidateView | None:
        """返回当前候选极值快照；无候选时返回 ``None``。"""
        candidate_id = self.candidate_id
        price = self._candidate_price
        atr_snapshot = self._candidate_atr
        occurred_ns = self._candidate_occurred_ns
        bar_id = self._candidate_bar_id
        threshold = self.reversal_threshold_price
        if (
            candidate_id is None
            or price is None
            or atr_snapshot is None
            or occurred_ns is None
            or bar_id is None
            or threshold is None
        ):
            return None
        return ZigZagCandidateView(
            candidate_id=candidate_id,
            direction=self._direction,
            price=price,
            atr_snapshot=atr_snapshot,
            occurred_at_ns=occurred_ns,
            bar_id=bar_id,
            reversal_threshold_price=threshold,
        )

    @property
    def swing_points(self) -> tuple[SwingPoint, ...]:
        """按确认顺序返回全部已确认摆动点。"""
        return tuple(self._swings)

    @property
    def last_swing(self) -> SwingPoint | None:
        """返回最近确认的摆动点，若无则返回 ``None``。"""
        return self._swings[-1] if self._swings else None

    @property
    def is_initialized(self) -> bool:
        """是否已确认过至少一个摆动点。"""
        return bool(self._swings)

    def update(self, bar: Bar, atr_value: Decimal | None) -> SwingPoint | None:
        """接收一根已完成 K 线。

        参数
        ----
        bar : Bar
            属于本识别器周期与合约的已完成 K 线。
        atr_value : Decimal 或 None
            该 K 线对应的 ATR；ATR 预热期间为 ``None``。

        返回
        ----
        SwingPoint 或 None
            本次确认出的摆动点；没有则为 ``None``。

        异常
        ----
        ValueError
            当 K 线属于其他合约或其他周期时抛出。
        """
        if bar.instrument_id != self._instrument_id:
            raise ValueError(
                f"bar instrument {bar.instrument_id} does not match {self._instrument_id}",
            )
        if bar.timeframe is not self._timeframe:
            raise ValueError(f"bar timeframe {bar.timeframe} does not match {self._timeframe}")

        if atr_value is None or atr_value <= 0:
            return None

        if self._direction is ZigZagDirection.SEEK_HIGH:
            return self._update_seeking_high(bar, atr_value)
        return self._update_seeking_low(bar, atr_value)

    def _update_seeking_high(self, bar: Bar, atr_value: Decimal) -> SwingPoint | None:
        candidate = self._candidate_price
        if candidate is None or bar.high > candidate:
            self._set_candidate(bar, atr_value, bar.high)
            candidate = bar.high
            snapshot = atr_value
        else:
            snapshot = self._candidate_atr
            if snapshot is None:
                # 不可达：候选价与 ATR 总是成对写入。
                return None

        trigger = candidate - self._config.reversal_atr_multiple * snapshot
        if bar.close > trigger:
            return None

        point = self._confirm(bar, SwingDirection.HIGH)
        self._direction = ZigZagDirection.SEEK_LOW
        return point

    def _update_seeking_low(self, bar: Bar, atr_value: Decimal) -> SwingPoint | None:
        candidate = self._candidate_price
        if candidate is None or bar.low < candidate:
            self._set_candidate(bar, atr_value, bar.low)
            candidate = bar.low
            snapshot = atr_value
        else:
            snapshot = self._candidate_atr
            if snapshot is None:
                # 不可达：候选价与 ATR 总是成对写入。
                return None

        trigger = candidate + self._config.reversal_atr_multiple * snapshot
        if bar.close < trigger:
            return None

        point = self._confirm(bar, SwingDirection.LOW)
        self._direction = ZigZagDirection.SEEK_HIGH
        return point

    def _set_candidate(self, bar: Bar, atr_value: Decimal, price: Decimal) -> None:
        """冻结候选极值及其 ATR（规格第 4.2 节第 3 步）。

        ``occurred_at`` 取来源 Bar 的 open_time：蜡烛图、人工标注与结构锚点
        都以该时刻作为时间键；原始 OHLC 无法还原 Bar 内极值的精确时刻，若取
        close_time 会让标记整体后移一根 Bar（规格第 4.3 节仅要求
        ``confirmed_at >= occurred_at``）。
        """
        self._candidate_price = price
        self._candidate_atr = atr_value
        self._candidate_occurred_ns = bar.ts_open_ns
        self._candidate_bar_id = bar.bar_id

    def _confirm(self, bar: Bar, direction: SwingDirection) -> SwingPoint:
        """产出一个摆动点，随后清空候选以切换到下一方向。"""
        price = self._candidate_price
        atr_snapshot = self._candidate_atr
        occurred_ns = self._candidate_occurred_ns
        source_bar_id = self._candidate_bar_id

        if price is None or atr_snapshot is None or occurred_ns is None or source_bar_id is None:
            raise RuntimeError("confirm called without a candidate extreme")

        point_id = (
            f"{self._instrument_id}-{self._timeframe.value}-{direction.value}-{self._sequence}"
        )
        point = SwingPoint(
            point_id=point_id,
            instrument_id=self._instrument_id,
            timeframe=self._timeframe,
            direction=direction,
            price=price,
            occurred_at_ns=occurred_ns,
            confirmed_at_ns=bar.ts_close_ns,
            atr_snapshot=atr_snapshot,
            source_bar_id=source_bar_id,
            sequence=self._sequence,
        )
        self._sequence += 1
        self._swings.append(point)

        self._candidate_price = None
        self._candidate_atr = None
        self._candidate_occurred_ns = None
        self._candidate_bar_id = None
        return point
