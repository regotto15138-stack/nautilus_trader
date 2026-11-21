"""ATR 反转 ZigZag 测试（规格第 4 与 18.1 节）。"""

from __future__ import annotations

import pytest

from helpers import INSTRUMENT_ID, dec, make_bar
from pa_trend.domain.models.swing import SwingDirection
from pa_trend.domain.models.timeframe import Timeframe
from pa_trend.domain.zigzag.detector import ZigZagConfig, ZigZagDetector, ZigZagDirection

ATR = dec(10)


def _detector(**kwargs: object) -> ZigZagDetector:
    return ZigZagDetector(
        instrument_id=INSTRUMENT_ID,
        timeframe=Timeframe.DAY,
        **kwargs,  # type: ignore[arg-type]
    )


def _three_bars_confirming_a_high() -> tuple[ZigZagDetector, list[object], list[object]]:
    detector = _detector()
    bars = [
        make_bar(index=0, open_price=99, high=100, low=98, close=100),
        make_bar(index=1, open_price=100, high=120, low=99, close=118),
        make_bar(index=2, open_price=118, high=125, low=100, close=101),
    ]
    results = [detector.update(bar, ATR) for bar in bars]
    return detector, results, bars


def test_swing_high_confirms_on_the_reversal_bar() -> None:
    detector, results, _ = _three_bars_confirming_a_high()
    assert results[0] is None
    assert results[1] is None
    swing = results[2]
    assert swing is not None
    assert swing.direction is SwingDirection.HIGH
    assert swing.price == dec(125)
    assert swing.atr_snapshot == ATR
    assert swing.sequence == 0
    assert detector.direction is ZigZagDirection.SEEK_LOW


def test_candidate_and_confirmation_can_share_one_bar() -> None:
    _, results, bars = _three_bars_confirming_a_high()
    swing = results[2]
    assert swing is not None
    # 候选高点与确认发生在同一根 K 线上；occurred 取该 Bar 的 open_time，
    # confirmed 取该 Bar 的 close_time，二者不再相等。
    assert swing.occurred_at_ns == bars[2].ts_open_ns
    assert swing.confirmed_at_ns == bars[2].ts_close_ns
    assert swing.occurred_at_ns < swing.confirmed_at_ns


def test_confirmed_at_never_precedes_occurred_at() -> None:
    detector = _detector()
    detector.update(make_bar(index=0, open_price=100, high=100, low=99, close=100), ATR)
    detector.update(make_bar(index=1, open_price=100, high=110, low=99, close=108), ATR)
    swing = detector.update(
        make_bar(index=2, open_price=108, high=109, low=85, close=86),
        ATR,
    )
    assert swing is not None
    assert swing.confirmed_at_ns > swing.occurred_at_ns


def test_occurred_at_is_the_source_bar_open_not_close() -> None:
    """摆动点 occurred_at 必须等于来源 Bar 的开盘时刻。

    真实缺陷：occurred_at 取来源 Bar 的收盘时刻，而图表蜡烛按开盘时刻绘制，
    导致摆动点标记整体后移一根 Bar（1M 上表现为跨月）。
    """
    detector = _detector()
    detector.update(make_bar(index=0, open_price=100, high=100, low=99, close=100), ATR)
    source = make_bar(index=1, open_price=100, high=110, low=99, close=108)
    detector.update(source, ATR)
    swing = detector.update(
        make_bar(index=2, open_price=108, high=109, low=85, close=86),
        ATR,
    )
    assert swing is not None
    assert swing.price == dec(110)
    assert swing.occurred_at_ns == source.ts_open_ns
    assert swing.source_bar_id == source.bar_id
    assert swing.confirmed_at_ns == make_bar(index=2).ts_close_ns


def test_candidate_atr_is_frozen_when_the_extreme_forms() -> None:
    detector = _detector()
    detector.update(make_bar(index=0, open_price=100, high=100, low=98, close=100), ATR)
    detector.update(make_bar(index=1, open_price=101, high=105, low=100, close=104), ATR)

    # ATR 膨胀到 100，但判定必须仍然使用冻结的 10。
    swing = detector.update(
        make_bar(index=2, open_price=104, high=104, low=80, close=84),
        dec(100),
    )
    assert swing is not None
    assert swing.price == dec(105)
    assert swing.atr_snapshot == ATR


def test_swing_low_confirms_when_seeking_low_initially() -> None:
    detector = _detector(initial_direction=ZigZagDirection.SEEK_LOW)
    assert (
        detector.update(
            make_bar(index=0, open_price=110, high=110, low=100, close=100),
            ATR,
        )
        is None
    )
    assert (
        detector.update(
            make_bar(index=1, open_price=90, high=95, low=80, close=90),
            ATR,
        )
        is None
    )
    swing = detector.update(
        make_bar(index=2, open_price=90, high=106, low=82, close=105),
        ATR,
    )
    assert swing is not None
    assert swing.direction is SwingDirection.LOW
    assert swing.price == dec(80)
    assert detector.direction is ZigZagDirection.SEEK_HIGH


def test_confirmation_bar_does_not_seed_the_next_candidate() -> None:
    detector, results, _ = _three_bars_confirming_a_high()
    assert results[2] is not None
    # 确认 K 线的最低价是 100，但该低点不得成为下一方向的候选。
    assert (
        detector.update(
            make_bar(index=3, open_price=101, high=110, low=95, close=100),
            ATR,
        )
        is None
    )
    swing = detector.update(
        make_bar(index=4, open_price=100, high=120, low=90, close=118),
        ATR,
    )
    assert swing is not None
    assert swing.direction is SwingDirection.LOW
    assert swing.price == dec(90)


def test_swings_are_monotonic_in_sequence() -> None:
    detector = _detector()
    detector.update(make_bar(index=0, open_price=100, high=100, low=99, close=100), ATR)
    detector.update(make_bar(index=1, open_price=100, high=110, low=99, close=108), ATR)
    detector.update(make_bar(index=2, open_price=108, high=109, low=85, close=86), ATR)
    detector.update(make_bar(index=3, open_price=86, high=87, low=70, close=71), ATR)
    swings = detector.swing_points
    assert len(swings) == 1
    assert swings[0].sequence == 0
    assert detector.last_swing is swings[0]


def test_missing_atr_blocks_all_detection() -> None:
    detector = _detector()
    detector.update(make_bar(index=0, open_price=99, high=100, low=98, close=100), ATR)
    assert (
        detector.update(
            make_bar(index=1, open_price=100, high=120, low=99, close=118),
            None,
        )
        is None
    )
    assert detector.swing_points == ()
    assert detector.direction is ZigZagDirection.SEEK_HIGH


def test_foreign_instrument_is_rejected() -> None:
    detector = _detector()
    bar = make_bar(index=0, instrument_id="BTC-USDT-SWAP.OKX")
    with pytest.raises(ValueError, match="instrument"):
        detector.update(bar, ATR)


def test_foreign_timeframe_is_rejected() -> None:
    detector = _detector()
    bar = make_bar(index=0, timeframe=Timeframe.WEEK)
    with pytest.raises(ValueError, match="timeframe"):
        detector.update(bar, ATR)


def test_config_rejects_non_positive_multiple() -> None:
    with pytest.raises(ValueError, match="reversal_atr_multiple"):
        ZigZagConfig(reversal_atr_multiple=dec(0))
