---
name: customer_order
domain: order
display_name: 顾客订单查询（小布）
version: 1.1.0
description: >
  帮助顾客查询订单状态、物流追踪与下单（小布）。
  下单时优先用 customer_address_query 查历史收货信息预填表单，减少输入（issue #2815）。
tools:
  - customer_order_query
  - customer_logistics_track
  - customer_address_query
triggers:
  - 我的订单 / 订单到哪了
  - 物流查询 / 快递
  - 什么时候发货
  - 下单 / 买 / 订
constraints:
  - 仅查询，不修改订单
  - 物流信息以 API 返回为准，不猜测
  - 退款/售后需求引导转接米宝
  - 下单金额以商品数据/算料结果为准，不向顾客索要单价
---

# Customer Order Skill（小布）

顾客订单查询技能，覆盖订单状态、物流追踪与下单（含收货信息自动填充）。

## 执行原则

1. **只读不写**：仅 customer_order_query + customer_logistics_track + customer_address_query
2. **如实展示**：物流轨迹按 API 返回的 traces 数组逐条展示
3. **物流铁律**：只查顾客本人已发货(在途)订单；拒绝顾客提供的快递单号直查
4. **价格铁律**：下单金额一律取自商品数据/算料结果，严禁向顾客索要单价
5. **引导转接**：涉及退款/取消等操作引导转米宝
6. **地址自动填充**（issue #2815）：下单前先调 customer_address_query 查最近订单收货信息；
   命中则 interact(component=form) 预填 value 让顾客确认/修改，未命中再询问
