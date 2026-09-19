package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.CraftCalcConfig;
import org.apache.ibatis.annotations.Mapper;

/**
 * 算料公式租户级配置（V80，issue #4528 = 包 E）。对应表：{@code craft_calc_configs}。
 */
@Mapper
public interface CraftCalcConfigMapper extends BaseMapper<CraftCalcConfig> {

    /**
     * 本租户的**活跃**配置行（单行表：{@code tenant_id} + {@code deleted = 0}）；无行 ⇒ {@code null}。
     *
     * <p>放在 mapper 的 default 方法里 = <b>一处查询口径</b>：读面（{@code CraftCalcConfigService}）
     * 与算料注入面（{@code CraftCalcClient}）都调它 —— 两处各写一遍 where 条件，
     * 迟早一处漏 {@code deleted = 0}（软删行被当成生效配置 = 静默用错口径算钱）。</p>
     *
     * <p>不加 {@code LIMIT 1}：{@code uk_craft_calc_configs_tenant}（部分唯一索引，{@code WHERE deleted = 0}）
     * 保证 ≤1 行；真出现两行是**不变式被破坏**，应当当场炸（{@code TooManyResultsException}），
     * 而不是被 LIMIT 掩盖成「随便取一行」。</p>
     */
    default CraftCalcConfig selectActiveByTenant(Long tenantId) {
        return selectOne(new LambdaQueryWrapper<CraftCalcConfig>()
                .eq(CraftCalcConfig::getTenantId, tenantId)
                .eq(CraftCalcConfig::getDeleted, 0));
    }
}
