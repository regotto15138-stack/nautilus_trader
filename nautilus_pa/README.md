# ETH 多周期趋势识别与 SACW 标注工作台（规格 V1.4.8 / SACW V1.1.2）

按 `ETH 永续合约价格行为趋势策略.md`（V1.4.8）与
`结构人工标注与参数自动校准工作台.md`（SACW V1.1.2）实现的多周期识别、
结构标注与 PB 回归基线，基于 NautilusTrader 2.0.0rc8。

**中文使用教程见 [USAGE.md](USAGE.md)**。

当前状态：

- **已实现**：P0-A 至 P0-D —— 七周期时间与 Bar 处理、SMA22/ATR14、ZigZag、
  SwingPoint、保护点、**Zone 引擎**、N 结构识别、宏观与 4H/1H 状态机、
  CanOpen/CanHold；SACW 的 SQLite 标注库、标注 API、ANCHOR_ONLY / HUMAN_BOUNDARY 后端几何、
  HUMAN_JUDGED Swing、冻结 Ground Truth 差异匹配、初始状态快照、PB-01..51
  回归工作台与前端工作台。
- **只定义接口**：Setup / Signal / 3M 执行 / 止损风控 / 参数校准引擎
  （`domain/lifecycle/`），业务判定等 P1 与人工黄金样本。

## 架构

七个周期共享同一套算法实现，各自持有完全独立的状态（规格第 2.1 节）：

| 周期 | 职责 | 状态机 |
| --- | --- | --- |
| 1MONTH | 宏观趋势方向 | UPTREND / WEAKENING / DOWNTREND / UNKNOWN |
| 1W | 中期趋势方向 | BULLISH / WEAKENING / BEARISH / TRANSITION / UNKNOWN |
| 1D | 短期趋势环境 | BULLISH / PULLBACK / BEARISH / TRANSITION / UNKNOWN |
| 4H | 回撤结构与支撑区域 | TREND_UP / TREND_DOWN / PULLBACK / RANGE / TRANSITION / UNKNOWN |
| 1H | 回撤结束与反转候选 | BULLISH / BEARISH / PULLBACK / RANGE / REVERSAL_CANDIDATE / TRANSITION / UNKNOWN |
| 15M | 核心 N 结构与入场信号 | —（仅结构与指标） |
| 3M | 入场执行确认 | —（仅结构与指标） |

执行链 `MarketContext → Setup4H → Setup1H → Signal15M → Execution3M → RiskManager`
中，本基线实现了第一环 `MarketContext`，其余环节只固化了数据契约。

每周期独立维护：ATR14、SMA22、ZigZag（k=2.0）、SwingPoint、ProtectedLow、
ProtectedHigh、PullbackOriginHigh、N 结构、Zone。

## 三个必须守住的边界

1. **ATR_MA22 不实现**：V1.4.8 第 4.1 节只定义 ATR14 与 SMA22。该指标既无配置项
   也无计算，前后端一律显示 `N/A / SPEC_AMBIGUITY`（SACW V1.1.2 第 17.1 节）。
   若配置里出现 `indicators.atr_ma_period`，加载时直接报错。
2. **N 结构失效判定只留接口**：失效公式 `Close < L2 - buffer × ATR` 已实现为
   `NStructureDetector.structural_break_price(atr)`，但**不决策**用哪个 ATR 时点，
   默认 `invalidation_enabled=False`，`invalidation_status = SPEC_AMBIGUITY`。
   4H/1H 结构为 `RESEARCH_ONLY`；PB-12/PB-13 标记 `BLOCKED_BY_SPEC_AMBIGUITY`。
3. **Zone 参数可配置**：`zone_min_half_width_ticks` 与 `zone_max_age_weeks` 进入
   配置与冻结快照，不写死在代码里，SACW 8.1 补齐白名单后可直接进入校准。

## 布局

