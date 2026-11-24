# REQUIREMENTS — 需求登记表

> **需求的唯一权威来源。** 任务（TASK）必须挂在此文件中的某个 REQ 下；REQ 之下再拆 TASK。
> 需求正文以引用规格/执行计划/用户指令为准，本文件只登记"需求存在及其边界"，不复制规格全文。

## 0. 登记规则

1. 一个 REQ 只描述一个可验收的交付目标；REQ 是任务的父级，任务不得凭空产生。
2. 每个 REQ 必须有：来源、范围、验收依据、当前状态。
3. REQ 的语义来自规格或用户明确指令；**规格没写的，不猜**，登记到
   `CHANGE_REQUESTS.md` 的歧义登记表。
4. REQ 状态：`OPEN`（未开始）→ `ACTIVE`（有任务在做）→ `DONE`（全部子任务 ACCEPTED）
   → `SUPERSEDED`（被新需求取代）。
5. 变更 REQ 范围必须走 `CHANGE_REQUESTS.md` 的 CR 流程。

## 1. 需求来源的优先级

| 等级 | 来源 | 说明 |
| --- | --- | --- |
| S1 | 用户当前明确指令 | 与规格冲突时先问，不自行取舍 |
| S2 | `.md` 规格文档（V1.4.8 / SACW V1.1.2） | 业务语义基线 |
| S3 | `planning/EXECUTION_PLAN.md`（批次与出口条件） | 排期与门禁依据 |
| S4 | [归档的 DSH 大型项目开发操作标准](archive/DSH%20大型项目开发操作标准.md) | 协作流程参考（REQ-000）；现行规则以 `AGENTS.md` / `.dsh/` 为准 |
| S5 | README / 既有代码与测试 | 现状事实，不是新需求 |

## 2. 需求清单

| REQ | 名称 | 来源 | 验收依据 | 状态 |
| --- | --- | --- | --- | --- |
| REQ-015 | 四级变更控制与架构保护 | 2026-11-24 用户明确指令 | 变更契约、执行授权、Diff范围拒绝及工具测试 | ACTIVE |
| REQ-000 | DSH 协作工程规范基线 | `requirements/archive/DSH 大型项目开发操作标准.md` | 本目录 `.dsh/` 可运行 + `AGENTS.md` + `tasks.json` 校验通过 | DONE |
| REQ-001 | 阶段 0：前置修正与基础设施（B00、B01a） | `planning/EXECUTION_PLAN.md` 阶段 0 | 阶段 0 出口条件全绿 | ACTIVE |
| REQ-002 | 阶段 1：结构层验收闭环（B01b、B02a、B02b、B03a、B03b） | `planning/EXECUTION_PLAN.md` 阶段 1 | 里程碑 1 出口 | OPEN |
| REQ-003 | 阶段 2：策略决策闭环（B04、B05、B06） | `planning/EXECUTION_PLAN.md` 阶段 2 | 里程碑 2 出口 | OPEN |
| REQ-004 | 阶段 3：交易执行与风险闭环（B07、B08、B02c） | `planning/EXECUTION_PLAN.md` 阶段 3 | 里程碑 3 出口 | OPEN |
| REQ-005 | 阶段 4：策略验证闭环（B09） | `planning/EXECUTION_PLAN.md` 阶段 4 | 里程碑 4 出口 | OPEN |
| REQ-006 | 阶段 5：SACW 校准与配置治理（B10b、B10c、B10d） | `planning/EXECUTION_PLAN.md` 阶段 5 | 里程碑 5 出口 | OPEN |
| REQ-007 | SACW 标注工作台（规格 V1.1.2 第 3–6 章） | `SACW 规格 V1.1.2` | 工作台可用 + 标注库/比对/回归全部可跑 | ACTIVE |
| REQ-008 | V1.4.8 策略规格章节化需求文档 | 用户明确指令、V1.4.8 原规格 | 25 个章节文档完整拆分，保留原章节内容及层级 | DONE |
| REQ-009 | V1.4.8 扩充结构化规格 | 用户在 2026-11-21 明确确认的 A–E 规格决策及 2026-11-23 CR-001 | 结构化章节 spec 作为唯一权威来源；原规格归档；确认决策全部落入并交叉引用；未决项和能力门禁显式登记；执行/回测边界可复现 | ACTIVE |
| REQ-010 | 合并 V1.4.8 与 SACW 现状的后续技术实施计划 | 用户明确指令、`requirements/spec_v1_4_8/`、既有 `planning/EXECUTION_PLAN.md` | 执行计划反映已核对实现状态、规格阶段顺序、准入门槛及未决决策；供后续技术方案拆解 | ACTIVE |
| REQ-011 | SACW 前后端技术方案与接口契约 | 用户明确指令、SACW V1.1.2、`requirements/spec_v1_4_8/`、当前源码 | 前后端两份技术方案、统一接口契约、SACW 原规格分层归档；不修改实现代码 | DONE |
| REQ-012 | DSH AI 协作规范归档与项目启动模板 | 用户明确指令、`requirements/archive/DSH 大型项目开发操作标准.md` | 原规范完整归档；项目规范明确每次 AI 会话启动协议；提供新项目可复用模板/清单；不得覆盖已有未提交改动 | ACTIVE |
| REQ-014 | 增量原子任务与全链追溯 | 用户 2026-11-23 明确指令；三份 plan | 单目标独立可验证交付物、保留历史任务、DAG、SPEC→PLAN→TASK→TEST 校验 | DONE |
| REQ-013 | 工程文档结构与迁移清理 | 用户明确指令、现有工程文档 | 文档按职责归位；引用统一更新；已完整迁移的根目录文档副本删除；校验任务台账及链接 | DONE |

