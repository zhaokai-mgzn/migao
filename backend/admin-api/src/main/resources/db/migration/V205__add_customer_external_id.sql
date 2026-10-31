-- V205 / issue #8295：客户主数据迁移的幂等键
--
-- 旧 ERP 的客户ID（迁移文件里映射为 externalId）与租户组合唯一：
-- 同一份客户 Excel 重跑 ⇒ 命中同一行，不重复建客户。
-- NULL 不参与唯一（部分唯一索引）：手工/会话/下单自动建档可以没有旧系统ID。
ALTER TABLE customer_profiles ADD COLUMN IF NOT EXISTS external_id VARCHAR(128);

COMMENT ON COLUMN customer_profiles.external_id IS
    '旧系统客户ID（迁移幂等键，issue #8295）；NULL = 非迁移建档。同一 (tenant_id, external_id) 至多一行';

CREATE UNIQUE INDEX IF NOT EXISTS uk_customer_profiles_external_id
    ON customer_profiles (tenant_id, external_id)
    WHERE external_id IS NOT NULL;
