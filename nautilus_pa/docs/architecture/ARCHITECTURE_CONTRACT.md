# 架构保护与变更控制契约

本契约落实用户的 Architecture Stability & Minimal Change Policy。
任务状态仍只以 [tasks.json](../../.dsh/tasks/tasks.json) 为准。

## 四级授权

| 级别 | 授权范围 | 重构与审批 |
| --- | --- | --- |
| L0 | SPEC、说明、相关文档；Main 可同步任务台账 | 禁止实现与重构 |
| L1 | 明确指定的函数、类、模块及相关测试 | 最小必要补丁，禁止重构与公共 API 变更 |
| L2 | 明确指定接口与必要调用方，兼容性约束逐项列出 | 必须单独人工审批；架构重构仍需 L3 |
| L3 | 明确列出的模块边界、公共接口、前后端架构调整 | 独立 TASK、影响分析及单独人工审批 |

所有级别均需 TASK 授权。L2/L3 不代表全仓库授权，仍受文件白名单约束。
新任务默认 L1，所有变更权限默认 false；DRAFT 不是批准，不能下发执行。
新功能若需要前端文件，只能在 `frontend_change_allowed=true` 且路径明确时实施，
不代表可以重构前端。数据库迁移同理，涉及模块或数据职责变化必须升级 L3。

## 六项架构保护

1. **模块边界冻结**：沿用现有 domain、application、config、adapters、presentation、web
   分层及职责；domain 不导入 NautilusTrader。未获 L3 授权不得移动职责、拆合模块或换技术栈。
2. **公共 API 兼容**：默认不得删除、重命名接口或改变参数、返回值、错误行为、时间/数据语义。
   内部实现变化也要保持任务未授权改变的外部可观察行为。接口变化需 L2/L3 与逐项兼容验证。
3. **前后端隔离**：后端算法规则变化不自动授权 API、载荷、前端组件或显示流程修改。
4. **数据库兼容**：默认保持 SQLite schema、冻结快照、历史数据语义与读取兼容性。
   Python 文件内嵌 SQL 也属于 schema 变更，不能以扩展名绕过审批。
5. **最小补丁**：先复用现有入口，仅修改新规则必要逻辑与测试；不顺带整理、改名或清理代码。
6. **冲突升级**：无法在现有边界内实现时停止受影响任务，返回 `DESIGN_CONFLICT` /
   `BLOCK_AND_REPORT`；Main 将任务置 BLOCKED，附 Change Request，不自行扩大 allowed_paths。

## SPEC → Change Control Layer → PLAN/TASK → 实现 → 门禁 → 审查

SPEC 的修改只授权文档。Main 在代码任务 READY 前完成影响分析：

- `spec_id` 标识规则；`impact_analysis.sources` 保存实际审阅的 SPEC/契约文件 SHA-256。
  哈希变化须重新分析并确认授权，哈希一致不等于人已批准规格。
- `rules`、`modules`、`interfaces`、`tests` 列受影响项及不变项，不能只写“全部”。
  先按引用、调用方、导入关系和既有测试搜索，再由人审确认；路径扫描不能证明影响分析完备。
- `code_change_required=false` 时生成 L0，`decision=document_only`；需要局部实现时生成 L1，
  `decision=minimal_patch`。架构不兼容须先提 Change Request，不得给 L1 放行。
- `change_policy` 固定 default=minimal_patch，显式列四个布尔值：`refactoring_allowed`、
  `public_api_change_allowed`、`database_schema_change_allowed`、`frontend_change_allowed`。
- `approval` 记录 `level`、`approved_by`、实际授权 `evidence`；L2/L3 额外要求
  `separate_approval=true`。审批者必须是人，Agent 不得凭分析结论补造批准记录。
- `allowed_paths`、`forbidden_paths`、验收及回归命令逐项固定；
  `on_scope_violation=BLOCK_AND_REPORT`。范围/规则/级别变化后重新审批，不能沿用旧授权。

Change Request 至少包含：冲突的 SPEC 条款/源码证据、为什么局部补丁不可行、
最小替代方案、涉及模块/API/前端/schema、兼容与迁移回退策略、拟新增 L2/L3 TASK 范围、
风险与测试、人工决定及证据。未批准的请求只可分析，不可执行。

例：ZigZag Swing 确认规则先改 SPEC；分析 detector、Swing 消费者和既有测试；
生成仅授权 detector 与相关测试的 L1。发现必须改变 Swing 公共数据契约时停止，
另提 L2/L3 请求，不能顺带修改 API、web 或数据库。

## 可执行检查与保障边界

`taskctl.py new --change-level L1 --spec-id SPEC-...` 创建待补齐的 DRAFT。
Main 补齐影响分析、真实批准、范围、验证与六项拆分门槛后才能 READY。
`set-status` 进入 READY/IN_PROGRESS 和 `dispatch` 检查授权、来源哈希、blockers、依赖。
旧任务不批量补造授权：历史结构仍可读取，但再次执行或提交前必须补齐控制契约。
下发包含全部变更控制及增量计划、追溯、验证字段，命令行不得覆盖台账的接口契约。

语义前置必须 ACCEPTED。仅文件写入排序可在 `dependency_policy[TASK-ID]` 中显式记录
`kind=write_order` 与释放写入的 `evidence`，且前置只能处于 IMPLEMENTED/REVIEWING/TESTING；
它不能替代业务前置验收。Main 与 Reviewer 必须核对分类和固定输入。

执行前后运行范围检查（路径相对 nautilus_pa，目录以 `/` 结尾，支持 glob，禁止项优先）：

```bash
python3 .dsh/scripts/check_scope.py TASK-NNN --worktree
python3 .dsh/scripts/check_scope.py TASK-NNN --staged
python3 .dsh/scripts/check_scope.py TASK-NNN --base <base-sha> --head <head-sha>
```

worktree 检查 HEAD 的暂存及未暂存差异和未跟踪文件；混合工作树不能把原有越界改动
宣称为当前任务通过。CI 模式检查三点 Diff；同一变更含多个任务时需由受信任编排按任务
分别验证，不允许把多任务白名单简单并集来掩盖越界。删除和重命名两端均检查，Git 失败拒绝。
L0 拒绝非 Markdown 文件（仅任务台账为 Main 行政例外）；常见 web、数据库路径还有显式权限检查。
提交门禁复用相同规则；本地 hook 可绕过，不能等同受保护分支上的必需检查。

CI 运行上述范围门禁、相关回归测试和项目现有 API/数据契约测试，失败阻止合并。
本次提供可调用的 CI 入口，**未修改上游 workflow、安装 hook 或设置远程分支保护**。
维护者需将入口接入必需检查，且从受信任基线加载脚本、审批与 TASK，防止提交自改门禁/批准。
审批字段是可审计记录，不是密码签名；脚本不能判断证据是否真实或发现所有语义/架构变化。

文件范围检查能拒绝越权 Diff，不能防止进程先写文件；workspace-write 也只限制工作区，
不会自动按 TASK 缩小写权限。执行期保护要由宿主将白名单变为实际文件系统权限/沙箱，
保护台账和审批记录；当前共享工作区不宣称已具备此能力。兼容性及隐性重构仍需契约测试、
架构审查与人审；相关回归通过降低业务风险，不能保证绝无行为回归。

SPEC defines behavior. PLAN defines implementation strategy. TASK authorizes changes.
DSH implements within scope. CI enforces boundaries. Human approves architectural changes.
