# 多周期趋势策略 + SACW 完整执行计划 V2.0

**策略语义基线：** [V1.4.8 扩充结构化规格](../requirements/spec_v1_4_8/README.md)（本目录唯一权威）
**SACW 基线：** V1.1.2（后续以仓库当前规格文件为准）
**当前状态核对：** 2026-11-21；完整测试 `PYTHONPATH=src python -m pytest -q` → **379 passed**。命令使用 `nautilus_pa/../python/.venv` 的 uv 项目环境；这是执行时工作树的验证结果，不等于任何阶段出口已过。
**开发目的：** 将现有代码能力、SACW 批次 B00…B10d 与 V1.4.8 P0…P3 统一映射，作为后续技术方案、任务书及出口验收的基线。本文是计划，不替代 `.dsh/tasks/tasks.json` 的任务状态事实。

---

## 〇、状态核对与证据（2026-11-21）

**核对范围：** `PROJECT_CONTEXT.md`、`src/pa_trend/` Python 模块、`tests/unit/` 与 `tests/integration/` 测试文件、`configs/`、`web/`、只读读取 SACW SQLite 指定表计数、V1.4.8 P0/P1/P2/P3、冻结条件及 OPEN_DECISIONS。未对未跟踪数据、缓存或父仓库改动做清理/覆盖。父仓库在本次操作前已有与本任务无关的变更及未跟踪行情数据；保留原状。

**最新实测：** `PYTHONPATH=src python -m pytest -q` → **379 passed in 41.60s**（实际由 `nautilus_pa/../python/.venv/bin/python` 执行）。通过只说明当前测试集通过，不证明黄金样本人工门槛、完整交易闭环或策略收益验证已经完成。当前 SQLite 只读计数：`annotations=9`、`golden_datasets=0`、`dataset_splits=0`、`regression_runs=5`、`regression_assertions=280`。数据库是本机状态快照，不能据此推定所有人工标注/黄金集工作的权威完成情况；需在任务技术方案中复核各 annotation 的内容、标注者/状态、哈希、PB 运行与实际报告。

**状态图例：** ✅ 已由代码/测试或登记证据确认　🟡 有实现但尚未达到批次/规格出口　⬜ 尚未找到实现或执行证据　⛔ 规格门禁阻塞　❓ 需后续核实。状态必须随实际任务证据更新；本次已在任务台账登记的本轮核验不等于子系统已通过验收。

| 能力区 | 核对状态 | 已看到的实现/证据 | 缺口、限制或后续复核 |
|---|:--:|---|---|
| 时间、Bar、聚合、数据完整性 | 🟡 | domain Bar/Timeframe、时间周期引擎/聚合、NAUTILUS 转换器、质量与间隔审计、七周期引擎入口；有相应单测 | P0-A 规格逐条验收仍需核对 UTC、Bar 左闭右开、结束判定、拒绝/隔离、缺失传播、统一时间快照及随机回放出口 |
| 指标、ZigZag、Swing | 🟡 | Wilder ATR、SMA、增量 ZigZag、候选冻结快照、SwingPoint、`occurred_at`/`confirmed_at` 修正 | P0-B 冻结与批量/增量等价须按规格证据收口；当前没有由通过数替代规格核查 |
| Protected 点、N 结构、宏观与 4H/1H | 🟡 | ProtectedLevelTracker、NStructureDetector、Month/Week/Day/4H/1H 状态实现及 CanOpen/CanHold；N 结构、状态、边界测试存在 | `n_structure_break_buffer_atr` ATR 时点歧义继续 `SPEC_AMBIGUITY`；状态映射须由 P0-E 人工样本验证；RANGE 突破后的转移/重置受 OD-04 限制 |
| Zone | 🟡 | ZoneEngine、几何/参数、生命周期事件与单测存在 | 仍须按 SPEC-V148-06 全部转换、年龄/版本及联动规则逐项和黄金样本验收 |
| SACW/API/标注工作台 | 🟡 | SQLite store、HTTP API、网页绘图与编辑、搜索/时间过滤、撤销/重做、服务脚本；集成测试存在 | 当前数据库表计数见上；须验证冻结 Ground Truth、分歧裁决、版本/哈希和人工标签质量，不能用测试通过数代替人工验收 |
| PB 框架 | 🟡 | 配置声明 PB-01…PB-51；测试确认全体声明、结构化样本和可运行当前案例；已保存回归运行/断言 | 对现阶段尚无引擎的用例仍标 `BLOCKED_BY_UNIMPLEMENTED_STAGE`；检查实际正负断言与各引擎映射。51 条“已声明”不等于 51 条可执行、通过或可作为黄金真值 |
| 成本/订单/策略执行链 | ⬜ | 已有 lifecycle Setup/Signal/Order/Position/Risk 数据契约与配置模型 | 未发现已完成的 Setup→Signal→Execution→Fill→Risk 生产决策链；分别按下文 P1/P2 批次验收 |
| 参数实验和配置治理 | 🟡 | 参数分类、启动门禁、配置/指纹能力；数据库有 config 相关表（需技术方案核查） | Trial/Experiment、搜索/Holdout、审批发布回滚未证明完成；不能以存在表/配置项视为闭环 |

**旧版阶段表与结论均为历史核验，不作现状事实；下方各批次条目也是历史计划细节，状态须由上方本轮矩阵和 tasks.json 更新。**

## 当前 SACW 批次状态（2026-11-21）

下表仅更新已在本轮核验的批次结论；下文逐批历史说明仍保留旧日期细节，应作为待技术方案阶段复核的差距清单，不得误读为最新独立验收结论。凡本轮没有逐条代码/数据库证据的位置均标为“待核”。

| 批次 | 当前状态 | 已确认的现状/缺口 |
|---|:--:|---|
| B00 | 🟡 | `TASK-002`（B00 PATCH 乐观锁）仍为 DRAFT；依任务说明尚需完成 expected_revision 强制与前端冲突处理，不得据旧段落判已完成 |
| B01a | ❓ | 旧记录称 replay API 可用、比较侧未接持久化事件；本轮未逐端点/数据源核查。复核比较是否消费 `program_events`、重复回放 hash 一致性 |
| B01b | 🟡 | PB 51 条结构化声明可确认；回归器源注释仍使用 `BLOCKED_BY_UNIMPLEMENTED_STAGE`。逐条断言映射、负向断言实际求值、差异定位、批量冻结与缺失引擎分类待复核 |
| B02a | ❓ | 本轮未核实完整成本公式实现；379 tests 不代表费率/Funding/滑点/加权均价模型达到出口 |
| B02b | 🟡 | 当前 API/前端工作台有标注和查询功能；是否逐项满足历史任务列表须按 TASK/API/浏览器验收重核 |
| B03a | 🟡 | 当前 SQLite 有 9 annotations、0 golden datasets、0 dataset_splits；不能据本机库证明黄金数据冻结/切分已完成。还需确认数据库是否权威/最新 |
| B03b | ⬜ | 本轮未找到可交付的冻结标注统计验收报告；Macro-F1、Per-State Recall、转换误差及因果/边界报告待核 |
| B04 | ⬜ | 当前入口只有 lifecycle 数据契约；Setup4H/1H 决策引擎出口未确认 |
| B05 | ⬜ | lifecycle 有 Signal 类型/模型，尚无 Signal 规则引擎出口证据 |
| B06 | ⬜ | 尚无 3M Execution 出口证据 |
| B07 | ⬜ | 尚无完整止损与风险闭环出口证据 |
| B08 | ⬜ | lifecycle 的 Order/Position/Fill 模型不等于订单与持仓管理闭环；尚无出口证据 |
| B02c | ⬜ | 尚无成本接入成交/持仓/交易记录的出口证据 |
| B09 | ⬜ | 本轮未找到完整策略回测与样本外验证报告 |
| B10b | 🟡 | 参数登记/配置指纹存在；Trial/Experiment/Holdout 完整出口尚无证据 |
| B10c | ⬜ | 参数搜索/Pareto/Holdout 出口尚无证据 |
| B10d | 🟡 | 本轮未核实候选审批发布/回滚 API；旧记录仅证明数据库表存在，不证明流程已实现 |

**准入结论：** 尚无经本计划新增门禁核对的 P0-E、OD-05 通过证据，因此 **P1-A 不准入**。SACW 阶段出口以任务台账、批次测试与复核报告逐项判定；旧的数据库零条统计已经过时（当前 annotations=9），旧版阶段结论不能直接继承为当前结论。

## 本轮核验后建议的后续工作顺序

1. 以 DRAFT 的 TASK-002 和 B00/B01a 现有工作为起点，先核实任务契约及其当前代码，不重做已完成内容。
2. 并行前置仅限无文件冲突的工作：B01b 差异定位/真实断言与缺引擎分类；B02a 成本模型；B02b 未完标注工具；B03a 复核实际 annotations、建立可审计人工标注与冻结流程。每项须新建或沿用合法 REQ/TASK，不同 TASK 不共享写入文件。
3. B03a 数据/哈希/标注责任和统计方法与规格 owner 核准并冻结，PB-01…PB-51 自动化样本逐条执行通过，P0-A…F 中适用任务均通过后，才复审 P1-A 准入；本地 SQLite 当前状态只作为线索。
4. P1-A→P1-B→P1-C→P1-D 逐级开发和门禁，不跳过失效/时序/Zone/Signal 引用契约；之后 P2 风险订单和 B02c 成本接入，再 P3 冻结回测；SACW B10b/B10c/B10d 按其独立依赖推进。

