# SPEC-V148-04｜指标与 ZigZag

> **文档状态：** REVIEW_CANDIDATE（V1.4.8-ZIGZAG-R1）。本文件为 V1.4.8 第 4 章的完整修订候选稿；未经跨章节审批不得视为已冻结 NORMATIVE 规则。原始版本保留归档。

## 1. 文档元数据

- 文档 ID：`SPEC-V148-04`（章节文档 ID，不是项目 REQ ID）
- 基线版本：V1.4.8 扩充版
- 修订标识：`V1.4.8-ZIGZAG-R1`
- 原规格章节：第 4 章
- 状态：`REVIEW_CANDIDATE`；本稿显式规则供评审和实验实现，涉及交易行为的跨章节变更须审批
- 主要变更：ZigZag 统一使用 High/Low 维度、定义候选更新/初始化/确认时序、补充参数和数据契约

## 2. 目标与范围

- **目标：** 规范 ETH-USDT-SWAP 多周期策略的 ATR、SMA、ZigZag 与 SwingPoint 行为，确保增量、批量和回放确定性一致。
- **范围：** 七个独立周期的指标与价格极值型 ZigZag；下游结构与 Zone 仅消费已确认 SwingPoint。
- **非目标：** 不以本章修改 ProtectedLow/High、N 结构及订单的收盘失效规则；不宣称 High/Low 型优于 Close 型的实证收益。

## 3. 规范性要求

本稿中 `MUST` 表示必须；`MUST NOT` 表示禁止。原 V1.4.8 与本稿冲突时，以本稿明确修订为评审候选；跨章节冲突进入 `OPEN_DECISIONS.md`，不得自行推定已获批准。

### 3.1 基础指标

| 指标 | 定义 | 可用性 |
|---|---|---|
| ATR | Wilder ATR(14)，True Range 由当前 High/Low 与前一有效 Close 计算 | 至少连续 14 个有效 TR 后可用 |
| SMA | SMA(22)，基于 Close | 至少连续 22 个有效 Close 后可用 |
| ZigZag | High/Low 极值、ATR 快照反转阈值 | ATR 有效后初始化 |

- 各周期独立维护 Bar、ATR、SMA、ZigZag 状态，不共享缓存或指标实例。
- ATR 种子按原 `OD-07` 决议；若该决议尚未冻结，必须将 ATR 种子实现设为发布门禁，不得假设与其他实现一致。
- 缺失、非有限数值、`High < Low`、Close 不在 `[Low, High]`、非正价格、非正 ATR 均属无效输入。无效输入使相关指标可用标志清零并重新累计；禁止前值填充、默认 ATR 或跨缺口连续计算。连续 TR 需要有效的前收盘价；重新启动一段数据时首根 Bar 用 `High-Low` 作为首个 TR 的约定须与 `OD-07` 对齐，否则保持不可用。
- SMA(22) 只作为供上游趋势/上下文模块引用的独立指标；**不参与本章 ZigZag 极值更新或反转阈值**。其在第 08、09、11 章的实际交易用途以各章已批准规则为准，不能据此新增过滤条件。

### 3.2 ZigZag 价格语义与参数

- `zigzag_price_basis = HIGH_LOW`（本次候选规则）；候选高点使用 Bar High，候选低点使用 Bar Low。
- 高点候选反转：`Bar.Low <= CandidateHigh.price - k * CandidateHigh.atr_snapshot`。
- 低点候选反转：`Bar.High >= CandidateLow.price + k * CandidateLow.atr_snapshot`。
- `k = 2.0` 为 RESEARCH 初值，非最优参数；同一配置版本内固定。
- 反转阈值严格采用当前候选极值生成或更新时保存的有效 ATR 快照，不使用确认 Bar 的 ATR 替代。
- ZigZag 识别极值使用 High/Low，不代表下游保护点或 N 结构的交易性失效也要改用 High/Low。下游 Close 规则保留，分别按第 05、09、11、15 章执行。
- 任何 Bar 仅在完整闭合且数据通过校验后进入引擎；禁止使用未完成 Bar 的 High/Low 作为已确认历史。

### 3.3 初始化、状态与候选更新

状态：`WARMUP`、`SEEK_INITIAL_DIRECTION`、`SEEK_HIGH`、`SEEK_LOW`、`DATA_GAP`。

