# 使用教程（规格 V1.4.8 / SACW V1.1.2）

覆盖：环境准备 → 七周期数据采集 → 数据校验 → 多周期识别 → SACW 标注工作台
→ PB 回归 → 数据集与快照 → 常见问题 → 实现边界。

---

## 1. 环境准备

```bash
cd /home/regotto/Code/nautilus_trader/nautilus_pa
VENV=/home/regotto/Code/nautilus_trader/python/.venv/bin/python

$VENV -V                                                     # 期望 3.14.x
$VENV -c "import nautilus_trader; print(nautilus_trader.__version__)"   # >= 2.0.0rc8
```

`pa_trend` 是 `src` 布局，未安装时用 `PYTHONPATH=src` 运行全部脚本：

```bash
PYTHONPATH=src $VENV scripts/validate_data.py --help
```

### 测试与规范

```bash
PYTHONPATH=src $VENV -m pytest -q      # 期望 349 passed
PYTHONPATH=src $VENV -m ruff check .   # 期望 All checks passed
```

---

## 2. 目录与职责

```text
nautilus_pa/
├── ETH 永续合约价格行为趋势策略.md    规格 V1.4.8（唯一策略依据）
├── 结构人工标注与参数自动校准工作台.md  SACW V1.1.2（标注与验收依据）
├── configs/                          冻结配置 + PB 回归样本
├── src/pa_trend/
│   ├── domain/                       纯 Python，不导入 NautilusTrader
│   │   ├── models/                   七周期边界、Bar、SwingPoint
│   │   ├── indicators/               SMA22、Wilder ATR14
│   │   ├── zigzag/                   ATR 反转 ZigZag + 候选快照
│   │   ├── structure/                保护点、N 结构、Zone 引擎
│   │   ├── state/                    宏观与 4H/1H 状态机、CanOpen/CanHold
│   │   └── lifecycle/                P1 数据契约（Setup/Signal/Fill/Stop）
│   ├── application/
│   │   ├── timeframe_engine.py       单周期引擎（算法共享、状态独立）
│   │   ├── market_context.py         七周期聚合与市场快照
│   │   ├── data_service.py           数据载入、覆盖统计、Zone 后端几何
│   │   ├── annotation_store.py       SACW SQLite（标注/修订/审计/黄金样本）
│   │   ├── snapshot.py               初始状态快照与可信度判定
│   │   ├── matching.py               人工 vs 程序差异匹配
│   │   └── regression.py             PB-01..51 回归工作台
│   ├── config/                       配置加载 + 指纹 + 启动门禁
│   ├── adapters/nautilus/            Bar 转换、采集器、策略外壳
│   └── presentation/                  图表载荷 + HTTP API
├── web/                              前端（Lightweight Charts 已内置）
├── var/                              SACW SQLite（gitignore）
└── scripts/                          采集、校验、研究、服务、浏览器自检
```

七个周期：`1M / 1W / 1D / 4H / 1H / 15M / 3M`。

---

## 3. 数据采集

```bash
PYTHONPATH=src $VENV scripts/run_collector.py --proxy-url http://172.21.192.1:7890
```

