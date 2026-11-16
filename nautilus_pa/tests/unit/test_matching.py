"""差异匹配测试（SACW V1.1.2 第 7 章）。"""

from __future__ import annotations

from decimal import Decimal

import pytest

from pa_trend.application.matching import (
    MatcherConfig,
    MatchType,
    SwingCandidate,
    hungarian,
    match_n_structures,
    match_swings,
    match_zones,
)

HOUR4_NS = 4 * 3600 * 1_000_000_000
ATR = Decimal("10")
BASE = 1_704_067_200_000_000_000  # 2024-01-01T00:00:00Z


def _swing(
    swing_id: str,
    direction: str,
    price: str,
    bars: int,
    *,
    confirmed_bars: int | None = None,
) -> SwingCandidate:
    occurred = BASE + bars * HOUR4_NS
    confirmed = BASE + (confirmed_bars if confirmed_bars is not None else bars + 1) * HOUR4_NS
    return SwingCandidate(
        swing_id=swing_id,
        timeframe="4H",
        direction=direction,
        price=Decimal(price),
        occurred_at_ns=occurred,
        confirmed_at_ns=confirmed,
        atr_snapshot=ATR,
    )


def test_hungarian_solves_minimum_assignment() -> None:
    """匈牙利算法给出全局最小代价分配，而不是逐行贪心。"""
    cost = [
        [4.0, 1.0, 3.0],
        [2.0, 0.0, 5.0],
        [3.0, 2.0, 2.0],
    ]
    assignment = hungarian(cost)
    total = sum(cost[row][col] for row, col in enumerate(assignment))
    assert total == pytest.approx(5.0)


def test_single_pair_matches_with_metrics() -> None:
    """单对匹配给出时间、价格与确认延迟指标。"""
    human = [_swing("h1", "LOW", "100", 0)]
    program = [_swing("p1", "LOW", "100.5", 0, confirmed_bars=2)]
    report = match_swings(human, program, timeframe_duration_ns=HOUR4_NS, reference_atr=ATR)

    assert report.matched == 1
    assert report.matches[0].match_type is MatchType.MATCHED
    assert report.matches[0].time_error_bars == 0
    assert report.matches[0].price_error_atr == pytest.approx(0.05)
    assert report.matches[0].confirmation_delay_bars == pytest.approx(1.0)
    assert report.precision == 1.0
    assert report.recall == 1.0


def test_time_tolerance_rejects_far_candidates() -> None:
    """超出时间容差的候选不连边。"""
    human = [_swing("h1", "LOW", "100", 0)]
    program = [_swing("p1", "LOW", "100", 5)]
    report = match_swings(
        human,
        program,
        timeframe_duration_ns=HOUR4_NS,
        reference_atr=ATR,
        config=MatcherConfig(max_time_tolerance_bars=1),
    )
    assert report.matched == 0
    kinds = {item.match_type for item in report.matches}
    assert kinds == {MatchType.HUMAN_ONLY, MatchType.PROGRAM_ONLY}


def test_price_tolerance_rejects_far_candidates() -> None:
    """超出价格容差的候选不连边。"""
    human = [_swing("h1", "LOW", "100", 0)]
    program = [_swing("p1", "LOW", "110", 0)]
    report = match_swings(
        human,
        program,
        timeframe_duration_ns=HOUR4_NS,
        reference_atr=ATR,
        config=MatcherConfig(max_price_tolerance_atr=Decimal("0.5")),
    )
    assert report.matched == 0


def test_direction_and_timeframe_must_agree() -> None:
    """方向或周期不同不得匹配。"""
    human = [_swing("h1", "LOW", "100", 0)]
    high = [_swing("p1", "HIGH", "100", 0)]
    assert (
        match_swings(
            human,
            high,
            timeframe_duration_ns=HOUR4_NS,
            reference_atr=ATR,
        ).matched
        == 0
    )


def test_crossing_swings_use_global_assignment() -> None:
    """连续摆动交叉时，全局最小代价分配避免贪心误配。"""
    human = [_swing("h1", "LOW", "100", 0), _swing("h2", "LOW", "200", 2)]
    program = [_swing("p1", "LOW", "200.5", 2), _swing("p2", "LOW", "100.5", 0)]
    report = match_swings(human, program, timeframe_duration_ns=HOUR4_NS, reference_atr=ATR)
    pairs = {(item.human_id, item.program_id) for item in report.matches}
    assert pairs == {("h1", "p2"), ("h2", "p1")}


