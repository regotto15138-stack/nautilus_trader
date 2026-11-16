"""面向 OKX 的多周期 K 线采集器，写入 Nautilus Parquet 数据目录。

改编自 ``examples/live/okx/eth_multi_bar_collector.py``，保留了其中关键的机制：
按时间戳去重、在周期收盘前缓存、定时落盘、检测并回补缺口、断线重连后重新回补。

按冻结的策略规格做了两处调整：

- 回补对齐使用 UTC，而不是本地交易时段时区，因为规格第 1.5 节把研究边界
  固定在 UTC。
- 月、周、日的周期长度取自共用的时间框架辅助函数，避免采集器与分析引擎
  各自实现导致口径漂移。

实时性语义
----------

- 只接受**已收盘**的 K 线：WebSocket 路径会收到反复推送的未完成蜡烛，合并
  它们会把限价与成交量写进 Parquet；实时路径因此以本地推导的窗口收盘时刻
  为准（``bar_window_ns``），历史接口返回的则都是定稿蜡烛。
- 每个周期的收盘时刻安排一次补拉，即使 WebSocket 订阅恰好漏掉那根 K 线，
  也会在一个刷新周期内从历史接口补上。
- 重启时按 Parquet 中最后一个已存 K 线的开盘时刻续采，因此停机期间产生的
  K 线会在下一次启动时补齐，而不是从「现在」重新开始。
- 落盘时间窗口取自实际写入的 K 线，而不是适配器给出的 ``ts_init``（WebSocket
  路径下它是消息到达时间），否则文件区间会错位并掩盖后续写入。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from pathlib import Path

from nautilus_trader.adapters.okx import (
    OKXDataClientConfig,
    OKXDataClientFactory,
    OKXEnvironment,
    OKXInstrumentType,
)
from nautilus_trader.common import DataActor, Environment
from nautilus_trader.config import DataActorConfig
from nautilus_trader.live import LiveNode
from nautilus_trader.model import Bar, BarType, InstrumentId, TraderId
from nautilus_trader.persistence import ParquetDataCatalog

from pa_trend.adapters.nautilus.bar_converter import bar_window_ns
from pa_trend.domain.models.timeframe import (
    Timeframe,
    add_periods,
    dt_to_ns,
    floor_to_boundary,
    ns_to_dt,
)

# 单次 request_bars 覆盖的周期数。按「一次一个周期」分块会导致采 5 年日线
# 发出约 1825 次请求；OKX 蜡烛接口单次可返回数百根，因此这里按批合并。
# 分钟级历史接口单次上限较低，故单独收紧。
BARS_PER_REQUEST: dict[Timeframe, int] = {
    Timeframe.MONTH: 300,
    Timeframe.WEEK: 300,
    Timeframe.DAY: 300,
    Timeframe.HOUR4: 300,
    Timeframe.HOUR1: 300,
    Timeframe.MIN15: 100,
    Timeframe.MIN3: 100,
}

#: 目录为空时各周期默认回补的天数（分钟级只回补较短区间）。
DEFAULT_BOOTSTRAP_DAYS: dict[Timeframe, int] = {
    Timeframe.MONTH: 365 * 5,
    Timeframe.WEEK: 365 * 3,
    Timeframe.DAY: 365,
    Timeframe.HOUR4: 120,
    Timeframe.HOUR1: 30,
    Timeframe.MIN15: 7,
    Timeframe.MIN3: 2,
}

#: 重启续采时最少回看的周期数。
#:
#: 正常重启从最后一根已存 K 线往回取一个「安全余量」，避免恰好截断在边界上；
#: 停机较久时按实际间隔放大，否则停机期间产生的 K 线不会全部补齐。
#: 单次补拉另有 ``self._max_close_fetch_periods`` 上限，防止异常时间戳一次
#: 请求过多历史。
RESUME_LOOKBACK_PERIODS = 3


class BarCollectorConfig(DataActorConfig):
    """:class:`MultiTimeframeBarCollector` 的配置。"""

    def __init__(
        self,
        *,
        instrument_id: InstrumentId,
        bar_types: Sequence[BarType],
        timeframes_by_bar_type: dict[str, Timeframe],
        catalog_path: str,
        bootstrap_days_by_timeframe: dict[Timeframe, int] | None = None,
        flush_interval_secs: int = 10,
        session_offset_minutes: int = 8 * 60,
        **_kwargs: object,
    ) -> None:
        """初始化配置。

        参数
        ----
        instrument_id : InstrumentId
            要采集的合约。
        bar_types : Sequence of BarType
            要采集并持久化的全部 K 线类型。
        timeframes_by_bar_type : dict
            把 ``str(bar_type)`` 映射到对应 :class:`Timeframe`。
        catalog_path : str
            Parquet 数据目录。
        bootstrap_days_by_timeframe : dict 或 None
            数据目录尚无历史时请求的回溯天数。
        flush_interval_secs : int
            落盘定时器间隔。
        session_offset_minutes : int
            交易所会话边界偏移（分钟）。OKX 为 UTC+8，故默认 480；该值只影响
            月线等自然周期窗口的收盘推导，不影响 K 线本身的时间戳。
        """
        super().__init__()
        self.instrument_id = instrument_id
        self.bar_types = tuple(bar_types)
        self.timeframes_by_bar_type = dict(timeframes_by_bar_type)
        self.catalog_path = catalog_path
        self.bootstrap_days_by_timeframe = dict(
            bootstrap_days_by_timeframe or DEFAULT_BOOTSTRAP_DAYS,
        )
        self.flush_interval_secs = flush_interval_secs
        self.session_offset_minutes = session_offset_minutes


class MultiTimeframeBarCollector(DataActor):
    """把单个合约的多种 K 线采集到 Parquet 数据目录。"""

    def __init__(self, config: BarCollectorConfig) -> None:
        """初始化采集器。

        参数
        ----
        config : BarCollectorConfig
            采集器配置。
        """
        super().__init__(config)

        self._catalog_path = Path(config.catalog_path)
        self._catalog_path.mkdir(parents=True, exist_ok=True)
        self._catalog = ParquetDataCatalog(str(self._catalog_path))

        self._timeframes = dict(config.timeframes_by_bar_type)
        self._bar_type_by_key = {str(item): item for item in config.bar_types}
        self._bootstrap_days = dict(config.bootstrap_days_by_timeframe)
        self._session_offset = config.session_offset_minutes

        self._known_ts: dict[str, set[int]] = {key: set() for key in self._bar_type_by_key}
        self._pending: dict[str, dict[int, Bar]] = {key: {} for key in self._bar_type_by_key}

        self._instrument_ready = False
        self._was_disconnected = False
        self._flush_timer_name = "pa_trend.collector.flush"
        self._close_timer_prefix = "pa_trend.collector.close"
        # 已经排定收盘补拉的周期，避免每根实时 K 线都重设定时器。
        self._close_timers: set[str] = set()
        # 单次收盘补拉最多请求几个周期，防止长停机后一次拉取过多历史。
        self._max_close_fetch_periods = 60

        self._load_existing_bars()

    def _load_existing_bars(self) -> None:
        for key in self._bar_type_by_key:
            bars = self._catalog.query_bars(identifiers=[key])
            timestamps = {int(bar.ts_event) for bar in bars}
            self._known_ts[key] = timestamps
            if timestamps:
                self.log.info(
                    f"Loaded existing bars: bar_type={key} count={len(timestamps)} "
                    f"latest_ts_event={max(timestamps)}",
                )
            else:
                self.log.info(f"No existing bars: bar_type={key}")

    def on_start(self) -> None:
        """订阅连接状态、请求合约信息，并启动定时落盘。"""
        self.subscribe_socket_state()
        # 通过 ImportableActorConfig 装配时，配置项会经 JSON 往返变成字符串，
        # 而 request_instrument 只接受 InstrumentId 或其序列。
        self.request_instrument(InstrumentId.from_str(str(self.config.instrument_id)))
        self.clock.set_timer(
            self._flush_timer_name,
            timedelta(seconds=self.config.flush_interval_secs),
            callback=self._on_flush_timer,
        )

    def on_instrument(self, instrument: object) -> None:
        """拿到合约信息后订阅全部 K 线类型。"""
        instrument_id = getattr(instrument, "id", None)
        if str(instrument_id) != str(self.config.instrument_id) or self._instrument_ready:
            return

        self._instrument_ready = True
        self.log.info(f"Instrument ready: {instrument_id}")
        now = self._now()

        for key, bar_type in self._bar_type_by_key.items():
            self.subscribe_bars(bar_type)
            try:
                self._request_backfill(bar_type, self._resume_start(key), now)
                self._request_historical_gaps(bar_type, now)
            except Exception:
                # 单个周期回补失败不能让其余周期失去订阅与回补机会。
                self.log.exception(f"Backfill failed at startup: {key}")

    def _resume_start(self, key: str) -> datetime:
        """按已存历史与停机时长推算回补起点。

        ``_known_ts`` 中保存的是 ``ts_event``，即蜡烛**开盘**时刻。固定回退几个
        周期是不够的：停机期间产生的 K 线会落在回退窗口之外，重启后既不会被
        回补、也不会被后续收盘补拉覆盖（补拉只从最后一根已存 K 线往后补），
        结果留下永久缺口。因此窗口从「缺口首期」再往前退
        :data:`RESUME_LOOKBACK_PERIODS` 个周期：

        - 刚重启（缺口为空）：回看最后一根附近的若干期，覆盖边界误差；
        - 停机 N 期：从缺口首期回看，整段缺口都被请求到。
        """
        timeframe = self._timeframes[key]
        known = self._known_ts[key]
        if not known:
            now = self._now()
            days = self._bootstrap_days.get(timeframe, 7)
            return floor_to_boundary(now - timedelta(days=days), timeframe)

        last_open = ns_to_dt(max(known))
        first_missing = add_periods(last_open, timeframe, 1)
        return floor_to_boundary(
            add_periods(first_missing, timeframe, -RESUME_LOOKBACK_PERIODS),
            timeframe,
        )

    def _request_historical_gaps(self, bar_type: BarType, now: datetime) -> None:
        """重启时补齐已存历史中间的缺口。

        续采只从**最后一根**已存 K 线往后补，因此早先运行遗留的中间缺口不会
        自行修复。这里按已存时间戳扫描一次，逐段请求缺失区间。
        """
        key = str(bar_type)
        timeframe = self._timeframes[key]
        known = sorted(self._known_ts[key])
        if len(known) < 2:
            return

        gap_count = 0
        for previous, current in pairwise(known):
            # 上一根的收盘时刻就是下一根应有的开盘时刻。
            _, previous_close = bar_window_ns(
                previous,
                timeframe,
                session_offset_minutes=self._session_offset,
            )
            if previous_close >= current:
                continue
            gap_count += 1
            gap_start = ns_to_dt(previous)
            gap_end = ns_to_dt(current)
            self.log.warning(
                f"Detected historical gap: bar_type={key} "
                f"start={gap_start.isoformat()} end={gap_end.isoformat()}",
            )
            self._request_backfill(bar_type, gap_start, gap_end, now=now)
        if gap_count:
            self.log.info(f"Requested {gap_count} historical gap(s): bar_type={key}")

    def _request_backfill(
        self,
        bar_type: BarType,
        start: datetime,
        end: datetime,
        *,
        now: datetime | None = None,
    ) -> None:
        """请求 ``[start, end)`` 内的历史 K 线，按单次上限分块。

        ``now`` 供调用方显式指定当前时刻；缺省取交易所时钟。运行时要求
        ``start <= end <= now``，因此每个分块的终点都会再截断到实际现在时刻：
        否则把窗口终点对齐到「下一根 K 线收盘」时会落进未来，直接抛
        ``end was > now`` 并中断全部回补。

        窗口按周期边界向下对齐：``end`` 落在边界上表示「到边界为止」，落在
        边界之间表示「含该边界开始的那根 K 线」，因此一次窗口恰好覆盖
        ``[start, end)`` 中开盘的每一根 K 线。
        """
        key = str(bar_type)
        timeframe = self._timeframes[key]
        cutoff = now if now is not None else self._now()

        aligned_start = floor_to_boundary(start, timeframe)
        if floor_to_boundary(end, timeframe) != end:
            end = add_periods(floor_to_boundary(end, timeframe), timeframe, 1)
        if aligned_start >= end:
            self.log.info(f"Skip backfill {key}: aligned start {aligned_start} >= end {end}")
            return
        start = aligned_start

        self.log.info(f"Backfill {key}: start={start} end={end}")
        cursor = start
        while cursor < end:
            chunk_end = min(
                add_periods(cursor, timeframe, BARS_PER_REQUEST[timeframe]),
                end,
                cutoff,
            )
            if chunk_end <= cursor:
                # 起点已到（或越过）现在：剩余窗口尚未开始，无法请求。
                self.log.info(f"Stop backfill {key}: cursor {cursor} >= now {cutoff}")
                break
            self.log.info(f"Request bars {key}: start={cursor} end={chunk_end}")
            self.request_bars(bar_type=bar_type, start=cursor, end=chunk_end)
            if chunk_end >= end or chunk_end >= cutoff:
                break
            # OKX 适配器按「开盘 >= start 且 收盘 <= end」双重过滤，若严格首尾相接，
            # 收盘正好落在 chunk_end 的那根 K 线会被两块同时排除而丢失。因此让下一块
            # 回退一个周期形成重叠（重复的 K 线由按时间戳去重的逻辑自动合并）。
            next_cursor = add_periods(chunk_end, timeframe, -1)
            cursor = next_cursor if next_cursor > cursor else chunk_end

    def on_historical_bars(self, bars: Sequence[Bar]) -> None:
        """缓存通过校验的历史 K 线。"""
        counts: dict[str, int] = {}
        for bar in bars:
            key = str(bar.bar_type)
            if key not in self._pending:
                self.log.debug(f"Ignoring historical bar for unconfigured type: {key}")
                continue
            if self._validate_bar(bar):
                self._enqueue(key, bar)
                counts[key] = counts.get(key, 0) + 1

        self.log.info(f"Historical response: received={len(bars)} accepted_by_type={counts}")

    def on_bar(self, bar: Bar) -> None:
        """缓存已收盘的实时 K 线，并在发现缺口时请求回补。"""
        key = str(bar.bar_type)
        if key not in self._pending:
            self.log.debug(f"Ignoring real-time bar for unconfigured type: {key}")
            return
        if not self._validate_bar(bar):
            return

        now_ns = dt_to_ns(self._now())
        if self._bar_complete_ns(key, int(bar.ts_event)) > now_ns:
            # 未走完的蜡烛会被反复推送；合并它们会把盘中限价与成交量写进
            # Parquet，因此实时路径只接受已收盘的 K 线。
            self.log.debug(f"Ignoring incomplete real-time bar: {bar}")
            self._schedule_close_fetch(key)
            return

        timeframe = self._timeframes[key]
        known = self._known_ts[key]
        pending = self._pending[key]
        latest_known = max((*known, *pending.keys()), default=None)
        bar_ts = int(bar.ts_event)

        if latest_known is not None:
            expected_next = dt_to_ns(
                add_periods(ns_to_dt(latest_known), timeframe, 1),
            )
            if bar_ts > expected_next:
                gap_start = ns_to_dt(expected_next)
                gap_end = ns_to_dt(bar_ts)
                self.log.warning(
                    f"Detected bar gap: bar_type={key} "
                    f"start={gap_start.isoformat()} end={gap_end.isoformat()}",
                )
                self._request_backfill(self._bar_type_by_key[key], gap_start, gap_end)

        self._enqueue(key, bar)
        self._schedule_close_fetch(key)

    def _validate_bar(self, bar: Bar) -> bool:
        try:
            open_price = bar.open.as_decimal()
            high = bar.high.as_decimal()
            low = bar.low.as_decimal()
            close = bar.close.as_decimal()
            volume = bar.volume.as_decimal()
        except Exception:
            self.log.exception(f"Bar value extraction failed: {bar}")
            return False

        valid = (
            low <= high
            and low <= min(open_price, close)
            and high >= max(open_price, close)
            and volume >= 0
        )
        if not valid:
            self.log.warning(f"Invalid OHLCV bar rejected: {bar}")
        return valid

    def _enqueue(self, key: str, bar: Bar) -> None:
        ts = int(bar.ts_event)
        if ts in self._known_ts[key]:
            return
        # 尚未走完的蜡烛会被反复推送，只保留最新一次修订。
        self._pending[key][ts] = bar

    def _on_flush_timer(self, event: object) -> None:
        self._flush_completed_bars()

    def _bar_complete_ns(self, key: str, ts_event: int) -> int:
        _, close_ns = bar_window_ns(
            ts_event,
            self._timeframes[key],
            session_offset_minutes=self._session_offset,
        )
        return close_ns

    def _now(self) -> datetime:
        """返回交易所时钟的当前 UTC 时刻。"""
        return self.clock.utc_now().astimezone(UTC)

    def _schedule_close_fetch(self, key: str) -> None:
        """在该周期下一次收盘后补拉一次历史 K 线。

        WebSocket 订阅偶尔会漏掉某一根收盘 K 线；收盘后从历史接口补拉，
        可以让每个已存 K 线在一个刷新周期内定稿。
        """
        if key in self._close_timers:
            return
        alert_ns = self._next_close_after(key, dt_to_ns(self._now()))
        if alert_ns is None:
            return

        self._close_timers.add(key)
        self._schedule_close_alert(key, alert_ns)

    def _schedule_close_alert(self, key: str, alert_ns: int) -> None:
        """把收盘补拉排定到交易所时钟上。"""
        self.clock.set_time_alert_ns(
            f"{self._close_timer_prefix}:{key}",
            alert_ns,
            callback=lambda event, bar_type=self._bar_type_by_key[key]: self._on_close_timer(
                bar_type
            ),
        )

    def _next_close_after(self, key: str, now_ns: int) -> int | None:
        """返回 ``now_ns`` 之后第一个已存 K 线的收盘时刻。"""
        known = self._known_ts[key]
        if not known:
            return None
        latest_close_ns = self._bar_complete_ns(key, max(known))
        if latest_close_ns <= now_ns:
            return latest_close_ns + self._period_ns(key, latest_close_ns)
        return latest_close_ns

    def _period_ns(self, key: str, open_ns: int) -> int:
        """返回本周期这根 K 线的窗口长度（纳秒）。"""
        open_, close = bar_window_ns(
            open_ns,
            self._timeframes[key],
            session_offset_minutes=self._session_offset,
        )
        return close - open_

    def _on_close_timer(self, bar_type: BarType) -> None:
        """周期收盘后补拉最近若干根 K 线，覆盖 WebSocket 漏推的情况。"""
        key = str(bar_type)
        self._close_timers.discard(key)
        now = self._now()
        known = self._known_ts[key]
        if not known:
            self._request_backfill(bar_type, self._resume_start(key), now)
            return

        timeframe = self._timeframes[key]
        gap_start = floor_to_boundary(
            ns_to_dt(self._bar_complete_ns(key, max(known))),
            timeframe,
        )
        # 长停机后缺口可能很长：单次最多推进固定周期数，其余部分由后续收盘
        # 补拉或下一次启动继续补齐，避免一次发出成百上千个请求。
        max_span = add_periods(gap_start, timeframe, self._max_close_fetch_periods)
        end = now if max_span >= now else max_span
        if end < now:
            self.log.info(
                f"Close fetch capped at {self._max_close_fetch_periods} periods: "
                f"bar_type={key} start={gap_start} end={end}",
            )
        self._request_backfill(bar_type, gap_start, end)

    def _flush_completed_bars(self, now: datetime | None = None) -> None:
        """把已收盘的 K 线写入 Parquet。

        ``now`` 供调用方显式指定当前时刻（停止时用它把缓冲全部落盘）；
        缺省取交易所时钟。
        """
        now_ns = dt_to_ns(now if now is not None else self._now())

        for key, pending in self._pending.items():
            ready_ts = sorted(ts for ts in pending if self._bar_complete_ns(key, ts) <= now_ns)
            if not ready_ts:
                continue

            ready = [pending[ts] for ts in ready_ts]
            start_ns = min(int(bar.ts_event) for bar in ready)
            last_open_ns = max(int(bar.ts_event) for bar in ready)
            end_ns = self._bar_complete_ns(key, last_open_ns)
            try:
                # 文件区间取自实际 K 线窗口：适配器的 ts_init 在 WebSocket 路径下
                # 是消息到达时间，用它命名会让区间错位并掩盖后续写入。
                self._catalog.write_bars(
                    ready,
                    start=start_ns,
                    end=end_ns,
                    skip_disjoint_check=True,
                )
            except Exception:
                self.log.exception(
                    f"Parquet write failed: bar_type={key} count={len(ready)}; "
                    "retaining pending data",
                )
                continue

            for ts in ready_ts:
                self._known_ts[key].add(ts)
                del pending[ts]

            self.log.info(
                f"Persisted bars: bar_type={key} count={len(ready)} "
                f"known={len(self._known_ts[key])} pending={len(pending)}",
            )

    def on_socket_state(self, event: object) -> None:
        """断线重连后对全部 K 线类型重新回补。

        适配器的连接状态只取 ``CONNECTED`` / ``DISCONNECTED``，早期版本用子串
        判断 ``"DISCONNECTED"``，导致重连永远不被识别、断线期间的 K 线要等到
        重启或下一次实时推送才补上。
        """
        state = str(getattr(event, "state", "")).upper()
        self.log.info(
            f"Socket state: client={getattr(event, 'client_id', None)} state={state}",
        )

        if state == "DISCONNECTED":
            self._was_disconnected = True
            return

        if state != "CONNECTED" or not self._was_disconnected or not self._instrument_ready:
            return

        self._was_disconnected = False
        now = self._now()
        self.log.info("Socket reconnected; requesting backfill for all bar types")

        for key, bar_type in self._bar_type_by_key.items():
            try:
                self._request_backfill(bar_type, self._resume_start(key), now)
            except Exception:
                self.log.exception(f"Backfill failed after reconnect: {key}")

    def on_stop(self) -> None:
        """取消定时器并把已就绪的数据落盘。"""
        self.clock.cancel_timer(self._flush_timer_name)
        for key in sorted(self._close_timers):
            self.clock.cancel_timer(f"{self._close_timer_prefix}:{key}")
        self._close_timers.clear()
        self._flush_completed_bars()
        self.log.info(
            "Collector stopped; pending by type="
            f"{ {key: len(value) for key, value in self._pending.items()} }",
        )


def build_live_node(
    *,
    node_name: str,
    trader_id: str,
    bar_types: Sequence[BarType],
    timeframes_by_bar_type: dict[str, Timeframe],
    instrument_id: InstrumentId,
    catalog_path: str,
    proxy_url: str | None = None,
    session_offset_minutes: int = 8 * 60,
) -> LiveNode:
    """构建已接入 OKX 数据客户端与采集器的实盘节点。

    参数
    ----
    node_name : str
        实盘节点名称。
    trader_id : str
        Trader 标识字符串。
    bar_types : Sequence of BarType
        要采集的 K 线类型。
    timeframes_by_bar_type : dict
        把 ``str(bar_type)`` 映射到对应周期。
    instrument_id : InstrumentId
        要采集的合约。
    catalog_path : str
        Parquet 数据目录。
    proxy_url : str 或 None
        OKX 客户端可选的 HTTP 代理。

    返回
    ----
    LiveNode
        已注册采集器的节点。
    """
    node = (
        LiveNode.builder(
            node_name,
            TraderId.from_str(trader_id),
            Environment.LIVE,
        )
        .add_data_client(
            None,
            OKXDataClientFactory(),
            OKXDataClientConfig(
                instrument_types=[OKXInstrumentType.SWAP],
                environment=OKXEnvironment.LIVE,
                proxy_url=proxy_url,
            ),
        )
        .build()
    )

    collector = MultiTimeframeBarCollector(
        BarCollectorConfig(
            instrument_id=instrument_id,
            bar_types=bar_types,
            timeframes_by_bar_type=timeframes_by_bar_type,
            catalog_path=catalog_path,
            session_offset_minutes=session_offset_minutes,
        ),
    )
    node.add_actor(collector)
    return node
