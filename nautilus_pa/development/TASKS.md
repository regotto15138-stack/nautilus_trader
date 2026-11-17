# TASKS — 任务与执行计划映射

> **任务状态不在这里维护。** 唯一状态源是 `.dsh/tasks/tasks.json`；本文件只提供人读视图：
> 批次映射、当前焦点、以及怎么查看任务。

## 1. 怎么查看任务

    python .dsh/scripts/taskctl.py list                    # 全部任务概览
    python .dsh/scripts/taskctl.py list --status READY     # 按状态筛
    python .dsh/scripts/taskctl.py show TASK-002           # 单任务详情 + 契约
    python .dsh/scripts/taskctl.py dispatch TASK-002 --role developer  # 生成下发契约

## 2. 当前焦点

| 项 | 值 |
| --- | --- |
| 进行中 | 无 |
| 下一个可开工 | TASK-002（B00 PATCH 乐观锁，DRAFT，需先拆到 READY） |
| 阻塞项 | 无 |

待办只从 `tasks.json` 的 `READY` 取；本表由 Main 在每个 Session 交接时刷新。

## 3. 批次与阶段映射

| 阶段 | 批次 | REQ | 出口 |
| --- | --- | --- | --- |
| 0 | B00、B01a | REQ-001 | 阶段 0 出口条件 |
| 1 | B01b、B02a、B02b、B03a、B03b | REQ-002 | 里程碑 1 |
| 2 | B04、B05、B06 | REQ-003 | 里程碑 2 |
| 3 | B07、B08、B02c | REQ-004 | 里程碑 3 |
| 4 | B09 | REQ-005 | 里程碑 4 |
| 5 | B10b、B10c、B10d | REQ-006 | 里程碑 5 |

规则：阶段出口是下一阶段的准入门槛；不允许跳阶段、不允许"先写后面再补前面"。

## 4. 任务粒度

一个任务 = 一次可独立审查的改动。粒度参考：

| 复杂度 | 规模 | Token 预算 |
| --- | --- | --- |
| S | 单点修复、补一个断言 | 5–10K |
| M | 一个功能点 + 测试 | 10–20K |
| L | 一个模块内多文件改动 | 20–40K |
| XL | 跨模块重构 | 30–60K |

超过 XL 必须拆。拆分门槛见 `.dsh/tasks/README.md`。

## 5. 状态维护职责

- Main：唯一可以 `set-status` 的角色。
- 子 Agent：在 `AGENT_OUTPUT` 报告里给"建议状态"，不改文件。
- 每次状态变化后执行 `python .dsh/scripts/validate_tasks.py`。
- 被 ACCEPTED 的任务追加一条 `development/CHANGELOG.md`。