1. **首根有效 Bar**：更新指标暖机状态；不得确认 Swing，不得把首根 Bar 的极值当作已确认 Swing。若 ATR 未可用，维持 `WARMUP`。
2. **ATR 首次可用的 Bar**：进入 `SEEK_INITIAL_DIRECTION`，以该 Bar 的 High/Low 记录初始探索区间上下界、各自的 `occurred_at`、`source_bar_id` 和 ATR 快照；该 Bar 不产生 Swing。
3. **方向发现**：后续每根完整 Bar 首先用旧探索区间边界和其 ATR 快照检查突破幅度。若价格向上超出旧探索低点 `k × ATR_at_low`，则进入 `SEEK_HIGH`；若向下超出旧探索高点 `k × ATR_at_high`，则进入 `SEEK_LOW`。这只是方向初始化，**不回填、也不确认初始探索区间的低点/高点为 Swing**。
4. **初始化双向同时满足**：由于 OHLC 内部路径未知，保持 `SEEK_INITIAL_DIRECTION`，记录 `AMBIGUOUS_INITIAL_DIRECTION`，不猜测先后。未触发方向时更新探索区间极值（严格创新高/新低才更新），并保存对应 ATR。
5. **方向发现的同一 Bar**：不确认 Swing；不将本 Bar 用作相反方向候选。下一根完整 Bar 初始化当前方向候选（见第 3.4 节）。此选择可能丢失初始转折，需回测量化。
6. **SEEK_HIGH**：只允许 High 严格大于候选高价时更新候选高点及 ATR 快照；相等则保留最早候选。`SEEK_LOW` 对称，只允许 Low 严格低于候选低价时更新。
7. 候选更新必须同时原子更新 `price`、`occurred_at`、`source_bar_id`、`atr_snapshot`；ATR 无效时暂停状态推进，进入 `DATA_GAP`，不可用旧 ATR 处理新 Bar。
8. 数据恢复后，须完成指标重新暖机，清空未确认候选与初始探索区间，重新执行初始化；旧已确认 Swing 历史保持不可变，但不得跨数据缺口拼接连续 N 结构，须输出数据断点事件供下游处理。

### 3.4 单 Bar 时序与 OHLC 路径歧义

对于已初始化的 `SEEK_HIGH`/`SEEK_LOW`：

1. 读取 Bar 开始时的候选快照 `old_candidate`。
2. 检查本 Bar 是否严格刷新候选极值，以及是否相对于 `old_candidate` 达到反转阈值。
3. **同 Bar 同时创新极值且触发反转**：记为 `AMBIGUOUS_INTRABAR_ORDER`；保守规则是本 Bar 不确认 Swing，不更新候选极值，维持旧候选和方向；该 Bar 不能在未来被回溯利用。此规则避免凭 OHLC 假设价格路径；对这种情形应在研究报告中单独统计发生率。
4. **仅刷新极值**：原子更新候选及其 ATR；本 Bar 不再用更新后的候选阈值判定反转。
5. **仅触发反转**：确认 `old_candidate` 为 SwingPoint，`confirmed_at` 为当前 Bar 结束时刻；此 Bar 不创建相反方向候选。
6. **均未触发**：保持原候选。
7. 确认 Swing 的**下一根**完整 Bar 才开始新方向候选：高点确认后以该下一 Bar 的 Low 初始化低点候选；低点确认后以该下一 Bar 的 High 初始化高点候选。**禁止回溯确认 Bar、禁止使用其 High/Low 初始化候选**。初始化新候选的 Bar 不允许同时确认该候选。
8. 对 `SEEK_INITIAL_DIRECTION`，方向判定必须使用更新前探索区间，双向歧义按第 3.3 节处理；方向选择后的本 Bar 不生成 Swing。

> 设计取舍：不使用同 Bar 内无法观测的极值先后关系，代价是可能延迟或遗漏短期转折。可在有逐笔或更低周期数据时作为单独研究变体比较，但不得在同一回测中无标记混用。

### 3.5 ATR 快照与数值规则

