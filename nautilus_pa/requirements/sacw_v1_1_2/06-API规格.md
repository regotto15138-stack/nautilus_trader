# 6. API 规格

API 前缀：`/api/v1`

统一响应：
```json
{
  "data": {},
  "meta": {"request_id": "uuid"},
  "error": null
}
```

错误响应必须包含稳定错误码、可读信息和字段路径。

## 6.1 市场数据 API

### 查询 K 线

`GET /market/bars`

参数：
- `instrument_id`
- `timeframe`
- `from`
- `to`
- `limit`
- `cursor`

返回按 `open_time` 升序的 Bar；明确 `is_closed`、`source` 和数据版本。

### 查询可用数据集

`GET /market/datasets`
`GET /market/datasets/{dataset_id}`

### 查询多周期数据覆盖

`GET /market/coverage?dataset_id=...`

返回每周期起止时间、Bar 数、缺失区间、重复 Bar、数据完整性状态。

## 6.2 标注 API

- `POST /annotation-projects`
- `GET /annotation-projects`
- `GET /annotation-projects/{project_id}`
- `POST /annotation-projects/{project_id}/annotations`
- `GET /annotation-projects/{project_id}/annotations`
- `GET /annotations/{annotation_id}`
- `PATCH /annotations/{annotation_id}`：必须传 `expected_revision`，采用乐观锁。
- `POST /annotations/{annotation_id}/submit`
- `POST /annotations/{annotation_id}/review`
- `POST /annotations/{annotation_id}/approve`
- `POST /annotations/{annotation_id}/freeze`
- `GET /annotations/{annotation_id}/revisions`

创建标注请求示例：
```json
{
  "entity_type": "SWING_POINT",
  "dataset_id": "dataset_uuid",
  "instrument_id": "ETH-USDT-SWAP.OKX",
  "timeframe": "15M",
  "payload": {
    "direction": "LOW",
    "price": "3100.0",
    "occurred_at": "2025-01-01T10:00:00Z",
    "confirmed_at": "2025-01-01T10:45:00Z",
    "source_bar_id": "bar_uuid"
  },
  "label_source": "HUMAN_PRIMARY",
  "spec_version": "V1.4.8"
}
```

服务端校验：
- 周期必须属于 V1.4.8 周期集合。
- 时间必须落在数据集覆盖范围。
- Swing 的价格和方向必须与来源 Bar 关系合理；若手动覆盖，必须记录覆盖原因。
- `confirmed_at >= occurred_at`。
- NStructure 引用的四个 Swing 必须存在、同周期、同方向规则正确且时间顺序合法。
- Zone 至少两个不同 SwingPoint 锚点。
- 15M ProtectedLow 不能作为独立策略保护点。
- `spec_version` 不等于 V1.4.8 时拒绝进入 V1.4.8 Ground Truth 项目。

## 6.3 黄金样本 API

- `POST /golden-datasets`：从 APPROVED 标注创建冻结版本。
- `GET /golden-datasets`
- `GET /golden-datasets/{id}`
- `POST /golden-datasets/{id}/validate`
- `POST /golden-datasets/{id}/split`

冻结时生成：
- `data_hash`
- `annotation_hash`
- `spec_version`
- `annotation_rule_version`
- `time_split_hash`
- `frozen_at`
- `baseline_replay_run_id`
- `baseline_code_commit`
- `baseline_config_hash`

冻结后不可修改；任何修改生成新版本。

## 6.4 程序回放 API

- `POST /replay-runs`
- `GET /replay-runs/{run_id}`
- `GET /replay-runs/{run_id}/events`
- `GET /replay-runs/{run_id}/snapshots`
- `POST /replay-runs/{run_id}/cancel`

请求：
```json
{
  "dataset_id": "dataset_uuid",
  "golden_dataset_id": "golden_uuid",
  "strategy_spec_version": "V1.4.8",
  "code_commit": "git_sha",
  "config_version_id": "config_uuid",
  "timeframes": ["3M", "15M", "1H", "4H", "1D", "1W", "1MONTH"],
  "initial_snapshot_id": "snapshot_uuid",
  "mode": "BATCH_DETERMINISTIC"
}
```

回放必须输出结构事件、状态事件、Setup/Signal 事件（如果对应模块启用）、事件来源 Bar、确认时间和参数快照。

## 6.5 差异比较 API

- `POST /comparisons`
- `GET /comparisons/{comparison_id}`
- `GET /comparisons/{comparison_id}/summary`
- `GET /comparisons/{comparison_id}/matches`
- `GET /comparisons/{comparison_id}/unmatched`
- `GET /comparisons/{comparison_id}/confusion-matrix`
- `GET /comparisons/{comparison_id}/export`

请求必须指定：
- golden dataset
- replay run
- matcher version
- 匹配容差配置
- 对象类型和周期过滤

## 6.6 参数实验 API

- `POST /calibration-experiments`
- `GET /calibration-experiments/{id}`
- `GET /calibration-experiments/{id}/trials`
- `POST /calibration-experiments/{id}/cancel`
- `POST /calibration-experiments/{id}/validate-out-of-sample`
- `GET /calibration-experiments/{id}/report`

创建实验时，后端必须拒绝 FIXED/REQUIRED/METADATA 字段进入搜索空间。

## 6.7 配置发布 API

- `POST /config-candidates`
- `GET /config-candidates/{id}`
- `POST /config-candidates/{id}/approve`
- `POST /config-candidates/{id}/reject`
- `POST /config-candidates/{id}/publish`
- `POST /config-versions/{id}/rollback`

发布 API 必须验证：
- 目标配置来自候选版本。
- 代码版本和 V1.4.8 规格版本兼容。
- 所有 REQUIRED 字段完整。
- 所有 FIXED 值未被覆盖。
- 样本内/验证/样本外门槛通过。
- 审批人和理由完整。
- 配置 Hash 已生成。

---

