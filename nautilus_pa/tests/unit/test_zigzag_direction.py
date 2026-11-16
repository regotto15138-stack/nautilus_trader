"""ZigZag 方向对外语义测试（SACW 17.1 / 第 33 章字段映射）。"""

from __future__ import annotations

from pathlib import Path

from helpers import INSTRUMENT_ID, dec, make_bar
from pa_trend.application.demo_data import generate_demo_bars
from pa_trend.application.market_context import MarketContext
from pa_trend.config.loader import load_config
from pa_trend.domain.models.timeframe import Timeframe
from pa_trend.domain.zigzag.detector import ZigZagConfig, ZigZagDetector, ZigZagDirection

CONFIGS_DIR = Path(__file__).resolve().parents[2] / "configs"


def _detector() -> ZigZagDetector:
    return ZigZagDetector(
        instrument_id=INSTRUMENT_ID,
        timeframe=Timeframe.DAY,
        config=ZigZagConfig(reversal_atr_multiple=dec("2.0")),
    )


def test_enum_matches_sacw_mapping() -> None:
    """枚举值必须与 SACW 第 33 章映射表一致。"""
    assert {d.value for d in ZigZagDirection} == {"SEEK_HIGH", "SEEK_LOW", "UNKNOWN"}


def test_no_candidate_reports_unknown() -> None:
    """尚未建立候选时对外方向为 UNKNOWN。"""
    detector = _detector()
    assert detector.reported_direction is ZigZagDirection.UNKNOWN
    # ATR 未就绪时不建立候选。
    detector.update(make_bar(index=0), None)
    assert detector.reported_direction is ZigZagDirection.UNKNOWN


def test_candidate_reports_seek_direction() -> None:
    """建立候选后对外方向为 SEEK_HIGH 或 SEEK_LOW。"""
    detector = _detector()
    detector.update(make_bar(index=0, high=101, low=99, close=100), dec("10"))
    assert detector.reported_direction is ZigZagDirection.SEEK_HIGH
    assert detector.candidate_price is not None
    assert detector.candidate_atr == dec("10")


def test_candidate_atr_is_frozen_snapshot() -> None:
    """候选 ATR 必须是候选形成时冻结的值（atr_snapshot）。"""
    detector = _detector()
    detector.update(make_bar(index=0, high=101, low=99, close=100), dec("10"))
    frozen = detector.candidate_atr
    # 后续 K 线 ATR 变化，但候选未被更新时快照不变。
    detector.update(make_bar(index=1, high=100.5, low=98, close=100), dec("999"))
    assert detector.candidate_atr == frozen == dec("10")


def test_context_exposes_zigzag_direction_per_timeframe() -> None:
    """七个周期各自独立报告 ZigZag 方向。"""
    config = load_config(CONFIGS_DIR)
    context = MarketContext(config)
    for bar in generate_demo_bars(
        instrument_id=INSTRUMENT_ID,
        timeframe=Timeframe.DAY,
        count=40,
    ):
        context.on_bar(bar)

    view = context.view(Timeframe.DAY)
    assert view.zigzag_direction in {"SEEK_HIGH", "SEEK_LOW", "UNKNOWN"}
    # 未喂数据的周期应停在 UNKNOWN。
    assert context.view(Timeframe.MONTH).zigzag_direction == "UNKNOWN"
