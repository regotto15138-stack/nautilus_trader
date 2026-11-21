# ETH-USDT-SWAP 多周期趋势策略开发规格

**版本：V1.4.8**  
**基线版本：V1.4.6**  
**适用框架：NautilusTrader 2.0.0rc8**  
**交易标的：ETH-USDT-SWAP.OKX**  
**策略类型：多周期趋势回撤延续策略**  
**文档状态：V1.4.8 冻结候选版；P0-D / P0-E 规格基线已修订，P1-A 须满足人工黄金样本验收门槛后准入**

---

# 1. 版本修订说明

V1.4.8 以 V1.4.7 为完整基线，保留原有多周期架构、指标定义、Zone、状态机、Setup、Signal、执行和风险框架。本版重点修复 Signal 部分成交终态、ATR 快照确定性、持仓权限定义、风险减仓口径、初始止损可执行性和黄金样本覆盖范围，并补充 Fill 级审计与相关边界测试；不以附录替代正文定义。

V1.4.8 修订重点：

1. Signal 一旦有实际成交且剩余订单终止，统一进入 PARTIALLY_EXECUTED；EXPIRED/CANCELLED 仅适用于零成交 Signal。
2. 明确 15M 信号决策 ATR、Pullback 阶段 ATR、TriggerSwing ATR、初始止损 ATR 和后续止损更新 ATR 的快照时点及用途。
3. 新增 CanOpen 与 CanHold 两种权限，风险恢复使用 CanHold，不再将新开仓权限混作持仓许可。
4. 风险预算减仓使用不含已发生入场费用的 CurrentRiskPerUnit。
5. 初始及部分成交后重算止损必须低于当前可执行退出价格，否则进入紧急退出或风险异常。
6. P0-E 黄金样本范围扩展至 PB-01 至 PB-51。
7. ExecutionRecord 增加 FillRecord 列表，保存每笔成交独立偏差；订单级偏差字段定义为累计最大不利偏差。
8. 区分尚未生效的 StopCandidate 紧急市价退出与已生效保护性止损单的触发模型。
9. 增加浮点边界容差、ATR 无效处理、风险恢复计数起点及 Fill 级审计测试。
10. 明确 Zone 可信快照必须包含全部有效锚点及 confirmed_at，补充回撤位置参数命名和 TriggerSwing 偏低统计窗口。

V1.4.7 修订重点（本版继续继承）：

1. PULLBACK_CONTINUATION 的观察区位置校验改为针对 PullbackLow，不再要求 HigherLow 靠近观察区。
2. PullbackLow 更新时，旧 TriggerSwingHigh 与 HigherLow 及其引用字段全部作废。
3. Signal.trigger_swing_id 改为可空，并区分 BREAKOUT_CONTINUATION 与 PULLBACK_CONTINUATION 的字段语义。
4. 风险恢复的 4H 连续 TREND_UP 确认数恢复为 2 根完成 Bar。
5. 新增 `min_trigger_swing_atr`，约束 TriggerSwingHigh 相对 PullbackLow 的最小反弹幅度。
6. Zone Min Anchors 固定为至少 2 个不同 SwingPoint，启动门禁拒绝小于 2 的配置。
7. Setup1H 创建时明确要求父 Setup4H ACTIVE 且当前宏观方向权限仍允许。
8. Signal 增加 `partially_filled`，区分尚未成交与部分成交但剩余订单仍有效。
9. `n_structure_break_buffer_atr` 的交易用途限定为 15M N 结构；4H/1H N 结构仅可作为研究对象。
10. 补充严格 3M 时序、风险恢复计数、触发幅度、成交延迟 ATR 偏差等黄金样本和统计要求。
11. 明确风险预算减仓回测成交价、REQUIRED 与 METADATA 的关系及 RESEARCH 参数实际生效值记录要求。

V1.4.6 已完成的基线修订（V1.4.7 / V1.4.8 继续继承）：

1. 15M 不维护独立 ProtectedLow；`PreviousProtectedLow` 统一引用当前有效 15M N 结构的 `L2`。
2. 补全实际成交偏差计算、超限事件、剩余订单撤销和实际风险预算联动。
3. 固定 15M `TriggerSwingHigh` 的选择规则，并定义 PullbackLow 更新时旧触发点失效。
4. 新增 `n_structure_break_buffer_atr`，统一参数化 N 结构失效缓冲。
5. 明确 1H PULLBACK 的 ProtectedLow 公式、Setup4H 宽度引用和 Signal 字段。
6. 统一 REQUIRED / RESEARCH 参数分类，避免“必须配置”与“自动默认值”冲突。
7. 明确 Signal 候选拒绝不是正式 Signal 状态。
8. 明确 3M 信号创建时正在形成的 SwingLow 不参与执行确认，并纳入黄金样本。
9. 明确移动止损从入场后的下一根完整 15M Bar 开始统计。
10. 补全风险预算超限减仓公式、风险恢复计数和保护性止损数量同步。
11. 明确 ProtectedHigh 相等高点、失效后各周期状态映射。
12. 补全 P0-E 黄金样本和 P1-A 冻结准入条件。

V1.4.7 中未被 V1.4.8 明确修改的规则继续有效；V1.4.7 已继承的 V1.4.6 / V1.4.5 规则亦继续有效。所有时间、价格、结构、状态和参数均以本版正文为准。

---

# 2. 系统总体架构

## 2.1 周期配置

系统使用一个统一的 `TimeframeEngine` 实现，创建七个独立实例。

| 周期 | 主要职责 | 是否允许产生入场信号 |
|---|---|---|
| 1MONTH | 宏观趋势方向 | 否 |
| 1W | 中期趋势方向 | 否 |
| 1D | 短期趋势环境 | 否 |
| 4H | 回撤结构与支撑区域 | 否 |
| 1H | 回撤结束与反转候选 | 否 |
| 15M | 核心 N 结构与入场信号 | 是 |
| 3M | 入场执行确认 | 否 |

各周期拥有独立的 ATR、SMA、ZigZag、SwingPoint、结构状态、Zone、Bar 缓存和配置版本。

共享算法实现，不共享周期状态。

## 2.2 策略执行链

`MarketContext → Setup4H → Setup1H → Signal15M → Execution3M → RiskManager`

- `MarketContext`：判断宏观趋势是否允许做多。
- `Setup4H`：识别 4H 趋势回撤和支撑区域。
- `Setup1H`：识别 1H 回撤结束候选。
- `Signal15M`：识别具体入场 N 结构。
- `Execution3M`：确认入场时机。
- `RiskManager`：仓位、止损、风险升级和异常处置。
- `PositionManager`：根据实际成交管理持仓。

3M 不得改变宏观方向，不得独立创建策略信号。

---

# 3. 时间与 Bar 处理规范

## 3.1 时间标准

全部内部时间使用 UTC。

Bar 区间采用左闭右开：

`[open_time, close_time)`

周期定义：

- 1W：周一 00:00 UTC 开始。
- 1MONTH：自然月开始。
- 其他周期：按照 UTC 时间边界聚合。

## 3.2 BarIdentity

```python
@dataclass(frozen=True)
class BarIdentity:
    instrument_id: str
    timeframe: str
    open_time: datetime
    close_time: datetime
    is_closed: bool
    source: str
    sequence: int
```

## 3.3 完成 Bar 原则

所有策略状态只能使用已完成 Bar 更新。

禁止：

- 使用未完成 Bar 产生 SwingPoint。
- 使用未完成 Bar 确认 N 结构。
- 使用未完成 Bar 更新趋势状态。
- 使用未来 Bar 数据判断当前信号。
- 在同一时间戳内使用尚未发生的执行价格。

周期聚合顺序：

1. 更新低周期完成 Bar。
2. 聚合高周期 Bar。
3. 更新各周期指标和结构。
4. 生成统一 `MarketSnapshot`。
5. 执行状态机。
6. 评估信号。
7. 生成订单或风险事件。

## 3.4 因果性约束

例如：

- 15M Bar `[12:00,12:15)` 在 12:15 完成。
- 3M Bar `[12:15,12:18)` 从 12:15 开始。

15M 信号只能在 12:15 收盘后生成，不能回填到 12:15 的 3M 开盘成交。

订单最早只能在满足订单提交时间约束的后续执行事件成交。

---

# 4. 指标与 ZigZag

## 4.1 基础指标

| 指标 | 定义 |
|---|---|
| ATR | Wilder ATR，周期 14 |
| SMA | 简单移动平均，周期 22 |
| ZigZag | ATR 动态反转阈值 |

所有周期独立计算。

## 4.2 ZigZag 规则

使用统一 `ZigZagEngine`，每个周期独立实例。

初始反转参数：

`k = 2.0`

该值为研究初值，不是已验证的最优参数。

高点候选反转：

`Close <= CandidateHigh - k × CandidateATR`

低点候选反转：

`Close >= CandidateLow + k × CandidateATR`

ATR 使用候选极值产生时的 ATR 快照；候选极值更新时同步更新 ATR 快照。

同一根 Bar 的处理顺序：

1. 更新候选极值。
2. 更新候选极值对应的 ATR。
3. 使用 Bar Close 判断反转。
4. 满足反转条件时确认此前候选 SwingPoint。

确认 SwingPoint 的 Bar 不允许同时初始化下一个方向的候选点；下一根 Bar 才开始新候选。

## 4.3 SwingPoint

```python
@dataclass(frozen=True)
class SwingPoint:
    point_id: str
    timeframe: str
    direction: str
    price: float
    occurred_at: datetime
    confirmed_at: datetime
    atr_snapshot: float
    source_bar_id: str
    config_version: str
    sequence: int
```

约束：

- `confirmed_at >= occurred_at`。
- 已确认 SwingPoint 不可修改。
- SwingPoint 必须记录来源 Bar。
- 增量计算、批量计算和历史回放必须产生相同结果。

---

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

# 6. Zone 支撑阻力区域

## 6.1 Zone 类型

- SUPPORT
- RESISTANCE

同一 Zone 只能由同周期、同方向的确认 SwingPoint 构成。

- SUPPORT：SwingLow 聚类。
- RESISTANCE：SwingHigh 聚类。

禁止跨周期合并。

## 6.2 Zone 状态

| 当前状态 | 事件 | 新状态 |
|---|---|---|
| CREATED | 满足最小锚点数量 | ACTIVE |
| ACTIVE | 价格首次有效测试 | TESTED |
| ACTIVE | 收盘价直接有效突破 | BROKEN |
| TESTED | 再次有效测试 | TESTED |
| TESTED | 收盘价有效突破 | BROKEN |
| CREATED | 锚点过期或结构失效 | INVALIDATED |
| ACTIVE | 锚点过期或结构失效 | INVALIDATED |
| TESTED | 锚点过期或结构失效 | INVALIDATED |

`ACTIVE → BROKEN` 必须支持，不要求先进入 TESTED。

BROKEN 优先于 TESTED；同一 Bar 同时满足测试和突破条件时，判定为 BROKEN。

BROKEN 和 INVALIDATED 均为终态。

## 6.3 CREATED 聚类规则

新确认 SwingPoint 首先搜索同周期、同类型的：

- CREATED
- ACTIVE
- TESTED

Zone。

禁止合并到 BROKEN 或 INVALIDATED Zone。

候选 Zone 必须满足：

`abs(new_anchor_price - zone.center) <= merge_distance_atr × ATR_TF`

同时必须满足聚类最大直径：

`max(anchor_prices) - min(anchor_prices) <= max_cluster_width_atr × ATR_TF`

多个 Zone 均符合时：

1. 选择新锚点到 Zone 中心距离最小者。
2. 距离相同，选择创建时间最早者。
3. 仍相同，选择 `zone_id` 字典序最小者。

不存在符合条件的 Zone 时，创建新的 CREATED Zone。

## 6.4 Zone 几何计算

设锚点价格集合为：

`P = {p1, p2, ..., pn}`

中心：

`center = median(P)`

半宽：

`half_width = max(min_half_width_ticks × tick_size, zone_half_width_atr × ATR_TF, (max(P)-min(P))/2)`

上下边界：

`lower = center - half_width`

`upper = center + half_width`

**设计说明：**

`(max(P)-min(P))/2` 用于确保 Zone 覆盖所有有效锚点。因此当锚点分散程度较大时，实际 Zone 半宽可能明显大于 `zone_half_width_atr × ATR_TF`。

这不是计算错误，而是当前 Zone 定义的设计结果。

`max_cluster_width_atr` 与 `zone_half_width_atr` 必须联合进行敏感性测试，防止 Zone 过宽影响 Setup 和 Signal 的定位质量。

