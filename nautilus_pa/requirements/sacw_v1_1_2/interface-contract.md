# SACW 前后端统一接口契约（设计基线）

版本：SACW V1.1.2 / API v1。本文是前端与后端两份 plan 的唯一 wire-contract 来源。当前 API 已在标准库 HTTP 服务与 Vanilla JS 中使用；此文界定兼容契约及方案新增点，不宣称所有资源均已实现。

> **修订 2026-11-23（TASK-096）**：对齐 [SPEC-V148-03](../spec_v1_4_8/03-时间与 Bar 处理规范.md)、[04](../spec_v1_4_8/04-指标与 ZigZag.md)、[05](../spec_v1_4_8/05-Swing 结构与保护点.md)、[06](../spec_v1_4_8/06-Zone 支撑阻力区域.md)、[14](../spec_v1_4_8/14-交易成本与合约元数据.md) 的修订候选及 TASK-029…035。五章当前均为 `REVIEW_CANDIDATE`，契约只描述候选字段与诊断传达方式，不构成语义批准；批准门禁见 [TASK-095](../../.dsh/tasks/tasks.json) 与 [`0.1` 节](../../planning/EXECUTION_PLAN.md)。

## 1. 共通协议

- Base path `/api/v1`；JSON UTF-8。成功响应 `{data: T, meta: {request_id: string}, error: null}`；失败响应 `{data: null, meta: {request_id: string}, error: {code: string, message: string, field?: string}}`。
- 时间以带时区 UTC ISO-8601 字符串（`Z`）表达；时间区间左闭右开。Bar 有 `open_time`, `close_time`, `is_closed`。不得使用不完整 Bar 作为回放/确认输入。
- 每个 Bar 另带 envelope 字段：`source_bar_id`、`source`、`sequence`、`received_at`、`available_at`、`finality_evidence`、`completeness_status`、`revision_id`、`config_version`。`is_closed=true` 只在最终性、时间、完整性三门禁同时通过后出现；接口只能转达 `PENDING/INCOMPLETE/QUARANTINED`，不得用本地时钟推定完成。
- 完成批次（`CompletionBatch`）是回放/快照的可见性单位：同 `close_time` 的到期周期先聚合、再按 `1MONTH→1W→1D→4H→1H→15M→3M` 处理，一次提交后才可被策略与前端读取；批次未提交时前端只能显示 `PENDING`，不得回填半更新快照。
- 因果性字段：`decision_at >= max(依赖输入 available_at)`；`submit_not_before = created_at + min_latency`（`min_latency` 待第 13/15 章统一）。接口不得返回由未来 Bar 推算的已完成事件。
- 规格版本以 `spec_revision`（如 `SPEC-V148-03@TIME-R1`）与 `spec_status`（`REVIEW_CANDIDATE|APPROVED`）随资源返回；候选状态下前端只能做标注/研究展示，不得据此生成交易许可或宣称阶段出口。
- 价格、数量、金额、费率在持久化和领域接口中用十进制字符串；图表投影允许数值型，仅限展示且不得回写领域数据。
- 列表支持 `limit`/`cursor`（旧端点可保留现有分页字段），结果顺序稳定。新增分页不得改变旧 response key。
- 修改标注用 `PATCH /annotations/{id}`，请求必须含 `expected_revision: integer`；修订不匹配返回 HTTP 409、`REVISION_CONFLICT` 与当前 revision（如可提供）。前端提示用户、重新 GET 并由用户决定重套编辑，不静默覆盖。
- 所有错误均稳定错误码、可读 message、可选字段路径；HTTP 状态码语义稳定（400/404/409/422/500）。
- freeze、approve、publish、rollback 等命令具备幂等语义或明确冲突错误；冻结版本不可原地变更。审计身份、时间、理由由服务端可信地产生/校验。

## 2. 基础类型（JSON Schema 概念）

