# 子 Agent 输入契约（Agent Input Contract）

Main 下发任务时使用本格式。缺任一必填字段，子 Agent 必须拒绝开工并返回
`CLARIFICATION_REQUIRED`，不得自行猜测。

## 格式

    {
      "task_id": "TASK-002",
      "role": "developer",
      "objective": "一句话说明要达成的结果（不是要写的代码）",
      "requirement_refs": ["REQ-001"],
      "context_files": ["src/pa_trend/presentation/api.py", "tests/unit/test_api.py"],
      "allowed_paths": ["src/pa_trend/presentation/", "tests/unit/test_api.py"],
      "forbidden_paths": ["configs/", "README.md"],
      "interfaces": "本次允许变更/必须保持的接口清单",
      "dependencies": ["TASK-001"],
      "acceptance": ["可验证的验收条目，逐条对应测试"],
      "test_plan": ["运行哪些测试，命令是什么"],
      "token_budget": {"total": 20000, "input": 15000, "output": 5000},
      "output_format": "AGENT_OUTPUT",
      "handoff_note": "可选：上一任务的结论、已知陷阱"
    }

## 字段规则

| 字段 | 必填 | 规则 |
| --- | --- | --- |
| task_id | 是 | 必须存在于 `tasks.json`，状态为 READY/IN_PROGRESS/REVIEWING |
| role | 是 | architect / developer / reviewer |
| objective | 是 | 可独立验证的结果描述，不写实现步骤 |
| requirement_refs | 是 | 至少一个 REQ-ID，能追溯到 `requirements/REQUIREMENTS.md` |
| context_files | 是 | 精确文件路径，不含整个目录；宁少勿多 |
| allowed_paths | 是 | 目录以 `/` 结尾表示整棵子树；与 tasks.json 一致 |
| forbidden_paths | 是 | 显式列出高风险文件（配置、文档、上游路径） |
| interfaces | 是 | 允许新增/修改的公开接口；不允许的写"不变" |
| dependencies | 是 | 依赖的已完成任务；无则空数组 |
| acceptance | 是 | 每条都能用命令或 Diff 判定真假 |
| test_plan | 是 | 具体命令，不含"跑全部测试"这种模糊表述 |
| token_budget | 是 | 与 `config/token_budget.md` 一致 |
| output_format | 是 | 固定 `AGENT_OUTPUT` |

## 自动生成

    python .dsh/scripts/taskctl.py dispatch TASK-002 --role developer

从 `tasks.json` 读取任务并渲染上面的 JSON，直接粘贴给子 Agent 或作为 subagent prompt 的种子。

## 拒绝与异常

| 码 | 含义 | 子 Agent 动作 |
| --- | --- | --- |
| CLARIFICATION_REQUIRED | 契约缺字段或验收不可判定 | 停止，列出缺口 |
| BLOCKED | 依赖未完成、环境不可用 | 停止，报告阻塞点 |
| DESIGN_CONFLICT | 需求与现有架构/接口冲突 | 停止，给出冲突证据 |
| CONTEXT_LIMIT | 预算不足以完成 | 停止，交接已完成部分 |
| FAILED | 实现或测试失败 | 报告失败原因与已尝试方案 |