## 一、总体原则

1. **先验收，后开发。** 结构识别层未通过人工黄金样本验收前，不进入 Setup/Signal/Execution。
2. **PB 执行框架与 PB 通过率分离。** B01 只负责让 PB 可执行、可分类、可定位；51 例全部 PASS 不是 B01 出口。
3. **引擎缺失阻塞与规格歧义阻塞分离。** `BLOCKED_BY_MISSING_ENGINE` 靠后续批次解除；`BLOCKED_BY_SPEC_AMBIGUITY` 靠规格维护方裁定。
4. **SACW 伴随建设。** 回放 API、比较持久化、标注工具必须与阶段 1 并行，不能等到最后。
5. **串行依赖严格。** B04 → B05 → B06 → B07 → B08 不可跳步；B02a、B02b、B10b 可并行。
6. **禁止事项全局生效。** 每批任务书必须附 V1.4.8 和 SACW 13.4 的禁止事项。

### 1.1 强制未决项与安全限制

下列事项不是默认值，也不能由代码惯例代替用户决定；相关能力在未决期间保持阻断/不可验收。

| 决策 | 现状约束 | 影响范围 |
|---|---|---|
| OD-01 Live 订单策略 | Live 订单类型、路由/有效期、超时重试、拒单和部分成交后剩余数量均未确认；Bar 回测模式不能推导 Live 行为 | 禁止 Live 准入；显式模式分隔 |
| OD-02 产品范围 | 暂限线性 USDT 结算 ETH-USDT-SWAP；不支持的合约必须在启动门禁拒绝 | 产品/保证金/PnL/账户元数据 |
| OD-03 风险异常处置 | 重试上限、间隔/退避、持续异常升级、人工接管条件及告警责任方未确认 | 不得自设无限/有限自动重试或宣称风险异常自动闭环完成；异常时冻结新开仓并持续告警 |
| OD-04 RANGE 重置 | 突破后的状态映射、Swing 确认和重置条件未冻结 | 不把有效突破自行解释为趋势；对应状态迁移保持 UNKNOWN/不可验收 |
| OD-05 黄金数据与统计 | 数据集版本/哈希、复核负责人/分歧流程、各状态最低样本量、Macro-F1 标签集合/算法/门槛未冻结 | **阻断 P0-E 完成及 P1-A 状态机准入** |
| OD-06 非 USDT 换算 | 权威源、时间、报价方向和缺失数据处置未确认 | 需换汇而来源/时点不全时不报告有效净收益/风险，相关启动或回测拒绝 |
| OD-07 指标预热 | Wilder ATR 初始种子与缺失 Bar 后重预热规则待确认；临时最低有效窗口不等于冻结决定 | 仅按明确临时口径实现可逆/可标记逻辑；未决细节不暗中固化 |

所有条款须以 [OPEN_DECISIONS.md](../requirements/spec_v1_4_8/OPEN_DECISIONS.md) 最新内容为准。即使用户未来选择关闭某个能力，也须先更新权威 spec、相关 REQUIREMENT 与测试/验收依据，之后才改实现。

---

## 二、统一阶段划分：V1.4.8 主链 × SACW 批次

V1.4.8 的 P0/P1/P2/P3 是策略规格顺序；SACW 的阶段与 B 批次是工程/数据验收批次。二者是**双轴映射**，不要假定编号或名称一一对应。后续技术方案须为每个 TASK 同时标注 `REQ-NNN`、`TASK-NNN`、V1.4.8 章节/阶段和对应 SACW 批次。

| 统一执行组 | V1.4.8 阶段/主任务 | 关联 SACW 批次 | 门槛与关系 |
|---|---|---|---|
| G0：规格/任务/基础能力收口 | 既有能力核验；P0-A…D 的缺口收敛 | B00、B01a、B01b、B02a、B02b、B03a、B10b 的无冲突前置工作 | B00 与 B01a 可并行；B02a/B02b 可在文件互斥后与回归框架工作并行；人工标注筹备可并行，但不等于达成 P0-E |
| G1：P0-E 样本与 P0-F 成本门禁 | P0-E 人工黄金样本/快照；P0-F 成本、元数据、REQUIRED 配置 | B01b、B03a、B03b、B02a；涉及标注工具继续 B02b | PB-01…PB-51 全部进入自动化并执行通过；OD-05 数据集版本/哈希、分歧裁决、样本数、Macro-F1 标签集/算法/门槛冻结。B03b 验收含策略定义的状态样本，不能以框架可运行代替 |
| G2：P1-A 多周期状态机准入 | 1MONTH、1W、1D、4H、1H；对应规格第 8/9 章 | B03b 出口及必要的 B01b/B03a | **必须等待 G1 的 P0-E 与 OD-05 全部通过**，并按人工黄金样本对照。OD-04 影响的 RANGE 突破后状态重置保持不可验收，除非待决语义已由授权流程确认 |
| G3：P1-B/P1-C 策略决策闭环 | Setup4H/1H → 15M Signal | B04 → B05；对照 PB-01…07、14…21、23…26、31 等规格适用项 | 严格串行：B04 的 Setup 完成/通过后才实现 B05 Signal；验证版本同步、状态传播、Signal 引用与终态 |
| G4：P1-D 执行确认 | 3M Execution | B06 | 依赖 P1-C/B05；只作入场执行确认，不产生独立方向/入场信号。OD-01 未确认时仅可验收显式模式配置/非 Live 能力，禁止准入 Live |
| G5：P2 风险、订单及成交闭环 | 仓位、止损、移动止损、风险升级/预算、部分成交、PositionManager | B07 → B08；B02c 成本接入依赖 B06 与 B08 | B07 风险/止损先于 B08 订单/仓位管理；B02c 可在依赖完成后接入成本。OD-03 的重试/退避/人工接管条件未决时，不得虚构这些策略或宣称异常自动闭环完成 |
| G6：P3 组合验证与冻结 | 历史/分阶段/随机片段/敏感性/成本压力/滑点压力/样本外 | B09 | 依赖 P0-P2 相关任务及 B02c。逐条通过第 24 章冻结门槛后才可冻结规格并进入完整策略回测；规格冻结不代表盈利结论或 Live 授权 |
| G7：SACW 参数实验与配置治理 | 与策略验证有依赖关系的非交易治理工作 | B10b → B10c → B10d | B10b 可在实现契约互不冲突时并行；B10c 依赖 B09 与 B10b；B10d 依赖 B10c。配置审批/发布不得自动发生 |

**执行原则：** 阶段出口是下一阶段的强制准入门槛。B 批次名称/旧阶段编号若与 V1.4.8 有不同含义，按本表的双轴映射追踪，不覆盖规格语义。P0 子任务只有在任务文件集互斥、依赖无环、六项拆分门槛齐全时才并行；同一 allowed_paths 文件交集任务串行。

### 2.1 任务化与交付流程（强制）

1. `tasks.json` 是唯一任务状态事实源；`planning/EXECUTION_PLAN.md` 只记录路线、出口和经核验的阶段快照，不自行维护另一套任务状态。
2. 新工作先登记其语义父项 REQ，再在 TASK 拆分目标、输入、输出、依赖、范围、唯一写入者、`allowed_paths`/`forbidden_paths`、验收、测试计划与风险/回滚；满足 `.dsh/tasks/README.md` 六项门槛后进入 READY。
3. 开工前 Main 将任务设为 IN_PROGRESS 并登记 owner；只在范围内改动。跨越能力/阶段出口的任务必须有任务证据、测试输出和审查结论，不以实现者自述通过。
4. 按合法状态机推进 IMPLEMENTED→REVIEWING→TESTING→ACCEPTED；只有 Main 更新台账及阶段结论。任何改动后运行 `python3 .dsh/scripts/validate_tasks.py`。未运行测试不算通过；异常条件写 BLOCKED/remaining，不擅自放行下游。
5. Git 所有操作在父仓库，用户明确要求提交之前不 commit/push；如用户要求提交，提交 subject 以 `<TASK-ID> <摘要>` 开头，不用 Conventional Commits。严禁无 Task ID 的状态外修改、越界、覆盖既有用户/工作区文件。
6. 技术方案先对照本计划、实际代码、测试、REQ/TASK 与 OPEN_DECISIONS；明确各接口/数据模型来源及变更，不从模块名/枚举存在推定业务引擎已实现。

---

## 三、批次详细任务（历史执行计划明细；请按第 〇 节重核状态）

> 本节包含旧版代码审计结论、测试/数据库计数和✅/⬜标记。除明确标为 2026-11-21 的顶层快照外，它们不是本轮独立核验的当前事实；不得用于绕过 tasks.json 或阶段准入复审。

### 阶段 0：前置修正与基础设施（下列 B 批次执行细节沿用旧版记录，状态需按第 〇 节重核）

#### B00：SACW 文档一致性与并发安全修正　❓ 历史状态待复核

> **历史记录（2026-11-17）：** 旧版计划记录了文档修正、白名单/跨文档核对和 PATCH 乐观锁收口；本轮未逐条核验 B00 出口。`TASK-002` 仍为 DRAFT（其任务说明记录了需完成 expected_revision 强制与冲突处理）；旧记录不能替代当前代码/前端核验及正式验收，以第 〇 节矩阵和任务台账为准。

**目标**：消除 SACW V1.1.1 与 V1.4.8 的明确冲突，补齐并发安全基础。

