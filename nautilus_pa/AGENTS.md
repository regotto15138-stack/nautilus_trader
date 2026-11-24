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
4. **不越界。** 只改任务 `allowed_paths` 内的文件；越界即停，返回 `BLOCK_AND_REPORT`，
   由 Main 置 BLOCKED 并提出 Change Request（替代原先把报告码混同任务状态的表述）。
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
- 接口变更必须显式列出，并按下节的 L2/L3 人工审批要求执行。
- 写或更新能证明改动的测试；不弱化、不删除测试来换取通过。
- 不改生成产物，要改就改生成器。
- 不引入新依赖，除非任务明确要求。

## 6.1 Architecture Stability & Minimal Change Policy

本工程以架构稳定、增量修改为默认原则。唯一详细契约见
[架构保护与变更控制](docs/architecture/ARCHITECTURE_CONTRACT.md)，TASK 生成与执行必须遵循：

1. SPEC 修改不自动授权代码修改；代码只由明确批准的 TASK 授权。
2. TASK 必须明确 L0/L1/L2/L3、文件白名单、变更权限、兼容约束、影响分析与真实人工授权。
3. 默认禁止前后端、公共 API、数据库和模块架构重构；仅单独批准的 L3 任务允许架构重构。
4. 优先最小必要补丁，不顺带改名、清理或重构；不擅自改变接口、职责、数据契约及未授权的外部行为。
5. 新 SPEC 与架构冲突时停止受影响任务，提交 Change Request，不自行扩大范围。
6. 修改须经过 Git Diff 范围检查、相关回归、接口/数据契约检查与架构审查；越权修改不得合并。
7. Main 负责保护审批及台账；执行者不能通过自行修改契约、审批字段或门禁获得额外权限。

SPEC → 影响分析 → 最小 PLAN/TASK → 授权范围内执行 → 门禁 → 审查；架构变更由人批准。
执行沙箱与合并门禁的能力区别及当前未启用部分以契约说明为准，不把提示词视为权限隔离。

## 7. 审查与验收

五门禁：需求一致性、架构一致性、代码质量、自动化测试、最终验收。
缺陷分级 P0（阻断）→ P3（技术债），P0/P1 不允许带缺陷验收。
ACCEPTED 十项清单见 `requirements/ACCEPTANCE.md`；测试未执行不算通过。

## 8. 会话交接

Session 结束前更新 `.dsh/sessions/SESSION_HANDOFF.md` 的 14 节；新 Session 按第 1 节启动协议
核对 Git 后继续。交接禁止做任何破坏性 Git 操作。

交接前置条件（缺一项就不算完成交接）：

1. `tasks.json` 里本 Session 动过的任务状态与证据已落盘，`python .dsh/scripts/validate_tasks.py` 通过。
2. 第 13 节"Token 使用"按 `.dsh/config/token_budget.md` 第 8 节填写：请求数、input、cache_read、
   output、所用模型、是否发生过模型/推理强度/执行器切换。
3. 第 4 节"未完成"写的是具体下一步与阻塞点，不是"继续推进"；第 10 节给出下个 Session 的前 3 步。
4. 第 6 节记录的提交/未提交改动与 `git -C .. status --short` 一致；未提交改动必须写明原因。
5. 开发类 Session 结束前已按第 12 节完成复盘，或明确写出"未复盘 + 原因"。

## 9. 与 DSH 的对应关系

| 规范 | DSH 落地 |
| --- | --- |
| 只读角色 | `architect` / `reviewer` preset 不挂载 write/edit/apply_patch |
| 限定读写 | `developer` preset + 任务 `allowed_paths` + 会话 sandbox `workspace-write` |
| 禁止无状态修改 | git commit-msg 门禁 + `tasks.json` 状态校验 |
| 上下文隔离 | 每个角色独立 preset/会话，子 Agent 只见契约与 `context_files` |
| 可恢复 | `tasks.json` + `SESSION_HANDOFF.md` + Git 历史 |

## 10. 每次 AI Session 启动与项目级协作范式

项目启动/每次新 Session 必须遵循此顺序，不能以历史聊天摘要替代文件事实：

