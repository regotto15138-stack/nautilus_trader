"""交易所会话偏移测试（OKX 的日/周/月 K 线按 UTC+8 零点开盘）。"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from helpers import INSTRUMENT_ID, dec
from pa_trend.application.aggregation import TimeframeAggregator
from pa_trend.domain.errors import BarAlignmentError
from pa_trend.domain.models.bar import Bar
from pa_trend.domain.models.timeframe import (
    Timeframe,
    dt_to_ns,
    expected_close_ns,
    is_aligned,
    window_start_ns,
)

# OKX 会话：本地零点 = 前一日 16:00 UTC。
OKX_OFFSET_MINUTES = 8 * 60


def _ns(year: int, month: int, day: int, hour: int = 0) -> int:
    return dt_to_ns(datetime(year, month, day, hour, tzinfo=UTC))


def _bar(ts_open_ns: int, ts_close_ns: int, *, offset: int, timeframe: Timeframe) -> Bar:
    return Bar(
        instrument_id=INSTRUMENT_ID,
        timeframe=timeframe,
        open=Decimal("2000"),
        high=Decimal("2100"),
        low=Decimal("1900"),
        close=Decimal("2050"),
        volume=Decimal("10"),
        ts_open_ns=ts_open_ns,
        ts_close_ns=ts_close_ns,
        session_offset_minutes=offset,
    )


def test_okx_daily_bar_is_rejected_under_strict_utc() -> None:
    """默认（偏移 0）时，16:00 UTC 开盘的 K 线必须被拒绝。"""
    with pytest.raises(BarAlignmentError):
        _bar(
            _ns(2025, 11, 15, 16),
            _ns(2025, 11, 16, 16),
            offset=0,
            timeframe=Timeframe.DAY,
        )


def test_okx_daily_bar_is_accepted_with_session_offset() -> None:
    """声明 UTC+8 会话后，同一根 K 线应被接受。"""
    bar = _bar(
        _ns(2025, 11, 15, 16),
        _ns(2025, 11, 16, 16),
        offset=OKX_OFFSET_MINUTES,
        timeframe=Timeframe.DAY,
    )
    assert bar.session_offset_minutes == OKX_OFFSET_MINUTES


def test_okx_weekly_bar_is_accepted_with_session_offset() -> None:
    """周线：周日 16:00 UTC 开盘，次周日 16:00 收盘。"""
    _bar(
        _ns(2023, 11, 19, 16),
        _ns(2023, 11, 26, 16),
        offset=OKX_OFFSET_MINUTES,
        timeframe=Timeframe.WEEK,
    )


def test_okx_monthly_bar_is_accepted_with_session_offset() -> None:
    """月线：11-30 16:00 UTC 开盘，12-31 16:00 收盘。"""
    _bar(
        _ns(2021, 11, 30, 16),
        _ns(2021, 12, 31, 16),
        offset=OKX_OFFSET_MINUTES,
        timeframe=Timeframe.MONTH,
    )


def test_session_offset_does_not_relax_length_checks() -> None:
    """声明会话偏移不能放过长度错误的 K 线（只有边界平移，不改周期长度）。"""
    with pytest.raises(BarAlignmentError):
        _bar(
            _ns(2025, 11, 15, 16),
            _ns(2025, 11, 16, 12),
            offset=OKX_OFFSET_MINUTES,
            timeframe=Timeframe.DAY,
        )


def test_is_aligned_respects_offset() -> None:
    """is_aligned 应在给定偏移下判断边界。"""
    open_ns = _ns(2025, 11, 15, 16)
    close_ns = _ns(2025, 11, 16, 16)
    assert not is_aligned(open_ns, close_ns, Timeframe.DAY)
    assert is_aligned(
        open_ns,
        close_ns,
        Timeframe.DAY,
        session_offset_minutes=OKX_OFFSET_MINUTES,
    )


def test_window_start_and_close_respect_offset() -> None:
    """窗口推导应在会话偏移下还原出正确的开收盘时刻。"""
    close_ns = _ns(2025, 11, 16, 16)
    start = window_start_ns(
        close_ns,
        Timeframe.DAY,
        session_offset_minutes=OKX_OFFSET_MINUTES,
    )
    assert start == _ns(2025, 11, 15, 16)
    assert (
        expected_close_ns(
            start,
            Timeframe.DAY,
            session_offset_minutes=OKX_OFFSET_MINUTES,
        )
        == close_ns
    )


def test_aggregator_uses_session_windows() -> None:
    """聚合器应按会话边界切窗：UTC+8 日线聚合成 UTC+8 月线。"""
    aggregator = TimeframeAggregator(
        instrument_id=INSTRUMENT_ID,
        target_timeframe=Timeframe.MONTH,
        source_timeframe=Timeframe.DAY,
        session_offset_minutes=OKX_OFFSET_MINUTES,
    )

    # 2022-01 的会话月：2021-12-31T16:00Z 起，共 31 天。
    start = _ns(2021, 12, 31, 16)
    completed = None
    for index in range(32):
        open_ns = start + index * 86_400 * 1_000_000_000
        close_ns = open_ns + 86_400 * 1_000_000_000
        out = aggregator.update(
            _bar(
                open_ns,
                close_ns,
                offset=OKX_OFFSET_MINUTES,
                timeframe=Timeframe.DAY,
            ),
        )
        if out is not None:
            completed = out
            break

    assert completed is not None
    assert completed.ts_open_ns == start
    assert completed.session_offset_minutes == OKX_OFFSET_MINUTES
    assert completed.ts_close_ns == _ns(2022, 1, 31, 16)


def test_helpers_default_still_utc() -> None:
    """未显式传偏移时，行为必须保持严格 UTC。"""
    assert dec("1") == Decimal("1")
    open_ns = _ns(2024, 1, 1)
    assert is_aligned(open_ns, expected_close_ns(open_ns, Timeframe.DAY), Timeframe.DAY)