```text
nautilus_pa/
├── configs/                       # 冻结配置 + PB 回归样本
│   ├── strategy_v1_4_8.yaml       # 周期角色、指标、ZigZag、保护点、N 结构、Zone
│   ├── market_okx_eth_swap.yaml    # 合约 + METADATA（tick_size 等）
│   ├── risk.yaml / execution.yaml / research.yaml
│   └── regression_cases.yaml       # PB-01..PB-51 结构化样本与负向断言
├── src/pa_trend/
│   ├── domain/                     # 纯 Python，不导入 NautilusTrader
│   │   ├── models/                 # 周期边界、Bar、SwingPoint
│   │   ├── indicators/             # SMA22、Wilder ATR14
│   │   ├── zigzag/                 # ATR 反转 ZigZag + 候选快照
│   │   ├── structure/             # 保护点、N 结构、Zone 引擎
│   │   ├── state/                  # 宏观 / 4H / 1H 状态机、CanOpen/CanHold
│   │   └── lifecycle/              # P1 数据契约（Setup/Signal/Fill/Stop）
│   ├── application/                # 引擎、上下文、数据服务、标注库、快照、匹配、回归
│   ├── config/                     # 加载、指纹、启动门禁
│   ├── adapters/nautilus/          # Bar 转换、采集器、策略外壳
│   └── presentation/               # 图表载荷 + HTTP API 路由
├── web/                            # Lightweight Charts 工作台（库内置，无需联网）
├── scripts/                        # 采集、校验、研究、服务、浏览器自检
├── tests/                          # 单元 + 集成（333 项）
└── var/                            # SACW SQLite（gitignore）
```

## 安装与验证

```bash
cd nautilus_pa
VENV=/home/regotto/Code/nautilus_trader/python/.venv/bin/python

PYTHONPATH=src $VENV -m pytest -q        # 333 passed
PYTHONPATH=src $VENV -m ruff check .     # All checks passed
```

领域层只需 Python 3.11+ 与 PyYAML；采集器、策略外壳与工作台需要 v2 运行时。

## 快速开始

```bash
# 1. 采集七个周期（默认写入 nautilus_pa/catalog）
PYTHONPATH=src $VENV scripts/run_collector.py --proxy-url http://172.21.192.1:7890

# 2. 校验（会话偏移默认读取配置 research.session_offset_hours = 8）
PYTHONPATH=src $VENV scripts/validate_data.py

# 3. 多周期识别
PYTHONPATH=src $VENV scripts/run_signal_research.py

# 4. SACW 工作台（标注 + PB 回归 + 数据集/快照）
PYTHONPATH=src $VENV scripts/serve_chart.py      # http://127.0.0.1:8787/
```

### 工作台三个页签

| 页签 | 内容 |
| --- | --- |
| 结构标注 | 七周期 K 线 + 成交量 + SMA22 + ATR14 副图；ZigZag 候选与反转阈值；Zone 边界；N 结构；保护点；Swing / N 结构 / Zone / 保护点 / 状态区间标注工具；Swing `HUMAN_JUDGED`；Zone `ANCHOR_ONLY` / `HUMAN_BOUNDARY`；人工标注图层；ATR 快照检查器；冻结 Ground Truth 后的 Swing/Zone/N 差异比较与程序回放 |
| PB 回归样本 | PB-01..51 列表与过滤、单例/全套运行、结构化断言与阻塞原因、run_id 与哈希绑定 |
| 数据集与快照 | 七周期覆盖与完整性、数据集/配置哈希、初始状态快照与 artifact、黄金样本冻结与 baseline replay 绑定、审计日志 |

### REST API（`/api/v1`）

统一信封 `{"data": ..., "meta": {"request_id": ...}, "error": null}`。

