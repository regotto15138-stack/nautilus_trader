"""启动 OKX 多周期 K 线采集器。

与 ``examples/live/okx/eth_multi_bar_collector.py`` 对应，但把冻结的策略配置作为
合约与周期的唯一来源。

示例
----
python scripts/run_collector.py
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from nautilus_trader.model import BarType, InstrumentId

from pa_trend.adapters.nautilus.collector import build_live_node
from pa_trend.application.paths import (
    DEFAULT_CATALOG_DIR,
    DEFAULT_CONFIGS_DIR,
    resolve_catalog_dir,
)
from pa_trend.config.loader import load_config
from pa_trend.domain.models.timeframe import Timeframe


def build_parser() -> argparse.ArgumentParser:
    """构建命令行解析器。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--configs", type=Path, default=DEFAULT_CONFIGS_DIR, help="配置目录")
    parser.add_argument(
        "--catalog",
        type=Path,
        default=DEFAULT_CATALOG_DIR,
        help=f"Parquet 数据目录（默认 {DEFAULT_CATALOG_DIR}）",
    )
    parser.add_argument("--proxy-url", default=None, help="OKX 可选的 HTTP 代理")
    parser.add_argument("--node-name", default="PA-TREND-COLLECTOR", help="实盘节点名称")
    parser.add_argument("--trader-id", default="PA-TREND", help="Trader 标识")
    parser.add_argument("--log-level", default="INFO", help="Python 日志级别")
    parser.add_argument(
        "--session-offset-hours",
        type=int,
        default=8,
        help="交易所会话边界偏移小时数；OKX 为 8（默认）",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """运行采集器直到被中断。"""
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO))

    config = load_config(args.configs)
    instrument_id = InstrumentId.from_str(config.instrument_id)

    bar_types: list[BarType] = []
    timeframes_by_bar_type: dict[str, Timeframe] = {}
    for timeframe in config.timeframes.all():
        bar_type = BarType.from_str(
            f"{instrument_id}-{timeframe.bar_spec}-LAST-EXTERNAL",
        )
        bar_types.append(bar_type)
        timeframes_by_bar_type[str(bar_type)] = timeframe

    print(f"开始采集 {len(bar_types)} 个周期：")
    for item in bar_types:
        print(f"  - {item}")
    catalog_dir = resolve_catalog_dir(args.catalog)
    print(f"数据目录: {catalog_dir}")

    node = build_live_node(
        node_name=args.node_name,
        trader_id=args.trader_id,
        bar_types=bar_types,
        timeframes_by_bar_type=timeframes_by_bar_type,
        instrument_id=instrument_id,
        catalog_path=str(catalog_dir),
        proxy_url=args.proxy_url,
        session_offset_minutes=args.session_offset_hours * 60,
    )
    node.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
