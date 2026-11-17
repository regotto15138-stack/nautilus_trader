# MODULES — 模块索引

> 找文件用这张表，不要遍历整个 `src/`。

## domain

| 模块 | 职责 | 关键文件 |
| --- | --- | --- |
| models | 领域模型与值对象（价格/数量/时间） | `domain/models.py` |
| indicators | SMA22、ATR14 | `domain/indicators.py` |
| zigzag | ZigZag(k=2.0) 转折识别 | `domain/zigzag.py` |
| structure | SwingPoint、Zone、N 结构、保护点 | `domain/structure.py` |
| state | 宏观 / 4H / 1H 状态机、CanOpen / CanHold | `domain/state.py` |
| lifecycle | Setup/Signal/Execution/Risk 契约（仅接口） | `domain/lifecycle/` |

约束：不导入 NautilusTrader、不做 I/O、不用 float 表示价格。

## application

| 模块 | 职责 | 关键文件 |
| --- | --- | --- |
| timeframe_engine | 七周期独立状态推进 | `application/timeframe_engine.py` |
| market_context | 汇总各周期指标/结构/状态 | `application/market_context.py` |
| annotation_store | SACW SQLite 持久层（标注/项目/审计/回归） | `application/annotation_store.py` |
| matching | 程序结果与人工 Ground Truth 差异匹配 | `application/matching.py` |
| regression | PB-01..51 回归执行与断言 | `application/regression.py` |
| snapshot | 运行快照与工件 | `application/snapshot.py` |
| data_service / market_sync | 行情读取、同步、覆盖度 | `application/data_service.py`、`market_sync.py` |
| aggregation | 多周期聚合 | `application/aggregation.py` |
| catalog_audit / data_quality | 数据目录审计、质量检查 | `application/catalog_audit.py`、`data_quality.py` |
| demo_data | 演示数据生成 | `application/demo_data.py` |
| paths | 路径规范化与定位 | `application/paths.py` |

## config / adapters / presentation / web

| 模块 | 职责 | 关键文件 |
| --- | --- | --- |
| config | 配置加载、指纹、门禁、版本 | `src/pa_trend/config/` |
| adapters/nautilus | 上游对接 | `src/pa_trend/adapters/nautilus/` |
| api | HTTP 路由与序列化 | `presentation/api.py` |
| chart_data | 前端图表载荷 | `presentation/chart_data.py` |
| web 工作台 | 图表、标注、比对、回归界面 | `web/index.html`、`web/app.js` |

## scripts / configs

| 位置 | 内容 |
| --- | --- |
| `scripts/` | 启动、同步、校验等运维脚本 |
| `configs/strategy_v1_4_8.yaml` | 策略参数（含 Zone 参数） |
| `configs/market_okx_eth_swap.yaml` | 合约与 tick 信息 |
| `configs/risk.yaml`、`execution.yaml` | 风控与执行参数 |
| `configs/research.yaml` | 研究开关（RESEARCH_ONLY） |
| `configs/regression_cases.yaml` | PB 回归用例与期望 |

## tests

| 位置 | 内容 | 何时跑 |
| --- | --- | --- |
| `tests/unit/` | 领域与应用单元测试 | 每次改动 |
| `tests/integration/` | API / 存储 / 引擎链路 | 涉及 I/O 与链路 |
