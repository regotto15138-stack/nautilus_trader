# SACW 前端技术设计方案

> TASK-009 / REQ-011；增量修订 TASK-096（2026-11-23）。设计只描述目标实现与当前兼容层，不是已完成状态。共用 [`统一接口契约`](../interface-contract.md)；原始需求章节见本目录 README。策略规则以 V1.4.8 结构化规格为准。五章（03/04/05/06/14）现为 `REVIEW_CANDIDATE`，涉及候选语义的界面只能以“候选/研究”状态展示。

## 1. 目标与边界

建设研究工作台 UI：市场数据浏览、人工标注与审阅、回归样本查看、快照/比较及后续参数实验操作。前端负责呈现、输入交互、本地未提交编辑队列和服务器结果缓存；不成为策略算法或可信数据层。

现状为 `web/app.js` 约 4100 行 Vanilla JS + Lightweight Charts v4；SACW 原规格建议 React/TypeScript/Vite 与 Zustand/Redux。迁移到 React 是目标选项，不是当前仓库事实，也不是本方案默认为必需的改造。先按现有视觉/HTTP 契约分模块，框架迁移另行 TASK/决策。

明确不做：策略规则推导、图表端 ZigZag/N结构/Zone 计算、Ground Truth 冻结、价格精度运算、实验/配置审批权限判断；不连接交易下单。页面可发起操作，但后端作最终验证。

## 2. 模块划分及职责边界

| 模块 | 职责 | 不负责 |
|---|---|---|
| Workbench Shell / Router | 主导航、全局错误/通知、布局、页面间共享 project/dataset/timeframe | 领域验证与 API 业务规则 |
| API Client / Contract Types | 统一 envelope 解包、错误映射、AbortSignal、分页、请求 ID/重试策略；类型对齐接口契约 | 业务状态机；不对写请求盲目重试 |
| Chart Workspace | Lightweight Charts 生命周期、Bar/指标/程序标记绘制、时间范围与多图同步、画布坐标转换 | 数据采集、程序输出生成、像素坐标持久化 |
| Annotation Tools | Swing/N/Zone/State 等工具、属性编辑、undo/redo、dirty state、局部校验 | 直接改写已冻结真值；最终 payload 校验 |
| Review & Ground Truth | 状态操作、修订列表、分歧/哈希/冻结集展示、冲突处理 | 自行算 hash 或绕开后端状态流 |
| Regression & Comparison | PB case/run 列表、assertion 状态、匹配结果和差异图层；标出 BLOCKED/ambiguity | 推断 blocked 为 PASS、调整策略容差掩盖差异 |
| Snapshot Viewer | 初始/回放快照字段、来源/版本/diagnostic 解释 | 补齐规格未定义字段 |
| Bar Freshness / Batch Indicator | 展示 Bar 的 `available_at`、`completeness_status`、完成批次 `PENDING/COMMITTED/QUARANTINED` 与快照切换；禁止用本地时间推断闭合 | 自行计算 `is_closed`、回填半更新批次 |
| Spec Status / Diagnostics | 显示 `spec_version`/`spec_status`、候选徽标、诊断码与阻塞原因（`OD-*`、`OPEN_DECISION-*`、`SPEC_AMBIGUITY`） | 解释成交易许可、隐藏 blocked、造诊断码 |
| Cost & Metadata Viewer (later) | 只读呈现 Fill 级费用/滑点、Funding 事件、元数据版本区间与缺项清单 | 计算净绩效、补估 FX/费率、绕过 OD-08 |
| Calibration & Config UI (later) | 参数筛选、实验状态/报告、候选审批表单、版本比较 | 搜索空间真实性校验、发布生效、自动审批 |
| State/Query Cache | 以资源 key 缓存服务器态，清除失效查询；区分 server state 与 draft | 把本地 draft 当成服务端真值 |

### 页面数据状态

