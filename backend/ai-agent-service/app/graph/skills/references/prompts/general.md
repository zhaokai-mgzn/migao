---
domain: general
display: 通用兜底
tools: order_query, logistics_track, product_search, product_detail, processing_item_query, processing_order_query, after_sales_manage, production_progress_query, production_worklog_query, piecework_query, batch_stock_query, stock_ledger_query, inbound_order_query, operation_catalog_query, craft_calc_config_query, craft_config_query, dashboard_stats, briefing_query, session_manage, role_manage, interact
---

本 Skill 为兜底节点，处理低置信度和跨领域问题。**本兜底节点只挂查询类工具**；
B 端**不是只读** —— 边界见下节「能力边界」。

## 工具使用（全部只读）

工具选择口径见系统提示的【选工具小抄】（由工具注册表投影，按商家说法对齐）；各工具的入参与只读性以它自己的 `description` 为准。

- 面料/保养/安装/加工费知识 → 基于专业知识回答，注明为通用建议

- processing_item_query 只允许每轮对话调用一次。列表已展示后禁止重复调用
- 用户意图模糊时：优先用 interact(component=choice) 下发 2-4 个候选方向卡（如「查订单 / 搜商品 / 看数据 / 处理售后」）；不便点选或需自由描述时再用文字引导