# SPEC-V148-05｜Swing 结构与保护点

> **文档状态：** 扩充结构化规格；本文件属于唯一权威规格的一章。原始规格仅作归档迁移来源。

## 1. 文档元数据

- 文档 ID：`SPEC-V148-05`（章节文档 ID，不是项目 REQ ID）
- 版本：V1.4.8 扩充版
- 原规格章节：第 5 章
- 状态：NORMATIVE，除显式 OPEN_DECISION 外按本章规范执行

## 2. 目标与范围

- **目标：** 规范 ETH-USDT-SWAP 多周期趋势策略的“Swing 结构与保护点”行为与数据契约。
- **范围：** 本章原规则及已确认补充要求。
- **非目标：** 不推断未确认的策略收益或运行行为。

## 3. 规范性要求

原文条款与本扩充版补充要求共同构成规范；发生冲突时本扩充版的明确决定优先，其他冲突登记 OPEN_DECISIONS，不猜测。

### 3.1 原规格条款（迁移保留）

# 5. Swing 结构与保护点

## 5.1 基础结构

多头结构：

- HH：新 SwingHigh 高于前一个 SwingHigh。
- HL：新 SwingLow 高于前一个 SwingLow。

空头结构：

- LH：新 SwingHigh 低于前一个 SwingHigh。
- LL：新 SwingLow 低于前一个 SwingLow。

## 5.2 ProtectedLow

`ProtectedLow` 是当前有效多头趋势中，最近一个已经确认并承担趋势保护作用的 HL SwingLow。

初始化：

- 首次确认 HH + HL 后，将构成该 HL 的 SwingLow 设为 ProtectedLow。
- 必须保存 `protected_low_swing_id`。

更新：

- 后续出现新的有效 HH + HL 结构后，更新为新结构中承担保护作用的 HL。
- 只能使用已确认 SwingLow。
- 不允许使用尚未确认的候选低点。

失效：

`Close_TF < ProtectedLow - protected_break_buffer_atr × ATR_TF`

失效后：

- 进入对应周期的 TRANSITION 或结构失效状态。
- 旧 ProtectedLow 不得复活。
- 必须等待新的多头结构确认，才能建立新的 ProtectedLow。

## 5.3 ProtectedHigh

`ProtectedHigh` 是当前有效空头趋势中，最近一个已经确认并承担趋势保护作用的 LH SwingHigh。

初始化：

1. 确认一个 LH SwingHigh。
2. 随后确认一个 LL SwingLow。
3. 该 LH SwingHigh 成为保护此次 LL 延续结构的 ProtectedHigh。
4. 保存 `protected_high_swing_id`。

更新：

1. 在当前空头结构中，先确认新的 LH SwingHigh。
2. 随后确认新的 LL SwingLow。
3. 只有新的 LH 与后续 LL 共同确认后，才将该 LH 更新为 ProtectedHigh。
4. 新 ProtectedHigh 必须严格低于旧 ProtectedHigh：`NewProtectedHigh.price < OldProtectedHigh.price`。
5. 如果价格相等，不更新 ProtectedHigh，不更换原 `protected_high_swing_id`；相等 SwingHigh 仍可保留为普通 SwingPoint。
6. 只允许向下更新，不允许向上更新。

失效：

`Close_TF > ProtectedHigh + protected_break_buffer_atr × ATR_TF`

失效后：

- 当前空头保护结构失效。
- 旧 ProtectedHigh 不得复活。
- 尚未确认新的 LH + LL 之前，不得重新建立 ProtectedHigh。
- 旧 ProtectedHigh 永久失效，不得复活。
- 各周期状态映射固定如下：

| 周期 | ProtectedHigh 失效后的状态 |
|---|---|
| 1MONTH | UNKNOWN |
| 1W | TRANSITION |
| 1D | TRANSITION |
| 4H | TRANSITION |
| 1H | TRANSITION |

