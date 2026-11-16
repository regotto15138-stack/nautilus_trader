"""行情数据质量检查（规格第 1.5 节的验证清单）。"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from pa_trend.domain.models.bar import Bar
from pa_trend.domain.models.timeframe import Timeframe, next_close_ns

# 单个连续性缺口最多枚举多少期，避免异常数据导致内存与时延失控。
_MAX_GAP_SCAN = 100_000


class IssueKind(StrEnum):
    """数据质量问题的分类。"""

    DUPLICATE = "DUPLICATE"
    OUT_OF_ORDER = "OUT_OF_ORDER"
    GAP = "GAP"


@dataclass(frozen=True, slots=True)
class DataIssue:
    """单个已检出的问题。

    属性
    ----
    kind : IssueKind
        问题分类。
    detail : str
        含相关时间戳的可读描述。
    """

    kind: IssueKind
    detail: str


@dataclass(slots=True)
class DataQualityReport:
    """单个 K 线序列的聚合质量结果。

    属性
    ----
    timeframe : Timeframe
        被检查的周期。
    bar_count : int
        检查的 K 线根数。
    issues : list of DataIssue
        按发现顺序记录的每个问题。
    gaps_suppressed : int
        因超出枚举上限而未逐条记录的缺口数量。
    """

    timeframe: Timeframe
    bar_count: int
    issues: list[DataIssue] = field(default_factory=list)
    gaps_suppressed: int = 0

    @property
    def is_clean(self) -> bool:
        """是否未发现任何问题。"""
        return not self.issues

    def count(self, kind: IssueKind) -> int:
        """返回 ``kind`` 类问题的条数。"""
        return sum(1 for issue in self.issues if issue.kind is kind)

    def summary(self) -> str:
        """返回适合报表的一行摘要。"""
        parts = [f"{kind.value}={self.count(kind)}" for kind in IssueKind]
        text = (
            f"timeframe={self.timeframe.name} bars={self.bar_count} "
            f"clean={self.is_clean} " + " ".join(parts)
        )
        if self.gaps_suppressed:
            text += f" gaps_suppressed={self.gaps_suppressed}"
        return text


def validate_bar_series(
    bars: Sequence[Bar],
    timeframe: Timeframe,
    *,
    max_gap_reports: int = 1_000,
) -> DataQualityReport:
    """检查顺序、重复与日历缺口。

    单根 K 线的 OHLCV 不变量已由 :class:`Bar` 构造函数保证，因此只要 K 线存在，
    其结构就是有效的。

    参数
    ----
    bars : Sequence of Bar
        期望按时间正序排列的 K 线。
    timeframe : Timeframe
        序列声称的周期。
    max_gap_reports : int
        逐条记录的缺口上限；超出部分只计数、不再分配对象，避免异常数据撑爆内存。

    返回
    ----
    DataQualityReport
        报告对象；通过 :attr:`DataQualityReport.issues` 查看问题。
    """
    report = DataQualityReport(timeframe=timeframe, bar_count=len(bars))
    if not bars:
        return report

    seen: set[int] = set()
    previous: Bar | None = None
    reported_gaps = 0

    for bar in bars:
        if bar.timeframe is not timeframe:
            report.issues.append(
                DataIssue(
                    kind=IssueKind.OUT_OF_ORDER,
                    detail=f"bar {bar.bar_id} has timeframe {bar.timeframe}, expected {timeframe}",
                ),
            )
            continue

        if bar.ts_close_ns in seen:
            report.issues.append(
                DataIssue(
                    kind=IssueKind.DUPLICATE,
                    detail=f"duplicate close timestamp {bar.ts_close_ns}",
                ),
            )
            continue
        seen.add(bar.ts_close_ns)

        if previous is not None:
            if bar.ts_close_ns < previous.ts_close_ns:
                report.issues.append(
                    DataIssue(
                        kind=IssueKind.OUT_OF_ORDER,
                        detail=(
                            f"close {bar.ts_close_ns} precedes previous {previous.ts_close_ns}"
                        ),
                    ),
                )
            else:
                expected = next_close_ns(
                    previous.ts_close_ns,
                    timeframe,
                    session_offset_minutes=previous.session_offset_minutes,
                )
                # 逐期推进，确保每一个缺失周期都被枚举。
                scanned = 0
                while expected < bar.ts_close_ns:
                    if scanned >= _MAX_GAP_SCAN:
                        report.gaps_suppressed += 1
                        break
                    scanned += 1
                    if reported_gaps < max_gap_reports:
                        report.issues.append(
                            DataIssue(
                                kind=IssueKind.GAP,
                                detail=f"missing bar closing at {expected}",
                            ),
                        )
                        reported_gaps += 1
                    else:
                        report.gaps_suppressed += 1
                    expected = next_close_ns(
                        expected,
                        timeframe,
                        session_offset_minutes=previous.session_offset_minutes,
                    )

        previous = bar

    return report
