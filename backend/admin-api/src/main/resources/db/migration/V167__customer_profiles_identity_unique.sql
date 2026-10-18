-- issue #7257：客户档案按「手机号 / 微信身份」唯一
--
-- 病：三处建档写面都是「selectOne 判空 → insert」，而本表**没有任何唯一约束** ⇒
-- 并发（下单自动建档 × 手工建档 × 接口重试）会静默写出同一手机号/微信身份的两条档案，
-- 于是 total_orders / total_consumption 被劈成两行（客户详情、销售额口径都读不准）。
--
-- 修法：两条普通唯一索引。⚠️ 本表**没有 deleted 列、也不做逻辑删除**（与 order_logistics 不同），
-- 所以不需要部分索引；PG 的唯一索引**不约束 NULL** ⇒ 没有手机号 / 没有 openid 的档案不会互相冲突，
-- 这正是我们要的语义（匿名档案可以多条）。
--
-- 已有重复行时逐个索引**不阻断部署**（RAISE WARNING + 跳过）：清理重复档案涉及订单归属与金额口径，
-- 属数据决策，不在迁移里替人决定。
DO $$
DECLARE
    dup_phone INTEGER;
    dup_openid INTEGER;
BEGIN
    SELECT COUNT(*) INTO dup_phone FROM (
        SELECT tenant_id, phone FROM customer_profiles
         WHERE phone IS NOT NULL
         GROUP BY tenant_id, phone HAVING COUNT(*) > 1
    ) d;
    IF dup_phone > 0 THEN
        RAISE WARNING 'customer_profiles 存在 % 组重复手机号 ⇒ 本次**不建**手机号唯一索引；请先清理（issue #7257）', dup_phone;
    ELSE
        CREATE UNIQUE INDEX IF NOT EXISTS uk_customer_profiles_phone
            ON customer_profiles (tenant_id, phone);
        RAISE NOTICE 'customer_profiles 手机号唯一索引已就绪（issue #7257）';
    END IF;

    SELECT COUNT(*) INTO dup_openid FROM (
        SELECT tenant_id, wechat_openid FROM customer_profiles
         WHERE wechat_openid IS NOT NULL
         GROUP BY tenant_id, wechat_openid HAVING COUNT(*) > 1
    ) d;
    IF dup_openid > 0 THEN
        RAISE WARNING 'customer_profiles 存在 % 组重复微信身份 ⇒ 本次**不建** openid 唯一索引；请先清理（issue #7257）', dup_openid;
    ELSE
        CREATE UNIQUE INDEX IF NOT EXISTS uk_customer_profiles_openid
            ON customer_profiles (tenant_id, wechat_openid);
        RAISE NOTICE 'customer_profiles 微信身份唯一索引已就绪（issue #7257）';
    END IF;
END $$;
