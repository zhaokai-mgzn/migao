-- 种子：纱帘工艺路线补齐（issue #4246，P2）
--
-- ## 缺口（数据驱动，不是印象）
-- 真值源 `docs/curtain-production-rules.md` §3 列了「韩褶 / 打孔 / 四爪钩 / 穿杆 / 纱帘 / 帘头 /
-- 罗马帘」，而 `production_routings` 只有 6 条、纱帘只有「韩褶」一条 ⇒ 库里早已存在、有价、
-- **零消费**的 `上车布-纱`（车位/米/¥0.5）与 `打孔-纱`（车位/孔/¥0.15）没有路线消费它们。
--
-- ## 真正的危害（本迁移修的就是它）
-- `ProcessingOrderService.deriveRouteKey` 派生出的「纱帘×打孔」在路线库取不到 ⇒
-- `resolveRoute` **回落默认路线 布帘×韩褶** ⇒ 一张「纱帘+打孔」的订单拿到**布帘的 11 道工序**
-- （精裁-布 / 布三边 / 韩褶-布 …）⇒ 工人按布帘工序报工、计件按布帘单价算 ⇒
-- **工序与工资都是错的**。补这 3 条路线即修此。
--
-- ## 本迁移**只加路线**（红线，零新造工序）
-- 不新增/不改动任何 `production_operations` 行、不动任何单价（猜出来的工序价会直接算成
-- 工人工资，故一律改为向客户提问，见 #4246 §二「不做」表）。3 条路线的工序序列按布帘同工艺
-- **镜像**，去掉纱帘没有的 熨烫/定型/复烫/车被（行业判断见 #4246 §三）。
--
-- ## 为什么是**新迁移**而不是往 V54 里加行（关键，别"顺手合并"）
-- `MigrationRunner` 的台账 `schema_migrations` 按**文件名**记，已应用的文件**整份跳过**
-- （`applied.contains(filename)` ⇒ `continue`）。V54 在 dev/线上环境**早已执行** ⇒ 往 V54 里
-- 加行会「CI 绿、存量环境永远拿不到这 3 条路线」= **绿了但没生效**（本仓库最忌讳的形态）。
-- 故 V54 **一字不动**，路线增量走本迁移。
-- ⚠️ 版本号用 **V58**：V57 已被另一个并行包（#4208/#4230 的 Java 半边）占用，别抢号。
--
-- ## 幂等（MigrationRunner 要求所有迁移可重复执行）
-- `ON CONFLICT (tenant_id, curtain_type, craft) WHERE deleted = 0 DO NOTHING`
-- （冲突目标 = V49 的部分唯一索引 `uk_production_routings_tenant_type_craft`，其谓词为
-- `WHERE deleted = 0` ⇒ 显式写出才与索引谓词一致；软删后同键路线可重建，本迁移不"复活"软删行）。
--
-- ## 与真值源的收敛判据（防第二份口径漂移）
-- 本文件是 Python 常量 `ROUTINGS` 的一次**增量快照**，不是第二份真值源。防漂移由测试守：
-- `tests/unit_ci_workflows/test_production_catalog_seed.py` 聚合 **V54 ∪ V58** 后与 `ROUTINGS`
-- **逐条逐字**比对（改序列/加减路线即红），并自证「每个源都真被读到」（V58 缺席即 fail-closed）。

-- ── 3 条纱帘路线（tenant_id=1；id 确定性 `rt-v58-NN`，与 routing.py ROUTINGS 的书写顺序一致）──
INSERT INTO production_routings
    (id, tenant_id, curtain_type, craft, operations, status)
VALUES
  ('rt-v58-01', 1, '纱帘', '打孔',
   '["精裁-纱","纱三边","打孔-纱","外帘打卷","外帘装袋","外帘发货"]'::jsonb, 'active'),
  ('rt-v58-02', 1, '纱帘', '四爪钩',
   '["精裁-纱","纱三边","上车布-纱","外帘打卷","外帘装袋","外帘发货"]'::jsonb, 'active'),
  ('rt-v58-03', 1, '纱帘', '穿杆',
   '["精裁-纱","纱三边","外帘打卷","外帘装袋","外帘发货"]'::jsonb, 'active')
ON CONFLICT (tenant_id, curtain_type, craft) WHERE deleted = 0 DO NOTHING;
