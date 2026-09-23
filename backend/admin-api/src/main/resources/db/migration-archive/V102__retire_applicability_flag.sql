-- 去部位化**彻底版**：一条原子迁移做完三件事（issue #4937 = 母单 #4936；本文件由 2026-09-21 合并重写）。
--
-- ## 一句话
-- 一条迁移、一个 `BEGIN; … COMMIT;`，**原子地**做完：
--   ① **价目矩阵物理塌缩** —— `production_operation_positions` 按 `(tenant_id, logical_name)` 收敛为**一行**：
--      非幸存行**软删**（`deleted = 1` + `updated_at`），幸存行写 `position = '通用'` + `applicable = TRUE`；
--   ② **补 4 道纱帘变体工序行** —— `熨烫-纱` / `定型-纱` / `复烫-纱` / `车被-纱`（单价**逐字取对应 `-布` 变体**）；
--   ③ **原子与自证** —— 显式 `BEGIN/COMMIT`；收尾判据只读**状态**（收敛度 / 取值集 / 计数），
--      **零**时间戳推断（见下方「上版死因」）。
--
-- ## 🔴 为什么这五条可以合并重写（**先核清前提再动手**，本单的立论基础）
-- 原 `V102` / `V103` / `V104` / `V105` / `V106` 五条**从未在任何环境成功应用过**：
--   · 证据 ①（云测试环境 **2026-09-20** 容器启动日志）：`MigrationRunner` 逐条点名
--     **`V102` / `V103` / `V104` / `V105` / `V106`** 全部失败
--     （另有 `V40` / `V72` / `V74` / `V79` 四条**存量噪音** —— 非幂等种子在重跑，**不在本单射程**，留着）；
--   · 证据 ②（唯一抓到的一条原文）：`V102` 报
--     `ERROR: V102 越界：有 1 条「applicable = FALSE」的存活行被改动过 …—— 回滚本迁移`；
--   · 证据 ③（线上读面实测）：矩阵 `position` 仍是 `布帘` / `帘头`（`V104` 本应写 `通用`）、
--     工序库里**没有** 4 道 `-纱` 变体（`V105` / `V106` 本应补）。
-- `MigrationRunner` 的台账 `schema_migrations` 按**文件名**记账、已应用的文件**整份跳过**
-- ⇒ 这五条**不是「已发布迁移」**，而是**五条没生效的半成品**（改/删它们不会让任何存量环境丢东西）。
-- 用户裁定逐字（2026-09-21）：「**DB层的改造需要彻底**」；早先同族裁定：
-- 「这些都是**测试数据**，**不要怕搞坏**」+「**不计成本的改**」
-- ⇒ **授权合并重写为一条 `V102`，并删除 `V103` ~ `V106` 四个文件**。
-- 迁移不可变账本 `tests/unit_ci_workflows/migration_fingerprints.json` 在**同一 PR** 里一次性更新
-- （`V102` 换新哈希 + 删掉那四条），正当性原文写在账本的 `_comment` 里。
--
-- ## 🔴 `V103` 的意图**已作废** —— 部位维**保留**，本文件**一字不碰** `production_route_rules`
-- 用户裁定「结合新的需求（#4962 **适用条件加回部位维**）**统一考量**」⇒ 部位维**只允许活在一个地方**：
-- **`production_route_rules.position` = 部位维的唯一载体**（#4962 要用它做「适用条件 = 部位」的筛选）。
-- ⇒ `V103`（把存活规则的 `position` 清空为 `NULL`）的意图**作废** ⇒ **删除该文件就是撤销它**；
--   线上那条种子规则 `韩褶 → insert 上车布` 的 `position = '布帘'` **至今还在**（因为 `V103` 从未生效）
--   —— 那是**要保留**的终态，不是要清掉的残留。
-- ⇒ 本文件的 DML **只碰两张表**：`production_operation_positions`（塌缩）与 `production_operations`（只 `INSERT`）；
--   **`production_route_rules` 的任何数据一字不动**（正文里连该表名都不出现）。
--   规则侧的终态由 **`V71` 的字面量种子**与 **bootstrap 镜像 `docs/sql/schema.sql`** 共同承载，
--   两者的 `position` 必须**逐字一致**（守卫 = `test_production_catalog_seed.py` 的
--   「部位维终态在多源间一致」判据）。
--
-- ## 上版的死因（**本文件必须不重犯**，逐条对应到下面的实现）
-- 上版 `V102` 的收尾守卫形如
--   `… WHERE deleted = 0 AND applicable IS FALSE AND <写入戳晚于创建戳>` ⇒ 命中即 `RAISE`。
-- 它**按时间戳推断「谁被改动」**：`updated_at > created_at` 只说明「这一行**历史上**被改过」
-- （例如商家改过价、或更早的迁移写过它）—— **与本迁移无关** ⇒ 存量里有一行就足以把整条迁移
-- **判死并整份回滚** ⇒ `V103` ~ `V106` 因失去前置被同一串问题拖住 ⇒ **五条一起没生效**。
-- 另一处**NULL 口径**错误：`applicable IS NOT FALSE` 对 `applicable IS NULL` 求值为 `TRUE`
-- ⇒ NULL 行被当成「已经是 TRUE」放行（云库里确实存在 `applicable IS NULL` 的存活行）。
-- ⇒ 本文件三条纪律（每一条都可机械核验）：
--   1. **零时间戳判据** —— 正文里**没有** `created_at` 这个列名，也没有任何 `>` / `<` 时间戳比较；
--      判据只读**状态**（收敛度 / 取值集 / 计数）⇒ 不存在「存量碰巧改过 ⇒ 迁移判死」这一形态；
--   2. **`applicable IS NULL` 按「非 TRUE」处理** —— 幸存判据写 `(p.applicable IS TRUE)`
--      （`NULL` ⇒ 排序里不被优先），**不写** `IS NOT FALSE`；
--   3. 失败一律靠 **`BEGIN` / `COMMIT` 整体回滚**（原子），**不靠猜**。
--
-- ## 选行规则（四档，**逐档与 Java / Python 同序，不得改名换序**）
-- 1. `applicable IS TRUE` 优先（`FALSE` / **`NULL`** = 「当年该部位明确不做 / 未标」，其 `unit_price`
--    一律 `NULL` ⇒ 优先它会把**有价**的工序判成未定价）；
-- 2. 其中 `position = '布帘'` 优先（用户裁定「取布帘价」；常量 =
--    `ProductionOperationQueryService.COLLAPSE_PRICE_SOURCE_POSITION`）；
-- 3. 再按 `position` **字典序**（`COALESCE(position,'')`，`COLLATE "C"`）；
-- 4. 最后按 `id` 升序（`COALESCE(id,'')`，`COLLATE "C"`）。
-- ⚠️ Java 的末档是 `String.compareTo`（**逐字节**）⇒ 本文件用 `COLLATE "C"` 对齐，
--    避免在非 C collation 的库上选出与 Java **不同**的幸存行（同一张单迁移前后取到不同的价）。
--
-- ## ⚠️ 必须**先算幸存集**再动手（否则 `帘头制作` 的 ¥2.00 会**静默丢失**，#4696 家族）
-- 幸存判据的第 ① 档依赖 `applicable` 的**迁移前**取值。若先写 `applicable`（或先软删）再选行，
-- 信号就没了：`帘头制作` 的 3 格本是 `布帘 (NULL, FALSE)` / `纱帘 (NULL, FALSE)` / `帘头 (2.00, TRUE)`，
-- 抹掉第 ① 档后决胜落到 ② 档「布帘列优先」⇒ 幸存行 = `布帘 / NULL` = **未定价**
-- ⇒ 该工序的 ¥2.00 **静默消失**（工人白干，且与「显式 0 元」不可区分 —— 正是 #4696 的红线）。
-- ⇒ 本文件把幸存集**物化**成 `_v102_survivors`（`CREATE TEMP TABLE … ON COMMIT DROP`），
--    **写语句与收尾自证共用同一份**；真库判据 =
--    `tests/unit_ci_workflows/test_deposition_total_migration.py` 的
--    `test_survivor_keeps_the_priced_curtain_head_and_never_invents_a_price`（钉 `帘头制作 = 2.00`）。
--
-- ## 🔴 写语句顺序为什么**不会撞** `uk_production_operation_positions_tenant_name_position`
-- 该唯一索引是**部分索引**：`(tenant_id, logical_name, position) WHERE deleted = 0`。逐步论证：
--   · **② 软删**（`SET deleted = 1`）**不改 `position`** —— 它只是把行从**部分索引的成员集**里移除
--     ⇒ 移除成员**不可能**制造新的重复键（迁移前该索引成立 ⇒ 移除后仍成立）；
--   · **③ 改名**（幸存行 `position := '通用'`）跑在 ② **之后** ⇒ 此刻每个 `(tenant_id, logical_name)`
--     在 `deleted = 0` 集合里**恰好只剩一行**（② 已把其余全软删）⇒ 该行无论写成哪个 `position`，
--     都不可能撞上「同 `(tenant_id, logical_name)` 的另一行」—— 因为**那样一行不存在**；
--   · 反序（先改名再软删）则**不安全**：若某键下**已经存在**一格 `position = '通用'` 的存活行，
--     把幸存行也改名成 `通用` 的那一瞬间就会撞键。本文件**不用**那个顺序。
--   · ⚠️ 前提「每键恰有一个幸存行」由 ① 的 `ROW_NUMBER() … = 1` **结构性保证**
--     （`PARTITION BY tenant_id, logical_name` ⇒ 每个分区恰好产出一行）。
--
-- ## ② 补 4 道纱帘变体：为什么**两段**（字面量 + 派生回填），各自的存在理由
-- 病根：`buildRoute` 原来靠 `applicable` 的过滤把 `熨烫` / `定型` / `复烫` / `车被` 从**纱帘**路线上滤掉
-- （`V71` 种子里 `熨烫 × 纱帘` 是 `FALSE`）⇒ 库里**从来没有**建过这 4 道的纱帘变体；该过滤退场后
-- 这 4 道会进入纱帘路线的实例化路径，而 `variantNameOf("熨烫","纱帘",catalog)` 在库里找不到
-- `熨烫-纱` ⇒ 返回 `null` ⇒ 该道进 `missing_operations` ⇒ 调用方 **fail-closed（422）**
-- ⇒ **一张纱帘单也建不出来**（不是「少一行数据」，是把下单能力打掉）。
--   · **段 A（字面量 `VALUES`，1 号租户、带同一套闸门）**：
--     `test_production_catalog_seed.py` 的**多源收敛**守卫按**内容**发现
--     「含**工序表**的 `INSERT` 且形如 `VALUES` 字面量」的源 ⇒ 只留派生形态会让这 4 道
--     **落在比对射程之外**（「改了这 4 行的价而没有任何东西变红」）。
--     单价 0.35 / 0.40 / 0.35 / 0.40 **逐字**等于 `OPERATION_CATALOG` 与 `V54` 的 `-布` 行
--     （`熨烫-布` 0.35 / `定型-布` 0.40 / `复烫-布` 0.35 / `布帘车被` 0.40）—— **不是发明的值**。
--   · **段 B（派生回填，按租户循环）**：`V54` / `V56` / `V79` 的字面量种子**只种 1 号租户**
--     ⇒ 存量**非 1 号租户**拿不到这 4 行（`V91` 的基线回填**早于本文件**、不含这 4 行）
--     ⇒ 必须逐租户补。形态照 `V91__backfill_baseline_operations_for_empty_catalogs.sql`
--     （同一范式，不发明第二套）：`INSERT … SELECT … FROM tenants t CROSS JOIN (… UNION ALL …) AS r`。
--   · **命名规则**：`id = 'op-v102-' || <tenant_id> || '-' || <一位序号>`（序号 1..4）——
--     **自带租户段**（`id` 是按租户唯一的）、**不复用** 1 号租户既有的 id（那是 `V56` 的命名空间）。
--     段 A 的 1 号租户行同样走 `op-v102-1-1` … `op-v102-1-4`（**与派生段同一套命名规则**：
--     段 A 与段 B 是同一条规则的两个来源，不是两套命名）。
--   · **闸门（两段共用同一套判据）**：只对「**已存在 4 个对应 `-布` 变体**
--     （`熨烫-布` / `定型-布` / `复烫-布` / `布帘车被`）**且 4 个 `-纱` 全缺**」的**活跃租户**补
--     —— 前者 = 该租户的工序库确实有这套基线（**不无中生有**：空工序库或只有 1 个 `-布` 的租户
--     一行都不插，交给 `V91` 先补基线），后者 = **幂等闸**。
--   · `group_name` / `unit` / `scope` **与对应 `-布` 行对齐**（段 B 逐列取该行；段 A 的值与 `V54` 的
--     `-布` 行逐字相同）；`unit_price` **逐字取对应 `-布` 变体的价**（红线：**不发明单价**）；
--     `position` 用 `'纱帘'`（这是**工人端快照名**的部位标识，用户明确保留）。
--   · 🔴 **软删行永久不动**（红线）：闸门只数 `deleted = 0`，本文件**从不**写 `deleted = 0`
--     ⇒ 商家/历史软删的那一行**一字不动**（不会被「复活」）。
--     ⚠️ **已知边界（照实登记）**：某租户「4 行里有 1 行已被软删、其余 3 行在」⇒ 闸门整块跳过
--     而收尾对账判「4 不齐」⇒ **整份迁移回滚**（fail-loud：红在下一次 `verify-all` / 部署上，
--     而不是把该租户留成「纱帘单恒 422」的死状态）。补那一行的正确做法 = 新开一条单行
--     `NOT EXISTS` 迁移（不碰软删行），**不在本文件射程内**。
--   · ⚠️ **形态细节（两处实测踩过的坑）**：用 `UNION ALL SELECT` 而不是「派生表行值构造 /
--     CTE」—— 前者会被种子解析器误当种子行（连注释里都不能出现那个关键字），
--     后者会被「引用表存在性」守卫当成表名（`FROM <标识符>` 一律按表名解析）。
--
-- ## 红线：**不动历史 / 工资 / 对客账 / 部位维**
-- 本文件的 DML 只碰 **2 张配置表**：`production_operation_positions`（`position` / `applicable` /
-- `deleted` / `updated_at` 四列）与 `production_operations`（**只 `INSERT`**）。以下一律**一字不动**：
--   · `unit_price`（矩阵侧）—— 塌缩**只选行、不改价**（`V86` 的调价账按 `position_row_id` 指向矩阵行，
--     所以只能**软删**、**不许**物理删 —— 物理删会断审计链）；
--   · `production_route_rules`（**整张表**）—— 特别是 `position`（#4962 的部位维唯一载体，
--     用户明确保留）与 `customer_unit_price`（对客那本账，元/套）；
--   · 工序实例 `processing_position_operations`（含 `operation_name` 旧名快照）；
--   · 报工流水 `production_work_logs` 的 `unit_price` / `factor` ⇒ 历史工资不受影响
--     （工资按报工当时落库的值结算，**不**按矩阵当前价/当前适用性回算）；
--   · 加工单快照 `processing_orders.items_snapshot`；
--   · `production_operations.is_must_finish` 的**取值**（另一个在飞包正在为它写新迁移 ⇒ 本文件不碰）。
--
-- ## 幂等（`MigrationRunner` 硬要求所有迁移可重复执行）
--   · ① 幸存集**每次重算**：第一遍后每个 `(tenant_id, logical_name)` 只剩一行存活 ⇒ 它自己就是幸存行
--     （收敛到**不动点**）；
--   · ② 第二遍非幸存行 = 0 行（`deleted = 0` 的行全是幸存行）；
--   · ③ 第二遍匹配 0 行（`position IS DISTINCT FROM '通用' OR applicable IS DISTINCT FROM TRUE` 已不成立）；
--   · ④ / ⑤ 纱帘段：闸门②（4 个 `-纱` 全缺）在第一遍后不成立 ⇒ 两段都整块跳过；
--     另加逐行 `NOT EXISTS` + `ON CONFLICT (tenant_id, name) WHERE deleted = 0 DO NOTHING` 兜底；
--   · ⑥ 收尾自证全是**状态**判据（不读时间戳）⇒ 第二遍同样通过。
-- ⇒ 第二遍**净效果相同**（真库两遍读数见
--   `test_deposition_total_migration.py::test_migration_is_idempotent_and_collapses_to_one_row_per_logical_operation`）。
--
-- ## bootstrap 镜像（`docs/sql/schema.sql`）
-- 该文件是 `docker-entrypoint-initdb.d` 的**一次性建库脚本**（该栈**不跑迁移链**）⇒ 它必须**一次给全终态**：
--   · 矩阵段的 120 行字面量已是塌缩终态（存活 30 行 `通用` + `applicable = TRUE`，退场 90 行 `deleted = 1`）；
--   · 规则段那条 `韩褶 → insert 上车布` 的 `position` = `'布帘'`（与 `V71` 的字面量**逐字一致** ——
--     上一版当时按已被删除的 `V103` 镜像成了 `NULL`，本单恢复）。
-- 守卫 = `test_deposition_total_migration.py` 的
-- `test_bootstrap_matches_migration_chain_terminal_state`（真库跑本迁移 + 解析 `schema.sql` 逐值比对）。
--
-- ## 回滚 SQL（**新迁移，不删本文件**；语义 = 复活软删行 + 复原部位 + 撤掉 `-纱` 变体）
-- ⚠️ **必须先记下本迁移的执行时刻**（下面用 psql 变量 `:'v102_run_at'`；`MigrationRunner` 路径
--    请从 `schema_migrations` 该行的 `applied_at` 取值）—— 那是「哪些行是本迁移软删的」的**唯一**认领键
--    （`deleted = 1` 里还混着 `V88` / `V89` / `V97` 的**更早**退场记录，不能一律复活）。
-- ⚠️ **不可逆的部分（如实登记，只有两条）**：
--   · 幸存行原本的 `applicable`：只有当它原本是 `FALSE` / `NULL` 时不可复原（本迁移把它写成 `TRUE`）
--     —— 这只在「该键里一格 `TRUE` 都没有」时才会发生（第 ① 档优先 `IS TRUE`）；
--   · 幸存行原本的 `position`：在「该键不足 4 格」时无法机械复原（下面按 30 个逻辑工序 → 原部位的
--     **种子映射**复原，与 `V71` / `V79` 的种子字面量逐值同源）。
--   · **其余都没有丢**：非幸存行的 `applicable` / `unit_price` / `position` **一字未动**
--     （只翻了 `deleted`）⇒ 「哪一格当年是 `FALSE` / `NULL`」这一信息**完整保留**；
--     `production_route_rules` **本文件从未写过** ⇒ 该表**无需回滚**（部位维留在原地）。
-- ```sql
-- -- V107__rollback_deposition_total.sql（本单只登记，不落码）
-- BEGIN;
-- -- ① 复活**本迁移**软删的矩阵行（认领口径 = 本迁移的写入戳；V88/V89/V97 的更早退场记录不动）
-- UPDATE production_operation_positions p
--    SET deleted = 0, updated_at = NOW()
--  WHERE p.deleted = 1 AND p.updated_at >= :'v102_run_at';
-- -- ② 幸存行的 `position` 复原（`通用` → 原部位；值 = V71/V79 的种子字面量，30 条逐行同源）
-- UPDATE production_operation_positions p
--    SET position = m.position, updated_at = NOW()
--   FROM (SELECT v.logical_name, v.position
--           FROM jsonb_to_recordset('[{"logical_name":"精裁","position":"布帘"}, ...30 条...]')
--                AS v(logical_name TEXT, position TEXT)) AS m
--  WHERE p.logical_name = m.logical_name AND p.deleted = 0 AND p.position = '通用';
-- -- ③ 撤掉本迁移补的 4 道纱帘变体（按 **id 前缀**认领 —— 名字会随商家改名漂移，id 不会）
-- UPDATE production_operations o SET deleted = 1, updated_at = NOW()
--  WHERE o.deleted = 0 AND o.id LIKE 'op-v102-%';
-- COMMIT;
-- ```
-- ⚠️ ③ 用**软删**而不是 `DELETE`：这 4 行可能已被报工引用（`production_work_logs.operation_name`）。
-- ⚠️ 回滚后这些租户的纱帘单会**重新 fail-closed 422**（回到缺陷）—— 仅在确认业务可接受时执行。
--
-- ## 显式事务（同 `V91` / `V97` 的实测口径）
-- `MigrationRunner` 用 `jdbc.execute(整份文件)` ⇒ PG 隐式包一个事务；而 `psql -f` **默认逐条 autocommit**
-- ⇒ 不显式 `BEGIN/COMMIT` 时，前面的 UPDATE 已提交、后面的 DO 块才抛 ⇒ 留下**半完成态**。
-- 两条执行路径必须同语义 ⇒ 本文件**显式** `BEGIN; … COMMIT;`（这也是「失败 = 整体回滚」的载体）。

