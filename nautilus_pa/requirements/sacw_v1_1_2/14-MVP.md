# 14. 建议首个可交付版本（MVP）

首个版本不追求一次完成全部策略生命周期，先交付可验证的结构标注闭环。

MVP 范围：

1. ETH-USDT-SWAP.OKX 的历史 OHLCV 数据读取。
2. 15M、4H、1H 三个周期先行，架构上保留七周期。
3. TradingView Lightweight Charts K 线、成交量、缩放和时间同步。
4. 人工 SwingHigh / SwingLow 标注。
5. 人工 NStructure 四点标注。
6. 人工 Zone 锚点与状态标注。
7. 程序 Swing/NStructure/Zone 叠加。
8. 人工与程序差异报告。
9. 标注版本、数据集冻结、回放快照。
10. PB-01 至 PB-51 回归样本页面、样本导入和自动回归接口，含负向断言。

MVP 暂不启用自动参数发布；先验证人工标注一致性、程序差异可解释性和回放确定性。

---

