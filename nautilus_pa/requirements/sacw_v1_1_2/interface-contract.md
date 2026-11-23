# SACW 前后端统一接口契约（设计基线）

版本：SACW V1.1.2 / API v1。本文是前端与后端两份 plan 的唯一 wire-contract 来源。当前 API 已在标准库 HTTP 服务与 Vanilla JS 中使用；此文界定兼容契约及方案新增点，不宣称所有资源均已实现。

## 1. 共通协议

- Base path `/api/v1`；JSON UTF-8。成功响应 `{data: T, meta: {request_id: string}, error: null}`；失败响应 `{data: null, meta: {request_id: string}, error: {code: string, message: string, field?: string}}`。
- 时间以带时区 UTC ISO-8601 字符串（`Z`）表达；时间区间左闭右开。Bar 有 `open_time`, `close_time`, `is_closed`。不得使用不完整 Bar 作为回放/确认输入。
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

type Envelope<T> = { data: T|null, meta: {request_id: UUID}, error: ApiError|null }
type ApiError = {code: string, message: string, field?: string, details?: object}
type Bar = {bar_id: UUID, instrument_id: string, timeframe: string,
 open_time: UtcInstant, close_time: UtcInstant, open: DecimalText,
 high: DecimalText, low: DecimalText, close: DecimalText, volume: DecimalText,
 is_closed: boolean, source: string, dataset_version: string}
type Annotation = {annotation_id: UUID, project_id: UUID, dataset_id: UUID|null,
 entity_type: EntityType, instrument_id: string, timeframe: string,
 payload: object, label_source: LabelSource, status: AnnotationStatus,
 revision: integer, spec_version: string, created_at: UtcInstant, updated_at: UtcInstant}
type DatasetRef = {dataset_id: UUID, data_hash: string, range_start: UtcInstant,
 range_end: UtcInstant, timeframes: string[], spec_version: string}
type FrozenGroundTruth = {golden_dataset_id: UUID, dataset: DatasetRef,
 annotation_hash: string, time_split_hash: string, frozen_at: UtcInstant,
 baseline_replay_run_id: UUID|null, baseline_code_commit: string|null,
 baseline_config_hash: string|null}
type AsyncRun = {run_id: UUID, status: RunStatus, progress: number|null,
 created_at: UtcInstant, started_at: UtcInstant|null, finished_at: UtcInstant|null,
 error: ApiError|null, input_hash: string|null}
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
| 参数实验/配置治理 | 规格目标：experiments/trials/OOS/candidates/approve/reject/publish/rollback | 仅 RESEARCH 参数搜索；附数据、代码和 config hashes | 实验/试验、验证报告、审批/版本记录；后续能力，现状未证实实现 |

资源路径的当前真实清单以 `api.py` 的路由为兼容基准。SACW 原文设计的 calibration/config-registry API 在当前 API 中尚未完整出现，须作为后续接口提案单独评审，不可让前端假定已有。

## 4. 核心 payload 约束

- `SwingPoint`: `direction`, `price: DecimalText`, `occurred_at`, `confirmed_at`, `source_bar_id`, `manual_price_override`, `override_reason`；`confirmed_at >= occurred_at`。
- `NStructure`: 四个 Swing ID、方向、validity、判定/失效时间与理由；无明确 V1.4.8 规则的失效状态用 ambiguity，不补算。
- `Zone`: anchors、polarity、mode (`ANCHOR_ONLY|HUMAN_BOUNDARY|ANCHOR_ONLY_WITH_OVERRIDE`)；程序几何、人工边界双轨保存，服务端负责 ANCHOR_ONLY geometry。
- `StateInterval`: state、`valid_from`/`valid_to`、source/review metadata；只标有定义的状态/周期值。
- 每个 program event 必含 source bar、`occurred_at`、`confirmed_at`（若适用）、spec/code/config hash；不得由客户端写入为程序真值。

## 5. 并发、冻结与安全

- 每次写请求由后端校验项目、数据集范围、实体特定规则、状态机和权限；客户端校验只为交互提示，非安全边界。
- `expected_revision` 是强制并发令牌。revision 冲突不得自动重放 PATCH。
- 只有 HUMAN_PRIMARY/HUMAN_REVIEWED 且 APPROVED/FROZEN 的人工标注可按规格进入 GT；冻结时计算并保存数据/标注/切分 hash 和基线信息。
- 回放、比对、实验以不可变输入引用（dataset/golden/config/code/spec/matcher versions）运行，输出带 run ID 和 input hash。
- 用户取消只是请求，不保证正在执行工作可立即中断；状态由后端持久记录，断连可按 ID 恢复查询。
- 当前无认证/授权规格明确实现的证据。单人本地工作台可沿用部署边界，但若网络暴露，须先补认证/CSRF/权限要求；方案不臆造 actor 权威性。

## 6. 现状兼容及待定项

- API 前缀与 envelope 可兼容既有实现；其中现有 response fields、分页键、diagnostic codes 以代码和测试为准，变更必须版本化或向后兼容。
- 现有实现使用 SQLite、标准库 HTTP、Parquet/内存快照；原 SACW 推荐 PostgreSQL/FastAPI 属目标技术建议，迁移需要单独决策，不在本方案中静默实施。
- P0-E、OD-05 未确认通过，故 P1-A 状态验收与其后的 calibration 不以当前框架/占位表/API 视作完成。
- OPEN_DECISIONS（特别 OD-01…07）及 SACW `SPEC_AMBIGUITY` 均作为业务门禁。接口只能传达 blocked/unknown，不定义新策略语义。
