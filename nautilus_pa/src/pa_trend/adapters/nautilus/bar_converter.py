"""把 NautilusTrader 的 K 线转换为领域 K 线。

价格与成交量一律通过 ``as_decimal()`` 读取，它暴露精确的定点值。绝不使用
``as_double()``：一次浮点往返就会破坏价格与数量的精确算术要求。

K 线时间戳语义
--------------
OKX 适配器把 EXTERNAL K 线的 ``ts_event`` 定义为蜡烛**开盘**时刻，``ts_init``
为收盘时刻（见 ``crates/adapters/okx/src/http/client.rs`` 的
``parse_historical_candlestick``，它令 ``ts_init = ts_event + interval``；以及
``Requests historical bars`` 的文档注释：“Each bar uses the candle open time as
``ts_event`` and its close time as ``ts_init``”）。

但 ``ts_init`` 不能普遍当作收盘时刻使用：WebSocket 路径传入的是消息到达时间。
因此窗口按 ``[ts_event, ts_event + period)`` 推导，这也正是适配器自身在除
``Month`` 之外所有聚合上的做法。

周期取自冻结的 UTC 口径（规格第 1.5 节），而不是取自交易所。开盘时刻不落在
UTC 边界上的 K 线会抛出 :class:`~pa_trend.domain.errors.BarAlignmentError`，
而不是被静默平移。这对 OKX 月线尤为重要：适配器按 UTC+8 日历界定月线，应用
:class:`~pa_trend.application.aggregation.TimeframeAggregator` 由日线重建 UTC 月线。
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from pa_trend.domain.errors import BarAlignmentError
from pa_trend.domain.models.bar import Bar as DomainBar
from pa_trend.domain.models.timeframe import Timeframe, expected_close_ns

if TYPE_CHECKING:
    from nautilus_trader.model import Bar as NautilusBar


def bar_window_ns(
    ts_event: int,
    timeframe: Timeframe,
    *,
    session_offset_minutes: int = 0,
) -> tuple[int, int]:
    """把 K 线的 ``ts_event`` 解析成精确的 ``(open_ns, close_ns)`` 窗口。

    参数
    ----
    ts_event : int
        K 线蜡烛开盘时刻，UNIX 纪元以来的纳秒数。
    timeframe : Timeframe
        K 线周期，采用冻结的 UTC 口径。

    返回
    ----
    tuple of (int, int)
        窗口起止时刻的纳秒数。
    """
    open_ns = ts_event
    return open_ns, expected_close_ns(
        open_ns,
        timeframe,
        session_offset_minutes=session_offset_minutes,
    )


def to_domain_bar(
    bar: NautilusBar,
    timeframe: Timeframe,
    *,
    instrument_id: str | None = None,
    session_offset_minutes: int = 0,
) -> DomainBar:
    """把一根 Nautilus K 线转换为领域 K 线。

    参数
    ----
    bar : NautilusBar
        交易所 K 线，其 ``ts_event`` 必须是蜡烛开盘时刻。
    timeframe : Timeframe
        该 K 线代表的周期。
    instrument_id : str 或 None
        可覆盖合约标识；缺省取 K 线类型自带的标识。
    session_offset_minutes : int
        交易所会话边界相对 UTC 的偏移（分钟）。0 表示严格 UTC；OKX 需要 480
        （UTC+8）。

    返回
    ----
    DomainBar
        经过校验的领域 K 线。

    异常
    ----
    BarAlignmentError
        当窗口未对齐到 ``timeframe`` 的 UTC 边界时抛出。
    """
    ts_open_ns, ts_close_ns = bar_window_ns(
        int(bar.ts_event),
        timeframe,
        session_offset_minutes=session_offset_minutes,
    )
    resolved_id = instrument_id or str(bar.bar_type.instrument_id)

    try:
        return DomainBar(
            instrument_id=resolved_id,
            timeframe=timeframe,
            open=Decimal(bar.open.as_decimal()),
            high=Decimal(bar.high.as_decimal()),
            low=Decimal(bar.low.as_decimal()),
            close=Decimal(bar.close.as_decimal()),
            volume=Decimal(bar.volume.as_decimal()),
            ts_open_ns=ts_open_ns,
            ts_close_ns=ts_close_ns,
            session_offset_minutes=session_offset_minutes,
        )
    except BarAlignmentError as exc:
        raise BarAlignmentError(
            f"{exc}. The bar window was derived as [{ts_open_ns}, {ts_close_ns}) from "
            f"ts_event={ts_open_ns}. If the venue aligns candles to a non-UTC session, "
            "rebuild them on UTC boundaries before analysis (spec section 1.5), or "
            "declare the venue session with session_offset_minutes (OKX = 480).",
        ) from exc
