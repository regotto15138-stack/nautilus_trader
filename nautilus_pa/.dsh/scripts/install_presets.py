#!/usr/bin/env python3
"""把三个 Agent Preset 合并进 DSH profile 的 cordis.patch.yml。

    python .dsh/scripts/install_presets.py            # 安装
    python .dsh/scripts/install_presets.py --dry-run  # 只打印将追加的内容
    python .dsh/scripts/install_presets.py --remove   # 卸载

profile 目录默认取 $DSH_PROFILE_DIR，否则 ~/.dsh/profiles/web。
安装后需要重启 dsh（例如重启 dsh web）才会出现新的 preset。
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import time
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
SOURCE = PROJECT / ".dsh" / "presets" / "all.patch.yml"
BEGIN = "# >>> nautilus_pa .dsh/presets (Architect / Developer / Reviewer)"
END = "# <<< nautilus_pa .dsh/presets"


def profile_dir(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).expanduser()
    env = os.environ.get("DSH_PROFILE_DIR")
    if env:
        return Path(env)
    return Path.home() / ".dsh" / "profiles" / "web"


def preset_rows() -> str:
    """返回竖顶层 patch 片段。

    profile 的 cordis.patch.yml 是 *patch* 文件：裸 `- id: xxx` 表示修改已有条目，
    新条目必须写在 `- insert:` 之下，否则会被 "entry not found" 丢弃。
    因此这里保留 all.patch.yml 里的 `- insert:` 结构，原样搬进 profile。
    """
    lines = SOURCE.read_text(encoding="utf-8").splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.startswith("- insert:"))
    except StopIteration:
        raise SystemExit(f"no '- insert:' block in {SOURCE}") from None
    body = list(lines[start:])
    while body and not body[-1].strip():
        body.pop()
    return "\n".join(body) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile-dir")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--remove", action="store_true")
    args = parser.parse_args()

    directory = profile_dir(args.profile_dir)
    target = directory / "cordis.patch.yml"
    if not target.exists():
        raise SystemExit(f"missing profile patch: {target}")

    text = target.read_text(encoding="utf-8")
    block = preset_rows()

    if args.remove:
        if BEGIN not in text:
            print("nothing to remove")
            return 0
        head, _, rest = text.partition(BEGIN)
        _, _, tail = rest.partition(END)
        new_text = head.rstrip("\n") + "\n" + tail.lstrip("\n")
        if args.dry_run:
            print(new_text)
            return 0
        shutil.copy2(target, target.with_suffix(".yml.bak." + time.strftime("%Y%m%d%H%M%S")))
        target.write_text(new_text, encoding="utf-8")
        print(f"removed presets from {target}; restart dsh to apply")
        return 0

    if "id: preset-architect" in text:
        print(f"presets already installed in {target}")
        return 0

    addition = f"\n{BEGIN}\n{block}{END}\n"
    if args.dry_run:
        print(addition)
        return 0

    backup = target.with_name(target.name + ".bak." + time.strftime("%Y%m%d%H%M%S"))
    shutil.copy2(target, backup)
    target.write_text(text.rstrip("\n") + "\n" + addition, encoding="utf-8")
    print(f"installed presets into {target}")
    print(f"backup: {backup}")
    print("restart dsh (for example: restart 'dsh web') to load Architect / Developer / Reviewer")
    return 0


if __name__ == "__main__":
    sys.exit(main())
