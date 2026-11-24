# SPEC-V148-05｜Swing 结构与保护点

> **文档状态：** 扩充结构化规格；本文件属于唯一权威规格的一章。原始规格仅作归档迁移来源。

## 1. 文档元数据

- 文档 ID：`SPEC-V148-05`（章节文档 ID，不是项目 REQ ID）
- 版本：V1.4.8-SWING-R1 修订候选版
- 原规格章节：第 5 章
- 状态：REVIEW_CANDIDATE；继承原 NORMATIVE 条款，新增跨章冲突与未决交易行为不得视为已批准

## 2. 目标与范围

- **目标：** 规范 ETH-USDT-SWAP 多周期趋势策略的“Swing 结构与保护点”行为与数据契约。
- **范围：** 本章原规则及已确认补充要求。
- **非目标：** 不推断未确认的策略收益或运行行为。

## 3. 规范性要求

本修订以原 V1.4.8 为基线；已确认原条款继续有效，本文明确修订的条款优先。跨章冲突须登记 OPEN_DECISIONS，未经批准不得推导交易行为。

### 3.1 修订后的规范性条款（基于原规格）

# 5. Swing 结构与保护点

## 5.1 基础结构与确认顺序

- HH：新确认 SwingHigh 严格高于前一个同周期已确认 SwingHigh；HL：新确认 SwingLow 严格高于前一个同周期已确认 SwingLow。
- LH：新确认 SwingHigh 严格低于前一个同周期已确认 SwingHigh；LL：新确认 SwingLow 严格低于前一个同周期已确认 SwingLow。
- 只使用第 04 章确认完成的 SwingPoint。`pivot_at` 表示极值发生时间，`confirmed_at` 表示算法确认时间；所有可交易状态变更以 `confirmed_at` 为准，不允许用回填的 `pivot_at` 提前产生事件。
- 同一周期内比较价格必须使用同类型、按确认顺序确定的前一有效 SwingPoint；相等价格不构成 HH/HL/LH/LL。SwingPoint ID 必须唯一且幂等；不得将不同周期的 Swing 混合构成同一结构。
- 同一确认时间有多个 Swing 时，按第 04 章的确定性事件顺序处理；若第 04 章未定义冲突裁决，标记 `OPEN_DECISION-SWING-ORDER`，禁止据此产生交易许可。

## 5.2 ProtectedLow（多头保护点）

`ProtectedLow` 是当前有效多头趋势中最近一个**已完成有序确认、承担保护作用**的 HL SwingLow。

**初始化（顺序必须成立）：**

1. 在当前周期先确认一个 HL SwingLow（候选保护点）。
2. 随后确认一个 HH SwingHigh，构成对该 HL 的趋势延续确认。
3. 仅在步骤 1、2 均完成后，将该 HL 设为 ProtectedLow；保存 `protected_low_swing_id`、`protected_low_price`、确认时间与来源 HH ID。
4. 未出现后续 HH 时，HL 仅为候选，不得提前作为 ProtectedLow；候选不具有止损或趋势保护效力。

**更新：**

1. 当前多头保护结构仍有效时，先确认新的 HL SwingLow。
2. 随后确认新的 HH SwingHigh。
3. 两者按顺序完整确认后，才允许将该 HL 更新为 ProtectedLow。
4. 必须满足 `NewProtectedLow.price > OldProtectedLow.price`；相等或更低均不更新，保留原 `protected_low_swing_id`。
5. 只使用已确认 SwingPoint；候选低点不得替代当前保护点。若候选结构失败，当前保护点仍按原规则监测失效。

**失效：**

`Close_TF < ProtectedLow.price - protected_break_buffer_atr × ATR_TF`

- 仅使用触发周期的已完成 Bar 收盘价和该 Bar 对应的有效 ATR；影线刺破不算失效。等号不构成失效。
- 失效后旧 ProtectedLow 永久不可复活；清除当前有效保护点引用，但保留历史快照与失效事件。重新建立必须等待新的有序 HL → HH 确认。
- 周期状态映射按 §5.3 的统一表执行；不得直接将保护点失效等同于反向趋势成立。

## 5.3 ProtectedHigh（空头保护点）与统一失效映射

`ProtectedHigh` 是当前有效空头趋势中最近一个已完成有序确认、承担保护作用的 LH SwingHigh。

