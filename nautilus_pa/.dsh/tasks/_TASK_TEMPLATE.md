# TASK-NNN 标题

## 1. 基本信息

| 字段 | 值 |
| --- | --- |
| 任务 ID | TASK-NNN |
| 需求来源 | REQ-NNN（`requirements/REQUIREMENTS.md`） |
| 优先级 | P0 / P1 / P2 / P3 |
| 状态 | DRAFT |
| 负责人 | 未分配 |
| 创建日期 | YYYY-MM-DD |
| 依赖 | TASK-NNN / 无 |
| 复杂度 | S / M / L / XL |

## 2. 任务目标

一句话说明可验证的结果。

## 3. 需求依据

引用规格章节或执行计划批次，例如：V1.4.8 第 6.9 节、执行计划 B00。

## 4. 输入

- 已知事实：
- 需要的上下文文件：
- 未知项/待确认：

## 5. 输出

- 代码/文档产物：
- 报告：

## 6. 修改范围

允许：
    src/pa_trend/...
    tests/...

禁止：
    configs/...
    README.md

## 7. 技术约束

### 强制变更控制（机器字段写入 tasks.json）

```yaml
spec_id: SPEC-...
change_level: L1
change_policy:
  default: minimal_patch
  refactoring_allowed: false
  public_api_change_allowed: false
  database_schema_change_allowed: false
  frontend_change_allowed: false
on_scope_violation: BLOCK_AND_REPORT
impact_analysis:
  rules: [具体条款]
  modules: [具体模块]
  interfaces: [保持不变的接口或允许变化清单]
  tests: [具体回归与兼容性检查]
  code_change_required: true
  architecture_compatible: true
  decision: minimal_patch
  sources: {} # 审阅输入的相对文件路径到SHA-256；必须补齐
approval: {} # 真实人工授权的level/approved_by/evidence；L2/L3另需separate_approval
dependency_policy: {} # 默认前置须ACCEPTED；write_order例外须有明确释放证据
```

DRAFT 中空分析/审批不得执行；完整流程见
[架构保护契约](../../docs/architecture/ARCHITECTURE_CONTRACT.md)。

- 不得引入新依赖（除非任务明确要求）。
- 保持公开接口兼容 / 明确接口变更清单。
- 遵循上游仓库 `AGENTS.md` 与 `docs/developer_guide/coding_standards.md`。

## 8. 验收标准

- [ ] 功能：
- [ ] 边界：
- [ ] 异常：
- [ ] 单测：
- [ ] 接口兼容：
- [ ] 无未解释回归：

## 9. 测试计划

    PYTHONPATH=src python -m pytest -q tests/unit/test_xxx.py

## 10. 风险

| 风险 | 触发条件 | 应对 |
| --- | --- | --- |
|  |  |  |

## 11. 执行结果

- 修改文件：
- 实现摘要：
- 测试结果：
- 审查结论：
- 遗留问题：

## 12. 验收

- 最终状态：
- 证据（命令/路径）：
- 验收人：
