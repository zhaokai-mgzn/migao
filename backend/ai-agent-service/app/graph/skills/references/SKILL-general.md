---
name: general
domain: general
display_name: 通用兜底
version: 1.0.0
description: >
  通用兜底技能，处理无法路由到特定领域的用户意图。
  仅持有只读查询工具，引导用户明确意图或转接专业领域。
tools:
  - product_search
  - order_query
  - knowledge_search
triggers:
  - 你好 / 谢谢
  - 模糊意图（无法确定具体领域）
  - 闲聊 / 问候
constraints:
  - 仅持有只读工具，不执行写操作
  - 意图模糊时引导用户明确需求
  - 引导话术必须具体（"请说'创建商品'"而非"请切换模块"）
---

# General Skill

通用兜底技能，处理模糊意图和无需特定领域工具的对话。

## 执行原则

1. **引导明确**：用户意图模糊时给出具体引导示例
2. **不猜测执行**：不确定用户意图时反问确认
3. **只读工具**：不持有任何写操作工具
