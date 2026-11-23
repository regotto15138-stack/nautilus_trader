# DECISIONS — 决策记录（ADR 风格）

> 只记"为什么这么定"，不记操作日志。新增决策追加一行 + 一段说明。
> 需求级变更另见 `requirements/CHANGE_REQUESTS.md`。

| ID | 日期 | 决策 | 状态 |
| --- | --- | --- | --- |
| D-001 | 2026-11-17 | `tasks.json` 为唯一任务状态源 | 生效 |
| D-002 | 2026-11-17 | 提交信息格式 `<TASK-ID> <摘要>`，不用 Conventional Commits | 生效 |
| D-003 | 2026-11-17 | 三 Agent Preset：Architect / Developer / Reviewer | 生效 |
| D-004 | 2026-11-17 | 权限靠工具面 + 沙箱 + allowed_paths 多层落实 | 生效 |
| D-005 | 2026-11-17 | 规格歧义不猜，标记 `SPEC_AMBIGUITY` 并留接口 | 生效 |
| D-006 | 2026-11-17 | 不使用 `git commit` 自动提交，提交由用户触发 | 生效 |
| D-007 | 2026-11-17 | `nautilus_pa/` 不建独立 git，随父仓库提交；子工程只管任务发布 | 生效 |
| D-010 | 2026-11-23 | 3M Bar 回测入场只在首个严格合格 Bar Open 全额成交；未定义的执行/风险/绩效能力受 OPEN_DECISIONS 门禁限制 | 生效（TASK-012） |

## D-010 规格执行与验收门禁补充

- **背景**：原规格未完全定义 3M 摆动配对、订单提交/回测首个成交事件、风险异常处置和绩效会计口径。
- **决定**：按 CR-001 与用户本轮选择，单一有效 3M SwingLow 确认后匹配其后首个合格 SwingHigh；多 SwingLow 优先级与替换规则留待 OD-09，未决场景禁止入场。Bar 回测入场仅在提交时间严格之后首根预期 3M Bar 存在且有效时，以该 Bar Open 全额成交；首根缺失/无效不跳过。Live/Paper、部分成交模拟、OD-03 风险异常处置、OD-08 绩效/Funding 会计在用户进一步批准前保持门禁关闭。
- **取舍**：确定性回测入场简化了订单簿/流动性模拟，但避免把回测约定外推至 Live；未定义风险和财务语义宁可阻断，不用默认值猜测。

## D-001 tasks.json 为唯一任务状态源

- **背景**：多份 md 各自记状态会漂移，Agent 之间无法对齐。
- **决定**：状态、范围、契约、证据全部在 `tasks.json`；md 只写规则与视图。
- **代价**：人读需要跑 `taskctl.py`；收益是机器可校验、可门禁。
- **替代方案**：多 md 并行维护（否决：必然漂移）。

## D-002 提交信息格式

- **背景**：上游 `AGENTS.md` 明确禁止 Conventional Commits。
- **决定**：第一行 `TASK-002 强制 PATCH 乐观锁`；Task ID 便于追溯。
- **校验**：`conventions.commit_subject` 正则 + commit-msg hook。

## D-003 三个 Agent Preset

- **背景**：需要"拆任务 / 写代码 / 审查"三种互斥职责。
- **决定**：Architect（无写工具、无 bash）、Developer（写工具 + bash，受 allowed_paths 约束）、
  Reviewer（只读 + bash 跑测试）。Main 不设 preset，用默认能力。
- **理由**：工具面即权限边界，比"提示词说别改"更硬。

## D-004 权限多层落实

- **背景**：DSH 沙箱只能设全局/会话级 root，无法按子目录授权。
- **决定**：四层——(1) preset 工具面；(2) 会话 cwd + 沙箱 workspace-write；
  (3) 任务 `allowed_paths`/`forbidden_paths`；(4) git hook 校验暂存路径。
- **残留风险**：Developer 在技术上能写任意路径，靠 hook + Diff 审查兜底。

## D-005 规格歧义处理

- **背景**：ATR_MA22、N 结构失效时点等规格未定义。
- **决定**：保留接口、默认关闭、标 `SPEC_AMBIGUITY`，不返回确定值。
- **理由**：错误固化业务语义的代价远高于暂不实现。

## D-006 不自动提交

- **背景**：上游规范要求"未经用户明确要求不 commit/push"。
- **决定**：Agent 只改工作区、给提交建议；`git commit`/`git push` 由用户触发。
- **例外**：用户明确要求时按其原话执行。

## D-007 子工程不独立管理 git

- **背景**：`nautilus_pa/` 没有自己的 `.git`，改动直接进父仓库
  `/home/regotto/Code/nautilus_trader`；用户明确"子工程只用关注任务发布"。
- **决定**：子工程的职责边界收在任务发布——需求拆解、`tasks.json` 流转、契约下发、
  证据与交接；不新建分支/worktree，不维护子工程提交体系。
- **落地**：并行任务按 `allowed_paths` 文件集互斥 + 依赖串行；Git 操作在父仓库根执行，
  只 stage `nautilus_pa/` 前缀文件；提交信息仍带 Task ID（D-002）。
- **代价**：并行隔离弱于独立 worktree，靠文件集互斥和串行依赖保证不互相覆盖。

## D-008 domain 不导入 NautilusTrader

- **背景**：策略语义需要脱离交易框架单独测试。
- **决定**：`src/pa_trend/domain/` 只依赖标准库与自身类型；框架适配留在 `adapters/`。
- **收益**：单测快、可移植；代价是适配层要多做一层转换。

## D-009 SQLite 作为 SACW 持久层

- **背景**：单机工作台需要事务、审计与只增不改的版本记录。
- **决定**：`var/sacw.sqlite3` 承载标注、回放、回归等运行态；parquet 目录只存行情。
- **约束**：运行态库不入 git；表结构变更走迁移。
