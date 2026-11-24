# PROJECT_CONTEXT

> 长期上下文。目标 1500–2500 Token，不得超过 3000。增量更新；不存完整日志与代码；
> 未确认的信息标注"待验证"。

## 1. 基本信息

| 项 | 值 |
| --- | --- |
| 项目 | `nautilus_pa`：ETH 多周期趋势识别 + SACW 结构标注与参数校准工作台 |
| 语义基线 | `ETH-USDT-SWAP 多周期趋势策略开发规格 V1.4.8`、`SACW V1.1.2` |
| 父仓库 | NautilusTrader（Python 3，uv 管理，`python/.venv`） |
| 交换/合约 | OKX `ETH-USDT-SWAP`，tick_size 见 `configs/market_okx_eth_swap.yaml` |
| 周期 | 1MONTH、1W、1D、4H、1H、15M、3M |

## 2. 当前状态（2026-11-24）

- 测试基线：2026-11-24 实测 `tests/unit tests/integration` 470 passed in 35.58s（`PYTHONPATH=src ../python/.venv/bin/python -m pytest -q tests/unit tests/integration`）；不代表阶段/人工/浏览器验收通过。
- Zone 展示（TASK-099/100 IMPLEMENTED，依赖 TASK-032 未收口）：图表载荷按 `effective_at` 输出历史版本 `versions[]`；前端候选 CREATED 用琥珀虚线、终态点线不延伸，侧栏显示候选/有效/已破位。TASK-032 仍 IN_PROGRESS（OD-ZONE 与 `max_half_width_atr` 待裁决）。
- 已实现：P0-A～P0-D——七周期时间与 Bar 处理、SMA22/ATR14、ZigZag、SwingPoint、
  保护点、Zone 引擎、N 结构、宏观与 4H/1H 状态机、CanOpen/CanHold；
  SACW 标注库、标注 API、ANCHOR_ONLY / HUMAN_BOUNDARY 几何、HUMAN_JUDGED Swing、
  冻结 Ground Truth 差异匹配、初始快照、PB-01..51 回归工作台、前端工作台。
- 仅接口：Setup / Signal / 3M 执行 / 止损风控 / 参数校准引擎（`domain/lifecycle/`）。
- 里程碑 1、2 未达出口；按计划不应进入阶段 2。

## 3. 核心架构

分层：`domain`（纯 Python，不导入 NautilusTrader）→ `application`（引擎/存储/匹配/回归）
→ `config`（加载/指纹/门禁）→ `adapters/nautilus` → `presentation`（HTTP API + 图表载荷）
→ `web`（Lightweight Charts 工作台）。

执行链：`MarketContext → Setup4H → Setup1H → Signal15M → Execution3M → RiskManager`；
当前只实现 `MarketContext`，其余固化数据契约。

七周期共享同一套算法实现，各自持有完全独立的状态（周期边界、ATR14、SMA22、ZigZag k=2.0、
SwingPoint、ProtectedLow/High、PullbackOriginHigh、N 结构、Zone）。

存储：SACW SQLite（`var/sacw.sqlite3`，gitignore）；行情 Parquet 在 `catalog/`。

## 4. 技术约束

1. `ATR_MA22` 不实现：规格只定义 ATR14 与 SMA22；配置里出现 `indicators.atr_ma_period`
   必须加载失败；前端显示 `N/A / SPEC_AMBIGUITY`。
2. N 结构失效只留接口：`NStructureDetector.structural_break_price(atr)` 存在但不决策 ATR 时点，
   默认 `invalidation_enabled=False`，`invalidation_status = SPEC_AMBIGUITY`；
   4H/1H 结构为 `RESEARCH_ONLY`；PB-12/PB-13 为 `BLOCKED_BY_SPEC_AMBIGUITY`。
3. Zone 参数可配置：`zone_min_half_width_ticks`、`zone_max_age_weeks` 进配置与冻结快照。
4. 价格/数量/金额精确算术（`Decimal` 或领域类型）；路径跨平台，禁止裸按 `/` 切分。
5. 完整 Bar 原则与因果性：只用已收盘 Bar；不得前视。
6. 测试不得依赖适配器环境变量（`scripts/strip-adapter-env.bash`）。

## 5. 已确认决策

