-- 种子：特殊选项 A′ 类新增工序（issue #4230 v1a-PY，2026-09-18 用户裁定「按行业推算补齐」）
--
-- ## 为什么是**新迁移**而不是往 V54 里加行（关键，别"顺手合并"）
-- `MigrationRunner` 的台账 `schema_migrations` 按**文件名**记，已应用的文件**整份跳过**
-- （`applied.contains(filename)` ⇒ `continue`）。V54 在 dev/线上环境**早已执行** ⇒ 往 V54 里
-- 加行会「CI 绿、存量环境永远拿不到这 5 道工序」= **绿了但没生效**（本仓库最忌讳的形态）。
-- 故 V54 **一字不动**，新增工序走本迁移。
--
-- ## 真值源
-- `backend/ai-agent-service/app/production/routing.py` 的 `OPERATION_CATALOG`（本迁移追加的 5 道）
-- 与 `SPECIAL_OPTION_ROUTINGS`（选项 → 条件工序的映射，本迁移只落**工序**，映射由 Java 侧消费）。
-- 补齐的是真值源 §1【默】19 项特殊选项里此前**零登记**的 A′ 类：
--   纱绑带→绑带-纱 / 加logo条→logo条-布 / 加立边→立边-布 / 扣环→扣环-布 / 防翘扣→防翘扣-布
-- 单价为**行业推算**（商家可配，见 routing.py 注释里的推算依据），非实证值。
--
-- ## 为什么必须同时补单价版本行
-- V55 建的 `production_operation_price_versions` 口径是「**当前价 = 最新版本行**」，其回填
-- `INSERT ... SELECT ... FROM production_operations` **只覆盖 V55 执行时刻已存在的工序** ⇒
-- 本迁移新增的 5 道工序在 V55 之后出现，**不会**被那次回填覆盖。不补 ⇒ 这 5 道工序在
-- 「当前价」口径下**没有价**（界面/改价/追溯全落空）。本迁移自己补这 5 行初始版本。
--
-- ## 幂等（MigrationRunner 要求所有迁移可重复执行）
-- ① 工序插入：`ON CONFLICT (tenant_id, name) WHERE deleted = 0 DO NOTHING`（冲突目标 = V49 部分唯一索引）；
-- ② 版本回填：先 `DELETE` 本迁移这 5 道工序的**重复版本行**（只保留最早一行）再按 `NOT EXISTS` 守卫插入
--    ⇒ 重复执行不产生第二行、也不留「同工序多行最新版本」的歧义（「当前价 = 最新版本行」口径的
--    静默失真形态：两行时间戳相同时取哪一行不确定）。DELETE 亦幂等（无重复行时影响 0 行）。
--
-- ## 与真值源的收敛判据（防第二份口径漂移）
-- 本文件是 Python 常量的一次**增量快照**，不是第二份真值源。防漂移由测试守：
-- `tests/unit_ci_workflows/test_production_catalog_seed.py` 聚合 **V54 ∪ V56** 后与
-- `OPERATION_CATALOG` **逐行逐值**比对（改名/改价/加减工序即红）。

-- ── ① 追加 5 道工序（tenant_id=1；id 确定性 `op-v56-NN`，sort_order 接着 V54 的最大值 30 排）──
INSERT INTO production_operations
    (id, tenant_id, name, group_name, position, unit, unit_price,
     is_must_finish, is_start_marker, sort_order, status)
VALUES
  ('op-v56-01', 1, '绑带-纱', '其他', NULL, '套', 0.5, FALSE, FALSE, 31, 'active'),
  ('op-v56-02', 1, 'logo条-布', '车位', NULL, '米', 0.6, FALSE, FALSE, 32, 'active'),
  ('op-v56-03', 1, '立边-布', '车位', NULL, '米', 0.5, FALSE, FALSE, 33, 'active'),
  ('op-v56-04', 1, '扣环-布', '车位', NULL, '个', 0.3, FALSE, FALSE, 34, 'active'),
  ('op-v56-05', 1, '防翘扣-布', '车位', NULL, '个', 0.2, FALSE, FALSE, 35, 'active')
ON CONFLICT (tenant_id, name) WHERE deleted = 0 DO NOTHING;

-- ── ② 补这 5 道工序的初始单价版本行（口径同 V55：当前价 = 最新版本行）──
-- ②a 去重：同一工序只保留**最早**一行（防「重复执行 / 与 V55 回填撞车」造出多行最新版本）
UPDATE production_operation_price_versions v
SET deleted = 1
WHERE v.deleted = 0
  AND v.operation_id IN (SELECT o.id FROM production_operations o WHERE o.name = ANY (ARRAY[
        '绑带-纱', 'logo条-布', '立边-布', '扣环-布', '防翘扣-布']))
  AND EXISTS (
      SELECT 1 FROM production_operation_price_versions newer
      WHERE newer.operation_id = v.operation_id AND newer.deleted = 0
        AND newer.created_at < v.created_at
  );

-- ②b 回填：没有版本行的新工序各插一行（幂等：已有即跳过）
INSERT INTO production_operation_price_versions (id, tenant_id, operation_id, unit_price, created_at)
SELECT 'pv-' || o.id, o.tenant_id, o.id, o.unit_price, NOW()
FROM production_operations o
WHERE o.deleted = 0
  AND o.name = ANY (ARRAY['绑带-纱', 'logo条-布', '立边-布', '扣环-布', '防翘扣-布'])
  AND NOT EXISTS (
      SELECT 1 FROM production_operation_price_versions v
      WHERE v.operation_id = o.id AND v.deleted = 0
  )
ON CONFLICT (id) DO NOTHING;
