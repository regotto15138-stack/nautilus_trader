"""SACW V1.1.2 第 5 章的 SQLite 持久化层。

使用标准库 ``sqlite3``，不引入额外服务依赖，数据库文件默认放在
``nautilus_pa/var/sacw.sqlite3``。

设计约束（SACW 5.2）：

- 所有时间以 UTC ISO-8601 字符串（``...Z``）保存，内部换算使用纳秒；
- 价格、数量、费率一律以字符串形式保存十进制文本，不使用二进制浮点；
- 每个标注对象都有稳定 UUID；
- 修订历史不可变，删除为软删除，冻结标注不允许物理删除；
- 所有写入都记录审计日志（``annotation_audit_logs``）。

本模块只负责持久化与状态机校验，不实现匹配算法、不做回放，也不产生交易指令。
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from pa_trend.domain.errors import PaTrendError

#: 可序列化的 JSON 值类型；避免在公开签名里使用 ``Any``。
JsonValue = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]

SCHEMA_VERSION = 3

#: 允许的实体类型（SACW 4.1、4.4）。
ENTITY_TYPES = (
    "SWING_POINT",
    "N_STRUCTURE",
    "ZONE",
    "STATE_INTERVAL",
    "PROTECTED_POINT",
    "PULLBACK_SEQUENCE",
    "SIGNAL_LIFECYCLE",
    "POSITION_LIFECYCLE",
)

#: 允许的标签来源（SACW 4.2）。只有前两种可进入正式 Ground Truth。
LABEL_SOURCES = (
    "HUMAN_PRIMARY",
    "HUMAN_REVIEWED",
    "PROGRAM_PREDICTION",
    "IMPORTED",
    "AI_SUGGESTED",
)
GROUND_TRUTH_SOURCES = frozenset({"HUMAN_PRIMARY", "HUMAN_REVIEWED"})

#: 标注状态（SACW 4.3）。
ANNOTATION_STATUSES = (
    "DRAFT",
    "SUBMITTED",
    "REVIEWED",
    "APPROVED",
    "FROZEN",
    "SUPERSEDED",
    "REJECTED",
    "AMBIGUOUS",
)
GROUND_TRUTH_STATUSES = frozenset({"APPROVED", "FROZEN"})

#: 允许的状态迁移；``FROZEN`` 与 ``SUPERSEDED`` 为不可原地修改的终态。
_STATUS_TRANSITIONS = {
    "DRAFT": {"SUBMITTED", "REJECTED", "AMBIGUOUS"},
    "SUBMITTED": {"REVIEWED", "REJECTED", "DRAFT"},
    "REVIEWED": {"APPROVED", "REJECTED", "SUBMITTED"},
    "APPROVED": {"FROZEN", "SUPERSEDED"},
    "FROZEN": {"SUPERSEDED"},
    "REJECTED": {"DRAFT", "SUPERSEDED"},
    "AMBIGUOUS": {"DRAFT", "SUBMITTED", "SUPERSEDED"},
    "SUPERSEDED": set(),
}

#: Zone 标注模式（SACW 21.1）。
ZONE_ANNOTATION_MODES = (
    "ANCHOR_ONLY",
    "HUMAN_BOUNDARY",
    "ANCHOR_ONLY_WITH_OVERRIDE",
)

#: 标注载荷里可作为“对象时间”的字段，按优先级排列（SACW 4.4）。
_ANNOTATION_TIME_FIELDS = ("occurred_at", "valid_from", "created_at", "updated_at")
#: 标注对象的结束时间字段；缺失时退化为对象时间。
_ANNOTATION_END_TIME_FIELDS = ("confirmed_at", "valid_to")


def compute_time_split_hash(splits: list[dict[str, Any]]) -> str:
    """对数据集切分区间生成确定性哈希（SACW 6.3 time_split_hash）。"""
    canonical = [
        {
            "split": str(item["split"]),
            "range_start": str(item["range_start"]),
            "range_end": str(item["range_end"]),
        }
        for item in sorted(
            splits,
            key=lambda item: (str(item["range_start"]), str(item["range_end"]), str(item["split"])),
        )
    ]
    return hashlib.sha256(_json(canonical).encode("utf-8")).hexdigest()


def compute_default_time_split_hash(range_start: str, range_end: str) -> str | None:
    """按 60/20/20 时间三分生成默认 time_split_hash（SACW 5.3、6.3）。

    冻结时尚未登记显式切分，用数据集时间范围固化一份默认三分计划；
    之后调用 split 的自动三分若使用同一范围，会得到同一哈希。
    """
    start = _parse_iso_datetime(range_start)
    end = _parse_iso_datetime(range_end)
    if start is None or end is None or end <= start:
        return None
    span_us = int((end - start) / timedelta(microseconds=1))
    calibration_end = start + timedelta(microseconds=span_us * 6 // 10)
    validation_end = start + timedelta(microseconds=span_us * 8 // 10)
    windows = (
        ("CALIBRATION", start, calibration_end),
        ("VALIDATION", calibration_end, validation_end),
        ("HOLDOUT", validation_end, end),
    )
    return compute_time_split_hash(
        [
            {
                "split": name,
                "range_start": window_start.isoformat().replace("+00:00", "Z"),
                "range_end": window_end.isoformat().replace("+00:00", "Z"),
            }
            for name, window_start, window_end in windows
        ]
    )


def _annotation_time_value(annotation: dict[str, Any]) -> str | None:
    """返回标注对象用于时间过滤与切分的起始时间。"""
    payload = annotation.get("payload") or {}
    if not isinstance(payload, dict):
        return None
    for field in _ANNOTATION_TIME_FIELDS:
        value = payload.get(field)
        if value:
            return str(value)
    created = annotation.get("created_at")
    return str(created) if created else None


def _annotation_end_time_value(annotation: dict[str, Any]) -> str | None:
    """返回标注对象用于时间过滤与切分的结束时间。"""
    payload = annotation.get("payload") or {}
    if isinstance(payload, dict):
        for field in _ANNOTATION_END_TIME_FIELDS:
            value = payload.get(field)
            if value:
                return str(value)
    return _annotation_time_value(annotation)


def _parse_iso_datetime(value: object) -> datetime | None:
    """把 ISO-8601 文本解析为 UTC 时间；失败返回 None。"""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _parse_time_bound(value: object, *, end: bool) -> datetime | None:
    """解析时间范围端点；只有日期时，起点取当日 0 点、终点取当日 24 点。"""
    text = str(value or "").strip()
    if not text:
        return None
    if len(text) == 10:
        text = text + ("T23:59:59.999999" if end else "T00:00:00")
    return _parse_iso_datetime(text)


_SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS market_datasets (
    dataset_id TEXT PRIMARY KEY,
    instrument_id TEXT NOT NULL,
    range_start TEXT NOT NULL,
    range_end TEXT NOT NULL,
    timeframe_set TEXT NOT NULL,
    data_hash TEXT NOT NULL,
    source TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dataset_splits (
    split_id TEXT PRIMARY KEY,
    dataset_id TEXT NOT NULL,
    split TEXT NOT NULL,
    range_start TEXT NOT NULL,
    range_end TEXT NOT NULL,
    data_hash TEXT NOT NULL,
    annotation_hash TEXT,
    time_split_hash TEXT,
    frozen_at TEXT NOT NULL,
    UNIQUE(dataset_id, split)
);

CREATE TABLE IF NOT EXISTS annotation_projects (
    project_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    spec_version TEXT NOT NULL,
    sacw_version TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS annotations (
    annotation_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    dataset_id TEXT,
    entity_type TEXT NOT NULL,
    instrument_id TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    payload TEXT NOT NULL,
    label_source TEXT NOT NULL,
    status TEXT NOT NULL,
    revision INTEGER NOT NULL,
    annotation_rule_version TEXT NOT NULL,
    config_hash TEXT,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT
);

CREATE TABLE IF NOT EXISTS annotation_revisions (
    revision_id TEXT PRIMARY KEY,
    annotation_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    payload TEXT NOT NULL,
    status TEXT NOT NULL,
    changed_by TEXT NOT NULL,
    changed_at TEXT NOT NULL,
    reason TEXT,
    UNIQUE(annotation_id, revision)
);

CREATE TABLE IF NOT EXISTS annotation_audit_logs (
    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    entity_type TEXT,
    entity_id TEXT,
    before TEXT,
    after TEXT,
    reason TEXT,
    at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS golden_datasets (
    golden_dataset_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    dataset_id TEXT,
    split TEXT NOT NULL,
    frozen_at TEXT NOT NULL,
    data_hash TEXT NOT NULL,
    annotation_hash TEXT NOT NULL,
    time_split_hash TEXT,
    baseline_replay_run_id TEXT,
    baseline_code_commit TEXT,
    baseline_config_hash TEXT,
    annotation_count INTEGER NOT NULL,
    status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS golden_dataset_annotations (
    golden_dataset_id TEXT NOT NULL,
    annotation_id TEXT NOT NULL,
    PRIMARY KEY (golden_dataset_id, annotation_id)
);

CREATE TABLE IF NOT EXISTS replay_runs (
    run_id TEXT PRIMARY KEY,
    code_commit TEXT,
    config_hash TEXT,
    dataset_hash TEXT,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS program_events (
    event_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    payload TEXT NOT NULL,
    bar_id TEXT,
    at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS comparison_runs (
    comparison_id TEXT PRIMARY KEY,
    golden_dataset_id TEXT NOT NULL,
    replay_run_id TEXT NOT NULL,
    matcher_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    summary TEXT
);

CREATE TABLE IF NOT EXISTS match_results (
    match_id TEXT PRIMARY KEY,
    comparison_id TEXT NOT NULL,
    human_id TEXT,
    program_id TEXT,
    match_type TEXT NOT NULL,
    errors TEXT,
    metrics TEXT
);

CREATE TABLE IF NOT EXISTS manual_boundary_overrides (
    override_id TEXT PRIMARY KEY,
    zone_annotation_id TEXT NOT NULL,
    original_lower TEXT NOT NULL,
    original_upper TEXT NOT NULL,
    original_center TEXT NOT NULL,
    override_lower TEXT NOT NULL,
    override_upper TEXT NOT NULL,
    override_center TEXT NOT NULL,
    operator TEXT NOT NULL,
    reason TEXT NOT NULL,
    review_status TEXT NOT NULL,
    reviewer TEXT,
    review_reason TEXT,
    created_at TEXT NOT NULL,
    reviewed_at TEXT,
    strategy_spec_version TEXT NOT NULL,
    config_hash TEXT
);

CREATE TABLE IF NOT EXISTS regression_cases (
    case_id TEXT PRIMARY KEY,
    case_version INTEGER NOT NULL,
    title TEXT NOT NULL,
    scenario_description TEXT,
    spec_section TEXT,
    category TEXT,
    instrument_id TEXT,
    timeframes TEXT,
    dataset_id TEXT,
    dataset_hash TEXT,
    bar_ranges TEXT,
    preconditions TEXT,
    input_events TEXT,
    expected TEXT,
    stage TEXT,
    blocked_reason TEXT,
    expected_events TEXT NOT NULL,
    expected_state_transitions TEXT,
    expected_final_state TEXT,
    expected_absent_events TEXT,
    expected_absent_state_transitions TEXT,
    negative_assertion_reason TEXT,
    status TEXT NOT NULL,
    review_status TEXT NOT NULL,
    expectation_revision_id TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS regression_expectation_revisions (
    revision_id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL,
    original_expected TEXT NOT NULL,
    proposed_expected TEXT NOT NULL,
    evidence TEXT,
    spec_section TEXT,
    status TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    reviewer TEXT,
    review_reason TEXT,
    reviewed_at TEXT
);

CREATE TABLE IF NOT EXISTS regression_runs (
    run_id TEXT PRIMARY KEY,
    code_commit TEXT,
    config_hash TEXT,
    dataset_hash TEXT,
    expectation_revision TEXT,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    summary TEXT
);

CREATE TABLE IF NOT EXISTS regression_assertions (
    assertion_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    assertion_kind TEXT NOT NULL,
    scope TEXT,
    target TEXT,
    window_start TEXT,
    window_end TEXT,
    result TEXT NOT NULL,
    detail TEXT
);

CREATE TABLE IF NOT EXISTS snapshot_artifacts (
    snapshot_id TEXT PRIMARY KEY,
    dataset_id TEXT NOT NULL,
    snapshot_hash TEXT NOT NULL,
    path TEXT,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    detail TEXT
);

CREATE TABLE IF NOT EXISTS cost_metadata_versions (
    version_id TEXT PRIMARY KEY,
    fee_version TEXT,
    funding_hash TEXT,
    instrument_meta_hash TEXT,
    effective_from TEXT,
    source TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS config_versions (
    config_id TEXT PRIMARY KEY,
    parent_id TEXT,
    config_json TEXT NOT NULL,
    config_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS config_approvals (
    approval_id TEXT PRIMARY KEY,
    config_id TEXT NOT NULL,
    reviewer TEXT NOT NULL,
    decision TEXT NOT NULL,
    reason TEXT,
    at TEXT NOT NULL
);
"""


