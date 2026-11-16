"""配置加载与启动门禁测试（规格 V1.4.8 第 18、19 章）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from helpers import dec
from pa_trend.config.loader import load_config
from pa_trend.config.models import require_int, to_decimal
from pa_trend.config.validation import Stage, validate_startup
from pa_trend.domain.errors import ConfigurationError
from pa_trend.domain.models.timeframe import ALL_TIMEFRAMES, Timeframe


def test_loads_frozen_values(configs_dir: Path) -> None:
    """冻结参数应被原样读出。"""
    config = load_config(configs_dir)
    assert config.instrument_id == "ETH-USDT-SWAP.OKX"
    assert config.strategy.version == "1.4.8"
    assert config.indicators.ma_period == 22
    assert config.indicators.atr_period == 14
    # V1.4.8 第 4.1 节没有 ATR_MA22；配置层也不得提供该周期。
    assert not hasattr(config.indicators, "atr_ma_period")
    assert config.zone.min_anchor_count == 2
    assert config.zone.merge_distance_atr == dec("0.5")
    assert config.zone.max_cluster_width_atr == dec("1.0")
    assert config.zone.half_width_atr == dec("0.1")
    assert config.zone.min_half_width_ticks == 2
    assert config.zone.test_tolerance_atr == dec("0.1")
    assert config.zone.break_buffer_atr == dec("0.1")
    assert config.zone.max_age_weeks == 52
    assert config.tick_size == dec("0.01")
    assert config.market.metadata.complete is True
    assert config.zigzag.reversal_atr_multiple == dec("2.0")
    assert config.protected.break_buffer_atr == dec("0.1")
    assert config.n_structure.break_buffer_atr == dec("0.1")
    assert config.n_structure.trading_timeframe == "15M"


def test_seven_timeframes_in_spec_order(configs_dir: Path) -> None:
    """七个周期角色固定且按由慢到快排列。"""
    config = load_config(configs_dir)
    assert config.timeframes.all() == ALL_TIMEFRAMES
    assert config.timeframes.macro is Timeframe.MONTH
    assert config.timeframes.mid is Timeframe.WEEK
    assert config.timeframes.short is Timeframe.DAY
    assert config.timeframes.setup is Timeframe.HOUR4
    assert config.timeframes.reversal is Timeframe.HOUR1
    assert config.timeframes.signal is Timeframe.MIN15
    assert config.timeframes.execution is Timeframe.MIN3


def test_research_defaults(configs_dir: Path) -> None:
    """研究口径默认值：UTC 与 UTC+8 会话。"""
    config = load_config(configs_dir)
    assert config.research.data_timezone == "UTC"
    assert config.research.session_offset_hours == 8
    assert config.research.funding_dataset is None


def test_structure_stage_accepts_and_skips_execution(configs_dir: Path) -> None:
    """结构研究阶段通过门禁并记录跳过项。"""
    report = validate_startup(load_config(configs_dir), Stage.RESEARCH_STRUCTURE)
    assert report.accepted
    assert "risk" in report.skipped
    assert "execution" in report.skipped


def test_full_gate_rejects_missing_required(configs_dir: Path) -> None:
    """完整门禁必须拒绝缺失的 REQUIRED 项。"""
    with pytest.raises(ConfigurationError) as excinfo:
        validate_startup(load_config(configs_dir), Stage.LIVE)
    message = str(excinfo.value)
    assert "risk.risk_per_trade_pct" in message
    assert "risk.max_notional_exposure" in message
    assert "risk.max_margin_usage_pct" in message
    assert "risk.leverage" in message
    assert "execution.maker_fee_rate" in message
    assert "execution.taker_fee_rate" in message
    assert "research.funding_dataset" in message


def test_full_gate_rejects_missing_versions(configs_dir: Path) -> None:
    """成本/滑点/元数据版本未指定时拒绝启动。"""
    with pytest.raises(ConfigurationError) as excinfo:
        validate_startup(load_config(configs_dir), Stage.RESEARCH_BACKTEST)
    message = str(excinfo.value)
    assert "cost_model_version" in message
    assert "slippage_model_version" in message
    assert "instrument_metadata_version" in message


def test_missing_file_raises(tmp_path: Path) -> None:
    """配置文件缺失时抛错。"""
    with pytest.raises(ConfigurationError, match="not found"):
        load_config(tmp_path)


def test_to_decimal_preserves_none() -> None:
    """空值必须原样保留。"""
    assert to_decimal(None, field_name="x") is None


def test_to_decimal_rejects_boolean() -> None:
    """布尔值不是数值。"""
    with pytest.raises(ConfigurationError, match="boolean"):
        to_decimal(True, field_name="x")


def test_require_int_accepts_whole_numbers() -> None:
    """整数正常通过。"""
    assert require_int(22, field_name="ma_period") == 22
    assert require_int("14", field_name="atr_period") == 14


def test_require_int_rejects_fractional_values() -> None:
    """非整数必须报错，不得静默截断。"""
    with pytest.raises(ConfigurationError, match="whole number"):
        require_int(22.9, field_name="ma_period")


def test_require_int_rejects_null() -> None:
    """缺失必须报错。"""
    with pytest.raises(ConfigurationError, match="must not be null"):
        require_int(None, field_name="ma_period")
