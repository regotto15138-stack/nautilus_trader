"""第三梯队数据契约：Setup / Signal / 执行 / 风险（只定义，不判定）。"""

from __future__ import annotations

from pa_trend.domain.lifecycle.models import (
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

__all__ = [
    "ExecutionRecord",
    "FillRecord",
    "OrderState",
    "PositionRiskView",
    "PositionState",
    "RiskStatus",
    "Setup",
    "SetupStatus",
    "SetupTimeframe",
    "Signal",
    "SignalStatus",
    "SignalType",
    "StateTransition",
    "StateTransitionRecord",
    "StopCandidate",
    "StopUpdateRecord",
    "fixed_stop_price",
    "initial_stop",
    "risk_budget_breached",
]
