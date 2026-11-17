"""审计 catalog 中每个周期的缺口与尾部滞后，并对照当前 UTC 时间。

用法::

    python scripts/gap_audit.py            # 报告
    python scripts/gap_audit.py --json     # 机器可读

逻辑在 :mod:`pa_trend.application.catalog_audit`，工作台的启动自检与
``/api/v1/market/freshness`` 用的是同一份实现。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pa_trend.application.catalog_audit import audit_catalog, summarize
from pa_trend.application.paths import (
    DEFAULT_CATALOG_DIR,
    DEFAULT_CONFIGS_DIR,
    resolve_catalog_dir,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG_DIR)
    parser.add_argument("--configs", type=Path, default=DEFAULT_CONFIGS_DIR)
    parser.add_argument("--instrument", default="ETH-USDT-SWAP.OKX")
    parser.add_argument("--session-offset-hours", type=int, default=8)
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args(argv)

    catalog_dir = resolve_catalog_dir(args.catalog)
    if not catalog_dir.is_dir():
        print(f"数据目录不存在: {catalog_dir}", file=sys.stderr)
        return 2

    rows = audit_catalog(
        catalog_dir=catalog_dir,
        configs_dir=args.configs,
        instrument_id=args.instrument,
        session_offset_hours=args.session_offset_hours,
    )
    summary = summarize(rows)

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    print(f"now(UTC) = {summary['nowUtc']}")
    header = (
        f"{'周期':<6}{'根数':>8}{'首根(UTC)':<22}{'末根开(UTC)':<22}"
        f"{'缺口段':>6}{'缺根':>6}{'尾部欠根':>8}"
    )
    print(header)
    print("-" * len(header))
    for row in summary["timeframes"]:
        if row["error"]:
            print(f"{row['timeframe']:<6}{'ERR':>8}  {row['error']}")
            continue
        print(
            f"{row['timeframe']:<6}{row['count']:>8}"
            f"{(row['firstOpen'] or '')[:19]:<22}{(row['lastOpen'] or '')[:19]:<22}"
            f"{row['gapSegments']:>6}{row['missingInGaps']:>6}"
            f"{row['tailMissingClosed']:>8}",
        )
        for gap in row["gaps"]:
            print(
                f"       gap {gap['start'][:19]} -> {gap['end'][:19]} "
                f"missing={gap['missing']}",
            )
    print()
    print("结论:", "存在缺口或尾部欠数" if summary["stale"] else "全部周期连续，无明显缺失")
    return 0 if not summary["stale"] else 1


if __name__ == "__main__":
    sys.exit(main())