```text
GET  /meta                                  GET  /market/snapshot
GET  /market/live?since_close_ns=           GET  /market/bars?timeframe=&from=&to=&limit=&cursor=
GET  /market/datasets                       GET  /market/coverage
GET  /indicators/series?timeframe=&fields=  POST /zones/preview
GET/POST /annotation-projects               GET/POST /annotation-projects/{id}/annotations
GET/PATCH /annotations/{id}                 POST /annotations/{id}/status
POST /annotations/{id}/{submit|review|approve|freeze}
GET  /annotations/{id}/revisions            GET  /audit-logs
DELETE /annotations/{id}
POST /annotation-projects/{id}/comparisons/swings?timeframe=&golden_dataset_id=
POST /annotation-projects/{id}/comparisons/zones?timeframe=&golden_dataset_id=
POST /annotation-projects/{id}/comparisons/n-structures?timeframe=&golden_dataset_id=
POST /annotation-projects/{id}/comparisons/state-intervals?timeframe=&golden_dataset_id=
GET  /comparisons[/{id}]
POST /replay-runs                           GET  /replay-runs[/{id}][/events][/snapshots]
POST /replay-runs/{id}/cancel
GET/POST /boundary-overrides                POST /boundary-overrides/{id}/review
GET/POST /golden-datasets                    GET  /golden-datasets/{id}
POST /golden-datasets/{id}/validate          POST /golden-datasets/{id}/split
GET  /market/datasets/{id}/splits
GET  /snapshots                              GET/POST /snapshots/artifacts
GET  /regression-cases[/{id}]               POST /regression-cases/{id}/runs
POST /regression-suites/v1-4-8/run          GET  /regression-runs[/{id}][/assertions]
```

`GET /indicators/series` 对 `atr_ma22` 固定返回
`{"status": "N/A / SPEC_AMBIGUITY", "points": []}`。

比较接口只读取黄金样本冻结清单中的 `APPROVED` / `FROZEN` 人工标注，并在冻结时
绑定的 baseline replay、数据哈希与配置哈希上运行。未冻结时返回
`GOLDEN_DATASET_REQUIRED`；DRAFT 标注不会参与比较。匹配结果
`MATCHED / HUMAN_ONLY / PROGRAM_ONLY / AMBIGUOUS_MATCH` 仅用于人工复核。

### 实时刷新（`GET /market/live`）

采集器与工作台是两个独立进程，工作台只在启动时构建一次视图。前端每
`refreshIntervalSecs`（默认 5 秒）轮询本接口：

- 服务端先对比 Parquet 与内存视图的最新 K 线；发现新数据就按全部历史重新回放
  （引擎有状态，不能只喂增量），并返回 `changed` / `addedBars` /
  `changesByTimeframe`；
- `changed` 为真时，**只在有变化的周期上下发** `since_close_ns` 之后的 K 线与
  该周期最新叠加层（摆动点、N 结构、Zone、保护点），前端增量追加；
- 单个周期新增超过 `maxLiveBars`（500）根时返回 `reload: true`，前端改为整页
  重载，不在浏览器里拼接过长历史；
- 整页每周期只带最近 `MAX_SERIES_BARS`（1200）根，更早历史由前端把视野拖到最左侧时
  通过 `GET /market/bars?to=&limit=` 分页前插；
- 没有新数据时只返回状态，载荷可以忽略。

页面顶栏的实时徽章显示最近一次更新时刻与追加根数，点击可暂停/恢复轮询。

### 数据持久化

- 行情：`nautilus_pa/catalog`（`src/pa_trend/application/paths.py`）；相对路径按
  工程根目录解析，重启采集器只补新增 Bar，不重复写入。
- 标注与回归：`nautilus_pa/var/sacw.sqlite3`（可用 `--store` 覆盖），表结构见
  SACW 第 5.1 节；修订不可变、删除为软删除、冻结标注禁止改动。
- `catalog/`、`var/`、`.tools/` 均已加入 `.gitignore`。

### 采集语义（实时 + 补数）

- **只落盘已收盘 K 线**：未走完的蜡烛会反复推送，写入会让 Parquet 留下盘中
  限价/成交量。
- **按 K 线窗口落盘**：文件区间取 `[开盘, 收盘)`，不用适配器的 `ts_init`
  （WebSocket 路径下它是消息到达时间）。
