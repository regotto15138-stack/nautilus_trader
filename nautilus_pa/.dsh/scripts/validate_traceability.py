#!/usr/bin/env python3
"""Validate TASK-015 traceability, planned tests, and file-conflict ordering."""

import hashlib
import json
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[2]


def validate(data):
    errors = []
    tasks = {task["id"]: task for task in data["tasks"]}
    test_ids = set()

    def ancestors(task_id, seen=None):
        seen = set() if seen is None else seen
        for parent in tasks[task_id]["depends_on"]:
            if parent in tasks and parent not in seen:
                seen.add(parent)
                ancestors(parent, seen)
        return seen

    planned = [task for task in tasks.values() if int(task["id"][5:]) >= 16]
    for task in tasks.values():
        for entry in task.get("verification", []):
            test_id = entry.get("test_id")
            if not test_id or test_id in test_ids:
                errors.append(f'{task["id"]}: duplicate/missing TEST-ID {test_id}')
            test_ids.add(test_id)
    for task in planned:
        for field in ("atomicity", "inputs", "deliverables", "non_goals", "risk_rollback"):
            if not task.get(field):
                errors.append(f'{task["id"]}: missing {field}')
        for kind in ("spec", "plan"):
            for ref in task.get("traceability", {}).get(kind, []):
                if not (PROJECT / ref.split("#", 1)[0]).is_file():
                    errors.append(f'{task["id"]}: missing {kind} source {ref}')
            if not task.get("traceability", {}).get(kind):
                errors.append(f'{task["id"]}: empty {kind}')
        planned_paths = set(task.get("planned_new_paths", []))
        allowed_paths = set(task["allowed_paths"])
        if not planned_paths <= allowed_paths:
            errors.append(f'{task["id"]}: planned_new_paths outside allowed_paths')
        for command in task["test_plan"]:
            for token in command.split():
                if token.startswith("tests/") and not (PROJECT / token).exists():
                    provided_upstream = any(
                        token in tasks[parent].get("allowed_paths", [])
                        for parent in ancestors(task["id"])
                    )
                    if token not in planned_paths and not provided_upstream:
                        errors.append(f'{task["id"]}: missing undeclared test path {token}')
        checks = task.get("verification", [])
        if not checks or {entry["command"] for entry in checks} != set(task["test_plan"]):
            errors.append(f'{task["id"]}: TEST commands differ from test_plan')
        for check in checks:
            if not check.get("assertions"):
                errors.append(f'{task["id"]}: empty TEST assertions')
        for path in task["allowed_paths"]:
            for forbidden in task["forbidden_paths"]:
                if path == forbidden or (forbidden.endswith("/") and path.startswith(forbidden)):
                    errors.append(f'{task["id"]}: allowed path is forbidden {path}')
    for index, task in enumerate(planned):
        for other in planned[:index]:
            overlaps = any(
                left == right
                or (left.endswith("/") and right.startswith(left))
                or (right.endswith("/") and left.startswith(right))
                for left in task["allowed_paths"]
                for right in other["allowed_paths"]
            )
            if overlaps and other["id"] not in ancestors(task["id"]) and task["id"] not in ancestors(other["id"]):
                errors.append(f'file conflict unordered: {other["id"]} / {task["id"]}')
    for source, expected in data["planning_baseline"]["sources"].items():
        path = PROJECT / source
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            errors.append(f'baseline changed, impact review required: {source}')
    return errors


def main():
    data = json.loads((PROJECT / ".dsh/tasks/tasks.json").read_text(encoding="utf-8"))
    errors = validate(data)
    for error in errors:
        print("error:", error)
    if errors:
        return 1
    print(f'ok: traceability, unique TEST IDs, baseline hashes and file ordering ({len(data["tasks"])} tasks)')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