## 3. 需求明细

### REQ-000 DSH 协作工程规范基线

- **目标**：让本项目所有 AI 协作都有任务载体、权限边界、状态机、提交门禁与会话交接。
- **范围**：`.dsh/`（config/contracts/tasks/presets/scripts/sessions/reviews）、`AGENTS.md`、
  `PROJECT_CONTEXT.md`、`requirements/`、`docs/`、`development/`。
- **不做**：不改 `src/`、`tests/`、`web/`、`configs/` 的任何业务逻辑。
- **验收**：`validate_tasks.py` 通过；`dsh web --patch .dsh/presets/all.patch.yml --dump-config`
  退出码 0；三 preset 在 registry 中可见；提交门禁能拒绝无 Task ID 的提交。

### REQ-001 阶段 0：前置修正与基础设施

- **目标**：修掉 P0-A～P0-D 留下的契约漏洞，并把配置/快照/版本地基固化。
- **范围**：`src/pa_trend/`（B00 指定模块）、`tests/unit`、`tests/integration`。
- **验收依据**：`planning/EXECUTION_PLAN.md` 阶段 0 出口条件；规格中 B00 / B01a 的逐条要求。
- **当前任务**：TASK-002（B00 PATCH 乐观锁），DRAFT。

### REQ-002 阶段 1：结构层验收闭环

- **目标**：Swing / Zone / N 结构 / 边界干预在同一条回归链上闭环。
- **范围**：`domain/structure`、`domain/zigzag`、`application/matching`、
  `application/regression`、`tests/integration`。
- **约束**：不得臆测 N 结构失效的 ATR 时点（`SPEC_AMBIGUITY`）。
- **验收**：阶段 1 出口条件全绿，PB-01..11 等适用用例通过。

### REQ-003 阶段 2：策略决策闭环

- **目标**：4H/1H Setup、15M Signal 的决策链可复现、可断言。
- **串行约束**：B04→B05→B06 不可跳步（上游输出是下游输入）。
- **验收**：阶段 2 出口条件 + PB-14..21 类用例。

### REQ-004 阶段 3：交易执行与风险闭环

- **目标**：3M 执行、止损/风控、执行回放一致。
- **串行约束**：B07→B08 串行；B02c 依赖 B06 与 B08 验收，不与其前置实现并行。
- **验收**：阶段 3 出口条件 + 风控断言用例。

### REQ-005 阶段 4：策略验证闭环

- **目标**：整链策略级回测/验证结果可复现。
- **验收**：阶段 4 出口条件。

### REQ-006 阶段 5：SACW 校准与配置治理

- **目标**：参数校准（B10b/B10c）与配置审批治理（B10d）闭环。
- **验收**：阶段 5 出口条件；配置版本与审批记录可追溯。

### REQ-007 SACW 标注工作台

- **目标**：标注、Ground Truth 冻结、程序-人工差异比对、重放、回归在同一个工作台完成。
- **范围**：`presentation/api.py`、`application/annotation_store.py`、`application/matching.py`、
  `application/regression.py`、`web/`。
- **约束**：已冻结的 Ground Truth 不允许被静默改写；人工边界干预必须留审计。
- **验收**：工作台端到端可跑；冻结哈希不变；回归断言可通过。

