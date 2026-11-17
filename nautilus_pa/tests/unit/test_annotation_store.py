"""标注存储测试（SACW V1.1.2 第 4、5 章）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from pa_trend.application.annotation_store import (
    SacwStore,
    StoreError,
    compute_time_split_hash,
    validate_annotation_payload,
)

SWING = {
    "direction": "LOW",
    "price": "3100.0",
    "occurred_at": "2025-01-01T10:00:00Z",
    "confirmed_at": "2025-01-01T10:45:00Z",
}


@pytest.fixture
def store(tmp_path: Path) -> SacwStore:
    instance = SacwStore(tmp_path / "sacw.sqlite3")
    yield instance
    instance.close()


def _create_swing(store: SacwStore, project_id: str, **overrides: object) -> dict:
    payload = dict(SWING, **overrides)
    return store.create_annotation(
        project_id=project_id,
        entity_type="SWING_POINT",
        timeframe="15M",
        payload=payload,
        instrument_id="ETH-USDT-SWAP.OKX",
        actor="tester",
    )


def test_project_is_created_once(store: SacwStore) -> None:
    """ensure_project 幂等。"""
    first = store.ensure_project()
    second = store.ensure_project()
    assert first["project_id"] == second["project_id"]
    assert first["spec_version"] == "V1.4.8"
    assert first["sacw_version"] == "V1.1.2"


def test_swing_point_validation_rejects_bad_time_order() -> None:
    """confirmed_at 早于 occurred_at 必须拒绝。"""
    with pytest.raises(StoreError):
        validate_annotation_payload(
            "SWING_POINT",
            {
                "direction": "LOW",
                "price": "1",
                "occurred_at": "2025-01-01T10:00:00Z",
                "confirmed_at": "2025-01-01T09:00:00Z",
            },
        )


def test_zone_validation_requires_two_anchors_and_mode() -> None:
    """ANCHOR_ONLY Zone 至少两个锚点，且必须声明模式。"""
    with pytest.raises(StoreError):
        validate_annotation_payload(
            "ZONE",
            {"zone_type": "SUPPORT", "anchor_swing_ids": ["a"], "annotation_mode": "ANCHOR_ONLY"},
        )
    with pytest.raises(StoreError):
        validate_annotation_payload(
            "ZONE",
            {"zone_type": "SUPPORT", "anchor_swing_ids": ["a", "b"]},
        )


def test_zone_anchor_only_requires_computed_bounds() -> None:
    """ANCHOR_ONLY 必须带后端计算的 center/lower/upper。"""
    with pytest.raises(StoreError):
        validate_annotation_payload(
            "ZONE",
            {
                "zone_type": "SUPPORT",
                "anchor_swing_ids": ["a", "b"],
                "annotation_mode": "ANCHOR_ONLY",
            },
        )


def test_n_structure_payload_cannot_forge_invalidation_price() -> None:
    """规格未定义失效 ATR 时点，标注不得写入失效价（SACW 27.6）。"""
    with pytest.raises(StoreError):
        validate_annotation_payload(
            "N_STRUCTURE",
            {
                "l1_swing_id": "l1",
                "h1_swing_id": "h1",
                "l2_swing_id": "l2",
                "h2_swing_id": "h2",
                "confirmed_at": "2025-01-01T00:00:00Z",
                "invalidation_price": "149.0",
            },
        )


def test_annotation_create_and_revise_history(store: SacwStore) -> None:
    """创建后可修订，旧版本保留为不可变历史。"""
    project = store.ensure_project()
    annotation = _create_swing(store, project["project_id"])
    assert annotation["revision"] == 1
    assert annotation["status"] == "DRAFT"

    revised = store.revise_annotation(
        annotation_id=annotation["annotation_id"],
        payload=dict(SWING, price="3110.0"),
        actor="reviewer",
        reason="价格修正",
    )
    assert revised["revision"] == 2
    assert revised["payload"]["price"] == "3110.0"

    revisions = store.list_revisions(annotation["annotation_id"])
    assert [item["revision"] for item in revisions] == [1, 2]
    assert revisions[0]["payload"]["price"] == "3100.0"


def test_illegal_status_transition_is_rejected(store: SacwStore) -> None:
    """DRAFT 不能直接跳到 APPROVED。"""
    project = store.ensure_project()
    annotation = _create_swing(store, project["project_id"])
    with pytest.raises(StoreError):
        store.transition_annotation(
            annotation_id=annotation["annotation_id"],
            status="APPROVED",
            actor="tester",
        )


def test_frozen_annotation_cannot_be_revised_or_deleted(store: SacwStore) -> None:
    """冻结标注不得原地修改或物理删除（SACW 5.2）。"""
    project = store.ensure_project()
    annotation = _create_swing(store, project["project_id"])
    for status in ("SUBMITTED", "REVIEWED", "APPROVED", "FROZEN"):
        store.transition_annotation(
            annotation_id=annotation["annotation_id"],
            status=status,
            actor="tester",
        )
    with pytest.raises(StoreError):
        store.revise_annotation(
            annotation_id=annotation["annotation_id"],
            payload=dict(SWING, price="9999"),
            actor="tester",
            reason="不应允许",
        )
    with pytest.raises(StoreError):
        store.soft_delete_annotation(
            annotation_id=annotation["annotation_id"],
            actor="tester",
            reason="不应允许",
        )


def test_ground_truth_requires_approved_labels_and_human_source(store: SacwStore) -> None:
    """黄金样本只接受 APPROVED/FROZEN 且来源为人工的标注。"""
    project = store.ensure_project()
    _create_swing(store, project["project_id"])
    with pytest.raises(StoreError):
        store.freeze_golden_dataset(
            project_id=project["project_id"],
            split="HOLDOUT",
            data_hash="hash",
            actor="tester",
        )

    ai = store.create_annotation(
        project_id=project["project_id"],
        entity_type="SWING_POINT",
        timeframe="15M",
        payload=dict(SWING, price="3200.0"),
        instrument_id="ETH-USDT-SWAP.OKX",
        actor="ai",
        label_source="AI_SUGGESTED",
        status="APPROVED",
    )
    assert ai["label_source"] == "AI_SUGGESTED"
    with pytest.raises(StoreError):
        store.freeze_golden_dataset(
            project_id=project["project_id"],
            split="HOLDOUT",
            data_hash="hash",
            actor="tester",
        )


def test_freeze_promotes_approved_labels_to_frozen(store: SacwStore) -> None:
    """冻结黄金样本后，参与的 APPROVED 标注自动转为 FROZEN。"""
    project = store.ensure_project()
    annotation = _create_swing(store, project["project_id"])
    for status in ("SUBMITTED", "REVIEWED", "APPROVED"):
        store.transition_annotation(
            annotation_id=annotation["annotation_id"],
            status=status,
            actor="tester",
        )

    golden = store.freeze_golden_dataset(
        project_id=project["project_id"],
        split="HOLDOUT",
        data_hash="data-hash",
        actor="tester",
        dataset_id="ds-1",
    )
    assert golden["annotation_count"] == 1
    assert golden["status"] == "FROZEN"
    assert store.get_annotation(annotation["annotation_id"])["status"] == "FROZEN"

    hash_after = store.annotation_hash(project["project_id"])
    assert golden["annotation_hash"] == hash_after


def test_boundary_override_requires_review_then_marks_zone(store: SacwStore) -> None:
    """人工边界覆盖必须先审核，批准后 Zone 模式改为带覆盖（SACW 21.2）。"""
    project = store.ensure_project()
    zone = store.create_annotation(
        project_id=project["project_id"],
        entity_type="ZONE",
        timeframe="4H",
        payload={
            "zone_type": "SUPPORT",
            "anchor_swing_ids": ["a", "b"],
            "annotation_mode": "ANCHOR_ONLY",
            "center": "3000",
            "lower": "2980",
            "upper": "3020",
        },
        instrument_id="ETH-USDT-SWAP.OKX",
        actor="tester",
    )
    override = store.create_boundary_override(
        zone_annotation_id=zone["annotation_id"],
        override_lower="2975",
        override_upper="3025",
        override_center="3000",
        operator="tester",
        reason="锚点覆盖不足",
    )
    assert override["review_status"] == "PENDING_REVIEW"
    assert override["original_lower"] == "2980"

    approved = store.review_boundary_override(
        override_id=override["override_id"],
        decision="APPROVED",
        reviewer="reviewer",
        reason="接受",
    )
    assert approved["review_status"] == "APPROVED"
    updated = store.get_annotation(zone["annotation_id"])
    assert updated["payload"]["annotation_mode"] == "ANCHOR_ONLY_WITH_OVERRIDE"


def test_program_events_keep_run_and_bar_reference(store: SacwStore) -> None:
    """程序事件必须保留 run_id 与来源 Bar。"""
    run = store.create_replay_run(
        code_commit="deadbeef",
        config_hash="cfg",
        dataset_hash="ds",
    )
    event = store.append_program_event(
        run_id=run["run_id"],
        event_type="ZONE_BROKEN",
        timeframe="4H",
        payload={"zone_id": "Z-1"},
        bar_id="bar-1",
        at="2026-01-01T00:00:00Z",
    )
    assert event["bar_id"] == "bar-1"
    events = store.list_program_events(run["run_id"])
    assert len(events) == 1
    assert events[0]["payload"]["zone_id"] == "Z-1"


def test_audit_log_records_every_write(store: SacwStore) -> None:
    """创建与状态迁移都进入审计日志。"""
    project = store.ensure_project()
    annotation = _create_swing(store, project["project_id"])
    store.transition_annotation(
        annotation_id=annotation["annotation_id"],
        status="SUBMITTED",
        actor="tester",
    )
    logs = store.list_audit_logs()
    actions = [item["action"] for item in logs]
    assert "PROJECT_CREATED" in actions
    assert "ANNOTATION_CREATED" in actions
    assert "ANNOTATION_STATUS_CHANGED" in actions
    assert all(item["at"] for item in logs)


def test_swing_defaults_to_human_judged_and_rejects_algorithm_derived() -> None:
    """工作台当前只能写 HUMAN_JUDGED（SACW 19.2、19.4）。"""
    data = validate_annotation_payload("SWING_POINT", dict(SWING))
    assert data["confirmation_policy"] == "HUMAN_JUDGED"
    assert data["human_judged_confirmed_at"] == SWING["confirmed_at"]
    assert data["confirmation_evidence"]["source"] == "SACW_WORKBENCH"

    with pytest.raises(StoreError, match="baseline replay"):
        validate_annotation_payload(
            "SWING_POINT",
            {
                **SWING,
                "confirmation_policy": "ALGORITHM_DERIVED",
                "algorithm_confirmed_at": SWING["confirmed_at"],
            },
        )


def test_zone_human_boundary_requires_ordered_human_bounds() -> None:
    """HUMAN_BOUNDARY 的人工边界必须有序且中心在区间内（SACW 21.3）。"""
    zone = validate_annotation_payload(
        "ZONE",
        {
            "zone_type": "SUPPORT",
            "anchor_swing_ids": ["a", "b"],
            "annotation_mode": "HUMAN_BOUNDARY",
            "human_lower": "2980",
            "human_upper": "3020",
            "human_center": "3000",
        },
    )
    assert zone["human_lower"] == "2980"
    assert zone["human_upper"] == "3020"

    with pytest.raises(StoreError, match="human_lower"):
        validate_annotation_payload(
            "ZONE",
            {
                "zone_type": "SUPPORT",
                "anchor_swing_ids": ["a", "b"],
                "annotation_mode": "HUMAN_BOUNDARY",
                "human_lower": "3020",
                "human_upper": "2980",
                "human_center": "3000",
            },
        )
    with pytest.raises(StoreError, match="human_center"):
        validate_annotation_payload(
            "ZONE",
            {
                "zone_type": "SUPPORT",
                "anchor_swing_ids": ["a", "b"],
                "annotation_mode": "HUMAN_BOUNDARY",
                "human_lower": "2980",
                "human_upper": "3020",
                "human_center": "3100",
            },
        )


def test_n_structure_blocks_all_invalidation_fields() -> None:
    """失效 ATR 时点未定时，整个失效字段组都不得伪造（SACW 20.1）。"""
    base = {
        "l1_swing_id": "l1",
        "h1_swing_id": "h1",
        "l2_swing_id": "l2",
        "h2_swing_id": "h2",
        "confirmed_at": "2025-01-01T00:00:00Z",
    }
    data = validate_annotation_payload("N_STRUCTURE", dict(base))
    assert data["invalidation_status"] == "SPEC_AMBIGUITY"
    with pytest.raises(StoreError, match="SPEC_AMBIGUITY"):
        validate_annotation_payload(
            "N_STRUCTURE",
            {**base, "invalidation_bar_id": "bar-1"},
        )


def test_golden_freeze_records_membership_and_baseline_replay(store: SacwStore) -> None:
    """冻结必须生成 baseline replay 并记录黄金样本成员关系（SACW 6.3）。"""
    project = store.ensure_project()
    swing = _create_swing(store, project["project_id"])
    for target in ("SUBMITTED", "REVIEWED", "APPROVED"):
        store.transition_annotation(
            annotation_id=swing["annotation_id"],
            status=target,
            actor="tester",
        )
    golden = store.freeze_golden_dataset(
        project_id=project["project_id"],
        split="HOLDOUT",
        data_hash="data-hash",
        actor="tester",
        dataset_id="ds-1",
        baseline_config_hash="cfg-1",
    )
    assert golden["baseline_replay_run_id"]
    run = store.get_replay_run(golden["baseline_replay_run_id"])
    assert run is not None
    assert run["status"] == "COMPLETED"
    assert store.list_golden_annotation_ids(golden["golden_dataset_id"]) == [
        swing["annotation_id"]
    ]
    frozen = store.get_annotation(swing["annotation_id"])
    assert frozen["status"] == "FROZEN"


def test_swing_manual_price_override_requires_reason() -> None:
    """手动改价必须带覆盖原因（SACW 3.4A、6.2）。"""
    with pytest.raises(StoreError, match="override_reason"):
        validate_annotation_payload(
            "SWING_POINT",
            {**SWING, "manual_price_override": True},
        )
    data = validate_annotation_payload(
        "SWING_POINT",
        {**SWING, "manual_price_override": True, "override_reason": "影线按 tick 取整"},
    )
    assert data["manual_price_override"] is True
    assert data["override_reason"] == "影线按 tick 取整"
    default = validate_annotation_payload("SWING_POINT", dict(SWING))
    assert default["manual_price_override"] is False


def test_protected_point_requires_source_swing_id() -> None:
    """保护点必须能追溯来源 SwingPoint（SACW 3.4D）。"""
    with pytest.raises(StoreError, match="source_swing_id"):
        validate_annotation_payload(
            "PROTECTED_POINT",
            {
                "direction": "LOW",
                "price": "3100",
                "valid_from": "2025-01-01T10:00:00Z",
            },
        )
    data = validate_annotation_payload(
        "PROTECTED_POINT",
        {
            "direction": "LOW",
            "price": "3100",
            "valid_from": "2025-01-01T10:00:00Z",
            "source_swing_id": "ann_swing_1",
        },
    )
    assert data["source_swing_id"] == "ann_swing_1"


def test_list_annotations_filters_by_time_and_keyword(store: SacwStore) -> None:
    """标注列表支持时间区间与关键字检索（SACW 11.1）。"""
    project = store.ensure_project()
    january = _create_swing(
        store,
        project["project_id"],
        occurred_at="2025-01-01T10:00:00Z",
        confirmed_at="2025-01-01T10:45:00Z",
    )
    february = _create_swing(
        store,
        project["project_id"],
        price="3200.0",
        occurred_at="2025-02-01T10:00:00Z",
        confirmed_at="2025-02-01T10:45:00Z",
    )
    filtered = store.list_annotations(
        project["project_id"],
        time_from="2025-01-15T00:00:00Z",
    )
    assert [item["annotation_id"] for item in filtered] == [february["annotation_id"]]
    same_day = store.list_annotations(
        project["project_id"],
        time_from="2025-02-01",
        time_to="2025-02-01",
    )
    assert [item["annotation_id"] for item in same_day] == [february["annotation_id"]]
    searched = store.list_annotations(project["project_id"], search="3200")
    assert [item["annotation_id"] for item in searched] == [february["annotation_id"]]
    assert len(store.list_annotations(project["project_id"], search="SWING")) == 2
    assert january["annotation_id"] != february["annotation_id"]


def test_copy_annotation_starts_new_draft(store: SacwStore) -> None:
    """复制生成新的 DRAFT，原标注与修订历史不受影响（SACW 3.6）。"""
    project = store.ensure_project()
    source = _create_swing(store, project["project_id"])
    copied = store.copy_annotation(
        annotation_id=source["annotation_id"],
        actor="tester",
        reason="duplicate",
    )
    assert copied["annotation_id"] != source["annotation_id"]
    assert copied["revision"] == 1
    assert copied["status"] == "DRAFT"
    assert copied["payload"]["price"] == source["payload"]["price"]
    actions = {item["action"] for item in store.list_audit_logs()}
    assert "ANNOTATION_COPIED" in actions


def test_time_split_hash_is_deterministic_and_bound_to_freeze(store: SacwStore) -> None:
    """切分哈希与顺序无关；冻结黄金样本时固化该哈希（SACW 6.3）。"""
    first = [
        {"split": "CALIBRATION", "range_start": "2025-01-01", "range_end": "2025-02-01"},
        {"split": "VALIDATION", "range_start": "2025-02-01", "range_end": "2025-03-01"},
        {"split": "HOLDOUT", "range_start": "2025-03-01", "range_end": "2025-04-01"},
    ]
    assert compute_time_split_hash(first) == compute_time_split_hash(list(reversed(first)))
    project = store.ensure_project()
    swing = _create_swing(store, project["project_id"])
    for target in ("SUBMITTED", "REVIEWED", "APPROVED"):
        store.transition_annotation(
            annotation_id=swing["annotation_id"],
            status=target,
            actor="tester",
        )
    for item in first:
        store.save_dataset_split(
            dataset_id="ds-hash",
            data_hash="data-hash",
            annotation_hash="ann-hash",
            **item,
        )
    splits = store.list_dataset_splits("ds-hash")
    assert {item["time_split_hash"] for item in splits} == {compute_time_split_hash(first)}
    golden = store.freeze_golden_dataset(
        project_id=project["project_id"],
        split="HOLDOUT",
        data_hash="data-hash",
        actor="tester",
        dataset_id="ds-hash",
    )
    assert golden["time_split_hash"] == compute_time_split_hash(first)



def test_freeze_generates_hash_for_zero_span_annotation_range(store: SacwStore) -> None:
    """单点标注（发生=确认）仍有可追溯的 time_split_hash（SACW 6.3）。"""
    project = store.ensure_project()
    swing = _create_swing(
        store,
        project["project_id"],
        occurred_at="2025-01-01T10:00:00Z",
        confirmed_at="2025-01-01T10:00:00Z",
    )
    for target in ("SUBMITTED", "REVIEWED", "APPROVED"):
        store.transition_annotation(
            annotation_id=swing["annotation_id"],
            status=target,
            actor="tester",
        )
    golden = store.freeze_golden_dataset(
        project_id=project["project_id"],
        split="HOLDOUT",
        data_hash="data-hash",
        actor="tester",
        dataset_id="ds-zero",
    )
    assert golden["time_split_hash"]

