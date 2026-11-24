# SACW 后端技术设计方案

> TASK-009 / REQ-011；增量修订 TASK-096（2026-11-23）。与前端通过 [`统一接口契约`](../interface-contract.md) 解耦而协同。本文列出目标模块和 Python 签名，不实现代码。策略语义唯一依据为 V1.4.8 结构化 spec；当前功能成熟度以源码、测试与执行计划为证据，不以规格架构图推定实现。五章（03/04/05/06/14）现为 `REVIEW_CANDIDATE`，本文新增的数据契约与门禁设计均为候选提案，批准前不得据此宣称阶段出口。

## 1. 目标与边界

后端承担 HTTP wire API、领域/应用编排、历史行情读入、人工标注与版本持久化、确定性回放/比较/回归，以及未来受约束的实验/配置治理。真实数据源以本地 Parquet/catalog 与当前数据服务为准。当前标准库 HTTP + SQLite 是兼容基线；FastAPI/PostgreSQL/DuckDB 是 SACW 原规格的建议目标，升级需单独任务和迁移决策。

后端不在此工作台中提交交易所真实订单，不复制策略算法，不把前端输入视为可信，不推断任何 OPEN_DECISION。Setup/Signal/Execution/风险及参数优化器为未完成/接口态的部分不可假称落地。

## 2. 模块划分与责任

| 模块/现有入口 | 职责 | 不负责 |
|---|---|---|
| `presentation.api` | HTTP routing、解析、状态码、Envelope/Error、request ID；请求校验和 Application 调度 | SQL 细节、策略状态算法 |
| `application.data_service` | Parquet/catalog 查询、Bar 转换、数据覆盖/质量、七周期回放上下文、chart projection 输入 | 标注写入、浏览器格式 |
| `application.annotation_store` | SQLite schema/迁移、CRUD、事务、revision、状态迁移、软删、审计、GT/dataset/splits | 匹配/策略运算 |
| `application.matching` | 人工/程序结构一对一差异计算、matcher version 与诊断 | 修改任何人工/程序事实、策略参数搜索 |
| `application.regression` | PB cases 加载、适用 evaluator 执行、assertions 和 run 持久化、blocked 分类 | 未实现引擎代跑/伪 PASS |
| `application.snapshot` | 初始/回放状态快照的生成、校验/可信度说明 | 未定的 ATR 或策略语义 |
| `presentation.chart_data` | domain -> chart wire projection、UTC/秒、display-only 数值序列 | 精确计算/数值写回 |
| `config` | 策略参数分类、load/validation/fingerprint/startup gates | 掩盖未决项或自动审批 |
| `domain` | 纯 Python bar/timeframe/indicator/structure/state/lifecycle 模型与规则 | SQLite/HTTP/Nautilus imports |
| Future `calibration`, `config_registry`, `reporting` | RESEARCH-only experiment/search/OOS/approval/version publishing/report | 本阶段未实现内容、自动生效 |
| Future `worker` | 持久运行队列、取消/恢复/状态更新 | 把进程内任务当持久事实 |

应用层依赖方向：HTTP adapter → application service → domain/config + store ports；基础 SQLite implementation 与 Parquet repository 由 application adapters 提供；domain 禁止依赖 presentation/store/Nautilus。当前代码尚未全部采用显式 ports；若重构依赖注入，逐步做，不动无关策略核心。

## 3. 核心数据结构（Python 模型草图）

以下为设计级定义，不要求原样复制/新增公共 API；现有 `SacwStore` 部分字段在 SQLite row 与 JSON 中实现。

