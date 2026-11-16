"""把多周期识别结果组装成图表 JSON 载荷（规格 V1.4.8 / SACW V1.1.2）。

载荷分三部分：

- ``market``：宏观与结构状态、``CanOpen``/``CanHold``；
- ``timeframes``：每个周期的状态、指标、候选、结构与 Zone 统计；
- ``series``：每个周期的蜡烛、成交量、指标、ZigZag、摆动点、N 结构、Zone
  边界与保护点价格线。

SACW V1.1.2 第 17.1 节：``ATR_MA22`` 在 V1.4.8 中不存在，因此载荷**不提供**
该曲线，只给出 ``atrMaStatus = "N/A / SPEC_AMBIGUITY"``，前端不得自行计算或绘制。

价格在绘图时转为 ``float``；领域层与风控仍使用精确 ``Decimal``。
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from pa_trend.application.market_context import MarketSnapshot, TimeframeStateView
from pa_trend.application.timeframe_engine import ATR_MA_STATUS, TimeframeUpdate
from pa_trend.domain.models.bar import Bar
from pa_trend.domain.models.swing import SwingDirection, SwingPoint
from pa_trend.domain.models.timeframe import Timeframe
from pa_trend.domain.structure.n_structure import NStructure
from pa_trend.domain.structure.zone import Zone, ZoneStatus

NS_PER_SECOND = 1_000_000_000

#: 每个周期最多绘制的 N 结构数量（优先 ACTIVE，其次最近的终态结构）。
MAX_STRUCTURE_OVERLAYS = 4

#: 每个周期最多绘制的未关闭 Zone 数量与终态 Zone 数量。
MAX_OPEN_ZONES = 4
MAX_CLOSED_ZONES = 2

#: 只给最近若干个已确认摆动点标注价格文本，其余仅保留箭头，避免图上文字堆叠。
SWING_LABEL_TAIL = 8

_ZONE_COLORS = {
    "SUPPORT": "#26a69a",
    "RESISTANCE": "#ef5350",
}
_ZONE_CLOSED_COLORS = {
    ZoneStatus.BROKEN: "#5c6270",
    ZoneStatus.INVALIDATED: "#454a54",
}


def ns_to_chart_time(value: int) -> int:
    """把纳秒时间戳转换为 Lightweight Charts 使用的秒级时间戳。"""
    return value // NS_PER_SECOND


def bar_to_candle(bar: Bar) -> dict[str, float | int]:
    """把一根完成 Bar 转成蜡烛数据点，时间取窗口起始时刻。"""
    return {
        "time": ns_to_chart_time(bar.ts_open_ns),
        "open": float(bar.open),
        "high": float(bar.high),
        "low": float(bar.low),
        "close": float(bar.close),
        "isClosed": True,
        "closeTime": ns_to_chart_time(bar.ts_close_ns),
        "barId": bar.bar_id,
    }


def bar_to_volume(bar: Bar) -> dict[str, float | int | str]:
    """把一根 Bar 转成成交量数据点，并按涨跌着色。"""
    return {
        "time": ns_to_chart_time(bar.ts_open_ns),
        "value": float(bar.volume),
        "color": "rgba(38, 166, 154, 0.45)" if bar.is_bullish else "rgba(239, 83, 80, 0.45)",
    }


def indicator_points(
    updates: Sequence[TimeframeUpdate],
    attribute: str,
    *,
    field_name: str,
) -> list[dict[str, object]]:
    """提取某条指标曲线，跳过预热期间的 ``None``。

    SACW 17.3：每个指标点必须带 ``as_of_bar_time``、来源 Bar 与完成状态，
    前端不得用当前值冒充历史值。
    """
    points: list[dict[str, object]] = []
    for update in updates:
        value = getattr(update, attribute)
        if value is None:
            continue
        points.append(
            {
                "time": ns_to_chart_time(update.bar.ts_open_ns),
                "value": float(value),
                "field": field_name,
                "sourceBarId": update.bar.bar_id,
                "asOfBarTime": ns_to_chart_time(update.bar.ts_close_ns),
                "isClosed": True,
            },
        )
    return points


def zigzag_points(swings: Sequence[SwingPoint]) -> list[dict[str, float | int]]:
    """用已确认摆动点连成 ZigZag 折线。"""
    points = [
        {
            "time": ns_to_chart_time(point.occurred_at_ns),
            "value": float(point.price),
        }
        for point in swings
    ]
    points.sort(key=lambda item: item["time"])
    return points


def swing_markers(swings: Sequence[SwingPoint]) -> list[dict[str, object]]:
    """构造**已确认**摆动点标记，位置取极值发生时刻。

    只有最近 :data:`SWING_LABEL_TAIL` 个点带价格文本：几十个摆动点同时
    标注价格会让主图不可读，而完整价格仍可通过十字光标与标注面板读取。
    """
    markers: list[dict[str, object]] = []
    label_from = max(0, len(swings) - SWING_LABEL_TAIL)
    for index, point in enumerate(swings):
        is_high = point.direction is SwingDirection.HIGH
        markers.append(
            {
                "time": ns_to_chart_time(point.occurred_at_ns),
                "position": "aboveBar" if is_high else "belowBar",
                "color": "#ef5350" if is_high else "#26a69a",
                "shape": "arrowDown" if is_high else "arrowUp",
                "text": (f"{'H' if is_high else 'L'} {point.price}" if index >= label_from else ""),
                "confirmedTime": ns_to_chart_time(point.confirmed_at_ns),
                "swingId": point.point_id,
                "kind": "SWING",
                "price": float(point.price),
                "direction": point.direction.value,
                "atrSnapshot": float(point.atr_snapshot),
            },
        )
    markers.sort(key=lambda item: item["time"])
    return markers


def candidate_markers(updates: Sequence[TimeframeUpdate]) -> list[dict[str, object]]:
    """构造 ZigZag **候选**极值标记。

    只标记当前最新候选：每个 Bar 的候选历史快照都能画出一个标记，但把它们
    全部画出来会让主图被几百个「候选」标签淹没。完整候选序列仍通过
    ``candidates`` 字段逐 Bar 下发，供十字光标与侧栏读取。

    候选点尚未确认，因此使用与已确认 Swing 不同的形状（``square``）与灰色，
    避免被误读成已确认结构（SACW 17.1）。
    """
    markers: list[dict[str, object]] = []
    latest = next(
        (update.zigzag_candidate for update in reversed(updates) if update.zigzag_candidate),
        None,
    )
    if latest is not None:
        candidate = latest
        is_high = candidate.direction.value == "SEEK_HIGH"
        markers.append(
            {
                "time": ns_to_chart_time(candidate.occurred_at_ns),
                "position": "aboveBar" if is_high else "belowBar",
                "color": "#b0bec5",
                "shape": "square",
                "text": f"候选{'高' if is_high else '低'} {candidate.price}",
                "candidateId": candidate.candidate_id,
                "kind": "CANDIDATE",
                "price": float(candidate.price),
                "direction": candidate.direction.value,
                "barId": candidate.bar_id,
                "atrSnapshot": float(candidate.atr_snapshot),
                "reversalThreshold": float(candidate.reversal_threshold_price),
                "status": candidate.status,
            },
        )
    return markers


def candidate_series(updates: Sequence[TimeframeUpdate]) -> list[dict[str, object]]:
    """导出带候选极值的 Bar，供十字光标提示使用（SACW 17.3）。

    只输出存在候选的行：没有候选的 Bar 查询结果本就是“无候选”，逐 Bar 输出
    一整行空值会让载荷随历史长度线性膨胀（5000 根时约 1.5 MB/周期）。
    """
    points: list[dict[str, object]] = []
    for update in updates:
        candidate = update.zigzag_candidate
        if candidate is None:
            continue
        points.append(
            {
                "time": ns_to_chart_time(update.bar.ts_open_ns),
                "direction": update.zigzag_direction,
                "candidateId": candidate.candidate_id,
                "price": float(candidate.price),
                "atrSnapshot": float(candidate.atr_snapshot),
                "reversalThreshold": float(candidate.reversal_threshold_price),
                "candidateBarId": candidate.bar_id,
                "status": candidate.status,
            },
        )
    return points


def structure_overlays(
    structures: Sequence[NStructure],
    *,
    invalidation_status: str,
    visible_from: int | None = None,
    visible_to: int | None = None,
) -> list[dict[str, object]]:
    """构造是近若干条 N 结构的叠加数据。

    ``visible_from`` / ``visible_to`` 是图表实际下发的秒级时间范围。完全落在
    范围之外的结构在图上没有对应蜡烛，Lightweight Charts 会把它们压到最左/最右
    边缘画出一条孤立的短线（视觉“错断”），因此剔除；跨越边界的结构（L1 早于
    窗口起点、H2 仍在窗口内）是真实可见的，必须保留。
    """
    ordered = sorted(
        (
            item
            for item in structures
            if _overlaps_window(
                (
                    ns_to_chart_time(item.l1.occurred_at_ns),
                    ns_to_chart_time(item.h2.occurred_at_ns),
                ),
                visible_from,
                visible_to,
            )
        ),
        key=lambda item: (item.status.value != "ACTIVE", item.confirmed_at_ns),
    )
    selected = sorted(
        ordered[:MAX_STRUCTURE_OVERLAYS],
        key=lambda item: item.confirmed_at_ns,
    )
    overlays: list[dict[str, object]] = []
    for structure in selected:
        labels = (
            ("L1", structure.l1, "#26a69a"),
            ("H1", structure.h1, "#ef5350"),
            ("L2", structure.l2, "#26a69a"),
            ("H2", structure.h2, "#ef5350"),
        )
        points = [
            {
                "time": ns_to_chart_time(point.occurred_at_ns),
                "value": float(point.price),
                "label": label,
                "color": color,
            }
            for label, point, color in labels
        ]
        points.sort(key=lambda item: item["time"])
        overlays.append(
            {
                "id": structure.n_structure_id,
                "status": structure.status.value,
                "retracement": float(structure.retracement_ratio),
                "retracementClass": structure.retracement_class.value,
                "confirmedTime": ns_to_chart_time(structure.confirmed_at_ns),
                "breakoutPrice": float(structure.reference_price),
                "structuralStop": float(structure.structural_anchor),
                # SACW 27.6 / UI-020：失效判定 ATR 时点未定义，不得默认使用当前 ATR。
                "invalidationStatus": invalidation_status,
                "invalidationPrice": None,
                "anchors": [
                    {
                        "label": label,
                        "swingId": point.point_id,
                        "price": float(point.price),
                        "occurredAt": ns_to_chart_time(point.occurred_at_ns),
                        "confirmedAt": ns_to_chart_time(point.confirmed_at_ns),
                    }
                    for label, point, _ in labels
                ],
                "points": points,
            },
        )
    return overlays


def _overlaps_window(
    span: tuple[int, int],
    visible_from: int | None,
    visible_to: int | None,
) -> bool:
    """判断 ``span``（起止秒级时刻）与图表下发的时间范围是否相交。"""
    start, end = span
    if visible_to is not None and start > visible_to:
        return False
    return not (visible_from is not None and end < visible_from)


def _segment(start: int, end: int, value: Decimal) -> list[dict[str, float | int]]:
    """构造 Zone 边界线段的两个端点。"""
    return [
        {"time": start, "value": float(value)},
        {"time": end, "value": float(value)},
    ]


def zone_overlay(zone: Zone, *, end_time: int) -> dict[str, object]:
    """把单个 Zone 转成可绘制的边界与元数据。

    Lightweight Charts v4 没有原生价格带图层，因此前端用上边界、中心、
    下边界三条线表示同一 Zone，并在图例与侧栏标注状态与半宽决定性项。
    """
    start = ns_to_chart_time(zone.created_at_ns)
    end = end_time
    if zone.broken_at_ns is not None:
        end = ns_to_chart_time(zone.broken_at_ns)
    elif zone.invalidated_at_ns is not None:
        end = ns_to_chart_time(zone.invalidated_at_ns)
    if end <= start:
        # 单点区间无法画出线段；至少保留一个可见点。
        end = start + 1

    color = _ZONE_COLORS[zone.zone_type.value]
    if zone.status in _ZONE_CLOSED_COLORS:
        color = _ZONE_CLOSED_COLORS[zone.status]

    return {
        "id": zone.zone_id,
        "zoneType": zone.zone_type.value,
        "status": zone.status.value,
        "version": zone.version,
        "center": float(zone.center),
        "lower": float(zone.lower),
        "upper": float(zone.upper),
        "halfWidth": float(zone.half_width),
        "basis": zone.basis.value,
        "anchorCount": zone.anchor_count,
        "testCount": zone.test_count,
        "color": color,
        "createdAt": start,
        "updatedAt": ns_to_chart_time(zone.updated_at_ns),
        "endAt": end,
        "invalidationReason": zone.invalidation_reason,
        "anchors": [
            {
                "swingId": anchor.swing_id,
                "price": float(anchor.price),
                "occurredAt": ns_to_chart_time(anchor.occurred_at_ns),
                "confirmedAt": ns_to_chart_time(anchor.confirmed_at_ns),
            }
            for anchor in zone.anchors
        ],
        "segments": {
            "upper": _segment(start, end, zone.upper),
            "center": _segment(start, end, zone.center),
            "lower": _segment(start, end, zone.lower),
        },
    }


def zone_overlays(
    zones: Sequence[Zone],
    *,
    last_time: int,
    first_time: int | None = None,
) -> list[dict[str, object]]:
    """挑选需要绘制的 Zone：最近若干未关闭者 + 最近若干终态者。

    与 N 结构同理：完全落在图表时间范围之前的 Zone 不画，否则会贴着左边缘
    拉出与蜡烛无关的竖线。
    """
    zones = [
        zone
        for zone in zones
        if _overlaps_window(
            (
                ns_to_chart_time(zone.created_at_ns),
                ns_to_chart_time(zone.updated_at_ns),
            ),
            first_time,
            last_time,
        )
    ]
    open_zones = [zone for zone in zones if zone.is_open][-MAX_OPEN_ZONES:]
    closed_zones = [zone for zone in zones if zone.is_terminal][-MAX_CLOSED_ZONES:]
    selected = sorted([*closed_zones, *open_zones], key=lambda zone: zone.created_at_ns)
    return [zone_overlay(zone, end_time=last_time) for zone in selected]


def level_lines(view: TimeframeStateView) -> list[dict[str, object]]:
    """把保护点与回撤起点转成价格线定义。"""
    lines: list[dict[str, object]] = []
    if view.protected_low is not None:
        lines.append(
            {
                "price": float(view.protected_low),
                "title": "ProtectedLow",
                "color": "#26a69a",
            },
        )
    if view.protected_high is not None:
        lines.append(
            {
                "price": float(view.protected_high),
                "title": "ProtectedHigh",
                "color": "#ef5350",
            },
        )
    if view.pullback_origin_high is not None:
        lines.append(
            {
                "price": float(view.pullback_origin_high),
                "title": "PullbackOrigin",
                "color": "#ffb74d",
            },
        )
    return lines


def zone_events_payload(updates: Sequence[TimeframeUpdate]) -> list[dict[str, object]]:
    """导出逐 Bar 的 Zone 事件时间线。"""
    events: list[dict[str, object]] = []
    for update in updates:
        for event in update.zone_events:
            events.append(
                {
                    "type": event.event_type.value,
                    "zoneId": event.zone_id,
                    "zoneVersion": event.zone_version,
                    "time": ns_to_chart_time(event.at_ns),
                    "barTime": ns_to_chart_time(update.bar.ts_open_ns),
                    "barId": update.bar.bar_id,
                    "detail": dict(event.detail),
                },
            )
    return events


def build_timeframe_section(
    *,
    updates: Sequence[TimeframeUpdate],
    structures: Sequence[NStructure],
    zones: Sequence[Zone],
    view: TimeframeStateView,
) -> dict[str, object]:
    """构造单个周期的图表数据段。"""
    bars = [update.bar for update in updates]
    swings = [update.swing_point for update in updates if update.swing_point is not None]
    first_time = ns_to_chart_time(bars[0].ts_open_ns) if bars else None
    last_time = ns_to_chart_time(bars[-1].ts_close_ns) if bars else 0

    return {
        "candles": [bar_to_candle(bar) for bar in bars],
        "volume": [bar_to_volume(bar) for bar in bars],
        "sma": indicator_points(updates, "sma", field_name="SMA22"),
        "atr": indicator_points(updates, "atr", field_name="ATR14"),
        # SACW V1.1.2：ATR_MA22 未在 V1.4.8 中定义，不提供曲线、不自行计算。
        "atrMa": None,
        "atrMaStatus": ATR_MA_STATUS,
        "zigzag": zigzag_points(swings),
        "swingMarkers": swing_markers(swings),
        "candidateMarkers": candidate_markers(updates),
        "candidates": candidate_series(updates),
        "structures": structure_overlays(
            structures,
            invalidation_status=view.n_structure_invalidation_status,
            visible_from=first_time,
            visible_to=last_time,
        ),
        "zones": zone_overlays(zones, last_time=last_time, first_time=first_time),
        "zoneEvents": zone_events_payload(updates),
        "levelLines": level_lines(view),
        "state": view.state,
        "warm": view.warm,
        "bars": view.bars,
    }


def _decimal_to_float(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


def build_payload(
    *,
    instrument_id: str,
    source: str,
    session_offset_hours: int,
    snapshot: MarketSnapshot,
    sections: dict[Timeframe, dict[str, object]],
    config_hash: str | None = None,
    dataset_id: str | None = None,
) -> dict[str, object]:
    """组装完整载荷。"""
    timeframes = []
    for timeframe, view in snapshot.per_timeframe.items():
        timeframes.append(
            {
                "code": timeframe.value,
                "label": timeframe.label,
                "state": view.state,
                "bars": view.bars,
                "warm": view.warm,
                "structureReady": view.structure_ready,
                "swings": view.swings,
                "swingHighs": view.swing_highs,
                "swingLows": view.swing_lows,
                "structures": view.structures,
                "activeStructures": view.active_structures,
                "structureScope": view.structure_scope,
                "nStructureInvalidationStatus": view.n_structure_invalidation_status,
                "zigzagDirection": view.zigzag_direction,
                "zigzagCandidateId": view.zigzag_candidate_id,
                "zigzagCandidatePrice": _decimal_to_float(view.zigzag_candidate_price),
                "zigzagCandidateAtr": _decimal_to_float(view.zigzag_candidate_atr),
                "zigzagCandidateOccurredAt": (
                    None
                    if view.zigzag_candidate_occurred_at_ns is None
                    else ns_to_chart_time(view.zigzag_candidate_occurred_at_ns)
                ),
                "zigzagReversalThreshold": _decimal_to_float(view.zigzag_reversal_threshold),
                "zones": view.zones,
                "openZones": view.open_zones,
                "close": _decimal_to_float(view.close),
                "atr": _decimal_to_float(view.atr),
                "sma": _decimal_to_float(view.sma),
                "atrMaStatus": view.atr_ma_status,
                "protectedLow": _decimal_to_float(view.protected_low),
                "protectedHigh": _decimal_to_float(view.protected_high),
                "pullbackOriginHigh": _decimal_to_float(view.pullback_origin_high),
            },
        )

    return {
        "instrumentId": instrument_id,
        "source": source,
        "specVersion": "V1.4.8",
        "sacwVersion": "V1.1.2",
        "sessionOffsetHours": session_offset_hours,
        "configHash": config_hash,
        "datasetId": dataset_id,
        "atrMaStatus": ATR_MA_STATUS,
        "market": {
            "month": snapshot.month.value,
            "week": snapshot.week.value,
            "day": snapshot.day.value,
            "h4": snapshot.h4.value,
            "h1": snapshot.h1.value,
            "canOpen": snapshot.can_open,
            "canHold": snapshot.can_hold,
        },
        "timeframes": timeframes,
        "series": {timeframe.value: section for timeframe, section in sections.items()},
    }
