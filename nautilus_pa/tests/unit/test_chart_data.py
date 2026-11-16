"""图表载荷测试（规格 V1.4.8 / SACW V1.1.2）。"""

from __future__ import annotations

import json
from collections import deque
from pathlib import Path

from helpers import INSTRUMENT_ID, dec, make_bar
from pa_trend.application.demo_data import generate_demo_bars
from pa_trend.application.market_context import MarketContext
from pa_trend.application.timeframe_engine import TimeframeUpdate
from pa_trend.config.loader import load_config
from pa_trend.domain.models.timeframe import ALL_TIMEFRAMES, Timeframe
from pa_trend.presentation.chart_data import (
    bar_to_candle,
    build_payload,
    build_timeframe_section,
    level_lines,
    ns_to_chart_time,
    structure_overlays,
    swing_markers,
    zigzag_points,
)

CONFIGS_DIR = Path(__file__).resolve().parents[2] / "configs"


def _build() -> tuple[dict[str, object], MarketContext]:
    config = load_config(CONFIGS_DIR)
    context = MarketContext(config)
    updates: dict[Timeframe, deque[TimeframeUpdate]] = {
        timeframe: deque(maxlen=500) for timeframe in ALL_TIMEFRAMES
    }
    for timeframe in ALL_TIMEFRAMES:
        for bar in generate_demo_bars(
            instrument_id=INSTRUMENT_ID,
            timeframe=timeframe,
            count=150,
        ):
            updates[timeframe].append(context.on_bar(bar))

    snapshot = context.snapshot()
    sections = {
        timeframe: build_timeframe_section(
            updates=list(updates[timeframe]),
            structures=context.engine(timeframe).structures.structures,
            zones=context.engine(timeframe).zones.zones,
            view=snapshot.per_timeframe[timeframe],
        )
        for timeframe in ALL_TIMEFRAMES
    }
    payload = build_payload(
        instrument_id=INSTRUMENT_ID,
        source="test",
        session_offset_hours=8,
        snapshot=snapshot,
        sections=sections,
    )
    return payload, context


def test_ns_to_chart_time_floors_to_seconds() -> None:
    """纳秒向下取整为秒。"""
    assert ns_to_chart_time(1_700_000_000_999_999_999) == 1_700_000_000


def test_bar_to_candle_uses_open_time() -> None:
    """蜡烛时间取窗口起始时刻。"""
    bar = make_bar(index=0)
    candle = bar_to_candle(bar)
    assert candle["time"] == ns_to_chart_time(bar.ts_open_ns)
    assert candle["close"] == float(bar.close)
    assert candle["isClosed"] is True


def test_payload_contains_seven_timeframes_and_market() -> None:
    """载荷需含七个周期与市场权限块。"""
    payload, _ = _build()

    assert payload["specVersion"] == "V1.4.8"
    assert payload["sacwVersion"] == "V1.1.2"
    assert payload["sessionOffsetHours"] == 8
    assert len(payload["timeframes"]) == len(ALL_TIMEFRAMES)

    market = payload["market"]
    assert market["month"] == "UPTREND"
    assert market["canOpen"] is True
    assert "canHold" in market


def test_atr_ma22_is_reported_as_spec_ambiguity() -> None:
    """SACW V1.1.2 17.1：不得下发 ATR_MA22 曲线。"""
    payload, _ = _build()
    assert payload["atrMaStatus"] == "N/A / SPEC_AMBIGUITY"
    for code, section in payload["series"].items():
        assert section["atrMa"] is None, code
        assert section["atrMaStatus"] == "N/A / SPEC_AMBIGUITY", code
    for frame in payload["timeframes"]:
        assert frame["atrMaStatus"] == "N/A / SPEC_AMBIGUITY"


def test_payload_is_json_serializable_and_ordered() -> None:
    """载荷可序列化，且各序列时间严格递增。"""
    payload, _ = _build()
    text = json.dumps(payload, ensure_ascii=False)
    restored = json.loads(text)

    for code, section in restored["series"].items():
        for key in ("candles", "volume", "sma", "atr", "zigzag"):
            times = [item["time"] for item in section[key]]
            assert times == sorted(times), f"{code}.{key} 未按时间升序"
        candle_times = [item["time"] for item in section["candles"]]
        assert len(candle_times) == len(set(candle_times))


def test_timeframe_metadata_matches_series() -> None:
    """周期列表与序列一一对应。"""
    payload, _ = _build()
    codes = {item["code"] for item in payload["timeframes"]}
    assert codes == {timeframe.value for timeframe in ALL_TIMEFRAMES}
    assert set(payload["series"].keys()) == codes