**输入**：SACW V1.1.1、V1.4.8、当前代码。

**任务**：

1. **ATR_MA22 修正**
    - SACW 17.1/17.2/17.3 删除“V1.4.8 2.3 定义为 RESEARCH_ONLY”的引用；
    - 改为“V1.4.8 未定义 ATR_MA22；UI 显示 `N/A / SPEC_AMBIGUITY`，不得展示、不得进入参数白名单”；
    - 29 验收矩阵增加 UI-022：ATR_MA22 未定义时显示 `N/A / SPEC_AMBIGUITY`；
    - 32 章诊断码已有 `SPEC_AMBIGUITY`，无需新增。

2. **Zone 两参数补入白名单**
    - SACW 8.1 增加 `zone_min_half_width_ticks`（初始 2）、`zone_max_age_weeks`（初始 52 周）；
    - 21.2、21.4、25.4 引用这两个参数；
    - 标注为 RESEARCH，与 V1.4.8 19 章一致。

3. **PATCH 乐观锁**　🟡 部分执行
    - 🟡 `PATCH /annotations/{id}` 必须传 `expected_revision`：服务端**支持**该字段（`expected_revision is not None` 时才校验），**未强制必传**，缺失即按无锁放行；
    - ✅ 版本不匹配返回 `409 REVISION_CONFLICT`，记录审计（`presentation/api.py`、`tests/integration/test_api.py`）；
    - ⬜ 前端保存失败时提示“标注已被他人修改，请刷新”：前端当前**没有任何 PATCH 调用**，不发送 `expected_revision`，也无 409 提示分支。

4. **编码前检查清单**
    - 13.1 增加“逐项核对 SACW 引用的 V1.4.8 章节号、参数名、枚举值、分类；不存在或分类不一致时标记 `SPEC_AMBIGUITY` 或 `PARAMETER_REGISTRY_MISMATCH`”。

**出口标准**：

- ✅ SACW 文档不再引用 V1.4.8 不存在的 2.3 节和 ATR_MA22；
- ✅ Zone 两参数进入白名单；
- 🟡 `PATCH` 乐观锁测试通过（仅覆盖「传了错误版本 → 409」，未覆盖「不传 → 拒绝」）；
- ✅ 编码前检查清单落地。

**依赖**：无。

**可并行**：B00 可与 B01a 并行，但 B00 必须先于 B10b。

---

#### B01a：回放 API + 比较持久化　❓ 历史状态待复核

> **核对：** 回放 API 与前端触发入口可用，`program_events` 有实际写入；但计划的第二条任务
> （比较引擎改读持久化事件）未做，比较仍以内存引擎为程序侧数据源。

**目标**：打通“冻结 Ground Truth → 程序回放 → 比较事件持久化”的基础设施。

**输入**：`replay_runs`、`program_events`、`comparison_runs`、`match_results` 表已存在；`PaTrendStrategy` 结构引擎可运行。

**任务**：

1. **回放 API**
    - `POST /replay-runs`：请求包含 `dataset_id`、`golden_dataset_id`、`spec_version`、`code_commit`、`config_version_id`、`timeframes`、`initial_snapshot_id`、`mode`；
    - `GET /replay-runs/{run_id}`：返回状态、进度、错误；
    - `GET /replay-runs/{run_id}/events`：分页返回 `program_events`；
    - `GET /replay-runs/{run_id}/snapshots`：返回初始快照和 `as_of` 快照；
    - `POST /replay-runs/{run_id}/cancel`；
    - 🟡 回放结果写入 `program_events`，保留 `event_id`、`event_type`、`timeframe`、`payload`、`source_bar_id`、`run_id`、`config_hash`：表内存的是 `bar_id`（非 `source_bar_id`），`config_hash` 只记在 `replay_runs`，事件行上没有。

2. **比较引擎改为读持久化事件**　⬜ 未执行
    - ⬜ 差异比较不再直接读内存引擎；
    - ⬜ 从 `program_events` 读取程序事件，与人工 Ground Truth 匹配；
    - 🟡 `comparison_runs` 记录 `golden_dataset_id`、`replay_run_id`、`matcher_version`（已记录，但 `replay_run_id` 来自黄金样本 baseline，不是被比较的 `program_events` 所属回放）；
    - ✅ `match_results` 记录 `human_id`、`program_id`、`match_type`、`errors`。

    现状：`api.py` 中 `compare_swings` 等四个比较端点仍调用 `self.service.swings(timeframe)` / 内存引擎上下文，
    `program_events` 只被回放 API 写入、未参与匹配。

3. **前端触发入口**　✅ 已执行
    - ✅ 数据集页增加“运行回放”按钮；
    - ✅ 回放进度、状态、错误可查；
    - 🟡 回放完成后可跳转差异对比页（当前只展示 run_id 与事件计数，无跳转）。

4. **确定性测试**　🟡 部分执行
    - ⬜ 相同数据、代码、配置、快照重复回放，`program_events` Hash 一致；
    - ⬜ 回放 API 返回的事件与内存引擎事件逐项一致（事件直接取自内存引擎，未设独立比对断言）。

**出口标准**：

- ✅ `POST /replay-runs` 可触发回放，结果写入 `program_events`；
- ⬜ 比较引擎读 `program_events`，不再读内存；
- 🟡 `comparison_runs`、`match_results` 有实际记录：写入路径存在，但工作区 `var/sacw.sqlite3` 中两表仍为 0 条；
- ⬜ 重复回放事件 Hash 一致；
- ✅ 前端可触发回放并查看进度。

**依赖**：无。

**可并行**：B01a 与 B00 并行；B01a 必须先于 B01b 和 B03b。

---

### 阶段 1：结构层验收闭环

#### B01b：PB 执行框架 + 正负向断言 + 差异定位　❓ 历史状态待复核

> **核对：** 执行入口、正向断言、批量运行、结果冻结已可用；阻塞分类未按计划拆成
> `SPEC_AMBIGUITY` / `MISSING_ENGINE` 两类，差异定位字段完全缺失，负向断言尚未真正参与判定。

**目标**：让 PB-01～51 可执行、可分类、可定位，不要求全部 PASS。

**输入**：B01a 完成；PB 样本定义（SACW 23.2）。

**任务**：

1. **PB 执行入口**　✅ 已执行
    - 统一 `POST /regression-suites/v1-4-8/run`；
    - 支持单例、批量、全套运行；
    - 每例记录 `regression_run_id`、`case_id`、`case_version`、`status`。

2. **正负向断言**　🟡 部分执行
    - 🟡 正向：`expected_events`、`expected_state_transitions`、`expected_final_state` **未作为结构化字段落库**；样本只有 `expected` 文本，可执行的 6 例由 Python 评估器直接产出断言；
    - 🟡 负向：`expected_absent_events` 有、`negative_assertion_reason` 有；⬜ `expected_absent_state_transitions` **未实现**；
    - 🟡 负向断言与正向同等权重，任一失败即 PB 失败：当前负向断言由运行器**无条件记为 PASSED**（`regression.py` 中直接 append `RESULT_PASSED`，理由写“当前阶段无可执行的产生路径”），未真正验证“未发生”。

3. **阻塞分类**　🟡 部分执行
    - ✅ `PASSED`：所有断言通过；
    - ✅ `FAILED`：断言失败；
    - ✅ `BLOCKED_BY_SPEC_AMBIGUITY`：PB-12、PB-13，记录 `invalidation_status = SPEC_AMBIGUITY`；
    - ⬜ `BLOCKED_BY_MISSING_ENGINE`：**未实现**。43 例统一记为 `BLOCKED_BY_UNIMPLEMENTED_STAGE` + 一句话原因（Setup/Signal/执行/风险引擎合并描述），没有逐例列出缺失引擎。

4. **差异定位**　⬜ 未执行
    - ⬜ 失败时返回 `bar_id`、`event_id`、`field_path`、`expected`、`actual`（断言表只有 `target` + `detail`，检索不到任何 `field_path`）；
    - ⬜ 前端可从差异行跳转图表对应 Bar 和事件详情。

5. **结果冻结**　✅ 已执行
    - ✅ 保存 `regression_run_id`、`code_commit`、`config_hash`、`dataset_hash`、`expectation_revision`；
    - ✅ 导出 JSON 与页面展示引用同一 `regression_run_id`。

**出口标准**：

- ✅ PB 执行框架就绪，可执行当前引擎能产生的 PB；
- ✅ 6 例现有 PB 通过（PB-21、PB-22、PB-34、PB-35、PB-47、PB-48）；
- ✅ PB-12/13 标记 `BLOCKED_BY_SPEC_AMBIGUITY`；
- ⬜ 43 例标记 `BLOCKED_BY_MISSING_ENGINE`，并列出缺失引擎（当前为 43 例 `BLOCKED_BY_UNIMPLEMENTED_STAGE`，无引擎清单）；
- 🟡 正负向断言（仅 `expected_absent_events`）、差异定位（⬜）、批量运行（✅）、结果冻结（✅）可用；
- ✅ **不要求 51 例全部 PASS。**

**依赖**：B01a。

**可并行**：B01b 与 B02a、B02b 并行。

---

#### B02a：成本模型 + 单元测试 + 成本数据结构　❓ 历史状态待复核

