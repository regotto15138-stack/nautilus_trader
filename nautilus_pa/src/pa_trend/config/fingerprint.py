"""配置快照与指纹（SACW 5.2、21.2、21.4）。

任何回放、标注与比较结果都必须能追溯到**实际生效**的参数值，而不是仓库里
``yaml`` 文件的当前内容。本模块把配置展开成扁平映射并计算稳定哈希，供：

- 图表载荷与事件载荷写入 ``config_hash``；
- 标注快照记录 ``zone_half_width_atr``、``min_half_width_ticks``、
  ``zone_max_age_weeks`` 与 ``tick_size`` 的来源版本（SACW 21.2、21.4）；
- 参数白名单分类（FIXED / RESEARCH / METADATA / REQUIRED）核对。
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal

from pa_trend.config.models import PaTrendConfig

#: 参数分类（规格第 19 章）。
FIXED = "FIXED"
RESEARCH = "RESEARCH"
METADATA = "METADATA"
REQUIRED = "REQUIRED"

#: 本阶段已实现且必须被记录的分类表。
PARAMETER_CLASSES: dict[str, str] = {
    "indicators.ma_period": FIXED,
    "indicators.atr_period": FIXED,
    "zigzag.reversal_atr_multiple": RESEARCH,
    "protected.break_buffer_atr": RESEARCH,
    "n_structure.break_buffer_atr": RESEARCH,
    "n_structure.trading_timeframe": FIXED,
    "zone.min_anchor_count": FIXED,
    "zone.merge_distance_atr": RESEARCH,
    "zone.max_cluster_width_atr": RESEARCH,
    "zone.half_width_atr": RESEARCH,
    "zone.min_half_width_ticks": RESEARCH,
    "zone.test_tolerance_atr": RESEARCH,
    "zone.break_buffer_atr": RESEARCH,
    "zone.max_age_weeks": RESEARCH,
    "pullback.min_atr_1d": RESEARCH,
    "pullback.min_atr_4h": RESEARCH,
    "pullback.min_atr_1h": RESEARCH,
    "pullback.min_atr_15m": RESEARCH,
    "range.boundary_tolerance_atr": RESEARCH,
    "risk.fixed_stop_pct": RESEARCH,
    "risk.hard_risk_budget_multiple": RESEARCH,
    "risk.trailing_k_normal": RESEARCH,
    "risk.trailing_k_escalated": RESEARCH,
    "risk.recovery_confirm_1h_bars": RESEARCH,
    "risk.recovery_confirm_4h_bars": RESEARCH,
    "risk.risk_per_trade_pct": REQUIRED,
    "risk.max_notional_exposure": REQUIRED,
    "risk.max_margin_usage_pct": REQUIRED,
    "risk.leverage": REQUIRED,
    "execution.max_execution_deviation_atr": RESEARCH,
    "execution.max_execution_gap_atr": RESEARCH,
    "execution.max_actual_fill_deviation_atr": RESEARCH,
    "execution.min_trigger_swing_atr": RESEARCH,
    "execution.maker_fee_rate": METADATA,
    "execution.taker_fee_rate": METADATA,
    "market.metadata.tick_size": METADATA,
    "market.metadata.lot_size": METADATA,
    "market.metadata.min_quantity": METADATA,
    "market.metadata.max_quantity": METADATA,
    "market.metadata.contract_multiplier": METADATA,
    "research.session_offset_hours": RESEARCH,
}

_STRUCTURAL_SECTIONS = (
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


def _stringify(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _stringify(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_stringify(item) for item in value]
    return value


def config_snapshot(config: PaTrendConfig) -> dict[str, object]:
    """把配置展开成可序列化的扁平快照（含分类与实际生效值）。"""
    raw: dict[str, object] = {
        "strategy": {
            "name": config.strategy.name,
            "version": config.strategy.version,
            "direction": config.strategy.direction.value,
        },
        "market": {
            "instrument_id": config.market.instrument_id,
            "venue": config.market.venue,
            "instrument_type": config.market.instrument_type,
            "leverage": config.market.leverage,
            "metadata": {
                "version": config.market.metadata.version,
                "tick_size": config.market.metadata.tick_size,
                "lot_size": config.market.metadata.lot_size,
                "min_quantity": config.market.metadata.min_quantity,
                "max_quantity": config.market.metadata.max_quantity,
                "contract_multiplier": config.market.metadata.contract_multiplier,
            },
        },
        "indicators": {
            "ma_type": config.indicators.ma_type,
            "ma_period": config.indicators.ma_period,
            "atr_type": config.indicators.atr_type,
            "atr_period": config.indicators.atr_period,
            "atr_ma22": "N/A / SPEC_AMBIGUITY",
        },
        "zigzag": {
            "method": config.zigzag.method,
            "reversal_atr_multiple": config.zigzag.reversal_atr_multiple,
            "confirmation_price": config.zigzag.confirmation_price,
        },
        "protected": {"break_buffer_atr": config.protected.break_buffer_atr},
        "n_structure": {
            "break_buffer_atr": config.n_structure.break_buffer_atr,
            "trading_timeframe": config.n_structure.trading_timeframe,
            "invalidation_status": "SPEC_AMBIGUITY",
        },
        "zone": {
            "min_anchor_count": config.zone.min_anchor_count,
            "merge_distance_atr": config.zone.merge_distance_atr,
            "max_cluster_width_atr": config.zone.max_cluster_width_atr,
            "half_width_atr": config.zone.half_width_atr,
            "min_half_width_ticks": config.zone.min_half_width_ticks,
            "test_tolerance_atr": config.zone.test_tolerance_atr,
            "break_buffer_atr": config.zone.break_buffer_atr,
            "max_age_weeks": config.zone.max_age_weeks,
        },
        "pullback": {
            "min_atr_1d": config.pullback.min_atr_1d,
            "min_atr_4h": config.pullback.min_atr_4h,
            "min_atr_1h": config.pullback.min_atr_1h,
            "min_atr_15m": config.pullback.min_atr_15m,
        },
        "range": {"boundary_tolerance_atr": config.range.boundary_tolerance_atr},
        "risk": {
            "risk_per_trade_pct": config.risk.risk_per_trade_pct,
            "max_notional_exposure": config.risk.max_notional_exposure,
            "max_margin_usage_pct": config.risk.max_margin_usage_pct,
            "leverage": config.risk.leverage,
            "fixed_stop_pct": config.risk.fixed_stop_pct,
            "hard_risk_budget_multiple": config.risk.hard_risk_budget_multiple,
            "trailing_k_normal": config.risk.trailing_k_normal,
            "trailing_k_escalated": config.risk.trailing_k_escalated,
            "recovery_confirm_1h_bars": config.risk.recovery_confirm_1h_bars,
            "recovery_confirm_4h_bars": config.risk.recovery_confirm_4h_bars,
        },
        "execution": {
            "maker_fee_rate": config.execution.maker_fee_rate,
            "taker_fee_rate": config.execution.taker_fee_rate,
            "max_execution_deviation_atr": config.execution.max_execution_deviation_atr,
            "max_execution_gap_atr": config.execution.max_execution_gap_atr,
            "max_actual_fill_deviation_atr": config.execution.max_actual_fill_deviation_atr,
            "min_trigger_swing_atr": config.execution.min_trigger_swing_atr,
            "cost_model_version": config.execution.cost_model_version,
            "slippage_model_version": config.execution.slippage_model_version,
            "instrument_metadata_version": config.execution.instrument_metadata_version,
        },
        "research": {
            "data_timezone": config.research.data_timezone,
            "session_offset_hours": config.research.session_offset_hours,
            "funding_dataset": config.research.funding_dataset,
        },
    }
    return _stringify(raw)  # type: ignore[return-value]


def config_hash(snapshot: dict[str, object]) -> str:
    """对配置快照计算稳定 SHA-256（键排序、无空格）。"""
    canonical = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def flatten(
    snapshot: dict[str, object],
    *,
    prefix: str = "",
) -> dict[str, object]:
    """把嵌套快照展开成 ``a.b.c`` 形式的扁平映射。"""
    flat: dict[str, object] = {}
    for key, value in snapshot.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            flat.update(flatten(value, prefix=path))
        else:
            flat[path] = value
    return flat


def research_parameters(config: PaTrendConfig) -> dict[str, str]:
    """返回按分类整理的实际生效参数，供报告与校准白名单使用。"""
    flat = flatten(config_snapshot(config))
    out: dict[str, str] = {}
    for path, value in flat.items():
        category = PARAMETER_CLASSES.get(path)
        if category is None:
            continue
        out[path] = f"{value} [{category}]"
    return out


def sections_for_stage(stage: str) -> tuple[str, ...]:
    """返回某阶段必须校验的配置小节。"""
    if stage == "RESEARCH_STRUCTURE":
        return _STRUCTURAL_SECTIONS
    return _STRUCTURAL_SECTIONS + _EXECUTION_SECTIONS