def test_ambiguous_match_is_flagged_when_costs_are_close() -> None:
    """两个候选代价几乎相同必须标记 AMBIGUOUS_MATCH 供人工复核。"""
    human = [_swing("h1", "LOW", "100", 0)]
    program = [_swing("p1", "LOW", "100.0", 0), _swing("p2", "LOW", "100.0", 0)]
    report = match_swings(human, program, timeframe_duration_ns=HOUR4_NS, reference_atr=ATR)
    assert report.ambiguous == 1
    assert any(item.match_type is MatchType.AMBIGUOUS_MATCH for item in report.matches)


def test_confirmation_weight_must_remain_zero() -> None:
    """SACW 27.4 固定 w_c = 0.00。"""
    with pytest.raises(ValueError):
        MatcherConfig(weight_confirmation=0.1)


def test_n_structure_requires_all_four_mapped_anchors() -> None:
    """四个锚点全部匹配且顺序一致才算候选。"""
    human = [
        {
            "structure_id": "HN-1",
            "l1": "hl1",
            "h1": "hh1",
            "l2": "hl2",
            "h2": "hh2",
            "confirmed_at_ns": BASE + 10 * HOUR4_NS,
            "status": "ACTIVE",
        },
    ]
    program = [
        {
            "structure_id": "PN-1",
            "l1": "pl1",
            "h1": "ph1",
            "l2": "pl2",
            "h2": "ph2",
            "confirmed_at_ns": BASE + 10 * HOUR4_NS,
            "status": "ACTIVE",
        },
    ]
    mapping = {"hl1": "pl1", "hh1": "ph1", "hl2": "pl2", "hh2": "ph2"}
    report = match_n_structures(
        human,
        program,
        swing_mapping=mapping,
        timeframe_duration_ns=HOUR4_NS,
    )
    assert report["results"][0]["match"] == "EXACT_MATCH"

    partial = match_n_structures(human, program, swing_mapping={"hl1": "pl1"})
    assert partial["results"][0]["match"] == "HUMAN_ONLY"


def test_n_structure_status_mismatch_is_reported() -> None:
    """状态不同必须报告 STATUS_MISMATCH。"""
    human = [
        {
            "structure_id": "HN-1",
            "l1": "a",
            "h1": "b",
            "l2": "c",
            "h2": "d",
            "confirmed_at_ns": BASE,
            "status": "ACTIVE",
        },
    ]
    program = [
        {
            "structure_id": "PN-1",
            "l1": "a",
            "h1": "b",
            "l2": "c",
            "h2": "d",
            "confirmed_at_ns": BASE,
            "status": "INVALIDATED",
        },
    ]
    report = match_n_structures(human, program, swing_mapping={})
    assert report["results"][0]["match"] == "STATUS_MISMATCH"


def test_zone_match_reports_anchor_precision_and_recall() -> None:
    """Zone 匹配以锚点为主，并给出精度/召回。"""
    human = [
        {
            "annotation_id": "ann-zone",
            "zone_type": "SUPPORT",
            "anchor_swing_ids": ["p1", "p2"],
            "annotation_mode": "ANCHOR_ONLY",
            "center": "3000",
        },
    ]
    program = [
        {
            "zone_id": "Z-1",
            "zone_type": "SUPPORT",
            "anchor_swing_ids": ["p1", "p2"],
            "center": "3000",
            "lower": "2990",
            "upper": "3010",
        },
        {
            "zone_id": "Z-2",
            "zone_type": "RESISTANCE",
            "anchor_swing_ids": ["p9"],
            "center": "3100",
            "lower": "3090",
            "upper": "3110",
        },
    ]
    report = match_zones(human, program)
    matched = [item for item in report["results"] if item["match"] == "MATCHED"]
    assert len(matched) == 1
    assert matched[0]["metrics"]["anchor_precision"] == 1.0
    assert matched[0]["metrics"]["anchor_recall"] == 1.0
    assert matched[0]["metrics"]["center_error"] == "0"


def test_zone_human_boundary_compares_errors_separately() -> None:
    """HUMAN_BOUNDARY 单独比较边界误差，不混入 ANCHOR_ONLY 主准确率。"""
    human = [
        {
            "annotation_id": "ann-human",
            "zone_type": "SUPPORT",
            "anchor_swing_ids": ["p1", "p2"],
            "annotation_mode": "HUMAN_BOUNDARY",
            "human_center": "3000",
            "human_lower": "2980",
            "human_upper": "3020",
        },
    ]
    program = [
        {
            "zone_id": "Z-1",
            "zone_type": "SUPPORT",
            "anchor_swing_ids": ["p1", "p2"],
            "center": "3000",
            "lower": "2990",
            "upper": "3010",
        },
    ]
    report = match_zones(human, program)
    metrics = report["results"][0]["metrics"]
    assert metrics["annotation_mode"] == "HUMAN_BOUNDARY"
    assert metrics["lower_error"] == "10"
    assert metrics["width_ratio"] == "0.5"
