-- 「韩折」→「韩褶」统一 —— 加工项目录名 + 加工费组合名/键（2026-09-28 用户裁定）
--
-- ## 用户裁定（原文，2026-09-28）
--   「成品帘行默认带 韩褶 + 定型，**把加工项和加工费组合里面叫韩折的都改成韩褶**」
--   （同一轮的上一条：「订单这里的布局得优化，正常用户提供净窗高/窗宽，然后再确认是否要韩折/打孔
--     定型等信息即可，其他信息尽量推导」）
--   ⚠️ 用户在更早的裁定里一直写的是 **韩褶**（逐字例：V68 头部引的 2026-09-19「选**韩褶 + 打孔**
--   是一种收费」；`fabric-calc.formula-selection` 的「默认用韩折的」是口语转写）。⇒ 本次是
--   **用户口径收口**：目录名与组合名统一到「韩褶」。
--
-- ## 一句话
-- 目录里那一项（V83 第 02 项：名字照 ERP 附件写「韩折」、`craft_hint` 已是「韩褶」）**改名为「韩褶」**；
-- 存量**加工费组合**（`processing_fee_combinations`）里作为组合成员的「韩折」**一并替换**，
-- 并把 `items` 规范化（去重 + **码点升序**）+ **重算 `composition_key`**。
--
-- ## 🔴 为什么组合价必须跟着改（本迁移唯一碰钱的地方，显式登记）
--   组合键的真值源 = `processingItems[].name`（V68 头部 + `ProcessingFeeCombinationCommandService
--   .compositionKey`：trim → 丢空 → 去重 → **Unicode 码点升序** → `+` 连接）。
--   只改目录名不改组合行 ⇒ 新单算出 `定型+韩褶`、库里存的仍是 `定型+韩折` ⇒ 一条都匹配不上
--   ⇒ `fee_source=unpriced`（有提示、不静默，但等于把**每个**组合价都变成未定价）。
--   ⇒ 本迁移**必须**一起改：**改的是同一笔钱的键**（`unit_price` / `status` / `sort_order` /
--   `source` / `id` **一字不动**，**不改价**）。
--
-- ## 排序口径：显式 `COLLATE "C"`（不是可选优化，是正确性）
--   ⚠️ **写法**：必须 `SELECT DISTINCT (<expr>) COLLATE "C" AS nm … ORDER BY 1` ——
--   `ORDER BY 1 COLLATE "C"` 会被 PG 解析成「整数 1 加排序规则」，当场报
--   `类型integer不能使用排序规则`（PG 16.15 实测）；而 `MigrationRunner` 对非连接类失败是
--   「记一条日志、跳过继续」⇒ **部署照样 success，改名等于没发生**（V102 那批的形态）。

