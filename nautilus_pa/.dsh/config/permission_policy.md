# 权限策略（Permission Policy）

目标：让"谁能改哪些文件"成为**可执行**的约束，而不是提示词里的君子协定。

## 1. 路径类别

| 类别 | 路径（相对 `nautilus_pa/`） | 说明 |
| --- | --- | --- |
| SRC | `src/pa_trend/**` | 生产代码 |
| TESTS | `tests/**` | 单元/集成测试 |
| WEB | `web/**` | 前端工作台 |
| CONFIG | `configs/**` | 冻结配置、回归样本 |
| SCRIPT | `scripts/**` | 采集、校验、服务脚本 |
| DOC | `README.md`、`USAGE.md`、`planning/**`、`docs/**`、`requirements/**`、`requirements/**`、`development/**` | 文档 |
| STATE | `.dsh/**` | 任务、契约、会话、审查、preset、脚本 |
| UPSTREAM | 仓库根 `nautilus_pa/` 之外的任何路径 | 上游 NautilusTrader 代码与配置 |

## 2. 角色 × 路径矩阵

| 角色 | SRC | TESTS | WEB | CONFIG | SCRIPT | DOC | STATE | UPSTREAM |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Main | RW | RW | RW | RW | RW | RW | RW | R（不主动改） |
| Architect | R | R | R | R | R | R | R | R |
| Developer | RW* | RW* | RW* | R* | R* | R | R | R |
| Reviewer | R | R | R | R | R | R | R | R |

`*`：仅限当前 TASK 的 `allowed_paths` 命中的子集。其余一律只读。
Main 对 UPSTREAM 的写操作需用户明确要求（上游仓库有自己的 AGENTS.md 约束）。

## 3. 五层落实（缺一层就只是建议）

1. **Preset 工具面**：architect / reviewer 的 `dsh-tool-fs` 关闭 `write`、`edit`、`applyPatch`，
   模型根本没有写工具。developer 才挂载写工具。
2. **会话沙箱**：在 Web UI 把会话 sandbox 设为 `workspace-write`（默认）并把 cwd 设在
   `nautilus_pa/`，写操作被内核层限制在工作区内；Reviewer 会话再切到 `read-only`，
   连 bash 也无法落盘。approval=never 时无法临时提权。
3. **任务契约**：`tasks.json` 的 `allowed_paths` / `forbidden_paths` 是唯一事实来源，
   下发契约时原样传给子 Agent。
4. **Git hook**：`.dsh/scripts/check_commit.py` 校验提交信息里的 TASK-ID、任务状态、
   `nautilus_pa/` 前缀的改动文件是否在 `allowed_paths` 内；不在则拒绝提交。
   父仓库其他路径不属于本子工程，直接放行。
5. **人工审查**：Main 审 Diff 后合并。自动化只挡明显越界，语义正确性仍由人/主 Agent 负责。

安装 hook：`bash .dsh/scripts/install_git_hooks.sh`（写入父仓库
`/home/regotto/Code/nautilus_trader/.git/hooks`；`nautilus_pa/` 没有自己的 `.git`）。
hook 是可选门禁，装与不装都不改变"提交由用户触发"。

## 4. 并发

变更级别、授权记录、执行前提与范围门禁以
[架构保护契约](../../docs/architecture/ARCHITECTURE_CONTRACT.md) 为准。
`allowed_paths` 仅声明边界，workspace-write 不自动提供逐 TASK 的文件写入隔离。
提交门禁可检查删除/重命名和越界，但不能替代受保护分支的受信任 CI 或语义兼容性审查。
执行期需由宿主把白名单落实为实际文件系统权限并保护审批记录；本次未配置该能力。

- 同一文件同一时刻只允许一个写 Agent。
- 并行任务：只按**文件集互斥**并行——两个任务的 `allowed_paths` 有交集就必须串行依赖。
  本项目共用父仓库，不为任务新建分支或 `git worktree`，`tasks.json` 也不登记 `branch`。
- 集成前：`git -C .. diff --check`、`git -C .. diff --stat`、相关测试通过、Reviewer 结论 PASS。
- 改动落盘即在同一工作区可见；并行任务结束顺序不影响结果，但不得互相覆盖文件。

## 5. 禁止操作（任何角色）

- `git reset --hard`、`git checkout -- .`、`git clean -fd` 等会丢弃他人改动的命令。
- 覆盖或删除用户未提交的修改。
- 修改 `RELEASES.md`、`.github/workflows`、`.github/actions`（上游维护者专属）。
- 手工编辑生成产物；必须改生成器。
- 未经用户明确要求执行 `git commit` / `push` / 任何远程状态变更。