**初始化：**

1. 先确认一个 LH SwingHigh。
2. 随后确认一个 LL SwingLow。
3. 完整确认后将该 LH 设为 ProtectedHigh。
4. 保存 `protected_high_swing_id`、`protected_high_price`、确认时间与来源 LL ID。

**更新：**

1. 当前空头保护结构有效时，先确认新的 LH SwingHigh。
2. 随后确认新的 LL SwingLow。
3. 仅在 LH → LL 均确认后允许更新。
4. 必须满足 `NewProtectedHigh.price < OldProtectedHigh.price`；相等或更高均不更新，不更换原 Swing ID。
5. 候选高点不能提前成为 ProtectedHigh。

**失效：**

`Close_TF > ProtectedHigh.price + protected_break_buffer_atr × ATR_TF`

- 仅已完成 Bar 收盘价触发；等号与单纯影线刺破不构成失效。
- 旧 ProtectedHigh 永久失效且不得复活；重新建立必须等待新的有序 LH → LL 确认。价格重新跌回旧点下方不恢复旧状态。

**统一映射（适用于 ProtectedLow 与 ProtectedHigh）：**

| 周期 | 任一当前有效保护点失效后的周期状态 |
|---|---|
| 1MONTH | UNKNOWN |
| 1W | TRANSITION |
| 1D | TRANSITION |
| 4H | TRANSITION |
| 1H | TRANSITION |

- 此表沿用原 ProtectedHigh 的映射并对称应用于 ProtectedLow；状态机仍须符合第 08、09 章。若对应章节定义了不一致的状态枚举或优先级，须登记跨章冲突，在解决前禁止该分支生成新的交易许可。
- 15M/3M 不适用此宏观/Setup 周期映射；15M 结构失效按 §5.6 和第 11 章，3M 不独立建立策略保护点。
- 双向保护点独立维护、共享 `protected_break_buffer_atr` 配置；禁止同一周期同时存在两个有效且相互矛盾的趋势保护点。方向切换须先按状态机使旧方向失效，再初始化新方向。

## 5.4 PullbackOriginHigh 与 PullbackOriginLow

- `PullbackOriginHigh`：有效多头趋势中，本次回撤开始前的最高**已确认** SwingHigh。
- `PullbackOriginLow`：有效空头趋势中，本次反弹/回撤开始前的最低**已确认** SwingLow，为多头定义的镜像。
- 两者统一记录 `pullback_origin_swing_id`、`pullback_origin_price`、`pullback_started_at`、`direction`、`timeframe`、`config_version`，并关联回撤所属 `structure_id`（若已存在）。
- 回撤开始后冻结本次起点，不得用回撤过程中新高/新低覆盖；只有回撤结束且形成新有效趋势阶段后才可建立下一次起点。
- 回撤开始/结束的具体触发条件由第 09 章定义。本章不新增阈值；如果第 09 章没有可执行定义，相关回撤起点标记为 `UNRESOLVED`，不得据此产生交易许可。
- PullbackOrigin 不是 ProtectedLow/High，也不是 N 结构的 L2/H2；仅在 Swing ID 实际相同时允许引用同一 SwingPoint，不能因价格接近而合并语义。

## 5.5 多头 N 结构

有序成员：`L1 → H1 → L2 → H2`，四个成员均为**同周期已确认** SwingPoint，且 `L1/L2` 为 SwingLow，`H1/H2` 为 SwingHigh。

- 以各成员 `confirmed_at` 严格递增为完成顺序，且 `L2.price > L1.price`、`H2.price > H1.price`。
- 不要求 `L2.price > H1.price`。价格相等不满足严格突破。
- **确认时点**：只有 H2 被确认的时刻，四点 N 结构才整体成立；L2 确认时只能形成候选，不得提前发出已确认 N 结构事件。
- 回撤比例 `Retracement = (H1.price - L2.price) / (H1.price - L1.price)`；要求分母严格大于 0，否则候选无效。对超出 `[0,1]` 的计算结果保留审计记录，但不擅自设立新的交易阈值；是否允许进入交易路径须由第 11 章明确。
- 交易性结构失效（仅 15M 多头）：`Close_TF < L2.price - n_structure_break_buffer_atr × ATR_TF`。该参数为 RESEARCH，初始值 `0.1`，仅以已完成 Bar 收盘判定，影线不算。
- 4H/1H N 结构仅 `RESEARCH_ONLY`，不得直接参与 Setup、Signal、持仓止损或交易性结构失效判定；不得复用 15M 交易参数。

