"""Zone 引擎测试（规格 V1.4.8 第 6 章）。"""

from __future__ import annotations

import pytest

from helpers import INSTRUMENT_ID, dec, make_bar, make_swing
from pa_trend.config.loader import load_config
from pa_trend.domain.models.swing import SwingDirection
from pa_trend.domain.models.timeframe import Timeframe
from pa_trend.domain.structure.zone import (
    HalfWidthBasis,
    ZoneEngine,
    ZoneEventType,
    ZoneParams,
    ZoneStatus,
    ZoneType,
    compute_zone_geometry,
    median,
)

CONFIGS_DIR = __file__.rsplit("/tests/", 1)[0] + "/configs"
TICK = dec("0.01")
ATR = dec("10")
PARAMS = ZoneParams()


def _engine(timeframe: Timeframe = Timeframe.WEEK) -> ZoneEngine:
    return ZoneEngine(
        instrument_id=INSTRUMENT_ID,
        timeframe=timeframe,
        tick_size=TICK,
        params=PARAMS,
    )


def _low(sequence: int, price: object, index: int, *, timeframe=Timeframe.WEEK):
    return make_swing(
        sequence=sequence,
        direction=SwingDirection.LOW,
        price=price,
        occurred_index=index,
        timeframe=timeframe,
        atr=ATR,
    )


def _high(sequence: int, price: object, index: int, *, timeframe=Timeframe.WEEK):
    return make_swing(
        sequence=sequence,
        direction=SwingDirection.HIGH,
        price=price,
        occurred_index=index,
        timeframe=timeframe,
        atr=ATR,
    )


# --------------------------------------------------------------------- 几何


def test_median_handles_odd_and_even_counts() -> None:
    """中位数：奇数取中间，偶数取中间两个的均值。"""
    assert median([dec(3), dec(1), dec(2)]) == dec(2)
    assert median([dec(1), dec(2), dec(3), dec(4)]) == dec("2.5")


def test_geometry_uses_max_of_three_terms() -> None:
    """半宽 = max(最小 tick 项, ATR 项, 锚点跨度项)。"""
    geometry = compute_zone_geometry(
        [dec(100), dec(103)],
        atr=ATR,
        tick_size=TICK,
        params=PARAMS,
    )
    assert geometry.center == dec("101.5")
    assert geometry.tick_term == dec("0.02")
    assert geometry.atr_term == dec("1.0")
    assert geometry.span_term == dec("1.5")
    assert geometry.half_width == dec("1.5")
    assert geometry.basis is HalfWidthBasis.ANCHOR_SPAN
    assert geometry.lower == dec(100)
    assert geometry.upper == dec(103)


def test_geometry_reports_min_ticks_basis_for_narrow_anchors() -> None:
    """锚点几乎重合且 ATR 很小时，由最小 tick 项决定半宽。"""
    geometry = compute_zone_geometry(
        [dec(3000), dec("3000.01")],
        atr=dec("0.05"),
        tick_size=TICK,
        params=PARAMS,
    )
    assert geometry.tick_term == dec("0.02")
    assert geometry.atr_term == dec("0.005")
    assert geometry.span_term == dec("0.005")
    assert geometry.half_width == dec("0.02")
    assert geometry.basis is HalfWidthBasis.MIN_TICKS


def test_geometry_basis_survives_decimal_quantization() -> None:
    """半宽定点化不得把决定性项误报为 MIN_TICKS。

    ATR 项为 0.1 × 50.6365610683... = 5.06365610683...，四舍五入到
    5.06365611；若先量化再比较，ATR 项会「小于」半宽而被误判成 tick 项。
    """
    geometry = compute_zone_geometry(
        [dec("2405.17"), dec("2400.63")],
        atr=dec("50.63656106831855319572630657"),
        tick_size=TICK,
        params=PARAMS,
    )
    assert geometry.basis is HalfWidthBasis.ATR
    assert geometry.half_width == dec("5.06365611")
    assert geometry.lower == dec("2397.83634389")
    assert geometry.upper == dec("2407.96365611")