```text
type DecimalText = string   // regex: ^-?\d+(\.\d+)?$
type UtcInstant = string    // RFC3339 UTC Z
type UUID = string
type AnnotationStatus = DRAFT|SUBMITTED|REVIEWED|APPROVED|FROZEN|SUPERSEDED|REJECTED|AMBIGUOUS
type LabelSource = HUMAN_PRIMARY|HUMAN_REVIEWED|PROGRAM_PREDICTION|IMPORTED|AI_SUGGESTED
type EntityType = SWING_POINT|N_STRUCTURE|ZONE|STATE_INTERVAL|PROTECTED_POINT|PULLBACK_SEQUENCE|SIGNAL_LIFECYCLE|POSITION_LIFECYCLE
type RunStatus = QUEUED|RUNNING|PASSED|FAILED|BLOCKED|CANCELLED
type BarSource = EXCHANGE_FINAL|LOCAL_AGGREGATED|HISTORICAL_VERIFIED
type CompletenessStatus = COMPLETE|PENDING|INCOMPLETE|QUARANTINED
type SpecStatus = REVIEW_CANDIDATE|APPROVED

type Envelope<T> = { data: T|null, meta: {request_id: UUID}, error: ApiError|null }
type ApiError = {code: string, message: string, field?: string, details?: object}
type Bar = {bar_id: UUID, instrument_id: string, timeframe: string,
 open_time: UtcInstant, close_time: UtcInstant, open: DecimalText,
 high: DecimalText, low: DecimalText, close: DecimalText, volume: DecimalText,
 is_closed: boolean, source: BarSource, sequence: integer,
 source_bar_id: string|null, received_at: UtcInstant, available_at: UtcInstant,
 finality_evidence: object|null, completeness_status: CompletenessStatus,
 revision_id: string|null, config_version: string, dataset_version: string}
type CompletionBatch = {batch_id: UUID, close_time: UtcInstant,
 status: "PENDING"|"COMMITTED"|"QUARANTINED", bar_ids_by_timeframe: object,
 snapshot_id: UUID|null, processed_timeframes: string[], decision_at: UtcInstant|null}
type Annotation = {annotation_id: UUID, project_id: UUID, dataset_id: UUID|null,
 entity_type: EntityType, instrument_id: string, timeframe: string,
 payload: object, label_source: LabelSource, status: AnnotationStatus,
 revision: integer, spec_version: string, spec_status: SpecStatus,
 created_at: UtcInstant, updated_at: UtcInstant}
type DatasetRef = {dataset_id: UUID, data_hash: string, range_start: UtcInstant,
 range_end: UtcInstant, timeframes: string[], spec_version: string}
type FrozenGroundTruth = {golden_dataset_id: UUID, dataset: DatasetRef,
 annotation_hash: string, time_split_hash: string, frozen_at: UtcInstant,
 baseline_replay_run_id: UUID|null, baseline_code_commit: string|null,
 baseline_config_hash: string|null}
type AsyncRun = {run_id: UUID, status: RunStatus, progress: number|null,
 created_at: UtcInstant, started_at: UtcInstant|null, finished_at: UtcInstant|null,
 error: ApiError|null, input_hash: string|null}

type SwingPoint = {point_id: UUID, instrument_id: string, timeframe: string,
 direction: "HIGH"|"LOW", price: DecimalText, occurred_at: UtcInstant,
 confirmed_at: UtcInstant, atr_snapshot: DecimalText, source_bar_id: string,
 confirmation_bar_id: string, segment_id: UUID, sequence: integer,
 price_basis: "HIGH_LOW", config_version: string, engine_revision: string,
 manual_price_override: DecimalText|null, override_reason: string|null}
type ZoneSnapshot = {zone_id: UUID, timeframe: string, zone_type: "SUPPORT"|"RESISTANCE",
 polarity: string, state: "CREATED"|"ACTIVE"|"TESTED"|"BROKEN"|"INVALIDATED",
 anchor_ids: UUID[], center: DecimalText, lower: DecimalText, upper: DecimalText,
 anchor_radius: DecimalText, base_half_width: DecimalText, half_width_cap: DecimalText,
 zone_version: integer, transition_reason: string, created_at: UtcInstant,
 activated_at: UtcInstant|null, tested_at: UtcInstant|null, terminal_at: UtcInstant|null,
 anchor_age_weeks: number, spec_version: string, config_version: string}
type StructureSnapshot = {structure_id: UUID, timeframe: string,
 kind: "SWING_STRUCTURE"|"N_STRUCTURE"|"PROTECTED_POINT"|"PULLBACK_ORIGIN",
 payload: object, version: integer, valid_from: UtcInstant, valid_to: UtcInstant|null,
 invalidation_reason: string|null, spec_version: string, config_version: string}
type CostEvent = {event_id: UUID, run_id: UUID|null, instrument_id: string,
 event_type: "FILL_FEE"|"FILL_SLIPPAGE"|"FUNDING", occurred_at: UtcInstant,
 order_role: "MAKER"|"TAKER"|null, quantity: DecimalText, price: DecimalText|null,
 amount: DecimalText, currency: string, sign: "DEBIT"|"CREDIT",
 funding_rate: DecimalText|null, bill_id: string|null, metadata_version: string,
 formula_version: string, source: string, ledger_hash: string|null}
type InstrumentMetadataRef = {instrument_id: string, instrument_type: string,
 contract_value: DecimalText|null, contract_value_currency: string|null,
 settlement_currency: string|null, quote_currency: string, base_currency: string,
 tick_size: DecimalText, lot_size: DecimalText, min_qty: DecimalText|null,
 max_qty: DecimalText|null, min_notional: DecimalText|null,
 price_precision: integer, qty_precision: integer, metadata_version: string,
 valid_from: UtcInstant, valid_to: UtcInstant|null, source: string,
 captured_at: UtcInstant}
type Diagnostic = {code: string, severity: "INFO"|"WARNING"|"BLOCKER",
 message: string, subject_type: string, subject_id: UUID|null,
 occurred_at: UtcInstant, spec_version: string, config_version: string|null,
 details: object}
```

