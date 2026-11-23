#!/usr/bin/env python3
"""Split the V1.4.8 specification into verbatim, chapter-level Markdown files."""

from __future__ import annotations

import re
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
SOURCE = PROJECT / "requirements" / "archive" / "ETH-USDT-SWAP 多周期趋势策略开发规格V1.4.8.md"
OUTPUT = PROJECT / "requirements" / "spec_v1_4_8"


def main() -> None:
    text = SOURCE.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    chapters: list[tuple[int, str, list[str]]] = []
    current: tuple[int, str, list[str]] | None = None
    for line in lines:
        match = re.match(r"^# (\d+)\. (.+?)\s*$", line)
        if match:
            if current is not None:
                chapters.append(current)
            current = (int(match.group(1)), match.group(2), [line])
        elif current is not None:
            current[2].append(line)
    if current is not None:
        chapters.append(current)

    if len(chapters) != 25 or [item[0] for item in chapters] != list(range(1, 26)):
        raise SystemExit(f"Expected chapters 1..25, found {[item[0] for item in chapters]}")

    OUTPUT.mkdir(parents=True, exist_ok=True)
    index = [
        "# ETH-USDT-SWAP 多周期趋势策略 V1.4.8 需求文档",
        "",
        "> 来源：`../archive/ETH-USDT-SWAP 多周期趋势策略开发规格V1.4.8.md`。以下文件按原文一级章节拆分，正文原样保留；章节编号、子标题和规则均沿用冻结规格，不构成策略定义变更。",
        "",
        "| 章节 | 标题 | 文档 |",
        "|---:|---|---|",
    ]
    for number, title, body in chapters:
        filename = f"{number:02d}-{title}.md"
        chapter_text = "".join(body)
        heading = chapter_text.splitlines()[0]
        chapter_text = chapter_text.replace(heading, f"# REQ-V148-{number:02d} {heading[2:]}", 1)
        header = (
            f"> 来源规格：ETH-USDT-SWAP 多周期趋势策略开发规格 V1.4.8；原章节：第 {number} 章。\n\n"
        )
        (OUTPUT / filename).write_text(header + chapter_text, encoding="utf-8")
        index.append(f"| {number} | {title} | [{filename}](./{filename}) |")
    index.extend(["", "## 使用说明", "", "- 本目录中的 25 份文档与 requirements/archive 中归档规格第 1–25 章一一对应。", "- 文档仅按一级章节拆分，原文内部层级、表格、代码块、公式及措辞不作改写。", "- 本目录为便于查阅和需求追踪的分章副本；策略语义的唯一权威来源见 requirements/spec_v1_4_8/。", ""])
    (OUTPUT / "README.md").write_text("\n".join(index), encoding="utf-8")
    print(f"created {len(chapters)} chapter documents and README in {OUTPUT.relative_to(PROJECT)}")


if __name__ == "__main__":
    main()
