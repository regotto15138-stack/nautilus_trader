# SPEC-V148-06｜Zone 支撑阻力区域

> **文档状态：** 扩充结构化规格；本文件属于唯一权威规格的一章。原始规格仅作归档迁移来源。

## 1. 文档元数据

- 文档 ID：`SPEC-V148-06`（章节文档 ID，不是项目 REQ ID）
- 版本：V1.4.8-ZONE-R1 修订候选版
- 原规格章节：第 6 章
- 状态：REVIEW_CANDIDATE；保留原已批准规则，新增/变更策略语义待冻结审批

## 2. 目标与范围

- **目标：** 规范 ETH-USDT-SWAP 多周期趋势策略的“Zone 支撑阻力区域”行为与数据契约。
- **范围：** 本章原规则及已确认补充要求。
- **非目标：** 不推断未确认的策略收益或运行行为。

## 3. 规范性要求

原文条款与本扩充版补充要求共同构成规范；发生冲突时本扩充版的明确决定优先，其他冲突登记 OPEN_DECISIONS，不猜测。

### 3.1 第 6 章修订后的规范性条款（替代原 6.1—6.10）

# 6. Zone 支撑阻力区域

## 6.1 类型、身份和输入

- 类型仅为 `SUPPORT`（确认 SwingLow）与 `RESISTANCE`（确认 SwingHigh）。每个 Zone 仅接受同一 `timeframe`、同一类型的**已确认** SwingPoint，禁止跨周期、跨类型合并。
- SwingPoint 的唯一身份使用 `(timeframe, swing_id)`；同一 Swing 不得重复计数，也不得同时归属于两个非终态 Zone。若输入重放，处理必须幂等。
- 每次决策只使用该事件时点已完成 Bar 的数据及 ATR；`source_bar_id`、`ATR_TF`、`config_version`、锚点集合与处理结果均写入不可变快照。缺失、非有限或 `ATR_TF <= 0` 时不进行价格相关判定，输出 `ZONE_INPUT_INVALID` 并按系统数据质量门禁处理；不得用未来 ATR 或创建时固定 ATR 替代。
- `zone_id` 在整个生命周期内稳定；Zone 终态后不得复活，也不得吸收新锚点。

## 6.2 状态与事件优先级

| 当前状态 | 事件 | 下一状态 |
|---|---|---|
| CREATED | 有效锚点数达到 `min_anchor_count` 且几何合法 | ACTIVE |
| CREATED | 锚点全部失效、结构失效或超龄 | INVALIDATED |
| ACTIVE | 收盘有效突破 | BROKEN |
| ACTIVE | 首次有效测试且未突破 | TESTED |
| ACTIVE | 有效锚点不足、结构失效或超龄 | INVALIDATED |
| TESTED | 收盘有效突破 | BROKEN |
| TESTED | 再次有效测试且未突破 | TESTED |
| TESTED | 有效锚点不足、结构失效或超龄 | INVALIDATED |

`BROKEN`、`INVALIDATED` 为终态；`CREATED` 不进行 TESTED/BROKEN 判定。**ACTIVE → BROKEN 直接有效，不要求先 TESTED。**

单一已完成 Bar 的处理次序：①校验输入和时间顺序；②依据上一有效快照的边界判断突破；③若未突破，处理已确认锚点的到期/失效及新锚点归属，重算几何并检查失效；④若仍处于 ACTIVE/TESTED，使用更新后的边界判断测试；⑤发布一次原子状态/版本结果。突破优先于同 Bar 测试及到期失效，避免失效先吞掉已发生的突破。相同 `source_bar_id` 重放不得再次改变版本。**同 Bar 新增锚点不得回溯改变本 Bar 的突破阈值。**

## 6.3 CREATED 聚类与归属

对每个新确认锚点，搜索同周期、同类型的 `CREATED`、`ACTIVE`、`TESTED` Zone；不搜索终态。仅在新锚点未被其他非终态 Zone 认领时处理。

候选必须**同时**满足（基于本次决策 ATR）：

1. `abs(new_price - zone.center) <= merge_distance_atr * ATR_TF`；
2. `max(P ∪ {new_price}) - min(P ∪ {new_price}) <= max_cluster_width_atr * ATR_TF`；
3. 将新锚点加入后按 6.4 计算的几何仍满足 `max_half_width_atr * ATR_TF` 硬上限；
4. 归属后不得违反唯一性和年龄条件。

