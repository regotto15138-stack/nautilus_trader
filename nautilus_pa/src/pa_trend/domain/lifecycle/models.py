"""第三梯队接口：Setup / Signal / 执行 / 风险的数据模型（只定义，不判定）。

规格 V1.4.8 第 10 至 17 章的业务判定依赖人工黄金样本（P0-E）与尚未裁定的
歧义项。按 SACW 13.2 的实施顺序，本阶段**只固化数据结构、状态枚举与字段
契约**，不实现任何创建条件、触发器或下单逻辑。

本模块中的函数只做纯计算（如初始止损取两者较大值），不读取行情、不写状态。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum


class SetupStatus(StrEnum):
    """Setup 生命周期状态（规格第 10.1 节）。"""

    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    INVALIDATED = "INVALIDATED"


class SetupTimeframe(StrEnum):
    """Setup 所属周期。"""

    HOUR4 = "4H"
    HOUR1 = "1H"


class SignalType(StrEnum):
    """15M 信号类型（规格第 11.1 节）。"""

    BREAKOUT_CONTINUATION = "BREAKOUT_CONTINUATION"
    PULLBACK_CONTINUATION = "PULLBACK_CONTINUATION"


class SignalStatus(StrEnum):
    """Signal 生命周期状态（规格第 11.7 节）。"""

    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    PARTIALLY_EXECUTED = "PARTIALLY_EXECUTED"
    EXECUTED = "EXECUTED"


class OrderState(StrEnum):
    """订单状态（规格第 13.3 节）。"""

    INITIALIZED = "INITIALIZED"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class PositionState(StrEnum):
    """持仓状态（规格第 13.4 节）。"""

    FLAT = "FLAT"
    OPEN = "OPEN"
    PARTIALLY_CLOSED = "PARTIALLY_CLOSED"
    CLOSED = "CLOSED"


class RiskStatus(StrEnum):
    """风险升级状态（规格第 16.2 节）。"""

    NORMAL = "NORMAL"
    ESCALATED = "ESCALATED"
    ACTUAL_RISK_BUDGET_BREACH = "ACTUAL_RISK_BUDGET_BREACH"
    RISK_ANOMALY = "RISK_ANOMALY"


class StateTransition(StrEnum):
    """状态迁移事件的统一标识。

    该枚举用于 SACW 23.2 的 ``expected_state_transitions`` 与
    ``expected_absent_state_transitions`` 结构化断言。
    """

    CREATED = "CREATED"
    ACTIVATED = "ACTIVATED"
    UPDATED = "UPDATED"
    EXPIRED = "EXPIRED"
    INVALIDATED = "INVALIDATED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True, slots=True)
class StateTransitionRecord:
    """一次状态迁移记录（不含判定逻辑，仅承载事实）。"""

    entity_type: str
    entity_id: str
    timeframe: str
    from_state: str | None
    to_state: str
    at_ns: int
    reason_code: str


@dataclass(slots=True)
class Setup:
    """Setup 数据契约（规格第 20.1 节）。

    父子传播规则：``parent_setup_id`` 指向 4H Setup，1H Setup 为其子节点；
    子节点失效不得自动复活父节点，反之亦然（规格第 10.6 至 10.8 节）。
    """

    setup_id: str
    parent_setup_id: str | None
    status: SetupStatus
    direction: str
    timeframe: SetupTimeframe
    structure_id: str
    protected_swing_id: str
    pullback_origin_swing_id: str | None
    observation_zone_id: str
    observation_zone_version: int
    observation_lower: Decimal
    observation_upper: Decimal
    created_at_ns: int
    expires_at_ns: int
    config_version: str

    def __post_init__(self) -> None:
        """校验观察区边界与有效期。"""
        if self.observation_lower > self.observation_upper:
            raise ValueError("observation_lower must not exceed observation_upper")
        if self.expires_at_ns < self.created_at_ns:
            raise ValueError("expires_at_ns must not precede created_at_ns")


@dataclass(slots=True)
class Signal:
    """Signal 数据契约（规格第 20.2 节）。

    字段可空语义由 ``signal_type`` 决定：

    - ``BREAKOUT_CONTINUATION``：回撤相关字段与 ``trigger_swing_id`` 均为空，
      ``trigger_reference_price = H2``；
    - ``PULLBACK_CONTINUATION``：``pullback_start_atr_15m``、``trigger_swing_id``、
      ``higher_low_swing_id`` 必填。
    """

    signal_id: str
    status: SignalStatus
    signal_type: SignalType
    setup_4h_id: str
    setup_1h_id: str
    n_structure_id: str
    observation_zone_id: str
    observation_zone_version: int
    observation_lower: Decimal
    observation_upper: Decimal
    pullback_start_swing_id: str | None
    pullback_start_atr_15m: Decimal | None
    pullback_low_swing_id: str | None
    trigger_swing_id: str | None
    trigger_reference_price: Decimal
    trigger_swing_atr_15m: Decimal | None
    higher_low_swing_id: str | None
    partially_filled: bool
    signal_decision_atr_15m: Decimal
    execution_reference_level: Decimal
    execution_reference_atr_15m: Decimal
    signal_reference_close: Decimal
    signal_reference_close_ns: int
    structural_stop_anchor_swing_id: str
    structural_stop_anchor_price: Decimal
    created_at_ns: int
    expires_at_ns: int
    remaining_order_terminal_reason: str | None = None
    config_version: str = "1.4.8"

    def __post_init__(self) -> None:
        """校验类型相关的必填字段（规格第 20.2 节）。"""
        if self.signal_type is SignalType.PULLBACK_CONTINUATION:
            missing = [
                name
                for name, value in (
                    ("pullback_start_swing_id", self.pullback_start_swing_id),
                    ("pullback_start_atr_15m", self.pullback_start_atr_15m),
                    ("trigger_swing_id", self.trigger_swing_id),
                    ("higher_low_swing_id", self.higher_low_swing_id),
                    ("trigger_swing_atr_15m", self.trigger_swing_atr_15m),
                )
                if value is None
            ]
            if missing:
                raise ValueError(
                    "PULLBACK_CONTINUATION requires: " + ", ".join(missing),
                )
        else:
            illegal = [
                name
                for name, value in (
                    ("pullback_start_swing_id", self.pullback_start_swing_id),
                    ("pullback_start_atr_15m", self.pullback_start_atr_15m),
                    ("pullback_low_swing_id", self.pullback_low_swing_id),
                    ("trigger_swing_id", self.trigger_swing_id),
                    ("trigger_swing_atr_15m", self.trigger_swing_atr_15m),
                    ("higher_low_swing_id", self.higher_low_swing_id),
                )
                if value is not None
            ]
            if illegal:
                raise ValueError(
                    "BREAKOUT_CONTINUATION requires null pullback fields: " + ", ".join(illegal),
                )
        if self.signal_decision_atr_15m <= 0 or self.execution_reference_atr_15m <= 0:
            raise ValueError("signal ATR snapshots must be positive")


@dataclass(frozen=True, slots=True)
class FillRecord:
    """单笔成交记录（规格第 13.5 节）。"""

    fill_id: str
    order_id: str
    signal_id: str
    quantity: Decimal
    price: Decimal
    fee: Decimal
    at_ns: int
    entry_reference_price: Decimal

    @property
    def deviation_atr(self) -> Decimal | None:
        """相对参考价的不利偏差（绝对值，需配合 ATR 才能换算倍数）。"""
        return abs(self.price - self.entry_reference_price)


@dataclass(slots=True)
class ExecutionRecord:
    """一次执行确认（3M 层）的事实记录，不含判定逻辑。"""

    execution_id: str
    signal_id: str
    breakout_bar_id: str | None
    signal_after_swing_low_id: str | None
    signal_after_swing_high_id: str | None
    fills: list[FillRecord] = field(default_factory=list)
    state: OrderState = OrderState.INITIALIZED

    @property
    def filled_quantity(self) -> Decimal:
        """已成交数量合计。"""
        return sum((fill.quantity for fill in self.fills), Decimal(0))

    @property
    def average_price(self) -> Decimal | None:
        """成交均价；无成交时返回 ``None``。"""
        quantity = self.filled_quantity
        if quantity == 0:
            return None
        total = sum((fill.price * fill.quantity for fill in self.fills), Decimal(0))
        return total / quantity


@dataclass(frozen=True, slots=True)
class StopCandidate:
    """一个尚未生效的止损候选（规格第 15.1 节）。"""

    stop_candidate_id: str
    signal_id: str
    price: Decimal
    computed_at_ns: int
    atr_snapshot: Decimal
    source: str

    def __post_init__(self) -> None:
        """校验 ATR 快照。"""
        if self.atr_snapshot <= 0:
            raise ValueError("stop candidate atr_snapshot must be positive")


@dataclass(slots=True)
class StopUpdateRecord:
    """一次止损更新记录（规格第 16.1、20.3 节）。"""

    stop_update_id: str
    position_id: str
    previous_stop_price: Decimal | None
    new_stop_price: Decimal
    stop_update_atr_15m: Decimal
    source_swing_id: str | None
    at_ns: int
    reason_code: str

    def __post_init__(self) -> None:
        """移动止损只能向有利方向推进（规格第 16.1 节）。"""
        if self.previous_stop_price is not None and self.new_stop_price < self.previous_stop_price:
            raise ValueError("stop must not move against the position")
        if self.stop_update_atr_15m <= 0:
            raise ValueError("stop_update_atr_15m must be positive")


@dataclass(frozen=True, slots=True)
class PositionRiskView:
    """仓位风险视图（规格第 17 章）。"""

    position_id: str
    quantity: Decimal
    actual_average_entry_price: Decimal
    current_stop_price: Decimal | None
    risk_budget: Decimal

    @property
    def current_risk_per_unit(self) -> Decimal | None:
        """每单位当前风险：``CurrentExecutablePrice - CurrentStopPrice``。

        规格第 17 章要求使用可执行价而非理论价；缺少止损或可执行价时返回
        ``None``，不得按零风险处理（PB-51）。
        """
        if self.current_stop_price is None:
            return None
        return self.actual_average_entry_price - self.current_stop_price


def initial_stop(fixed_stop_price: Decimal, structural_stop_price: Decimal) -> Decimal:
    """初始有效止损 = ``max(P_fixed, P_structural)``（规格第 15.1 节 D）。

    多头方向下，两者都可作为止损价，取较高者以承受更小风险。
    """
    return max(fixed_stop_price, structural_stop_price)


def fixed_stop_price(entry_price: Decimal, fixed_stop_pct: Decimal) -> Decimal:
    """按百分比计算的固定止损价（多头）。"""
    if not (Decimal(0) < fixed_stop_pct < Decimal(1)):
        raise ValueError("fixed_stop_pct must be within (0, 1)")
    return entry_price * (Decimal(1) - fixed_stop_pct)


def risk_budget_breached(risk_per_unit: Decimal, quantity: Decimal, budget: Decimal) -> bool:
    """实际风险是否超过预算（规格第 16.2 节）。"""
    return risk_per_unit * quantity > budget
