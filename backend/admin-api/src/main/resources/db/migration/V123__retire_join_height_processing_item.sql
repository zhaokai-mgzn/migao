-- 「接高」撤出**加工项目录** —— 该目录项软删 + 停用；**不动任何价**（issue #5230）
--
-- ## 一句话
-- `processing_items` 里名为 `接高` 的**存活行**（V83 第 09 项种下的那一批，含商家自建的同名项）
-- 一律 `.deleted = 1` + `.status = 'disabled'`：**商家不再能勾它** ⇒ 它不再进
-- `processingInfo.processingItems[]` ⇒ 不再进**顾客侧加工费组合键**。
-- `接高` 保留的出口只有一条 —— 经**特殊选项**（`specialOptions`）插 `接高-布` 工序 + 计件 ¥1.0/幅
-- （#5211 已落，本单不动）；顾客侧那笔「接缝」的钱改由**派生的「拼接」加工项**承载
-- （接高 / 接宽 发生 ⇒ 前端把 `拼接` 并进 `processingItems[]`，见
-- `frontend/admin-web/src/lib/craft-calc-request.ts::derivedJoinSpliceItemOf`）。
--
-- ## 用户裁定（原文，2026-09-23）
--   「**选2，并且接高同接宽一样，都不要进加工项，但是会派生出拼接加工项**」
--   同日追加（v2，收窄范围）：「**移除接宽逻辑，接高在特殊选项中选择，但是仍然得自动推导**」
-- ⇒ `接宽` **不建**任何出口（选项 / 工序 / 计件都不加）；`接高` **保持**特殊选项通路，
--   只把「加工项目录项」这一条通路撤掉。
--
-- ## 为什么必须是**新增 V123**（不能改 V83）
-- `MigrationRunner` 的台账 `schema_migrations` 按**文件名**记账、已应用的文件**整份跳过** ⇒ 改 V83
-- 只对**全新库**生效，存量环境永远拿不到 = 「CI 全绿、功能静默缺失」（issue #4235）。
-- V83 另被 `tests/unit_ci_workflows/migration_fingerprints.json` 逐字节冻结 ⇒ 改它必红。
--
-- ## 幂等（`MigrationRunner` 硬要求所有迁移可重复执行）
-- 谓词 = `WHERE name = '接高' AND deleted = 0` ⇒ 第二遍匹配 **0 行**、净效果相同；
-- ⚠️ 因此本文件**不能**用「认领 0 行 ⇒ 抛异常」的空跑自证（第二遍合法地认领 0 行）——
-- 空跑自证由文末的**终态对账**承担（它两遍都成立，而「只改了一部分行 / 谓词写歪」会让它当场抛并整份回滚）。
--
-- ## 为什么不按租户循环（issue 正文写「按租户」；这里说明为什么不循环也满足其意图）
-- 终态口径对**全部租户完全同构**：任何租户名下都不得再留存活 `接高` 项，**不存在**「某些租户保留」这种终态。
-- ⇒ 一条**不带租户过滤**的 UPDATE 覆盖面**严格更大**（含 `tenants` 表里缺席的租户行与将来新建租户的存量行），
-- 且覆盖面由文末对账块**机械核验**（不靠人读注释）。这与 V83 的 INSERT 侧口径一致（那是「按租户种」，本迁移是「全表撤」）。
--
-- ## 🔴 存量影响面（**显式登记**，不静默变价）
-- 撤出的直接后果（一条都不许含糊）：
--   ① **含 `接高` 的存量加工费组合**（`processing_fee_combinations`）**一行都不动**（不改价、不停用、不删除）：
--      `status` / `unit_price` / `composition_key` / `items` 保持原样 ⇒ **本迁移自身不改任何钱**；
--   ② 但它们在新单上**再也匹配不到**了 —— 组合键的真值源是 `processingItems[].name`，而 `接高`
--      从此不可能出现在新单里（目录项已撤）⇒ 那些单会落到**更便宜的组合**或 `unpriced`；
--      ⚠️ 落 `unpriced` 时**不是静默按 0 收**：`ProcessingFeeCalculator` 会给 `fee_source=unpriced`
--      + `compositionKey` + 可行动提示（`PRICING_ENTRY`，issue #4594 的口径）；
--   ③ 那些组合在「加工费组合」配置页**照旧可见**（列表由 `composition_key` 拆名渲染，不查目录），
--      但**保存 / 改价**会被挡：`validateItems` 查 `activeItemsByName` ⇒ 422
--      「加工项「接高」在加工项目录中不存在或已停用」。
--
-- **可机械复算的影响面查询**（只读；商家 / 运维可原样执行）：
-- ```sql
-- SELECT c.tenant_id, c.id, c.composition_key, c.unit_price, c.status, c.updated_at
--   FROM processing_fee_combinations c
--  WHERE c.deleted = 0
--    AND c.status = 'active'
--    AND c.items @> '["接高"]'::jsonb
--  ORDER BY c.tenant_id, c.id;
-- ```
-- **商家的可行动处置**（一句话）：在「加工费组合」里**改用 `拼接` 配价** ——
-- 「拼接」在目录里仍在（V83 第 10 项），且接高 / 接宽 发生时会被**自动派生**进组合键
-- ⇒ 新单会真的带上它、真的取到那条价。
--
-- ## 红线：本迁移**只写 `processing_items` 的三列**（`deleted` / `status` / `updated_at`）
--   · `processing_fee_combinations`（对客组合价）**一字不动** —— 撤目录项 ≠ 改钱（见上「影响面」）；
--   · `production_route_rules` **一字不动** —— 尤其 V84 那条 `trigger_kind='processing_item'` /
--     `trigger_value='接高'` 的规则**保留**：**存量单**（在本迁移之前建、其 `processingItems` 里已经
--     带着 `接高`）重放 / 生成加工单时**照旧插 `接高-布` 工序**（不追溯、不少发工钱）；
--     挡新单靠的是**目录项退场**（新单不可能再产生 `接高` 这个名），不是删规则；
--   · `production_operations` / `production_operation_positions` **一字不动** —— `接高-布` 工序行是
--     **特殊选项**那条通路（#5211）的承重件，删它会让所有接高单 fail-closed 422；
--   · `production_route_rules.customer_unit_price`（V82 的 `接高` = ¥2.50/套 对客价）**一字不动** ——
--     用户裁定「接高在特殊选项中选择」= **保持现状**；
--   · 三张快照 / 历史表 `processing_orders.items_snapshot` / `processing_position_operations` /
--     `production_work_logs` **一字不动**（历史工资与历史实例不回溯）。
--
-- ## 与代码侧的关系（`deleted = 0` 过滤是共同前提）
--   下单页手选加工项、加工费组合配置页的候选下拉都读**存活**目录项（`activeItemsByName` 同时过滤
--   `status` 与 `deleted`）⇒ 撤出后两处自然都看不到 `接高`（**不需要**再在前端加一份黑名单 ——
--   两份口径必然漂移）。前端的**唯一**新增口径 = 派生「拼接」（见上）。
--
-- ## 回滚 SQL（**新迁移，不删 V123**；⚠️ 有损，如实登记）
-- ```sql
-- -- V124__rollback_retire_join_height_processing_item.sql（本单只登记，不落码）
-- -- 有损点：把 `deleted = 1` 的 `接高` 行一律复活，会**连带复活商家自己删过 / 停用过的同名行**
-- -- （本迁移与「商家手动删过」在数据上不可区分：都只是 `deleted = 1`）。
-- UPDATE processing_items
--    SET deleted = 0, status = 'active', updated_at = NOW()
--  WHERE name = '接高' AND deleted = 1;
-- ```

