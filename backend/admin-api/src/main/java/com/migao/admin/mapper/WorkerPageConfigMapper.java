package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.WorkerPageConfig;
import org.apache.ibatis.annotations.Mapper;

/**
 * 工人端页面开关（V141，母单 #5161）。对应表：{@code worker_page_configs}。
 */
@Mapper
public interface WorkerPageConfigMapper extends BaseMapper<WorkerPageConfig> {

    /**
     * 本租户的**活跃**配置行（单行表：{@code tenant_id} + {@code deleted = 0}）；无行 ⇒ {@code null}。
     *
     * <p>与 {@code CuttingHeightConfigMapper#selectActiveByTenant} 同款：查询口径**只写一处**
     * （商家读面与工人 {@code GET /api/worker/me} 都调它）—— 两处各写一遍 where 条件，迟早一处漏
     * {@code deleted = 0}（软删行被当成生效配置 = 静默下发错的页面集）。</p>
     *
     * <p>不加 {@code LIMIT 1}：{@code uk_worker_page_configs_tenant}（部分唯一索引，
     * {@code WHERE deleted = 0}）保证 ≤1 行；真出现两行是**不变式被破坏**，应当当场炸，
     * 而不是被 LIMIT 掩盖成「随便取一行」。</p>
     */
    default WorkerPageConfig selectActiveByTenant(Long tenantId) {
        return selectOne(new LambdaQueryWrapper<WorkerPageConfig>()
                .eq(WorkerPageConfig::getTenantId, tenantId)
                .eq(WorkerPageConfig::getDeleted, 0));
    }
}
