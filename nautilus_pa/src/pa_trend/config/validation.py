"""启动门禁（规格 V1.4.8 第 18.3 节）。

门禁绝不把 ``null`` 当成零、当成无上限，也不会静默跳过约束。拒绝时抛出
:class:`ConfigurationError` 并列出全部缺失项与非法值。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum

from pa_trend.config.models import PaTrendConfig
from pa_trend.domain.errors import ConfigurationError


class Stage(StrEnum):
    """评估门禁时对应的开发阶段。"""

    #: 结构研究：只做多周期识别与结构统计，不提交任何订单。
    RESEARCH_STRUCTURE = "RESEARCH_STRUCTURE"
    #: 完整策略的历史回测。
    RESEARCH_BACKTEST = "RESEARCH_BACKTEST"
    #: OKX 模拟盘。
    PAPER = "PAPER"
    #: 控制真实资金的实盘交易。
    LIVE = "LIVE"


@dataclass(frozen=True, slots=True)
class StartupReport:
    """启动门禁的评估结果。"""

    stage: Stage
    checked: tuple[str, ...]
    skipped: tuple[str, ...] = ()
    reasons: tuple[str, ...] = field(default_factory=tuple)

    @property
    def accepted(self) -> bool:
        """门禁是否接受该配置。"""
        return True


_STRUCTURAL_SECTIONS = (
    "market",
    "indicators",
    "zigzag",
    "protected",
    "n_structure",
    "zone",
    "pullback",
    "range",
    "research",
)
_EXECUTION_SECTIONS = ("risk", "execution")


def _require(condition: bool, message: str, failures: list[str]) -> None:
    if not condition:
        failures.append(message)


def _require_non_negative(value: Decimal, field_name: str, failures: list[str]) -> None:
    _require(value >= 0, f"{field_name} must be >= 0", failures)


def validate_startup(config: PaTrendConfig, stage: Stage) -> StartupReport:
    """执行启动门禁。"""
    failures: list[str] = []

    # 结构性参数在每个阶段都必须合法（FIXED 与 RESEARCH 的合法性范围）。
    _require_non_negative(
        config.zigzag.reversal_atr_multiple,
        "zigzag.reversal_atr_multiple",
        failures,
    )
    _require_non_negative(
        config.protected.break_buffer_atr,
        "protected.break_buffer_atr",
        failures,
    )
    _require_non_negative(
        config.n_structure.break_buffer_atr,
        "n_structure.break_buffer_atr",
        failures,
    )
    _require_non_negative(config.pullback.min_atr_1d, "pullback.min_atr_1d", failures)
    _require_non_negative(config.pullback.min_atr_4h, "pullback.min_atr_4h", failures)
    _require_non_negative(config.pullback.min_atr_1h, "pullback.min_atr_1h", failures)
    _require_non_negative(config.pullback.min_atr_15m, "pullback.min_atr_15m", failures)
    _require_non_negative(
        config.range.boundary_tolerance_atr,
        "range.boundary_tolerance_atr",
        failures,
    )
    _require(
        0 <= config.research.session_offset_hours <= 14,
        "research.session_offset_hours must be within [0, 14]",
        failures,
    )

    # Zone 参数（第 6 章、第 19 章）。
    _require(
        config.zone.min_anchor_count == 2,
        "zone.min_anchor_count is FIXED at 2 (spec section 6.5)",
        failures,
    )
    for name in (
        "merge_distance_atr",
        "max_cluster_width_atr",
        "half_width_atr",
        "test_tolerance_atr",
        "break_buffer_atr",
    ):
        value = getattr(config.zone, name)
        _require(value >= 0, f"zone.{name} must be >= 0", failures)
    _require(
        config.zone.min_half_width_ticks >= 0,
        "zone.min_half_width_ticks must be >= 0",
        failures,
    )
    _require(config.zone.max_age_weeks > 0, "zone.max_age_weeks must be > 0", failures)

    # Zone 半宽下限项依赖 tick size（第 6.4 节）；缺失时无法计算几何。
    tick_size = config.market.metadata.tick_size
    _require(
        tick_size is not None and tick_size > 0,
        "market.metadata.tick_size is required for Zone half-width and must be > 0",
        failures,
    )

    if stage is Stage.RESEARCH_STRUCTURE:
        if failures:
            raise ConfigurationError(
                "startup REJECTED for stage RESEARCH_STRUCTURE:\n- " + "\n- ".join(failures),
            )
        return StartupReport(
            stage=stage,
            checked=_STRUCTURAL_SECTIONS,
            skipped=_EXECUTION_SECTIONS,
            reasons=(
                "结构研究阶段：只做多周期识别与结构统计，不产生 Setup/Signal，"
                "也不提交订单，因此风险与成本门禁不适用（规格第 10 至 17 章）。",
            ),
        )

    # 完整门禁：第 18.1 节 REQUIRED 项与第 18.3 节拒绝条件。
    if config.risk.risk_per_trade_pct is None:
        failures.append("risk.risk_per_trade_pct must not be null")
    if config.risk.max_notional_exposure is None:
        failures.append("risk.max_notional_exposure must not be null")
    if config.risk.max_margin_usage_pct is None:
        failures.append("risk.max_margin_usage_pct must not be null")
    if config.risk.leverage is None:
        failures.append("risk.leverage must not be null")
    if config.execution.maker_fee_rate is None:
        failures.append("execution.maker_fee_rate must not be null")
    if config.execution.taker_fee_rate is None:
        failures.append("execution.taker_fee_rate must not be null")
    if config.execution.cost_model_version is None:
        failures.append("execution.cost_model_version must not be null")
    if config.execution.slippage_model_version is None:
        failures.append("execution.slippage_model_version must not be null")
    if config.execution.instrument_metadata_version is None:
        failures.append("execution.instrument_metadata_version must not be null")
    if config.research.funding_dataset is None:
        failures.append("research.funding_dataset must not be null")

    # 第 18.3 节第 5、6 项：合约元数据缺失即拒绝。
    for field_name in config.market.metadata.missing_fields():
        failures.append(f"market.metadata.{field_name} is required by spec section 18.2")

    # RESEARCH 参数合法性（第 18.1 节）。
    if config.risk.risk_per_trade_pct is not None and config.risk.risk_per_trade_pct <= 0:
        failures.append("risk.risk_per_trade_pct must be > 0")
    if config.risk.max_margin_usage_pct is not None and not (
        0 < config.risk.max_margin_usage_pct <= 1
    ):
        failures.append("risk.max_margin_usage_pct must be within (0, 1]")
    if not (0 < config.risk.fixed_stop_pct < 1):
        failures.append("risk.fixed_stop_pct must be within (0, 1)")
    if config.risk.hard_risk_budget_multiple < 1:
        failures.append("risk.hard_risk_budget_multiple must be >= 1")

    if failures:
        raise ConfigurationError(
            f"startup REJECTED for stage {stage.value}:\n- " + "\n- ".join(failures),
        )

    return StartupReport(
        stage=stage,
        checked=_STRUCTURAL_SECTIONS + _EXECUTION_SECTIONS,
        reasons=("完整门禁已通过（规格第 18.3 节）。",),
    )
