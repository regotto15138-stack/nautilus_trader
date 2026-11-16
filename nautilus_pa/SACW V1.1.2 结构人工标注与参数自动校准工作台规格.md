# SACW V1.1.2 结构人工标注与参数自动校准工作台规格

**文档版本：** SACW V1.1.2  
**基线版本：** SACW V1.1.1（完整继承 V1.0 + V1.1 + V1.1.1 修订包）  
**策略基线：** ETH-USDT-SWAP 多周期趋势策略 V1.4.8  
**适用交易标的：** ETH-USDT-SWAP.OKX  
**策略框架：** NautilusTrader 2.0.0rc8  
**前端图表：** TradingView Lightweight Charts（优先方案）  
**文档用途：** 可交付 AI 编码代理的产品、架构、数据模型、API、算法与验收规格（含 V1.1.2 修订）  
**系统定位：** 独立研究工作台；不直接承担实盘下单，不擅自修改 V1.4.8 策略定义。

> **版本说明：** 本文件整合 SACW V1.1 原文、V1.1.1 与 V1.1.2 修订包。修订包覆盖的章节以修订后内容为准；未覆盖章节继续按 V1.1 / V1.1.1 执行。与 V1.4.8 策略规则冲突时，以 V1.4.8 为准并记录 `SPEC_AMBIGUITY`。

## V1.1.2 修订摘要

V1.1.2 只修复跨文档核对中发现的 3 项问题，不改变任何 V1.4.8 策略行为：

1. **删除凭空引用的 ATR_MA22。** V1.1.1 第 17.1 / 17.2 / 17.3 节引用「V1.4.8 2.3 节」并将 `ATR_MA22` 定义为 `RESEARCH_ONLY`，但 V1.4.8 第 2 章只有 2.1、2.2 两节，第 4.1 节仅定义 ATR14、SMA22、ZigZag，**全文不存在 ATR_MA22**。该引用违反 16.2 第 2 款与 27.5 「参数注册表单一来源」。本版改为 `SPEC_AMBIGUITY` 并暂停展示，新增验收项 UI-022。
2. **补齐两个漏列的 Zone RESEARCH 参数。** V1.4.8 第 19 章的 `Zone Min Half Width Ticks`（2）与 `Zone Max Age`（52 weeks）未进入 8.1 可搜索白名单，导致 Zone 半宽最小 tick 项与年龄失效阈值无法被校准。本版补入 `zone_min_half_width_ticks` 与 `zone_max_age_weeks`，并在 21.2、21.4、25.4 中引用。
3. **新增跨文档核对机制。** 13.1 编码前清单增加「逐项核对 SACW 引用的 V1.4.8 章节号、参数名、枚举值、分类」；27.5 明确白名单必须与 V1.4.8 第 19 章逐一比对，遗漏项须显式声明 `OUT_OF_SEARCH_SCOPE`，不得静默省略。

---

# 1. 项目目标与边界

## 1.1 项目目标

建设一套围绕 V1.4.8 的人工结构标注、程序识别对比、参数校准和配置治理系统。研究人员在 TradingView 风格的 K 线页面完成标注，系统保存不可变标注版本；NautilusTrader 结构引擎对同一数据区间运行回放；对比引擎将程序识别结果与人工 Ground Truth 匹配；参数校准引擎只对允许调整的 RESEARCH 参数执行实验，输出候选参数、样本外验证报告和配置版本。

必须形成以下闭环：

`行情数据 → 人工标注 → Ground Truth 冻结 → 程序回放 → 差异匹配 → 参数实验 → 样本外验证 → 人工批准 → 配置发布`

## 1.2 核心原则

1. **V1.4.8 是唯一策略语义基线。** 工作台不得自行重新定义 Swing、NStructure、Zone、ProtectedLow/High、Setup、Signal、CanOpen、CanHold、ATR 快照或时间边界。
2. **人工标签与程序输出隔离。** 人工标注不能由程序自动生成后直接转为真值；程序预测也不能覆盖人工标注。
3. **事件时间和确认时间分离。** SwingPoint、结构、状态和 Signal 必须保留 `occurred_at`、`confirmed_at` 或相应的状态生效时间。
4. **只使用完成 Bar。** 标注可以回看历史，但必须区分事后人工识别的结构位置与当时可知的确认时间；禁止把事后信息伪装成实时可知信息。
5. **优化器只调 RESEARCH。** FIXED、REQUIRED、METADATA 和状态机逻辑不可由普通参数搜索修改。
6. **候选参数不自动生效。** 必须通过独立样本验证、人工审批、配置版本化后，才可用于新的研究运行。
7. **所有实验可复现。** 数据集、人工标注版本、策略规则版本、代码 Commit、参数配置、初始快照和成本元数据均需记录 Hash/版本。
8. **买卖点展示与人工结构标签分离。** 图表上的程序入场、退出标记属于预测/执行事件；人工结构标签是 Ground Truth。不得混用同一图层或同一数据类型。

## 1.3 不在本项目范围内

- 不直接向 OKX 提交真实订单。
- 不替代 NautilusTrader 的行情、指标、结构和策略引擎。
- 不将 TradingView 图表组件当作行情数据源。
- 不自动改变策略规则、状态转移顺序或成交模型。
- 不以收益最大化作为结构识别参数校准的唯一目标。
- 不允许 AI 自由推断未定义的 V1.4.8 规则；遇到规格歧义必须输出 `SPEC_AMBIGUITY`，等待人工裁定。

---

# 2. 技术架构与工程边界

## 2.1 推荐技术栈

| 层 | 推荐技术 | 职责 |
|---|---|---|
| 前端 | React + TypeScript + Vite | 标注工作台 UI |
| 图表 | TradingView Lightweight Charts | K 线、成交量、标记、价格线、时间轴 |
| 前端状态 | Zustand 或 Redux Toolkit | 当前图表、工具、选中对象、筛选状态 |
| API | Python FastAPI | 标注、数据、回放、对比、实验 API |
| 结构引擎 | 独立 Python 包，复用/调用 Nautilus 结构模块 | 按 V1.4.8 运行结构识别 |
| 任务队列 | 初期可用进程任务管理；规模扩大后 Celery/RQ | 回放和参数搜索异步任务 |
| 主数据库 | PostgreSQL | 标注、标签版本、实验、配置、审核记录 |
| 历史行情/回放结果 | Parquet + DuckDB | 批量历史数据、实验结果分析 |
| 对象存储 | 本地文件系统起步，后续可兼容 S3 | 数据集、快照、报告、图表导出 |
| 版本控制 | Git + 数据 Hash + Config Hash | 代码和实验可追溯 |

前后端通过 REST API 交互；长时间运行的回放和参数实验通过任务 ID 查询状态。需要实时推送进度时可增加 WebSocket/SSE，但不能把 WebSocket 消息作为持久化事实来源。

## 2.2 TradingView 图表选型

默认采用 **TradingView Lightweight Charts**，原因是本项目是个人/内部研究工作台，需要自有行情、自定义标注交互和自定义 UI。

注意：

- Lightweight Charts 是绘图组件，不自带完整标注工作台、行情服务、指标计算和数据持久化；这些由本项目实现。
- 交互式结构绘图需自行实现 Chart Primitive / 自定义图层 / HTML overlay；不能假设内置 TradingView Drawing Tools 可直接使用。
- 静态程序标记可使用 series markers、price lines 等能力；人工可编辑对象需要单独维护 ID、坐标、命中测试、拖动和保存逻辑。
- 必须按官方要求展示 TradingView 署名和链接，并遵守当前版本许可证及 NOTICE 要求。
- TradingView Advanced Charts / Trading Platform 属于需申请访问及许可的产品，且其许可场景与个人内部研究并不等同。除非已取得适合本项目用途的书面许可，否则不得让 AI 编码代理从非官方来源复制或集成该库。

官方资料：
- Lightweight Charts 文档：https://tradingview.github.io/lightweight-charts/docs
- Lightweight Charts 与其他图表产品比较：https://tradingview.github.io/lightweight-charts/docs/product-comparison
- Advanced Charts 接入说明：https://www.tradingview.com/charting-library-docs/latest/quick-start/

## 2.3 模块划分

```text
sacw/
├── frontend/
│   ├── chart-workbench/
│   ├── annotation-tools/
│   ├── comparison-view/
│   ├── calibration-lab/
│   └── config-registry/
├── backend/
│   ├── api/
│   ├── auth/
│   ├── market_data/
│   ├── annotation/
│   ├── dataset/
│   ├── replay/
│   ├── comparison/
│   ├── calibration/
│   ├── config_registry/
│   └── reporting/
├── strategy_adapter/
│   └── v1_4_8/
├── schemas/
├── migrations/
├── tests/
└── docs/
```

模块职责：

- `market_data`：查询 K 线、成交量、Funding、合约元数据；不负责生成策略标签。
- `annotation`：人工标签 CRUD、版本、审核、锁定。
- `dataset`：标注集冻结、时间切分、数据 Hash、快照。
- `replay`：以指定代码版本和配置版本运行 V1.4.8 结构引擎。
- `comparison`：人工真值与程序输出的一对一匹配和误差计算。
- `calibration`：受约束参数搜索、敏感性分析、样本外验证。
- `config_registry`：候选配置、审批、发布、回滚。
- `strategy_adapter`：把工作台数据契约映射到 NautilusTrader 2.0.0rc8，不在此处复制另一套策略逻辑。

## 2.4 与 NautilusTrader 的关系

工作台调用结构引擎时必须使用同一套 V1.4.8 实现，不允许前端另写 ZigZag 或 NStructure 算法。

推荐把策略代码拆分为可独立调用的纯计算/事件模块：

- `BarNormalizer`
- `IndicatorEngine`
- `ZigZagEngine`
- `SwingStructureEngine`
- `ZoneEngine`
- `TrendStateEngine`
- `SetupEngine`
- `SignalEngine`
- `ExecutionSimulator`

工作台 P0 阶段主要调用前六项；Setup、Signal、Execution 的程序标记在相应模块实现后接入。所有模块必须能够输入固定 Bar 序列、配置快照和初始状态快照，输出确定性事件序列。

---

# 3. 前端信息架构与页面交互

## 3.1 页面结构

主导航（以第 28 章为准）：

1. 数据集
2. 结构标注
3. 程序识别
4. 差异对比
5. 回归样本
6. 快照查看
7. 参数实验室
8. 配置版本
9. 运行与审计

## 3.2 结构标注页面布局

建议桌面端三栏：

- 左侧：数据集、周期、时间范围、标注对象树、过滤器。
- 中间：主 K 线图及成交量，支持多图层。
- 右侧：选中对象属性、时间、价格、状态、证据、备注和审核信息。
- 底部：时间轴、事件列表、当前 Bar 信息、标注历史。

主图支持周期：
`3M / 15M / 1H / 4H / 1D / 1W / 1MONTH`

多周期联动：
- 默认一个主图。
- 可打开 2/4 个同步图表面板。
- 同步十字光标时间。
- 同步时间范围时按 UTC 时间映射，不把不同周期 Bar 的开盘时间误当成同一根 Bar。
- 选择 4H Zone 后可在 1H/15M 面板显示其投影边界，但投影对象必须保留原周期和来源 ID，不能将跨周期 Zone 合并。

## 3.3 K 线基础交互

必须支持：

- 鼠标滚轮缩放时间轴。
- 拖动平移。
- 十字光标和 OHLCV 提示。
- 跳转指定 UTC 时间。
- 输入起止时间区间。
- 周期切换。
- 显示/隐藏成交量。
- 显示/隐藏各标注图层。
- 撤销/重做。
- 键盘快捷键。
- 选中对象后删除、编辑、复制属性。
- 图表截图及标注快照导出。

禁止通过屏幕像素作为标注的唯一坐标。标注必须保存为 `bar_time + price` 或时间区间与价格区间；像素坐标只用于前端渲染。

## 3.4 标注工具栏

### A. Swing 工具

- SwingHigh
- SwingLow

操作：
1. 选择工具。
2. 点击对应 K 线。
3. 系统默认填入该 Bar 的 High（SwingHigh）或 Low（SwingLow）。
4. 右侧属性栏可编辑价格，但必须保留 `manual_price_override=true` 和修改原因。
5. 输入/选择 `occurred_at`。
6. 输入/选择 `confirmed_at`。
7. 指定方向、周期和证据备注。
8. 保存为人工标注。

SwingPoint 标注必须允许“发生时间”和“确认时间”分别指定。`confirmed_at < occurred_at` 必须拒绝保存。

### B. NStructure 工具

通过依次选择四个 SwingPoint 创建：

`L1 → H1 → L2 → H2`

保存：
- 四个 SwingPoint ID。
- 结构方向。
- 结构有效/无效判断。
- 判定时间。
- 失效时间（如有）。
- 失效原因。
- 人工备注。

界面即时显示规则检查：
- 顺序是否合法。
- `L2 > L1`。
- `H2 > H1`。
- 不要求 `L2 > H1`。
- 是否违反 V1.4.8 15M N 结构 L2 引用约束。

不满足定义时允许保存为 `REJECTED_ANNOTATION` 或草稿，但不能保存为有效 NStructure。

### C. Zone 工具

支持：
- 创建 SUPPORT / RESISTANCE。
- 选择至少两个不同 SwingPoint 作为锚点。
- 展示人工确认的 Upper / Lower / Center。
- 记录 CREATED / ACTIVE / TESTED / BROKEN / INVALIDATED 事件。
- 标记 Zone 状态变化原因和对应 Bar。
- 维护 Zone 版本和锚点增删历史。

人工绘制的边界与程序按 V1.4.8 计算的边界必须分别保存。不可用人工边界覆盖程序计算结果。

### D. 保护点工具

支持：
- ProtectedLow
- ProtectedHigh
- 初始化、更新、失效事件
- 来源 SwingPoint ID
- 保护点有效区间
- 失效确认 Bar 与原因

15M 不允许建立独立 ProtectedLow 标签作为策略保护点；15M 的 `PreviousProtectedLow` 必须引用当时有效 NStructure.L2。若用户试图在 15M 创建独立 ProtectedLow，界面应提示该标注与 V1.4.8 规则不一致，可保存为研究备注但不得进入策略 Ground Truth。

### E. 状态区间工具

支持对每个周期标注状态区间：

- 1MONTH：UPTREND / WEAKENING / DOWNTREND / UNKNOWN
- 1W：BULLISH / WEAKENING / BEARISH / TRANSITION / UNKNOWN
- 1D：BULLISH / PULLBACK / BEARISH / TRANSITION / UNKNOWN
- 4H：TREND_UP / TREND_DOWN / PULLBACK / RANGE / TRANSITION / UNKNOWN
- 1H：BULLISH / BEARISH / PULLBACK / RANGE / REVERSAL_CANDIDATE / TRANSITION / UNKNOWN

区间保存 `valid_from`、`valid_to`、`known_at`、`reason_code`。`known_at` 表示该状态在当时可被确认的时间。区间可在图上以背景色带显示。

### F. Setup / Signal / 买卖点工具

人工标签可包含：
- Setup4H / Setup1H 创建、失效、过期。
- BREAKOUT_CONTINUATION / PULLBACK_CONTINUATION Signal。
- 3M 执行确认。
- 入场 Fill。
- 止损、移动止损更新。
- 风险减仓。
- 强制退出、最终平仓。

必须区分：
- `MANUAL_GROUND_TRUTH`：人工确认事件。
- `PROGRAM_PREDICTION`：程序识别/策略输出。
- `ACTUAL_EXECUTION`：真实或回测模拟的订单/Fill/Position 事件。