```python
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Protocol, TypedDict
from uuid import UUID
from datetime import datetime

class EntityType(StrEnum):
    SWING_POINT = "SWING_POINT"; N_STRUCTURE = "N_STRUCTURE"; ZONE = "ZONE"
    STATE_INTERVAL = "STATE_INTERVAL"; PROTECTED_POINT = "PROTECTED_POINT"
    PULLBACK_SEQUENCE = "PULLBACK_SEQUENCE"; SIGNAL_LIFECYCLE = "SIGNAL_LIFECYCLE"
    POSITION_LIFECYCLE = "POSITION_LIFECYCLE"
class AnnotationStatus(StrEnum):
    DRAFT = "DRAFT"; SUBMITTED = "SUBMITTED"; REVIEWED = "REVIEWED"
    APPROVED = "APPROVED"; FROZEN = "FROZEN"; SUPERSEDED = "SUPERSEDED"
    REJECTED = "REJECTED"; AMBIGUOUS = "AMBIGUOUS"
class LabelSource(StrEnum):
    HUMAN_PRIMARY = "HUMAN_PRIMARY"; HUMAN_REVIEWED = "HUMAN_REVIEWED"
    PROGRAM_PREDICTION = "PROGRAM_PREDICTION"; IMPORTED = "IMPORTED"; AI_SUGGESTED = "AI_SUGGESTED"
class RunStatus(StrEnum):
    QUEUED = "QUEUED"; RUNNING = "RUNNING"; PASSED = "PASSED"
    FAILED = "FAILED"; BLOCKED = "BLOCKED"; CANCELLED = "CANCELLED"

@dataclass(frozen=True, slots=True)
class Bar:
    instrument_id: str; timeframe: str; open_time_ns: int; close_time_ns: int
    open: Decimal; high: Decimal; low: Decimal; close: Decimal; volume: Decimal
    is_closed: bool; source_bar_id: str
@dataclass(frozen=True, slots=True)
class Annotation:
    annotation_id: UUID; project_id: UUID; dataset_id: UUID | None
    entity_type: EntityType; instrument_id: str; timeframe: str
    payload: dict[str, object]; label_source: LabelSource; status: AnnotationStatus
    revision: int; spec_version: str; created_at: datetime; updated_at: datetime
@dataclass(frozen=True, slots=True)
class AnnotationPatch:
    expected_revision: int; payload: dict[str, object]; reason: str | None
@dataclass(frozen=True, slots=True)
class FrozenDataset:
    dataset_id: UUID; data_hash: str; annotation_hash: str; time_split_hash: str
    spec_version: str; annotation_rule_version: str; frozen_at: datetime
    baseline_replay_run_id: UUID | None; baseline_code_commit: str | None
    baseline_config_hash: str | None
@dataclass(frozen=True, slots=True)
class ReplayRequest:
    dataset_id: UUID; spec_version: str; code_commit: str; config_version_id: UUID
    timeframes: tuple[str, ...]; initial_snapshot_id: UUID | None; mode: str
@dataclass(frozen=True, slots=True)
class RunRecord:
    run_id: UUID; status: RunStatus; input_hash: str; progress: float | None
    blocked_reason: str | None; error_code: str | None
@dataclass(frozen=True, slots=True)
class MatcherConfig:
    matcher_version: str; max_time_tolerance_bars: int
    max_price_tolerance_atr: Decimal; weight_time: Decimal; weight_price: Decimal
    weight_confirmation: Decimal = Decimal("0")
@dataclass(frozen=True, slots=True)
class RegressionAssertion:
    case_id: str; assertion_id: str; status: str; detail: dict[str, object]
@dataclass(frozen=True, slots=True)
class ApiError:
    code: str; message: str; field: str | None = None
```

原代码中的 `annotation_store.ENTITY_TYPES` 等是 tuple/frozenset 字符串常量；`matching.MatchType`/`StructureMatch` 是 StrEnum、`MatcherConfig` frozen dataclass、`SwingCandidate` frozen dataclass；`api.HandlerLike` 是 Protocol。该接口草图不要求将数据库内字符串批量改为 enum，也不得改变 JSON wire names。

### 3.1 五章修订新增数据契约（候选，TASK-096 对齐）

以下为 SPEC-03/04/05/06/14 候选语义在领域/持久层的设计级补充，字段名与 [`统一接口契约`](../interface-contract.md) 第 2 节一致；实现分别由 TASK-029、030、031、032、034 承接，未批准前只作为设计约束与校验目标。

