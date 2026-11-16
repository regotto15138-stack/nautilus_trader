"""按 UTC 边界把细周期 K 线聚合为更慢的周期。

策略本身消费交易所原生（EXTERNAL）K 线。本聚合器的用途是：研究阶段用日线
重建周线与月线，并与交易所序列交叉核对，对应规格第 1.5 节的验证要求。
"""

from __future__ import annotations

from decimal import Decimal

from pa_trend.domain.errors import DataIntegrityError
from pa_trend.domain.models.bar import Bar
from pa_trend.domain.models.timeframe import (
    SECONDS_PER_DAY,
    Timeframe,
    expected_close_ns,
    ns_to_dt,
    window_start_ns,
)


class TimeframeAggregator:
    """把较快周期聚合为较慢周期。

    只有当来自后续窗口的 K 线到达、从而证明前一窗口不可能再有数据时，才输出
    该窗口。源 K 线数量少于该窗口日历长度的窗口会被记录在
    :attr:`incomplete_windows` 中，调用方可以选择拒绝或上报，而不是默认信任
    一个残缺的聚合结果。
    """

    def __init__(
        self,
        *,
        instrument_id: str,
        target_timeframe: Timeframe,
        source_timeframe: Timeframe,
        session_offset_minutes: int = 0,
    ) -> None:
        """初始化聚合器。

        参数
        ----
        instrument_id : str
            写入聚合 K 线的合约标识。
        target_timeframe : Timeframe
            要生成的较慢周期。
        source_timeframe : Timeframe
            输入 K 线的周期，必须快于目标周期。
        session_offset_minutes : int
            会话边界偏移（分钟）；0 表示 UTC。

        异常
        ----
        ValueError
            当源周期不快于目标周期时抛出。
        """
        if source_timeframe.rank >= target_timeframe.rank:
            raise ValueError(
                f"source timeframe {source_timeframe} must be faster than "
                f"target timeframe {target_timeframe}",
            )
        self._instrument_id = instrument_id
        self._target = target_timeframe
        self._source = source_timeframe
        self._session_offset = session_offset_minutes
        self._window_open_ns: int | None = None
        self._open = Decimal(0)
        self._high = Decimal(0)
        self._low = Decimal(0)
        self._close = Decimal(0)
        self._volume = Decimal(0)
        self._member_count = 0
        self._incomplete: list[int] = []

    @property
    def incomplete_windows(self) -> tuple[int, ...]:
        """返回源 K 线数量不足却已关闭的窗口起始时刻。"""
        return tuple(self._incomplete)

    def update(self, bar: Bar) -> Bar | None:
        """接收一根源周期 K 线。

        参数
        ----
        bar : Bar
            处于 ``source_timeframe`` 的 K 线。

        返回
        ----
        Bar 或 None
            窗口发生滚动时返回已完成的聚合 K 线。

        异常
        ----
        DataIntegrityError
            当 K 线属于其他周期或合约时抛出。
        """
        if bar.timeframe is not self._source:
            raise DataIntegrityError(
                f"aggregator expects {self._source} bars, received {bar.timeframe}",
            )
        if bar.instrument_id != self._instrument_id:
            raise DataIntegrityError(
                f"aggregator expects {self._instrument_id} bars, received {bar.instrument_id}",
            )

        window = window_start_ns(
            bar.ts_close_ns,
            self._target,
            session_offset_minutes=self._session_offset,
        )
        completed: Bar | None = None

        if self._window_open_ns is None:
            self._open_window(window, bar)
        elif window != self._window_open_ns:
            completed = self._close_window()
            self._open_window(window, bar)
        else:
            self._accumulate(bar)

        return completed

    def flush(self) -> Bar | None:
        """在没有新输入的情况下关闭当前尾部窗口。"""
        if self._window_open_ns is None:
            return None
        return self._close_window()

    def _open_window(self, window_open_ns: int, bar: Bar) -> None:
        self._window_open_ns = window_open_ns
        self._open = bar.open
        self._high = bar.high
        self._low = bar.low
        self._close = bar.close
        self._volume = bar.volume
        self._member_count = 1

    def _accumulate(self, bar: Bar) -> None:
        self._high = max(self._high, bar.high)
        self._low = min(self._low, bar.low)
        self._close = bar.close
        self._volume += bar.volume
        self._member_count += 1

    def _expected_members(self, window_open_ns: int) -> int:
        close_ns = expected_close_ns(
            window_open_ns,
            self._target,
            session_offset_minutes=self._session_offset,
        )
        if self._source is Timeframe.DAY:
            days = (close_ns - window_open_ns) // (SECONDS_PER_DAY * 1_000_000_000)
            return int(days)
        return 1

    def _close_window(self) -> Bar:
        if self._window_open_ns is None:
            raise RuntimeError("close_window called without an open window")

        expected = self._expected_members(self._window_open_ns)
        if self._member_count < expected:
            self._incomplete.append(self._window_open_ns)

        bar = Bar(
            instrument_id=self._instrument_id,
            timeframe=self._target,
            open=self._open,
            high=self._high,
            low=self._low,
            close=self._close,
            volume=self._volume,
            ts_open_ns=self._window_open_ns,
            ts_close_ns=expected_close_ns(
                self._window_open_ns,
                self._target,
                session_offset_minutes=self._session_offset,
            ),
            session_offset_minutes=self._session_offset,
        )
        self._window_open_ns = None
        self._member_count = 0
        return bar

    def describe_open_window(self) -> str:
        """返回当前正在构建的窗口的简短描述。"""
        if self._window_open_ns is None:
            return "no open window"
        return f"open={ns_to_dt(self._window_open_ns).isoformat()} members={self._member_count}"
