-- 商品模型改造（用户裁定 2026-09-21，逐字）：
--   「商品需要增加 1 卷=多少米，作为**商品货号的基础参数**，商品的售卖方式**整卷/散件不能作为 SKU 的组合项**，
--     只能作为**基础属性**，商品的 SKU 由**颜色+门幅**组成即可，在订单中再体现**客户要求优先整卷发货**，
--     例子：客户买 100 米布，一卷=60 米，那就发 1 整卷 60 + 散剪出的 40 米」
--
-- ## 一句话
--   ① `products` 追加 `selling_methods`（基础属性：该货号**支持**哪些售卖方式）
--      与 `roll_length_m`（**1 卷 = 多少米**，货号级基础参数）；
--   ② `product_skus` **删掉 `selling_method` 列**，唯一键收窄为 `(product_id, color_id, door_width)`
--      ⇒ SKU 组合只剩 **颜色 + 门幅**；
--   ③ `order_items` 追加三列，让「客户要求优先整卷发货」及其**分配结果**落在订单行上。
--
-- ## 为什么售卖方式必须是**商品级**而不是 SKU 级（缺陷形态）
-- 旧模型 `UNIQUE(product_id, color_id, selling_method, door_width)` 把售卖方式当**组合维度** ⇒
-- 同一颜色同一门幅被迫存两行 SKU（散剪一行、整卷一行），两行的价格/库存各自漂移，
-- 而「这卷布到底能不能整卷卖」其实是**货号级**事实（同一批布不会只有 2.8 门幅能整卷）。
-- 实证形态：`backend/ai-agent-service/app/tools/order_create.py` 的 SKU 定位键族里
-- `colorId+sellingMethod+doorWidth` 是**必要**的一环 —— 少传 `sellingMethod` 就定位不到 SKU、
-- 库存扣减链路直接失败（C 端顾客说「散剪」还得先被归一化成枚举才能下单）。
-- 收窄后定位键族退化为 `colorId+doorWidth`（见同批 Java/Python 改动）。
--
-- ## 为什么 `roll_length_m` 可空、且**不给默认值**
-- 行业卷长是**区间值**不是定值（调研见 `docs/curtain-selling-method-industry-research.md` §5：
-- 「一卷 60 米**左右**」）⇒ 商家不填时系统**不得**编一个卷长去算整卷分配。
-- NULL = **未知**（口径同 V100 的「未传 ⇒ NULL，服务端不猜」）⇒ 分配逻辑必须显式处理未知分支。
--
-- ## 为什么订单侧要落「分配结果」而不是只落偏好
-- 「优先整卷发货」只有在**算出**「几整卷 + 剩多少米散剪」之后才是可执行的（仓库/裁床照它拣货）。
-- 分配是 `quantity` 与 `roll_length_m` 的**确定性函数** ⇒ 落库才能被加工单/发货单引用，
-- 也才能让「同一次下单，重算结果不变」可被断言（只存偏好则每次读都要重算，且卷长改动会让历史单漂移）。
-- 三列全部 nullable：`roll_length_m IS NULL`（货号未配卷长）或顾客未要求整卷时**不写**（保持 NULL 真值）。
--
-- ## 幂等（`MigrationRunner` 硬要求所有迁移可重复执行）
--   · 列：`ADD COLUMN IF NOT EXISTS` + `DROP COLUMN IF EXISTS` + 覆盖式 `COMMENT ON COLUMN`；
--   · 约束：`DROP CONSTRAINT IF EXISTS` + 「不存在才 ADD」（`pg_constraint` 判据）；
--   · 回填：`UPDATE ... WHERE <目标态不成立>`（第二遍匹配 0 行）；
--   · 去重：`DELETE ... USING` 自连接（第二遍无重复行 ⇒ 匹配 0 行）；
--   · 文末 `DO` 块**终态对账**两遍都成立（既是幂等自证，也是判据漂移的停止条件）。
--
-- ## 顺序（不可交换，逐条都有理由）
--   ① 先**回填** `products.selling_methods`（此时 SKU 列还在，能从旧数据取真值）；
--   ② 再**去重** `product_skus`（新唯一键要求 `(product,color,door_width)` 唯一）；
--   ③ 最后才 `DROP COLUMN selling_method` + `ADD CONSTRAINT`（顺序颠倒 ⇒ 回填丢失真值 / 建约束失败）。
--
-- ## 存量行（如实登记，不粉饰）
--   · `products.selling_methods` 回填自该货号 SKU 里出现过的**去重值集合**；一个 SKU 都没有的货号
--     回填 `["bulk_cut","full_roll"]`（= 两种都支持，最宽口径，不误禁商家已有的售卖方式）；
--   · 去重时保留**价格最低**的那一行（同色同门幅的两行是同一物理规格，取低价行 = 不把顾客的
--     可售价格抬高），同价时保留 `id` 最小的一行（确定性，两遍结果一致）；
--   · **被删掉的那一行里独有的信息（另一档价格）在库里消失** —— 这是本迁移的**有损项**，见回滚段。
--
-- ## 回滚（**新迁移，不删本文件**）
-- ```sql
-- -- V109__rollback_product_roll_length_and_selling_method.sql（本单只登记，不落码）
-- -- ALTER TABLE order_items DROP COLUMN IF EXISTS selling_method;
-- -- ALTER TABLE order_items DROP COLUMN IF EXISTS roll_count;
-- -- ALTER TABLE order_items DROP COLUMN IF EXISTS roll_length_m;
-- -- ALTER TABLE products    DROP COLUMN IF EXISTS selling_methods;
-- -- ALTER TABLE products    DROP COLUMN IF EXISTS roll_length_m;
-- -- ALTER TABLE product_skus ADD COLUMN IF NOT EXISTS selling_method VARCHAR(20);
-- -- UPDATE product_skus SET selling_method = 'bulk_cut' WHERE selling_method IS NULL;
-- -- ALTER TABLE product_skus ALTER COLUMN selling_method SET NOT NULL;
-- -- ALTER TABLE product_skus DROP CONSTRAINT IF EXISTS uq_product_skus_combination;
-- -- ALTER TABLE product_skus ADD CONSTRAINT uq_product_skus_combination
-- --     UNIQUE (product_id, color_id, selling_method, door_width);
-- ```
-- **回滚是有损的**（不可复原项）：被去重删掉的 SKU 行**回不来**（只有 id/价格/库存被丢弃，
-- 无法从剩余行还原），故回滚后每个 (颜色,门幅) 只有**一个** `selling_method='bulk_cut'` 行 ——
-- 「整卷」档的 SKU 需要商家重新录。这与「售卖方式本就不该是 SKU 维度」的终态一致，属**有意**。
--
-- ## bootstrap 终态同步（同 V99/V100 纪律）
-- `docs/sql/schema.sql`（新建库路径**不跑迁移链**）已同步本文件终态。
--
-- ## 停止条件（fail-closed）
--   ① `products` / `product_skus` / `order_items` 任一不存在 ⇒ 迁移失败并停下（不 CREATE TABLE 兜底）；
--   ② 终态对账报「`product_skus` 仍有 `selling_method` 列」/「新唯一键缺失」/「仍有重复组合」
--      ⇒ 写语句判据漂移或被部分回滚 ⇒ 回滚本迁移，不硬推。
--
-- ## 显式事务（同 V97 / V102 / V107 的实测口径）
-- `MigrationRunner` 用 `jdbc.execute(整份文件)` ⇒ PG 隐式包一个事务；而 `psql -f` **默认逐条
-- autocommit** ⇒ 不显式 `BEGIN/COMMIT` 时，中间步骤已提交、`DO` 块才抛 ⇒ 留下**半完成态**。
-- 两条执行路径必须同语义 ⇒ 本文件**显式** `BEGIN; … COMMIT;`。