```python
class BarSource(StrEnum):
    EXCHANGE_FINAL = "EXCHANGE_FINAL"; LOCAL_AGGREGATED = "LOCAL_AGGREGATED"
    HISTORICAL_VERIFIED = "HISTORICAL_VERIFIED"
class CompletenessStatus(StrEnum):
    COMPLETE = "COMPLETE"; PENDING = "PENDING"
    INCOMPLETE = "INCOMPLETE"; QUARANTINED = "QUARANTINED"

@dataclass(frozen=True, slots=True)
class BarEnvelope:
    bar_id: str; source_bar_id: str | None; sequence: int
    received_at_ns: int; available_at_ns: int; finality_evidence: dict[str, object] | None
    completeness_status: CompletenessStatus; revision_id: str | None
    config_version: str

@dataclass(frozen=True, slots=True)
class CompletionBatch:
    batch_id: UUID; close_time_ns: int; status: str  # PENDING|COMMITTED|QUARANTINED
    bar_ids_by_timeframe: dict[str, list[str]]; processed_timeframes: tuple[str, ...]
    snapshot_id: UUID | None; decision_at_ns: int | None

@dataclass(frozen=True, slots=True)
class SwingPointRecord:
    point_id: UUID; direction: str; price: Decimal; occurred_at_ns: int
    confirmed_at_ns: int; atr_snapshot: Decimal; source_bar_id: str
    confirmation_bar_id: str; segment_id: UUID; sequence: int
    price_basis: str; config_version: str; engine_revision: str

@dataclass(frozen=True, slots=True)
class ZoneSnapshot:
    zone_id: UUID; zone_type: str; state: str; anchor_ids: tuple[UUID, ...]
    center: Decimal; lower: Decimal; upper: Decimal; anchor_radius: Decimal
    base_half_width: Decimal; half_width_cap: Decimal; zone_version: int
    transition_reason: str; anchor_age_weeks: int; config_version: str

@dataclass(frozen=True, slots=True)
class StructureSnapshot:
    structure_id: UUID; kind: str; payload: dict[str, object]; version: int
    valid_from_ns: int; valid_to_ns: int | None; invalidation_reason: str | None

@dataclass(frozen=True, slots=True)
class CostEvent:
    event_id: UUID; run_id: UUID | None; event_type: str; occurred_at_ns: int
    order_role: str | None; quantity: Decimal; price: Decimal | None
    amount: Decimal; currency: str; sign: str; funding_rate: Decimal | None
    bill_id: str | None; metadata_version: str; formula_version: str
    ledger_hash: str | None

@dataclass(frozen=True, slots=True)
class InstrumentMetadataRef:
    instrument_id: str; instrument_type: str; contract_value: Decimal | None
    contract_value_currency: str | None; settlement_currency: str | None
    quote_currency: str; base_currency: str; tick_size: Decimal; lot_size: Decimal
    min_qty: Decimal | None; max_qty: Decimal | None; min_notional: Decimal | None
    price_precision: int; qty_precision: int; metadata_version: str
    valid_from_ns: int; valid_to_ns: int | None; source: str; captured_at_ns: int
```

约束：`Bar` 的既有字段与构造方式保持向后兼容，envelope 是附加视图，`is_closed` 只能由三门禁推导，禁止调用方写入；`sequence` 按 `(instrument_id, timeframe)` 独立递增且重启可恢复，重复 Bar 不占号；`CompletionBatch` 是快照可见性单元，批次提交前的部分 Bar 只能标记 `PENDING`。`SwingPointRecord.occurred_at_ns` 的“来源 Bar 结束时刻”与历史 TASK-004 的 `open_time` 口径冲突，需在 OPEN_DECISION 裁定前保留 `source_bar_id` 并禁止按时间键自动对齐。`InstrumentMetadataRef` 区间不得重叠/缺口；缺 FX 或缺元数据时成本计算返回 blocked，不生成估算值。

## 4. 模块间函数签名（设计提案，不含实现）

```python
class MarketDataRepository(Protocol):
    def get_bars(self, *, instrument_id: str, timeframe: str, start_ns: int,
                 end_ns: int, limit: int, cursor: str | None = None) -> tuple[list[Bar], str | None]: ...
    def list_datasets(self, *, instrument_id: str | None = None) -> list[dict[str, object]]: ...
    def get_coverage(self, *, dataset_id: UUID, timeframes: tuple[str, ...]) -> dict[str, object]: ...

class AnnotationRepository(Protocol):
    def create(self, *, project_id: UUID, payload: dict[str, object]) -> Annotation: ...
    def get(self, *, annotation_id: UUID) -> Annotation | None: ...
    def revise(self, *, annotation_id: UUID, patch: AnnotationPatch) -> Annotation: ...
    def transition(self, *, annotation_id: UUID, action: str, actor: str | None,
                   reason: str | None) -> Annotation: ...
    def list_revisions(self, *, annotation_id: UUID) -> list[dict[str, object]]: ...
    def freeze_ground_truth(self, *, project_id: UUID, dataset_id: UUID,
                            baseline: dict[str, object]) -> FrozenDataset: ...

class DataServiceProtocol(Protocol):
    def chart_snapshot(self, *, timeframe: str, start_ns: int | None,
                       end_ns: int | None, limit: int) -> dict[str, object]: ...
    def query_bars(self, *, timeframe: str, start_ns: int, end_ns: int,
                   limit: int, cursor: str | None = None) -> dict[str, object]: ...
    def indicator_series(self, *, timeframe: str, indicator: str,
                         start_ns: int, end_ns: int) -> dict[str, object]: ...
    def zone_preview(self, *, timeframe: str, anchors: list[str], mode: str,
                     config_version: str) -> dict[str, object]: ...

class MatchingService(Protocol):
    def match_swings(self, *, human: list[dict[str, object]], program: list[dict[str, object]],
                     config: MatcherConfig) -> dict[str, object]: ...
    def match_n_structures(self, *, human: list[dict[str, object]], program: list[dict[str, object]],
                           swing_matches: list[dict[str, object]], config: MatcherConfig) -> dict[str, object]: ...
    def match_zones(self, *, human: list[dict[str, object]], program: list[dict[str, object]],
                    config: MatcherConfig) -> dict[str, object]: ...
    def match_state_intervals(self, *, human: list[dict[str, object]], program: list[dict[str, object]],
                              config: MatcherConfig) -> dict[str, object]: ...

class ReplayService(Protocol):
    def submit(self, request: ReplayRequest) -> RunRecord: ...
    def get_run(self, *, run_id: UUID) -> RunRecord | None: ...
    def list_events(self, *, run_id: UUID, cursor: str | None = None,
                    limit: int = 500) -> dict[str, object]: ...
    def cancel(self, *, run_id: UUID) -> RunRecord: ...

class RegressionService(Protocol):
    def run_cases(self, *, case_ids: list[str], dataset_id: UUID | None,
                  config_version: str) -> RunRecord: ...
    def get_outcome(self, *, run_id: UUID) -> dict[str, object]: ...

class CalibrationService(Protocol):
    def create_experiment(self, *, dataset_id: UUID, split_id: UUID,
                          parameter_space: dict[str, object], objective: dict[str, object]) -> RunRecord: ...
    def validate_out_of_sample(self, *, experiment_id: UUID) -> dict[str, object]: ...
    def publish_candidate(self, *, candidate_id: UUID, approver: str,
                          reason: str) -> dict[str, object]: ...
```

