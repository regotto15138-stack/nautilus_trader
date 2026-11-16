"""多头 N 结构识别与生命周期（规格第 5 节）。"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum

from pa_trend.domain.models.bar import Bar
from pa_trend.domain.models.swing import SwingDirection, SwingPoint
from pa_trend.domain.models.timeframe import Timeframe

# 回撤分档边界（规格第 5.2 节）。分档左闭右开，最后一档包含 1.0。
_SHALLOW_EDGE = Decimal("0.382")
_NORMAL_EDGE = Decimal("0.618")
_DEEP_EDGE = Decimal("1.0")


class NStructureStatus(StrEnum):
    """生命周期状态（规格第 5.5 节）。"""

    CREATED = "CREATED"
    CONFIRMED = "CONFIRMED"
    ACTIVE = "ACTIVE"
    INVALIDATED = "INVALIDATED"
    EXPIRED = "EXPIRED"


class RetracementClass(StrEnum):
    """回撤深度分类（规格第 5.2 节）。"""

    HIGH_CONSOLIDATION = "HIGH_CONSOLIDATION"
    SHALLOW = "SHALLOW"
    NORMAL = "NORMAL"
    DEEP = "DEEP"
    BREAK_CANDIDATE = "BREAK_CANDIDATE"


def classify_retracement(ratio: Decimal) -> RetracementClass:
    """对回撤比例分类。

    参数
    ----
    ratio : Decimal
        ``(H1 - L2) / (H1 - L1)``。

    返回
    ----
    RetracementClass
        该比例落入的分档。
    """
    if ratio < 0:
        return RetracementClass.HIGH_CONSOLIDATION
    if ratio < _SHALLOW_EDGE:
        return RetracementClass.SHALLOW
    if ratio < _NORMAL_EDGE:
        return RetracementClass.NORMAL
    if ratio < _DEEP_EDGE:
        return RetracementClass.DEEP
    return RetracementClass.BREAK_CANDIDATE


@dataclass(slots=True)
class NStructure:
    """一个已确认的多头 N 结构 ``L1 -> H1 -> L2 -> H2``。

    该结构是带生命周期的实体：状态只会向前推进，永不回退（规格第 5.5 节与
    第 7.8 节）。

    属性
    ----
    n_structure_id : str
        由四个摆动点序号推导出的确定性标识。
    instrument_id : str
        结构所属合约。
    timeframe : Timeframe
        摆动点被识别时的周期。
    l1, h1, l2, h2 : SwingPoint
        按时间顺序排列的四个已确认、方向交替的摆动点。
    retracement_ratio : Decimal
        ``(H1 - L2) / (H1 - L1)``。
    retracement_class : RetracementClass
        ``retracement_ratio`` 所属分档。
    created_at_ns : int
        模式中第一个摆动点被确认的时刻。
    confirmed_at_ns : int
        第 ``H2`` 个点被确认的时刻。
    status : NStructureStatus
        当前生命周期状态。
    activated_at_ns : int 或 None
        结构被激活的时刻。
    invalidated_at_ns : int 或 None
        结构失效的时刻。
    """

    n_structure_id: str
    instrument_id: str
    timeframe: Timeframe
    l1: SwingPoint
    h1: SwingPoint
    l2: SwingPoint
    h2: SwingPoint
    retracement_ratio: Decimal
    retracement_class: RetracementClass
    created_at_ns: int
    confirmed_at_ns: int
    status: NStructureStatus = NStructureStatus.CONFIRMED
    activated_at_ns: int | None = None
    invalidated_at_ns: int | None = None
    triggered_signal: bool = field(default=False)

    def activate(self, activated_at_ns: int) -> None:
        """把已确认结构转为 ``ACTIVE``。

        参数
        ----
        activated_at_ns : int
            激活时刻。
        """
        if self.status is not NStructureStatus.CONFIRMED:
            return
        self.status = NStructureStatus.ACTIVE
        self.activated_at_ns = activated_at_ns

    def invalidate(self, invalidated_at_ns: int) -> None:
        """把结构转为 ``INVALIDATED``；已破位的结构不会复活。

        参数
        ----
        invalidated_at_ns : int
            失效时刻。
        """
        if self.status in {NStructureStatus.INVALIDATED, NStructureStatus.EXPIRED}:
            return
        self.status = NStructureStatus.INVALIDATED
        self.invalidated_at_ns = invalidated_at_ns

    @property
    def is_tradeable(self) -> bool:
        """该结构是否仍可能产生入场信号。"""
        return self.status is NStructureStatus.ACTIVE and not self.triggered_signal

    @property
    def reference_price(self) -> Decimal:
        """返回突破参考价，即 ``H2``（规格第 9.2 节）。"""
        return self.h2.price

    @property
    def structural_anchor(self) -> Decimal:
        """返回初始结构止损锚点，即 ``L2``（规格第 10.3 节）。"""
        return self.l2.price


class NStructureDetector:
    """从已确认摆动点流中构建多头 N 结构。

    每当一根摆动高点确认、且末尾四个摆动点构成 ``LOW, HIGH, LOW, HIGH``、
    时间严格递增、``L2 > L1`` 且 ``H2 > H1`` 时，产出一个新结构（规格第 5.3
    节）。``L2`` 允许低于、等于或高于 ``H1``：若强制要求 ``H1 < L2``，就会
    拒绝掉正常的回调结构（规格第 5.1 节）。
    """

    def __init__(
        self,
        *,
        instrument_id: str,
        timeframe: Timeframe,
        break_buffer_atr: Decimal = Decimal("0.1"),
        trading_enabled: bool = True,
        invalidation_enabled: bool = False,
    ) -> None:
        """初始化识别器。

        参数
        ----
        instrument_id : str
            结构所属合约。
        timeframe : Timeframe
            被分析的周期。
        break_buffer_atr : Decimal
            基于收盘价的失效缓冲（规格第 5.4 节）。
        trading_enabled : bool
            该周期的 N 结构是否具备**交易性**失效判定。规格第 5.5 节规定
            ``n_structure_break_buffer_atr`` 仅适用于 15M 多头 N 结构；4H/1H
            等周期的 N 结构只能作为 ``RESEARCH_ONLY`` 研究对象，不得与 15M
            共用该交易参数，也不得参与交易性结构失效判定。
        invalidation_enabled : bool
            是否产出失效判定。规格第 5.5 节给出了失效公式
            ``Close_TF < L2 - buffer * ATR_TF``，但**没有定义使用哪一个 ATR
            时点**（结构确认时的 ``L2`` 冻结 ATR、当根 Bar 的 ATR，还是结构
            失效候选时的 ATR）。SACW 27.6 要求把该歧义标记为
            ``SPEC_AMBIGUITY`` 并保持阻塞，因此缺省为 ``False``：接口
            （:meth:`structural_break_price`）存在，但不产出失效价、也不改变
            结构状态。裁定后把该开关置为 ``True`` 即可启用既有实现。
        """
        self._instrument_id = instrument_id
        self._timeframe = timeframe
        self._break_buffer_atr = break_buffer_atr
        self._trading_enabled = trading_enabled
        self._invalidation_enabled = invalidation_enabled
        # 只有末尾四个点参与判据，因此窗口长度固定、内存有界。
        self._points: deque[SwingPoint] = deque(maxlen=4)
        self._structures: dict[str, NStructure] = {}

    @property
    def structures(self) -> tuple[NStructure, ...]:
        """按创建顺序返回已识别的全部结构。"""
        return tuple(self._structures.values())

    @property
    def active_structures(self) -> tuple[NStructure, ...]:
        """返回仍可能产生入场信号的结构。

        非交易周期（``trading_enabled = False``）的研究结构不在此列。
        """
        if not self._trading_enabled:
            return ()
        return tuple(item for item in self._structures.values() if item.is_tradeable)

    @property
    def trading_enabled(self) -> bool:
        """该周期的 N 结构是否具备交易性失效判定。"""
        return self._trading_enabled

    @property
    def invalidation_status(self) -> str:
        """返回失效判定状态。

        规格未定义失效判定使用的 ATR 时点，因此交易周期返回
        ``SPEC_AMBIGUITY``；非交易周期返回 ``RESEARCH_ONLY``。只有显式启用
        失效判定（策略负责人裁定后）才返回 ``ENABLED``。
        """
        if not self._trading_enabled:
            return "RESEARCH_ONLY"
        if not self._invalidation_enabled:
            return "SPEC_AMBIGUITY"
        return "ENABLED"

    @property
    def invalidation_enabled(self) -> bool:
        """是否启用失效判定。"""
        return self._invalidation_enabled and self._trading_enabled

    def structural_break_price(self, atr_value: Decimal | None) -> Decimal | None:
        """返回结构失效价 ``L2 - n_structure_break_buffer_atr * ATR``。

        该接口只做公式计算：调用方必须自己决定传入哪一个 ATR 快照，因为
        **ATR 时点正是规格尚未裁定的歧义点**（SACW 27.6）。因此在歧义解除
        之前，生产路径不调用本方法，UI 与事件载荷只显示 ``SPEC_AMBIGUITY``。
        """
        if atr_value is None or atr_value <= 0:
            return None
        if not self._trading_enabled:
            return None
        return self._latest_break_price(atr_value)

    def _latest_break_price(self, atr_value: Decimal) -> Decimal | None:
        # 目前只对最新确认的结构给出参考价；N 结构失效判定尚未解禁，
        # 这里保持最小接口，不批量产出。
        if not self._structures:
            return None
        latest = next(reversed(self._structures.values()))
        return latest.l2.price - self._break_buffer_atr * atr_value

    @property
    def scope(self) -> str:
        """返回该周期结构的用途标注：``TRADING`` 或 ``RESEARCH_ONLY``。"""
        return "TRADING" if self._trading_enabled else "RESEARCH_ONLY"

    def on_swing_point(self, point: SwingPoint) -> NStructure | None:
        """接收一个新确认的摆动点。

        参数
        ----
        point : SwingPoint
            刚确认的摆动点。

        返回
        ----
        NStructure 或 None
            末尾窗口满足条件时返回新结构。
        """
        if point.instrument_id != self._instrument_id:
            raise ValueError(
                f"swing point instrument {point.instrument_id} does not match "
                f"{self._instrument_id}",
            )
        if point.timeframe is not self._timeframe:
            raise ValueError(
                f"swing point timeframe {point.timeframe} does not match {self._timeframe}",
            )

        self._points.append(point)
        if len(self._points) < 4:
            return None

        window = list(self._points)
        structure = self._build(window)
        if structure is None:
            return None

        if structure.n_structure_id in self._structures:
            return None
        self._structures[structure.n_structure_id] = structure
        return structure

    def on_bar(self, bar: Bar, atr_value: Decimal | None) -> tuple[NStructure, ...]:
        """对所有未关闭的结构应用基于收盘价的失效判断。

        只有已完成 K 线的**收盘价**低于 ``L2 - 0.1 * ATR_W`` 才使结构失效；仅有
        影线跌破不算（规格第 5.4 节）。

        参数
        ----
        bar : Bar
            属于本识别器周期的已完成 K 线。
        atr_value : Decimal 或 None
            该 K 线的 ATR；预热期间为 ``None``。

        返回
        ----
        tuple of NStructure
            被本次 K 线判定失效的结构。
        """
        # 规格第 5.5 节：交易性失效判定仅适用于 15M，其他周期只做研究识别。
        if not self._trading_enabled:
            return ()
        # 失效判定使用的 ATR 时点未定义（SACW 27.6 / UI-020），默认不产出失效。
        if not self._invalidation_enabled:
            return ()
        if atr_value is None or atr_value <= 0:
            return ()

        invalidated: list[NStructure] = []
        for structure in self._structures.values():
            if structure.status not in {
                NStructureStatus.CONFIRMED,
                NStructureStatus.ACTIVE,
            }:
                continue
            buffer = self._break_buffer_atr * atr_value
            if bar.close < structure.l2.price - buffer:
                structure.invalidate(bar.ts_close_ns)
                invalidated.append(structure)
        return tuple(invalidated)

    def _build(self, window: list[SwingPoint]) -> NStructure | None:
        l1, h1, l2, h2 = window
        expected = (
            SwingDirection.LOW,
            SwingDirection.HIGH,
            SwingDirection.LOW,
            SwingDirection.HIGH,
        )
        if tuple(point.direction for point in window) != expected:
            return None
        if not (l1.occurred_at_ns < h1.occurred_at_ns < l2.occurred_at_ns < h2.occurred_at_ns):
            return None
        if l2.price <= l1.price:
            return None
        if h2.price <= h1.price:
            return None

        impulse = h1.price - l1.price
        if impulse <= 0:
            return None
        ratio = (h1.price - l2.price) / impulse

        return NStructure(
            n_structure_id=(
                f"N-{self._instrument_id}-{self._timeframe.value}-"
                f"{l1.sequence}-{h1.sequence}-{l2.sequence}-{h2.sequence}"
            ),
            instrument_id=self._instrument_id,
            timeframe=self._timeframe,
            l1=l1,
            h1=h1,
            l2=l2,
            h2=h2,
            retracement_ratio=ratio,
            retracement_class=classify_retracement(ratio),
            created_at_ns=l1.confirmed_at_ns,
            confirmed_at_ns=h2.confirmed_at_ns,
        )