## 6.5 ACTIVE 条件

最小锚点数量为 FIXED 规则：

`min_anchor_count = 2`

必须来自两个不同 SwingPoint。配置值不得小于 2；小于 2 属于非法配置，启动门禁必须拒绝。该规则不是可放宽至单点的 RESEARCH 参数。

满足聚类最大直径约束后，Zone 从 CREATED 进入 ACTIVE。

## 6.6 Zone 测试

定义：

`test_tolerance = zone_test_tolerance_atr × ATR_TF`

SUPPORT 测试：

- Bar Low 进入 `[lower-test_tolerance, upper+test_tolerance]`。
- Bar Close 不低于 `lower-test_tolerance`。
- Bar Close 高于 Zone center。

RESISTANCE 测试：

- Bar High 进入 `[lower-test_tolerance, upper+test_tolerance]`。
- Bar Close 不高于 `upper+test_tolerance`。
- Bar Close 低于 Zone center。

满足条件时进入或保持 TESTED。

## 6.7 Zone 突破

SUPPORT：

`Close < lower - break_buffer_atr × ATR_TF`

RESISTANCE：

`Close > upper + break_buffer_atr × ATR_TF`

满足条件立即进入 BROKEN。

## 6.8 Zone 年龄

`zone.max_age_weeks = 52`

年龄按每个锚点的 `confirmed_at` 计算。

超过最大年龄的锚点从当前有效锚点集合移除。

如果剩余有效锚点数量低于 `min_anchor_count`，Zone 进入 INVALIDATED。

## 6.9 Zone 版本

以下变化必须递增 `zone_version`：

- 锚点增加或移除。
- 中心变化。
- 上下边界变化。
- 状态变化。

每个版本保存不可变快照。

## 6.10 Zone 版本更新与 Setup

如果 Setup 尚未产生 15M Signal：

- Zone 版本发生有效变化时，重新计算 Setup 观察区。
- 同步更新 `observation_zone_version`。
- 同步更新 `observation_lower` 和 `observation_upper`。
- 生成 `SETUP_ZONE_REVISED` 事件。

如果 Setup 已经产生 Signal：

- Signal 使用创建时的 Zone 快照。
- 不得静默修改 Signal 的观察区。
- Zone 后续进入 BROKEN 或 INVALIDATED 时，仍按失效传播规则处理。
- 普通边界调整不追溯修改已经创建的 Signal。

---

# 7. 数据标注与黄金样本

## 7.1 人工标注必须前置

P1-A 状态机实现前，必须先完成冻结历史数据的人工标注。

标注对象：

- 1MONTH：UPTREND、WEAKENING、DOWNTREND、UNKNOWN。
- 1W：BULLISH、WEAKENING、BEARISH、TRANSITION、UNKNOWN。
- 1D：BULLISH、PULLBACK、BEARISH、TRANSITION、UNKNOWN。
- 4H：TREND_UP、TREND_DOWN、PULLBACK、RANGE、TRANSITION、UNKNOWN。
- 1H：BULLISH、BEARISH、PULLBACK、RANGE、REVERSAL_CANDIDATE、TRANSITION、UNKNOWN。

每条标注包含：

- Bar 时间。
- 周期。
- 人工状态。
- 关键 SwingPoint。
- ProtectedLow。
- ProtectedHigh。
- PullbackOriginHigh。
- 状态转换原因。
- 标注版本。

## 7.2 工程验收标准

以下是初始工程验收门槛，不是策略收益指标：

| 指标 | 初始门槛 |
|---|---:|
| Overall Macro-F1 | ≥ 0.85 |
| 各状态 Recall | ≥ 0.80 |
| 状态转换时间误差 | ±1 根周期 Bar |
| 转换识别准确率 | ≥ 90% |

某个状态样本数量不足时，必须单独报告样本数量，不得只报告总体准确率。

## 7.3 黄金样本覆盖

至少覆盖：

- 趋势延续。
- 趋势回撤。
- 趋势中整理。
- 真正震荡区间。
- 趋势反转。
- ProtectedLow 失效。
- ProtectedHigh 失效。
- Zone 直接突破。
- Zone 测试后突破。
- 快速突破。
- 缺失历史数据。
- 价格跳空。
- Funding 结算边界。
- 信号前低点不得用于 3M 执行确认。
- 突破 Bar 必须晚于信号后 SwingHigh 确认。
- Signal 创建后无法形成有效 SwingHigh 的快速突破行情。

V1.4.8 必须额外覆盖以下回归用例：

| ID | 场景 | 预期结果 |
|---|---|---|
| PB-01 | PullbackLow 高于当前 15M NStructure.L2 | 允许继续识别回撤延续 |
| PB-02 | PullbackLow 等于 NStructure.L2 | 拒绝 |
| PB-03 | PullbackLow 低于 NStructure.L2 | 当前回撤候选失效 |
| PB-04 | PullbackLow 后出现多个 SwingHigh | 选择第一个满足确认时序的 SwingHigh |
| PB-05 | TriggerSwing 确认后出现更高 SwingHigh | 不替换 TriggerSwing |
| PB-06 | PullbackLow 更新为更低但仍高于 L2 的低点 | 原 TriggerSwingHigh 与 HigherLow 全部作废并重新等待；新 HigherLow 必须晚于新 TriggerSwingHigh 确认 |
| PB-07 | PullbackLow 跌破或等于 NStructure.L2 | 回撤候选失效 |
| PB-08 | 实际成交偏差超过阈值 | 记录 FILL_DEVIATION_BREACH |
| PB-09 | 成交偏差超限且存在剩余入场数量 | 取消剩余入场订单 |
| PB-10 | 成交偏差超限但实际风险未超预算 | 管理已有仓位，不强制平仓 |
| PB-11 | 成交偏差超限且实际风险超预算 | 进入 ACTUAL_RISK_BUDGET_BREACH |
| PB-12 | N 结构跌破参数化缓冲 | N 结构失效 |
| PB-13 | 修改 n_structure_break_buffer_atr | 失效结果随参数变化 |
| PB-14 | Signal 创建时 3M SwingLow 正在形成 | 不参与执行确认 |
| PB-15 | Signal 创建后才开始形成 3M SwingLow | 满足其余条件时可参与执行确认 |
| PB-16 | 12:07 入场，12:00–12:15 15M Bar | 不参与移动止损最高价统计 |
| PB-17 | 部分成交后更新保护性止损 | StopQuantity 等于 PositionQuantity |
| PB-18 | 连续 3 根 1H Bar 均为 BULLISH | 满足 1H 恢复计数 |
| PB-19 | 恢复计数期间出现非 BULLISH 状态 | 计数重置 |
| PB-20 | 风险恢复后候选止损低于当前止损 | 忽略，不下移 |
| PB-21 | ProtectedHigh 新候选与旧值相等 | 保留旧 ProtectedHigh ID |
| PB-22 | ProtectedHigh 失效 | 各周期按映射表进入 UNKNOWN/TRANSITION |
| PB-23 | PullbackLow 位于观察区内，HigherLow 略高于观察区上沿 | 位置校验通过；HigherLow 只校验高于 PullbackLow 与 L2 |
| PB-24 | PullbackLow 更新后仍高于 L2，旧 HigherLow 已存在 | 旧 TriggerSwingHigh 与 HigherLow 全部清空；新 HigherLow 确认时间必须晚于新 TriggerSwingHigh 确认时间 |
| PB-25 | TriggerSwingHigh 相对 PullbackLow 的反弹幅度低于 0.3 ATR | 不得选为 TriggerSwingHigh，继续等待满足阈值的后续 SwingHigh |
| PB-26 | TriggerSwingHigh 相对 PullbackLow 的反弹幅度恰好达到最小阈值 | 满足幅度边界，若时序条件成立则可选为 TriggerSwingHigh |
| PB-27 | 1H 连续 2 根 BULLISH 后第 3 根为 PULLBACK | 1H 恢复计数归零，不得解除风险升级 |
| PB-28 | 4H 仅连续 1 根 TREND_UP，其他恢复条件满足 | 不得解除风险升级 |
| PB-29 | 4H 连续 2 根 TREND_UP，且其他恢复条件满足 | 4H 恢复计数通过；仍须满足全部其他恢复条件 |
| PB-30 | 4H 连续 1 根 TREND_UP 后出现非 TREND_UP | 4H 恢复计数归零 |
| PB-31 | Signal 创建前已发生、创建后才确认的 3M SwingLow | 不得用于本次执行确认 |
| PB-32 | ACTIVE Signal 尚未成交 | `partially_filled = False` |
| PB-33 | ACTIVE Signal 已部分成交且剩余订单仍有效 | 状态仍为 ACTIVE，`partially_filled = True` |
| PB-34 | Zone Min Anchors 配置为 1 | 启动门禁以配置非法拒绝 |
| PB-35 | 4H/1H 研究 N 结构失效，但对应周期状态机条件未触发失效 | 不得直接改变 Setup、Signal 或持仓状态 |
| PB-36 | Signal 已部分成交，随后超时且剩余订单终止 | 进入 PARTIALLY_EXECUTED；原因记录为 TIMEOUT，不得进入 EXPIRED |
| PB-37 | Signal 已部分成交，随后结构/上下文/宏观权限失效或 FILL_DEVIATION_BREACH | 进入 PARTIALLY_EXECUTED；具体原因写入 remaining_order_terminal_reason |
| PB-38 | Signal 零成交后超时/结构失效 | 分别进入 EXPIRED/CANCELLED；仅适用于 filled_quantity = 0 |
| PB-39 | 回放中 ATR 更新，已保存的回撤起点/TriggerSwing/Signal 决策快照 | 历史判定不被后续 ATR 改写；同输入回放结果一致 |
| PB-40 | execution_reference_atr_15m 缺失、非有限数或小于等于 0 | 记录 INVALID_ATR，不计算偏差倍数，撤销剩余订单并进入风险异常流程 |
| PB-41 | 风险预算减仓，CurrentRiskPerUnit 含退出成本但不含已发生入场费 | 减仓量按 CurrentRiskPerUnit 计算，不重复计入沉没入场成本 |
| PB-42 | 首次成交后 InitialStop 高于或等于 ActualAverageEntryPrice / CurrentExecutablePrice | 不提交无效保护止损；取消剩余入场订单并进入紧急退出/RISK_ANOMALY |
| PB-43 | 尚未生效的 StopCandidate 在下一合格 3M Open 已被触及 | 按紧急市价退出及不利滑点处理，不套用 15.5 已生效止损单模型，不使用该 Bar Low |
| PB-44 | 风险升级触发所在 1H/4H Bar 同时满足恢复状态 | 升级触发 Bar 不计入恢复计数；从升级后的下一根完整 Bar 起算 |
| PB-45 | 1H 恢复计数连续 2 根 BULLISH 后第 3 根非 BULLISH | 1H 计数立即归零；后续必须重新累计完整 3 根 |
| PB-46 | 同一订单出现多笔 Fill，其中一笔单笔不利偏差超限但累计均价未超限 | FillRecord 保留各笔数据，订单级最大单笔偏差仍触发 FILL_DEVIATION_BREACH |
| PB-47 | Zone 可信快照只含边界/中心/锚点数量，缺少全部锚点 confirmed_at | 判定快照不可信，SnapshotStatus = INSUFFICIENT_HISTORY |
| PB-48 | CanOpen = False，但 CanHold = True 且无强制退出条件 | 已有持仓可满足风险恢复权限；禁止新开仓，不自动强平 |
| PB-49 | 同一 Signal 的 signal_decision_atr_15m 与 execution_reference_atr_15m | 必须来自同一根已完成 15M Bar 且数值相等；pullback_start/trigger_swing ATR 保留各自事件快照 |
| PB-50 | 首笔成交后 ATR 更新，后续部分成交或移动止损更新 | initial_stop_atr_15m 保持不变；每次止损更新单独记录 stop_update_atr_15m |
| PB-51 | 风险减仓时 CurrentExecutablePrice 已触及或低于 CurrentStopPrice | 不执行公式减仓，进入止损/紧急退出流程；CurrentRiskPerUnit 不得按零风险处理 |

---

# 8. 宏观趋势状态机

## 8.1 通用定义

所有状态只在对应周期完成 Bar 后更新。

各周期独立维护：

- ProtectedLow。
- ProtectedHigh。
- PullbackOriginHigh。
- 当前结构 ID。
- 当前结构确认时间。

## 8.2 1MONTH 状态

状态：

- UPTREND
- WEAKENING
- DOWNTREND
- UNKNOWN