数据默认写入 **`nautilus_pa/catalog`**。相对路径按工程根目录解析，与启动时所在的
工作目录无关；重启采集器只补新增 K 线，不重复写入。

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--catalog` | `nautilus_pa/catalog` | Parquet 输出目录 |
| `--proxy-url` | 无 | OKX 访问代理；直连通常不通 |
| `--configs` | `nautilus_pa/configs` | 配置目录 |
| `--session-offset-hours` | `8` | 交易所会话边界偏移；OKX 为 8 |
| `--node-name` | `PA-TREND-COLLECTOR` | 实盘节点名称 |
| `--trader-id` | `PA-TREND` | Trader 标识 |
| `--log-level` | `INFO` | Python 日志级别 |

采集器会一次订阅并回补**七个周期**。各周期默认回补区间不同（分钟级只回补较短区间），
定义在 `collector.DEFAULT_BOOTSTRAP_DAYS`：

| 周期 | 默认天数 | 约合根数 | 单次请求周期数 |
| --- | ---: | ---: | ---: |
| 1M | 2190（6 年） | 71 | 300 |
| 1W | 2190（6 年） | 312 | 300 |
| 1D | 2190（6 年） | 2189 | 300 |
| 4H | 1095（3 年） | 6570 | 300 |
| 1H | 365（1 年） | 8760 | 300 |
| 15M | 90 | 8640 | 100 |
| 3M | 30 | 14401 | 100 |

大周期补齐到合约上线（OKX ETH-USDT-SWAP 始于 2020-09）；分钟级刻意只保留近期区间，
因为 3M 全量约 108 万根、需要上万次分页请求，既拖慢首次启动也更容易触发限频。

实测七周期全量落盘约 **1.7 MB**、约 2 分钟。**扩大范围后无需删库**：启动时会自动比较
第一根已存 K 线与目标起点，缺多少向前补多少（见 3.1）。重复启动不会重复请求。

`Ctrl+C` 停止；已收盘数据由 10 秒定时器落盘。

### 3.1 实时与补数语义

采集器长期运行，与工作台（第 6 节）是两个独立进程：

| 场景 | 行为 |
| --- | --- |
| 首次运行（catalog 为空） | 按上表的天数回补历史，然后进入实时订阅 |
| 重启（catalog 已有数据） | 从「最后一根已存 K 线的下一期」往前回退 3 期续采，**停机期间产生的 K 线全部补齐** |
| 已有数据但历史不够深 | 比较第一根已存 K 线与目标起点，自动向前补齐到上表的回补深度（调大天数后重启即可生效，无需删库） |
| 已存历史中间的缺口 | 启动时扫描时间戳，逐段请求补齐（续采只往后补，靠这一步修复中间缺口） |
| 正常收盘 | 每个周期在自己的收盘时刻后补拉一次历史接口，覆盖 WebSocket 漏推 |
| 断线重连 | 收到 `DISCONNECTED` → `CONNECTED` 后对全部周期重新回补 |
| 未收盘蜡烛 | **不落盘**（WebSocket 会反复推送盘中版本，写入会污染 Parquet） |
| 落盘区间 | 取 K 线窗口 `[开盘, 收盘)`，不取适配器 `ts_init`（WebSocket 下是到达时间） |
| 请求上界 | 运行时要求 `start <= end <= now`，每个请求终点都截断到当前时刻 |

单个周期回补失败只记录 `Backfill failed ...`，不会中断其余周期的订阅与回补。

### 3.2 数据持久化位置

| 项目 | 路径 |
| --- | --- |
| 默认 catalog | `nautilus_pa/catalog` |
| 默认配置 | `nautilus_pa/configs` |
| 前端静态资源 | `nautilus_pa/web` |
| SACW 数据库 | `nautilus_pa/var/sacw.sqlite3` |
| 浏览器验证环境 | `nautilus_pa/.tools/playwright` |
| Chromium | `~/.cache/ms-playwright/chromium-1255` |

路径约定由 `src/pa_trend/application/paths.py` 统一定义。相对 `--catalog` 按
**工程根目录**解析，因此从任何工作目录启动都指向同一份数据。

`catalog/`、`var/`、`.tools/`、`chart-check*.png` 已写入 `nautilus_pa/.gitignore`。

---

## 4. 数据校验

```bash
PYTHONPATH=src $VENV scripts/validate_data.py
```

真实数据示例（七周期全部干净）：

```text
1-MONTH  bars=59   clean=True DUPLICATE=0 OUT_OF_ORDER=0 GAP=0 misaligned=0
1-WEEK   bars=156  clean=True DUPLICATE=0 OUT_OF_ORDER=0 GAP=0 misaligned=0
1-DAY    bars=364  clean=True DUPLICATE=0 OUT_OF_ORDER=0 GAP=0 misaligned=0
4-HOUR   bars=721  clean=True DUPLICATE=0 OUT_OF_ORDER=0 GAP=0 misaligned=0
1-HOUR   bars=723  clean=True DUPLICATE=0 OUT_OF_ORDER=0 GAP=0 misaligned=0
15-MIN   bars=683  clean=True DUPLICATE=0 OUT_OF_ORDER=0 GAP=0 misaligned=0
3-MIN    bars=1011 clean=True DUPLICATE=0 OUT_OF_ORDER=0 GAP=0 misaligned=0
```

K 线根数会随采集器运行增长，上面的数字只是某一时刻的快照；判断标准是
`clean=True` 且各项计数为 0。

退出码 `0` 才可继续。`misaligned` 非零通常意味着 `--session-offset-hours` 没设对。

---

## 5. 多周期识别

```bash
PYTHONPATH=src $VENV scripts/run_signal_research.py
```

输出每个周期的状态、摆动点、N 结构，以及宏观汇总与权限（示例为实测输出）：

```text
[ 1M] 状态=UNKNOWN              已处理=   59 未对齐=0 摆动点=  5 N结构= 0 结构就绪=True
  最近收盘: 2026-10-31T16:00:00+00:00
[ 1W] 状态=UNKNOWN              已处理=  156 未对齐=0 摆动点=  9 N结构= 0 结构就绪=True
  最近收盘: 2026-11-15T16:00:00+00:00
