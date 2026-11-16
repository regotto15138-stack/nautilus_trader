"""UTC 边界测试（规格第 1.5 节）。"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from helpers import dec
from pa_trend.domain.models.timeframe import (
    Timeframe,
    add_periods,
    dt_to_ns,
    expected_close_ns,
    floor_to_boundary,
    is_aligned,
    next_boundary,
    ns_to_dt,
    window_start_ns,
)


def test_ns_roundtrip_is_exact_for_microsecond_values() -> None:
    moment = datetime(2024, 3, 7, 13, 45, 21, 987654, tzinfo=UTC)
    assert ns_to_dt(dt_to_ns(moment)) == moment


def test_naive_datetime_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        dt_to_ns(datetime(2024, 1, 1))


def test_floor_day() -> None:
    moment = datetime(2024, 5, 17, 23, 59, 59, tzinfo=UTC)
    assert floor_to_boundary(moment, Timeframe.DAY) == datetime(2024, 5, 17, tzinfo=UTC)


def test_floor_week_is_monday() -> None:
    # 2024-05-17 是周五，其 UTC 周起始于周一 2024-05-13。
    moment = datetime(2024, 5, 17, 12, 0, tzinfo=UTC)
    assert floor_to_boundary(moment, Timeframe.WEEK) == datetime(2024, 5, 13, tzinfo=UTC)


def test_floor_month() -> None:
    moment = datetime(2024, 5, 17, 12, 0, tzinfo=UTC)
    assert floor_to_boundary(moment, Timeframe.MONTH) == datetime(2024, 5, 1, tzinfo=UTC)


def test_next_boundary_rolls_over_month() -> None:
    start = datetime(2023, 12, 1, tzinfo=UTC)
    assert next_boundary(start, Timeframe.MONTH) == datetime(2024, 1, 1, tzinfo=UTC)


def test_next_boundary_rolls_over_year_for_weeks() -> None:
    start = datetime(2023, 12, 25, tzinfo=UTC)
    assert next_boundary(start, Timeframe.WEEK) == datetime(2024, 1, 1, tzinfo=UTC)


def test_add_periods_month_crosses_year() -> None:
    start = datetime(2024, 11, 1, tzinfo=UTC)
    assert add_periods(start, Timeframe.MONTH, 3) == datetime(2025, 2, 1, tzinfo=UTC)
    assert add_periods(start, Timeframe.MONTH, -12) == datetime(2023, 11, 1, tzinfo=UTC)


def test_add_periods_week_backwards() -> None:
    start = datetime(2024, 1, 8, tzinfo=UTC)
    assert add_periods(start, Timeframe.WEEK, -2) == datetime(2023, 12, 25, tzinfo=UTC)


def test_daily_bar_window_is_the_previous_utc_day() -> None:
    close_ns = dt_to_ns(datetime(2024, 1, 2, tzinfo=UTC))
    assert window_start_ns(close_ns, Timeframe.DAY) == dt_to_ns(datetime(2024, 1, 1, tzinfo=UTC))


def test_weekly_bar_window_starts_on_monday() -> None:
    close_ns = dt_to_ns(datetime(2024, 1, 8, tzinfo=UTC))
    assert window_start_ns(close_ns, Timeframe.WEEK) == dt_to_ns(
        datetime(2024, 1, 1, tzinfo=UTC),
    )


def test_monthly_bar_window_starts_on_first_of_month() -> None:
    close_ns = dt_to_ns(datetime(2024, 2, 1, tzinfo=UTC))
    assert window_start_ns(close_ns, Timeframe.MONTH) == dt_to_ns(
        datetime(2024, 1, 1, tzinfo=UTC),
    )


def test_alignment_accepts_utc_daily_bar() -> None:
    open_ns = dt_to_ns(datetime(2024, 1, 1, tzinfo=UTC))
    close_ns = expected_close_ns(open_ns, Timeframe.DAY)
    assert is_aligned(open_ns, close_ns, Timeframe.DAY)


def test_alignment_rejects_shanghai_session_close() -> None:
    # 00:00 Asia/Shanghai 等于前一日 16:00 UTC，不是 UTC 自然日边界。
    open_ns = dt_to_ns(datetime(2024, 1, 1, 16, 0, tzinfo=UTC))
    close_ns = dt_to_ns(datetime(2024, 1, 2, 16, 0, tzinfo=UTC))
    assert not is_aligned(open_ns, close_ns, Timeframe.DAY)


def test_bar_spec_tokens() -> None:
    assert Timeframe.MONTH.bar_spec == "1-MONTH"
    assert Timeframe.WEEK.bar_spec == "1-WEEK"
    assert Timeframe.DAY.bar_spec == "1-DAY"


def test_rank_orders_slower_timeframes_higher() -> None:
    assert Timeframe.MONTH.rank > Timeframe.WEEK.rank > Timeframe.DAY.rank


def test_decimal_helper_is_exact() -> None:
    assert dec("0.1") + dec("0.2") == dec("0.3")