class StoreError(PaTrendError):
    """SACW 持久化层的拒绝性错误。"""


def new_id(prefix: str) -> str:
    """生成带前缀的稳定 UUID。"""
    return f"{prefix}_{uuid.uuid4().hex}"


def now_iso() -> str:
    """返回当前 UTC 时间的 ISO-8601 文本（秒精度，``Z`` 结尾）。"""
    from datetime import UTC, datetime

    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _load(text: str | None) -> JsonValue:
    if text is None:
        return None
    return json.loads(text)


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    # sqlite3.Row 不支持键成员测试，只能通过 keys() 迭代。
    return {key: row[key] for key in row.keys()}  # noqa: SIM118


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise StoreError(message)


def _require_fields(payload: dict[str, Any], fields: tuple[str, ...], entity: str) -> None:
    missing = [name for name in fields if payload.get(name) in (None, "", [])]
    if missing:
        raise StoreError(f"{entity} payload missing required fields: {', '.join(missing)}")


def _require_decimal(value: object, field: str) -> Decimal:
    """把价格类字段解析为 Decimal，拒绝空值与非法数字。"""
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise StoreError(f"{field} must be a decimal value") from exc


def validate_annotation_payload(
    entity_type: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """校验并规范化标注载荷（SACW 4.4）。

    参数
    ----
    entity_type : str
        实体类型，必须是 :data:`ENTITY_TYPES` 之一。
    payload : dict
        标注内容；价格等十进制值以字符串形式保存。

    返回
    ----
    dict
        规范化后的载荷副本。

    异常
    ----
    StoreError
        类型未知或必填字段缺失时抛出。
    """
    _require(entity_type in ENTITY_TYPES, f"unknown entity_type: {entity_type}")
    data = dict(payload)

    if entity_type == "SWING_POINT":
        _require_fields(data, ("direction", "price", "occurred_at", "confirmed_at"), entity_type)
        _require(
            str(data["direction"]).upper() in {"HIGH", "LOW"},
            "SWING_POINT direction must be HIGH or LOW",
        )
        data["direction"] = str(data["direction"]).upper()
        _require(
            str(data["confirmed_at"]) >= str(data["occurred_at"]),
            "SWING_POINT confirmed_at must not precede occurred_at",
        )
        # SACW 19.1：工作台当前只允许 HUMAN_JUDGED。ALGORITHM_DERIVED 的
        # confirmed_at 必须由已冻结的 baseline replay 生成，前端不得写入。
        policy = str(data.get("confirmation_policy") or "HUMAN_JUDGED").upper()
        _require(
            policy in {"HUMAN_JUDGED", "ALGORITHM_DERIVED"},
            f"unknown confirmation_policy: {policy}",
        )
        _require(
            policy == "HUMAN_JUDGED",
            "ALGORITHM_DERIVED requires a frozen baseline replay run; "
            "the workbench must save HUMAN_JUDGED annotations",
        )
        human_confirmed_at = data.get("human_judged_confirmed_at") or data["confirmed_at"]
        _require(
            str(human_confirmed_at) >= str(data["occurred_at"]),
            "SWING_POINT human_judged_confirmed_at must not precede occurred_at",
        )
        data["confirmation_policy"] = policy
        data["human_judged_confirmed_at"] = str(human_confirmed_at)
        data.setdefault(
            "confirmation_evidence",
            {"policy": policy, "source": "SACW_WORKBENCH"},
        )
        # SACW 3.4A / 6.2：手动改价必须保留覆盖标记与修改原因，审核时可见。
        override_raw = data.get("manual_price_override")
        override = override_raw is True or str(override_raw or "").lower() in {
            "true",
            "1",
            "yes",
        }
        if override:
            override_reason = str(data.get("override_reason") or "").strip()
            _require(
                bool(override_reason),
                "SWING_POINT manual_price_override requires override_reason",
            )
            data["manual_price_override"] = True
            data["override_reason"] = override_reason
        else:
            data["manual_price_override"] = False
        data["price"] = str(data["price"])

    elif entity_type == "N_STRUCTURE":
        _require_fields(
            data,
            ("l1_swing_id", "h1_swing_id", "l2_swing_id", "h2_swing_id", "confirmed_at"),
            entity_type,
        )
        _require(
            len({data[key] for key in ("l1_swing_id", "h1_swing_id", "l2_swing_id", "h2_swing_id")})
            == 4,
            "N_STRUCTURE requires four distinct anchor swing ids",
        )
        # V1.4.8 第 5.5 节：失效判定 ATR 时点未定义，人工标注不得伪造
        # 失效价、失效 ATR 或失效 Bar；统一标记为 SPEC_AMBIGUITY。
        invalidation_status = str(data.get("invalidation_status") or "SPEC_AMBIGUITY").upper()
        _require(
            invalidation_status
            in {"NOT_INVALIDATED", "INVALIDATED", "AMBIGUOUS", "SPEC_AMBIGUITY"},
            f"unknown invalidation_status: {invalidation_status}",
        )
        blocked_fields = (
            "invalidation_atr_value",
            "invalidation_atr_source_bar_id",
            "invalidation_price",
            "invalidation_confirmed_at",
            "invalidation_bar_id",
            "invalidation_close",
        )
        forged = [name for name in blocked_fields if data.get(name) is not None]
        if forged:
            raise StoreError(
                "N_STRUCTURE invalidation fields are blocked by SPEC_AMBIGUITY "
                f"(V1.4.8 does not define the ATR snapshot): {', '.join(forged)}",
            )
        data["invalidation_status"] = invalidation_status
        structure_status = str(data.get("status") or "CONFIRMED").upper()
        _require(
            structure_status in {"CONFIRMED", "ACTIVE", "INVALIDATED", "EXPIRED"},
            f"unknown N_STRUCTURE status: {structure_status}",
        )
        data["status"] = structure_status

    elif entity_type == "ZONE":
        _require_fields(data, ("zone_type", "anchor_swing_ids", "annotation_mode"), entity_type)
        _require(
            str(data["zone_type"]).upper() in {"SUPPORT", "RESISTANCE"},
            "ZONE zone_type must be SUPPORT or RESISTANCE",
        )
        data["zone_type"] = str(data["zone_type"]).upper()
        _require(
            isinstance(data["anchor_swing_ids"], list) and len(data["anchor_swing_ids"]) >= 2,
            "ZONE requires at least two distinct anchor swing ids (spec section 6.5)",
        )
        _require(
            len(set(map(str, data["anchor_swing_ids"]))) == len(data["anchor_swing_ids"]),
            "ZONE anchor_swing_ids must be distinct",
        )
        _require(
            data["annotation_mode"] in ZONE_ANNOTATION_MODES,
            f"ZONE annotation_mode must be one of {ZONE_ANNOTATION_MODES}",
        )
        if data["annotation_mode"] == "HUMAN_BOUNDARY":
            _require_fields(data, ("human_lower", "human_upper", "human_center"), entity_type)
            human_lower = _require_decimal(data["human_lower"], "human_lower")
            human_upper = _require_decimal(data["human_upper"], "human_upper")
            human_center = _require_decimal(data["human_center"], "human_center")
            _require(
                human_lower < human_upper,
                "ZONE human_lower must be below human_upper",
            )
            _require(
                human_lower <= human_center <= human_upper,
                "ZONE human_center must lie inside [human_lower, human_upper]",
            )
            data["human_lower"] = str(human_lower)
            data["human_upper"] = str(human_upper)
            data["human_center"] = str(human_center)
        elif data["annotation_mode"] == "ANCHOR_ONLY":
            # ANCHOR_ONLY：边界必须由后端 V1.4.8 ZoneEngine 计算后写入。
            _require_fields(data, ("center", "lower", "upper"), entity_type)
        else:
            raise StoreError(
                "ANCHOR_ONLY_WITH_OVERRIDE is produced only by an approved "
                "manual_boundary_override; create the Zone as ANCHOR_ONLY first",
            )
        for key in ("center", "lower", "upper", "half_width"):
            if data.get(key) is not None:
                data[key] = str(data[key])

    elif entity_type == "PROTECTED_POINT":
        # SACW 3.4D：保护点必须能追溯到来源 SwingPoint。
        _require_fields(
            data,
            ("direction", "price", "valid_from", "source_swing_id"),
            entity_type,
        )
        _require(
            str(data["direction"]).upper() in {"HIGH", "LOW"},
            "PROTECTED_POINT direction must be HIGH or LOW",
        )
        event_type = str(data.get("event_type") or "INIT").upper()
        _require(
            event_type in {"INIT", "UPDATE", "INVALIDATE"},
            f"unknown PROTECTED_POINT event_type: {event_type}",
        )
        if data.get("valid_to") is not None:
            _require(
                str(data["valid_to"]) >= str(data["valid_from"]),
                "PROTECTED_POINT valid_to must not precede valid_from",
            )
        if event_type == "INVALIDATE":
            _require_fields(data, ("invalidated_at", "invalidation_reason"), entity_type)
        data["direction"] = str(data["direction"]).upper()
        data["event_type"] = event_type
        data["price"] = str(data["price"])
        data["source_swing_id"] = str(data["source_swing_id"])

    elif entity_type == "STATE_INTERVAL":
        _require_fields(
            data,
            ("state", "valid_from", "known_at", "reason_code"),
            entity_type,
        )
        if data.get("valid_to") is not None:
            _require(
                str(data["valid_to"]) >= str(data["valid_from"]),
                "STATE_INTERVAL valid_to must not precede valid_from",
            )
        _require(
            str(data["known_at"]) >= str(data["valid_from"]),
            "STATE_INTERVAL known_at must not precede valid_from",
        )
        data["state"] = str(data["state"]).upper()
        data["reason_code"] = str(data["reason_code"])

    return data


class SacwStore:
    """SACW 标注、黄金样本与回归数据的持久化门面。"""

    def __init__(self, path: Path | str) -> None:
        """打开（必要时创建）数据库并建立结构。"""
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.execute(
            "INSERT INTO schema_meta(key, value) VALUES('schema_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(SCHEMA_VERSION),),
        )
        self._migrate()
        self._conn.commit()

    def _migrate(self) -> None:
        """为旧库补齐新增列（SQLite 不支持 ``ADD COLUMN IF NOT EXISTS``）。"""
        additions = {
            "regression_cases": {
                "expected": "TEXT",
                "stage": "TEXT",
                "blocked_reason": "TEXT",
            },
            "dataset_splits": {"time_split_hash": "TEXT"},
            "golden_datasets": {"time_split_hash": "TEXT"},
        }
        for table, columns in additions.items():
            existing = {
                row["name"] for row in self._conn.execute(f"PRAGMA table_info({table})").fetchall()
            }
            for name, kind in columns.items():
                if name not in existing:
                    self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {kind}")

    # ------------------------------------------------------------------ 基础

    def close(self) -> None:
        """关闭数据库连接。"""
        with self._lock:
            self._conn.close()

    def __enter__(self) -> SacwStore:
        """上下文管理器入口。"""
        return self

    def __exit__(self, *exc: object) -> None:
        """上下文管理器出口。"""
        self.close()

    def _audit(
        self,
        *,
        actor: str,
        action: str,
        entity_type: str | None = None,
        entity_id: str | None = None,
        before: object = None,
        after: object = None,
        reason: str | None = None,
    ) -> None:
        self._conn.execute(
            "INSERT INTO annotation_audit_logs"
            "(actor, action, entity_type, entity_id, before, after, reason, at) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (
                actor,
                action,
                entity_type,
                entity_id,
                None if before is None else _json(before),
                None if after is None else _json(after),
                reason,
                now_iso(),
            ),
        )

    # --------------------------------------------------------------- 行情数据集

    def upsert_market_dataset(
        self,
        *,
        dataset_id: str,
        instrument_id: str,
        range_start: str,
        range_end: str,
        timeframe_set: list[str] | tuple[str, ...],
        data_hash: str,
        source: str,
    ) -> dict[str, Any]:
        """登记一个行情数据集。"""
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO market_datasets"
                "(dataset_id, instrument_id, range_start, range_end, timeframe_set,"
                " data_hash, source, created_at) VALUES(?,?,?,?,?,?,?,?) "
                "ON CONFLICT(dataset_id) DO UPDATE SET"
                " range_end=excluded.range_end, data_hash=excluded.data_hash,"
                " timeframe_set=excluded.timeframe_set",
                (
                    dataset_id,
                    instrument_id,
                    range_start,
                    range_end,
                    ",".join(str(item) for item in timeframe_set),
                    data_hash,
                    source,
                    now_iso(),
                ),
            )
        return self.get_market_dataset(dataset_id)  # type: ignore[return-value]

    def get_market_dataset(self, dataset_id: str) -> dict[str, Any] | None:
        """按 ID 读取行情数据集。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM market_datasets WHERE dataset_id = ?",
                (dataset_id,),
            ).fetchone()
        return None if row is None else _row_to_dict(row)

    def list_market_datasets(self) -> list[dict[str, Any]]:
        """列出全部行情数据集。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM market_datasets ORDER BY created_at, dataset_id",
            ).fetchall()
        return [_row_to_dict(row) for row in rows]

    def save_dataset_split(
        self,
        *,
        dataset_id: str,
        split: str,
        range_start: str,
        range_end: str,
        data_hash: str,
        annotation_hash: str | None = None,
    ) -> dict[str, Any]:
        """保存 Calibration / Validation / Holdout 切分（SACW 5.3）。

        同一切分区间会参与数据集级 time_split_hash；该哈希在每次登记后
        重新计算并回写到该数据集的全部切分记录，保证切分边界与黄金样本
        绑定的哈希一致。
        """
        _require(split in {"CALIBRATION", "VALIDATION", "HOLDOUT"}, f"unknown split: {split}")
        split_id = f"{dataset_id}:{split}"
        with self._lock, self._conn:
            existing = [
                _row_to_dict(row)
                for row in self._conn.execute(
                    "SELECT * FROM dataset_splits WHERE dataset_id = ?",
                    (dataset_id,),
                ).fetchall()
            ]
            candidate = [
                item for item in existing if str(item["split"]) != split
            ] + [{"split": split, "range_start": range_start, "range_end": range_end}]
            time_split_hash = compute_time_split_hash(candidate)
            self._conn.execute(
                "INSERT INTO dataset_splits"
                "(split_id, dataset_id, split, range_start, range_end, data_hash,"
                " annotation_hash, time_split_hash, frozen_at) VALUES(?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(split_id) DO UPDATE SET"
                " range_start=excluded.range_start, range_end=excluded.range_end,"
                " data_hash=excluded.data_hash, annotation_hash=excluded.annotation_hash,"
                " time_split_hash=excluded.time_split_hash,"
                " frozen_at=excluded.frozen_at",
                (
                    split_id,
                    dataset_id,
                    split,
                    range_start,
                    range_end,
                    data_hash,
                    annotation_hash,
                    time_split_hash,
                    now_iso(),
                ),
            )
            # 数据集级哈希必须对全部切分一致，避免只登记一个切分就冻结的歧义。
            self._conn.execute(
                "UPDATE dataset_splits SET time_split_hash = ? WHERE dataset_id = ?",
                (time_split_hash, dataset_id),
            )
        return {
            "split_id": split_id,
            "dataset_id": dataset_id,
            "split": split,
            "range_start": range_start,
            "range_end": range_end,
            "data_hash": data_hash,
            "annotation_hash": annotation_hash,
            "time_split_hash": time_split_hash,
        }

    def list_dataset_splits(self, dataset_id: str) -> list[dict[str, Any]]:
        """列出某数据集的全部切分。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM dataset_splits WHERE dataset_id = ? ORDER BY split",
                (dataset_id,),
            ).fetchall()
        return [_row_to_dict(row) for row in rows]

    # --------------------------------------------------------------- 标注项目

    def create_project(
        self,
        *,
        name: str,
        spec_version: str = "V1.4.8",
        sacw_version: str = "V1.1.2",
        actor: str = "system",
    ) -> dict[str, Any]:
        """创建标注项目。"""
        project_id = new_id("proj")
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO annotation_projects"
                "(project_id, name, spec_version, sacw_version, status, created_at) "
                "VALUES(?,?,?,?,?,?)",
                (project_id, name, spec_version, sacw_version, "ACTIVE", now_iso()),
            )
            self._audit(
                actor=actor,
                action="PROJECT_CREATED",
                entity_type="PROJECT",
                entity_id=project_id,
                after={"name": name, "spec_version": spec_version},
            )
        return self.get_project(project_id)  # type: ignore[return-value]

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        """按 ID 读取项目。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM annotation_projects WHERE project_id = ?",
                (project_id,),
            ).fetchone()
        return None if row is None else _row_to_dict(row)

    def list_projects(self) -> list[dict[str, Any]]:
        """列出全部项目。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM annotation_projects ORDER BY created_at, project_id",
            ).fetchall()
        return [_row_to_dict(row) for row in rows]

    def ensure_project(self, *, name: str = "P0-E", actor: str = "system") -> dict[str, Any]:
        """返回默认项目，不存在时创建。"""
        for project in self.list_projects():
            if project["name"] == name:
                return project
        return self.create_project(name=name, actor=actor)

    # ------------------------------------------------------------------ 标注

    def _annotation_row(self, annotation_id: str) -> sqlite3.Row:
        row = self._conn.execute(
            "SELECT * FROM annotations WHERE annotation_id = ?",
            (annotation_id,),
        ).fetchone()
        if row is None:
            raise StoreError(f"annotation not found: {annotation_id}")
        return row

    def _annotation_view(self, row: sqlite3.Row) -> dict[str, Any]:
        data = _row_to_dict(row)
        data["payload"] = _load(data["payload"])
        return data

    def create_annotation(
        self,
        *,
        project_id: str,
        entity_type: str,
        timeframe: str,
        payload: dict[str, Any],
        instrument_id: str,
        actor: str,
        label_source: str = "HUMAN_PRIMARY",
        status: str = "DRAFT",
        annotation_rule_version: str = "SACW-V1.1.2",
        dataset_id: str | None = None,
        config_hash: str | None = None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """创建一个标注（初始修订号为 1，同时写入不可变修订记录）。"""
        _require(label_source in LABEL_SOURCES, f"unknown label_source: {label_source}")
        _require(status in ANNOTATION_STATUSES, f"unknown annotation status: {status}")
        data = validate_annotation_payload(entity_type, payload)

        annotation_id = new_id("ann")
        timestamp = now_iso()
        # SACW 4.5：标注者作出判断的时间必须可追溯；前端未提供时以入库时间补齐。
        data.setdefault("annotated_at", timestamp)
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO annotations"
                "(annotation_id, project_id, dataset_id, entity_type, instrument_id,"
                " timeframe, payload, label_source, status, revision,"
                " annotation_rule_version, config_hash, created_by, created_at, updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    annotation_id,
                    project_id,
                    dataset_id,
                    entity_type,
                    instrument_id,
                    timeframe,
                    _json(data),
                    label_source,
                    status,
                    1,
                    annotation_rule_version,
                    config_hash,
                    actor,
                    timestamp,
                    timestamp,
                ),
            )
            self._conn.execute(
                "INSERT INTO annotation_revisions"
                "(revision_id, annotation_id, revision, payload, status, changed_by,"
                " changed_at, reason) VALUES(?,?,?,?,?,?,?,?)",
                (
                    new_id("rev"),
                    annotation_id,
                    1,
                    _json(data),
                    status,
                    actor,
                    timestamp,
                    reason or "initial",
                ),
            )
            self._audit(
                actor=actor,
                action="ANNOTATION_CREATED",
                entity_type=entity_type,
                entity_id=annotation_id,
                after={"payload": data, "status": status},
                reason=reason,
            )
        return self.get_annotation(annotation_id)  # type: ignore[return-value]

    def get_annotation(self, annotation_id: str) -> dict[str, Any] | None:
        """按 ID 读取标注（含当前载荷）。"""
        with self._lock:
            try:
                row = self._annotation_row(annotation_id)
            except StoreError:
                return None
        return self._annotation_view(row)

    def list_annotations(
        self,
        project_id: str,
        *,
        entity_type: str | None = None,
        timeframe: str | None = None,
        status: str | None = None,
        time_from: str | None = None,
        time_to: str | None = None,
        search: str | None = None,
        include_deleted: bool = False,
    ) -> list[dict[str, Any]]:
        """列出项目下的标注，支持周期/类型/状态/时间区间与关键字过滤。

        时间区间按标注对象的 occurred_at / valid_from 过滤；关键字在实体
        类型、ID、状态、标签来源与完整载荷 JSON 上做不区分大小写的匹配。
        """
        sql = "SELECT * FROM annotations WHERE project_id = ?"
        params: list[Any] = [project_id]
        if entity_type is not None:
            sql += " AND entity_type = ?"
            params.append(entity_type)
        if timeframe is not None:
            sql += " AND timeframe = ?"
            params.append(timeframe)
        if status is not None:
            sql += " AND status = ?"
            params.append(status)
        if not include_deleted:
            sql += " AND deleted_at IS NULL"
        sql += " ORDER BY created_at, annotation_id"
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        result = [self._annotation_view(row) for row in rows]
        start = _parse_time_bound(time_from, end=False)
        end = _parse_time_bound(time_to, end=True)
        if start is not None or end is not None:
            filtered: list[dict[str, Any]] = []
            for item in result:
                value = _parse_iso_datetime(_annotation_time_value(item))
                if value is None:
                    continue
                if start is not None and value < start:
                    continue
                if end is not None and value > end:
                    continue
                filtered.append(item)
            result = filtered
        keyword = str(search or "").strip().lower()
        if keyword:
            result = [
                item
                for item in result
                if keyword
                in " ".join(
                    [
                        str(item["annotation_id"]),
                        str(item["entity_type"]),
                        str(item["timeframe"]),
                        str(item["status"]),
                        str(item["label_source"]),
                        _json(item["payload"]),
                    ],
                ).lower()
            ]
        return result

    def revise_annotation(
        self,
        *,
        annotation_id: str,
        payload: dict[str, Any],
        actor: str,
        reason: str,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        """追加一次修订；旧版本保留在 ``annotation_revisions`` 中不可变。"""
        with self._lock, self._conn:
            row = self._annotation_row(annotation_id)
            current = self._annotation_view(row)
            if expected_revision is not None and int(row["revision"]) != expected_revision:
                raise StoreError(
                    f"annotation revision conflict: expected {expected_revision}, "
                    f"was {row['revision']}",
                )
            if current["status"] == "FROZEN":
                raise StoreError(
                    f"annotation {annotation_id} is FROZEN and cannot be revised in place",
                )
            if row["deleted_at"] is not None:
                raise StoreError(f"annotation {annotation_id} is deleted")
            data = validate_annotation_payload(row["entity_type"], payload)
            revision = int(row["revision"]) + 1
            timestamp = now_iso()
            self._conn.execute(
                "UPDATE annotations SET payload = ?, revision = ?, updated_at = ? "
                "WHERE annotation_id = ?",
                (_json(data), revision, timestamp, annotation_id),
            )
            self._conn.execute(
                "INSERT INTO annotation_revisions"
                "(revision_id, annotation_id, revision, payload, status, changed_by,"
                " changed_at, reason) VALUES(?,?,?,?,?,?,?,?)",
                (
                    new_id("rev"),
                    annotation_id,
                    revision,
                    _json(data),
                    row["status"],
                    actor,
                    timestamp,
                    reason,
                ),
            )
            self._audit(
                actor=actor,
                action="ANNOTATION_REVISED",
                entity_type=row["entity_type"],
                entity_id=annotation_id,
                before=current["payload"],
                after=data,
                reason=reason,
            )
        return self.get_annotation(annotation_id)  # type: ignore[return-value]

    def copy_annotation(
        self,
        *,
        annotation_id: str,
        actor: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """复制标注为新 DRAFT（SACW 3.6：修订不覆盖旧版本）。

        复制保留实体类型、周期、载荷与人工来源，但不复制状态与修订号；
        冻结标注可以复制，复制出的对象仍需重新走提交/审核流程。
        """
        source = self.get_annotation(annotation_id)
        if source is None:
            raise StoreError(f"annotation not found: {annotation_id}")
        if source["deleted_at"] is not None:
            raise StoreError(f"annotation {annotation_id} is deleted")
        copied = self.create_annotation(
            project_id=source["project_id"],
            entity_type=source["entity_type"],
            timeframe=source["timeframe"],
            payload=dict(source["payload"]),
            instrument_id=source["instrument_id"],
            actor=actor,
            label_source=source["label_source"],
            status="DRAFT",
            annotation_rule_version=source["annotation_rule_version"],
            dataset_id=source.get("dataset_id"),
            config_hash=source.get("config_hash"),
            reason=reason or f"copied from {annotation_id}",
        )
        with self._lock, self._conn:
            self._audit(
                actor=actor,
                action="ANNOTATION_COPIED",
                entity_type=source["entity_type"],
                entity_id=copied["annotation_id"],
                before={"source_annotation_id": annotation_id},
                after={"annotation_id": copied["annotation_id"]},
                reason=reason or f"copied from {annotation_id}",
            )
        return copied

    def transition_annotation(
        self,
        *,
        annotation_id: str,
        status: str,
        actor: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """按 SACW 4.3 的状态机迁移标注状态。"""
        _require(status in ANNOTATION_STATUSES, f"unknown annotation status: {status}")
        with self._lock, self._conn:
            row = self._annotation_row(annotation_id)
            current = str(row["status"])
            if current == status:
                return self._annotation_view(row)
            allowed = _STATUS_TRANSITIONS.get(current, set())
            if status not in allowed:
                raise StoreError(
                    f"illegal annotation status transition {current} -> {status}",
                )
            timestamp = now_iso()
            self._conn.execute(
                "UPDATE annotations SET status = ?, updated_at = ? WHERE annotation_id = ?",
                (status, timestamp, annotation_id),
            )
            # 状态迁移只写审计日志：``annotation_revisions`` 记录的是载荷修订，
            # 不是状态流水，避免同一修订号出现多条记录（SACW 5.1）。
            self._audit(
                actor=actor,
                action="ANNOTATION_STATUS_CHANGED",
                entity_type=row["entity_type"],
                entity_id=annotation_id,
                before={"status": current},
                after={"status": status},
                reason=reason,
            )
        return self.get_annotation(annotation_id)  # type: ignore[return-value]

    def soft_delete_annotation(
        self,
        *,
        annotation_id: str,
        actor: str,
        reason: str,
    ) -> None:
        """软删除标注；冻结标注禁止删除。"""
        with self._lock, self._conn:
            row = self._annotation_row(annotation_id)
            if row["status"] == "FROZEN":
                raise StoreError(f"annotation {annotation_id} is FROZEN and cannot be deleted")
            self._conn.execute(
                "UPDATE annotations SET deleted_at = ?, updated_at = ? WHERE annotation_id = ?",
                (now_iso(), now_iso(), annotation_id),
            )
            self._audit(
                actor=actor,
                action="ANNOTATION_SOFT_DELETED",
                entity_type=row["entity_type"],
                entity_id=annotation_id,
                reason=reason,
            )

    def list_revisions(self, annotation_id: str) -> list[dict[str, Any]]:
        """列出某个标注的全部修订（不可变历史）。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM annotation_revisions WHERE annotation_id = ? "
                "ORDER BY revision, changed_at",
                (annotation_id,),
            ).fetchall()
        out = []
        for row in rows:
            item = _row_to_dict(row)
            item["payload"] = _load(item["payload"])
            out.append(item)
        return out

    def list_audit_logs(self, *, limit: int = 200) -> list[dict[str, Any]]:
        """返回最近的审计日志。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM annotation_audit_logs ORDER BY log_id DESC LIMIT ?",
                (max(1, limit),),
            ).fetchall()
        out = []
        for row in rows:
            item = _row_to_dict(row)
            item["before"] = _load(item["before"])
            item["after"] = _load(item["after"])
            out.append(item)
        return list(reversed(out))

    # --------------------------------------------------------------- 黄金样本

    def project_time_bounds(
        self,
        project_id: str,
        *,
        statuses: frozenset[str] = GROUND_TRUTH_STATUSES,
    ) -> tuple[str | None, str | None]:
        """返回项目正式标注的最早/最晚对象时间，用于自动切分（SACW 5.3）。"""
        rows = [row for row in self.list_annotations(project_id) if row["status"] in statuses]
        starts = sorted(value for value in (_annotation_time_value(row) for row in rows) if value)
        ends = sorted(value for value in (_annotation_end_time_value(row) for row in rows) if value)
        if not starts or not ends:
            return (None, None)
        return (starts[0], ends[-1])

    def annotation_hash(
        self,
        project_id: str,
        *,
        statuses: frozenset[str] = GROUND_TRUTH_STATUSES,
    ) -> str:
        """计算某项目正式 Ground Truth 的标注哈希（SACW 5.1）。"""
        rows = self.list_annotations(project_id)
        selected = [row for row in rows if row["status"] in statuses]
        selected.sort(key=lambda item: item["annotation_id"])
        canonical = [
            {
                "annotation_id": row["annotation_id"],
                "entity_type": row["entity_type"],
                "timeframe": row["timeframe"],
                "revision": row["revision"],
                "payload": row["payload"],
            }
            for row in selected
        ]
        return hashlib.sha256(_json(canonical).encode("utf-8")).hexdigest()

    def freeze_golden_dataset(
        self,
        *,
        project_id: str,
        split: str,
        data_hash: str,
        actor: str,
        dataset_id: str | None = None,
        baseline_replay_run_id: str | None = None,
        baseline_code_commit: str | None = None,
        baseline_config_hash: str | None = None,
    ) -> dict[str, Any]:
        """冻结黄金样本：只允许 APPROVED/FROZEN 标注进入 Ground Truth。"""
        _require(split in {"CALIBRATION", "VALIDATION", "HOLDOUT"}, f"unknown split: {split}")
        rows = self.list_annotations(project_id)
        usable = [row for row in rows if row["status"] in GROUND_TRUTH_STATUSES]
        if not usable:
            raise StoreError(
                "golden dataset requires at least one APPROVED or FROZEN annotation",
            )
        for row in usable:
            if row["label_source"] not in GROUND_TRUTH_SOURCES:
                raise StoreError(
                    f"annotation {row['annotation_id']} has label_source "
                    f"{row['label_source']} which cannot enter Ground Truth",
                )
        annotation_hash = self.annotation_hash(project_id)
        # SACW 6.3：冻结时固化时间切分哈希。已登记切分优先；否则用数据集
        # 时间范围固化一份 60/20/20 默认三分哈希，供后续实验复现。
        splits = self.list_dataset_splits(dataset_id) if dataset_id else []
        if splits:
            time_split_hash: str | None = compute_time_split_hash(splits)
        else:
            time_range: dict[str, str] | None = None
            market = self.get_market_dataset(dataset_id) if dataset_id else None
            if market is not None:
                market_start = str(market["range_start"])
                market_end = str(market["range_end"])
                if market_start.isdigit() and market_end.isdigit():
                    from pa_trend.domain.models.timeframe import ns_to_dt

                    time_range = {
                        "range_start": ns_to_dt(int(market_start))
                        .isoformat()
                        .replace("+00:00", "Z"),
                        "range_end": ns_to_dt(int(market_end))
                        .isoformat()
                        .replace("+00:00", "Z"),
                    }
            if time_range is None:
                starts = sorted(
                    value for value in (_annotation_time_value(row) for row in usable) if value
                )
                ends = sorted(
                    value for value in (_annotation_end_time_value(row) for row in usable) if value
                )
                if starts and ends:
                    time_range = {"range_start": starts[0], "range_end": ends[-1]}
            time_split_hash = None
            if time_range is not None:
                time_split_hash = compute_default_time_split_hash(
                    time_range["range_start"],
                    time_range["range_end"],
                )
                if time_split_hash is None:
                    # 单点标注的起止时间相同，无法三分；仍固化一份单窗口哈希，
                    # 保证黄金样本具备可追溯的 time_split_hash。
                    time_split_hash = compute_time_split_hash(
                        [dict(time_range, split=split)]
                    )
        golden_id = new_id("gold")
        # 冻结即建立 baseline replay 绑定（SACW 19.4、6.3）：后续差异比较
        # 必须引用同一条回放，而不是临时用当前上下文“复核”标注。
        if baseline_replay_run_id is None:
            replay = self.create_replay_run(
                code_commit=baseline_code_commit,
                config_hash=baseline_config_hash,
                dataset_hash=data_hash,
                notes=f"golden dataset baseline replay: {golden_id}",
            )
            self.finish_replay_run(run_id=replay["run_id"])
            baseline_replay_run_id = str(replay["run_id"])
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO golden_datasets"
                "(golden_dataset_id, project_id, dataset_id, split, frozen_at, data_hash,"
                " annotation_hash, time_split_hash, baseline_replay_run_id, baseline_code_commit,"
                " baseline_config_hash, annotation_count, status) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    golden_id,
                    project_id,
                    dataset_id,
                    split,
                    now_iso(),
                    data_hash,
                    annotation_hash,
                    time_split_hash,
                    baseline_replay_run_id,
                    baseline_code_commit,
                    baseline_config_hash,
                    len(usable),
                    "FROZEN",
                ),
            )
            self._audit(
                actor=actor,
                action="GOLDEN_DATASET_FROZEN",
                entity_type="GOLDEN_DATASET",
                entity_id=golden_id,
                after={
                    "project_id": project_id,
                    "split": split,
                    "data_hash": data_hash,
                    "annotation_hash": annotation_hash,
                    "time_split_hash": time_split_hash,
                    "annotation_count": len(usable),
                    "baseline_replay_run_id": baseline_replay_run_id,
                },
            )
            # 冻结后把参与 Ground Truth 的标注同步转为 FROZEN，防止原地修改；
            # 同时写入黄金样本成员关系，后续比较只读取这份冻结清单。
            for row in usable:
                self._conn.execute(
                    "INSERT OR IGNORE INTO golden_dataset_annotations"
                    "(golden_dataset_id, annotation_id) VALUES(?,?)",
                    (golden_id, row["annotation_id"]),
                )
                if row["status"] == "APPROVED":
                    self._conn.execute(
                        "UPDATE annotations SET status = 'FROZEN', updated_at = ? "
                        "WHERE annotation_id = ?",
                        (now_iso(), row["annotation_id"]),
                    )
        return self.get_golden_dataset(golden_id)  # type: ignore[return-value]

    def list_golden_annotation_ids(self, golden_dataset_id: str) -> list[str]:
        """返回黄金样本冻结时纳入的标注 ID（SACW 6.3）。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT annotation_id FROM golden_dataset_annotations "
                "WHERE golden_dataset_id = ? ORDER BY annotation_id",
                (golden_dataset_id,),
            ).fetchall()
        return [str(row["annotation_id"]) for row in rows]

    def get_golden_dataset(self, golden_dataset_id: str) -> dict[str, Any] | None:
        """按 ID 读取黄金样本。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM golden_datasets WHERE golden_dataset_id = ?",
                (golden_dataset_id,),
            ).fetchone()
        return None if row is None else _row_to_dict(row)

    def list_golden_datasets(self) -> list[dict[str, Any]]:
        """列出全部黄金样本。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM golden_datasets ORDER BY frozen_at, golden_dataset_id",
            ).fetchall()
        return [_row_to_dict(row) for row in rows]

    # ------------------------------------------------------------------ 回放

    def create_replay_run(
        self,
        *,
        code_commit: str | None,
        config_hash: str | None,
        dataset_hash: str | None,
        notes: str | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        """登记一次程序回放。"""
        identifier = run_id or new_id("run")
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO replay_runs"
                "(run_id, code_commit, config_hash, dataset_hash, status, started_at, notes) "
                "VALUES(?,?,?,?,?,?,?)",
                (identifier, code_commit, config_hash, dataset_hash, "RUNNING", now_iso(), notes),
            )
        return self.get_replay_run(identifier)  # type: ignore[return-value]

    def finish_replay_run(self, *, run_id: str, status: str = "COMPLETED") -> dict[str, Any]:
        """结束一次回放。"""
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE replay_runs SET status = ?, finished_at = ? WHERE run_id = ?",
                (status, now_iso(), run_id),
            )
        return self.get_replay_run(run_id)  # type: ignore[return-value]

    def get_replay_run(self, run_id: str) -> dict[str, Any] | None:
        """按 ID 读取回放。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM replay_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        return None if row is None else _row_to_dict(row)

    def list_replay_runs(self) -> list[dict[str, Any]]:
        """列出全部回放。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM replay_runs ORDER BY started_at DESC",
            ).fetchall()
        return [_row_to_dict(row) for row in rows]

    def append_program_event(
        self,
        *,
        run_id: str,
        event_type: str,
        timeframe: str,
        payload: dict[str, Any],
        bar_id: str | None = None,
        at: str | None = None,
    ) -> dict[str, Any]:
        """追加一条程序事件（保留 run_id、来源 Bar 与时间）。"""
        event_id = new_id("evt")
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO program_events"
                "(event_id, run_id, event_type, timeframe, payload, bar_id, at) "
                "VALUES(?,?,?,?,?,?,?)",
                (
                    event_id,
                    run_id,
                    event_type,
                    timeframe,
                    _json(payload),
                    bar_id,
                    at or now_iso(),
                ),
            )
        return {
            "event_id": event_id,
            "run_id": run_id,
            "event_type": event_type,
            "timeframe": timeframe,
            "payload": payload,
            "bar_id": bar_id,
            "at": at or now_iso(),
        }

    def list_program_events(self, run_id: str) -> list[dict[str, Any]]:
        """列出某次回放的全部程序事件。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM program_events WHERE run_id = ? ORDER BY at, event_id",
                (run_id,),
            ).fetchall()
        out = []
        for row in rows:
            item = _row_to_dict(row)
            item["payload"] = _load(item["payload"])
            out.append(item)
        return out

    # --------------------------------------------------------------- 比较结果

    def save_comparison_run(
        self,
        *,
        golden_dataset_id: str,
        replay_run_id: str,
        matcher_version: str,
        summary: dict[str, Any],
        matches: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """持久化一次差异比较及其逐项匹配结果（SACW 6.5）。"""
        comparison_id = new_id("cmp")
        created_at = now_iso()
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO comparison_runs"
                "(comparison_id, golden_dataset_id, replay_run_id, matcher_version,"
                " created_at, summary) VALUES(?,?,?,?,?,?)",
                (
                    comparison_id,
                    golden_dataset_id,
                    replay_run_id,
                    matcher_version,
                    created_at,
                    _json(summary),
                ),
            )
            for item in matches:
                self._conn.execute(
                    "INSERT INTO match_results"
                    "(match_id, comparison_id, human_id, program_id, match_type,"
                    " errors, metrics) VALUES(?,?,?,?,?,?,?)",
                    (
                        new_id("match"),
                        comparison_id,
                        item.get("human_id"),
                        item.get("program_id"),
                        str(item.get("match") or item.get("match_type") or "UNKNOWN"),
                        _json(item.get("errors") or []),
                        _json(item.get("metrics") or {}),
                    ),
                )
        return self.get_comparison_run(comparison_id)  # type: ignore[return-value]

    def get_comparison_run(self, comparison_id: str) -> dict[str, Any] | None:
        """读取一次比较及其匹配结果。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM comparison_runs WHERE comparison_id = ?",
                (comparison_id,),
            ).fetchone()
            if row is None:
                return None
            matches = self._conn.execute(
                "SELECT * FROM match_results WHERE comparison_id = ? ORDER BY match_id",
                (comparison_id,),
            ).fetchall()
        item = _row_to_dict(row)
        item["summary"] = _load(item["summary"])
        item["matches"] = []
        for match in matches:
            entry = _row_to_dict(match)
            entry["errors"] = _load(entry["errors"])
            entry["metrics"] = _load(entry["metrics"])
            item["matches"].append(entry)
        return item

    def list_comparison_runs(self) -> list[dict[str, Any]]:
        """列出全部比较运行（不含逐项结果）。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM comparison_runs ORDER BY created_at, comparison_id",
            ).fetchall()
        out = []
        for row in rows:
            item = _row_to_dict(row)
            item["summary"] = _load(item["summary"])
            out.append(item)
        return out

    # -------------------------------------------------------- 边界覆盖（人工）

    def create_boundary_override(
        self,
        *,
        zone_annotation_id: str,
        override_lower: str,
        override_upper: str,
        override_center: str,
        operator: str,
        reason: str,
        config_hash: str | None = None,
        strategy_spec_version: str = "V1.4.8",
    ) -> dict[str, Any]:
        """创建人工边界覆盖（SACW 21.2），初始状态 PENDING_REVIEW。"""
        zone = self.get_annotation(zone_annotation_id)
        if zone is None:
            raise StoreError(f"zone annotation not found: {zone_annotation_id}")
        _require(zone["entity_type"] == "ZONE", "boundary override requires a ZONE annotation")
        payload = zone["payload"]
        for key in ("center", "lower", "upper"):
            _require(payload.get(key) is not None, f"zone annotation missing computed {key}")

        override_id = new_id("ovr")
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO manual_boundary_overrides"
                "(override_id, zone_annotation_id, original_lower, original_upper,"
                " original_center, override_lower, override_upper, override_center,"
                " operator, reason, review_status, created_at, strategy_spec_version,"
                " config_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    override_id,
                    zone_annotation_id,
                    str(payload["lower"]),
                    str(payload["upper"]),
                    str(payload["center"]),
                    str(override_lower),
                    str(override_upper),
                    str(override_center),
                    operator,
                    reason,
                    "PENDING_REVIEW",
                    now_iso(),
                    strategy_spec_version,
                    config_hash,
                ),
            )
            self._audit(
                actor=operator,
                action="BOUNDARY_OVERRIDE_CREATED",
                entity_type="ZONE",
                entity_id=zone_annotation_id,
                after={
                    "override_id": override_id,
                    "override_lower": str(override_lower),
                    "override_upper": str(override_upper),
                    "override_center": str(override_center),
                },
                reason=reason,
            )
        return self.get_boundary_override(override_id)  # type: ignore[return-value]

    def review_boundary_override(
        self,
        *,
        override_id: str,
        decision: str,
        reviewer: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """审核人工边界覆盖。批准后对应 Zone 标注模式改为带覆盖。"""
        _require(decision in {"APPROVED", "REJECTED"}, f"unknown decision: {decision}")
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT * FROM manual_boundary_overrides WHERE override_id = ?",
                (override_id,),
            ).fetchone()
            if row is None:
                raise StoreError(f"boundary override not found: {override_id}")
            self._conn.execute(
                "UPDATE manual_boundary_overrides SET review_status = ?, reviewer = ?,"
                " review_reason = ?, reviewed_at = ? WHERE override_id = ?",
                (decision, reviewer, reason, now_iso(), override_id),
            )
            zone_row = self._conn.execute(
                "SELECT * FROM annotations WHERE annotation_id = ?",
                (row["zone_annotation_id"],),
            ).fetchone()
            if zone_row is not None and decision == "APPROVED" and zone_row["status"] != "FROZEN":
                payload = _load(zone_row["payload"])
                payload["annotation_mode"] = "ANCHOR_ONLY_WITH_OVERRIDE"
                self._conn.execute(
                    "UPDATE annotations SET payload = ?, updated_at = ? WHERE annotation_id = ?",
                    (_json(payload), now_iso(), zone_row["annotation_id"]),
                )
            self._audit(
                actor=reviewer,
                action="BOUNDARY_OVERRIDE_REVIEWED",
                entity_type="ZONE",
                entity_id=row["zone_annotation_id"],
                after={"override_id": override_id, "decision": decision},
                reason=reason,
            )
        return self.get_boundary_override(override_id)  # type: ignore[return-value]

    def get_boundary_override(self, override_id: str) -> dict[str, Any] | None:
        """按 ID 读取边界覆盖。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM manual_boundary_overrides WHERE override_id = ?",
                (override_id,),
            ).fetchone()
        return None if row is None else _row_to_dict(row)

    def list_boundary_overrides(
        self,
        *,
        zone_annotation_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """列出边界覆盖。"""
        sql = "SELECT * FROM manual_boundary_overrides"
        params: list[Any] = []
        if zone_annotation_id is not None:
            sql += " WHERE zone_annotation_id = ?"
            params.append(zone_annotation_id)
        sql += " ORDER BY created_at"
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [_row_to_dict(row) for row in rows]

    # ------------------------------------------------------------ 回归样本

    def upsert_regression_case(self, case: dict[str, Any]) -> dict[str, Any]:
        """写入或更新一个 PB 回归样本（SACW 23.2）。"""
        _require_fields(dict(case), ("case_id", "title"), "REGRESSION_CASE")
        case_id = str(case["case_id"])
        now = now_iso()
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO regression_cases"
                "(case_id, case_version, title, scenario_description, spec_section, category,"
                " instrument_id, timeframes, dataset_id, dataset_hash, bar_ranges, preconditions,"
                " input_events, expected, stage, blocked_reason, expected_events,"
                " expected_state_transitions, expected_final_state,"
                " expected_absent_events, expected_absent_state_transitions,"
                " negative_assertion_reason, status, review_status, expectation_revision_id,"
                " updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(case_id) DO UPDATE SET"
                " case_version=excluded.case_version, title=excluded.title,"
                " scenario_description=excluded.scenario_description,"
                " spec_section=excluded.spec_section, category=excluded.category,"
                " expected=excluded.expected, stage=excluded.stage,"
                " blocked_reason=excluded.blocked_reason,"
                " expected_events=excluded.expected_events,"
                " expected_absent_events=excluded.expected_absent_events,"
                " expected_absent_state_transitions=excluded.expected_absent_state_transitions,"
                " negative_assertion_reason=excluded.negative_assertion_reason,"
                " status=excluded.status, updated_at=excluded.updated_at",
                (
                    case_id,
                    int(case.get("case_version", 1)),
                    str(case["title"]),
                    case.get("scenario_description"),
                    case.get("spec_section"),
                    case.get("category"),
                    case.get("instrument_id"),
                    _json(case.get("timeframes", [])),
                    case.get("dataset_id"),
                    case.get("dataset_hash"),
                    _json(case.get("bar_ranges", {})),
                    _json(case.get("preconditions", [])),
                    _json(case.get("input_events", [])),
                    case.get("expected"),
                    case.get("stage"),
                    case.get("blocked_reason"),
                    _json(case.get("expected_events", [])),
                    _json(case.get("expected_state_transitions", [])),
                    _json(case.get("expected_final_state", {})),
                    _json(case.get("expected_absent_events", [])),
                    _json(case.get("expected_absent_state_transitions", [])),
                    case.get("negative_assertion_reason"),
                    str(case.get("status", "PENDING")),
                    str(case.get("review_status", "PENDING_REVIEW")),
                    case.get("expectation_revision_id"),
                    now,
                ),
            )
        return self.get_regression_case(case_id)  # type: ignore[return-value]

    def get_regression_case(self, case_id: str) -> dict[str, Any] | None:
        """按 ID 读取回归样本。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM regression_cases WHERE case_id = ?",
                (case_id,),
            ).fetchone()
        if row is None:
            return None
        item = _row_to_dict(row)
        for key in (
            "timeframes",
            "bar_ranges",
            "preconditions",
            "input_events",
            "expected_events",
            "expected_state_transitions",
            "expected_final_state",
            "expected_absent_events",
            "expected_absent_state_transitions",
        ):
            item[key] = _load(item[key])
        return item

    def list_regression_cases(self) -> list[dict[str, Any]]:
        """列出全部回归样本。"""
        with self._lock:
            ids = [
                row["case_id"]
                for row in self._conn.execute(
                    "SELECT case_id FROM regression_cases ORDER BY case_id",
                ).fetchall()
            ]
        return [case for case in (self.get_regression_case(item) for item in ids) if case]

    def create_regression_run(
        self,
        *,
        code_commit: str | None,
        config_hash: str | None,
        dataset_hash: str | None,
        expectation_revision: str | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        """创建一次回归运行。"""
        identifier = run_id or new_id("regrun")
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO regression_runs"
                "(run_id, code_commit, config_hash, dataset_hash, expectation_revision,"
                " status, started_at) VALUES(?,?,?,?,?,?,?)",
                (
                    identifier,
                    code_commit,
                    config_hash,
                    dataset_hash,
                    expectation_revision,
                    "RUNNING",
                    now_iso(),
                ),
            )
        return self.get_regression_run(identifier)  # type: ignore[return-value]

    def finish_regression_run(
        self,
        *,
        run_id: str,
        status: str,
        summary: dict[str, Any],
    ) -> dict[str, Any]:
        """结束回归运行并写入汇总。"""
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE regression_runs SET status = ?, finished_at = ?, summary = ? "
                "WHERE run_id = ?",
                (status, now_iso(), _json(summary), run_id),
            )
        return self.get_regression_run(run_id)  # type: ignore[return-value]

    def get_regression_run(self, run_id: str) -> dict[str, Any] | None:
        """按 ID 读取回归运行。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM regression_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        item = _row_to_dict(row)
        item["summary"] = _load(item["summary"])
        return item

    def list_regression_runs(self) -> list[dict[str, Any]]:
        """列出全部回归运行。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM regression_runs ORDER BY started_at DESC",
            ).fetchall()
        out = []
        for row in rows:
            item = _row_to_dict(row)
            item["summary"] = _load(item["summary"])
            out.append(item)
        return out

    def record_assertion(
        self,
        *,
        run_id: str,
        case_id: str,
        assertion_kind: str,
        result: str,
        scope: str | None = None,
        target: str | None = None,
        window_start: str | None = None,
        window_end: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """记录一条断言结果（正向或负向同等权重）。"""
        _require(result in {"PASSED", "FAILED", "BLOCKED"}, f"unknown result: {result}")
        assertion_id = new_id("asrt")
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO regression_assertions"
                "(assertion_id, run_id, case_id, assertion_kind, scope, target,"
                " window_start, window_end, result, detail) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    assertion_id,
                    run_id,
                    case_id,
                    assertion_kind,
                    scope,
                    target,
                    window_start,
                    window_end,
                    result,
                    None if detail is None else _json(detail),
                ),
            )
        return {
            "assertion_id": assertion_id,
            "run_id": run_id,
            "case_id": case_id,
            "assertion_kind": assertion_kind,
            "scope": scope,
            "target": target,
            "window_start": window_start,
            "window_end": window_end,
            "result": result,
            "detail": detail,
        }

    def list_assertions(self, run_id: str) -> list[dict[str, Any]]:
        """列出某次运行的全部断言结果。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM regression_assertions WHERE run_id = ? "
                "ORDER BY case_id, assertion_id",
                (run_id,),
            ).fetchall()
        out = []
        for row in rows:
            item = _row_to_dict(row)
            item["detail"] = _load(item["detail"])
            out.append(item)
        return out

    # --------------------------------------------------------------- 快照

    def save_snapshot_artifact(
        self,
        *,
        dataset_id: str,
        snapshot_hash: str,
        status: str,
        path: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """保存初始状态快照的元数据。"""
        snapshot_id = new_id("snap")
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO snapshot_artifacts"
                "(snapshot_id, dataset_id, snapshot_hash, path, status, created_at, detail) "
                "VALUES(?,?,?,?,?,?,?)",
                (
                    snapshot_id,
                    dataset_id,
                    snapshot_hash,
                    path,
                    status,
                    now_iso(),
                    None if detail is None else _json(detail),
                ),
            )
        return {
            "snapshot_id": snapshot_id,
            "dataset_id": dataset_id,
            "snapshot_hash": snapshot_hash,
            "path": path,
            "status": status,
            "detail": detail,
        }

    def list_snapshot_artifacts(self, *, dataset_id: str | None = None) -> list[dict[str, Any]]:
        """列出快照元数据。"""
        sql = "SELECT * FROM snapshot_artifacts"
        params: list[Any] = []
        if dataset_id is not None:
            sql += " WHERE dataset_id = ?"
            params.append(dataset_id)
        sql += " ORDER BY created_at"
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        out = []
        for row in rows:
            item = _row_to_dict(row)
            item["detail"] = _load(item["detail"])
            out.append(item)
        return out
