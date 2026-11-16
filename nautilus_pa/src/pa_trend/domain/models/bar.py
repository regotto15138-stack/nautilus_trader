"""已完成 K 线的领域模型（规格第 0.3 节：只使用已完成 K 线）。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from pa_trend.domain.errors import BarAlignmentError, BarValidationError
from pa_trend.domain.models.timeframe import Timeframe, is_aligned, ns_to_dt


@dataclass(frozen=True, slots=True)
class Bar:
    """某个周期上的一根已完成 OHLCV K 线。

    每个实例都代表**已完成**的 K 线；策略不会用未走完的蜡烛构造 Bar
    （规格第 0.3 节）。

    属性
    ----
    instrument_id : str
        Nautilus 合约标识，例如 ``ETH-USDT-SWAP.OKX``。
    timeframe : Timeframe
        该 K 线所属周期。
    open, high, low, close : Decimal
        精确价格；绝不使用浮点（规格第 10.x 节）。
    volume : Decimal
        成交量，不可为负。
    ts_open_ns : int
        窗口起始时刻，UNIX 纪元以来的纳秒数（UTC）。
    ts_close_ns : int
        窗口结束时刻，UNIX 纪元以来的纳秒数（UTC）。
    """

    instrument_id: str
    timeframe: Timeframe
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    ts_open_ns: int
    ts_close_ns: int
    #: 交易所会话边界相对 UTC 的偏移（分钟）；0 表示严格 UTC（规格第 1.5 节）。
    session_offset_minutes: int = 0

    def __post_init__(self) -> None:
        """校验价格、成交量与时间边界不变量。"""
        if not self.instrument_id:
            raise BarValidationError("instrument_id must not be empty")
        if self.ts_close_ns <= self.ts_open_ns:
            raise BarValidationError(
                f"ts_close_ns must be greater than ts_open_ns, "
                f"was {self.ts_close_ns} <= {self.ts_open_ns}",
            )
        if self.low > self.high:
            raise BarValidationError(f"low {self.low} must not exceed high {self.high}")
        if self.low > min(self.open, self.close):
            raise BarValidationError(
                f"low {self.low} must not exceed open/close ({self.open}, {self.close})",
            )
        if self.high < max(self.open, self.close):
            raise BarValidationError(
                f"high {self.high} must not be below open/close ({self.open}, {self.close})",
            )
        if self.volume < 0:
            raise BarValidationError(f"volume must not be negative, was {self.volume}")
        if not is_aligned(
            self.ts_open_ns,
            self.ts_close_ns,
            self.timeframe,
            session_offset_minutes=self.session_offset_minutes,
        ):
            raise BarAlignmentError(
                f"bar {self.bar_id} is not aligned to a UTC {self.timeframe.name} "
                f"boundary (open={self.ts_open}, close={self.ts_close}); "
                "verify the venue bar timestamps against spec section 1.5",
            )

    @property
    def bar_id(self) -> str:
        """返回确定性的、可重放的 K 线标识。"""
        return f"{self.instrument_id}-{self.timeframe.value}-{self.ts_close_ns}"

    @property
    def ts_open(self) -> datetime:
        """把窗口起始时刻返回为带时区的 UTC datetime。"""
        return ns_to_dt(self.ts_open_ns)

    @property
    def ts_close(self) -> datetime:
        """把窗口结束时刻返回为带时区的 UTC datetime。"""
        return ns_to_dt(self.ts_close_ns)

    @property
    def is_bullish(self) -> bool:
        """收盘价是否不低于开盘价。"""
        return self.close >= self.open

    @property
    def body(self) -> Decimal:
        """返回蜡烛实体的绝对值。"""
        return abs(self.close - self.open)

    @property
    def price_range(self) -> Decimal:
        """返回最高价到最低价的振幅。"""
        return self.high - self.low

    def close_position(self) -> Decimal | None:
        """返回收盘价在振幅中的相对位置，取值 ``[0, 1]``。

        返回
        ----
        Decimal 或 None
            振幅为零、位置无定义时返回 ``None``。
        """
        if self.high == self.low:
            return None
        return (self.close - self.low) / (self.high - self.low)