- 候选点 `atr_snapshot` 为其价格极值最后一次**严格更新**时该已完成 Bar 的有效 ATR；候选未创新极值则 ATR 快照不随时间滚动。
- 快照滞留是显式研究设计；需比较 `CANDIDATE_SNAPSHOT` 与其他候选方案的敏感性，但当前候选规格仅允许前者参与交易研究。
- `k > 0`，ATR 有限且 `> 0`；阈值和比较使用内部精确数值，不隐式按 tick 舍入。`High/Low` 原始数据必须符合交易所价格精度，订单价格量化由执行章节处理。
- 价格相等不刷新候选；反转条件使用 `<=` / `>=`，阈值恰好触及时可确认（但仍受同 Bar 歧义规则约束）。
- 若 ATR 失效、时间倒序、重复冲突 Bar 或配置在候选存续期间被热切换，停止候选推进并记录事件；不得静默改写历史。

### 3.6 SwingPoint 数据契约

```python
@dataclass(frozen=True)
class SwingPoint:
    point_id: str
    timeframe: str
    direction: str             # HIGH | LOW
    price: float
    occurred_at: datetime      # 极值来源 Bar 的结束时刻
    confirmed_at: datetime     # 确认反转 Bar 的结束时刻
    atr_snapshot: float
    source_bar_id: str          # 极值来源 Bar
    confirmation_bar_id: str    # 反转确认 Bar
    config_version: str
    sequence: int              # 周期内确认 Swing 的严格递增序号，从 1 开始
    price_basis: str           # HIGH_LOW
    engine_revision: str
```

- `confirmed_at > occurred_at`（按本稿禁止同 Bar 确认）；所有时间戳采用第 03 章统一时区/Bar 结束时间定义。
- `sequence` 是**每个 timeframe + instrument + 连续数据段**内从 1 开始、按确认事件严格递增的整数；持久化恢复时必须恢复最后序号，不得重置导致 ID 冲突。数据断点增加 `segment_id`，新段 sequence 从 1 开始。
- 实际唯一键：`(instrument_id, timeframe, segment_id, sequence)`；`point_id` 由此稳定生成，不能使用随机 UUID 或依赖进程启动次数。`instrument_id` 与 `segment_id` 应为对象字段或不可变外部封套字段。
- `source_bar_id` 指向极值 Bar；`confirmation_bar_id` 指向确认 Bar，二者不能混用。`occurred_at` 不得用于提前激活下游结构；**只有 confirmed_at 及之后**才允许下游读取该 Swing。
- 相邻确认 Swing 的 `direction` 必须 HIGH/LOW 交替；任何未确认候选不得对外发布为已确认 Swing。
- 已确认 SwingPoint 不可修改；重复消费同一确认事件不得重复增加 `sequence`。
- 若下游需要候选排序，沿用 `(confirmed_at, occurred_at, source_bar_id, sequence, point_id)` 升序；该排序不替代本章事件时间顺序。
- `config_version` 和 `engine_revision` 进入事件审计；同一数据、同一配置、同一修订版本必须产生相同输出。

### 3.7 参数表

| 参数 | 默认/约束 | 类型 | 用途 |
|---|---|---|---|
| `atr_period` | 14；基线固定 | FIXED | Wilder ATR |
| `sma_period` | 22；基线固定 | FIXED | 上下文可引用的 SMA |
| `zigzag_k` | 2.0；必须 > 0 | RESEARCH | 反转阈值倍数 |
| `zigzag_price_basis` | `HIGH_LOW` | REVIEW_DECISION | 极值与反转价格维度 |
| `zigzag_atr_reference` | `CANDIDATE_SNAPSHOT` | REVIEW_DECISION | ATR 快照策略 |
| `same_bar_ambiguity_policy` | `DEFER_NO_UPDATE` | REVIEW_DECISION | 同 Bar 路径不明处理 |
| `candidate_equal_price_policy` | `KEEP_EARLIEST` | FIXED | 相等极值处理 |
| `opposite_candidate_start` | `NEXT_BAR_NO_LOOKBACK` | REVIEW_DECISION | 新候选启动边界 |
| `invalid_input_policy` | `RESET_WARMUP` | FIXED | 数据异常处理 |

参数须纳入 `config_version`；研究参数调整必须建立独立回测实验与结果标识。

### 3.8 变更影响与跨章节契约

