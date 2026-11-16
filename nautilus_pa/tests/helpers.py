"""可导入的测试辅助函数（经 ``pythonpath = ["src", "tests"]`` 加入 sys.path）。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from pa_trend.domain.models.bar import Bar
from pa_trend.domain.models.swing import SwingDirection, SwingPoint
from pa_trend.domain.models.timeframe import (
    Timeframe,
    dt_to_ns,
    expected_close_ns,
    ns_to_dt,
)

INSTRUMENT_ID = "ETH-USDT-SWAP.OKX"

# 2024-01-01 是周一：同时是日、周、月的合法 UTC 边界。
ANCHOR = datetime(2024, 1, 1, tzinfo=UTC)


def dec(value: object) -> Decimal:
    """把标量转换为精确的 Decimal。"""
    return Decimal(str(value))


def make_bar(
    *,
    index: int = 0,
    timeframe: Timeframe = Timeframe.DAY,
    open_price: object = 100,
    high: object = 101,
    low: object = 99,
    close: object = 100,
    volume: object = 10,
    instrument_id: str = INSTRUMENT_ID,
) -> Bar:
    """构造一根对齐的 K 线，窗口起始于锚点之后的第 ``index`` 个周期。"""
    duration = timeframe.duration_ns
    if duration is not None:
        # 日内固定时长周期（4H/1H/15M/3M）按纳秒平移。
        start = ns_to_dt(dt_to_ns(ANCHOR) + index * duration)
    elif timeframe is Timeframe.DAY:
        start = ANCHOR + timedelta(days=index)
    elif timeframe is Timeframe.WEEK:
        start = ANCHOR + timedelta(weeks=index)
    elif timeframe is Timeframe.MONTH:
        months = index
        year = ANCHOR.year + months // 12
        month = 1 + months % 12
        start = ANCHOR.replace(year=year, month=month)
    else:  # pragma: no cover - guarded by the enum
        raise ValueError(f"unsupported timeframe: {timeframe}")

    ts_open = dt_to_ns(start)
    ts_close = expected_close_ns(ts_open, timeframe)

    return Bar(
        instrument_id=instrument_id,
        timeframe=timeframe,
        open=dec(open_price),
        high=dec(high),
        low=dec(low),
        close=dec(close),
        volume=dec(volume),
        ts_open_ns=ts_open,
        ts_close_ns=ts_close,
    )


def make_swing(
    *,
    sequence: int,
    direction: SwingDirection,
    price: object,
    occurred_index: int,
    confirmed_index: int | None = None,
    timeframe: Timeframe = Timeframe.WEEK,
    atr: object = 10,
    instrument_id: str = INSTRUMENT_ID,
) -> SwingPoint:
    """在合成的周线上构造一个已确认的摆动点。"""

    def ns(bars: int) -> int:
        base = make_bar(index=bars, timeframe=timeframe).ts_close_ns
        return base

    occurred_ns = ns(occurred_index)
    confirmed_ns = ns(confirmed_index if confirmed_index is not None else occurred_index)

    return SwingPoint(
        point_id=f"{instrument_id}-{timeframe.value}-{direction.value}-{sequence}",
        instrument_id=instrument_id,
        timeframe=timeframe,
        direction=direction,
        price=dec(price),
        occurred_at_ns=occurred_ns,
        confirmed_at_ns=confirmed_ns,
        atr_snapshot=dec(atr),
        source_bar_id=f"src-{sequence}",
        sequence=sequence,
    )