### REQ-012 DSH AI 协作规范归档与项目启动模板

- **目标**：将原始《DSH 大型项目开发操作标准》完整归档，并把与本项目兼容的通用机制纳入项目 AGENTS/DSH 文档；提供可按项目裁剪的新工程模板及每轮 Session 启动清单。
- **范围**：归档原规范、`AGENTS.md`、`.dsh/` 文档、`PROJECT_CONTEXT.md`、`requirements/ACCEPTANCE.md` 与 `requirements/templates/ai-project-bootstrap/`；只改协作规范与模板，不改业务代码/工具实现。
- **边界**：`tasks.json` 仍为本项目唯一任务状态源；父仓库安全/贡献规范、本项目 AGENTS、用户授权规则优先于归档历史文本；新项目模板不得复制 nautilus_pa 专属交易规则、路径或仓库提交流程。
- **验收**：原文归档逐字节一致；旧路径为迁移指针；每次 Session 启动协议在 AGENTS 中明确；新项目模板覆盖唯一权威来源、任务/权限/上下文/验证/交接；链接、任务校验与 Diff 检查通过。

### REQ-013 工程文档结构与迁移清理

> 当前执行任务：TASK-011（详见 `.dsh/tasks/tasks.json`）。

- **目标**：将已拆解归档的权威文档集中置于 `requirements/`，将执行路线与协作运行手册区分，统一入口导航并清理已被完整迁移取代的旧路径。
- **范围**：文档、Markdown 链接、REQ/TASK 台账、任务/会话/项目索引；不改业务代码、测试、配置与生成产物。
- **边界**：删除前核对目标内容已逐字节/逐章节归档且无剩余引用；规格正文只允许一个权威位置，历史原文保留在 archive。不可删除仍承载当前执行计划、面向用户使用说明或独立工程事实的文档。
- **验收**：目录分层清晰；原规格/DSH 迁移指针和当前执行计划均在合理位置；所有受影响链接更新；只删除可证实已迁移且无引用的副本；任务校验、Markdown 相对链接校验、`git diff --check` 通过。

### REQ-010 合并 V1.4.8 与 SACW 现状的后续技术实施计划

- **目标**：把用户要求的 V1.4.8 结构化规格实施顺序与既有 SACW 执行批次、当前代码/测试/数据状态合并，形成供后续技术方案拆解的可信执行基线。
- **范围**：`planning/EXECUTION_PLAN.md`；本需求仅更新计划和必要的任务/REQ 台账，不实现策略功能。
- **来源**：用户明确指令；`requirements/spec_v1_4_8/`；既有执行计划。
- **验收**：执行计划标注核对日期、证据范围、已实现/部分实现/未实现和待复核事项；完整映射 P0-A…F、P1-A…D、P2、P3 到 B00…B10d 批次；明确依赖、PB-01…PB-51 与 OD-05 的 P1-A 准入门槛、OPEN_DECISIONS 风险限制、任务流转与阶段出口；不将未运行/未达出口写为完成。

## 4. 需求 → 任务映射

### REQ-015 四级变更控制与架构保护

- 来源：用户明确提出 L0–L3、强制任务边界及 Change Control Layer。
- 范围：AGENTS、架构保护文档、任务模板/契约/台账、工程下发/校验/Diff工具与工具测试。
- 边界：不改变业务架构/API/算法/数据库/前端；不改上游 CI，不伪造旧任务授权。
- 验收：缺授权、来源漂移、未就绪任务、越界 Diff 被拒绝；L2/L3 单独审批；
  删除/重命名两端及 Git 失败均检查；测试验证实际下发与失败不写台账；如实说明宿主权限和 CI 未启用部分。

映射关系只存在于 `.dsh/tasks/tasks.json` 的 `requirement_refs` 字段（手工维护会造成双源）。
本文件不维护任务列表，需要时执行 `python .dsh/scripts/taskctl.py list`。

### REQ-014 增量原子任务与全链追溯

- 来源：本轮用户明确要求，执行计划及前后端 plan。
- 范围：任务台账、任务规则、计划的已批准规格同步、追溯校验及会话交接；不实现业务。
- 验收：每项单一交付物、明确边界与独立验证；已执行与正式完成分离；历史 ID/证据不删除；依赖无环、路径重叠串行；SPEC→PLAN→TASK→TEST 可检查；规格变化按差量修订并保留旧值。
- 依据：`.dsh/tasks/ATOMIC_TASK_RULES.md`；状态仍仅由 tasks.json 管理。
