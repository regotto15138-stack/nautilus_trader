"""按规格第 1.5 节校验已采集的 Parquet 数据目录。

按周期分别报告：K 线根数、未对齐根数、重复、缺口与顺序问题。退出码非零表示
该数据不适合用于分析。

示例
----
python scripts/validate_data.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from nautilus_trader.persistence import ParquetDataCatalog

from pa_trend.adapters.nautilus.bar_converter import to_domain_bar
from pa_trend.application import paths
from pa_trend.application.data_quality import validate_bar_series
from pa_trend.application.paths import DEFAULT_CATALOG_DIR as DEFAULT_CATALOG
from pa_trend.application.paths import DEFAULT_CONFIGS_DIR as DEFAULT_CONFIGS
from pa_trend.config.loader import load_config
from pa_trend.domain.errors import BarAlignmentError
from pa_trend.domain.models.bar import Bar
from pa_trend.domain.models.timeframe import ALL_TIMEFRAMES

DEFAULT_INSTRUMENT = "ETH-USDT-SWAP.OKX"
TIMEFRAMES = ALL_TIMEFRAMES


def build_parser() -> argparse.ArgumentParser:
    """构建命令行解析器。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--catalog",
        type=Path,
        default=DEFAULT_CATALOG,
        help=f"Parquet 数据目录（默认 {DEFAULT_CATALOG}）",
    )
    parser.add_argument("--instrument", default=DEFAULT_INSTRUMENT, help="合约标识")
    parser.add_argument("--configs", type=Path, default=DEFAULT_CONFIGS, help="配置目录")
    parser.add_argument(
        "--session-offset-hours",
        type=int,
        default=None,
        help=(
            "交易所会话边界相对 UTC 的偏移小时数；缺省读取 "
            "research.session_offset_hours（当前配置为 8）"
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """执行校验。"""
    args = build_parser().parse_args(argv)
    if args.session_offset_hours is None:
        # 与采集器、图表服务共用同一配置来源，避免「采集用 8、校验用 0」
        # 导致同一份数据一边通过一边全部未对齐。
        args.session_offset_hours = load_config(args.configs).research.session_offset_hours
    catalog = ParquetDataCatalog(str(paths.resolve_catalog_dir(args.catalog)))

    exit_code = 0
    for timeframe in TIMEFRAMES:
        key = f"{args.instrument}-{timeframe.bar_spec}-LAST-EXTERNAL"
        nautilus_bars = catalog.query_bars(identifiers=[key])
        if not nautilus_bars:
            print(f"{key}: 未找到 K 线")
            exit_code = 1
            continue

        bars: list[Bar] = []
        misaligned = 0
        for nautilus_bar in nautilus_bars:
            try:
                bars.append(
                    to_domain_bar(
                        nautilus_bar,
                        timeframe,
                        instrument_id=args.instrument,
                        session_offset_minutes=args.session_offset_hours * 60,
                    ),
                )
            except BarAlignmentError:
                misaligned += 1

        report = validate_bar_series(bars, timeframe)
        print(f"{key}: {report.summary()} misaligned={misaligned}")

        for issue in report.issues[:10]:
            print(f"  - {issue.kind.value}: {issue.detail}")
        if len(report.issues) > 10:
            print(f"  ... 另有 {len(report.issues) - 10} 条问题")

        if misaligned:
            print(
                f"  - 未对齐: {misaligned} 根 K 线的开盘时刻不在 UTC "
                f"{timeframe.name} 边界上。OKX 的日/周/月 K 线均按 UTC+8 零点开盘，"
                "当前按 research.session_offset_hours 判断；若为 0 表示严格执行"
                "规格第 1.5 节的 UTC 口径。",
            )
            exit_code = 1
        if not report.is_clean:
            exit_code = 1

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
