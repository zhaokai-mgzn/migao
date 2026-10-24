-- issue #7174：一单一条物流（(tenant_id, order_id) 唯一，软删后的历史行不参与）
--
-- 为什么需要：并发两次发货（双击「发货」/ 工人端与商家端同时确认）时，应用侧的
-- 「先条件更新、影响 0 行才建行」在**极端交叉窗口**里仍可能双双走到建行 —— 唯一索引是最后一道兜底，
-- 让第二次建行抛 DuplicateKeyException；应用侧捕获后**退化为更新那一行**（见 OrderLogisticsWriter），
-- 最终仍是恰好 1 行、且不报错。
--
-- 为什么是**部分索引**（WHERE deleted = 0）：逻辑删除的历史行不参与唯一性，否则删掉重建会永久阻塞。
--
-- 为什么用 DO 块：线上若已存在历史重复行（本单修之前产生的），直接 CREATE UNIQUE INDEX 会让**迁移失败
-- ⇒ 部署被卡住**。这里改成：有重复行时 RAISE WARNING 并**跳过建索引**（迁移照常完成），把问题留给
-- 可观测面（WARNING 会进迁移日志），而不是让整次发布失败。重复行清理是一次独立的人工/脚本动作
-- （删哪条属于数据决策，不在迁移里替人决定）。
DO $$
DECLARE
    dup_pairs INTEGER;
BEGIN
    SELECT COUNT(*) INTO dup_pairs FROM (
        SELECT tenant_id, order_id FROM order_logistics
         WHERE deleted = 0
         GROUP BY tenant_id, order_id
        HAVING COUNT(*) > 1
    ) d;

    IF dup_pairs > 0 THEN
        RAISE WARNING 'order_logistics 存在 % 组重复的 (tenant_id, order_id) ⇒ 本次**不建**唯一索引；'
                      ' 请先清理重复行再重跑本迁移（issue #7174）', dup_pairs;
    ELSE
        CREATE UNIQUE INDEX IF NOT EXISTS uk_order_logistics_tenant_order
            ON order_logistics (tenant_id, order_id) WHERE deleted = 0;
        RAISE NOTICE 'order_logistics 唯一索引已就绪（issue #7174）';
    END IF;
END $$;
