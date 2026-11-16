"""周期聚合测试（规格第 1.5 节）。"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from helpers import INSTRUMENT_ID, dec, make_bar
from pa_trend.application.aggregation import TimeframeAggregator
from pa_trend.domain.errors import DataIntegrityError
from pa_trend.domain.models.timeframe import Timeframe, dt_to_ns


def _weekly_from_daily() -> TimeframeAggregator:
    return TimeframeAggregator(
        instrument_id=INSTRUMENT_ID,
        target_timeframe=Timeframe.WEEK,
        source_timeframe=Timeframe.DAY,
    )


def test_weekly_aggregate_opens_the_first_bar_and_closes_the_last() -> None:
    aggregator = _weekly_from_daily()

    for index in range(7):
        aggregated = aggregator.update(
            make_bar(
                index=index,
                open_price=100 + index,
                high=110 + index,
                low=90 + index,
                close=105 + index,
                volume=1,
            ),
        )
        assert aggregated is None

    weekly = aggregator.update(make_bar(index=7))
    assert weekly is not None
    assert weekly.timeframe is Timeframe.WEEK
    assert weekly.open == dec(100)
    assert weekly.high == dec(116)
    assert weekly.low == dec(90)
    assert weekly.close == dec(111)
    assert weekly.volume == dec(7)
    assert weekly.ts_open_ns == dt_to_ns(datetime(2024, 1, 1, tzinfo=UTC))
    assert weekly.ts_close_ns == dt_to_ns(datetime(2024, 1, 8, tzinfo=UTC))


def test_short_window_is_recorded_as_incomplete() -> None:
    aggregator = _weekly_from_daily()
    for index in range(3):
        aggregator.update(make_bar(index=index))
    aggregator.update(make_bar(index=7))
    assert aggregator.incomplete_windows == (dt_to_ns(datetime(2024, 1, 1, tzinfo=UTC)),)


def test_flush_closes_the_trailing_window() -> None:
    aggregator = _weekly_from_daily()
    aggregator.update(make_bar(index=0))
    weekly = aggregator.flush()
    assert weekly is not None
    assert weekly.ts_close_ns == dt_to_ns(datetime(2024, 1, 8, tzinfo=UTC))
    assert aggregator.flush() is None


def test_source_must_be_faster_than_target() -> None:
    with pytest.raises(ValueError, match="faster"):
        TimeframeAggregator(
            instrument_id=INSTRUMENT_ID,
            target_timeframe=Timeframe.DAY,
            source_timeframe=Timeframe.WEEK,
        )


def test_foreign_timeframe_is_rejected() -> None:
    aggregator = _weekly_from_daily()
    with pytest.raises(DataIntegrityError, match="expects"):
        aggregator.update(make_bar(index=0, timeframe=Timeframe.WEEK))


def test_foreign_instrument_is_rejected() -> None:
    aggregator = _weekly_from_daily()
    with pytest.raises(DataIntegrityError, match="expects"):
        aggregator.update(make_bar(index=0, instrument_id="BTC-USDT-SWAP.OKX"))


def test_describe_open_window_is_informative() -> None:
    aggregator = _weekly_from_daily()
    assert aggregator.describe_open_window() == "no open window"
    aggregator.update(make_bar(index=0))
    assert "members=1" in aggregator.describe_open_window()
