# SACW 前端技术设计方案

> TASK-009 / REQ-011。设计只描述目标实现与当前兼容层，不是已完成状态。共用 [`统一接口契约`](../interface-contract.md)；原始需求章节见本目录 README。策略规则以 V1.4.8 结构化规格为准。

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
| Calibration & Config UI (later) | 参数筛选、实验状态/报告、候选审批表单、版本比较 | 搜索空间真实性校验、发布生效、自动审批 |
| State/Query Cache | 以资源 key 缓存服务器态，清除失效查询；区分 server state 与 draft | 把本地 draft 当成服务端真值 |

### 页面数据状态

- 全局选择：`ProjectSelection`, `DatasetSelection`, `Timeframe`, `UtcRange`。
- 服务态分域：`marketQuery`, `annotationQuery`, `comparisonQuery`, `runQuery`；加载/错误/新鲜度和数据版本均显式表示。
- 编辑态：`AnnotationDraft` 保存 base revision、payload、dirty fields；成功保存后以服务端返回 revision 替换；409 保留用户 draft 并加载最新版供人工比较。
- 图层类型分离：`ProgramOverlay`、`HumanAnnotationOverlay`、`BoundaryOverrideOverlay`、`TradeEventOverlay` 视觉上可切换但语义永不互混。SPEC_AMBIGUITY 显示专用诊断提示，不画伪造数值。

## 3. 前端核心数据结构

```typescript
type UUID = string;
type DecimalText = string;
type UtcInstant = string;
type AnnotationStatus = "DRAFT" | "SUBMITTED" | "REVIEWED" | "APPROVED" | "FROZEN" | "SUPERSEDED" | "REJECTED" | "AMBIGUOUS";
type ApiEnvelope<T> = { data: T | null; meta: { request_id: UUID }; error: ApiError | null };
type ApiError = { code: string; message: string; field?: string; details?: unknown };
type BarDTO = { bar_id: UUID; timeframe: string; open_time: UtcInstant; close_time: UtcInstant; open: DecimalText; high: DecimalText; low: DecimalText; close: DecimalText; volume: DecimalText; is_closed: boolean; dataset_version: string };
type AnnotationDTO = { annotation_id: UUID; project_id: UUID; dataset_id: UUID | null; entity_type: string; timeframe: string; payload: Record<string, unknown>; label_source: string; status: AnnotationStatus; revision: number; spec_version: string };
type AnnotationDraft = { annotationId?: UUID; baseRevision?: number; entityType: string; payload: Record<string, unknown>; dirty: boolean; validation: FieldIssue[] };
type FieldIssue = { field: string; code: string; message: string };
type TimeRange = { from: UtcInstant; to: UtcInstant };
type ChartViewState = { timeframe: string; range: TimeRange; cursor: UtcInstant | null; visibleLayers: Set<string>; selectedId: UUID | null };
type AsyncRunView = { runId: UUID; status: "QUEUED" | "RUNNING" | "PASSED" | "FAILED" | "BLOCKED" | "CANCELLED"; progress?: number; blockedReason?: string };
type ComparisonRow = { humanId: UUID | null; programId: UUID | null; result: string; metrics: Record<string, DecimalText | number | null> };
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
}
```

`ApiClient` 的 DTO、请求字段和分页键必须引用接口契约，不能另行复制并分叉。实际后端当前为单一 snapshot payload + 分散 API，逐步抽象时保持当前响应兼容。

## 5. 实施顺序与依赖

1. **契约层**：定义 wire DTO、errors、时间/decimal helper、API client envelope；依赖接口契约冻结。无此层不得铺开组件调用。
2. **Shell + 服务器状态**：抽取 project/dataset/timeframe、loading/error/query cache；依赖契约层。
3. **图表适配**：把当前 `app.js` 绘图逻辑拆成 ChartWorkspace 与 overlays，保持 candle 时间、时间范围、显隐行为；依赖统一 DTO 与 smoke baseline。
4. **标注工具**：先 Swing/选中/属性/保存，再 Zone、N、state interval；依赖图表 selection API、payload schema、乐观锁。
5. **Revision/review/GT UI**：展示状态迁移、revision、freeze/hash；依赖 annotation CRUD 与 GT endpoints。
6. **PB/regression/comparison**：run/case/assertions、逐项 blocked reason 与差异图层；依赖后端现有 runner/matching/replay 数据契约。
7. **Snapshot/诊断 UI**：按接口诊断字段显示 unknown/ambiguity 与快照来源；依赖 view payload contract。
8. **实验和配置治理**：仅在相应后端能力、OD-05 及需求验收准入后开发；依赖 calibration API/schema/授权决策，不并入前置 UI 假实现。

同一 API DTO 改动须前后端联审。旧脚本状态与新 store 不可双向复制成为双重事实源。Vanilla JS 是否改 React/TS 在第 1 阶段前单独决定，未决定就沿用现有运行方式渐进模块化。

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

## 7. 验收与交付

前端验收以接口契约一致性、七周期/完整 Bar/分层图层、409 冲突流程、freeze 状态只读、PB blocked 可见、无策略计算为核心；浏览器集成测试/截图验收另行指定。当前测试脚本可能直接调用 API dispatch，不能当作浏览器 UI 验收。任何前端实现另建 TASK，明确允许文件和验证步骤；本 plan 本身不含代码改动。
## 8. 增量任务追溯（TASK-015，2026-11-23）

任务定义及 SPEC→PLAN→TASK→TEST 关系以 `../../../.dsh/tasks/tasks.json` 为准；拆分规则见 `../../../.dsh/tasks/ATOMIC_TASK_RULES.md`。保持 Vanilla JS 渐进模块化，不默认引入框架。浏览器验证与 API 测试分开登记。PB-01…59 按功能阶段执行，blocked 不得画成 PASS；OD-08 绩效、OD-09 多低点限制均须显示，不由 UI 解除。
