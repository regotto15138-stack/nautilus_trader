"""K 线转换测试，使用仿 Nautilus 的桩对象。

``bar_converter`` 仅在 ``TYPE_CHECKING`` 下导入 NautilusTrader，因此用一个鸭子类型
的小桩即可在无需编译扩展的情况下覆盖转换逻辑。
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from helpers import INSTRUMENT_ID, dec
from pa_trend.adapters.nautilus.bar_converter import bar_window_ns, to_domain_bar
from pa_trend.domain.errors import BarAlignmentError
from pa_trend.domain.models.timeframe import Timeframe, dt_to_ns


class _FakePrice:
    def __init__(self, value: object) -> None:
        self._value = Decimal(str(value))

    def as_decimal(self) -> Decimal:
        return self._value


class _FakeInstrumentId:
    def __str__(self) -> str:
        return INSTRUMENT_ID


class _FakeBarType:
    def __init__(self) -> None:
        self.instrument_id = _FakeInstrumentId()


class _FakeBar:
    """复刻转换器所需的 Nautilus Bar 接口。"""

    def __init__(
        self,
        *,
        ts_event: int,
        open_price: object = 100,
        high: object = 101,
        low: object = 99,
        close: object = 100,
        volume: object = 10,
    ) -> None:
        self.ts_event = ts_event
        self.ts_init = ts_event
        self.open = _FakePrice(open_price)
        self.high = _FakePrice(high)
        self.low = _FakePrice(low)
        self.close = _FakePrice(close)
        self.volume = _FakePrice(volume)
        self.bar_type = _FakeBarType()


def _ts(year: int, month: int, day: int, hour: int = 0) -> int:
    return dt_to_ns(datetime(year, month, day, hour, tzinfo=UTC))


def test_daily_window_starts_at_the_candle_open() -> None:
    bar = _FakeBar(ts_event=_ts(2024, 1, 1))
    domain = to_domain_bar(bar, Timeframe.DAY)
    assert domain.ts_open_ns == _ts(2024, 1, 1)
    assert domain.ts_close_ns == _ts(2024, 1, 2)


def test_weekly_window_spans_one_utc_week() -> None:
    bar = _FakeBar(ts_event=_ts(2024, 1, 1))
    domain = to_domain_bar(bar, Timeframe.WEEK)
    assert domain.ts_close_ns == _ts(2024, 1, 8)


def test_monthly_window_is_a_calendar_month() -> None:
    bar = _FakeBar(ts_event=_ts(2024, 1, 1))
    domain = to_domain_bar(bar, Timeframe.MONTH)
    assert domain.ts_close_ns == _ts(2024, 2, 1)


def test_december_monthly_window_rolls_into_next_year() -> None:
    bar = _FakeBar(ts_event=_ts(2023, 12, 1))
    domain = to_domain_bar(bar, Timeframe.MONTH)
    assert domain.ts_close_ns == _ts(2024, 1, 1)


def test_shanghai_aligned_monthly_candle_is_rejected() -> None:
    # OKX 月线按 UTC+8 日历开盘：2024-01-01 00:00 +08:00 即
    # 2023-12-31 16:00 UTC，不是 UTC 自然月边界。
    bar = _FakeBar(ts_event=_ts(2023, 12, 31, hour=16))
    with pytest.raises(BarAlignmentError, match="not aligned"):
        to_domain_bar(bar, Timeframe.MONTH)


def test_decimal_prices_are_preserved_exactly() -> None:
    bar = _FakeBar(
        ts_event=_ts(2024, 1, 1),
        open_price="2481.13",
        high="2495.07",
        low="2470.55",
        close="2492.31",
        volume="1234.5678",
    )
    domain = to_domain_bar(bar, Timeframe.DAY)
    assert domain.open == dec("2481.13")
    assert domain.high == dec("2495.07")
    assert domain.low == dec("2470.55")
    assert domain.close == dec("2492.31")
    assert domain.volume == dec("1234.5678")


def test_instrument_id_can_be_overridden() -> None:
    bar = _FakeBar(ts_event=_ts(2024, 1, 1))
    domain = to_domain_bar(bar, Timeframe.DAY, instrument_id="BTC-USDT-SWAP.OKX")
    assert domain.instrument_id == "BTC-USDT-SWAP.OKX"


def test_bar_window_helper_matches_ninety_day() -> None:
    open_ns, close_ns = bar_window_ns(_ts(2024, 1, 1), Timeframe.DAY)
    assert open_ns == _ts(2024, 1, 1)
    assert close_ns == _ts(2024, 1, 2)


def test_invalid_ohlc_is_rejected() -> None:
    bar = _FakeBar(ts_event=_ts(2024, 1, 1), high=90, low=95)
    with pytest.raises(Exception, match="low"):
        to_domain_bar(bar, Timeframe.DAY)
