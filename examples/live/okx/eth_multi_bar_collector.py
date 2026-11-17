from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Sequence
from zoneinfo import ZoneInfo

from dateutil.relativedelta import relativedelta

from nautilus_trader.adapters.okx import OKX
from nautilus_trader.adapters.okx import OKXDataClientConfig
from nautilus_trader.adapters.okx import OKXDataClientFactory
from nautilus_trader.adapters.okx import OKXEnvironment
from nautilus_trader.adapters.okx import OKXInstrumentType
from nautilus_trader.common import DataActor
from nautilus_trader.common import Environment
from nautilus_trader.config import DataActorConfig
from nautilus_trader.live import LiveNode
from nautilus_trader.model import Bar, BarAggregation
from nautilus_trader.model import BarType
from nautilus_trader.model import InstrumentId
from nautilus_trader.model import TraderId
from nautilus_trader.persistence import ParquetDataCatalog

logging.basicConfig(level=logging.DEBUG)

INSTRUMENT_ID = InstrumentId.from_str(f"ETH-USDT-SWAP.{OKX}")
CATALOG_PATH = Path("catalog")
PROXY_URL = "http://172.21.192.1:7890"

# BarType 规格与实际周期长度。时间长度单位在内部统一转换为纳秒。
BAR_SPECS = [
    # ("1-MINUTE", timedelta(minutes=1)),
    # ("5-MINUTE", timedelta(minutes=5)),
    # ("15-MINUTE", timedelta(minutes=15)),
    # ("1-HOUR", timedelta(hours=1)),
    ("1-DAY", timedelta(days=1)),
    ("1-WEEK", timedelta(weeks=1)),
    ("1-MONTH", relativedelta(months=1)),
]

# 不同周期下采集天数, 避免全部使用365天
BOOTSTRAP_DAYS_BY_PERIOD = {
    "OKX-1-MINUTE": 7,
    "OKX-5-MINUTE": 30,
    "OKX-15-MINUTE": 90,
    "OKX-1-HOUR": 365,
    "OKX-1-DAY": 365,
    "OKX-1-WEEK": 365 * 3,
    "OKX-1-MONTH": 365 * 5,
}

BACKFILL_CHUNK = timedelta(days=1)
TZ = ZoneInfo("Asia/Shanghai")
NS_PER_SECOND = 1_000_000_000


class EthMultiCollectorConfig(DataActorConfig):
    def __init__(
        self,
        *,
        instrument_id: InstrumentId,
        bar_types: Sequence[BarType],
        interval_ns_by_bar_type: dict[str, int],
        catalog_path: str,
        flush_interval_secs: int = 10,
        **_kwargs,
    ) -> None:
        super().__init__()
        self.instrument_id = instrument_id
        self.bar_types = tuple(bar_types)
        self.interval_ns_by_bar_type = dict(interval_ns_by_bar_type)
        self.catalog_path = catalog_path
        self.flush_interval_secs = flush_interval_secs


