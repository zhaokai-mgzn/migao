# 数据库

## 概览

PostgreSQL 15，39 张业务表，按域分组：

| 域 | 表 | 说明 |
|----|----|------|
| **租户/认证** | tenants, tenant_apps, tenant_ai_configs, users, user_identities, platform_admins | 多租户 + 多渠道认证 |
| **RBAC** | roles, permissions, user_roles | 5角色权限体系 |
| **商品** | products, product_skus, product_colors, product_attributes | SKU矩阵 |
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

## 数据库 (MigrationRunner)

Flyway 已移除（与 PG 18 不兼容），替换为自定义 `MigrationRunner`。

### 形状：**唯一的一份建库脚本 + 一条归档链 + 未来的增量迁移**（issue #5243）

改前本仓有四代 SQL 资产（`schema_full.sql` / `docs/sql/migrations/V2026*` / `docs/sql/00*.sql` / 迁移链），
互相漂移且哪一份都不是权威。现在**只有一份**建库脚本：

| 载体 | 路径 | 性质 |
|---|---|---|
| **建库脚本（唯一）** | `backend/admin-api/src/main/resources/db/init/schema.sql` | 表 + 索引 + RLS + 终态种子。位置有两条硬理由：在 **admin-api 的 classpath** 内（`MigrationRunner` 读得到），且在 **Docker 构建上下文**内（`backend/admin-api/Dockerfile` 只 `COPY src` ⇒ 模块外的文件镜像构建时**根本不可见**） |
| 归档链 | `backend/admin-api/src/main/resources/db/migration-archive/` | 历史迁移链，**只读**：逐字节冻结（`migration_fingerprints.json`），**不得修改** |
| 活目录 | `backend/admin-api/src/main/resources/db/migration/` | **只放未来的增量迁移**（每个文件必须幂等）；文件一发布即冻结 |

清单以**目录**为单一源（**别在本页抄文件数/版本号 —— 会腐烂**）：

```bash
ls backend/admin-api/src/main/resources/db/init backend/admin-api/src/main/resources/db/migration{,-archive}
# 下一个空闲版本号（别抄数字）：归档链 ∪ 活目录里的最大 V 号 + 1
ls backend/admin-api/src/main/resources/db/migration{,-archive} \
  | sed -n 's/^V\([0-9]*\)__.*/\1/p' | sort -n | tail -1
```

> ⚠️ **历史证据不动**：`docs/design/**` 等设计文档与 `.github/cases/**` 用例文本里引用的
> `backend/admin-api/src/main/resources/db/migration/V*.sql` 是 **#5243 之前的旧位置** ——
> 那整条链现已归档到 `db/migration-archive/`（内容逐字节未变）。
> 那些是历史证据，**有意不批量改写**（批量重写会把证据链改花）。

### 基线语义（`MigrationRunner.applyBaseline`，issue #5243）

启动时**先处理建库脚本（基线）**，再扫描活目录的增量迁移：

- 配置键 `migao.migration.init-script`（默认 `classpath:db/init/schema.sql`）。
  **台账键 = 该资源的文件名**（`schema.sql`）—— 与迁移同一种记账粒度（都按文件名记）。
- 台账**已有**该键 ⇒ 整段跳过（幂等；增量迁移照常扫描）。
- 台账**没有**该键 ∧ 库**非空**（哨兵表 `tenants` 存在）⇒ **只记账、不执行**
  —— 存量库**绝不重放**建库脚本（重放会往活库灌终态种子，比少建一张表严重得多）。
- 台账**没有**该键 ∧ 库**为空** ⇒ 执行建库脚本后记账。执行形态与迁移**逐一相同**：
  整份文件文本一次 `jdbc.execute(...)`（PG 扩展查询下多语句走单一隐式事务，任一句失败即整份回滚）。
- **失败分级与迁移逐字相同**：**连接类** ⇒ 有限退避重试、耗尽即 fail-closed（拒绝启动，
  不让 `/actuator/health` 谎报 UP）；**内容类** ⇒ 记入失败清单 + ERROR、**不阻塞启动**
  （#3615 / #3270 的刻意权衡，逐字未改）。

### 幂等与失败语义（原有口径，一字未改）