`EntityType` 与端点实际可接受类型可能按现有 `validate_annotation_payload` 更窄；不能用枚举存在推定实现覆盖所有实体。`BLOCKED` 需保留区分规格歧义/缺引擎，建议在 `details.blocked_reason` 使用 `BLOCKED_BY_SPEC_AMBIGUITY` 或 `BLOCKED_BY_UNIMPLEMENTED_STAGE`。

## 3. 资源与操作

| 能力 | Method + path | 请求/查询重点 | 响应数据 |
|---|---|---|---|
| 元信息/图表 | GET `/meta`, `/market/snapshot`, `/market/live`, `/market/freshness` | timeframe、since | 页面 meta、图表 view model、更新游标/新闭合 Bar |
| K线/数据集 | GET `/market/bars`, `/market/datasets`, `/market/datasets/{id}`, `/market/coverage` | instrument_id, timeframe, from, to, limit, cursor, dataset_id | Bar[]、DatasetRef、coverage completeness/gaps |
| 指标/Zone预览 | GET `/indicators/series`; POST `/zones/preview` | dataset/timeframe/range、anchors、模式、配置快照 | 指标点含 `as_of_bar_time`/有效性；Zone 几何和来源信息 |
| 标注项目/标注 | GET/POST `/annotation-projects`; GET/POST `/{project_id}/annotations`; GET/PATCH/DELETE `/annotations/{id}` | project filters、entity、payload、`expected_revision` | Annotation、revision、count；DELETE 软删语义 |
| 状态/审计 | POST `/annotations/{id}/{submit|review|approve|freeze}`; GET revisions、audit-logs | actor/reason 由服务策略确定 | Annotation 状态、append-only revisions/audit |
| 人工边界覆盖 | GET/POST `/boundary-overrides`; POST `/{id}/review` | anchor reference、boundary、reason | 独立 override 状态；不可覆写程序 Zone |
| Ground Truth | GET/POST `/golden-datasets`; GET `/{id}`; POST validate/split; GET project ground-truth-hash | 来源标注、split ranges | FrozenGroundTruth、校验报告；freeze 后 immutable |
| 回放/快照 | POST/GET `/replay-runs`; GET run/events/snapshots; POST cancel; GET `/snapshots` | dataset, code/spec/config hash, timeframes, initial snapshot, mode | AsyncRun、确定性事件、snapshot refs |
| 比对 | POST comparisons by type（当前按 project/type routes）；GET `/comparisons`、`/{id}` | golden/replay/matcher version/tolerance/object/timeframe | matches/unmatched/summary/metrics；one-to-one matching |
| PB回归 | GET `/regression-cases`; POST case runs/suite; GET `/regression-runs/{id}`、assertions | case ids、input version | AsyncRun/summary/assertions；blocked 不得伪报 PASS |
| 完成批次/快照 | GET `/completion-batches`、`/{id}`；GET `/snapshots/{id}` | close_time、timeframe、batch_id | CompletionBatch、按周期的 bar_ids 与 snapshot_id；未提交批次只读 PENDING |
| 诊断/门禁 | GET `/diagnostics`、`/spec-status` | subject_type/subject_id、code、severity | Diagnostic[]、spec revision/status；只传达 blocked，不解释成交易结论 |
| 成本账本 | GET `/cost-events`、`/funding-events`；GET `/cost-summary` | run_id、instrument、时间范围、currency | CostEvent[]、按 Fill/结算汇总；净绩效受 OD-08 阻断 |
| 合约元数据 | GET `/instrument-metadata`、`/{instrument_id}/versions` | instrument_id、as_of | InstrumentMetadataRef 时间版本；重叠或缺口即拒绝选用 |
| 参数实验/配置治理 | 规格目标：experiments/trials/OOS/candidates/approve/reject/publish/rollback | 仅 RESEARCH 参数搜索；附数据、代码和 config hashes | 实验/试验、验证报告、审批/版本记录；后续能力，现状未证实实现 |