UPTREND：

- HH + HL。
- Close 高于 SMA22。
- ProtectedLow 有效。

DOWNTREND：

- LH + LL。
- ProtectedHigh 有效。

SMA22 只作为趋势强度指标，不作为空头结构成立的必要条件。

WEAKENING：

满足任一：

1. 原有 UPTREND 中 Close 跌破 SMA22，但 ProtectedLow 尚未失效。
2. 原多头结构失去延续条件，但尚未确认完整空头结构。

不再使用“LH + LL 且 Close 高于 SMA22”作为 WEAKENING 条件。因为 LH + LL 且 ProtectedHigh 有效时，已经满足 DOWNTREND。

UNKNOWN：

- 指标预热不足。
- SwingPoint 不足。
- 结构关系无法确认。
- 数据不完整。

优先级：

`UNKNOWN → DOWNTREND → WEAKENING → UPTREND`

## 8.3 1W 状态

状态：

- BULLISH
- WEAKENING
- BEARISH
- TRANSITION
- UNKNOWN

BULLISH：

- HH + HL。
- Close 高于 SMA22。
- ProtectedLow 有效。

BEARISH：

- LH + LL。
- ProtectedHigh 有效。

SMA22 只作为趋势强度指标，不作为空头结构成立的必要条件。

WEAKENING：

- 多头结构仍有效，但 Close 跌破 SMA22；或
- 原多头结构失去延续条件，但尚未确认完整空头结构。

不再使用“LH + LL 且 Close 高于 SMA22”作为 WEAKENING 条件。

TRANSITION：

- 原有多头 ProtectedLow 失效。
- 空头结构尚未完整确认。

UNKNOWN：

- 数据或指标不足。
- 无法建立有效 Swing 结构。

优先级：

`UNKNOWN → BEARISH → TRANSITION → WEAKENING → BULLISH`

## 8.4 1D 状态

状态：

- BULLISH
- PULLBACK
- BEARISH
- TRANSITION
- UNKNOWN

BULLISH：

- HH + HL。
- Close 高于 SMA22。
- ProtectedLow 有效。

PULLBACK：

- 前态为 BULLISH。
- 当前回撤未破坏 ProtectedLow。
- 回撤幅度达到：

`PullbackOriginHigh - Close_1D >= pullback_min_atr_1d × ATR_1D`

`PullbackOriginHigh` 必须是当前 1D 有效多头结构中回撤开始前的最高确认 SwingHigh，并保存 `pullback_origin_swing_id`。

BEARISH：

- LH + LL。
- ProtectedHigh 有效。

TRANSITION：

- 原有多头 ProtectedLow 失效。
- 空头结构尚未完整确认。

UNKNOWN：

- 指标预热不足。
- 结构不足。
- 数据不完整。

## 8.5 宏观方向权限：CanOpen 与 CanHold

宏观权限必须拆分为新开仓权限和持仓许可，不得用同一个布尔值表达两种语义。

### CanOpen：新开多头权限

| 1MONTH | 1W | 1D | CanOpen |
|---|---|---|---|
| UPTREND | BULLISH | BULLISH | True |
| UPTREND | BULLISH | PULLBACK | True |
| 任意 | WEAKENING | 任意 | False |
| WEAKENING | 任意 | 任意 | False |
| DOWNTREND | 任意 | 任意 | False |
| 任意 | BEARISH | 任意 | False |
| 任意 | TRANSITION | 任意 | False |
| 任意 | 任意 | BEARISH | False |
| 任意 | 任意 | TRANSITION | False |
| 任意 | UNKNOWN | 任意 | False |
| UNKNOWN | 任意 | 任意 | False |
| 任意 | 任意 | UNKNOWN | False |

只有明确允许的组合才能创建新入场 Signal 或提交新开仓订单。

### CanHold：已有持仓许可

`CanHold` 表示当前已有多头仓位是否仍允许继续持有，不等同于 `CanOpen`。

定义：

`CanHold = PositionExists AND NOT ForcedExitTriggered`

其中 `ForcedExitTriggered` 至少包括：

- 已触发有效硬止损或有效保护性止损。
- 当前持仓所绑定的交易结构发生本规格定义的强制失效（例如 15M N 结构失效或对应 Setup/宏观规则明确规定必须退出的结构失效事件）。
- 风险异常处置规则明确要求立即全平。
- 交易所、账户或订单状态异常导致无法维持合规保护。

仅仅因为 `CanOpen = False`，不自动推导 `CanHold = False`，也不自动强制平仓。宏观 WEAKENING、BEARISH、TRANSITION 或 UNKNOWN 首先禁止新开仓；已有持仓是否退出，必须由结构失效、硬止损、风险异常或明确的强制退出规则决定。1H/4H TRANSITION 仍按 16.2 触发风险升级。

16.3 风险升级解除使用 `CanHold = True`，不得使用 `CanOpen` 作为持仓恢复条件。因此，在宏观环境禁止新开仓但尚未触发强制退出时，已有持仓可以满足 CanHold；风险恢复仍须同时满足 1H/4H 状态计数和 ProtectedLow 有效条件。

---

# 9. 4H 与 1H 状态机

## 9.1 4H 状态

- TREND_UP
- TREND_DOWN
- PULLBACK
- RANGE
- TRANSITION
- UNKNOWN

## 9.2 4H TREND_UP

要求：

- HH + HL。
- Close 高于 SMA22。
- ProtectedLow 有效。

## 9.3 4H PULLBACK

要求：

1. 前态为 TREND_UP。
2. 当前 Close 低于回撤起点 SwingHigh。
3. Close 高于 `ProtectedLow - protected_break_buffer_atr × ATR_4H`。
4. 回撤幅度达到：

`PullbackOriginHigh - Close_4H >= pullback_min_atr_4h × ATR_4H`

保存：

- `pullback_origin_swing_id`
- `protected_low_swing_id`
- `pullback_started_at`

## 9.4 4H TREND_DOWN

要求：

- LH + LL。
- ProtectedHigh 有效。

## 9.5 4H TRANSITION

原有 TREND_UP 的 ProtectedLow 被有效跌破，但尚未确认完整空头结构。

## 9.6 4H RANGE

RANGE 不得覆盖有效 TREND_UP 或 TREND_DOWN。

要求：

1. 最近至少两个确认 SwingHigh。
2. 最近至少两个确认 SwingLow。
3. 高点和低点均处于相对稳定区域。
4. 高低点时间顺序形成有效交替。
5. 区间内没有新的有效 HH + HL 或 LH + LL 趋势延续结构。
6. 价格没有有效突破区间边界。

高点稳定：

`abs(SH2 - SH1) <= range_boundary_tolerance_atr × ATR_4H`

低点稳定：

`abs(SL2 - SL1) <= range_boundary_tolerance_atr × ATR_4H`

区间边界：

- Upper = 最近两个有效 SwingHigh 的中位数。
- Lower = 最近两个有效 SwingLow 的中位数。

要求：

`Upper > Lower`

## 9.7 4H 状态优先级

1. UNKNOWN
2. TREND_DOWN
3. TRANSITION
4. PULLBACK
5. TREND_UP
6. RANGE

RANGE 只有在不存在有效趋势结构时才允许成立。

## 9.8 1H 状态

- BULLISH
- BEARISH
- PULLBACK
- RANGE
- REVERSAL_CANDIDATE
- TRANSITION
- UNKNOWN

BULLISH：

- HH + HL。
- Close 高于 SMA22。
- ProtectedLow 有效。

BEARISH：

- LH + LL。
- ProtectedHigh 有效。

SMA22 只作为趋势强度指标，不作为空头结构成立的必要条件。1H 与 1W 的空头结构定义保持一致。

PULLBACK：

- 前态为 BULLISH。
- Close 低于 PullbackOriginHigh。
- 必须满足：

`Close_1H >= ProtectedLow_1H - protected_break_buffer_atr × ATR_1H`

- 回撤幅度达到 `pullback_min_atr_1h × ATR_1H`。

REVERSAL_CANDIDATE：

1. 前态为 PULLBACK。
2. 回撤低点已经确认。
3. 回撤低点高于原 ProtectedLow。
4. 已形成新的 HL。
5. Close 突破当前 1H PULLBACK 开始后最近一个已确认的 1H SwingHigh。

第 5 项保存：

`reversal_breakout_swing_id`

该 SwingHigh 必须来自当前 PULLBACK 开始之后。

TRANSITION：

- 原 ProtectedLow 失效。
- 空头结构尚未完整确认。

RANGE：

使用与 4H 相同的区间判定原则，但 ATR、SwingPoint 和容差全部使用 1H 数据。

## 9.9 1H 状态优先级

1. UNKNOWN
2. BEARISH
3. TRANSITION
4. REVERSAL_CANDIDATE
5. PULLBACK
6. BULLISH
7. RANGE

RANGE 不得覆盖有效 BULLISH 趋势或 PULLBACK。

---

# 10. Setup 生命周期

## 10.1 Setup 状态

Setup 采用：

- ACTIVE
- EXPIRED
- INVALIDATED

**Setup 创建时直接进入 ACTIVE，不设置 CREATED 状态。**

创建条件全部通过后，分配 ID 并写入 ACTIVE 事件。

EXPIRED：

- 有效观察窗口自然结束。
- 不再创建新的子 Setup 或 Signal。
- 不自动取消已经创建且仍然有效的 15M Signal。

INVALIDATED：

- 结构被破坏。
- Zone BROKEN 或 INVALIDATED。
- ProtectedLow 被有效跌破。
- 父 Setup INVALIDATED。

INVALIDATED 必须向下游传播。

父 Setup EXPIRED 时，子 Setup EXPIRED，不得错误传播为 INVALIDATED。

## 10.2 Setup4H 创建条件

只有 4H 状态为 PULLBACK 时，才允许创建 Setup4H。

必须满足：

1. 宏观方向权限允许。
2. 4H 状态为 PULLBACK。
3. 4H 多头结构有效。
4. ProtectedLow 有效。
5. 存在 ACTIVE 或 TESTED 的 4H SUPPORT Zone。
6. Zone 未 BROKEN 或 INVALIDATED。
7. 当前回撤低点与 Zone 存在有效价格关系。
8. `Width4H >= MinimumObservationWidth4H`，具体计算见 10.5。

## 10.3 PullbackLow_4H 选择规则

定义当前 4H PULLBACK 开始时间：

`pullback_started_at`

候选 SwingLow 必须满足：

`SwingLow.occurred_at > pullback_started_at`

并且：

`SwingLow.confirmed_at <= current_bar.close_time`

在当前 PULLBACK 开始后已经确认的 SwingLow 中，选择价格最低者：

`PullbackLow_4H = argmin(SwingLow.price)`

如果多个 SwingLow 价格相同：

1. 选择 `occurred_at` 最早者。
2. 若仍相同，选择 `point_id` 字典序最小者。

如果当前 PULLBACK 开始后尚未确认任何 SwingLow：

- 不创建 Setup4H。
- 等待后续 SwingLow 确认。
- 不允许使用回撤开始前的旧 SwingLow。
- 不允许使用未确认候选低点。

## 10.4 Setup4H 与 Zone 价格关系

定义：

`DistanceToZone(P, [L,U]) = max(L-P, 0, P-U)`

创建条件：

`DistanceToZone(PullbackLow_4H, [Zone.lower, Zone.upper]) <= setup_zone_tolerance_atr × ATR_4H`

必须使用已确认的 4H 回撤低点 SwingPoint.price。

不使用当前 Close 代替回撤低点，也不使用未完成 Bar 的 Low。

## 10.5 Setup4H 观察区

Setup4H 初始观察区：

`Observation4H = Zone4H`

宽度：

`Width4H = Observation4H.upper - Observation4H.lower`

最小宽度：

`MinimumObservationWidth4H = max(min_observation_width_4h_atr × ATR_4H, 2 × tick_size)`

如果：

`Width4H < MinimumObservationWidth4H`

则不创建 Setup4H。

## 10.6 Setup1H

Setup1H 是 Setup4H 的子对象。

创建条件：

1. 父 Setup4H 状态为 ACTIVE，且当前宏观方向权限仍允许做多。
2. 1H 状态为 PULLBACK 或 REVERSAL_CANDIDATE。
3. 1H 多头结构有效。
4. 1H ProtectedLow 有效。
5. 存在有效 1H SUPPORT Zone。
6. 4H 和 1H 观察区存在有效交集。
7. 交集宽度满足最小要求。

观察区：

`Observation1H = Intersection(Observation4H, Zone1H)`

即：

`lower = max(Observation4H.lower, Zone1H.lower)`

