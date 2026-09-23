-- 未定价实例的**显式补价**动作账（issue #4709 C，P1）
--
-- ## 一句话
-- `#4696`（V90）之后三态在数据层可区分：**未定价**（实例 `unit_price IS NULL`）/ **价 0** /
-- **有价**。但**已实例化**的旧单在商家补定价之后**没有任何补价路径** —— 商家的钱还是算不出来：
--
-- | 可能的「补价」路径 | 为什么不行 |
-- |---|---|
-- | 重新实例化（`POST /orders/{id}/instantiate`） | `OpSpec.signature()` 的 `num()` 是 `nz(value).stripTrailingZeros()` ⇒ `null` 与 `0` **同签名** ⇒「未定价 ↔ 定价 0」的切换**不判**「工艺变更」（不软删重插 —— 安全方向）；而 `null → 非 0` 虽会判变更，代价是**软删旧实例 + 重插 + 报工进度清零**（`done_qty` 归零，红线禁止） |
-- | 读面实时取价（`NULL` 实例按当前矩阵价显示「预计金额」） | 与「**下单时刻快照**」口径冲突（实例单价是生成时的快照，改价只影响新报工）⇒ 同一张单的界面数字与工人实际拿到的钱会**两套口径** |
-- | 什么都不做 | 商家定了价、工人干了活，**钱永远算不出来且不报错** |
--
-- ⇒ 本单走**显式补价动作**（只把 `unit_price IS NULL` 的实例行补成**当前矩阵价**）——
-- 本迁移为它建**动作账**。
--
-- ## 为什么必须建账（而不是只写代码）
-- 补价是**改写实例快照**的动作：`PUT /production/operations/{id}` 的既有结构判据逐字是
-- 「物理上没有写实例表的能力」（PG-020），而本动作**故意**要写它 ⇒ 必须可追溯
-- ① 「这行价是商家在矩阵里定的，还是补价补出来的」；② 一次动作改了多少行、改成多少；
-- ③ **可回滚**（回滚的判据只能来自账本 —— 没有账本就分不清「该回滚的行」与「商家本来定的行」）。
--
-- 粒度 = **一次动作一批**（`batch_id`），一行 = 一个被补价的实例行。回滚 = 按批把
-- `unit_price` 还原成 `NULL`（`rolled_back_at` 留痕），**只回滚本批、且只在当前值仍等于
-- 本行记录的 `new_unit_price` 时**（并发/后续改动不被覆盖，见服务层 CAS 谓词）。
--
-- ## 不记录 `old_unit_price`（有意的）
-- 本账只由「`unit_price IS NULL` ⇒ 有价」这一条路径写入（服务层的 CAS 谓词 `unit_price IS NULL`
-- 是机械保证）⇒ `old_unit_price` 恒为 `NULL`，多一列恒空列只会制造「它可能是别的值」的错觉。
-- 「只补 NULL」的判据落在**写路径的谓词**上，不落在账本的冗余列上。
--
-- ## 幂等
-- `CREATE TABLE/INDEX IF NOT EXISTS` + `COMMENT ON` 天然幂等；**不回填任何存量行**
-- （存量实例的未定价行要不要补价是**商家的动作**，不是迁移的默认行为 —— 迁移静默改价
-- 就是本 issue 要治的「无人知道」形态）。
--
-- ## 停止条件（fail-closed，不静默降级）
-- 外键（`tenants` / `processing_orders` / `processing_position_operations`）是「账本不会留下孤儿行」
-- 的保证 ⇒ 任一被引用表缺失时**建表失败并停下**（Flyway 事务回滚），
-- **不**为了通过而摘掉外键、也不改用「弱引用字符串」。
CREATE TABLE IF NOT EXISTS production_instance_repricing_logs (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    -- 一次补价动作 = 一个批次（回滚的粒度）；同一批次的每个被补价实例行一行
    batch_id VARCHAR(64) NOT NULL,
    processing_order_id VARCHAR(64) NOT NULL REFERENCES processing_orders(id),
    position_operation_id VARCHAR(64) NOT NULL REFERENCES processing_position_operations(id),
    -- 本次补上的单价（元/单位）= 补价那一刻**部位价目矩阵**的当前价
    new_unit_price NUMERIC(10,2) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    -- 回滚时刻；NULL = 未回滚（回滚后该行的 unit_price 已被还原为 NULL）
    rolled_back_at TIMESTAMP WITH TIME ZONE,
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_instance_repricing_batch
    ON production_instance_repricing_logs (tenant_id, batch_id)
    WHERE deleted = 0;
CREATE INDEX IF NOT EXISTS idx_instance_repricing_operation
    ON production_instance_repricing_logs (position_operation_id)
    WHERE deleted = 0;
COMMENT ON TABLE production_instance_repricing_logs IS
    '未定价实例的**显式补价**动作账（V94，issue #4709）：一行 = 一个被补价的实例行；'
    '只由「unit_price IS NULL ⇒ 当前矩阵价」这一条路径写入（已有价的行永远不产生账行）；'
    'batch_id = 一次动作，回滚按批（rolled_back_at 留痕）';
COMMENT ON COLUMN production_instance_repricing_logs.new_unit_price IS
    '本次补上的计件单价（元/单位）= 补价那一刻部位价目矩阵的当前价；'
    '回滚只在实例行当前值仍等于本值时才还原（CAS），不覆盖后续改动';
COMMENT ON COLUMN production_instance_repricing_logs.rolled_back_at IS
    '回滚时刻（NULL = 未回滚）；回滚只还原 unit_price → NULL，**不碰** factor / done_qty / status / 报工历史';
