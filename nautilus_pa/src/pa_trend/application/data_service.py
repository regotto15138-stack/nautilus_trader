"""图表与标注页面的数据服务（规格 V1.4.8 / SACW V1.1.2）。

把「读取 Parquet / 合成数据 → 送入七周期引擎 → 缓存」的过程集中到一处，
供 HTTP 接口层复用：

- ``payload()``：整页看板载荷（各周期蜡烛、指标、ZigZag、结构与 Zone）；
- ``bars()`` / ``updates()``：按周期取出完整序列，用于 K 线查询与标注定位；
- ``coverage()``：每周期起止时间、Bar 数、缺失、重复与完整性状态；
- ``zone_preview()``：SACW 21.2 的 ANCHOR_ONLY 后端几何计算；
- ``dataset_info()``：数据版本与哈希，写入标注与回放记录；
- ``refresh()``：检测采集器新落盘的 K 线并增量重建，供实时视图轮询。
"""

from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from nautilus_trader.persistence import ParquetDataCatalog

from pa_trend.adapters.nautilus.bar_converter import to_domain_bar
from pa_trend.application.data_quality import IssueKind, validate_bar_series
from pa_trend.application.demo_data import DEFAULT_SEED, generate_demo_bars
from pa_trend.application.market_context import MarketContext, MarketSnapshot
from pa_trend.application.timeframe_engine import ATR_MA_STATUS, TimeframeUpdate
from pa_trend.config.fingerprint import config_hash, config_snapshot
from pa_trend.config.loader import load_config
from pa_trend.config.models import PaTrendConfig
from pa_trend.domain.errors import BarAlignmentError
from pa_trend.domain.models.bar import Bar
from pa_trend.domain.models.swing import SwingPoint
from pa_trend.domain.models.timeframe import ALL_TIMEFRAMES, Timeframe
from pa_trend.domain.structure.zone import (
    Zone,
    ZoneParams,
    compute_zone_geometry,
)
from pa_trend.presentation.chart_data import build_payload, build_timeframe_section

#: 每个周期在整页载荷里最多下发多少根 K 线（首屏窗口）。
#:
#: 更早的历史由前端向左滚动时按需调用 ``GET /market/bars`` 分页追加。取值按
#: 载荷实测：每周期 5000 根时整页约 21 MB，1200 根时约 6 MB，浏览器打开明显
#: 更快；需要更长视野时滚动即可继续加载。
MAX_SERIES_BARS = 1200

#: 合成数据的默认根数。
DEFAULT_DEMO_BARS = 400

#: 实时视图：一次增量更新最多包含多少根新 K 线（超出时前端改为整页重载）。
MAX_LIVE_BARS = 500

#: 实时视图的刷新间隔（秒）。
LIVE_REFRESH_INTERVAL_SECS = 5.0


@dataclass(frozen=True, slots=True)
class TimeframeData:
    """单个周期的原始数据与回放结果。"""

    timeframe: Timeframe
    bars: tuple[Bar, ...]
    updates: tuple[TimeframeUpdate, ...]
    skipped: int


@dataclass(frozen=True, slots=True)
class DatasetInfo:
    """数据集版本信息（SACW 5.1 ``market_datasets``）。"""

    dataset_id: str
    instrument_id: str
    source: str
    range_start_ns: int | None
    range_end_ns: int | None
    data_hash: str
    timeframes: tuple[str, ...]


def _hash_bars(bars: dict[Timeframe, tuple[Bar, ...]]) -> str:
    digest = hashlib.sha256()
    for timeframe in ALL_TIMEFRAMES:
        digest.update(timeframe.value.encode("utf-8"))
        for bar in bars.get(timeframe, ()):
            digest.update(
                (
                    f"{bar.ts_open_ns}:{bar.open}:{bar.high}:{bar.low}:{bar.close}:{bar.volume}"
                ).encode(),
            )
    return digest.hexdigest()


