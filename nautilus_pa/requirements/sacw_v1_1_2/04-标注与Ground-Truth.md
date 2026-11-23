# 4. 人工标注规范与 Ground Truth

## 4.1 标注单位

标注单位分为：

- 点事件：SwingPoint、Fill、SignalCreated、StopTriggered。
- 结构对象：NStructure、Zone、ProtectedPoint。
- 状态区间：TrendState、SetupState。
- 过程对象：PullbackSequence、SignalLifecycle、PositionLifecycle。

每个对象必须绑定：
- instrument_id
- timeframe
- dataset_id
- strategy_spec_version（固定 V1.4.8）
- annotation_rule_version
- label_source
- created_by
- created_at
- revision
- status

## 4.2 标签来源枚举

`label_source`：
- `HUMAN_PRIMARY`
- `HUMAN_REVIEWED`
- `PROGRAM_PREDICTION`
- `IMPORTED`
- `AI_SUGGESTED`

只有 `HUMAN_PRIMARY` 和 `HUMAN_REVIEWED` 可进入正式 Ground Truth。AI 建议标签必须由人工确认后才能升级。

## 4.3 标注状态

- DRAFT：草稿。
- SUBMITTED：已提交审核。
- REVIEWED：已审核。
- APPROVED：已批准。
- FROZEN：已冻结，不能原地修改。
- SUPERSEDED：被新版本替代。
- REJECTED：审核拒绝。

P0-E 的黄金样本只能由 APPROVED/FROZEN 标注构成。

## 4.4 V1.4.8 标注对象

### SwingPoint

```json
{
  "annotation_id": "ann_x",
  "entity_type": "SWING_POINT",
  "instrument_id": "ETH-USDT-SWAP.OKX",
  "timeframe": "15M",
  "direction": "LOW",
  "price": "3100.0",
  "occurred_at": "2025-01-01T10:00:00Z",
  "confirmed_at": "2025-01-01T10:45:00Z",
  "source_bar_id": "bar_x",
  "label_source": "HUMAN_PRIMARY",
  "spec_version": "V1.4.8"
}
```

价格、数量和费率在持久化与比较计算中优先使用 Decimal/定点数，不应依赖二进制浮点数作为价格真值。

### NStructure

```json
{
  "annotation_id": "ann_n",
  "entity_type": "N_STRUCTURE",
  "instrument_id": "ETH-USDT-SWAP.OKX",
  "timeframe": "15M",
  "direction": "BULLISH",
  "l1_swing_id": "ann_l1",
  "h1_swing_id": "ann_h1",
  "l2_swing_id": "ann_l2",
  "h2_swing_id": "ann_h2",
  "valid_from": "2025-01-01T12:00:00Z",
  "confirmed_at": "2025-01-01T12:15:00Z",
  "invalidated_at": null,
  "validation_status": "VALID"
}
```

### Zone

```json
{
  "annotation_id": "ann_zone",
  "entity_type": "ZONE",
  "timeframe": "4H",
  "zone_type": "SUPPORT",
  "anchor_swing_ids": ["swing_a", "swing_b"],
  "center": "3000.0",
  "lower": "2980.0",
  "upper": "3020.0",
  "state": "ACTIVE",
  "state_events": [
    {"state": "CREATED", "at": "2025-01-01T00:00:00Z"},
    {"state": "ACTIVE", "at": "2025-01-02T00:00:00Z"}
  ],
  "zone_revision": 1
}
```

人工 Zone 边界属于人工参考真值；程序 Zone 边界单独保存，不可混写。

### StateInterval

```json
{
  "annotation_id": "ann_state",
  "entity_type": "STATE_INTERVAL",
  "timeframe": "1H",
  "state": "PULLBACK",
  "valid_from": "2025-01-01T08:00:00Z",
  "valid_to": "2025-01-01T16:00:00Z",
  "known_at": "2025-01-01T09:00:00Z",
  "reason_code": "PULLBACK_RULES_SATISFIED"
}
```

## 4.5 事后标注与实时可知性

人工在完整历史图表上标出 SwingLow 时，可能知道它后来成为低点，但实时系统在 `confirmed_at` 之前不知道它是 SwingLow。

因此必须同时保存：
- 事后结构发生时间 `occurred_at`
- 结构确认时间 `confirmed_at`
- 标注者做出判断的时间 `annotated_at`

回放评估必须以 `confirmed_at` 作为程序最早可识别时间。任何程序输出早于人工允许确认时间的情况，应作为时间因果性错误单独报告。

## 4.6 标注指南与仲裁

每类标签提供：
- 定义。
- 正例。
- 反例。
- 边界案例。
- 必填字段。
- 禁止操作。
- 对应 V1.4.8 章节。

模糊样本可以标记 `AMBIGUOUS`，不强制标成正例或负例。AMBIGUOUS 不计入主准确率，但必须单独统计数量和原因。存在多人标注时，使用双人独立标注 + 仲裁流程；不得让第二位标注者直接看到第一位标注者的标签后再“独立”标注。

---

