"""Wilder 平均真实波幅（规格第 2.2 节）。"""

from __future__ import annotations

from collections import deque
from decimal import Decimal


class WilderAtr:
    """Wilder 平均真实波幅。

    真实波幅按规格定义::

        TR_t = max(H_t - L_t, |H_t - C_{t-1}|, |L_t - C_{t-1}|)

    第一根 K 线没有前收盘价，故取 ``H_t - L_t``。平滑的种子值取前 ``period``
    个真实波幅的算术平均，之后按规格递推::

        ATR_t = ((period - 1) * ATR_{t-1} + TR_t) / period

    除以 ``period`` 并非总能整除，因此数值保持在当前 ``decimal`` 上下文精度
    （默认 28 位有效数字）。该上下文是确定性的，可保证重放可复现。
    """

    def __init__(self, period: int = 14) -> None:
        """初始化平均真实波幅。

        参数
        ----
        period : int
            平滑周期，必须为正。

        异常
        ----
        ValueError
            当 ``period`` 不为正时抛出。
        """
        if period <= 0:
            raise ValueError(f"period must be positive, was {period}")
        self._period = period
        self._seed_trs: deque[Decimal] = deque(maxlen=period)
        self._atr: Decimal | None = None
        self._previous_close: Decimal | None = None

    @property
    def period(self) -> int:
        """返回平滑周期。"""
        return self._period

    @property
    def is_ready(self) -> bool:
        """ATR 数值是否已可用。"""
        return self._atr is not None

    @property
    def value(self) -> Decimal | None:
        """返回当前 ATR；预热期间返回 ``None``。"""
        return self._atr

    @property
    def previous_close(self) -> Decimal | None:
        """返回指标最近一次见到的收盘价。"""
        return self._previous_close

    def update(self, high: Decimal, low: Decimal, close: Decimal) -> None:
        """加入一根已完成 K 线。

        参数
        ----
        high : Decimal
            K 线最高价。
        low : Decimal
            K 线最低价。
        close : Decimal
            K 线收盘价。
        """
        if low > high:
            raise ValueError(f"low {low} must not exceed high {high}")

        true_range = self._true_range(high, low)
        self._previous_close = close

        if self._atr is None:
            self._seed_trs.append(true_range)
            if len(self._seed_trs) == self._period:
                self._atr = sum(self._seed_trs) / Decimal(self._period)
            return

        self._atr = (self._atr * (self._period - 1) + true_range) / Decimal(self._period)

    def _true_range(self, high: Decimal, low: Decimal) -> Decimal:
        if self._previous_close is None:
            return high - low
        high_gap = abs(high - self._previous_close)
        low_gap = abs(low - self._previous_close)
        return max(high - low, high_gap, low_gap)

    def reset(self) -> None:
        """清空所有状态。"""
        self._seed_trs.clear()
        self._atr = None
        self._previous_close = None