> **核对：** 只有 `configs/execution.yaml` 的 `maker_fee_rate` / `taker_fee_rate` /
> `cost_model_version` / `slippage_model_version` 占位、`configs/research.yaml` 的
> `funding_dataset` 占位，以及 `config/validation.py` 的启动门禁。全仓库检索不到
> `CostBreakdown`，`FillRecord` 也没有 `fee_amount` / `fee_currency` / `slippage_cost` 字段，
> 没有任何成本计算代码或成本单测。

**目标**：实现成本计算核心，不依赖策略引擎。

**输入**：V1.4.8 13 章、14 章；SACW 27.3。

**任务**：

1. **成本模型**　⬜
    - ⬜ Maker/Taker 费率；
    - ⬜ 入场/出场滑点；
    - ⬜ Funding 历史序列与结算；
    - ⬜ 成交均价加权；
    - ⬜ 净收益 = 毛收益 − 手续费 − 滑点 − Funding。

2. **数据结构**　⬜
    - ⬜ `CostBreakdown`：每笔交易的成本明细；
    - ⬜ `FillRecord` 扩展 `fee_amount`、`fee_currency`、`slippage_cost`（现有 `FillRecord` 无这三个字段）；
    - ⬜ `ExecutionRecord` 聚合成本；
    - ⬜ 成本关联 `Signal`、`Order`、`Fill`、`Position`、`Trade`。

3. **单元测试**　⬜
    - ⬜ 单笔 Fill 成本；
    - ⬜ 多笔 Fill 加权均价；
    - ⬜ 跳空止损滑点；
    - ⬜ Funding 正负费率；
    - ⬜ 成本缺失时拒绝有效净收益回测。

**出口标准**：

- ⬜ 成本模型单元测试通过；
- ⬜ `CostBreakdown`、`FillRecord`、`ExecutionRecord` 数据结构落地；
- ✅ 成本缺失时启动门禁拒绝（`config/validation.py` 校验费率、成本/滑点模型版本与 Funding 数据集）；
- ✅ **不要求接入真实交易记录**（B02c 再做）。

**依赖**：无。

**可并行**：B02a 与 B01b、B02b 并行。

---

#### B02b：ProtectedPoint + StateInterval 标注工具　❓ 历史状态待复核

> **核对：** 两类对象的创建、提交、审核、批准、冻结与 15M 拒绝均已可用；缺 Swing 手动覆盖、
> 复制、撤销/重做、属性编辑 UI、时间过滤与搜索、图上状态色带。另：前端
> `drawManualAnnotations` 存在拼接残留，ProtectedPoint 图层实际画不出来（见第十节）。

**目标**：补齐 P0-E 人工黄金样本所需的标注工具。

**输入**：SACW 3.4D、3.4E、4.4。

**任务**：

1. **ProtectedLow / ProtectedHigh 工具**　🟡 部分执行
    - ✅ 初始化、更新、失效事件（`event_type = INIT / UPDATE / INVALIDATE`）；
    - 🟡 来源 SwingPoint ID：payload 不强制该字段，前端表单也不采集；
    - ✅ 有效区间（`valid_from` / `valid_to`，并校验先后）；
    - ✅ 失效确认 Bar 与原因（`INVALIDATE` 强制 `invalidated_at` + `invalidation_reason`）；
    - ✅ 15M 不建独立 ProtectedLow，API 拒绝并提示（`PROTECTED_POINT_15M_NOT_ALLOWED`，创建与修订两处都拦）。

2. **StateInterval 工具**　🟡 部分执行
    - ✅ 1M/1W/1D/4H/1H 状态枚举（`_STATE_INTERVAL_STATES` 按周期校验）；
    - ✅ `valid_from`、`valid_to`、`known_at`、`reason_code`；
    - ⬜ 图上背景色带显示（前端只在 `valid_from` 画一个 `belowBar` 标记，没有区间底色）；
    - ✅ 状态转换原因必填（`reason_code`）。

3. **Swing 价格手动覆盖**　⬜ 未执行
    - ⬜ `manual_price_override=true` + 修改原因；
    - ⬜ 审核时可见。

4. **对象属性编辑、删除、复制、撤销/重做**　🟡 部分执行
    - 🟡 乐观锁保护：`PATCH` 支持 `expected_revision` 但非必传，前端未接入（同 B00-3）；
    - ✅ 审计日志；
    - ✅ 删除（软删除）；
    - ⬜ 复制（无 copy/duplicate 端点或前端动作）；
    - ⬜ 撤销/重做（`web/` 内无任何 undo/redo 实现）；
    - ⬜ 属性编辑 UI（前端无 PATCH 调用，标注一经创建只能走状态流转或删除）。

5. **标注列表筛选和搜索**　🟡 部分执行
    - ✅ 按周期、类型、状态过滤（`list_annotations` 的 `timeframe` / `entity_type` / `status`）；
    - ⬜ 按时间过滤（无时间区间参数）；
    - ⬜ 搜索（前端只有 PB 样本搜索框，标注列表无关键字检索）。

**出口标准**：

- 🟡 ProtectedPoint 和 StateInterval 标注工具可用（后端完整，前端 ProtectedPoint 图层有缺陷）；
- ✅ 人工标注可保存、提交、审核、批准、冻结；
- ✅ 15M 独立 ProtectedLow 被拒绝；
- 🟡 乐观锁生效（仅当调用方主动传 `expected_revision`）。

**依赖**：B00（乐观锁）。

**可并行**：B02b 与 B01b、B02a 并行。

---

#### B03a：Golden Dataset API + 人工标注完成　❓ 历史状态待复核

> **核对：** API 四件套里 `GET / {id}`、`validate`、`split` 与 `dataset_splits` 读取已可用；
> `split` 只按调用方显式区间登记，没有三分法与 `time_split_hash`。人工标注与冻结**尚未开始**：
> 工作区数据库 `annotations = 0`、`golden_datasets = 0`、`dataset_splits = 0`。
> 7.2 验收门槛所需指标（Macro-F1 / Recall）无任何计算实现。

**目标**：完成 Golden Dataset 管理 API，启动并完成人工标注。

**输入**：B02b 完成；SACW 6.3、7.1、10.1。

**任务**：

1. **Golden Dataset API**　🟡 部分执行
    - ✅ `GET /golden-datasets/{id}`；
    - ✅ `POST /golden-datasets/{id}/validate`；
    - 🟡 `POST /golden-datasets/{id}/split`：Calibration / Validation / Holdout 时间切分可在冻结时指定 split、也可按显式区间登记，但**不会自动三分**，`range_start` / `range_end` 必须由调用方传入；
    - ⬜ `time_split_hash` 生成（表与返回值都无该字段）；
    - 🟡 `dataset_splits` 表暴露 API/UI（有 `GET /market/datasets/{id}/splits` 与列表展示，但无登记入口的 UI）。

2. **人工标注执行**　👤⬜ 未执行
    - ⬜ 按 SACW 10.1 顺序：先 15M Swing/NStructure/Zone，再 4H/1H/1D/1W/1M 状态区间和保护点，再 3M Signal 后时序案例；
    - 🟡 PB-01～51 人工场景样本及预期结果：51 例的 `expected` 文本与 `expected_absent_events` 已登记，⬜ 但未产出“人工场景样本”本身（真实 Bar 区间与标注）；
    - ⬜ 双人复核或仲裁处理模糊案例（无仲裁流程/角色实现）；
    - ⬜ 冻结 Ground Truth，记录 `baseline_replay_run_id`（代码支持，但尚未实际冻结过任何数据集）。

3. **验收门槛**　⬜ 未执行
    - ⬜ 按 SACW 7.2：Overall Macro-F1 ≥ 0.85、各状态 Recall ≥ 0.80、转换时间误差 ±1 Bar、转换识别准确率 ≥ 90%；
    - ⬜ 样本不足的状态单独报告。

**出口标准**：

- 🟡 Golden Dataset API 可用（缺 `time_split_hash` 与自动三分）；
- ⬜ 人工标注完成并冻结；
- ⬜ `baseline_replay_run_id` 绑定（能力已有，尚无实际数据）；
- ⬜ 7.2 工程验收门槛达到或样本不足项已单独报告。

**依赖**：B02b。

**可并行**：B03a 的人工标注可与 B01b 并行，但 API 部分依赖 B02b。

---

#### B03b：P1-A 状态机与人工黄金样本验收　❓ 历史状态待复核

> **核对：** 没有任何「程序状态序列 vs 人工状态区间」的验收实现。`matching.py` 只做对象级
> 匹配（含状态区间重叠匹配），其注释明确写着「该函数不计算 Macro-F1，逐 Bar 混淆矩阵需要
> 额外 Bar 序列」。任务 2～4 的确定性/因果/边界断言只存在于 P0 基线单测（如 replay 幂等、
> `as_of` 快照不回看未来、状态枚举边界），不是本批要求的验收套件。

**目标**：P1-A 多周期状态机通过人工黄金样本验收。

**输入**：B01b（PB 执行框架）、B03a（人工 Ground Truth）。

**任务**：

1. **状态机与人工样本对比**　⬜
    - ⬜ 1M/1W/1D/4H/1H 状态逐 Bar 对比；
    - ⬜ Confusion Matrix、Macro-F1、Per-State Recall、转换时间误差；
    - ⬜ 按 `confirmation_policy` 分组。

2. **确定性回放**　🟡 基线已有部分覆盖
    - 🟡 相同数据、代码、配置、快照重复回放，状态序列一致（`snapshot` 回放排序用例存在，未针对状态序列横比）；
    - ⬜ 多周期数据到达顺序变化时，最终状态一致；
    - 🟡 未完成 Bar 不进入状态机（引擎侧已只喂收盘 Bar，缺显式验收用例）。

