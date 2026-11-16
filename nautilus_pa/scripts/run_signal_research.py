"""在已采集的数据目录上做信号事件研究（规格第 19 与 20 节）。

在任何入场逻辑存在之前先统计结构事件，这是规格要求的顺序：先评估统计可行性，
再谈策略参数调优。

示例
----
python scripts/run_signal_research.py
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from nautilus_trader.persistence import ParquetDataCatalog

from pa_trend.adapters.nautilus.bar_converter import to_domain_bar
from pa_trend.application import paths
from pa_trend.application.market_context import MarketContext
from pa_trend.config.loader import load_config
from pa_trend.domain.errors import BarAlignmentError
from pa_trend.domain.models.timeframe import ns_to_dt

DEFAULT_INSTRUMENT = "ETH-USDT-SWAP.OKX"
DEFAULT_CONFIGS = paths.DEFAULT_CONFIGS_DIR
DEFAULT_CATALOG = paths.DEFAULT_CATALOG_DIR


def build_parser() -> argparse.ArgumentParser:
    """构建命令行解析器。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--catalog",
        type=Path,
        default=DEFAULT_CATALOG,
        help=f"Parquet 数据目录（默认 {DEFAULT_CATALOG}）",
    )
    parser.add_argument("--configs", type=Path, default=DEFAULT_CONFIGS, help="配置目录")
    parser.add_argument("--instrument", default=DEFAULT_INSTRUMENT, help="合约标识")
    parser.add_argument(
        "--session-offset-hours",
        type=int,
        default=None,
        help="会话偏移小时数；缺省读取 research.session_offset_hours",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """输出研究报告。"""
    args = build_parser().parse_args(argv)
    if args.session_offset_hours is None:
        args.session_offset_hours = load_config(args.configs).research.session_offset_hours

    config = load_config(args.configs)
    context = MarketContext(config)
    catalog = ParquetDataCatalog(str(paths.resolve_catalog_dir(args.catalog)))

    for timeframe in config.timeframes.all():
        key = f"{args.instrument}-{timeframe.bar_spec}-LAST-EXTERNAL"
        nautilus_bars = sorted(catalog.query_bars(identifiers=[key]), key=lambda bar: bar.ts_event)

        fed = 0
        misaligned = 0
        for nautilus_bar in nautilus_bars:
            try:
                domain_bar = to_domain_bar(
                    nautilus_bar,
                    timeframe,
                    instrument_id=args.instrument,
                    session_offset_minutes=args.session_offset_hours * 60,
                )
            except BarAlignmentError:
                misaligned += 1
                continue
            context.on_bar(domain_bar)
            fed += 1

        state = context.engine(timeframe)
        print(
            f"[{timeframe.value:>3}] 状态={state.state!s:<20} 已处理={fed:5d} "
            f"未对齐={misaligned} 摆动点={len(state.swings):3d} "
            f"N结构={len(state.structures.structures):2d} "
            f"结构就绪={state.structure_ready}",
        )
        if state.last_bar is not None:
            print(f"  最近收盘: {state.last_bar.ts_close.isoformat()}")

    print()
    snapshot = context.snapshot()
    print(
        f"宏观：1M={snapshot.month.value} 1W={snapshot.week.value} "
        f"1D={snapshot.day.value} | 4H={snapshot.h4.value} 1H={snapshot.h1.value}",
    )
    print(f"CanOpen={snapshot.can_open} CanHold={snapshot.can_hold}")
    print()
    _print_structures(context)
    return 0


def _print_structures(context: MarketContext) -> None:
    structures = [
        structure
        for timeframe in context.config.timeframes.all()
        for structure in context.engine(timeframe).structures.structures
    ]
    print(f"N 结构总数: {len(structures)}")
    if not structures:
        print("  （无；历史可能太短，或波动不足以触发 ATR 反转）")
        return

    by_class = Counter(item.retracement_class.value for item in structures)
    by_status = Counter(item.status.value for item in structures)
    by_year = Counter(ns_to_dt(item.confirmed_at_ns).year for item in structures)

    print(f"  按状态: {dict(sorted(by_status.items()))}")
    print(f"  按回撤分类: {dict(sorted(by_class.items()))}")
    print(f"  按确认年份: {dict(sorted(by_year.items()))}")
    invalidation = {
        timeframe.value: context.engine(timeframe).structures.invalidation_status
        for timeframe in context.config.timeframes.all()
    }
    print(f"  失效判定: {invalidation}")
    print(
        "  说明: N 结构失效使用的 ATR 时点未在 V1.4.8 中定义（SACW 27.6），"
        "因此当前不产出失效价；"
        "4H/1H 结构为 RESEARCH_ONLY，不得参与交易性失效判定。",
    )

    print()
    print("  最近五个结构:")
    for item in structures[-5:]:
        confirmed = ns_to_dt(item.confirmed_at_ns)
        print(
            f"    {item.n_structure_id} 确认={confirmed.date()} "
            f"L1={item.l1.price} H1={item.h1.price} "
            f"L2={item.l2.price} H2={item.h2.price} "
            f"回撤={item.retracement_ratio:.3f} ({item.retracement_class.value}) "
            f"状态={item.status.value}",
        )


if __name__ == "__main__":
    sys.exit(main())