- 全局选择：`ProjectSelection`, `DatasetSelection`, `Timeframe`, `UtcRange`。
- 服务态分域：`marketQuery`, `annotationQuery`, `comparisonQuery`, `runQuery`；加载/错误/新鲜度和数据版本均显式表示。
- 编辑态：`AnnotationDraft` 保存 base revision、payload、dirty fields；成功保存后以服务端返回 revision 替换；409 保留用户 draft 并加载最新版供人工比较。
- 候选态：`specStatus` 随页面/标注加载，`REVIEW_CANDIDATE` 时显示候选徽标与“不得作为验收/交易依据”提示；切换规格版本或批准状态必须重新加载，不在本地合并。
- 批次态：`batchState` 按 `close_time` 记录 `PENDING/COMMITTED/QUARANTINED`；提交前的 Bar 只显示至多 `PENDING`，图表与标注不允许把未提交周期拼进已闭合序列。
- 图层类型分离：`ProgramOverlay`、`HumanAnnotationOverlay`、`BoundaryOverrideOverlay`、`TradeEventOverlay` 视觉上可切换但语义永不互混。SPEC_AMBIGUITY 显示专用诊断提示，不画伪造数值。

## 3. 前端核心数据结构

```typescript
type UUID = string;
type DecimalText = string;
type UtcInstant = string;
type AnnotationStatus = "DRAFT" | "SUBMITTED" | "REVIEWED" | "APPROVED" | "FROZEN" | "SUPERSEDED" | "REJECTED" | "AMBIGUOUS";
type ApiEnvelope<T> = { data: T | null; meta: { request_id: UUID }; error: ApiError | null };
type ApiError = { code: string; message: string; field?: string; details?: unknown };
type BarDTO = { bar_id: UUID; timeframe: string; open_time: UtcInstant; close_time: UtcInstant; open: DecimalText; high: DecimalText; low: DecimalText; close: DecimalText; volume: DecimalText; is_closed: boolean; dataset_version: string; source: "EXCHANGE_FINAL"|"LOCAL_AGGREGATED"|"HISTORICAL_VERIFIED"; sequence: number; source_bar_id?: string | null; received_at: UtcInstant; available_at: UtcInstant; completeness_status: "COMPLETE"|"PENDING"|"INCOMPLETE"|"QUARANTINED"; revision_id?: string | null; config_version: string };
type AnnotationDTO = { annotation_id: UUID; project_id: UUID; dataset_id: UUID | null; entity_type: string; timeframe: string; payload: Record<string, unknown>; label_source: string; status: AnnotationStatus; revision: number; spec_version: string };
type AnnotationDraft = { annotationId?: UUID; baseRevision?: number; entityType: string; payload: Record<string, unknown>; dirty: boolean; validation: FieldIssue[] };
type FieldIssue = { field: string; code: string; message: string };
type TimeRange = { from: UtcInstant; to: UtcInstant };
type ChartViewState = { timeframe: string; range: TimeRange; cursor: UtcInstant | null; visibleLayers: Set<string>; selectedId: UUID | null };
type AsyncRunView = { runId: UUID; status: "QUEUED" | "RUNNING" | "PASSED" | "FAILED" | "BLOCKED" | "CANCELLED"; progress?: number; blockedReason?: string };
type ComparisonRow = { humanId: UUID | null; programId: UUID | null; result: string; metrics: Record<string, DecimalText | number | null> };
type CompletionBatchDTO = { batch_id: UUID; close_time: UtcInstant; status: "PENDING" | "COMMITTED" | "QUARANTINED"; processed_timeframes: string[]; snapshot_id?: UUID | null };
type DiagnosticDTO = { code: string; severity: "INFO" | "WARNING" | "BLOCKER"; message: string; subject_type: string; subject_id?: UUID | null; details?: Record<string, unknown> };
type SpecStatusDTO = { spec_version: string; spec_status: "REVIEW_CANDIDATE" | "APPROVED"; blockers: string[] };
type ZoneSnapshotDTO = { zone_id: UUID; timeframe: string; zone_type: string; state: string; center: DecimalText; lower: DecimalText; upper: DecimalText; anchor_radius: DecimalText; half_width_cap: DecimalText; zone_version: number; transition_reason: string };
type CostEventDTO = { event_id: UUID; event_type: "FILL_FEE" | "FILL_SLIPPAGE" | "FUNDING"; occurred_at: UtcInstant; amount: DecimalText; currency: string; sign: "DEBIT" | "CREDIT"; order_role?: "MAKER" | "TAKER" | null; metadata_version: string };
type InstrumentMetadataDTO = { instrument_id: string; contract_value?: DecimalText | null; quote_currency: string; tick_size: DecimalText; lot_size: DecimalText; metadata_version: string; valid_from: UtcInstant; valid_to?: UtcInstant | null };
```

