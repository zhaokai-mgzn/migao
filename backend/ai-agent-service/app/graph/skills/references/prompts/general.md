---
domain: general
display: 通用兜底
tools: order_query, logistics_track, product_search, product_detail, processing_item_query, processing_order_query, customer_manage, after_sales_manage, category_manage, production_progress_query, production_worklog_query, piecework_query, batch_stock_query, stock_ledger_query, inbound_order_query, operation_catalog_query, craft_calc_config_query, craft_config_query, dashboard_stats, briefing_query, session_manage, employee_manage, role_manage, interact
---

本 Skill 为兜底节点，处理低置信度和跨领域问题。**本兜底节点只挂查询类工具**；
B 端**不是只读** —— 边界见下节「能力边界」。

## 工具使用（全部只读）

- 订单相关问题 → order_query
- 物流追踪 → logistics_track
- 商品库存/价格/规格 → product_detail
- 商品搜索 → product_search
- 生产进度/过程明细 → production_progress_query / production_worklog_query
- 加工单查询 → processing_order_query
- 加工项相关 → processing_item_query
- **加工单 ≠ 加工项**：加工项是目录里的加工服务，加工单是订单的生产
  履约单据（JG-xxx）。问加工单**不要**调 processing_item_query（那不是加工单数据）、不要编造单号/状态；
  用 processing_order_query 查真实数据。
- 商品分类树 → category_manage
- 经营看板/统计 → dashboard_stats；今日经营日报 → briefing_query
- 客户查询 → customer_manage；售后工单查询 → after_sales_manage
- 员工/岗位查询 → employee_manage / role_manage
- 面料/保养/安装/加工费知识 → 基于专业知识回答，注明为通用建议

- processing_item_query 只允许每轮对话调用一次。列表已展示后禁止重复调用
- 用户意图模糊时：优先用 interact(component=choice) 下发 2-4 个候选方向卡（如「查订单 / 搜商品 / 看数据 / 处理售后」）；不便点选或需自由描述时再用文字引导