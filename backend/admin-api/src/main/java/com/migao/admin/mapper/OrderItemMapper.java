package com.migao.admin.mapper;

import com.migao.admin.entity.OrderItem;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.ResultMap;
import org.apache.ibatis.annotations.Select;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.Map;

/**
 * 订单明细 Mapper 接口
 *
 * <p>🔴 手写 {@code @Select} 必须显式绑 autoResultMap（口径与判据见
 * {@code ProcessingOrderMapper} 的类注释 / {@code JacksonTypeHandlerMappingGuardTest}）——
 * 否则 {@code processing_info}（JSONB）以 JSON 字符串落到 {@code Object} 字段上，
 * {@code instanceof Map} 判据静默为假（issue #3340 实测过、issue #4865 是同一根因的复发）。</p>
 */
@Mapper
public interface OrderItemMapper extends BaseMapper<OrderItem> {

    /**
     * 根据订单 ID 查询订单明细列表
     */
    @ResultMap("mybatis-plus_OrderItem")
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
     * #2984 口径治理：JOIN orders 只统计有效订单（confirmed/producing/shipped/completed），
     * 排除 pending(未付款)/cancelled(已取消)——避免未付款测试单/废弃单污染排行并制造虚假环比。
     * #2989 数据治理：排除 product_id 为 NULL/空 的幽灵明细（否则被 GROUP BY 聚合成不存在商品行，
     * 生产实证曾出现排行里 54 件无 productId 的假商品）。
     * 租户条件由 TenantLineInnerInterceptor 自动注入（order_items + orders 两表均已注册，与
     * selectProcessingPendingOrdersCount 同模式）。
     */
    @Select("SELECT oi.product_id, MAX(oi.product_name) AS product_name, " +
            "COALESCE(SUM(oi.quantity), 0) AS qty, COALESCE(SUM(FLOOR(oi.subtotal)), 0) AS amt " +
            "FROM order_items oi JOIN orders o ON oi.order_id = o.id " +
            "WHERE oi.deleted = 0 AND o.deleted = 0 " +
            "AND oi.product_id IS NOT NULL AND oi.product_id != '' " +
            "AND o.status IN ('confirmed','producing','shipped','completed') " +
            "AND oi.created_at >= #{periodStart} " +
            "GROUP BY oi.product_id ORDER BY qty DESC LIMIT #{limit}")
    List<Map<String, Object>> selectProductRanking(
            @Param("periodStart") OffsetDateTime periodStart,
            @Param("limit") int limit);

    /**
     * 商品上期销量（topN 产品 IN 批量一次，替代原来每商品一次查询，#2886）。
     * #2984：与 selectProductRanking 同口径 —— JOIN orders 过滤有效状态，保证环比分母一致。
     * #2989：同样排除 product_id 为 NULL/空 的幽灵明细，与本期口径严格一致。
     * #2990 回归修复：`!=` 替代 `<>`（`<>` 在 @Select(<script>) XML 块内非法，导致镜像启动时
     * MyBatis 解析 mapper 崩溃，部署健康检查全挂——见 #2994）。
     */
    @Select("<script>" +
            "SELECT oi.product_id, COALESCE(SUM(oi.quantity), 0) AS qty " +
            "FROM order_items oi JOIN orders o ON oi.order_id = o.id " +
            "WHERE oi.deleted = 0 AND o.deleted = 0 " +
            "AND oi.product_id IS NOT NULL AND oi.product_id != '' " +
            "AND o.status IN ('confirmed','producing','shipped','completed') " +
            "AND oi.product_id IN " +
            "<foreach collection='productIds' item='pid' open='(' separator=',' close=')'>#{pid}</foreach> " +
            "AND oi.created_at &gt;= #{prevStart} AND oi.created_at &lt; #{periodStart} " +
            "GROUP BY oi.product_id" +
            "</script>")
    List<Map<String, Object>> selectPrevPeriodQuantities(
            @Param("productIds") List<String> productIds,
            @Param("prevStart") OffsetDateTime prevStart,
            @Param("periodStart") OffsetDateTime periodStart);

    /**
     * 商品订单行数（窗口内，**退货率的分母**，issue #5369 族 3 · 包 2）。
     *
     * <p>口径与 {@link #selectProductRanking} **同源**：#2984 的有效订单状态集（排除 pending 未付款 /
     * cancelled 已取消）、#2989 排除 product_id 为 NULL/空 的幽灵明细 —— 两处各写一份状态集就会
     * 「同一真值两处投影」，等价性由判据钉住
     * （`backend/ai-agent-service/tests/test_briefing_product_health.py` 的同源守卫）。</p>
     *
     * <p>租户条件**显式带上**（拦截器之外的第二道，与 {@link #selectByOrderId} 同模式）；
     * 有界（`LIMIT`）—— 有界必须显式，否则「看不见的商品」会被读成「没有退货」。</p>
     */
    @Select("SELECT oi.product_id AS product_id, COUNT(*) AS order_lines " +
            "FROM order_items oi JOIN orders o ON oi.order_id = o.id " +
            "WHERE oi.tenant_id = #{tenantId} AND o.tenant_id = #{tenantId} " +
            "AND oi.deleted = 0 AND o.deleted = 0 " +
            "AND oi.product_id IS NOT NULL AND oi.product_id != '' " +
            "AND o.status IN ('confirmed','producing','shipped','completed') " +
            "AND oi.created_at >= #{windowStart} " +
            "GROUP BY oi.product_id ORDER BY order_lines DESC LIMIT #{limit}")
    List<Map<String, Object>> selectProductOrderLineCounts(
            @Param("tenantId") Long tenantId,
            @Param("windowStart") OffsetDateTime windowStart,
            @Param("limit") int limit);
}