BEGIN;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ① 幸存集：**先算后动**，物化成一份共享结果（`CREATE TEMP TABLE … ON COMMIT DROP`）
-- ══════════════════════════════════════════════════════════════════════════════════════
-- 写成物化结果而不是在写语句与自证里各写一遍窗口函数：两处**共用同一份**判据 ⇒
-- 「判据漂移」不可能只漂一半。
-- ⚠️ 本块读的是 `applicable` 的**迁移前**取值 —— 所以它必须在 ② / ③ **之前**执行
--    （否则第 ① 档失效 ⇒ `帘头制作` 的 ¥2.00 静默丢失，见文件头的口径陷阱）。
CREATE TEMP TABLE _v102_survivors ON COMMIT DROP AS
SELECT ranked.id,
       ranked.tenant_id,
       ranked.logical_name
  FROM (
        SELECT p.id,
               p.tenant_id,
               p.logical_name,
               ROW_NUMBER() OVER (
                   PARTITION BY p.tenant_id, p.logical_name
                   -- ① 适用行优先 —— `(p.applicable IS TRUE)`：`FALSE` **与 `NULL` 都落 false**
                   --    （🔴 不得写成 `IS NOT FALSE`：那会把 NULL 放行 —— 上版的 NULL 口径错误）
                   ORDER BY (p.applicable IS TRUE) DESC,
                            (p.position = '布帘') DESC,                        -- ② 布帘列优先
                            COALESCE(p.position, '') COLLATE "C" ASC,          -- ③ position 字典序
                            COALESCE(p.id, '') COLLATE "C" ASC                 -- ④ id 升序（逐字节）
               ) AS rn
          FROM production_operation_positions p
         WHERE p.deleted = 0
       ) ranked
 WHERE ranked.rn = 1;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ② 非幸存行**软删**（`deleted = 1` + `updated_at`；**不物理删** —— V86 的调价账仍指向它们）