`upper = min(Observation4H.upper, Zone1H.upper)`

要求：

`upper > lower`

最小宽度：

`MinimumObservationWidth1H = max(min_observation_width_1h_atr × ATR_1H, 2 × tick_size)`

如果交集不存在或交集宽度不足，不创建 Setup1H。

当前版本不扩展父级观察区。

必须分别统计：

- `SETUP1H_NO_INTERSECTION`
- `SETUP1H_INTERSECTION_TOO_NARROW`

不得把两种拒绝原因合并为普通 Setup 失败。

## 10.7 Setup 有效期

默认：

- Setup4H：8 根 4H Bar。
- Setup1H：12 根 1H Bar。

超过有效期：

`ACTIVE → EXPIRED`

参数属于研究初值。

## 10.8 Setup 恢复

当 4H 从 PULLBACK 恢复 TREND_UP：

- 当前 Setup4H 进入 EXPIRED。
- 不允许基于旧 Setup 创建新的 Setup1H 或 15M Signal。
- 已创建且仍有效的 Signal 不因恢复事件自动取消。

当 1H 从 REVERSAL_CANDIDATE 恢复 BULLISH：

- 当前 Setup1H 进入 EXPIRED。
- 不允许创建新的 15M Signal。
- 已创建且仍在有效期内的 Signal 可以继续等待 3M 执行。

只有结构失效、Zone 失效、上下文权限禁止或 Signal 自身超时，才取消已有 Signal。

---

# 11. 15M 信号系统

## 11.1 信号类型

- BREAKOUT_CONTINUATION
- PULLBACK_CONTINUATION

每个 Signal 必须关联：

- `setup_4h_id`
- `setup_1h_id`
- `n_structure_id`
- `observation_zone_id`
- `context_snapshot_id`
- `observation_zone_version`
- `signal_reference_close`
- `signal_reference_close_time`
- `execution_reference_level`
- `execution_reference_atr_15m`

`signal_reference_close` 定义为创建该 Signal 的 15M 完成 Bar 的 Close；`signal_reference_close_time` 为该 Bar 的 `close_time`。两者创建后不可修改。

**创建新 Signal 时，父 Setup4H 和 Setup1H 必须均为 ACTIVE。**

父 Setup 后续进入 EXPIRED，不追溯取消已经创建的 Signal。

## 11.2 15M N 结构位置判定

N 结构 L2 使用确认 SwingPoint.price。

定义：

`DistanceToZone(L2, [lower,upper])`

要求：

`DistanceToZone(L2, ObservationZone) <= l2_tolerance_atr × signal_decision_atr_15m`

默认：

`l2_tolerance_atr = 0.1`

L2 是位置验证，突破 Close 是触发验证。

突破 Close 不要求仍处于观察区内。

## 11.3 15M 观察区宽度

`MinimumObservationWidth15M = max(min_observation_width_15m_atr × signal_decision_atr_15m, 2 × tick_size)`

该规则仅用于 15M 信号定位区，不得替代 Setup4H、Setup1H 的周期宽度校验。

## 11.4 BREAKOUT_CONTINUATION

条件：

1. 父 Setup4H 和 Setup1H 均为 ACTIVE。
2. 宏观权限允许。
3. 15M 多头 N 结构有效。
4. N 结构 L2 位于观察区或容差范围内。
5. Close 突破 H2：

`Close_15M > H2`

6. Close 高于 SMA22：

`Close_15M > SMA22_15M`

7. 突破幅度不超过：

`Close_15M - H2 <= breakout_max_extension_atr × signal_decision_atr_15m`

保存：

- `trigger_reference_price = H2`
- `structural_stop_anchor_swing_id = L2`

## 11.5 PULLBACK_CONTINUATION

本信号不依赖未定义的 15M PULLBACK 状态枚举，而是通过确定的 SwingPoint 序列识别回撤。

15M 不维护独立 ProtectedLow。回撤延续的前置保护低点统一引用当前有效 15M 多头 N 结构的 `L2`：

`PreviousProtectedLow = CurrentNStructure.L2`

`CurrentNStructure` 必须有效，且 `L2` 必须为已确认 SwingLow。不得引用 1H、4H 的 ProtectedLow，也不得在 N 结构失效后继续使用旧 L2。

### A. 回撤起点

使用 5.4 定义的当前有效多头结构 `PullbackOriginHigh`，不得简单使用最近一个 SwingHigh 替代。必须保存：

- `pullback_start_swing_id = pullback_origin_swing_id`
- `pullback_start_price = pullback_origin_price`
- `pullback_started_at`

当后续完成 15M Bar 满足：

`PullbackStartHigh - Close_15M >= pullback_min_atr_15m × pullback_start_atr_15m`

其中 `pullback_start_atr_15m` 是确认回撤开始的该根已完成 15M Bar 的 ATR14 快照，确认后不可修改。且当前 N 结构有效、`PreviousProtectedLow` 尚未失效时，确认进入本轮 15M 回撤观察阶段。

本轮回撤开始后，`pullback_start_swing_id` 不得被后续 SwingHigh 替换。变量别名固定为：`PullbackStartHigh = PullbackOriginHigh`。

### B. 回撤低点

回撤开始后，等待确认新的 15M SwingLow。候选必须满足：

- `occurred_at > pullback_started_at`
- `confirmed_at > pullback_started_at`
- `PullbackLow > PreviousProtectedLow`

其中 `PreviousProtectedLow` 始终等于本轮信号候选所绑定的 `CurrentNStructure.L2`。

如果后续确认出更低的回撤 SwingLow：

1. 若新低仍高于 `CurrentNStructure.L2`，更新 `pullback_low_swing_id`。
2. 原 `trigger_swing_id`、`trigger_reference_price`、`higher_low_swing_id` 及其关联的 HigherLow 确认状态立即全部作废，并清空对应字段。
3. 重新等待新的 TriggerSwingHigh；新的 HigherLow 必须在新 TriggerSwingHigh 确认之后形成并确认，不得复用旧 HigherLow。
4. 如果新低等于或低于 `CurrentNStructure.L2`，本轮回撤候选失效；不得创建 PULLBACK_CONTINUATION。

### C. TriggerSwingHigh 选择

回撤低点确认后，选择**该 PullbackLow 确认之后形成并确认的第一个同时满足时序条件和最小反弹幅度条件的 15M SwingHigh** 作为 `TriggerSwingHigh`。低于最小反弹幅度的 SwingHigh 不占用 TriggerSwingHigh 槽位。

必须满足：

- `TriggerSwingHigh.occurred_at > PullbackLow.occurred_at`
- `TriggerSwingHigh.confirmed_at > PullbackLow.confirmed_at`
- `TriggerSwingHigh.confirmed_at <= trigger_bar.close_time`
- 最小反弹幅度满足：

`TriggerSwingHigh.price - PullbackLow.price >= min_trigger_swing_atr × trigger_swing_atr_15m`

`min_trigger_swing_atr` 为 RESEARCH 参数，初始值 0.3。低于该阈值的 SwingHigh 不得成为 TriggerSwingHigh；继续等待后续第一个满足最小幅度且时序条件成立的已确认 SwingHigh。ATR 使用 TriggerSwingHigh 确认时对应的已完成 15M Bar ATR，并将该值快照保存到本轮候选，避免后续 ATR 变化改写历史判定。

保存：

- `trigger_swing_id`
- `trigger_reference_price = TriggerSwingHigh.price`
- `trigger_swing_atr_15m = TriggerSwingHigh` 确认时对应的已完成 15M Bar ATR 快照

本轮回撤内 TriggerSwingHigh 一旦选定，不因后续出现更高 SwingHigh 而替换，避免触发价漂移。若 PullbackLow 更新为更低且仍有效的低点，旧 TriggerSwingHigh 作废，必须重新等待新的触发高点。

### D. HigherLow 确认与位置关系

TriggerSwingHigh 之后，必须确认一个新的 15M SwingLow 作为 `HigherLow`，并满足：

- `HigherLow.occurred_at > TriggerSwingHigh.occurred_at`
- `HigherLow.confirmed_at > TriggerSwingHigh.confirmed_at`
- `HigherLow.price > PullbackLow.price`
- `HigherLow.price > PreviousProtectedLow`

保存 `higher_low_swing_id`。

观察区位置校验针对 `PullbackLow`，而不是 HigherLow：

`DistanceToZone(PullbackLow.price, ObservationZone) <= pullback_low_zone_tolerance_atr × signal_decision_atr_15m`

其中 `DistanceToZone(price, zone)` 定义为：价格位于 `[zone.lower, zone.upper]` 内时为 0；低于 `zone.lower` 时为 `zone.lower - price`；高于 `zone.upper` 时为 `price - zone.upper`。

`HigherLow` 只承担结构抬高确认，必须满足本节前述时序条件，且高于 PullbackLow 和 PreviousProtectedLow；不要求 HigherLow 本身仍贴近观察区。位置容差使用 Signal 创建时冻结的 `signal_decision_atr_15m`，不使用 ATR_1H、ATR_4H 或后续更新的 ATR。

### E. 突破触发

HigherLow 确认后，后续完成 15M Bar 必须满足：

`Close_15M > trigger_reference_price`

且：

`trigger_bar.close_time > trigger_swing.confirmed_at`

只有 A 至 E 全部成立，才创建 PULLBACK_CONTINUATION Signal。

保存：

- `pullback_start_swing_id`
- `pullback_low_swing_id`
- `trigger_swing_id`
- `higher_low_swing_id`
- `trigger_reference_price`
- `structural_stop_anchor_swing_id = higher_low_swing_id`
- `execution_reference_level = trigger_reference_price`

禁止使用回撤开始之前的旧 SwingHigh 作为触发高点。

### F. 15M 决策 ATR 快照

为保证同一输入在批量回放、增量回放和实时运行中得到相同判定，所有 ATR 参与的历史决策必须绑定明确的已完成 Bar 快照，不得在后续 Bar 到来后回算并改写既有候选结果：

- `signal_decision_atr_15m`：Signal 创建时最近一根已完成 15M Bar 的 ATR14 快照。11.2 的 L2 位置容差、11.3 的 15M 观察区最小宽度、11.4 的突破延伸上限、11.5 D 的 PullbackLow 观察区位置校验统一使用该值；创建 Signal 时写入 Signal，之后不可修改。
- `pullback_start_atr_15m`：确认回撤开始的 15M 完成 Bar ATR14 快照，只用于 11.5 A 的回撤开始幅度判定。
- `trigger_swing_atr_15m`：TriggerSwingHigh 确认时对应的 15M 完成 Bar ATR14 快照，只用于 11.5 C 的最小反弹幅度判定，不得替代 `signal_decision_atr_15m` 或 `execution_reference_atr_15m`。
- `execution_reference_atr_15m`：Signal 创建时最近一根已完成 15M Bar 的 ATR14 快照，用于 12.6/12.8 执行偏差与成交偏差计算；与 `signal_decision_atr_15m` 在同一 Signal 创建事件中取自同一根已完成 Bar，数值必须相等，但字段语义分别服务于信号决策和执行风控。

若 ATR 快照缺失、非有限数或小于等于 0，相关 ATR 倍数判定不得执行；候选进入 `INVALID_ATR` 拒绝/异常路径，不得以 0、NaN 或临近 Bar 的 ATR 替代。

同一：

`n_structure_id + signal_type`

最多允许创建一次 Signal 尝试。

REJECTED 也消耗该唯一性槽位。

如需重新尝试，必须出现新的 N 结构 ID。

## 11.7 Signal 状态

Signal 创建前完成所有校验。创建成功时直接进入 ACTIVE，不单独设置 CREATED。

创建校验失败时，不创建正式 Signal，而是记录内部事件 `SignalCandidateRejected`，保存幂等键、拒绝原因、结构 ID、Signal 类型和时间。候选拒绝仍消耗同一 `n_structure_id + signal_type` 的唯一尝试槽位。

正式 Signal 状态：

- ACTIVE
- CANCELLED
- EXPIRED
- PARTIALLY_EXECUTED
- EXECUTED

**终态优先级（高于一般超时/取消原因映射）：**

1. 若 `filled_quantity = 0` 且剩余订单终止：根据终止原因进入 `EXPIRED` 或 `CANCELLED`。
2. 若 `filled_quantity > 0` 且仍有剩余订单有效：保持 `ACTIVE`，并设置 `partially_filled = True`。
3. 一旦 `filled_quantity > 0` 且剩余订单因任何原因终止（包括超时、结构失效、上下文失效、宏观权限禁止、`FILL_DEVIATION_BREACH`、人工撤单或交易所撤单），Signal 统一进入 `PARTIALLY_EXECUTED`；具体原因写入 `remaining_order_terminal_reason`，不得进入 `EXPIRED` 或 `CANCELLED`。
4. 若累计成交数量达到 Signal 目标数量，进入 `EXECUTED`。

