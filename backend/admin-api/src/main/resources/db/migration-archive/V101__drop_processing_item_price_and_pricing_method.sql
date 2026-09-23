-- 加工项目录彻底删除「加工项计价方式」与「加工项单价」（issue #4882，用户裁定）
--
-- ## 用户裁定（冻结，不得扩大或收窄）
--   彻底删除「加工项单价」与「加工项计价方式」两列：
--     · `processing_items.pricing_method`（历史取值 per_meter / per_set / fixed / per_area）
--     · `processing_items.unit_price`
--   加工费的真值源是 `processing_fee_combinations`（组合价 × 加工费米数），加工项目录不再承担计价。
--
-- ## 为什么必须是**新迁移**（迁移不可变：V83 / V34 一字不动）
--   `MigrationRunner` 按**文件名**记 `schema_migrations`（`applied.contains(filename) ⇒ 整份 skip`）
--   ⇒ 直接改 V83（它 `INSERT INTO processing_items (…, pricing_method, unit_price, …)`）会让**存量库**
--   永远停在旧形态，而 CI 全绿、功能静默缺失（判据与账本见
--   backend/admin-api/src/main/resources/db/migration 的同族护栏
--   `tests/unit_ci_workflows/test_migration_immutability.py`）。
--   ⇒ 本迁移**只做删列**这一件事；V83 的历史 INSERT 保持原样（它在迁移链里排在 V101 之前，能跑）。
--
-- ## 幂等（MigrationRunner 要求所有 SQL 可重复执行）
--   `DROP COLUMN IF EXISTS`：第二遍重跑是 no-op；`ALTER COLUMN … SET DEFAULT` 重复设置同值亦无副作用。
--
-- ## 语义变化（如实登记）
--   · `unit` 列**保留**，语义改为「**加工数量**单位」，默认由 `元` 改为 `米`
--     （目录不再有单价 ⇒ 它不再是「计价单位」）。
--   · 存量订单快照（`order_items.processing_info.processingItems[]` 里的 `pricingMethod` / `unitPrice`）
--     **不迁移、不清洗**：那是历史事实，Java 读面仍按 #4882 的三段契约消费
--     （`ProcessingOrderService.isMeterBasedLine`：带键的行按 `per_meter` 判、全无键的行按米类判）。
ALTER TABLE processing_items DROP COLUMN IF EXISTS pricing_method;
ALTER TABLE processing_items DROP COLUMN IF EXISTS unit_price;
ALTER TABLE processing_items ALTER COLUMN unit SET DEFAULT '米';