-- ══════════════════════════════════════════════════════════════════════════════════════
-- ⚠️ 显式写列（不回落 MyBatis-Plus 的 `updateById`：它的 NOT_NULL 策略会把逻辑删除字段
--    从 SET 子句剔除 ⇒ 静默 no-op）。
-- ⚠️ 原本就是 `deleted = 1` 的行（`V88` / `V89` / `V97` 的退场留痕）**不碰**。
-- 🔴 本语句**不改 `position`** ⇒ 从部分唯一索引的成员集里「移除」成员，不可能制造重复键（见文件头论证）。
UPDATE production_operation_positions p
   SET deleted = 1,
       updated_at = NOW()
 WHERE p.deleted = 0
   AND NOT EXISTS (SELECT 1 FROM _v102_survivors s WHERE s.id = p.id);

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ③ 幸存行：`position := '通用'`（中性值；该列**仅作历史载体**）+ `applicable := TRUE`
-- ══════════════════════════════════════════════════════════════════════════════════════
-- `unit_price` **一字不动**（塌缩只选行，不改价）。
-- 🔴 这里把 `applicable` 写成 `TRUE` 是**终态收敛**（含原本是 `FALSE` / `NULL` 的幸存行）——
--    它与「一刀切置 TRUE」**不是**同一件事：那个错误发生在**选行之前**（抹掉了选行信号），
--    本文件发生在**选行之后**（信号已被 `_v102_survivors` 物化固定）。
-- 🔴 执行顺序在 ② **之后** ⇒ 此刻每个 `(tenant_id, logical_name)` 在 `deleted = 0` 里只剩一行
--    ⇒ 改成 `'通用'` 不会撞部分唯一索引（见文件头论证）。
-- ⚠️ 加了 `IS DISTINCT FROM` 幂等闸：第二遍匹配 0 行（且 `NOW()` 在同事务内是常量）。
UPDATE production_operation_positions p
   SET position = '通用',
       applicable = TRUE,
       updated_at = NOW()
  FROM _v102_survivors s
 WHERE p.id = s.id
   AND p.deleted = 0
   AND (p.position IS DISTINCT FROM '通用' OR p.applicable IS DISTINCT FROM TRUE);

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ④ 纱帘变体**段 A**（**字面量种子**，1 号租户；**带同一套闸门**）
-- ══════════════════════════════════════════════════════════════════════════════════════
-- 为什么这一段必须存在（**不是冗余**）：多源收敛守卫按**内容**发现「含
-- 「含**工序表**的 `INSERT` 且形如 `VALUES` 字面量」的迁移源，并与 `OPERATION_CATALOG` /
-- `docs/sql/schema.sql` **逐行逐值**比对 ⇒ 只有派生形态会让这 4 道落在射程之外
-- （改价没有任何东西变红）。单价 0.35 / 0.40 / 0.35 / 0.40 **逐字**等于 `OPERATION_CATALOG`
-- 与 `V54` 的 `-布` 行，**不是发明的值**。
-- ⚠️ 用 `DO` 块包住并**复用同一套闸门**：这样它对「`-布` 不齐」的租户同样**一行都不插**
--    （不无中生有），也避免在租户表里没有 1 号租户时撞外键。
-- 🔴 **额外的「不发明单价」闸**：字面量形态只能写出**冻结的种子价**，所以段 A 还要求
--    1 号租户那 4 行 `-布` 变体的 `(name, group_name, unit, unit_price, scope)` **逐格等于**
--    下面的字面量元组 —— 商家改过其中任何一格，段 A 就整块跳过，**交给段 B**（段 B 逐列取
--    `-布` 行，永远与商家自己的价一致）⇒ 段 A 在任何情况下都不会「发明」一个单价。
DO $$
DECLARE
    ready BOOLEAN;
