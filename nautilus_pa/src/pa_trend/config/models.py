"""对应规格 V1.4.8 第 18、19 章的类型化配置对象。"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from pa_trend.config.timeframes import TimeframeSettings
from pa_trend.domain.errors import ConfigurationError


def to_decimal(value: object, *, field_name: str) -> Decimal | None:
    """把 YAML 标量转成精确的 Decimal；``None`` 原样保留。"""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise ConfigurationError(f"{field_name} must be numeric, was a boolean")
    if isinstance(value, int | float | str):
        return Decimal(str(value))
    raise ConfigurationError(f"{field_name} must be numeric, was {type(value).__name__}")


def require_decimal(value: object, *, field_name: str) -> Decimal:
    """转换必填标量，遇 ``None`` 直接拒绝。"""
    result = to_decimal(value, field_name=field_name)
    if result is None:
        raise ConfigurationError(f"{field_name} is required and must not be null")
    return result


def require_int(value: object, *, field_name: str) -> int:
    """转换必填整数，拒绝非整数取值（不静默截断）。"""
    result = require_decimal(value, field_name=field_name)
    if result != result.to_integral_value():
        raise ConfigurationError(f"{field_name} must be a whole number, was {result}")
    return int(result)


class TradingDirection(StrEnum):
    """交易方向策略。"""

    LONG_ONLY = "LONG_ONLY"


class IndicatorSettings:
    """ATR14 与 SMA22（规格第 4.1 节，FIXED）。

    规格 V1.4.8 第 4.1 节只定义 ATR（Wilder，周期 14）、SMA（周期 22）与
    ZigZag。``ATR_MA22`` 在该版规格中**不存在**，因此这里不提供任何周期
    配置项，引擎也不会计算该指标（SACW V1.1.2 第 17.1 节：UI 显示
    ``N/A / SPEC_AMBIGUITY``，后端不得自行计算作为替代）。
    """

    def __init__(self, raw: dict[str, object]) -> None:
        """从 ``indicators`` 映射构建。"""
        self.ma_type = str(raw.get("ma_type", "SMA"))
        self.ma_period = require_int(raw.get("ma_period"), field_name="ma_period")
        self.atr_type = str(raw.get("atr_type", "WILDER"))
        self.atr_period = require_int(raw.get("atr_period"), field_name="atr_period")
        if "atr_ma_period" in raw:
            raise ConfigurationError(
                "indicators.atr_ma_period is not defined by spec V1.4.8 section 4.1; "
                "ATR_MA22 is SPEC_AMBIGUITY and must not be configured or computed",
            )
        if self.ma_type != "SMA":
            raise ConfigurationError(f"ma_type must be SMA, was {self.ma_type}")
        if self.atr_type != "WILDER":
            raise ConfigurationError(f"atr_type must be WILDER, was {self.atr_type}")
        if self.ma_period != 22:
            raise ConfigurationError(f"SMA period is FIXED at 22, was {self.ma_period}")
        if self.atr_period != 14:
            raise ConfigurationError(f"ATR period is FIXED at 14, was {self.atr_period}")


class ZigZagSettings:
    """ZigZag 反转参数（RESEARCH，初始 k=2.0）。"""

    def __init__(self, raw: dict[str, object]) -> None:
        """从 ``zigzag`` 映射构建。"""
        self.method = str(raw.get("method", "ATR_REVERSAL"))
        self.reversal_atr_multiple = require_decimal(
            raw.get("reversal_atr_multiple"),
            field_name="zigzag.reversal_atr_multiple",
        )
        self.confirmation_price = str(raw.get("confirmation_price", "CLOSE"))
        if self.method != "ATR_REVERSAL":
            raise ConfigurationError(f"zigzag.method must be ATR_REVERSAL, was {self.method}")
        if self.confirmation_price != "CLOSE":
            raise ConfigurationError(
                f"zigzag.confirmation_price must be CLOSE, was {self.confirmation_price}",
            )


class ProtectedSettings:
    """保护点失效缓冲（RESEARCH，初始 0.1 ATR）。"""

    def __init__(self, raw: dict[str, object]) -> None:
        """从 ``protected`` 映射构建。"""
        self.break_buffer_atr = require_decimal(
            raw.get("break_buffer_atr"),
            field_name="protected.break_buffer_atr",
        )


class NStructureSettings:
    """N 结构失效缓冲（RESEARCH，初始 0.1 ATR，仅适用于 15M）。"""

    def __init__(self, raw: dict[str, object]) -> None:
        """从 ``n_structure`` 映射构建。"""
        self.break_buffer_atr = require_decimal(
            raw.get("break_buffer_atr"),
            field_name="n_structure.break_buffer_atr",
        )
        self.trading_timeframe = str(raw.get("trading_timeframe", "15M"))
        if self.trading_timeframe != "15M":
            raise ConfigurationError(
                "n_structure.trading_timeframe is FIXED at 15M per spec section 5.5, "
                f"was {self.trading_timeframe}",
            )


class ZoneSettings:
    """Zone 聚类与几何参数（规格第 6 章与第 19 章）。"""

    def __init__(self, raw: dict[str, object]) -> None:
        """从 ``zone`` 映射构建。"""
        self.min_anchor_count = require_int(
            raw.get("min_anchor_count"),
            field_name="zone.min_anchor_count",
        )
        # FIXED：规格第 6.5 节规定最小锚点数量为 2，且不得放宽至单点。
        if self.min_anchor_count != 2:
            raise ConfigurationError(
                "zone.min_anchor_count is FIXED at 2 per spec section 6.5, "
                f"was {self.min_anchor_count}",
            )
        self.merge_distance_atr = require_decimal(
            raw.get("merge_distance_atr"),
            field_name="zone.merge_distance_atr",
        )
        self.max_cluster_width_atr = require_decimal(
            raw.get("max_cluster_width_atr"),
            field_name="zone.max_cluster_width_atr",
        )
        self.half_width_atr = require_decimal(
            raw.get("half_width_atr"),
            field_name="zone.half_width_atr",
        )
        self.min_half_width_ticks = require_int(
            raw.get("min_half_width_ticks"),
            field_name="zone.min_half_width_ticks",
        )
        self.test_tolerance_atr = require_decimal(
            raw.get("test_tolerance_atr"),
            field_name="zone.test_tolerance_atr",
        )
        self.break_buffer_atr = require_decimal(
            raw.get("break_buffer_atr"),
            field_name="zone.break_buffer_atr",
        )
        self.max_age_weeks = require_int(
            raw.get("max_age_weeks"),
            field_name="zone.max_age_weeks",
        )

    def snapshot(self) -> dict[str, str]:
        """返回必须随比较结果记录的实际生效值（SACW 21.2）。"""
        return {
            "merge_distance_atr": str(self.merge_distance_atr),
            "max_cluster_width_atr": str(self.max_cluster_width_atr),
            "zone_half_width_atr": str(self.half_width_atr),
            "min_half_width_ticks": str(self.min_half_width_ticks),
            "zone_max_age_weeks": str(self.max_age_weeks),
            "test_tolerance_atr": str(self.test_tolerance_atr),
            "break_buffer_atr": str(self.break_buffer_atr),
            "min_anchor_count": str(self.min_anchor_count),
        }


class PullbackSettings:
    """各周期回撤最小幅度（RESEARCH）。"""

    def __init__(self, raw: dict[str, object]) -> None:
        """从 ``pullback`` 映射构建。"""
        self.min_atr_1d = require_decimal(
            raw.get("min_atr_1d"),
            field_name="pullback.min_atr_1d",
        )
        self.min_atr_4h = require_decimal(
            raw.get("min_atr_4h"),
            field_name="pullback.min_atr_4h",
        )
        self.min_atr_1h = require_decimal(
            raw.get("min_atr_1h"),
            field_name="pullback.min_atr_1h",
        )
        self.min_atr_15m = require_decimal(
            raw.get("min_atr_15m"),
            field_name="pullback.min_atr_15m",
        )


class RangeSettings:
    """区间判定容差（RESEARCH）。"""

    def __init__(self, raw: dict[str, object]) -> None:
        """从 ``range`` 映射构建。"""
        self.boundary_tolerance_atr = require_decimal(
            raw.get("boundary_tolerance_atr"),
            field_name="range.boundary_tolerance_atr",
        )


class StrategySettings:
    """策略标识与方向策略。"""

    def __init__(self, raw: dict[str, object], timeframes: TimeframeSettings) -> None:
        """从 ``strategy`` 与 ``timeframes`` 构建。"""
        self.name = str(raw.get("name", "eth_multi_tf_trend"))
        self.version = str(raw.get("version", "1.4.8"))
        direction = str(raw.get("direction", "LONG_ONLY"))
        if direction != TradingDirection.LONG_ONLY.value:
            raise ConfigurationError(f"direction must be LONG_ONLY, was {direction}")
        self.direction = TradingDirection.LONG_ONLY
        self.allow_short = bool(raw.get("allow_short", False))
        self.allow_reverse = bool(raw.get("allow_reverse", False))
        self.allow_pyramiding = bool(raw.get("allow_pyramiding", False))
        if self.allow_short or self.allow_reverse or self.allow_pyramiding:
            raise ConfigurationError(
                "spec V1.4.8 is LONG_ONLY: allow_short, allow_reverse and "
                "allow_pyramiding must all be false",
            )
        self.timeframes = timeframes


@dataclass(frozen=True, slots=True)
class InstrumentMetadata:
    """交易所合约元数据（规格第 18.2 节，分类 METADATA）。

    这些值必须由交易所提供并带版本；缺失时启动门禁拒绝（第 18.3 节第 5、6 项）。
    ``tick_size`` 同时是 Zone 半宽下限项 ``min_half_width_ticks * tick_size``
    的输入（规格第 6.4 节），因此必须与策略配置一起冻结。
    """

    version: str | None
    tick_size: Decimal | None
    lot_size: Decimal | None
    min_quantity: Decimal | None
    max_quantity: Decimal | None
    contract_multiplier: Decimal | None

    @property
    def complete(self) -> bool:
        """元数据是否齐全。"""
        return (
            bool(self.version)
            and self.tick_size is not None
            and self.tick_size > 0
            and self.lot_size is not None
            and self.min_quantity is not None
            and self.max_quantity is not None
            and self.contract_multiplier is not None
        )

    def missing_fields(self) -> tuple[str, ...]:
        """返回缺失或非法的字段名，供门禁报告。"""
        missing: list[str] = []
        if not self.version:
            missing.append("version")
        if self.tick_size is None or self.tick_size <= 0:
            missing.append("tick_size")
        if self.lot_size is None:
            missing.append("lot_size")
        if self.min_quantity is None:
            missing.append("min_quantity")
        if self.max_quantity is None:
            missing.append("max_quantity")
        if self.contract_multiplier is None:
            missing.append("contract_multiplier")
        return tuple(missing)


class MarketSettings:
    """交易标的标识与合约元数据。"""

    def __init__(self, raw: dict[str, object]) -> None:
        """从 ``market`` 映射构建。"""
        self.venue = str(raw.get("venue", "OKX"))
        self.instrument_id = str(raw.get("instrument_id", ""))
        self.instrument_type = str(raw.get("instrument_type", "SWAP"))
        self.settlement_currency = str(raw.get("settlement_currency", "USDT"))
        self.margin_mode = str(raw.get("margin_mode", "ISOLATED"))
        self.leverage = to_decimal(raw.get("leverage"), field_name="market.leverage")
        if not self.instrument_id:
            raise ConfigurationError("market.instrument_id is required")
        metadata = raw.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        version = metadata.get("version")
        self.metadata = InstrumentMetadata(
            version=str(version) if version is not None else None,
            tick_size=to_decimal(metadata.get("tick_size"), field_name="metadata.tick_size"),
            lot_size=to_decimal(metadata.get("lot_size"), field_name="metadata.lot_size"),
            min_quantity=to_decimal(
                metadata.get("min_quantity"),
                field_name="metadata.min_quantity",
            ),
            max_quantity=to_decimal(
                metadata.get("max_quantity"),
                field_name="metadata.max_quantity",
            ),
            contract_multiplier=to_decimal(
                metadata.get("contract_multiplier"),
                field_name="metadata.contract_multiplier",
            ),
        )


class RiskSettings:
    """风险配置（第 18.1 节：REQUIRED + RESEARCH）。"""

    def __init__(self, raw: dict[str, object]) -> None:
        """从 ``risk`` 映射构建。"""
        self.risk_per_trade_pct = to_decimal(
            raw.get("risk_per_trade_pct"),
            field_name="risk.risk_per_trade_pct",
        )
        self.max_notional_exposure = to_decimal(
            raw.get("max_notional_exposure"),
            field_name="risk.max_notional_exposure",
        )
        self.max_margin_usage_pct = to_decimal(
            raw.get("max_margin_usage_pct"),
            field_name="risk.max_margin_usage_pct",
        )
        self.leverage = to_decimal(raw.get("leverage"), field_name="risk.leverage")
        self.fixed_stop_pct = require_decimal(
            raw.get("fixed_stop_pct"),
            field_name="risk.fixed_stop_pct",
        )
        self.hard_risk_budget_multiple = require_decimal(
            raw.get("hard_risk_budget_multiple"),
            field_name="risk.hard_risk_budget_multiple",
        )
        self.trailing_k_normal = require_decimal(
            raw.get("trailing_k_normal"),
            field_name="risk.trailing_k_normal",
        )
        self.trailing_k_escalated = require_decimal(
            raw.get("trailing_k_escalated"),
            field_name="risk.trailing_k_escalated",
        )
        self.recovery_confirm_1h_bars = require_int(
            raw.get("recovery_confirm_1h_bars"),
            field_name="risk.recovery_confirm_1h_bars",
        )
        self.recovery_confirm_4h_bars = require_int(
            raw.get("recovery_confirm_4h_bars"),
            field_name="risk.recovery_confirm_4h_bars",
        )


class ExecutionSettings:
    """执行与成本配置（第 14、18.1 节）。"""

    def __init__(self, raw: dict[str, object]) -> None:
        """从 ``execution`` 映射构建。"""
        self.maker_fee_rate = to_decimal(
            raw.get("maker_fee_rate"),
            field_name="execution.maker_fee_rate",
        )
        self.taker_fee_rate = to_decimal(
            raw.get("taker_fee_rate"),
            field_name="execution.taker_fee_rate",
        )
        self.max_execution_deviation_atr = require_decimal(
            raw.get("max_execution_deviation_atr"),
            field_name="execution.max_execution_deviation_atr",
        )
        self.max_execution_gap_atr = require_decimal(
            raw.get("max_execution_gap_atr"),
            field_name="execution.max_execution_gap_atr",
        )
        self.max_actual_fill_deviation_atr = require_decimal(
            raw.get("max_actual_fill_deviation_atr"),
            field_name="execution.max_actual_fill_deviation_atr",
        )
        self.min_trigger_swing_atr = require_decimal(
            raw.get("min_trigger_swing_atr"),
            field_name="execution.min_trigger_swing_atr",
        )
        self.cost_model_version = raw.get("cost_model_version")
        self.slippage_model_version = raw.get("slippage_model_version")
        self.instrument_metadata_version = raw.get("instrument_metadata_version")


class ResearchSettings:
    """研究口径与数据来源（第 3.1、18.1 节）。"""

    def __init__(self, raw: dict[str, object]) -> None:
        """从 ``research`` 映射构建。"""
        self.data_timezone = str(raw.get("data_timezone", "UTC"))
        if self.data_timezone != "UTC":
            raise ConfigurationError(
                f"research.data_timezone must be UTC, was {self.data_timezone}",
            )
        self.session_offset_hours = require_int(
            raw.get("session_offset_hours"),
            field_name="research.session_offset_hours",
        )
        self.funding_dataset = raw.get("funding_dataset")


@dataclass(frozen=True, slots=True)
class PaTrendConfig:
    """V1.4.8 冻结配置聚合体。"""

    market: MarketSettings
    strategy: StrategySettings
    indicators: IndicatorSettings
    zigzag: ZigZagSettings
    protected: ProtectedSettings
    n_structure: NStructureSettings
    zone: ZoneSettings
    pullback: PullbackSettings
    range: RangeSettings
    risk: RiskSettings
    execution: ExecutionSettings
    research: ResearchSettings

    @property
    def instrument_id(self) -> str:
        """返回配置的合约标识。"""
        return self.market.instrument_id

    @property
    def timeframes(self) -> TimeframeSettings:
        """返回周期角色配置。"""
        return self.strategy.timeframes

    @property
    def tick_size(self) -> Decimal:
        """返回合约最小价格变动单位；缺失时抛错而不是退回猜测值。"""
        tick_size = self.market.metadata.tick_size
        if tick_size is None or tick_size <= 0:
            raise ConfigurationError(
                "market.metadata.tick_size is required for Zone half-width "
                "(spec section 6.4) and was missing or non-positive",
            )
        return tick_size
