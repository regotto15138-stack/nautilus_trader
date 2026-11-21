#!/usr/bin/env python3
"""Deterministically rebuild structured V1.4.8 chapter specifications."""
from __future__ import annotations
import re, shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
SRC=ROOT/'requirements/archive/ETH-USDT-SWAP 多周期趋势策略开发规格V1.4.8.md'
OUT=ROOT/'requirements/spec_v1_4_8'
RELATED={1:[2,23,24,25],2:[3,8,9,10,11,12,13,16,17],3:[4,5,6,7,12,21],4:[3,5,6,11,20],5:[4,6,8,9,10,11,15,20],6:[5,10,11,21],7:[8,9,21,22,23,24],8:[5,9,10,11,16],9:[5,8,10,16],10:[6,8,9,11,12,20],11:[5,6,8,9,10,12,13,15,20,22],12:[3,11,13,15,21,22],13:[12,14,15,17,20],14:[13,17,18,19,21],15:[11,12,13,16,17,20,22],16:[8,9,15,17,20,22],17:[13,14,15,16,18,19,20,22],18:[14,19,21],19:[6,10,11,12,15,16,17,18,21],20:[5,6,10,11,13,15,16,17,21],21:[3,4,6,7,12,14,18,19,20,22,24],22:[7,11,12,15,16,17,21],23:[7,24,25],24:[7,21,23,25],25:[1,24]}
ADD={
3:['所有内部时间统一为 UTC。重复或乱序 Bar 必须拒绝或隔离；缺失 Bar 不合成，数据连续性标记不完整，并阻止依赖区间的状态判定和回测验收。','事件顺序依原文策略链：低周期 Bar 更新→高周期聚合→指标/结构→MarketSnapshot→状态机→信号→订单/风险。周期顺序固定为 1MONTH、1W、1D、4H、1H、15M、3M；同阶段按稳定 ID 排序，确保批量、增量、回放一致。'],
4:['指标定义、可用标志及连续有效输入要求是显式契约：ATR 为 Wilder ATR(14)，SMA 为 SMA(22)；ATR 至少连续 14 个有效 True Range，SMA 至少连续 22 个有效 Close 后可用。缺失/无效输入使可用标志清零并重新累计。无效 ATR 标记 INVALID_ATR，禁止替代值及 ATR 倍数计算；Wilder 种子公式见 OD-07。','候选点并列按 (confirmed_at, occurred_at, source_bar_id, sequence, point_id) 升序稳定排序；原文同 Bar 处理步骤不得交换。增量、批量与回放必须得到同一候选、确认结果。'],
5:['结构对象记录全部构成 SwingPoint IDs、confirmed_at、所属 structure_id、周期、状态、配置版本；结构确认后冻结成员关系。按 Swing 完成确认时序选首个有效候选；结构明确失效前不得分配新 ID。失效传播遵循第 24 章统一表。'],
6:['每次 Zone 决策使用触发该决策的已完成 Bar ATR，并将值与 source_bar_id 记入不可变 Zone 版本快照；这不是固定 Zone 创建 ATR。内部价格/边界保留精确值，不隐式 tick 舍入；仅订单价格按交易所 tick 规则量化。'],
7:['黄金样本须冻结数据集版本及内容哈希，逐状态报告样本数，人工分歧由指定复核流程裁定。数据集、复核责任人、Macro-F1 算法和样本门槛见 OD-05；冻结前不得作为 P1-A 准入证据。'],
8:['1MONTH、1W、1D 使用各自原规格优先级；无已定义条件匹配或输入不完整时输出 UNKNOWN，不维持前态。CanOpen 与 CanHold 分离；风险恢复只用 CanHold，详见第 16 章。'],
9:['未定义状态/条件组合统一 UNKNOWN，不维持前态。RANGE 使用最近两个已确认且时间交替的 SwingHigh/Low；突破判定使用 zone_break_buffer_atr 和触发决策 Bar ATR。突破后 RANGE 退出/重置不自动推导，须用户确认 OD-04。'],
10:['Setup/Signal 有效期从创建完成 Bar 后的下一根完整同周期 Bar 开始计数；到达最大计数的 Bar 收盘后过期，创建 Bar 不计。Signal 仅代表入场执行，已成交仓位始终由 PositionManager/RiskManager 决策，终态不替代持仓退出规则。'],
11:['N 结构候选按 Swing 完成确认时序选首个有效序列；结构确认后冻结，失效前不分配新 ID。Signal 状态仅描述入场执行，已成交仓位由 PositionManager/RiskManager 管理。Signal 有效期计数见第 10 章。'],
12:['订单类型、路由、有效期、超时/重试及剩余数量策略为显式运行模式配置；Bar 回测不得推定 Live 行为。Live 具体策略待用户确认 OD-01。'],
13:['执行订单类型、路由、有效期、重试与剩余数量处理属于显式运行模式配置，不由 Bar 回测模型推断。Live 策略待 OD-01。交易所回报是成交/撤单事实源；本地请求不代表已生效。订单不一致进入第 24 章异常处置与对账流程。'],
14:['费用/Funding 按交易所历史费率、结算事件和账单定义；币种换算记录币种、汇率、来源及时点。缺少成本或换算数据不得标记有效净收益；权威换算源见 OD-06。'],
15:['止损价、价格边界内部保持精确值；订单价格按 tick size 量化，比较不采用任意 epsilon。'],
17:['CurrentRiskPerUnit 非正或不可计算时不得公式化减仓，进入风险异常流程。金额、数量用精确十进制或领域类型。合约产品范围见 OD-02；未确认时不准入未识别类型。'],
18:['运行模式（回测/Paper/Live）必须显式配置；运行模式必需参数不得从另一模式隐式继承。未确认的合约类型、币种换算源、数据完整性不足或必需运行参数缺失时拒绝启动。Live 参数见 OD-01。'],
20:['价格、数量、金额字段使用精确十进制或领域类型；审计记录保留来源、时间、配置版本。结构保存组成 Swing IDs、确认时点及所属结构 ID，冻结后不可改写，传播规则见第 24 章。'],
21:['有效回测冻结数据集版本与内容哈希，逐状态报告样本量；依赖缺失/不完整数据的区间不得通过验收。P1-A 准入统计定义见 OD-05。'],
24:['增加独立风险异常处置状态机。未平仓或未完成订单/账户对账期间保持新开仓冻结并持续告警；自动重试上限、退避与人工接管门槛见 OD-03。']}

