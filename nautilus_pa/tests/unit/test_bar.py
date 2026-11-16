"""K 线不变量测试。"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from helpers import INSTRUMENT_ID, dec, make_bar
from pa_trend.domain.errors import BarAlignmentError, BarValidationError
from pa_trend.domain.models.bar import Bar
from pa_trend.domain.models.timeframe import Timeframe, dt_to_ns, expected_close_ns


def test_valid_bar_exposes_derived_values() -> None:
    bar = make_bar(open_price=100, high=110, low=95, close=105, volume=3)
    assert bar.is_bullish
    assert bar.body == dec(5)
    assert bar.price_range == dec(15)
    position = bar.close_position()
    assert position is not None
    assert dec("0.66") < position < dec("0.67")


def test_bar_id_is_deterministic() -> None:
    first = make_bar(index=4)
    second = make_bar(index=4)
    assert first.bar_id == second.bar_id


def test_flat_bar_has_undefined_close_position() -> None:
    bar = make_bar(open_price=100, high=100, low=100, close=100)
    assert bar.close_position() is None


def test_low_above_high_is_rejected() -> None:
    with pytest.raises(BarValidationError, match="low"):
        make_bar(open_price=100, high=99, low=101, close=100)


def test_high_below_close_is_rejected() -> None:
    with pytest.raises(BarValidationError, match="high"):
        make_bar(open_price=100, high=104, low=99, close=105)


def test_negative_volume_is_rejected() -> None:
    with pytest.raises(BarValidationError, match="volume"):
        make_bar(volume=-1)


def test_close_before_open_time_is_rejected() -> None:
    with pytest.raises(BarValidationError, match="ts_close_ns"):
        Bar(
            instrument_id=INSTRUMENT_ID,
            timeframe=Timeframe.DAY,
            open=dec(100),
            high=dec(101),
            low=dec(99),
            close=dec(100),
            volume=dec(1),
            ts_open_ns=dt_to_ns(datetime(2024, 1, 2, tzinfo=UTC)),
            ts_close_ns=dt_to_ns(datetime(2024, 1, 2, tzinfo=UTC)),
        )


def test_unaligned_bar_is_rejected() -> None:
    # 16:00 UTC 的日边界对应 Asia/Shanghai 时段的收盘。
    open_ns = dt_to_ns(datetime(2024, 1, 1, 16, 0, tzinfo=UTC))
    close_ns = dt_to_ns(datetime(2024, 1, 2, 16, 0, tzinfo=UTC))
    with pytest.raises(BarAlignmentError):
        Bar(
            instrument_id=INSTRUMENT_ID,
            timeframe=Timeframe.DAY,
            open=dec(100),
            high=dec(101),
            low=dec(99),
            close=dec(100),
            volume=dec(1),
            ts_open_ns=open_ns,
            ts_close_ns=close_ns,
        )


def test_aligned_window_helper_matches_daily_bar() -> None:
    bar = make_bar(index=3)
    assert bar.ts_close_ns == expected_close_ns(bar.ts_open_ns, Timeframe.DAY)