推荐初始配置将 `max_cluster_width_atr` 从 `1.0` 收紧至 `0.5`；`merge_distance_atr` 作为独立可配置阈值，必须满足 `0 < merge_distance_atr <= max_cluster_width_atr`。二者是初始研究参数，**不是已经验证的最优值**。

多个候选合格时依次按新锚点与旧中心的绝对距离、Zone 创建时间升序、`zone_id` 字典序排序，取第一个；无候选时新建 `CREATED`。不得以单链相邻距离代替**整个锚点集合**的直径约束；不得因为候选不合格而强制并入最近 Zone。处理同一 Bar 多个新锚点时按 `(confirmed_at, swing_id)` 稳定排序。不得自动合并两个已有 Zone；若未来需要 Zone-to-Zone 合并，另立规范。

## 6.4 Zone 几何与上限

设有效锚点价格多重集 `P`，`center = median(P)`（偶数个取两个中位数算术平均）。

- `anchor_radius = max(max(P)-center, center-min(P))`；
- `base_half_width = max(min_half_width_ticks * tick_size, zone_half_width_atr * ATR_TF)`；
- `required_half_width = max(base_half_width, anchor_radius)`；
- `half_width_cap = max_half_width_atr * ATR_TF`；
- 仅当 `required_half_width <= half_width_cap` 时几何有效；此时 `half_width = required_half_width`，`lower = center-half_width`，`upper = center+half_width`。

**禁止**使用 `min(required_half_width, half_width_cap)` 静默裁剪，因为可能排除合法锚点。新锚点使几何不合法时拒绝本次合并并另建 CREATED；现有 Zone 因 ATR 下降而不满足上限时，不能静默缩窄或删除锚点，须输出 `ZONE_GEOMETRY_LIMIT_EXCEEDED` 并按 6.8 的保守失效规则处理。

原式 `(max(P)-min(P))/2` 在 `median(P)` 不等于极值中点时**不能保证覆盖全部锚点**，因此由 `anchor_radius` 替代。内部计算使用精确价格，不隐式按 tick 舍入；仅交易所订单价格按订单规范量化。

参数启动校验：`tick_size > 0`、`min_half_width_ticks > 0`、`zone_half_width_atr > 0`、`max_half_width_atr > 0`、`max_cluster_width_atr > 0`、`zone_test_tolerance_atr >= 0`、`break_buffer_atr >= 0`，且 `max_half_width_atr >= zone_half_width_atr`；不满足则拒绝启动。若 `min_half_width_ticks*tick_size > half_width_cap`，当前事件几何不可行，按输入/几何异常处理而非强行越限。

## 6.5 ACTIVE 条件

`min_anchor_count = 2` 为 FIXED 规则，两个不同 `swing_id` 才可激活，禁止配置为 1。满足有效锚点数、聚类直径与几何上限后，`CREATED → ACTIVE`。CREATED 可继续接收锚点，避免只搜索 ACTIVE 导致创建死锁。

## 6.6 测试判定

`tol = zone_test_tolerance_atr * ATR_TF`。只在已完成 Bar 上判断，且须未满足 6.7 的突破条件。

- SUPPORT：`Low <= upper + tol` 且 `Low >= lower - tol`，并且 `Close >= lower - tol`。
- RESISTANCE：`High >= lower - tol` 且 `High <= upper + tol`，并且 `Close <= upper + tol`。

取消 SUPPORT 的 `Close > center` 和 RESISTANCE 的 `Close < center` 要求，允许在区域内部收盘仍构成有效测试；保留收盘不得明显穿出外边界的约束。测试仅表示价格触及且未确认突破，**不等价于强反弹或入场许可**。若需识别强拒绝形态，应由 Setup/Signal 独立评估。

测试采用单 Bar 极值的明确条件，不能以 `Low < lower-tol` 但 Bar 区间穿过 Zone 的情况自动认定有效测试；这类深刺破的额外语义若要支持，应单独定义。测试同一 `source_bar_id` 仅记录一次；TESTED 自循环只有新增审计事件时才需要新版本，不得空转递增。

## 6.7 有效突破

