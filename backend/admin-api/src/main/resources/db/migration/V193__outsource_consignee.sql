-- 外发承接方：供应商档案加类型 + 作业单记承接方引用（issue #7723）
--
-- ## 一句话
-- 「发加工」不再是作业单上的必经动作（用户 2026-10-25 裁定 A）⇒ 外发（给其他加工厂做单）
-- 的信息改在**智能派单**录入。加工厂主数据**复用供应商档案**（不新建第二套主数据），
-- 作业单只记「名称快照 + 档案引用」，界面不在作业单上展示/录入。
--
-- ## 两列的分工（与 InboundOrder 的 supplier / supplier_id 同款）
-- | 列 | 语义 |
-- |---|---|
-- | `processing_orders.processor`（**已存在**，V48 起） | 承接方**名称快照** —— 派单那一刻写死，事后改名不回写历史单 |
-- | `processing_orders.processor_supplier_id`（本迁移新增） | 承接方**档案引用** —— 可改名、可停用、可被多张单引用 |
--
-- ## 为什么**不**新建「加工厂」表
-- 加工厂本质是外部协作者，与供应商同形（名称/联系人/账期/启停）；`suppliers` 已有 V170 的
-- 名称唯一口径与 `inbound:view/create` 权限面。新建第二套主数据 = 同一家被录成两份、两套权限、
-- 两处停用。用 `type` 区分即可（material 采购供应商 / processor 外发加工厂）。
--
-- ## 为什么 type 是 NOT NULL DEFAULT 'material'
-- 存量行都是采购供应商（V170 建的档案只为入库/采购）⇒ 缺省即正确，**不回填、不猜**。
--
-- ## 为什么**不**加外键
-- 与 #7369 段 2 同口径：档案可停用/软删，单据侧引用的是**历史事实**；加外键会把「停用档案」
-- 变成「不能停用」，反而挡业务。服务层写面已校验「存在 / 本租户 / 在用 / 类型=加工厂」。
--
-- ## bootstrap 终态同步（同 V99/V108/V127/V133/V170 纪律）
-- 新建库路径**不跑历史迁移链** ⇒ `backend/admin-api/src/main/resources/db/init/schema.sql`
-- 已同步本文件终态（两列 + 约束 + 索引 + 注释）。只改一处 ⇒ 新建库缺列。
--
-- ## 回滚（**新迁移，不删本文件**）
-- ```sql
-- -- V193__rollback_outsource_consignee.sql（本单只登记，不落码）
-- -- DROP INDEX IF EXISTS idx_processing_orders_processor_supplier;
-- -- ALTER TABLE processing_orders DROP COLUMN IF EXISTS processor_supplier_id;
-- -- ALTER TABLE suppliers DROP CONSTRAINT IF EXISTS ck_suppliers_type;
-- -- ALTER TABLE suppliers DROP COLUMN IF EXISTS type;
-- ```
-- ⚠️ 回滚是**有损**的：已录入的「哪家是加工厂」与「哪张单外发给谁」会一并消失。属**有意**。
--
-- ## 显式事务
-- `MigrationRunner` 用 `jdbc.execute(整份文件)`（PG 隐式包一个事务）；而 `psql -f` 默认逐条
-- autocommit ⇒ 不显式 `BEGIN/COMMIT` 时中间步骤已提交 ⇒ 留下**半完成态**。两条执行路径必须同语义。
-- ══════════════════════════════════════════════════════════════════════════════════════

BEGIN;

-- ① 供应商档案加类型（material 采购供应商 / processor 外发加工厂）
ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS type VARCHAR(32) NOT NULL DEFAULT 'material';
ALTER TABLE suppliers DROP CONSTRAINT IF EXISTS ck_suppliers_type;
ALTER TABLE suppliers ADD CONSTRAINT ck_suppliers_type CHECK (type IN ('material', 'processor'));

COMMENT ON COLUMN suppliers.type IS
    '档案类型（V193，issue #7723）：material 采购供应商（缺省，存量行全部在档）/ processor 外发加工厂（可被智能派单选为承接方）。缺省即正确 ⇒ 不回填、不猜。';

-- ② 作业单记承接方档案引用（名称快照仍在 processor 列，两列同批写、同批读）
ALTER TABLE processing_orders ADD COLUMN IF NOT EXISTS processor_supplier_id VARCHAR(64);

COMMENT ON COLUMN processing_orders.processor_supplier_id IS
    '外发承接方档案引用（V193，issue #7723）：NULL = 本厂自做 / 存量单。processor 列仍是派单那一刻的名称快照（事后改名不回写历史单）。写入口 = 智能派单（ProcessingOrderService.prepare），**不是**作业单页。';

CREATE INDEX IF NOT EXISTS idx_processing_orders_processor_supplier
    ON processing_orders (tenant_id, processor_supplier_id)
    WHERE deleted = 0 AND processor_supplier_id IS NOT NULL;

COMMIT;