## 5.6 空头 N 结构及适用边界

镜像有序成员：`H1 → L1 → H2 → L2`，其中 `H2.price < H1.price`、`L2.price < L1.price`，全部为同周期已确认 SwingPoint。

- **确认时点**：只有末端 L2 确认后，空头 N 结构才整体成立；之前仅为候选。
- 镜像反弹比例 `RetracementShort = (H2.price - L1.price) / (H1.price - L1.price)`；分母须严格大于 0，越界值仅审计，不擅自添加交易许可。
- 本章定义空头 N 结构用于对称结构识别；**原规格只批准了 15M 多头 N 的交易性失效参数**。空头 N 的交易性失效阈值、Setup/Signal 接入及退出行为均为 `OPEN_DECISION-SHORT-N-TRADING`，未跨章批准前不得使用推导的镜像公式自动下单或退出。
- 研究性结构的失效仅改变研究对象状态，不传播为交易事件；不得以“已定义空头结构”推定空头交易已获批准。

## 5.7 保护点与 N 结构锚点关系

| 对象 | 产生条件 | 作用 | 与 N 结构的关系 |
|---|---|---|---|
| ProtectedLow | 有序 HL → HH | 多头趋势保护 | 可能与多头 N 的 L2 引用同一 SwingLow，但**不自动等同** |
| ProtectedHigh | 有序 LH → LL | 空头趋势保护 | 可能与空头 N 的 H2 引用同一 SwingHigh，但**不自动等同** |
| 多头 N L2 | L1→H1→L2→H2 全部确认 | 15M N 失效锚点 | 不覆盖 ProtectedLow |
| 空头 N H2 | H1→L1→H2→L2 全部确认 | 空头研究锚点 | 不覆盖 ProtectedHigh |

- 趋势保护点只由 §5.2/§5.3 更新，N 结构锚点只由已冻结 N 成员定义；两者拥有独立 ID 引用、生命周期和失效判定。
- 若两套规则在同一 Bar 同时触发，各自记录事件；最终策略状态、Signal 取消与持仓退出优先级以第 08/09/11/15/24 章为准，不在本章虚构交易优先级。
- 已成交仓位的实际止损价格不直接等于 ProtectedLow/High 或 L2/H2；按第 15 章订单与可执行价格规则处理。

## 5.8 结构标识、版本与不可变快照

**结构对象最低数据契约：**

| 字段 | 约束 |
|---|---|
| `structure_id` | 非空、同一策略运行范围内唯一、不可复用的稳定标识 |
| `structure_type` | `BULL_N` / `BEAR_N` / 其他类型须由第 20 章定义 |
| `timeframe`、`instrument_id` | 必填，禁止跨标的、跨周期引用 |
| `direction` | `LONG` / `SHORT` |
| `swing_ids` | 有序成员 ID 列表，确认后不可变 |
| `pivot_at`、`swing_confirmed_at` | 各成员极值时刻与确认时刻，保持顺序及来源 |
| `confirmed_at`、`source_bar_id` | 结构完成确认时间及来源已完成 Bar |
| `state` | 候选、确认、失效状态；具体枚举需与第 20 章统一 |
| `structure_version`、`config_version` | 单调递增版本与产生时配置版本 |
| `invalidated_at`、`invalidation_reason` | 失效时必填，未失效可为空 |

**保护点快照最低数据契约：** `protection_id`、`direction`、`timeframe`、`instrument_id`、`swing_id`、`price`、`confirmed_at`、`effective_at`、`source_structure_id`（若存在）、`source_bar_id`、`protection_version`、`config_version`、`state`、`invalidated_at`、`invalidation_reason`。历史快照不可变；保护点初始化、更新、失效均生成新版本与审计事件。