FAILURE_TABLE='''
### 4.1 失效传播表

| 失效事件 | 直接对象 | 下游传播 | 已成交仓位 | 新开仓约束 |
|---|---|---|---|---|
| 15M N 结构失效 | 绑定该结构的候选 | 旧 structure_id 终止，候选按生命周期失效 | PositionManager/RiskManager 执行结构退出规则 | 旧结构不得再生成 Signal |
| 4H/1H ProtectedLow 失效 | 周期转 TRANSITION | 活动 Setup INVALIDATED 并向子对象传播 | 风险升级；仅明确强制退出时平仓 | 禁止新开仓 |
| Zone BROKEN/INVALIDATED | 绑定该 Zone 的活动 Setup | Setup INVALIDATED；Signal 按自身失效条件处理 | 不隐式平仓 | 不依赖此 Zone 新建对象 |
| Setup EXPIRED | 当前 Setup | 子 Setup EXPIRED，不传播为 INVALIDATED | 不自动取消已有 Signal | 不再创建子对象 |
| Setup INVALIDATED | 当前 Setup | 子 Setup INVALIDATED；未成交 Signal 按规则终止 | PositionManager/RiskManager 按明确规则决策 | 禁止使用该父级 |
| CanOpen 变 False | 新 Signal/入场资格 | 禁止新增；已成交部分按执行状态管理 | 不自动平仓，独立判断 CanHold/ForcedExit | 冻结新开仓 |
| 订单/账户/保护异常 | 异常管理器 | 进入风险异常状态机 | 紧急退出并对账 | 未处置期间冻结并持续告警 |

### 4.2 风险异常处置状态机

| 状态 | 含义 | 后继状态/条件 |
|---|---|---|
| NORMAL | 无待处理异常 | EXIT_PENDING 或 RECONCILIATION_PENDING |
| EXIT_PENDING | 紧急退出已提交、尚未确认全平 | RECONCILIATION_PENDING；无法自动保证安全则 MANUAL_INTERVENTION_REQUIRED |
| RECONCILIATION_PENDING | 订单、持仓或账务差异待核对 | 差异消除且仓位合规转 RESOLVED；仍需退出转 EXIT_PENDING；需要人工则 MANUAL_INTERVENTION_REQUIRED |
| MANUAL_INTERVENTION_REQUIRED | 需要人工接管 | 人工完成后 RECONCILIATION_PENDING |
| RESOLVED | 异常已处置且对账完成 | 新异常周期转 NORMAL |

进入非 NORMAL 状态即冻结新开仓并告警；仅所有未平风险已处理、订单与账户对账完成后解除冻结。记录异常 ID、触发事件、订单/持仓 ID、请求/回报时间、成交、剩余数量、对账结果及人工操作审计。重试上限、退避与人工接管阈值见 OD-03；确认前不得宣称自动处置完整，不得静默无限重试或解除冻结。
'''
def slug(n):return next(OUT.glob(f'{n:02d}-*.md')).name
def link(n):return f'[{n:02d}](./{slug(n)})'
def main():
 text=SRC.read_text(encoding='utf-8'); chapters=[]; cur=None
 for line in text.splitlines(keepends=True):
  m=re.match(r'^# (\d+)\. (.+?)\s*$',line)
  if m:
   if cur:chapters.append(cur)
   cur=[int(m.group(1)),m.group(2),[line]]
  elif cur:cur[2].append(line)
 if cur:chapters.append(cur)
 assert len(chapters)==25 and [x[0] for x in chapters]==list(range(1,26))
 for n,title,body in chapters:
  doc=f'SPEC-V148-{n:02d}'; links='、'.join(link(i) for i in RELATED[n])
  s=[f'# {doc}｜{title}\n\n','> **文档状态：** 扩充结构化规格；本文件属于唯一权威规格的一章。原始规格仅作归档迁移来源。\n\n',
  '## 1. 文档元数据\n\n',f'- 文档 ID：`{doc}`（章节文档 ID，不是项目 REQ ID）\n- 版本：V1.4.8 扩充版\n- 原规格章节：第 {n} 章\n- 状态：NORMATIVE，除显式 OPEN_DECISION 外按本章规范执行\n\n',
  '## 2. 目标与范围\n\n',f'- **目标：** 规范 ETH-USDT-SWAP 多周期趋势策略的“{title}”行为与数据契约。\n- **范围：** 本章原规则及已确认补充要求。\n- **非目标：** 不推断未确认的策略收益或运行行为。\n\n',
  '## 3. 规范性要求\n\n','原文条款与本扩充版补充要求共同构成规范；发生冲突时本扩充版的明确决定优先，其他冲突登记 OPEN_DECISIONS，不猜测。\n\n','### 3.1 原规格条款（迁移保留）\n\n',''.join(body),'\n### 3.2 已确认补充要求\n\n']
  for i,rule in enumerate(ADD.get(n,[]),1):s.append(f'- **{doc}-ADD-{i:02d}：** {rule}\n')
  if n not in ADD:s.append('- 本章无新增业务语义；通用结构化契约和追溯要求仍适用。\n')
  s += ['\n## 4. 数据与状态契约\n\n',f'- 原文定义见第 3.1 节；新增约束见第 3.2 节。\n- 本章决策依赖章节：{links}。\n- 所有有损失风险的行为不得由未决规则推导；未决项见 [OPEN_DECISIONS.md](./OPEN_DECISIONS.md)。\n\n','## 5. 验收要求\n\n','- 本章原有规则、公式、状态转换和适用样例均须测试覆盖。\n- 新增条款须有可追溯断言、黄金样本或审计证据。\n- 整体冻结门槛见 [24](./24-冻结条件.md)，数据验收见 [07](./07-数据标注与黄金样本.md) 与 [21](./21-回测与验证规范.md)。\n\n','## 6. 依赖与交叉引用\n\n',f'- 相关章节：{links}。\n- 项目级需求追踪使用 `REQ-NNN`，不得与 `SPEC-V148-NN` 混用。\n\n','## 7. 未决项\n\n','- 业务选择集中登记于 [OPEN_DECISIONS.md](./OPEN_DECISIONS.md)；未决项不构成批准规则。\n']
  (OUT/slug(n)).write_text(''.join(s),encoding='utf-8')
 idx=['# ETH-USDT-SWAP 多周期趋势策略 V1.4.8 扩充结构化规格','','> **唯一权威来源：** 本目录；章节 ID 为 `SPEC-V148-NN`，与项目 REQ 分离。','> **归档来源：** 原始规格全文位于 [`../archive/ETH-USDT-SWAP 多周期趋势策略开发规格V1.4.8.md`](../archive/ETH-USDT-SWAP%20多周期趋势策略开发规格V1.4.8.md)，仅供历史迁移追溯；后续迭代只修改本目录。','','## 文档结构','','每章栏目：元数据、目标与范围、规范性要求（原文+扩充）、数据与状态契约、验收、交叉引用、未决项。','','| ID | 章节 | 文档 |','|---|---|---|']
 for n,title,_ in chapters:idx.append(f'| `SPEC-V148-{n:02d}` | {title} | [{slug(n)}](./{slug(n)}) |')
 idx += ['','## 全局规范','','- 内部时间统一 UTC；Bar 左闭右开。重复/乱序数据拒绝或隔离；缺失 Bar 不合成并标记数据不完整，阻止相关状态/回测验收。','- 指标预热、INVALID_ATR 和确定性要求见[第 4 章](./'+slug(4)+')；结构及统一失效传播见[第 5 章](./'+slug(5)+')与[第 24 章](./'+slug(24)+')。','- 所有章节以精确十进制/领域类型表达价格、数量、金额。订单按 tick 规则量化；内部 Zone 比较不隐式舍入、不用任意 epsilon。','- 订单策略按运行模式配置；不把 Bar 回测模型推定为 Live 规则。已成交持仓始终由 PositionManager/RiskManager 管理。','','## 开放决策与准入','','查看 [OPEN_DECISIONS.md](./OPEN_DECISIONS.md)。未决规则阻断对应能力验收；P1-A 须在黄金样本、标注分歧流程、样本数及 Macro-F1 定义全部冻结后准入。','']
 (OUT/'README.md').write_text('\n'.join(idx),encoding='utf-8')
 print('rebuilt 25 structured specs')
if __name__=='__main__':main()
