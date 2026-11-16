"""七周期时间边界（规格 V1.4.8 第 3.1 节与第 2.1 节）。

系统使用七个周期，各自独立维护状态：

- ``1MONTH``：宏观趋势方向
- ``1W``：中期趋势方向
- ``1D``：短期趋势环境
- ``4H``：回撤结构与支撑区域
- ``1H``：回撤结束与反转候选
- ``15M``：核心 N 结构与入场信号
- ``3M``：入场执行确认

全部内部时间为 UTC；Bar 区间左闭右开 ``[open_time, close_time)``。日历周期
（月/周/日）按 UTC 自然边界切分，日内周期（4H/1H/15M/3M）按固定时长对齐。
交易所若使用非 UTC 会话（例如 OKX 为 UTC+8），通过 ``session_offset_minutes``
把会话边界映射回 UTC 后再判断。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum

NS_PER_SECOND = 1_000_000_000
NS_PER_MICROSECOND = 1_000
NS_PER_MINUTE = 60 * NS_PER_SECOND
NS_PER_HOUR = 60 * NS_PER_MINUTE

SECONDS_PER_DAY = 86_400

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_ONE_MICROSECOND = timedelta(microseconds=1)


class Timeframe(StrEnum):
    """七个分析周期（规格第 2.1 节）。"""

    MONTH = "1M"
    WEEK = "1W"
    DAY = "1D"
    HOUR4 = "4H"
    HOUR1 = "1H"
    MIN15 = "15M"
    MIN3 = "3M"

    @property
    def bar_spec(self) -> str:
        """返回 NautilusTrader 的 K 线规格标记。"""
        return _BAR_SPECS[self]

    @property
    def rank(self) -> int:
        """快慢等级；数值越大周期越慢。"""
        return _RANKS[self]

    @property
    def label(self) -> str:
        """返回中文显示名。"""
        return _LABELS[self]

    @property
    def duration_ns(self) -> int | None:
        """固定时长周期的纳秒长度；日历周期返回 ``None``。"""
        return _DURATIONS_NS.get(self)


_BAR_SPECS = {
    Timeframe.MONTH: "1-MONTH",
    Timeframe.WEEK: "1-WEEK",
    Timeframe.DAY: "1-DAY",
    Timeframe.HOUR4: "4-HOUR",
    Timeframe.HOUR1: "1-HOUR",
    Timeframe.MIN15: "15-MINUTE",
    Timeframe.MIN3: "3-MINUTE",
}

_RANKS = {
    Timeframe.MONTH: 7,
    Timeframe.WEEK: 6,
    Timeframe.DAY: 5,
    Timeframe.HOUR4: 4,
    Timeframe.HOUR1: 3,
    Timeframe.MIN15: 2,
    Timeframe.MIN3: 1,
}

_LABELS = {
    Timeframe.MONTH: "月线",
    Timeframe.WEEK: "周线",
    Timeframe.DAY: "日线",
    Timeframe.HOUR4: "4 小时",
    Timeframe.HOUR1: "1 小时",
    Timeframe.MIN15: "15 分钟",
    Timeframe.MIN3: "3 分钟",
}

_DURATIONS_NS = {
    Timeframe.HOUR4: 4 * NS_PER_HOUR,
    Timeframe.HOUR1: NS_PER_HOUR,
    Timeframe.MIN15: 15 * NS_PER_MINUTE,
    Timeframe.MIN3: 3 * NS_PER_MINUTE,
}

#: 宏观周期（决定方向权限）。
MACRO_TIMEFRAMES = (Timeframe.MONTH, Timeframe.WEEK, Timeframe.DAY)

#: 结构周期（4H 回撤结构、1H 反转候选）。
SETUP_TIMEFRAMES = (Timeframe.HOUR4, Timeframe.HOUR1)

#: 信号与执行周期。
SIGNAL_TIMEFRAME = Timeframe.MIN15
EXECUTION_TIMEFRAME = Timeframe.MIN3

#: 规格中的全部周期，按由慢到快排序。
ALL_TIMEFRAMES = (
    Timeframe.MONTH,
    Timeframe.WEEK,
    Timeframe.DAY,
    Timeframe.HOUR4,
    Timeframe.HOUR1,
    Timeframe.MIN15,
    Timeframe.MIN3,
)


def dt_to_ns(value: datetime) -> int:
    """把带时区的 datetime 转为 UNIX 纪元以来的整数纳秒。"""
    if value.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")
    delta = value.astimezone(UTC) - _EPOCH
    return (delta.days * SECONDS_PER_DAY + delta.seconds) * NS_PER_SECOND + (
        delta.microseconds * NS_PER_MICROSECOND
    )


def ns_to_dt(value: int) -> datetime:
    """把整数纳秒转为 UTC datetime，并截断到微秒精度。"""
    return _EPOCH + timedelta(microseconds=value // NS_PER_MICROSECOND)


def _session_shift_ns(session_offset_minutes: int) -> int:
    """把会话偏移（分钟）换算为纳秒位移；0 表示严格 UTC。"""
    return session_offset_minutes * 60 * NS_PER_SECOND


def floor_to_boundary(value: datetime, timeframe: Timeframe) -> datetime:
    """返回小于等于 ``value`` 的最大周期边界（UTC 语义）。

    日内周期按固定时长对齐；日历周期按自然月/周/日对齐。
    """
    ts = value.astimezone(UTC)
    duration = timeframe.duration_ns
    if duration is not None:
        epoch_ns = dt_to_ns(ts)
        return ns_to_dt(epoch_ns - (epoch_ns % duration))
    if timeframe is Timeframe.DAY:
        return ts.replace(hour=0, minute=0, second=0, microsecond=0)
    if timeframe is Timeframe.WEEK:
        midnight = ts.replace(hour=0, minute=0, second=0, microsecond=0)
        return midnight - timedelta(days=midnight.weekday())
    if timeframe is Timeframe.MONTH:
        return ts.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    raise ValueError(f"unsupported timeframe: {timeframe!r}")


def next_boundary(value: datetime, timeframe: Timeframe) -> datetime:
    """返回 ``value`` 所在窗口之后的下一个周期边界（UTC 语义）。"""
    duration = timeframe.duration_ns
    if duration is not None:
        epoch_ns = dt_to_ns(value)
        return ns_to_dt(epoch_ns - (epoch_ns % duration) + duration)
    start = floor_to_boundary(value, timeframe)
    if timeframe is Timeframe.DAY:
        return start + timedelta(days=1)
    if timeframe is Timeframe.WEEK:
        return start + timedelta(weeks=1)
    if start.month == 12:
        return start.replace(year=start.year + 1, month=1)
    return start.replace(month=start.month + 1)


def add_periods(value: datetime, timeframe: Timeframe, periods: int) -> datetime:
    """把 ``value`` 平移整数个周期。"""
    duration = timeframe.duration_ns
    if duration is not None:
        return ns_to_dt(dt_to_ns(value) + periods * duration)
    if timeframe is Timeframe.DAY:
        return value.astimezone(UTC) + timedelta(days=periods)
    if timeframe is Timeframe.WEEK:
        return value.astimezone(UTC) + timedelta(weeks=periods)
    if timeframe is Timeframe.MONTH:
        months = value.year * 12 + (value.month - 1) + periods
        year, month = divmod(months, 12)
        return value.astimezone(UTC).replace(year=year, month=month + 1, day=1)
    raise ValueError(f"unsupported timeframe: {timeframe!r}")


def window_start_ns(
    close_ns: int,
    timeframe: Timeframe,
    *,
    session_offset_minutes: int = 0,
) -> int:
    """返回以 ``close_ns`` 收盘的窗口起始时刻。"""
    shift = _session_shift_ns(session_offset_minutes)
    previous = ns_to_dt(close_ns + shift) - _ONE_MICROSECOND
    return dt_to_ns(floor_to_boundary(previous, timeframe)) - shift


def expected_close_ns(
    open_ns: int,
    timeframe: Timeframe,
    *,
    session_offset_minutes: int = 0,
) -> int:
    """返回从 ``open_ns`` 开始的窗口应收盘的时刻。"""
    shift = _session_shift_ns(session_offset_minutes)
    return dt_to_ns(next_boundary(ns_to_dt(open_ns + shift), timeframe)) - shift


def next_close_ns(
    close_ns: int,
    timeframe: Timeframe,
    *,
    session_offset_minutes: int = 0,
) -> int:
    """返回紧接 ``close_ns`` 之后的下一个周期收盘时刻。"""
    shift = _session_shift_ns(session_offset_minutes)
    return dt_to_ns(add_periods(ns_to_dt(close_ns + shift), timeframe, 1)) - shift


def is_aligned(
    open_ns: int,
    close_ns: int,
    timeframe: Timeframe,
    *,
    session_offset_minutes: int = 0,
) -> bool:
    """判断 K 线是否精确落在 ``timeframe`` 的（会话）边界上。

    先校验窗口长度与该周期一致（防止周期配错），再校验开盘时刻落在边界上。
    """
    shift = _session_shift_ns(session_offset_minutes)
    expected_close = (
        dt_to_ns(
            next_boundary(ns_to_dt(open_ns + shift), timeframe),
        )
        - shift
    )
    if expected_close != close_ns:
        return False
    floored = dt_to_ns(floor_to_boundary(ns_to_dt(open_ns + shift), timeframe)) - shift
    return floored == open_ns
