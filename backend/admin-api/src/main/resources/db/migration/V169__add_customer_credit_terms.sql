-- 客户授信额度 / 账期天数（issue #7370，P0-2 段 1）
--
-- ## 一句话
-- 中型客户是**赊销**为主：谁有额度、超了怎么拦、账期几天，是「管得住」的第一道门。
-- 本迁移只加**两列**，不改任何既有列语义（存量客户两列为 NULL ⇒ **未启用授信，零回归**）。
--
-- ## 口径（与 CreditPolicy / CreditService 同源，改这里必须同步那两处）
-- | 列 | NULL | 0 | 正数 |
-- |---|---|---|---|
-- | `credit_limit` | 未启用授信（一律放行） | 启用但零额度（拒一切赊销） | 额度上限（闭区间） |
-- | `payment_terms_days` | 未设置 | 现结 | 账期天数（0~365） |
--
-- ## 为什么 NULL 与 0 必须分开
-- 「没设授信」与「设了零额度」在业务上是**两件事**：前者是存量客户（不拦），
-- 后者是明确不许赊销（如现金客户）。合成一个值 ⇒ 要么放行了不该放行的，要么拦了不该拦的。
--
-- ## bootstrap 终态同步
-- 新建库路径不跑历史迁移链 ⇒ `backend/admin-api/src/main/resources/db/init/schema.sql`
-- 已同步本文件终态（`customer_profiles` 两列）。只改一处 ⇒ 新建库缺列。
--
-- ## 回滚（**新迁移，不删本文件**）
-- ```sql
-- ALTER TABLE customer_profiles DROP COLUMN IF EXISTS payment_terms_days;
-- ALTER TABLE customer_profiles DROP COLUMN IF EXISTS credit_limit;
-- ```
-- ⚠️ 回滚会**丢**已录入的授信与账期（有损，属**有意**）。
--
-- ## 显式事务
-- `MigrationRunner` 用 `jdbc.execute(整份文件)`；`psql -f` 默认逐条 autocommit ⇒ 不显式
-- `BEGIN/COMMIT` 时中途失败会留半完成态。两条执行路径必须同语义。
-- ══════════════════════════════════════════════════════════════════════════════════════

BEGIN;

ALTER TABLE customer_profiles ADD COLUMN IF NOT EXISTS credit_limit NUMERIC(12,2);
ALTER TABLE customer_profiles ADD COLUMN IF NOT EXISTS payment_terms_days INTEGER;

COMMENT ON COLUMN customer_profiles.credit_limit IS
    '授信额度（issue #7370）：NULL = 未启用授信；0 = 启用但零额度；正数 = 额度上限';
COMMENT ON COLUMN customer_profiles.payment_terms_days IS
    '账期天数（issue #7370）：NULL = 未设置；0 = 现结；正数 = 账期';

-- 终态对账（fail-closed）：两列必须存在，否则本迁移视为未生效
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'customer_profiles' AND column_name = 'credit_limit'
    ) OR NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'customer_profiles' AND column_name = 'payment_terms_days'
    ) THEN
        RAISE EXCEPTION 'customer_profiles 缺 credit_limit / payment_terms_days 终态列（issue #7370）';
    END IF;
END $$;

COMMIT;