BEGIN
    SELECT (t.deleted = 0
            AND (SELECT count(*) FROM production_operations s
                  WHERE s.tenant_id = t.id AND s.deleted = 0
                    AND s.name IN ('熨烫-布', '定型-布', '复烫-布', '布帘车被')) = 4
            AND (SELECT count(*) FROM production_operations d
                  WHERE d.tenant_id = t.id AND d.deleted = 0
                    AND d.name IN ('熨烫-纱', '定型-纱', '复烫-纱', '车被-纱')) = 0
            -- 段 A 的字面量价必须与该租户自己的 `-布` 行逐格一致（否则跳过，交给段 B 派生）
            AND (SELECT count(*) FROM production_operations s
                  WHERE s.tenant_id = t.id AND s.deleted = 0
                    AND (s.name, s.group_name, s.unit, s.unit_price, s.scope) IN (
                          ('熨烫-布', '后道', '米', 0.35, 'position'),
                          ('定型-布', '后道', '米', 0.40, 'position'),
                          ('复烫-布', '后道', '米', 0.35, 'position'),
                          ('布帘车被', '后道', '米', 0.40, 'position'))) = 4)
      INTO ready
      FROM tenants t
     WHERE t.id = 1;

    IF COALESCE(ready, FALSE) THEN
        INSERT INTO production_operations
            (id, tenant_id, name, group_name, position, unit, unit_price,
             is_must_finish, is_start_marker, sort_order, scope, status, deleted)
        VALUES
          ('op-v102-1-1', 1, '熨烫-纱', '后道', '纱帘', '米', 0.35, FALSE, FALSE, 38, 'position', 'active', 0),
          ('op-v102-1-2', 1, '定型-纱', '后道', '纱帘', '米', 0.40, FALSE, FALSE, 39, 'position', 'active', 0),
          ('op-v102-1-3', 1, '复烫-纱', '后道', '纱帘', '米', 0.35, FALSE, FALSE, 40, 'position', 'active', 0),
          ('op-v102-1-4', 1, '车被-纱', '后道', '纱帘', '米', 0.40, FALSE, FALSE, 41, 'position', 'active', 0)
        ON CONFLICT (tenant_id, name) WHERE deleted = 0 DO NOTHING;
    END IF;