class DataService:
    """多周期数据与识别的内存视图（线程安全，构建一次后只读）。"""

    def __init__(
        self,
        *,
        instrument_id: str,
        configs_dir: Path,
        catalog_path: Path | None,
        demo: bool,
        demo_bars: int = DEFAULT_DEMO_BARS,
        session_offset_hours: int | None = None,
    ) -> None:
        """初始化数据服务。"""
        self.instrument_id = instrument_id
        self._config = load_config(configs_dir)
        self._catalog_path = catalog_path
        self._demo = demo
        self._demo_bars = demo_bars
        if session_offset_hours is not None:
            self._session_offset_hours = session_offset_hours
        elif demo:
            self._session_offset_hours = 0
        else:
            self._session_offset_hours = self._config.research.session_offset_hours

        self._lock = threading.Lock()
        self._built = False
        self._data: dict[Timeframe, TimeframeData] = {}
        self._context: MarketContext | None = None
        self._snapshot: MarketSnapshot | None = None
        self._payload: dict[str, Any] | None = None
        self._dataset: DatasetInfo | None = None
        self._coverage: list[dict[str, Any]] = []
        self._built_monotonic = 0.0
        self._build_count = 0
        self._last_refresh_monotonic: float | None = None
        self._last_refresh_change_count = 0

    # ------------------------------------------------------------------ 元信息

    @property
    def config(self) -> PaTrendConfig:
        """返回冻结配置。"""
        return self._config

    @property
    def config_hash(self) -> str:
        """返回配置指纹。"""
        return config_hash(config_snapshot(self._config))

    @property
    def session_offset_hours(self) -> int:
        """返回交易所会话偏移小时数。"""
        return self._session_offset_hours

    @property
    def source(self) -> str:
        """返回数据来源标识。"""
        return "demo" if self._demo else "catalog"

    @property
    def demo(self) -> bool:
        """是否为合成数据。"""
        return self._demo

    # ------------------------------------------------------------------ 构建

    def ensure_built(self) -> None:
        """确保数据已载入并完成回放（幂等）。"""
        with self._lock:
            if self._built:
                return
            self._build()
            self._built = True
            self._built_monotonic = time.monotonic()
            self._build_count += 1

    def invalidate(self) -> None:
        """丢弃缓存，下次访问时重建。"""
        with self._lock:
            self._reset()

    def _reset(self) -> None:
        """清空内存视图（需持有锁）。"""
        self._built = False
        self._data = {}
        self._context = None
        self._snapshot = None
        self._payload = None
        self._dataset = None
        self._coverage = []

    # ------------------------------------------------------------------ 实时

    def refresh(self) -> dict[str, Any]:
        """检测采集器新落盘的 K 线，并在有变化时重建内存视图。

        采集器与工作台是两个独立进程：采集器把已收盘的 K 线写入 Parquet，
        工作台此前只在启动时构建一次。这里对比 Parquet 与内存视图的最新 K 线，
        发现新数据就丢弃缓存并按全部历史重建（引擎是有状态的，必须从同一份
        历史重新回放），供前端轮询。

        返回
        ----
        dict
            刷新结果：是否变化、新增根数、按周期统计、耗时与视图信息。
        """
        started = time.monotonic()
        with self._lock:
            changes = self._detect_changes()
            added = sum(changes.values())
            if added:
                self._reset()
            if not self._built:
                self._build()
                self._built = True
                self._built_monotonic = time.monotonic()
                self._build_count += 1
            self._last_refresh_monotonic = time.monotonic()
            self._last_refresh_change_count = added

            refresh_millis = (self._last_refresh_monotonic - started) * 1000
            build_millis = refresh_millis if added else 0.0
            return {
                "changed": bool(added),
                "addedBars": added,
                "changesByTimeframe": {
                    timeframe.value: count for timeframe, count in changes.items() if count
                },
                "maxSeriesBars": MAX_SERIES_BARS,
                "maxLiveBars": MAX_LIVE_BARS,
                "refreshIntervalSecs": LIVE_REFRESH_INTERVAL_SECS,
                "buildCount": self._build_count,
                "buildMillis": round(build_millis, 1),
                "refreshMillis": round(refresh_millis, 1),
                "lastRefreshChangeCount": self._last_refresh_change_count,
                "lastBarAtNs": self._newest_bar_ns(),
                "generatedAtNs": time.time_ns(),
            }

    def _detect_changes(self) -> dict[Timeframe, int]:
        """返回每个周期相对内存视图的新增 K 线根数（需持有锁）。"""
        changes: dict[Timeframe, int] = {}
        if not self._built or not self._data:
            return changes
        for timeframe, item in self._data.items():
            bars = self._read_catalog_bars(timeframe)
            latest = _latest_close_ns(item.bars)
            added = sum(1 for bar in bars if latest is None or bar.ts_close_ns > latest)
            if added:
                changes[timeframe] = added
        return changes

    def _newest_bar_ns(self) -> int | None:
        if not self._data:
            return None
        closes = [item.bars[-1].ts_close_ns for item in self._data.values() if item.bars]
        return max(closes) if closes else None

    def bars_since(self, timeframe: Timeframe, *, since_close_ns: int | None) -> list[Bar]:
        """返回 ``timeframe`` 上收盘时刻晚于 ``since_close_ns`` 的 K 线。

        ``since_close_ns`` 为 ``None`` 时返回当前视图内该周期的全部 K 线；
        最多返回 :data:`MAX_LIVE_BARS` 根，超出时由调用方改为整页重载。
        """
        bars = self.bars(timeframe)
        if since_close_ns is not None:
            bars = tuple(bar for bar in bars if bar.ts_close_ns > since_close_ns)
        return list(bars[-MAX_LIVE_BARS:])

    def timeframe_section_view(self, timeframe: Timeframe) -> dict[str, Any]:
        """返回某周期最新叠加层（与整页载荷同构，供前端在增量刷新时替换）。

        最新 K 线可能新增或改变摆动点、N 结构、Zone 与状态，因此叠加层整体
        重算；K 线本身由调用方以增量下发。
        """
        self.ensure_built()
        engine = self.context.engine(timeframe)
        assert self._snapshot is not None
        return build_timeframe_section(
            updates=list(self.updates(timeframe)[-MAX_SERIES_BARS:]),
            structures=engine.structures.structures,
            zones=engine.zones.zones,
            view=self._snapshot.per_timeframe[timeframe],
        )

    def _load_bars(self, timeframe: Timeframe) -> tuple[list[Bar], int]:
        if self._demo:
            return (
                generate_demo_bars(
                    instrument_id=self.instrument_id,
                    timeframe=timeframe,
                    count=self._demo_bars,
                    seed=DEFAULT_SEED + timeframe.rank * 1000,
                ),
                0,
            )

        if self._catalog_path is None:
            raise RuntimeError("catalog path is required when demo mode is off")

        catalog = ParquetDataCatalog(str(self._catalog_path))
        key = self._bar_key(timeframe)
        raw_bars = sorted(catalog.query_bars(identifiers=[key]), key=lambda bar: bar.ts_event)

        offset_minutes = self._session_offset_hours * 60
        bars: list[Bar] = []
        skipped = 0
        for nautilus_bar in raw_bars:
            converted = self._to_domain(nautilus_bar, timeframe, offset_minutes)
            if converted is None:
                skipped += 1
            else:
                bars.append(converted)
        return bars, skipped

    def _read_catalog_bars(self, timeframe: Timeframe) -> list[Bar]:
        """按周期读取 Parquet 中已收盘的 K 线（跳过未对齐的 K 线）。"""
        if self._catalog_path is None:
            return []
        catalog = ParquetDataCatalog(str(self._catalog_path))
        key = self._bar_key(timeframe)
        raw_bars = sorted(catalog.query_bars(identifiers=[key]), key=lambda bar: bar.ts_event)
        offset_minutes = self._session_offset_hours * 60
        bars: list[Bar] = []
        for nautilus_bar in raw_bars:
            converted = self._to_domain(nautilus_bar, timeframe, offset_minutes)
            if converted is not None:
                bars.append(converted)
        return bars

    def _to_domain(
        self,
        nautilus_bar: object,
        timeframe: Timeframe,
        offset_minutes: int,
    ) -> Bar | None:
        try:
            return to_domain_bar(
                nautilus_bar,
                timeframe,
                instrument_id=self.instrument_id,
                session_offset_minutes=offset_minutes,
            )
        except BarAlignmentError:
            return None

    def _bar_key(self, timeframe: Timeframe) -> str:
        return f"{self.instrument_id}-{timeframe.bar_spec}-LAST-EXTERNAL"

    def _build(self) -> None:
        context = MarketContext(self._config)
        data: dict[Timeframe, TimeframeData] = {}
        coverage: list[dict[str, Any]] = []

        for timeframe in ALL_TIMEFRAMES:
            bars, skipped = self._load_bars(timeframe)
            updates: list[TimeframeUpdate] = []
            for bar in bars:
                updates.append(context.on_bar(bar))

            report = validate_bar_series(bars, timeframe)
            data[timeframe] = TimeframeData(
                timeframe=timeframe,
                bars=tuple(bars),
                updates=tuple(updates),
                skipped=skipped,
            )
            coverage.append(
                {
                    "timeframe": timeframe.value,
                    "label": timeframe.label,
                    "bars": len(bars),
                    "skipped": skipped,
                    "start": None if not bars else _iso(bars[0].ts_open_ns),
                    "end": None if not bars else _iso(bars[-1].ts_close_ns),
                    "startNs": None if not bars else bars[0].ts_open_ns,
                    "endNs": None if not bars else bars[-1].ts_close_ns,
                    "gaps": report.count(IssueKind.GAP),
                    "duplicates": report.count(IssueKind.DUPLICATE),
                    "outOfOrder": report.count(IssueKind.OUT_OF_ORDER),
                    "clean": report.is_clean,
                    "summary": report.summary(),
                },
            )

        snapshot = context.snapshot()
        sections = {
            timeframe: build_timeframe_section(
                updates=list(data[timeframe].updates[-MAX_SERIES_BARS:]),
                structures=context.engine(timeframe).structures.structures,
                zones=context.engine(timeframe).zones.zones,
                view=snapshot.per_timeframe[timeframe],
            )
            for timeframe in ALL_TIMEFRAMES
        }
        bars_hash = _hash_bars({tf: item.bars for tf, item in data.items()})
        dataset_id = f"ds-{bars_hash[:16]}"

        payload = build_payload(
            instrument_id=self.instrument_id,
            source=self.source,
            session_offset_hours=self._session_offset_hours,
            snapshot=snapshot,
            sections=sections,
            config_hash=self.config_hash,
            dataset_id=dataset_id,
        )
        payload["coverage"] = coverage
        payload["skippedBars"] = sum(item.skipped for item in data.values())
        payload["maxSeriesBars"] = MAX_SERIES_BARS
        payload["atrMaStatus"] = ATR_MA_STATUS

        all_bars = [bar for item in data.values() for bar in item.bars]
        self._dataset = DatasetInfo(
            dataset_id=dataset_id,
            instrument_id=self.instrument_id,
            source=self.source,
            range_start_ns=None if not all_bars else min(b.ts_open_ns for b in all_bars),
            range_end_ns=None if not all_bars else max(b.ts_close_ns for b in all_bars),
            data_hash=bars_hash,
            timeframes=tuple(tf.value for tf in ALL_TIMEFRAMES),
        )
        self._data = data
        self._context = context
        self._snapshot = snapshot
        self._payload = payload
        self._coverage = coverage

    # ------------------------------------------------------------------ 读取

    @property
    def context(self) -> MarketContext:
        """返回回放后的多周期上下文。"""
        self.ensure_built()
        assert self._context is not None
        return self._context

    def payload(self) -> dict[str, Any]:
        """返回看板载荷。"""
        self.ensure_built()
        assert self._payload is not None
        return self._payload

    def dataset_info(self) -> DatasetInfo:
        """返回数据集版本信息。"""
        self.ensure_built()
        assert self._dataset is not None
        return self._dataset

    def coverage(self) -> list[dict[str, Any]]:
        """返回多周期数据覆盖情况。"""
        self.ensure_built()
        return list(self._coverage)

    def bars(self, timeframe: Timeframe) -> tuple[Bar, ...]:
        """返回某周期的全部完成 Bar。"""
        self.ensure_built()
        return self._data[timeframe].bars

    def updates(self, timeframe: Timeframe) -> tuple[TimeframeUpdate, ...]:
        """返回某周期的逐 Bar 识别结果。"""
        self.ensure_built()
        return self._data[timeframe].updates

    def swings(self, timeframe: Timeframe) -> tuple[SwingPoint, ...]:
        """返回某周期的已确认 SwingPoint。"""
        return tuple(self.context.engine(timeframe).swings)

    def zones(self, timeframe: Timeframe) -> tuple[Zone, ...]:
        """返回某周期的全部 Zone。"""
        return self.context.engine(timeframe).zones.zones

    def find_swing(self, timeframe: Timeframe, swing_id: str) -> SwingPoint | None:
        """按 ID 查找已确认 SwingPoint。"""
        for point in self.swings(timeframe):
            if point.point_id == swing_id:
                return point
        return None

    # -------------------------------------------------------- ANCHOR_ONLY 计算

    def zone_preview(
        self,
        *,
        timeframe: Timeframe,
        anchor_swing_ids: list[str],
    ) -> dict[str, Any]:
        """按 SACW 21.2 由后端计算 ANCHOR_ONLY Zone 几何。

        前端只提交锚点，不得自行重写公式；这里使用与策略引擎完全相同的
        ``compute_zone_geometry``、同一 Config Snapshot 与同一 ATR 快照。
        """
        if len(set(anchor_swing_ids)) < 2:
            raise ValueError("ANCHOR_ONLY requires at least two distinct anchor swing ids")

        points: list[SwingPoint] = []
        missing: list[str] = []
        for swing_id in anchor_swing_ids:
            point = self.find_swing(timeframe, swing_id)
            if point is None:
                missing.append(swing_id)
            else:
                points.append(point)
        if missing:
            raise ValueError(f"unknown swing ids for {timeframe.value}: {missing}")

        expected = {point.is_high for point in points}
        if len(expected) != 1:
            raise ValueError("anchors must all be swing highs or all be swing lows")

        engine = self.context.engine(timeframe)
        atr = engine.atr.value
        if atr is None or atr <= 0:
            raise ValueError(f"{timeframe.value} ATR is not ready; cannot compute Zone geometry")

        zone_type = "RESISTANCE" if points[0].is_high else "SUPPORT"
        params = engine.zones.params
        geometry = compute_zone_geometry(
            [point.price for point in points],
            atr=atr,
            tick_size=self._config.tick_size,
            params=params,
        )
        return {
            "timeframe": timeframe.value,
            "zoneType": zone_type,
            "anchorSwingIds": list(anchor_swing_ids),
            "anchors": [
                {
                    "swingId": point.point_id,
                    "price": str(point.price),
                    "occurredAt": _iso(point.occurred_at_ns),
                    "confirmedAt": _iso(point.confirmed_at_ns),
                }
                for point in points
            ],
            "center": str(geometry.center),
            "halfWidth": str(geometry.half_width),
            "lower": str(geometry.lower),
            "upper": str(geometry.upper),
            "halfWidthBasis": geometry.basis.value,
            "atrTerm": str(geometry.atr_term),
            "tickTerm": str(geometry.tick_term),
            "spanTerm": str(geometry.span_term),
            "atrSnapshot": str(atr),
            "tickSize": str(self._config.tick_size),
            "tickSizeVersion": self._config.market.metadata.version,
            "zoneParameters": zone_params_snapshot(params),
            "formulaVersion": "V1.4.8-6.4",
            "configHash": self.config_hash,
        }

    def indicator_series(
        self,
        *,
        timeframe: Timeframe,
        fields: list[str],
    ) -> dict[str, Any]:
        """返回指标序列（SACW 17.5）。

        只允许 ``sma22`` / ``atr14``；``atr_ma22`` 一律返回
        ``N/A / SPEC_AMBIGUITY``，不参与计算。
        """
        updates = self.updates(timeframe)
        field_map = {"sma22": "sma", "atr14": "atr"}
        unknown = [name for name in fields if name not in field_map and name != "atr_ma22"]
        if unknown:
            raise ValueError(f"unknown indicator fields: {unknown}")

        series: dict[str, Any] = {}
        for name in fields:
            if name == "atr_ma22":
                series[name] = {"status": ATR_MA_STATUS, "points": []}
                continue
            attribute = field_map[name]
            points: list[dict[str, Any]] = []
            for update in updates:
                value: Decimal | None = getattr(update, attribute)
                if value is None:
                    continue
                points.append(
                    {
                        "time": update.bar.ts_open_ns // 1_000_000_000,
                        "value": float(value),
                        "asOfBarTime": update.bar.ts_close_ns // 1_000_000_000,
                        "sourceBarId": update.bar.bar_id,
                        "isClosed": True,
                        "runId": None,
                        "configHash": self.config_hash,
                    },
                )
            series[name] = {"status": "READY" if points else "N/A", "points": points}
        return {
            "timeframe": timeframe.value,
            "fields": fields,
            "series": series,
            "configHash": self.config_hash,
            "datasetHash": self.dataset_info().data_hash,
        }

    def zone_program_snapshots(self, timeframe: Timeframe) -> list[dict[str, Any]]:
        """导出程序 Zone 快照，供差异比较使用（SACW 7.4）。"""
        out: list[dict[str, Any]] = []
        for zone in self.zones(timeframe):
            out.append(
                {
                    "zone_id": zone.zone_id,
                    "zone_type": zone.zone_type.value,
                    "status": zone.status.value,
                    "anchor_swing_ids": [anchor.swing_id for anchor in zone.anchors],
                    "center": str(zone.center),
                    "lower": str(zone.lower),
                    "upper": str(zone.upper),
                    "version": zone.version,
                },
            )
        return out


