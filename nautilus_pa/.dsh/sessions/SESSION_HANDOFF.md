# SESSION_HANDOFF

> 更新日期：2026-11-23。TASK-013 收口 Session token 消耗核算：写清固定前缀成本、缓存未命中口径，
> 新增开发复盘制度（AGENTS.md 第 12 节）与交接前置条件（第 8 节），并按该结构重写本文件。
> 后续交接按 `nautilus_pa/AGENTS.md` 第 8 节核对 Git 和实际文件，不盲信本文件。

> 每个 Session 结束前更新。新 Session 必须核对 Git 与实际文件，不盲信本文件。

## 1. Session 信息

| 字段 | 值 |
| --- | --- |
| Session ID | 2026-11-23 TASK-013 token 消耗核算 |
| 日期 | 2026-11-23 |
| 主 Agent | lead（DSH，deepseek-flash → 中途用过 gpt-6-luna / gpt-6-sol） |
| 被分析的会话 | `session-c996353b-c0c2-4728-8827-afc3a35e9746`（10:58–12:26，4 轮，250 次请求） |

## 2. 本 Session 目标

回答"为什么这个会话消耗这么多 token、是否合理"，并把结论落成可执行的规范，而不是只给解释。

## 3. 已完成

- **账本核算**（数据来自会话日志 `~/.dsh/sessions/--home-regotto-Code-nautilus_trader--/session-c996353b-c0c2-*/session.v4.jsonl.zstd`）：
  - 250 次请求：input 1,526,819、cache_read 44,918,016、output 58,665、reasoning 9,510。
  - **8 次缓存未命中共付 1,265,672 input**，占输入侧 83%：turn1 开头 2 次（27.6K + 28.1K 全价，属正常首付）、
    切到 gpt-6-sol 时 2 次（103K + 105K）、中途额度报错后继续 2 次（224K + 228K）、`/compact` 2 次（274K + 274K）。
  - 模型分布：gpt-6-luna 174 次（479K input，26.5M cache_read）、gpt-6-sol 76 次（1,047K input，18.4M cache_read）。
  - 系统提示每请求 108,120–108,185 字节，其中 `run_code` SDK 89.4K（83%）：71 个工具的 `ToolArgsMap` 57.8K + `ToolOutputMap` 29.3K。
  - 工具结果 1.13MB：read 907KB/193 次（75% 是同一文件的带 offset 重读，`tasks.json` 被读 15 次）、grep 162KB/33 次。
  - 输出侧仅 58.7K（tool 参数 JSON 113KB 字符），**不是成本大头**。
  - 结论：消耗**不合理但可解释**——不是单次读得太多，而是请求数 × 固定前缀 + 8 次缓存未命中，加上 `/compact` 太晚。
- **规范落地**：
  - `.dsh/config/token_budget.md`：新增第 5 节（计量口径：可见上下文 vs 请求级用量）、第 6 节（固定前缀分解与核算方法）、
    第 7 节（已验证有效的 6 条降耗措施）、第 8 节（汇报要求）。
  - `AGENTS.md`：第 8 节新增交接前置条件（5 条）；新增第 12 节"开发复盘"，规定触发条件、五问内容与写法约束。
  - 本文件按上述结构重写，第 13 节按新口径记录。
- **已验证配置**：`~/.dsh/profiles/web/cordis.patch.yml` 已在 `token-cost tuning` 段加入
  `tool-executor-ptc: disabled` 与 `preset-ptc` 的裁剪阈值（4096/2048/512）；该文件改动**需重启 `dsh web` 才生效**，
  本 Session 未重启。

## 4. 未完成

- **重启 `dsh web` 使 PTC 关闭与裁剪阈值生效**，并开新会话核对系统提示是否从 108K 降到约 25K（阻塞点：重启会中断当前会话，需用户执行）。
- `preset-ptc` 的 patch 只覆盖 `tool-result-pruner`，`selectedDefault: ptc` 仍在；下次进 PTC 预设时应再确认 `request/header.tools` 只有 1 个入口。
- 尚未评估把常驻的 agent-teams/agency 段按需装卸（需各自插件提供开关，未验证可行性）。

## 5. 当前状态

`nautilus_pa/` 的规范文件已更新，`tasks.json` 新增 TASK-013（IN_PROGRESS）。父仓库其他改动（行情 parquet、
backtest html、`okx.pcap`）与本任务无关，保持原状。

## 6. 代码变更

- 仓库：父仓库 `/home/regotto/Code/nautilus_trader`（子工程无独立 git，见 D-007）
- 分支：（新 Session 自行 `git -C .. branch --show-current` 核对）
- 提交：无（未获用户授权；按 AGENTS.md 第 3 节，等待用户明确要求后以 `TASK-013 ...` 提交）
- 未提交改动（仅本任务范围）：
  - `nautilus_pa/AGENTS.md`
  - `nautilus_pa/.dsh/config/token_budget.md`
  - `nautilus_pa/.dsh/sessions/SESSION_HANDOFF.md`
  - `nautilus_pa/.dsh/tasks/tasks.json`（新增 TASK-013）
- 工作区外改动：`~/.dsh/profiles/web/cordis.patch.yml`（不属于父仓库 Git，需重启生效）

