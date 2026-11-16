"""Zone 支撑阻力区域引擎（规格 V1.4.8 第 6 章）。

实现内容严格对应规格第 6.1 至 6.9 节：

- 聚类：同周期、同方向的已确认 SwingPoint 聚类（第 6.3 节）；
- 几何：``center = median(P)``、``half_width = max(最小 tick 项, ATR 项, 锚点跨度项)``
  （第 6.4 节）；
- 状态机：``CREATED / ACTIVE / TESTED / BROKEN / INVALIDATED``（第 6.2、6.5 至
  6.7 节）；
- 锚点年龄：超过 ``zone.max_age_weeks`` 的锚点被移除，剩余锚点不足
  ``min_anchor_count`` 时 Zone 进入 ``INVALIDATED``（第 6.8 节）；
- 版本：锚点、中心、边界或状态变化都递增 ``zone_version``（第 6.9 节）。

本模块只做区域识别，不产生 Setup/Signal；第 6.10 节的版本传播由上层实现。

半宽决定性项（SACW 21.4）通过 :class:`HalfWidthBasis` 标注，避免把「因最小 tick
支撑而变宽」误判为边界估计误差。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum

from pa_trend.domain.models.bar import Bar
from pa_trend.domain.models.swing import SwingDirection, SwingPoint
from pa_trend.domain.models.timeframe import Timeframe

NS_PER_WEEK = 7 * 24 * 60 * 60 * 1_000_000_000

#: 价格量化精度：8 位小数，远小于任何交易所 tick size，同时避免除不尽的
#: 十进制尾数在界面与报告中无限扩散。
_PRICE_QUANTUM = Decimal("0.00000001")

#: ``median`` 使用同一精度，保证中心价与边界价口径一致。
_MEDIAN_QUANTUM = _PRICE_QUANTUM


class ZoneType(StrEnum):
    """Zone 类型（规格第 6.1 节）。"""

    SUPPORT = "SUPPORT"
    RESISTANCE = "RESISTANCE"


class ZoneStatus(StrEnum):
    """Zone 生命周期状态（规格第 6.2 节）。"""

    CREATED = "CREATED"
    ACTIVE = "ACTIVE"
    TESTED = "TESTED"
    BROKEN = "BROKEN"
    INVALIDATED = "INVALIDATED"


class HalfWidthBasis(StrEnum):
    """``half_width`` 由哪一项决定（SACW 21.4 要求显式标注）。"""

    MIN_TICKS = "MIN_TICKS"
    ATR = "ATR"
    ANCHOR_SPAN = "ANCHOR_SPAN"


class ZoneEventType(StrEnum):
    """Zone 状态或结构变化事件类型。"""

    CREATED = "ZONE_CREATED"
    ANCHOR_ADDED = "ZONE_ANCHOR_ADDED"
    ACTIVATED = "ZONE_ACTIVATED"
    TESTED = "ZONE_TESTED"
    BROKEN = "ZONE_BROKEN"
    INVALIDATED = "ZONE_INVALIDATED"
    ANCHOR_EXPIRED = "ZONE_ANCHOR_EXPIRED"


_OPEN_STATUSES = frozenset({ZoneStatus.CREATED, ZoneStatus.ACTIVE, ZoneStatus.TESTED})
_TERMINAL_STATUSES = frozenset({ZoneStatus.BROKEN, ZoneStatus.INVALIDATED})


@dataclass(frozen=True, slots=True)
class ZoneAnchor:
    """参与某个 Zone 聚类的一个已确认 SwingPoint 引用。"""

    swing_id: str
    price: Decimal
    occurred_at_ns: int
    confirmed_at_ns: int
    sequence: int


@dataclass(frozen=True, slots=True)
class ZoneGeometry:
    """Zone 的几何结果与决定性项。"""

    center: Decimal
    half_width: Decimal
    lower: Decimal
    upper: Decimal
    basis: HalfWidthBasis
    atr_term: Decimal
    tick_term: Decimal
    span_term: Decimal

    def as_snapshot(self) -> dict[str, str]:
        """返回可写入标注快照的字符串映射（价格保持十进制精度）。"""
        return {
            "center": str(self.center),
            "half_width": str(self.half_width),
            "lower": str(self.lower),
            "upper": str(self.upper),
            "half_width_basis": self.basis.value,
            "atr_term": str(self.atr_term),
            "tick_term": str(self.tick_term),
            "span_term": str(self.span_term),
        }


@dataclass(frozen=True, slots=True)
class ZoneParams:
    """冻结的 Zone 参数（规格第 19 章）。"""

    merge_distance_atr: Decimal = Decimal("0.5")
    max_cluster_width_atr: Decimal = Decimal("1.0")
    half_width_atr: Decimal = Decimal("0.1")
    min_half_width_ticks: int = 2
    test_tolerance_atr: Decimal = Decimal("0.1")
    break_buffer_atr: Decimal = Decimal("0.1")
    max_age_weeks: int = 52
    min_anchor_count: int = 2

    def __post_init__(self) -> None:
        """校验 FIXED 与数值边界。"""
        if self.min_anchor_count < 2:
            raise ValueError(
                f"min_anchor_count is FIXED at 2 per spec section 6.5, was {self.min_anchor_count}",
            )
        for name in (
            "merge_distance_atr",
            "max_cluster_width_atr",
            "half_width_atr",
            "test_tolerance_atr",
            "break_buffer_atr",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be >= 0")
        if self.min_half_width_ticks < 0:
            raise ValueError("min_half_width_ticks must be >= 0")
        if self.max_age_weeks <= 0:
            raise ValueError("max_age_weeks must be > 0")

    @property
    def max_age_ns(self) -> int:
        """锚点最大年龄（纳秒）。"""
        return self.max_age_weeks * NS_PER_WEEK


def median(values: list[Decimal]) -> Decimal:
    """返回中位数；偶数个时取中间两个的均值。"""
    ordered = sorted(values)
    count = len(ordered)
    if count == 0:
        raise ValueError("median of an empty sequence is undefined")
    middle = count // 2
    if count % 2 == 1:
        return ordered[middle]
    return ((ordered[middle - 1] + ordered[middle]) / 2).quantize(_MEDIAN_QUANTUM)


def compute_zone_geometry(
    anchor_prices: list[Decimal],
    *,
    atr: Decimal,
    tick_size: Decimal,
    params: ZoneParams,
) -> ZoneGeometry:
    """按规格第 6.4 节计算 Zone 几何。

    参数
    ----
    anchor_prices : list of Decimal
        参与聚类的锚点价格集合 ``P``。
    atr : Decimal
        该周期当前 ATR。
    tick_size : Decimal
        合约最小价格变动单位（METADATA）。
    params : ZoneParams
        冻结的 Zone 参数。

    返回
    ----
    ZoneGeometry
        含中心、半宽、上下边界以及半宽的决定性项。
    """
    if not anchor_prices:
        raise ValueError("zone geometry requires at least one anchor price")
    if atr <= 0:
        raise ValueError(f"zone geometry requires a positive ATR, was {atr}")
    if tick_size <= 0:
        raise ValueError(f"zone geometry requires a positive tick size, was {tick_size}")

    center = median(anchor_prices)
    tick_term = params.min_half_width_ticks * tick_size
    atr_term = params.half_width_atr * atr
    span_term = (max(anchor_prices) - min(anchor_prices)) / 2

    # 先比较未量化的三项，再对半宽定点化：若先量化再比较，ATR 项可能因
    # 进位被判定为「小于」半宽，从而把决定性项错误地标成 MIN_TICKS。
    raw_half_width = max(tick_term, atr_term, span_term)
    half_width = raw_half_width.quantize(_PRICE_QUANTUM)
    # 相等时按 ANCHOR_SPAN > ATR > MIN_TICKS 的顺序报告决定性项，
    # 保证同一输入永远得到同一标注结果。
    if span_term >= raw_half_width:
        basis = HalfWidthBasis.ANCHOR_SPAN
    elif atr_term >= raw_half_width:
        basis = HalfWidthBasis.ATR
    else:
        basis = HalfWidthBasis.MIN_TICKS

    return ZoneGeometry(
        center=center,
        half_width=half_width,
        lower=(center - half_width).quantize(_PRICE_QUANTUM),
        upper=(center + half_width).quantize(_PRICE_QUANTUM),
        basis=basis,
        atr_term=atr_term,
        tick_term=tick_term,
        span_term=span_term,
    )


@dataclass(slots=True)
class Zone:
    """一个 Zone 实体；状态只向前推进，``BROKEN`` 与 ``INVALIDATED`` 为终态。"""

    zone_id: str
    instrument_id: str
    timeframe: Timeframe
    zone_type: ZoneType
    status: ZoneStatus
    version: int
    anchors: tuple[ZoneAnchor, ...]
    geometry: ZoneGeometry
    created_at_ns: int
    updated_at_ns: int
    test_count: int = 0
    broken_at_ns: int | None = None
    invalidated_at_ns: int | None = None
    invalidation_reason: str | None = None
    events: list[str] = field(default_factory=list)

    @property
    def center(self) -> Decimal:
        """Zone 中心价。"""
        return self.geometry.center

    @property
    def half_width(self) -> Decimal:
        """Zone 半宽。"""
        return self.geometry.half_width

    @property
    def lower(self) -> Decimal:
        """Zone 下边界。"""
        return self.geometry.lower

    @property
    def upper(self) -> Decimal:
        """Zone 上边界。"""
        return self.geometry.upper

    @property
    def basis(self) -> HalfWidthBasis:
        """半宽的决定性项。"""
        return self.geometry.basis

    @property
    def anchor_count(self) -> int:
        """当前有效锚点数量。"""
        return len(self.anchors)

    @property
    def is_open(self) -> bool:
        """是否仍可能继续吸收锚点或发生状态变化。"""
        return self.status in _OPEN_STATUSES

    @property
    def is_terminal(self) -> bool:
        """是否为终态。"""
        return self.status in _TERMINAL_STATUSES

    def contains(self, price: Decimal) -> bool:
        """价格是否落在 Zone 边界内。"""
        return self.lower <= price <= self.upper


@dataclass(frozen=True, slots=True)
class ZoneEvent:
    """一次 Zone 结构变化事件。"""

    event_type: ZoneEventType
    zone_id: str
    zone_version: int
    timeframe: Timeframe
    at_ns: int
    detail: dict[str, str] = field(default_factory=dict)


class ZoneEngine:
    """单周期 Zone 引擎（聚类、几何、状态机、年龄、版本）。"""

    def __init__(
        self,
        *,
        instrument_id: str,
        timeframe: Timeframe,
        tick_size: Decimal,
        params: ZoneParams | None = None,
    ) -> None:
        """初始化引擎。

        参数
        ----
        instrument_id : str
            合约标识。
        timeframe : Timeframe
            本引擎负责的周期；禁止跨周期合并（第 6.1 节）。
        tick_size : Decimal
            合约最小价格变动单位（METADATA）。
        params : ZoneParams 或 None
            冻结参数；缺省使用规格初始值。
        """
        if tick_size <= 0:
            raise ValueError(f"tick_size must be positive, was {tick_size}")
        self._instrument_id = instrument_id
        self._timeframe = timeframe
        self._tick_size = tick_size
        self._params = params or ZoneParams()
        self._zones: dict[str, Zone] = {}
        self._sequence = 0

    @property
    def timeframe(self) -> Timeframe:
        """返回本引擎负责的周期。"""
        return self._timeframe

    @property
    def params(self) -> ZoneParams:
        """返回冻结参数。"""
        return self._params

    @property
    def tick_size(self) -> Decimal:
        """返回合约 tick size。"""
        return self._tick_size

    @property
    def zones(self) -> tuple[Zone, ...]:
        """按创建顺序返回全部 Zone。"""
        return tuple(self._zones.values())

    @property
    def open_zones(self) -> tuple[Zone, ...]:
        """返回尚未进入终态的 Zone。"""
        return tuple(zone for zone in self._zones.values() if zone.is_open)

    def active_zone(self, zone_id: str) -> Zone | None:
        """按 ID 查找 Zone。"""
        return self._zones.get(zone_id)

    # ------------------------------------------------------------------ 聚类

    def on_swing_point(
        self,
        point: SwingPoint,
        atr_value: Decimal | None,
    ) -> tuple[Zone, ...]:
        """接收一个已确认 SwingPoint，按第 6.3 节聚类。

        参数
        ----
        point : SwingPoint
            刚确认的摆动点；必须是本合约、本周期的已确认点。
        atr_value : Decimal 或 None
            该周期的当前 ATR；预热未完成时无法计算聚类阈值，直接忽略该点。

        返回
        ----
        tuple of Zone
            被本次锚点影响的 Zone（新建或被追加锚点者）。
        """
        if point.instrument_id != self._instrument_id:
            raise ValueError(
                f"swing point instrument {point.instrument_id} does not match "
                f"{self._instrument_id}",
            )
        if point.timeframe is not self._timeframe:
            raise ValueError(
                f"swing point timeframe {point.timeframe} does not match {self._timeframe}",
            )
        if atr_value is None or atr_value <= 0:
            return ()

        zone_type = (
            ZoneType.RESISTANCE if point.direction is SwingDirection.HIGH else ZoneType.SUPPORT
        )
        anchor = ZoneAnchor(
            swing_id=point.point_id,
            price=point.price,
            occurred_at_ns=point.occurred_at_ns,
            confirmed_at_ns=point.confirmed_at_ns,
            sequence=point.sequence,
        )

        target = self._select_cluster(zone_type, anchor.price, atr_value)
        if target is None:
            return (self._create_zone(zone_type, anchor, atr_value, point.confirmed_at_ns),)

        self._add_anchor(target, anchor, atr_value, point.confirmed_at_ns)
        return (target,)

    def _select_cluster(
        self,
        zone_type: ZoneType,
        price: Decimal,
        atr_value: Decimal,
    ) -> Zone | None:
        merge_limit = self._params.merge_distance_atr * atr_value
        width_limit = self._params.max_cluster_width_atr * atr_value

        candidates: list[tuple[Decimal, int, str, Zone]] = []
        for zone in self._zones.values():
            if zone.zone_type is not zone_type or not zone.is_open:
                continue
            distance = abs(price - zone.center)
            if distance > merge_limit:
                continue
            prices = [item.price for item in zone.anchors] + [price]
            if max(prices) - min(prices) > width_limit:
                continue
            candidates.append((distance, zone.created_at_ns, zone.zone_id, zone))

        if not candidates:
            return None
        # 距离最小 → 创建最早 → zone_id 字典序最小（第 6.3 节）。
        candidates.sort(key=lambda item: (item[0], item[1], item[2]))
        return candidates[0][3]

    def _create_zone(
        self,
        zone_type: ZoneType,
        anchor: ZoneAnchor,
        atr_value: Decimal,
        now_ns: int,
    ) -> Zone:
        self._sequence += 1
        zone_id = f"Z-{self._instrument_id}-{self._timeframe.value}-{self._sequence:04d}"
        geometry = compute_zone_geometry(
            [anchor.price],
            atr=atr_value,
            tick_size=self._tick_size,
            params=self._params,
        )
        zone = Zone(
            zone_id=zone_id,
            instrument_id=self._instrument_id,
            timeframe=self._timeframe,
            zone_type=zone_type,
            status=ZoneStatus.CREATED,
            version=1,
            anchors=(anchor,),
            geometry=geometry,
            created_at_ns=now_ns,
            updated_at_ns=now_ns,
            events=[ZoneEventType.CREATED.value],
        )
        self._zones[zone_id] = zone
        self._try_activate(zone, now_ns)
        return zone

    def _add_anchor(
        self,
        zone: Zone,
        anchor: ZoneAnchor,
        atr_value: Decimal,
        now_ns: int,
    ) -> None:
        anchors = (*zone.anchors, anchor)
        geometry = compute_zone_geometry(
            [item.price for item in anchors],
            atr=atr_value,
            tick_size=self._tick_size,
            params=self._params,
        )
        zone.anchors = anchors
        self._apply_geometry(zone, geometry, now_ns)
        zone.events.append(ZoneEventType.ANCHOR_ADDED.value)
        self._try_activate(zone, now_ns)

    def _apply_geometry(
        self,
        zone: Zone,
        geometry: ZoneGeometry,
        now_ns: int,
    ) -> None:
        """仅在几何真正变化时递增版本（第 6.9 节）。"""
        if geometry != zone.geometry:
            zone.geometry = geometry
            zone.version += 1
            zone.updated_at_ns = now_ns

    def _try_activate(self, zone: Zone, now_ns: int) -> None:
        """锚点数量达到 ``min_anchor_count`` 时 CREATED → ACTIVE（第 6.5 节）。"""
        if zone.status is not ZoneStatus.CREATED:
            return
        if zone.anchor_count < self._params.min_anchor_count:
            return
        self._set_status(zone, ZoneStatus.ACTIVE, now_ns)
        zone.events.append(ZoneEventType.ACTIVATED.value)

    # ------------------------------------------------------------------ 逐 Bar

    def on_bar(
        self,
        bar: Bar,
        atr_value: Decimal | None,
    ) -> tuple[ZoneEvent, ...]:
        """用一根完成 Bar 推进 Zone 状态机。

        处置顺序为：锚点过期 → 突破 → 测试。同一 Bar 同时满足测试与突破时，
        突破优先（第 6.2 节）。

        参数
        ----
        bar : Bar
            属于本引擎周期的完成 Bar。
        atr_value : Decimal 或 None
            当前 ATR；为 ``None`` 时只做锚点年龄判定，状态机不推进。

        返回
        ----
        tuple of ZoneEvent
            本次产生的全部事件。
        """
        if bar.timeframe is not self._timeframe:
            raise ValueError(f"bar timeframe {bar.timeframe} does not match {self._timeframe}")

        if atr_value is None or atr_value <= 0:
            # ATR 预热未完成时无法重算几何，因此既不做过期移除也不推进状态机。
            return ()

        events: list[ZoneEvent] = []
        events.extend(self._expire_anchors(bar.ts_close_ns, atr_value))

        for zone in self._zones.values():
            # 规格第 6.2 节：只有 ACTIVE / TESTED 能因测试或突破改变状态；
            # CREATED 只能因锚点过期或结构失效进入 INVALIDATED。
            if zone.status not in {ZoneStatus.ACTIVE, ZoneStatus.TESTED}:
                continue
            if self._is_broken(zone, bar, atr_value):
                self._set_status(zone, ZoneStatus.BROKEN, bar.ts_close_ns)
                zone.broken_at_ns = bar.ts_close_ns
                zone.events.append(ZoneEventType.BROKEN.value)
                events.append(self._event(ZoneEventType.BROKEN, zone, bar.ts_close_ns))
                continue
            if self._is_tested(zone, bar, atr_value):
                zone.test_count += 1
                if zone.status is not ZoneStatus.TESTED:
                    self._set_status(zone, ZoneStatus.TESTED, bar.ts_close_ns)
                zone.events.append(ZoneEventType.TESTED.value)
                events.append(self._event(ZoneEventType.TESTED, zone, bar.ts_close_ns))

        return tuple(events)

    def _expire_anchors(self, now_ns: int, atr_value: Decimal) -> list[ZoneEvent]:
        """移除超龄锚点；剩余锚点不足时进入 INVALIDATED（第 6.8 节）。"""
        events: list[ZoneEvent] = []
        max_age_ns = self._params.max_age_ns

        for zone in self._zones.values():
            if not zone.is_open:
                continue
            kept = tuple(
                anchor for anchor in zone.anchors if now_ns - anchor.confirmed_at_ns <= max_age_ns
            )
            if len(kept) == len(zone.anchors):
                continue

            dropped = len(zone.anchors) - len(kept)
            zone.anchors = kept
            zone.version += 1
            zone.updated_at_ns = now_ns
            zone.events.append(ZoneEventType.ANCHOR_EXPIRED.value)
            if kept:
                # 锚点集合变化必须重算几何并递增版本（第 6.9 节）。
                self._apply_geometry(
                    zone,
                    compute_zone_geometry(
                        [item.price for item in kept],
                        atr=atr_value,
                        tick_size=self._tick_size,
                        params=self._params,
                    ),
                    now_ns,
                )
            events.append(
                ZoneEvent(
                    event_type=ZoneEventType.ANCHOR_EXPIRED,
                    zone_id=zone.zone_id,
                    zone_version=zone.version,
                    timeframe=self._timeframe,
                    at_ns=now_ns,
                    detail={"dropped_anchors": str(dropped)},
                ),
            )
            if len(zone.anchors) < self._params.min_anchor_count:
                self._set_status(zone, ZoneStatus.INVALIDATED, now_ns)
                zone.invalidated_at_ns = now_ns
                zone.invalidation_reason = "ANCHOR_AGE"
                zone.events.append(ZoneEventType.INVALIDATED.value)
                events.append(
                    self._event(ZoneEventType.INVALIDATED, zone, now_ns),
                )
        return events

    def _is_tested(self, zone: Zone, bar: Bar, atr_value: Decimal) -> bool:
        tolerance = self._params.test_tolerance_atr * atr_value
        lower_edge = zone.lower - tolerance
        upper_edge = zone.upper + tolerance

        if zone.zone_type is ZoneType.SUPPORT:
            return (
                bar.low >= lower_edge
                and bar.low <= upper_edge
                and bar.close >= lower_edge
                and bar.close > zone.center
            )
        return (
            bar.high >= lower_edge
            and bar.high <= upper_edge
            and bar.close <= upper_edge
            and bar.close < zone.center
        )

    def _is_broken(self, zone: Zone, bar: Bar, atr_value: Decimal) -> bool:
        buffer = self._params.break_buffer_atr * atr_value
        if zone.zone_type is ZoneType.SUPPORT:
            return bar.close < zone.lower - buffer
        return bar.close > zone.upper + buffer

    def _set_status(self, zone: Zone, status: ZoneStatus, now_ns: int) -> None:
        if zone.status is status:
            return
        zone.status = status
        zone.version += 1
        zone.updated_at_ns = now_ns

    def _event(self, kind: ZoneEventType, zone: Zone, at_ns: int) -> ZoneEvent:
        return ZoneEvent(
            event_type=kind,
            zone_id=zone.zone_id,
            zone_version=zone.version,
            timeframe=self._timeframe,
            at_ns=at_ns,
            detail={
                "zone_type": zone.zone_type.value,
                "status": zone.status.value,
                "center": str(zone.center),
                "lower": str(zone.lower),
                "upper": str(zone.upper),
                "anchor_count": str(zone.anchor_count),
            },
        )