3. **因果性测试**　🟡 基线已有部分覆盖
    - 🟡 结构发生时间、观察时间、确认时间、回放确认时间严格区分（`occurred_at` / `confirmed_at` 已分离）；
    - ✅ 不使用未来数据（`GET /snapshots?as_of=` 重放裁剪有测试）。

4. **边界测试**　🟡 基线已有部分覆盖
    - 🟡 状态失效、恢复、冻结（状态枚举与迁移单测存在，未覆盖全部周期组合）；
    - ⬜ `ProtectedHigh` 失效后各周期状态映射；
    - ⬜ `WEAKENING` 不可达条件。

**出口标准**：

- ⬜ 状态机与人工黄金样本一致率达到 SACW 7.2 门槛；
- 🟡 确定性回放通过（部分）；
- 🟡 因果性测试通过（部分）；
- 🟡 边界测试通过（部分）。

**依赖**：B01b、B03a。

---

### 阶段 2：策略决策闭环

#### B04：P1-B Setup4H / Setup1H　❓ 历史状态待复核

> **核对：** `market_context.py` 仅在模块 docstring 中列出执行链，`Setup4H` / `Setup1H` 没有任何
> 实现；`domain/lifecycle/models.py` 只有 `Setup` 数据类与 `SetupStatus` 枚举，
> `SetupStatus.ACTIVE/EXPIRED/INVALIDATED` 无迁移逻辑，无 `PullbackLow_4H` 选择、
> 无观察区交集、无 Zone 版本同步。**（被 B03b 出口阻塞，按计划不应开工。）**

**目标**：实现 Setup 状态机和识别规则。

**输入**：B03b 完成；V1.4.8 第 10 章。

**任务**：

1. **Setup4H**
    - 创建条件：4H PULLBACK、多头结构有效、ProtectedLow 有效、4H SUPPORT Zone ACTIVE/TESTED、`PullbackLow_4H` 与 Zone 距离、观察区宽度；
    - `PullbackLow_4H` 选择规则；
    - `Setup4H` 生命周期：ACTIVE / EXPIRED / INVALIDATED；
    - 父级失效传播。

2. **Setup1H**
    - 创建条件：父 Setup4H ACTIVE、1H PULLBACK/REVERSAL_CANDIDATE、1H SUPPORT Zone、观察区交集；
    - 交集失败统计：`SETUP1H_NO_INTERSECTION`、`SETUP1H_INTERSECTION_TOO_NARROW`；
    - 生命周期与父级传播。

3. **Zone 版本同步**
    - Zone 版本变化时 Setup 观察区更新；
    - 已产生 Signal 的 Setup 不静默修改。

**出口标准**：

- PB-01～07、PB-23～26 相关 Setup 前置可执行；
- Setup 生命周期测试通过；
- Zone 版本同步测试通过。

**依赖**：B03b。

---

#### B05：P1-C 15M Signal　❓ 历史状态待复核

> **核对：** `SignalType.BREAKOUT_CONTINUATION` / `PULLBACK_CONTINUATION` 与
> `SignalStatus` 只是枚举（仅 `tests/unit/test_lifecycle.py` 引用），无触发条件、
> 无生命周期迁移、无 ATR 快照、无唯一性槽位逻辑。**（被 B04 阻塞。）**

**目标**：实现 BREAKOUT_CONTINUATION 和 PULLBACK_CONTINUATION。

**输入**：B04 完成；V1.4.8 第 11 章。

**任务**：

1. **BREAKOUT_CONTINUATION**
    - 父 Setup ACTIVE；
    - N 结构有效、L2 位置判定；
    - `Close > H2`、`Close > SMA22`、突破延伸上限；
    - 结构止损锚点 = L2。

2. **PULLBACK_CONTINUATION**
    - 回撤起点 `PullbackOriginHigh`；
    - `PullbackLow` 选择与更新；
    - `TriggerSwingHigh` 选择与 `min_trigger_swing_atr`；
    - `HigherLow` 确认；
    - 观察区位置校验（`pullback_low_zone_tolerance_atr`）；
    - 结构止损锚点 = `higher_low_swing_id`。

3. **Signal 生命周期**
    - `ACTIVE / CANCELLED / EXPIRED / PARTIALLY_EXECUTED / EXECUTED`；
    - `REJECTED` 消耗唯一槽位；
    - `partially_filled` 字段；
    - 决策 ATR 快照。

4. **唯一性**
    - `n_structure_id + signal_type` 最多一次。

**出口标准**：

- PB-01～07、PB-23～26 通过；
- Signal 生命周期测试通过；
- ATR 快照测试通过；
- 唯一性测试通过。

**依赖**：B04。

---

#### B06：P1-D 3M Execution　❓ 历史状态待复核

> **核对：** `ExecutionReferencePrice` 全仓库只出现在规格与计划中；3M 分形、
> Signal 后严格时序、追价限制、`FILL_DEVIATION_BREACH`、执行取消均无实现。
> **（被 B05 阻塞。）**

**目标**：实现 3M 执行确认和追价限制。

**输入**：B05 完成；V1.4.8 第 12 章。

**任务**：

1. **3M 分形**
    - 2-left / 2-right；
    - 相等高低点处理；
    - `confirmed_at` 等待右侧两根 Bar。

2. **Signal 后严格时序**
    - SwingLow / SwingHigh 必须 `occurred_at > SignalCreatedAt` 且 `confirmed_at > SignalCreatedAt`；
    - 突破 Bar 必须晚于 SwingHigh 确认；
    - 快速突破行情统计。

3. **追价限制**
    - `ExecutionReferencePrice` vs `ExecutionReferenceLevel`；
    - 跳空限制；
    - 实际成交偏差 `FILL_DEVIATION_BREACH`。

4. **执行取消**
    - 结构失效、宏观否决、追价超限、执行价低于参考价。

**出口标准**：

- PB-14～16、PB-31 通过；
- 3M 时序测试通过；
- 追价限制测试通过。

**依赖**：B05。

---

### 阶段 3：交易执行与风险闭环

#### B07：P2 Risk Manager　❓ 历史状态待复核

> **核对：** 只有 `domain/lifecycle/models.py` 的纯函数 `initial_stop` / `fixed_stop_price` /
> `risk_budget_breached` 与 `RiskStatus`、`PositionRiskView` 数据类，加上 `configs/risk.yaml`
> 的参数项。移动止损引擎、风险升级/解除计数、减仓公式、`ACTUAL_RISK_BUDGET_BREACH`
> 处置均未实现。**（被 B06 阻塞。）**

**目标**：实现风险预算、止损、风险升级和异常处置。

**输入**：B06 完成；V1.4.8 第 14～17 章。

**任务**：

1. **初始止损**
    - `P_fixed`、`P_structural`、`InitialStop = max(...)`；
    - 必须低于 `ActualAverageEntryPrice` 和 `CurrentExecutablePrice`；
    - 部分成交后重算。

2. **移动止损**
    - 首根完整 15M Bar 后启用；
    - 只上移；
    - `k_normal`、`k_escalated`。

3. **风险升级 / 解除**
    - 1H/4H TRANSITION 触发；
    - 1H 3 根 BULLISH、4H 2 根 TREND_UP、`CanHold=True` 解除；
    - 计数重置。

4. **风险预算超限**
    - `ACTUAL_RISK_BUDGET_BREACH`；
    - `CurrentRiskPerUnit` 不含已发生入场费；
    - 减仓公式、`hard_risk_budget_multiple`。

**出口标准**：

- PB-08～11、PB-40～43、PB-50～51 通过；
- 止损、风险升级、超限处置测试通过。

**依赖**：B06。

---

#### B08：P2 Order / Position Manager　❓ 历史状态待复核

> **核对：** `OrderState`、`PositionState` 只有枚举定义，无状态迁移实现；
> `PositionManager` 全仓库只出现在规格与计划文本中；无部分成交、加权均价、
> 保护止损数量同步、`FillRecord` 的 `execution_reference_atr_15m` / `fill_deviation_atr` 写入。
> **（被 B07 阻塞。）**

**目标**：实现订单、Fill、Position 状态机和部分成交处理。

**输入**：B07 完成；V1.4.8 第 13 章；SACW 27.3。

**任务**：

1. **OrderState / PositionState 分离**
    - `INITIALIZED / SUBMITTED / ACCEPTED / PARTIALLY_FILLED / FILLED / CANCEL_PENDING / CANCELED / REJECTED / EXPIRED`；
    - `FLAT / OPEN / CLOSING / CLOSED`。

2. **部分成交**
    - 加权均价；
    - 保护止损数量同步；
    - 剩余订单处理。

3. **FillRecord**
    - 每笔独立；
    - `execution_reference_atr_15m`；
    - `fill_deviation_atr`。

4. **PositionManager**
    - 持仓数量、成本、浮盈亏；
    - 止损、移动止损；
    - 退出。

**出口标准**：

- PB-17、PB-36～38、PB-46 通过；
- 部分成交、订单状态机测试通过。

**依赖**：B07。

---

#### B02c：成本接入 Fill / Position / Trade　❓ 历史状态待复核

> **核对：** 依赖的 B02a（成本模型）为空、B08（Fill/Position）未实现，本批未开始。

**目标**：把 B02a 的成本模型接入实际交易记录。