BEGIN;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ① 表存在性（fail-closed：缺表立即停，不兜底建表）
-- ══════════════════════════════════════════════════════════════════════════════════════
DO $$
DECLARE
    missing TEXT;
BEGIN
    SELECT string_agg(t, ', ') INTO missing
      FROM (VALUES ('products'), ('product_skus'), ('order_items')) AS v(t)
     WHERE NOT EXISTS (SELECT 1 FROM information_schema.tables
                        WHERE table_schema = 'public' AND table_name = v.t);
    IF missing IS NOT NULL THEN
        RAISE EXCEPTION 'V112 前置表缺失：% —— 不兜底建表（会造出无外键/无索引的影子表），迁移停下', missing;
    END IF;
END $$;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ② `products`：售卖方式（基础属性）+ 1 卷多少米（货号级基础参数）
-- ══════════════════════════════════════════════════════════════════════════════════════
ALTER TABLE products
    ADD COLUMN IF NOT EXISTS selling_methods JSONB DEFAULT '["bulk_cut", "full_roll"]'::jsonb;

ALTER TABLE products
    ADD COLUMN IF NOT EXISTS roll_length_m NUMERIC(8,2);

-- 回填：从该货号 SKU 里**真实出现过**的售卖方式取值（此时 SKU 列还在 —— 这是本迁移里
-- 唯一能取到该真值的时点）。一个 SKU 都没有的货号保持列默认（两种都支持，最宽口径）。
--
-- 🔴 **必须归一化到库内枚举**（本单复核抓到，形态是**越界 422 误伤存量商品**）：
-- 真库存量 `product_skus.selling_method` 是**混合写法**（取证：`.github/cases/processing-order.yml`
-- 记「真库 11 个取值 `bulk_cut`/`散剪`/`full_roll`/`整卷`/…」）—— 中文字面与英文枚举**并存**。
-- 若原样回填，一个货号可能拿到 `["full_roll","整卷"]`（同一档出现两次），而订单侧
-- `OrderService.assertSellingMethodSupported` 是「归一化后逐项相等」⇒ 顾客传「整卷」会被判
-- **越界**并 422（服务端明明支持整卷）⇒ 误伤存量商品。
-- ⇒ 回填时按与 `SkuNotation.normalizeSellingMethod` **同一套映射**归一（中文字面 → 枚举），
-- `DISTINCT` 自然把同一档合并成一条。**未在映射表里的历史取值原样保留**（宁可留着让商家在
-- 商品页重配，也不静默丢弃一种真实存在过的售卖方式）。
--
-- 🔴 **本表没有 `deleted` 列，回填**不得**加 `AND deleted = 0`**（独立对抗式复核实测抓到）：
-- `product_skus` 全仓从未有过软删列（`docs/sql/schema.sql` 的 `CREATE TABLE product_skus` 无该列、
-- 迁移链无 `ALTER TABLE product_skus ADD COLUMN deleted`、`ProductSku` 无 `@TableLogic`，
-- 删除走 `deleteById` = **物理删除**）。写了它 ⇒ 真库抛「字段 "deleted" 不存在」⇒ 整份迁移回滚，
-- 而 `MigrationRunner` 对非连接类失败是**跳过并继续**（只打一行 ERROR、不写 `schema_migrations`）
-- ⇒ **部署 success、三列永不建、每次重启重试**（issue #4402 的同族形态）。
-- ⚠️ 本单第一版的**测试夹具自己给该表加了 `deleted`** ⇒ 夹具把真缺陷挡掉了（真库判据全绿）。
-- 夹具现已改为照真 schema（见 `tests/unit_ci_workflows/test_product_roll_length_migration.py`
-- 的 `_DDL` 注释「不得加 deleted」）。
--
-- 🔴 **幂等闸必须在「列还在吗」这一层，不能只靠 `WHERE selling_methods IS DISTINCT FROM …`**
-- （本单真库两遍实测抓到，形态是**第二遍整份迁移报错**而不是静默 no-op）：
-- 本文件**自己**会在第 ③ 段把 `product_skus.selling_method` DROP 掉 ⇒ 第二遍执行时这条
-- `UPDATE ... FROM (SELECT … selling_method …)` 引用的列**已不存在** ⇒ PG 抛
-- 「字段 "selling_method" 不存在」⇒ 整份迁移回滚。而 `MigrationRunner` **硬要求所有迁移可重复执行**。
-- ⇒ 判据改成「先问列在不在，在才回填」（`EXECUTE` 动态 SQL：静态 SQL 在解析期就会报缺列，
-- 只有动态 SQL 才能让「列不存在」这条路径真的走通）。
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'product_skus'
                  AND column_name = 'selling_method') THEN
        EXECUTE $backfill$
            UPDATE products p
               SET selling_methods = agg.methods,
                   updated_at      = NOW()
              FROM (
                    SELECT product_id,
                           to_jsonb(array_agg(DISTINCT
                               CASE selling_method
                                   WHEN '散剪' THEN 'bulk_cut'
                                   WHEN '整卷' THEN 'full_roll'
                                   WHEN '按片' THEN 'per_piece'
                                   WHEN '定高' THEN 'fixed_height'
                                   WHEN '买通' THEN 'buy_through'
                                   ELSE selling_method
                               END
                               ORDER BY CASE selling_method
                                   WHEN '散剪' THEN 'bulk_cut'
                                   WHEN '整卷' THEN 'full_roll'
                                   WHEN '按片' THEN 'per_piece'
                                   WHEN '定高' THEN 'fixed_height'
                                   WHEN '买通' THEN 'buy_through'
                                   ELSE selling_method
                               END)) AS methods
                      FROM product_skus
                     WHERE selling_method IS NOT NULL
                     GROUP BY product_id
                   ) AS agg
             WHERE p.id = agg.product_id
               AND p.selling_methods IS DISTINCT FROM agg.methods
        $backfill$;
    END IF;