[ 1D] 状态=BEARISH              已处理=  364 未对齐=0 摆动点= 19 N结构= 4 结构就绪=True
  最近收盘: 2026-11-15T16:00:00+00:00
[ 4H] 状态=TREND_DOWN           已处理=  721 未对齐=0 摆动点= 54 N结构= 9 结构就绪=True
  最近收盘: 2026-11-16T08:00:00+00:00
[ 1H] 状态=BEARISH              已处理=  723 未对齐=0 摆动点= 40 N结构= 4 结构就绪=True
  最近收盘: 2026-11-16T09:00:00+00:00
[15M] 状态=None                 已处理=  683 未对齐=0 摆动点= 45 N结构= 3 结构就绪=True
  最近收盘: 2026-11-16T09:00:00+00:00
[ 3M] 状态=None                 已处理= 1011 未对齐=0 摆动点= 71 N结构= 6 结构就绪=True
  最近收盘: 2026-11-16T09:00:00+00:00

宏观：1M=UNKNOWN 1W=UNKNOWN 1D=BEARISH | 4H=TREND_DOWN 1H=BEARISH
CanOpen=False CanHold=False
```

未对齐 K 线数为 0 才算配置正确；它对应 `validate_bar_series` 的 `misaligned`。

### 判读要点

- **`1M` / `1W` 显示 UNKNOWN 是正常的**：状态机要求「HH+HL 且 Close>SMA22 且
  ProtectedLow 有效」或反向条件同时成立；当前月线 59 根、周线 156 根，摆动点
  只有 5 / 9 个，结构既非完整多头也非完整空头（第 8.2、8.3 节的「其余情况」→
  UNKNOWN）。
- **`15M` / `3M` 没有趋势状态**：按第 2.1 节它们只承担 N 结构与执行，状态显示 `—`。
- **`CanOpen` 只认一种组合**：`1M=UPTREND + 1W=BULLISH + 1D∈{BULLISH,PULLBACK}`。
- **`CanHold` 与 `CanOpen` 分离**：`CanHold = 有持仓 且 未触发强制退出`；
  宏观转向不会自动清仓（第 8.5 节）。
- **N 结构失效价不产出**：失效判定的 ATR 时点尚未裁定，结构列表显示
  `RESEARCH_ONLY` / `SPEC_AMBIGUITY`，不给出失效价（SACW 27.6）。

---

## 6. SACW 标注工作台

```bash
# 真实采集数据
PYTHONPATH=src $VENV scripts/serve_chart.py

# 合成数据（无需任何数据即可体验）
PYTHONPATH=src $VENV scripts/serve_chart.py --demo

# 独立数据库（默认 nautilus_pa/var/sacw.sqlite3）
PYTHONPATH=src $VENV scripts/serve_chart.py --store /tmp/sacw.sqlite3
```

打开 <http://127.0.0.1:8787/>。服务仅监听 `127.0.0.1`，标准库实现，无第三方依赖；
前端库已内置于 `web/vendor/`。

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--catalog` | `nautilus_pa/catalog` | Parquet 数据目录；相对路径按工程根目录解析 |
| `--demo` | 关 | 使用合成数据，不读 catalog |
| `--demo-bars` | 400 | 合成数据每周期根数 |
| `--configs` | `nautilus_pa/configs` | 配置目录 |
| `--store` | `nautilus_pa/var/sacw.sqlite3` | SACW 标注与回归数据库 |
| `--instrument` | `ETH-USDT-SWAP.OKX` | 合约标识 |
| `--host` | `127.0.0.1` | 监听地址（默认仅本机可访问） |
| `--port` | `8787` | 监听端口 |
| `--code-commit` | 无 | 写入回归记录的代码版本 |
| `--session-offset-hours` | 配置中的 `research.session_offset_hours`（8） | 会话偏移 |
| `--proxy-url` | 无 | 点「实时」徽章补数时传给采集器的 OKX 代理；不填则补数多半连不上 |
| `--sync-timeout-secs` | 300 | 单次按需补数的等待上限 |

#### 端口被占用

默认端口是 8787。如果该端口已有进程在监听（最常见：**上一次启动的工作台还在跑**），
工作台会退出并打印提示，而不是抛出 traceback：

```text
端口 8787 不可用（Address already in use）。
提示：可能已有工作台在运行（浏览器打开 http://127.0.0.1:8787/ ），或换一个端口：--port 8788
     查看占用进程：lsof -i :8787（macOS/Linux） 或 netstat -ano | findstr :8787（Windows）
```

处理方式二选一：

```bash
# 1) 已经在运行 —— 直接打开浏览器即可，无需再次启动
#      http://127.0.0.1:8787/

# 2) 想换一个实例 —— 指定其他端口
PYTHONPATH=src $VENV scripts/serve_chart.py --port 8788
```