### 4.1 五章修订新增服务边界（候选，设计提案）

```python
class MarketEnvelopeRepository(Protocol):
    def get_bars(self, *, instrument_id: str, timeframe: str, start_ns: int,
                 end_ns: int) -> list[tuple[Bar, BarEnvelope]]: ...
    def get_completion_batch(self, *, close_time_ns: int) -> CompletionBatch | None: ...

class CompletionBatchService(Protocol):
    def accept_bar(self, *, bar: Bar, envelope: BarEnvelope) -> str: ...   # ACCEPTED|DUPLICATE|QUARANTINED
    def commit_batch(self, *, close_time_ns: int) -> CompletionBatch: ...
    def read_snapshot(self, *, snapshot_id: UUID) -> dict[str, object]: ...

class StructureService(Protocol):
    def swing_points(self, *, instrument_id: str, timeframe: str,
                     segment_id: UUID | None) -> list[SwingPointRecord]: ...
    def protection_snapshots(self, *, instrument_id: str, timeframe: str) -> list[StructureSnapshot]: ...
    def structure_snapshots(self, *, instrument_id: str, timeframe: str) -> list[StructureSnapshot]: ...

class ZoneService(Protocol):
    def zone_snapshots(self, *, instrument_id: str, timeframe: str) -> list[ZoneSnapshot]: ...
    def on_completion_batch(self, *, batch: CompletionBatch) -> list[ZoneSnapshot]: ...

class CostLedgerService(Protocol):
    def record_fill(self, *, run_id: UUID, fill: dict[str, object]) -> list[CostEvent]: ...
    def apply_funding(self, *, run_id: UUID, settlement: dict[str, object]) -> CostEvent: ...
    def summarize(self, *, run_id: UUID) -> dict[str, object]: ...  # OD-08 未决时只返回 blocked

class InstrumentMetadataRepository(Protocol):
    def resolve(self, *, instrument_id: str, at_ns: int) -> InstrumentMetadataRef: ...

class DiagnosticService(Protocol):
    def emit(self, *, code: str, severity: str, subject_type: str,
             subject_id: UUID | None, details: dict[str, object]) -> None: ...
```

这些 Protocol 与 §3.1 一样是未来边界，不代表现存类；`CompletionBatchService` 未实现时必须以 `BLOCKED_BY_UNIMPLEMENTED_STAGE` 暴露，而不是让 `data_service` 直接假定 Bar 连续。`CostLedgerService.summarize` 在 OD-08 与元数据/FX 未齐时返回缺项清单，不返回净绩效数值。

当前代码签名优先，方案 Protocol 是未来解耦边界；特别 `CalibrationService` 是未来设计接口，不代表现存后端类。所有端点 handler 只负责 wire -> domain request 与 DomainError -> ApiError 转换，不能把 SQL/算法堆进 handler。

## 5. API/application 责任分解

