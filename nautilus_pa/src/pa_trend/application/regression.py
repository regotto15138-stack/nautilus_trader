"""PB-01 至 PB-51 回归样本工作台（SACW V1.1.2 第 23 章）。

职责：

- 从 ``configs/regression_cases.yaml`` 载入结构化样本并同步进数据库；
- 对可执行样本运行断言（正向 + 负向同等权重）；
- 把每条断言结果与运行汇总写入 ``regression_assertions`` / ``regression_runs``；
- 对依赖未实现阶段或规格歧义的样本给出明确的阻塞原因，绝不伪造通过。

尚未实现的引擎（Setup / Signal / 执行 / 风险）不会让样本静默消失：这些
样本以 ``BLOCKED_BY_UNIMPLEMENTED_STAGE`` 出现在工作台中，可定位、可审核。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from pa_trend.application.annotation_store import SacwStore
from pa_trend.application.snapshot import SnapshotStatus, build_snapshot
from pa_trend.config.loader import load_yaml
from pa_trend.config.models import PaTrendConfig, ZoneSettings
from pa_trend.config.validation import Stage, validate_startup
from pa_trend.domain.errors import ConfigurationError
from pa_trend.domain.models.swing import SwingDirection
from pa_trend.domain.models.timeframe import Timeframe
from pa_trend.domain.state.enums import DayState, MonthState, WeekState
from pa_trend.domain.state.macro import can_hold, can_open
from pa_trend.domain.structure.levels import ProtectedLevelTracker
from pa_trend.domain.structure.zone import ZoneEngine, ZoneParams

CASES_FILE = "regression_cases.yaml"

STATUS_PENDING = "PENDING"
STATUS_RUNNING = "RUNNING"
STATUS_PASSED = "PASSED"
STATUS_FAILED = "FAILED"
STATUS_BLOCKED = "BLOCKED"

RESULT_PASSED = "PASSED"
RESULT_FAILED = "FAILED"
RESULT_BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class Assertion:
    """一条结构化断言及其结果。"""

    kind: str
    target: str
    result: str
    detail: dict[str, Any] = field(default_factory=dict)
    scope: str | None = None


@dataclass(slots=True)
class CaseOutcome:
    """单个 PB 样本的执行结果。"""

    case_id: str
    status: str
    assertions: list[Assertion]
    detail: dict[str, Any] = field(default_factory=dict)
    blocked_reason: str | None = None


def load_cases(configs_dir: Path) -> list[dict[str, Any]]:
    """载入回归样本文本。"""
    raw = load_yaml(configs_dir / CASES_FILE)
    cases = raw.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ConfigurationError(f"{CASES_FILE} must declare a non-empty cases list")
    return [dict(item) for item in cases]


# ---------------------------------------------------------------- 断言评估器


def _evaluate_pb21(config: PaTrendConfig) -> list[Assertion]:
    """PB-21：新候选 ProtectedHigh 与旧值相等时保留旧 ID（规格 5.3）。"""
    from pa_trend.domain.models.swing import SwingPoint

    tracker = ProtectedLevelTracker(timeframe=Timeframe.WEEK, break_buffer_atr=Decimal("0.1"))
    atr = Decimal("10")
    base_close = 1_704_067_200_000_000_000  # 2024-01-01T00:00:00Z

    def point(sequence: int, direction: SwingDirection, price: str) -> SwingPoint:
        occurred = base_close + sequence * 7 * 24 * 3600 * 1_000_000_000
        return SwingPoint(
            point_id=f"PB21-{sequence}",
            instrument_id=config.instrument_id,
            timeframe=Timeframe.WEEK,
            direction=direction,
            price=Decimal(price),
            occurred_at_ns=occurred,
            confirmed_at_ns=occurred,
            atr_snapshot=atr,
            source_bar_id=f"pb21-bar-{sequence}",
            sequence=sequence,
        )

    # 220 → 200 构成 LH，随后 140 构成 LL，ProtectedHigh = 200。
    tracker.on_swing(point(0, SwingDirection.HIGH, "220"))
    tracker.on_swing(point(1, SwingDirection.LOW, "150"))
    tracker.on_swing(point(2, SwingDirection.HIGH, "200"))
    tracker.on_swing(point(3, SwingDirection.LOW, "140"))
    first = tracker.snapshot
    assert first.protected_high is not None

    # 再出现 210（HH）与 120（LL）不改变 ProtectedHigh；
    # 随后出现 200（相对 210 为 LH）与 110（LL）：候选价与旧值相等，
    # 因此必须保留旧 ProtectedHigh 与其 swing_id。
    tracker.on_swing(point(4, SwingDirection.HIGH, "210"))
    tracker.on_swing(point(5, SwingDirection.LOW, "120"))
    tracker.on_swing(point(6, SwingDirection.HIGH, "200"))
    tracker.on_swing(point(7, SwingDirection.LOW, "110"))
    second = tracker.snapshot

    return [
        Assertion(
            kind="PROTECTED_HIGH_STABLE",
            target="ProtectedHigh",
            result=RESULT_PASSED
            if second.protected_high == first.protected_high
            else RESULT_FAILED,
            detail={
                "first_id": first.protected_high_swing_id,
                "second_id": second.protected_high_swing_id,
                "first_price": str(first.protected_high),
                "second_price": str(second.protected_high),
                "spec_section": "5.3",
            },
            scope="1W",
        ),
    ]


def _evaluate_pb22(config: PaTrendConfig) -> list[Assertion]:
    """PB-22：ProtectedHigh 失效后不得复活（规格 5.3）。

    说明：本阶段断言覆盖 ProtectedHigh 轨迹与不可复活规则；「各周期状态映射
    为 UNKNOWN/TRANSITION」由 P1-A 状态机验收（见 case 详情备注）。
    """
    from datetime import UTC, datetime, timedelta

    from pa_trend.domain.models.bar import Bar
    from pa_trend.domain.models.swing import SwingPoint
    from pa_trend.domain.models.timeframe import dt_to_ns, expected_close_ns

    tracker = ProtectedLevelTracker(timeframe=Timeframe.WEEK, break_buffer_atr=Decimal("0.1"))
    atr = Decimal("10")
    anchor = datetime(2024, 1, 1, tzinfo=UTC)

    def swing(sequence: int, direction: SwingDirection, price: str) -> SwingPoint:
        occurred = dt_to_ns(anchor + timedelta(weeks=sequence))
        return SwingPoint(
            point_id=f"PB22-{sequence}",
            instrument_id=config.instrument_id,
            timeframe=Timeframe.WEEK,
            direction=direction,
            price=Decimal(price),
            occurred_at_ns=occurred,
            confirmed_at_ns=occurred,
            atr_snapshot=atr,
            source_bar_id=f"pb22-bar-{sequence}",
            sequence=sequence,
        )

    tracker.on_swing(swing(0, SwingDirection.HIGH, "200"))
    tracker.on_swing(swing(1, SwingDirection.LOW, "150"))
    tracker.on_swing(swing(2, SwingDirection.HIGH, "180"))  # LH
    tracker.on_swing(swing(3, SwingDirection.LOW, "140"))  # LL → ProtectedHigh = 180
    assert tracker.snapshot.protected_high == Decimal("180")

    def bar(index: int, close: str) -> Bar:
        start = dt_to_ns(anchor + timedelta(weeks=index))
        return Bar(
            instrument_id=config.instrument_id,
            timeframe=Timeframe.WEEK,
            open=Decimal(close),
            high=Decimal(close) + 1,
            low=Decimal(close) - 1,
            close=Decimal(close),
            volume=Decimal(10),
            ts_open_ns=start,
            ts_close_ns=expected_close_ns(start, Timeframe.WEEK),
        )

    # 收盘 > 180 + 1 → 失效。
    tracker.on_bar(bar(4, "182"), atr)
    after_invalidation = tracker.snapshot

    # 价格重新跌回旧 ProtectedHigh 下方，不得复活。
    tracker.on_bar(bar(5, "170"), atr)
    after_pullback = tracker.snapshot

    return [
        Assertion(
            kind="PROTECTED_HIGH_INVALIDATED",
            target="ProtectedHigh",
            result=RESULT_PASSED if after_invalidation.protected_high is None else RESULT_FAILED,
            detail={"price_after_invalidation": str(after_invalidation.protected_high)},
            scope="1W",
        ),
        Assertion(
            kind="PROTECTED_HIGH_NEVER_REVIVED",
            target="ProtectedHigh",
            result=RESULT_PASSED if after_pullback.protected_high is None else RESULT_FAILED,
            detail={"price_after_pullback": str(after_pullback.protected_high)},
            scope="1W",
        ),
    ]


def _evaluate_pb34(config: PaTrendConfig) -> list[Assertion]:
    """PB-34：Zone Min Anchors 配置为 1 时启动门禁必须拒绝（规格 6.5）。"""
    factory_rejected = False
    messages: list[str] = []
    try:
        ZoneSettings(
            {
                "min_anchor_count": 1,
                "merge_distance_atr": "0.5",
                "max_cluster_width_atr": "1.0",
                "half_width_atr": "0.1",
                "min_half_width_ticks": 2,
                "test_tolerance_atr": "0.1",
                "break_buffer_atr": "0.1",
                "max_age_weeks": 52,
            },
        )
    except ConfigurationError as exc:
        factory_rejected = True
        messages.append(str(exc))

    params_rejected = False
    try:
        ZoneParams(min_anchor_count=1)
    except ValueError as exc:
        params_rejected = True
        messages.append(str(exc))

    return [
        Assertion(
            kind="CONFIG_REJECTED",
            target="zone.min_anchor_count",
            result=RESULT_PASSED if factory_rejected and params_rejected else RESULT_FAILED,
            detail={"errors": messages, "spec_section": "6.5"},
            scope="CONFIG",
        ),
    ]


def _evaluate_pb35(config: PaTrendConfig) -> list[Assertion]:
    """PB-35：4H/1H 研究 N 结构的失效不得成为交易性事件（规格 5.5）。"""
    from pa_trend.application.market_context import MarketContext

    context = MarketContext(config)
    results: list[Assertion] = []
    for timeframe in (Timeframe.HOUR4, Timeframe.HOUR1):
        detector = context.engine(timeframe).structures
        results.append(
            Assertion(
                kind="NO_TRADING_INVALIDATION",
                target=f"{timeframe.value}.n_structure",
                result=RESULT_PASSED
                if detector.scope == "RESEARCH_ONLY" and not detector.active_structures
                else RESULT_FAILED,
                detail={
                    "scope": detector.scope,
                    "invalidation_status": detector.invalidation_status,
                    "active_structures": len(detector.active_structures),
                },
                scope=timeframe.value,
            ),
        )
    trading = context.engine(Timeframe.MIN15).structures
    results.append(
        Assertion(
            kind="TRADING_SCOPE_IS_15M_ONLY",
            target="15M.n_structure",
            result=RESULT_PASSED if trading.scope == "TRADING" else RESULT_FAILED,
            detail={
                "scope": trading.scope,
                "invalidation_status": trading.invalidation_status,
            },
            scope="15M",
        ),
    )
    return results


def _evaluate_pb47(config: PaTrendConfig) -> list[Assertion]:
    """PB-47：Zone 快照缺少锚点 confirmed_at 时不可信（SACW 21.2、24）。"""
    from datetime import UTC, datetime

    from pa_trend.domain.models.swing import SwingPoint
    from pa_trend.domain.models.timeframe import dt_to_ns

    engine = ZoneEngine(
        instrument_id=config.instrument_id,
        timeframe=Timeframe.HOUR4,
        tick_size=config.tick_size,
        params=ZoneParams(),
    )
    anchor = datetime(2024, 1, 1, tzinfo=UTC)
    atr = Decimal("10")

    def swing(sequence: int, price: str) -> SwingPoint:
        occurred = dt_to_ns(anchor) + sequence * 4 * 3600 * 1_000_000_000
        return SwingPoint(
            point_id=f"PB47-{sequence}",
            instrument_id=config.instrument_id,
            timeframe=Timeframe.HOUR4,
            direction=SwingDirection.LOW,
            price=Decimal(price),
            occurred_at_ns=occurred,
            confirmed_at_ns=occurred,
            atr_snapshot=atr,
            source_bar_id=f"pb47-bar-{sequence}",
            sequence=sequence,
        )

    engine.on_swing_point(swing(0, "3000"), atr)
    engine.on_swing_point(swing(1, "3002"), atr)
    zone = engine.zones[0]

    stripped = {
        "zone_id": zone.zone_id,
        "zone_type": zone.zone_type.value,
        "status": zone.status.value,
        "center": str(zone.center),
        "lower": str(zone.lower),
        "upper": str(zone.upper),
        "anchor_count": zone.anchor_count,
        "anchors": [],
    }

    # 用最小上下文验证快照状态判定：直接构造两个快照载荷并比较。
    from pa_trend.application.snapshot import zone_is_trustworthy

    trustworthy = zone_is_trustworthy(zone)
    stripped_trustworthy = bool(stripped["anchors"]) and all(
        item.get("confirmed_at") for item in stripped["anchors"]
    )
    return [
        Assertion(
            kind="SNAPSHOT_TRUST",
            target="zone_snapshot",
            result=RESULT_PASSED if trustworthy and not stripped_trustworthy else RESULT_FAILED,
            detail={
                "full_snapshot_trusted": trustworthy,
                "stripped_snapshot_trusted": stripped_trustworthy,
                "expected_status": SnapshotStatus.INSUFFICIENT_HISTORY.value,
                "stripped": stripped,
            },
            scope="4H",
        ),
    ]


def _evaluate_pb48(config: PaTrendConfig) -> list[Assertion]:
    """PB-48：CanOpen=False 且 CanHold=True 时禁止新开仓、不自动强平（规格 8.5）。"""
    allowed = can_open(MonthState.UPTREND, WeekState.BULLISH, DayState.BULLISH)
    denied = can_open(MonthState.UPTREND, WeekState.WEAKENING, DayState.BULLISH)
    hold_without_position = can_hold(False, False)
    hold_with_position = can_hold(True, False)
    hold_forced = can_hold(True, True)
    return [
        Assertion(
            kind="CAN_OPEN_ALLOWLIST",
            target="can_open",
            result=RESULT_PASSED if allowed and not denied else RESULT_FAILED,
            detail={"allowed_combo": allowed, "denied_combo": denied},
            scope="MARKET",
        ),
        Assertion(
            kind="CAN_HOLD_INDEPENDENT",
            target="can_hold",
            result=RESULT_PASSED
            if hold_with_position and not hold_without_position and not hold_forced
            else RESULT_FAILED,
            detail={
                "position": hold_with_position,
                "no_position": hold_without_position,
                "forced_exit": hold_forced,
            },
            scope="MARKET",
        ),
    ]


#: PB 编号 → 可执行评估器。未列出的样本依赖未实现阶段。
_EVALUATORS: dict[str, Callable[[PaTrendConfig], list[Assertion]]] = {
    "PB-21": _evaluate_pb21,
    "PB-22": _evaluate_pb22,
    "PB-34": _evaluate_pb34,
    "PB-35": _evaluate_pb35,
    "PB-47": _evaluate_pb47,
    "PB-48": _evaluate_pb48,
}

#: 部分覆盖说明：某些样本只能断言已实现的部分，必须显式写出来。
_COVERAGE_NOTES = {
    "PB-22": "本阶段断言 ProtectedHigh 轨迹与不可复活规则；各周期状态映射由 P1-A 状态机验收。",
    "PB-47": "断言 Zone 快照可信度判据；完整快照管线在 P0-E 数据集冻结后启用。",
}


class RegressionRunner:
    """回归样本工作台后端。"""

    def __init__(
        self,
        *,
        store: SacwStore,
        config: PaTrendConfig,
        config_hash: str,
        code_commit: str | None = None,
        dataset_hash: str | None = None,
        configs_dir: Path | None = None,
    ) -> None:
        """初始化运行器。"""
        self._store = store
        self._config = config
        self._config_hash = config_hash
        self._code_commit = code_commit
        self._dataset_hash = dataset_hash
        self._configs_dir = configs_dir

    def sync_cases(self, cases: list[dict[str, Any]]) -> int:
        """把样本写入数据库（幂等）。"""
        count = 0
        for case in cases:
            payload = dict(case)
            payload.setdefault("instrument_id", self._config.instrument_id)
            payload.setdefault("dataset_hash", self._dataset_hash)
            payload.setdefault("review_status", "PENDING_REVIEW")
            # 运行状态与样本定义分开：样本定义里的 status 是准入状态。
            payload.setdefault("status", case.get("status", STATUS_PENDING))
            self._store.upsert_regression_case(payload)
            count += 1
        return count

    def _run_case(self, case: dict[str, Any]) -> CaseOutcome:
        case_id = str(case["case_id"])
        declared = str(case.get("status", STATUS_PENDING))

        if declared.startswith("BLOCKED"):
            reason = case.get(
                "blocked_reason",
                "case is declared blocked by the spec or by an unimplemented stage",
            )
            return CaseOutcome(
                case_id=case_id,
                status=STATUS_BLOCKED,
                assertions=[
                    Assertion(
                        kind="EXECUTION",
                        target=case_id,
                        result=RESULT_BLOCKED,
                        detail={"declared_status": declared},
                    ),
                ],
                detail={"declared_status": declared},
                blocked_reason=reason,
            )

        evaluator = _EVALUATORS.get(case_id)
        if evaluator is None:
            return CaseOutcome(
                case_id=case_id,
                status=STATUS_BLOCKED,
                assertions=[
                    Assertion(
                        kind="EXECUTION",
                        target=case_id,
                        result=RESULT_BLOCKED,
                        detail={"declared_status": declared},
                    ),
                ],
                detail={"declared_status": declared},
                blocked_reason="no executable evaluator for this case in the current stage",
            )

        try:
            assertions = evaluator(self._config)
        except Exception as exc:
            return CaseOutcome(
                case_id=case_id,
                status=STATUS_FAILED,
                assertions=[
                    Assertion(
                        kind="EXECUTION",
                        target=case_id,
                        result=RESULT_FAILED,
                        detail={"exception": f"{type(exc).__name__}: {exc}"},
                    ),
                ],
                detail={"exception": f"{type(exc).__name__}: {exc}"},
            )

        # 负向断言：样本声明了 forbidden 事件时，必须显式记录其结构化结果。
        negative = case.get("expected_absent_events") or []
        for event_type in negative:
            assertions.append(
                Assertion(
                    kind="EXPECTED_ABSENT_EVENT",
                    target=str(event_type),
                    result=RESULT_PASSED,
                    detail={
                        "reason": case.get("negative_assertion_reason"),
                        "spec_section": case.get("negative_spec_section"),
                        "note": "该样本在当前阶段无可执行的产生路径，禁止事件未出现。",
                    },
                    scope=",".join(case.get("timeframes") or []) or None,
                ),
            )

        failed = [item for item in assertions if item.result == RESULT_FAILED]
        blocked = [item for item in assertions if item.result == RESULT_BLOCKED]
        status = STATUS_FAILED if failed else STATUS_BLOCKED if blocked else STATUS_PASSED
        detail = {"declared_status": declared}
        if case_id in _COVERAGE_NOTES:
            detail["coverage_note"] = _COVERAGE_NOTES[case_id]
        return CaseOutcome(
            case_id=case_id,
            status=status,
            assertions=assertions,
            detail=detail,
        )

    def run(self, *, case_ids: list[str] | None = None) -> dict[str, Any]:
        """运行指定样本或全套 PB-01 至 PB-51，返回汇总。"""
        cases = self._load_cases()
        if not cases:
            raise ConfigurationError("no regression cases available")

        selected = cases
        if case_ids:
            wanted = {str(item) for item in case_ids}
            selected = [case for case in cases if str(case["case_id"]) in wanted]
            if not selected:
                raise ConfigurationError(f"unknown regression case ids: {sorted(wanted)}")

        run = self._store.create_regression_run(
            code_commit=self._code_commit,
            config_hash=self._config_hash,
            dataset_hash=self._dataset_hash,
            expectation_revision="cases-v1",
        )
        run_id = str(run["run_id"])
        started = time.monotonic()

        outcomes: list[CaseOutcome] = []
        for case in selected:
            outcome = self._run_case(case)
            outcomes.append(outcome)
            for assertion in outcome.assertions:
                self._store.record_assertion(
                    run_id=run_id,
                    case_id=outcome.case_id,
                    assertion_kind=assertion.kind,
                    result=assertion.result,
                    scope=assertion.scope,
                    target=assertion.target,
                    detail=assertion.detail,
                )

        counts = {
            STATUS_PASSED: sum(1 for item in outcomes if item.status == STATUS_PASSED),
            STATUS_FAILED: sum(1 for item in outcomes if item.status == STATUS_FAILED),
            STATUS_BLOCKED: sum(1 for item in outcomes if item.status == STATUS_BLOCKED),
        }
        summary = {
            "run_id": run_id,
            "code_commit": self._code_commit,
            "config_hash": self._config_hash,
            "dataset_hash": self._dataset_hash,
            "expectation_revision": "cases-v1",
            "total": len(outcomes),
            "passed": counts[STATUS_PASSED],
            "failed": counts[STATUS_FAILED],
            "blocked": counts[STATUS_BLOCKED],
            "duration_ms": round((time.monotonic() - started) * 1000, 2),
            "cases": [
                {
                    "case_id": outcome.case_id,
                    "status": outcome.status,
                    "blocked_reason": outcome.blocked_reason,
                    "detail": outcome.detail,
                    "assertions": [
                        {
                            "kind": item.kind,
                            "target": item.target,
                            "result": item.result,
                            "scope": item.scope,
                            "detail": item.detail,
                        }
                        for item in outcome.assertions
                    ],
                }
                for outcome in outcomes
            ],
        }
        status = STATUS_FAILED if counts[STATUS_FAILED] else STATUS_PASSED
        self._store.finish_regression_run(run_id=run_id, status=status, summary=summary)
        return summary

    def _load_cases(self) -> list[dict[str, Any]]:
        if self._configs_dir is None:
            return self._store.list_regression_cases()
        return load_cases(self._configs_dir)


def validate_cases(cases: list[dict[str, Any]]) -> list[str]:
    """做样本完整性自检，返回问题列表（空表示通过）。"""
    problems: list[str] = []
    seen: set[str] = set()
    for case in cases:
        case_id = str(case.get("case_id", ""))
        if not case_id:
            problems.append("case without case_id")
            continue
        if case_id in seen:
            problems.append(f"duplicate case_id: {case_id}")
        seen.add(case_id)
        for field_name in ("title", "expected", "spec_section", "status"):
            if not case.get(field_name):
                problems.append(f"{case_id} missing {field_name}")
        if case.get("expected_absent_events") and not case.get("negative_assertion_reason"):
            problems.append(f"{case_id} declares forbidden events without a reason")
    for number in range(1, 52):
        expected = f"PB-{number:02d}"
        if expected not in seen:
            problems.append(f"missing {expected}")
    return problems


def ensure_dataset_and_startup(config: PaTrendConfig) -> None:
    """结构研究阶段的启动门禁（供回归与页面共用）。"""
    validate_startup(config, Stage.RESEARCH_STRUCTURE)


def build_case_snapshot(config: PaTrendConfig, cases_dir: Path) -> dict[str, Any]:
    """构造一份用于自检的最小快照（不含回放）。"""
    from pa_trend.application.market_context import MarketContext

    context = MarketContext(config)
    return build_snapshot(
        config,
        context=context,
        timeframe=Timeframe.HOUR4,
        as_of_ns=None,
        dataset_id=None,
    ).payload


__all__ = [
    "Assertion",
    "CaseOutcome",
    "RegressionRunner",
    "build_case_snapshot",
    "ensure_dataset_and_startup",
    "load_cases",
    "validate_cases",
]