**输入**：B06、B08 完成。

**任务**：

- `CostBreakdown` 关联 `Fill`、`Position`、`Trade`；
- 净收益计算；
- 成本归因分析。

**出口标准**：

- 一笔完整交易的净收益和成本明细可计算；
- 成本归因测试通过。

**依赖**：B06、B08。

---

### 阶段 4：策略验证闭环

#### B09：P3 回测与组合验证　❓ 历史状态待复核

> **核对：** 现有 `scripts/run_signal_research.py` 只做结构事件统计（规格第 19、20 章），
> 不是回测：无 R 倍数、无分市场阶段、无随机片段、无样本外、无成本/滑点压力。
> **（被 B08、B02c 阻塞。）**

**目标**：完整历史回测、分市场阶段、随机片段、样本外验证。

**输入**：B08、B02c 完成。

**任务**：

1. 完整历史回测；
2. 分市场阶段回测；
3. 随机片段回测（含初始状态快照）；
4. Macro-F1、Per-State Recall、转换时间误差统计；
5. R 倍数、Signal/Execution/风险统计；
6. 参数敏感性、成本压力、滑点压力；
7. 样本外验证。

**出口标准**：

- 回测报告包含 SACW 22 章全部统计项；
- 样本外验证通过；
- 成本前后对比可审计。

**依赖**：B08、B02c。

---

### 阶段 5：SACW 校准与配置治理

#### B10b：参数实验室 UI 骨架 + 白名单 + Trial 存储　❓ 历史状态待复核

> **核对：** 白名单分类表已在 `config/fingerprint.py`，含 `zone.min_half_width_ticks` 与
> `zone.max_age_weeks`（均 RESEARCH），FIXED 参数在加载时被强制校验。但 Trial 存储、
> Experiment/Trial 列表 UI、Holdout 角色权限均未实现。

**目标**：建立参数实验室基础，不执行实际搜索。

**输入**：B00 完成；SACW 8.1、25.1、25.2。

**任务**：

- 🟡 参数白名单加载（含 Zone 两参数）：分类表已含两参数，但只有内置 36 项字典，没有从 SACW 8.1 清单加载/校验的机制；
- 🟡 FIXED/REQUIRED/METADATA 拒绝：FIXED 由 `config/models.py` 与 `validation.py` 拒绝改写；优化器侧的「拒绝」无从谈起（无优化器）；
- ⬜ Trial 存储；
- ⬜ Experiment/Trial 列表 UI；
- ⬜ Holdout 角色权限。

**出口标准**：

- 🟡 白名单校验测试通过（只覆盖 FIXED 参数被拒，未覆盖白名单加载与 Zone 两参数可搜索）；
- ⬜ Trial 存储可用；
- ⬜ Holdout 隔离测试通过。

**依赖**：B00。

**可并行**：B10b 可在阶段 2 并行。

---

#### B10c：实际参数搜索 + Pareto + 敏感性 + Holdout 隔离　❓ 历史状态待复核

> **核对：** 无 Grid/Random Search、无 Pareto 前沿、无敏感性分析、无
> `CONSUMED_FOR_SELECTION` 状态（全仓库检索不到）。**（被 B09、B10b 阻塞。）**

**目标**：执行实际参数搜索和样本外验证。

**输入**：B09 完成；B10b 完成。

**任务**：

- Grid/Random Search；
- Pareto 前沿；
- 参数敏感性；
- Holdout 隔离与 `CONSUMED_FOR_SELECTION`。

**出口标准**：

- 参数搜索可执行；
- 敏感性报告可生成；
- Holdout 隔离测试通过。

**依赖**：B09、B10b。

---

#### B10d：配置候选、审批、发布、回滚　❓ 历史状态待复核

> **核对：** `config_versions` / `config_approvals` 两张表已建好（`annotation_store.py`），
> 但没有任何 `POST /config-candidates` 或审批/发布/回滚端点，前端无配置治理页。
> **（被 B10c 阻塞。）**

**目标**：配置治理闭环。

**输入**：B10c 完成。

**任务**：

- `POST /config-candidates`；
- 审批、发布、回滚；
- 配置差异报告；
- `configuration_hash`。

**出口标准**：

- 候选配置审批、发布、回滚完整；
- 配置 Hash 可追溯；
- FIXED 参数未被修改。

**依赖**：B10c。

---

## 四、依赖关系图

```text
B00 ──┬──────────────────────────────┐
      │                              │
B01a ─┴── B01b ──┬── B03b ── B04 ── B05 ── B06 ──┬── B07 ── B08 ──┬── B09 ── B10c ── B10d
                 │                              │                 │
B02a ────────────┼──────────────────────────────┘                 │
                 │                                                │
B02b ── B03a ────┘                                                │
                                                                  │
B10b ─────────────────────────────────────────────────────────────┘
```

**关键路径**：B00 → B01a → B01b → B03b → B04 → B05 → B06 → B07 → B08 → B09 → B10c → B10d。

**并行路径**：B02a、B02b、B10b 可与主链并行；B02c 依赖 B06、B08。

---

## 五、规格冻结与能力准入矩阵

### 5.1 P0 基础设施和准入

| 规格阶段 | 主要验收内容 | 关联批次/证据 | 强制出口 |
|---|---|---|---|
| P0-A Bar 与时间 | BarIdentity、UTC、完成检测、多周期聚合、统一快照；重复/乱序拒绝或隔离；缺失 Bar 不合成且完整性阻断相关状态/回测 | 现有 timeframe、aggregation、data_quality、collector、bar converter 与其测试；对照 §03 | 完整性、切分边界与确定性测试通过；random slice 可恢复有效初始快照 |
| P0-B ZigZag/指标 | ATR14、候选极值、ATR 冻结、SwingPoint 确认、增量/批量一致 | §04；indicator/ZigZag 测试；B01b | 预热/INVALID_ATR、时间戳与转换边界有可追溯断言；OD-07 未决部分不自选口径 |
| P0-C Swing/N | Swing HH/HL/LH/LL、ProtectedLow/High、PullbackOriginHigh、多头 N、结构 ID、失效参数及引用一致 | §05；levels/n_structure/regression；B01b/B03b | 回放可复现；结构冻结/失效传播验证；N 失效 ATR 时点未决的生产决策保持阻断 |
| P0-D Zone | CREATED→ACTIVE→TESTED/BROKEN/INVALIDATED、版本、年龄、Setup 观察区联动 | §06；Zone 测试；B02b | 所有适用转换与 Setup 联动样本有测试，无隐式舍入；出口由对应 TASK 证据确认 |
| P0-E 人工样本与快照 | 多周期/状态转移/ProtectedHigh/边界/3M 时序标注、warmup 与 random-slice 初始快照 | §07、§21、§24；B02b/B03a/B03b/B01b | **PB-01…PB-51 全部纳入自动化黄金样本；任何一个未实现、未执行或未通过均不得判完成。** 数据版本/哈希、标注复核与分歧裁决、各状态最低样本数、Macro-F1 标签集/算法/门槛冻结并可复现（OD-05） |
| P0-F 成本/元数据 | 费率版本、Funding、滑点、合约元数据、成本一致性测试、REQUIRED 启动门禁 | §14、§18、§19、§21；B02a 与后续 B02c | 线性 USDT 合约范围门禁；相关版本/RESEARCH 参数可追溯；OD-06 涉及换汇时拒绝将结果标为有效净收益/风险 |

P0-A…F 的“实现存在”与“规格验收通过”分开记录。必要任务可并行，但只有完整任务 DAG、明确依赖、互斥文件集和证据有效时才能并行。

### 5.2 P1/P2/P3 交易主链和验收

| 规格阶段 | 内容与验收范围 | 对应 SACW 批次 | 下一步准入 |
|---|---|---|---|
| P1-A 多周期状态机 | 1MONTH/1W/1D/4H/1H；按人工样本验收 §08/09；覆盖 Protected 点生命周期、状态映射、RANGE | B03b；既有 Macro/4H/1H 引擎先做差距核验 | P0-E 全部通过 + OD-05 冻结；OD-04 未决状态映射仍不可验收 |
| P1-B Setup | Setup4H/1H、回撤低点、观察区交集、生命周期、Zone 版本同步、EXPIRED/INVALIDATED 传播 | B04；PB 适用样本 | P1-A 通过，P0-D 出口通过；完成后才准入 P1-C |
| P1-C 15M Signal | BREAKOUT_CONTINUATION/PULLBACK_CONTINUATION、回撤起点、TriggerSwingHigh 唯一性、N 结构引用、Signal 生命周期 | B05；PB 适用样本 | P1-B/B04 通过；PullbackLow 更新时旧 TriggerSwingHigh/HigherLow 失效；BREAKOUT 的 trigger ID 为空，PULLBACK 必填 |
| P1-D 3M Execution | 3M 分形、信号后 SwingLow/High、突破 Bar 时序、执行确认、追价和成交偏差 | B06 | P1-C/B05 通过；3M 不产生独立方向/入场信号。OD-01 未决前不准入 Live |
| P2 风险与订单 | 仓位/成本风险、固定止损按成交均价重算、结构止损、移动止损、风险升级/解除、部分成交/保护单数量、止损成交模型、PositionManager | B07→B08；B02c 在 B06、B08 后接成本 | 各适用 PB/压力边界全部通过；逐 Fill 记录、最大单笔不利偏差、CanOpen/CanHold 分离等 §24 约束闭环。OD-03 未决时不宣称异常重试/人工接管闭环完成 |
| P3 组合验证 | 完整历史、分市场阶段、随机片段、参数敏感性、成本/滑点压力、样本外 | B09 | P0-P2 相关出口全部满足；按 §21/22/24 报告可复现；全冻结门禁过后才冻结规格 |
| SACW 治理附线 | Trial/Experiment、搜索/Pareto/Holdout、审批/发布/回滚 | B10b→B10c→B10d | B10c 依赖 B09+B10b，B10d 依赖 B10c；固定/必需参数保护与人审审批，不自动发布 |

