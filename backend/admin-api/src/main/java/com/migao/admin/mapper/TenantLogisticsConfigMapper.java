package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.TenantLogisticsConfig;
import org.apache.ibatis.annotations.Mapper;

/**
 * 物流取号租户级配置（issue #8698）。对应表：{@code tenant_logistics_configs}。
 */
@Mapper
public interface TenantLogisticsConfigMapper extends BaseMapper<TenantLogisticsConfig> {

    /**
     * 本租户的**活跃**配置行（单行表：{@code tenant_id} + {@code deleted = 0}）；无行 ⇒ {@code null}。
     *
     * <p>查询口径只写一处（读面与写面 upsert 前的判重共用）——
     * 两处各写一遍 where 条件，迟早一处漏 {@code deleted = 0}（软删行被当成生效配置
     * ⇒ 商家改了承运商却不生效，且没有任何东西会红）。</p>
     *
     * <p>不加 {@code LIMIT 1}：{@code uk_tenant_logistics_configs_tenant}（部分唯一索引，
     * {@code WHERE deleted = 0}）保证 ≤1 行；真出现两行是**不变式被破坏**，应当当场炸。</p>
     */
    default TenantLogisticsConfig selectActiveByTenant(Long tenantId) {
        return selectOne(new LambdaQueryWrapper<TenantLogisticsConfig>()
                .eq(TenantLogisticsConfig::getTenantId, tenantId)
                .eq(TenantLogisticsConfig::getDeleted, 0));
    }
}
