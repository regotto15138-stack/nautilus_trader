"""加载冻结的 V1.4.8 YAML 配置集合。"""

from __future__ import annotations

from pathlib import Path

import yaml

from pa_trend.config.models import (
    ExecutionSettings,
    IndicatorSettings,
    MarketSettings,
    NStructureSettings,
    PaTrendConfig,
    ProtectedSettings,
    PullbackSettings,
    RangeSettings,
    ResearchSettings,
    RiskSettings,
    StrategySettings,
    ZigZagSettings,
    ZoneSettings,
)
from pa_trend.config.timeframes import TimeframeSettings
from pa_trend.domain.errors import ConfigurationError

STRATEGY_FILE = "strategy_v1_4_8.yaml"
MARKET_FILE = "market_okx_eth_swap.yaml"
RISK_FILE = "risk.yaml"
EXECUTION_FILE = "execution.yaml"
RESEARCH_FILE = "research.yaml"


def load_yaml(path: Path) -> dict[str, object]:
    """把 YAML 文件读成映射。

    固定使用 ``yaml.safe_load``，避免反序列化时构造任意 Python 对象。
    """
    if not path.is_file():
        raise ConfigurationError(f"configuration file not found: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw is None:
        raise ConfigurationError(f"configuration file is empty: {path}")
    if not isinstance(raw, dict):
        raise ConfigurationError(f"configuration file must contain a mapping: {path}")
    return raw


def load_config(configs_dir: Path) -> PaTrendConfig:
    """加载并组装五个配置文件。"""
    strategy_raw = load_yaml(configs_dir / STRATEGY_FILE)
    market_raw = load_yaml(configs_dir / MARKET_FILE)
    risk_raw = load_yaml(configs_dir / RISK_FILE)
    execution_raw = load_yaml(configs_dir / EXECUTION_FILE)
    research_raw = load_yaml(configs_dir / RESEARCH_FILE)

    timeframes = TimeframeSettings(dict(strategy_raw.get("timeframes") or {}))

    return PaTrendConfig(
        market=MarketSettings(dict(market_raw.get("market") or {})),
        strategy=StrategySettings(dict(strategy_raw.get("strategy") or {}), timeframes),
        indicators=IndicatorSettings(dict(strategy_raw.get("indicators") or {})),
        zigzag=ZigZagSettings(dict(strategy_raw.get("zigzag") or {})),
        protected=ProtectedSettings(dict(strategy_raw.get("protected") or {})),
        n_structure=NStructureSettings(dict(strategy_raw.get("n_structure") or {})),
        zone=ZoneSettings(dict(strategy_raw.get("zone") or {})),
        pullback=PullbackSettings(dict(strategy_raw.get("pullback") or {})),
        range=RangeSettings(dict(strategy_raw.get("range") or {})),
        risk=RiskSettings(dict(risk_raw.get("risk") or {})),
        execution=ExecutionSettings(dict(execution_raw.get("execution") or {})),
        research=ResearchSettings(dict(research_raw.get("research") or {})),
    )
