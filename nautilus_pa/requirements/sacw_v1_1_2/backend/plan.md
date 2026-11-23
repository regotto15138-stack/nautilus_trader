# SACW 后端技术设计方案

> TASK-009 / REQ-011。与前端通过 [`统一接口契约`](../interface-contract.md) 解耦而协同。本文列出目标模块和 Python 签名，不实现代码。策略语义唯一依据为 V1.4.8 结构化 spec；当前功能成熟度以源码、测试与执行计划为证据，不以规格架构图推定实现。

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

当前代码签名优先，方案 Protocol 是未来解耦边界；特别 `CalibrationService` 是未来设计接口，不代表现存后端类。所有端点 handler 只负责 wire -> domain request 与 DomainError -> ApiError 转换，不能把 SQL/算法堆进 handler。

## 5. API/application 责任分解

1. `ApiRouter.dispatch`：method/path/body/query → handler；限制异常映射稳定、统一 envelope/request_id。未找到匹配路由返回 404，输入错误按契约拒绝。
2. Annotation command：校验 entity payload、项目/数据集/spec版本、状态迁移与 revision；单事务追加 revision/audit，冻结/删除遵守不可变边界。
3. Replay command：输入引用经校验、生成可复现 input hash，持久化 run 状态；工作完成/异常/取消都以状态机写库，事件分页读取。初始单进程任务不可等同持久分布式 queue。
4. Comparison query/command：限定相同数据、周期、范围与类型；固定 matcher version，匹配输出只读存储且不可反写 annotation。
5. Regression runner：PB-01..51 每项须有 evaluator 或明确 blocked；正/负断言均需真实计算；一个 blocked case 不得被总结成全 suite PASS。当前若需修正需单独任务与验收，不在本技术设计任务直接变更。
6. Calibration：后续工作只开放 RESEARCH 参数白名单；实验固定 dataset/code/spec/config/split/matcher/hash，train/validation/holdout 隔离；要求 P0-E 与 OD-05 冻结及阶段门禁。FIXED/REQUIRED/METADATA 和状态机逻辑不得进入搜索。
7. Config registry：candidate -> OOS report -> human approval/reject -> explicit publish -> rollback；发布不可隐式替换运行配置，记录 actor/reason/hash。

## 6. 实施顺序与依赖

- **B00 接口与并发安全**：统一 API payload，强制 PATCH `expected_revision` 与 409；前端随后对接。独立于策略引擎，但先于并发编辑验收。
- **B01a replay/comparison 持久链**：确认 replay event 存储及比较消费来源、hash 确定性；依赖 store schema 与 API 契约。
- **B01b 回归器**：PB 断言 mapping、负向 evaluator、blocked classification、run 汇总正确；依赖 domain 能力和持久化。阻塞不得误算 PASS。
- **B02b 标注工具/边界**：依赖 B00、标注 schema 与 API；与 B02a 可按文件互斥平行。
- **B03a 数据冻结/审阅**：数据集、annotation、split hash、审批与审计；依赖 annotation store/API；OD-05 的样本/责任/裁决/统计定义必须经授权冻结。
- **P0-E/B03b**：完整 PB-01…51 自动化黄金样本、逐项 PASS、统计与报告；依赖 B01b、B03a、适用 P0-A…F。当前没有证据可宣称通过。
- **P1-A**：只有 P0-E 与 OD-05 证据均通过才可准入；不是当前立即实施项目。OD-04 仍限制相关状态迁移。
- **B02a / P0-F 成本元数据**：可与工具/回归工作并行但涉及独立风险精度、配置门禁；不得改变交易 API 语义。
- **B04→B05→B06→B07→B08→B02c→B09**：严格按执行计划的策略链依赖推进；Setup/Signal/Execution/Risk/Order/Portfolio 回放逐阶段实现验收，B02c 依赖 B06 与 B08，B09 依赖 P0–P2。
- **B10b→B10c→B10d**：配置参数白名单/指纹先于实验与搜索，后者依赖 B09 和 OOS 数据；发布依赖人工审批。不得绕开 OD/冻结门禁。

该顺序将 SACW 批次与 V1.4.8 P 阶段作双轴追踪，不把批次号映射为策略阶段的同义词。任务实际状态只由 tasks.json 确认。

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

## 8. 验证与方案使用

本方案的文档校验不替代任何代码阶段验收。后端实现任务须按批次列出可运行 pytest 范围、API 集成契约、数据库迁移和回滚证据；当前 379 passed 是执行计划的历史实测快照（2026-11-21），不能代替后续精确状态验收。本方案编制本身不得修改业务代码或运行数据。