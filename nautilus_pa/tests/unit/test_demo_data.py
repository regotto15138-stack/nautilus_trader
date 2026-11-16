"""合成演示数据测试。"""

from __future__ import annotations

from pa_trend.application.demo_data import generate_demo_bars
from pa_trend.domain.models.timeframe import Timeframe, is_aligned

INSTRUMENT = "ETH-USDT-SWAP.OKX"


def test_same_seed_produces_identical_series() -> None:
    """相同种子必须产生完全一致的序列，便于复现。"""
    first = generate_demo_bars(instrument_id=INSTRUMENT, timeframe=Timeframe.DAY, count=30)
    second = generate_demo_bars(instrument_id=INSTRUMENT, timeframe=Timeframe.DAY, count=30)
    assert [bar.close for bar in first] == [bar.close for bar in second]


def test_bars_are_aligned_and_ascending() -> None:
    """生成的 K 线必须落在 UTC 边界上且时间递增。"""
    bars = generate_demo_bars(
        instrument_id=INSTRUMENT,
        timeframe=Timeframe.DAY,
        count=20,
    )
    for bar in bars:
        assert is_aligned(bar.ts_open_ns, bar.ts_close_ns, Timeframe.DAY)
    closes = [bar.ts_close_ns for bar in bars]
    assert closes == sorted(closes)
    assert len(set(closes)) == len(closes)


def test_ohlc_invariants_are_satisfied() -> None:
    """高低价必须包住开收价（构造过程由 Bar 自身校验，这里再确认一次）。"""
    bars = generate_demo_bars(
        instrument_id=INSTRUMENT,
        timeframe=Timeframe.WEEK,
        count=15,
    )
    for bar in bars:
        assert bar.low <= min(bar.open, bar.close)
        assert bar.high >= max(bar.open, bar.close)
        assert bar.volume >= 0


def test_count_and_rejection() -> None:
    """根数应准确，非法根数应报错。"""
    assert len(generate_demo_bars(instrument_id=INSTRUMENT, timeframe=Timeframe.DAY, count=7)) == 7
    try:
        generate_demo_bars(instrument_id=INSTRUMENT, timeframe=Timeframe.DAY, count=0)
    except ValueError as exc:
        assert "count" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected ValueError")


def test_monthly_series_rolls_over_years() -> None:
    """月线序列应能跨年连续生成。"""
    bars = generate_demo_bars(
        instrument_id=INSTRUMENT,
        timeframe=Timeframe.MONTH,
        count=30,
    )
    assert len(bars) == 30
    years = {bar.ts_open.year for bar in bars}
    assert len(years) >= 2
