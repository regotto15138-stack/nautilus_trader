"""PB 回归工作台测试（SACW V1.1.2 第 23 章）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from pa_trend.application.annotation_store import SacwStore
from pa_trend.application.regression import (
    RegressionRunner,
    load_cases,
    validate_cases,
)
from pa_trend.config.fingerprint import config_hash, config_snapshot
from pa_trend.config.loader import load_config
from pa_trend.config.validation import Stage, validate_startup
from pa_trend.domain.errors import ConfigurationError

CONFIGS_DIR = Path(__file__).resolve().parents[2] / "configs"


@pytest.fixture(scope="module")
def config():
    return load_config(CONFIGS_DIR)


@pytest.fixture(scope="module")
def cases() -> list[dict]:
    return load_cases(CONFIGS_DIR)


def test_all_51_cases_are_declared(cases: list[dict]) -> None:
    """PB-01 至 PB-51 必须全部登记，且样本自检无问题。"""
    ids = [case["case_id"] for case in cases]
    assert len(ids) == 51
    assert ids[0] == "PB-01" and ids[-1] == "PB-51"
    assert validate_cases(cases) == []


def test_cases_are_structured_not_free_text(cases: list[dict]) -> None:
    """每条样本都要有章节、类别、预期与状态。"""
    for case in cases:
        assert case["spec_section"]
        assert case["category"]
        assert case["expected"]
        assert case["status"]


def test_n_structure_invalidation_cases_are_blocked_by_spec(cases: list[dict]) -> None:
    """PB-12/PB-13 因 ATR 时点未定义而阻塞（SACW 27.6）。"""
    blocked = {case["case_id"] for case in cases if case["status"] == "BLOCKED_BY_SPEC_AMBIGUITY"}
    assert blocked == {"PB-12", "PB-13"}
    for case in cases:
        if case["case_id"] in blocked:
            assert "ATR" in case["blocked_reason"]


def test_negative_cases_declare_reason_and_forbidden_event(cases: list[dict]) -> None:
    """SACW 23.6 点名的负向用例必须带结构化禁止事件与依据。"""
    by_id = {case["case_id"]: case for case in cases}
    for case_id in ("PB-02", "PB-07", "PB-25", "PB-27", "PB-28"):
        case = by_id[case_id]
        assert case["expected_absent_events"], case_id
        assert case["negative_assertion_reason"], case_id
        assert case["negative_spec_section"], case_id


def test_validate_cases_detects_missing_and_duplicate() -> None:
    """自检能发现缺号、重复与缺字段。"""
    problems = validate_cases([{"case_id": "PB-01", "title": "t"}])
    assert any("missing PB-51" in item for item in problems)
    assert any("PB-01 missing expected" in item for item in problems)

    duplicated = [
        {"case_id": "PB-01", "title": "a", "expected": "b", "spec_section": "c", "status": "READY"},
        {"case_id": "PB-01", "title": "a", "expected": "b", "spec_section": "c", "status": "READY"},
    ]
    assert any("duplicate case_id" in item for item in validate_cases(duplicated))


def test_runner_records_assertions_and_summary(config, cases, tmp_path: Path) -> None:
    """全套运行必须写入断言与汇总，并与 run_id 绑定。"""
    store = SacwStore(tmp_path / "sacw.sqlite3")
    try:
        runner = RegressionRunner(
            store=store,
            config=config,
            config_hash=config_hash(config_snapshot(config)),
            code_commit="test-commit",
            dataset_hash="test-dataset",
            configs_dir=CONFIGS_DIR,
        )
        runner.sync_cases(cases)
        summary = runner.run()

        assert summary["total"] == 51
        assert summary["passed"] + summary["failed"] + summary["blocked"] == 51
        assert summary["failed"] == 0
        assert summary["blocked"] >= 45
        assert summary["duration_ms"] >= 0

        assertions = store.list_assertions(summary["run_id"])
        assert assertions
        run = store.get_regression_run(summary["run_id"])
        assert run["status"] == "PASSED"
        assert run["config_hash"] == config_hash(config_snapshot(config))
    finally:
        store.close()


def test_now_cases_actually_pass(config, cases, tmp_path: Path) -> None:
    """已实现部分的样本必须真正通过，而不是被静默跳过。"""
    store = SacwStore(tmp_path / "sacw.sqlite3")
    try:
        runner = RegressionRunner(
            store=store,
            config=config,
            config_hash="cfg",
            configs_dir=CONFIGS_DIR,
        )
        runner.sync_cases(cases)
        summary = runner.run()
        outcomes = {item["case_id"]: item["status"] for item in summary["cases"]}
        for case_id in ("PB-21", "PB-22", "PB-34", "PB-35", "PB-47", "PB-48"):
            assert outcomes[case_id] == "PASSED", case_id
        for case_id in ("PB-12", "PB-13"):
            assert outcomes[case_id] == "BLOCKED"
    finally:
        store.close()


def test_single_case_run_only_executes_that_case(config, cases, tmp_path: Path) -> None:
    """单例运行只包含指定样本。"""
    store = SacwStore(tmp_path / "sacw.sqlite3")
    try:
        runner = RegressionRunner(
            store=store,
            config=config,
            config_hash="cfg",
            configs_dir=CONFIGS_DIR,
        )
        runner.sync_cases(cases)
        summary = runner.run(case_ids=["PB-34"])
        assert summary["total"] == 1
        assert summary["cases"][0]["case_id"] == "PB-34"
        assert summary["cases"][0]["status"] == "PASSED"
    finally:
        store.close()


def test_unknown_case_id_is_rejected(config, cases, tmp_path: Path) -> None:
    """未知样本编号必须报错，而不是静默返回空结果。"""
    store = SacwStore(tmp_path / "sacw.sqlite3")
    try:
        runner = RegressionRunner(
            store=store,
            config=config,
            config_hash="cfg",
            configs_dir=CONFIGS_DIR,
        )
        runner.sync_cases(cases)
        with pytest.raises(ConfigurationError):
            runner.run(case_ids=["PB-99"])
    finally:
        store.close()


def test_startup_gate_passes_for_structure_stage(config) -> None:
    """结构研究阶段的门禁必须通过冻结配置。"""
    report = validate_startup(config, Stage.RESEARCH_STRUCTURE)
    assert report.accepted
    assert "risk" in report.skipped