END $$;

-- 存量 NULL 收敛为默认（`ADD COLUMN` 对**已存在**的列不会施加 DEFAULT ⇒ 早于本迁移建的表
-- 可能已有该列且全 NULL；本句让「NULL 表示未设置」这个第三态不存在）。
-- 本句天然幂等（第二遍匹配 0 行）。
UPDATE products
   SET selling_methods = '["bulk_cut", "full_roll"]'::jsonb,
       updated_at      = NOW()
 WHERE selling_methods IS NULL;

COMMENT ON COLUMN products.selling_methods IS
    '售卖方式基础属性（商品级，非 SKU 组合维度）：该货号支持哪些售卖方式，取值 bulk_cut(散剪) / full_roll(整卷) 的 JSONB 数组。用户裁定 2026-09-21「售卖方式整卷/散件不能作为 SKU 的组合项，只能作为基础属性」；SKU 组合只有 颜色×门幅（V112）';

COMMENT ON COLUMN products.roll_length_m IS
    '1 卷 = 多少米（**商品货号级基础参数**）。NULL = 未配置/未知 ⇒ 订单侧**禁止**推算整卷分配（行业卷长是区间值，不得编造，见 docs/curtain-selling-method-industry-research.md §5）。有值时订单行按「优先整卷发货」算 roll_count + 散剪余量（V112）';

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ③ `product_skus`：去掉售卖方式维度 —— 先**去重**，再删列，最后收窄唯一键
-- ══════════════════════════════════════════════════════════════════════════════════════
-- 旧唯一键 (product_id, color_id, selling_method, door_width) 允许同色同门幅存在两行
-- （散剪一行 / 整卷一行）。新唯一键只认 (product_id, color_id, door_width) ⇒ 必须先去重，
-- 否则 `ADD CONSTRAINT` 当场失败（那会让整份迁移回滚 —— 属**正确**的 fail-closed，
-- 但迁移自己就该把存量收敛干净，不把失败留给部署）。
--
-- 保留规则：价格最低优先（同色同门幅是**同一物理规格**，取低价行 = 不抬高顾客可售价），
-- 同价时取 id 最小（确定性 —— 两遍执行保留同一行，幂等可断言）。
DELETE FROM product_skus victim
 USING product_skus keeper
 WHERE victim.product_id IS NOT DISTINCT FROM keeper.product_id
   AND victim.color_id  IS NOT DISTINCT FROM keeper.color_id
   AND victim.door_width = keeper.door_width
   AND (   COALESCE(victim.price, 0) > COALESCE(keeper.price, 0)
        OR (COALESCE(victim.price, 0) = COALESCE(keeper.price, 0) AND victim.id > keeper.id));