--   Java 侧 `compositionKey()` 用 `TreeSet<String>` = **UTF-16 自然序**（BMP 内 = 码点序）；
--   而库**默认排序规则**会把中文按 locale 序排 ⇒ **两者结果不同**（本机实测 `zh_CN.UTF-8`：
--   `打孔/定型/韩褶`，而码点序是 `定型/打孔/韩褶`；判据 = V139 的真库用例用 `COLLATE "C"` 独立复算逐行比）。
--   本迁移一律 `ORDER BY … COLLATE "C"`（UTF-8 字节序 = 码点序）⇒ 与 Java 逐字一致；
--   否则「迁移写出的键」与「商家在页面上再保存一次得到的键」会是两个 ⇒ 同一组合两行价。
--
-- ## 幂等（`MigrationRunner` 硬要求所有迁移可重复执行）
--   两条 UPDATE 的谓词都含**旧名**（`name = '韩折'` / `items @> '["韩折"]'`）⇒ 第二遍匹配 0 行，
--   净效果相同。故**不能**用「认领 0 行 ⇒ 抛异常」的空跑自证：由文末**终态对账**承担
--   （它两遍都成立，而「只改了一部分 / 谓词写歪」会让它当场抛并整份回滚）。
--
-- ## 🔴 红线（本迁移**只写**这两张表的这几列）
--   · `processing_items`：`name` / `updated_at`；
--   · `processing_fee_combinations`：`items` / `composition_key` / `updated_at`；
--   · **不动** `order_items.processing_info`（已成交订单的加工项快照）—— 历史单据仍显示当时的
--     「韩折」，那是**当时的**事实（快照不可改写，与本仓「快照 = 冻结事实」的口径一致）；
--   · **不动** `processing_fee_combination_versions`（组合版本账）—— 同上，是历史；
--   · **不动** `production_route_rules` / `production_routings`（工艺与工序名**本来就是**「韩褶」，
--     `韩褶-布` / `韩褶-纱` 早已是这个写法）；
--   · **不动** 已归档的 `db/migration-archive/**`（逐字节冻结）与 `db/init/schema.sql` 的历史行 ——
--     新建库由**基线**直接到达终态（`db/init/schema.sql` 的第 02 项已按终态写成「韩褶」）；
--     存量库由本迁移把「韩折」改成「韩褶」 —— 两条路径的终态**逐字一致**（由
--     `tests/unit_ci_workflows/test_processing_catalog_seed.py` 的三源收敛判据钉住）。
--
-- ## 与 ERP 的关系（**照实登记，不粉饰**）
--   ERP 附件（壁达「窗帘货号资料」页）里这一项写作「**韩折**」，我们此前是「照 ERP 逐字」。
--   本次改名后，**目录名与 ERP 附件差一个字** ⇒ 按 ERP 名称做导入/核对时需要一张对照
--   （`韩折` → `韩褶`）；该对照登记在 `tests/unit_ci_workflows/synthetic_processing_fee_data.py`
--   的 `PROCESSING_CATALOG` 注释与 `docs/design/processing-fee-and-option-pricing.md`。
--
-- ## 商家侧影响面（可机械复算，只读）
-- ```sql
-- -- 改前：哪些组合含旧名（本迁移会改这些行的 items / composition_key，不改价）
-- SELECT tenant_id, id, composition_key, unit_price, status, updated_at
--   FROM processing_fee_combinations
--  WHERE deleted = 0 AND items @> '["韩折"]'::jsonb
--  ORDER BY tenant_id, composition_key;
-- ```
-- 跑完本迁移后，上一条查询应当**恒返回 0 行**（终态对账块机械保证）。

BEGIN;

-- ① 前置自证：改名后会撞上**已存在**的组合键 ⇒ fail-closed 并点名（不让下游撞唯一键报错）
--    形态：同一租户里既有一条含「韩折」的行，又已经有一条叫「…韩褶…」的行，且两者规范化后同名。
DO $$
DECLARE
    v_conflicts TEXT;
BEGIN
    SELECT string_agg(
               format('tenant=%s 的现行组合「%s」与「%s」改名后同名', t.tenant_id, t.old_key, c.composition_key),
               '；')
      INTO v_conflicts
      FROM (
            SELECT c1.id,
                   c1.tenant_id,
                   c1.composition_key AS old_key,
                   array_to_string(
                       ARRAY(
                           -- ⚠️ 排序必须写成 `SELECT DISTINCT (<expr>) COLLATE "C" AS nm … ORDER BY 1`：
                           -- `ORDER BY 1 COLLATE "C"` 会被 PG 解析成「整数 1 加排序规则」⇒
                           -- `类型integer不能使用排序规则`（PG 16.15 实测，整份迁移当场抛 + 回滚）。
                           SELECT DISTINCT CASE WHEN e = '韩折' THEN '韩褶' ELSE e END
                                           COLLATE "C" AS nm
                             FROM jsonb_array_elements_text(c1.items) AS e
                            ORDER BY 1
                       ), '+') AS new_key
              FROM processing_fee_combinations c1
             WHERE c1.deleted = 0
               AND jsonb_typeof(c1.items) = 'array'
               AND c1.items @> '["韩折"]'::jsonb
           ) t
      JOIN processing_fee_combinations c
        ON c.tenant_id = t.tenant_id
       AND c.deleted = 0
       AND c.id <> t.id
       AND c.composition_key = t.new_key;

    IF v_conflicts IS NOT NULL THEN
        RAISE EXCEPTION
            '「韩折」→「韩褶」会撞上已存在的加工费组合键（本迁移 fail-closed，不静默合并两笔价）：%。'
            '请先在「加工费组合」页人工处置（改价 / 停用其中一条）后重跑。', v_conflicts;
    END IF;
