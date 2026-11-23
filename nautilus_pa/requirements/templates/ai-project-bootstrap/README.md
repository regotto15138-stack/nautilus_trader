# AI 协作工程模板（Bootstrap）

此目录提供新项目初始化模板。按项目规模和安全要求裁剪，不将任何具体项目业务假设照搬过去。模板参考 [归档的 DSH 大型项目开发操作标准](../../archive/DSH%20大型项目开发操作标准.md)，以任务追溯、最小上下文、范围权限、独立验证和可恢复会话为核心。

## 新项目初始化顺序

1. 先读平台/仓库贡献、安全规范；确定项目语言、框架、数据风险、Git 拓扑及不可覆盖文件。
2. 复制 `AGENTS.template.md` 为项目根 `AGENTS.md`，改成具体项目规则；不要覆盖已有 AGENTS，先合并并记录优先级。
3. 复制 `PROJECT_CONTEXT.template.md` 为 `PROJECT_CONTEXT.md`，只填可验证的简明事实，未知项标待验证。
4. 创建 `requirements/REQUIREMENTS.md`、`requirements/ACCEPTANCE.md` 和 `requirements/CHANGE_REQUESTS.md`，明确各自唯一职责。
5. 按项目选择任务台账实现：简单项目可用规范化 TASK 文件/索引；需要自动校验时使用 `.dsh/tasks/tasks.json` 为唯一机器状态来源。不可同时让多个文件成为状态权威。
6. 填写任务、角色、输入输出契约、token budget、permission policy、session handoff 和 review 模板。权限要通过工具/沙箱/Git 范围落实，不能只写在提示词里。
7. 用一个小型只读/文档任务试跑启动协议、任务拆分、状态转换、校验和交接，再进入业务开发。

## 每次新 AI Session 启动清单

- [ ] 读取项目 AGENTS、项目状态快照与上游安全/贡献约束。
- [ ] 核对唯一任务状态源、当前任务契约、依赖、owner 和允许/禁止路径。
- [ ] 阅读必要的交接文件；交接摘要必须与 Git/文件现实核对。
- [ ] 运行 `git status` / 最近提交检查，识别并保护用户已有工作区改动。
- [ ] 只加载 L0→L1→L2→L3 的当前任务必要上下文，不遍历无关模块。
- [ ] 任务未登记/未 READY 时先澄清需求、拆分、定义验收与验证，不先动手改文件。
- [ ] 开工登记状态/owner；每次变更后做范围审查、Diff 检查和任务规定的最小测试。
- [ ] 不伪报完成；将失败、未运行检查、风险、遗留项明确记录。
- [ ] 结束/切换前按需增量更新状态快照，写 Session handoff，不执行破坏性清理。

## 新项目必须做的裁剪

- 源代码目录、测试命令、路径规范、数据类型、兼容性、并发模型、缺陷等级、提交规则、CI/部署门禁均须来自目标项目实况。
- 多 Agent 仅用于任务确实可分离且写入路径互斥的情况；不要求每个任务都启动完整角色组。
- token 预算和阈值属于规划管理，不宣称为模型/DSH 硬性限制；以实际工具能力为准。
- 简单项目不必部署 DSH 插件，但仍需保留需求来源、范围、验证和 Git 状态的事实记录。
- 交易、医疗、金融或其他高风险系统应在模板基础上增加领域安全评审与明确的人类授权门禁。

## 模板文件

- [AGENTS.template.md](./AGENTS.template.md)：每轮协作协议和项目规则骨架。
- [PROJECT_CONTEXT.template.md](./PROJECT_CONTEXT.template.md)：紧凑状态快照。
- [TASK.template.md](./TASK.template.md)：可追踪、可验收的任务契约。
- [SESSION_HANDOFF.template.md](./SESSION_HANDOFF.template.md)：跨 Session 恢复记录。
- [BOOTSTRAP_CHECKLIST.md](./BOOTSTRAP_CHECKLIST.md)：项目首次启用前核对表。
