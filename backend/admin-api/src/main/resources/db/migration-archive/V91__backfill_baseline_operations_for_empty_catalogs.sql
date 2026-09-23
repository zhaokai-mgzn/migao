-- 补种「工序库从未被种上」的租户的**基线工序行**（issue #4707，P0 真库缺陷·第二层根因）。
--
-- ## 一句话
-- `V54` / `V56` 的工序种子**只种 `tenant_id = 1`**（四个文件里 `FROM tenants` 出现 0 次），
-- 而 `V71` / `V72` 的**按租户**回填（`FROM tenants`）只种了矩阵 / 路线 / 工艺 ——
-- ⇒ 非 1 号租户的**路线引用的工序在工序库里没有行** ⇒ 实例化取不到工序元数据
-- （分组 / 单位 / 单价 / 必完 / scope）⇒ `ProcessingOrderService.buildRoute` 的
-- `variantNameOf` 返回 `null` ⇒ 该道进 `missing_operations` ⇒ **fail-closed 422**。
--
-- ## 用户原始问题逐字（本单的修复理由）
-- > 「我想制定**纯布料**的工序路线，应该如何设置」+ 反复反馈「**建不出单 / 建不出路线**」。
--
-- ## 真库实测（2026-09-20，PG 18.3 / 阿里云 RDS `ai_customer_service`）
-- | 租户 | `production_operations`（含软删） | 矩阵行 | 活跃路线 | 判定 |
-- |---|---|---|---|---|
-- | 1 词元通达 | 36 | 86 | 1 | 健康（主线 9 道逐道可解析） |
-- | 20 米高POC演示布艺 | **0** | 84 | 1 | 窗帘主线 **9 道逐道悬空** ⇒ 布帘 9/9、帘头 6/6、纱帘 5/5 **fail-closed 422** |
-- | 21 POC彩排5605 | **0** | 84 | 1 | 同上 |
--
-- 「悬空」判定按**逐道比对**（逻辑名 → 该租户工序库里的变体名 / 裸逻辑名，与
-- `ProductionOperationQueryService.variantNameOf` 四步同口径）⇒ 这两户**一张加工单也建不出来**。
-- ⚠️ 与 `#4685` 的 V79 缺陷**正交**：V79 漏的是 `打包` / 布料价目格 / 布料路线（V89 已补），
-- 本单漏的是**整本工序库**（35 道基线工序一条都没有）。
--
-- ## 为什么必须是**新迁移**（不能改 V54 / V56）
-- `MigrationRunner` 的台账 `schema_migrations` 按**文件名**记账、已应用的文件**整份跳过**
-- ⇒ 改 V54 只对全新库生效、存量环境永远拿不到（=「CI 绿、功能静默缺失」，issue #4235）；
-- 已发布迁移另被 `tests/unit_ci_workflows/migration_fingerprints.json` 的 sha256 逐字节冻结。
--
-- ## 迁移号
-- `ls backend/admin-api/src/main/resources/db/migration | tail` **现取** ⇒ **V91**
-- （V89 被 #4685 占用、**V90 被 #4696 占用** ⇒ 顺延到 V91；若 push 时 V91 也被占 ⇒
-- 取下一个空闲号并在 PR body 说明）。
--
-- ## 目标终态 = **V88 之后**的口径（**36 行** = V54 的 30 + V56 的 5 + `打包`）
-- 逐行逐值与 `docs/sql/schema.sql` 的 bootstrap 终态种子、以及
-- `ProductionSeedTemplateService`（开租播种）读的
-- `resources/production-templates/curtain/seed.json` **逐项一致**：
-- 名称 / 分组 / 部位 / 单位 / 单价 / 必完 / 开始标记 / `sort_order` / `source` / `scope`。
--   · `source` = V54 ∪ V79 → `占位待确认`；V56 → `推算`（与 schema.sql 的 provenance 回填逐条同口径）；
--   · `scope` = `外帘打卷` / `外帘装袋` / `外帘发货` / `打包` → `set`（套级，一樘窗一次），其余 `position`；
--   · `sort_order` 保留 V54/V56 的 1..35 与 V79 的 37（`36` 是 `配料`，见下）。
--
-- ⚠️ **为什么不种 `配料`**（**有意取舍，照实登记**）：`V88`（issue #4676）已让 `配料` 退场
-- （工序行软删 + 矩阵 4 格软删 + 布料主线元素替换为 `裁剪`）⇒ 本文件**直接落终态**，不种退场工序。
-- `docs/sql/schema.sql` 里保留了一行 `配料`（`deleted = 1`）是**bootstrap 的一次性建库脚本**要
-- 「留痕可审计」；对本迁移的受众（**从未有过该行**的租户）而言，插入一行注定软删的行只会
-- 让「工序库有多少行」这个数在两类租户间继续分裂，没有可审计的对象。
--
-- ## 闸门：**只补「从未种过基线工序」的租户**（不覆盖商家已改，红线）
-- 谓词 = 该租户的 `production_operations` 里**一条 V54 ∪ V56 的基线工序都没有**（**含软删行**）。
--   · **含软删行**是承重的：商家删过某道 ⇒ 说明**种过了** ⇒ 本迁移不碰他（否则会把商家
--     主动删掉的工序**悄悄种回来**）；
--   · 🔴 **必须把 `打包` 从名字集里排除**：`V89`（#4685）刚给这些租户补过 `打包` ⇒
--     把它算进「基线是否已种」会让闸门**恒假** ⇒ 本迁移**静默空跑**（正是本单要治的形态）。
--   · 为什么**不按 id 前缀**（`op-v54-%`）判：开租播种（`ProductionSeedTemplateService`）落的
--     id 是 UUID（模板 id 是模板内稳定键、不是落库 id）⇒ 按 id 判会把**健康**的开租租户误判成
--     「从未种过」。
--   · 为什么**不是**「全量 upsert」：`NOT EXISTS` 逐行去重 + 闸门双重保护 ⇒ 商家改过的价 /
--     适用性 / 自建行**一字不动**（本文件**没有任何** `UPDATE` / `DELETE`）。
--
-- ## 幂等（`MigrationRunner` 硬要求所有迁移可重复执行）
-- ① 闸门（`NOT EXISTS` 按名字集）⇒ 已补过的租户整块跳过；
-- ② 逐行 `NOT EXISTS`（业务唯一键 `(tenant_id, name) WHERE deleted = 0`，对齐 V49 的部分唯一索引）；
-- ③ `ON CONFLICT (tenant_id, name) WHERE deleted = 0 DO NOTHING` 兜底。
-- ⇒ 第二次执行匹配 0 行、净效果相同。
--
-- ## 🔴 类型显式（**V79 的真库事故教训**）
-- `VALUES` 列表里 `unit_price` 逐行 `::numeric`、`is_must_finish` / `is_start_marker` 逐行
-- `::boolean` —— 不写就复现 V79 的推断坑（`JOIN (VALUES …)` 里整列 NULL 被推断成 `text`，
-- 而 `text → numeric` **不是赋值转换** ⇒ 整文件单事务回滚、`schema_migrations` 里该版本永久缺席）。
-- 本文件的 `unit_price` 列**没有** NULL（`production_operations.unit_price` 是
-- `NOT NULL DEFAULT 0`），但**仍然逐行显式**：口径与 V89 一致，且防止将来加一行 NULL 时静默复发。
--
-- ## 回滚（**新迁移，不删 V91**；语义 = 撤掉本次补种的行）
-- ```sql
-- -- V92__rollback_baseline_operations_backfill.sql（本单只登记，不落码）
-- UPDATE production_operations o SET deleted = 1, updated_at = NOW()
--   FROM tenants t WHERE o.tenant_id = t.id AND t.deleted = 0
--    AND o.id LIKE 'op-v91-%' AND o.deleted = 0;
-- ```
-- ⚠️ **回滚不能复原的东西（如实登记）**：本迁移生效期间**新建**的加工单已按当前工序库实例化
-- ⇒ 回滚后这些单的**实例快照不会自动变回**（`processing_position_operations` 是本文件的**红线外**表，
-- 一字未动）。回滚的语义是「让新单回到旧行为」，**不是**「让历史单回到旧行为」。
-- ⚠️ 回滚后这些租户会**重新** fail-closed 422 —— 那是**回到缺陷**，仅在确认业务可接受时执行。
--
-- ## 停止条件（出现任一条即停手，不回滚 V91、另开单）
-- S1 补种后某租户的窗帘单实例化仍 422（核法：真库逐道比对主线 → 变体名解析，应 0 条悬空）；
-- S2 补种后某租户的**工序库行数** > 36（说明闸门漏了 ⇒ 覆盖了商家自建行，立即停手）；
-- S3 三张快照表任一被写入（核法：`git grep` 本文件应零命中
--    `processing_orders` / `processing_position_operations` / `production_work_logs`）；
-- S4 商家已改过的价 / 适用性被覆盖（核法：改前记 `(tenant_id, name)` → `unit_price`，重跑后逐行比对）；
-- S5 重复执行净效果不同（核法：跑两遍，逐表 `count(*)` + 全行指纹一致）；
-- S6 某租户的 `配料` 被种回来（`production_operations` 里出现 `name = '配料' AND deleted = 0`）。
--
-- ## 🔴 红线：三张快照表**一字不动**（本文件的 DML 只碰 1 张**配置**表）
--   · `processing_orders.items_snapshot`（加工单快照）
--   · `processing_position_operations`（工序实例快照；⚠️ 与 `production_operation_positions`
--     **名字极像**，本文件**两张都不写**）
--   · `production_work_logs.unit_price` / `factor`（报工快照；历史工资不回溯）
--
-- ## 与真值源的收敛
-- 本文件落的终态与 `ProductionSeedTemplateService`（开租播种终态）+ `docs/sql/schema.sql`
-- （bootstrap 终态）**逐项一致** —— 「存量租户走迁移链、新租户走开租播种」两条路径必须落同一个
-- 终态，否则同一种单在两类租户上工序数不同。静态守卫 =
-- `tests/unit_ci_workflows/test_v91_baseline_operations_backfill.py`（三处口径 + 注入式红证）
-- 与 `backend/admin-api/src/test/java/com/migao/admin/service/MainlineOperationReferenceTest.java`
-- （运行时读面）。