class EthMultiBarCollector(DataActor):
    """One Actor collecting multiple bar types for a single instrument."""

    def __init__(self, config: EthMultiCollectorConfig) -> None:
        super().__init__(config)

        self._catalog_path = Path(config.catalog_path)
        self._catalog_path.mkdir(parents=True, exist_ok=True)
        self._catalog = ParquetDataCatalog(str(self._catalog_path))

        # Use the string representation as the key so callback bars can be routed
        # back to the matching per-period state.
        self._bar_type_by_key: dict[str, BarType] = {
            str(bar_type): bar_type for bar_type in config.bar_types
        }
        self._interval_ns_by_key = dict(config.interval_ns_by_bar_type)

        # Each period has its own persisted timestamps and pending bars.
        self._known_ts: dict[str, set[int]] = {
            key: set() for key in self._bar_type_by_key
        }
        self._pending: dict[str, dict[int, Bar]] = {
            key: {} for key in self._bar_type_by_key
        }

        self._instrument_ready = False
        self._was_disconnected = False
        self._flush_timer_name = "eth_multi_bar_collector.flush"

        self._load_existing_bars()

    def _load_existing_bars(self) -> None:
        for key, bar_type in self._bar_type_by_key.items():
            try:
                bars = self._catalog.query_bars(identifiers=[key])
            except Exception as exc:
                raise RuntimeError(
                    f"读取 Parquet 历史数据失败: path={self._catalog_path}, "
                    f"bar_type={key}",
                ) from exc

            timestamps = {int(bar.ts_event) for bar in bars}
            self._known_ts[key] = timestamps
            if timestamps:
                self.log.info(
                    f"Loaded existing bars: bar_type={key}, count={len(timestamps)}, "
                    f"latest_ts_event={max(timestamps)}",
                )
            else:
                self.log.info(f"No existing bars: bar_type={key}")

    def on_start(self) -> None:
        self.subscribe_socket_state()
        self.request_instrument(self.config.instrument_id)
        self.clock.set_timer(
            self._flush_timer_name,
            timedelta(seconds=self.config.flush_interval_secs),
            callback=self._on_flush_timer,
        )

    def on_instrument(self, instrument) -> None:
        if instrument.id != self.config.instrument_id or self._instrument_ready:
            return

        self._instrument_ready = True
        self.log.info(f"Instrument ready: {instrument.id}")
        now = self.clock.utc_now().astimezone(TZ)

        for key, bar_type in self._bar_type_by_key.items():
            self.subscribe_bars(bar_type)

            known = self._known_ts[key]
            interval_ns = self._interval_ns_by_key[key]

            if known:
                start_ns = max(0, max(known) - 2 * interval_ns)
                start = datetime.fromtimestamp(
                    start_ns / NS_PER_SECOND,
                    tz=TZ,
                    )
            else:
                period_key = str(bar_type).split("-LAST-")[0].split(".")[-1]
                days = BOOTSTRAP_DAYS_BY_PERIOD.get(period_key, 7)
                start = now - timedelta(days=days)

            self._request_backfill(bar_type, start, now)

    def _request_backfill(
        self,
        bar_type: BarType,
        start: datetime,
        end: datetime,
    ) -> None:
        key = str(bar_type)
        period = self._bar_period(bar_type)

        if period != "other":
            # 起点向下对齐，确保覆盖对应自然周期。
            start = self._align_period_boundary(start, period)

            # 终点向下对齐，只请求已经结束的自然周期。
            end = self._align_period_boundary(end, period)

        if start >= end:
            self.log.info(
                f"Skip backfill {key}: "
                f"aligned start {start} >= end {end}"
            )
            return

        self.log.info(
            f"Backfill {key}: start={start}, end={end}"
        )

        cursor = start

        while cursor < end:
            if period != "other":
                chunk_end = min(
                    self._next_period_boundary(cursor, period),
                    end,
                )
            else:
                chunk_end = min(
                    cursor + BACKFILL_CHUNK,
                    end,
                    )

            self.log.info(
                f"Request bars {key}: "
                f"start={cursor}, end={chunk_end}"
            )

            self.request_bars(
                bar_type=bar_type,
                start=cursor,
                end=chunk_end,
            )

            cursor = chunk_end

    def _bar_period(self, bar_type: BarType) -> str:
        """识别需要按自然周期对齐的 K 线。"""
        key = str(bar_type)

        if "-1-DAY-" in key:
            return "day"
        if "-1-WEEK-" in key:
            return "week"
        if "-1-MONTH-" in key:
            return "month"

        return "other"


    def _align_period_boundary(
            self,
            dt: datetime,
            period: str,
    ) -> datetime:
        """向下对齐到北京时间的自然周期起点。"""
        if dt.tzinfo is None:
            raise ValueError("datetime must be timezone-aware")

        dt = dt.astimezone(TZ)

        if period == "day":
            return dt.replace(
                hour=0, minute=0, second=0, microsecond=0
            )

        if period == "week":
            dt = dt - timedelta(days=dt.weekday())
            return dt.replace(
                hour=0, minute=0, second=0, microsecond=0
            )

        if period == "month":
            return dt.replace(
                day=1, hour=0, minute=0, second=0, microsecond=0
            )

        return dt


    def _next_period_boundary(
            self,
            dt: datetime,
            period: str,
    ) -> datetime:
        """计算下一个自然周期起点。"""
        if period == "day":
            return dt + timedelta(days=1)

        if period == "week":
            return dt + timedelta(days=7)

        if period == "month":
            if dt.month == 12:
                return dt.replace(
                    year=dt.year + 1,
                    month=1,
                    day=1,
                )
            return dt.replace(
                month=dt.month + 1,
                day=1,
            )

        return dt + BACKFILL_CHUNK

    def on_historical_bars(self, bars: Sequence[Bar]) -> None:
        counts: dict[str, int] = {}
        for bar in bars:
            key = str(bar.bar_type)
            if key not in self._pending:
                self.log.debug(f"Ignoring historical bar for unconfigured type: {key}")
                continue
            if self._validate_bar(bar):
                self._enqueue(key, bar)
                counts[key] = counts.get(key, 0) + 1

        self.log.info(
            f"Historical response: received={len(bars)}, accepted_by_type={counts}, "
            f"pending_by_type={ {key: len(value) for key, value in self._pending.items()} }",
        )

    def on_bar(self, bar: Bar) -> None:
        key = str(bar.bar_type)
        if key not in self._pending:
            self.log.debug(f"Ignoring real-time bar for unconfigured type: {key}")
            return
        if not self._validate_bar(bar):
            return

        interval_ns = self._interval_ns_by_key[key]
        known = self._known_ts[key]
        pending = self._pending[key]
        latest_known = max((*known, *pending.keys()), default=None)
        bar_ts = int(bar.ts_event)

        # Request missing bars only when this incoming bar is ahead of the latest
        # known/pending timestamp by more than one interval.
        if latest_known is not None and bar_ts > latest_known + interval_ns:
            gap_start = datetime.fromtimestamp(
                (latest_known + interval_ns) / NS_PER_SECOND,
                tz=TZ,
            )
            gap_end = datetime.fromtimestamp(
                (bar_ts - interval_ns) / NS_PER_SECOND,
                tz=TZ,
            )
            if gap_start <= gap_end:
                self.log.warning(
                    f"Detected bar gap: bar_type={key}, start={gap_start.isoformat()}, "
                    f"end={gap_end.isoformat()}",
                )
                self._request_backfill(self._bar_type_by_key[key], gap_start, gap_end)

        self._enqueue(key, bar)

    def _validate_bar(self, bar: Bar) -> bool:
        try:
            o = bar.open.as_double()
            h = bar.high.as_double()
            low = bar.low.as_double()
            c = bar.close.as_double()
            volume = bar.volume.as_double()
            valid = low <= h and low <= min(o, c) and h >= max(o, c) and volume >= 0
            if not valid:
                self.log.warning(f"Invalid OHLCV bar rejected: {bar}")
            return valid
        except Exception as exc:
            self.log.warning(f"Bar validation failed: {exc}")
            return False

    def _enqueue(self, key: str, bar: Bar) -> None:
        ts = int(bar.ts_event)
        if ts in self._known_ts[key]:
            return
        # If the same not-yet-persisted candle is updated, keep the latest version.
        self._pending[key][ts] = bar

    def _on_flush_timer(self, event) -> None:
        self._flush_completed_bars()

    def _flush_completed_bars(self) -> None:
        now_ns = int(self.clock.utc_now().timestamp() * NS_PER_SECOND)

        for key, pending in self._pending.items():
            ready_ts = sorted(
                ts for ts in pending
                if self._bar_end_ns(key, ts) <= now_ns
            )
            if not ready_ts:
                continue

            ready = [pending[ts] for ts in ready_ts]
            try:
                self._catalog.write_bars(ready, skip_disjoint_check=True)
            except Exception:
                self.log.exception(
                    f"Parquet write failed: bar_type={key}, count={len(ready)}; "
                    "retaining pending data",
                )
                continue

            for ts in ready_ts:
                self._known_ts[key].add(ts)
                del pending[ts]

            self.log.info(
                f"Persisted bars: bar_type={key}, count={len(ready)}, "
                f"known_timestamps={len(self._known_ts[key])}, "
                f"pending={len(pending)}",
            )

    def on_socket_state(self, event) -> None:
        state = str(event.state).upper()
        self.log.info(
            f"Socket state: client={event.client_id}, endpoint={event.endpoint}, "
            f"state={state}",
        )

        if "DISCONNECTED" in state:
            self._was_disconnected = True
            return

        if not (
            "CONNECTED" in state
            and "DISCONNECTED" not in state
            and self._was_disconnected
            and self._instrument_ready
        ):
            return

        self._was_disconnected = False
        now = self.clock.utc_now().astimezone(TZ)
        self.log.info("Socket reconnected; requesting backfill for all configured bar types")

        for key, bar_type in self._bar_type_by_key.items():
            known = self._known_ts[key]
            interval_ns = self._interval_ns_by_key[key]
            if known:
                start_ns = max(0, max(known) - 2 * interval_ns)
                start = datetime.fromtimestamp(start_ns / NS_PER_SECOND, tz=TZ)
            else:
                period_key = str(bar_type).split("-LAST-")[0].split(".")[-1]
                days = BOOTSTRAP_DAYS_BY_PERIOD.get(period_key, 7)
                start = now - timedelta(days=days)
            self._request_backfill(bar_type, start, now)

    def on_stop(self) -> None:
        self.clock.cancel_timer(self._flush_timer_name)
        self._flush_completed_bars()
        self.log.info(
            "Collector stopped; pending bars by type="
            f"{ {key: len(value) for key, value in self._pending.items()} }",
        )

    def _bar_end_ns(self, key: str, ts_ns: int) -> int:
        start = datetime.fromtimestamp(
            ts_ns / NS_PER_SECOND,
            tz=TZ,
            )

        if "-1-MONTH-" in key:
            end = start + relativedelta(months=1)
        elif "-1-WEEK-" in key:
            end = start + timedelta(weeks=1)
        else:
            interval_ns = self._interval_ns_by_key[key]
            end = start + timedelta(
                seconds=interval_ns / NS_PER_SECOND
            )

        return int(end.timestamp() * NS_PER_SECOND)

def main() -> None:
    bar_types = [
        BarType.from_str(f"{INSTRUMENT_ID}-{bar_spec}-LAST-EXTERNAL")
        for bar_spec, _interval in BAR_SPECS
    ]
    interval_ns_by_bar_type = {
        str(bar_type): (
            None
            if isinstance(interval, relativedelta)
            else int(interval.total_seconds() * NS_PER_SECOND)
        )
        for bar_type, interval in zip(
            bar_types,
            [interval for _, interval in BAR_SPECS],
        )
    }

    node = (
        LiveNode.builder(
            "OKX-ETH-MULTI-BAR-COLLECTOR",
            TraderId.from_str("ETH-COLLECTOR"),
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

    actor = EthMultiBarCollector(
        EthMultiCollectorConfig(
            instrument_id=INSTRUMENT_ID,
            bar_types=bar_types,
            interval_ns_by_bar_type=interval_ns_by_bar_type,
            catalog_path=str(CATALOG_PATH),
            flush_interval_secs=10,
        ),
    )
    node.add_actor(actor)  # 只注册一次 Actor
    node.run()


if __name__ == "__main__":
    main()