退出码：`0` 正常停止，`2` 前置条件缺失（数据目录/前端文件），`3` 启动门禁或数据载入失败，
`4` 端口不可用。

### 6.0 实时刷新

工作台启动后**无需重启**就能跟上采集器。前端每 5 秒轮询
`GET /api/v1/market/live`：

1. 服务端对比 Parquet 与内存视图，发现新 K 线就按全部历史重新回放；
2. 只在有变化的周期上下发新增 K 线与该周期最新叠加层（摆动点、N 结构、Zone、
   保护点），前端增量追加；
3. 单个周期新增超过 500 根时前端整页重载。

顶栏实时徽章有三种状态：

| 徽章 | 含义 |
| --- | --- |
| 实时 · 已追平（绿） | 目录里的 K 线已跟上当前 UTC |
| 实时 · 数据落后 …（黄） | 落后当前 UTC，附周期名与欠根数；点击即可补齐 |
| 实时刷新失败 …（红） | 轮询本身失败 |

**点击徽章 = 补齐数据**（不是暂停轮询）。补齐走
`POST /api/v1/market/sync`：服务端先审计目录，确实落后才用子进程起一次
`run_collector.py --backfill-only`，等它落盘退出后再整页重载 K 线与全部指标。
「已追平」时不会启动子进程。`Shift+点击` 或右键仍是暂停/恢复轮询。

> 为什么要区分「有新数据」和「数据落后」：采集器停掉时 `/market/live` 的
> `changed` 会一直是假。只看 `changed` 就会把 17 小时前的数据当实时数据展示。
> `stale` 由服务端按当前 UTC 与目录里最后一根**已收盘** K 线比较得出，尚未
> 收盘的蜡烛不计入。

#### 启动时的数据新鲜度自检

`serve_chart.py` 启动时审计一次目录并打印落后情况（**只报告，不自动补数**）：

```
数据新鲜度: 以下周期落后于当前 UTC
  - 1H: 末根 2026-11-16T10:00:00+00:00 缺 18 根已收盘 K 线
  - 15M: 末根 2026-11-16T11:15:00+00:00 缺 71 根已收盘 K 线
  提示：打开页面后点击右上角「实时」按钮补齐，或运行 scripts/run_collector.py 常驻采集。
```

工作台不替用户访问交易所：补齐要么点按钮按需触发，要么另开常驻采集器。
补数需要网络，所以 `serve_chart.py` 要带 `--proxy-url` 才能点按钮补数：

```bash
PYTHONPATH=src $VENV scripts/serve_chart.py --proxy-url http://172.21.192.1:7890
```

随时可从命令行审计目录（退出码 1 表示存在缺口）：

```bash
PYTHONPATH=src $VENV scripts/gap_audit.py
PYTHONPATH=src $VENV scripts/gap_audit.py --json
```

#### 长周期视野与向左滚动加载

整页载荷对每个周期只带**最近 1200 根**（`MAX_SERIES_BARS`）。实测每周期 5000 根时
整页约 21 MB、1200 根时约 6 MB，首屏明显更快。
其余历史按需加载：把图表拖到最左侧时，前端自动调用
`GET /api/v1/market/bars?timeframe=4H&to=<最早一根>&limit=1000` 再往前取一页并前插，
视野保持不动；加载完更早的全部数据后才提示“已加载到最早一根 K 线”。

切到其他周期会重置该周期的加载状态。指标与叠加层始终来自服务端最新一版计算，
向前加载只补充 K 线与成交量。

先启动采集器、再启动工作台即可；两者顺序无关，工作台每次轮询都会读取磁盘上
的最新数据。

```bash
# 终端 1
PYTHONPATH=src $VENV scripts/run_collector.py --proxy-url http://172.21.192.1:7890
# 终端 2
PYTHONPATH=src $VENV scripts/serve_chart.py --proxy-url http://172.21.192.1:7890
curl -s "localhost:8787/api/v1/market/live" | python3 -m json.tool | head -20
```

只起工作台、按需补数（不常驻采集器）也可以：点顶栏「实时」徽章即补齐一次。

```bash
PYTHONPATH=src $VENV scripts/serve_chart.py --proxy-url http://172.21.192.1:7890
```

### 6.1 结构标注页签

