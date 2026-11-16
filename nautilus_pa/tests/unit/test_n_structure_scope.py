"""N 结构交易性失效的周期限定测试（规格 V1.4.8 第 5.5 节）。

规格原文：``n_structure_break_buffer_atr`` 的交易性失效判定**仅适用于 15M 多头
N 结构**；4H/1H 的 N 结构只能作为 ``RESEARCH_ONLY`` 研究对象，不得与 15M 共用
该交易参数。
"""

from __future__ import annotations

from pathlib import Path

from helpers import INSTRUMENT_ID, dec, make_swing
from pa_trend.application.demo_data import generate_demo_bars
from pa_trend.application.market_context import MarketContext
from pa_trend.config.loader import load_config
from pa_trend.domain.models.swing import SwingDirection
from pa_trend.domain.models.timeframe import Timeframe
from pa_trend.domain.structure.n_structure import NStructureDetector

CONFIGS_DIR = Path(__file__).resolve().parents[2] / "configs"


def _detector(
    timeframe: Timeframe,
    *,
    trading: bool,
    invalidation: bool = False,
) -> NStructureDetector:
    return NStructureDetector(
        instrument_id=INSTRUMENT_ID,
        timeframe=timeframe,
        break_buffer_atr=dec("0.1"),
        trading_enabled=trading,
        invalidation_enabled=invalidation,
    )


def _feed_n_structure(detector: NStructureDetector) -> object:
    """喂入 L1=100 → H1=200 → L2=150 → H2=250，得到一个多头 N 结构。"""
    sequence = (
        (SwingDirection.LOW, 100, 0),
        (SwingDirection.HIGH, 200, 1),
        (SwingDirection.LOW, 150, 2),
        (SwingDirection.HIGH, 250, 3),
    )
    structure = None
    for seq, (direction, price, index) in enumerate(sequence):
        structure = detector.on_swing_point(
            make_swing(
                sequence=seq,
                direction=direction,
                price=price,
                occurred_index=index,
                timeframe=detector._timeframe,
            ),
        )
    return structure


def test_signal_timeframe_structure_is_tradeable() -> None:
    """15M 结构具备交易性失效判定。"""
    detector = _detector(Timeframe.MIN15, trading=True)
    assert detector.scope == "TRADING"
    structure = _feed_n_structure(detector)
    assert structure is not None
    # 检测器只产出 CONFIRMED；交易性由 scope 与引擎激活共同决定。
    structure.activate(structure.confirmed_at_ns)
    assert detector.active_structures


def test_research_timeframe_structure_is_not_tradeable() -> None:
    """非 15M 结构标记为 RESEARCH_ONLY，且不计入可交易结构。"""
    detector = _detector(Timeframe.HOUR4, trading=False)
    assert detector.scope == "RESEARCH_ONLY"
    structure = _feed_n_structure(detector)
    assert structure is not None
    structure.activate(structure.confirmed_at_ns)
    assert detector.active_structures == ()
    assert detector.structures  # 研究结构仍然被识别与保留


def test_research_timeframe_skips_trading_invalidation() -> None:
    """非交易周期不做交易性失效判定。"""
    detector = _detector(Timeframe.HOUR4, trading=False)
    structure = _feed_n_structure(detector)
    assert structure is not None

    # 收盘远低于 L2 - 0.1 ATR，若按交易规则应失效。
    from helpers import make_bar

    bar = make_bar(
        index=10,
        timeframe=Timeframe.HOUR4,
        open_price=100,
        high=101,
        low=90,
        close=95,
    )
    assert detector.on_bar(bar, dec("10")) == ()
    # 检测器产出 CONFIRMED；引擎负责 activate()。此处只需确认未被失效。
    assert structure.status.value != "INVALIDATED"


def test_trading_timeframe_does_invalidate() -> None:
    """15M 按交易规则失效。"""
    from helpers import make_bar

    detector = _detector(Timeframe.MIN15, trading=True, invalidation=True)
    structure = _feed_n_structure(detector)
    assert structure is not None

    bar = make_bar(
        index=10,
        timeframe=Timeframe.MIN15,
        open_price=140,
        high=141,
        low=130,
        close=140,
    )
    invalidated = detector.on_bar(bar, dec("10"))
    assert len(invalidated) == 1
    assert structure.status.value == "INVALIDATED"


def test_trading_timeframe_defaults_to_spec_ambiguity() -> None:
    """交易周期的失效判定默认阻塞，直到 ATR 时点被裁定。"""
    from helpers import make_bar

    detector = _detector(Timeframe.MIN15, trading=True)
    structure = _feed_n_structure(detector)
    assert structure is not None
    assert detector.scope == "TRADING"
    assert detector.invalidation_status == "SPEC_AMBIGUITY"

    bar = make_bar(
        index=10,
        timeframe=Timeframe.MIN15,
        open_price=140,
        high=141,
        low=130,
        close=140,
    )
    assert detector.on_bar(bar, dec("10")) == ()
    assert structure.status.value != "INVALIDATED"


def test_config_declares_signal_timeframe() -> None:
    """配置必须声明交易性 N 结构所属周期，且被门禁固定为 15M。"""
    config = load_config(CONFIGS_DIR)
    assert config.n_structure.trading_timeframe == "15M"


def test_market_context_applies_scope_per_timeframe() -> None:
    """七个周期中只有 15M 的结构 scope 为 TRADING。"""
    config = load_config(CONFIGS_DIR)
    context = MarketContext(config)

    scopes = {
        timeframe.value: context.engine(timeframe).structures.scope
        for timeframe in config.timeframes.all()
    }
    assert scopes["15M"] == "TRADING"
    for code, scope in scopes.items():
        if code != "15M":
            assert scope == "RESEARCH_ONLY", f"{code} 不应具备交易性失效判定"


def test_research_structures_never_count_as_active(context_placeholder=None) -> None:
    """喂入真实形态后，非 15M 周期的可交易结构数必须为 0。"""
    config = load_config(CONFIGS_DIR)
    context = MarketContext(config)
    for timeframe in config.timeframes.all():
        for bar in generate_demo_bars(
            instrument_id=INSTRUMENT_ID,
            timeframe=timeframe,
            count=160,
        ):
            context.on_bar(bar)

    snapshot = context.snapshot()
    for code, view in snapshot.per_timeframe.items():
        if code is Timeframe.MIN15:
            continue
        assert view.active_structures == 0, f"{code.value} 不应存在可交易结构"
