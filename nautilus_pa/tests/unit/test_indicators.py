"""SMA22 与 Wilder ATR14 指标测试（规格第 2 节）。"""

from __future__ import annotations

import pytest

from helpers import dec
from pa_trend.domain.indicators.atr import WilderAtr
from pa_trend.domain.indicators.sma import SimpleMovingAverage


def test_sma_reports_none_until_the_window_is_full() -> None:
    sma = SimpleMovingAverage(3)
    assert sma.value is None
    sma.update(dec(1))
    sma.update(dec(2))
    assert not sma.is_ready
    assert sma.value is None
    sma.update(dec(3))
    assert sma.is_ready
    assert sma.value == dec(2)


def test_sma_evicts_the_oldest_sample() -> None:
    sma = SimpleMovingAverage(3)
    for value in (1, 2, 3):
        sma.update(dec(value))
    sma.update(dec(4))
    assert sma.value == dec(3)
    assert sma.count == 3


def test_sma_rejects_non_positive_period() -> None:
    with pytest.raises(ValueError, match="period must be positive"):
        SimpleMovingAverage(0)


def test_atr_seeds_with_the_mean_of_the_first_true_ranges() -> None:
    atr = WilderAtr(2)
    atr.update(dec(10), dec(8), dec(9))
    assert atr.value is None
    atr.update(dec(11), dec(9), dec(10))
    assert atr.value == dec(2)


def test_atr_applies_the_wilder_recurrence() -> None:
    atr = WilderAtr(2)
    atr.update(dec(10), dec(8), dec(9))
    atr.update(dec(11), dec(9), dec(10))
    atr.update(dec(12), dec(9), dec(11))
    # TR = max(3, |12-10|, |9-10|) = 3；ATR = (2*1 + 3) / 2 = 2.5
    assert atr.value == dec("2.5")


def test_atr_uses_gap_aware_true_range() -> None:
    atr = WilderAtr(1)
    atr.update(dec(10), dec(8), dec(9))
    assert atr.value == dec(2)
    # 前收盘 9、最高 20，则 TR = |20 - 9| = 11（跳空），大于 20-19。
    atr.update(dec(20), dec(19), dec(19))
    assert atr.value == dec(11)


def test_atr_rejects_inconsistent_bar() -> None:
    atr = WilderAtr(2)
    with pytest.raises(ValueError, match="low"):
        atr.update(dec(8), dec(10), dec(9))


def test_atr14_reaches_readiness_on_the_fourteenth_bar() -> None:
    atr = WilderAtr(14)
    for _ in range(13):
        atr.update(dec(101), dec(99), dec(100))
        assert not atr.is_ready
    atr.update(dec(101), dec(99), dec(100))
    assert atr.is_ready
    assert atr.value == dec(2)