| 区域 | 内容 |
| --- | --- |
| 顶栏 | 规格 / SACW 版本、合约、数据来源与会话偏移、数据集与配置哈希、`CanOpen`/`CanHold`、宏观汇总 |
| 周期条 | 七个周期按钮，按钮内直接显示该周期状态 |
| 主图 | 蜡烛、成交量、SMA22、ZigZag、已确认摆动点、ZigZag 候选、反转阈值、Zone 边界（上/中/下三条线）、N 结构、保护点价格线 |
| 图例 | 十字光标处显示 周期 / 时间 / OHLCV / 完成状态 / SMA22 + `as_of` / `ATR_MA22 = N/A / SPEC_AMBIGUITY` / ZigZag 方向 / 候选价 / 冻结 ATR / 反转阈值 |
| ATR 副图 | 仅 ATR14；不绘制 `ATR_MA22`（V1.4.8 未定义） |
| 右侧 | 七周期状态表、本周期指标、ATR 快照检查器、Zone 列表（含半宽决定性项）、N 结构列表、标注列表、审计入口 |

**读图约定**

- 已确认 Swing 用箭头表示，只有最近 8 个点带价格文本，其余价格通过十字光标与
  差异报告读取，避免主图被文字淹没。
- ZigZag **候选**使用方块标记（`UNCONFIRMED`），与已确认 Swing 形状不同。
- 未关闭 Zone 用实线边界、终态（`BROKEN` / `INVALIDATED`）用点线且更淡。
- 灰色点线是反转阈值价；红色/绿色/橙色价格线分别是 ProtectedHigh /
  ProtectedLow / PullbackOrigin。

### 6.2 三种标注工具

| 工具 | 操作 | 产物 |
| --- | --- | --- |
| Swing | 第一次点击选发生 Bar，第二次点击选确认 Bar；价格默认取该 Bar 的 High/Low，可在待提交面板改价（必须填改价原因） | `SWING_POINT`（区分 `occurred_at` / `confirmed_at`，默认 `confirmation_policy=HUMAN_JUDGED`；改价写 `manual_price_override=true` + `override_reason`） |
| N 结构 | 依次选 L1 → H1 → L2 → H2 四个已确认摆动点 | `N_STRUCTURE`（前端先校验顺序与 `L2>L1`、`H2>H1`；失效字段标记 `SPEC_AMBIGUITY`） |
| Zone | 选 ≥2 个**同向**摆动点，再选 `ANCHOR_ONLY` 或 `HUMAN_BOUNDARY` | `ZONE`（ANCHOR_ONLY 边界由后端计算；HUMAN_BOUNDARY 人工边界与程序边界分开保存） |
| 保护点 | 点击 Bar，选择 `INIT / UPDATE / INVALIDATE`，并确认来源 SwingPoint | `PROTECTED_POINT`（必须带 `source_swing_id`；15M 独立 ProtectedLow 被拒绝） |
| 状态区间 | 先选状态，再点击开始 Bar 与结束 Bar | `STATE_INTERVAL`（`valid_from` / `valid_to` / `known_at` / `reason_code`；图上以背景色带显示） |

右侧「锚点候选」面板列出本周期已确认摆动点，点击即选中（比在图上点更精确），
也可直接在图上点击。选中后底部显示待提交对象，点「**保存草稿（DRAFT）**」入库。

**保存与连续标注**：保存成功后当前工具保持不变，可直接开始下一个对象；标注面板
上方可取消「保存后继续标注」以在保存后回到选择模式。页面内「使用说明」列出了
全部工具的连续标注步骤。图层复选框只控制显示，不进入标注。

标注列表支持软删除（`DELETE /annotations/{id}`，FROZEN 不可删）和导出 JSON。
「人工标注」图层把已保存的 Swing / Zone / N 结构 / 保护点 / 状态区间叠加到图上，
与程序结构分开显示；状态区间额外绘制背景色带。

**列表与编辑**：标注列表上方可按类型 / ID / 价格 / 状态关键字搜索，并可按对象时间
区间过滤（Swing 用 `occurred_at`，区间/保护点用 `valid_from`）。每条标注可「编辑」
（PATCH + `expected_revision`，冲突时提示“标注已被他人修改，请刷新”）或「复制」为
新的 DRAFT；编辑支持撤销 / 重做（按钮或 `Ctrl+Z` / `Ctrl+Y`）。
保护点必须选择来源 SwingPoint；Swing 改价必须填写原因，列表会显示「人工改价」徽章。

**保存后一律是 `DRAFT`，不是 Ground Truth。** 前端不会在保存时调用策略引擎
“核对标注是否正确”；程序只会在黄金样本冻结之后，用 V1.4.8 引擎回放同一段数据，
再与冻结标注做差异匹配。

**Swing 的确认策略**：当前工作台只写 `HUMAN_JUDGED`，并保存
`human_judged_confirmed_at`、`annotated_at` 与 `confirmation_evidence`。
`ALGORITHM_DERIVED` 的 `confirmed_at` 必须由冻结时的 baseline replay 生成，
前端不可写入，API 会直接拒绝。