1. 读取本文件、`PROJECT_CONTEXT.md`，确认上游仓库 `AGENTS.md`、`AI_POLICY.md`、`CONTRIBUTING.md` 的约束仍生效。
2. 读取 `.dsh/tasks/tasks.json` 和 `.dsh/tasks/README.md`，确认当前 TASK、状态、owner、依赖、允许/禁止路径；未登记任务先登记 REQ/TASK，不进行正式修改。
3. 读取当前任务契约与其 `context_files`；只按 L0（项目约束/状态）→L1（模块接口）→L2（任务文件/相关源码）→L3（执行输出/Diff）加载，不扫描无关目录。
4. 核对父仓库 `git status --short`、`git log -3 --oneline`，并阅读未完成的 `SESSION_HANDOFF.md`（若存在）；不得覆盖、清理或归因不明的用户改动。
5. 只有任务通过六项拆分门槛并进入 `READY` 后才可开始；开工改为 `IN_PROGRESS`、登记 owner 和证据。实现后依次审查、测试、最终验收；不可把未运行测试说成通过。

通用协作规则：Main 管全局状态、拆任务、范围和最终验收；Architect/Reviewer 默认只读；Developer 只在 `allowed_paths` 内修改；单文件单写者，路径重叠任务串行。子 Agent 仅接收目标、输入、接口、依赖、范围、验收、验证与预算等最小契约；超界、缺规格、接口冲突时先停并申请澄清。对话/模型记忆为临时载体，只有通过验证并记录到权威项目文件的状态才可跨 Session 依赖。

预算和交接：按 `.dsh/config/token_budget.md` 的实际可用预算执行（60%停止探索、80%收敛、95%保存状态并交接）；这些阈值是管理策略，不得伪装为 DSH 硬限制。达到交接条件时检查任务/成员状态、Git Diff、测试证据，必要时增量更新 `PROJECT_CONTEXT.md` 并填写 `.dsh/sessions/SESSION_HANDOFF.md`；不为交接执行破坏性 Git 操作。

新建项目时先复用 `requirements/templates/ai-project-bootstrap/`，再按项目栈/风险裁剪；不得把 nautilus_pa 的交易域约束、路径、提交规范误植到其他项目。当前执行计划见 `planning/EXECUTION_PLAN.md`；归档来源见 `requirements/archive/DSH 大型项目开发操作标准.md`，与现有规范冲突时依本文件第 0 节优先级处理。

## 11. 沟通

- 面向用户的回复用中文；代码与提交信息按项目既有风格。
- 不确定就说不确定；阻塞就说阻塞点；不要用"已完成"掩盖未验证。
- 需要用户决策时，给出选项、影响与建议，而不是替用户决定。

## 12. 开发复盘（每个开发类 Session 收尾必做）

"开发复盘"和"会话交接"是两件事：交接是给下一个 Agent 的现状，复盘是给后续所有 Agent 的方法约束。
只有复盘结论**写进规则文件**（本文件、`.dsh/config/`、任务 `notes`），才算生效；只写在聊天里的不算。

**触发条件（满足任一条就复盘）：**

1. 出现 P0/P1 缺陷、返工、被用户指出错误。
2. 同一文件在同一 Session 内被读 5 次以上，或同一结论被反复核实。
3. 中途切换模型、推理强度或执行器；出现额度/限流报错；单次请求输入超过 200K。
4. 一个 Session 累计超过第二节某复杂度预算的 80%，或触发过交接阈值。
5. 任务从 `IMPLEMENTED` 被退回 `IN_PROGRESS`，或审查结论为 NEEDS_REVISION/REJECT。

**复盘内容（五问，按顺序写）：**

1. 现象：用可核对的事实描述（文件、行号、账本数字），不写"感觉慢"。
2. 根因：如果直接原因是"上下文里少了 X"或"重复做了 Y"，继续问为什么会这样。
3. 是规范缺口还是个人失误：规范缺口进规则文件；个人失误进任务 `notes` 或交接第 8 节。
4. 下次的动作：必须可执行（如"开工前先跑 `taskctl.py list --status DRAFT`"），不能写"更加小心"。
5. 生效位置：本 Session 内改完规则文件，并在交接第 8 节登记改了什么、为什么改。

**写法约束：**

- 规则文件只增不删：新规则与旧规则冲突时改旧规则并写明替代关系，不并列保留两条。
- 一个规则只写一处；在别处只引用（如"见第 8 节前置条件"），不复制。
- 不改上游 `nautilus_trader` 的 `AGENTS.md`；上游规则与本文件的复盘规则同时成立时，以上游为准。

**Token 复盘额外要求：** 涉及消耗异常时，必须按 `.dsh/config/token_budget.md` 第 5 节区分"可见上下文"
与"请求级用量"，并给出请求数、缓存未命中次数与全价输入合计；只有聊天观察、没有账本数字的结论不算复盘。
