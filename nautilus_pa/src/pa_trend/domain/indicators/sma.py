"""简单移动平均（规格第 2.1 节）。"""

from __future__ import annotations

from collections import deque
from decimal import Decimal


class SimpleMovingAverage:
    """对 ``period`` 个样本求算术移动平均。

    样本数不足时取值为 ``None``，避免调用方把尚未预热完成的均值当作有效值
    （规格第 4.6 节）。
    """

    def __init__(self, period: int) -> None:
        """初始化移动平均。

        参数
        ----
        period : int
            窗口内的样本个数，必须为正。

        异常
        ----
        ValueError
            当 ``period`` 不为正时抛出。
        """
        if period <= 0:
            raise ValueError(f"period must be positive, was {period}")
        self._period = period
        self._samples: deque[Decimal] = deque(maxlen=period)
        self._total = Decimal(0)

    @property
    def period(self) -> int:
        """返回窗口长度。"""
        return self._period

    @property
    def count(self) -> int:
        """返回窗口内当前的样本数。"""
        return len(self._samples)

    @property
    def is_ready(self) -> bool:
        """窗口是否已填满。"""
        return len(self._samples) == self._period

    @property
    def value(self) -> Decimal | None:
        """返回当前均值；预热期间返回 ``None``。"""
        if not self.is_ready:
            return None
        return self._total / Decimal(self._period)

    def update(self, sample: Decimal) -> None:
        """加入一个样本；窗口已满时淘汰最旧的样本。

        参数
        ----
        sample : Decimal
            新的观测值。
        """
        if len(self._samples) == self._period:
            self._total -= self._samples[0]
        self._samples.append(sample)
        self._total += sample

    def reset(self) -> None:
        """清空所有样本。"""
        self._samples.clear()
        self._total = Decimal(0)
