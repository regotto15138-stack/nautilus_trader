# 开发与治理记录

本目录保存有生命周期价值的工程治理材料，不承担任务状态的第二事实源。

| 文档 | 职责 |
|---|---|
| [DECISIONS.md](DECISIONS.md) | 已确认的技术/工程决策及原因 |
| [CHANGELOG.md](CHANGELOG.md) | 重要变更摘要 |
| [TASKS.md](TASKS.md) | 历史任务索引；当前状态以 `.dsh/tasks/tasks.json` 唯一为准 |
| [TASK_DEPENDENCIES.md](TASK_DEPENDENCIES.md) | 阶段任务依赖图，路线细节见 [执行计划](../planning/EXECUTION_PLAN.md) |

新建或更新任务必须通过 `.dsh/scripts/taskctl.py` 维护任务台账；不要在本目录手工维护任务状态。
