# 子 Agent 输出契约（Agent Output Contract）

所有子 Agent 返回 500–1000 Token 的结构化报告，Main 据此决定状态流转。
**报告不替代证据**：结论后面必须能指到命令输出、Diff 或测试文件。

## 模板

    Task: TASK-002
    Status: DONE | PARTIAL | BLOCKED | FAILED | CLARIFICATION_REQUIRED
    Summary: 2–4 句，做到什么、没做到什么
    Changed Files:
      - src/pa_trend/presentation/api.py (修改，+12/-3)
    Implementation: 关键实现选择与理由（不复述代码）
    Interface Changes: 新增/变更/删除的公开接口；无则 None
    Tests:
      - 命令: PYTHONPATH=src python -m pytest -q tests/unit/test_api.py
      - 结果: 42 passed，用时 3.1s
    Git Diff: 父仓库路径 + 提交号（子工程无独立 git）；未提交时写"未提交"
    Risks: 已知风险与触发条件
    Unresolved Issues: 未解决项、越界发现的其他模块问题
    Evidence: 日志/截图/报告文件的路径
    Next: 建议的下一步（只建议，不执行）

## 规则

1. Status 为 DONE 时 Tests 必须有真实输出；未运行写"未执行"。
2. Changed Files 必须与 `git diff --name-only` 一致；有出入说明原因。
3. 越界发现的问题只写 `Unresolved Issues`，不修。
4. 接口变更必须在 `Interface Changes` 显式列出，供 Main 决定是否触发架构确认。
5. 报告 ≤1000 Token；细节放证据文件，路径写进 Evidence。
