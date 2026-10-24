-- 供应商付款（issue #7369，P0-1 段 3-B）—— **一笔付款可冲抵多张入库单**（用户 2026-10-20 裁定「按实际的来」）
--
-- ## 一句话
-- 实际业务里给供应商打款，通常**一笔转账覆盖好几张入库单**（甚至先付后收货 = 预付）。
-- ⇒ 两张表：`supplier_payments`（一笔付款）+ `supplier_payment_allocations`（这笔钱冲到哪几张单、各多少）。
--
-- ## 口径（逐条写清）
-- ① **付款额 vs 冲抵额**：`Σallocations ≤ payment.amount`。差额 = **未冲抵（预付 / 待勾对）**——
--    这是真实存在的状态（先打款后到票），不是数据错误，所以允许且必须能显示出来。
-- ② **单张单不许超付**：某张入库单的冲抵合计 ≤ 该单金额（`posted` 单的 `total_amount`），
--    否则同一张单会被重复付掉 —— 这是不可逆的账实不符。
-- ③ **只能冲本供应商的单**：入库单 `supplier_id` 必须 = 付款的 `supplier_id`，且同为 `posted`、未软删。
-- ④ **作废 = 留痕**：`status = 'voided'` + 谁/何时/为什么；**不物理删**（付款凭证要能追溯）。
--    作废后该笔金额与它的冲抵**同时失效**（聚合按 `status = 'posted'` 过滤）。
-- ⑤ **付款单号** `FK-yyyyMMdd-NNNN` 租户内唯一（财务对账要凭号找单）。
--
-- ## 终态同步与回滚
-- - 建库脚本 `backend/admin-api/src/main/resources/db/init/schema.sql` 已同步两张表（新建库路径不跑迁移链）。
-- - 回滚（新迁移，不删本文件）：`DROP TABLE supplier_payment_allocations; DROP TABLE supplier_payments;`
--   **有损**：丢付款凭证。上线后不建议回滚，改为「作废付款单」。
--
-- ## 显式事务
-- 两条执行路径（MigrationRunner 整份 execute / psql -f 逐条 autocommit）必须同语义 ⇒ 显式 BEGIN/COMMIT。
-- ══════════════════════════════════════════════════════════════════════════════════════

BEGIN;

CREATE TABLE IF NOT EXISTS supplier_payments (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    -- 停用的供应商**仍然要能收款/付款**（欠款不会因为停用就消失）⇒ 这里不做状态约束
    supplier_id VARCHAR(64) NOT NULL REFERENCES suppliers(id),
    payment_no VARCHAR(32) NOT NULL,                 -- FK-yyyyMMdd-NNNN（租户内唯一）
    paid_at DATE NOT NULL,                           -- 付款日期（财务按日期对账，不按时刻）
    amount NUMERIC(16,4) NOT NULL CONSTRAINT ck_supplier_payments_amount CHECK (amount > 0),
    method VARCHAR(16) NOT NULL CONSTRAINT ck_supplier_payments_method
        CHECK (method IN ('cash', 'transfer', 'wechat', 'alipay', 'other')),
    reference_no VARCHAR(64),                        -- 回单号 / 流水号（对账时要能对上银行流水）
    remark TEXT,
    status VARCHAR(16) NOT NULL DEFAULT 'posted' CONSTRAINT ck_supplier_payments_status
        CHECK (status IN ('posted', 'voided')),
    voided_at TIMESTAMP WITH TIME ZONE,
    voided_by VARCHAR(64),
    voided_reason TEXT,
    created_by VARCHAR(64),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    deleted BOOLEAN NOT NULL DEFAULT FALSE
);

COMMENT ON TABLE supplier_payments IS '供应商付款（issue #7369 段 3-B）：一笔付款 + 若干冲抵；作废留痕不物理删';
COMMENT ON COLUMN supplier_payments.amount IS '付款金额（> 0）；与冲抵合计的差额 = 未冲抵（预付 / 待勾对）';

CREATE UNIQUE INDEX IF NOT EXISTS uk_supplier_payments_no
    ON supplier_payments (tenant_id, payment_no)
    WHERE deleted = FALSE;
CREATE INDEX IF NOT EXISTS idx_supplier_payments_tenant_supplier
    ON supplier_payments (tenant_id, supplier_id, paid_at DESC)
    WHERE deleted = FALSE;

ALTER TABLE supplier_payments ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
         WHERE tablename = 'supplier_payments' AND policyname = 'tenant_isolation_supplier_payments'
    ) THEN
        CREATE POLICY tenant_isolation_supplier_payments ON supplier_payments
            USING (tenant_id::text = current_setting('app.current_tenant_id'));
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS supplier_payment_allocations (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    payment_id VARCHAR(64) NOT NULL REFERENCES supplier_payments(id),
    inbound_order_id VARCHAR(64) NOT NULL REFERENCES inbound_orders(id),
    amount NUMERIC(16,4) NOT NULL CONSTRAINT ck_supplier_payment_allocations_amount CHECK (amount > 0),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    deleted BOOLEAN NOT NULL DEFAULT FALSE
);

COMMENT ON TABLE supplier_payment_allocations IS
    '付款冲抵明细（issue #7369 段 3-B）：这一笔钱冲到哪张入库单、各多少；单张单合计不许超该单金额';

-- 同一笔付款对同一张单只允许一行（要改金额就删了重记，不留两份口径）
CREATE UNIQUE INDEX IF NOT EXISTS uk_supplier_payment_allocations_pair
    ON supplier_payment_allocations (payment_id, inbound_order_id)
    WHERE deleted = FALSE;
CREATE INDEX IF NOT EXISTS idx_supplier_payment_allocations_order
    ON supplier_payment_allocations (tenant_id, inbound_order_id)
    WHERE deleted = FALSE;

ALTER TABLE supplier_payment_allocations ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
         WHERE tablename = 'supplier_payment_allocations'
           AND policyname = 'tenant_isolation_supplier_payment_allocations'
    ) THEN
        CREATE POLICY tenant_isolation_supplier_payment_allocations ON supplier_payment_allocations
            USING (tenant_id::text = current_setting('app.current_tenant_id'));
    END IF;
END $$;

-- 终态对账（fail-closed）
DO $$
DECLARE
    has_payments BOOLEAN;
    has_allocations BOOLEAN;
    payments_rls BOOLEAN;
    allocations_rls BOOLEAN;
BEGIN
    SELECT EXISTS (SELECT 1 FROM information_schema.tables
                    WHERE table_name = 'supplier_payments') INTO has_payments;
    SELECT EXISTS (SELECT 1 FROM information_schema.tables
                    WHERE table_name = 'supplier_payment_allocations') INTO has_allocations;
    IF NOT has_payments OR NOT has_allocations THEN
        RAISE EXCEPTION 'supplier_payments / supplier_payment_allocations 缺表（issue #7369 段 3-B 迁移未生效）';
    END IF;

    SELECT relrowsecurity FROM pg_class WHERE relname = 'supplier_payments' INTO payments_rls;
    SELECT relrowsecurity FROM pg_class WHERE relname = 'supplier_payment_allocations' INTO allocations_rls;
    IF payments_rls IS NOT TRUE OR allocations_rls IS NOT TRUE THEN
        RAISE EXCEPTION '供应商付款两表必须开启 RLS（跨租户读付款凭证 = 数据泄漏）';
    END IF;
END $$;

COMMIT;