def _latest_close_ns(bars: tuple[Bar, ...]) -> int | None:
    return bars[-1].ts_close_ns if bars else None


def _iso(ts_ns: int) -> str:
    from pa_trend.domain.models.timeframe import ns_to_dt

    return ns_to_dt(ts_ns).isoformat().replace("+00:00", "Z")


def zone_params_snapshot(params: ZoneParams) -> dict[str, str]:
    """返回 Zone 参数的实际生效值。"""
    return {
        "merge_distance_atr": str(params.merge_distance_atr),
        "max_cluster_width_atr": str(params.max_cluster_width_atr),
        "half_width_atr": str(params.half_width_atr),
        "min_half_width_ticks": str(params.min_half_width_ticks),
        "test_tolerance_atr": str(params.test_tolerance_atr),
        "break_buffer_atr": str(params.break_buffer_atr),
        "max_age_weeks": str(params.max_age_weeks),
        "min_anchor_count": str(params.min_anchor_count),
    }


__all__ = [
    "DEFAULT_DEMO_BARS",
    "LIVE_REFRESH_INTERVAL_SECS",
    "MAX_LIVE_BARS",
    "MAX_SERIES_BARS",
    "DataService",
    "DatasetInfo",
    "TimeframeData",
    "zone_params_snapshot",
]
