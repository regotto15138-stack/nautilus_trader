# DATA_MODEL — 数据模型

> 持久化契约。SQLite 结构以 `src/pa_trend/application/annotation_store.py` 为准，本文件写不变量。

## 1. 存储划分

| 存储 | 位置 | 内容 | 是否入库 |
| --- | --- | --- | --- |
| SACW SQLite | `var/sacw.sqlite3` | 标注、项目、比对、重放、回归、配置审批 | 否（gitignore） |
| 行情 Parquet | `catalog/` | OKX K 线数据集与切分 | 是（`!catalog/**/*.parquet`） |
| 快照工件 | `var/` 下工件目录 | 运行快照、断言输出 | 否 |

## 2. 表分组

**元数据与行情**

| 表 | 含义 |
| --- | --- |
| `schema_meta` | schema 版本 |
| `market_datasets` | 行情数据集登记 |
| `dataset_splits` | 训练/验证/测试切分 |

**标注**

| 表 | 含义 |
| --- | --- |
| `annotation_projects` | 标注项目 |
| `annotations` | 标注条目 |
| `annotation_revisions` | 修订历史（只增） |
| `annotation_audit_logs` | 审计日志（只增） |
| `manual_boundary_overrides` | 人工边界干预 |

**Ground Truth**

| 表 | 含义 |
| --- | --- |
| `golden_datasets` | 黄金数据集 |
| `golden_dataset_annotations` | 冻结标注快照 |
| `snapshot_artifacts` | 快照工件（含哈希） |

**运行与比对**

| 表 | 含义 |
| --- | --- |
| `replay_runs` | 重放运行 |
| `program_events` | 程序事件流 |
| `comparison_runs` | 比对运行 |
| `match_results` | 差异匹配结果 |

**回归**

| 表 | 含义 |
| --- | --- |
| `regression_cases` | PB 用例 |
| `regression_expectation_revisions` | 期望修订（只增） |
| `regression_runs` | 回归运行 |
| `regression_assertions` | 断言结果 |

**配置治理**

| 表 | 含义 |
| --- | --- |
| `cost_metadata_versions` | 成本元数据版本 |
| `config_versions` | 配置版本与指纹 |
| `config_approvals` | 配置审批记录 |

## 3. 不变量

1. **只增不改**：`annotation_revisions`、`annotation_audit_logs`、
   `regression_expectation_revisions`、`config_approvals` 只能插入，不得 UPDATE/DELETE。
2. **冻结哈希**：黄金数据集冻结后，`ground-truth-hash` 必须稳定；任何变更都要新版本。
3. **审计完备**：标注状态变更、边界复核、配置审批都必须留下审计行（谁、何时、为什么）。
4. **版本关联**：比对/回归结果必须带 `config_version` 与 `cost_metadata_version`，
   否则结果不可解释。
5. **精确数值**：价格、数量、金额、tick 数用整数或十进制字符串存储；不用浮点列。
6. **时间**：统一 UTC ISO-8601 字符串或纳秒整数，一个表内保持一致。

## 4. 迁移规则

- schema 变更必须升 `schema_meta` 版本，并提供向前迁移（旧库可打开）。
- 不允许在迁移里丢弃历史行；需要清理时另建表并保留旧表。
- 迁移必须有对应测试，覆盖"空库建表"和"旧库升级"两条路径。

## 5. 与领域模型的映射

| 领域概念 | 存储表现 |
| --- | --- |
| SwingPoint | 标注条目 + 锚点类型（`HUMAN_JUDGED` 可覆盖） |
| Zone | 边界（`ANCHOR_ONLY` / `HUMAN_BOUNDARY`）+ 半宽 ticks |
| N 结构 | 结构条目；失效时点为 `SPEC_AMBIGUITY`，不落确定值 |
| 状态区间 | `state-intervals` 比对对象 |
| PB 断言 | `regression_assertions` |
