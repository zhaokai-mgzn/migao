-- 具名审批流（issue #7374，P1-2 段 1）—— 改价 / 超授信 / 退款 / 采购超额 / 盘点差异
--
-- ## 一句话
-- 现在只有权限码（能做 / 不能做），**没有审批**：谁能批、批了什么、批之前是多少，全在微信里。
-- 本表让「必须先审批」成为**服务端事实**：未审批的超阈动作在**写面**直接被拒，不是前端藏按钮。
--
-- ## 五个具名类型（`object_type`，不造 BPM 引擎）
-- `credit_override`（超授信下单）/ `price_change`（改价）/ `refund`（退款）/
-- `purchase_over`（采购单超额）/ `stocktake_diff`（盘点差异）。
-- 类型是**封闭集合**（CHECK 约束）：新增一类必须改迁移 + 改判据，不允许字符串随便长。
--
-- ## 四态与「不出现双真值」
-- `pending → approved | rejected | withdrawn`；只有 `pending` 可以流转。
-- 🔴 **业务对象不存审批结论副本**：订单/退款单需要审批时**读**本表（`object_ref` 定位），
-- 一旦对象自己也存一个「已批准」布尔，两边就会漂移（审批撤回了、对象还写着已批准）。
--
-- ## 单次消费（`consumed_at`）
-- 「超授信审批」批的是**这一笔**，不是「这个客户以后随便超」⇒ 批过一次用一次：
-- 下单闸门命中后用 `consumed_at` + `consumed_ref` 标记已用（并发下靠 CAS 更新，只有一个请求能吃下）。
--
-- ## 为什么 `amount` 单独一列（不只塞 payload）
-- 钱是审批的**主要论据**（超多少、退多少、超采购预算多少），要能直接比对与索引；
-- 塞进 JSONB 就只能全表扫 + 每处自己解析。
--
-- ## 终态同步与回滚
-- - 建库脚本 `db/init/schema.sql` 已同步本表（新建库不跑迁移链）。
-- - 回滚：`DROP TABLE approvals;` **无数据损失**（审批是过程数据；对象的金额/状态本来就不依赖它落库）。
--
-- ## 显式事务
-- 两条执行路径（MigrationRunner 整份 execute / psql -f 逐条 autocommit）必须同语义 ⇒ 显式 BEGIN/COMMIT。
-- ══════════════════════════════════════════════════════════════════════════════════════

BEGIN;

CREATE TABLE IF NOT EXISTS approvals (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),

    object_type VARCHAR(32) NOT NULL,
    object_ref VARCHAR(128) NOT NULL,            -- 定位业务对象的键（客户手机号 / 订单号 / 采购单 id）
    object_label VARCHAR(255),                   -- 人读标签（客户名 / 单号），上屏用
    amount NUMERIC(16,4),                        -- 钱（超多少 / 退多少 / 超预算多少）；非钱类审批可空
    payload JSONB,                               -- 类型专属细节（改价：旧价/新价；盘点：差异行）
    reason VARCHAR(500),                         -- 申请理由（谁申请谁负责）

    status VARCHAR(16) NOT NULL DEFAULT 'pending',
    requested_by VARCHAR(64),
    requested_by_name VARCHAR(64),
    requested_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    decided_by VARCHAR(64),
    decided_by_name VARCHAR(64),
    decided_at TIMESTAMP WITH TIME ZONE,
    decision_note VARCHAR(500),

    -- 单次消费（超授信 / 退款这类「批这一笔」的审批用）
    consumed_at TIMESTAMP WITH TIME ZONE,
    consumed_ref VARCHAR(128),                   -- 用在哪（订单 id / 流水 id）

    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    deleted INT NOT NULL DEFAULT 0,

    CONSTRAINT ck_approvals_object_type CHECK (object_type IN (
        'credit_override', 'price_change', 'refund', 'purchase_over', 'stocktake_diff')),
    CONSTRAINT ck_approvals_status CHECK (status IN ('pending', 'approved', 'rejected', 'withdrawn')),
    -- 结论必须带人（「谁批的」是审批的全部意义）
    CONSTRAINT ck_approvals_decided_shape CHECK (
        (status = 'pending' AND decided_at IS NULL)
        OR (status <> 'pending' AND decided_at IS NOT NULL))
);

-- 同一对象同一类型**同时只能有一个待审**（否则两个审批人各批一次，谁生效说不清）
CREATE UNIQUE INDEX IF NOT EXISTS uk_approvals_pending
    ON approvals (tenant_id, object_type, object_ref)
    WHERE status = 'pending' AND deleted = 0;

-- 闸门查询：按对象找「已批准且未被用掉」的那条（超授信/退款走它）
CREATE INDEX IF NOT EXISTS idx_approvals_gate
    ON approvals (tenant_id, object_type, object_ref, status)
    WHERE deleted = 0;

COMMENT ON COLUMN approvals.object_type IS
    '封闭集合（CHECK）：credit_override 超授信下单 / price_change 改价 / refund 退款 / purchase_over 采购超额 / stocktake_diff 盘点差异';
COMMENT ON COLUMN approvals.consumed_at IS
    '单次消费时刻：非空 = 这条审批已经用掉了（超授信一笔一批，不许复用）';

-- 终态对账（fail-closed）
DO $$
DECLARE
    has_table BOOLEAN;
BEGIN
    SELECT EXISTS (SELECT 1 FROM information_schema.tables
                    WHERE table_name = 'approvals' AND table_schema = 'public') INTO has_table;
    IF NOT has_table THEN
        RAISE EXCEPTION 'approvals 缺表（issue #7374 段 1 迁移未生效）';
    END IF;
END $$;

COMMIT;