1. `ApiRouter.dispatch`：method/path/body/query → handler；限制异常映射稳定、统一 envelope/request_id。未找到匹配路由返回 404，输入错误按契约拒绝。
2. Annotation command：校验 entity payload、项目/数据集/spec版本、状态迁移与 revision；单事务追加 revision/audit，冻结/删除遵守不可变边界。
3. Replay command：输入引用经校验、生成可复现 input hash，持久化 run 状态；工作完成/异常/取消都以状态机写库，事件分页读取。初始单进程任务不可等同持久分布式 queue。
4. Comparison query/command：限定相同数据、周期、范围与类型；固定 matcher version，匹配输出只读存储且不可反写 annotation。
5. Regression runner：PB-01..51 每项须有 evaluator 或明确 blocked；正/负断言均需真实计算；一个 blocked case 不得被总结成全 suite PASS。当前若需修正需单独任务与验收，不在本技术设计任务直接变更。
6. Calibration：后续工作只开放 RESEARCH 参数白名单；实验固定 dataset/code/spec/config/split/matcher/hash，train/validation/holdout 隔离；要求 P0-E 与 OD-05 冻结及阶段门禁。FIXED/REQUIRED/METADATA 和状态机逻辑不得进入搜索。
7. Config registry：candidate -> OOS report -> human approval/reject -> explicit publish -> rollback；发布不可隐式替换运行配置，记录 actor/reason/hash。
8. Bar 摄入与完成批次：写入端只接受带 envelope 的 Bar，按最终性、时间基线、完整性三门禁推导 `is_closed`；重复 Bar 幂等、冲突/迟到隔离、缺失不合成。同 `close_time` 的批次先按 3M→15M→1H→4H→1D 递归聚合、再 `1D→1W` 与 `1D→1MONTH` 分叉，按 `1MONTH→1W→1D→4H→1H→15M→3M` 屏障顺序处理并由一次快照提交；`sequence` 独立递增、重启可恢复。
9. 结构与区域：ZigZag/保护点/N 结构/Zone 只在输入 Bar 已闭合且批次已提交后计算；确认不回溯，同一 Bar 内顺序歧义发 `AMBIGUOUS_INTRABAR_ORDER` 并 `DEFER_NO_UPDATE`；Zone 终态不可复活、超几何上限拒绝合并不裁剪；结构与保护点快照各自版本化。
10. 成本账本与元数据：Fill 级费用/滑点、Funding 结算事件、`InstrumentMetadataRef` 时间版本与 FX 一致性是计算前置；缺任一项返回 blocked 清单。净绩效输出受 OD-08 阻断，`FIXED_TICKS_V1` 滑点只计一次。
11. 诊断：只发注册表内 code（`SPEC_AMBIGUITY`、`AMBIGUOUS_INTRABAR_ORDER`、`DATA_GAP`、`ZONE_INPUT_INVALID`、`ZONE_GEOMETRY_LIMIT_EXCEEDED`、`SETUP_ZONE_REVISED`、`BLOCKED_BY_UNIMPLEMENTED_STAGE`），不得由 application 层临时造码。

## 6. 实施顺序与依赖

本节为能力依赖；当前增量调度、复用入口与验证见 §11 和执行计划当前入口。
模型/Protocol 草图不构成先拆分全部 application 服务的前置条件。

- **B00 接口与并发安全**：统一 API payload，强制 PATCH `expected_revision` 与 409；前端随后对接。独立于策略引擎，但先于并发编辑验收。
- **B01a replay/comparison 持久链**：确认 replay event 存储及比较消费来源、hash 确定性；依赖 store schema 与 API 契约。
- **B01b 回归器**：PB 断言 mapping、负向 evaluator、blocked classification、run 汇总正确；依赖 domain 能力和持久化。阻塞不得误算 PASS。
- **B02b 标注工具/边界**：依赖 B00、标注 schema 与 API；与 B02a 可按文件互斥平行。
- **B03a 数据冻结/审阅**：数据集、annotation、split hash、审批与审计；依赖 annotation store/API；OD-05 的样本/责任/裁决/统计定义必须经授权冻结。
- **P0-E 输入冻结 / B03b 输出验收分离**：PB-01…59 场景、期望及可用夹具先冻结；当前阶段适用 PB 执行，后续 PB 在对应功能阶段执行。P0-E 依赖 B01b、B03a、适用 P0-A…F；B03b 的状态统计报告在 P1-A 实现后产出，不倒置为编码前置。当前没有证据可宣称通过。
- **P1-A**：只有 P0-E 与 OD-05 证据均通过才可准入；不是当前立即实施项目。OD-04 仍限制相关状态迁移。
- **B02a / P0-F 成本元数据**：可与工具/回归工作并行但涉及独立风险精度、配置门禁；不得改变交易 API 语义。
- **B04→B05→B06→B07→B08→B02c→B09**：严格按执行计划的策略链依赖推进；Setup/Signal/Execution/Risk/Order/Portfolio 回放逐阶段实现验收，B02c 依赖 B06 与 B08，B09 依赖 P0–P2。
- **B10b→B10c→B10d**：配置参数白名单/指纹先于实验与搜索，后者依赖 B09 和 OOS 数据；发布依赖人工审批。不得绕开 OD/冻结门禁。

该顺序将 SACW 批次与 V1.4.8 P 阶段作双轴追踪，不把批次号映射为策略阶段的同义词。任务实际状态只由 tasks.json 确认。

五章修订对应的任务链（候选语义，全部依赖 TASK-095 门禁）：