## 7. 测试结果

| 命令 | 结果 | 时间 |
| --- | --- | --- |
| `python3 .dsh/scripts/validate_tasks.py`（nautilus_pa 下） | ok: 13 task(s) | 2026-11-23 13:05 |

未运行代码测试：本任务只改文档/配置，未触碰 `src/`、`tests/`。

## 8. 关键决策与复盘

**复盘（按 AGENTS.md 第 12 节五问，本 Session 首次应用）：**

1. 现象：被分析的会话 250 次请求付了 1.53M input，其中 8 次未命中占 1.27M；系统提示 108K，PTC SDK 占 89K。
2. 根因：固定前缀由"默认 PTC 预设"决定（`selectedDefault: ptc`），而 4 次模型/推理强度切换与 1 次过晚的
   `/compact` 把整段上下文反复按全价重发。直接原因不是"某个工具输出太大"，而是"请求数 × 前缀 × 未命中"。
3. 性质：规范缺口——项目此前只有阈值（60/80/95%）与分层加载，没有"单次请求固定成本"与"切模型立即收尾"的规则；
   已写进 `token_budget.md` 第 5–7 节与 `AGENTS.md` 第 12 节。
4. 下次动作：长任务开始前先确认当前执行器（PTC/ native）与模型；确需切换模型时，切换后立即压缩并写交接，不继续长跑。
5. 生效位置：`token_budget.md`、`AGENTS.md` 第 8/12 节、本文件本节。

**其它决策：**

- `tasks.json` 是唯一任务状态源；md 只写规则与视图（D-001）。
- 子工程无独立 git，随父仓库提交，只负责任务发布；不建分支/worktree（D-007）。
- 交接前置条件与复盘制度写入 `AGENTS.md` 而非单独文档：两者都是强制规则，分散会失效。
- `token_budget.md` 第 5 节明确"预算口径 ≠ 计费口径"，避免再拿可见上下文去解释 API 账单。

## 9. 风险与阻塞

- `cordis.patch.yml` 的 PTC 关闭属于 profile 层配置，重启失败会直接打不开 Web；改动前已备份 `cordis.patch.yml.bak.*`。
- 关闭 PTC 后部分依赖 `run_code` 的自动化习惯（一次批量调多工具）需要改用并行 tool call；如果实测发现并发工具调用
  表现变差，应恢复 PTC 并改从"减少请求数"入手。
- 裁剪阈值只在压缩触发时生效，单次请求输入 >200K 仍需人工介入（见 `token_budget.md` 第 8 节）。
- 本 Session 自身也在消耗 token：分析 1.68MB 会话日志应尽量用脚本聚合，不要整段读入。

## 10. 下个 Session 计划

1. 重启 `dsh web`，开新会话确认系统提示从约 108K 降到约 25K（native 执行器），并把新账本的 `request/header` 记入本文件第 13 节。
2. 复核 `preset-ptc` 是否仍需保留；若确认只用 native，把 `agent-preset-registry.selectedDefault` 改为 `standard`。
3. 另立任务同步 `requirements/templates/ai-project-bootstrap/`：把 `AGENTS.md` 第 12 节复盘制度按项目裁剪后加入模板。

## 11. 上下文入口

- 必读：`AGENTS.md`（第 5、8、12 节）、`PROJECT_CONTEXT.md`、`.dsh/tasks/tasks.json`
- 本次核算口径：`.dsh/config/token_budget.md` 第 5–8 节
- 账本命令：日志是 zstd，无 CLI 时用 `node -e "require('zlib').zstdDecompressSync(...)"` 解到临时文件后再按事件类型聚合。

## 12. Git 状态

    （新 Session 自己跑：git -C .. status --short && git -C .. log -3 --oneline）

    本 Session 结束时未提交改动（nautilus_pa/ 下 7 个文件）：
    AGENTS.md、.dsh/config/token_budget.md、.dsh/sessions/SESSION_HANDOFF.md、
    .dsh/tasks/tasks.json、requirements/templates/ai-project-bootstrap/{AGENTS.template.md,
    SESSION_HANDOFF.template.md, BOOTSTRAP_CHECKLIST.md}

## 13. Token 使用

按 `token_budget.md` 第 8 节口径填写（请求级用量，不是可见上下文）：

| 会话 | 模型 | 请求数 | input | cache_read | output | 未命中 | 备注 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| c996353b（被分析） | gpt-6-luna 174 / gpt-6-sol 76 | 250 | 1,526,819 | 44,918,016 | 58,665 | 8 | 1.27M 全价输入来自 8 次未命中；PTC 前缀 108K |
| 本 Session（479a3f2b） | gpt-6-luna → gpt-5.6-luna → deepseek-flash | 209 | 299,743 | 11,392,384 | 50,527 | 4 | 命中率约 97%；系统提示 15.7K 字符（native 执行器），约为旧会话的 1/7；大结果来自 1 次 22.9KB grep 与 147 次 bash 小输出 |

## 14. 交接结论

可以继续。文档与配置改动完整、`validate_tasks.py` 通过；**Git 未提交**（等用户授权），
**`dsh web` 未重启**（PTC 关闭与裁剪阈值尚未生效）。下个 Session 先做第 10 节第 1 步。
