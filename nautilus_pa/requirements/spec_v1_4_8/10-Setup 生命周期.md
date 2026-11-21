# SPEC-V148-10｜Setup 生命周期

> **文档状态：** 扩充结构化规格；本文件属于唯一权威规格的一章。原始规格仅作归档迁移来源。

## 1. 文档元数据

- 文档 ID：`SPEC-V148-10`（章节文档 ID，不是项目 REQ ID）
- 版本：V1.4.8 扩充版
- 原规格章节：第 10 章
- 状态：NORMATIVE，除显式 OPEN_DECISION 外按本章规范执行

## 2. 目标与范围

- **目标：** 规范 ETH-USDT-SWAP 多周期趋势策略的“Setup 生命周期”行为与数据契约。
- **范围：** 本章原规则及已确认补充要求。
- **非目标：** 不推断未确认的策略收益或运行行为。

## 3. 规范性要求

原文条款与本扩充版补充要求共同构成规范；发生冲突时本扩充版的明确决定优先，其他冲突登记 OPEN_DECISIONS，不猜测。

### 3.1 原规格条款（迁移保留）

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


### 3.2 已确认补充要求

- **SPEC-V148-10-ADD-01：** Setup/Signal 有效期从创建完成 Bar 后的下一根完整同周期 Bar 开始计数；到达最大计数的 Bar 收盘后过期，创建 Bar 不计。Signal 仅代表入场执行，已成交仓位始终由 PositionManager/RiskManager 决策，终态不替代持仓退出规则。

## 4. 数据与状态契约

- 原文定义见第 3.1 节；新增约束见第 3.2 节。
- 本章决策依赖章节：[06](./06-Zone 支撑阻力区域.md)、[08](./08-宏观趋势状态机.md)、[09](./09-4H 与 1H 状态机.md)、[11](./11-15M 信号系统.md)、[12](./12-3M 执行确认.md)、[20](./20-核心数据结构.md)。
- 所有有损失风险的行为不得由未决规则推导；未决项见 [OPEN_DECISIONS.md](./OPEN_DECISIONS.md)。

## 5. 验收要求

- 本章原有规则、公式、状态转换和适用样例均须测试覆盖。
- 新增条款须有可追溯断言、黄金样本或审计证据。
- 整体冻结门槛见 [24](./24-冻结条件.md)，数据验收见 [07](./07-数据标注与黄金样本.md) 与 [21](./21-回测与验证规范.md)。

## 6. 依赖与交叉引用

- 相关章节：[06](./06-Zone 支撑阻力区域.md)、[08](./08-宏观趋势状态机.md)、[09](./09-4H 与 1H 状态机.md)、[11](./11-15M 信号系统.md)、[12](./12-3M 执行确认.md)、[20](./20-核心数据结构.md)。
- 项目级需求追踪使用 `REQ-NNN`，不得与 `SPEC-V148-NN` 混用。

## 7. 未决项

- 业务选择集中登记于 [OPEN_DECISIONS.md](./OPEN_DECISIONS.md)；未决项不构成批准规则。
