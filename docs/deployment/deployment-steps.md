# 阿里云完整部署步骤

> 版本：v8.0（补充 CRM 客户管理表结构）  
> 日期：2026-04-12  
> 目标：从零开始，在阿里云上完整部署 AI 智能客服系统并验证运行

---

## 数据库迁移文件说明

本项目包含两个数据库迁移文件，需按顺序执行：

| 文件 | 说明 | 表数量 |
|------|------|--------|
| `migrations/001_init.sql` | 初始表结构（17 张基础表） | 17 |
| `docs/sql/002_complete_tables.sql` | 补充缺失表（13 张新表 + 1 张扩展 + RLS 策略 + 默认数据） | 13 新表 + 12 字段扩展 |

### 执行顺序

```bash
# 1. 先执行初始迁移
psql -h "$RDS_HOST" -U app_user -d ai_customer_service \
     -f migrations/001_init.sql

# 2. 再执行补充迁移
psql -h "$RDS_HOST" -U app_user -d ai_customer_service \
     -f docs/sql/002_complete_tables.sql
```

### 002 迁移文件新增内容

**P0 核心表**：
- `session_messages` — AI 对话消息持久化
- `tenant_ai_configs` — AI 客服配置（欢迎语/营业时间/转人工规则）
- `categories` — 商品分类表
- `customer_profiles` — 客户档案表（CRM 核心：RFM 评分/客户等级/标签/统计）
- `processing_items` — 加工项（布艺行业：打孔/挂钩/折边）
- `processing_categories` — 加工分类
- `processing_rules` — 加工组合规则
- `tenant_apps` — 租户前端应用配置

**P1 扩展表**：
- `ticket_timeline` — 工单处理时间线
- `ticket_notes` — 工单内部备注
- `customer_tags` — 客户标签定义（自动/手动标签、打标规则）
- `customer_segments` — 客户分群规则（价值分层/行为分群/自定义）
- `customer_segment_members` — 分群成员关联
- `after_sales_tickets` — 扩展 12 个字段（ticket_no/priority/handler_id/refund_amount 等）
- `audit_logs` — 操作审计日志

**P2 辅助表**：
- `notification_templates` — 通知模板
- `notification_rules` — 通知规则
- `notifications` — 通知发送记录
- `order_logistics` — 物流跟踪（第三方物流查询结果存 JSONB）
- `knowledge_sync_history` — 知识库同步历史

所有新增表均包含 RLS 多租户隔离策略和必要索引。

---

## 完整数据库表清单（v8.1）

执行完两个迁移文件后，数据库将包含 **37 张表**：

| 类别 | 表名 | 来源 |
|------|------|------|
| 多租户基础 | tenants, tenant_apps, tenant_ai_configs | 001 + 002 |
| 用户认证 | users, user_identities | 001 |
| 商品管理 | products, product_skus, categories | 001 + 002 |
| 加工项 | processing_items, processing_categories, processing_rules | 002 |
| 订单管理 | orders, order_logistics | 001 + 002 |
| CRM 客户管理 | customer_profiles, customer_tags, customer_segments, customer_segment_members | 002 |
| 售后工单 | after_sales_tickets(扩展), ticket_timeline, ticket_notes | 001 + 002 |
| AI 会话 | sessions, session_messages | 001 + 002 |
| 客服工作台 | agent_employees, agent_sessions, agent_messages, quick_reply_templates | 001 |
| RAG 知识库 | knowledge_documents, rag_chunks, embedding_tasks, knowledge_sync_history | 001 + 002 |
| 通知系统 | notification_templates, notification_rules, notifications | 002 |
| 审计日志 | audit_logs | 002 |
| 工具日志 | tool_execution_logs | 001 |

详细审查报告见：[DB_SCHEMA_REVIEW.md](DB_SCHEMA_REVIEW.md)
