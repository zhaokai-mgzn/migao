-- 特殊选项**旧名存量回填**（issue #4399；上游 = #4389 / PR #4396 的「未做项」）
--
-- ## 病根（静默失效，直接少发工人钱）
-- 特殊选项名是「**订单选配 → 车间工序 / 计件系数**」的 **join key**。V65 已把**配置表**改成 ERP 名
-- （`一分二` → `一分为二`、`余料带回(布)/(纱)` → `余料带回-布/-纱`），但**只覆盖了配置表**：
-- **已落库的订单 / 加工单快照**里若仍带**旧名**，则改名之后才生成加工单的单，
-- 按旧名查 `SPECIAL_OPTION_ROUTINGS` / `OPTION_FACTOR_SCOPES` / `NON_PIECEWORK_OPTIONS`
-- **全部查不到** ⇒ 条件工序不插、计件系数退回 1.0 ⇒ **少发工人钱且不报错**
-- （与 V58 错配、#4230「静默黑洞」同族）。
--
-- ## 实况（2026-09-19 主会话**全量**实测，非抽样）
-- RDS 白名单不可达 ⇒ 改用云测试环境 API 通路（dev 短信万能码在云上有效）：
--   `GET /api/admin/orders?page=N&size=50` → `items[].processingInfo.specialOptions`
-- 读数：
--   扫描订单 781 张 / 明细 782 条（取尽）
--   旧名命中: {'一分二': 3}  → 涉及订单数: 3
--   新名命中: {}（一分为二 / 余料带回-布 / 余料带回-纱 / 余料带回 全零命中）
--   全部 specialOptions 取值分布: [('拼1次', 3), ('一分二', 3)]
-- ⇒ **缺陷是真的（非 0 行）**；且**只有 `一分二` 一项**需要回填
--   （`余料带回(布)/(纱)` 旧名零命中）。
--
-- ## 为什么**不能**用文本裸替换
-- `一分二` 是 `一分为二` 的**子串** ⇒ 对整段 JSONB 文本做 `replace()` 会把
-- **已经正确的新名**再改一次（`一分为二` → `一一分为二`），并可能误伤其它字段的文本。
-- ⇒ 必须**按 `specialOptions` 数组元素**逐个比对替换，且**保留原顺序**（用 `WITH ORDINALITY`）。
--
-- ## 为什么是**数据回填**而不是代码里加双名兼容
-- 本仓明确反对第二份口径（#4389 已裁定「旧写法**不是**兼容别名」）⇒ 只能把数据改成 ERP 名。
--
-- ## 两处载体都要过（漏一处 = 老订单回填了、它的加工单快照还是旧名）
--   ① `orders.processing_info`                    —— 对象，键 `specialOptions`
--   ② `processing_orders.items_snapshot`          —— **数组**，每个元素的键 `specialOptions`
--      （形状见 `ProcessingOrderService` 的 `copyIfPresent(pi, entry, "specialOptions")`）
--
-- ## 幂等（MigrationRunner 要求所有 SQL 可重复执行）
-- 两条 UPDATE 都带「**仍含旧名**」的 WHERE 守卫（`@>` 包含判断）⇒ 重跑时旧名已不存在 ⇒
-- **空转**（0 行），不产生第二次改动。`jsonb_typeof(...) = 'array'` 再挡一层
-- （脏数据里 `specialOptions` 不是数组时不碰，避免 `jsonb_array_elements_text` 报错中断迁移）。
--
-- ## 回滚（人工，如需）
--   本迁移**不可逆**（旧名与新名是多对一：`一分为二` 也可能是本来就对的）——
--   但回滚无意义：回滚回旧名只会让缺陷重现。若确需，按 `special_options_backfill_audit`
--   思路先备份受影响行（本迁移**不做**备份表：影响面实测 3 行，且备份表会成为新的漂移面）。
--
-- ## 不做
-- - ❌ 不改任何**已发布**迁移（V65/V56/V59 一个字都不动；`MigrationRunner` 按文件名整份跳过）。
-- - ❌ 不加双名兼容代码（第二份口径）。
-- - ❌ 不动 `docs/sql/schema.sql`（本迁移是**数据**回填，不改 schema ⇒ bootstrap 路径无需镜像）。
-- - ❌ 不处理 `余料带回(布)/(纱)`（实测零命中；真出现时按同一形态补一条 UPDATE 即可）。

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ① 订单：`orders.processing_info.specialOptions`
-- ══════════════════════════════════════════════════════════════════════════════════════
UPDATE orders
   SET processing_info = jsonb_set(
           processing_info,
           '{specialOptions}',
           (
               -- 按元素替换 + **保序**（jsonb_agg 不带 ORDER BY 时顺序未定义）
               SELECT jsonb_agg(
                          CASE WHEN elem = '一分二' THEN '一分为二' ELSE elem END
                          ORDER BY ord
                      )
                 FROM jsonb_array_elements_text(processing_info -> 'specialOptions')
                      WITH ORDINALITY AS t(elem, ord)
           ),
           false   -- create_if_missing = false：键不存在就不造（键存在已由 WHERE 保证）
       ),
       updated_at = NOW()
 WHERE processing_info IS NOT NULL
   AND jsonb_typeof(processing_info -> 'specialOptions') = 'array'
   AND (processing_info -> 'specialOptions') @> '["一分二"]'::jsonb;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ② 加工单快照：`processing_orders.items_snapshot[].specialOptions`
--    外层是**数组** ⇒ 逐元素重建（保序），只对含旧名的元素做 jsonb_set
-- ══════════════════════════════════════════════════════════════════════════════════════
UPDATE processing_orders
   SET items_snapshot = (
           SELECT jsonb_agg(
                      CASE
                          WHEN jsonb_typeof(item -> 'specialOptions') = 'array'
                               AND (item -> 'specialOptions') @> '["一分二"]'::jsonb
                          THEN jsonb_set(
                                   item,
                                   '{specialOptions}',
                                   (
                                       SELECT jsonb_agg(
                                                  CASE WHEN elem = '一分二' THEN '一分为二' ELSE elem END
                                                  ORDER BY ord
                                              )
                                         FROM jsonb_array_elements_text(item -> 'specialOptions')
                                              WITH ORDINALITY AS t(elem, ord)
                                   ),
                                   false
                               )
                          ELSE item
                      END
                      ORDER BY idx
                  )
             FROM jsonb_array_elements(items_snapshot) WITH ORDINALITY AS e(item, idx)
       ),
       updated_at = NOW()
 WHERE items_snapshot IS NOT NULL
   AND jsonb_typeof(items_snapshot) = 'array'
   AND items_snapshot @> '[{"specialOptions": ["一分二"]}]'::jsonb;