END $$;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ⑤ 纱帘变体**段 B**（**派生回填**，**按租户循环** —— 存量非 1 号租户的唯一来源）
-- ══════════════════════════════════════════════════════════════════════════════════════
-- 形态与 `V91__backfill_baseline_operations_for_empty_catalogs.sql` 同款：
-- **1 条 `INSERT … SELECT`**，4 行由 `CROSS JOIN (SELECT … UNION ALL …) AS r` 提供
-- （清单只写一份 ⇒ 闸门与收尾对账都不需要第二份名单）。
-- 🔴 `unit_price` / `group_name` / `unit` / `scope` **逐字取对应 `-布` 变体那一行**
--    （`JOIN production_operations s ON … s.name = r.cloth_name`）—— **不发明单价**，也不猜分组。
--    类型显式（`::numeric` / `::integer`，`V79` 的真库事故教训）：不写会被推断成 `text`，
--    而 `text → numeric` **不是赋值转换** ⇒ 整文件单事务回滚。
-- ⚠️ 逐行 `NOT EXISTS` 是**业务唯一键**去重（`ON CONFLICT` 兜底）；闸门②（4 个 `-纱` 全缺）是
--    **幂等闸**。两者都只数 `deleted = 0` ⇒ **软删行不会被复活**（红线）。
INSERT INTO production_operations
    (id, tenant_id, name, group_name, position, unit, unit_price,
     is_must_finish, is_start_marker, sort_order, scope, status, deleted)