- **重启补数**：启动时以未收盘缺口为基准续采——窗口从「最后一根已存 K 线的下一期」
  往前回退 `RESUME_LOOKBACK_PERIODS`（3 期），因此停机期间产生的 K 线在下一次
  启动时**全部**补齐，而不是只回退固定两期。
- **历史前向扩展**：启动时比较第一根已存 K 线与目标回补深度，缺多少向前补多少。
  因此调大回补天数后**无需删库**即可让已有目录获得更长历史。
- **历史缺口修复**：启动时扫描已存时间戳，逐段请求中间的缺口。续采只从最后一根
  往后补，早先运行遗留的中间缺口靠这一步修复。
- **回补深度**（`DEFAULT_BOOTSTRAP_DAYS`）：1M/1W/1D 六年（覆盖合约上线）：
  4H 三年、1H 一年、15M 90 天、3M 30 天。分钟级不取全量，因为 3M 六年约 108 万根、
  需要上万次分页请求。
- **收盘补拉**：每个周期在自己的收盘时刻后补拉一次历史 K 线，覆盖 WebSocket
  漏推。
- **断线重连**：只在收到显式 `DISCONNECTED` → `CONNECTED` 后重新回补
  （早期按子串判断会让重连永远不被识别）。
- **请求上界**：运行时要求 `start <= end <= now`，因此每个请求终点都会截断到
  当前时刻；单个周期回补失败不影响其余周期的订阅与回补。

### 浏览器验证环境（持久化）

```bash
# 仅首次
uv venv .tools/playwright --python 3.13
uv pip install --python .tools/playwright/bin/python playwright
.tools/playwright/bin/python -m playwright install chromium

# 之后每次直接用（会截三张图并打印断言数据）
.tools/playwright/bin/python scripts/check_chart.py
```

Chromium 位于 `~/.cache/ms-playwright`，Playwright 包位于 `.tools/playwright`，
两者都不在 `/tmp`。无数据时可用 `--demo` 直接查看界面。

## 会话边界（关键）

规格第 3.1 节要求内部时间使用 UTC。实测 OKX 的**全部七个周期**都在 UTC 16:00
开盘（即 UTC+8 零点）：

```text
1M  open=2021-11-30T16:00:00Z
1W  open=2023-11-19T16:00:00Z
1D  open=2025-11-15T16:00:00Z
4H / 1H / 15M / 3M 同为零点对齐
```

因此所有脚本都提供 `--session-offset-hours`：

- `0`：严格执行规格的 UTC 口径，OKX 数据会被全部拒绝。
- `8`：声明交易所 UTC+8 会话，数据被接受，界面显示 `会话 UTC+8`。

偏移只平移边界判断，不修改任何价格或时间戳；它同时参与月线窗口收盘推导。

## 未实现的部分

- **Setup4H / Setup1H 生命周期**（第 10 章）：仅 `domain/lifecycle` 数据契约。
- **15M Signal**（第 11 章）与 **3M 执行确认**（第 12 章）：仅数据契约。
- **订单/成交/持仓**（第 13 章）、**成本与 Funding**（第 14 章）、
  **止损与风险闭环**（第 15 至 17 章）：仅数据契约与门禁。
- **参数校准搜索**（SACW 第 8、25 章）：仅白名单分类与配置快照。

PB-01..51 中 6 例（PB-21、PB-22、PB-34、PB-35、PB-47、PB-48）当前可执行并通过；
45 例以 `BLOCKED_BY_UNIMPLEMENTED_STAGE`（43 例）或
`BLOCKED_BY_SPEC_AMBIGUITY`（PB-12、PB-13）出现在工作台中，原因逐条可见，
不会被静默跳过，也不伪造通过。

启动门禁已按第 18.3 节实现：结构研究阶段校验结构性参数与合约元数据；
回测/Paper/Live 阶段会拒绝缺失的 REQUIRED 项。策略外壳 `PaTrendStrategy`
只做识别、不下单。

## 许可

LGPL-3.0-only，与父仓库一致。
