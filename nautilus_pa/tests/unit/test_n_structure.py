"""多头 N 结构测试（规格第 5 与 18.2 节）。"""

from __future__ import annotations

import pytest

from helpers import INSTRUMENT_ID, dec, make_bar, make_swing
from pa_trend.domain.models.swing import SwingDirection
from pa_trend.domain.models.timeframe import Timeframe
from pa_trend.domain.structure.n_structure import (
    NStructureDetector,
    NStructureStatus,
    RetracementClass,
    classify_retracement,
)


def _detector(*, invalidation: bool = False) -> NStructureDetector:
    return NStructureDetector(
        instrument_id=INSTRUMENT_ID,
        timeframe=Timeframe.WEEK,
        break_buffer_atr=dec("0.1"),
        invalidation_enabled=invalidation,
    )


def _feed(
    detector: NStructureDetector,
    prices: tuple[object, object, object, object],
    *,
    occurrences: tuple[int, int, int, int] = (0, 1, 2, 3),
):
    directions = (
        SwingDirection.LOW,
        SwingDirection.HIGH,
        SwingDirection.LOW,
        SwingDirection.HIGH,
    )
    structure = None
    for sequence, (direction, price, index) in enumerate(
        zip(directions, prices, occurrences, strict=True),
    ):
        structure = detector.on_swing_point(
            make_swing(
                sequence=sequence,
                direction=direction,
                price=price,
                occurred_index=index,
            ),
        )
    return structure


def test_normal_pullback_structure_is_detected() -> None:
    structure = _feed(_detector(), (100, 200, 150, 250))
    assert structure is not None
    assert structure.retracement_ratio == dec("0.5")
    assert structure.retracement_class is RetracementClass.NORMAL
    assert structure.status is NStructureStatus.CONFIRMED
    assert structure.reference_price == dec(250)
    assert structure.structural_anchor == dec(150)


def test_pullback_low_below_h1_is_allowed() -> None:
    # L2 (150) 低于 H1 (200)：这是必须保留的常规回调情形。
    structure = _feed(_detector(), (100, 200, 150, 250))
    assert structure is not None
    assert structure.l2.price < structure.h1.price


def test_pullback_low_above_h1_is_allowed() -> None:
    structure = _feed(_detector(), (100, 200, 210, 250))
    assert structure is not None
    assert structure.retracement_ratio == dec("-0.1")
    assert structure.retracement_class is RetracementClass.HIGH_CONSOLIDATION


def test_pullback_low_equal_to_l1_is_rejected() -> None:
    assert _feed(_detector(), (100, 200, 100, 250)) is None


def test_pullback_low_below_l1_is_rejected() -> None:
    assert _feed(_detector(), (100, 200, 90, 250)) is None


def test_h2_equal_to_h1_is_rejected() -> None:
    assert _feed(_detector(), (100, 200, 150, 200)) is None


def test_h2_below_h1_is_rejected() -> None:
    assert _feed(_detector(), (100, 200, 150, 190)) is None


def test_out_of_order_occurrences_are_rejected() -> None:
    assert _feed(_detector(), (100, 200, 150, 250), occurrences=(0, 1, 3, 2)) is None


def test_structure_id_is_deterministic() -> None:
    first = _feed(_detector(), (100, 200, 150, 250))
    second = _feed(_detector(), (100, 200, 150, 250))
    assert first is not None
    assert second is not None
    assert first.n_structure_id == second.n_structure_id


def test_invalidation_uses_the_close_not_the_wick() -> None:
    """显式启用失效判定后，只有收盘跌破缓冲价才算失效（影线不算）。"""
    detector = _detector(invalidation=True)
    structure = _feed(detector, (100, 200, 150, 250))
    assert structure is not None
    structure.activate(structure.confirmed_at_ns)

    # ATR 10 → 缓冲 1.0 → 阈值 149；收盘仍在 149 之上则不算破位。
    wick = make_bar(index=4, open_price=150, high=151, low=140, close=149.5)
    assert detector.on_bar(wick, dec(10)) == ()
    assert structure.status is NStructureStatus.ACTIVE

    broken = make_bar(index=5, open_price=149, high=150, low=140, close=148)
    invalidated = detector.on_bar(broken, dec(10))
    assert invalidated == (structure,)
    assert structure.status is NStructureStatus.INVALIDATED


def test_invalidation_is_disabled_by_default_due_to_spec_ambiguity() -> None:
    """V1.4.8 未定义失效判定使用的 ATR 时点，默认不得产出失效价。"""
    detector = _detector()
    structure = _feed(detector, (100, 200, 150, 250))
    assert structure is not None
    structure.activate(structure.confirmed_at_ns)

    assert detector.invalidation_status == "SPEC_AMBIGUITY"
    assert detector.invalidation_enabled is False
    # 接口存在，但调用方必须自己提供 ATR 快照。
    assert detector.structural_break_price(dec(10)) == dec(149)
    assert detector.structural_break_price(None) is None

    broken = make_bar(index=5, open_price=149, high=150, low=140, close=148)
    assert detector.on_bar(broken, dec(10)) == ()
    assert structure.status is NStructureStatus.ACTIVE


def test_broken_structure_never_becomes_active_again() -> None:
    detector = _detector()
    structure = _feed(detector, (100, 200, 150, 250))
    assert structure is not None
    structure.activate(structure.confirmed_at_ns)
    structure.invalidate(structure.confirmed_at_ns + 1)
    structure.activate(structure.confirmed_at_ns + 2)
    assert structure.status is NStructureStatus.INVALIDATED


def test_missing_atr_skips_invalidation() -> None:
    detector = _detector()
    structure = _feed(detector, (100, 200, 150, 250))
    assert structure is not None
    structure.activate(structure.confirmed_at_ns)
    broken = make_bar(index=4, open_price=140, high=141, low=130, close=131)
    assert detector.on_bar(broken, None) == ()
    assert structure.status is NStructureStatus.ACTIVE


def test_foreign_instrument_swing_is_rejected() -> None:
    detector = _detector()
    point = make_swing(
        sequence=0,
        direction=SwingDirection.LOW,
        price=100,
        occurred_index=0,
        instrument_id="BTC-USDT-SWAP.OKX",
    )
    with pytest.raises(ValueError, match="instrument"):
        detector.on_swing_point(point)


@pytest.mark.parametrize(
    ("ratio", "expected"),
    [
        ("-0.5", RetracementClass.HIGH_CONSOLIDATION),
        ("0", RetracementClass.SHALLOW),
        ("0.381", RetracementClass.SHALLOW),
        ("0.382", RetracementClass.NORMAL),
        ("0.617", RetracementClass.NORMAL),
        ("0.618", RetracementClass.DEEP),
        ("0.999", RetracementClass.DEEP),
        ("1.0", RetracementClass.BREAK_CANDIDATE),
        ("1.5", RetracementClass.BREAK_CANDIDATE),
    ],
)
def test_retracement_buckets_are_left_closed_right_open(
    ratio: str,
    expected: RetracementClass,
) -> None:
    assert classify_retracement(dec(ratio)) is expected
