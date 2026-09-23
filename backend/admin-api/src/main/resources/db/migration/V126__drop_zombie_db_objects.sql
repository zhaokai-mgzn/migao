-- DB 僵尸对象清理（删列 / 删表）+ V51 陈旧注释纠正 —— issue #5245 **A 组**
--
-- ## 一句话
-- 把「库里在、代码里早已没有消费者」的 3 列 + 3 张表**物理删掉**（用户裁定），
-- 并用 `COMMENT ON COLUMN` 纠正 V51 的一处**与代码事实相反**的注释
-- （V51 是已发布迁移、逐字节冻结 ⇒ 只能在新迁移里改 DB 注释，不能编辑它）。
--
-- ## 为什么是「僵尸」而不是「功能」——逐条给判据（每条都有三面证明，见下）
--
-- | # | 对象 | 形态 | 判据 |
-- |---|---|---|---|
-- | A1 | `processing_items.per_meter_quantity` | 列在、**生产零消费者** | V33 加列 → V34 删列 → V41 又把列加回；DTO / admin-web TS / Agent Python 的字段**确已全删**（无读无写）⇒ 列定义本身在暗示一个**已回滚**的口径（issue #3005）仍然成立 |
-- | A2 | `orders.stock_deducted` | 列在、零读取点 | V51/V53 头注释已写明它是**死列**；Java 实体无映射、两条 SQL 链无写点；扣库存真值源 = `stock_ledger` / `stock_batch_consumptions` |
-- | A3 | `orders.payment_status` | 列在、零读取点 | 无实体映射、无 DTO、无 Agent 参数；支付真值源 = 订单状态机 + `tenant_payment_qrcodes` |
-- | A4 | `production_option_routings` / `production_option_factors` | V73 **只软删行、表没删** | 规则真值源自 P2b（#4459）已收口到 `production_route_rules`；两张旧表只剩历史行 + **一个残留读点**（`RemnantService`，本单已改读新表 ⇒ 收口完成）。归档证据 = `V59__create_production_option_tables.sql` ∪ `V65`（逐字节冻结，**不动**） |
-- | A5 | `processing_rules` | 表在、**全仓 0 代码引用** | V68 头注释早已登记 `KNOWN-03`「表在、全仓 0 代码引用」；用户裁定**删表**。真值源是 `processing_fee_combinations`（V68）——把「组合」做成**计价**口径，与这张从未落码的「组合校验」表不是同一个概念 |
--
-- ## 三面证明（本单的验收口径：任一面加回去 ⇒ 红）
--
-- ① **建库脚本里不再有该对象**（`db/init/schema.sql`：无 `CREATE`、无种子 `INSERT`）；
-- ② **本迁移里有对应的幂等 `DROP`**（`IF EXISTS`）；
-- ③ **全仓生产源码零引用**（`backend/admin-api/src/main/java/**`、`backend/ai-agent-service/app/**`、
--    `frontend/admin-web/src/**`，注释剥离后）。
-- 机械判据 = `tests/unit_ci_workflows/test_dropped_db_objects.py`（每条判据各有注入式红证）。
--
-- ## 🔴 为什么必须有这一条（而不是「留着不用也无害」）
--
-- 本仓最贵的一类事故是「两份真相」：列/表还建着，于是任何人都能读出一个**看起来权威**的值，
-- 而它没有任何写点（永远是默认值）或没有任何读点（永远不被看见）。`production_option_*`
-- 更具体：V73 之后它们的活跃行 = 0，任何**仍按旧口径**写的代码都会静默读到空集
-- （实测形态 = `RemnantService.requiredItems()` 自 V73 起恒返回空 ⇒ 余料小件匹配**静默失效**）
-- —— 删表把「静默读空」变成**启动即报错**，那才是可发现的状态。
--
-- ## 幂等（判据 16）
--
-- 全部 `IF EXISTS`：重复执行是空操作；`COMMENT ON COLUMN` 是幂等覆盖写。整份文件 = 一个事务
-- （`MigrationRunner` 是 `jdbc.execute(整份文本)`），任一句失败即整份回滚且不记账。
--
-- ## 回滚 SQL（保留于注释；按需手工执行 —— 只恢复**结构**，不恢复数据）
--
-- ```sql
-- ALTER TABLE processing_items ADD COLUMN IF NOT EXISTS per_meter_quantity DECIMAL(6,2);
-- ALTER TABLE orders ADD COLUMN IF NOT EXISTS stock_deducted BOOLEAN DEFAULT FALSE;
-- ALTER TABLE orders ADD COLUMN IF NOT EXISTS payment_status VARCHAR(20) DEFAULT 'unpaid';
-- -- 两张旧规则表：结构在 V59（归档，逐字节冻结）里，按它重建即可；
-- -- 行数据在 V126 之前已由 V73 软删（deleted=1），物理删表后**行不再存在** ⇒ 回滚只回到空表。
-- ```
--
-- ## 与既有判据的关系（改判，不是放宽）
--
-- · `tests/unit_ci_workflows/test_migration_references_exist_in_schema.py`：本迁移只做
--   `DROP TABLE` / `DROP COLUMN` / `COMMENT ON COLUMN`，**不引用**任何已删对象；
--   那四条判据新学会「被后续迁移 DROP/RENAME 掉的表不是终态要求」（**豁免清单因此缩短**）。
-- · `tests/unit_ci_workflows/test_routing_model_p2_consumers.py` 的 C 段语义**变强**：
--   「旧规则表已退役 / 无读」→「旧规则表**已不存在** + 实体/Mapper 已删 + 全仓零读」。
-- · `tests/unit_ci_workflows/test_production_catalog_seed.py`：两张旧表的**终态面**随风化，
--   迁移侧的归档载体（V59 ∪ V65）仍与真值源逐行逐值比对（收敛面显式缩小并写明理由）。