**ANCHOR_ONLY 的边界永远由后端计算**（SACW 21.2）：前端只提交锚点 ID，服务端用
与策略完全相同的 `compute_zone_geometry`、同一 ATR 快照与同一配置计算
`center / half_width / lower / upper`，并写入 `half_width_basis`、`tick_size`、
`tick_size_version`、`formula_version`、`config_hash`。前端传入的边界会被覆盖。

**HUMAN_BOUNDARY**：人工填写 `human_lower / human_upper / human_center`；后端同时
计算并保存 `program_lower / program_upper / program_center`。该模式只进入人工边界
研究集和仲裁视图，不并入 `ANCHOR_ONLY` 主准确率。

若确实需要覆盖 ANCHOR_ONLY 公式边界，必须走 `POST /boundary-overrides` 并经审核；
批准后 Zone 的 `annotation_mode` 自动变为 `ANCHOR_ONLY_WITH_OVERRIDE`，不再计入
`ANCHOR_ONLY` 主准确率。

### 6.3 标注状态与版本

状态机：

```text
DRAFT → SUBMITTED → REVIEWED → APPROVED → FROZEN
```

审核阶段可 `REJECTED`，研究歧义可 `AMBIGUOUS`，之后退回 `DRAFT`。创建与每次
修订都会写审计日志；修订历史不可变；`FROZEN` 标注既不能修改也不能删除。

**黄金样本冻结**：只接受 `APPROVED` / `FROZEN` 且来源为 `HUMAN_PRIMARY` /
`HUMAN_REVIEWED` 的标注。冻结时：

1. 生成 `data_hash` / `annotation_hash` / `time_split_hash` / `frozen_at`；
2. 创建并绑定 `baseline_replay_run_id`、`baseline_code_commit`、
   `baseline_config_hash`；
3. 把参与冻结的标注加入黄金样本成员清单，并将 `APPROVED` 同步转为 `FROZEN`。

冻结后刷新标注列表即可看到 `FROZEN` 状态；冻结版不可原地修改，修订会创建新版本。
数据集页签的「自动三分（60/20/20）」按时间顺序生成 CALIBRATION / VALIDATION /
HOLDOUT 三个切分，并把同一 `time_split_hash` 写回三条记录。
标注面板会显示项目级状态汇总（DRAFT / SUBMITTED / REVIEWED / APPROVED / FROZEN）；
没有 APPROVED/FROZEN 时「冻结黄金样本」按钮保持禁用，避免误点后返回 400。

### 6.4 差异比较

差异比较不是“程序自动核对标注对不对”，而是：

```text
人工标注 → DRAFT → 审核 → 批准 → 冻结 Ground Truth
        → V1.4.8 程序回放同一数据
        → 人工 Ground Truth vs 程序输出一对一匹配
        → 差异报告 + 人工复核
```

因此比较接口必须指定已冻结的黄金样本；未冻结时返回
`GOLDEN_DATASET_REQUIRED`，DRAFT 标注不会进入比较。前端「Ground Truth 差异比较」
按钮只在黄金样本冻结后启用。

```bash
PID=$(curl -s localhost:8787/api/v1/annotation-projects | python3 -c "import json,sys;print(json.load(sys.stdin)['data']['projects'][0]['project_id'])")
GOLD=$(curl -s localhost:8787/api/v1/golden-datasets | python3 -c "import json,sys;print(json.load(sys.stdin)['data']['goldenDatasets'][-1]['golden_dataset_id'])")
curl -s -X POST "localhost:8787/api/v1/annotation-projects/$PID/comparisons/swings?timeframe=4H&golden_dataset_id=$GOLD"
curl -s -X POST "localhost:8787/api/v1/annotation-projects/$PID/comparisons/zones?timeframe=4H&golden_dataset_id=$GOLD"
curl -s -X POST "localhost:8787/api/v1/annotation-projects/$PID/comparisons/n-structures?timeframe=4H&golden_dataset_id=$GOLD"
curl -s -X POST "localhost:8787/api/v1/annotation-projects/$PID/comparisons/state-intervals?timeframe=4H&golden_dataset_id=$GOLD"
```

N 结构比较先用冻结的人工 Swing 与程序 Swing 建立映射，再比较四锚点、确认时间
和结构状态。状态区间比较按状态与时间重叠匹配人工/程序区间；逐 Bar 混淆矩阵和
Macro-F1 尚未实现。每次比较写入 `comparison_runs` / `match_results`，可用
`GET /comparisons` 与 `GET /comparisons/{id}` 追溯。

