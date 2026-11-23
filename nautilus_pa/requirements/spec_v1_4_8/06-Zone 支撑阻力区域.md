# SPEC-V148-06｜Zone 支撑阻力区域

> **文档状态：** 扩充结构化规格；本文件属于唯一权威规格的一章。原始规格仅作归档迁移来源。

## 1. 文档元数据

- 文档 ID：`SPEC-V148-06`（章节文档 ID，不是项目 REQ ID）
- 版本：V1.4.8 扩充版
- 原规格章节：第 6 章
- 状态：NORMATIVE，除显式 OPEN_DECISION 外按本章规范执行

## 2. 目标与范围

- **目标：** 规范 ETH-USDT-SWAP 多周期趋势策略的“Zone 支撑阻力区域”行为与数据契约。
- **范围：** 本章原规则及已确认补充要求。
- **非目标：** 不推断未确认的策略收益或运行行为。

## 3. 规范性要求

原文条款与本扩充版补充要求共同构成规范；发生冲突时本扩充版的明确决定优先，其他冲突登记 OPEN_DECISIONS，不猜测。

### 3.1 原规格条款（迁移保留）

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


### 3.2 已确认补充要求

- **SPEC-V148-06-ADD-01：** 每次 Zone 决策使用触发该决策的已完成 Bar ATR，并将值与 source_bar_id 记入不可变 Zone 版本快照；这不是固定 Zone 创建 ATR。内部价格/边界保留精确值，不隐式 tick 舍入；仅订单价格按交易所 tick 规则量化。

## 4. 数据与状态契约

- 原文定义见第 3.1 节；新增约束见第 3.2 节。
- 本章决策依赖章节：[05](./05-Swing 结构与保护点.md)、[10](./10-Setup 生命周期.md)、[11](./11-15M 信号系统.md)、[21](./21-回测与验证规范.md)。
- 所有有损失风险的行为不得由未决规则推导；未决项见 [OPEN_DECISIONS.md](./OPEN_DECISIONS.md)。

## 5. 验收要求

- 本章原有规则、公式、状态转换和适用样例均须测试覆盖。
- 新增条款须有可追溯断言、黄金样本或审计证据。
- 整体冻结门槛见 [24](./24-冻结条件.md)，数据验收见 [07](./07-数据标注与黄金样本.md) 与 [21](./21-回测与验证规范.md)。

## 6. 依赖与交叉引用

- 相关章节：[05](./05-Swing 结构与保护点.md)、[10](./10-Setup 生命周期.md)、[11](./11-15M 信号系统.md)、[21](./21-回测与验证规范.md)。
- 项目级需求追踪使用 `REQ-NNN`，不得与 `SPEC-V148-NN` 混用。

## 7. 未决项

- 业务选择集中登记于 [OPEN_DECISIONS.md](./OPEN_DECISIONS.md)；未决项不构成批准规则。
