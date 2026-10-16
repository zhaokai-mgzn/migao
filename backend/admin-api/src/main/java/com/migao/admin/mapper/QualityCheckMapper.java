package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.QualityCheck;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.Collection;
import java.util.List;

/**
 * 质检记录 Mapper（V157，issue #5652）。
 *
 * <p>写入一律走 {@code BaseMapper}（租户列由 {@code TenantLineInnerInterceptor} 注入，
 * 与既有服务同款）；这里只加**一条读面**：按成品帘 id 批量取**最新一条**质检判定。</p>
 */
@Mapper
public interface QualityCheckMapper extends BaseMapper<QualityCheck> {

    /**
     * 这批成品帘各自的**最新**一条质检判定（一条成品帘允许多条记录：返工后重检是正常业务）。
     *
     * <p>用 {@code DISTINCT ON (order_item_id)} —— PG 原生特性（最少代码阶梯：原生特性优先于
     * 自造窗口函数 + 二次过滤），与 {@code idx_quality_inspections_item} 的
     * {@code (tenant_id, order_item_id, inspected_at)} 序逐字对齐。</p>
     *
     * <p>租户隔离由 {@code TenantLineInnerInterceptor} 自动注入；{@code deleted = 0} 显式过滤
     * （与全仓软删口径同款）。</p>
     */
    @Select("<script>"
            + "SELECT DISTINCT ON (order_item_id) * FROM quality_inspections "
            + "WHERE deleted = 0 AND order_item_id IN "
            + "<foreach item='id' collection='orderItemIds' open='(' separator=',' close=')'>#{id}</foreach> "
            + "ORDER BY order_item_id, inspected_at DESC, created_at DESC"
            + "</script>")
    List<QualityCheck> selectLatestByOrderItemIds(@Param("orderItemIds") Collection<String> orderItemIds);
}