买卖点展示规则：
- 买入标记来自 Signal、ExecutionDecision 或 Fill，必须显示具体类型和状态。
- 卖出标记来自 StopTriggered、RiskReduction、ForcedExit、ManualExit 或 PositionClosed 等事件。
- 不允许仅凭一根 K 线涨跌自动绘制“买点/卖点”并声称是 V1.4.8 信号。
- Signal 不是 Fill；图上必须使用不同形状/图层显示“信号产生”“执行确认”“实际成交”。
- 未成交 Signal 不能显示为实际买入点。
- 部分成交必须显示部分成交数量和剩余数量。
- 退出信号、止损触发价和实际退出成交价必须分开显示。

> **V1.1.1 说明：** 本小节买卖点展示规则由第 18 章整体替代；3.4F 中与第 18 章冲突的表述不再有效。

## 3.5 图层规范

至少提供以下可单独开关的图层：

1. K 线与成交量
2. 人工 SwingPoint
3. 程序 SwingPoint
4. 人工 NStructure 连线
5. 程序 NStructure 连线
6. 人工 Zone
7. 程序 Zone
8. ProtectedLow / ProtectedHigh
9. TrendState 背景
10. Setup 区间
11. Signal 标记
12. Execution 标记
13. Fill 标记
14. Stop / Trailing Stop
15. 风险事件
16. 匹配连线与差异标记

人工与程序图层默认使用不同颜色/线型；颜色应可配置，不能只依赖颜色区分，需同时使用线型、形状和图例。

## 3.6 标注编辑与审计

每次创建、修改、删除、审核、锁定均写入审计日志：
- 操作者。
- 时间。
- 原值。
- 新值。
- 修改原因。
- 标注版本。
- 数据集版本。

已进入冻结数据集的标注不能原地修改。修订时创建新版本，旧版本保持可查询。

---

# 4. 人工标注规范与 Ground Truth

## 4.1 标注单位

标注单位分为：

- 点事件：SwingPoint、Fill、SignalCreated、StopTriggered。
- 结构对象：NStructure、Zone、ProtectedPoint。
- 状态区间：TrendState、SetupState。
- 过程对象：PullbackSequence、SignalLifecycle、PositionLifecycle。

每个对象必须绑定：
- instrument_id
- timeframe
- dataset_id
- strategy_spec_version（固定 V1.4.8）
- annotation_rule_version
- label_source
- created_by
- created_at
- revision
- status

## 4.2 标签来源枚举

`label_source`：
- `HUMAN_PRIMARY`
- `HUMAN_REVIEWED`
- `PROGRAM_PREDICTION`
- `IMPORTED`
- `AI_SUGGESTED`

只有 `HUMAN_PRIMARY` 和 `HUMAN_REVIEWED` 可进入正式 Ground Truth。AI 建议标签必须由人工确认后才能升级。

## 4.3 标注状态

- DRAFT：草稿。
- SUBMITTED：已提交审核。
- REVIEWED：已审核。
- APPROVED：已批准。
- FROZEN：已冻结，不能原地修改。
- SUPERSEDED：被新版本替代。
- REJECTED：审核拒绝。

P0-E 的黄金样本只能由 APPROVED/FROZEN 标注构成。

## 4.4 V1.4.8 标注对象

### SwingPoint

```json
{
  "annotation_id": "ann_x",
  "entity_type": "SWING_POINT",
  "instrument_id": "ETH-USDT-SWAP.OKX",
  "timeframe": "15M",
  "direction": "LOW",
  "price": "3100.0",
  "occurred_at": "2025-01-01T10:00:00Z",
  "confirmed_at": "2025-01-01T10:45:00Z",
  "source_bar_id": "bar_x",
  "label_source": "HUMAN_PRIMARY",
  "spec_version": "V1.4.8"
}
```

价格、数量和费率在持久化与比较计算中优先使用 Decimal/定点数，不应依赖二进制浮点数作为价格真值。

### NStructure

```json
{
  "annotation_id": "ann_n",
  "entity_type": "N_STRUCTURE",
  "instrument_id": "ETH-USDT-SWAP.OKX",
  "timeframe": "15M",
  "direction": "BULLISH",
  "l1_swing_id": "ann_l1",
  "h1_swing_id": "ann_h1",
  "l2_swing_id": "ann_l2",
  "h2_swing_id": "ann_h2",
  "valid_from": "2025-01-01T12:00:00Z",
  "confirmed_at": "2025-01-01T12:15:00Z",
  "invalidated_at": null,
  "validation_status": "VALID"
}
```

### Zone

```json
{
  "annotation_id": "ann_zone",
  "entity_type": "ZONE",
  "timeframe": "4H",
  "zone_type": "SUPPORT",
  "anchor_swing_ids": ["swing_a", "swing_b"],
  "center": "3000.0",
  "lower": "2980.0",
  "upper": "3020.0",
  "state": "ACTIVE",
  "state_events": [
    {"state": "CREATED", "at": "2025-01-01T00:00:00Z"},
    {"state": "ACTIVE", "at": "2025-01-02T00:00:00Z"}
  ],
  "zone_revision": 1
}
```

人工 Zone 边界属于人工参考真值；程序 Zone 边界单独保存，不可混写。

### StateInterval

```json
{
  "annotation_id": "ann_state",
  "entity_type": "STATE_INTERVAL",
  "timeframe": "1H",
  "state": "PULLBACK",
  "valid_from": "2025-01-01T08:00:00Z",
  "valid_to": "2025-01-01T16:00:00Z",
  "known_at": "2025-01-01T09:00:00Z",
  "reason_code": "PULLBACK_RULES_SATISFIED"
}
```

## 4.5 事后标注与实时可知性

人工在完整历史图表上标出 SwingLow 时，可能知道它后来成为低点，但实时系统在 `confirmed_at` 之前不知道它是 SwingLow。

因此必须同时保存：
- 事后结构发生时间 `occurred_at`
- 结构确认时间 `confirmed_at`
- 标注者做出判断的时间 `annotated_at`

回放评估必须以 `confirmed_at` 作为程序最早可识别时间。任何程序输出早于人工允许确认时间的情况，应作为时间因果性错误单独报告。

## 4.6 标注指南与仲裁

每类标签提供：
- 定义。
- 正例。
- 反例。
- 边界案例。
- 必填字段。
- 禁止操作。
- 对应 V1.4.8 章节。

模糊样本可以标记 `AMBIGUOUS`，不强制标成正例或负例。AMBIGUOUS 不计入主准确率，但必须单独统计数量和原因。存在多人标注时，使用双人独立标注 + 仲裁流程；不得让第二位标注者直接看到第一位标注者的标签后再“独立”标注。

---

# 5. 数据库模型

## 5.1 核心表

| 表 | 主要字段 | 说明 |
|---|---|---|
| `market_datasets` | id, instrument, range, timeframe_set, data_hash, source | 行情数据集 |
| `bars` / Parquet | instrument, timeframe, open_time, OHLCV | 历史 K 线 |
| `annotation_projects` | id, name, spec_version, status | 标注项目 |
| `annotations` | id, project_id, entity_type, timeframe, payload, source, status | 当前标注版本 |
| `annotation_revisions` | id, annotation_id, revision, payload, changed_by | 不可变修订历史 |
| `annotation_audit_logs` | actor, action, before, after, reason, at | 审计 |
| `golden_datasets` | id, project_id, frozen_at, data_hash, annotation_hash, baseline_replay_run_id, baseline_code_commit, baseline_config_hash | 冻结黄金样本 |
| `replay_runs` | id, code_commit, config_hash, dataset_hash, status | 程序回放 |
| `program_events` | run_id, event_id, event_type, timeframe, payload | 程序事件 |
| `comparison_runs` | id, golden_dataset_id, replay_run_id, matcher_version | 差异比较 |
| `match_results` | comparison_id, human_id, program_id, match_type, errors | 匹配结果 |
| `calibration_experiments` | id, search_space, objective, split, status | 参数实验 |
| `calibration_trials` | experiment_id, trial_id, params, metrics, status | 参数组合结果 |
| `config_versions` | id, parent_id, config_json, config_hash, status | 配置版本 |
| `config_approvals` | config_id, reviewer, decision, reason, at | 审批 |
| `snapshot_artifacts` | id, dataset_id, snapshot_hash, path, status | 初始状态快照 |
| `cost_metadata_versions` | id, fee_version, funding_hash, instrument_meta_hash | P0-F 元数据 |
| `manual_boundary_overrides` | override_id, zone_annotation_id, original_lower, original_upper, original_center, override_lower, override_upper, override_center, operator, reason, review_status, created_at, config_hash | V1.1.1 新增 |
| `regression_cases` | case_id, case_version, expected_events, expected_absent_events, expected_state_transitions, expected_absent_state_transitions, status | V1.1.1 负向断言 |
| `regression_runs` | run_id, code_commit, config_hash, dataset_hash, expectation_revision, status | V1.1.1 |

## 5.2 存储约束

- 所有时间使用 UTC `timestamptz`。
- 价格、数量、费率、成本使用 Decimal 或明确 scale 的定点数。
- 每个标注对象必须有稳定 UUID。
- 复合唯一性至少包括：项目、数据集、周期、对象 ID、修订号。
- 删除操作默认采用软删除；冻结标注不允许物理删除。
- 所有实验必须引用冻结的标注集 ID，不能引用“当前最新标注”这种可变指针。
- 所有程序事件保留 `run_id`、`code_commit`、`config_hash` 和来源 Bar ID。

## 5.3 数据集切分

必须按时间区间切分，不能随机打散相邻 Bar：

- Calibration：允许参数搜索。
- Validation：用于候选筛选，不参与该轮参数拟合。
- Holdout：最终独立验收，实验完成前不得反复查看并据此调参。

切分区间、数据 Hash 和标注 Hash 在实验开始前冻结。若修改标注或行情数据，生成新 Dataset Version，旧实验保持原始引用。

---

# 6. API 规格

API 前缀：`/api/v1`

统一响应：
```json
{
  "data": {},
  "meta": {"request_id": "uuid"},
  "error": null
}
```

错误响应必须包含稳定错误码、可读信息和字段路径。

## 6.1 市场数据 API

### 查询 K 线

`GET /market/bars`

参数：
- `instrument_id`
- `timeframe`
- `from`
- `to`
- `limit`
- `cursor`

返回按 `open_time` 升序的 Bar；明确 `is_closed`、`source` 和数据版本。

### 查询可用数据集

`GET /market/datasets`
`GET /market/datasets/{dataset_id}`

### 查询多周期数据覆盖

`GET /market/coverage?dataset_id=...`

返回每周期起止时间、Bar 数、缺失区间、重复 Bar、数据完整性状态。

## 6.2 标注 API

- `POST /annotation-projects`
- `GET /annotation-projects`
- `GET /annotation-projects/{project_id}`
- `POST /annotation-projects/{project_id}/annotations`
- `GET /annotation-projects/{project_id}/annotations`
- `GET /annotations/{annotation_id}`
- `PATCH /annotations/{annotation_id}`：必须传 `expected_revision`，采用乐观锁。
- `POST /annotations/{annotation_id}/submit`
- `POST /annotations/{annotation_id}/review`
- `POST /annotations/{annotation_id}/approve`
- `POST /annotations/{annotation_id}/freeze`
- `GET /annotations/{annotation_id}/revisions`

创建标注请求示例：
```json
{
  "entity_type": "SWING_POINT",
  "dataset_id": "dataset_uuid",
  "instrument_id": "ETH-USDT-SWAP.OKX",
  "timeframe": "15M",
  "payload": {
    "direction": "LOW",
    "price": "3100.0",
    "occurred_at": "2025-01-01T10:00:00Z",
    "confirmed_at": "2025-01-01T10:45:00Z",
    "source_bar_id": "bar_uuid"
  },
  "label_source": "HUMAN_PRIMARY",
  "spec_version": "V1.4.8"
}
```

服务端校验：
- 周期必须属于 V1.4.8 周期集合。
- 时间必须落在数据集覆盖范围。
- Swing 的价格和方向必须与来源 Bar 关系合理；若手动覆盖，必须记录覆盖原因。
- `confirmed_at >= occurred_at`。
- NStructure 引用的四个 Swing 必须存在、同周期、同方向规则正确且时间顺序合法。
- Zone 至少两个不同 SwingPoint 锚点。
- 15M ProtectedLow 不能作为独立策略保护点。
- `spec_version` 不等于 V1.4.8 时拒绝进入 V1.4.8 Ground Truth 项目。

## 6.3 黄金样本 API

- `POST /golden-datasets`：从 APPROVED 标注创建冻结版本。
- `GET /golden-datasets`
- `GET /golden-datasets/{id}`
- `POST /golden-datasets/{id}/validate`
- `POST /golden-datasets/{id}/split`

冻结时生成：
- `data_hash`
- `annotation_hash`
- `spec_version`
- `annotation_rule_version`
- `time_split_hash`
- `frozen_at`
- `baseline_replay_run_id`
- `baseline_code_commit`
- `baseline_config_hash`

冻结后不可修改；任何修改生成新版本。

## 6.4 程序回放 API

- `POST /replay-runs`
- `GET /replay-runs/{run_id}`
- `GET /replay-runs/{run_id}/events`
- `GET /replay-runs/{run_id}/snapshots`
- `POST /replay-runs/{run_id}/cancel`

请求：
```json
{
  "dataset_id": "dataset_uuid",
  "golden_dataset_id": "golden_uuid",
  "strategy_spec_version": "V1.4.8",
  "code_commit": "git_sha",
  "config_version_id": "config_uuid",
  "timeframes": ["3M", "15M", "1H", "4H", "1D", "1W", "1MONTH"],
  "initial_snapshot_id": "snapshot_uuid",
  "mode": "BATCH_DETERMINISTIC"
}
```

回放必须输出结构事件、状态事件、Setup/Signal 事件（如果对应模块启用）、事件来源 Bar、确认时间和参数快照。

## 6.5 差异比较 API

- `POST /comparisons`
- `GET /comparisons/{comparison_id}`
- `GET /comparisons/{comparison_id}/summary`
- `GET /comparisons/{comparison_id}/matches`
- `GET /comparisons/{comparison_id}/unmatched`
- `GET /comparisons/{comparison_id}/confusion-matrix`
- `GET /comparisons/{comparison_id}/export`

请求必须指定：
- golden dataset
- replay run
- matcher version
- 匹配容差配置
- 对象类型和周期过滤

## 6.6 参数实验 API

- `POST /calibration-experiments`
- `GET /calibration-experiments/{id}`
- `GET /calibration-experiments/{id}/trials`
- `POST /calibration-experiments/{id}/cancel`
- `POST /calibration-experiments/{id}/validate-out-of-sample`
- `GET /calibration-experiments/{id}/report`

创建实验时，后端必须拒绝 FIXED/REQUIRED/METADATA 字段进入搜索空间。

## 6.7 配置发布 API

- `POST /config-candidates`
- `GET /config-candidates/{id}`
- `POST /config-candidates/{id}/approve`
- `POST /config-candidates/{id}/reject`
- `POST /config-candidates/{id}/publish`
- `POST /config-versions/{id}/rollback`

发布 API 必须验证：
- 目标配置来自候选版本。
- 代码版本和 V1.4.8 规格版本兼容。
- 所有 REQUIRED 字段完整。
- 所有 FIXED 值未被覆盖。
- 样本内/验证/样本外门槛通过。
- 审批人和理由完整。
- 配置 Hash 已生成。

---

# 7. 人工与程序差异匹配算法

## 7.1 匹配基本原则

差异匹配采用**同类型、同周期、同数据集、同时间范围的一对一匹配**。禁止一个程序 Swing 同时匹配多个人工 Swing，也禁止多个程序结果重复匹配同一个人工标签。