金额/价格以 DecimalText 保存到请求和 UI 编辑模型；绘图转换 `number` 仅为 Lightweight Charts 的显示精度边界，禁止用绘图值覆盖原字段。TS type/enum 若采用，仅前端编译时约束，不能取代后端校验。

## 4. 模块接口（前端签名）

```typescript
interface ApiClient {
  get<T>(path: string, query?: URLSearchParams, signal?: AbortSignal): Promise<T>;
  post<T, B>(path: string, body: B, signal?: AbortSignal): Promise<T>;
  patch<T, B>(path: string, body: B, signal?: AbortSignal): Promise<T>;
  delete<T>(path: string, signal?: AbortSignal): Promise<T>;
}
interface AnnotationRepository {
  list(projectId: UUID, filter: AnnotationFilter, signal?: AbortSignal): Promise<Page<AnnotationDTO>>;
  create(projectId: UUID, draft: AnnotationDraft): Promise<AnnotationDTO>;
  revise(id: UUID, expectedRevision: number, patch: AnnotationPatch): Promise<AnnotationDTO>;
  transition(id: UUID, action: "submit"|"review"|"approve"|"freeze", reason?: string): Promise<AnnotationDTO>;
  revisions(id: UUID, signal?: AbortSignal): Promise<AnnotationRevision[]>;
}
interface ChartWorkspace {
  mount(container: HTMLElement, options: ChartOptions): void;
  render(payload: ChartPayload, overlays: Overlay[]): void;
  setRange(range: TimeRange): void;
  setCursor(time: UtcInstant | null): void;
  hitTest(point: ChartPoint): ChartSelection | null;
  dispose(): void;
}
interface AnnotationTool {
  begin(kind: string, context: ToolContext): void;
  onChartSelection(selection: ChartSelection): AnnotationDraft | null;
  validate(draft: AnnotationDraft): FieldIssue[];
  cancel(): void;
}
interface WorkbenchController {
  loadWorkspace(selection: WorkspaceSelection, signal?: AbortSignal): Promise<WorkspaceViewModel>;
  saveDraft(draft: AnnotationDraft): Promise<AnnotationDTO>;
  refreshAfterConflict(annotationId: UUID): Promise<AnnotationDTO>;
  startRegression(caseIds: string[]): Promise<AsyncRunView>;
  loadSpecStatus(specVersion: string, signal?: AbortSignal): Promise<SpecStatusDTO>;
  loadCompletionBatch(closeTime: UtcInstant, signal?: AbortSignal): Promise<CompletionBatchDTO>;
  loadDiagnostics(filter: DiagnosticFilter, signal?: AbortSignal): Promise<Page<DiagnosticDTO>>;
}
```

`ApiClient` 的 DTO、请求字段和分页键必须引用接口契约，不能另行复制并分叉。实际后端当前为单一 snapshot payload + 分散 API，逐步抽象时保持当前响应兼容。

## 5. 实施顺序与依赖

以下为能力依赖；当前落地按 §10 的入口差量切片进行，不要求先完成整套模块抽取。

1. **契约层**：定义 wire DTO、errors、时间/decimal helper、API client envelope；依赖接口契约冻结。无此层不得铺开组件调用。
2. **Shell + 服务器状态**：抽取 project/dataset/timeframe、loading/error/query cache；依赖契约层。
3. **图表适配**：仅为本次改动包裹图表生命周期与 selection，复用当前绘图函数，保持 candle 时间、时间范围、显隐行为；依赖统一 DTO 与 smoke baseline。
4. **标注工具**：先 Swing/选中/属性/保存，再 Zone、N、state interval；依赖图表 selection API、payload schema、乐观锁。
5. **Revision/review/GT UI**：展示状态迁移、revision、freeze/hash；依赖 annotation CRUD 与 GT endpoints。
6. **PB/regression/comparison**：run/case/assertions、逐项 blocked reason 与差异图层；依赖后端现有 runner/matching/replay 数据契约。
7. **Snapshot/诊断 UI**：按接口诊断字段显示 unknown/ambiguity 与快照来源；依赖 view payload contract。
8. **候选规格/批次可见性**：候选徽标、`spec_status`、批次 `PENDING/COMMITTED/QUARANTINED` 与阻塞清单；可在 §1 契约层完成后与 Shell 并行启动，但任何候选语义的编辑/导出必须先展示候选提示。
9. **成本与元数据只读视图**：Fill 费用/滑点、Funding 事件、元数据版本区间与缺项；依赖 TASK-034/035 的真实数据契约，OD-08 未决时只显示 blocked，不显示净绩效数字。
10. **实验和配置治理**：仅在相应后端能力、OD-05 及需求验收准入后开发；依赖 calibration API/schema/授权决策，不并入前置 UI 假实现。

