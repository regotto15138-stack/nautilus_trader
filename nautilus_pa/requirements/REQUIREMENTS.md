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
| S3 | `执行计划.md`（批次与出口条件） | 排期与门禁依据 |
| S4 | `DSH 大型项目开发操作标准.md` | 协作流程依据（REQ-000） |
| S5 | README / 既有代码与测试 | 现状事实，不是新需求 |

## 2. 需求清单

| REQ | 名称 | 来源 | 验收依据 | 状态 |
| --- | --- | --- | --- | --- |
| REQ-000 | DSH 协作工程规范基线 | `DSH 大型项目开发操作标准.md` | 本目录 `.dsh/` 可运行 + `AGENTS.md` + `tasks.json` 校验通过 | DONE |
| REQ-001 | 阶段 0：前置修正与基础设施（B00、B01a） | `执行计划.md` 阶段 0 | 阶段 0 出口条件全绿 | ACTIVE |
| REQ-002 | 阶段 1：结构层验收闭环（B01b、B02a、B02b、B03a、B03b） | `执行计划.md` 阶段 1 | 里程碑 1 出口 | OPEN |
| REQ-003 | 阶段 2：策略决策闭环（B04、B05、B06） | `执行计划.md` 阶段 2 | 里程碑 2 出口 | OPEN |
| REQ-004 | 阶段 3：交易执行与风险闭环（B07、B08、B02c） | `执行计划.md` 阶段 3 | 里程碑 3 出口 | OPEN |
| REQ-005 | 阶段 4：策略验证闭环（B09） | `执行计划.md` 阶段 4 | 里程碑 4 出口 | OPEN |
| REQ-006 | 阶段 5：SACW 校准与配置治理（B10b、B10c、B10d） | `执行计划.md` 阶段 5 | 里程碑 5 出口 | OPEN |
| REQ-007 | SACW 标注工作台（规格 V1.1.2 第 3–6 章） | `SACW 规格 V1.1.2` | 工作台可用 + 标注库/比对/回归全部可跑 | ACTIVE |

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
- **验收依据**：`执行计划.md` 阶段 0 出口条件；规格中 B00 / B01a 的逐条要求。
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
- **串行约束**：B07→B08 串行；B02c 可与 B08 并行。
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

## 4. 需求 → 任务映射

映射关系只存在于 `.dsh/tasks/tasks.json` 的 `requirement` 字段（手工维护会造成双源）。
本文件不维护任务列表，需要时执行 `python .dsh/scripts/taskctl.py list`。
