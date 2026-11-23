# SPEC-V148-18｜REQUIRED 配置与启动门禁

> **文档状态：** 扩充结构化规格；本文件属于唯一权威规格的一章。原始规格仅作归档迁移来源。

## 1. 文档元数据

- 文档 ID：`SPEC-V148-18`（章节文档 ID，不是项目 REQ ID）
- 版本：V1.4.8 扩充版
- 原规格章节：第 18 章
- 状态：NORMATIVE，除显式 OPEN_DECISION 外按本章规范执行

## 2. 目标与范围

- **目标：** 规范 ETH-USDT-SWAP 多周期趋势策略的“REQUIRED 配置与启动门禁”行为与数据契约。
- **范围：** 本章原规则及已确认补充要求。
- **非目标：** 不推断未确认的策略收益或运行行为。

## 3. 规范性要求

原文条款与本扩充版补充要求共同构成规范；发生冲突时本扩充版的明确决定优先，其他冲突登记 OPEN_DECISIONS，不猜测。

### 3.1 原规格条款（迁移保留）

# 18. REQUIRED 配置与启动门禁

## 18.1 必须配置的策略参数

以下参数缺失时，不允许启动有效回测、Paper 或 Live：

| 配置项 | 说明 |
|---|---|
| `risk_per_trade_pct` | 单笔风险预算占账户净值比例 |
| `max_notional_exposure` | 最大名义敞口 |
| `max_margin_usage_pct` | 最大保证金使用比例 |
| `leverage` | 策略允许使用的杠杆上限 |
| `maker_fee_rate` | Maker 费率及版本 |
| `taker_fee_rate` | Taker 费率及版本 |
| `funding_dataset` | 回测区间覆盖所需的历史 Funding 数据集 |
| `contract_multiplier` | 合约乘数 |
| `tick_size` | 最小价格变动单位 |
| `lot_size` | 下单数量步长 |
| `min_quantity` | 最小下单数量 |
| `max_quantity` | 最大下单数量 |
| `initial_capital` | 回测初始资金或 Paper/Live 账户净值来源 |
| `cost_model_version` | 成本模型版本 |
| `instrument_metadata_version` | 合约元数据版本 |
| `slippage_model_version` | 滑点模型版本 |

以下参数属于 RESEARCH，可使用第 19 章研究初始值，但每次运行必须记录实际生效值：

- `fixed_stop_pct`
- `hard_risk_budget_multiple`
- `max_execution_deviation_atr`
- `max_execution_gap_atr`
- `max_actual_fill_deviation_atr`
- `min_trigger_swing_atr`

必须进行合法性校验：

- `risk_per_trade_pct > 0`
- `max_notional_exposure > 0`
- `0 < max_margin_usage_pct <= 1`
- `leverage > 0`
- `initial_capital > 0`
- 费率、合约元数据、Funding 数据集和版本标识必须有效。
- 所有 ATR 倍数参数必须大于或等于 0。
- `fixed_stop_pct > 0` 且小于 1。
- `hard_risk_budget_multiple >= 1`。

REQUIRED 表示必须显式提供，不得因为参数表展示了某个研究初始值就自动视为已配置。RESEARCH 参数允许使用初始值，但必须在报告中记录实际值。
## 18.2 必须加载的交易所元数据

| 元数据 | 来源 |
|---|---|
| `contract_multiplier` | 交易所 Instrument |
| `tick_size` | 交易所 Instrument |
| `lot_size` | 交易所 Instrument |
| `min_quantity` | 交易所 Instrument |
| `max_quantity` | 交易所 Instrument |
| `maker_fee_rate` | 费率配置 |
| `taker_fee_rate` | 费率配置 |
| Funding 数据 | 历史 Funding 数据集 |

以上数据必须保存版本、生效时间和来源。`REQUIRED` 与 `METADATA` 是两个不同维度：REQUIRED 表示该值必须由运行配置显式提供、缺失即拒绝启动；METADATA 表示该值的权威来源和版本管理方式。Maker/Taker 费率既是 REQUIRED（必须显式配置），也是 METADATA（必须记录来源、版本和生效时间），两者不冲突。

## 18.3 启动门禁

以下任一情况发生时，拒绝启动有效策略：

1. REQUIRED 策略参数缺失。
2. `min_anchor_count < 2` 或其他 FIXED 规则被配置覆盖。
3. 初始资金或账户净值不可用。
4. 成本模型、滑点模型或合约元数据版本未指定。
5. 合约乘数缺失。
6. Tick Size、Lot Size、最小数量或最大数量缺失。
7. Maker/Taker 费率缺失。
8. Funding 数据集缺失、不覆盖测试区间或无法验证 Hash。
9. 账户杠杆或保证金配置与策略配置冲突。
10. Instrument ID 与配置的交易标的不一致。

启动失败必须返回明确的 `CONFIG_VALIDATION_ERROR`，并列出所有缺失项和非法值。RESEARCH 参数使用默认初始值时，必须将实际生效值写入运行配置快照和回测报告。
---


### 3.2 已确认补充要求

- **SPEC-V148-18-ADD-01：** 运行模式（回测/Paper/Live）必须显式配置；运行模式必需参数不得从另一模式隐式继承。未确认的合约类型、币种换算源、数据完整性不足或必需运行参数缺失时拒绝启动。Live 参数见 OD-01。

## 4. 数据与状态契约

- 原文定义见第 3.1 节；新增约束见第 3.2 节。
- 本章决策依赖章节：[14](./14-交易成本与合约元数据.md)、[19](./19-参数配置表.md)、[21](./21-回测与验证规范.md)。
- 所有有损失风险的行为不得由未决规则推导；未决项见 [OPEN_DECISIONS.md](./OPEN_DECISIONS.md)。

## 5. 验收要求

- 本章原有规则、公式、状态转换和适用样例均须测试覆盖。
- 新增条款须有可追溯断言、黄金样本或审计证据。
- 整体冻结门槛见 [24](./24-冻结条件.md)，数据验收见 [07](./07-数据标注与黄金样本.md) 与 [21](./21-回测与验证规范.md)。

## 6. 依赖与交叉引用

- 相关章节：[14](./14-交易成本与合约元数据.md)、[19](./19-参数配置表.md)、[21](./21-回测与验证规范.md)。
- 项目级需求追踪使用 `REQ-NNN`，不得与 `SPEC-V148-NN` 混用。

## 7. 未决项

- 业务选择集中登记于 [OPEN_DECISIONS.md](./OPEN_DECISIONS.md)；未决项不构成批准规则。