资源路径的当前真实清单以 `api.py` 的路由为兼容基准。SACW 原文设计的 calibration/config-registry API 在当前 API 中尚未完整出现，须作为后续接口提案单独评审，不可让前端假定已有。`/completion-batches`、`/diagnostics`、`/cost-events`、`/funding-events`、`/instrument-metadata` 同属**设计提案**：当前实现无对应路由，落地分别由 TASK-029、TASK-031/032、TASK-034/035 承接，不得先由前端假定可用。

## 4. 核心 payload 约束

- `SwingPoint`：必含 `price_basis=HIGH_LOW`、`occurred_at`、`confirmed_at`、`source_bar_id`、`confirmation_bar_id`、`atr_snapshot`、`segment_id`、`sequence`、`engine_revision`；`confirmed_at >= occurred_at`，且 `confirmed_at` 只能落在确认 Bar 的结束时刻。候选价差语义（`k=2.0`）与候选态 `state` 只作为研究展示，不由接口固化为真值。
- **`occurred_at` 口径**：SPEC-04 候选定义为极值来源 Bar 的**结束时刻**；历史实现 TASK-004 使用来源 Bar 的 `open_time`。该冲突未决，接口同时返回 `source_bar_id` 供对齐，禁止客户端自行换算或据此判等；冲突登记 `OPEN_DECISION` 并阻断以时间为键的自动匹配。
- `SwingPoint` 的 `segment_id`/`sequence` 是唯一键分量：`(instrument_id, timeframe, segment_id, sequence)`。缺口、坏 Bar、重同步产生新段，前端不得跨段连线。
- `Zone`：`anchors`、`polarity`、`mode` (`ANCHOR_ONLY|HUMAN_BOUNDARY|ANCHOR_ONLY_WITH_OVERRIDE`)；程序几何、人工边界双轨保存，服务端负责 ANCHOR_ONLY geometry。程序几何须回传 `center`、`lower`、`upper`、`anchor_radius`、`base_half_width`、`half_width_cap`、`zone_version`、`transition_reason`；`BROKEN`/`INVALIDATED` 为终态，不得原地复活或裁剪超限宽度。
- `Zone` 测试/突破判定由服务端按规格顺序执行（校验 → 旧边界突破 → 锚点到期/归属 → 测试 → 原子发布）；接口只回传结果与 `occurred_at`，不接受客户端判定写回。`SETUP_ZONE_REVISED` 仅在 Setup 尚未产出 Signal 时出现，已出 Signal 的 Zone 快照冻结。
- `ProtectedPoint` / `NStructure` / `PullbackOrigin`：以 `StructureSnapshot` 版本化返回；保护点失效、结构失效与 `UNRESOLVED` 必须给 `invalidation_reason`，不补算。状态映射按规格：保护点失效 1MONTH→`UNKNOWN`，1W/1D/4H/1H→`TRANSITION`，15M/3M 不适用。
- `StateInterval`：state、`valid_from`/`valid_to`、source/review metadata；只标有定义的状态/周期值。
- 每个 program event 必含 source bar、`occurred_at`、`confirmed_at`（若适用）、spec/code/config hash；不得由客户端写入为程序真值。
- `CostEvent`：Fill 级费用与滑点、Funding 结算事件分列；`amount` 带币种与正负号，借方为现金流出。滑点按 `FIXED_TICKS_V1` 只在成交侧计算一次，不得与费用或价差重复计入。`CostEvent.metadata_version` 必须指向当时有效的 `InstrumentMetadataRef`。
- `InstrumentMetadataRef`：时间版本区间不得重叠或留缺口；`contract_value` 仅在线性合约且元数据明确时参与换算，`ctVal` 不得默认按报价币解释；缺 FX 或缺元数据时接口返回 `BLOCKED`，不返回估算结果。
- `Diagnostic.code` 至少包含 `SPEC_AMBIGUITY`、`AMBIGUOUS_INTRABAR_ORDER`、`DATA_GAP`、`ZONE_INPUT_INVALID`、`ZONE_GEOMETRY_LIMIT_EXCEEDED`、`SETUP_ZONE_REVISED`、`BLOCKED_BY_UNIMPLEMENTED_STAGE`；未注册码不得由前端造名，注册表见 [`32-诊断码注册表.md`](./32-诊断码注册表.md)。