-- ══════════════════════════════════════════════════════════════════════════════════════
-- 基线工序库（36 行 = V54 的 30 + V56 的 5 + `打包`）—— 只补「从未种过」的活跃租户
-- ══════════════════════════════════════════════════════════════════════════════════════
-- 形态：**1 条 `INSERT … SELECT`**，36 行由 `CROSS JOIN (SELECT … UNION ALL SELECT …) AS b` 提供
-- （清单只写一份 ⇒ 闸门与逐行守卫都不需要第二份名单）。
--
-- 🔴 **为什么不用 `(VALUES …)` 也不用 `WITH … AS (VALUES …)`**（两条都是踩过的坑，别再改回去）：
--   ① `CROSS JOIN (VALUES …)`：`tests/unit_ci_workflows/test_production_catalog_seed.py` 的
--      `parse_seed` 用「`INSERT INTO` … `[^;]*?VALUES`」抓种子行，会把**派生表里**的 `VALUES`
--      当成种子行 ⇒ 列数 10 ≠ INSERT 列数 14 ⇒ **假红**（该文件对 P2/V72 的同款形态已用
--      `values_sources_for` 的「`VALUES` 必须在 `FROM` 之前」分流修过，但 `parse_seed` 本身
--      仍按老正则走 ⇒ 本迁移**刻意避开**这个关键词）；
--      ⚠️ 本注释**不得**写出那个「`INSERT INTO` + 表名」的连写形态 —— 那些守卫用
--      `re.search` 非贪婪抓语句，注释里的连写会被当成**真语句**（实测：把连写留在注释里，
--      `test_seed_sql_is_idempotent` 与 `test_every_seed_source_contributes_to_the_aggregate`
--      双双假红）。
--   ② `WITH baseline AS (VALUES …)`：`tests/unit_ci_workflows/test_migration_references_exist_in_schema.py`
--      把 `FROM <标识符>` 一律当表名做存在性校验 ⇒ CTE 名会被判「表 `baseline` 不存在」（同样假红）。
--   ⇒ `UNION ALL SELECT` 两个坑都不踩。
INSERT INTO production_operations
    (id, tenant_id, name, group_name, position, unit, unit_price,
     is_must_finish, is_start_marker, sort_order, status, deleted, scope, source)