| 规格 | 任务 | 本方案承接点 |
|---|---|---|
| SPEC-03 `TIME-R1` | TASK-029 | §3.1 `BarEnvelope`、`CompletionBatch`；§4.1 `MarketEnvelopeRepository`/`CompletionBatchService`；§5.8 |
| SPEC-04 `ZIGZAG-R1` | TASK-030 | §3.1 `SwingPointRecord`；§5.9；`occurred_at` 口径冲突待 OPEN_DECISION |
| SPEC-05 `SWING-R1` | TASK-031 | §3.1 `StructureSnapshot`；§4.1 `StructureService`；§5.9 |
| SPEC-06 `ZONE-R1` | TASK-032 | §3.1 `ZoneSnapshot`；§4.1 `ZoneService`；§5.9 |
| SPEC-14 `COST-R1` | TASK-034、TASK-035 | §3.1 `CostEvent`/`InstrumentMetadataRef`；§4.1 `CostLedgerService`/`InstrumentMetadataRepository`；§5.10 |
| 候选门禁 | TASK-095 | 规格批准与开放决策冻结；未通过时上层任务只可研究/设计 |

TASK-033（跨层快照/诊断集成）、TASK-036/037/038 等下游在候选解除后才可按新契约验收；当前顺序不代表可跳过 P0-E/OD-05。

## 7. 风险点

| 风险 | 影响 | 缓解/门禁 |
|---|---|---|
| SQLite 当前单机事务/进程锁能力有限 | 并发与多worker时数据库锁、写覆盖 | 先强制 revision/事务；若扩展多进程再评估 PostgreSQL 迁移，不虚构现已有能力 |
| application 模块集多职责且 handler 直接耦合 | API 修改易影响存储/计算 | 以小步引入服务接口、保留现有行为测试，不全盘分层重写 |
| 数据服务缓存只按最新闭合 Bar 侦测变化 | 历史 Bar 更正可能陈旧 | 数据 hash/version 检测、显式失效与回放；必要时定期审计，不宣称实时强一致 |
| DB schema migration/可恢复性 | 用户 SQLite 数据损坏或新旧版本错配 | schema version、备份、事务迁移、只增不删审计；禁止覆写实际 var 数据 |
| 数值从 float 混入持久模型 | 价格/手续费/数量偏差 | 领域 Decimal，序列化十进制文本；仅图表 adapter 做 float |
| 冻结 GT 哈希非规范化 | 同一事实 hash 漂移或冻结错误 | 字段规范排序、canonical serialization、版本内容 hash；冻结后新版本派生 |
| PB 当前执行覆盖不等于 51/51 可执行通过 | 错误门禁放行 P1-A | 每条 evaluator/blocked 原因与验收证据分离；suite 汇总见阻塞即不完成 |
| 状态区间仅基础重叠匹配、Macro-F1 未冻结 | 统计不可复现 | OD-05 明确后再制定指标和门槛；不由现存代码“默认定义” |
| Setup/Signal/执行/风险与优化器只有契约/占位 | 误将接口当业务能力 | 任务和文档标状态；阶段依赖门禁，不接入真实交易 |
| 行情断档、时间边界或前视 | 回放结果失真 | 完整收盘 Bar、UTC、完整性阻断、确定性 replay、因果测试 |
| 网络暴露下无已证实权限防护 | 标注数据被未授权操作 | 明确部署为本地可信环境；远程多用户前增设授权/审计需求，否则禁用外部暴露 |
| OPEN_DECISIONS 被实现端暗中固化 | 金融行为被错误定型 | `SPEC_AMBIGUITY` / blocked enum 传播；决策只经规格/REQ/TASK 流程变更 |
| 五章 `REVIEW_CANDIDATE` 被当作已批准 | 参数、诊断与验收按未定语义落地，返工面扩大 | `spec_status` 随资源返回；TASK-095 门禁；候选期只允许研究/设计 |
| Bar 时间口径冲突（`occurred_at` 结束时刻 vs TASK-004 `open_time`） | 时间键匹配、Golden 与一致性测试静默偏移 | 保留 `source_bar_id`；冲突期内禁止按时间自动对齐，登记 OPEN_DECISION |
| 完成批次半更新（部分周期已处理、快照未提交） | 策略读到跨周期不一致状态 | 单批次单次快照提交；未提交只暴露 `PENDING` |
| 成本重复计入（费用/滑点/价差叠加） | 风险与净绩效偏乐观 | Fill 级台账、`FIXED_TICKS_V1` 只计一次、公式版本与审计字段 |
| 元数据时间区间重叠/缺口或 `ctVal` 币种误设 | 合约价值与风险量纲错误 | `InstrumentMetadataRef` 区间校验；缺 FX/元数据返回 blocked 不估算 |
| Funding 晚到账单被丢弃 | 账户现金流与余额对账不成立 | 结算事件唯一键 + 重建回放，晚到按账单重算并留审计 |

