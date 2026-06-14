---
name: settings
domain: settings
display_name: 系统配置
version: 1.0.0
description: >
  系统设置管理：AI 配置、站内通知、快捷回复模板。
  支持租户级配置的查看与修改。
tools:
  - settings_manage
  - notification_manage
  - quick_reply_manage
triggers:
  - 系统设置 / AI 配置
  - 通知模板 / 通知管理
  - 快捷回复 / 话术模板
  - 租户配置
constraints:
  - 修改配置前展示变更对比
  - AI 配置变更需告知影响范围（如影响 Agent 行为）
  - 禁止修改系统级只读配置
---

# Settings Skill

系统配置管理技能，覆盖 AI 配置、通知和快捷回复管理。

## 执行原则

1. **变更透明**：修改前后对比展示
2. **影响告知**：AI 配置变更说明可能影响 Agent 行为
3. **确认执行**：配置修改需用户确认
