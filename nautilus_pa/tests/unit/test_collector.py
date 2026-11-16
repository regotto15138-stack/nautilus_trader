"""采集器的实时性与落盘窗口测试。

采集器继承 ``DataActor``，未注册到 trader 时 ``self.clock`` 不可用，因此用一个
固定时钟的子类驱动，其余逻辑全部走生产代码。覆盖与实时性直接相关的行为：

- 实时路径只接受**已收盘**的 K 线（未走完的蜡烛会反复推送，合并会把盘中
  数值写进 Parquet）；
- 落盘文件的时间区间取自 K 线窗口，而不是适配器的 ``ts_init``；
- 回补窗口是半开区间且不请求未来窗口；连接状态按精确值判断（子串判断会让
  重连永远不被识别）。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import pairwise
from typing import Any, ClassVar

import pytest

from helpers import INSTRUMENT_ID
from pa_trend.adapters.nautilus.collector import (
    BARS_PER_REQUEST,
    DEFAULT_BOOTSTRAP_DAYS,
    RESUME_LOOKBACK_PERIODS,
    MultiTimeframeBarCollector,
)
from pa_trend.domain.models.timeframe import Timeframe, dt_to_ns, floor_to_boundary

OPEN_15M = datetime(2026, 11, 16, 6, 30, tzinfo=UTC)
MIN15_KEY = f"{INSTRUMENT_ID}-15-MINUTE-LAST-EXTERNAL"


class _FakePrice:
    def __init__(self, value: object) -> None:
        self._value = Decimal(str(value))

    def as_decimal(self) -> Decimal:
        return self._value


class _FakeBar:
    """复刻采集器所需的 Nautilus Bar 接口（ts_event 为开盘时刻）。"""

    def __init__(
        self,
        *,
        ts_event: int,
        bar_type: str = MIN15_KEY,
        open_price: object = 3000,
        high: object = 3010,
        low: object = 2990,
        close: object = 3005,
        volume: object = 10,
        ts_init: int | None = None,
    ) -> None:
        self.bar_type = bar_type
        self.ts_event = ts_event
        # WebSocket 路径的 ts_init 是消息到达时间，与蜡烛窗口无关。
        self.ts_init = ts_event + 1 if ts_init is None else ts_init
        self.open = _FakePrice(open_price)
        self.high = _FakePrice(high)
        self.low = _FakePrice(low)
        self.close = _FakePrice(close)
        self.volume = _FakePrice(volume)


class _FakeBarType:
    def __init__(self, key: str) -> None:
        self._key = key

    def __str__(self) -> str:
        return self._key


class _FakeCatalog:
    """记录写入参数的最小 Parquet 目录替身。"""

    def __init__(self) -> None:
        self.writes: list[dict[str, Any]] = []

    def write_bars(
        self,
        bars: list[Any],
        *,
        start: int | None = None,
        end: int | None = None,
        skip_disjoint_check: bool = False,
    ) -> None:
        self.writes.append(
            {"bars": list(bars), "start": start, "end": end, "skip": skip_disjoint_check},
        )


class _PinnedCollector(MultiTimeframeBarCollector):
    """固定交易所时钟、记录收盘补拉排定的采集器。

    真实采集器由 LiveNode 注入时钟；测试里改用固定时刻，使收盘判定与定时器
    排定完全可控。除这两个入口外，所有逻辑都走生产代码。
    """

    fixed_now: ClassVar[datetime] = OPEN_15M
    scheduled: ClassVar[list[tuple[str, int]]] = []

    def _now(self) -> datetime:
        return self.fixed_now

    def _schedule_close_alert(self, key: str, alert_ns: int) -> None:
        # 定时器属于 Nautilus 运行时，这里只记录排定结果。
        self.scheduled.append((key, alert_ns))


@pytest.fixture(autouse=True)
def _reset_scheduled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_PinnedCollector, "scheduled", [])


def _make_collector(
    *,
    known: tuple[int, ...] = (),
    now: datetime | None = None,
) -> tuple[_PinnedCollector, _FakeCatalog]:
    collector = _PinnedCollector.__new__(_PinnedCollector)
    catalog = _FakeCatalog()
    collector.__dict__.update(
        {
            "_catalog": catalog,
            "_catalog_path": None,
            "_timeframes": {MIN15_KEY: Timeframe.MIN15},
            "_bar_type_by_key": {MIN15_KEY: _FakeBarType(MIN15_KEY)},
            "_bootstrap_days": {},
            "_session_offset": 8 * 60,
            "_known_ts": {MIN15_KEY: set(known)},
            "_pending": {MIN15_KEY: {}},
            "_instrument_ready": True,
            "_was_disconnected": False,
            "_flush_timer_name": "pa_trend.collector.flush",
            "_close_timer_prefix": "pa_trend.collector.close",
            "_close_timers": set(),
            "_max_close_fetch_periods": 60,
        },
    )
    if now is not None:
        collector.fixed_now = now
    return collector, catalog


def _bar(open_at: datetime, **kwargs: object) -> _FakeBar:
    return _FakeBar(ts_event=dt_to_ns(open_at), **kwargs)


def _collect_requests(
    collector: _PinnedCollector,
    monkeypatch: pytest.MonkeyPatch,
) -> list[tuple[datetime, datetime]]:
    requests: list[tuple[datetime, datetime]] = []
    monkeypatch.setattr(
        collector,
        "request_bars",
        lambda **kwargs: requests.append((kwargs["start"], kwargs["end"])),
    )
    return requests


class TestRealtimeBarAcceptance:
    def test_incomplete_bar_is_never_buffered(self) -> None:
        collector, catalog = _make_collector(now=OPEN_15M + timedelta(minutes=14))

        collector.on_bar(_bar(OPEN_15M, close=30099))

        assert collector._pending[MIN15_KEY] == {}
        collector._flush_completed_bars()
        assert catalog.writes == []

    def test_completed_bar_is_persisted_once(self) -> None:
        collector, catalog = _make_collector(now=OPEN_15M + timedelta(minutes=15))

        # 收盘瞬间 WebSocket 可能连推两次，只保留最后一版。
        collector.on_bar(_bar(OPEN_15M))
        collector.on_bar(_bar(OPEN_15M, close=3008))
        collector._flush_completed_bars()
        collector.fixed_now = OPEN_15M + timedelta(minutes=20)
        collector._flush_completed_bars()

        assert len(catalog.writes) == 1
        assert catalog.writes[0]["bars"][0].close.as_decimal() == Decimal("3008")
        assert collector._pending[MIN15_KEY] == {}

    def test_known_bar_is_not_rewritten(self) -> None:
        collector, catalog = _make_collector(
            known=(dt_to_ns(OPEN_15M),),
            now=OPEN_15M + timedelta(minutes=15),
        )

        collector.on_bar(_bar(OPEN_15M))
        collector._flush_completed_bars()

        assert catalog.writes == []

    def test_invalid_ohlcv_is_rejected(self) -> None:
        collector, catalog = _make_collector(now=OPEN_15M + timedelta(minutes=15))

        collector.on_bar(_bar(OPEN_15M, high=2995, low=2990, close=3000))
        collector._flush_completed_bars()

        assert catalog.writes == []

    def test_no_close_alert_before_first_bar(self) -> None:
        collector, _ = _make_collector(now=OPEN_15M)

        collector._schedule_close_fetch(MIN15_KEY)

        assert collector.scheduled == []


class TestFlushWindow:
    def test_window_uses_bar_open_and_close_not_ts_init(self) -> None:
        second_open = OPEN_15M + timedelta(minutes=15)
        arrival = second_open + timedelta(minutes=15)
        collector, catalog = _make_collector(now=arrival)

        collector.on_bar(_bar(OPEN_15M, ts_init=dt_to_ns(second_open)))
        collector.on_bar(_bar(second_open, ts_init=dt_to_ns(arrival)))
        collector._flush_completed_bars()

        write = catalog.writes[0]
        assert write["start"] == dt_to_ns(OPEN_15M)
        assert write["end"] == dt_to_ns(second_open + timedelta(minutes=15))
        assert write["skip"] is True

    def test_only_completed_bars_are_written(self) -> None:
        collector, catalog = _make_collector(now=OPEN_15M + timedelta(minutes=15))

        collector.on_bar(_bar(OPEN_15M))
        collector._flush_completed_bars()

        assert len(catalog.writes) == 1
        assert len(catalog.writes[0]["bars"]) == 1


class TestCloseFetch:
    def test_close_alert_uses_next_completed_period(self) -> None:
        collector, _ = _make_collector(
            known=(dt_to_ns(OPEN_15M),),
            now=OPEN_15M + timedelta(minutes=15),
        )

        collector._schedule_close_fetch(MIN15_KEY)

        assert collector.scheduled == [(MIN15_KEY, dt_to_ns(OPEN_15M + timedelta(minutes=30)))]

    def test_close_fetch_requests_the_completed_bar(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        collector, _ = _make_collector(
            known=(dt_to_ns(OPEN_15M),),
            now=OPEN_15M + timedelta(minutes=15),
        )
        requests = _collect_requests(collector, monkeypatch)
        # 收盘补拉发生在 06:45 窗口收完之后，只请求那一根已收盘的 K 线。
        collector.fixed_now = OPEN_15M + timedelta(hours=1)

        collector._on_close_timer(collector._bar_type_by_key[MIN15_KEY])

        # 从最后一根已存 K 线的收盘（06:45）补到现在（07:30），
        # 覆盖停机期间全部已收盘的 K 线。
        assert requests == [
            (OPEN_15M + timedelta(minutes=15), OPEN_15M + timedelta(hours=1)),
        ]
        # 排定记录被清除，下一次收盘可以重新排定。
        assert collector._close_timers == set()


class TestResumeStart:
    """重启续采起点必须覆盖全部停机缺口，而不是只回退两期。"""

    def test_empty_catalog_uses_bootstrap_days(self) -> None:
        now = OPEN_15M + timedelta(days=120)
        collector, _ = _make_collector(now=now)
        collector._bootstrap_days = dict(DEFAULT_BOOTSTRAP_DAYS)

        start = collector._resume_start(MIN15_KEY)

        # 15M 默认回补 90 天。
        assert start == floor_to_boundary(now - timedelta(days=90), Timeframe.MIN15)

    def test_short_restart_keeps_a_safety_margin(self) -> None:
        collector, _ = _make_collector(
            known=(dt_to_ns(OPEN_15M),),
            now=OPEN_15M + timedelta(minutes=15),
        )

        start = collector._resume_start(MIN15_KEY)

        # 缺口首期是 06:45，再往前退 RESUME_LOOKBACK_PERIODS 期。
        assert start == OPEN_15M + timedelta(
            minutes=15 * (1 - RESUME_LOOKBACK_PERIODS),
        )

    def test_long_outage_starts_at_the_first_missing_bar(self) -> None:
        """停机 8 期时，续采必须从缺口首期之前开始，覆盖整段缺口。

        真实回归：早期固定回退 2 期，停机期间产生的 K 线永远补不回来，
        目录里留下 06:45 缺口。
        """
        last_open = OPEN_15M + timedelta(hours=2)
        now = last_open + timedelta(minutes=15 * 8)
        collector, _ = _make_collector(known=(dt_to_ns(last_open),), now=now)

        start = collector._resume_start(MIN15_KEY)

        first_missing = last_open + timedelta(minutes=15)
        assert start <= first_missing
        # 窗口终点覆盖到「现在」，缺口中间没有遗漏。
        assert start < now

    @pytest.mark.parametrize("periods", [1, 4, 12, 96])
    def test_every_period_of_the_outage_is_inside_the_window(self, periods: int) -> None:
        last_open = OPEN_15M
        now = last_open + timedelta(minutes=15 * periods)
        collector, _ = _make_collector(known=(dt_to_ns(last_open),), now=now)

        start = collector._resume_start(MIN15_KEY)

        # 缺口内每一期（含最后一期已收盘的）都必须落在 [start, now) 内。
        missing = [last_open + timedelta(minutes=15 * offset) for offset in range(1, periods + 1)]
        assert all(start <= moment <= now for moment in missing)


class TestBackwardHistoryExtension:
    """已有目录也要能把历史向前补齐到设定的回补深度。"""

    def test_extends_when_stored_history_is_shorter_than_target(self) -> None:
        now = OPEN_15M + timedelta(days=10)
        earliest = OPEN_15M - timedelta(days=1)
        collector, _ = _make_collector(known=(dt_to_ns(earliest),), now=now)
        collector._bootstrap_days = {Timeframe.MIN15: 90}
        requests: list[tuple[datetime, datetime]] = []
        collector._request_backfill = lambda bar_type, start, end, **kw: requests.append(
            (start, end),
        )

        collector._extend_history_backwards(collector._bar_type_by_key[MIN15_KEY], now)

        expected_start = floor_to_boundary(now - timedelta(days=90), Timeframe.MIN15)
        assert requests == [(expected_start, earliest)]

    def test_does_nothing_when_history_is_deep_enough(self) -> None:
        now = OPEN_15M
        collector, _ = _make_collector(
            known=(dt_to_ns(OPEN_15M - timedelta(days=200)),),
            now=now,
        )
        collector._bootstrap_days = {Timeframe.MIN15: 90}
        requests: list[object] = []
        collector._request_backfill = lambda *a, **kw: requests.append(a)

        collector._extend_history_backwards(collector._bar_type_by_key[MIN15_KEY], now)

        assert requests == []

    def test_empty_catalog_is_left_to_bootstrap(self) -> None:
        collector, _ = _make_collector(now=OPEN_15M)
        collector._bootstrap_days = {Timeframe.MIN15: 90}
        requests: list[object] = []
        collector._request_backfill = lambda *a, **kw: requests.append(a)

        collector._extend_history_backwards(collector._bar_type_by_key[MIN15_KEY], OPEN_15M)

        assert requests == []


class TestHistoricalGapRepair:
    """重启时必须能修复已存历史中间的缺口（不只是末尾）。"""

    @staticmethod
    def _bars_at(*minutes: int) -> tuple[int, ...]:
        return tuple(dt_to_ns(OPEN_15M + timedelta(minutes=offset)) for offset in minutes)

    def test_contiguous_history_requests_nothing(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        collector, _ = _make_collector(known=self._bars_at(0, 15, 30, 45))
        requests = _collect_requests(collector, monkeypatch)

        collector._request_historical_gaps(
            collector._bar_type_by_key[MIN15_KEY],
            now=OPEN_15M + timedelta(hours=2),
        )

        assert requests == []

    def test_middle_gap_is_requested(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """真实回归：06:15 与 06:45 之间缺一根 06:30，必须请求该区间。"""
        collector, _ = _make_collector(known=self._bars_at(0, 15, 45, 60))
        requests = _collect_requests(collector, monkeypatch)

        collector._request_historical_gaps(
            collector._bar_type_by_key[MIN15_KEY],
            now=OPEN_15M + timedelta(hours=2),
        )

        assert requests == [(OPEN_15M + timedelta(minutes=15), OPEN_15M + timedelta(minutes=45))]

    def test_multiple_gaps_are_requested_separately(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        collector, _ = _make_collector(known=self._bars_at(0, 30, 45, 90))
        requests = _collect_requests(collector, monkeypatch)

        collector._request_historical_gaps(
            collector._bar_type_by_key[MIN15_KEY],
            now=OPEN_15M + timedelta(hours=3),
        )

        assert requests == [
            (OPEN_15M, OPEN_15M + timedelta(minutes=30)),
            (OPEN_15M + timedelta(minutes=45), OPEN_15M + timedelta(minutes=90)),
        ]

    def test_single_bar_history_is_skipped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        collector, _ = _make_collector(known=self._bars_at(0))
        requests = _collect_requests(collector, monkeypatch)

        collector._request_historical_gaps(
            collector._bar_type_by_key[MIN15_KEY],
            now=OPEN_15M + timedelta(hours=1),
        )

        assert requests == []


class TestBackfillWindow:
    def test_range_starts_at_floor_and_includes_end_boundary(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        collector, _ = _make_collector()
        requests = _collect_requests(collector, monkeypatch)

        collector._request_backfill(
            collector._bar_type_by_key[MIN15_KEY],
            start=OPEN_15M + timedelta(minutes=7),
            end=OPEN_15M + timedelta(minutes=45),
            now=OPEN_15M + timedelta(hours=6),
        )

        # 起点向下对齐；终点落在 06:45 边界上，包含从该时刻开始的 K 线，
        # 因此请求到 07:15 收盘为止。
        assert requests == [(OPEN_15M, OPEN_15M + timedelta(minutes=45))]

    def test_range_on_boundary_does_not_add_a_period(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        collector, _ = _make_collector()
        requests = _collect_requests(collector, monkeypatch)

        collector._request_backfill(
            collector._bar_type_by_key[MIN15_KEY],
            start=OPEN_15M,
            end=OPEN_15M + timedelta(minutes=45),
            now=OPEN_15M + timedelta(hours=6),
        )

        assert requests == [(OPEN_15M, OPEN_15M + timedelta(minutes=45))]

    @pytest.mark.parametrize(
        "offset",
        [
            timedelta(minutes=7, seconds=30),
            timedelta(minutes=13),
            timedelta(minutes=22, seconds=30),
            timedelta(minutes=45),
        ],
    )
    def test_request_end_is_capped_at_now(
        self,
        monkeypatch: pytest.MonkeyPatch,
        offset: timedelta,
    ) -> None:
        """无论现在走到哪里，请求终点都截断到 now，不请求未来窗口。"""
        collector, _ = _make_collector()
        requests = _collect_requests(collector, monkeypatch)
        now = OPEN_15M + offset

        collector._request_backfill(
            collector._bar_type_by_key[MIN15_KEY],
            start=OPEN_15M,
            end=OPEN_15M + timedelta(hours=3),
            now=now,
        )

        assert requests == [(OPEN_15M, now)]

    def test_empty_window_is_skipped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        collector, _ = _make_collector()
        requests = _collect_requests(collector, monkeypatch)

        collector._request_backfill(
            collector._bar_type_by_key[MIN15_KEY],
            start=OPEN_15M,
            end=OPEN_15M,
        )

        assert requests == []

    def test_chunks_overlap_by_one_period(self, monkeypatch: pytest.MonkeyPatch) -> None:
        collector, _ = _make_collector()
        requests = _collect_requests(collector, monkeypatch)
        # 两个整块再加 10 个周期，确保会分成多块。
        span = timedelta(minutes=15 * (2 * BARS_PER_REQUEST[Timeframe.MIN15] + 10))

        collector._request_backfill(
            collector._bar_type_by_key[MIN15_KEY],
            start=OPEN_15M,
            end=OPEN_15M + span,
            now=OPEN_15M + span,
        )

        assert len(requests) == 3
        for (_, previous_end), (next_start, _) in pairwise(requests):
            # 适配器按「收盘 <= end」过滤，严格首尾相接会丢掉边界 K 线。
            assert next_start == previous_end - timedelta(minutes=15)
        # 最后一块仍以目标终点收尾，且整体不超过 now。
        assert requests[-1][1] == OPEN_15M + span


class _SocketEvent:
    def __init__(self, state: str) -> None:
        self.state = state
        self.client_id = "OKX"
        self.endpoint = "wss://ws.okx.com"


class TestSocketReconnect:
    def test_reconnect_is_detected_from_exact_states(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        collector, _ = _make_collector(
            known=(dt_to_ns(OPEN_15M),),
            now=OPEN_15M + timedelta(hours=1),
        )
        requested: list[Any] = []
        monkeypatch.setattr(
            collector,
            "_request_backfill",
            lambda bar_type, start, end: requested.append((start, end)),
        )

        collector.on_socket_state(_SocketEvent("CONNECTED"))
        assert requested == []

        collector.on_socket_state(_SocketEvent("DISCONNECTED"))
        collector.on_socket_state(_SocketEvent("CONNECTED"))

        assert len(requested) == 1

    def test_unknown_state_does_not_trigger_backfill(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        collector, _ = _make_collector(
            known=(dt_to_ns(OPEN_15M),),
            now=OPEN_15M + timedelta(hours=1),
        )
        requested: list[Any] = []
        monkeypatch.setattr(
            collector,
            "_request_backfill",
            lambda bar_type, start, end: requested.append((start, end)),
        )

        collector.on_socket_state(_SocketEvent("DISCONNECTED"))
        collector.on_socket_state(_SocketEvent("RECONNECTING"))

        assert requested == []
