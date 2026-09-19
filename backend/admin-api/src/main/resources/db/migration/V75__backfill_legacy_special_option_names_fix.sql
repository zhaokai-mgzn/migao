-- 特殊选项**旧名存量回填 · 修正版**（issue #4501；修正 V74 的载体①）
--
-- ## 为什么是**新增 V75** 而不是改 V74
-- V74（#4399）的载体①写成了 `UPDATE orders SET processing_info = …`，而
-- **`orders` 表根本没有 `processing_info` 列**（实测
-- `awk '/^CREATE TABLE orders \(/,/^\);/' docs/sql/schema.sql | grep -c processing_info` ⇒ **0**；
-- `order_items` ⇒ **1**）—— `specialOptions` 在**订单明细 `order_items.processing_info`** 上
-- （`OrderItem` 实体 `@TableName("order_items")`；API 的 `items[].processingInfo` 就是它）。
--
-- 后果链（**每一环都不报错**）：
--   ① 该条 SQL 失败；
--   ② `MigrationRunner` 对**非连接类**失败是「跳过这一条、继续跑后面的」（`MigrationRunner:185`，
--      issue #3270 的刻意权衡：一条坏迁移不该冻结整个 schema）；
--   ③ ⇒ **部署 success、服务 UP、探活 200**；
--   ④ ⇒ **回填从未发生** —— 云测试环境实测（2026-09-19，全量 781 张订单）：
--      旧名 `一分二` 仍 **3** 处、新名 `一分为二` 仍 **0** 处。
--
-- ⚠️ **不能改 V74**：`.github/danger_scan.py` 机械阻塞「已发布迁移被修改/删除」，
-- 且它的确认通道（`/danger-ack`）**只对 workflow 删除开放**，对迁移没有
-- ⇒ 合规路径**只有**「新增 V{n+1}__」（本文件）。
-- ⇒ V74 会**永久失败并每次启动记一条 ERROR**（它已失败 ⇒ 不入 `schema_migrations` 台账 ⇒ 每次重试）——
--   这是**已知且接受**的代价：本文件承担真正的回填，V74 的失败只是日志噪音。
--   「迁移失败 ⇒ 部署仍 success」这个**可观测性缺口**已在 issue #4501 登记，另单处理。
--
-- ## 本文件的载体（两处都要过；漏一处 = 老订单回填了、它的加工单快照还是旧名）
--   ① `order_items.processing_info`               —— **订单明细**的 JSONB 对象，键 `specialOptions`
--   ② `processing_orders.items_snapshot`          —— **数组**，每个元素的键 `specialOptions`
--
-- ## 为什么**不能**用文本裸替换
-- `一分二` 是 `一分为二` 的**子串** ⇒ 对整段 JSONB 文本做 `replace()` 会把
-- **已经正确的新名**再改一次（`一分为二` → `一一分为二`），并可能误伤其它字段的文本。
-- ⇒ 必须**按 `specialOptions` 数组元素**逐个比对替换，且**保留原顺序**（用 `WITH ORDINALITY`）。
--
-- ## 幂等（MigrationRunner 要求所有 SQL 可重复执行）
-- 两条 UPDATE 都带「**仍含旧名**」的 WHERE 守卫（`@>` 包含判断）⇒ 重跑时旧名已不存在 ⇒
-- **空转**（0 行）。`jsonb_typeof(...) = 'array'` 再挡一层（脏数据里不是数组时不碰，避免中断迁移）。
--
-- ## 实况（2026-09-19 全量实测 781 张订单）
--   旧名命中: {'一分二': 3} → 涉及订单 3 张；新名零命中；'余料带回(布)/(纱)' 零命中
--   ⇒ **缺陷是真的（非 0 行）**；且**只有 `一分二` 一项**需要回填。
--
-- ## 不做
-- - ❌ 不改任何**已发布**迁移（V74/V65/V56/V59 一个字不动）。
-- - ❌ 不加双名兼容代码（第二份口径，见 #4389 裁定）。
-- - ❌ 不动 `docs/sql/schema.sql`（本迁移是**数据**回填，不改 schema）。

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ① 订单：`orders.processing_info.specialOptions`
-- ══════════════════════════════════════════════════════════════════════════════════════
UPDATE order_items
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
