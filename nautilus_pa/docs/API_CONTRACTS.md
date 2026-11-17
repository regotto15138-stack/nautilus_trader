# API_CONTRACTS — 接口契约

> 对外（HTTP）与对内（模块间）接口的稳定约定。改接口先改本文件，再改代码。

## 1. 通用约定

- 基础路径：`/api/v1`；JSON 请求/响应；时间统一 ISO-8601（UTC 或带偏移）。
- 价格/数量/金额以字符串输出（十进制精确），不使用 JSON 浮点。
- 错误响应：`{"error": {"code": "...", "message": "...", "details": {...}}}`；
  常用 code：`NOT_FOUND`、`VALIDATION_ERROR`、`CONFLICT`、`SPEC_AMBIGUITY`、
  `BLOCKED_BY_SPEC_AMBIGUITY`、`INTERNAL`。
- 列表接口支持 `limit`/`offset`，返回 `{items, total}`。
- 破坏性变更必须走 CR；兼容性新增直接加。

## 2. 市场与指标

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/meta` | 版本、配置指纹、能力声明 |
| GET | `/market/snapshot` | 当前市场快照 |
| GET | `/market/live` | 实时行情 |
| GET | `/market/freshness` | 数据新鲜度 |
| POST | `/market/sync` | 触发同步 |
| GET | `/market/bars` | K 线查询 |
| GET | `/market/datasets`、`/market/coverage` | 数据集与覆盖度 |
| GET | `/indicators/series` | 指标序列 |
| POST | `/zones/preview` | Zone 预览（不落库） |

## 3. 标注与比对

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET/POST | `/annotation-projects` | 标注项目 |
| GET | `/annotation-projects/{project_id}/annotations` | 项目下标注 |
| GET | `/annotation-projects/{project_id}/ground-truth-hash` | 冻结哈希 |
| GET | `/annotation-projects/{project_id}/comparisons/{swings,zones,n-structures,state-intervals}` | 差异比对 |
| GET | `/comparisons`、`/comparisons/{id}` | 比对运行 |
| GET/POST/PATCH/DELETE | `/annotations/{id}` | 标注增查改删 |
| POST | `/annotations/{id}/status`、`/annotations/{id}/copy` | 状态流转、复制 |
| GET | `/annotations/{id}/revisions` | 修订历史（只增） |
| GET | `/audit-logs` | 审计日志 |
| GET/POST | `/boundary-overrides`、POST `/{id}/review` | 人工边界干预与复核 |

## 4. 黄金数据集 / 快照 / 重放

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET/POST | `/golden-datasets`、`/{id}` | 黄金数据集 |
| POST | `/golden-datasets/{id}/validate`、`/split` | 校验、切分 |
| GET | `/market/datasets/{id}/splits` | 切分结果 |
| GET | `/snapshots`、`/snapshots/artifacts` | 快照与工件 |
| GET/POST | `/replay-runs`、`/{id}` | 重放 |
| GET | `/replay-runs/{id}/events`、`/snapshots` | 重放事件与快照 |
| POST | `/replay-runs/{id}/cancel` | 取消 |

## 5. 回归

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET/POST | `/regression-cases`、`/{id}/runs` | 用例与运行 |
| POST | `/regression-suites/v1-4-8/run` | 套件运行 |
| GET | `/regression-runs`、`/{id}`、`/{id}/assertions` | 运行与断言结果 |

## 6. 模块间接口

| 接口 | 约定 |
| --- | --- |
| `TimeframeEngine.advance(bar)` | 单根已收盘 Bar 推进一个周期，幂等 |
| `MarketContext` | 只读视图；不得由调用方回写 |
| `AnnotationStore` | 事务写入；修订与审计只增不改 |
| `Matching.compare(...)` | 纯函数式比对，返回差异集合，不落库 |
| `RegressionRunner.run(...)` | 输出断言结果，不修改用例定义 |

## 7. 变更规则

1. 新增接口：先加 `API_CONTRACTS.md` 行 → 实现 → 测试 → 前端适配。
2. 改字段：默认只增；删除/改名必须走 CR，并保持旧字段一个版本兼容。
3. 语义变更（同一路径含义变了）：必须 CR，并在 `CHANGELOG.md` 记录。
4. `SPEC_AMBIGUITY` 相关字段：不得在未解除歧义时返回确定值。