- 第 05 章：Swing 的 `occurred_at` 与 `confirmed_at` 不同，ProtectedLow/High 和 N 结构只能引用确认后 Swing；本章不修改保护点 Close 失效条件。
- 第 06 章：Zone 仅聚类已确认 Swing，禁止使用候选极值；须兼容新 `point_id` 和 `segment_id`。
- 第 03 章：Bar 时间、缺口、同时间戳排序和回放顺序应以该章为准；如冲突，阻止冻结。
- 第 11 章：15M Signal 不得读取尚未确认的 H2/L2；确认延迟应纳入信号时效研究。
- 第 20 章：同步补充 `confirmation_bar_id`、`price_basis`、`engine_revision`、`instrument_id`、`segment_id` 和 `sequence` 作用域。
- 第 21 章：单独比较旧 Close 反转逻辑与本稿 High/Low 逻辑，禁止把两种价格语义的绩效差异归因于其他参数。

## 4. 数据与状态契约

- 输入：严格有序的已完成 OHLC Bar、有效时间戳、instrument/timeframe、ATR/SMA 状态、配置版本。
- 输出：不可变 SwingPoint、候选状态快照、数据缺口事件、歧义事件、指标可用标志。
- 状态快照至少包含：`instrument_id`、`timeframe`、`segment_id`、`engine_revision`、`config_version`、`state`、`candidate_price`、`candidate_occurred_at`、`candidate_source_bar_id`、`candidate_atr_snapshot`、`exploration_high/low`、`last_sequence`、`last_processed_bar_id`、`atr_ready`、`sma_ready`。
- 恢复时校验快照配置与 Bar 游标一致；不一致则重新回放，不得混合旧快照与新算法。
- 未决且有损失风险的行为不得由工程人员自行补全，统一登记 `OPEN_DECISIONS.md`。

## 5. 验收要求

必须建立黄金样本和可重复测试：

1. 首根 Bar、ATR 未暖机、ATR 首次可用均不产生 Swing。
2. 初始化方向向上、向下、双向歧义、无方向均有确定输出。
3. 候选 High/Low 严格刷新时同步更新价格、时间、来源 Bar、ATR；相等极值不刷新。
4. 仅反转触发确认旧候选；同 Bar 同时创新极值和反转触发时不确认、不更新。
5. 反转阈值等号成立；无效 ATR 不计算阈值。
6. 确认 Bar 不初始化相反候选；下一根 Bar 初始化且不回溯。
7. 极值发生时刻与确认时刻分离；任何下游消费者不得提前使用 Swing。
8. 同一输入的增量、批量、历史回放、断点恢复产生相同 Swing IDs、sequence、事件及状态快照。
9. 数据缺口和坏 Bar 使候选重置、指标重新暖机；不跨段拼接结构。
10. 同 Bar 歧义事件发生率、确认延迟、Swing 密度、Zone 宽度和保护点变化纳入对照回测。
11. SMA 不得改变 ZigZag 输出；ATR/SMA 在各周期独立计算。
12. 新旧 ZigZag 版本回测必须使用一致的数据、手续费、滑点、风险模型，报告差异和置信区间（若有）。

整体冻结门槛见 [24](./24-冻结条件.md)，数据验收见 [07](./07-数据标注与黄金样本.md) 与 [21](./21-回测与验证规范.md)。

## 6. 依赖与交叉引用

- [03](./03-时间与 Bar 处理规范.md)、[05](./05-Swing 结构与保护点.md)、[06](./06-Zone 支撑阻力区域.md)、[11](./11-15M 信号系统.md)、[20](./20-核心数据结构.md)、[21](./21-回测与验证规范.md)、[24](./24-冻结条件.md)。
- 项目级需求追踪使用 `REQ-NNN`，不得与 `SPEC-V148-NN` 混用。

## 7. 未决项

- **OD-ZZ-01（待批准）**：将 ZigZag 价格语义正式变更为 `HIGH_LOW`，并确定是否允许 Close 型作为独立研究变体。
- **OD-ZZ-02（待批准）**：确认 `DEFER_NO_UPDATE` 对同 Bar 路径歧义的保守处理及其引入的偏差。
- **OD-ZZ-03（待批准）**：确认方向初始化不回填首个 Swing、确认 Bar 不回溯，以及下一 Bar 才初始化新候选。
- **OD-ZZ-04（待验证）**：ATR 候选快照滞留对反转延迟、Swing 密度及下游 Zone/Signal 的敏感性。
- **OD-ZZ-05（跨章节）**：`OD-07` Wilder ATR 种子与数据缺口处理、SwingPoint 新字段、结构生命周期传播的契约一致性。

以上事项须同步登记至项目 `OPEN_DECISIONS.md`；本章列出仅作为修订候选的待办清单，不代表已修改该外部文件。
