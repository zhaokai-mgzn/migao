# 数据库

## 概览

PostgreSQL 15，39 张业务表，按域分组：

| 域 | 表 | 说明 |
|----|----|------|
| **租户/认证** | tenants, tenant_apps, tenant_ai_configs, users, user_identities, platform_admins | 多租户 + 多渠道认证 |
| **RBAC** | roles, permissions, user_roles | 5角色权限体系 |
| **商品** | products, product_skus, product_colors, product_attributes, product_processing_items | SKU矩阵 |
| **分类/加工** | categories, processing_categories, processing_items | 分类树 + 加工项 |
| **订单** | orders, order_items, order_logistics | 订单全生命周期 |
| **售后** | after_sales_tickets, ticket_notes, ticket_timeline | 售后工单 |
| **客户** | customers, customer_tags, customer_segments, customer_segment_members | CRM(RFM) |
| **对话** | chat_sessions, chat_messages, sessions, session_messages | C端对话 |
| **人工坐席** | agent_employees, agent_sessions, agent_messages, quick_reply_templates | 客服工作台 |
| **知识库** | knowledge_documents, knowledge_chunks, knowledge_sync_history | RAG |
| **通知** | notifications, notification_templates, notification_rules | 消息推送 |
| **系统** | system_configs, login_logs, audit_logs, user_memories, user_suggestion_prefs | 配置/审计/AI偏好 |

## 多租户隔离 (5层)

1. JWT 提取 tenant_id (不可伪造)
2. Spring Security RBAC 校验
3. MyBatis 拦截器自动注入 tenant_id → SQL WHERE
4. PostgreSQL RLS 行级安全 (每张业务表启用)
5. 字段脱敏 (日志/响应)

## 关键设计决策

| 决策 | 方案 | 原因 |
|------|------|------|
| 订单商品 | JSON 列 (order.items) | 订单快照，不需复杂查询 |
| SKU规格 | JSON 列 (sku_matrix) | 灵活规格组合 (颜色×尺寸) |
| 物流 | 独立表 (order_logistics) | 需按运单号查询 |
| 用户身份 | 1 user : N user_identities | 微信小程序+H5+账号统一用户，unionid 跨端识别 |
| 软删除 | `deleted` 字段 (0/1) | MyBatis-Plus @TableLogic |

## 数据库迁移 (MigrationRunner)

Flyway 已移除（与 PG 18 不兼容），替换为自定义 `MigrationRunner`：

- 启动时扫描 `db/migration/V*__xxx.sql`
- 对比 `schema_migrations` 表，跳过已执行迁移
- SQL 必须幂等 (IF NOT EXISTS / ADD COLUMN IF NOT EXISTS)
- 迁移失败不阻塞启动（可能已在 DB 执行过）

当前迁移: V1 ~ V9 + V20260604 ~ V20260614

---
详见: [schema.sql](../sql/schema.sql) · [多租户架构](../architecture/multi-tenant-multi-platform.md)
