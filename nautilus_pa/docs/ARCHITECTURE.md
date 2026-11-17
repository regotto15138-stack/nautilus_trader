# ARCHITECTURE — 架构说明

> 面向"改代码前先知道自己在动哪一层"。实现细节看代码，这里只写边界与约束。

## 1. 分层

| 层 | 包 | 职责 | 依赖方向 |
| --- | --- | --- | --- |
| 领域 | `src/pa_trend/domain/` | 指标、ZigZag、Swing、结构、状态机、生命周期 | 只能依赖标准库，**不导入 NautilusTrader** |
| 应用 | `src/pa_trend/application/` | 周期引擎、市场上下文、存储、匹配、回归、快照、数据服务 | 依赖领域 |
| 配置 | `src/pa_trend/config/` | 配置加载、指纹、门禁 | 依赖领域 |
| 适配 | `src/pa_trend/adapters/nautilus/` | 与上游 NautilusTrader 对接 | 可依赖上述所有层 |
| 表现 | `src/pa_trend/presentation/` | HTTP API、图表载荷 | 依赖应用 |
| 前端 | `web/` | Lightweight Charts 工作台 | 只通过 HTTP API |

依赖方向不可反转：领域层出现适配器/HTTP 依赖即为架构缺陷（P1）。

## 2. 数据流

    OKX K 线（Parquet catalog）
      → data_service / market_sync
      → timeframe_engine（七周期独立状态）
      → market_context（SMA22 / ATR14 / ZigZag / Swing / 保护点 / N 结构 / Zone / 状态机）
      → presentation.api → web 工作台
      → annotation_store（标注、比对、重放、回归）

## 3. 七周期独立状态

每个周期各自持有：周期边界、ATR14、SMA22、ZigZag(k=2.0)、SwingPoint、ProtectedLow/High、
PullbackOriginHigh、N 结构、Zone。**周期之间不得共享可变状态**；跨周期只通过显式的
`MarketContext` 读取，不得回写。

## 4. 执行链

    MarketContext → Setup4H → Setup1H → Signal15M → Execution3M → RiskManager

当前仅 `MarketContext` 有实现；Setup/Signal/Execution/Risk 固化数据契约，未实现逻辑。
任何"把后面几层先写出来"的做法必须由 REQ 驱动，不允许顺手补。

## 5. 因果性约束

- 只使用已收盘的 Bar；不得使用未来数据做判定。
- 周期切换时，低周期不得提前看到高周期未完成的 Bar。
- 重放（replay）与实时路径必须走同一套判定函数，否则视为架构缺陷。

## 6. 存储边界

- SACW 业务数据：SQLite（`var/sacw.sqlite3`，不入库）。
- 行情数据：Parquet `catalog/`（`!catalog/**/*.parquet` 例外放行）。
- 冻结 Ground Truth 以哈希锁定；写入只增不改。

## 7. 规格歧义的结构化处理

规格未定义的行为（见 `requirements/CHANGE_REQUESTS.md` §5）在代码中必须：
1. 保留接口（签名可被调用）；
2. 默认关闭决策路径（`*_enabled=False`）；
3. 状态字段标记 `SPEC_AMBIGUITY` 或 `RESEARCH_ONLY`；
4. 相关回归用例标 `BLOCKED_BY_SPEC_AMBIGUITY`。

## 8. 扩展点

| 想加什么 | 应该改哪里 | 不该改哪里 |
| --- | --- | --- |
| 新指标 | `domain/indicators/` + 配置 + 测试 | API 里现算 |
| 新结构类型 | `domain/structure/` + 匹配器 | 前端硬编码 |
| 新 API | `presentation/api.py` + `API_CONTRACTS.md` | 绕过应用层直连 SQLite |
| 新配置项 | `configs/` + 指纹/快照 | 代码里写死魔法数 |
