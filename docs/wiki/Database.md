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
| **人工坐席** | agent_employees, agent_sessions, agent_messages | 客服工作台 |
| **知识库** | knowledge_cards, knowledge_candidates | LLM WIKI 知识卡片模型 + AI 提炼待确认队列（RAG 已下线并移除，决策 D1 + issue #3051） |
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

迁移文件清单以目录为单一源（**别在本页抄文件数/版本号 —— 会腐烂**）：
`ls backend/admin-api/src/main/resources/db/migration/`

### 🔴 迁移不可变（已发布迁移只增不改，issue #4235）

`MigrationRunner` 的台账按**文件名**记（`applied.contains(filename)` ⇒ `continue`），
**已应用的迁移整份跳过**。⇒ 往已发布的迁移（如 `V54__seed_production_operations.sql`）里加行，
**存量环境永远拿不到**，而静态守卫反而会因此转绿 —— 本仓库最忌讳的「CI 全绿、功能静默缺失」。

**机械护栏**（此前零护栏，改 V54 不会让任何东西变红）：

| 判据 | 落点 |
|---|---|
| 已发布迁移的内容**逐字节冻结** | `tests/unit_ci_workflows/test_migration_immutability.py` |
| 账本 = `{文件名: 内容 sha256}` | `tests/unit_ci_workflows/migration_fingerprints.json` |

账本是**仓内文件**（不依赖 git 历史 / `origin/main` / DB）—— 判据跑在 CI job
`ci workflow helper unit tests`，该 job 是 `fetch-depth: 1`（**没有历史**），
"比对 `origin/main` 的 blob hash" 这类写法在那里只能 skip（= 没跑）。

**给种子库/任何已发布迁移追加内容 = 新迁移 + 登记指纹**（唯一合法路径）：

```bash
# 1) 新建 V<下一个空闲号>__xxx.sql（不动任何已登记文件）
# 2) 登记新文件的指纹（**只新增条目**；已登记文件被改 ⇒ 非零退出，不是"刷新一下就好"）
python3 tests/unit_ci_workflows/test_migration_immutability.py --write-ledger
# 3) 新迁移 + 账本一起提交
```

⚠️ 确需变更一条**已发布**迁移（如版本号让号改名）时，必须**手工**改账本条目并在 PR 说明 ——
手改会出现在 diff 里、可被评审看见（重生成命令**拒绝**覆盖已登记指纹）。

### 种子源按集合聚合（守卫不再写死文件名）

`production_operations` / `production_routings` 的种子事实有**多个载体**
（`app/production/routing.py` 真值源 + `db/migration/V*__*.sql` 增量迁移 + `docs/sql/schema.sql`
bootstrap 终态）。守卫 `tests/unit_ci_workflows/test_production_catalog_seed.py` 的种子源
**按内容发现**（凡含 `INSERT INTO <table>` 的迁移即被纳入），
⇒ 新增种子迁移**无需改守卫**即进入逐行逐值比对射程（issue #4235 判据 1）。

---
详见: [schema.sql](../sql/schema.sql) · [架构](Architecture.md)
