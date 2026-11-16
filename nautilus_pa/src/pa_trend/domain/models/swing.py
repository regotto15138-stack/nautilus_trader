"""摆动点领域模型（规格第 3 节）。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pa_trend.domain.errors import BarValidationError
from pa_trend.domain.models.timeframe import Timeframe, ns_to_dt


class SwingDirection(StrEnum):
    """摆动极值的方向。"""

    HIGH = "HIGH"
    LOW = "LOW"


@dataclass(frozen=True, slots=True)
class SwingPoint:
    """一个已确认的摆动极值。

    模型把 ``occurred_at_ns`` 与 ``confirmed_at_ns`` 分开保存，确保任何决策都
    不会用到确认之后才产生的信息（规格第 0.3 节与第 3 节）。已确认的摆动点
    永不回溯修改。

    属性
    ----
    point_id : str
        唯一且确定性的摆动点标识。
    instrument_id : str
        Nautilus 合约标识。
    timeframe : Timeframe
        识别出该摆动点的周期。
    direction : SwingDirection
        ``HIGH`` 表示摆动高点，``LOW`` 表示摆动低点。
    price : Decimal
        极值价格。
    occurred_at_ns : int
        极值实际形成的时刻，UNIX 纪元以来的纳秒数。
    confirmed_at_ns : int
        反转被确认的时刻，UNIX 纪元以来的纳秒数。
    atr_snapshot : Decimal
        候选极值形成时冻结的 ATR。
    source_bar_id : str
        包含该极值的 K 线标识。
    sequence : int
        同周期内的顺序编号，从零开始。
    """

    point_id: str
    instrument_id: str
    timeframe: Timeframe
    direction: SwingDirection
    price: Decimal
    occurred_at_ns: int
    confirmed_at_ns: int
    atr_snapshot: Decimal
    source_bar_id: str
    sequence: int

    def __post_init__(self) -> None:
        """校验确认时序与取值不变量。"""
        if self.price <= 0:
            raise BarValidationError(f"swing price must be positive, was {self.price}")
        if self.atr_snapshot <= 0:
            raise BarValidationError(f"atr_snapshot must be positive, was {self.atr_snapshot}")
        if self.confirmed_at_ns < self.occurred_at_ns:
            raise BarValidationError(
                f"confirmed_at must not precede occurred_at for {self.point_id}",
            )
        if self.sequence < 0:
            raise BarValidationError(f"sequence must not be negative, was {self.sequence}")

    @property
    def occurred_at(self) -> datetime:
        """把极值时刻返回为带时区的 UTC datetime。"""
        return ns_to_dt(self.occurred_at_ns)

    @property
    def confirmed_at(self) -> datetime:
        """把确认时刻返回为带时区的 UTC datetime。"""
        return ns_to_dt(self.confirmed_at_ns)

    @property
    def is_high(self) -> bool:
        """该点是否为摆动高点。"""
        return self.direction is SwingDirection.HIGH
