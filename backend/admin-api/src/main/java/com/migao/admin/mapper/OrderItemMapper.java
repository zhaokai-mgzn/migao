package com.migao.admin.mapper;

import com.migao.admin.entity.OrderItem;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.Map;

/**
 * 订单明细 Mapper 接口
 */
@Mapper
public interface OrderItemMapper extends BaseMapper<OrderItem> {

    /**
     * 根据订单 ID 查询订单明细列表
     */
    @Select("SELECT * FROM order_items WHERE order_id = #{orderId} AND tenant_id = #{tenantId} AND deleted = 0")
    List<OrderItem> selectByOrderId(@Param("orderId") String orderId, @Param("tenantId") Long tenantId);

    /**
     * 含加工待发货订单数（#2886 性能优化：JOIN orders 一次统计，
     * 替代原来「全量待发货订单 ID 拉取 + order_items IN 查询」两次串行往返）。
     * 两张表租户条件均由 TenantLineInnerInterceptor 自动注入（与 findLowStockByColor 同模式）。
     */
    @Select("SELECT COUNT(DISTINCT oi.order_id) FROM order_items oi " +
            "JOIN orders o ON oi.order_id = o.id " +
            "WHERE o.deleted = 0 AND o.status IN ('confirmed','producing') " +
            "AND oi.deleted = 0 AND oi.processing_info IS NOT NULL")
    long selectProcessingPendingOrdersCount();

    /**
     * 商品销量排行（本周期聚合，#2886 性能优化：替代原来全量明细拉到 JVM 再分组排序）。
     * FLOOR(subtotal) 与旧逻辑 item.getSubtotal().longValue() 的逐行截断语义一致（非负金额下等于截断）。
     */
    @Select("SELECT product_id, MAX(product_name) AS product_name, " +
            "COALESCE(SUM(quantity), 0) AS qty, COALESCE(SUM(FLOOR(subtotal)), 0) AS amt " +
            "FROM order_items WHERE deleted = 0 AND created_at >= #{periodStart} " +
            "GROUP BY product_id ORDER BY qty DESC LIMIT #{limit}")
    List<Map<String, Object>> selectProductRanking(
            @Param("periodStart") OffsetDateTime periodStart,
            @Param("limit") int limit);

    /**
     * 商品上期销量（topN 产品 IN 批量一次，替代原来每商品一次查询，#2886）。
     */
    @Select("<script>" +
            "SELECT product_id, COALESCE(SUM(quantity), 0) AS qty FROM order_items " +
            "WHERE deleted = 0 AND product_id IN " +
            "<foreach collection='productIds' item='pid' open='(' separator=',' close=')'>#{pid}</foreach> " +
            "AND created_at &gt;= #{prevStart} AND created_at &lt; #{periodStart} " +
            "GROUP BY product_id" +
            "</script>")
    List<Map<String, Object>> selectPrevPeriodQuantities(
            @Param("productIds") List<String> productIds,
            @Param("prevStart") OffsetDateTime prevStart,
            @Param("periodStart") OffsetDateTime periodStart);
}
