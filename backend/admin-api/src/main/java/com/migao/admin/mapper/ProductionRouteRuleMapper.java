package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.ProductionRouteRule;
import org.apache.ibatis.annotations.Mapper;

import java.math.BigDecimal;
import java.time.OffsetDateTime;

/**
 * 工艺路线规则表（V71 / V72，issue #4427 + #4432）
 * 对应表：{@code production_route_rules}。
 */
@Mapper
public interface ProductionRouteRuleMapper extends BaseMapper<ProductionRouteRule> {

    /**
     * 只写**对客元/套价**这一列（issue #4567：特殊选项定价）。
     *
     * <p><b>为什么用 {@code LambdaUpdateWrapper} 而不是实体 {@code updateById}</b>：
     * {@code updateById} 会把整行按实体回写 —— 调用方只要漏设一个字段就会被写成 {@code null}
     * （本表同时承载车间路由语义与对客价语义，误写 {@code factor} 会改计件系数 ⇒ 工人工资错）。
     * 本方法**只** {@code SET} 这一列 + {@code updated_at}，其余列一个不碰。</p>
     *
     * @param price {@code null} = 显式改回**未定价**（不是 0 元）
     * @return 受影响行数（0 = 行不存在 / 非本租户 / 已软删）
     */
    default int updateCustomerUnitPrice(String id, Long tenantId, BigDecimal price) {
        return update(null, new LambdaUpdateWrapper<ProductionRouteRule>()
                .eq(ProductionRouteRule::getId, id)
                .eq(ProductionRouteRule::getTenantId, tenantId)
                .eq(ProductionRouteRule::getDeleted, 0)
                .set(ProductionRouteRule::getCustomerUnitPrice, price)
                .set(ProductionRouteRule::getUpdatedAt, OffsetDateTime.now()));
    }

    /**
     * 软删条件工序规则 = <b>带谓词的条件更新</b>（issue #6962 P5-③）：谓词 = {@code id + tenant_id +
     * deleted = 0}，按<b>影响行数</b>判是否真删到。
     *
     * <p><b>修前的两个洞</b>：{@code ProductionRoutingCommandService#deleteRouteRule} 的落库语句
     * 只有 {@code .eq(id)} —— ① <b>缺 tenant 限定</b>（跨租户误删）；② <b>无 {@code deleted = 0}</b>、
     * <b>不判影响行数</b>（已软删 / 不存在也回「deleted=true」= 0 行当成功）。与
     * {@link ProductionRouteTemplateMapper#markDeletedByIdAndTenant} 同口径、同形态。</p>
     *
     * @return 受影响行数（{@code 0} = 不存在 / 跨租户 / 已软删过）
     */
    default int markDeletedByIdAndTenant(String id, Long tenantId) {
        return update(null, new LambdaUpdateWrapper<ProductionRouteRule>()
                .eq(ProductionRouteRule::getId, id)
                .eq(ProductionRouteRule::getTenantId, tenantId)
                .eq(ProductionRouteRule::getDeleted, 0)
                .set(ProductionRouteRule::getDeleted, 1)
                .set(ProductionRouteRule::getUpdatedAt, OffsetDateTime.now()));
    }
}