### 5.3 第 24 章完整冻结门禁（通过证据逐项登记）

冻结门禁使用逐条证据清单，不将多个条件合并成一个“通过”：

| # | 冻结检查项 | 验收证据要求 |
|---|---|---|
| 1 | P0-A 至 P0-F 均通过测试 | 对应 TASK、规格映射、命令/结果、数据/配置版本 |
| 2 | ProtectedLow 与 ProtectedHigh 生命周期可确定性复现 | 黄金样本及重复回放证据 |
| 3 | 所有周期状态机通过人工黄金样本 | 各周期标签集合、固定数据哈希、统计报告 |
| 4 | Zone 状态转换无遗漏 | 状态转移覆盖矩阵与边界用例 |
| 5 | Setup 生命周期传播正确 | 父子终态、EXPIRED/INVALIDATED 区分测试 |
| 6 | 15M 两类 Signal 触发 SwingPoint 可唯一确定；BREAKOUT trigger ID 为空，PULLBACK trigger ID 必填 | PB 对应样本与引用 ID 断言 |
| 7 | 3M 严守 Signal 后确认与突破时序 | 事件时间顺序/Bar 边界测试 |
| 8 | 3M 不产生独立方向或入场信号 | 负向断言真实求值 |
| 9 | 回测无未来数据引用 | as-of / 时间截断/因果性测试 |
| 10 | Bar 回测成交价格与订单时间约束一致 | 执行模型与 Bar 时间边界测试 |
| 11 | 固定止损按实际成交均价重算 | 多 Fill 精确算术测试 |
| 12 | 止损单从生效后的 Bar 才能触发 | 同 Bar 与下一完整 Bar 对照测试 |
| 13 | 实际成交风险处置闭环完整 | 风险超限与异常路径回归 |
| 14 | REQUIRED 缺失启动门禁有效；RESEARCH 实值可追溯 | 缺省/错误配置拒绝与版本快照证据 |
| 15 | 成本、滑点和合约元数据版本可追溯 | 费用/Funding/滑点/元数据版本审计 |
| 16 | 成交偏差检测、剩余订单撤销与风险预算联动完整 | 多 Fill 偏差阈值及仓位风险测试 |
| 17 | 部分成交后的保护性止损数量不大于实际持仓 | 部分成交数量约束测试 |
| 18 | 相同输入确定性复现 | 独立重放 Hash/状态序列比较 |
| 18a | ACTIVE Signal 的 partially_filled 区分未成交与部分成交 | Signal 状态测试 |
| 18b | 风险恢复连续计数：1H 连续 3 根 BULLISH、4H 连续 2 根 TREND_UP；升级触发 Bar 不计，从下一根完整 Bar 起算，中断清零 | Bar 序列边界测试 |
| 18c | 已成交 Signal 剩余订单终止后为 PARTIALLY_EXECUTED；EXPIRED/CANCELLED 仅允许零成交 | 成交与终态组合测试 |
| 18d | 15M ATR 快照来源明确；无效 ATR 不计算倍数或静默替代 | INVALID_ATR 与快照来源断言 |
| 18e | 初始/部分成交后止损低于当前可执行退出价，否则紧急退出/异常 | 可执行价边界测试 |
| 18f | 保留全部 FillRecord；单笔偏差超限不被累计均价掩盖 | 逐 Fill 审计与订单聚合对照 |
| 18g | 风险预算减仓使用不含已发生入场费用的 CurrentRiskPerUnit | 风险预算公式测试 |
| 18h | CanOpen 与 CanHold 分离；风险恢复用 CanHold | 状态权限组合测试 |
| 18i | 每笔 Fill 独立审计，订单最大单笔不利偏差不被均价掩盖 | 多 Fill 不利偏差测试 |
| 18j | initial_stop_atr_15m 首笔成交后不可修改；每次止损更新保存 stop_update_atr_15m | 不可变字段与止损更新审计测试 |
| 19 | 随机片段使用有效初始状态快照 | 快照哈希、状态恢复与结果重复性证据 |
| 24-A | 风险异常期间冻结新开仓、持续告警；记录异常、订单/持仓、请求/回报、成交/余量、对账及人工操作 | 异常状态机端到端审计 |

OD-03 的重试上限、退避与人工接管门槛未确认前，不得把这些未决动作算作通过；相关风险异常能力不可宣称自动处置闭环完成。每项证据须指向 TASK/规格条款、固定数据/配置哈希、测试命令及结果、审查结论与报告路径。任一项未实现、未执行、失败或不可复现，则保持未冻结，不得宣布已进入完整策略回测。


---

## 六、每批出口标准汇总（历史任务切分参考；准入以第 5 节为准）

| 批次 | 出口标准 | 依赖 | 可并行 |
|---|---|---|---|
| B00 | ATR_MA22 修正、Zone 两参数、乐观锁、编码前检查清单（状态待 TASK-002 与代码复核） | 无 | 与 B01a |
| B01a | 回放 API、比较持久化、前端触发、确定性测试 | 无 | 与 B00 |
| B01b | PB 框架、正负向断言、差异定位、批量运行、结果冻结；历史统计 6 例 PASS、2 例 SPEC_AMBIGUITY、43 例 `BLOCKED_BY_UNIMPLEMENTED_STAGE`（需重跑复核） | B01a | 与 B02a、B02b |
| B02a | 成本模型、数据结构、单元测试；不接入交易记录 | 无 | 与 B01b、B02b |
| B02b | ProtectedPoint、StateInterval、手动覆盖、属性编辑、筛选 | B00 | 与 B01b、B02a |
| B03a | Golden Dataset API、人工标注完成、7.2 门槛达到 | B02b | 人工标注与 B01b 并行 |
| B03b | P1-A 与人工样本一致率达标、确定性回放、因果性、边界测试 | B01b、B03a | 无 |
| B04 | Setup4H/1H 状态机、生命周期、Zone 版本同步 | B03b | 无 |
| B05 | BREAKOUT/PULLBACK Signal、生命周期、ATR 快照、唯一性 | B04 | 无 |
| B06 | 3M 分形、时序、追价、成交偏差 | B05 | 无 |
| B07 | 止损、移动止损、风险升级、超限处置 | B06 | 无 |
| B08 | Order/Position 状态机、部分成交、FillRecord | B07 | 无 |
| B02c | 成本接入 Fill/Position/Trade、净收益、成本归因 | B06、B08 | 无 |
| B09 | 完整回测、分阶段、随机片段、样本外、统计项 | B08、B02c | 无 |
| B10b | 参数白名单、Trial 存储、Experiment/Trial UI、Holdout 权限 | B00 | 与阶段 2 并行 |
| B10c | 参数搜索、Pareto、敏感性、Holdout 隔离 | B09、B10b | 无 |
| B10d | 配置候选、审批、发布、回滚 | B10c | 无 |

> **状态说明：** 上表只概括历史批次出口目标，不记录当前执行状态。当前状态与准入以第 〇 节、第 5 节及 `tasks.json` 为准；未逐项复核的历史批次状态不作当前事实。

---

## 七、全局禁止事项

每批任务书必须附以下禁止事项，来自 V1.4.8 13.4 和 SACW 13.4：

1. 禁止自行更改 V1.4.8 策略定义、状态机、ATR 快照时点、信号触发顺序、执行时间边界、参数分类。
2. 禁止使用未来数据或未完成 Bar。
3. 禁止把 `occurred_at` 和 `confirmed_at` 合并。
4. 禁止把 Signal 标记当成实际成交标记。
5. 禁止让人工标签和程序预测共用可覆盖的表。
6. 禁止让优化器修改 FIXED / REQUIRED / METADATA。
7. 禁止将候选配置自动发布到正式环境。
8. 禁止通过删除难例、改变匹配容差或重标样本虚增匹配率。
9. 禁止集成来源不明或许可不匹配的 TradingView 图表库。
10. 禁止为 NStructure 失效 ATR 时点自行选择替代 ATR；必须标记 `SPEC_AMBIGUITY`。
11. 禁止前端写入 `ALGORITHM_DERIVED` 的 `confirmed_at`。
12. 禁止将 15M 层显示对象标记为独立 15M Zone。
13. 禁止在 PB-12/13 阻塞期间通过调参让它们“通过”。
14. 禁止 B01b 为了追求 51 例全 PASS 而伪造引擎或跳过阻塞分类。

---

## 八、历史里程碑记录（2026-11-16；以第 5 节准入矩阵为准）

> 本节状态与数字为旧快照，特别是“annotations 0 条”和阶段门槛结论已经过期，不代表当前状态；复核见第 〇 节。

### 里程碑 1：阶段 0 完成　🟡 当时未达成

- 🟡 B00、B01a 完成；
- ✅ SACW 文档一致性修正（随 V1.1.2 落地）；
- 🟡 回放 API 可用（✅），比较持久化（⬜——比较仍读内存）。