| ID | 决策 | 理由 |
| --- | --- | --- |
| D-001 | `tasks.json` 为唯一任务状态源 | 避免多文件状态漂移 |
| D-002 | 提交信息 `<TASK-ID> <摘要>`，不用 Conventional Commits | 上游 AGENTS.md 禁止 |
| D-003 | 三 Agent Preset：Architect/Developer/Reviewer | 职责隔离，工具面即权限 |
| D-004 | 权限靠工具面 + 沙箱 + `allowed_paths` + hook 多层落实 | 提示词约束不住模型 |
| D-005 | 规格歧义不猜：标记 `SPEC_AMBIGUITY` 并留接口 | 避免错误固化业务语义 |
| D-006 | Zone 图表按历史版本分段绘制，候选与有效区域视觉区分 | 最新几何不得回画历史，单锚点候选不等于有效区 |
| D-006 | 不自动 `git commit`/`push`，提交由用户触发 | 上游规范要求 |
| D-007 | `nautilus_pa/` 无独立 git，随父仓库提交；子工程只管任务发布 | 用户明确要求 |
| D-008 | `domain/` 不导入 NautilusTrader | 保持可测试与可移植 |
| D-009 | SQLite 作为 SACW 持久层 | 单机、事务、审计简单 |

完整说明见 `development/DECISIONS.md`；本节只留摘要。

## 6. 当前任务

2026-11-24 TASK-103 实施四级变更控制层：架构保护契约位于 `docs/architecture/ARCHITECTURE_CONTRACT.md`；新任务默认 L1/最小补丁/无特权，开工及下发须有影响分析与人工授权。旧任务历史保留，但再执行前须补契约；本轮不改变业务。CI 范围入口 `check_scope.py` 已提供，远程必需检查及逐TASK文件系统隔离尚未启用。验证/审查状态以台账为准。

以 `.dsh/tasks/tasks.json` 为准。2026-11-24 TASK-101 核对90个存量未验收任务，补齐调度优先级与逐项增量步骤；三份plan补现有入口/兼容/回退/验证；TASK-083移出其余页面前置链且保留BLOCKED。计划调整不代表业务验收或规格批准。2026-11-23 TASK-015 增量拆分三份计划；新增 TASK-016…094 为 DRAFT，尚未执行业务实现。TASK-002 保留并收敛后端并发边界，已实现部分与未验收部分分开登记。拆分规则见 `.dsh/tasks/ATOMIC_TASK_RULES.md`，SPEC→PLAN→TASK→TEST 及依赖均在台账，不另维护状态表。

## 7. 开发约束

- 所有改动带 TASK-ID；先改状态再动手；越界即停。
- 最小 diff，复用既有函数/类型/命名。
- 相关测试必须通过；不得弱化测试。
- 不改生成产物、不改 `RELEASES.md`、不改 `.github/`。

## 8. 重要代码入口

| 关注点 | 路径 |
| --- | --- |
| 周期引擎 | `src/pa_trend/application/timeframe_engine.py` |
| 市场上下文 | `src/pa_trend/application/market_context.py` |
| 标注存储 | `src/pa_trend/application/annotation_store.py` |
| 差异匹配 | `src/pa_trend/application/matching.py` |
| PB 回归 | `src/pa_trend/application/regression.py` |
| HTTP API | `src/pa_trend/presentation/api.py` |
| 前端工作台 | `web/app.js`、`web/index.html` |
| 配置 | `configs/strategy_v1_4_8.yaml`、`configs/regression_cases.yaml` |

## 9. 最近变更

- 2026-11-17：建立 DSH 协作规范（`.dsh/`、三 preset、tasks.json、提交门禁）。
- 2026-11-17：校正 Git 定位——子工程随父仓库提交、只负责任务发布，取消分支/worktree 要求（D-007）。
- 2026-11-23：归档 DSH 大型项目开发操作标准；AGENTS.md 含每次 Session 启动协议，新项目通用模板位于 `requirements/templates/ai-project-bootstrap/`。
- 2026-11-23：工程文档以 README 导航；当前执行计划归位 `planning/EXECUTION_PLAN.md`；V1.4.8、SACW、DSH 旧根入口清理，正文统一到 requirements 的权威/归档目录。

## 10. 信息可信度

| 信息 | 来源 | 可信度 |
| --- | --- | --- |
| 已实现范围 | README + 373 行测试 + 执行计划核对 | 高 |
| 测试基线 349 | 执行计划第十一节 | 高 |
| SACW 高级功能未实现 | 执行计划状态表 | 高 |
| 规格未覆盖的语义 | 规格原文 | 高（歧义已登记） |

## 11. 维护规则

1. 只增量更新受影响的小节，附日期。
2. 不复制代码/日志/长表格；引用路径与任务 ID。
3. 决策变更写进 `development/DECISIONS.md`，这里只留一行摘要。
4. 未验证的信息标"待验证"，验证后更新。
