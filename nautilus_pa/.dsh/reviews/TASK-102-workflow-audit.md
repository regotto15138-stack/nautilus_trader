# TASK-102 开发体系与规格变更审计

日期：2026-11-24。角色：Main。范围：项目流程、任务下发、指标规则、关键代码和当前测试基线。
本报告为诊断产物，不修改业务语义、不批准候选spec、不代表独立Reviewer验收。

## 1. 结论

当前业务测试可运行，工程执行约束未形成闭环，不能评价为“开发体系正常”。
规格变动引发的混乱同时包含真实未决语义、任务输入丢失、审批/研究模式未隔离及调度过度串行。
仅增加计划和规则文本不能解决执行入口遗漏。

本轮复跑：`PYTHONPATH=src ../python/.venv/bin/python -m pytest -q tests/unit tests/integration`
→ **481 passed in 35.43s**。这是当前工作树结果，不能代替候选规则批准、真实浏览器及策略阶段出口。
此前470项为历史结果，本轮未增加/删除业务测试，不推定数量差异的来源。

DeepSeek Harness CLI在本机存在，`dsh --help`成功，项目有developer/reviewer/architect preset。
本轮未调用其他模型写代码，未读取用户账户凭据；当前实际会话使用哪个preset、是否恢复旧上下文，
以及最近一次“指标冲突”的原始回复尚未取得，不能断言每一次提示均由同一原因造成。

## 2. 已复现的执行链问题

### F1 / P1：增量计划未进入下发契约

证据：`.dsh/scripts/taskctl.py::cmd_dispatch`仅导出13个字段。
对TASK-030实际调用，缺少`status`、`priority`、`incremental_plan`、`blockers`、
`traceability`、`verification`和`dependency_reasons`。
TASK-101新增的差量说明存在于台账，但没有随默认dispatch输出传给Developer。

影响：计划要求“只补残余”，契约却只给泛化目标和包含候选规则的整体验收。
Developer必须再自行读任务表才能补齐；若只消费下发JSON，会丢失新旧边界和局部门禁。
preset确实要求读任务表，故“遗漏字段”不等于证明实际会话完全没读到；仍是下发链路的确定缺陷。

修复方向：先补契约字段、任务目标基线和局部受限能力，再测试输出完整性；不继续复制更多计划正文。
需要明确“已满足/允许改动/未决且不得修改”，而非让执行者自己从历史文件推断。

### F2 / P1：开工约束主要停留在文字，CLI可绕过

证据：当前TASK-083为BLOCKED、TASK-066为DRAFT，`cmd_dispatch`仍成功输出开发契约。
该函数既不检任务状态，也不检前置状态或规格批准。
`cmd_set_status`只检状态枚举迁移；`validate_tasks.py`检依赖存在/无环，不检依赖验收或六门槛。
TASK-030/031/032/035均IN_PROGRESS，而共同前置TASK-095仍DRAFT；两个结构校验脚本照常通过。
这可能含已被授权的研究实现，工具没有结构化字段区分，不能据状态单独判定全部为违规交易实现。

另一个可核对缺陷：`save`先写台账，再验证；验证失败只打印warning，调用方仍可返回0。
上一轮TASK-101漏owner曾实际触发该行为。

修复方向：先设计并验证候选数据的预检，失败不覆盖台账且非零退出；dispatch/state入口执行明确门禁。
语义前置、文件写入排序、人工审批和研究夹具授权需要分类，不能简单规定“任何前置非ACCEPTED均禁止”，
否则合法的文档核对与固定输入研究也会被误锁。旧任务不批量强改状态。

### F3 / P1：哈希一致性不能证明语义批准或执行契约完整

证据：`validate_traceability.py`检查路径/TEST-ID/命令/哈希及文件排序。
在内存副本删掉所有任务`incremental_plan`和`priority_reason`，`validate()`仍返回空错误列表。
复现未写真实台账。当前没有逐任务可校验的`approved_spec`/`execution_mode`字段；
全局`planning_baseline.sources`记录“看的是哪个内容”，并不记录“谁批准了什么行为”。