候选规格期间（TASK-095 未通过）第 8 步只做展示与诊断，不做基于新语义的批量编辑或实验入口；第 7 步的既有快照字段保持兼容，不因候选字段重命名旧 key。

同一 API DTO 改动须前后端联审。旧脚本状态与新 store 不可双向复制成为双重事实源。本批继续使用 Vanilla JS；React/TS 迁移不作为任何任务前置，未来如需要另立任务决策。

## 6. 技术风险与缓解

| 风险 | 后果 | 控制 |
|---|---|---|
| 单体 app.js 当前数据状态与计划类型不一致 | 模块抽取回归/画图错位 | 建立行为基线与 DTO 测试；分步提取，不做一次性改写 |
| HTTP DTO 中数字/时间精度损失 | 标注价格或事件时间漂移 | 表单存十进制字符串、UTC 明确；number 只用于 chart adapter |
| 409 并发冲突被自动重试 | 覆盖他人标注 | 保存 baseRevision；冲突进入比较/人工决策态 |
| 人工/程序 overlays 混合 | 污染 Ground Truth | 不同模型、图层、颜色/legend；操作按钮约束来源 |
| 浏览器分页/缓存和 live 增量竞争 | 重复 Bar、旧状态覆盖 | resource key 加 dataset/version/cursor；合并前去重并检查递增时间 |
| 超长回放采用轮询过载或丢状态 | UI 假死、误报完成 | 先按 AsyncRun polling + backoff；持久事实只读后端状态；SSE 另立契约 |
| 规格建议技术栈被误当当前依赖 | 引入无授权许可/大迁移 | 先遵守 Lightweight Charts 授权署名；框架迁移单独评估，不擅加组件依赖 |
| P0-E/OD-05 未冻结却展示 calibration | 用户误以为已可调参/准入 | 标示 disabled/blocked 与理由；不可提交真实实验请求 |
| 候选规格被界面暗示为已批准 | 用户据候选语义做标注/导出 | 全局 `spec_status` 徽标 + 导出/冻结前提示；`REVIEW_CANDIDATE` 时禁用“确认/过门禁”类操作 |
| 未提交批次被画成已闭合 | 图表出现虚假完整序列 | 只按 `completeness_status` 与 `CompletionBatch` 渲染；`PENDING` 用独立样式，禁止本地补 Bar |
| 成本/元数据缺项被前端估算 | 用户看到错误的净绩效 | 只显示 blocked 与缺项清单；金额/价差全部 DecimalText，不参与本地计算 |
| 诊断码/阻塞原因被隐藏或改写 | 误判为 PASS/已批准 | 诊断面板固定展示 code+severity+来源；未注册码不渲染为已知语义 |

## 7. 验收与交付

前端验收以接口契约一致性、七周期/完整 Bar/分层图层、409 冲突流程、freeze 状态只读、PB blocked 可见、无策略计算为核心；浏览器集成测试/截图验收另行指定。当前测试脚本可能直接调用 API dispatch，不能当作浏览器 UI 验收。任何前端实现另建 TASK，明确允许文件和验证步骤；本 plan 本身不含代码改动。
## 8. 增量任务追溯（TASK-015，2026-11-23）

任务定义及 SPEC→PLAN→TASK→TEST 关系以 `../../../.dsh/tasks/tasks.json` 为准；拆分规则见 `../../../.dsh/tasks/ATOMIC_TASK_RULES.md`。保持 Vanilla JS 渐进模块化，不默认引入框架。浏览器验证与 API 测试分开登记。PB-01…59 按功能阶段执行，blocked 不得画成 PASS；OD-08 绩效、OD-09 多低点限制均须显示，不由 UI 解除。

## 9. 五章规格修订对齐（TASK-096，2026-11-23）

本次按 SPEC-03/04/05/06/14 修订候选增量更新本文，不新增业务语义、不引入框架或依赖：

