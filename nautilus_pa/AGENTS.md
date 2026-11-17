# AGENTS.md — nautilus_pa

本文件是 `nautilus_pa/` 的 AI 协作最高规范，DSH 会把本目录的 AGENTS.md 作为 workspace
instructions 自动加载。上游仓库根目录的 `AGENTS.md`、`AI_POLICY.md`、`CONTRIBUTING.md`
同时生效；两者冲突时，涉及上游代码与公开交互的以上游为准，涉及本项目流程的以本文件为准。

配套文件：
- 长期状态：`PROJECT_CONTEXT.md`
- 任务状态：`.dsh/tasks/tasks.json`（**唯一事实来源**）
- 角色与权限：`.dsh/config/agent_roles.md`、`.dsh/config/permission_policy.md`
- 契约：`.dsh/contracts/agent_input.md`、`.dsh/contracts/agent_output.md`
- 需求与验收：`requirements/REQUIREMENTS.md`、`requirements/ACCEPTANCE.md`

## 0. 五条铁律

1. **所有任务必须基于 `tasks.json` 流转。** 没有 TASK-ID 的工作不是正式工作：不在任务表里的
   修改、没有登记状态的修改，一律视为无效改动。
2. **代码修改必须带 Task ID 提交 Git。** 提交信息第一行固定为 `<TASK-ID> <摘要>`；
   不使用 Conventional Commits 前缀（上游规范禁止）。`nautilus_pa/` 没有独立仓库，
   改动随父仓库 `nautilus_trader` 一起提交；本子工程只负责**任务发布与状态流转**，
   不建立自己的分支、worktree 或提交体系。
3. **禁止无状态修改。** 开工前任务状态置 `IN_PROGRESS`，完成/审查/验收必须同步状态与证据；
   状态变化必须有测试输出、Diff 或审查结论支撑。
4. **不越界。** 只改任务 `allowed_paths` 内的文件；越界即停，回 `CLARIFICATION_REQUIRED`。
5. **不伪造完成。** 测试未运行不等于通过；Agent 自述完成不等于 ACCEPTED。

## 1. 启动协议（每个 Session 固定顺序）

1. 读本文件与 `PROJECT_CONTEXT.md`（L0 上下文）。
2. 读 `.dsh/tasks/tasks.json`，确认自己负责的任务与状态。
3. 读当前任务的契约（`taskctl.py show TASK-NNN`）与 `context_files` 中的文件（L2）。
4. 核对 Git 实际状态：`git -C .. status --short`、`git -C .. log -3 --oneline`。
   **不要相信摘要，要相信 Git 与文件。**
5. 若存在未完成的交接，读 `.dsh/sessions/SESSION_HANDOFF.md`，理解未完成项后再动手。

## 2. 任务流转

- 新建任务：`python .dsh/scripts/taskctl.py new --title ... --requirement REQ-NNN`，从 `DRAFT` 开始。
- 进入 `READY` 前必须通过六项拆分门槛，见 `.dsh/tasks/README.md`。
- 下发给子 Agent：`python .dsh/scripts/taskctl.py dispatch TASK-NNN --role developer`。
- 状态机：`DRAFT → READY → IN_PROGRESS → IMPLEMENTED → REVIEWING → TESTING → ACCEPTED`；
  异常 `BLOCKED / REJECTED / CANCELLED`。非法流转会被 `taskctl.py` 拒绝。
- 只有 Main 能改状态；子 Agent 在报告里给建议状态，不改文件。
- 每次改动后运行 `python .dsh/scripts/validate_tasks.py`。

## 3. Git 规则

- **唯一仓库**：`nautilus_pa/` 无独立 `.git`，Git 操作都在父仓库
  `/home/regotto/Code/nautilus_trader` 里做；本子工程路径在 Git 中表现为 `nautilus_pa/` 前缀。
- **子工程只管任务发布**：任务拆解、契约下发、状态流转、证据记录都在 `tasks.json`；
  不要为每个任务新建分支或 worktree，也不要建子工程的提交体系。
