# .dsh 目录索引

本目录是 AI 协作流程的机器可读状态与模板。

| 文件 | 作用 |
| --- | --- |
| `config/agent_roles.md` | 角色职责与编排规则 |
| `config/permission_policy.md` | 角色 × 路径权限矩阵与五层落实 |
| `config/token_budget.md` | 任务/Session 预算与上下文分层 |
| `contracts/agent_input.md` | 子 Agent 输入契约 |
| `contracts/agent_output.md` | 子 Agent 输出报告格式 |
| `tasks/tasks.json` | **唯一任务状态来源** |
| `tasks/README.md` | 状态机、拆分门槛、提交规则 |
| `tasks/_TASK_TEMPLATE.md` | 任务详述模板 |
| `sessions/SESSION_HANDOFF.md` | 会话交接模板 |
| `reviews/_REVIEW_TEMPLATE.md` | 审查记录模板 |
| `presets/*.patch.yml` | Architect / Developer / Reviewer 三个 Agent Preset |
| `scripts/validate_tasks.py` | tasks.json 校验 |
| `scripts/taskctl.py` | 任务新建/流转/下发契约 |
| `scripts/check_commit.py` | 提交门禁（Task ID + 范围） |
| `scripts/install_git_hooks.sh` | 安装/卸载 git hooks |
| `scripts/install_presets.py` | 合并 preset 到 DSH profile |

## 5 分钟上手

1.（可选）安装提交门禁：`bash .dsh/scripts/install_git_hooks.sh`（写入**父仓库**
   `/home/regotto/Code/nautilus_trader/.git/hooks`；`nautilus_pa/` 无独立 git，所有提交随父仓库走）
2. 安装 presets 到 profile：`python .dsh/scripts/install_presets.py`，然后重启 `dsh web`。
   不改 profile 也可以临时试用：`dsh web --patch nautilus_pa/.dsh/presets/all.patch.yml`
   注意：profile 的 `cordis.patch.yml` 是 patch 文件，裸 `- id: preset-x` 只会"修改已有条目"
   并报 entry not found；新条目必须写在 `- insert:` 下面（脚本已处理）。
3. 新建任务：`python .dsh/scripts/taskctl.py new --title ... --requirement REQ-001 --priority P1`
4. 下发契约：`python .dsh/scripts/taskctl.py dispatch TASK-002 --role developer`
5. 每次改动前后：`python .dsh/scripts/validate_tasks.py`
