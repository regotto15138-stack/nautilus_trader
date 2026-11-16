"""生成确定性的合成 K 线，供演示与自检使用。

合成序列按「上涨段 + 回调段」的模板生成，因此会稳定出现较高高点与较高低点，
从而使 ZigZag 与多头 N 结构真实触发。同一 ``seed`` 总是产生同一序列，便于复现
图表与回归对比。

该数据仅用于界面演示与自检，不具备任何市场含义。
"""

from __future__ import annotations

import random
from datetime import UTC, datetime
from decimal import Decimal

from pa_trend.domain.models.bar import Bar
from pa_trend.domain.models.timeframe import (
    Timeframe,
    add_periods,
    dt_to_ns,
    expected_close_ns,
    floor_to_boundary,
)

DEFAULT_SEED = 20240101
DEFAULT_START = datetime(2023, 1, 1, tzinfo=UTC)
DEFAULT_START_PRICE = Decimal("1600.00")

# 单根 K 线的价格单位：起始价的 0.2%。
_UNIT_DIVISOR = 500

# 上涨段与回调段每根 K 线的位移倍数。回调斜率更缓，保证净涨幅为正。
_UP_STEP_MULTIPLIER = 2
_DOWN_STEP_MULTIPLIER = 1

_UP_LEG_BARS = (7, 14)
_DOWN_LEG_BARS = (5, 9)


def generate_demo_bars(
    *,
    instrument_id: str,
    timeframe: Timeframe,
    count: int = 320,
    seed: int = DEFAULT_SEED,
    start: datetime = DEFAULT_START,
    start_price: Decimal = DEFAULT_START_PRICE,
) -> list[Bar]:
    """生成一段确定性的合成 OHLCV 序列。

    参数
    ----
    instrument_id : str
        写入 K 线的合约标识。
    timeframe : Timeframe
        生成 K 线的周期，决定时间边界。
    count : int
        生成的 K 线根数。
    seed : int
        随机种子；相同种子产生相同序列。
    start : datetime
        第一根 K 线的起始时间，会先向下对齐到周期边界。
    start_price : Decimal
        起始价格。

    返回
    ----
    list of Bar
        按时间升序排列的已完成 K 线。
    """
    if count <= 0:
        raise ValueError(f"count must be positive, was {count}")

    rng = random.Random(seed)
    base_cents = int(start_price * 100)
    price_cents = base_cents
    unit = max(1, base_cents // _UNIT_DIVISOR)

    bars: list[Bar] = []
    window_start = floor_to_boundary(start, timeframe)

    rising = True
    leg_left = rng.randint(*_UP_LEG_BARS)

    for _ in range(count):
        if leg_left <= 0:
            rising = not rising
            leg_left = rng.randint(*(_UP_LEG_BARS if rising else _DOWN_LEG_BARS))

        step = unit * (_UP_STEP_MULTIPLIER if rising else _DOWN_STEP_MULTIPLIER)
        move = rng.randint(1, 2) * step
        if not rising:
            move = -move

        # 叠加少量噪声，避免走势过于机械。
        noise = rng.randint(-unit // 2, unit // 2)

        open_cents = price_cents
        close_cents = max(1, open_cents + move + noise)

        wick_up = rng.randint(0, unit)
        wick_down = rng.randint(0, unit)
        high_cents = max(open_cents, close_cents) + wick_up
        low_cents = max(1, min(open_cents, close_cents) - wick_down)

        ts_open_ns = dt_to_ns(window_start)
        bars.append(
            Bar(
                instrument_id=instrument_id,
                timeframe=timeframe,
                open=Decimal(open_cents) / 100,
                high=Decimal(high_cents) / 100,
                low=Decimal(low_cents) / 100,
                close=Decimal(close_cents) / 100,
                volume=Decimal(rng.randint(500, 25_000)),
                ts_open_ns=ts_open_ns,
                ts_close_ns=expected_close_ns(ts_open_ns, timeframe),
            ),
        )

        price_cents = close_cents
        leg_left -= 1
        window_start = add_periods(window_start, timeframe, 1)

    return bars