## 8. 验证与方案使用

本方案的文档校验不替代任何代码阶段验收。后端实现任务须按批次列出可运行 pytest 范围、API 集成契约、数据库迁移和回滚证据；当前 379 passed 是执行计划的历史实测快照（2026-11-21），不能代替后续精确状态验收。本方案编制本身不得修改业务代码或运行数据。
## 9. 增量任务追溯（TASK-015，2026-11-23）

任务定义及 SPEC→PLAN→TASK→TEST 关系以 `../../../.dsh/tasks/tasks.json` 为准；拆分规则见 `../../../.dsh/tasks/ATOMIC_TASK_RULES.md`。本次同步已批准 CR-001 的 PB 分期门禁，不新增业务语义；OD-08 继续阻断绩效验收，OD-09 阻断多低点自动入场。已核实 PATCH 必传令牌及 Golden 自动三分/hash 已实现，不重复开发；历史功能存在不代表整批出口完成。

## 10. 五章规格修订对齐（TASK-096，2026-11-23）

本次按 SPEC-03/04/05/06/14 修订候选增量更新本文，不新增业务语义、不实现代码、不改历史 TASK-009 验收结论：

- 数据契约：§3.1 增补 `BarEnvelope`、`CompletionBatch`、`SwingPointRecord`、`ZoneSnapshot`、`StructureSnapshot`、`CostEvent`、`InstrumentMetadataRef`；既有 `Bar`/`Annotation` 字段与 wire name 不变。
- 服务边界：§4.1 增补完成批次、结构、Zone、成本账本、元数据与诊断 Protocol，仍为设计提案。
- 行为约束：§5.8–5.11 与 §6 表格将三门禁、批次屏障、确认不回溯、Zone 终态、成本前置与诊断注册表落到责任分解。
- 门禁：五章为 `REVIEW_CANDIDATE`，TASK-095 通过前 TASK-029…032/034/035 只能研究/设计；OD-ZZ-01…05、OD-ZONE-01…06、OD-06、OD-08 及结构层 OPEN_DECISION 原样阻断。
- 追溯：任务合同、依赖与 TEST-ID 以 `../../../.dsh/tasks/tasks.json` 为准；接口字段以 [`../interface-contract.md`](../interface-contract.md) 为唯一 wire 来源。

本方案本身不构成任何阶段出口；实现任务的验收须按 tasks.json 的 test_plan 与证据执行。

## Zone 1H 审计差量（TASK-098，2026-11-24）

SPEC-V148-06 §6.2要求先用上一快照判断突破，再处理到期和新锚点。TASK-032须同时覆盖domain引擎与TimeframeEngine正常入口，避免调用方提前加入锚点改变本Bar突破阈值。配置模型和启动门禁同步补齐半宽上限、寿命及合法性校验，依文件互斥顺序接在TASK-035之后。每根有效Bar按当前ATR重算几何，完整记录无效输入、超限失效和原子版本结果。逐Bar的不可变快照需包含有效时间、旧新版本、状态、锚点、精确边界、ATR、来源Bar、配置版本与原因。

TASK-099独立负责图表历史载荷。以TASK-032快照或固定夹具为输入，将各版本有效区间分别绘制，创建时间与激活时间明确表达。保留现有camelCase接口兼容，先读现有调用者，再追加历史分段字段。禁止把最新upper/center/lower从created_at整段回画；as_of截断、终态、窗口裁剪均须定向测试。前端TASK-100以该载荷为唯一几何来源。

验收覆盖旧边界已突破但同Bar新锚点扩大边界、突破与到期同时发生、ATR下降、整体寿命独立到期、单锚点CREATED保留及重放版本不变。历史450项通过不证明新增验收。半宽生产值保持OD-ZONE-01待决，固定夹具显式参数仅用于测试，不能写成默认生产配置。


## 11. 剩余任务的后端增量技术说明（TASK-101，2026-11-24）

本节细化实施方法，不增加策略语义。状态与逐项优先级见
[tasks.json](../../../.dsh/tasks/tasks.json)，四波次见
[执行计划当前入口](../../../planning/EXECUTION_PLAN.md)。
当前保留 `ApiRouter`、`SacwStore`、`DataService`、`TimeframeEngine` 和现有 matcher/runner；
上文建议的 service/port 只在某个切片确有需要时局部增加，不以全量服务拆分为开工前置。

