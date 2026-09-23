-- V25: 售后工单号唯一约束改为「租户内唯一」(tenant_id, ticket_no)
--
-- 背景（POC 从 0 验证发现，P0-2）：after_sales_tickets.ticket_no 原为
-- 列级 UNIQUE（全局唯一），而 generateTicketNo() 经 MyBatis-Plus 多租户
-- 拦截器只查询【本租户】当天最大工单号：
--   - 老租户当天已占用 AS-yyyyMMdd-0001~000N
--   - 新租户从 AS-yyyyMMdd-0001 起号 → 撞全局唯一约束 → INSERT 500
--     「服务器内部错误」（老租户同请求 200，新租户必 500）
-- 修复：工单号在租户内唯一（多租户 SaaS 语义），生成逻辑无需改动。
--
-- 幂等：约束不存在/已存在均可重复执行；新约束名 uq_after_sales_tickets_tenant_no。

-- 1) 删除旧的全局唯一约束（列级 UNIQUE 的默认命名 after_sales_tickets_ticket_no_key；
--    兼容其它自定义命名）
DO $$
DECLARE
    con_name TEXT;
BEGIN
    FOR con_name IN
        SELECT c.conname
        FROM pg_constraint c
        JOIN pg_class t ON c.conrelid = t.oid
        WHERE t.relname = 'after_sales_tickets'
          AND c.contype = 'u'
          AND c.conname <> 'uq_after_sales_tickets_tenant_no'
    LOOP
        EXECUTE format('ALTER TABLE after_sales_tickets DROP CONSTRAINT %I', con_name);
    END LOOP;
END $$;

-- 2) 建立租户内唯一约束（幂等：已存在则跳过）
ALTER TABLE after_sales_tickets
    DROP CONSTRAINT IF EXISTS uq_after_sales_tickets_tenant_no;
ALTER TABLE after_sales_tickets
    ADD CONSTRAINT uq_after_sales_tickets_tenant_no UNIQUE (tenant_id, ticket_no);

-- 说明：若执行时存在跨租户同 ticket_no 的存量脏数据，本迁移会失败，
-- 需先人工去重（当前生产/开发库已验证无脏数据）。
