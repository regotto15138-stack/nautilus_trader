"""初始状态快照（SACW 21.2、21.3、24）。

快照把某一时刻的指标、ZigZag、SwingPoint、N 结构与 Zone 固化成可比较的
JSON，并给出可信度状态。本阶段包含底层结构与已实现的 1M/1W/1D/4H/1H 状态机；
持仓与订单仍留空，等 P2 阶段再补。

可信度规则（SACW 21.2、PB-47）：

- 任一启用周期的 ATR / SMA 未就绪 → ``INSUFFICIENT_HISTORY``；
- 任一 Zone 快照缺少锚点的 ``confirmed_at`` → ``INSUFFICIENT_HISTORY``；
- ATR 非有限数或小于等于 0 → ``INVALID_ATR``；
- 其余情况为 ``READY``。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pa_trend.application.market_context import MarketContext
from pa_trend.config.fingerprint import config_hash, config_snapshot
from pa_trend.config.models import PaTrendConfig
from pa_trend.domain.models.bar import Bar
from pa_trend.domain.models.timeframe import Timeframe
from pa_trend.domain.structure.zone import Zone


class SnapshotStatus(StrEnum):
    """快照可信度状态。"""

    READY = "READY"
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
    INVALID_ATR = "INVALID_ATR"


@dataclass(frozen=True, slots=True)
class SnapshotResult:
    """快照构建结果。"""

    status: SnapshotStatus
    as_of_ns: int | None
    payload: dict[str, Any]
    missing: tuple[str, ...]

    @property
    def snapshot_hash(self) -> str:
        """返回快照内容的稳定 SHA-256。"""
        canonical = json.dumps(
            self.payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def zone_is_trustworthy(zone: Zone) -> bool:
    """判读 Zone 快照是否可信（PB-47）。

    只保存边界、中心与锚点数量而丢失锚点 ``confirmed_at`` 的 Zone 快照
    无法验证年龄与失效原因，必须标记为不可信。
    """
    if not zone.anchors:
        return False
    return all(anchor.confirmed_at_ns > 0 for anchor in zone.anchors)


def _decimal_text(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _valid_atr(value: Decimal | None) -> bool:
    return value is not None and value.is_finite() and value > 0


def _state_machines(context: MarketContext) -> dict[str, Any]:
    """把已实现的周期状态机写入快照（SACW 21.3）。

    15M/3M 没有独立趋势状态机，``state`` 为 ``None`` 时保持 null，不伪造状态。
    """
    market = context.snapshot()
    states = {
        timeframe.value: market.per_timeframe[timeframe].state
        for timeframe in Timeframe
    }
    return {
        "states": states,
        "macro": {
            "1M": market.month.value,
            "1W": market.week.value,
            "1D": market.day.value,
            "4H": market.h4.value,
            "1H": market.h1.value,
        },
        "canOpen": market.can_open,
        "canHold": market.can_hold,
    }


def _zone_payload(zone: Zone) -> dict[str, Any]:
    return {
        "zone_id": zone.zone_id,
        "zone_type": zone.zone_type.value,
        "status": zone.status.value,
        "version": zone.version,
        "center": str(zone.center),
        "lower": str(zone.lower),
        "upper": str(zone.upper),
        "half_width": str(zone.half_width),
        "half_width_basis": zone.basis.value,
        "anchor_count": zone.anchor_count,
        "anchors": [
            {
                "swing_id": anchor.swing_id,
                "price": str(anchor.price),
                "occurred_at_ns": anchor.occurred_at_ns,
                "confirmed_at_ns": anchor.confirmed_at_ns,
            }
            for anchor in zone.anchors
        ],
    }


def build_snapshot(
    config: PaTrendConfig,
    *,
    context: MarketContext,
    timeframe: Timeframe,
    as_of_ns: int | None,
    dataset_id: str | None = None,
) -> SnapshotResult:
    """从已回放的多周期上下文构建初始状态快照。

    参数
    ----
    config : PaTrendConfig
        冻结配置。
    context : MarketContext
        已按时间顺序送入 K 线后的上下文。
    timeframe : Timeframe
        快照的目标周期。
    as_of_ns : int 或 None
        快照时点（纳秒）；``None`` 表示取最新一根完成 Bar。
    dataset_id : str 或 None
        数据版本标识。

    返回
    ----
    SnapshotResult
        快照状态、缺失项与载荷。
    """
    engine = context.engine(timeframe)
    missing: list[str] = []

    last_bar: Bar | None = engine.last_bar
    if as_of_ns is not None and last_bar is not None and last_bar.ts_close_ns < as_of_ns:
        missing.append(f"{timeframe.value}:NO_BAR_AT_AS_OF")
    resolved_as_of = as_of_ns
    if resolved_as_of is None and last_bar is not None:
        resolved_as_of = last_bar.ts_close_ns

    if not engine.is_warm:
        missing.append(f"{timeframe.value}:INSUFFICIENT_HISTORY")
    # ATR 缺失属于「历史不足」；只有显式存在但不合法的 ATR 才是 INVALID_ATR
    # （PB-40 针对的是已提供但非有限或 <= 0 的快照值）。
    if engine.atr.value is not None and not _valid_atr(engine.atr.value):
        missing.append(f"{timeframe.value}:INVALID_ATR")

    zones = engine.zones.zones
    for zone in zones:
        if not zone_is_trustworthy(zone):
            missing.append(f"{timeframe.value}:ZONE_ANCHORS_INCOMPLETE:{zone.zone_id}")

    candidate = engine.zigzag_candidate
    payload: dict[str, Any] = {
        "dataset_id": dataset_id,
        "timeframe": timeframe.value,
        "as_of_ns": resolved_as_of,
        "config_hash": config_hash(config_snapshot(config)),
        "market": {
            "instrument_id": config.instrument_id,
            "tick_size": str(config.market.metadata.tick_size),
            "tick_size_version": config.market.metadata.version,
        },
        "zone_parameters": config.zone.snapshot(),
        "indicators": {
            "atr14": _decimal_text(engine.atr.value),
            "sma22": _decimal_text(engine.sma.value),
            "atr_ma22": "N/A / SPEC_AMBIGUITY",
            "bar_count": engine.bar_count,
        },
        "zigzag": {
            "direction": engine.zigzag_direction,
            "candidate": None
            if candidate is None
            else {
                "candidate_id": candidate.candidate_id,
                "direction": candidate.direction.value,
                "price": str(candidate.price),
                "atr_snapshot": str(candidate.atr_snapshot),
                "occurred_at_ns": candidate.occurred_at_ns,
                "bar_id": candidate.bar_id,
                "reversal_threshold_price": str(candidate.reversal_threshold_price),
                "status": candidate.status,
            },
        },
        "swing_points": [
            {
                "swing_id": point.point_id,
                "direction": point.direction.value,
                "price": str(point.price),
                "occurred_at_ns": point.occurred_at_ns,
                "confirmed_at_ns": point.confirmed_at_ns,
                "atr_snapshot": str(point.atr_snapshot),
                "sequence": point.sequence,
            }
            for point in engine.swings
        ],
        "n_structures": [
            {
                "n_structure_id": structure.n_structure_id,
                "status": structure.status.value,
                "l1": structure.l1.point_id,
                "h1": structure.h1.point_id,
                "l2": structure.l2.point_id,
                "h2": structure.h2.point_id,
                "retracement": str(structure.retracement_ratio),
                "confirmed_at_ns": structure.confirmed_at_ns,
                "invalidation_status": engine.structures.invalidation_status,
                "invalidation_price": None,
            }
            for structure in engine.structures.structures
        ],
        "zones": [_zone_payload(zone) for zone in zones],
        "state_machines": _state_machines(context),
        "position": None,
        "orders": None,
        "notes": [
            "1M/1W/1D/4H/1H 状态机按当前已回放上下文写入（SACW 21.3）。",
            "ATR_MA22 为 SPEC_AMBIGUITY，不写入快照数值（SACW 17.1）。",
            "N 结构失效价在 ATR 时点裁定前保持 null（SACW 27.6）。",
            "持仓与订单在 P2 前保持 null，不伪造。",
        ],
    }

    if any(item.endswith("INVALID_ATR") for item in missing):
        status = SnapshotStatus.INVALID_ATR
    elif missing:
        status = SnapshotStatus.INSUFFICIENT_HISTORY
    else:
        status = SnapshotStatus.READY

    return SnapshotResult(
        status=status,
        as_of_ns=resolved_as_of,
        payload=payload,
        missing=tuple(missing),
    )


def replay_and_snapshot(
    config: PaTrendConfig,
    *,
    bars_by_timeframe: dict[Timeframe, Sequence[Bar]],
    timeframe: Timeframe,
    as_of_ns: int | None = None,
    dataset_id: str | None = None,
) -> SnapshotResult:
    """按时间顺序回放给定 K 线后构建快照。

    各周期的 Bar 按 ``ts_close_ns`` 合并排序，保证同一时间戳内「高周期完成
    在前、低周期执行在后」（规格第 3.3、3.4 节）。
    """
    context = MarketContext(config)
    merged: list[Bar] = []
    for bars in bars_by_timeframe.values():
        merged.extend(bars)
    merged.sort(key=lambda bar: (bar.ts_close_ns, -bar.timeframe.rank))

    for bar in merged:
        if as_of_ns is not None and bar.ts_close_ns > as_of_ns:
            break
        context.on_bar(bar)

    return build_snapshot(
        config,
        context=context,
        timeframe=timeframe,
        as_of_ns=as_of_ns,
        dataset_id=dataset_id,
    )
