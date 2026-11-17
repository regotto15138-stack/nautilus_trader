# CHANGELOG

> 只记已 ACCEPTED 的变更；每条带 TASK-ID。未验收的改动不写这里。
> 上游 `RELEASES.md` 与本文件无关，不要动它。

## 2026-11-17

- TASK-001 建立 DSH 协作工程规范基线：新增 `.dsh/`（config/contracts/tasks/presets/
  scripts/sessions/reviews）、`AGENTS.md`、`PROJECT_CONTEXT.md`、`requirements/`、
  `docs/`、`development/`；新增三 Agent Preset（Architect/Developer/Reviewer）；
  新增任务状态机与 Git 提交门禁。
  - 影响：`nautilus_pa` 目录结构；不涉及 `src/`、`tests/`、`web/` 逻辑。
  - 验证：`validate_tasks.py` 通过；`dsh web --patch .dsh/presets/all.patch.yml --dump-config` 退出码 0。
