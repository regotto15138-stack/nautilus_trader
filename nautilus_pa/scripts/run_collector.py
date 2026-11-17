"""启动 OKX 多周期 K 线采集器。

与 ``examples/live/okx/eth_multi_bar_collector.py`` 对应，但把冻结的策略配置作为
合约与周期的唯一来源。

两种运行方式：

- 常驻采集（默认）：启动补齐后持续订阅 WebSocket 与收盘补拉；
- 补齐后退出（``--backfill-only``）：启动补齐落盘后立即停止节点。工作台
  「实时」按钮用它做一次性补数，不需要另开常驻进程。

示例
-------
python scripts/run_collector.py
python scripts/run_collector.py --backfill-only --proxy-url http://172.21.192.1:7890
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import threading
import time
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
    parser.add_argument(
        "--backfill-only",
        action="store_true",
        help="补齐落盘后立即退出（供工作台「实时」按钮做一次性补数）",
    )
    parser.add_argument(
        "--backfill-timeout-secs",
        type=float,
        default=180.0,
        help="补齐后退出模式的等待上限；超时即停止节点（默认 180 秒）",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """运行采集器直到被中断（或补齐完成后退出）。"""
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

    # 补齐后退出：回调在采集器线程里触发，这里只设一个事件，由主线程停止节点。
    done = threading.Event()
    node = build_live_node(
        node_name=args.node_name,
        trader_id=args.trader_id,
        bar_types=bar_types,
        timeframes_by_bar_type=timeframes_by_bar_type,
        instrument_id=instrument_id,
        catalog_path=str(catalog_dir),
        proxy_url=args.proxy_url,
        session_offset_minutes=args.session_offset_hours * 60,
        on_backfill_done=(done.set if args.backfill_only else None),
    )

    if not args.backfill_only:
        node.run()
        return 0

    # 常驻 node.run() 只会在收到信号时返回。补齐后退出不能在旁路线程里调用
    # node.stop()：PyLiveNode 绑定在创建它的线程上，跨线程调用会直接 abort。
    # 因此改由本进程向自己发 SIGINT，走与 Ctrl-C 相同的正常停止路径。
    def _interrupt_when_ready() -> None:
        finished = done.wait(timeout=args.backfill_timeout_secs)
        if not finished:
            print(
                f"补齐未在 {args.backfill_timeout_secs:.0f} 秒内完成，正在停止采集器。",
                file=sys.stderr,
            )
        else:
            print("补齐完成，正在停止采集器。")
        # 稍等一拍，让补齐回调返回、事件循环回到可接收信号的状态。
        time.sleep(0.2)
        os.kill(os.getpid(), signal.SIGINT)

    threading.Thread(target=_interrupt_when_ready, name="backfill-watchdog", daemon=True).start()
    node.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
