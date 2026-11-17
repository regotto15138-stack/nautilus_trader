
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Sequence
from zoneinfo import ZoneInfo

from nautilus_trader.adapters.okx import OKX
from nautilus_trader.adapters.okx import OKXDataClientConfig
from nautilus_trader.adapters.okx import OKXDataClientFactory
from nautilus_trader.adapters.okx import OKXEnvironment
from nautilus_trader.adapters.okx import OKXInstrumentType
from nautilus_trader.common import DataActor
from nautilus_trader.common import Environment
from nautilus_trader.config import DataActorConfig
from nautilus_trader.live import LiveNode
from nautilus_trader.model import Bar
from nautilus_trader.model import BarType
from nautilus_trader.model import InstrumentId
from nautilus_trader.model import TraderId
from nautilus_trader.persistence import ParquetDataCatalog

import logging
logging.basicConfig(level=logging.DEBUG)

INSTRUMENT_ID = InstrumentId.from_str(f"ETH-USDT-SWAP.{OKX}")
BAR_TYPE = BarType.from_str(
    f"{INSTRUMENT_ID}-1-MINUTE-LAST-EXTERNAL",
)

CATALOG_PATH = Path("catalog")
PROXY_URL = "http://172.21.192.1:7890"

# 时间统一都是ns
MINUTE_NS = 60_000_000_000
DAY_NS = 86_400_000_000_000
BACKFILL_CHUNK = timedelta(days=1)

tz = ZoneInfo("Asia/Shanghai")

class EthCollectorConfig(DataActorConfig):
    def __init__(
            self,
            *,
            instrument_id: InstrumentId, #标识具体交易品种
            bar_type: BarType, #描述 K 线的数据类型和聚合规则
            catalog_path: str, #数据存储路径
            bootstrap_days: int, #采集从现在往前多少天数据
            flush_interval_secs: int, #刷盘时间间隔
            **_kwargs,
    ) -> None:
        super().__init__()
        self.instrument_id = instrument_id
        self.bar_type = bar_type
        self.catalog_path = catalog_path
        self.bootstrap_days = bootstrap_days
        self.flush_interval_secs = flush_interval_secs