- SUPPORT：`Close < lower - break_buffer_atr * ATR_TF`；
- RESISTANCE：`Close > upper + break_buffer_atr * ATR_TF`。

严格不等号：恰好等于阈值不算突破。优先于 TESTED，且 ACTIVE 可以直接 BROKEN。比较使用 6.2 规定的**本 Bar 处理前有效边界快照**和本 Bar ATR，记录参与比较的边界、阈值、ATR、Bar ID。BROKEN 不自动翻转为另一类型 Zone。

## 6.8 年龄、锚点清理和保守失效

`zone_max_age_weeks` 为配置项，初始默认 `52`，须为正数；锚点年龄以 `confirmed_at` 为起点，使用 UTC 时间差 `age > zone_max_age_weeks * 7 * 24h` 判定超龄（等于阈值时保留）。锚点逐一清理，不能因加入新锚点而刷新旧锚点年龄。

新增 `zone_max_lifetime_weeks`（可配置，默认 `52`，须为正数），以 Zone `created_at` 为起点，限制整个 Zone 被持续加入锚点后无限延寿；`age > lifetime` 则 INVALIDATED。寿命与锚点年龄相互独立。清理后锚点不足 2 个、结构明确失效、或既有几何无法在当前有效 ATR 下满足硬上限时，非终态 Zone 转 INVALIDATED，并输出明确 `reason_code`。**不允许在未定义的拆分算法下自动把既有 ACTIVE Zone 分裂为多个 Zone。**

若 CREATED 在锚点清理后剩一个有效锚点，可保留 CREATED，直至该锚点失效或 Zone 寿命结束；ACTIVE/TESTED 少于 2 个则 INVALIDATED。终态不可重新聚类。

## 6.9 版本、快照和确定性

以下**实际变化**必须递增 `zone_version`：锚点增删、center/half_width/lower/upper 改变、状态变化。纯 ATR 更新若导致边界实际改变也须递增；完全无变化不递增。版本单调递增，快照不可变。

每个快照至少包含：`zone_id, zone_version, config_version, timeframe, zone_type, state, created_at, updated_at, anchor_ids, anchor_prices, center, half_width, lower, upper, atr_value, source_bar_id, transition_reason`。事件需可追溯至输入 Bar 和旧版本。对相同排序输入、配置及数据必须生成相同状态序列。

## 6.10 Zone 版本与 Setup / Signal

- Setup 尚未产生 15M Signal：Zone 有效版本变更时重新计算观察区，更新 `observation_zone_version`、`observation_lower`、`observation_upper`，发布 `SETUP_ZONE_REVISED`；若 Zone BROKEN/INVALIDATED 则走既有失效传播契约，不能仅修订边界。
- Setup 已产生 Signal：Signal 保留创建时的不可变 Zone 快照，不得静默修改观察区；普通边界变化不追溯改变 Signal；Zone 后续 BROKEN/INVALIDATED 仍按跨章节既定失效传播规则处理。
- 发布事件应包含 `(zone_id, old_version, new_version, event_type, source_bar_id)`；消费方须幂等，并不得用未来版本重写历史决策。

## 6.11 参数表（新增）

| 参数 | 初始值 | 类型 | 说明 |
|---|---|---|---|
| `min_anchor_count` | 2 | FIXED | 不允许降为 1 |
| `max_cluster_width_atr` | 0.5 | RESEARCH | 从 1.0 收紧，需回测 |
| `merge_distance_atr` | 待与原配置核对 | CONFIG | 必须 >0 且 <= max_cluster_width_atr |
| `zone_half_width_atr` | 沿用原配置 | CONFIG | 基础半宽系数 |
| `max_half_width_atr` | 待校准 | RESEARCH | 半宽硬上限；未配置禁止启用本修订算法 |
| `min_half_width_ticks` | 沿用原配置 | CONFIG | 最小 tick 半宽 |
| `zone_test_tolerance_atr` | 沿用原配置 | CONFIG | 测试容差 |
| `break_buffer_atr` | 沿用原配置 | CONFIG | 收盘突破缓冲 |
| `zone_max_age_weeks` | 52 | CONFIG | 单锚点最大年龄 |
| `zone_max_lifetime_weeks` | 52 | RESEARCH | Zone 整体寿命，需敏感性分析 |

