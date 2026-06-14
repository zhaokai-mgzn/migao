---
name: order
domain: order
display_name: 订单管理
version: 1.0.0
description: >
  订单全生命周期管理：查询、创建、修改、物流追踪、发货。
  支持关联商品查询和详情查看，写操作前需校验。
tools:
  - order_query
  - order_manage
  - order_create
  - logistics_track
  - product_search
  - product_detail
  - validate_input
triggers:
  - 订单列表 / 订单详情 / 查订单
  - 创建订单 / 新订单
  - 发货 / 物流 / 快递
  - 修改订单 / 取消订单
constraints:
  - 写操作前必须调 validate_input 校验
  - 创建/修改订单展示汇总确认后再执行
  - 禁止编造订单号、金额等字段
---

# Order Skill

订单管理技能，覆盖订单全生命周期操作。

## 执行原则

1. **先查后改**：修改/取消前先用 order_query 确认当前状态
2. **校验先行**：写操作前调 validate_input
3. **确认再执行**：form → choice → confirm → execute
4. **数据只从系统来**：不编造订单字段值
