# SPEC-V148-04｜指标与 ZigZag

> **文档状态：** 扩充结构化规格；本文件属于唯一权威规格的一章。原始规格仅作归档迁移来源。

## 1. 文档元数据

- 文档 ID：`SPEC-V148-04`（章节文档 ID，不是项目 REQ ID）
- 版本：V1.4.8 扩充版
- 原规格章节：第 4 章
- 状态：NORMATIVE，除显式 OPEN_DECISION 外按本章规范执行

## 2. 目标与范围

- **目标：** 规范 ETH-USDT-SWAP 多周期趋势策略的“指标与 ZigZag”行为与数据契约。
- **范围：** 本章原规则及已确认补充要求。
- **非目标：** 不推断未确认的策略收益或运行行为。

## 3. 规范性要求

原文条款与本扩充版补充要求共同构成规范；发生冲突时本扩充版的明确决定优先，其他冲突登记 OPEN_DECISIONS，不猜测。

### 3.1 原规格条款（迁移保留）

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


### 3.2 已确认补充要求

- **SPEC-V148-04-ADD-01：** 指标定义、可用标志及连续有效输入要求是显式契约：ATR 为 Wilder ATR(14)，SMA 为 SMA(22)；ATR 至少连续 14 个有效 True Range，SMA 至少连续 22 个有效 Close 后可用。缺失/无效输入使可用标志清零并重新累计。无效 ATR 标记 INVALID_ATR，禁止替代值及 ATR 倍数计算；Wilder 种子公式见 OD-07。
- **SPEC-V148-04-ADD-02：** 候选点并列按 (confirmed_at, occurred_at, source_bar_id, sequence, point_id) 升序稳定排序；原文同 Bar 处理步骤不得交换。增量、批量与回放必须得到同一候选、确认结果。

## 4. 数据与状态契约

- 原文定义见第 3.1 节；新增约束见第 3.2 节。
- 本章决策依赖章节：[03](./03-时间与 Bar 处理规范.md)、[05](./05-Swing 结构与保护点.md)、[06](./06-Zone 支撑阻力区域.md)、[11](./11-15M 信号系统.md)、[20](./20-核心数据结构.md)。
- 所有有损失风险的行为不得由未决规则推导；未决项见 [OPEN_DECISIONS.md](./OPEN_DECISIONS.md)。

## 5. 验收要求

- 本章原有规则、公式、状态转换和适用样例均须测试覆盖。
- 新增条款须有可追溯断言、黄金样本或审计证据。
- 整体冻结门槛见 [24](./24-冻结条件.md)，数据验收见 [07](./07-数据标注与黄金样本.md) 与 [21](./21-回测与验证规范.md)。

## 6. 依赖与交叉引用

- 相关章节：[03](./03-时间与 Bar 处理规范.md)、[05](./05-Swing 结构与保护点.md)、[06](./06-Zone 支撑阻力区域.md)、[11](./11-15M 信号系统.md)、[20](./20-核心数据结构.md)。
- 项目级需求追踪使用 `REQ-NNN`，不得与 `SPEC-V148-NN` 混用。

## 7. 未决项

- 业务选择集中登记于 [OPEN_DECISIONS.md](./OPEN_DECISIONS.md)；未决项不构成批准规则。