所有匹配参数属于 `matcher_version`，与策略参数分开管理；不能通过扩大匹配容差掩盖程序误差。

## 7.2 SwingPoint 匹配

候选匹配必须满足：
- `instrument_id` 相同。
- `timeframe` 相同。
- `direction` 相同。
- 时间差不超过 `max_time_tolerance_bars`。
- 价格差不超过 `max_price_tolerance_atr × ATR_reference` 或明确的 tick 容差。

建议默认匹配容差先设为严格值，并由人工确认后固化；匹配容差不是 ZigZag 参数。

计算：
- `time_error_bars = abs(program.occurred_at - human.occurred_at) / timeframe_duration`
- `price_error_atr = abs(program.price - human.price) / human_or_frozen_reference_atr`
- `confirmation_delay_bars = (program.confirmed_at - human.confirmed_at) / timeframe_duration`

若一个人工 Swing 有多个程序候选，使用全局最小代价的一对一分配（匈牙利算法或等价最小费用二分图匹配），代价函数：
`cost = w_t * normalized_time_error + w_p * normalized_price_error + w_c * normalized_confirmation_error`

超出容差的候选不连边。权重和容差必须写入 matcher version。

匹配结果：
- MATCHED
- HUMAN_ONLY（程序漏检）
- PROGRAM_ONLY（程序误检）
- AMBIGUOUS_MATCH（存在多种近似匹配，需复核）

不能只按最近价格贪心匹配，因为连续 Swing 可能发生交叉误配。

## 7.3 NStructure 匹配

只有四个锚点 SwingPoint 均匹配且顺序一致，才可视为结构匹配候选。

比较：
- L1/H1/L2/H2 对应关系。
- 结构确认时间。
- 结构有效/失效状态。
- 失效时间。
- `L2 > L1`、`H2 > H1` 约束。
- 15M L2 是否正确引用当前 NStructure。

结构结果：
- EXACT_MATCH
- ANCHOR_MISMATCH
- CONFIRMATION_TIME_MISMATCH
- STATUS_MISMATCH
- HUMAN_ONLY
- PROGRAM_ONLY

## 7.4 Zone 匹配

候选 Zone 必须同周期、同极性（SUPPORT/RESISTANCE）且时间区间有重叠或锚点存在匹配关系。

指标：
- Anchor Precision / Recall。
- Center Error。
- Upper Error。
- Lower Error。
- Width Ratio。
- State Transition Timing Error。
- Zone Version Count Difference。

人工 Zone 是人工判定的聚类对象；若人工没有明确标注聚类边界，只标了锚点，则应以锚点匹配为主，不应把人工未提供的边界当成 Ground Truth。

## 7.5 状态区间匹配

以每根完成 Bar 为评估单位，比较人工状态和程序状态：
- Confusion Matrix。
- Precision / Recall / F1（macro 与 per-class）。
- 状态持续时间偏差。
- 状态转换时间误差。
- 转换漏检/误检。
- UNKNOWN 比例。

不能只按区间重叠率评价；短暂状态和转换边界必须单独统计。

## 7.6 Signal 与买卖点匹配

Signal 匹配至少要求：
- Signal 类型相同。
- 所属 NStructure ID 对应。
- 所属 Setup 链路一致。
- 方向一致。
- 创建时间在明确容差内。
- 触发参考价及触发 Swing 引用符合 V1.4.8。

Execution/Fill 另行比较：
- 执行确认时间。
- 订单提交时间。
- 首笔 Fill 时间。
- Fill 价格、数量。
- 退出事件和退出原因。

Signal 与 Fill 不得合并为同一“买点”；StopCandidate、已生效 Stop、StopTriggered、ExitFill 也不得合并为同一“卖点”。

---

# 8. 指标与参数校准策略

## 8.1 参数分类白名单

参数搜索服务启动时必须从 V1.4.8 参数注册表加载分类。仅 `RESEARCH` 可搜索。

### 允许作为候选搜索的 RESEARCH 参数（示例清单）

| 参数 | V1.4.8 初始值 | 说明 |
|---|---:|---|
| `zigzag_k` | 2.0 | ZigZag 反转阈值 |
| `zone_merge_distance_atr` | 0.5 | Zone 聚类距离 |
| `max_cluster_width_atr` | 1.0 | Zone 最大直径 |
| `zone_half_width_atr` | 0.1 | Zone 基础半宽 |
| `zone_min_half_width_ticks` | 2 | Zone 最小半宽 tick 数（V1.1.2 补入） |
| `zone_max_age_weeks` | 52 | Zone 锚点最大年龄，单位周（V1.1.2 补入） |
| `zone_test_tolerance_atr` | 0.1 | Zone 测试容差 |
| `zone_break_buffer_atr` | 0.1 | Zone 突破缓冲 |
| `setup_zone_tolerance_atr` | 0.5 | Setup 与 Zone 距离 |
| `min_observation_width_4h_atr` | 0.5 | 4H 观察区最小宽度 |
| `min_observation_width_1h_atr` | 0.5 | 1H 观察区最小宽度 |
| `min_observation_width_15m_atr` | 0.5 | 15M 观察区最小宽度 |
| `l2_tolerance_atr` | 0.1 | N 结构 L2 位置容差 |
| `pullback_low_zone_tolerance_atr` | 0.1 | PullbackLow 观察区容差 |
| `min_trigger_swing_atr` | 0.3 | TriggerSwing 最小反弹 |
| `stop_buffer_atr` | 0.1 | 结构止损缓冲 |
| `pullback_min_atr_4h` | 0.5 | 4H 回撤幅度 |
| `pullback_min_atr_1h` | 0.3 | 1H 回撤幅度 |
| `pullback_min_atr_1d` | 0.5 | 1D 回撤幅度 |
| `pullback_min_atr_15m` | 0.3 | 15M 回撤幅度 |
| `protected_break_buffer_atr` | 0.1 | 保护点失效缓冲 |
| `n_structure_break_buffer_atr` | 0.1 | 15M N 结构失效缓冲；V1.1.1 中受 27.6 阻塞 |
| `range_boundary_tolerance_atr` | 0.5 | 区间边界容差 |
| `setup4h_max_bars` | 8 | Setup4H 有效期 |
| `setup1h_max_bars` | 12 | Setup1H 有效期 |
| `signal15m_max_bars` | 4 | Signal 有效期 |
| `breakout_max_extension_atr` | 0.5 | 突破延伸上限 |
| `max_execution_deviation_atr` | 0.5 | 执行追价限制 |
| `max_execution_gap_atr` | 0.5 | 执行跳空限制 |
| `max_actual_fill_deviation_atr` | 0.75 | 实际成交偏差 |
| `fixed_stop_pct` | 5% | 固定止损比例 |
| `trailing_k_normal` | 3.0 | 正常移动止损 |
| `trailing_k_escalated` | 2.0 | 风险升级移动止损 |
| `risk_recovery_1h_bars` | 3 | 1H 风险恢复计数 |
| `risk_recovery_4h_bars` | 2 | 4H 风险恢复计数 |
| `hard_risk_budget_multiple` | 1.25 | 硬风险预算倍数 |

注：实际字段名以 V1.4.8 参数配置映射为准。上表不能覆盖 V1.4.8 原有默认值或定义。

> **V1.1.2 补入说明：** V1.1.1 的清单遗漏了 V1.4.8 第 19 章中的两个 Zone RESEARCH 参数：
> `Zone Min Half Width Ticks = 2` 与 `Zone Max Age = 52 weeks`。遗漏会使 21.2 的
> `min_half_width_ticks × tick_size` 项成为不可校准的固定值，且 Zone 年龄失效阈值无法
> 进入敏感性分析。本版补为 `zone_min_half_width_ticks` 与 `zone_max_age_weeks`，
> 初始值与分类严格取自 V1.4.8 第 19 章。
>
> 补入后本白名单共 **36 项**，与 V1.4.8 第 19 章的 RESEARCH 参数逐项对齐（见 27.5 的比对
> 与声明要求）。

### 禁止搜索

- `ATR Period = 14`（FIXED）
- `SMA Period = 22`（FIXED）
- `Zone Min Anchors = 2`（FIXED，禁止降至 1）
- 3M Fractal Left/Right = 2（FIXED）
- `CanOpen` / `CanHold` 规则
- SwingPoint 确认时序
- NStructure 锚点顺序和不等式
- Zone 状态转移规则
- Signal 状态终态规则
- ATR 快照取值时点
- Bar 时间边界、订单提交与成交时间约束
- Fill 偏差事件优先级
- 止损单生效和触发模型
- REQUIRED 资金、敞口、杠杆、费率、Funding、合约元数据
- METADATA 的交易所实际数据

后端必须硬编码分类校验，并在实验创建时拒绝越权字段。前端隐藏搜索控件不是安全措施。

## 8.2 搜索空间

每个参数定义：
- 类型：float / int / enum / bool。
- 合法范围。
- 步长或候选集合。
- 初始值。
- 单位。
- 参数分类。
- 约束关系。
- 适用周期。
- 影响的事件/判定项。

初期采用 Grid Search 或 Random Search。参数维度较多时先做单参数敏感性，再做小范围联合搜索。后续可接入 Bayesian Optimization，但必须保留每次 trial 的完整参数、结果和随机种子。

不允许搜索空间超出规格合法范围。对互相约束的参数需增加联合约束，例如 Zone 最大聚类宽度必须足以容纳至少两个锚点，但不能超过项目设定上限。

## 8.3 校准目标

结构校准优先使用多目标评价，不以交易收益作为结构标签匹配的唯一目标。

至少输出：
- Swing Precision / Recall / F1。
- Swing Price Error。
- Swing Confirmation Delay。
- NStructure Anchor Accuracy。
- Zone Anchor Precision / Recall。
- Zone Boundary Error。
- State Macro-F1。
- Per-State Recall。
- State Transition Accuracy。
- False Structure Rate。
- Unmatched Human Rate。
- Unmatched Program Rate。

可以生成 Pareto 前沿候选，不要只返回一个“最佳参数”。

## 8.4 分阶段校准

推荐顺序：

1. ZigZag：先校准 SwingPoint 数量、价格误差、确认延迟。
2. Swing / NStructure：在 Swing 基础稳定后检查结构锚点和结构失效。
3. Zone：校准聚类距离、最大直径、半宽、测试和突破缓冲。
4. 多周期状态：在底层结构稳定后校准状态相关 RESEARCH 参数。
5. Setup / Signal：仅在相应状态机和信号模块实现后校准。
6. Execution / Cost：独立验证执行过滤、滑点和费用，不得用成交率目标反向扭曲结构定义。

不能一次同时搜索所有参数，否则无法判断改善来自哪一项参数。

## 8.5 参数敏感性

对每个参数至少输出：
- 参数值。
- 各项识别指标。
- 相对基线变化。
- 不同时间区间表现。
- 不同市场阶段表现。
- 计算耗时。
- 样本数量。
- 置信区间或重采样稳定性结果。

如果一个参数只有在极窄取值附近表现良好，或相邻取值结果剧烈波动，应标记 `UNSTABLE_PARAMETER`，不推荐发布。

## 8.6 防止过拟合

按时间划分：
- Calibration：参数搜索。
- Validation：候选选择。
- Holdout：最终验收。

Holdout 结果一旦用于调参，就不再是独立 Holdout；必须建立新的未见时间段或重新定义测试协议。

推荐增加 Walk-Forward：
- 训练窗口按时间向前滚动。
- 每个窗口只使用过去数据校准。
- 后续窗口只做验证。
- 所有切分边界和参数结果固定记录。

人工标注规则在一轮实验期间必须冻结。若规则本身修改，升级 `annotation_rule_version` 并重新建立新实验。

## 8.7 自动校准的安全边界

自动化只允许：
- 生成候选参数组合。
- 执行历史回放。
- 计算识别指标。
- 排序候选。
- 输出推荐理由和风险。
- 生成候选配置文件。

自动化不允许：
- 直接覆盖当前正式配置。
- 修改 FIXED 参数。
- 改写状态机代码。
- 修改人工标签。
- 根据 Holdout 结果反复调参。
- 因追求高匹配率而扩大匹配容差。
- 通过删除难例来提高评分。

---

# 9. 配置版本发布与回滚

## 9.1 配置状态

- DRAFT
- EXPERIMENT
- CANDIDATE
- VALIDATION_PASSED
- APPROVED
- PUBLISHED
- REJECTED
- SUPERSEDED
- ROLLED_BACK

## 9.2 配置发布流程

1. 参数实验完成，生成 Trial Summary。
2. 选定一个或多个候选参数组合。
3. 自动生成配置差异（与当前基线逐项比较）。
4. 对候选配置运行 Validation。
5. 对最终候选运行 Holdout（只允许按预先定义的验收流程执行）。
6. 检查所有 FIXED/REQUIRED/METADATA。
7. 生成 `configuration_hash`。
8. 人工填写批准意见。
9. 发布为新的不可变 Config Version。
10. 后续回测明确引用该 Config Version。
11. 若发现问题，发布新版本回滚到历史配置内容，不删除历史记录。

## 9.3 发布验收门槛

候选配置至少满足：
- 结构识别指标达到项目设定门槛。
- 关键状态 Recall 不低于门槛。
- 转换时间误差满足 V1.4.8 工程验收标准。
- 样本外结果不出现明显退化。
- 参数对相邻取值不高度敏感。
- PB-01 至 PB-51 自动化黄金样本全部通过；被 `SPEC_AMBIGUITY` 阻塞的 PB-12/PB-13 按 27.6 处理。
- 无未来数据引用。
- 相同输入可确定性复现。
- FIXED 参数未被修改。
- 所有 REQUIRED 与 METADATA 版本有效。

V1.4.8 规定的初始状态验收指标（例如 Macro-F1、各状态 Recall、状态转换误差）应原样保留；工作台不能擅自降低门槛。具体门槛由策略规格版本管理，不由优化器学习。

## 9.4 配置差异报告

必须列出：
- 参数名。
- 旧值。
- 新值。
- 参数分类。
- 修改原因。
- Calibration 指标变化。
- Validation 指标变化。
- Holdout 指标变化。
- 适用数据范围。
- 关联实验 ID。
- 审批人。
- 发布时间。

---

# 10. P0-E / P0-F 与 V1.4.8 的落地流程

## 10.1 P0-E：人工黄金样本与快照

P0-E 的核心不是一开始就调参，而是建立可靠 Ground Truth。

执行顺序：

1. 选定行情数据集，检查 7 个周期的数据覆盖和完整性。
2. 固定 UTC 时间、数据 Hash、交易标的和 V1.4.8 规格版本。
3. 先标注 15M：SwingPoint、NStructure、Zone 及其事件。
4. 标注 4H/1H/1D/1W/1MONTH 的趋势状态、保护点和状态转换。
5. 标注 3M Signal 后执行时序案例。
6. 完成 PB-01 至 PB-51 的人工场景样本及预期结果；负向用例使用 `expected_absent_events` / `expected_absent_state_transitions` 表达。
7. 双人复核或由第二轮独立复核处理模糊案例。
8. 冻结 Ground Truth，并记录 `baseline_replay_run_id`。
9. 用 V1.4.8 程序回放同一数据区间。
10. 生成逐对象差异报告。
11. 先排除代码 Bug 和规格歧义，再判断是否需要调整 RESEARCH 参数。
12. 任何参数修改都要跑全量黄金样本回归。

## 10.2 P0-F：成本与元数据

P0-F 与人工结构标签分开验收。

记录：
- 合约乘数。
- Tick Size。
- Lot Size。
- 最小/最大数量。
- Maker/Taker 费率及其版本、生效时间。
- Funding 历史序列和 Hash。
- 滑点模型版本。
- 账户杠杆、保证金和风险配置。