def test_geometry_rejects_non_positive_atr_and_tick() -> None:
    """ATR 或 tick size 非正时拒绝计算，不静默回退。"""
    with pytest.raises(ValueError):
        compute_zone_geometry([dec(100)], atr=dec(0), tick_size=TICK, params=PARAMS)
    with pytest.raises(ValueError):
        compute_zone_geometry([dec(100)], atr=ATR, tick_size=dec(0), params=PARAMS)


def test_min_anchor_count_below_two_is_rejected() -> None:
    """FIXED：最小锚点数不得小于 2（规格第 6.5 节，PB-34）。"""
    with pytest.raises(ValueError):
        ZoneParams(min_anchor_count=1)


# --------------------------------------------------------------------- 聚类


def test_two_close_lows_form_an_active_support_zone() -> None:
    """两个接近的 SwingLow 聚成一个 SUPPORT，并从 CREATED 进入 ACTIVE。"""
    engine = _engine()
    first = engine.on_swing_point(_low(0, 100, 0), ATR)
    assert len(first) == 1
    zone = first[0]
    assert zone.zone_type is ZoneType.SUPPORT
    assert zone.status is ZoneStatus.CREATED
    assert zone.anchor_count == 1

    second = engine.on_swing_point(_low(1, 103, 1), ATR)
    assert second[0] is zone
    assert zone.status is ZoneStatus.ACTIVE
    assert zone.anchor_count == 2
    assert zone.center == dec("101.5")


def test_far_anchor_creates_a_separate_zone() -> None:
    """超出 merge_distance 的锚点不会并入既有 Zone。"""
    engine = _engine()
    engine.on_swing_point(_low(0, 100, 0), ATR)
    engine.on_swing_point(_low(1, 120, 1), ATR)
    assert len(engine.zones) == 2


def test_cluster_width_constraint_prevents_merge() -> None:
    """即使距离中心够近，超过聚类最大直径也不得合并。"""
    engine = _engine()
    engine.on_swing_point(_low(0, 100, 0), ATR)
    # 距离中心 4.9 <= 5，但跨度 9.8 <= 10 仍然合法；改成 9.9 则越界。
    engine.on_swing_point(_low(1, dec("109.9"), 1), ATR)
    assert len(engine.zones) == 2


def test_support_and_resistance_never_merge() -> None:
    """SUPPORT 与 RESISTANCE 是不同 Zone，不得互相合并。"""
    engine = _engine()
    engine.on_swing_point(_low(0, 100, 0), ATR)
    engine.on_swing_point(_high(1, 100, 1), ATR)
    assert len(engine.zones) == 2
    types = {zone.zone_type for zone in engine.zones}
    assert types == {ZoneType.SUPPORT, ZoneType.RESISTANCE}


def test_missing_atr_ignores_the_anchor() -> None:
    """ATR 预热未完成时无法计算聚类阈值，不得凭空建 Zone。"""
    engine = _engine()
    assert engine.on_swing_point(_low(0, 100, 0), None) == ()
    assert engine.zones == ()


def test_closest_zone_wins_then_earliest_created() -> None:
    """多个候选 Zone 时按「距离最小 → 创建最早 → ID 字典序」选择。"""
    engine = _engine()
    engine.on_swing_point(_low(0, 95, 0), ATR)
    engine.on_swing_point(_low(1, 105, 1), ATR)
    assert len(engine.zones) == 2

    # 价格 101 距离 105 的中心 4、距离 95 的中心 6（超过 merge 上限 5），
    # 因此只能并入中心为 105 的那个 Zone。
    far_zone, near_zone = engine.zones
    merged = engine.on_swing_point(_low(2, 101, 2), ATR)
    assert merged[0] is near_zone
    assert near_zone.anchor_count == 2
    assert far_zone.anchor_count == 1


# --------------------------------------------------------------------- 状态机


def test_active_zone_can_break_without_being_tested() -> None:
    """ACTIVE → BROKEN 必须支持，不要求先进入 TESTED（规格第 6.2 节）。"""
    engine = _engine()
    engine.on_swing_point(_low(0, 100, 0), ATR)
    engine.on_swing_point(_low(1, 103, 1), ATR)
    zone = engine.zones[0]
    assert zone.status is ZoneStatus.ACTIVE

    bar = make_bar(index=5, timeframe=Timeframe.WEEK, open_price=100, high=101, low=98, close=98)
    events = engine.on_bar(bar, ATR)
    kinds = [event.event_type for event in events]
    assert ZoneEventType.BROKEN in kinds
    assert zone.status is ZoneStatus.BROKEN
    assert zone.broken_at_ns == bar.ts_close_ns


