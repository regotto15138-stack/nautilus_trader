#!/usr/bin/env python3
"""tasks.json 的任务操作入口。

    python .dsh/scripts/taskctl.py list [--status READY]
    python .dsh/scripts/taskctl.py show TASK-002
    python .dsh/scripts/taskctl.py new --title "..." --requirement REQ-001 --priority P1
    python .dsh/scripts/taskctl.py set-status TASK-002 IN_PROGRESS --evidence "契约已下发"
    python .dsh/scripts/taskctl.py dispatch TASK-002 --role developer

只使用标准库。所有写操作都会保留 JSON 缩进与排序稳定性，并在写入后运行校验。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
TASKS_FILE = PROJECT / ".dsh" / "tasks" / "tasks.json"
VALIDATOR = PROJECT / ".dsh" / "scripts" / "validate_tasks.py"

BUDGET = {"S": 10000, "M": 20000, "L": 40000, "XL": 60000}
TRANSITIONS = {
    "DRAFT": {"READY", "CANCELLED"},
    "READY": {"IN_PROGRESS", "BLOCKED", "CANCELLED"},
    "IN_PROGRESS": {"IMPLEMENTED", "BLOCKED", "CANCELLED"},
    "IMPLEMENTED": {"REVIEWING", "TESTING", "IN_PROGRESS"},
    "REVIEWING": {"TESTING", "IN_PROGRESS", "REJECTED"},
    "TESTING": {"ACCEPTED", "IN_PROGRESS", "REJECTED"},
    "REJECTED": {"IN_PROGRESS", "CANCELLED"},
    "BLOCKED": {"IN_PROGRESS", "READY", "CANCELLED"},
    "ACCEPTED": set(),
    "CANCELLED": set(),
}


def load() -> dict:
    return json.loads(TASKS_FILE.read_text(encoding="utf-8"))


def save(data: dict) -> None:
    data["updated_at"] = date.today().isoformat()
    TASKS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result = subprocess.run([sys.executable, str(VALIDATOR)], check=False)
    if result.returncode != 0:
        print("warning: tasks.json saved but failed validation", file=sys.stderr)


def find(data: dict, task_id: str) -> dict:
    for task in data["tasks"]:
        if task["id"] == task_id:
            return task
    raise SystemExit(f"unknown task {task_id}")


def cmd_list(args: argparse.Namespace) -> int:
    data = load()
    rows = data["tasks"]
    if args.status:
        rows = [task for task in rows if task["status"] == args.status]
    for task in rows:
        print(
            f'{task["id"]:9} {task["status"]:12} {task["priority"]:2} '
            f'{task.get("complexity", "?"):2} {task["title"]}'
        )
    print(f"{len(rows)} task(s)")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    print(json.dumps(find(load(), args.task_id), ensure_ascii=False, indent=2))
    return 0


def cmd_new(args: argparse.Namespace) -> int:
    data = load()
    numbers = [int(task["id"].split("-")[1]) for task in data["tasks"]]
    task_id = f"TASK-{max(numbers, default=0) + 1:03d}"
    task = {
        "id": task_id,
        "title": args.title,
        "requirement_refs": [args.requirement],
        "status": "DRAFT",
        "priority": args.priority,
        "complexity": args.complexity,
        "owner": None,
        "role": None,
        "created_at": date.today().isoformat(),
        "updated_at": date.today().isoformat(),
        "depends_on": args.depends_on or [],
        "objective": args.objective or "",
        "context_files": args.context or [],
        "allowed_paths": args.allowed or [],
        "forbidden_paths": args.forbidden or [],
        "acceptance": args.acceptance or [],
        "test_plan": args.test or [],
        # 子工程无独立 git（D-007）；branch 只记父仓库当前分支，不代表任务分支。
        "branch": None,
        "commits": [],
        "evidence": {"commands": [], "reviews": [], "artifacts": []},
        "notes": args.notes or "",
    }
    data["tasks"].append(task)
    save(data)
    print(task_id)
    return 0


def cmd_set_status(args: argparse.Namespace) -> int:
    data = load()
    task = find(data, args.task_id)
    current, target = task["status"], args.status
    if target not in TRANSITIONS.get(current, set()) and not args.force:
        allowed = ", ".join(sorted(TRANSITIONS.get(current, set()))) or "none"
        raise SystemExit(f"illegal transition {current} -> {target}; allowed: {allowed}")
    task["status"] = target
    task["updated_at"] = date.today().isoformat()
    if args.owner is not None:
        task["owner"] = args.owner or None
    if args.evidence:
        evidence = task.setdefault("evidence", {}).setdefault("commands", [])
        evidence.append(args.evidence)
    if args.commit:
        task.setdefault("commits", []).append(args.commit)
    save(data)
    print(f"{task['id']}: {current} -> {target}")
    return 0


def cmd_dispatch(args: argparse.Namespace) -> int:
    data = load()
    task = find(data, args.task_id)
    total = BUDGET.get(task["complexity"], 20000)
    contract = {
        "task_id": task["id"],
        "role": args.role,
        "objective": task["objective"],
        "requirement_refs": task["requirement_refs"],
        "context_files": task.get("context_files", []),
        "allowed_paths": task["allowed_paths"],
        "forbidden_paths": task["forbidden_paths"],
        "interfaces": args.interfaces,
        "dependencies": task.get("depends_on", []),
        "acceptance": task["acceptance"],
        "test_plan": task["test_plan"],
        "token_budget": {"total": total, "input": int(total * 0.75), "output": total - int(total * 0.75)},
        "output_format": "AGENT_OUTPUT",
    }
    print(json.dumps(contract, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    listing = sub.add_parser("list")
    listing.add_argument("--status")
    listing.set_defaults(func=cmd_list)

    show = sub.add_parser("show")
    show.add_argument("task_id")
    show.set_defaults(func=cmd_show)

    new = sub.add_parser("new")
    new.add_argument("--title", required=True)
    new.add_argument("--requirement", required=True)
    new.add_argument("--priority", default="P2", choices=["P0", "P1", "P2", "P3"])
    new.add_argument("--complexity", default="M", choices=list(BUDGET))
    new.add_argument("--depends-on", nargs="*", default=[])
    new.add_argument("--objective", default="")
    new.add_argument("--context", nargs="*", default=[])
    new.add_argument("--allowed", nargs="*", default=[])
    new.add_argument("--forbidden", nargs="*", default=[])
    new.add_argument("--acceptance", nargs="*", default=[])
    new.add_argument("--test", nargs="*", default=[])
    new.add_argument("--notes", default="")
    new.set_defaults(func=cmd_new)

    status = sub.add_parser("set-status")
    status.add_argument("task_id")
    status.add_argument("status")
    status.add_argument("--evidence")
    status.add_argument("--commit")
    status.add_argument("--owner")
    status.add_argument("--force", action="store_true")
    status.set_defaults(func=cmd_set_status)

    dispatch = sub.add_parser("dispatch")
    dispatch.add_argument("task_id")
    dispatch.add_argument("--role", default="developer", choices=["architect", "developer", "reviewer"])
    dispatch.add_argument("--interfaces", default="保持现有公开接口")
    dispatch.set_defaults(func=cmd_dispatch)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
