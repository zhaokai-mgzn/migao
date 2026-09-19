-- 特殊选项**对客按套单价**的**初始价目**（V82，issue #4567；用户裁定 2026-09-19）
--
-- ## 一句话
-- 为**每个活跃租户**的 **16 条 `trigger_kind='option'` 规则行**写入 `customer_unit_price`
-- （**元/套**）。这是**初始占位价**：商家在「加工费管理」里改价即可覆盖，本迁移**不覆盖**商家改动。
--
-- ## 用户裁定原文（2026-09-19，**推翻 V77 的「恒 NULL」口径**）
-- 「**特殊选项缺乏单价，通常按套收费**」
-- 「**特殊选项要有定价，你随便初始化一份价格数据，单价是元/套**」
--
-- ## 这 16 个值是**占位初始值**，且**会真的参与对客取价**（已知代价，不粉饰）
-- V77 复核裁定曾把该列定为「恒 `NULL` = 未定价」——理由是**该列没有 `status` 可门控**：
-- `ProductionService` / `ProcessingFeeCalculator` 侧只判 `customer_unit_price IS NOT NULL`
-- ⇒ 一旦落价就参与真实取价（生产 tenant 1 的真实订单会按这批价收费）。
-- **本裁定推翻该口径**：用户要的就是「初始化一份价」（现状是「所有特殊选项都按 0 收」，
-- 用户认为那是错的）。⇒ 这 16 个值**不是测试资产**（与 V77 的合成组合价目 `source='synthetic'`
-- 明确不同），它们是**对客售价账的初始值**，会参与取价，**改它们 = 改钱**。
-- ⇒ 与 V77 的组合价目（92 行 `status='disabled'`，不参与取价）**刻意不同**：本列没有开关，
-- 唯一的惰性就是**商家自己改价**（`IS NULL` 守卫保证本迁移不把商家改过的价刷回去）。
--
-- ## 幂等 + 不覆盖商家改动
-- `UPDATE … WHERE … AND customer_unit_price IS NULL`：重跑空转；**已定价的行（商家改过 / 已生效）
-- 一字不动**。非 `option` 行（工艺变体 / 定型 / 计件系数档）**一律保持 `NULL`**
-- —— 它们不按套收费（V77 的 §4.1 边界不变）。
--
-- ## 为什么按 `trigger_kind='option' + trigger_value` 匹配（**不按 id 形态**）
-- 规则行的 id 形态是**历史实现细节**：1 号租户是 `rr-v70-11` … `rr-v70-26`（V71 字面量种子），
-- 其它租户是 `rr-v72-<tenantId>-11` … `-26`（V72 ⑤ 的按租户回填）。按 id 匹配 = 把历史实现
-- 写进数据面（V76 已因 `sort_order` 踩过同款坑）。业务键 `(tenant_id, trigger_kind,
-- trigger_value, …)` 才是稳定口径 ⇒ 本迁移按 `trigger_kind` + `trigger_value` 匹配。
--
-- ## 回滚 SQL（保留于注释；按需手工执行）
-- ```sql
-- -- ⚠️ 回滚 = 把**所有** option 行的价清回 NULL（含商家自己配过的价）—— 只在确认整批作废时用。
-- UPDATE production_route_rules
--    SET customer_unit_price = NULL
--  WHERE trigger_kind = 'option'
--    AND trigger_value IN ('拼1次','拼2次','拼3次','加花边','加铅块','接高','双眼皮接高',
--                          '余料做绑带','布绑带','余料做帘头','抱枕','纱绑带','加logo条',
--                          '加立边','扣环','防翘扣');
-- ```
--
-- ## 与 schema.sql 的收敛
-- `docs/sql/schema.sql` 是**全新库的一次性 bootstrap**（该路径**不跑迁移链**）⇒ 同源同值的
-- `UPDATE` 必须同步写进该文件（本文件 ① 段与它逐字同源），否则 bootstrap 建库后选项仍无价
-- （形态见 #3270）。
--
-- ## 为什么不改已发布迁移（issue #4235）
-- `MigrationRunner` 的台账 `schema_migrations` 按**文件名**记、已应用的文件**整份跳过**
-- ⇒ 改 V77（把「不落库」改成「落库」）只对全新库生效、**存量环境永远拿不到**
-- （= 「CI 全绿、功能静默缺失」）⇒ 一切增量走**本新文件**。V77 保持原样（不可变）。

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ① 16 条 `option` 规则行 → 对客元/套单价（**占位初始值**，见文件头）
-- ══════════════════════════════════════════════════════════════════════════════════════
-- 逐字口径：`trigger_value` 与 V71 / V72 ⑤ 的 16 条 option 行**逐字相同**（它是 join key）。
-- `action <> 'factor'` 是**语义护栏**：计件系数档（`action='factor'`，如「一分为二 ×1.7」）也是
-- `trigger_kind='option'` 行，但它是**车间计件语义**、不按套收费 ⇒ 不得被本迁移定价。
UPDATE production_route_rules
   SET customer_unit_price = v.unit_price,
       updated_at = NOW()
  FROM tenants t,
       (VALUES
           ('拼1次', 3.00),
           ('拼2次', 5.00),
           ('拼3次', 7.00),
           ('加花边', 4.00),
           ('加铅块', 6.00),
           ('接高', 2.50),
           ('双眼皮接高', 5.00),
           ('余料做绑带', 2.00),
           ('布绑带', 3.00),
           ('余料做帘头', 8.00),
           ('抱枕', 12.00),
           ('纱绑带', 3.00),
           ('加logo条', 2.00),
           ('加立边', 4.00),
           ('扣环', 1.50),
           ('防翘扣', 1.50)
       ) AS v(trigger_value, unit_price)
 WHERE t.deleted = 0
   AND production_route_rules.tenant_id = t.id
   AND production_route_rules.deleted = 0
   AND production_route_rules.trigger_kind = 'option'
   AND production_route_rules.action <> 'factor'
   AND production_route_rules.trigger_value = v.trigger_value
   -- 🔴 幂等 + 不覆盖商家改动：已定价的行（含商家自己配的价）一字不动。
   AND production_route_rules.customer_unit_price IS NULL;
