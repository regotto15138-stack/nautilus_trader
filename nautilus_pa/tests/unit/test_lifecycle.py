"""第三梯队数据契约测试（只验证结构与公式，不验证业务判定）。"""

from __future__ import annotations

from decimal import Decimal

import pytest

from pa_trend.domain.lifecycle import (
    ExecutionRecord,
    FillRecord,
    OrderState,
    PositionRiskView,
    PositionState,
    RiskStatus,
    Setup,
    SetupStatus,
    SetupTimeframe,
    Signal,
    SignalStatus,
    SignalType,
    StateTransition,
    StateTransitionRecord,
    StopCandidate,
    StopUpdateRecord,
    fixed_stop_price,
    initial_stop,
    risk_budget_breached,
)


def _signal(**overrides: object) -> Signal:
    base = {
        "signal_id": "sig-1",
        "status": SignalStatus.ACTIVE,
        "signal_type": SignalType.BREAKOUT_CONTINUATION,
        "setup_4h_id": "setup-4h",
        "setup_1h_id": "setup-1h",
        "n_structure_id": "N-1",
        "observation_zone_id": "Z-1",
        "observation_zone_version": 1,
        "observation_lower": Decimal("2990"),
        "observation_upper": Decimal("3010"),
        "pullback_start_swing_id": None,
        "pullback_start_atr_15m": None,
        "pullback_low_swing_id": None,
        "trigger_swing_id": None,
        "trigger_reference_price": Decimal("3020"),
        "trigger_swing_atr_15m": None,
        "higher_low_swing_id": None,
        "partially_filled": False,
        "signal_decision_atr_15m": Decimal("5"),
        "execution_reference_level": Decimal("3020"),
        "execution_reference_atr_15m": Decimal("5"),
        "signal_reference_close": Decimal("3015"),
        "signal_reference_close_ns": 1_700_000_000_000_000_000,
        "structural_stop_anchor_swing_id": "sw-1",
        "structural_stop_anchor_price": Decimal("2980"),
        "created_at_ns": 1_700_000_000_000_000_000,
        "expires_at_ns": 1_700_000_900_000_000_000,
    }
    base.update(overrides)
    return Signal(**base)


def test_breakout_signal_requires_null_pullback_fields() -> None:
    """BREAKOUT_CONTINUATION 的回撤字段必须为空（规格 20.2）。"""
    signal = _signal()
    assert signal.pullback_start_swing_id is None

    with pytest.raises(ValueError):
        _signal(trigger_swing_id="sw-x")


def test_pullback_signal_requires_trigger_and_atr_snapshot() -> None:
    """PULLBACK_CONTINUATION 必须带触发摆动与 ATR 快照。"""
    with pytest.raises(ValueError):
        _signal(signal_type=SignalType.PULLBACK_CONTINUATION)

    signal = _signal(
        signal_type=SignalType.PULLBACK_CONTINUATION,
        pullback_start_swing_id="sw-start",
        pullback_start_atr_15m=Decimal("4.5"),
        pullback_low_swing_id="sw-low",
        trigger_swing_id="sw-trigger",
        trigger_swing_atr_15m=Decimal("4.8"),
        higher_low_swing_id="sw-hl",
        trigger_reference_price=Decimal("3010"),
    )
    assert signal.trigger_swing_id == "sw-trigger"


def test_setup_rejects_inverted_observation_zone() -> None:
    """观察区下沿不得高于上沿。"""
    with pytest.raises(ValueError):
        Setup(
            setup_id="s1",
            parent_setup_id=None,
            status=SetupStatus.ACTIVE,
            direction="LONG",
            timeframe=SetupTimeframe.HOUR4,
            structure_id="N-1",
            protected_swing_id="sw-1",
            pullback_origin_swing_id=None,
            observation_zone_id="Z-1",
            observation_zone_version=1,
            observation_lower=Decimal("3010"),
            observation_upper=Decimal("2990"),
            created_at_ns=1,
            expires_at_ns=2,
            config_version="1.4.8",
        )


