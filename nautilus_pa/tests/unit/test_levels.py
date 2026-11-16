"""保护点与回撤起点测试（规格 V1.4.8 第 5 节）。"""

from __future__ import annotations

from helpers import INSTRUMENT_ID, dec, make_bar, make_swing
from pa_trend.domain.models.swing import SwingDirection
from pa_trend.domain.models.timeframe import Timeframe
from pa_trend.domain.structure.levels import ProtectedLevelTracker

TF = Timeframe.WEEK


def _tracker() -> ProtectedLevelTracker:
    return ProtectedLevelTracker(timeframe=TF, break_buffer_atr=dec("0.1"))


def _swing(sequence: int, direction: SwingDirection, price: object, index: int):
    return make_swing(
        sequence=sequence,
        direction=direction,
        price=price,
        occurred_index=index,
        timeframe=TF,
    )


def _bullish_sequence(tracker: ProtectedLevelTracker) -> None:
    """L 100 → H 120 → L 105 → H 130：HH + HL。"""
    tracker.on_swing(_swing(0, SwingDirection.LOW, 100, 0))
    tracker.on_swing(_swing(1, SwingDirection.HIGH, 120, 1))
    tracker.on_swing(_swing(2, SwingDirection.LOW, 105, 2))
    tracker.on_swing(_swing(3, SwingDirection.HIGH, 130, 3))


def test_hh_hl_establishes_protected_low_and_pullback_origin() -> None:
    """HH + HL 后建立 ProtectedLow 与回撤起点。"""
    tracker = _tracker()
    _bullish_sequence(tracker)
    snapshot = tracker.snapshot
    assert snapshot.protected_low == dec(105)
    assert snapshot.pullback_origin_high == dec(130)
    assert snapshot.protected_low_swing_id is not None
    assert snapshot.protected_high is None


def test_protected_low_invalidates_on_close_below_buffer() -> None:
    """收盘跌破 ProtectedLow - 0.1 ATR 后失效。"""
    tracker = _tracker()
    _bullish_sequence(tracker)
    bar = make_bar(index=4, timeframe=TF, open_price=100, high=101, low=90, close=100)
    tracker.on_bar(bar, dec("10"))  # 阈值 105 - 1 = 104，收盘 100 跌破
    assert tracker.snapshot.protected_low is None
    assert tracker.snapshot.pullback_origin_high is None


def test_protected_low_holds_when_close_inside_buffer() -> None:
    """收盘仍在阈值之上时不失效（影线跌破不算）。"""
    tracker = _tracker()
    _bullish_sequence(tracker)
    bar = make_bar(index=4, timeframe=TF, open_price=104, high=105, low=95, close=104.5)
    tracker.on_bar(bar, dec("10"))
    assert tracker.snapshot.protected_low == dec(105)


def test_invalidated_protected_low_does_not_revive() -> None:
    """失效后价格回升也不会复活旧 ProtectedLow。"""
    tracker = _tracker()
    _bullish_sequence(tracker)
    tracker.on_bar(
        make_bar(index=4, timeframe=TF, open_price=100, high=101, low=90, close=100),
        dec("10"),
    )
    tracker.on_bar(
        make_bar(index=5, timeframe=TF, open_price=120, high=130, low=119, close=129),
        dec("10"),
    )
    assert tracker.snapshot.protected_low is None


def test_lh_ll_establishes_protected_high() -> None:
    """LH + LL 后建立 ProtectedHigh。"""
    tracker = _tracker()
    tracker.on_swing(_swing(0, SwingDirection.HIGH, 130, 0))
    tracker.on_swing(_swing(1, SwingDirection.LOW, 100, 1))
    tracker.on_swing(_swing(2, SwingDirection.HIGH, 120, 2))
    tracker.on_swing(_swing(3, SwingDirection.LOW, 90, 3))
    assert tracker.snapshot.protected_high == dec(120)


def test_protected_high_only_updates_strictly_lower() -> None:
    """相等或更高的 LH 不替换已有 ProtectedHigh。"""
    tracker = _tracker()
    tracker.on_swing(_swing(0, SwingDirection.HIGH, 130, 0))
    tracker.on_swing(_swing(1, SwingDirection.LOW, 100, 1))
    tracker.on_swing(_swing(2, SwingDirection.HIGH, 120, 2))
    tracker.on_swing(_swing(3, SwingDirection.LOW, 90, 3))
    first = tracker.snapshot.protected_high

    # 新的 LH 与旧值相等：不得替换。
    tracker.on_swing(_swing(4, SwingDirection.HIGH, 120, 4))
    tracker.on_swing(_swing(5, SwingDirection.LOW, 80, 5))
    assert tracker.snapshot.protected_high == first == dec(120)

    # 更低的 LH：允许向下更新。
    tracker.on_swing(_swing(6, SwingDirection.HIGH, 110, 6))
    tracker.on_swing(_swing(7, SwingDirection.LOW, 70, 7))
    assert tracker.snapshot.protected_high == dec(110)


def test_protected_high_invalidates_on_close_above_buffer() -> None:
    """收盘突破 ProtectedHigh + 0.1 ATR 后失效。"""
    tracker = _tracker()
    tracker.on_swing(_swing(0, SwingDirection.HIGH, 130, 0))
    tracker.on_swing(_swing(1, SwingDirection.LOW, 100, 1))
    tracker.on_swing(_swing(2, SwingDirection.HIGH, 120, 2))
    tracker.on_swing(_swing(3, SwingDirection.LOW, 90, 3))

    tracker.on_bar(
        make_bar(index=4, timeframe=TF, open_price=120, high=130, low=119, close=125),
        dec("10"),
    )
    assert tracker.snapshot.protected_high is None


def test_missing_atr_skips_invalidation() -> None:
    """ATR 不可用时不做失效判定，避免用零缓冲误判。"""
    tracker = _tracker()
    _bullish_sequence(tracker)
    tracker.on_bar(
        make_bar(index=4, timeframe=TF, open_price=100, high=101, low=50, close=60),
        None,
    )
    assert tracker.snapshot.protected_low == dec(105)


def test_foreign_timeframe_is_rejected() -> None:
    """其他周期的摆动点必须拒绝。"""
    tracker = _tracker()
    point = make_swing(
        sequence=0,
        direction=SwingDirection.HIGH,
        price=120,
        occurred_index=0,
        timeframe=Timeframe.DAY,
    )
    try:
        tracker.on_swing(point)
    except ValueError as exc:
        assert "timeframe" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected ValueError")


def test_instrument_id_is_preserved() -> None:
    """摆动点合约标识不影响结构计算。"""
    tracker = _tracker()
    point = make_swing(
        sequence=0,
        direction=SwingDirection.HIGH,
        price=120,
        occurred_index=0,
        timeframe=TF,
        instrument_id=INSTRUMENT_ID,
    )
    tracker.on_swing(point)
    assert tracker.snapshot.protected_high is None
