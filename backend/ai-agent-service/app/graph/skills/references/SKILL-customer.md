---
name: customer
domain: crm
display_name: 客户管理
version: 1.0.0
description: >
  客户档案查询与维护、标签管理、跟进记录。
  支持客户搜索、详情查看、标签编辑，以及关联订单/商品查询。
tools:
  - customer_manage
  - order_query
  - product_search
  - validate_input
triggers:
  - 查客户 / 客户列表 / 客户详情
  - 客户标签 / 跟进记录
  - 这个客户买了什么
constraints:
  - 写操作前调 validate_input 校验
  - 客户手机号等敏感信息脱敏展示
  - 禁止编造客户数据
---

# Customer Skill

客户管理技能，覆盖客户档案查询、标签维护、消费记录关联查询。

## 执行原则

1. **关联查询**：查客户时可附带查其订单和购买商品
2. **脱敏展示**：手机号中间 4 位显示为 ****
3. **数据只从系统来**：不编造客户信息