END $$;

-- ② 加工项目录：把那一项（含商家自建的同名项）改名
--    ⚠️ `processing_items` **没有** `(tenant_id, name)` 唯一索引（见 schema.sql 的种子里那句说明）
--    ⇒ 改名不可能违反唯一约束；同名并存（如评测种子故意造的重复行）在改后仍是同名并存，语义不变。
UPDATE processing_items
   SET name = '韩褶',
       updated_at = NOW()
 WHERE name = '韩折'
   AND deleted = 0;

-- ③ 加工费组合：成员名替换 + `items` 规范化（去重 + 码点升序）+ `composition_key` 重算
--    （`unit_price` / `status` / `sort_order` / `source` / `id` 一字不动 —— 不改价）
-- ⚠️ **不写成 `WITH normalized AS (…)`**：`tests/unit_ci_workflows/test_migration_references_exist_in_schema.py`
-- 的 `_referenced_tables()` 按 `FROM <裸标识符>` 抽表名、**不认识 CTE** ⇒ CTE 名会被当成「schema 里不存在的表」判红
-- （CI 实测：`表 normalized 在 schema.sql 里不存在`）。子查询形态（`FROM ( … ) s`）对同一个抽取器是干净的，
-- 且语义逐字等价 —— 这是**守卫的射程**决定的写法，不是口味。
UPDATE processing_fee_combinations c
   SET items = to_jsonb(s.names),
       composition_key = array_to_string(s.names, '+'),
       updated_at = NOW()
  FROM (
        SELECT c2.id AS id,
               ARRAY(
                   SELECT DISTINCT CASE WHEN e = '韩折' THEN '韩褶' ELSE e END
                                   COLLATE "C" AS nm
                     FROM jsonb_array_elements_text(c2.items) AS e
                    WHERE btrim(e) <> ''
                    ORDER BY 1
               ) AS names
          FROM processing_fee_combinations c2
         WHERE c2.deleted = 0
           AND jsonb_typeof(c2.items) = 'array'
           AND c2.items @> '["韩折"]'::jsonb
       ) s
 WHERE c.id = s.id;

-- ④ 终态对账（两遍都成立；「只改了一部分 / 谓词写歪」⇒ 当场抛 + 整份回滚）
DO $$
DECLARE
    v_item_rows    INTEGER;
    v_combo_rows   INTEGER;
    v_bad_rows     INTEGER;
BEGIN
    SELECT COUNT(*) INTO v_item_rows FROM processing_items
     WHERE name = '韩折' AND deleted = 0;

    SELECT COUNT(*) INTO v_combo_rows FROM processing_fee_combinations
     WHERE deleted = 0 AND jsonb_typeof(items) = 'array' AND items @> '["韩折"]'::jsonb;

    -- 本次改过的那些行必须自洽：key == 规范化后的 items（码点序、'+' 连接）
    SELECT COUNT(*) INTO v_bad_rows
      FROM processing_fee_combinations c
     WHERE c.deleted = 0
       AND jsonb_typeof(c.items) = 'array'
       AND c.items @> '["韩褶"]'::jsonb
       AND c.composition_key <> array_to_string(
               ARRAY(
                   SELECT DISTINCT e COLLATE "C" AS nm
                     FROM jsonb_array_elements_text(c.items) AS e
                    WHERE btrim(e) <> ''
                    ORDER BY 1
               ), '+');

    IF v_item_rows <> 0 OR v_combo_rows <> 0 OR v_bad_rows <> 0 THEN
        RAISE EXCEPTION
            '「韩折」→「韩褶」终态对账未通过：目录仍剩 % 行旧名 · 组合仍剩 % 行含旧名 · % 行 key 与 items 不自洽',
            v_item_rows, v_combo_rows, v_bad_rows;
    END IF;
END $$;

COMMIT;