| 当前对象/状态 | 事件 | 结果 |
|---|---|---|
| 无 Signal | 创建校验失败 | 不创建 Signal；记录 SignalCandidateRejected |
| 无 Signal | 创建校验通过 | 创建并进入 ACTIVE |
| ACTIVE | 累计成交数量达到 Signal 目标数量 | EXECUTED |
| ACTIVE，filled_quantity > 0 | 剩余订单仍有效 | 保持 ACTIVE，设置 `partially_filled = True` |
| ACTIVE，filled_quantity = 0 | 超时 | EXPIRED |
| ACTIVE，filled_quantity = 0 | 结构、上下文或宏观权限失效 | CANCELLED |
| ACTIVE，filled_quantity > 0 | 剩余订单因任意原因终止 | PARTIALLY_EXECUTED，记录 `remaining_order_terminal_reason` |
| PARTIALLY_EXECUTED | 已成交数量达到目标数量（例如剩余订单重新提交后完成） | EXECUTED |
| PARTIALLY_EXECUTED | 已成交持仓由 PositionManager 接管 | 保持 PARTIALLY_EXECUTED |

`EXPIRED` 和 `CANCELLED` 只允许用于 `filled_quantity = 0` 的 Signal。`PARTIALLY_EXECUTED` 表示 Signal 的入场执行未完成但已经形成真实持仓，可作为最终执行状态；已成交部分由 PositionManager 接管，不得因为剩余订单撤销而将 Signal 改为 CANCELLED/EXPIRED。

Signal 字段 `partially_filled` 初始为 `False`；首次出现 `filled_quantity > 0` 且 `unfilled_quantity > 0` 时置为 `True`。该字段用于区分“尚未成交的 ACTIVE”与“部分成交且剩余订单仍有效的 ACTIVE”。进入 `PARTIALLY_EXECUTED` 后该字段仍保持 `True`，直至 Signal 生命周期结束，不得仅因剩余订单撤销而清零。

必须记录：

- `remaining_order_terminal_reason`
- `filled_quantity`
- `unfilled_quantity`
- `position_id`

`REJECTED` 是候选拒绝事件的结果，不是正式 Signal 状态。
## 11.8 Signal 有效期

默认最多等待 4 根 15M Bar。

出现以下情况立即终止：

- 15M N 结构失效。
- 父 Setup INVALIDATED。
- Zone BROKEN 或 INVALIDATED。
- 宏观权限变为禁止。
- Signal 超时。

父 Setup EXPIRED 本身不取消已经创建的有效 Signal。

---

# 12. 3M 执行确认

## 12.1 职责限制

3M 只确认执行时机，不产生方向判断和独立入场信号。

## 12.2 3M 分形

采用 2 左 2 右分形。

SwingHigh：

`High[i] > High[i-1]`

`High[i] > High[i-2]`

`High[i] >= High[i+1]`

`High[i] >= High[i+2]`

SwingLow 反向定义。

分形必须等右侧两根 Bar 完成后才能确认。

相同高点平台采用最早出现的成员作为分形点。

## 12.3 Signal 后的严格时序

定义：

`SignalCreatedAt`

必须满足以下全部条件。

### A. Signal 后 SwingLow

执行确认所使用的 SwingLow 必须满足：

`SwingLow.confirmed_at > SignalCreatedAt`

并且：

`SwingLow.occurred_at > SignalCreatedAt`

Signal 创建前已经确认的 SwingLow 一律不可用于本次执行确认。Signal 创建前已经发生、但创建后才确认的 SwingLow 同样不可用；该情况属于有意的严格时序过滤，必须单独统计其对 3M 执行确认率和成交率的影响。

即使某 SwingLow 的 `occurred_at < SignalCreatedAt`、但 `confirmed_at > SignalCreatedAt`，也不得使用。这是有意采用的严格过滤条件。

### B. Signal 后 SwingHigh

执行确认所使用的 SwingHigh 必须满足：

`SwingHigh.confirmed_at > SignalCreatedAt`

并且：

`SwingHigh.occurred_at > SignalCreatedAt`

该 SwingHigh 必须在 Signal 创建后形成并完成右侧两根 Bar 确认。

### C. 突破 Bar

突破 Bar 必须在 SwingHigh 确认后完成：

`BreakoutBar.close_time > PostSignalSwingHigh.confirmed_at`

并满足：

`BreakoutBar.Close > PostSignalSwingHigh.price`

不允许使用 SwingHigh 确认之前的 Bar Close 判断突破。

### D. 执行条件

只有 A、B、C 全部满足，才允许生成执行确认。

## 12.4 快速突破行情

快速突破行情可能因无法形成信号后的完整分形而错过执行。

该规则属于明确的保守过滤设计，未经对照实验不得移除。

必须统计：

- 因无信号后 SwingLow 超时的比例。
- 因无信号后 SwingHigh 超时的比例。
- 因等待分形导致的平均入场延迟。
- 快速突破行情的放弃比例。
- 与简化确认方案的成交率和收益风险比较。

## 12.5 执行参考价格

`ExecutionReferencePrice`：

执行确认 Bar 的最后完成 3M Close。

`ExecutionReferenceLevel`：

- BREAKOUT_CONTINUATION：15M N 结构 H2。
- PULLBACK_CONTINUATION：Signal 保存的 `trigger_reference_price`。

## 12.6 提交前追价限制

执行参考价相对触发参考价的不利偏离：

`max(ExecutionReferencePrice - ExecutionReferenceLevel, 0) <= max_execution_deviation_atr × execution_reference_atr_15m`

相对 Signal 创建时 15M Close 的不利跳空：

`max(ExecutionReferencePrice - signal_reference_close, 0) <= max_execution_gap_atr × execution_reference_atr_15m`

其中 `signal_reference_close` 为 11.1 定义的 Signal 创建 15M Bar Close；两项检查均使用创建时冻结的 `execution_reference_atr_15m`，不得使用未来或更新后的 ATR。

任一条件不满足，取消 Signal，不提交入场订单。

## 12.7 下单时间约束

订单提交时间为 `order_submit_time`。

可成交 Bar 必须满足：

`bar.open_time > order_submit_time`

不允许在同一时间戳的 Bar Open 成交。


## 12.8 Actual Fill Deviation Control

每个 Signal 创建时必须冻结：

- `execution_reference_level`
- `execution_reference_atr_15m`

其中：

- BREAKOUT_CONTINUATION：`execution_reference_level = NStructure.H2`。
- PULLBACK_CONTINUATION：`execution_reference_level = trigger_reference_price`。
- `execution_reference_atr_15m` 使用 Signal 创建时最近一根已完成 15M Bar 的 ATR14 快照，创建后不可修改。

每笔实际成交分别计算并写入独立 `FillRecord`：

`ActualFillDeviation = ActualFillPrice - ExecutionReferenceLevel`

多头不利偏差：

`AdverseFillDeviation = max(ActualFillPrice - ExecutionReferenceLevel, 0)`

若 `ExecutionReferenceATR15M` 缺失、非有限数或 `<= 0`：

- 不计算 `AdverseFillDeviationATR`，不得发生除零或使用替代 ATR。
- 记录 `INVALID_ATR`，取消该入场订单剩余未成交数量。
- 使用已发生的实际 Fill、实际持仓、可用止损和成本数据执行风险重算；若风险输入不完整，进入 `RISK_ANOMALY` 并执行预先定义的紧急风险处置。
- 禁止新开仓，直至异常处理和订单对账完成。

ATR 有效时：

`AdverseFillDeviationATR = AdverseFillDeviation / ExecutionReferenceATR15M`

超限条件：

`AdverseFillDeviationATR > max_actual_fill_deviation_atr`

当任意一笔 Fill 超限时：

1. 记录 `FILL_DEVIATION_BREACH` 事件及订单、Signal、参考价、ATR 快照、成交价、偏差金额和 ATR 倍数。
2. 立即取消该入场订单剩余未成交数量。
3. 不回溯删除或撤销已经发生的成交。
4. 使用实际累计加权平均成交价、实际持仓数量、实际止损和实际交易成本重新计算风险。
5. 如果实际风险未超预算，继续由 PositionManager 管理已有仓位，不强制平仓。
6. 如果实际风险超预算，进入 `ACTUAL_RISK_BUDGET_BREACH` 流程。
7. 风险恢复预算范围且订单对账完成前，禁止建立新仓位。

部分成交时每笔 Fill 单独审计，同时维护累计加权平均成交价。订单级 `actual_fill_deviation_atr` 定义为该订单所有有效 Fill 中最大的单笔不利偏差 ATR；不得用累计均价偏差覆盖单笔超限事实。任意 Fill 超限即触发上述撤单和风险复核。

事件至少包含：

```python
FILL_DEVIATION_BREACH = {
    "signal_id": str,
    "order_id": str,
    "fill_id": str,
    "execution_reference_level": float,
    "execution_reference_atr_15m": float,
    "actual_fill_price": float,
    "actual_fill_deviation": float,
    "actual_fill_deviation_atr": float,
    "max_actual_fill_deviation_atr": float,
    "occurred_at": datetime,
}
```

成交偏差超限与风险预算超限是两个独立事件：前者触发撤销剩余入场订单和风险重算；只有重算结果超过预算才触发 `ACTUAL_RISK_BUDGET_BREACH`。
---

# 13. 订单与成交执行规范

## 13.1 实时交易价格

多头交易：

- 入场使用可成交 Ask。
- 退出使用可成交 Bid。

不能使用中间价假设实际成交。

## 13.2 Bar 回测成交模型

入场订单：

- 以首个符合时间约束的 3M Bar Open 作为基础成交参考。
- 加入不利滑点。
- 按订单数量和成交规则模拟成交。

实际成交价格必须与策略参考价格分离保存。

## 13.3 订单状态

- INITIALIZED
- SUBMITTED
- ACCEPTED
- PARTIALLY_FILLED
- FILLED
- CANCEL_PENDING
- CANCELED
- REJECTED
- EXPIRED

## 13.4 Position 状态

- FLAT
- OPEN
- CLOSING
- CLOSED

OrderState 与 PositionState 必须独立管理。

## 13.5 部分成交

部分成交后：

- 持仓数量以实际成交数量为准。
- 保护性止损数量必须与实际持仓同步。
- 剩余入场订单撤销后，不得影响已成交仓位。
- 止损单修改或替换必须有明确的订单关联和状态确认。
- 发生订单状态不一致时，以交易所回报为最终事实来源，并触发对账。

---

# 14. 交易成本与合约元数据

## 14.1 成本组成

必须包含：

- Maker Fee。
- Taker Fee。
- 入场滑点。
- 出场滑点。
- Funding Rate。
- 合约乘数。
- Tick Size。
- Lot Size。
- 最小下单数量。

## 14.2 版本管理

每次回测必须固定：

- `cost_model_version`
- `instrument_metadata_version`
- `funding_dataset_hash`
- `fee_schedule_version`
- `slippage_model_version`

缺少必需成本数据时，不允许将回测标记为有效净收益结果。

## 14.3 Funding

Funding 必须按照实际结算时间、历史费率和持仓方向计算。

不得用简单平均费率代替真实结算序列。

## 14.4 风险成本

初始开仓仓位计算使用完整的初始每单位风险：

`InitialRiskPerUnit = StopLossPriceRisk + EstimatedEntryFee + EstimatedExitFee + EntrySlippageCost + ExitSlippageCost`

`InitialRiskPerUnit` 包含预计入场成本，用于初始仓位 sizing；实际成交后用于风险核算时，已发生的入场费用作为已发生成本单独计入 `ActualRisk`，不得在后续减仓的边际每单位风险中重复计入。

风险预算超限减仓使用：

`CurrentRiskPerUnit = CurrentStopLossPriceRisk + EstimatedExitFee + ExitSlippageCost`

`CurrentStopLossPriceRisk = max(CurrentExecutablePrice - CurrentStopPrice, 0) × contract_multiplier`

其中：

- `CurrentStopLossPriceRisk`：当前可执行价格至当前有效止损的每单位价格风险，按合约乘数换算。
- `EstimatedExitFee`：按当前适用退出费率和预计退出名义价值计算的每单位退出费用。
- `ExitSlippageCost`：按当前退出滑点模型计算的每单位预计退出滑点成本。
- 不包含已经发生且不可通过减仓收回的 `EstimatedEntryFee`、`EntrySlippageCost` 或其他沉没入场成本。

