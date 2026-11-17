#!/usr/bin/env python3
"""校验 .dsh/tasks/tasks.json 的结构与不变量。

用法：
    python .dsh/scripts/validate_tasks.py [--json]

退出码 0 表示通过；非 0 时打印每条错误，供 git hook 与 CI 使用。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
TASKS_FILE = PROJECT / ".dsh" / "tasks" / "tasks.json"
REQUIREMENTS_FILE = PROJECT / "requirements" / "REQUIREMENTS.md"

TASK_ID_RE = re.compile(r"^TASK-\d{3}$")
REQ_ID_RE = re.compile(r"^REQ-\d{3}$")
PRIORITIES = {"P0", "P1", "P2", "P3"}
COMPLEXITIES = {"S", "M", "L", "XL"}

REQUIRED_FIELDS = [
    "id",
    "title",
    "requirement_refs",
    "status",
    "priority",
    "complexity",
    "objective",
    "depends_on",
    "allowed_paths",
    "forbidden_paths",
    "acceptance",
    "test_plan",
]


def load() -> dict:
    try:
        return json.loads(TASKS_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(f"missing {TASKS_FILE}")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid JSON in {TASKS_FILE}: {exc}")


def known_requirements() -> set[str]:
    if not REQUIREMENTS_FILE.exists():
        return set()
    text = REQUIREMENTS_FILE.read_text(encoding="utf-8")
    return set(re.findall(r"\|\s*(REQ-\d{3})\s*\|", text))


def check_path(path: str) -> str | None:
    if not isinstance(path, str) or not path:
        return "path must be a non-empty string"
    if path.startswith("/"):
        return f"path must be relative to nautilus_pa/: {path}"
    if ".." in Path(path).parts:
        return f"path must not contain '..': {path}"
    if "\\" in path:
        return f"path must use forward slashes: {path}"
    return None


def main() -> int:
    data = load()
    errors: list[str] = []
    warnings: list[str] = []

    def err(message: str) -> None:
        errors.append(message)

    if data.get("schema_version") != 1:
        err("schema_version must be 1")

    states = set(data.get("state_machine", []))
    exceptions = set(data.get("exception_states", []))
    active = set(data.get("active_states", []))
    if not states:
        err("state_machine is empty")
    tasks = data.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise SystemExit("tasks must be a non-empty list")

    reqs = known_requirements()
    seen: dict[str, dict] = {}
    for index, task in enumerate(tasks):
        where = f"tasks[{index}]"
        if not isinstance(task, dict):
            err(f"{where}: must be an object")
            continue
        for field in REQUIRED_FIELDS:
            if field not in task:
                err(f"{where}: missing field {field}")
        task_id = task.get("id", "")
        where = task_id or where
        if not TASK_ID_RE.match(str(task_id)):
            err(f"{where}: id must match TASK-NNN")
        if task_id in seen:
            err(f"{where}: duplicate id")
        seen[task_id] = task

        status = task.get("status")
        if status not in states | exceptions:
            err(f"{where}: invalid status {status!r}")
        if task.get("priority") not in PRIORITIES:
            err(f"{where}: invalid priority {task.get('priority')!r}")
        if task.get("complexity") not in COMPLEXITIES:
            err(f"{where}: invalid complexity {task.get('complexity')!r}")

        refs = task.get("requirement_refs") or []
        if not isinstance(refs, list) or not refs:
            err(f"{where}: requirement_refs must be a non-empty list")
        for ref in refs:
            if not REQ_ID_RE.match(str(ref)):
                err(f"{where}: bad requirement ref {ref!r}")
            elif reqs and ref not in reqs:
                err(f"{where}: requirement {ref} not registered in requirements/REQUIREMENTS.md")

        if not (task.get("title") or "").strip():
            err(f"{where}: title is empty")
        if not (task.get("objective") or "").strip():
            err(f"{where}: objective is empty")

        acceptance = task.get("acceptance") or []
        if not isinstance(acceptance, list) or not acceptance:
            err(f"{where}: acceptance must be a non-empty list")
        test_plan = task.get("test_plan") or []
        if status in {"READY", "IN_PROGRESS", "IMPLEMENTED", "REVIEWING", "TESTING", "ACCEPTED"}:
            if not isinstance(test_plan, list) or not test_plan:
                err(f"{where}: {status} task needs a non-empty test_plan")

        allowed = task.get("allowed_paths") or []
        if not isinstance(allowed, list) or not allowed:
            err(f"{where}: allowed_paths must be a non-empty list")
        for path in allowed:
            problem = check_path(path)
            if problem:
                err(f"{where}: allowed_paths: {problem}")
        for path in task.get("forbidden_paths") or []:
            problem = check_path(path)
            if problem:
                err(f"{where}: forbidden_paths: {problem}")

        if status in active and not task.get("owner"):
            err(f"{where}: {status} task needs owner")
        if status == "ACCEPTED":
            evidence = task.get("evidence") or {}
            if not evidence.get("commands") and not task.get("notes"):
                warnings.append(f"{where}: ACCEPTED without evidence.commands")

    for task_id, task in seen.items():
        for dependency in task.get("depends_on") or []:
            if dependency == task_id:
                err(f"{task_id}: depends on itself")
            elif dependency not in seen:
                err(f"{task_id}: unknown dependency {dependency}")

    color: dict[str, str] = {}

    def visit(node: str, path: list[str]) -> None:
        if color.get(node) == "black":
            return
        if color.get(node) == "gray":
            cycle = path[path.index(node) :] + [node]
            err("dependency cycle: " + " -> ".join(cycle))
            return
        color[node] = "gray"
        path.append(node)
        for dependency in seen[node].get("depends_on") or []:
            if dependency in seen:
                visit(dependency, path)
        path.pop()
        color[node] = "black"

    for task_id in seen:
        visit(task_id, [])

    for message in warnings:
        print(f"warning: {message}")
    if errors:
        for message in errors:
            print(f"error: {message}", file=sys.stderr)
        print(f"{len(errors)} error(s)", file=sys.stderr)
        return 1
    print(f"ok: {len(seen)} task(s), states={','.join(sorted(states))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
