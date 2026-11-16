"""数据质量报告测试（规格第 1.5 节验证清单）。"""

from __future__ import annotations

from helpers import make_bar
from pa_trend.application.data_quality import IssueKind, validate_bar_series
from pa_trend.domain.models.timeframe import Timeframe


def test_contiguous_series_is_clean() -> None:
    """连续序列应无任何问题。"""
    bars = [make_bar(index=index) for index in range(3)]
    report = validate_bar_series(bars, Timeframe.DAY)
    assert report.is_clean
    assert report.bar_count == 3


def test_duplicate_close_is_reported() -> None:
    """重复的收盘时间戳应被报出。"""
    bars = [make_bar(index=0), make_bar(index=1), make_bar(index=1)]
    report = validate_bar_series(bars, Timeframe.DAY)
    assert report.count(IssueKind.DUPLICATE) == 1
    assert not report.is_clean


def test_missing_period_is_reported() -> None:
    """缺失一期应被报出。"""
    bars = [make_bar(index=0), make_bar(index=2)]
    report = validate_bar_series(bars, Timeframe.DAY)
    assert report.count(IssueKind.GAP) == 1


def test_every_missing_period_is_reported() -> None:
    """每一个缺失周期都应被逐条枚举。"""
    bars = [make_bar(index=0), make_bar(index=4)]
    report = validate_bar_series(bars, Timeframe.DAY)
    assert report.count(IssueKind.GAP) == 3


def test_out_of_order_bar_is_reported() -> None:
    """时序倒退的 K 线应被报出。"""
    bars = [make_bar(index=2), make_bar(index=0)]
    report = validate_bar_series(bars, Timeframe.DAY)
    assert report.count(IssueKind.OUT_OF_ORDER) == 1


def test_wrong_timeframe_is_reported() -> None:
    """周期不匹配的 K 线应被报出。"""
    bars = [make_bar(index=0, timeframe=Timeframe.WEEK)]
    report = validate_bar_series(bars, Timeframe.DAY)
    assert report.count(IssueKind.OUT_OF_ORDER) == 1


def test_empty_series_is_clean_but_empty() -> None:
    """空序列应无问题，但根数为零。"""
    report = validate_bar_series([], Timeframe.DAY)
    assert report.is_clean
    assert report.bar_count == 0


def test_summary_contains_every_counter() -> None:
    """摘要应包含各项计数。"""
    report = validate_bar_series([make_bar(index=0)], Timeframe.DAY)
    summary = report.summary()
    assert "timeframe=DAY" in summary
    assert "DUPLICATE=0" in summary


def test_gap_reports_are_capped() -> None:
    """缺口枚举必须有上限，超出部分只计数，避免异常数据撑爆内存。"""
    bars = [make_bar(index=0), make_bar(index=200)]
    report = validate_bar_series(bars, Timeframe.DAY, max_gap_reports=5)
    assert report.count(IssueKind.GAP) == 5
    assert report.gaps_suppressed == 194
    assert "gaps_suppressed=194" in report.summary()