### 里程碑 2：阶段 1 完成　⬜ 2026-11-16 时未达成

- ⬜ B01b、B02a、B02b、B03a、B03b 完成；
- 🟡 PB 框架就绪，6 例 PASS，2 例 SPEC_AMBIGUITY，43 例 MISSING_ENGINE（实际为 `BLOCKED_BY_UNIMPLEMENTED_STAGE`）；
- ⬜ 成本模型单元测试通过；
- ⬜ 当时人工标注完成并冻结（数据库 0 条标注、0 个黄金样本）；
- ⬜ 当时 P1-A 通过人工黄金样本验收。

当时记录的阶段门槛是后续开发准入门槛；当前 P1-A 准入结论请以第 〇 节和第 5 节为准。

### 里程碑 3：阶段 2 完成　⬜ 未开始

- B04、B05、B06 完成；
- PB-01～07、PB-14～16、PB-23～26、PB-31 通过；
- Setup → Signal → Execution 决策链可完整重放。

### 里程碑 4：阶段 3 完成　⬜ 未开始

- B07、B08、B02c 完成；
- PB-08～11、PB-17、PB-36～38、PB-40～43、PB-46、PB-50～51 通过；
- 开仓、部分成交、撤单、减仓、平仓、异常恢复可运行。

### 里程碑 5：阶段 4 完成　⬜ 未开始

- B09 完成；
- 回测报告包含 SACW 22 章全部统计项；
- 样本外验证通过。

### 里程碑 6：阶段 5 完成　⬜ 未开始

- B10b、B10c、B10d 完成；
- 参数校准、Holdout 隔离、配置发布闭环。

---

## 九、PB 通过率演进预期（已过期的历史预测，不作当前目标或状态）

> 下表仅为 2026-11-16 估算，数字和当前行均未在本轮重新跑 PB 验证；移除或重算前不得作为目标、基线或结果引用。

| 里程碑 | 可执行 PB | PASS | SPEC_AMBIGUITY | MISSING_ENGINE |
|---|---:|---:|---:|---:|
| 当前 | 6 | 6 | 2 | 43 |
| 里程碑 1 | 6 | 6 | 2 | 43 |
| 里程碑 2 | 6 | 6 | 2 | 43 |
| 里程碑 3 | 约 16 | 约 16 | 2 | 约 33 |
| 里程碑 4 | 约 30 | 约 30 | 2 | 约 19 |
| 里程碑 5 | 49 | 49 | 2 | 0 |

**说明**：里程碑 1、2 不会让 PB 通过率立即上升，这是预期行为。B01b 的价值是让 PB 可执行、可分类、可定位，为后续批次解除 MISSING_ENGINE 提供基础。里程碑 3 开始，PB 通过率才逐步上升。

> **历史实测（2026-11-16；本轮未重新运行）：** 可执行 6 例、PASS 6 例、`BLOCKED_BY_SPEC_AMBIGUITY` 2 例（PB-12/13），
> 其余 43 例为 `BLOCKED_BY_UNIMPLEMENTED_STAGE`，**不是**本表写的 `MISSING_ENGINE`。
> 数字与「当前」行一致，但分类口径尚未落地；上表里程碑 1、2 的 `MISSING_ENGINE` 一列
> 在 B01b 补完分类前应读作 `UNIMPLEMENTED_STAGE`。

---

## 十、历史结论（不可替代当前准入判断）

本执行计划与 V1.4.8 和 SACW V1.1.1 的依赖关系一致，修正了原计划的 6 处问题：

1. B01 目标改为“PB 执行框架就绪”，不要求 51 例全 PASS；
2. 增加 B01a 回放 API + 比较持久化；
3. 增加 B02b / B03a 标注工具；
4. B02 拆成 B02a（成本模型）和 B02c（成本接入交易记录）；
5. B10 拆成 B10b / B10c / B10d；
6. 补 4 项前置修正：乐观锁、Golden Dataset API、ATR_MA22 歧义、Zone 两参数。

**历史下一步建议（2026-11-16；已被本版“本轮核验的后续工作顺序”取代）：** 当时建议收尾 B00/B01a、补 B01b、开工 B02a/B02b、启动 B03a。具体事项当前是否仍适用，须先核对相应 TASK 状态与代码，不沿用当时“当前完全空白/0 条”等快照。

---

## 十一、历史核对发现（2026-11-16，待按现状复核）

以下问题是 2026-11-16 当时记录的风险/缺口，不是本轮重新验证的事实；须先复核再影响出口判定：

1. **比较链路未消费 `program_events`（B01a-2）。** 四个比较端点的程序侧数据全部取自
   内存 `MarketContext`，`replay_runs` / `program_events` 只是并行写了一份快照。
   计划的核心要求“冻结 Ground Truth → 程序回放 → 比较事件持久化”目前只完成了第三段的存储，
   第二段与比较之间没有连接，因此“回放确定性”尚不能证明“比较可复现”。
2. **`BLOCKED_BY_MISSING_ENGINE` 分类缺失（B01b-3）。** 43 例只有统一的
   `BLOCKED_BY_UNIMPLEMENTED_STAGE` 与一句合并原因，无法按缺失引擎定位；
   计划「一、总体原则」第 3 条“引擎缺失阻塞与规格歧义阻塞分离”只完成了规格歧义一侧。
3. **负向断言是“无条件通过”（B01b-2）。** `RegressionRunner._run_case` 对
   `expected_absent_events` 直接 append `RESULT_PASSED`，理由为“当前阶段无可执行的产生路径”。
   这会让负向断言在引擎实现后仍恒为通过，违反全局禁止事项中“不得虚增匹配率”的要求，
   应在 B04 前后改为真实判定。
4. **`web/app.js` 的 `drawManualAnnotations` 被 `payloadSummary` 片段污染。**
   第 733～742 行（STATE_INTERVAL、PROTECTED_POINT 的 `return`）以及第 1800～1808 行
   （`renderAnnotations` 内同源片段）是从 `payloadSummary` 误粘贴的死代码：
   - `drawManualAnnotations` 遇到 STATE_INTERVAL / PROTECTED_POINT 标注时直接返回字符串，
     导致其后的 `else if (PROTECTED_POINT)` 分支**永远不可达**，人工 ProtectedPoint 价格线画不出来；
   - `renderAnnotations` 对这两类标注提前 return，列表项的徽章与操作按钮不会渲染。
   会影响 B02b 出口“标注工具可用”的判定，需单独修复。
5. **`expected_revision` 未强制（B00-3）**，且前端完全没有 PATCH 调用，
   “标注已被他人修改，请刷新”这条 UI 提示无法触达。
6. **`program_events` 表缺 `source_bar_id` 与 `config_hash`**（实为 `bar_id`，`config_hash`
   只在 `replay_runs` 上），与计划字段清单不一致。
7. **SACW 版本漂移。** 计划基线 V1.1.1，仓库规格为 V1.1.2。V1.1.2 已包含 B00 的文档修正
   并要求 8.1 白名单与 V1.4.8 第 19 章 36 项 RESEARCH 参数逐一对应；后续任务书应以 V1.1.2 为准。
8. **测试基线漂移。** 计划写 327 tests，README 写 333，实测 340 passed；数字需随代码更新，
   避免用旧计数作为验收依据。

---

## 十二、历史收口记录（2026-11-17）

> 以下内容为 2026-11-17 的历史工作记录；其中“当前/仍未完成”、旧数据库计数及阶段结论不是 2026-11-21 现状。现况以第 〇 节为准。

当时本轮只做人工标注工具链，不进入阶段 2。实现记录：

1. **B00-3 前端乐观锁闭环。** `PATCH /annotations/{id}` 现在强制要求
   `expected_revision`，缺失返回 `EXPECTED_REVISION_REQUIRED`；前端属性编辑
   携带版本号，409 时提示「标注已被他人修改，请刷新」。
2. **B02b 工具补齐。**
   - 修复 `web/app.js` 中 `drawManualAnnotations` / `renderAnnotations` 被
     `payloadSummary` 片段污染的问题：ProtectedPoint 价格线与列表徽章/操作按钮恢复；
   - Swing 价格手动覆盖：待提交面板可改价，必须填写原因，保存
     `manual_price_override=true` + `override_reason`，列表显示「人工改价」；
   - 保护点强制 `source_swing_id`，前端提供同向已确认 Swing 选择；
   - StateInterval 在图上绘制背景色带（独立透明 canvas，按时间坐标绘制）；
   - 标注列表支持关键字搜索与对象时间区间过滤（后端 `search` / `time_from` /
     `time_to`，日期端点按自然日处理）；
   - 属性编辑 UI（PATCH）、复制为 DRAFT（`POST /annotations/{id}/copy`）、
     撤销/重做（按钮与 Ctrl+Z / Ctrl+Y）。
3. **B03a 切分能力。** `time_split_hash` 落地到 `dataset_splits` 与
   `golden_datasets`；`POST /golden-datasets/{id}/split` 省略区间时按数据时间范围
   自动 60/20/20 三分，并回写统一哈希；前端数据集页签提供「自动三分」入口。

**当时未完成项（旧快照，不代表现状）：** 人工标注实际录入与冻结（数据库当时记录为 0 条）、
SACW 7.2 的 Macro-F1 / Per-State Recall / 转换时间误差验收、B03b、B01b 的分类与
差异定位、B01a 的比较读持久化事件。当前是否完成均须按第 〇 节、任务台账和新证据重核。

