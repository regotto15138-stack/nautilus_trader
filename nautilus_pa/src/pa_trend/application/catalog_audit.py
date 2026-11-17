"""审计采集目录相对于当前时钟的缺口与尾部滞后。

工作台与采集器是两个独立进程：采集器把已收盘的 K 线写入 Parquet，工作台只
读取。一旦采集器停过一段时间，目录里的最新 K 线就会落后于当前时刻，而工作台
本身无法从数据外观上区分「确实没有新 K 线」和「采集器已经停止」。

本模块按当前 UTC 时间计算每个周期的尾部欠根与中间缺口，供启动自检、命令行
工具和前端状态徽章共用。它只读，不写入、不请求网络。
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path

from nautilus_trader.persistence import ParquetDataCatalog

from pa_trend.adapters.nautilus.bar_converter import bar_window_ns
from pa_trend.config.loader import load_config
from pa_trend.domain.models.timeframe import Timeframe, floor_to_boundary

# 单个周期最多列出的缺口片段数，避免把长期停机的明细全部塞进响应。
MAX_LISTED_GAPS = 10


@dataclass(frozen=True)
class CatalogGap:
    """一段中间缺口：``[start, end)`` 之间应有的 K 线缺失。"""

    start_ns: int
    end_ns: int
    missing: int


@dataclass(frozen=True)
class TimeframeFreshness:
    """单个周期的新鲜度快照。"""

    timeframe: Timeframe
    count: int
    first_open_ns: int | None = None
    last_open_ns: int | None = None
    last_close_ns: int | None = None
    # 最后一根已存 K 线之后、到当前时刻为止已收盘但缺失的根数。
    tail_missing_closed: int = 0
    gaps: tuple[CatalogGap, ...] = field(default=())
    error: str | None = None

    @property
    def missing_in_gaps(self) -> int:
        """中间缺口里缺失的根数合计。"""
        return sum(gap.missing for gap in self.gaps)

    @property
    def behind(self) -> bool:
        """是否落后于当前时钟（尾部欠根或存在中间缺口）。"""
        return self.tail_missing_closed > 0 or self.missing_in_gaps > 0

    def as_dict(self, *, now_utc: dt.datetime) -> dict[str, object]:
        """转为可 JSON 序列化的摘要。"""
        return {
            "timeframe": self.timeframe.value,
            "count": self.count,
            "firstOpen": _iso(self.first_open_ns),
            "lastOpen": _iso(self.last_open_ns),
            "lastClose": _iso(self.last_close_ns),
            "tailMissingClosed": self.tail_missing_closed,
            "gapSegments": len(self.gaps),
            "missingInGaps": self.missing_in_gaps,
            "behind": self.behind,
            "nextDueOpen": floor_to_boundary(now_utc, self.timeframe).isoformat(),
            "gaps": [
                {
                    "start": _iso(gap.start_ns),
                    "end": _iso(gap.end_ns),
                    "missing": gap.missing,
                }
                for gap in self.gaps[:MAX_LISTED_GAPS]
            ],
            "error": self.error,
        }


def _iso(ns: int | None) -> str | None:
    if ns is None:
        return None
    return dt.datetime.fromtimestamp(ns / 1e9, tz=dt.UTC).isoformat()


def _ns(value: dt.datetime) -> int:
    return int(value.timestamp() * 1e9)


def count_missing_between(
    previous_open_ns: int,
    current_open_ns: int,
    timeframe: Timeframe,
    *,
    session_offset_minutes: int,
) -> int:
    """返回两根已存 K 线之间缺失的根数（按会话边界计算）。"""
    _, previous_close = bar_window_ns(
        previous_open_ns,
        timeframe,
        session_offset_minutes=session_offset_minutes,
    )
    if previous_close >= current_open_ns:
        return 0
    missing = 0
    cursor = previous_close
    while cursor < current_open_ns:
        missing += 1
        cursor = bar_window_ns(
            cursor,
            timeframe,
            session_offset_minutes=session_offset_minutes,
        )[1]
    return missing


def count_tail_missing(
    last_open_ns: int,
    *,
    timeframe: Timeframe,
    session_offset_minutes: int,
    now_utc: dt.datetime,
) -> int:
    """返回最后一根已存 K 线之后，到 ``now_utc`` 为止已收盘但缺失的根数。

    尚未收盘的蜡烛不计入：它本来就还不该出现在目录里。
    """
    now_ns = _ns(now_utc)
    _, last_close = bar_window_ns(
        last_open_ns,
        timeframe,
        session_offset_minutes=session_offset_minutes,
    )
    if last_close > now_ns:
        return 0
    missing = 0
    cursor = last_close
    while cursor < now_ns:
        _, close_ns = bar_window_ns(
            cursor,
            timeframe,
            session_offset_minutes=session_offset_minutes,
        )
        if close_ns > now_ns:
            break
        missing += 1
        cursor = close_ns
    return missing


def audit_timeframe(
    catalog: ParquetDataCatalog,
    bar_key: str,
    timeframe: Timeframe,
    *,
    session_offset_minutes: int,
    now_utc: dt.datetime,
) -> TimeframeFreshness:
    """审计单个周期。读取失败时把错误记进返回值，不向上抛。"""
    try:
        raw = sorted(catalog.query_bars(identifiers=[bar_key]), key=lambda bar: bar.ts_event)
    except Exception as exc:
        # 审计不应因单个周期读取失败而中断整张报告。
        return TimeframeFreshness(timeframe=timeframe, count=0, error=str(exc))

    if not raw:
        return TimeframeFreshness(timeframe=timeframe, count=0)

    ts = [int(bar.ts_event) for bar in raw]
    gaps: list[CatalogGap] = []
    for previous, current in pairwise(ts):
        missing = count_missing_between(
            previous,
            current,
            timeframe,
            session_offset_minutes=session_offset_minutes,
        )
        if not missing:
            continue
        _, previous_close = bar_window_ns(
            previous,
            timeframe,
            session_offset_minutes=session_offset_minutes,
        )
        gaps.append(
            CatalogGap(
                start_ns=previous_close,
                end_ns=current,
                missing=missing,
            ),
        )

    _, last_close = bar_window_ns(
        ts[-1],
        timeframe,
        session_offset_minutes=session_offset_minutes,
    )
    return TimeframeFreshness(
        timeframe=timeframe,
        count=len(ts),
        first_open_ns=ts[0],
        last_open_ns=ts[-1],
        last_close_ns=last_close,
        tail_missing_closed=count_tail_missing(
            ts[-1],
            timeframe=timeframe,
            session_offset_minutes=session_offset_minutes,
            now_utc=now_utc,
        ),
        gaps=tuple(gaps),
    )


def audit_catalog(
    *,
    catalog_dir: Path,
    configs_dir: Path,
    instrument_id: str,
    session_offset_hours: int,
    now_utc: dt.datetime | None = None,
) -> list[TimeframeFreshness]:
    """审计目录内全部周期，按配置中的周期顺序返回。"""
    now = now_utc if now_utc is not None else dt.datetime.now(dt.UTC)
    config = load_config(configs_dir)
    catalog = ParquetDataCatalog(str(catalog_dir))
    offset_minutes = session_offset_hours * 60
    return [
        audit_timeframe(
            catalog,
            f"{instrument_id}-{timeframe.bar_spec}-LAST-EXTERNAL",
            timeframe,
            session_offset_minutes=offset_minutes,
            now_utc=now,
        )
        for timeframe in config.timeframes.all()
    ]


def summarize(
    results: list[TimeframeFreshness],
    *,
    now_utc: dt.datetime | None = None,
) -> dict[str, object]:
    """把审计结果汇总成可直接下发给前端的结构。"""
    now = now_utc if now_utc is not None else dt.datetime.now(dt.UTC)
    behind = [item for item in results if item.behind or item.error]
    worst = max(
        (item.tail_missing_closed for item in results),
        default=0,
    )
    return {
        "nowUtc": now.isoformat(),
        "stale": bool(behind),
        "worstTailMissingClosed": worst,
        "staleTimeframes": [item.timeframe.value for item in behind],
        "timeframes": [item.as_dict(now_utc=now) for item in results],
    }


__all__ = [
    "MAX_LISTED_GAPS",
    "CatalogGap",
    "TimeframeFreshness",
    "audit_catalog",
    "audit_timeframe",
    "count_missing_between",
    "count_tail_missing",
    "summarize",
]