- 提交信息：`TASK-002 强制 PATCH 乐观锁`（Task ID + 空格 + 摘要，3–72 字符）。
- 一个任务一个逻辑提交；提交前 `git -C .. diff --check`、`git -C .. diff --stat`。
- 只 stage 任务范围内、且位于 `nautilus_pa/` 的文件；不要顺手带上父仓库其他改动
  或用户未提交的修改（父仓库可能有大量无关变更）。
- 若安装门禁（`bash .dsh/scripts/install_git_hooks.sh`，写入父仓库 `.git/hooks`），
  commit-msg 只校验 `nautilus_pa/` 前缀的暂存文件，父仓库其他路径直接放行；
  装与不装都不改变"提交由用户触发"这条。
- 未经用户明确要求，不执行 `git commit`、`git push` 或任何远程状态变更；
  禁止 `git reset --hard`、`git checkout -- .`、`git clean -fd`。
- 上游专属路径（`RELEASES.md`、`.github/`）不改。

## 4. 角色与权限

| 角色 | 能做什么 | 不能做什么 |
| --- | --- | --- |
| Main | 拆分、下发、审查 Diff、合并、验收、交接 | 跳过审查直接 ACCEPTED |
| Architect | 只读、拆任务、定接口与依赖 | 写任何文件 |
| Developer | 在 `allowed_paths` 内写代码与测试 | 越界、改文档/配置、动上游 |
| Reviewer | 只读、跑测试、按五门禁审查 | 改代码、替开发者修复 |

同一文件同一时刻只允许一个写者。并行任务靠**文件集互斥 + 依赖排序**隔离
（同一子工程的 Git 仓库只有一个，不靠分支/worktree 隔离）；`tasks.json` 的
`allowed_paths` 有交集的任务必须串行。详见 `.dsh/config/permission_policy.md`。

## 5. 上下文与 Token

- 按 L0→L1→L2→L3 分层加载，只读与当前验收相关的文件；Developer 不遍历整个 `src/`。
- Reviewer 先读 Diff，再按需扩读。
- 60% 预算停探索，80% 收敛 diff，95% 写交接并停止。详见 `.dsh/config/token_budget.md`。
- `PROJECT_CONTEXT.md` 增量更新，不写完整日志与代码。

## 6. 实现协议

- 先读相关代码与既有模式，再动手；最小 diff，不做无关重构与改名。
- 保持价格/数量/金额的精确算术（项目领域类型或 `Decimal`）。
- 接口变更必须显式列出，由 Main 判断是否需要架构确认。
- 写或更新能证明改动的测试；不弱化、不删除测试来换取通过。
- 不改生成产物，要改就改生成器。
- 不引入新依赖，除非任务明确要求。

## 7. 审查与验收

五门禁：需求一致性、架构一致性、代码质量、自动化测试、最终验收。
缺陷分级 P0（阻断）→ P3（技术债），P0/P1 不允许带缺陷验收。
ACCEPTED 十项清单见 `requirements/ACCEPTANCE.md`；测试未执行不算通过。

## 8. 会话交接

Session 结束前更新 `.dsh/sessions/SESSION_HANDOFF.md` 的 14 节；新 Session 按第 1 节启动协议
核对 Git 后继续。交接禁止做任何破坏性 Git 操作。

## 9. 与 DSH 的对应关系

| 规范 | DSH 落地 |
| --- | --- |
| 只读角色 | `architect` / `reviewer` preset 不挂载 write/edit/apply_patch |
| 限定读写 | `developer` preset + 任务 `allowed_paths` + 会话 sandbox `workspace-write` |
| 禁止无状态修改 | git commit-msg 门禁 + `tasks.json` 状态校验 |
| 上下文隔离 | 每个角色独立 preset/会话，子 Agent 只见契约与 `context_files` |
| 可恢复 | `tasks.json` + `SESSION_HANDOFF.md` + Git 历史 |

## 10. 沟通

- 面向用户的回复用中文；代码与提交信息按项目既有风格。
- 不确定就说不确定；阻塞就说阻塞点；不要用"已完成"掩盖未验证。
- 需要用户决策时，给出选项、影响与建议，而不是替用户决定。