- `structure_id` 在首次完整确认时分配；候选阶段使用独立 `candidate_id`，不得提前分配正式 ID。结构明确失效前不得为同一已确认结构重新分配 ID；新结构确认必须使用新 ID。
- 按 Swing 完成确认时序选择首个有效候选；同一事件重放不得重复创建结构或重复增加版本。`structure_id` 的具体编码可由工程实现决定，但唯一性、稳定性与可复现性必须满足。
- 结构确认后冻结成员；状态变化只新增版本，不原地修改历史成员或快照。保护点更新时新保护点拥有独立引用，旧版本留存以供审计。
- 计算缓冲使用触发判定的已完成 Bar ATR 与 `source_bar_id`，不得使用未来 ATR；ATR 无效、非正、缺失时禁止生成新的交易性失效判断并记录数据异常。内部价格比较不隐式按 tick 舍入，订单价格量化依第 15 章。
- 结构失效后不得恢复旧 `structure_id`。尚未触发的依赖 Setup/Signal 按其生命周期和第 24 章传播规则处理；已成交仓位退出依第 15/24 章，不能把研究结构失效当作订单指令。

---


### 3.2 已确认补充要求

- **SPEC-V148-05-ADD-01：** 结构对象记录全部构成 SwingPoint IDs、confirmed_at、所属 structure_id、周期、状态、配置版本；结构确认后冻结成员关系。按 Swing 完成确认时序选首个有效候选；结构明确失效前不得分配新 ID。失效传播遵循第 24 章统一表。

### 3.3 修订说明与待跨章确认事项

- 本次针对 10 项审查意见完成修订，并额外处理：Swing 确认时刻与极值时刻混淆、等价价格比较、候选结构提前生效、ATR 缺失、事件重放、方向切换时保护点并存、回撤比例分母无效、结构与保护点独立版本等问题。
- `OPEN_DECISION-SWING-ORDER`：同一 `confirmed_at` 多 Swing 的冲突顺序须与第 04 章一致。
- `OPEN_DECISION-SHORT-N-TRADING`：空头 N 的交易失效阈值及 Signal/Exit 接入须跨第 11/15/24 章批准。
- `OPEN_DECISION-PULLBACK-BOUNDARY`：第 09 章若未定义回撤开始/结束事件，须先补齐。
- `OPEN_DECISION-STATE-ENUM`：本章结构状态枚举与第 20 章一致性、保护点失效映射与第 08/09 章一致性待核验。
- 以上未决项不自动改变已获批准的多头 15M 交易规则。

## 4. 数据与状态契约

- 原文定义见第 3.1 节；新增约束见第 3.2 节。
- 本章决策依赖章节：[04](./04-指标与 ZigZag.md)、[06](./06-Zone 支撑阻力区域.md)、[08](./08-宏观趋势状态机.md)、[09](./09-4H 与 1H 状态机.md)、[10](./10-Setup 生命周期.md)、[11](./11-15M 信号系统.md)、[15](./15-止损与可执行价格.md)、[20](./20-核心数据结构.md)。
- 所有有损失风险的行为不得由未决规则推导；未决项见 [OPEN_DECISIONS.md](./OPEN_DECISIONS.md)。

## 5. 验收要求

- 本章原有规则、公式、状态转换和适用样例均须测试覆盖。
- 验收至少覆盖：HL→HH 与 LH→LL 顺序；仅候选不初始化；严格单向更新及相等不更新；ProtectedLow/High 直接失效及周期映射；影线/等号不失效；旧保护点不可复活；多空 N 仅末端确认才成立；多头 N 的 L2 与 ProtectedLow 非自动同一；同一 Bar 多事件；无效 ATR；回放幂等；跨周期隔离；成员冻结与快照版本；无效回撤分母；空头交易门禁。
- 新增条款须有可追溯断言、黄金样本或审计证据。
- 整体冻结门槛见 [24](./24-冻结条件.md)，数据验收见 [07](./07-数据标注与黄金样本.md) 与 [21](./21-回测与验证规范.md)。

## 6. 依赖与交叉引用

- 相关章节：[04](./04-指标与 ZigZag.md)、[06](./06-Zone 支撑阻力区域.md)、[08](./08-宏观趋势状态机.md)、[09](./09-4H 与 1H 状态机.md)、[10](./10-Setup 生命周期.md)、[11](./11-15M 信号系统.md)、[15](./15-止损与可执行价格.md)、[20](./20-核心数据结构.md)。
- 项目级需求追踪使用 `REQ-NNN`，不得与 `SPEC-V148-NN` 混用。

## 7. 未决项

- 业务选择集中登记于 [OPEN_DECISIONS.md](./OPEN_DECISIONS.md)；未决项不构成批准规则。