- 在重新确认完整 LH + LL 之前，不得重新建立 ProtectedHigh。
- 不得仅凭价格重新跌回旧 ProtectedHigh 下方就恢复旧空头状态。

ProtectedHigh 和 ProtectedLow 使用相同的保护缓冲参数，但分别独立维护。

## 5.4 PullbackOriginHigh

`PullbackOriginHigh` 是当前有效多头结构中，回撤开始前的最高确认 SwingHigh。

必须保存：

- `pullback_origin_swing_id`
- `pullback_origin_price`
- `pullback_started_at`

回撤开始后，不允许使用后续新高覆盖当前回撤起点。

只有当前回撤结束、形成新的有效趋势阶段后，才允许建立新的回撤起点。

## 5.5 多头 N 结构

结构顺序：

`L1 → H1 → L2 → H2`

要求：

- 时间顺序成立。
- `L2 > L1`。
- `H2 > H1`。

不要求 `L2 > H1`。

回撤比例：

`Retracement = (H1 - L2) / (H1 - L1)`

结构失效：

`Close_TF < L2 - n_structure_break_buffer_atr × ATR_TF`

其中 `n_structure_break_buffer_atr` 为 RESEARCH 参数，初始值 0.1。本策略中该参数的交易性失效判定仅适用于 15M 多头 N 结构。4H、1H 的方向状态和保护点由第 9 章状态机定义；即使研究模块计算 4H/1H N 结构，也仅作为 `RESEARCH_ONLY` 结构研究对象，不得直接参与 Setup、Signal、持仓止损或交易性结构失效判定，不得与 15M 共用该交易参数。

只使用收盘价判断，单纯影线刺破不构成结构失效。

结构失效后，旧结构不可恢复，后续新结构必须分配新的 `structure_id`。依赖该结构且尚未触发的 Setup/Signal 候选必须按其生命周期规则失效；已成交仓位按结构失效退出规则处理。

---


### 3.2 已确认补充要求

- **SPEC-V148-05-ADD-01：** 结构对象记录全部构成 SwingPoint IDs、confirmed_at、所属 structure_id、周期、状态、配置版本；结构确认后冻结成员关系。按 Swing 完成确认时序选首个有效候选；结构明确失效前不得分配新 ID。失效传播遵循第 24 章统一表。

## 4. 数据与状态契约

- 原文定义见第 3.1 节；新增约束见第 3.2 节。
- 本章决策依赖章节：[04](./04-指标与 ZigZag.md)、[06](./06-Zone 支撑阻力区域.md)、[08](./08-宏观趋势状态机.md)、[09](./09-4H 与 1H 状态机.md)、[10](./10-Setup 生命周期.md)、[11](./11-15M 信号系统.md)、[15](./15-止损与可执行价格.md)、[20](./20-核心数据结构.md)。
- 所有有损失风险的行为不得由未决规则推导；未决项见 [OPEN_DECISIONS.md](./OPEN_DECISIONS.md)。

## 5. 验收要求

- 本章原有规则、公式、状态转换和适用样例均须测试覆盖。
- 新增条款须有可追溯断言、黄金样本或审计证据。
- 整体冻结门槛见 [24](./24-冻结条件.md)，数据验收见 [07](./07-数据标注与黄金样本.md) 与 [21](./21-回测与验证规范.md)。

## 6. 依赖与交叉引用

- 相关章节：[04](./04-指标与 ZigZag.md)、[06](./06-Zone 支撑阻力区域.md)、[08](./08-宏观趋势状态机.md)、[09](./09-4H 与 1H 状态机.md)、[10](./10-Setup 生命周期.md)、[11](./11-15M 信号系统.md)、[15](./15-止损与可执行价格.md)、[20](./20-核心数据结构.md)。
- 项目级需求追踪使用 `REQ-NNN`，不得与 `SPEC-V148-NN` 混用。

## 7. 未决项

- 业务选择集中登记于 [OPEN_DECISIONS.md](./OPEN_DECISIONS.md)；未决项不构成批准规则。
