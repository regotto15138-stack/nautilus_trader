#!/usr/bin/env python3
"""Git 提交门禁：Task ID、任务状态、改动范围。

用法：
    python .dsh/scripts/check_commit.py commit-msg <message-file>
    python .dsh/scripts/check_commit.py staged          # 仅检查暂存范围（调试用）

规则：
1. 提交信息第一行必须是 "<TASK-ID> <摘要>"，且该任务存在于 tasks.json。
2. 任务状态必须是 READY/IN_PROGRESS/IMPLEMENTED/REVIEWING/TESTING（ACCEPTED 仅告警）。
3. 所有暂存的项目文件必须落在 allowed_paths 内，且不命中 forbidden_paths。
4. 不属于 nautilus_pa/ 的暂存文件（上游改动）跳过本门禁。
"""

from __future__ import annotations

import fnmatch
import json
import re
import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
TASKS_FILE = PROJECT / ".dsh" / "tasks" / "tasks.json"
COMMIT_STATES = {"READY", "IN_PROGRESS", "IMPLEMENTED", "REVIEWING", "TESTING", "ACCEPTED"}


def load_tasks() -> tuple[dict, list[dict]]:
    data = json.loads(TASKS_FILE.read_text(encoding="utf-8"))
    return data, data.get("tasks", [])


def staged_files() -> list[str]:
    output = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMRTUXB"],
        cwd=PROJECT,
        check=False,
        capture_output=True,
        text=True,
    ).stdout
    return [line for line in output.splitlines() if line.strip()]


def project_relative(path: str) -> str | None:
    prefix = PROJECT.name + "/"
    if path == PROJECT.name:
        return ""
    if path.startswith(prefix):
        return path[len(prefix) :]
    return None


def path_allowed(path: str, allowed: list[str], forbidden: list[str]) -> bool:
    def hit(pattern: str) -> bool:
        if pattern.endswith("/"):
            return path.startswith(pattern)
        return path == pattern or fnmatch.fnmatch(path, pattern)

    if any(hit(pattern) for pattern in forbidden):
        return False
    return any(hit(pattern) for pattern in allowed)


def fail(messages: list[str]) -> int:
    for message in messages:
        print(f"commit rejected: {message}", file=sys.stderr)
    return 1


def main(argv: list[str]) -> int:
    mode = argv[0] if argv else "commit-msg"
    data, tasks = load_tasks()
    by_id = {task["id"]: task for task in tasks}
    errors: list[str] = []

    subject = ""
    if mode == "commit-msg":
        if len(argv) < 2:
            return fail(["missing message file argument"])
        message = Path(argv[1]).read_text(encoding="utf-8")
        subject = message.strip().splitlines()[0] if message.strip() else ""
        pattern = data.get("conventions", {}).get(
            "commit_subject", r"^(TASK-\d{3})\s+\S.{2,71}$"
        )
        match = re.match(pattern, subject)
        if not match:
            return fail(
                [
                    "subject must be '<TASK-ID> <summary>' (for example: 'TASK-002 强制 PATCH 乐观锁')",
                    f"got: {subject!r}",
                ]
            )
        task_id = match.group(1)
        task = by_id.get(task_id)
        if task is None:
            return fail([f"{task_id} is not registered in .dsh/tasks/tasks.json"])
        if task.get("status") not in COMMIT_STATES:
            errors.append(
                f"{task_id} status is {task.get('status')}; commit needs one of {sorted(COMMIT_STATES)}"
            )
        if task.get("status") == "ACCEPTED":
            print(f"warning: {task_id} is already ACCEPTED", file=sys.stderr)
    else:
        task = None
        task_id = "(staged)"
        print("warning: 'staged' mode cannot verify the Task ID; use commit-msg for enforcement", file=sys.stderr)

    files = staged_files()
    scoped = [(project_relative(path), path) for path in files]
    in_project = [(relative, original) for relative, original in scoped if relative is not None]
    if not in_project:
        print("ok: no nautilus_pa changes staged; upstream-only commit passes", file=sys.stderr)
        return 0
    if mode != "commit-msg" or task is None:
        return fail(errors + ["project changes require a commit-msg check with a Task ID"])

    allowed = task.get("allowed_paths") or []
    forbidden = task.get("forbidden_paths") or []
    for relative, original in in_project:
        if not path_allowed(relative, allowed, forbidden):
            errors.append(f"{relative} is outside {task_id} allowed_paths / hits forbidden_paths")

    if errors:
        return fail(errors)
    print(f"ok: {task_id} covers {len(in_project)} staged project file(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