-- ══════════════════════════════════════════════════════════════════════════════════
-- A1：`processing_items.per_meter_quantity`（僵尸列）
-- ══════════════════════════════════════════════════════════════════════════════════
ALTER TABLE processing_items DROP COLUMN IF EXISTS per_meter_quantity;

-- ══════════════════════════════════════════════════════════════════════════════════
-- A2 / A3：`orders.stock_deducted` / `orders.payment_status`（零引用死列）
-- ══════════════════════════════════════════════════════════════════════════════════
ALTER TABLE orders DROP COLUMN IF EXISTS stock_deducted;
ALTER TABLE orders DROP COLUMN IF EXISTS payment_status;

-- ══════════════════════════════════════════════════════════════════════════════════
-- A4：`production_option_routings` / `production_option_factors`（V73 只软删行）
-- ══════════════════════════════════════════════════════════════════════════════════
-- 顺序无关（两表之间无外键）；索引 / RLS 策略随 `DROP TABLE` 一并消失。
-- ⚠️ 先删 `production_option_factors`：V72/V76 的等价回填段读它（那些是已发布迁移，
-- 各自整份跳过；本迁移**不**读任何已删对象，故顺序只影响可读性）。
DROP TABLE IF EXISTS production_option_factors;
DROP TABLE IF EXISTS production_option_routings;

-- ══════════════════════════════════════════════════════════════════════════════════
-- A5：`processing_rules`（全仓 0 代码引用；用户裁定删表）
-- ══════════════════════════════════════════════════════════════════════════════════
DROP TABLE IF EXISTS processing_rules;

-- ══════════════════════════════════════════════════════════════════════════════════
-- C1：V51 陈旧注释纠正 —— `products.stock_warning_threshold` / `stock_deduction_mode`
-- ══════════════════════════════════════════════════════════════════════════════════
-- 🔴 V51（`V51__product_stock_single_authority.sql`）的注释称这两列「无消费方」——
-- **与代码事实相反**。V51 是**已发布迁移**（逐字节冻结，改它必红且存量环境拿不到）
-- ⇒ 纠正只能落在**新迁移**的 `COMMENT ON COLUMN` 上（DB 注释是可被 `\d+` 看到的真值面）。
-- **两列都不删**（删了商品页崩）：
--   · `stock_warning_threshold` ← `Product.stockWarningThreshold` + `ProductResponse.stockWarningThreshold`
--     ⇒ admin-web 商品表/详情页用它判「库存低于阈值标红」；
--   · `stock_deduction_mode` ← `Product.stockDeductionMode` + `ProductResponse.stockDeductionMode`
--     ⇒ admin-web 商品详情/编辑页把它映射成 on_place / on_pay 文案。
COMMENT ON COLUMN products.stock_warning_threshold IS
    '库存预警阈值。⚠️ V51 的旧注释称本列「无消费方」——**为假**（issue #5245 C1 纠正）：'
    '本列被 admin-web 的商品表与商品详情页真实读取（Java / TS 两侧字段名均为 stockWarningThreshold）。'
    '列**不得删**（删了商品页库存标红即失效）。';
COMMENT ON COLUMN products.stock_deduction_mode IS
    '库存扣减模式: on_order / on_payment。⚠️ V51 的旧注释称本列「无消费方」——**为假**'
    '（issue #5245 C1 纠正）：本列被 admin-web 商品详情页 / 编辑页真实读取（Java / TS 两侧字段名均为 '
    'stockDeductionMode，页面映射为 on_place / on_pay 文案）。列**不得删**。';