影响：候选正文与完成历史能同时指向同一路径；更新hash后结构检查通过，语义冲突仍存在。

修复方向：分清来源hash、批准证据、研究目标和兼容基线；对下发所需字段做契约校验与负例测试。
批准来源应回到实际授权记录，不能由Agent补一个APPROVED值。

### F4 / P2：任务队列把多类依赖混成全局等待

证据：TASK-095同时等待026/027/028人工Golden链及066浏览器基线，
又成为029…035等基础层共同前置。这些是不同能力出口，不能仅靠“DAG无环”证明拆分合理。
前端大量任务共享app.js/index.html/styles.css，文件排序容易被当作算法依赖。
TASK-101已减冗余边，但把BLOCKED的083放到094之后只是当前串行排程，
不表示指标诊断业务上必须依赖完整参数实验室。

影响：一次局部指标变化被放大为“所有工作先等整个门禁任务”，或反过来为开发而越过整个门禁。

修复方向：按受影响条款/能力记录门禁；文件排序只约束写者。083恢复前核实实际原因并重排，
不要强行执行全部后续研究任务作为它的前置。正式依赖调整必须重新核对任务范围、DAG和证据。

## 3. “指标冲突”必须分开处理

| 项目 | 实际文件证据 | 判断与执行边界 |
| --- | --- | --- |
| ATR14 / SMA22 | SPEC-04 §3.1、当前配置indicators、WilderAtr/SMA实现 | 周期与基础类型一致，没有证据说明这两个定义整体互相矛盾；先保留已有能力 |
| ATR_MA22 | SACW 16–22章§17.1、34章、CHANGE_REQUESTS AMB-001及配置注释 | 已明确不计算、不绘图、不入搜索；显示N/A/SPEC_AMBIGUITY是既定处理，不能据此阻塞其他指标 |
| ATR种子/缺口 | SPEC-04 §3.1、OPEN_DECISIONS OD-07、WilderAtr docstring | 代码明确首TR=High-Low、前period个TR均值作种子，审批记录仍标未冻结；“已有确定实现”不等于“已批准”，需要批准或标明研究口径 |
| ZigZag High/Low | SPEC-04 OD-ZZ-01、配置confirmation_price、config.models.ZigZagSettings | HIGH_LOW仍标待批准，但当前配置已取HIGH_LOW且模型只接受HIGH_LOW；代码入口未见显式选择已批准/研究基线，易把候选实现当默认事实 |
| occurred_at | TASK-004目标、SPEC-04 §3.6、detector._set_candidate、test_occurred_at_is_the_source_bar_close | 004已验收open_time，候选要求close_time；当前代码/测试已用close。TASK-030虽保留“批准后更新测试”约束，工作树已发生相应改变；仓库内未见冲突已获批准的证据，不能用新测试通过反推批准 |
| 图表时间与事件时间 | chart_data._source_chart_time、zigzag_points、structure_overlays | Swing绘图按source_bar_id映射open_time；N结构仍直接用occurred_at。证明消费者尚有不同时间投影路径，需契约核对；本轮未真实浏览器复现，不断言具体错位已发生 |
| N失效ATR | PROJECT_CONTEXT §4、CHANGE_REQUESTS AMB-002、TASK-031 | 局部交易失效语义未决，保持SPEC_AMBIGUITY/PB12/13阻塞；不影响ATR14本身的正常计算 |

审批问题不能靠“选最新spec”解决，因为最新文件自己声明REVIEW_CANDIDATE。
也不能强迫执行者“忽略所有冲突”，因为open/close与HIGH_LOW确实改变下游事件与黄金样本。
正确报告应列出具体条款、旧值/候选值、受影响能力、已有批准证据及可继续的无关工作。

## 4. 为什么局部spec变动扩散成全工程返工

