---
name: knowledge
domain: knowledge
display_name: 知识库管理
version: 1.0.0
description: >
  知识库条目的增删改查与管理。
  支持 FAQ 搜索、知识条目创建/编辑/删除、分类管理。
tools:
  - knowledge_search
  - knowledge_manage
triggers:
  - 知识库 / FAQ / 问答
  - 添加知识 / 编辑知识条目
  - 搜索知识 / 查找答案
constraints:
  - 写操作前必须收集完整信息并展示确认
  - 禁止编造知识条目内容
  - 知识条目删除需二次确认
---

# Knowledge Skill

知识库管理技能，覆盖 FAQ 搜索和条目管理。

## 执行原则

1. **RAG 引用**：搜索回答时注明知识来源
2. **确认再写**：创建/编辑/删除前展示变更摘要并获确认
3. **内容来自用户**：知识条目内容由用户提供，不编造