成本和元数据必须有来源、版本、生效时间和完整性状态。缺少 REQUIRED 数据时，系统可以做结构识别研究，但不得把对应回测标记为有效净收益回测。

## 10.3 第一轮最小数据范围

优先做一个连续时间段、一个交易标的、七周期数据，先完成：
- 15M Swing + NStructure。
- 4H/1H Zone。
- 人工/程序叠加。
- 差异报告。
- 固定参数基线回放。

底层稳定后再扩展状态区间、Setup、Signal、Execution 和买卖点。

---

# 11. 前端组件与交互验收清单

## 11.1 必须实现

- [ ] TradingView Lightweight Charts K 线和成交量。
- [ ] 七周期切换。
- [ ] 多周期同步时间光标。
- [ ] 时间范围加载和历史分页。
- [ ] SwingHigh / SwingLow 点击标注。
- [ ] NStructure 四点连线工具。
- [ ] Zone 锚点与边界工具。
- [ ] ProtectedLow / ProtectedHigh 工具。
- [ ] TrendState 区间工具。
- [ ] Setup / Signal / Execution / Fill 事件标注。
- [ ] 程序结果叠加图层。
- [ ] 人工/程序图层独立开关。
- [ ] 对象属性面板。
- [ ] 标注列表、筛选、搜索。
- [ ] 撤销/重做。
- [ ] 保存、版本、审核和冻结。
- [ ] 图表截图与数据导出。
- [ ] 买卖点展示并区分 Signal、Execution、Fill。
- [ ] 差异高亮和匹配连线。
- [ ] 参数实验结果页面。
- [ ] 配置候选、审批、发布和回滚页面。
- [ ] 指标展示：SMA22、ATR14、ZigZag 候选、候选冻结 ATR、反转阈值。
- [ ] ATR 快照侧栏。
- [ ] NStructure 失效缓冲线与 `SPEC_AMBIGUITY` 标记。
- [ ] Zone `ANCHOR_ONLY` / `HUMAN_BOUNDARY` / `ANCHOR_ONLY_WITH_OVERRIDE` 模式。
- [ ] Setup4H / Setup1H / Intersection / 15M 定位区投影。
- [ ] PB-01 至 PB-51 回归样本页面、负向断言和预期修订审核。
- [ ] Snapshot Inspector。
- [ ] 参数实验室 Trial / Pareto / 敏感性视图及 Holdout 隔离。

## 11.2 前端非功能要求

- 大数据量使用可视区加载和分页，不一次性渲染全部历史 Bar。
- 图层更新不能每次都销毁重建整个 Chart。
- 标注拖动需有防抖保存和明确保存状态。
- 未保存修改关闭页面前提示。
- 多用户并发修改使用乐观锁。
- 所有时间显示可切换本地时区，但内部始终 UTC。
- 导出文件包含数据集 ID、标注版本、规格版本和 Hash。
- 图表显示程序事件时必须标识 `run_id` 和 `config_version`。

---

# 12. 测试与验收

## 12.1 单元测试

- 标注数据 Schema 校验。
- Swing 时间顺序。
- NStructure 不等式。
- Zone 最少两个不同锚点。
- 15M ProtectedLow 规则限制。
- StateInterval 时间边界。
- Decimal 精度。
- FIXED 参数保护。
- 配置 Hash 稳定性。
- 一对一匹配算法。
- 匹配容差边界。
- API 乐观锁。
- 冻结数据集不可变。
- `manual_boundary_override` 结构与审核状态。
- 负向断言解析与执行。

## 12.2 集成测试

- 前端创建 Swing → 后端保存 → 刷新后仍一致。
- 编辑 Swing → revision 增加 → audit log 生成。
- 冻结标注 → 创建回放 → 输出程序事件。
- 人工/程序比较 → 匹配结果可追溯。
- 参数实验 → 生成 trial → 输出候选配置。
- 发布配置 → 新回放引用新版本。
- 回滚配置 → 新运行可引用历史配置内容。
- 相同数据、代码、配置、快照重复回放，事件 Hash 一致。
- `ALGORITHM_DERIVED` 写入非基线 Replay Run → 返回 409。
- PB 负向断言失败 → 定位到 forbidden 事件窗口。

## 12.3 P0 验收

P0 阶段完成标准：
1. K 线数据准确且时间语义一致。
2. 人工标注对象能完整保存和版本化。
3. 人工与程序图层可独立显示。
4. 差异匹配具备一对一约束。
5. 可导出黄金样本和程序回放快照。
6. PB-01 至 PB-51 在 UI 可定位、可核对、可标记通过/失败；失败可定位到差异 Bar、事件和字段；负向断言可执行。
7. 任何人工修订都不会静默改变已冻结数据集。
8. 参数实验不会修改正式配置。
9. FIXED 参数不可进入搜索空间。
10. 所有运行可复现。
11. NStructure 失效 ATR 时点未定义时显示 `SPEC_AMBIGUITY`，不默认使用当前 ATR。
12. `ALGORITHM_DERIVED` 的 `confirmed_at` 由后端 `baseline_replay_run_id` 生成，前端不可写入。

## 12.4 P1 验收

- 网格/随机搜索可执行。
- 参数敏感性报告可生成。
- Calibration / Validation / Holdout 分离。
- 候选配置审批、发布、回滚完整。
- Holdout 数据在实验中保持隔离，并按 25.3 角色控制访问。
- 参数候选在样本外未达到门槛时明确标记失败，不得发布。

---

# 13. AI 编码代理执行说明

## 13.1 编码前必须完成

1. 阅读完整 V1.4.8 策略规格。
2. 建立 V1.4.8 术语、状态、参数注册表。
3. 建立前后端数据 Schema。
4. 先输出项目目录、模块边界和数据库 ERD。
5. 输出 API 契约和前端交互状态图。
6. 对不明确的策略定义列出 `SPEC_AMBIGUITY`，不要猜测。
7. 读取 TradingView Lightweight Charts 当前官方文档，使用当前版本 API，不使用旧版示例。
8. **跨文档核对（V1.1.2 新增，必须完成并留档）：** 逐项核对 SACW 所引用的 V1.4.8
   章节号、参数名、枚举值、分类与初始值，输出核对报告。核对规则：

   | 核对对象 | 判定 | 处理 |
   |---|---|---|
   | 章节号 | V1.4.8 中不存在 | 不得引用；标记 `SPEC_AMBIGUITY` 并删除该引用 |
   | 参数名 | V1.4.8 第 19 章中不存在 | 不得进入白名单；标记 `PARAMETER_REGISTRY_MISMATCH` |
   | 参数分类 | 与 V1.4.8 第 19 章不一致 | 以 V1.4.8 为准；标记 `PARAMETER_REGISTRY_MISMATCH` |
   | 参数初始值 | 与 V1.4.8 第 19 章不一致 | 以 V1.4.8 为准；标记 `PARAMETER_REGISTRY_MISMATCH` |
   | 枚举值 | V1.4.8 中不存在该枚举成员 | 不得使用；标记 `SPEC_AMBIGUITY` |

   核对报告须列出：核对项总数、缺失项、不一致项及各自处理结论。**未完成核对的阶段不得进入编码。**
   本机制的直接来源是 V1.1.1 曾引用不存在的「V1.4.8 2.3 节」与未定义的 `ATR_MA22`。

## 13.2 实施顺序

**阶段 A：工程骨架**
- React + TypeScript + Vite。
- FastAPI。
- PostgreSQL migration。
- 数据集/Bar 查询。
- Lightweight Charts 基础 K 线。

**阶段 B：人工标注**
- 标注工具栏。
- SwingPoint。
- NStructure。
- Zone。
- ProtectedPoint。
- StateInterval。
- 审计、版本、冻结。

**阶段 C：程序叠加与回放**
- 接入 V1.4.8 结构引擎。
- 程序事件图层。
- Replay Run。
- 快照和确定性测试。

**阶段 D：差异匹配**
- Swing 一对一匹配。
- NStructure 锚点匹配。
- Zone 匹配。
- StateInterval 逐 Bar 比较。
- 差异报告。

**阶段 E：参数实验**
- 参数白名单。
- Grid Search。
- Trial 存储。
- 指标报告。
- 时间切分和样本外验证。

**阶段 F：配置治理**
- 候选配置。
- 审批。
- 发布。
- 回滚。
- 审计。

不得跳过阶段 B 直接开发自动调参；没有冻结 Ground Truth，不允许将参数搜索结果标记为有效校准结果。

## 13.3 每阶段交付物

每个阶段必须交付：
- 可运行代码。
- 单元测试。
- 集成测试。
- API 文档。
- 数据库迁移。
- README 启动说明。
- 示例数据集。
- 截图或录屏。
- 未完成事项和已知限制。

AI 代理不得只输出代码片段或伪代码，必须将实现落到项目文件中，并运行测试。无法运行测试时必须明确报告，不得声称通过。

## 13.4 AI 代理禁止事项

- 禁止自行更改 V1.4.8 策略定义。
- 禁止使用未来数据或未完成 Bar。
- 禁止把 occurred_at 和 confirmed_at 合并。
- 禁止把 Signal 标记当成实际成交标记。
- 禁止让人工标签和程序预测共用可覆盖的表。
- 禁止让优化器修改 FIXED / REQUIRED / METADATA。
- 禁止将候选配置自动发布到正式环境。
- 禁止通过删除难例、改变匹配容差或重标样本来虚增匹配率。
- 禁止集成来源不明或许可不匹配的 TradingView 图表库。
- 禁止为 NStructure 失效 ATR 时点自行选择替代 ATR；必须标记 `SPEC_AMBIGUITY`。
- 禁止前端写入 `ALGORITHM_DERIVED` 的 `confirmed_at`。
- 禁止将 15M 层显示对象标记为独立 15M Zone。

---

# 14. 建议首个可交付版本（MVP）

首个版本不追求一次完成全部策略生命周期，先交付可验证的结构标注闭环。

MVP 范围：

1. ETH-USDT-SWAP.OKX 的历史 OHLCV 数据读取。
2. 15M、4H、1H 三个周期先行，架构上保留七周期。
3. TradingView Lightweight Charts K 线、成交量、缩放和时间同步。
4. 人工 SwingHigh / SwingLow 标注。
5. 人工 NStructure 四点标注。
6. 人工 Zone 锚点与状态标注。
7. 程序 Swing/NStructure/Zone 叠加。
8. 人工与程序差异报告。
9. 标注版本、数据集冻结、回放快照。
10. PB-01 至 PB-51 回归样本页面、样本导入和自动回归接口，含负向断言。

MVP 暂不启用自动参数发布；先验证人工标注一致性、程序差异可解释性和回放确定性。

---

# 15. 最终设计决策

1. 工作台采用独立前后端工程，不嵌入 NautilusTrader 交易进程。
2. 前端优先使用 TradingView Lightweight Charts；需要自行实现可编辑绘图工具和标注 UI。
3. 人工 Ground Truth、程序预测和实际执行数据三类数据严格分离。
4. 所有标注必须版本化、可审计、可冻结。
5. 程序回放必须调用 V1.4.8 同一套结构引擎。
6. 差异匹配采用同类型、同周期、一对一匹配；结构和状态分别使用适合自身的数据指标。
7. 参数搜索只允许 RESEARCH 参数，FIXED 规则永远不可由优化器调整。
8. 参数搜索结果先成为候选配置，经过时间外验证和人工审批后才能发布。
9. P0-E 以人工黄金样本、程序快照、差异报告和 PB-01 至 PB-51 回归为核心验收。
10. P0-F 负责成本、Funding 和合约元数据版本化，不与结构标签混为一谈。

**最终目标：** 研究人员只需在图表上按 V1.4.8 规则完成人工结构标注；系统即可自动回放程序、对齐结构、生成差异报告、评估允许调整的参数，并输出可审计、可回滚的候选配置。系统不替研究人员决定策略定义，也不允许优化器把历史样本过拟合成“看起来完全一致”的结果。

---

# 16. V1.1 前端功能补充规格（含 V1.1.1、V1.1.2 修订）

**本补充版本优先级：** 本章及以下新增章节对 V1.0 对应内容具有覆盖效力。  
**适用基线：** ETH-USDT-SWAP 多周期趋势策略 V1.4.8。  
**目的：** 补齐指标可视化、完整交易事件语义、确认时间治理、NStructure 失效缓冲、Zone 标注模式、Setup 观察区投影、PB 回归 UI、快照查看和参数实验 UI。  
**兼容原则：** 不改变 V1.4.8 的策略定义、状态机、指标公式、事件优先级、Bar 时间边界、订单/Fill 语义或参数分类。

## 16.1 V1.1 变更摘要

| 编号 | 变更 | 优先级 |
|---|---|---|
| V11-P0-01 | 增加 SMA22、ATR14、ZigZag 候选及阈值可视化（**V1.1.2：移除 ATR_MA22**，V1.4.8 未定义该指标） | P0 |
| V11-P0-02 | 统一交易事件标记为 Signal / Execution / Fill / Exit / Risk 五类 | P0 |
| V11-P0-03 | 明确 SwingPoint confirmation_policy 与确认时间裁决 | P0 |
| V11-P0-04 | NStructure 增加失效缓冲线及失效证据字段 | P0 |
| V11-P0-05 | Zone 增加 ANCHOR_ONLY / HUMAN_BOUNDARY 两种标注模式 | P0 |
| V11-P0-06 | 定义 Setup4H、Setup1H、交集区和 15M 投影展示 | P0 |
| V11-P0-07 | 增加 PB-01 至 PB-51 回归样本 UI 和审核流程 | P0 |
| V11-P1-01 | 明确交易事件图例、ATR 快照侧栏、快照查看页面 | P1 |
| V11-P1-02 | 明确投影 Zone 不参与 15M L2 判定 | P1 |
| V11-P1-03 | 明确参数实验室 UI、Pareto、敏感性和 Holdout 隔离 | P1 |
| V11-P1-04 | 明确 Lightweight Charts MVP 交互边界 | P1 |
| V11-P2-01a | Decimal API 序列化：价格、数量、费率统一十进制字符串 | P2 |
| V11-P2-01b | Matcher 默认配置和版本化 | P2 |
| V11-P2-01c | 参数注册表严格读取 V1.4.8 第 19 章，不维护独立别名表 | P2 |

## 16.2 规格冲突裁决

1. V1.4.8 策略规格定义策略行为；SACW 定义研究、标注、展示和审计行为。
2. V1.1 只补充前端展示和数据契约，不得重新解释 V1.4.8 的 Swing 确认算法、ATR 取值时点、NStructure 失效公式、Zone 公式、Setup 交集算法或 Signal 状态机。
3. 本文与 V1.0 原文冲突时，以 V1.1 本补充条款为准；与 V1.4.8 策略规则冲突时，以 V1.4.8 为准，并将冲突记录为 `SPEC_AMBIGUITY`，不得自行折中。
4. 所有前端展示值必须标明数据来源：`MANUAL_GROUND_TRUTH`、`PROGRAM_PREDICTION`、`ACTUAL_EXECUTION` 或 `DERIVED_DISPLAY`。
5. `DERIVED_DISPLAY` 只用于展示计算，不是独立策略事实，不得回写策略引擎。

---

# 17. 指标展示与诊断图层（P0）

## 17.1 指标支持矩阵

前端必须支持下列指标按周期独立开关。指标值由后端 V1.4.8 同源指标引擎计算并返回；前端不得用另一套实现产生用于比较的“程序指标”。