**程序回放**：`POST /replay-runs` 会绑定冻结黄金样本的 baseline，回放七周期结构
事件并持久化到 `program_events`；支持 `GET /replay-runs[/{id}][/events][/snapshots]`
与 `POST /replay-runs/{id}/cancel`。前端「程序回放」区域可直接运行并查看事件数。

Swing 采用**全局最小代价一对一匹配**（匈牙利算法），输出
`MATCHED / HUMAN_ONLY / PROGRAM_ONLY / AMBIGUOUS_MATCH` 以及
`time_error_bars`、`price_error_atr` 与仅作诊断的 `confirmation_delay_bars`
（`w_c = 0.00`）。Zone 以锚点精度/召回为主，`HUMAN_BOUNDARY` 单独统计边界误差。

**匹配结果不是对错判定**：`HUMAN_ONLY` 可能是程序漏检，也可能是人工标错；
`PROGRAM_ONLY` 可能是程序误检，也可能是人工漏标；`AMBIGUOUS_MATCH` 必须人工复核。
比较报告会带 `goldenDatasetId`、`replayRunId`、`configHash`、`datasetHash` 与
`groundTruthCount`，便于追溯。

---

## 7. PB 回归工作台

打开「PB 回归样本」页签，或直接调用：

```bash
curl -s localhost:8787/api/v1/regression-cases | python3 -m json.tool | head -40
curl -s -X POST localhost:8787/api/v1/regression-suites/v1-4-8/run | python3 -m json.tool | head -30
```

- 51 个样本来自 V1.4.8 第 7.3 节表格，逐条结构化：章节、类别、预期、
  负向断言（`expected_absent_events` + `negative_assertion_reason`）。
- 当前可执行并通过的 6 例：PB-21、PB-22（ProtectedHigh 轨迹）、PB-34（启动门禁
  拒绝 `min_anchor_count < 2`）、PB-35（4H/1H 研究结构不得产生交易性失效）、
  PB-47（Zone 快照缺锚点 `confirmed_at` → `INSUFFICIENT_HISTORY`）、
  PB-48（`CanOpen=False` 且 `CanHold=True`）。
- 其余 45 例逐条显示阻塞原因：43 例 `BLOCKED_BY_UNIMPLEMENTED_STAGE`
  （依赖 Setup/Signal/执行/风险引擎），2 例 `BLOCKED_BY_SPEC_AMBIGUITY`
  （PB-12、PB-13）。**不伪造通过，也不静默跳过。**
- 每次运行生成 `regression_run_id`，与 `code_commit`、`config_hash`、
  `dataset_hash`、`expectation_revision` 绑定；断言逐条落库，可在
  `/api/v1/regression-runs/{run_id}/assertions` 复读。
- 前端样本详情新增「运行当前样本」，调用
  `POST /api/v1/regression-cases/{case_id}/runs`，无需重跑全套。

---

## 8. 数据集与快照

「数据集与快照」页签提供：

- **七周期覆盖表**：Bar 数、缺失、重复、乱序、完整性、起止时间（服务端用
  `validate_bar_series` 现算）。
- **数据集 / 配置哈希**：数据哈希由全部 Bar 内容计算，配置哈希由生效参数计算；
  两者都会写进标注、快照与回归记录。
- **初始状态快照**：`GET /api/v1/snapshots?timeframe=4H`，含 ATR/SMA/ZigZag/
  Swing/N 结构/Zone 与 `zone_parameters`（3 个入选参数 + 其余 Zone 参数），
  状态为 `READY / INSUFFICIENT_HISTORY / INVALID_ATR`。已实现的
  1M/1W/1D/4H/1H 状态机与 `CanOpen`/`CanHold` 写入 `state_machines`；
  持仓与订单仍为 `null`。
- **保存快照**：`POST /api/v1/snapshots/artifacts` 把快照哈希与元数据写入
  `snapshot_artifacts`，`GET /api/v1/snapshots/artifacts` 可列出。
- **黄金样本冻结**：`POST /api/v1/golden-datasets`（`CALIBRATION` /
  `VALIDATION` / `HOLDOUT`），返回 `annotation_hash` 与参与数量。

---

## 9. 常见问题

**Q: 采集报错连不上 OKX。**
A: 直连通常被墙，加 `--proxy-url`。自检：

```bash
curl -s --proxy http://172.21.192.1:7890 https://www.okx.com/api/v5/public/time
```

**Q: 运行 `serve_chart.py` 报 `OSError: [Errno 98] Address already in use`（或 Windows 的
`WinError 10048`）。**
A: 8787 端口已被占用，通常是你之前启动的工作台还没关闭。先看浏览器打开
<http://127.0.0.1:8787/> 是否已经有界面——有的话直接用，不必再启动。要另起实例就换端口：