| 任务/切片 | 当前复用入口与已知行为 | 只增加或修正的部分 | 验证出口 |
| --- | --- | --- | --- |
| TASK-002/016/017 | `ApiRouter.dispatch/revise_annotation`、`SacwStore.revise_annotation`；API已必传expected_revision，Store当前仍允许None | 002核入口边界，016核envelope/分页兼容，017补严格整数和事务内原子冲突；不重做CRUD | 保留成功请求；缺失/bool/float/字符串/过期令牌拒绝；两个同revision请求只成功一个，失败无部分写入 |
| TASK-018 | `create_replay_run/append_program_event/list_program_events`与现有SQLite迁移 | 来源/版本持久化差量，保留run/event ID | 临时旧schema副本升级前后事件可读；新增来源可审计；不操作真实var库 |
| TASK-019/020 | 现有comparison端点、matcher与replay入口 | 019逐端点改读指定run事件，020补确定性/取消/恢复 | 不同run不串读，重复输入hash一致，取消不伪完成，重启恢复有依据 |
| TASK-021…024 | `load_cases`、`RegressionRunner._run_case/run`、现有case/assertion表 | 目录到59、负向真实求值、阻塞汇总、差异定位分别交付 | 注入禁止事件必须FAIL，无对应引擎BLOCKED；混合状态不得整体PASS；后续PB按所属阶段执行 |
| TASK-025…028 | 现有DRAFT创建/来源白名单、freeze/split/hash与审计 | 先查绕过路径；已存在的自动三分不重做；人工授权/双人复核单列证据 | 冻结事实不可写，hash可复现；无实际授权和人工样本不可宣布通过 |
| TASK-029…031 | BarEnvelope/bar_stream/aggregation、ATR/SMA/ZigZag、Protected/N | 只补未覆盖边界、稳定ID、批量增量等价和证据 | test_plan逐条对照候选/批准范围；未决时间口径和ATR不由实现端补默认值 |
| TASK-032 | 现有ZoneEngine、ZoneSnapshot、transition_reason | Z1旧边界突破优先/同Bar冲突/幂等；Z2显式几何上限/独立寿命/ATR；Z3诊断传播和消费契约 | 正常TimeframeEngine入口矩阵；精确等号/超限/无效ATR；不可变历史、终态不复活；生产参数待批准 |
| TASK-099 | `zone_overlay/zone_overlays`、`build_timeframe_section`、DataService两处snapshot传参已实现 | 只补as_of/窗口裁剪/终态/兼容字段证据 | 旧消费者仍读顶层segments；新消费者按versions生效时间；后续版本不回画历史 |
| TASK-033…040 | snapshot、costs.py、config models/validation、已有状态机 | 恢复/元数据拒绝/人工准入/统计分切片；不重写已实现成本与状态规则 | 逐项test_plan；P0-E/OD05不足则P1-A不准入；原始费用账本不等于净绩效 |
| TASK-041…057 | 已有lifecycle模型、TimeframeEngine/MarketContext与逐Fill成本 | 按Setup→Signal→Execution→Risk→Order/Position→报告逐能力新增application实现 | 每步使用已验收上游及固定输入；下游未实现时可验证输出契约，不冒充整链通过 |
| TASK-058…065 | 现有参数分类/fingerprint及SQLite模式 | 白名单、不可变Trial、Holdout、搜索/报告、审批发布分别增加 | 不修改FIXED/REQUIRED/METADATA；OD08未决不产已验收净绩效；发布须人工批准 |

### 11.1 接口与数据兼容

`interface-contract.md` 仍是唯一 wire 来源。每个切片先列实际受影响端点、字段、调用者和旧值，
不因设计草图换名已有DTO。新增字段先由后端输出显式来源/版本/有效性，再由前端逐入口消费。
缺少业务必需的版本/费率/参数必须明确拒绝；兼容不能靠虚构值或静默按零处理。
`occurred_at/confirmed_at` 的口径变化必须先裁决并对旧样本显式标版本，不能原地重写冻结真值。

SQLite仅按既有迁移模式增量升级，先在临时数据库验证旧数据、事务失败回滚和幂等重启。
保留全部annotation revision、Golden hash、program event和审计；代码回退不得删除新增事实。
任何需要破坏旧schema或更换存储引擎的方案须另登记任务，本批不包含此类迁移。

### 11.2 交付顺序与证据

每个TASK先运行自身test_plan最小基线，再补差量断言和实现；有API/存储变化必须做对应集成验证，
纯领域变化先做定向单测再覆盖受影响引擎链。具体命令/TEST-ID仍从台账取，不在本文另维护测试状态。
前后端联合切片按“固定夹具契约→后端真实HTTP输出→前端真实消费→浏览器”推进；
候选规格可做研究夹具开发，不能替代正式批准或阶段验收。

当前P0优先收口不会自动解除TASK-095/OD门禁。上轮470项测试属于历史证据，
本轮只校验计划/台账，不宣称这批残余断言已通过。全量catalog资源问题先复现并另登记性能TASK，
不能借Zone收口重写DataService缓存或删历史快照。
