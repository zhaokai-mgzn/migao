---
name: product
domain: product
display_name: 商品管理
version: 1.1.0
description: >
  商品全生命周期管理：搜索、详情查询、创建、上下架、库存调整。
  支持加工项关联、分类管理、图片识别辅助创建。
tools:
  - product_search
  - product_detail
  - product_manage
  - inventory_manage
  - processing_item_query
  - category_manage
  - processing_item_manage
  - validate_input
  - interact
triggers:
  - 创建商品 / 上架 / 上下架
  - 商品搜索 / 查商品 / 有没有货
  - 库存查询 / 库存调整
  - 加工项管理 / 分类管理
  - 图片上传（商品识别 + 创建）
constraints:
  - 写操作前必须调 validate_input 校验
  - 创建流程必须走 form→choice→confirm→execute 四步
  - confirmValue 必须包含上下文（如 "确认创建商品"）
  - 禁止编造商品名称、价格等任何字段值
  - 每个回复最多弹一个交互组件
---

# Product Skill

商品管理技能，覆盖搜索、详情、创建、库存、加工项、分类等全部商品域操作。

## 执行原则

1. **写操作必须校验**：调用 product_manage 前先用 validate_input 检查参数
2. **创建必须确认**：form → choice → confirm → execute，不可跳步
3. **数据只从用户来**：绝不编造字段值，图片识别结果全部预填到 form
4. **一次一个交互**：每个回复最多一个 interact 组件

## 参考

- 完整示例见 `references/EXAMPLES-product.md`