SELECT 'op-v102-' || t.id::text || '-' || r.seq::text,
       t.id, r.sheer_name, s.group_name, '纱帘', s.unit, s.unit_price,
       FALSE, FALSE, r.sort_order, s.scope, 'active', 0
  FROM tenants t
  CROSS JOIN (
      -- 第一行带列别名（`UNION ALL` 的类型也由它钉住：`::numeric` / `::integer` 逐行显式）
      SELECT '熨烫-纱' AS sheer_name, '熨烫-布' AS cloth_name,
             38::integer AS sort_order, 1 AS seq
      UNION ALL SELECT '定型-纱', '定型-布', 39, 2
      UNION ALL SELECT '复烫-纱', '复烫-布', 40, 3
      UNION ALL SELECT '车被-纱', '布帘车被', 41, 4
  ) AS r
  JOIN production_operations s
    ON s.tenant_id = t.id AND s.name = r.cloth_name AND s.deleted = 0
 WHERE t.deleted = 0
   -- 闸门①：4 个 `-布` 变体**齐全**（不无中生有 —— 工序库从未种过的租户交给 V91）
   AND (SELECT count(*) FROM production_operations b
         WHERE b.tenant_id = t.id AND b.deleted = 0
           AND b.name IN ('熨烫-布', '定型-布', '复烫-布', '布帘车被')) = 4
   -- 闸门②（幂等）：4 个 `-纱` 变体**全缺**（按 `deleted = 0` 计，与收尾对账**同口径**）
   AND (SELECT count(*) FROM production_operations d
         WHERE d.tenant_id = t.id AND d.deleted = 0
           AND d.name IN ('熨烫-纱', '定型-纱', '复烫-纱', '车被-纱')) = 0
   -- 逐行去重（业务唯一键；`ON CONFLICT` 兜底）
   AND NOT EXISTS (SELECT 1 FROM production_operations e
                    WHERE e.tenant_id = t.id AND e.name = r.sheer_name AND e.deleted = 0)