-- 旧约束先摘（`IF EXISTS`：本句必须能重复执行）。
-- ⚠️ 这里**有意**无条件 DROP 同名约束：存量库里那个名字上的定义就是**旧四维**
-- （`product_id, color_id, selling_method, door_width`），必须摘掉才能建两维；
-- 而第二遍执行时它已经是**正确的两维**、再摘再建虽无副作用（`ADD` 会重建同一个索引），
-- 但白付一次「重建唯一索引」的代价（大表上是全表扫描 + 排他锁）⇒ 下面用「定义对不对」判据
-- 把**建**这一步做成幂等：对 ⇒ 不重建；不对 ⇒ **抛异常**（不静默跳过，见下）。
ALTER TABLE product_skus DROP CONSTRAINT IF EXISTS uq_product_skus_combination;

ALTER TABLE product_skus DROP COLUMN IF EXISTS selling_method;

-- 新唯一键（两维）：判据是「**定义对不对**」，不是「存在与否」。
--
-- 🔴 为什么不能只判「存在与否」（本单注入式红证实测抓到）：若同名约束**已存在但列清单不对**
-- （例如手工/旧脚本建成了 `(product_id, color_id, door_width, tenant_id)`），
-- 只判存在会**静默跳过** ⇒ 库里留着一个错误的唯一键，而整份迁移「成功」。
-- ⇒ 对 ⇒ 跳过（幂等）；不对 ⇒ 抛异常回滚（fail-closed，不静默）。
DO $$
DECLARE
    current_def TEXT;