## 5. 并发、冻结与安全

- 每次写请求由后端校验项目、数据集范围、实体特定规则、状态机和权限；客户端校验只为交互提示，非安全边界。
- `expected_revision` 是强制并发令牌。revision 冲突不得自动重放 PATCH。
- 只有 HUMAN_PRIMARY/HUMAN_REVIEWED 且 APPROVED/FROZEN 的人工标注可按规格进入 GT；冻结时计算并保存数据/标注/切分 hash 和基线信息。
- 回放、比对、实验以不可变输入引用（dataset/golden/config/code/spec/matcher versions）运行，输出带 run ID 和 input hash。
- 用户取消只是请求，不保证正在执行工作可立即中断；状态由后端持久记录，断连可按 ID 恢复查询。
- 规格状态是数据的一部分：五章当前为 `REVIEW_CANDIDATE`，接口可保存、展示和比较候选字段，但不得把候选语义当作 `APPROVED` 真值。ACCEPTED/冻结产物必须同时记录 `spec_version` 与 `spec_status`；候选期间的 Gate/验收结论不得升级为阶段出口。
- 成本与绩效接口不返回未经 OD-08 许可的净绩效结论；缺失费率、元数据版本、Funding 记录或 FX 时只返回 blocked 与缺项清单。
- 当前无认证/授权规格明确实现的证据。单人本地工作台可沿用部署边界，但若网络暴露，须先补认证/CSRF/权限要求；方案不臆造 actor 权威性。

## 6. 现状兼容及待定项

- API 前缀与 envelope 可兼容既有实现；其中现有 response fields、分页键、diagnostic codes 以代码和测试为准，变更必须版本化或向后兼容。
- 现有实现使用 SQLite、标准库 HTTP、Parquet/内存快照；原 SACW 推荐 PostgreSQL/FastAPI 属目标技术建议，迁移需要单独决策，不在本方案中静默实施。
- P0-E、OD-05 未确认通过，故 P1-A 状态验收与其后的 calibration 不以当前框架/占位表/API 视作完成。
- 五章候选规格（SPEC-03 `TIME-R1`、04 `ZIGZAG-R1`、05 `SWING-R1`、06 `ZONE-R1`、14 `COST-R1`）在 TASK-095 通过前不具批准效力；新增字段与端点均为提案，接口不得先行冻结。
- 开放决策必须原样阻断对应输出：`OD-ZZ-01…05`（ZigZag 口径）、`OD-ZONE-01…06`（Zone 几何/测试/寿命）、`OD-06`（成本口径）、`OD-08`（净绩效）、`OPEN_DECISION-SWING-ORDER`/`SHORT-N-TRADING`/`PULLBACK-BOUNDARY`/`STATE-ENUM`（结构层）。
- Bar 时间口径冲突（SPEC-04 `occurred_at`=来源 Bar 结束 vs TASK-004 `open_time`）未决，见 §4；解决前既有一致性测试与 Golden 不得按新口径静默重算。
- OPEN_DECISIONS（特别 OD-01…07）及 SACW `SPEC_AMBIGUITY` 均作为业务门禁。接口只能传达 blocked/unknown，不定义新策略语义。