SELECT 'op-v91-' || t.id || '-' || lpad(b.sort_order::text, 2, '0'),
       t.id, b.name, b.group_name, b.position, b.unit, b.unit_price,
       b.is_must_finish, b.is_start_marker, b.sort_order, 'active', 0, b.scope, b.source
  FROM tenants t
  CROSS JOIN (
      -- 第一行带列别名（`UNION ALL` 的类型也由它钉住：`::numeric` / `::boolean` 逐行显式）
      SELECT '精裁-布' AS name, '裁剪' AS group_name, '布帘' AS position, '米' AS unit, 0.4::numeric AS unit_price, FALSE::boolean AS is_must_finish, TRUE::boolean AS is_start_marker, 1 AS sort_order, '占位待确认' AS source, 'position' AS scope
      UNION ALL SELECT '精裁-纱', '裁剪', '纱帘', '米', 0.4::numeric, FALSE::boolean, TRUE::boolean, 2, '占位待确认', 'position'
      UNION ALL SELECT '裁剪-布', '裁剪', '布帘', '米', 0.4::numeric, FALSE::boolean, FALSE::boolean, 3, '占位待确认', 'position'
      UNION ALL SELECT '裁剪-纱', '裁剪', '纱帘', '米', 0.4::numeric, FALSE::boolean, FALSE::boolean, 4, '占位待确认', 'position'
      UNION ALL SELECT '布三边', '车位', NULL, '米', 0.4::numeric, FALSE::boolean, FALSE::boolean, 5, '占位待确认', 'position'
      UNION ALL SELECT '纱三边', '车位', NULL, '米', 0.4::numeric, FALSE::boolean, FALSE::boolean, 6, '占位待确认', 'position'
      UNION ALL SELECT '韩褶-布', '车位', '布帘', '折', 0.4::numeric, FALSE::boolean, FALSE::boolean, 7, '占位待确认', 'position'
      UNION ALL SELECT '韩褶-纱', '车位', '纱帘', '折', 0.4::numeric, FALSE::boolean, FALSE::boolean, 8, '占位待确认', 'position'
      UNION ALL SELECT '上车布-布', '车位', '布帘', '米', 0.5::numeric, FALSE::boolean, FALSE::boolean, 9, '占位待确认', 'position'
      UNION ALL SELECT '上车布-纱', '车位', '纱帘', '米', 0.5::numeric, FALSE::boolean, FALSE::boolean, 10, '占位待确认', 'position'
      UNION ALL SELECT '打孔-布', '车位', '布帘', '孔', 0.15::numeric, FALSE::boolean, FALSE::boolean, 11, '占位待确认', 'position'
      UNION ALL SELECT '打孔-纱', '车位', '纱帘', '孔', 0.15::numeric, FALSE::boolean, FALSE::boolean, 12, '占位待确认', 'position'
      UNION ALL SELECT '拼1次-布', '车位', '布帘', '幅', 0.8::numeric, FALSE::boolean, FALSE::boolean, 13, '占位待确认', 'position'
      UNION ALL SELECT '拼2次-布', '车位', '布帘', '幅', 1.2::numeric, FALSE::boolean, FALSE::boolean, 14, '占位待确认', 'position'
      UNION ALL SELECT '拼3次-布', '车位', '布帘', '幅', 1.6::numeric, FALSE::boolean, FALSE::boolean, 15, '占位待确认', 'position'
      UNION ALL SELECT '花边-布', '车位', '布帘', '米', 0.6::numeric, FALSE::boolean, FALSE::boolean, 16, '占位待确认', 'position'
      UNION ALL SELECT '铅坠-布', '车位', '布帘', '米', 0.3::numeric, FALSE::boolean, FALSE::boolean, 17, '占位待确认', 'position'
      UNION ALL SELECT '接高-布', '车位', '布帘', '幅', 1.0::numeric, FALSE::boolean, FALSE::boolean, 18, '占位待确认', 'position'
      UNION ALL SELECT '帘头制作', '车位', '帘头', '个', 2.0::numeric, FALSE::boolean, FALSE::boolean, 19, '占位待确认', 'position'
      UNION ALL SELECT '熨烫-布', '后道', '布帘', '米', 0.35::numeric, FALSE::boolean, FALSE::boolean, 20, '占位待确认', 'position'
      UNION ALL SELECT '定型-布', '后道', '布帘', '米', 0.4::numeric, FALSE::boolean, FALSE::boolean, 21, '占位待确认', 'position'
      UNION ALL SELECT '复烫-布', '后道', '布帘', '米', 0.35::numeric, FALSE::boolean, FALSE::boolean, 22, '占位待确认', 'position'
      UNION ALL SELECT '布帘车被', '后道', NULL, '米', 0.4::numeric, FALSE::boolean, FALSE::boolean, 23, '占位待确认', 'position'
      UNION ALL SELECT '外帘打卷', '后道', '外帘', '套', 1.0::numeric, FALSE::boolean, FALSE::boolean, 24, '占位待确认', 'set'
      UNION ALL SELECT '外帘装袋', '后道', '外帘', '套', 1.0::numeric, TRUE::boolean, FALSE::boolean, 25, '占位待确认', 'set'
      UNION ALL SELECT '质检', '后道', NULL, '套', 1.5::numeric, FALSE::boolean, FALSE::boolean, 26, '占位待确认', 'position'
      UNION ALL SELECT '外帘发货', '后道', '外帘', '套', 1.0::numeric, FALSE::boolean, FALSE::boolean, 27, '占位待确认', 'set'
      UNION ALL SELECT '绑带-布', '其他', '布帘', '套', 0.5::numeric, FALSE::boolean, FALSE::boolean, 28, '占位待确认', 'position'
      UNION ALL SELECT '抱枕', '其他', NULL, '个', 2.0::numeric, FALSE::boolean, FALSE::boolean, 29, '占位待确认', 'position'
      UNION ALL SELECT '腰靠垫', '其他', NULL, '个', 2.0::numeric, FALSE::boolean, FALSE::boolean, 30, '占位待确认', 'position'
      UNION ALL SELECT '绑带-纱', '其他', NULL, '套', 0.5::numeric, FALSE::boolean, FALSE::boolean, 31, '推算', 'position'
      UNION ALL SELECT 'logo条-布', '车位', NULL, '米', 0.6::numeric, FALSE::boolean, FALSE::boolean, 32, '推算', 'position'
      UNION ALL SELECT '立边-布', '车位', NULL, '米', 0.5::numeric, FALSE::boolean, FALSE::boolean, 33, '推算', 'position'
      UNION ALL SELECT '扣环-布', '车位', NULL, '个', 0.3::numeric, FALSE::boolean, FALSE::boolean, 34, '推算', 'position'
      UNION ALL SELECT '防翘扣-布', '车位', NULL, '个', 0.2::numeric, FALSE::boolean, FALSE::boolean, 35, '推算', 'position'
      UNION ALL SELECT '打包', '后道', NULL, '套', 0::numeric, FALSE::boolean, FALSE::boolean, 37, '占位待确认', 'set'
  ) AS b
 WHERE t.deleted = 0
   -- ① 闸门：该租户的工序库里**除 `打包` 外没有任何行**（**含软删行**）⇒ 判定为「从未被种过」。
   --    🔴 为什么排除 `打包`：`V89`（#4685）刚给这些租户补过它 ⇒ 不排除则闸门**恒假**、
   --       本迁移**静默空跑**（正是本单要治的形态）。
   --    🔴 为什么**不加** `e.deleted = 0`：商家删过 / 改过名 ⇒ 他的库里**仍有行** ⇒ 闸门为假
   --       ⇒ 本迁移**不碰他**（否则会把商家主动删掉的工序悄悄种回来）。
   --    🔴 为什么不用「35 条基线工序名一条都不存在」当闸门：那需要**第二份名单**（会漂移）；
   --       而「除 `打包` 外没有任何行」与它在本迁移链的**所有可达状态**上等价
   --       （V54/V56 一次性种 30+5 行、开租播种一次性种 37 行 ⇒ 不存在「只有一两行」的中间态）。
   AND NOT EXISTS (
       SELECT 1 FROM production_operations e
        WHERE e.tenant_id = t.id
          AND e.name <> '打包')
   -- ② 逐行幂等（业务唯一键 `(tenant_id, name) WHERE deleted = 0`，对齐 V49 的部分唯一索引）
   AND NOT EXISTS (
       SELECT 1 FROM production_operations e
        WHERE e.tenant_id = t.id AND e.name = b.name AND e.deleted = 0)
ON CONFLICT (tenant_id, name) WHERE deleted = 0 DO NOTHING;