BEGIN
    SELECT pg_get_constraintdef(oid) INTO current_def
      FROM pg_constraint
     WHERE conname = 'uq_product_skus_combination'
       AND conrelid = 'product_skus'::regclass;

    IF current_def IS NULL THEN
        ALTER TABLE product_skus
            ADD CONSTRAINT uq_product_skus_combination
            UNIQUE (product_id, color_id, door_width);
    ELSIF substring(current_def FROM '\((.*)\)') IS DISTINCT FROM 'product_id, color_id, door_width' THEN
        RAISE EXCEPTION 'V112 前置对账失败：已存在的 uq_product_skus_combination 列清单不是「product_id, color_id, door_width」，实际 = % —— 不静默跳过（那会留下一个错误的唯一键）—— 回滚本迁移', current_def;
    END IF;
END $$;

COMMENT ON TABLE product_skus IS
    'SKU矩阵表，组合 = 颜色 × 门幅（**仅此二维**）。售卖方式是商品级基础属性 products.selling_methods，不是 SKU 组合维度（用户裁定 2026-09-21，V112）';

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ④ `order_items`：「客户要求优先整卷发货」+ 分配结果
-- ══════════════════════════════════════════════════════════════════════════════════════
ALTER TABLE order_items
    ADD COLUMN IF NOT EXISTS selling_method VARCHAR(20);

ALTER TABLE order_items
    ADD COLUMN IF NOT EXISTS roll_count INTEGER;

ALTER TABLE order_items
    ADD COLUMN IF NOT EXISTS roll_length_m NUMERIC(8,2);