def test_initial_stop_takes_the_higher_price() -> None:
    """初始有效止损 = max(固定止损, 结构止损)。"""
    assert initial_stop(Decimal("2950"), Decimal("2980")) == Decimal("2980")
    assert initial_stop(Decimal("2990"), Decimal("2980")) == Decimal("2990")


def test_fixed_stop_pct_is_validated() -> None:
    """固定止损百分比必须在 (0, 1)。"""
    assert fixed_stop_price(Decimal("3000"), Decimal("0.05")) == Decimal("2850.00")
    with pytest.raises(ValueError):
        fixed_stop_price(Decimal("3000"), Decimal("1.2"))


def test_stop_update_must_not_move_against_position() -> None:
    """移动止损不得下移。"""
    with pytest.raises(ValueError):
        StopUpdateRecord(
            stop_update_id="su-1",
            position_id="pos-1",
            previous_stop_price=Decimal("2980"),
            new_stop_price=Decimal("2970"),
            stop_update_atr_15m=Decimal("5"),
            source_swing_id=None,
            at_ns=1,
            reason_code="TRAILING",
        )


def test_stop_candidate_requires_positive_atr() -> None:
    """止损候选的 ATR 快照必须为正。"""
    with pytest.raises(ValueError):
        StopCandidate(
            stop_candidate_id="sc-1",
            signal_id="sig-1",
            price=Decimal("2980"),
            computed_at_ns=1,
            atr_snapshot=Decimal(0),
            source="STRUCTURAL",
        )


def test_execution_record_aggregates_fills() -> None:
    """多笔成交的均价与数量由 FillRecord 聚合。"""
    record = ExecutionRecord(
        execution_id="ex-1",
        signal_id="sig-1",
        breakout_bar_id="bar-1",
        signal_after_swing_low_id=None,
        signal_after_swing_high_id=None,
        fills=[
            FillRecord(
                fill_id="f1",
                order_id="o1",
                signal_id="sig-1",
                quantity=Decimal("1"),
                price=Decimal("3010"),
                fee=Decimal("0.3"),
                at_ns=1,
                entry_reference_price=Decimal("3005"),
            ),
            FillRecord(
                fill_id="f2",
                order_id="o1",
                signal_id="sig-1",
                quantity=Decimal("3"),
                price=Decimal("3020"),
                fee=Decimal("0.9"),
                at_ns=2,
                entry_reference_price=Decimal("3005"),
            ),
        ],
        state=OrderState.PARTIALLY_FILLED,
    )
    assert record.filled_quantity == Decimal("4")
    assert record.average_price == Decimal("3017.5")
    assert record.fills[0].deviation_atr == Decimal("5")


def test_position_risk_requires_stop_and_neverzero() -> None:
    """缺少止损时不得按零风险处理（PB-51）。"""
    view = PositionRiskView(
        position_id="pos-1",
        quantity=Decimal("2"),
        actual_average_entry_price=Decimal("3000"),
        current_stop_price=None,
        risk_budget=Decimal("100"),
    )
    assert view.current_risk_per_unit is None

    with_stop = PositionRiskView(
        position_id="pos-1",
        quantity=Decimal("2"),
        actual_average_entry_price=Decimal("3000"),
        current_stop_price=Decimal("2950"),
        risk_budget=Decimal("100"),
    )
    assert with_stop.current_risk_per_unit == Decimal("50")
    # 风险 50 × 2 = 100，恰好等于预算时不算突破；超过才算。
    assert risk_budget_breached(Decimal("50"), Decimal("2"), Decimal("100")) is False
    assert risk_budget_breached(Decimal("50"), Decimal("3"), Decimal("100")) is True


def test_state_transition_record_is_typed() -> None:
    """状态迁移记录使用统一枚举，便于负向断言。"""
    record = StateTransitionRecord(
        entity_type="ZONE",
        entity_id="Z-1",
        timeframe="4H",
        from_state="ACTIVE",
        to_state="BROKEN",
        at_ns=1,
        reason_code=StateTransition.INVALIDATED.value,
    )
    assert record.to_state == "BROKEN"
    assert PositionState.OPEN.value == "OPEN"
    assert RiskStatus.ESCALATED.value == "ESCALATED"