BEGIN;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ① 撤出「接高」加工项目录项（软删 + 停用 —— **显式逐列写全**，不走 MyBatis 的自动填充形态）
-- ══════════════════════════════════════════════════════════════════════════════════════
-- 为什么两列都写：读面 `activeItemsByName` 同时过滤 `status='active'` 与 `deleted = 0`；
-- 只写一列会让「目录项已退场」这件事在不同读面上表现不一致（有的读面还看得到它）。
UPDATE processing_items
   SET deleted = 1,
       status = 'disabled',
       updated_at = NOW()
 WHERE name = '接高'
   AND deleted = 0;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ② 终态对账（**两遍都必须成立** ⇒ 既是幂等自证，也是「写语句判据漂移」的停止条件）
-- ══════════════════════════════════════════════════════════════════════════════════════
DO $$
DECLARE
    remaining      INTEGER;
    splice_alive   INTEGER;
    catalog_alive  INTEGER;
BEGIN
    -- ① 表必须仍在（本迁移只许改行，**不许**删表 / 删列）
    IF to_regclass('processing_items') IS NULL THEN
        RAISE EXCEPTION 'V123 红线被破：processing_items 表不存在 —— 本迁移只许软删行，不许动结构 —— 回滚本迁移';
    END IF;

    -- ② 终态：任何租户名下都不得再有存活（`deleted = 0`）的「接高」目录项
    SELECT count(*) INTO remaining
      FROM processing_items
     WHERE name = '接高'
       AND deleted = 0;
    IF remaining > 0 THEN
        RAISE EXCEPTION
            'V123 数量对账失败：仍有 % 条存活的「接高」加工项目录项（写语句判据漂移 / 被部分回滚）—— 回滚本迁移',
            remaining;
    END IF;

    -- ③ **不得误撤其它项**：目录里若还有人活着的项，`拼接` 就必须活着（派生的接缝那笔账靠它取价）。
    --    ⚠️ 闸门 `catalog_alive > 0`：空库 / 未种目录的库上本条不适用（不是放宽 —— 那种库上没有
    --    「误撤」可言），而一旦目录非空，把谓词写歪（例如写成 `name = '拼接'`）会当场抛。
    SELECT count(*) INTO catalog_alive FROM processing_items WHERE deleted = 0;
    SELECT count(*) INTO splice_alive  FROM processing_items WHERE name = '拼接' AND deleted = 0;
    IF catalog_alive > 0 AND splice_alive = 0 THEN
        RAISE EXCEPTION
            'V123 误撤：目录里还有 % 条存活项，但「拼接」已被撤出 —— 谓词写歪了？—— 回滚本迁移',
            catalog_alive;
    END IF;
END $$;

COMMIT;