- 数据契约：`BarDTO` 增补 envelope 字段（`source`、`sequence`、`received_at`、`available_at`、`completeness_status`、`revision_id`、`config_version`）；新增 `CompletionBatchDTO`、`DiagnosticDTO`、`SpecStatusDTO`、`ZoneSnapshotDTO`、`CostEventDTO`、`InstrumentMetadataDTO`，字段以 [`../interface-contract.md`](../interface-contract.md) 为准。
- 模块：新增 Bar Freshness/Batch 指示、Spec Status/Diagnostics 面板与成本/元数据只读视图（后者 later）；明确不自行计算 `is_closed`、不补 Bar、不估算成本。
- 状态：`specStatus`、`batchState` 进入页面状态；候选与 `PENDING` 必须有独立视觉与不可执行提示。
- 门禁：TASK-095 通过前，候选语义只可展示与诊断；OD-ZZ、OD-ZONE、OD-06、OD-08 与结构层 OPEN_DECISION 原样显示为阻塞。
- 追溯：任务与 TEST-ID 以 `../../../.dsh/tasks/tasks.json` 为准；浏览器验收仍与 API 测试分开登记，本文不含代码改动。

## Zone候选与历史绘制差量（TASK-098，2026-11-24）

TASK-100独立承接Zone展示，TASK-083继续负责指标有效性与歧义诊断。输入为TASK-099按版本有效区间输出的分段载荷。CREATED保留显示时必须标明“候选”和当前锚点数，并与ACTIVE/TESTED在视觉及文本上可辨；终态按对应有效时间截断。页面不推导新几何、不自行将被穿越的CREATED设为BROKEN、不把单锚点候选解释为有效支撑阻力。

浏览器测试使用固定载荷验证候选、有效、终态、历史版本变更、缩放裁剪与as_of回放。2026-11-19T22:00:00Z红色0393的1782.34单锚点候选作为复现线索；绿色0392/0395分别为1766.03/1647.12单锚点候选，用户具体绿色目标待确认。测试用稳定夹具，不硬编码真实回放的Zone序号。显示时明确UTC与UTC+8，截图与网络载荷共同留证。

只做node语法检查或后端API测试不足以完成此验收。若历史版本接口尚未落地，可用固定夹具开发浏览器测试，联调验收须消费TASK-099真实载荷。候选审批及max_half_width_atr生产值继续保留门禁。


## 10. 剩余任务的前端增量技术说明（TASK-101，2026-11-24）

本批沿用 Vanilla JS、现有DOM、共享state和Lightweight Charts。
模块表是责任边界，不要求先把整个app.js搬到modules，也不新增router/store框架。
状态、范围、优先级和逐项步骤只读 [tasks.json](../../../.dsh/tasks/tasks.json)；
波次与准入见 [执行计划](../../../planning/EXECUTION_PLAN.md) 当前入口。

