---
name: aftersales
domain: order
display_name: 售后服务
version: 1.0.0
description: >
  售后工单管理：查询订单、创建/更新售后工单（退款/换货/维修/投诉）。
  必须先查订单再创建工单，收集必要信息后确认执行。
tools:
  - order_query
  - order_manage
  - after_sales_manage
  - validate_input
triggers:
  - 退款 / 退货 / 换货
  - 售后工单 / 投诉 / 维修
  - 订单有问题 / 质量问题
constraints:
  - 创建工单前必须先调 order_query 确认订单状态
  - 收集必填字段后展示汇总确认
  - 禁止编造订单号或售后信息
---

# Aftersales Skill

售后服务技能，覆盖退款、换货、维修、投诉等售后场景。

## 执行原则

1. **先查后动**：创建工单前必须先用 order_query 确认订单存在且状态允许售后
2. **确认再执行**：展示工单摘要 → 用户确认 → after_sales_manage(action="create")
3. **数据只从系统来**：订单信息从 API 获取，不编造