| 指标/对象 | 周期 | 展示位置 | 必须展示的信息 |
|---|---|---|---|
| SMA22 | 1MONTH / 1W / 1D / 4H / 1H / 15M | 主图叠加线 | 值、来源 Bar、是否完成 |
| ATR14 | V1.4.8 实际使用的各周期 | 独立副图 | 数值、单位、来源 Bar、完成状态 |
| ATR_MA22 | **V1.4.8 未定义** | 不提供图层 | V1.1.2：`SPEC_AMBIGUITY`。UI 显示 `N/A / SPEC_AMBIGUITY`，不得自行计算、不得作为指标图层、不得进入参数搜索空间 |
| ZigZag 当前方向 | 各启用结构周期 | 主图状态栏 | `SEEK_HIGH / SEEK_LOW / UNKNOWN` |
| ZigZag 候选极值 | 各启用结构周期 | 主图候选标记 | 候选价、候选 Bar、候选方向、候选状态 |
| 候选冻结 ATR | 与候选 Swing 对应 | 候选标记详情/侧栏 | `atr_snapshot`、来源 Bar 时间、ATR 周期 |
| ZigZag 反转阈值 | 与候选 Swing 对应 | 主图辅助线/带 | 阈值价格、计算方向、阈值来源 |
| 已确认 Swing | 各启用结构周期 | 主图标记 | occurred_at、confirmed_at、价格、方向 |
| ATR 冻结快照 | Signal / 首笔 Fill / Stop 更新 | 事件标记及侧栏 | 快照字段名、值、来源 Bar 时间 |

注意：
- SMA22、ATR14 的周期与计算口径以 V1.4.8 指标注册表为准。前端不得因为图表切换周期而错误复用另一周期指标。
> **V1.1.2 更正：`ATR_MA22` 在 V1.4.8 中不存在。**
>
> V1.1.1 曾声明「`ATR_MA22` 在 V1.4.8 2.3 中定义为 `RESEARCH_ONLY`」。跨文档核对确认：V1.4.8 第 2 章只有 **2.1 周期配置**、**2.2 策略执行链**，不存在 2.3；第 4.1 节「基础指标」只定义 **ATR（Wilder，周期 14）**、**SMA（周期 22）**、**ZigZag**，**全文没有 ATR_MA22**。该引用属于对 V1.4.8 的凭空解释，违反 16.2 第 2 款与 27.5。
>
> 因此在 V1.4.8 补定该指标之前：
>
> - UI **不得**展示 `ATR_MA22` 曲线、不得生成对应指标图层、不得出现在十字光标提示或指标面板中；
> - 所有引用处统一显示 `N/A / SPEC_AMBIGUITY`；
> - 后端**不得**自行计算该指标作为替代，也不得把它写入任何事件载荷、黄金样本快照或参数搜索空间；
> - 若未来 V1.4.8 在第 4.1 节补入 `ATR_MA22 = SMA(ATR14, 22)` 并明确分类，则须升版 SACW 并改为引用该章节，不得沿用 17.1 旧措辞。
- ZigZag 候选点是未确认状态，不得渲染为已确认 SwingPoint；候选点与确认 Swing 使用不同形状和图例。
- 候选 ATR 与反转阈值必须使用结构引擎在候选形成时冻结的值，不能用当前最新 ATR 替代。
- 指标计算缺失、无效或未就绪时显示 `N/A` 和原因码，不得画零值曲线误导研究人员。

## 17.2 指标面板布局

图表区域采用可折叠面板：
1. 主图：OHLC K 线、成交量（可独立副图或叠加缩放）、SMA22、Swing、ZigZag 候选、Zone、Setup、交易事件。
2. ATR 副图：仅 **ATR14**。`ATR_MA22` 在 V1.4.8 中未定义，V1.1.2 起**不绘制**；若请求该字段，返回 `N/A / SPEC_AMBIGUITY`（见 17.1 更正说明）。
3. 事件/快照面板：选中事件后展示该事件实际引用的指标快照，不用当前光标值冒充历史快照。

指标图层控制项必须包括：显示开关、周期选择、线型/透明度、数值格式、来源说明。颜色不能作为唯一识别方式，需同时使用线型、点型或文字标记。

## 17.3 十字光标指标提示

十字光标停留在某根 Bar 时，提示框至少展示：
- 周期、Bar open_time、Bar close_time、OHLCV。
- SMA22 数值及来源 Bar。
- ATR14 数值及来源 Bar。
- `ATR_MA22`：V1.4.8 未定义，一律显示 `N/A / SPEC_AMBIGUITY`，不显示数值。
- ZigZag 当前方向。
- 候选极值价、候选方向、候选冻结 ATR。
- 反转阈值价格。
- 数据是否为完成 Bar。

所有指标值均须显示字段来源和 `as_of_bar_time`。若当前 Bar 尚未完成，则明确标记 `FORMING_BAR`，该值不能用于 V1.4.8 完成 Bar 决策核对。

## 17.4 ATR 快照侧栏

增加独立 `ATR Snapshot Inspector`。选中 Signal、首笔 Fill、StopUpdate、Position 或相关事件时显示适用字段：

| 字段 | 语义 | 取值时点 |
|---|---|---|
| `signal_decision_atr_15m` | Signal 决策使用的冻结 ATR | Signal 创建/决策时，按 V1.4.8 定义 |
| `execution_reference_atr_15m` | 执行参考 ATR | Signal 创建时冻结值，按 V1.4.8 定义 |
| `initial_stop_atr_15m` | 初始结构止损 ATR | 首笔 Fill 时最近完成的 15M ATR |
| `stop_update_atr_15m` | 后续止损更新 ATR | 对应 StopUpdate 计算时最近完成的 15M ATR |

每个快照必须显示：
- 字段名和值；
- 来源周期；
- 来源 Bar ID、open_time、close_time；
- snapshot/event ID；
- 采集时点；
- `run_id`、`config_hash`；
- 是否缺失、无效或为 `INVALID_ATR`。

不同快照不可合并为一个通用 `ATR` 字段。未发生的事件不应伪造对应快照；字段为 null 时显示原因，不显示 0。

## 17.5 指标与候选数据 API

增加：
- `GET /indicators/series?dataset_id=&timeframe=&fields=&from=&to=`
- `GET /replay-runs/{run_id}/indicator-events`
- `GET /replay-runs/{run_id}/zigzag-candidates`
- `GET /replay-runs/{run_id}/atr-snapshots`

响应每个点至少包含：
`time`, `value`, `timeframe`, `field`, `source_bar_id`, `as_of_bar_time`, `is_closed`, `run_id`, `config_hash`。

ZigZag 候选对象至少包含：
`candidate_id`, `direction`, `candidate_price`, `candidate_bar_id`, `candidate_occurred_at`, `atr_snapshot`, `atr_snapshot_source_bar_id`, `reversal_threshold_price`, `status`, `confirmed_swing_id`。

---

# 18. 交易事件标记与买卖点语义（P0）

## 18.1 术语统一

界面和 API 统一使用“交易事件标记（Trading Event Marker）”，分为五类：
1. `SIGNAL`：策略信号生命周期事件。
2. `EXECUTION`：执行资格确认、订单提交及执行决策。
3. `FILL`：实际或回测模拟成交记录。
4. `EXIT`：止损、减仓、强制退出、紧急退出、最终平仓。
5. `RISK`：风险异常、风险升级/恢复、预算或成交偏差事件。

“买点/卖点”只作为 UI 筛选俗称，不作为数据库事件类型，也不能混淆 Signal 与 Fill。

> **V1.1.1 说明：** V1.0 3.4F 买卖点展示规则由本章整体替代。3.4F 中与本章冲突的买卖点表述、图例和“买卖点”术语不再有效。

## 18.2 必须展示的事件类型

**SIGNAL**
- `SignalCreated`，显示 Signal 类型（例如 BREAKOUT_CONTINUATION / PULLBACK_CONTINUATION）；
- `ACTIVE`、`CANCELLED`、`EXPIRED`、`PARTIALLY_EXECUTED`、`EXECUTED` 状态变化；
- `SignalCandidateRejected`，显示拒绝原因及是否消耗唯一槽位；
- 部分成交时显示 `filled_quantity`、`remaining_quantity`、`remaining_order_terminal_reason`。

**EXECUTION**
- `ExecutionConfirmed`；
- OrderSubmitted / OrderAccepted / OrderCancelled / OrderExpired（以实际事件模型为准）；
- `FILL_DEVIATION_BREACH` 对应的执行拒绝/撤单结果；
- `ACTUAL_RISK_BUDGET_BREACH` 对应的风险预算处理结果。

**FILL**
- 每一笔 `FillRecord` 独立标记，不得仅展示订单聚合均价；
- 显示 `fill_id`、`order_id`、`signal_id`、成交时间、成交价格、成交数量、手续费、流动性角色（若可得）；
- 部分成交按每笔 Fill 分别绘制，并可聚合查看已成交/剩余数量。

**EXIT**
- 固定止损触发；
- 结构止损触发；
- 移动止损更新及触发；
- `RiskReduction`；
- `ForcedExit`；
- `EmergencyExit` / `STOP_TRIGGERED_OR_INVALID`；
- `PositionClosed`。

**RISK**
- `FILL_DEVIATION_BREACH`；
- `ACTUAL_RISK_BUDGET_BREACH`；
- `RISK_ANOMALY`；
- `INVALID_ATR`；
- `RISK_ESCALATED`；
- `RISK_RECOVERED`；
- `CanOpen = False` 且 `CanHold = True` 的宏观状态组合。

事件代码大小写以 V1.4.8 代码/事件注册表为准；上述是展示分类，不得为 UI 自行改写后端事件事实。

## 18.3 图表图例与符号

默认图例建议如下。用户可调整主题色，但事件形状/线型语义必须保持：

| 事件 | 默认形状 | 视觉语义 |
|---|---|---|
| Signal ACTIVE | 空心三角形 | 尚未成交的有效信号 |
| Signal EXECUTED | 实心三角形 | 信号已执行，不代表单独一笔 Fill |
| Signal PARTIALLY_EXECUTED | 半填充三角形 | 已有成交且仍有剩余订单终态信息 |
| Signal CANCELLED / EXPIRED | 空心菱形加叉/斜线 | 未完成或撤销/过期 |
| SignalCandidateRejected | 灰色小叉 | 候选被拒绝，不是买入点 |
| ExecutionConfirmed | 小圆点 | 执行确认 |
| Fill | 实心方块 | 实际成交 |
| StopTriggered | 向下箭头 | 止损触发 |
| RiskReduction | 向下小三角 | 风险减仓 |
| ForcedExit / EmergencyExit | 叉号 | 强制/紧急退出 |
| PositionClosed | 方形终止标记 | 持仓结束 |
| Risk warning | 警告菱形/叹号 | 风险事件，不是买卖点 |

图例必须同时使用形状、边框/填充、线型和文字；颜色仅作辅助。

## 18.4 事件详情悬浮与侧栏

每个事件标记 hover/click 至少显示：
- `event_id`、`event_type`、`event_time`；
- `signal_id`、`setup_id`、`order_id`、`fill_id`（存在时）；
- `run_id`、`config_version_id`；
- 价格、数量、方向；
- 事件状态、原因码、拒绝原因；
- 相关 ATR 快照字段和值；
- 来源 Bar ID 和来源周期；
- 前序/后续关联事件链接。

字段不存在时显示 null/—，不得从相邻事件推断填充。

## 18.5 关键绘图规则

1. 未成交 Signal 只画 Signal 标记，不能画成 Fill 或“已买入”。
2. 部分成交必须明确显示已成交数量、剩余数量及 `remaining_order_terminal_reason`；不能将订单整体显示为完全成交。
3. `filled_quantity > 0` 时，即使剩余订单撤销/过期/被拒绝，Signal 状态仍按 V1.4.8 的 `PARTIALLY_EXECUTED` 语义展示。
4. 止损触发价、StopCandidate、已生效 Stop 价格和实际 Exit Fill 价格必须使用不同图层/符号。
5. 紧急市价退出标记在实际紧急退出决策/订单事件时间及实际 Fill 时间分别展示；不得把它伪装成旧 StopOrder 在该 Bar 成交。
6. 风险事件不画成买入或卖出点；它们可以与交易事件共享时间轴，但使用独立图层。
7. 同一 Bar 多个事件重叠时，使用 marker stack / cluster 展开，不允许静默覆盖事件。
8. `CanOpen=False, CanHold=True` 显示为“禁止新开仓、允许持仓继续”，不得显示为强制退出。

## 18.6 事件查询 API

增加：
- `GET /replay-runs/{run_id}/trading-events`
- `GET /positions/{position_id}/event-timeline`
- `GET /signals/{signal_id}/lifecycle`
- `GET /orders/{order_id}/fills`

所有返回事件必须包含稳定 `event_id` 和来源标识。实际 Fill 使用独立 `fill_id`，支持一订单多 Fill。

---

# 19. SwingPoint 确认策略与时间语义（P0）

## 19.1 字段定义

SwingPoint 人工标注增加：

```json
{
  "confirmation_policy": "ALGORITHM_DERIVED",
  "human_judged_confirmed_at": null,
  "algorithm_confirmed_at": "2025-01-01T10:45:00Z",
  "confirmed_at": "2025-01-01T10:45:00Z",
  "confirmation_evidence": {
    "algorithm_name": "V1.4.8_ZIGZAG",
    "algorithm_version": "V1.4.8",
    "confirmation_bar_id": "bar_confirm",
    "confirmation_bar_close_time": "2025-01-01T10:45:00Z",
    "atr_snapshot": "35.25",
    "atr_snapshot_source_bar_id": "bar_atr"
  }
}
```

枚举：
- `ALGORITHM_DERIVED`：按 V1.4.8 ZigZag 确认逻辑，由程序回放产生算法确认时间；人工审核极值位置、方向和对应确认事件，不自由指定一个更早的确认时间。
- `HUMAN_JUDGED`：人工独立判断确认时间；必须填写 `human_judged_confirmed_at`、证据说明和审核状态。

## 19.2 黄金样本默认策略

1. P0-E 黄金 Swing 样本默认 `ALGORITHM_DERIVED`。
2. 采用该模式时，先由冻结的 V1.4.8 基线 ZigZag 回放产生候选确认时间和证据；标注者审核候选 Swing 的发生位置、方向、算法确认 Bar 和 ATR 冻结快照。
3. 人工可以驳回候选、修正发生价/位置（必须记录原因），但不得把算法确认时间改成更早时间并仍标为 `ALGORITHM_DERIVED`。
4. 若研究人员要表达“人工认为在另一时刻已可确认”，必须切换为 `HUMAN_JUDGED`，该标签进入单独研究分层，不混入算法确认时间主准确率。
5. 人工修订必须保留原始算法建议值、修订人、修订原因和版本。

## 19.3 匹配和提前确认裁决

- 主 Ground Truth 准确率只对结构发生位置、方向和对象匹配计算；确认时间延迟单独作为诊断指标。
- `confirmation_delay_bars` 不进入主 Swing Precision / Recall / F1 的匹配代价，也不决定 Swing 是否命中。
- `ALGORITHM_DERIVED`：程序与同版本算法的确认时间应完全一致；若不一致，优先检查代码版本、配置、数据完整性、ATR 快照和确定性，标记 `REPLAY_CONFIRMATION_DIVERGENCE`，不是简单归为人工/程序准确率差异。
- `HUMAN_JUDGED`：程序 `confirmed_at` 早于人工 `human_judged_confirmed_at` 时标记 `PROGRAM_CONFIRMED_EARLIER`；晚于时标记 `PROGRAM_CONFIRMED_LATER`。两者均是诊断项，不自动判为结构识别错误。
- 只有明确违反 V1.4.8 因果约束（例如使用确认 Bar 之后才可获得的数据提前输出）才判为 `CAUSALITY_VIOLATION`。
- 匹配报告必须按 `confirmation_policy` 分组展示，禁止将两类标签混合统计。