ON CONFLICT (tenant_id, name) WHERE deleted = 0 DO NOTHING;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ⑥ 收尾自证（**全部是状态判据，零时间戳推断** —— 见文件头的「上版死因」第 1 条）
-- ══════════════════════════════════════════════════════════════════════════════════════
-- 这一块的**职责边界**：它只判「结果态是否收敛」。
-- 它**不**判「谁被改动过」—— 那正是上版的死因（按写入戳推断「本迁移越界」，与本次迁移无关）。
-- 失败即 `RAISE EXCEPTION` ⇒ 由 `BEGIN/COMMIT` **整体回滚**（原子）。
DO $$
DECLARE
    alive_rows      INTEGER;
    survivor_rows   INTEGER;
    multi_row       INTEGER;
    bad_position    INTEGER;
    bad_applicable  INTEGER;
    sheer_missing   INTEGER;
BEGIN
    -- 自证（防空跑，**由构造保证、不会误判**）：有存活矩阵行 ⇒ 幸存集必须非空。
    -- 反过来（空库）不抛 —— 「全库没有矩阵行」不是本迁移的失败。
    SELECT count(*) INTO alive_rows FROM production_operation_positions WHERE deleted = 0;
    SELECT count(*) INTO survivor_rows FROM _v102_survivors;
    IF alive_rows > 0 AND survivor_rows = 0 THEN
        RAISE EXCEPTION
            'V102 幸存集为空但库里仍有 % 条存活矩阵行（选行判据写岔了 ⇒ 后续 UPDATE 是空操作）'
            '—— 回滚本迁移', alive_rows;
    END IF;

    -- S1 塌缩收敛：**活跃行里不存在同一 `(tenant_id, logical_name)` 两行**（本迁移的核心终态）
    SELECT count(*) INTO multi_row
      FROM (SELECT p.tenant_id, p.logical_name
              FROM production_operation_positions p
             WHERE p.deleted = 0
             GROUP BY p.tenant_id, p.logical_name
            HAVING count(*) <> 1) bad;
    IF multi_row > 0 THEN
        RAISE EXCEPTION
            'V102 塌缩未收敛：% 个 (租户, 逻辑工序) 的存活行数 ≠ 1 —— 回滚本迁移', multi_row;
    END IF;

    -- S2 幸存行的 `position` 一律中性值「通用」
    SELECT count(*) INTO bad_position
      FROM production_operation_positions p
     WHERE p.deleted = 0 AND p.position IS DISTINCT FROM '通用';
    IF bad_position > 0 THEN
        RAISE EXCEPTION
            'V102 幸存行的 position 不是中性值「通用」（% 条）—— 回滚本迁移', bad_position;
    END IF;

    -- S3 存活行的 `applicable` 一律 `TRUE`（**含原本是 FALSE / NULL 的幸存行**）
    SELECT count(*) INTO bad_applicable
      FROM production_operation_positions p
     WHERE p.deleted = 0
       AND p.applicable IS NOT TRUE;
    IF bad_applicable > 0 THEN
        RAISE EXCEPTION
            'V102 终态核验失败：仍有 % 条存活矩阵行的 `applicable` 不是 TRUE —— 回滚本迁移',
            bad_applicable;
    END IF;

    -- S4 纱帘变体：**4 个 `-布` 齐全**的活跃租户必须 **4 个 `-纱` 齐全**（判据与 ⑤ 的闸门逐字同源）
    -- ⚠️ 判据写成「**四元组**计数」而不是「4 个 name 分开查（各 ≥1）」：后者在**部分补种**时会漏报
    --    （只补了 1 道也算「有」）⇒ 那正是「把该租户的下单能力打掉」的形态。
    -- ⚠️ 这里**不判** `production_route_rules.position`：部位维是**要保留**的终态
    --    （`V103` 的意图已作废，见文件头）⇒ 本文件对该表**没有任何判据**，也不该有。
    SELECT count(*) INTO sheer_missing
      FROM tenants t
     WHERE t.deleted = 0
       AND (SELECT count(*) FROM production_operations b
             WHERE b.tenant_id = t.id AND b.deleted = 0
               AND b.name IN ('熨烫-布', '定型-布', '复烫-布', '布帘车被')) = 4
       AND (SELECT count(DISTINCT a.name) FROM production_operations a
             WHERE a.tenant_id = t.id AND a.deleted = 0 AND a.status = 'active'
               AND a.name IN ('熨烫-纱', '定型-纱', '复烫-纱', '车被-纱')) <> 4;
    IF sheer_missing > 0 THEN
        RAISE EXCEPTION
            'V102 数量对账失败：仍有 % 个活跃租户「有 4 个 -布 变体但 4 个 -纱 变体不全」'
            '（该租户的纱帘单一律 422）—— 回滚本迁移', sheer_missing;
    END IF;
END $$;

COMMIT;
