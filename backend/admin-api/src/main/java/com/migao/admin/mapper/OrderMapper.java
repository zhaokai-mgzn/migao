package com.migao.admin.mapper;

import com.migao.admin.entity.Order;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.Map;

/**
 * 订单 Mapper 接口
 */
@Mapper
public interface OrderMapper extends BaseMapper<Order> {

    @Select("SELECT DATE(created_at) as date, COUNT(*) as orders, COALESCE(SUM(total_amount), 0) as amount " +
            "FROM orders WHERE deleted = 0 AND created_at >= #{startDate} " +
            "GROUP BY DATE(created_at) ORDER BY date")
    List<Map<String, Object>> selectOrderTrend(@Param("startDate") OffsetDateTime startDate);

    @Select("SELECT status, COUNT(*) as count FROM orders " +
            "WHERE deleted = 0 GROUP BY status")
    List<Map<String, Object>> selectOrderStatusDistribution();

    /**
     * 看板 stats 订单维度聚合（#2886 性能优化：替代原来 8 次串行 selectCount/selectList）。
     * 一次查询返回：总订单数 / 今日订单数+销售额 / 昨日订单数+销售额 / 本月营收 / 上月营收 / 待发货订单数。
     * 租户条件由 TenantLineInnerInterceptor 自动注入（与 selectOrderTrend 同模式）。
     */
    @Select("SELECT " +
            "COUNT(*) AS total_orders, " +
            "COUNT(*) FILTER (WHERE created_at >= #{todayStart} AND created_at < #{tomorrowStart}) AS today_orders, " +
            "COUNT(*) FILTER (WHERE created_at >= #{yesterdayStart} AND created_at < #{todayStart}) AS yesterday_orders, " +
            "COALESCE(SUM(total_amount) FILTER (WHERE created_at >= #{todayStart} AND created_at < #{tomorrowStart}), 0) AS today_sales, " +
            "COALESCE(SUM(total_amount) FILTER (WHERE created_at >= #{yesterdayStart} AND created_at < #{todayStart}), 0) AS yesterday_sales, " +
            "COALESCE(SUM(total_amount) FILTER (WHERE created_at >= #{monthStart} AND status IN ('confirmed','producing','shipped','completed')), 0) AS month_revenue, " +
            "COALESCE(SUM(total_amount) FILTER (WHERE created_at >= #{lastMonthStart} AND created_at < #{monthStart} AND status IN ('confirmed','producing','shipped','completed')), 0) AS last_month_revenue, " +
            "COUNT(*) FILTER (WHERE status IN ('confirmed','producing')) AS pending_ship " +
            "FROM orders WHERE deleted = 0")
    Map<String, Object> selectDashboardOrderStats(
            @Param("todayStart") OffsetDateTime todayStart,
            @Param("tomorrowStart") OffsetDateTime tomorrowStart,
            @Param("yesterdayStart") OffsetDateTime yesterdayStart,
            @Param("monthStart") OffsetDateTime monthStart,
            @Param("lastMonthStart") OffsetDateTime lastMonthStart);
}