COMMENT ON COLUMN order_items.selling_method IS
    '本行售卖方式：bulk_cut(散剪) / full_roll(整卷)。**订单级偏好**（顾客要求），不是 SKU 维度；NULL = 下单未指定（不猜）。校验口径 = 必须属于该货号 products.selling_methods';

COMMENT ON COLUMN order_items.roll_length_m IS
    '下单时该货号的「1 卷 = 多少米」快照（products.roll_length_m 的当时值）。订单是快照不是视图 ⇒ 货号后来改卷长不改变历史单的分配口径。NULL = 当时未配卷长';

COMMENT ON COLUMN order_items.roll_count IS
    '优先整卷发货时发出的**整卷数**（= floor(quantity / roll_length_m)）。用户裁定 2026-09-21 例：买 100 米、一卷 60 米 ⇒ roll_count=1、整卷 60 米 + 散剪 40 米。NULL = 未要求整卷或货号未配卷长（禁止推算）';

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ⑤ 终态对账（**两遍都必须成立** ⇒ 既是幂等自证，也是「判据漂移」的停止条件）
-- ══════════════════════════════════════════════════════════════════════════════════════
DO $$
DECLARE
    n            INTEGER;
    constraint_def TEXT;
BEGIN
    -- ① 红线：product_skus 不得再有 selling_method 列（它是本迁移要退场的那一维）
    SELECT count(*) INTO n
      FROM information_schema.columns
     WHERE table_schema = 'public' AND table_name = 'product_skus'
       AND column_name = 'selling_method';
    IF n > 0 THEN
        RAISE EXCEPTION 'V112 红线被破：product_skus.selling_method 列仍在 —— 售卖方式必须是商品级基础属性，不得留在 SKU 组合里 —— 回滚本迁移';
    END IF;

    -- ② 新唯一键必须在，且**恰好**是 (product_id, color_id, door_width) 三列
    -- ⚠️ 判据**不能**写成 `constraint_def LIKE '%(product_id, color_id, door_width)%'`：
    --    那是子串匹配，`UNIQUE (product_id, color_id, door_width, tenant_id)`（多一列）**照样命中**
    --    ⇒ 判据没有判别力（本单注入式红证实测抓到）。必须把列清单**整段取出来逐字比**。
    SELECT pg_get_constraintdef(oid) INTO constraint_def
      FROM pg_constraint
     WHERE conname = 'uq_product_skus_combination'
       AND conrelid = 'product_skus'::regclass;
    IF constraint_def IS NULL THEN
        RAISE EXCEPTION 'V112 终态对账失败：uq_product_skus_combination 约束不存在 —— 回滚本迁移';
    END IF;
    IF substring(constraint_def FROM '\((.*)\)') IS DISTINCT FROM 'product_id, color_id, door_width' THEN
        RAISE EXCEPTION 'V112 终态对账失败：唯一键列清单不是「product_id, color_id, door_width」，实际 = % —— 回滚本迁移', constraint_def;
    END IF;

    -- ③ 去重必须收敛：不得再有同 (product,color,door_width) 的重复行
    SELECT count(*) INTO n
      FROM (SELECT 1 FROM product_skus
             GROUP BY product_id, color_id, door_width
            HAVING count(*) > 1) AS dup;
    IF n > 0 THEN
        RAISE EXCEPTION 'V112 终态对账失败：仍有 % 组重复的 (product_id, color_id, door_width) SKU —— 回滚本迁移', n;
    END IF;

    -- ④ products.selling_methods 不得有 NULL（「未设置」这一态在本列不存在）
    SELECT count(*) INTO n FROM products WHERE selling_methods IS NULL;
    IF n > 0 THEN
        RAISE EXCEPTION 'V112 终态对账失败：仍有 % 个商品的 selling_methods 为 NULL —— 回滚本迁移', n;
    END IF;
END $$;

COMMIT;