价格风险按照合约乘数换算。仓位同时受到风险预算、最大敞口、最大保证金、交易所最大下单数量、Lot Size 和最小下单数量约束。最终初始数量必须按 Lot Size 向下取整；如果取整后低于最小下单量，则拒绝开仓。

---

# 15. 止损与可执行价格

## 15.1 固定止损与结构止损

固定止损比例：

`fixed_stop_pct`

### A. 下单前预检查

在尚未成交时，使用：

`ExecutionReferencePrice`

计算预估固定止损：

`P_fixed_precheck = ExecutionReferencePrice × (1 - fixed_stop_pct)`

该值只用于入场前风险预估，不是最终固定止损。

### B. 实际成交后

实际平均入场价：

`ActualAverageEntryPrice = Sum(FillPrice × FillQty) / Sum(FillQty)`

固定止损必须按实际成交均价计算：

`P_fixed = ActualAverageEntryPrice × (1 - fixed_stop_pct)`

每次新增部分成交后，重新计算实际平均入场价和固定止损。

### C. 结构止损

BREAKOUT_CONTINUATION：

`P_structural = N_L2 - stop_buffer_atr × initial_stop_atr_15m`

PULLBACK_CONTINUATION：

`P_structural = PullbackHL - stop_buffer_atr × initial_stop_atr_15m`

其中 PullbackHL 必须使用 Signal 保存的 `structural_stop_anchor_swing_id`。

### D. 初始有效止损

成交后：

`InitialStop = max(P_fixed, P_structural)`

`initial_stop_atr_15m` 定义为首次实际成交发生时，最近一根已完成 15M Bar 的 ATR14 快照；首次成交后固定，不因后续 ATR 更新而改变。结构止损按该快照计算。

要求同时满足：

`InitialStop < ActualAverageEntryPrice`

`InitialStop < CurrentExecutablePrice`

`CurrentExecutablePrice` 的定义见 15.4。实时交易使用首笔成交确认时最新有效 Bid；Bar 回测中，使用首笔成交后第一根满足时间约束的 3M Bar Open，在该 Open 对保护止损进行生效前校验。若任一条件不满足，初始止损无效：不得将其作为正常保护性止损提交或保留；立即取消剩余入场订单，进入 `RISK_ANOMALY` / 紧急退出流程，按当前可执行退出价格退出已成交仓位。回测中该校验不得使用未来 Bar 的 Low。

## 15.2 部分成交后的止损

每次部分成交：

1. 更新实际平均入场价。
2. 更新实际持仓数量。
3. 按实际平均入场价重新计算固定止损。
4. 重新计算结构止损与有效止损；结构止损继续使用首次成交时冻结的 `initial_stop_atr_15m`，不得因部分成交时 ATR 变化而重写初始结构止损。
5. 校验新的有效止损同时满足 `InitialStop < ActualAverageEntryPrice` 和 `InitialStop < CurrentExecutablePrice`。若不满足，取消剩余入场订单并立即进入 `RISK_ANOMALY` / 紧急退出流程，不得将无效止损视为正常保护。
6. 同步保护性止损数量：

`StopQuantity = PositionQuantity`

7. 记录止损修改事件及当次 `stop_update_atr_15m`（如本次计算涉及新的止损候选）。

每次首笔成交、部分成交、追加成交、部分减仓和全部平仓后都必须重新同步。任何时刻必须满足：

`StopQuantity <= PositionQuantity`

持仓归零时必须取消剩余保护性止损订单。不得因部分成交导致止损数量大于持仓数量，也不得使已成交仓位失去保护性止损。

## 15.3 止损更新时机

移动止损只能在 15M 完成 Bar 后计算。

新止损最早从下一个合格的 3M 执行事件生效。

不得在同一根已经完成的 3M Bar 内追溯触发新止损。

## 15.4 CurrentExecutablePrice

Bar 回测中：

- 止损更新在 Bar 收盘后计算。
- `CurrentExecutablePrice` 定义为下一根满足时间约束的 3M Bar Open。
- 在该 Bar Open 到达之前，不得提前使用其价格参与其他策略判断。
- 如果该 Open 已经触及或低于尚未生效的 `StopCandidate`，立即提交紧急市价退出；回测退出参考价为该 3M Bar Open，并叠加不利退出滑点。该动作不是原保护性止损单成交，不得套用 15.5 的已生效止损单触发模型，也不得使用该 Bar Low 追溯触发候选止损。
- 只有在该 Bar 开盘前已生效的保护性止损单，才按 15.5 使用该 Bar Open/Low 判断触发。
- 不允许将上一根 3M Close 当作真实可成交价格。

实时交易中：

- 多头仓位使用最新可成交 Bid 作为 `CurrentExecutablePrice` 和退出参考价。
- 必须考虑报价时间戳和报价有效性。
- 报价过期或不可用时进入执行异常处理。

## 15.5 止损成交模型

**前置条件：只有止损单在该 3M Bar 开盘之前已经生效，才允许使用该 Bar 的 Open 和 Low 判断止损触发。**

如果止损是在某根 Bar 收盘后计算或提交，则该 Bar 的历史 Low 不得用于触发新止损。新止损从下一根符合时间约束的 3M Bar 开始检查。

设有效止损价为 `S`。

情况 A：

`Open <= S`

发生跳空穿越：

`StopTriggerPrice = Open`

`StopFillPrice = Open - StopSlippage`

情况 B：

`Open > S and Low <= S`

正常触及：

`StopTriggerPrice = S`

`StopFillPrice = S - StopSlippage`

情况 C：

`Low > S`

未触发止损。

## 15.6 保守滑点说明

当 `StopSlippage > S - Low` 时，模拟成交价可能低于该 Bar 的 Low。

这是一种保守压力测试模型，不代表该价格在真实市场中必然可成交。

回测报告必须分别统计：

- Bar 范围内的止损成交。
- Bar Low 以下保守模拟成交。
- 额外滑点成本。
- 止损跳空次数。

## 15.7 止损候选校验

止损更新候选必须满足：

`StopCandidate < CurrentExecutablePrice`

如果下一根合格 3M Open 已经触及或低于尚未生效的 StopCandidate：

- 不允许把该止损当作正常更新后继续持仓。
- 取消尚未生效的止损更新请求（如已提交则按订单状态对账），进入紧急市价退出或 `RISK_ANOMALY`。
- 回测以该 Bar Open 作为紧急市价退出参考价并叠加不利滑点；不得将该候选价视为已生效止损单，也不得用该 Bar Low 套用 15.5。

---

# 16. 移动止损与风险升级

## 16.1 移动止损

移动止损从入场时间之后的**下一根完整 15M Bar** 开始统计。包含入场时间的那根 15M Bar 不参与最高价统计，即使该 Bar 在入场后才收盘，也不得使用其中的入场前 High。

例如，12:07 入场时，12:00–12:15 Bar 不参与统计；12:15–12:30 是第一根可参与统计的完整 15M Bar。

`first_15m_bar_open_time_after_entry` 定义为不早于 EntryTime 的下一个 15M 周期边界；若 EntryTime 恰好等于周期边界，则该边界即为下一根 Bar 的开盘时间。`TrailingActivationBar` 是第一根满足 `bar.open_time >= first_15m_bar_open_time_after_entry` 的 15M Bar。只有该 Bar 完成后，才更新：

最高价：

`Highest_15M_High_since_activation`

正常移动止损：

`P_trailing = Highest_15M_High_since_activation - k_normal × stop_update_atr_15m`

默认：

`k_normal = 3.0`

## 16.2 风险升级

触发条件：

- 1H 状态进入 TRANSITION；或
- 4H 状态进入 TRANSITION。

触发后：

`RiskState = RISK_ESCALATED`

升级移动止损：

`P_trailing = Highest_15M_High_since_activation - k_escalated × stop_update_atr_15m`

默认：

`k_escalated = 2.0`

止损只能向有利方向移动，不得下移。

## 16.3 风险升级解除

风险升级解除计数从 `RiskState` 首次进入 `RISK_ESCALATED` 之后的下一根完整周期 Bar 开始。触发风险升级的那根 1H/4H Bar 只用于触发升级，不计入恢复连续计数。1H 与 4H 分别按各自周期的完成 Bar 独立计数。

风险升级解除必须满足：

1. 1H 连续 `risk_recovery_1h_bars` 根已完成 Bar 收盘后状态均为 BULLISH。
2. 4H 至少连续 `risk_recovery_4h_bars` 根已完成 Bar 收盘后状态均为 TREND_UP。
3. 1H ProtectedLow 有效。
4. 4H ProtectedLow 有效。
5. `CanHold = True`（见 8.5），不要求 `CanOpen = True`。

任一 1H Bar 收盘后状态不是 BULLISH，1H 连续计数立即归零；任一 4H Bar 收盘后状态不是 TREND_UP，4H 连续计数立即归零。计数按完成 Bar 递增，不按盘中状态递增。

初始研究值：`risk_recovery_1h_bars = 3`、`risk_recovery_4h_bars = 2`。4H 必须连续两根已完成 Bar 均为 TREND_UP；单根 4H TREND_UP 不足以解除风险升级。解除条件同时要求 1H、4H ProtectedLow 有效，且 `CanHold = True`。即使 `CanOpen = False`，只要没有强制退出条件，仍可解除风险升级；但新开仓继续禁止。

解除后：

`RiskState = NORMAL`

后续移动止损候选可以恢复使用 `k_normal`。每次移动止损计算使用计算时最近一根已完成 15M Bar 的 ATR14，并冻结为该次事件的 `stop_update_atr_15m`；同一候选的校验、事件记录和回放必须复用该快照，不得在后续 Bar 中回算。恢复 NORMAL 后统一执行：

`NewStop = max(CurrentStop, CandidateStopNormal)`

候选止损低于当前止损时忽略；高于当前止损时才允许上移。

但是：

- 已经上移的止损不得下移。
- 恢复 NORMAL 不得扩大已有风险。
- 如果当前价格已经接近或低于已有止损，仍按已有止损执行。

## 16.4 结构失效与风险升级的区别

TRANSITION 触发风险升级。

ProtectedLow 有效突破属于结构失效，必须触发退出逻辑，不得仅仅通过缩小 ATR 倍数处理。

---

# 17. 仓位与风险闭环

## 17.1 初始风险预算

`RiskBudget = AccountEquity × risk_per_trade_pct`

`risk_per_trade_pct` 是 REQUIRED 配置。

## 17.2 初始仓位

`Q_risk = RiskBudget / InitialRiskPerUnit`

同时计算：

- `Q_exposure`
- `Q_margin`
- `Q_exchange`

最终：

`Q_final = floor_to_lot_step(min(Q_risk, Q_exposure, Q_margin, Q_exchange))`

## 17.3 ACTUAL_RISK_BUDGET_BREACH

实际成交后重新计算：

- 实际平均成交价。
- 实际止损价。
- 实际持仓数量。
- 实际手续费。
- 已知滑点。
- 预计止损退出成本。

如果：

`ActualRisk > RiskBudget`

必须：

1. 立即取消剩余入场订单。
2. 冻结新的入场信号和加仓权限。
3. 计算超预算比例。
4. 若通过部分减仓可以恢复预算，计算：

`RequiredReduceRisk = ActualRisk - RiskBudget`

`RawReduceQty = RequiredReduceRisk / CurrentRiskPerUnit`

如果 `CurrentRiskPerUnit <= 0`、不可计算或退出费用/滑点/有效止损数据不完整，不得执行公式化减仓；进入风险异常并全平或执行预先配置的紧急风险处置。`CurrentRiskPerUnit` 不包含已发生入场费和入场滑点；已发生入场成本仍保留在 `ActualRisk` 的总账核算中，但不得作为减仓边际风险分母重复计入。

按 Lot Size 向上取整，避免减仓不足：

`ReduceQty = ceil(RawReduceQty / LotSize) × LotSize`

并限制：

`ReduceQty = min(ReduceQty, PositionQuantity)`

减仓回测成交价使用减仓指令提交后第一根合格 3M Bar 的 `Open`，并叠加不利方向滑点；不得使用信号 Bar 收盘价或减仓指令提交前已经发生的价格。若下一根合格 Bar 无法成交，则按订单执行规则继续等待或触发预先定义的紧急风险处置。

