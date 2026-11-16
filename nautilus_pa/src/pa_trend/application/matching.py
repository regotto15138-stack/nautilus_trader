"""人工标注与程序输出的差异匹配（SACW 第 7 章）。

实现三件事：

1. SwingPoint 一对一匹配：全局最小代价分配（匈牙利算法），禁止贪心；
2. NStructure 匹配：四个锚点全部匹配且顺序一致才算候选；
3. Zone 匹配：锚点精度/召回与中心、边界、宽度误差。

匹配参数属于 ``matcher_version``，与策略参数分开管理（SACW 7.1）。本模块
不修改任何价格或结构，只输出匹配关系与误差指标。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Any

#: 无法匹配的代价哨兵；必须严格大于任何合法匹配代价。
_FORBIDDEN = 1e9


class MatchType(StrEnum):
    """SwingPoint 匹配结果类型（SACW 7.2）。"""

    MATCHED = "MATCHED"
    HUMAN_ONLY = "HUMAN_ONLY"
    PROGRAM_ONLY = "PROGRAM_ONLY"
    AMBIGUOUS_MATCH = "AMBIGUOUS_MATCH"


class StructureMatch(StrEnum):
    """NStructure 匹配结果类型（SACW 7.3）。"""

    EXACT_MATCH = "EXACT_MATCH"
    ANCHOR_MISMATCH = "ANCHOR_MISMATCH"
    CONFIRMATION_TIME_MISMATCH = "CONFIRMATION_TIME_MISMATCH"
    STATUS_MISMATCH = "STATUS_MISMATCH"
    HUMAN_ONLY = "HUMAN_ONLY"
    PROGRAM_ONLY = "PROGRAM_ONLY"


@dataclass(frozen=True, slots=True)
class MatcherConfig:
    """匹配容差与权重（属于 ``matcher_version``，不是 ZigZag 参数）。"""

    matcher_version: str = "matcher-1.0.0"
    max_time_tolerance_bars: int = 1
    max_price_tolerance_atr: Decimal = Decimal("0.25")
    ambiguity_epsilon: float = 0.05
    #: SACW 27.4 明确 ``w_c = 0.00``：确认延迟只进诊断，不进主代价。
    weight_time: float = 0.5
    weight_price: float = 0.5
    weight_confirmation: float = 0.0
    structure_confirmation_tolerance_bars: int = 1

    def __post_init__(self) -> None:
        """校验容差合法性。"""
        if self.max_time_tolerance_bars < 0:
            raise ValueError("max_time_tolerance_bars must be >= 0")
        if self.max_price_tolerance_atr < 0:
            raise ValueError("max_price_tolerance_atr must be >= 0")
        if self.weight_confirmation != 0.0:
            raise ValueError(
                "SACW 27.4 fixes w_c = 0.00; confirmation delay must stay diagnostic only",
            )


@dataclass(frozen=True, slots=True)
class SwingCandidate:
    """参与匹配的摆动点（人工或程序）。"""

    swing_id: str
    timeframe: str
    direction: str
    price: Decimal
    occurred_at_ns: int
    confirmed_at_ns: int
    atr_snapshot: Decimal | None = None


@dataclass(slots=True)
class SwingMatch:
    """一对一人匹配结果。"""

    human_id: str | None
    program_id: str | None
    match_type: MatchType
    cost: float | None = None
    time_error_bars: float | None = None
    price_error_atr: float | None = None
    confirmation_delay_bars: float | None = None
    errors: tuple[str, ...] = ()


@dataclass(slots=True)
class SwingMatchReport:
    """SwingPoint 匹配汇总。"""

    matcher_version: str
    matches: list[SwingMatch] = field(default_factory=list)
    human_count: int = 0
    program_count: int = 0

    @property
    def matched(self) -> int:
        """匹配成功的对数（含 AMBIGUOUS）。"""
        return sum(
            1
            for match in self.matches
            if match.match_type in {MatchType.MATCHED, MatchType.AMBIGUOUS_MATCH}
        )

    @property
    def ambiguous(self) -> int:
        """存在多种近似匹配、需要复核的对数。"""
        return sum(1 for match in self.matches if match.match_type is MatchType.AMBIGUOUS_MATCH)

    @property
    def precision(self) -> float:
        """精确率：匹配数 / 程序输出数。"""
        return 0.0 if self.program_count == 0 else self.matched / self.program_count

    @property
    def recall(self) -> float:
        """召回率：匹配数 / 人工标注数。"""
        return 0.0 if self.human_count == 0 else self.matched / self.human_count

    def as_dict(self) -> dict[str, Any]:
        """转成可序列化字典。"""
        return {
            "matcher_version": self.matcher_version,
            "human_count": self.human_count,
            "program_count": self.program_count,
            "matched": self.matched,
            "ambiguous": self.ambiguous,
            "precision": self.precision,
            "recall": self.recall,
            "matches": [
                {
                    "human_id": match.human_id,
                    "program_id": match.program_id,
                    "match_type": match.match_type.value,
                    "cost": match.cost,
                    "time_error_bars": match.time_error_bars,
                    "price_error_atr": match.price_error_atr,
                    "confirmation_delay_bars": match.confirmation_delay_bars,
                    "errors": list(match.errors),
                }
                for match in self.matches
            ],
        }


def hungarian(cost: list[list[float]]) -> list[int]:
    """求解方阵的最小代价分配（Kuhn-Munkres / JV 变体）。

    参数
    ----
    cost : list of list of float
        方阵代价矩阵；``_FORBIDDEN`` 表示禁止连边。

    返回
    ----
    list of int
        ``assignment[row] = column``。
    """
    n = len(cost)
    if n == 0:
        return []
    if any(len(row) != n for row in cost):
        raise ValueError("hungarian requires a square cost matrix")

    u = [0.0] * (n + 1)
    v = [0.0] * (n + 1)
    p = [0] * (n + 1)
    way = [0] * (n + 1)

    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [float("inf")] * (n + 1)
        used = [False] * (n + 1)
        while True:
            used[j0] = True
            i0 = p[j0]
            delta = float("inf")
            j1 = 0
            for j in range(1, n + 1):
                if used[j]:
                    continue
                current = cost[i0 - 1][j - 1] - u[i0] - v[j]
                if current < minv[j]:
                    minv[j] = current
                    way[j] = j0
                if minv[j] < delta:
                    delta = minv[j]
                    j1 = j
            for j in range(n + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break

    assignment = [-1] * n
    for j in range(1, n + 1):
        if p[j] > 0:
            assignment[p[j] - 1] = j - 1
    return assignment


def _price_error_atr(
    human: SwingCandidate,
    program: SwingCandidate,
    reference_atr: Decimal | None,
) -> float | None:
    atr = reference_atr or human.atr_snapshot or program.atr_snapshot
    if atr is None or atr <= 0:
        return None
    return float(abs(program.price - human.price) / atr)


def _pair_cost(
    human: SwingCandidate,
    program: SwingCandidate,
    *,
    timeframe_duration_ns: int,
    reference_atr: Decimal | None,
    config: MatcherConfig,
) -> tuple[float, float, float | None, float] | None:
    """返回 ``(cost, time_error_bars, price_error_atr, confirmation_delay_bars)``。

    超出容差时返回 ``None``（不连边）。
    """
    if human.timeframe != program.timeframe:
        return None
    if human.direction != program.direction:
        return None
    if timeframe_duration_ns <= 0:
        raise ValueError("timeframe_duration_ns must be positive")

    time_error_ns = abs(program.occurred_at_ns - human.occurred_at_ns)
    time_error_bars = time_error_ns / timeframe_duration_ns
    if time_error_bars > config.max_time_tolerance_bars:
        return None

    price_error_atr = _price_error_atr(human, program, reference_atr)
    if price_error_atr is None:
        return None
    if Decimal(str(price_error_atr)) > config.max_price_tolerance_atr:
        return None

    confirmation_delay_bars = (
        program.confirmed_at_ns - human.confirmed_at_ns
    ) / timeframe_duration_ns

    time_limit = max(1, config.max_time_tolerance_bars)
    price_limit = float(config.max_price_tolerance_atr) or 1.0
    cost = (
        config.weight_time * (time_error_bars / time_limit)
        + config.weight_price * (price_error_atr / price_limit)
        + config.weight_confirmation * (abs(confirmation_delay_bars) / time_limit)
    )
    return cost, time_error_bars, price_error_atr, confirmation_delay_bars


def _decimal_text(value: Decimal) -> str:
    """把 Decimal 渲染成不带指数的定点文本（``0E-8`` → ``0``）。"""
    return format(value, "f")


def match_swings(
    human: Sequence[SwingCandidate],
    program: Sequence[SwingCandidate],
    *,
    timeframe_duration_ns: int,
    reference_atr: Decimal | None = None,
    config: MatcherConfig | None = None,
) -> SwingMatchReport:
    """用全局最小代价分配匹配人工与程序 SwingPoint（SACW 7.2）。

    只按最近价格贪心会跨对误配，因此这里对全部合法边求解一次最小代价
    二分图匹配；未匹配项分别记为 ``HUMAN_ONLY`` 与 ``PROGRAM_ONLY``。
    """
    cfg = config or MatcherConfig()
    report = SwingMatchReport(matcher_version=cfg.matcher_version)
    report.human_count = len(human)
    report.program_count = len(program)

    if not human or not program:
        report.matches.extend(
            SwingMatch(human_id=item.swing_id, program_id=None, match_type=MatchType.HUMAN_ONLY)
            for item in human
        )
        report.matches.extend(
            SwingMatch(human_id=None, program_id=item.swing_id, match_type=MatchType.PROGRAM_ONLY)
            for item in program
        )
        return report

    size = max(len(human), len(program))
    matrix: list[list[float]] = []
    details: dict[tuple[int, int], tuple[float, float, float | None, float]] = {}
    for i in range(size):
        row: list[float] = []
        for j in range(size):
            if i >= len(human) or j >= len(program):
                row.append(_FORBIDDEN)
                continue
            pair = _pair_cost(
                human[i],
                program[j],
                timeframe_duration_ns=timeframe_duration_ns,
                reference_atr=reference_atr,
                config=cfg,
            )
            if pair is None:
                row.append(_FORBIDDEN)
            else:
                row.append(pair[0])
                details[(i, j)] = pair
        matrix.append(row)

    assignment = hungarian(matrix)
    matched_program: set[int] = set()
    matched_human: set[int] = set()

    for i, j in enumerate(assignment):
        if i >= len(human) or j < 0 or j >= len(program):
            continue
        if matrix[i][j] >= _FORBIDDEN:
            continue
        cost, time_error_bars, price_error_atr, delay = details[(i, j)]

        # 近似匹配检测：若换一个程序点得到的代价几乎相同，则需复核。
        alternatives = [
            matrix[i][other] - cost
            for other in range(size)
            if other != j and other < len(program) and matrix[i][other] < _FORBIDDEN
        ]
        ambiguous = bool(alternatives) and min(alternatives) <= cfg.ambiguity_epsilon

        report.matches.append(
            SwingMatch(
                human_id=human[i].swing_id,
                program_id=program[j].swing_id,
                match_type=MatchType.AMBIGUOUS_MATCH if ambiguous else MatchType.MATCHED,
                cost=cost,
                time_error_bars=time_error_bars,
                price_error_atr=price_error_atr,
                confirmation_delay_bars=delay,
            ),
        )
        matched_human.add(i)
        matched_program.add(j)

    for i, item in enumerate(human):
        if i not in matched_human:
            report.matches.append(
                SwingMatch(
                    human_id=item.swing_id,
                    program_id=None,
                    match_type=MatchType.HUMAN_ONLY,
                ),
            )
    for j, item in enumerate(program):
        if j not in matched_program:
            report.matches.append(
                SwingMatch(
                    human_id=None,
                    program_id=item.swing_id,
                    match_type=MatchType.PROGRAM_ONLY,
                ),
            )
    return report


def match_n_structures(
    human: Sequence[dict[str, Any]],
    program: Sequence[dict[str, Any]],
    *,
    swing_mapping: dict[str, str],
    config: MatcherConfig | None = None,
    timeframe_duration_ns: int | None = None,
) -> dict[str, Any]:
    """匹配 NStructure（SACW 7.3）。

    参数
    ----
    human : sequence of dict
        人工结构，键为 ``structure_id``、``l1``、``h1``、``l2``、``h2``、
        ``confirmed_at_ns``、``status``。
    program : sequence of dict
        程序结构，键同上。
    swing_mapping : dict
        人工 SwingPoint ID → 程序 SwingPoint ID 的匹配映射。
    config : MatcherConfig 或 None
        匹配容差。
    timeframe_duration_ns : int 或 None
        结构确认时间容差换算用；缺省时不做时间比较。

    返回
    ----
    dict
        含 ``results`` 与汇总计数。
    """
    cfg = config or MatcherConfig()
    results: list[dict[str, Any]] = []
    used_program: set[str] = set()

    for item in human:
        anchor_ids = [str(item[key]) for key in ("l1", "h1", "l2", "h2")]
        # 未提供映射时退化为同名锚点比较（例如人工直接引用程序 swing_id）。
        mapped = [swing_mapping.get(anchor_id, anchor_id) for anchor_id in anchor_ids]
        candidates = [
            candidate
            for candidate in program
            if candidate["structure_id"] not in used_program
            and [candidate[key] for key in ("l1", "h1", "l2", "h2")] == mapped
        ]
        if not candidates:
            results.append(
                {
                    "human_id": item["structure_id"],
                    "program_id": None,
                    "match": StructureMatch.HUMAN_ONLY.value,
                    "errors": ["no program structure with the same mapped anchors"],
                },
            )
            continue

        candidate = candidates[0]
        errors: list[str] = []
        match_type = StructureMatch.EXACT_MATCH

        if timeframe_duration_ns:
            tolerance = cfg.structure_confirmation_tolerance_bars * timeframe_duration_ns
            delta = abs(candidate["confirmed_at_ns"] - item["confirmed_at_ns"])
            if delta > tolerance:
                match_type = StructureMatch.CONFIRMATION_TIME_MISMATCH
                errors.append(f"confirmation_time_delta_ns={delta}")

        same_status = candidate.get("status") == item.get("status")
        if match_type is StructureMatch.EXACT_MATCH and not same_status:
            match_type = StructureMatch.STATUS_MISMATCH
            errors.append(f"status human={item.get('status')} program={candidate.get('status')}")

        used_program.add(candidate["structure_id"])
        results.append(
            {
                "human_id": item["structure_id"],
                "program_id": candidate["structure_id"],
                "match": match_type.value,
                "errors": errors,
            },
        )

    for candidate in program:
        if candidate["structure_id"] in used_program:
            continue
        results.append(
            {
                "human_id": None,
                "program_id": candidate["structure_id"],
                "match": StructureMatch.PROGRAM_ONLY.value,
                "errors": [],
            },
        )

    return {
        "matcher_version": cfg.matcher_version,
        "human_count": len(human),
        "program_count": len(program),
        "results": results,
    }


def match_zones(
    human: Sequence[dict[str, Any]],
    program: Sequence[dict[str, Any]],
    *,
    swing_mapping: dict[str, str] | None = None,
) -> dict[str, Any]:
    """匹配 Zone（SACW 7.4）。

    人工只提供锚点时，以锚点匹配为主，**不得**把人工未提供的边界当成
    Ground Truth；只有人工显式给出 ``HUMAN_BOUNDARY`` 时才比较边界误差。
    """
    mapping = swing_mapping or {}
    results: list[dict[str, Any]] = []
    used: set[str] = set()

    for item in human:
        human_anchors = {mapping.get(str(a), str(a)) for a in item.get("anchor_swing_ids", [])}
        best: dict[str, Any] | None = None
        best_overlap = 0
        for candidate in program:
            if candidate["zone_id"] in used:
                continue
            if candidate.get("zone_type") != item.get("zone_type"):
                continue
            program_anchors = {str(a) for a in candidate.get("anchor_swing_ids", [])}
            overlap = len(human_anchors & program_anchors)
            if overlap > best_overlap:
                best_overlap = overlap
                best = candidate

        if best is None:
            results.append(
                {
                    "human_id": item.get("zone_id") or item.get("annotation_id"),
                    "program_id": None,
                    "match": "HUMAN_ONLY",
                    "metrics": {},
                },
            )
            continue

        used.add(best["zone_id"])
        program_anchors = {str(a) for a in best.get("anchor_swing_ids", [])}
        precision = 1.0 if not program_anchors else best_overlap / len(program_anchors)
        recall = 1.0 if not human_anchors else best_overlap / len(human_anchors)

        metrics: dict[str, Any] = {
            "anchor_precision": precision,
            "anchor_recall": recall,
        }
        mode = item.get("annotation_mode", "ANCHOR_ONLY")
        metrics["annotation_mode"] = mode
        if mode in {"HUMAN_BOUNDARY"} and item.get("human_center") is not None:
            human_center = Decimal(str(item["human_center"]))
            human_width = Decimal(str(item["human_upper"])) - Decimal(str(item["human_lower"]))
            program_center = Decimal(str(best["center"]))
            program_width = Decimal(str(best["upper"])) - Decimal(str(best["lower"]))
            metrics.update(
                {
                    "center_error": _decimal_text(abs(program_center - human_center)),
                    "lower_error": _decimal_text(
                        abs(Decimal(str(best["lower"])) - Decimal(str(item["human_lower"]))),
                    ),
                    "upper_error": _decimal_text(
                        abs(Decimal(str(best["upper"])) - Decimal(str(item["human_upper"]))),
                    ),
                    "width_ratio": None
                    if human_width == 0
                    else _decimal_text(program_width / human_width),
                },
            )
        elif item.get("center") is not None and best.get("center") is not None:
            # ANCHOR_ONLY：双方都按同一配置计算，因此边界应完全一致。
            metrics["center_error"] = _decimal_text(
                abs(Decimal(str(best["center"])) - Decimal(str(item["center"]))),
            )

        results.append(
            {
                "human_id": item.get("zone_id") or item.get("annotation_id"),
                "program_id": best["zone_id"],
                "match": "MATCHED",
                "metrics": metrics,
            },
        )

    for candidate in program:
        if candidate["zone_id"] in used:
            continue
        results.append(
            {
                "human_id": None,
                "program_id": candidate["zone_id"],
                "match": "PROGRAM_ONLY",
                "metrics": {},
            },
        )

    return {
        "human_count": len(human),
        "program_count": len(program),
        "results": results,
    }


def match_state_intervals(
    human: Sequence[dict[str, Any]],
    program: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    """按状态与时间重叠匹配人工/程序状态区间（SACW 7.5 的基础版）。

    先匹配同状态且时间重叠最大的区间；没有重叠的分别记为 HUMAN_ONLY /
    PROGRAM_ONLY。该函数不计算 Macro-F1，逐 Bar 混淆矩阵需要额外 Bar 序列。
    """
    results: list[dict[str, Any]] = []
    used: set[str] = set()
    for item in human:
        best: dict[str, Any] | None = None
        best_overlap = 0
        for candidate in program:
            if candidate["interval_id"] in used:
                continue
            if candidate.get("state") != item.get("state"):
                continue
            overlap = min(int(item["valid_to_ns"]), int(candidate["valid_to_ns"])) - max(
                int(item["valid_from_ns"]),
                int(candidate["valid_from_ns"]),
            )
            if overlap > best_overlap:
                best_overlap = overlap
                best = candidate
        if best is None:
            results.append(
                {
                    "human_id": item.get("interval_id") or item.get("annotation_id"),
                    "program_id": None,
                    "match": "HUMAN_ONLY",
                    "metrics": {},
                },
            )
            continue
        used.add(best["interval_id"])
        results.append(
            {
                "human_id": item.get("interval_id") or item.get("annotation_id"),
                "program_id": best["interval_id"],
                "match": "MATCHED",
                "metrics": {
                    "overlap_seconds": round(best_overlap / 1_000_000_000, 3),
                    "start_delta_seconds": round(
                        abs(int(item["valid_from_ns"]) - int(best["valid_from_ns"])) / 1e9,
                        3,
                    ),
                    "end_delta_seconds": round(
                        abs(int(item["valid_to_ns"]) - int(best["valid_to_ns"])) / 1e9,
                        3,
                    ),
                },
            },
        )
    for candidate in program:
        if candidate["interval_id"] in used:
            continue
        results.append(
            {
                "human_id": None,
                "program_id": candidate["interval_id"],
                "match": "PROGRAM_ONLY",
                "metrics": {},
            },
        )
    return {
        "human_count": len(human),
        "program_count": len(program),
        "results": results,
    }