def test_broken_is_evaluated_before_tested() -> None:
    """突破判定先于测试判定执行（规格第 6.2 节）。

    说明：在规格给定的两组条件下，「SUPPORT 测试」要求 ``Close > center``，
    而「SUPPORT 突破」要求 ``Close < lower - buffer``，两者互相排斥；因此
    该优先级规则是防御性的。这里验证的是**判定顺序**：一旦收盘已跌破缓冲
    价，即使影线重新回到测试带内，也不会被登记为 TESTED。
    """
    engine = _engine()
    engine.on_swing_point(_low(0, 100, 0), ATR)
    engine.on_swing_point(_low(1, 103, 1), ATR)
    zone = engine.zones[0]

    # lower=100，break buffer=1 → close=98 触发突破；low=98 亦在测试带外，
    # 说明只依赖收盘价即可判定，无需影线参与。
    bar = make_bar(
        index=6,
        timeframe=Timeframe.WEEK,
        open_price=99,
        high=100,
        low=98,
        close=98,
    )
    events = engine.on_bar(bar, ATR)
    kinds = [event.event_type for event in events]
    assert ZoneEventType.BROKEN in kinds
    assert ZoneEventType.TESTED not in kinds
    assert zone.status is ZoneStatus.BROKEN


def test_support_test_requires_close_above_center() -> None:
    """SUPPORT 测试要求收盘不低于容差下沿且高于中心（规格第 6.6 节）。"""
    engine = _engine()
    engine.on_swing_point(_low(0, 100, 0), ATR)
    engine.on_swing_point(_low(1, 103, 1), ATR)
    zone = engine.zones[0]

    above = make_bar(
        index=7,
        timeframe=Timeframe.WEEK,
        open_price=102,
        high=103,
        low=100,
        close=102,
    )
    events = engine.on_bar(above, ATR)
    assert ZoneEventType.TESTED in [event.event_type for event in events]
    assert zone.status is ZoneStatus.TESTED


def test_resistance_test_and_break() -> None:
    """RESISTANCE 的测试与突破方向与 SUPPORT 相反。"""
    engine = _engine()
    engine.on_swing_point(_high(0, 200, 0), ATR)
    engine.on_swing_point(_high(1, 203, 1), ATR)
    zone = engine.zones[0]
    assert zone.zone_type is ZoneType.RESISTANCE

    tested = make_bar(
        index=8,
        timeframe=Timeframe.WEEK,
        open_price=201,
        high=202,
        low=199,
        close=201,
    )
    events = engine.on_bar(tested, ATR)
    assert ZoneEventType.TESTED in [event.event_type for event in events]

    bar = make_bar(
        index=9,
        timeframe=Timeframe.WEEK,
        open_price=205,
        high=206,
        low=204,
        close=206,
    )
    events = engine.on_bar(bar, ATR)
    assert ZoneEventType.BROKEN in [event.event_type for event in events]
    assert zone.status is ZoneStatus.BROKEN


def test_created_zone_never_tests_or_breaks() -> None:
    """单锚点 CREATED Zone 不得因测试或突破改变状态。"""
    engine = _engine()
    engine.on_swing_point(_low(0, 100, 0), ATR)
    zone = engine.zones[0]
    bar = make_bar(index=9, timeframe=Timeframe.WEEK, open_price=90, high=91, low=80, close=80)
    assert engine.on_bar(bar, ATR) == ()
    assert zone.status is ZoneStatus.CREATED


def test_zone_version_increments_on_anchor_and_status_change() -> None:
    """锚点增加与状态变化都递增 zone_version（规格第 6.9 节）。"""
    engine = _engine()
    engine.on_swing_point(_low(0, 100, 0), ATR)
    zone = engine.zones[0]
    assert zone.version == 1

    engine.on_swing_point(_low(1, 103, 1), ATR)
    assert zone.version > 1
    version_after_anchor = zone.version

    bar = make_bar(index=10, timeframe=Timeframe.WEEK, open_price=100, high=101, low=98, close=98)
    engine.on_bar(bar, ATR)
    assert zone.version > version_after_anchor
    assert zone.status is ZoneStatus.BROKEN


