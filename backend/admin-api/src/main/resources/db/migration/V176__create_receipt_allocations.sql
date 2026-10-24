-- 客户收款核销（issue #7370，P0-2 段 3）—— **一笔收款可冲抵多张订单**
--
-- ## 一句话
-- 客户打来一笔钱，常常一次付掉好几张单（或先付后货）。段 2 的账龄只能按「订单有没有
-- `paid_at`」判已收/未收，遇到部分收款就按不下去 ⇒ 本表把「这笔钱冲了哪几张单、各多少」记下来，
-- 应收余额改为 `货值 − 退款 − Σ核销`。
--
-- ## 为什么**不**新建一张「客户收款表」
-- 客户收款的现金真值源早就是 `finance_transactions`（type=income、status=success，金额/方式/日期都在那里），
-- 再建一张收款表 = 两处现金口径（同一笔钱两种合计，必然漂移）。所以这里**只加核销明细**，
-- 现金仍只认 `finance_transactions`。
--
-- ## 口径（逐条写清）
-- ① **核销合计 ≤ 收款金额**：`Σallocations ≤ transaction.amount`。差额 = **未核销**（预收 / 待勾对）——
--    先付后货是真实状态，不是脏数据，所以允许并必须能显示。
-- ② **单张订单不许超收**：某单的核销合计 ≤ 该单余额（`total_amount − Σ退款`），否则同一张单被重复收钱。
-- ③ **只核销收入类流水**：`type = 'income'` 且 `status = 'success'`；退款与失败流水不许核销。
-- ④ **同客户**：流水的订单与核销的订单必须是同一客户（按 `orders.customer_phone`）——
--    把钱冲到别人单上是对账灾难，宁可拒绝。
-- ⑤ **删除 = 软删**（`deleted`）：核销记错要能撤回，但撤回动作本身留时间戳
--    （谁/何时由 `created_by`/`deleted` 旁的应用日志承担；本表不重复存审计真值）。
--
-- ## 终态同步与回滚
-- - 建库脚本 `db/init/schema.sql` 已同步（新建库不跑迁移链）。
-- - 回滚（新迁移，不删本文件）：`DROP TABLE receipt_allocations;` **有损**：丢核销明细
--   （应收会回到「按 paid_at 判」的段 2 口径，钱没丢，但对账口径变粗），上线后不建议回滚。
--
-- ## 显式事务
-- 两条执行路径（MigrationRunner 整份 execute / psql -f 逐条 autocommit）必须同语义 ⇒ 显式 BEGIN/COMMIT。
-- ══════════════════════════════════════════════════════════════════════════════════════

BEGIN;

CREATE TABLE IF NOT EXISTS receipt_allocations (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    -- 现金真值源：只做引用，不复制金额（复制 = 第二份会漂移的真相）
    transaction_id VARCHAR(36) NOT NULL REFERENCES finance_transactions(id),
    order_id VARCHAR(36) NOT NULL REFERENCES orders(id),
    amount NUMERIC(16,4) NOT NULL CONSTRAINT ck_receipt_allocations_amount CHECK (amount > 0),
    created_by VARCHAR(64),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    deleted BOOLEAN NOT NULL DEFAULT FALSE
);

COMMENT ON TABLE receipt_allocations IS
    '客户收款核销（issue #7370 段 3）：一笔收入流水冲抵到哪张订单、各多少；现金真值仍只认 finance_transactions';
COMMENT ON COLUMN receipt_allocations.amount IS '本行核销金额（> 0）；同一流水的核销合计 ≤ 该流水金额';

-- 同一笔收款对同一张单只允许一行（要改金额就删了重记，不留两份口径）
CREATE UNIQUE INDEX IF NOT EXISTS uk_receipt_allocations_pair
    ON receipt_allocations (transaction_id, order_id)
    WHERE deleted = FALSE;
CREATE INDEX IF NOT EXISTS idx_receipt_allocations_order
    ON receipt_allocations (tenant_id, order_id)
    WHERE deleted = FALSE;
CREATE INDEX IF NOT EXISTS idx_receipt_allocations_transaction
    ON receipt_allocations (tenant_id, transaction_id)
    WHERE deleted = FALSE;

ALTER TABLE receipt_allocations ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
         WHERE tablename = 'receipt_allocations'
           AND policyname = 'tenant_isolation_receipt_allocations'
    ) THEN
        CREATE POLICY tenant_isolation_receipt_allocations ON receipt_allocations
            USING (tenant_id::text = current_setting('app.current_tenant_id'));
    END IF;
END $$;

-- 终态对账（fail-closed）
DO $$
DECLARE
    has_table BOOLEAN;
    rls_on BOOLEAN;
BEGIN
    SELECT EXISTS (SELECT 1 FROM information_schema.tables
                    WHERE table_name = 'receipt_allocations') INTO has_table;
    IF NOT has_table THEN
        RAISE EXCEPTION 'receipt_allocations 缺表（issue #7370 段 3 迁移未生效）';
    END IF;

    SELECT relrowsecurity FROM pg_class WHERE relname = 'receipt_allocations' INTO rls_on;
    IF rls_on IS NOT TRUE THEN
        RAISE EXCEPTION 'receipt_allocations 必须开启 RLS（跨租户读客户收款核销 = 数据泄漏）';
    END IF;
END $$;

COMMIT;
