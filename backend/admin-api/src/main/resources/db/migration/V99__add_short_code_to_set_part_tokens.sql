-- 工人端**稳定短链**的人可读短码（issue #4802；设计 `docs/design/worker-h5-scan-and-report.md` §1.3 / §1.4 / §7.1①）
--
-- ## 一句话
-- `processing_set_part_tokens` 追加一列 `short_code`（8 位 Crockford Base32）+ 部分唯一索引
-- ⇒ 印刷品上的码 `https://<稳定域名>/s/<short_code>` 由**服务端** 302 换回 `token`（落到报工页 `/w/?t=<token>`）。
--
-- ## 为什么是「同一行两种表示」而不是第二套编号
-- `token`（32 位 UUID 去横线）= **机器标识**（#4687 冻结形态，本迁移**一字不动**）；
-- `short_code` = **人可读入口**（印得下、抄得准）。两者是**同一行**的两种表示
-- ⇒ 不新造编号体系（#4687 §13 禁的是「套号的第二套编号」，与标识符的两种表示不是一回事）。
--
-- ## 迁移号（**现取**）
-- `ls backend/admin-api/src/main/resources/db/migration | tail` ⇒ 落码时最大 = `V98` ⇒ 本单取 `V99`。
--
-- ## 幂等（`MigrationRunner` 硬要求所有迁移可重复执行）
-- `ADD COLUMN IF NOT EXISTS` + `CREATE UNIQUE INDEX IF NOT EXISTS` + 覆盖式 `COMMENT ON` ⇒ 重复执行净效果相同。
--
-- ## 存量行（**如实登记，不粉饰**）
-- 本迁移**不回填**：`short_code` 可空，本次之前已写入的 token 行保持 NULL。理由：
--   ① 消费码的**打印流程尚未落码**（`processing_set_part_tokens` 的写入方 = 实例化路径，
--      见 `backend/admin-api/src/main/java/com/migao/admin/service/ProductionService.java` 的 `ensurePartTokens`）
--      ⇒ 存量行没有任何**已打印**的 URL 依赖它；
--   ② 回填要在 SQL 里造随机码并处理碰撞（「不静默造重码」），那是「在事故点再加一道门」；
--   ③ 读面按 `short_code IS NOT NULL` 匹配 ⇒ NULL 行只是「没有短链」，**不会**造出错误跳转。
--   ⚠️ 跟随单（打印流程落码时）：**要印的行必须有 `short_code`**（否则印出来的码打不开）。
--
-- ## 🔴 红线（本文件**一字不动**的历史值）
--   · `processing_set_part_tokens.token` —— 本文件**零写入**（只加一列，不改类型/不改语义）；
--   · `processing_orders.qr_token` —— 本文件**零命中**（旧码继续有效，不设强制失效日）；
--   · `production_work_logs` —— 本文件**零命中**（冻结契约 + 红线）。
-- 机械核验：`grep -c "qr_token\|production_work_logs\|UPDATE" V99__*.sql` ⇒ 只应命中注释里的红线说明。
--
-- ## 回滚（**新迁移，不删本文件**；同 V88 / V89 / V92 的处置）
-- ```sql
-- -- V100__rollback_short_code.sql（本单只登记，不落码 —— 落码即被 MigrationRunner 当场执行）
-- -- DROP INDEX IF EXISTS uk_set_part_tokens_short_code;
-- -- ALTER TABLE processing_set_part_tokens DROP COLUMN IF EXISTS short_code;
-- ```
-- 回滚会丢什么：已打印的 `/s/<短码>` 全部失效（**不可恢复** —— 短码是随机的，无法重算）。
--
-- ## bootstrap 终态同步（设计 §7.1⑧）
-- `docs/sql/schema.sql` 已同步本文件终态（列 + 唯一索引 + 注释）—— 新建库路径**不跑迁移链**
-- （docker `docker-entrypoint-initdb.d/001_schema.sql`），只写迁移 = 新建库无该列（#3270 同族）。

ALTER TABLE processing_set_part_tokens
    ADD COLUMN IF NOT EXISTS short_code CHAR(8);

-- 唯一性判据 = 「活跃行内全局唯一」：短码是**印刷品上的公开入口**，跨租户也必须唯一
-- （`/s/<短码>` 那一跳**没有**租户上下文 —— 租户由短码本身解出，设计 C12）。
CREATE UNIQUE INDEX IF NOT EXISTS uk_set_part_tokens_short_code
    ON processing_set_part_tokens (short_code)
    WHERE deleted = 0;

COMMENT ON COLUMN processing_set_part_tokens.short_code IS
    '人可读短码（8 位 Crockford Base32 = 0-9 + A-Z 去掉 I/L/O/U；**随机**、非顺序号 —— 顺序号可枚举）。与 token 同一行的两种表示：印刷品写 https://<稳定域名>/s/<short_code>，服务端 302 换回 token。NULL = 尚未分配（本次之前的存量行）';