def test_terminal_zone_is_not_revived() -> None:
    """BROKEN 为终态：后续不再测试、不再吸收锚点。"""
    engine = _engine()
    engine.on_swing_point(_low(0, 100, 0), ATR)
    engine.on_swing_point(_low(1, 103, 1), ATR)
    zone = engine.zones[0]
    bar = make_bar(index=11, timeframe=Timeframe.WEEK, open_price=100, high=101, low=98, close=98)
    engine.on_bar(bar, ATR)
    assert zone.status is ZoneStatus.BROKEN

    again = make_bar(
        index=12,
        timeframe=Timeframe.WEEK,
        open_price=101,
        high=103,
        low=100,
        close=102,
    )
    assert engine.on_bar(again, ATR) == ()
    assert zone.status is ZoneStatus.BROKEN


# --------------------------------------------------------------------- 年龄


def test_anchor_expiry_invalidates_the_zone() -> None:
    """锚点全部超龄后剩余锚点不足，Zone 进入 INVALIDATED（规格第 6.8 节）。"""
    params = ZoneParams(max_age_weeks=1)
    engine = ZoneEngine(
        instrument_id=INSTRUMENT_ID,
        timeframe=Timeframe.WEEK,
        tick_size=TICK,
        params=params,
    )
    engine.on_swing_point(_low(0, 100, 0), ATR)
    engine.on_swing_point(_low(1, 103, 1), ATR)
    zone = engine.zones[0]
    assert zone.status is ZoneStatus.ACTIVE

    # 第 3 周时锚点 confirmed_at（第 0、1 周）已超过 1 周。
    bar = make_bar(index=3, timeframe=Timeframe.WEEK, open_price=101, high=102, low=100, close=101)
    events = engine.on_bar(bar, ATR)
    kinds = [event.event_type for event in events]
    assert ZoneEventType.ANCHOR_EXPIRED in kinds
    assert ZoneEventType.INVALIDATED in kinds
    assert zone.status is ZoneStatus.INVALIDATED
    assert zone.invalidation_reason == "ANCHOR_AGE"
    assert zone.anchor_count == 0


def test_zone_survives_while_one_anchor_remains_fresh() -> None:
    """只要剩余锚点仍达到最小数量，Zone 不因部分锚点过期而失效。"""
    params = ZoneParams(max_age_weeks=2)
    engine = ZoneEngine(
        instrument_id=INSTRUMENT_ID,
        timeframe=Timeframe.WEEK,
        tick_size=TICK,
        params=params,
    )
    engine.on_swing_point(_low(0, 100, 0), ATR)
    engine.on_swing_point(_low(1, 103, 1), ATR)
    engine.on_swing_point(_low(2, 101, 2), ATR)
    zone = engine.zones[0]
    assert zone.anchor_count == 3

    bar = make_bar(index=3, timeframe=Timeframe.WEEK, open_price=101, high=102, low=100, close=101)
    engine.on_bar(bar, ATR)
    # 第 0 周锚点超龄，剩余 2 个仍满足 min_anchor_count=2。
    assert zone.anchor_count == 2
    assert zone.status in {ZoneStatus.ACTIVE, ZoneStatus.TESTED}


# --------------------------------------------------------------------- 配置


def test_config_zone_parameters_match_spec_initial_values() -> None:
    """冻结配置中的 Zone 参数与规格第 19 章初始值一致。"""
    from pathlib import Path

    config = load_config(Path(CONFIGS_DIR))
    assert config.zone.min_anchor_count == 2
    assert config.zone.merge_distance_atr == dec("0.5")
    assert config.zone.max_cluster_width_atr == dec("1.0")
    assert config.zone.half_width_atr == dec("0.1")
    assert config.zone.min_half_width_ticks == 2
    assert config.zone.test_tolerance_atr == dec("0.1")
    assert config.zone.break_buffer_atr == dec("0.1")
    assert config.zone.max_age_weeks == 52
    assert config.tick_size == TICK
