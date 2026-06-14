---
name: data
domain: analytics
display_name: 数据分析
version: 1.0.0
description: >
  经营看板、统计指标与客服会话管理。
  支持仪表盘数据查询、会话记录查看、数据报表生成。
tools:
  - dashboard_stats
  - session_manage
triggers:
  - 经营数据 / 看板 / 仪表盘
  - 销售额 / 订单量 / 转化率
  - 会话记录 / 客服数据
  - 报表 / 统计
constraints:
  - 统计数据以 API 返回为准
  - 禁止编造经营指标数值
  - 超出统计范围的问题建议联系管理员
---

# Data Skill

数据分析技能，覆盖经营看板和会话管理。

## 执行原则

1. **API 为准**：经营数据全部来自 dashboard_stats API
2. **不编造数字**：销售额、订单量等指标不编造不估算
3. **会话管理**：session_manage 用于查看和分析客服会话