未在上传文档中给出的原配置数值不擅自补造。`max_half_width_atr` 与 `merge_distance_atr` 等必须在部署配置中显式确认；参数未确认前不得视为生产冻结。

## 6.12 验收断言与黄金样本（新增）

1. 两个不同确认 SwingLow 可从 CREATED 激活；同一 `swing_id` 重放不得激活或重复计数。
2. 锚点价格 `[100,101,110]` 时，`median=101`，`anchor_radius=9`；不得误用半极差 5 以致遗漏 110。
3. 新锚点满足中心距离但使总直径超过 `0.5*ATR` 时必须创建独立 CREATED，原 Zone 不变。
4. 新锚点使 `required_half_width > cap` 时不得强行合并或裁剪边界。
5. SUPPORT Bar Low 进入 Zone、Close 在 `lower` 与 `center` 之间且未突破时允许 TESTED；RESISTANCE 对称。
6. ACTIVE 在首次接触 Bar 直接满足突破条件时进入 BROKEN，不能先 TESTED；同 Bar 测试与突破冲突时仅 BROKEN。
7. Bar Close 恰等于突破阈值时不得 BROKEN。
8. 单锚点超过 52 周被清理；新增锚点不得重置旧锚点年龄；Zone 超过整体寿命应 INVALIDATED。
9. ATR 下降导致既有 Zone 超过半宽上限时 INVALIDATED 并记录原因，不得静默裁剪。
10. 同一 Bar 重放、不同输入枚举顺序（经稳定排序后）应产生一致版本和结果。
11. Setup 在 Signal 前接收 Zone 版本变更；Signal 后冻结快照，BROKEN/INVALIDATED 仍触发失效传播。
12. 使用历史已完成 Bar ATR，禁止未来 Bar 值影响当期 Zone。
13. Zone 终态后新锚点不复活： 一个 Zone 进入 BROKEN 后，同价位新确认的 SwingLow 应创建新 Zone，旧 zone_id 不变更。
14. 多候选排序确定性： 同一 Bar 同一价格的两个候选 Zone，按创建时间→zone_id 排序后结果确定，不受输入顺序影响。
15. zone_max_lifetime_weeks 独立于锚点年龄生效： 构造一个 Zone 在所有锚点都未超龄但 Zone 整体寿命到期的场景，验证 INVALIDATED。
16. CROSS-TYPE 隔离： 一个 SwingHigh 锚点不会触发 SwingLow Zone 的聚类搜索。

### 3.2 已确认补充要求及修订说明

- **SPEC-V148-06-ADD-01（保留）：** 每次 Zone 决策使用触发该决策的已完成 Bar ATR，并将值与 `source_bar_id` 记入不可变 Zone 版本快照；不固定使用 Zone 创建 ATR。内部价格/边界保留精确值，不隐式 tick 舍入；仅订单价格按交易所 tick 规则量化。
- **本次修订提案：** 6.3、6.4、6.6、6.8、6.11 所涉阈值与行为属于新增或改变的策略语义，须经回测/黄金样本及项目冻结流程确认；在确认前按候选规则管理，不应误标为既有业务已批准决定。

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

- `OD-ZONE-01`：确认 `max_half_width_atr` 生产值与不同周期是否独立配置。
- `OD-ZONE-02`：确认 `merge_distance_atr` 原值与收紧后默认值。
- `OD-ZONE-03`：批准或调整 `zone_max_lifetime_weeks=52`，评估长期趋势支撑区是否被过早淘汰。
- `OD-ZONE-04`：确认 `Low/High` 深刺破后收回的测试语义是否另增规则；本版不自动算测试。
- `OD-ZONE-05`：跨章节确认 Zone 终态事件如何影响已经产生的 15M Signal 与在途订单。
- `OD-ZONE-06`：ATR 下降导致 Zone 失效的合理性。 当前规则：ATR 下降 → half_width_cap 缩小 → 既有 Zone 可能超限 → INVALIDATED。但在低波动期 Zone 被强制失效是否符合交易逻辑？是否应该引入暂停状态而非直接终态？需要回测验证 ETH 上 ATR 下降导致 Zone 失效的频率和后续价格行为。
- 以上应同步登记于 [OPEN_DECISIONS.md](./OPEN_DECISIONS.md)；未决项不构成批准规则。