def test_indicator_points_carry_source_bar_and_as_of_time() -> None:
    """SACW 17.3：指标点必须带来源 Bar 与 as_of_bar_time。"""
    payload, _ = _build()
    section = payload["series"]["4H"]
    assert section["sma"]
    for point in section["sma"]:
        assert point["field"] == "SMA22"
        assert point["sourceBarId"]
        assert point["asOfBarTime"] >= point["time"]
        assert point["isClosed"] is True
    for point in section["atr"]:
        assert point["field"] == "ATR14"


def test_structure_overlays_have_four_points() -> None:
    """N 结构叠加应有四个按时间升序的标注点。"""
    _, context = _build()
    structures = context.engine(Timeframe.DAY).structures.structures
    assert structures

    overlays = structure_overlays(structures, invalidation_status="SPEC_AMBIGUITY")
    labels = [point["label"] for point in overlays[0]["points"]]
    assert sorted(labels) == ["H1", "H2", "L1", "L2"]
    times = [point["time"] for point in overlays[0]["points"]]
    assert times == sorted(times)
    # SACW 27.6：失效判定被阻塞，不得给出失效价。
    assert overlays[0]["invalidationStatus"] == "SPEC_AMBIGUITY"
    assert overlays[0]["invalidationPrice"] is None
    assert len(overlays[0]["anchors"]) == 4


def test_swing_markers_are_sorted() -> None:
    """摆动点标记按时间升序。"""
    _, context = _build()
    swings = context.engine(Timeframe.DAY).swings
    markers = swing_markers(swings)
    times = [marker["time"] for marker in markers]
    assert times == sorted(times)
    assert all(marker["shape"] in {"arrowUp", "arrowDown"} for marker in markers)
    assert all(marker["kind"] == "SWING" for marker in markers)


def test_level_lines_include_protected_levels() -> None:
    """保护点应转成价格线定义。"""
    _, context = _build()
    view = context.view(Timeframe.DAY)
    lines = level_lines(view)
    titles = {line["title"] for line in lines}
    assert "ProtectedLow" in titles
    if view.protected_high is not None:
        assert "ProtectedHigh" in titles
    for line in lines:
        assert isinstance(line["price"], float)


def test_warmup_section_has_no_indicator_points() -> None:
    """预热不足时指标序列为空。"""
    config = load_config(CONFIGS_DIR)
    context = MarketContext(config)
    updates = [
        context.on_bar(bar)
        for bar in generate_demo_bars(
            instrument_id=INSTRUMENT_ID,
            timeframe=Timeframe.DAY,
            count=5,
        )
    ]
    section = build_timeframe_section(
        updates=updates,
        structures=(),
        zones=(),
        view=context.view(Timeframe.DAY),
    )
    assert section["sma"] == []
    assert section["atr"] == []
    assert section["warm"] is False


def test_protected_low_is_decimal_in_view() -> None:
    """视图中的保护点仍是精确 Decimal。"""
    _, context = _build()
    view = context.view(Timeframe.DAY)
    assert view.protected_low is None or isinstance(view.protected_low, type(dec("1")))


def test_zigzag_points_use_occurred_time() -> None:
    """ZigZag 折线使用极值发生时刻。"""
    _, context = _build()
    swings = context.engine(Timeframe.DAY).swings
    points = zigzag_points(swings)
    assert points
    assert points[0]["time"] == ns_to_chart_time(swings[0].occurred_at_ns)


def test_sections_expose_zones_and_candidates() -> None:
    """Zone 与 ZigZag 候选必须出现在载荷中（SACW 17.1、21.x）。"""
    payload, _ = _build()
    section = payload["series"]["4H"]

    zones = section["zones"]
    assert isinstance(zones, list)
    for zone in zones:
        assert zone["zoneType"] in {"SUPPORT", "RESISTANCE"}
        assert zone["status"] in {"CREATED", "ACTIVE", "TESTED", "BROKEN", "INVALIDATED"}
        assert zone["lower"] <= zone["center"] <= zone["upper"]
        assert zone["basis"] in {"MIN_TICKS", "ATR", "ANCHOR_SPAN"}
        assert len(zone["segments"]["upper"]) == 2

    candidates = section["candidates"]
    assert len(candidates) == len(section["candles"])
    assert any(item["direction"] in {"SEEK_HIGH", "SEEK_LOW"} for item in candidates)

    frames = {frame["code"]: frame for frame in payload["timeframes"]}
    assert frames["15M"]["nStructureInvalidationStatus"] == "SPEC_AMBIGUITY"
    assert frames["4H"]["nStructureInvalidationStatus"] == "RESEARCH_ONLY"