## 19.4 API 校验

- `ALGORITHM_DERIVED` 的 `confirmed_at` 必须由 Golden Dataset 冻结时绑定的 `baseline_replay_run_id` 生成，不接受客户端任意写入，也不接受切换为其他 Replay Run。
- `golden_datasets` 表新增字段：`baseline_replay_run_id`、`baseline_code_commit`、`baseline_config_hash`。冻结后不可修改。
- 若需要升级基线算法，必须创建新的 Golden Dataset 版本，不得原地修改。
- 尝试用其他 Replay Run 写入 `ALGORITHM_DERIVED` 的 `confirmed_at` 时，API 返回 `409 BASELINE_REPLAY_MISMATCH`，记录审计日志并拒绝保存。
- `HUMAN_JUDGED` 必须包含 `human_judged_confirmed_at` 和 evidence。
- `confirmed_at >= occurred_at`。
- 确认时间必须对齐对应周期完成 Bar 的时间语义；具体使用 open_time 或 close_time 由 V1.4.8 时间契约决定，不得在 API 层混用。
- 价格字段 API 使用 Decimal 序列化字符串，数据库/计算层使用 Decimal 或定点数。

---

# 20. NStructure 失效缓冲标注（P0）

## 20.1 标注字段

NStructure 标注增加：
- `invalidation_rule_id`
- `n_structure_break_buffer_atr`
- `invalidation_atr_value`
- `invalidation_atr_source_bar_id`
- `invalidation_price`
- `invalidation_confirmed_at`
- `invalidation_bar_id`
- `invalidation_close`
- `invalidation_reason_code`
- `invalidation_status`: `NOT_INVALIDATED / INVALIDATED / AMBIGUOUS / SPEC_AMBIGUITY`

V1.4.8 首版为 `LONG_ONLY`，仅定义多头 N 结构失效公式。SACW 首版仅对多头 N 结构执行失效缓冲展示与标注。空头 N 结构失效公式留待未来策略扩展，UI 遇到空头 N 结构时显示 `OUT_OF_SCOPE_FOR_V1_4_8`。

对看涨 NStructure，按 V1.4.8 公式显示：
`invalidation_price = L2 - n_structure_break_buffer_atr × ATR_TF`

**ATR 时点处理：** V1.4.8 5.5 未指定 `ATR_TF` 的快照时点。SACW 不得默认使用当前最新 ATR 或 L2 确认时 ATR。在策略负责人裁定前：
- NStructure 标注的 `invalidation_atr_value`、`invalidation_atr_source_bar_id`、`invalidation_price` 标记为 `SPEC_AMBIGUITY`；
- UI 显示“ATR 快照时点待策略裁定”警告；
- 不得将此类 NStructure 纳入 PB-12/PB-13 主验收；
- 参数实验中 `n_structure_break_buffer_atr` 不可作为独立搜索维度，直到 ATR 时点冻结。

策略负责人裁定后，必须在 V1.4.8 增补明确的 ATR 快照字段名（如 `n_structure_invalidation_atr_15m`），SACW 再引用该字段，不得使用任何替代 ATR。

其余字段定义保持 V1.1 不变。

## 20.2 可视化与交互

- 在图表上显示 L2 参考线和独立失效缓冲线。
- 失效缓冲线 tooltip 显示 buffer 参数、ATR 数值、ATR 来源 Bar、计算结果和公式版本。
- 当完成 Bar Close 满足策略失效条件时，标出 `invalidation_bar_id`、收盘价、确认时间。
- 如果只触及 L2 但未满足缓冲失效条件，显示 `L2_TOUCHED_NOT_INVALIDATED` 诊断，不得把 NStructure 标为失效。
- 人工认为规则应用存在歧义时，标记 `AMBIGUOUS` 并填写原因；不允许为了贴合某次程序输出而改写冻结 Ground Truth。
- 参数实验可研究 `n_structure_break_buffer_atr`，但仅当 V1.4.8 参数注册表明确将它分类为 `RESEARCH`；不得由 UI 默认假设其可调。
- 若 `invalidation_status = SPEC_AMBIGUITY`，失效缓冲线使用虚线并显示“ATR 时点待定”标记。不得把该线当作可执行的策略失效价，也不得在 PB 回归中断言具体失效 Bar。

## 20.3 人工与程序比较

比较：
- L2 锚点匹配；
- buffer 参数和 ATR 快照是否一致；
- `invalidation_price` 误差；
- 首个满足失效条件的 Bar；
- `invalidation_confirmed_at`；
- invalidation 状态；
- 失效原因码。

若参数版本不同，必须先分层比较，不能把不同配置下的失效时间差直接算作算法 Bug。

---

# 21. Zone 标注模式与边界计算（P0）

## 21.1 标注模式

每个人工 Zone 必须有 `annotation_mode`：

- `ANCHOR_ONLY`：只确认锚点集合；Center / Lower / Upper 按指定 V1.4.8 配置快照和公式计算。黄金样本默认使用此模式。
- `HUMAN_BOUNDARY`：人工独立定义边界，供研究比较和仲裁使用；不得进入主 Zone 边界准确率，除非经单独规则审核并明确声明 Ground Truth 口径。
- `ANCHOR_ONLY_WITH_OVERRIDE`：存在已批准 `manual_boundary_override` 的 ANCHOR_ONLY Zone，进入单独研究分层，不进入 ANCHOR_ONLY 主边界准确率。

## 21.2 ANCHOR_ONLY 计算

1. 人工选择至少两个不同 SwingPoint 作为锚点。
2. 后端使用 V1.4.8 ZoneEngine 和同一 Config Snapshot 计算 Zone。
3. 展示并保存 `center`、`lower`、`upper`、`half_width`、锚点 ID、ATR 快照、tick size、公式版本和配置 Hash。

三个入选参数必须随快照一同记录，且必须来自同一 Config Snapshot：

- `zone_half_width_atr`：半宽的 ATR 倍数项。
- `zone_min_half_width_ticks`：半宽的最小 tick 项，与 `tick_size` 相乘后参与 `max(...)` 取大。
- `zone_max_age_weeks`：锚点年龄上限（见 6.8），超过该年龄的锚点从有效集合移除；
  该参数决定 Zone 是否因锚点过期进入 `INVALIDATED`，因此必须随比较结果一并记录。
4. 前端不得自行重写公式。V1.4.8 公式（包括 `half_width = max(min_half_width_ticks × tick_size, zone_half_width_atr × ATR_TF, (max(P)-min(P))/2)`）必须由后端策略实现计算；若 V1.4.8 实际公式字段或边界条件不同，以策略规格原文和代码为准。
5. 用户需要覆盖公式计算边界时，必须显式创建 `manual_boundary_override`，记录原计算边界、覆盖后边界、操作者、原因和审核状态；覆盖后的对象不能继续伪装成纯 `ANCHOR_ONLY`。

`manual_boundary_override` 数据结构：

```json
{
  "override_id": "ovr_uuid",
  "zone_annotation_id": "ann_zone",
  "original_lower": "2980.0",
  "original_upper": "3020.0",
  "original_center": "3000.0",
  "override_lower": "2975.0",
  "override_upper": "3025.0",
  "override_center": "3000.0",
  "operator": "user_id",
  "reason": "人工认为锚点覆盖不足",
  "review_status": "PENDING_REVIEW | APPROVED | REJECTED",
  "created_at": "2025-01-01T00:00:00Z",
  "strategy_spec_version": "V1.4.8",
  "config_hash": "sha256"
}
```

> 存在已批准 `manual_boundary_override` 的 Zone 必须标记 `annotation_mode = ANCHOR_ONLY_WITH_OVERRIDE`，不得继续标记为纯 `ANCHOR_ONLY`，也不得进入 `ANCHOR_ONLY` 主边界准确率。`ANCHOR_ONLY_WITH_OVERRIDE` 进入单独研究分层。

## 21.3 HUMAN_BOUNDARY 规则

- 人工绘制的边界保存为 `human_lower`、`human_upper`、`human_center`。
- 原始程序边界另存为 `program_lower`、`program_upper`、`program_center`。
- HUMAN_BOUNDARY 仅进入人工边界研究集和仲裁视图；不得混入 ANCHOR_ONLY 主准确率。
- 若人工只提供锚点，禁止系统推断人工边界作为 Ground Truth。

## 21.4 比较指标

ANCHOR_ONLY 主比较：
- Anchor Precision / Recall；
- 由相同锚点和相同配置计算的边界一致性；
- Program Zone 与 Ground Truth Zone 的 Center / Width / Upper / Lower Error；
- Zone 状态转移差异。

Zone 比较必须记录并报告下列参数的实际生效值，否则结果不可复现：

- `zone_min_half_width_ticks`（V1.1.2 补入）：影响 `half_width` 的最小 tick 项；
- `zone_max_age_weeks`（V1.1.2 补入）：影响锚点是否过期、进而影响 Zone 是否 `INVALIDATED`；
- 同时报告 `tick_size` 来源版本，因为 tick 项依赖它。

当两个 Zone 的 `half_width` 由不同项决定（tick 项 / ATR 项 / 锚点跨度项）时，必须标注
决定性项，避免把「因最小 tick 支撑而变宽」误判为边界估计误差。

HUMAN_BOUNDARY 研究比较：
- Center Error；
- Upper / Lower Error；
- Width Ratio；
- 边界重叠率；
- 人工分歧统计。

报告必须显示 `annotation_mode`，不同模式分开汇总。

---

# 22. Setup 观察区、交集和多周期投影（P0）

## 22.1 图层对象

必须独立展示：
- `Observation4H`；
- `Observation1H`；
- `Observation1H = Intersection(Observation4H, Zone1H)`；
- 15M 层显示的定位区（见下文，不创建独立 15M Zone）；
- 4H Zone、1H Zone 在下级周期图表上的投影边界。

**15M 不创建独立观察区，也不创建独立 15M Zone。** 图中 15M 层显示的定位区为：
- `BREAKOUT_CONTINUATION`：直接使用 `Observation1H` 交集区，标注来源 `setup_1h_id`、`observation_zone_id`、`observation_zone_version`；
- `PULLBACK_CONTINUATION`：使用 `Observation1H` 交集区，并叠加 `pullback_low_zone_tolerance_atr × signal_decision_atr_15m` 的 PullbackLow 容差带；容差带只用于显示 PullbackLow 位置校验范围，不是 Zone，不参与 Zone 状态机；
- 上述对象必须标记 `source_timeframe = 1H` 或 `DERIVED_DISPLAY`，不得标记为 15M Zone；
- 15M 信号关联的 `n_structure_id`、`setup_4h_id`、`setup_1h_id` 必须可点击跳转。

每个可视对象必须保存：
`object_id`, `source_timeframe`, `source_zone_id`, `setup_id`, `parent_setup_id`, `valid_from`, `valid_to`（Setup 使用 `expires_at`）, `known_at`, `lower`, `upper`, `config_hash`。

## 22.2 显示规则

- 在 4H 图显示 Observation4H 的原生区间。
- 在 1H 图显示 Observation4H 投影、Zone1H、Observation1H 交集区；各自独立图层，不合并成一个不透明矩形。
- 在 15M 图显示来自 4H/1H 的投影区、Observation1H 交集区和 PullbackLow 容差带；每个区域标明源周期、Zone ID、Setup ID。
- 选择 Signal 时，联动高亮关联 Setup4H、Setup1H、ObservationZone、NStructure、Signal 触发 Swing 和相关 Zone。高亮顺序为 `setup_4h_id → setup_1h_id → observation_zone_id → n_structure_id → trigger_swing_id`。
- 区域超出有效期后应按 `valid_to` / `expires_at` 截止，不得无限延伸到当前图表右侧。
- 同一价格区间的跨周期投影仍是不同对象，不能合并 ID、合并状态或合并来源。
- 15M 图上的 `Observation1H` 交集区、4H/1H 投影区、PullbackLow 容差带必须分别使用不同填充样式和来源标签；三者不得合并为同一对象，也不得用 4H 投影边界替代 `Observation1H` 交集区。

## 22.3 交集失败事件

对 `SETUP1H_NO_INTERSECTION`、`SETUP1H_INTERSECTION_TOO_NARROW`：
- 在对应 1H 判定 Bar 上绘制拒绝事件标记；
- 详情展示两个输入区域边界、交集计算结果、最小宽度要求、配置 Hash 和原因码；
- 若没有交集，显示“无交集”；若交集宽度不足，显示实际宽度和门槛；
- 不得生成一个虚构的 Setup1H 或 Signal 观察区。

## 22.4 投影语义限制

**投影 Zone 边界只用于可视化上下文，不参与 15M L2 位置判定。** 15M L2 位置判定必须使用 V1.4.8 定义的 `Observation1H` 交集区及对应引用；禁止用 4H 投影边界替代。

15M 层不存在独立 Zone 对象；任何标记为 `15M Zone` 的图层均为实现错误，必须在回归测试中拦截。`Observation1H` 交集区与 PullbackLow 容差带均属于 `DERIVED_DISPLAY`，可展示、可定位，但不得回写策略引擎作为 Zone 或 ObservationZone。

---

# 23. PB-01 至 PB-51 回归样本工作台（P0）

## 23.1 页面布局

新增一级页面：`回归样本（Regression Cases）`。

桌面布局：
- 左侧：PB 样本列表、类别过滤、状态过滤、版本过滤、搜索。
- 中间：K 线主图，自动定位样本指定周期和 Bar 区间。
- 右侧：场景说明、输入数据、人工预期、程序实际输出、差异字段和审核操作。
- 底部：事件时间线、差异 Bar 列表、运行日志摘要。

## 23.2 每个 PB 样本字段

每个样本至少包括：
- `case_id`：PB-01 至 PB-51；
- `case_version`；
- `title`、`scenario_description`；
- `spec_section`；
- `instrument_id`；
- `timeframes`；
- `dataset_id` / `dataset_hash`；
- `bar_ranges`：每周期起止 Bar ID / 时间；
- `preconditions`；
- `input_events`；
- `expected_events`；
- `expected_state_transitions`；
- `expected_final_state`；
- `expected_absent_events`；
- `expected_absent_state_transitions`；
- `negative_assertion_reason`；
- `actual_replay_run_id`；
- `actual_events`；
- `assertion_results`；
- `status`；
- `review_status`；
- `expectation_revision_id`。

负向断言字段格式：

```text
expected_absent_events: []               # 每项含 event_type、匹配范围、匹配窗口
expected_absent_state_transitions: []    # 每项含 timeframe、from_state、to_state、窗口
negative_assertion_reason: str           # 负向断言依据的 V1.4.8 条款
```

每个负向断言至少包含：
- `assertion_id`
- `window_start_bar_id` / `window_end_bar_id`
- `forbidden_event_type` 或 `forbidden_transition`
- `scope`（timeframe、setup_id、n_structure_id、signal_id）
- `reason_spec_section`
- `evaluation_result`（PASSED / FAILED / BLOCKED）

负向断言与正向断言同等权重；任一负向断言失败即 PB 失败，不得因“正向全部通过”而忽略。

不得只保存自然语言描述；PB 预期结果必须结构化为可执行断言。

## 23.3 样本页面交互

