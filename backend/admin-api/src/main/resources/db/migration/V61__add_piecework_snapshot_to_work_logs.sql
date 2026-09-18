-- 报工增列计件单价/系数快照（issue #4351，P0：计件工资静默少算）
--
-- ## 为什么需要这两列（病根）
-- 计件金额原先在**聚合时**回查工序实例算：
--
--     ProcessingPositionOperation op = operationLookup.apply(log.getOperationId());
--     if (op == null) { continue; }   -- 工序实例已不存在（软删）→ 该笔不可计价
--
-- 而 `ProcessingOrderService.instantiate` 在**重新实例化**时会**软删旧实例并重插**
-- （触发路径 `POST /production/orders/{orderId}/instantiate` —— 工艺变更 / #4202 给存量单补工序，
-- 都是正常运维动作）⇒ 旧报工指向**已软删的旧实例 id** ⇒ 被 `continue` 跳过
-- ⇒ **工人已经做完、已经报过的工，那笔钱从计件合计里消失，且不报错**（报表照常返回一个偏小的合计）。
--
-- 真值源 §4 的明文口径是「单价 = 工序 × 部位定价，**版本化**（调价只影响新报工，
-- **历史报工按当时价，逐笔可追溯**）」—— 回查实例做不到这一点（实例会被软删/重插），
-- 故计件金额必须在**报工那一刻固化**：本迁移把当时的 `unit_price`/`factor` 写进报工自己。
-- 副作用正是想要的：**重算历史工资变成不可能**。
--
-- ## 幂等
-- `ADD COLUMN IF NOT EXISTS`（MigrationRunner 要求所有 SQL 可重复执行）；
-- 回填按 `unit_price IS NULL` 守卫（只补本列引入前的行，不覆盖已固化的快照）。
--
-- ## 回填为什么**含软删实例**
-- 存量报工里已经有指向软删实例的行（那正是本单要治的形态）。回填时**不过滤 `deleted`**：
-- 软删实例上的 `unit_price`/`factor` 仍是**生成时快照**（V49 口径：改价不回溯既有实例）
-- ⇒ 它就是「报工当时的价」，正是真值源 §4 要的那个值。过滤 `deleted = 0` 会把最需要救的
-- 那批历史报工留成 NULL，聚合只能按实例回查 ⇒ 钱照样消失。
--
-- ## 三源收敛
-- 迁移列 / Java 实体 `ProductionWorkLog.unitPrice|factor` / bootstrap `docs/sql/schema.sql`
-- 三处同口径。`NULL` = 本列引入之前的存量报工（聚合按实例回查兜底，见 `ProductionService.aggregate`）。

ALTER TABLE production_work_logs
    ADD COLUMN IF NOT EXISTS unit_price NUMERIC(10,2);

ALTER TABLE production_work_logs
    ADD COLUMN IF NOT EXISTS factor NUMERIC(10,2);

COMMENT ON COLUMN production_work_logs.unit_price IS
    '计件单价快照（元/单位，V61，issue #4351）：报工那一刻从工序实例 processing_position_operations.unit_price 写入；聚合只读本列 ⇒ 重新实例化软删旧实例不影响历史报工的钱；NULL=本列引入前的存量行（按实例回查兜底）';
COMMENT ON COLUMN production_work_logs.factor IS
    '计件系数快照（V61，issue #4351）：与 unit_price 同一次报工写入、同一口径；NULL=存量行';

-- 回填存量报工（只补 unit_price IS NULL 的行；含软删实例 —— 见上方「回填为什么含软删实例」）
UPDATE production_work_logs w
   SET unit_price = o.unit_price,
       factor     = COALESCE(o.factor, 1)
  FROM processing_position_operations o
 WHERE w.unit_price IS NULL
   AND o.id = w.operation_id
   AND o.tenant_id = w.tenant_id;
