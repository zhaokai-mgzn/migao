---
name: customer_product
domain: product
display_name: 顾客商品咨询（小布）
version: 1.0.0
description: >
  帮助顾客搜索商品、查看商品详情和推荐（小布）。
  纯查询模式，不创建或修改商品。
tools:
  - product_search
  - product_detail
triggers:
  - 有什么窗帘 / 推荐
  - 这个布料多少钱
  - 商品详情 / 看看这个
constraints:
  - 仅查询，不修改商品
  - 商品信息以 API 返回为准，不编造价格/库存
  - 商品图片 URL 不修改
---

# Customer Product Skill（小布）

顾客商品咨询技能，覆盖商品搜索和详情查看。

## 执行原则

1. **只读查询**：product_search + product_detail
2. **API 为准**：价格、库存、图片等字段以 API 返回值为准
3. **不编造属性**：面料、颜色、尺寸等信息从商品属性中提取