| 任务/切片 | 当前代码复用点 | 最小接入与兼容要求 | 浏览器/契约出口 |
| --- | --- | --- | --- |
| TASK-066 | 当前七周期按钮、图表、图层与标注流程 | 固定dataset/config、浏览器版本及截图基线；只增加基线测试与证据 | 七周期加载/切换、时间范围、选中、图层、编辑和409，真实浏览器执行 |
| TASK-067 | `api(path, options)` | 保留调用签名，内部接结构化错误、request_id、AbortSignal与取消；不批量改全部调用点，不重试写请求 | 成功兼容、非JSON/非2xx错误可见、取消不覆盖新选择 |
| TASK-068/069 | `fmt`、`loadPayload/loadAnnotations`、现有state | 表单保存DecimalText原文；只在chart坐标转换number；新增资源key/请求序号防旧响应覆盖 | 高精度价格保存前后文本一致；快切周期与反序响应无串数据 |
| TASK-070/071 | 现有导航/按钮绑定、chart创建销毁与selection | 单一共享选择来源；局部包裹mount/dispose，未受影响的绘图/事件绑定保留 | 重复切换无重复订阅和残留series，既有绘图/选中可用 |
| TASK-072/073/074 | `loadOlderBars/applyLive/applyToggles`、`drawManualAnnotations/drawZones` | 每项只改分页合并、范围同步或图层拥有者；继续使用现有chart实例 | 完整Bar去重与递增、范围游标同步；人工/程序/覆盖层不串改 |
| TASK-075/076 | `renderPending/saveAnnotationEdit/applyAnnotationHistory` | 075补Swing精确保存；076在已有PATCH上保留冲突draft并展示人工比较 | 服务端revision为准；409不清空草稿、不自动覆盖、不盲重试 |
| TASK-077…080 | `renderZoneModeControls/renderAnchorPicker/drawStateBands`与现有编辑器 | Zone三模式、N引用、保护点来源、StateInterval逐项补差距；已有可用工具只回归 | 人工边界与程序算法隔离；不造15M保护点/独立Zone；冻结对象只读 |
| TASK-081/082 | `copyAnnotation/filteredAnnotations`、历史栈、`loadGolden` | 补复制/筛选/撤销一致性与revision/hash展示，不替换整套工具状态 | 复制仍DRAFT，撤销不越revision，FROZEN展示不提供绕过操作 |
| TASK-084/085/086 | `loadCases/renderCaseAssertions/runComparison` | PB状态/差异定位、预期审核、指定run独立差异层分开接入 | BLOCKED不画PASS，预期修改须审核，program事件不覆盖human事实 |
| TASK-087/083 | `buildSnapshot/updateAtrSnapshotInspector`与现有指标展示 | 087补字段来源/unknown；083只显示后端诊断，原BLOCKED待核，不重新计算策略 | ATR_MA22仅N/A/SPEC_AMBIGUITY；未知字段显式缺失，不造数值 |
| TASK-100 | 已有`web/modules/fe-zone.js`、`drawZones/renderZones/clipPolyline` | 保留候选/有效/终态与历史分段，只补真实1H载荷、UTC/UTC+8及资源复核 | as_of不读未来；终态不延伸；记录载荷hash、版本数、series数量与截图 |
| TASK-088/089 | 现有程序图层与`exportAnnotations` | 后端真实Setup/Fill就绪后接投影与同版本导出 | Signal与Fill分类，15M投影不作为独立Zone，导出含来源/版本/阻塞 |
| TASK-090…094 | 现有页面容器、API客户端和选择state | 按Experiment/Trial→Holdout→报告→候选→显式审批发布分别接后端 | 未就绪禁用并显示原因；权限/审批由后端裁决，前端不算指标或自动发布 |

### 10.1 小步接入规则

每个TASK只修改自身delta所需的调用入口。`web/modules/fe-*.js` 是可用的纯函数承载位置，
不是必须搬迁整段UI的目标；仅当本次差量确实需要可单测边界时提取，原调用签名保持兼容。
保留现有state作为唯一来源，不能新旧store双向复制；本地draft与服务端事实分离。
新增字段由后端契约提供，缺失时显示unknown/blocked，不由UI合成批准状态、is_closed或成本公式。

共享app.js/index.html/styles.css的任务必须串行。台账已收敛冗余直接依赖，并把BLOCKED的
TASK-083放到当前共享写入队列末尾，让PB/比较/快照可沿TASK-082继续；这不是删除指标需求。
其解除阻塞后可由Main重新排序并跑DAG/互斥校验，不能直接同时写共享文件。

### 10.2 每个页面切片的验证与回退

先用现有node:test方式验证纯函数和固定载荷；再跑该TASK明确的真实浏览器交互，记录选择路径、
网络payload、数据/配置版本、UTC标签和截图。API dispatch、node语法检查、demo截图均不能替代真实数据联调出口。
真实catalog全量资源问题若复现，记录启动时间/内存/版本数并另登记性能TASK；本批不重写缓存与快照保留策略。

TASK-100沿用已有实现与历史证据，不重复制作分段图层；待TASK-032/099契约收口后，
对冻结真实1H输入做as_of、终态、候选、缩放裁剪和UTC/UTC+8验收。
三只Zone的旧序号只作审计线索，回归用冻结输入与语义断言，不能依赖会变化的序号。

回退时只撤当前页面调用和模块增量，保留既有DOM/state/事件绑定及用户未提交draft；
不得覆盖已保存annotation revision或冻结数据。若恢复旧UI仍可能产生错误业务操作，
应显式禁用受影响动作并显示阻塞，而非恢复不安全行为。
本轮仅修订计划，不代表上述浏览器或待开发功能已通过验收。