class EthBarCollector(DataActor):
    def __init__(self, config: EthCollectorConfig) -> None:
        super().__init__(config)

        self._catalog_path = Path(config.catalog_path)
        self._catalog_path.mkdir(parents=True, exist_ok=True)
        self._catalog = ParquetDataCatalog(str(self._catalog_path))

        # 已经持久化的时间戳，用于去重。
        self._known_ts: set[int] = set()

        # 等待落盘的 K 线，以事件时间戳作为键。
        self._pending: dict[int, Bar] = {}

        self._instrument_ready = False
        self._was_disconnected = False

        self._load_existing_bars()

    def _load_existing_bars(self) -> None:
        try:
            bars = self._catalog.query_bars(
                identifiers=[str(self.config.bar_type)],
            )
        except Exception as exc:
            # 不把查询异常当成“空目录”，避免误判已有数据。
            raise RuntimeError(
                f"读取 Parquet 历史数据失败: {self._catalog_path}",
            ) from exc

        self._known_ts = {int(bar.ts_event) for bar in bars}

        if self._known_ts:
            latest = max(self._known_ts)
            self.log.info(
                f"Loaded {len(self._known_ts)} existing bars; "
                f"latest ts_event={latest}",
            )
        else:
            self.log.info("No existing bars; initial historical backfill required")
    # 启动阶段
    def on_start(self) -> None:
        # 监听连接状态；断线恢复后重新请求历史数据。
        # 监听完成调用 on_socket_state
        self.subscribe_socket_state()

        # 先获取合约定义，收到后调用 on_instrument 订阅 K 线。
        self.request_instrument(self.config.instrument_id)

        self.clock.set_timer(
            "eth_bar_collector.flush",
            timedelta(seconds=self.config.flush_interval_secs),
            callback=self._on_flush_timer,
        )

    # 收到合约定义时调用
    def on_instrument(self, instrument) -> None:
        if instrument.id != self.config.instrument_id:
            return

        if self._instrument_ready:
            return

        self._instrument_ready = True
        self.log.info(f"Instrument ready: {instrument.id}")

        # 先订阅实时数据，再请求历史数据。
        self.subscribe_bars(self.config.bar_type)

        now = self.clock.utc_now().astimezone(tz)
        if self._known_ts:
            # 向前重叠两分钟，避免边界遗漏；重复数据会被去重。
            last_ts = max(self._known_ts)
            start = datetime.fromtimestamp(
                max(0, last_ts - 2 * MINUTE_NS) / 1_000_000_000,
                tz=tz,
                )
        else:
            start = now - timedelta(days=self.config.bootstrap_days)
        self._request_backfill(start, now)

    def _request_backfill(self, start: datetime, end: datetime) -> None:
        self.log.info(
            f"Requesting historical bars: "
            f"bar_type={self.config.bar_type}, start={start}, end={end}"
        )
        if start >= end:
            return

        # 分段请求，避免一次请求跨度过大。
        cursor = start
        while cursor < end:
            chunk_end = min(cursor + BACKFILL_CHUNK, end)

            self.log.info(
                f"Requesting historical bars: {cursor.isoformat()} "
                f"to {chunk_end.isoformat()}",
            )

            self.request_bars(
                bar_type=self.config.bar_type,
                start=cursor,
                end=chunk_end,
            )
            cursor = chunk_end

    # 收到历史数据时调用
    def on_historical_bars(self, bars: Sequence[Bar]) -> None:
        accepted = 0

        for bar in bars:
            if self._validate_bar(bar):
                self._enqueue(bar)
                accepted += 1

        self.log.info(
            f"Historical response: received={len(bars)}, "
            f"accepted={accepted}, pending={len(self._pending)}",
        )

    # 收到实时k线时调用
    def on_bar(self, bar: Bar) -> None:
        if not self._validate_bar(bar):
            return

        # 如果实时数据中间出现时间缺口，主动请求缺失区间。
        latest_known = max(
            (*self._known_ts, *self._pending.keys()),
            default=None,
        )

        if (
                latest_known is not None
                and int(bar.ts_event) > latest_known + MINUTE_NS
        ):
            gap_start = datetime.fromtimestamp(
                (latest_known + MINUTE_NS) / 1_000_000_000,
                tz=tz,
                )
            gap_end = datetime.fromtimestamp(
                (int(bar.ts_event) - MINUTE_NS) / 1_000_000_000,
                tz=tz,
                )

            if gap_start <= gap_end:
                self.log.warning(
                    f"Detected bar gap: {gap_start.isoformat()} "
                    f"to {gap_end.isoformat()}",
                )
                self._request_backfill(gap_start, gap_end)

        self._enqueue(bar)

    def _validate_bar(self, bar: Bar) -> bool:
        try:
            o = bar.open.as_double()
            h = bar.high.as_double()
            low = bar.low.as_double()
            c = bar.close.as_double()
            volume = bar.volume.as_double()

            valid = (
                    low <= h
                    and low <= min(o, c)
                    and h >= max(o, c)
                    and volume >= 0
            )

            if not valid:
                self.log.warning(f"Invalid OHLCV bar rejected: {bar}")
            return valid

        except Exception as exc:
            self.log.warning(f"Bar validation failed: {exc}")
            return False

    def _enqueue(self, bar: Bar) -> None:
        ts = int(bar.ts_event)

        # 已落盘的时间戳不重复写。
        if ts in self._known_ts:
            return

        # 如果同一根尚未完成的 K 线多次更新，只保留最新版本。
        self._pending[ts] = bar

    def _on_flush_timer(self, event) -> None:
        self._flush_completed_bars()

    def _flush_completed_bars(self) -> None:
        now = self.clock.utc_now().astimezone(tz)

        # 只落盘当前分钟之前的 K 线，避免保存正在形成的 K 线。
        current_minute_ns = (
                int(now.replace(second=0, microsecond=0).timestamp())
                * 1_000_000_000
        )

        ready_ts = sorted(
            ts for ts in self._pending
            if ts < current_minute_ns
        )

        if not ready_ts:
            return

        ready = [self._pending[ts] for ts in ready_ts]

        try:
            self._catalog.write_bars(
                ready,
                skip_disjoint_check=True,
            )
        except Exception:
            self.log.exception(
                f"Parquet write failed for {len(ready)} bars; "
                "retaining pending data",
            )
            return

        for ts in ready_ts:
            self._known_ts.add(ts)
            del self._pending[ts]

        self.log.info(
            f"Persisted {len(ready)} bars; "
            f"total known timestamps={len(self._known_ts)}",
        )

    # 监听到连接状态变化时调用
    def on_socket_state(self, event) -> None:
        state = str(event.state).upper()

        self.log.info(
            f"Socket state: client={event.client_id}, "
            f"endpoint={event.endpoint}, state={state}",
        )

        if "DISCONNECTED" in state:
            self._was_disconnected = True
            return

        if (
                "CONNECTED" in state
                and "DISCONNECTED" not in state
                and self._was_disconnected
                and self._instrument_ready
        ):
            self._was_disconnected = False

            now = self.clock.utc_now().astimezone(tz)
            if self._known_ts:
                last_ts = max(self._known_ts)
                start = datetime.fromtimestamp(
                    max(0, last_ts - 2 * MINUTE_NS)
                    / 1_000_000_000,
                    tz=tz,
                    )
            else:
                start = now - timedelta(days=self.config.bootstrap_days)

            self.log.info("Socket reconnected; requesting backfill")
            self._request_backfill(start, now)

    # 程序停止时调用
    def on_stop(self) -> None:
        self.clock.cancel_timer("eth_bar_collector.flush")
        self._flush_completed_bars()
        self.log.info(
            f"Collector stopped; pending unclosed bars={len(self._pending)}",
        )


def main() -> None:
    node = (
        LiveNode.builder(
            "OKX-ETH-BAR-COLLECTOR",
            TraderId.from_str("ETH-COLLECTOR-001"),
            Environment.LIVE,
        )
        .add_data_client(
            None,
            OKXDataClientFactory(),
            OKXDataClientConfig(
                instrument_types=[OKXInstrumentType.SWAP],
                environment=OKXEnvironment.LIVE,
                proxy_url=PROXY_URL,
            ),
        )
        .build()
    )

    actor = EthBarCollector(
        EthCollectorConfig(
            instrument_id=INSTRUMENT_ID,
            bar_type=BAR_TYPE,
            catalog_path=str(CATALOG_PATH),
            bootstrap_days=7,
            flush_interval_secs=3600,
        ),
    )

    node.add_actor(actor) #node只能注册一种类型的actor
    node.run()


if __name__ == "__main__":
    main()