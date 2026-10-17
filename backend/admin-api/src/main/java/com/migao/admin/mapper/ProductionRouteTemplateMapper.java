package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.ProductionRouteTemplate;
import org.apache.ibatis.annotations.Mapper;

import java.time.OffsetDateTime;

/**
 * 具名工艺路线模板（V71 / V72，issue #4427 + #4432）
 * 对应表：{@code production_route_templates}。
 */
@Mapper
public interface ProductionRouteTemplateMapper extends BaseMapper<ProductionRouteTemplate> {

    /**
     * 软删路线 = <b>带谓词的条件更新</b>（issue #6962 P5-③）：谓词 = {@code id + tenant_id +
     * deleted = 0}，按<b>影响行数</b>判是否真删到。
     *
     * <p><b>修前的两个洞</b>：{@code ProductionRoutingCommandService#deleteRouting} 的落库语句
     * 只有 {@code .eq(id)} —— ① <b>缺 tenant 限定</b>（跨租户误删：拿到别人的 id 就能删别人的路线，
     * 租户隔离只靠更早一次读判的 {@code tenantId.equals(...)}，读判与写之间无互斥）；
     * ② <b>无 {@code deleted = 0}</b>、<b>不判影响行数</b>（重复删同一 id 照样「成功」——
     * 调用方报 200 而这次没有删到任何东西，即「0 行当成功」）。</p>
     *
     * <p>仍走 {@code update(null, LambdaUpdateWrapper)} 而<b>不是</b> {@code updateById}：MP 全局逻辑
     * 删除会把 {@code deleted} 从 {@code updateById} 的 SET 子句里剔除 ⇒ 静默 no-op（issue #4608 的
     * 实测形态）。{@code updated_at} 一并显式写（「谁在什么时候删的」是排查工序错配的唯一证据）。</p>
     *
     * @return 受影响行数（{@code 0} = 不存在 / 跨租户 / 已软删过）
     */
    default int markDeletedByIdAndTenant(String id, Long tenantId) {
        return update(null, new LambdaUpdateWrapper<ProductionRouteTemplate>()
                .eq(ProductionRouteTemplate::getId, id)
                .eq(ProductionRouteTemplate::getTenantId, tenantId)
                .eq(ProductionRouteTemplate::getDeleted, 0)
                .set(ProductionRouteTemplate::getDeleted, 1)
                .set(ProductionRouteTemplate::getUpdatedAt, OffsetDateTime.now()));
    }
}