1. spec修订不是只有文字：同一轮同时改变ZigZag价格输入、候选确认时序、Swing事件时间及Zone版本，
   其输出被结构、匹配、图表、快照、人工真值共同消费。变化本身有跨层影响，但不要求重写整个工程。
2. 已批准与候选通过同一个文件路径传播，没有逐任务可执行的目标基线与授权状态。
3. 旧任务保留open_time完成历史，当前代码和新测试已转close_time；图表只局部做来源Bar映射，
   执行者面对的是“历史正确、候选也明确、工作树又不同”的三种事实。
4. 增量计划停在台账，默认dispatch遗漏；结构校验无法发现这种丢失。
5. 状态机与门禁文字很多，实际开工/写入前未完成强校验；Agent只能反复自主解释和请求澄清。
6. 当前tasks.json在登记102后约0.8MB/16643行，历史修订和当前目标混放。
   全量读取增加旧内容进入上下文与截断的风险；这只是可见输入负担，不能据此推断实际模型成本或每次会话已误读。

TASK-101补齐计划有价值，但不足以证明体系修好。其dispatch漏传与校验未覆盖，属于上一轮未闭环的工作，
应先补执行链再继续推进业务，而不是继续增加相似的规范文件。

## 5. 最小修复顺序（本轮未实现）

| 顺序 | 单一交付物 | 验证要求 |
| --- | --- | --- |
| 1 | taskctl下发契约与预检：含差量/门禁/基线/原因，区分可开工与只读审计 | DRAFT/BLOCKED开发拒绝；合法只读审计可核对；缺字段明确失败；无效写入不落盘且非零退出 |
| 2 | 指标变更裁决记录：occurred_at、HIGH_LOW、OD07逐项明确已批准或研究目标 | 每项有授权来源、旧/新值、受影响接口和冻结数据处理；不是批量批准五章 |
| 3 | TASK-030及直接消费者的最小时间兼容切片 | 复用现有WilderAtr/ZigZag/chart adapter；分别断言领域事件时间、来源蜡烛位置、匹配和快照；旧真值不静默重写 |
| 4 | 把批准、数据冻结、文件排序分成可核对的局部门禁 | 一个指标未决只阻断相应输出；其他能力可用已批准契约继续；不降低正式验收标准 |
| 5 | Harness任务输入采用单任务完整契约与当前基线 | 从taskctl下发的固定任务开始，不给“按全部最新plan继续”的泛指令；报告写具体冲突ID/条款/未受影响工作 |

每项代码修复需另登记范围明确的TASK，并由用户选择的DeepSeek Harness执行；
本轮未替换执行器、未启动第二个写者，未擅自运行任何候选业务实现。
不需要先迁移React/FastAPI/数据库，也不需要重新生成全套spec和plan。

## 6. Harness与权限核验的限制

仓库preset确有读任务/限定范围/运行测试的指令，Reviewer禁用fs写工具但保留bash。
permission_policy明确还依赖会话read-only sandbox；仅凭preset文件不能证明实际会话已启用该沙箱。
同样，allowed_paths目前由契约约束和提交门禁检查，不等于所有写入工具在每次写入前都按TASK校验。
本轮没有取得实际会话配置和原始冲突回复，不把这些未核实状态当作已证实的Harness故障。

## 7. 本轮证据与范围

- validate_tasks.py、validate_traceability.py实测通过；这只证明它们已实现的检查范围。
- 内存导出TASK-030/083/066契约，实际复现字段遗漏及BLOCKED/DRAFT可导出；未修改这些任务。
- 内存删除增量说明再跑traceability校验，返回空错误；未删真实台账字段。
- 当前unit+integration 481 passed in 35.43s；未运行浏览器或调用DeepSeek模型生成代码。
- git diff --check及报告相对链接检查在收尾执行；结果记TASK-102 evidence。
- 本轮只写TASK-102审计报告、tasks.json中的102记录及SESSION_HANDOFF，原业务工作树保持不变。