- 点击 PB 项自动加载对应数据集、周期、Bar 区间和初始快照。
- 预期事件与程序实际事件使用独立图层。
- 差异字段定位到具体 Bar、事件 ID、字段路径。
- 支持“只看失败断言”“只看未匹配事件”“只看状态转换差异”。
- 支持单例运行、批量运行、全部 PB-01 至 PB-51 运行。
- 显示每例耗时、回放 Run ID、代码 Commit、Config Hash、数据 Hash。
- 失败时允许从差异行跳转至图表对应 Bar 和事件详情。
- 全部 51 例的汇总状态可导出，但导出不能替代页面可视化验收。

**全套回归一键运行：**
- 提供 `Run all PB-01 to PB-51` 按钮；
- 运行前必须显示当前 `code_commit`、`config_hash`、`dataset_hash`、`PB expectation_revision` 版本；
- 运行中显示每例状态（PENDING / RUNNING / PASSED / FAILED / BLOCKED）；
- 完成后显示通过/失败/阻塞计数、总耗时、失败用例列表；
- 支持导出汇总 JSON，包含 `regression_run_id` 和每例 assertion 结果；
- 页面展示与导出 JSON 必须引用同一 `regression_run_id`，不得分别统计。

## 23.4 预期结果修订治理

允许提出 `PB_EXPECTATION_REVISED`，但不能直接覆盖预期结果：
1. 用户创建修订提案，说明原预期、拟修改内容、证据和 V1.4.8 对应条款。
2. 修订进入 `PENDING_REVIEW`。
3. 审核人检查是否属于规格修订、测试数据错误、原预期录入错误或程序 Bug。
4. 若策略规格未变且原预期确有错误，批准后创建新 `expectation_revision_id`。
5. 若实际属于 V1.4.8 规则变化，必须升级策略规格版本，不得只改 PB 预期。
6. 旧版本保留，所有历史回归报告仍指向原版本。
7. 每次修订后重新运行受影响 PB 和完整 PB-01 至 PB-51 回归。

## 23.5 PB API

增加：
- `GET /regression-cases`
- `GET /regression-cases/{case_id}`
- `GET /regression-cases/{case_id}/runs`
- `POST /regression-cases/{case_id}/runs`
- `POST /regression-suites/v1-4-8/run`
- `GET /regression-runs/{run_id}`
- `GET /regression-runs/{run_id}/assertions`
- `POST /regression-cases/{case_id}/expectation-revisions`
- `POST /regression-cases/{case_id}/expectation-revisions/{revision_id}/review`

## 23.6 P0 验收

- PB-01 至 PB-51 均可从 UI 打开并定位到具体 Bar 区间。
- 每例可查看结构化预期与实际输出。
- 每例失败可定位到具体差异 Bar、事件和字段。
- 可显示通过/失败/待审核/被阻塞状态。
- 预期修订必须审批、版本化和审计。
- PB 全套回归结果与代码、配置、数据、预期版本 Hash 绑定。
- PB-02、PB-07、PB-25、PB-27、PB-28 等负向用例必须通过 `expected_absent_events` 或 `expected_absent_state_transitions` 结构化断言。
- 任一负向断言失败时，页面必须定位到 forbidden 事件未发生窗口或 forbidden 状态转换窗口。
- 全套回归必须支持一键运行，并以 `regression_run_id` 关联所有断言结果。

---

# 24. 快照查看页面（P1）

新增 `Snapshot Inspector` 页面，可按 `snapshot_id` 或 `replay_run_id + timestamp` 查询。

至少展示：
- 快照时间、快照类型、数据集 Hash、配置 Hash、代码 Commit；
- 每周期最后完成 Bar 时间；
- SMA22、ATR14、ZigZag 方向和候选状态；
- SwingPoint 列表及确认时间；
- NStructure 列表、有效性、L2 和失效缓冲；
- Zone 列表、锚点、版本、状态和来源周期；
- TrendState / MacroState；
- ProtectedLow / ProtectedHigh；
- PullbackOriginHigh；
- Setup4H / Setup1H 及 Observation 区间；
- 未完成 Signal 及生命周期状态；
- Orders、`ExecutionRecord.fills`、Position、活动 Stop；
- `CanOpen` 与 `CanHold` 的独立值及其原因。

快照数据只读。页面必须提供“与前一快照比较”，展示新增、删除、字段变化和状态转换；不得通过快照页面修改回放事实。

增加 API：
- `GET /snapshots/{snapshot_id}`
- `GET /replay-runs/{run_id}/snapshots/{timestamp}`
- `GET /snapshots/{snapshot_id}/diff?base_snapshot_id=...`

---

# 25. 参数实验室 UI（P1）

## 25.1 页面结构

新增/完善 `参数实验室` 页面，至少包括：
1. Experiment 列表；
2. Trial 列表；
3. Trial 详情；
4. Pareto 前沿；
5. 参数敏感性；
6. 数据切分和隔离状态；
7. 候选配置对比。

## 25.2 Trial 列表字段

每个 Trial 显示：
- `trial_id`；
- 参数组合及参数 Hash；
- 参数分类校验结果；
- Calibration 指标；
- Validation 指标（完成验证后才显示）；
- Holdout 状态（默认仅显示 `SEALED / NOT_RUN / PASSED / FAILED`，按权限决定是否可见具体数值）；
- 运行状态、失败原因、耗时；
- 关联 Replay Run、Dataset、Golden Dataset；
- 代码 Commit、Config Hash、Matcher Version。

## 25.3 Holdout 隔离

**Holdout 访问角色：**

| 角色 | Calibration | Validation | Holdout 汇总 | Holdout 逐样本 |
|---|---|---|---|---|
| `PARAM_TUNER` | 可见 | 不可见 | 不可见 | 不可见 |
| `VALIDATION_REVIEWER` | 只读 | 可见 | 不可见 | 不可见 |
| `HOLDOUT_EXECUTOR` | 只读 | 只读 | 可见 | 可见 |
| `APPROVER` | 只读 | 只读 | 可见 | 不可见 |
| `AUDITOR` | 只读 | 只读 | 可见（审计用途） | 可见（审计用途） |

权限由后端实施，前端隐藏控件不构成隔离。

**Holdout 消耗规则：**
- 一旦 Holdout 结果被用于选择参数，该 Holdout 标记 `CONSUMED_FOR_SELECTION`；
- `CONSUMED_FOR_SELECTION` 的 Holdout 不得再宣称为独立最终测试集；
- 需要新的独立验收时，必须建立新的未见时间段或重新定义测试协议，并升级 `golden_dataset` 版本。

一次实验只允许一个 Holdout 执行角色运行一次 Holdout。重复运行必须由 `HOLDOUT_EXECUTOR` 显式发起新实验版本，旧结果保留审计。

## 25.4 Pareto 与敏感性视图

Pareto 图必须显示选定的两个或三个目标维度，支持筛选、悬浮查看 Trial、点击跳转 Trial 详情。图表不得把单一收益指标作为唯一优化目标。

参数敏感性图按单参数取值展示各识别指标、相对基线变化、样本数和稳定性；不同市场区间可分组查看。对不稳定参数显示 `UNSTABLE_PARAMETER`。

V1.1.2 起，敏感性分析必须覆盖全部 8.1 白名单参数，其中特别注意下列两项（此前遗漏）：

- `zone_min_half_width_ticks`：在小 tick 值区间内会改变 `half_width` 的决定项，
  从而导致 Zone 边界与匹配结果阶跃变化；
- `zone_max_age_weeks`：改变锚点过期时机，直接影响 Zone 生命周期与 Setup 可用性，
  敏感性图须按时间轴展示失效边界变化。

## 25.5 Trial 详情

显示：
- 完整参数 JSON 和参数分类；
- 基线与候选指标差异；
- 失败断言和错误日志；
- 按时间段、市场状态分层的指标；
- 关联 PB 回归结果；
- 关联 Replay Run 事件；
- 是否满足生成 Candidate 的门槛。

参数实验室不得提供修改 FIXED/REQUIRED/METADATA 或状态机逻辑的 UI 控件。

---

# 26. Lightweight Charts MVP 交互边界（P1）

## 26.1 MVP 交互（不依赖复杂拖拽）

MVP 必须先实现：
- SwingPoint：点击 Bar 放置；右侧属性面板修改字段。
- NStructure：依次点击选择四个已存在 SwingPoint；自动连线；不拖拽锚点。
- Zone：选择 Swing 锚点；调用后端计算边界；不自由拖拽边界。
- StateInterval：在时间轴选择起止 Bar；右侧选择状态。
- Setup/Signal/交易事件：由事件数据驱动展示；人工事件可通过属性面板创建/编辑。
- 区域/点位选中后，通过属性面板编辑，不要求首版直接在图表上拖动。

## 26.2 P1 增强交互

后续才实现：
- Swing 锚点拖拽及吸附 Bar；
- Zone 边界拖拽与覆盖审核；
- 多点批量编辑；
- 复杂区域绘制；
- 高级图层组合和自定义布局。

任何拖拽修改都必须保存为新 revision，并记录原始数据坐标、修改后坐标和操作者。

## 26.3 图表性能要求

- 采用可视范围数据加载和增量更新。
- 指标序列与标注事件按时间范围分页。
- 图层更新不得重建整个 Chart。
- 大量事件按时间/价格聚类；聚类展开后必须能定位每个原始事件。
- 多周期联动只同步时间，不将不同周期的 Bar ID 混用。
- 通过性能测试确定目标设备和数据规模；未测量前不得宣称固定 FPS 或百万级事件能力。

---

# 27. API 与数据契约增补

## 27.1 Decimal 序列化

- API JSON 中价格、数量、费率、ATR、边界和金额均序列化为十进制字符串，例如 `"3100.125"`。
- 后端计算使用 Decimal 或定点数；前端只负责解析显示，不以 JS `number` 作为持久化真值。
- 时间使用 ISO-8601 UTC 字符串，明确 Bar 的 open_time / close_time 语义。
- 价格字段不得一部分返回 JSON number、一部分返回 string。

## 27.2 标准事件信封

所有程序事件统一包含：

```json
{
  "event_id": "evt_uuid",
  "event_type": "FILL",
  "event_code": "FILL_RECORDED",
  "event_time": "2025-01-01T12:00:00Z",
  "occurred_at": "2025-01-01T12:00:00Z",
  "confirmed_at": "2025-01-01T12:00:00Z",
  "instrument_id": "ETH-USDT-SWAP.OKX",
  "timeframe": "3M",
  "source_bar_id": "bar_uuid",
  "run_id": "run_uuid",
  "config_hash": "sha256",
  "payload": {}
}
```

字段按事件语义可为空，但必须区分“无此语义”与“数据缺失”。事件原始字段不得为了满足 UI 而伪造。

## 27.3 FillRecord

每笔 Fill 独立存储：
- `fill_id`
- `order_id`
- `signal_id`
- `position_id`
- `fill_time`
- `fill_price`
- `fill_quantity`
- `fee_amount`
- `fee_currency`
- `liquidity_side`（若可得）
- `source_bar_id`
- `execution_reference_atr_15m`
- `fill_deviation_atr`（若该事件适用）
- `run_id`
- `code_commit`
- `config_hash`

订单级汇总字段不能替代 FillRecord。FillRecord 是审计事实，不得由前端合并覆盖。

## 27.4 Matcher 默认配置

Matcher 与策略参数分离。V1.1.1 首版默认配置：

```json
{
  "matcher_version": "SACW_SWING_MATCHER_V1",
  "swing": {
    "max_time_tolerance_bars": 1,
    "max_price_tolerance_atr": "0.10",
    "max_price_tolerance_ticks": 2,
    "price_tolerance_mode": "MIN_OF_ATR_AND_TICKS",
    "confirmation_time_in_primary_cost": false,
    "weights": {
      "w_t": "0.50",
      "w_p": "0.50",
      "w_c": "0.00"
    }
  }
}
```

说明：
- 上述仅是 Matcher 初始比较配置，不是 V1.4.8 策略参数，也不能作为自动扩大容差的依据。
- 时间/价格容差最终必须通过人工样本复核后冻结为 matcher version。
- `MIN_OF_ATR_AND_TICKS` 表示候选匹配需同时满足 ATR 容差和 tick 容差；若 V1.4.8 项目决定采用其他口径，必须升级 matcher version 并记录理由。
- `confirmation_time_in_primary_cost = false` 的强制语义：`confirmation_delay_bars` 只进入 19.3 诊断指标；不进入 7.2 的 `cost` 中的 `w_c` 项；默认 `w_c = "0.00"`，禁止在 P0/P1 阶段用确认时间改善匹配率；若未来需要将确认时间纳入代价，必须升级 `matcher_version` 并在报告中单独声明，不得与主准确率混算。
- 结构匹配还需保证顺序、方向和对象引用一致，不能只凭总代价匹配。

## 27.5 参数注册表单一来源

- 参数名、初始值、分类、范围、周期和说明必须直接从 V1.4.8 第 19 章及其机器可读参数注册表生成。
- SACW 不维护一套可独立演进的参数别名表。
- 本文 V1.0 第 8.1 节中的候选参数表只作为历史说明，不具备覆盖 V1.4.8 参数注册表的权力；实现时若字段名/默认值/分类不一致，以 V1.4.8 为准并报告 `PARAMETER_REGISTRY_MISMATCH`。
- 未能从 V1.4.8 明确确认分类为 `RESEARCH` 的参数，不得进入搜索空间。
- 任何策略规格升级都必须重新生成参数注册表快照和 Hash。

### V1.1.2 新增：白名单比对与遗漏声明

1. **强制逐一比对。** 8.1 的候选搜索白名单必须与 V1.4.8 第 19 章参数表**逐项比对**，
   比对结果写入参数注册表快照。比对维度：参数名、分类、初始值、单位。
2. **遗漏不得静默。** V1.4.8 中分类为 `RESEARCH` 但**本版不纳入搜索**的参数，
   必须在白名单中显式列出并标注 `OUT_OF_SEARCH_SCOPE` 及原因（例如「依赖未实现的上游
   结构，待 P1 后启用」）。**禁止静默省略**——静默省略会让校准覆盖面在无人察觉的情况下缩小，
   这正是 V1.1.1 遗漏 `Zone Min Half Width Ticks` 与 `Zone Max Age` 的成因。
3. **超出不得混入。** V1.4.8 第 19 章不存在的参数不得进入白名单，也不得为其编造分类
   （参见 `ATR_MA22` 的处理，见 17.1）。
4. **比对产物。** 每次升版必须产出比对表，包含三列：`V1.4.8 RESEARCH 参数`、
   `SACW 搜索状态（SEARCHABLE / OUT_OF_SEARCH_SCOPE）`、`差异原因`。该表进入配置版本
   发布报告（见 9.4）。

## 27.6 NStructure 失效 ATR 快照待定

V1.4.8 5.5 未指定 `ATR_TF` 快照时点，构成规格歧义。

处理规则：

1. SACW 不自行定义 N 结构失效 ATR 时点。
2. 相关 NStructure 标注标记 `invalidation_status = SPEC_AMBIGUITY`。
3. UI 显示“ATR 时点待策略裁定”，失效缓冲线为虚线。
4. `n_structure_break_buffer_atr` 不进入参数搜索空间，直至 ATR 时点冻结。
5. PB-12、PB-13 暂不作为 P0 验收门槛，标记 `BLOCKED_BY_SPEC_AMBIGUITY`。
6. 策略负责人裁定后，必须新增 V1.4.8 参数注册表字段，SACW 引用该字段后解除阻塞。
7. 本规则与 20.1、20.2 一致；如有冲突，以本章为准。

---

# 28. 术语与前端导航最终清单

统一术语：
- “交易事件标记”统称 Signal / Execution / Fill / Exit / Risk 事件。
- “买入/卖出点”仅是用户界面筛选语，不作为事实数据类型。
- `Signal` 表示策略信号，不表示成交。
- `Fill` 表示单笔成交事实。
- `StopCandidate`、Active Stop、StopTriggered、ExitFill 是不同阶段。
- “程序识别结果”是 `PROGRAM_PREDICTION`；“人工 Ground Truth”是审核冻结后的人工标签；“实际执行”是 `ACTUAL_EXECUTION`。