5. 减仓后重新计算 `ActualRiskAfterReduction`。若仍超过 RiskBudget，继续按同一规则减仓。
6. 如果剩余仓位低于 MinQuantity、无法按 Lot Size 合法减仓，或继续减仓仍无法恢复预算，则全平。若风险超过 `hard_risk_budget_multiple × RiskBudget`，立即全平。
7. 记录 `ACTUAL_RISK_BUDGET_BREACH` 和处置结果。
8. 只有实际风险恢复预算范围内，且所有异常订单完成对账后，才允许解除新开仓冻结。

默认：

`hard_risk_budget_multiple = 1.25`

该值为初始研究值，必须通过压力测试确认。

## 17.4 R 倍数

初始风险：

`R_initial = abs(InitialAverageEntryPrice - InitialStopPrice)`

净 R：

`R_multiple = NetTradePnL / (InitialRiskPerUnit × InitialFilledQty)`

必须考虑手续费、滑点、Funding 和实际成交数量。

---

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

# 19. 参数配置表

参数分类：

- FIXED：定义性规则或数据契约。
- RESEARCH：研究初值，需要回测验证。
- METADATA：交易所或数据源提供，按生效时间版本化。
- REQUIRED：必须配置，否则拒绝启动。

| 参数 | 初始值 | 分类 | 运行记录要求 |
|---|---:|---|---|
| ATR Period | 14 | FIXED | 固定规则版本 |
| SMA Period | 22 | FIXED | 固定规则版本 |
| ZigZag k | 2.0 | RESEARCH | 必须记录实际生效值 |
| Zone Min Anchors | 2（不可低于 2） | FIXED | 固定规则版本 |
| Zone Merge Distance ATR | 0.5 | RESEARCH | 必须记录实际生效值 |
| Zone Max Cluster Width ATR | 1.0 | RESEARCH | 必须记录实际生效值 |
| Zone Half Width ATR | 0.1 | RESEARCH | 必须记录实际生效值 |
| Zone Min Half Width Ticks | 2 | RESEARCH | 必须记录实际生效值 |
| Zone Test Tolerance ATR | 0.1 | RESEARCH | 必须记录实际生效值 |
| Zone Break Buffer ATR | 0.1 | RESEARCH | 必须记录实际生效值 |
| Zone Max Age | 52 weeks | RESEARCH | 必须记录实际生效值 |
| Setup Zone Tolerance ATR | 0.5 | RESEARCH | 必须记录实际生效值 |
| Min Observation Width 4H ATR | 0.5 | RESEARCH | 必须记录实际生效值 |
| Min Observation Width 1H ATR | 0.5 | RESEARCH | 必须记录实际生效值 |
| Min Observation Width 15M ATR | 0.5 | RESEARCH | 必须记录实际生效值 |
| L2 Tolerance ATR | 0.1 | RESEARCH | 必须记录实际生效值 |
| Pullback Low Zone Tolerance ATR | 0.1 | RESEARCH | 必须记录实际生效值 |
| Min Trigger Swing ATR | 0.3 | RESEARCH | 必须记录实际生效值 |
| Stop Buffer ATR | 0.1 | RESEARCH | 必须记录实际生效值 |
| Pullback Min ATR 4H | 0.5 | RESEARCH | 必须记录实际生效值 |
| Pullback Min ATR 1H | 0.3 | RESEARCH | 必须记录实际生效值 |
| Pullback Min ATR 1D | 0.5 | RESEARCH | 必须记录实际生效值 |
| Pullback Min ATR 15M | 0.3 | RESEARCH | 必须记录实际生效值 |
| Protected Break Buffer ATR | 0.1 | RESEARCH | 必须记录实际生效值 |
| N Structure Break Buffer ATR | 0.1 | RESEARCH | 必须记录实际生效值 |
| Range Boundary Tolerance ATR | 0.5 | RESEARCH | 必须记录实际生效值 |
| Setup4H Max Bars | 8 | RESEARCH | 必须记录实际生效值 |
| Setup1H Max Bars | 12 | RESEARCH | 必须记录实际生效值 |
| Signal15M Max Bars | 4 | RESEARCH | 必须记录实际生效值 |
| Breakout Max Extension ATR | 0.5 | RESEARCH | 必须记录实际生效值 |
| 3M Fractal Left | 2 | FIXED | 固定规则版本 |
| 3M Fractal Right | 2 | FIXED | 固定规则版本 |
| Max Execution Deviation ATR | 0.5 | RESEARCH | 必须记录实际生效值 |
| Max Execution Gap ATR | 0.5 | RESEARCH | 必须记录实际生效值 |
| Max Actual Fill Deviation ATR | 0.75 | RESEARCH | 必须记录实际生效值 |
| Fixed Stop Pct | 5% | RESEARCH | 必须记录实际生效值 |
| Trailing k Normal | 3.0 | RESEARCH | 必须记录实际生效值 |
| Trailing k Escalated | 2.0 | RESEARCH | 必须记录实际生效值 |
| Recovery Confirm 1H Bars | 3 | RESEARCH | 必须记录实际生效值 |
| Recovery Confirm 4H Bars | 2 | RESEARCH | 必须记录实际生效值 |
| Hard Risk Budget Multiple | 1.25 | RESEARCH | 必须记录实际生效值 |
| Risk Per Trade Pct | 用户配置 | REQUIRED | 显式配置值 |
| Max Notional Exposure | 用户配置 | REQUIRED | 显式配置值 |
| Max Margin Usage Pct | 用户配置 | REQUIRED | 显式配置值 |
| Leverage | 用户配置 | REQUIRED | 显式配置值 |
| Contract Multiplier | Exchange | METADATA | 来源及生效版本 |
| Tick Size | Exchange | METADATA | 来源及生效版本 |
| Lot Size | Exchange | METADATA | 来源及生效版本 |
| Min Quantity | Exchange | METADATA | 来源及生效版本 |
| Max Quantity | Exchange | METADATA | 来源及生效版本 |
| Maker Fee | Versioned | METADATA | 来源及生效版本 |
| Taker Fee | Versioned | METADATA | 来源及生效版本 |
| Funding Rate | Historical | METADATA | 来源及生效版本 |

RESEARCH 参数允许采用表中初始值，但每次运行必须保存实际生效值、参数分类、策略版本和 `configuration_hash`。REQUIRED 参数必须由用户/运行环境显式提供；表格中的示例值不得替代显式配置。

---

# 20. 核心数据结构

## 20.1 Setup

```python
@dataclass
class Setup:
    setup_id: str
    parent_setup_id: str | None
    status: str
    direction: str
    timeframe: str

    structure_id: str
    protected_swing_id: str
    pullback_origin_swing_id: str | None

    observation_zone_id: str
    observation_zone_version: int
    observation_lower: float
    observation_upper: float

    created_at: datetime
    expires_at: datetime
    config_version: str
```

## 20.2 Signal

字段约束：

- `BREAKOUT_CONTINUATION`：`trigger_swing_id = None`、`higher_low_swing_id = None`、`pullback_start_swing_id = None`、`pullback_start_atr_15m = None`、`pullback_low_swing_id = None`、`trigger_swing_atr_15m = None`；`trigger_reference_price = H2`。
- `PULLBACK_CONTINUATION`：`pullback_start_atr_15m`、`trigger_swing_id`、`higher_low_swing_id` 必填；`trigger_reference_price = TriggerSwingHigh.price`，并必须保存对应 SwingPoint ID；`trigger_swing_atr_15m` 必须保存 TriggerSwingHigh 确认时的 ATR 快照。
- `partially_filled` 初始为 `False`，首次部分成交且仍有未成交数量时置为 `True`。

```python
@dataclass
class Signal:
    signal_id: str
    status: str
    signal_type: str

    setup_4h_id: str
    setup_1h_id: str
    n_structure_id: str

    observation_zone_id: str
    observation_zone_version: int
    observation_lower: float
    observation_upper: float

    pullback_start_swing_id: str | None
    pullback_start_atr_15m: float | None  # PULLBACK: 回撤开始确认 Bar ATR；BREAKOUT: None
    pullback_low_swing_id: str | None
    trigger_swing_id: str | None
    trigger_reference_price: float
    trigger_swing_atr_15m: float | None
    higher_low_swing_id: str | None
    partially_filled: bool

    signal_decision_atr_15m: float
    execution_reference_level: float
    execution_reference_atr_15m: float
    signal_reference_close: float
    signal_reference_close_time: datetime

    structural_stop_anchor_swing_id: str
    structural_stop_anchor_price: float

    created_at: datetime
    expires_at: datetime

    context_snapshot_id: str
    config_version: str
```

## 20.3 FillRecord 与 ExecutionRecord

每笔交易所 Fill 必须独立保存，不得只保留订单级累计均价或最后一笔成交值。

```python
@dataclass
class FillRecord:
    fill_id: str
    order_id: str
    signal_id: str

    fill_price: float
    fill_quantity: float
    fill_time: datetime
    fee_amount: float
    fee_currency: str

    execution_reference_level: float
    execution_reference_atr_15m: float
    actual_fill_deviation: float
    adverse_fill_deviation: float
    adverse_fill_deviation_atr: float | None
    deviation_status: str  # VALID / INVALID_ATR / BREACH

@dataclass
class StopUpdateRecord:
    stop_update_id: str
    position_id: str
    calculated_at: datetime
    stop_update_atr_15m: float
    candidate_stop_price: float
    previous_effective_stop: float
    resulting_effective_stop: float
    activation_time: datetime | None
    status: str  # CALCULATED / PENDING / ACTIVE / REJECTED / EMERGENCY_EXIT

@dataclass
class ExecutionRecord:
    signal_id: str
    order_id: str

    execution_reference_price: float
    execution_reference_level: float

    fills: list[FillRecord]
    actual_fill_price: float | None  # 最近一笔 Fill 价格，仅作展示，不用于累计风险计算
    actual_average_entry_price: float | None
    filled_quantity: float
    remaining_quantity: float

    actual_fill_deviation: float | None  # 按所有 Fill 数量加权的有符号平均偏差
    actual_fill_deviation_atr: float | None  # 所有有效 Fill 中最大的单笔不利偏差 ATR
    fill_deviation_breach: bool
    execution_reference_atr_15m: float
    initial_stop_atr_15m: float | None  # 首笔 Fill 后设置，之后不可修改
    stop_updates: list[StopUpdateRecord]  # 每次止损更新的 ATR 快照与生效状态

    order_submit_time: datetime | None
    first_fill_time: datetime | None

    terminal_reason: str | None
```

`fills` 按交易所成交时间和 Fill ID 稳定排序。`actual_average_entry_price` 按全部有效 Fill 的数量加权计算。订单级 `actual_fill_deviation` 是各 Fill 有符号偏差的数量加权平均；订单级 `actual_fill_deviation_atr` 是所有有效 Fill 的最大单笔不利偏差 ATR，不能用平均值掩盖单笔超限。若任一 Fill 的参考 ATR 无效，其 `adverse_fill_deviation_atr = None`、`deviation_status = INVALID_ATR`，并触发 12.8 的异常处理。
---

# 21. 回测与验证规范

## 21.1 回测版本

每次回测保存：

- 策略版本。
- 参数版本。
- 数据集版本。
- 成本模型版本。
- 合约元数据版本。
- Funding 数据 Hash。
- 代码 Git Commit。
- 初始状态快照 Hash。

## 21.2 随机片段测试

随机片段不得直接作为全新策略状态启动。

必须先从片段起点之前的历史数据回放，生成完整初始状态快照。

快照必须包含：

- 所有周期 ATR、SMA 状态。
- ZigZag 候选点和已确认 SwingPoint。
- N 结构状态。
- Zone 状态及版本。
- 宏观状态。
- ProtectedLow。
- ProtectedHigh。
- PullbackOriginHigh。
- Setup 状态。
- 未完成 Signal。
- 持仓和订单状态。
- 成本与元数据版本。

## 21.3 最低历史数据要求

初始建议最低历史 Bar 数：

| 周期 | 建议最低历史 Bar 数 |
|---|---:|
| 1MONTH | 36 |
| 1W | 52 |
| 1D | 100 |
| 4H | 200 |
| 1H | 300 |
| 15M | 500 |
| 3M | 1000 |

还必须满足：

