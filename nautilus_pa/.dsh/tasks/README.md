# 任务体系（tasks.json）

`tasks.json` 是本项目唯一任务状态来源。TASK 文件/聊天记录/执行计划都只是补充材料。

## 1. 状态机

    DRAFT → READY → IN_PROGRESS → IMPLEMENTED → REVIEWING → TESTING → ACCEPTED

异常状态：BLOCKED（等待外部条件）、REJECTED（审查不通过，回到 IN_PROGRESS 返工）、
CANCELLED（明确终止）。

| 状态 | 含义 | 进入条件（必须有证据） |
| --- | --- | --- |
| DRAFT | 想法或未拆分需求 | 无 |
| READY | 可下发 | 通过下面 6 项拆分门槛，`allowed_paths`/acceptance 已填 |
| IN_PROGRESS | 有 Agent 在写 | 已下发输入契约，登记 owner（`branch` 字段可选，只记父仓库当前分支，不建任务分支） |
| IMPLEMENTED | 代码完成 | 自测通过，报告 Status=DONE |
| REVIEWING | 审查中 | 有 Diff 与审查者 |
| TESTING | 独立验证 | Reviewer 开始跑测试，或有专项 Tester |
| ACCEPTED | 验收通过 | 十项验收清单全满足（见 `requirements/ACCEPTANCE.md`） |

铁律：
- Agent 自称完成 ≠ IMPLEMENTED，必须有测试输出。
- Reviewer 说通过 ≠ ACCEPTED，Main 还要核需求、范围、Diff、文档。
- 测试未执行 ≠ 通过。

## 2. 拆分门槛（6 项，缺一不进 READY）

1. **可追溯**：至少一个 `requirement_refs`，指向 `requirements/REQUIREMENTS.md`。
2. **完整**：目标、输入、输出、验收、测试计划齐全。
3. **独立**：能单独验收；需要同时改多个互不相关模块的，继续拆。
4. **依赖无环**：`depends_on` 构成 DAG，且依赖任务状态已 ACCEPTED 或同批可并行。
5. **测试明确**：验收标准能落到具体命令/断言。
6. **风险明确**：列出失败模式与回滚方式。

## 3. 粒度参考

| 类型 | 例子 | 复杂度 |
| --- | --- | --- |
| 单点修复 | 修正 PATCH 乐观锁校验 | S |
| 单模块功能 | 新增一个查询 API + 测试 | M |
| 跨层功能 | 回放比较引擎改为读持久化事件 | L |
| 架构调整 | 拆分引擎/存储边界 | XL |

一个任务应能在一次 Agent 回合内完成，且改动 ≤ 约 400 行。

## 4. ID 与文件

- 任务 ID：`TASK-NNN`，三位递增，不复用。
- 需求 ID：`REQ-NNN`，定义在 `requirements/REQUIREMENTS.md`。
- 任务详述（可选）：`.dsh/tasks/TASK-NNN.md`，从 `_TASK_TEMPLATE.md` 复制。
- 机器可读字段以 `tasks.json` 为准；两者冲突时以 `tasks.json` 为准并修正 md。

## 5. 常用命令

    python .dsh/scripts/taskctl.py list
    python .dsh/scripts/taskctl.py show TASK-002
    python .dsh/scripts/taskctl.py new --title "..." --requirement REQ-001 --priority P1
    python .dsh/scripts/taskctl.py set-status TASK-002 IN_PROGRESS --evidence "契约已下发"
    python .dsh/scripts/taskctl.py dispatch TASK-002 --role developer
    python .dsh/scripts/validate_tasks.py      # 校验 schema、DAG、状态与路径

## 6. 新项目复用与 Session 启动

新项目协作规范模板位于 `requirements/templates/ai-project-bootstrap/`。复制前按目标仓库约束、代码栈、风险及 Git 拓扑裁剪；不可复制本项目的交易规则、硬编码路径或独立提交约定。

每次 Session 开始按 `AGENTS.md` 固定协议：读项目规范/状态 → 核唯一任务台账及当前 TASK → 读契约与必要上下文 → 核 Git 状态/最近提交 → 核未完成交接 → 确认任务处于可开工状态。历史对话与 handoff 仅是线索，实际任务状态与工作区文件优先。

## 7. 提交规则

`nautilus_pa/` 没有独立 git，改动随父仓库 `/home/regotto/Code/nautilus_trader` 提交，
路径在提交里表现为 `nautilus_pa/` 前缀；子工程只负责任务发布，不建任务分支/worktree（D-007）。

提交信息第一行固定：

    TASK-002 强制 PATCH 乐观锁

- Task ID 必须在 `tasks.json` 中存在，状态为 IN_PROGRESS/IMPLEMENTED/REVIEWING/TESTING。
- 改动文件必须在任务的 `allowed_paths` 内，且不命中 `forbidden_paths`；
  校验只看 `nautilus_pa/` 前缀的暂存文件，父仓库其他路径不影响。
- 由 `.dsh/scripts/check_commit.py` 在 commit-msg / pre-commit 阶段强制；
  安装 hook 写入父仓库 `.git/hooks`（可选，见 `permission_policy.md` §3）。
