"""周期角色映射（规格 V1.4.8 第 2.1 节）。"""

from __future__ import annotations

from pa_trend.domain.errors import ConfigurationError
from pa_trend.domain.models.timeframe import ALL_TIMEFRAMES, Timeframe

_TIMEFRAME_BY_SPEC = {
    "1-MONTH": Timeframe.MONTH,
    "1-WEEK": Timeframe.WEEK,
    "1-DAY": Timeframe.DAY,
    "4-HOUR": Timeframe.HOUR4,
    "1-HOUR": Timeframe.HOUR1,
    "15-MINUTE": Timeframe.MIN15,
    "3-MINUTE": Timeframe.MIN3,
}

#: 配置键 → 期望周期。角色由规格固定，不允许互换。
_ROLE_EXPECTATIONS = {
    "macro": Timeframe.MONTH,
    "mid": Timeframe.WEEK,
    "short": Timeframe.DAY,
    "setup": Timeframe.HOUR4,
    "reversal": Timeframe.HOUR1,
    "signal": Timeframe.MIN15,
    "execution": Timeframe.MIN3,
}


def parse_timeframe_spec(value: object, *, role: str) -> Timeframe:
    """把 K 线规格标记映射为 :class:`Timeframe`。"""
    token = str(value)
    try:
        return _TIMEFRAME_BY_SPEC[token]
    except KeyError:
        supported = ", ".join(sorted(_TIMEFRAME_BY_SPEC))
        raise ConfigurationError(
            f"timeframes.{role} must be one of {supported}, was {token}",
        ) from None


class TimeframeSettings:
    """七个周期角色（规格第 2.1 节）。"""

    def __init__(self, raw: dict[str, object]) -> None:
        """从 ``timeframes`` 映射构建并校验角色。"""
        for role, expected in _ROLE_EXPECTATIONS.items():
            if role not in raw:
                raise ConfigurationError(f"timeframes.{role} is required")
            actual = parse_timeframe_spec(raw.get(role), role=role)
            if actual is not expected:
                raise ConfigurationError(
                    f"timeframes.{role} must be {expected.bar_spec}, was {actual.bar_spec}",
                )
            setattr(self, role, actual)

    def all(self) -> tuple[Timeframe, ...]:
        """按由慢到快返回全部周期。"""
        return ALL_TIMEFRAMES

    def as_dict(self) -> dict[str, Timeframe]:
        """返回角色到周期的映射。"""
        return dict(_ROLE_EXPECTATIONS.items())