1. SMA22 已完成预热。
2. ATR14 已完成预热。
3. ZigZag 至少确认足够数量的 SwingHigh 和 SwingLow。
4. Zone 锚点可以完成有效初始化。
5. 所有必要状态均已明确，不处于无法解释的半初始化状态。
6. 由于 `zone.max_age_weeks = 52`，随机片段起点必须具备完整的最近 52 周 Zone 锚点历史；或者使用经过全历史回放验证的可信快照。可信快照必须包含每个存续 Zone 的完整状态、Zone ID/版本、全部当前有效锚点的 SwingPoint ID、价格、极性、周期、`occurred_at`、`confirmed_at`，以及锚点纳入/剔除状态；仅包含 Zone 中心、上下边界或锚点数量的快照不可信，不能用于验证 52 周最大年龄。
7. 不得仅用表中最低 Bar 数截断 52 周 Zone 锚点历史后，仍将该片段标记为有效测试。

如果任一周期不满足，或 Zone 历史/快照不完整：

`SnapshotStatus = INSUFFICIENT_HISTORY`

该快照不得用于有效随机片段测试。

## 21.4 确定性要求

相同数据、配置、初始快照和代码版本必须产生：

- 相同 SwingPoint。
- 相同 Zone。
- 相同状态转换。
- 相同 Setup。
- 相同 Signal。
- 相同订单决策。

禁止依赖线程调度顺序或未定义集合遍历顺序。

---

# 22. 回测统计

## 22.1 趋势状态

- 各状态 Bar 数量。
- 状态持续时间。
- 状态转换次数。
- 状态转换误差。
- UNKNOWN 占比。

## 22.2 RANGE

- RANGE 总样本数。
- RANGE 平均持续时间。
- RANGE 与趋势整理重叠的人工复核比例。
- RANGE 误判为趋势的比例。
- 趋势误判为 RANGE 的比例。

## 22.3 Setup

- Setup4H 创建数。
- Setup1H 创建数。
- Setup 超时数。
- Setup 结构失效数。
- Zone 失效数。
- Zone 版本修订数。
- 观察区宽度不足导致的拒绝数。
- `SETUP1H_NO_INTERSECTION` 次数。
- `SETUP1H_INTERSECTION_TOO_NARROW` 次数。

## 22.4 Signal

- BREAKOUT_CONTINUATION 数量。
- PULLBACK_CONTINUATION 数量。
- `SignalCandidateRejected` 事件数量及拒绝原因分布。
- Signal CANCELLED 数量。
- Signal EXPIRED 数量。
- 部分成交数量。
- 完整成交数量。
- ACTIVE 状态下 `partially_filled = False` 与 `partially_filled = True` 的数量及持续时间。
- 因 PullbackLow 不在观察区容差内而拒绝的数量。
- 因固定 TriggerSwingHigh 偏低、后续突破旧触发价而提前触发的比例：统计窗口从 TriggerSwingHigh.confirmed_at 之后开始，至以下最早事件为止：Signal 创建、PullbackLow 更新、15M N 结构失效或该候选按 Signal15M Max Bars 超时。若窗口内出现 confirmed_at 晚于原 TriggerSwingHigh 的更高 SwingHigh，且其价格高于原 trigger_reference_price，则记为“存在后续更高 SwingHigh”；统计此类样本占全部 PULLBACK_CONTINUATION Signal 的比例。该指标仅用于诊断，不得据此动态替换触发点。
- TriggerSwingHigh 最小反弹幅度过滤的拒绝数量及通过率。
- HigherLow 位于观察区上沿之外但 PullbackLow 在观察区内的有效信号数量。

## 22.5 3M 执行

- 3M 确认成功率。
- 因无信号后 SwingLow 超时的比例。
- 因无信号后 SwingHigh 超时的比例。
- 平均执行延迟。
- 成交延迟导致的 `execution_reference_atr_15m` 与成交时 ATR 偏差分布（绝对值、比例及分位数）。
- 追价拒绝比例。
- 跳空拒绝比例。
- 实际成交偏差超限比例。
- `FILL_DEVIATION_BREACH` 次数。
- 因成交偏差超限取消的剩余入场订单数量。
- `ACTUAL_RISK_BUDGET_BREACH` 次数。
- 快速突破放弃比例。

## 22.6 风险

- 初始风险预算。
- 实际风险。
- 风险预算超限次数。
- 风险升级次数。
- 风险升级平均持续时间。
- 风险升级解除次数。
- 1H 与 4H 风险恢复连续计数的分布、重置次数及未满足原因。
- 止损跳空次数。
- Bar Low 以下保守模拟成交次数。
- 部分成交后止损重算次数。
- 部分成交后 StopQuantity 与 PositionQuantity 不一致次数（必须为 0）。
- 风险预算超限减仓次数及减仓后仍超限次数。

---

# 23. 开发顺序

## P0：基础设施与确定性

### P0-A：Bar 与时间

完成：

- BarIdentity。
- UTC 时间标准。
- Bar 完成检测。
- 多周期聚合。
- 统一时间快照。

### P0-B：ZigZag

完成：

- ATR14。
- 候选极值。
- ATR 冻结。
- SwingPoint 确认。
- 增量与批量一致性测试。

### P0-C：Swing 与 N 结构

完成：

- HH/HL/LH/LL。
- ProtectedLow。
- ProtectedHigh。
- PullbackOriginHigh。
- 多头 N。
- 结构失效及 `n_structure_break_buffer_atr` 参数化。
- 结构 ID。
- 15M PreviousProtectedLow 与 NStructure.L2 的引用一致性。
- 回放一致性测试。

### P0-D：Zone

完成：

- CREATED 聚类。
- ACTIVE 激活。
- TESTED 测试。
- ACTIVE 直接 BROKEN。
- TESTED BROKEN。
- INVALIDATED。
- Zone 版本。
- Zone 年龄。
- Setup 观察区联动规则。

### P0-E：人工黄金样本与快照

完成：

- 多周期人工标注。
- 状态转换标注。
- ProtectedHigh 标注。
- 边界案例。
- 3M 信号后时序案例。
- 历史预热快照。
- 随机片段初始状态。

P0-E 完成前，不进入 P1-A 状态机正式编码。PB-01 至 PB-51 必须全部纳入自动化黄金样本；任何一项未实现、未执行或未通过，P0-E 均不得判定完成。

### P0-F：成本与元数据

完成：

- 费率版本。
- Funding 数据。
- 滑点模型。
- 合约元数据。
- 成本一致性测试。
- REQUIRED 配置门禁。

## P1：策略状态机与信号

### P1-A：多周期状态机

完成：

- 1MONTH。
- 1W。
- 1D。
- 4H。
- 1H。

对照人工黄金样本验收。

### P1-B：Setup

完成：

- Setup4H。
- Setup1H。
- 回撤低点选择。
- 观察区交集。
- 生命周期。
- Zone 版本同步。
- EXPIRED / INVALIDATED 传播。

### P1-C：15M Signal

完成：

- BREAKOUT_CONTINUATION。
- PULLBACK_CONTINUATION。
- 15M 回撤起点识别。
- 15M 触发 SwingHigh。
- N 结构位置校验。
- 唯一性。
- Signal 生命周期。

### P1-D：3M Execution

完成：

- 3M 分形。
- 信号后 SwingLow。
- 信号后 SwingHigh。
- 突破 Bar 时序。
- 执行确认。
- 追价限制。
- 成交偏差审计。

## P2：风险与订单

完成：

- 仓位计算。
- 成本风险。
- 固定止损实际均价重算。
- 结构止损。
- 移动止损。
- 风险升级和解除。
- 风险预算超限处置。
- 部分成交。
- 止损成交模型。
- PositionManager。

## P3：组合验证

完成：

- 完整历史回测。
- 分市场阶段回测。
- 随机片段回测。
- 参数敏感性分析。
- 成本压力测试。
- 滑点压力测试。
- 样本外验证。

---

# 24. 冻结条件

V1.4.8 不应仅因代码可以运行就视为完成。

必须同时满足：

1. P0-A 至 P0-F 通过测试。
2. ProtectedLow 和 ProtectedHigh 生命周期可确定性复现。
3. 所有周期状态机通过人工黄金样本验收。
4. Zone 状态转换没有遗漏。
5. Setup 生命周期没有错误传播。
6. 15M 两类信号的触发 SwingPoint 可唯一确定；BREAKOUT 的 `trigger_swing_id` 为空，PULLBACK 的触发 SwingPoint ID 必填。
   6a. PULLBACK 的观察区位置校验只针对 PullbackLow；PullbackLow 更新时 TriggerSwingHigh 与 HigherLow 全部失效。
   6b. TriggerSwingHigh 最小反弹幅度参数、Zone 最小锚点 FIXED 约束和 Setup1H 宏观权限约束通过回归测试。
7. 3M 执行严格遵守 Signal 后确认和突破时序。
8. 3M 不产生独立方向或入场信号。
9. 回测不存在未来数据引用。
10. Bar 回测成交价格与订单时间约束一致。
11. 固定止损按实际成交均价重算。
12. 止损单只能从生效后的 Bar 开始触发。
13. 实际成交风险处置闭环完整。
14. REQUIRED 配置缺失时启动门禁有效，RESEARCH 参数实际值可追溯。
15. 成本模型、滑点模型和合约元数据版本可追溯。
16. 实际成交偏差检测、剩余订单撤销和风险预算联动闭环完整。
17. 部分成交后保护性止损数量不大于实际持仓数量。
18. 相同输入可以确定性复现。
    18a. ACTIVE Signal 的 `partially_filled` 能区分未成交与部分成交状态。
    18b. 风险恢复要求 1H 连续 3 根 BULLISH、4H 连续 2 根 TREND_UP；升级触发 Bar 不计数，从下一根完整 Bar 起算，计数中断立即重置。
    18c. 任意已成交 Signal 的剩余订单终止后必须进入 PARTIALLY_EXECUTED；EXPIRED/CANCELLED 仅允许零成交 Signal。
    18d. 所有 15M ATR 决策和止损计算均有明确快照来源；无效 ATR 不得计算倍数或静默替代。
    18e. 初始止损及部分成交后止损必须低于当前可执行退出价格，否则触发紧急退出/风险异常。
    18f. ExecutionRecord 保留全部 FillRecord，任一 Fill 的偏差超限不得被订单累计均价掩盖。
    18g. 风险预算减仓使用不含已发生入场费用的 CurrentRiskPerUnit。
    18h. CanOpen 与 CanHold 分离；风险恢复使用 CanHold，禁止以 CanOpen 替代持仓许可。
    18i. 每笔 Fill 独立审计，订单级最大单笔不利偏差不得被累计均价掩盖。
    18j. `initial_stop_atr_15m` 首笔成交后不可修改；每次止损更新必须保存 `stop_update_atr_15m`。
19. 随机片段测试使用有效初始状态快照。

完成以上条件后，才能冻结策略规格并进入完整策略回测阶段。

---

# 25. 版本结论

V1.4.8 在完整保留 V1.4.7 架构和策略主链的基础上，进一步修订以下实现定义：

- 15M 回撤延续统一引用当前有效 N 结构 L2，不引入独立 15M ProtectedLow。
- TriggerSwingHigh 采用 PullbackLow 确认后第一个满足时序和最小反弹幅度条件的已确认 SwingHigh，且本轮回撤内不漂移。
- PullbackLow 更新时旧 TriggerSwingHigh 作废并重新等待。
- 实际成交偏差有明确计算、事件记录、剩余订单撤销和风险预算联动。
- N 结构失效缓冲统一参数化。
- 1H PULLBACK、ProtectedHigh 生命周期和状态映射明确。
- SignalReferenceClose、执行参考价和 ATR 快照字段明确。
- REQUIRED 与 RESEARCH 分类统一，参数初始值不再与启动门禁冲突。
- 3M 信号后 SwingPoint 严格时序和快速行情过滤边界明确。
- 移动止损首根完整 15M Bar、部分成交止损数量和风险预算减仓公式明确。
- 风险恢复计数按连续完成 Bar 计算，计数中断即重置。

**开发建议：**

V1.4.8 可作为 P0-D Zone 和 P0-E 人工黄金样本的规格基线。P0-D、P0-E 可按本版定义继续执行；P1-A 须在 PB-01 至 PB-51 全部自动化黄金样本通过，且人工标注一致率达到工程验收门槛后准入。P0-D/P0-E 已产生的结果如依赖旧版 Zone Min Anchors、旧版 15M 回撤延续规则或旧版 Signal 终态规则，必须按 V1.4.8 重新核对。

P1-A 状态机实现必须以人工标注结果和本文件状态定义为验收依据，不允许在编码过程中自行改变状态定义、结构引用、信号触发顺序、ATR 快照时点或执行时间边界。

本版本冻结仅代表规格具有可实现性，不代表策略收益已经验证。参数初值、Zone 聚类宽度、3M 执行过滤、成交偏差阈值和风险参数仍需通过样本内、样本外、成本敏感性及压力测试确认。