最终一级导航：
1. 数据集
2. 结构标注
3. 程序识别
4. 差异对比
5. 回归样本
6. 快照查看
7. 参数实验室
8. 配置版本
9. 运行与审计

---

# 29. V1.1.2 前端验收矩阵

| 编号 | 验收项 | 优先级 | 验收标准 |
|---|---|---|---|
| UI-001 | SMA22 | P0 | 支持指定周期独立开关，显示来源 Bar |
| UI-002 | ATR14 | P0 | 独立指标面板；显示数值、单位、来源 Bar、完成状态；未定义字段不伪造 |
| UI-003 | ZigZag 候选 | P0 | 候选点、冻结 ATR、反转阈值可查看 |
| UI-004 | ATR Snapshot Inspector | P1 | 四类 ATR 快照按事件来源分别展示 |
| UI-005 | 交易事件五分类 | P0 | Signal / Execution / Fill / Exit / Risk 全覆盖 |
| UI-006 | Signal 生命周期 | P0 | ACTIVE/CANCELLED/EXPIRED/PARTIALLY_EXECUTED/EXECUTED 可见 |
| UI-007 | 部分成交语义 | P0 | 显示成交量、剩余量、终止原因 |
| UI-008 | 风险事件 | P0 | 风险异常/升级/恢复/CanOpen-CanHold 可见 |
| UI-009 | Swing confirmation_policy | P0 | 两种策略分层、时间诊断分离；`ALGORITHM_DERIVED` 的 `confirmed_at` 由后端 `baseline_replay_run_id` 生成，前端不可写入；尝试写入返回 403 并记录审计 |
| UI-010 | NStructure 缓冲失效 | P0 | 缓冲线、ATR 来源、失效 Bar 可核对 |
| UI-011 | Zone 标注模式 | P0 | ANCHOR_ONLY 默认；HUMAN_BOUNDARY / ANCHOR_ONLY_WITH_OVERRIDE 独立统计 |
| UI-012 | Setup 观察区投影 | P0 | 4H/1H/15M 区域来源、交集和失败原因可见；15M 不创建独立 Zone |
| UI-013 | PB-01 至 PB-51 页面 | P0 | 每例可定位、比较、失败跳转和预期修订审核；全套可一键运行 |
| UI-014 | 快照查看 | P1 | 状态、指标、结构、Signal、Position 可追溯 |
| UI-015 | 参数实验室 | P1 | Trial、Pareto、敏感性、Holdout 隔离 |
| UI-016 | MVP 无拖拽交互 | P1 | 点击放置/选择锚点/属性面板完成标注 |
| UI-017 | Decimal API | P2 | 价格数量等统一十进制字符串 |
| UI-018 | Matcher 版本化 | P2 | 默认值、权重和版本可追溯；确认时间不进入主代价 |
| UI-019 | 参数注册表单一来源 | P2 | 严格读取 V1.4.8 第 19 章，不维护漂移别名 |
| UI-020 | NStructure 失效 ATR 时点歧义 | P0 | 当 V1.4.8 未定义失效 ATR 快照时，UI 显示 `SPEC_AMBIGUITY`；不得默认使用当前 ATR；该 NStructure 不纳入 PB-12/PB-13 主验收 |
| UI-021 | PB 负向断言 | P0 | `expected_absent_events` / `expected_absent_state_transitions` 可配置、可执行、可定位失败；负向断言失败即 PB 失败 |
| UI-022 | ATR_MA22 未定义（V1.1.2） | P0 | V1.4.8 未定义 `ATR_MA22`；UI 显示 `N/A / SPEC_AMBIGUITY`，不得自行计算、不得绘制曲线、不得进入图层/光标提示/事件载荷/参数搜索空间；验收时断言页面不存在该指标图层 |

---

# 30. AI 编码代理增补指令

1. 编码前先实现 V1.4.8 指标/事件/参数注册表读取适配层，再实现 UI；不能先写静态假数据图层。
2. 前端图层必须有 `source_type`、`source_id`、`run_id`、`config_hash`，并能按来源过滤。
3. 任何候选指标、事件或快照字段都必须来自后端 API；前端不能自行推断策略状态。
4. 先完成 P0 指标、事件、Swing 确认、NStructure 失效、Zone 模式、Setup 投影、PB UI；再做 P1 快照和参数实验室增强。
5. PB 预期和程序实际结果必须使用不同数据对象、不同图层和不同权限。
6. 对 `ALGORITHM_DERIVED` 的 Swing 确认时间，不允许前端写入或覆盖。
7. 对 ANCHOR_ONLY Zone，前端只能选择锚点并请求后端计算，不能自行计算后作为策略事实保存。
8. 任何投影区域必须保留来源周期和来源对象 ID；投影不改变策略判定输入。
9. 事件标记必须由事件流驱动；禁止根据 K 线形态或颜色推断买卖点。
10. 不得把 Holdout 数值泄漏给调参角色；后端必须做权限校验。
11. Lightweight Charts MVP 不要求复杂拖拽；先按点击/选择/属性面板实现可测试交互。
12. 若 V1.4.8 代码/规格缺少本补充要求的数据字段，先提出明确的数据契约变更，不得用临时字段或静态常量伪造。
13. 禁止为 NStructure 失效 ATR 时点自行选择替代 ATR；必须标记 `SPEC_AMBIGUITY`。
14. 禁止将 15M 层显示对象标记为独立 15M Zone。

---

# 31. V1.1.1 最终实施优先级

## P0：前端核心闭环

- 指标展示：SMA22、ATR14、ZigZag 候选、候选冻结 ATR、反转阈值。
- 交易事件标记五分类，覆盖 Signal 生命周期、拒绝事件、部分成交、FillRecord、止损/紧急退出、风险事件。
- Swing confirmation_policy 及确认时间分层。
- NStructure 失效缓冲线和证据字段；ATR 时点未定义时显示 `SPEC_AMBIGUITY`。
- Zone ANCHOR_ONLY / HUMAN_BOUNDARY / ANCHOR_ONLY_WITH_OVERRIDE 模式。
- Setup4H / Setup1H / Intersection / 15M 定位区投影；15M 不创建独立 Zone。
- PB-01 至 PB-51 回归样本页面、负向断言和预期修订审核。
- Ground Truth、程序预测、实际执行三类图层持续隔离。
- 诊断码注册表落地。

## P1：研究效率与增强交互

- ATR 快照侧栏。
- Snapshot Inspector。
- 参数实验室 Trial / Pareto / 敏感性视图及 Holdout 隔离。
- Lightweight Charts 点击式 MVP 交互；拖拽编辑延后。
- 多事件聚类、快照 diff 和高级联动。

## P2：一致性和治理完善

- Decimal API 契约。
- Matcher 默认配置和版本化。
- V1.4.8 第 19 章参数注册表单一来源。
- 导出报告、图例主题和可访问性优化。

**V1.1.1 冻结条件：** 上述 P0 验收项全部通过，PB-01 至 PB-51 能在 UI 完整定位和核对，负向断言可执行，且不存在将 Signal 当作 Fill、将投影 Zone 当作策略判定输入、将人工确认时间冒充算法确认时间、将人工 Zone 边界混入 ANCHOR_ONLY 主准确率、将 15M 显示对象当作独立 15M Zone 等语义错误。PB-12/PB-13 在策略负责人裁定 N 结构失效 ATR 时点前保持 `BLOCKED_BY_SPEC_AMBIGUITY`。

---

# 32. SACW 诊断码与状态码注册表

## 32.1 诊断码

| 代码 | 所属对象 | 触发条件 | 图例 | 进入主准确率 | 进入审计 |
|---|---|---|---|---|---|
| `REPLAY_CONFIRMATION_DIVERGENCE` | Swing | `ALGORITHM_DERIVED` 下程序与基线算法确认时间不一致 | 黄色感叹号 | 否 | 是 |
| `PROGRAM_CONFIRMED_EARLIER` | Swing | `HUMAN_JUDGED` 下程序确认早于人工 `human_judged_confirmed_at` | 蓝色左箭头 | 否 | 是 |
| `PROGRAM_CONFIRMED_LATER` | Swing | `HUMAN_JUDGED` 下程序确认晚于人工 `human_judged_confirmed_at` | 蓝色右箭头 | 否 | 是 |
| `CAUSALITY_VIOLATION` | Swing / Structure | 使用确认 Bar 之后才可获得的数据提前输出 | 红色叉 | 是（计为错误） | 是 |
| `L2_TOUCHED_NOT_INVALIDATED` | NStructure | Close 触及 L2 但未满足缓冲失效条件 | 灰色虚线 | 否 | 是 |
| `SPEC_AMBIGUITY` | NStructure / 通用 | 规格未定义关键时点或公式 | 橙色问号 | 否 | 是 |
| `PARAMETER_REGISTRY_MISMATCH` | 参数 | SACW 字段名或默认值与 V1.4.8 注册表不一致 | 红色感叹号 | 不适用 | 是 |
| `BASELINE_REPLAY_MISMATCH` | Swing / API | `ALGORITHM_DERIVED` 写入使用非基线 Replay Run | 红色禁止符 | 不适用 | 是 |
| `INVALID_ATR` | Signal / Fill / Stop | ATR 缺失、非有限或 ≤0 | 橙色感叹号 | 是（计为异常） | 是 |
| `PROGRAM_ONLY` / `HUMAN_ONLY` | Swing / Structure / Zone | 单向匹配 | 灰点 | 是（作为漏检/误检） | 是 |
| `AMBIGUOUS_MATCH` | Swing / Structure / Zone | 多候选近似匹配 | 黄色问号 | 否（需人工复核） | 是 |
| `UNSTABLE_PARAMETER` | 参数 | 敏感性测试中相邻取值剧烈波动 | 橙色波浪线 | 不适用 | 是 |
| `CONSUMED_FOR_SELECTION` | Holdout | Holdout 已被用于选参 | 红色封条 | 不适用 | 是 |
| `OUT_OF_SCOPE_FOR_V1_4_8` | NStructure | 空头 N 结构在 LONG_ONLY 首版中出现 | 灰色禁止符 | 不适用 | 是 |

## 32.2 状态码

| 代码 | 所属对象 | 含义 | 是否终态 |
|---|---|---|---|
| `PENDING_REVIEW` | PB 预期修订 / Zone override | 等待审核 | 否 |
| `BLOCKED_BY_SPEC_AMBIGUITY` | PB / 参数 / NStructure | 被规格歧义阻塞 | 是（待裁定后重开） |
| `SPEC_AMBIGUITY` | NStructure / 通用 | 规格歧义标记 | 否（裁定后清除） |
| `MANUAL_BOUNDARY_OVERRIDE` | Zone | 人工边界覆盖已生效 | 否（可再次修订） |

## 32.3 与 V1.1 枚举的关系

- 32.1/32.2 是 SACW 诊断码与状态码，不与 V1.4.8 事件类型或 Signal 状态枚举混用；
- 4.3 标注状态（DRAFT / SUBMITTED / REVIEWED / APPROVED / FROZEN / SUPERSEDED / REJECTED）与 32.2 的 `PENDING_REVIEW` 是两套状态，不得混用；
- 19.3、20.1、21.2、23.4、27.5 中引用的诊断码以本章为准。

---

# 33. V1.4.8 字段名映射表

SACW 展示字段与 V1.4.8 字段名对照。SACW 只做展示别名，持久化和 API 契约以 V1.4.8 字段名为准。

| SACW 展示名 | V1.4.8 字段名 | 说明 |
|---|---|---|
| `frozen_atr` | `atr_snapshot` | SwingPoint 候选冻结 ATR |
| `valid_to`（Setup） | `expires_at` | Setup 到期时间 |
| `FillRecords` | `ExecutionRecord.fills` | 成交记录列表 |
| `ZigZag 方向 UP/DOWN/UNINITIALIZED` | `SEEK_HIGH / SEEK_LOW / UNKNOWN` | ZigZag 状态枚举 |
| `Observation1H` 交集区 | `Observation1H = Intersection(Observation4H, Zone1H)` | 不新增独立字段 |
| `signal_decision_atr_15m` | 同名字段 | 见 V1.4.8 11.5 F |
| `execution_reference_atr_15m` | 同名字段 | 见 V1.4.8 11.5 F |
| `initial_stop_atr_15m` | 同名字段 | 见 V1.4.8 15.1 |
| `stop_update_atr_15m` | 同名字段 | 见 V1.4.8 16.1 |
| `invalidation_atr_value` | 待策略裁定 | 见 27.6 |
| `manual_boundary_override` | SACW 本地扩展 | 见 21.2；不回写 V1.4.8 策略字段 |

API 契约与数据库列名必须使用 V1.4.8 字段名；SACW 展示别名只在前端标签层使用，不得进入事件载荷或黄金样本快照。

---

# 34. 继承与冻结声明

V1.1.2 修改的章节（相对 V1.1.1）：

- 文档头与 V1.1.2 修订摘要（新增）；
- 8.1（补入 `zone_min_half_width_ticks`、`zone_max_age_weeks`）；
- 13.1（新增第 8 项跨文档核对规则）；
- 16、16.1（V11-P0-01 移除 ATR_MA22）；
- 17.1、17.2、17.3（ATR_MA22 改为 `SPEC_AMBIGUITY` 并暂停展示）；
- 21.2、21.4（引用两个补入的 Zone 参数）；
- 25.4（敏感性分析覆盖面要求）；
- 27.5（新增白名单比对与遗漏声明条款）；
- 29（UI-002 改写，新增 UI-022）。

以下章节继续按 SACW V1.1 / V1.1.1 / V1.0 执行，本修订包未修改：

- 第 1～15 章（除 3.1、16.1 已覆盖）
- 第 24 章（快照查看页面，字段名按第 33 章映射）
- 第 26 章（Lightweight Charts MVP 交互边界）
- 第 27.1～27.5（除 27.4 已覆盖，27.6 新增）
- 第 28 章（术语与导航最终清单）
- 第 30、31 章

本修订包中出现的编号以本文件内容为准，与 SACW V1.1 原文冲突时以本文件为准。

**V1.1.2 冻结结论：** 本文件可以替代 SACW V1.1 / V1.1.1 作为前端 MVP 的实现基线。

V1.1.2 已消除与 V1.4.8 的唯一明确冲突：`ATR_MA22` 与其引用的「V1.4.8 2.3 节」在 V1.4.8 中均不存在，现已改为 `SPEC_AMBIGUITY` 并暂停展示（17.1、17.2、17.3、UI-022）。同时补齐两个漏列的 Zone RESEARCH 参数（`zone_min_half_width_ticks`、`zone_max_age_weeks`），使 8.1 白名单与 V1.4.8 第 19 章的 36 项 RESEARCH 参数逐一对应、初始值一致。

仍处于阻塞的两项，均需策略负责人裁定，SACW 不得自行解释：

- P0-E 的 PB-12/PB-13：N 结构失效 ATR 时点未定义，保持 `BLOCKED_BY_SPEC_AMBIGUITY`。
- `ATR_MA22`：在 V1.4.8 第 4.1 节补定该指标并明确分类前，保持 `SPEC_AMBIGUITY`，不展示、不计算、不进入搜索空间。

开发不得在编码中自行改变 V1.4.8 状态定义、ATR 快照时点、信号触发顺序、执行时间边界或参数分类。每次升版必须按 13.1 第 8 项完成跨文档核对，并按 27.5 产出白名单比对表。