```bash
PYTHONPATH=src $VENV scripts/serve_chart.py --port 8788
```

当前版本的脚本会直接打印上述提示并以退出码 `4` 结束，不再抛 traceback。
查占用进程：`lsof -i :8787`（macOS/Linux）或 `netstat -ano | findstr :8787`（Windows）。

**Q: 校验显示全部 `misaligned`。**
A: 忘了 `--session-offset-hours 8`。OKX 的七个周期都在 UTC+8 零点开盘。

**Q: 图表里 `1M`、`1W` 没有状态（显示 UNKNOWN）。**
A: 见第 5 节判读要点，属于规格定义下的正常结果，不是 bug。

**Q: 主图上看不到 `ATR_MA22`。**
A: 正确行为。V1.4.8 第 4.1 节没有该指标，SACW V1.1.2 第 17.1 节要求显示
`N/A / SPEC_AMBIGUITY` 且不得自行计算；配置里出现 `atr_ma_period` 会直接报错。

**Q: N 结构列表没有失效价。**
A: 失效判定使用的 ATR 时点未定义，接口存在但默认不产出失效价（SACW 27.6）；
PB-12/PB-13 因此在回归中标记为阻塞。

**Q: 提交 Zone 报 `VALIDATION_ERROR`。**
A: 常见原因是锚点方向不一致（必须同为 SwingHigh 或同为 SwingLow）或少于 2 个锚点。

**Q: 想在不联网时看界面。**
A: `--demo`。合成数据为各周期**独立**生成的示意序列，不代表真实的多周期一致性。

**Q: 标注数据存在哪里？会进 git 吗？**
A: `nautilus_pa/var/sacw.sqlite3`，已在 `.gitignore` 中。可用 `--store` 切库。

---

## 10. 实现边界

**已实现**

- 七周期边界与 Bar 处理、SMA22、ATR14、ZigZag（含候选快照与反转阈值）、
  SwingPoint、ProtectedLow/High、PullbackOriginHigh、**Zone 引擎**
  （聚类/几何/状态机/年龄/版本）、N 结构识别；
- 1M/1W/1D 状态机、4H/1H 状态机、CanOpen/CanHold、启动门禁、采集器；
- SACW：SQLite 标注库（标注/修订/审计/人工边界覆盖/黄金样本）、HTTP API、
  ANCHOR_ONLY / HUMAN_BOUNDARY 后端几何、HUMAN_JUDGED Swing、冻结 Ground Truth
  差异匹配、初始状态快照、PB-01..51 回归工作台、前端工作台。

**只定义接口，未实现判定**

- Setup4H/Setup1H 生命周期（第 10 章）与 15M Signal（第 11 章）；
- 3M 执行确认与订单/成交/持仓（第 12、13 章）；
- 成本与 Funding（第 14 章）、止损与风险闭环（第 15 至 17 章）；
- 参数校准搜索（SACW 第 8、25 章）。

`PaTrendStrategy` 只做识别，不下单。

---

## 11. 可复现验证

```bash
# 单元 + 集成测试（349 项）
PYTHONPATH=src $VENV -m pytest -q

# 静态检查
PYTHONPATH=src $VENV -m ruff check .

# 真实链路
PYTHONPATH=src $VENV scripts/run_collector.py --proxy-url http://172.21.192.1:7890
PYTHONPATH=src $VENV scripts/validate_data.py
PYTHONPATH=src $VENV scripts/run_signal_research.py

# 工作台是前台阻塞进程：单独开一个终端窗口运行，Ctrl+C 结束。
# 它必须在浏览器自检之前启动，且不要在同一个端口重复启动。
PYTHONPATH=src $VENV scripts/serve_chart.py

# 浏览器端到端（Playwright 环境持久化在 .tools/），需工作台已在 8787 运行
.tools/playwright/bin/python scripts/check_chart.py
```

> 同一端口只能有一个实例。重复启动会以退出码 `4` 结束并提示换端口，见第 6 节。

测试覆盖：七周期边界（含日内固定时长）、ATR/SMA 精确值、ZigZag 反转规则、
N 结构判据与回撤分档、保护点建立/失效/不复活、各状态机优先级、`CanOpen`
允许表、`CanHold` 独立性、多周期状态隔离、图表载荷契约、Zone 几何（含半宽
决定性项与量化）、Zone 状态机与年龄、标注库状态机与冻结规则、快照可信度、
匈牙利匹配与负向断言、PB 回归、API 路由与错误信封、P1 数据契约。

浏览器自检会截图三个页签并打印断言数据（周期切换、十字光标、Swing/Zone 工具、
回归运行、快照生成），任一面板/控制台报错即返回非零。