- 所有 SQL 必须幂等 (IF NOT EXISTS / ADD COLUMN IF NOT EXISTS)；
- 内容类失败**只跳过该条**、继续执行其余迁移（一条坏迁移不得冻结整个 schema）；
- 已知存量非幂等迁移的降级名单 `KNOWN_BENIGN_LEGACY`（`MigrationRunner` 内）**保留**：
  其中的文件名如今全在**归档链**里、活目录为空 ⇒ 该名单**当前不会被命中**。
  留着的理由（不静默删诊断）：它是**单一事实源**，由 L0 测试
  （`tests/unit_ci_workflows/test_migration_idempotency.py` 的 `TestKnownBenignLegacyRegistry`）
  与 Java 侧键集合逐条锁死；将来若把迁移放回活目录，语义逐字不变。

### 🔴 迁移不可变（已发布迁移只增不改，issue #4235）

`MigrationRunner` 的台账按**文件名**记（`applied.contains(filename)` ⇒ `continue`），
**已应用的迁移整份跳过**。⇒ 往已发布的迁移（如 `V54__seed_production_operations.sql`）里加行，
**存量环境永远拿不到**，而静态守卫反而会因此转绿 —— 本仓库最忌讳的「CI 全绿、功能静默缺失」。

**机械护栏**（此前零护栏，改 V54 不会让任何东西变红）：

| 判据 | 落点 |
|---|---|
| **冻结面**（唯一建库脚本 + 归档链 + 新增迁移）的内容**逐字节冻结** | `tests/unit_ci_workflows/test_migration_immutability.py` |
| 账本 = `{文件名: 内容 sha256}` | `tests/unit_ci_workflows/migration_fingerprints.json` |

账本是**仓内文件**（不依赖 git 历史 / `origin/main` / DB）—— 判据跑在 CI job
`ci workflow helper unit tests`，该 job 是 `fetch-depth: 1`（**没有历史**），
"比对 `origin/main` 的 blob hash" 这类写法在那里只能 skip（= 没跑）。

**给种子库/任何已发布迁移追加内容 = 新迁移 + 登记指纹**（唯一合法路径）：

```bash
# 1) 新建 V<下一个空闲号>__xxx.sql（不动任何已登记文件；空闲号怎么算见上）
# 2) 登记新文件的指纹（**只新增条目**；已登记文件被改 ⇒ 非零退出，不是"刷新一下就好"）
python3 tests/unit_ci_workflows/test_migration_immutability.py --write-ledger
# 3) 新迁移 + 账本一起提交
```

⚠️ 确需变更一条**已发布**迁移（如版本号让号改名）时，必须**手工**改账本条目并在 PR 说明 ——
手改会出现在 diff 里、可被评审看见（重生成命令**拒绝**覆盖已登记指纹）；
`.github/danger_scan.py` 另有一条**人工确认通道**（仓库 owner 评论
`/danger-ack rewrite-migration`）与之交叉校验。

### 种子源按集合聚合（守卫不再写死文件名）

`production_operations` / `production_routings` 的种子事实有**多个载体**
（`app/production/routing.py` 真值源 + 归档链 `db/migration-archive/V*__*.sql` 增量迁移
+ `backend/admin-api/src/main/resources/db/init/schema.sql` bootstrap 终态）。
守卫 `tests/unit_ci_workflows/test_production_catalog_seed.py` 的种子源
**按内容发现**（凡含 `INSERT INTO <table>` 的迁移即被纳入，归档 ∪ 活目录），
⇒ 新增种子迁移**无需改守卫**即进入逐行逐值比对射程（issue #4235 判据 1）。

### 判据面为什么必须**两个目录一起扫**（`_migration_paths.py`）

`tests/unit_ci_workflows/_migration_paths.py` 是「历史链在哪、活目录在哪」的**单一事实源**：
只看归档 ⇒ 新迁移不在射程（门禁对**将来**失效）；只看活目录 ⇒ 今天扫不到任何文件
（判据**空转** = 假绿）。下一次搬目录只改这一个文件；`.github/danger_scan.py` 与
`scripts/drift_audit.py` 同样按两个目录取扫描面（判据强度一字未改）。

---
详见: [schema.sql](../../backend/admin-api/src/main/resources/db/init/schema.sql) · [架构](Architecture.md)
