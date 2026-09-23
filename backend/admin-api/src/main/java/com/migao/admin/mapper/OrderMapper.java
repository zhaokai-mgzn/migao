package com.migao.admin.mapper;

import com.migao.admin.entity.Order;
import com.baomidou.mybatisplus.annotation.InterceptorIgnore;
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

    /**
     * 定时腿（到期扫描，issue #5184）的**租户入口**：哪些租户可能还有待派订单。
     *
     * <h2>为什么是它</h2>
     * 调度线程没有请求上下文（也就没有租户上下文），而 {@code orders} 是租户隔离表 ——
     * 要逐个租户去扫，先得知道「有哪些租户可能有池」。本查询就是那个入口：
     * **一条索引查询**（{@code idx_orders_status}）替代「遍历全部租户 × 每个租户跑一次池读」。
     *
     * <h2>🔴 它是<b>超集</b>预筛，不是池的定义</h2>
     * 只按「已确认支付 + 未删」过滤 —— 已派出的单**仍在结果里**（多扫一个租户是浪费，不是错）。
     * 池的真实口径（无活跃加工单 / 有加工项 / 按物料分组）**只有一个实现**：
     * {@code ProcessingOrderService.pool(tenantId, …)}。
     * ⇒ <b>超集方向是刻意的</b>：预筛若比池更严，就会造出「到期却永远扫不到」的静默压单
     * （那是本单最不能出的错），所以这里宁可比池宽，绝不比池严。
     *
     * <h2>🔴 {@code @InterceptorIgnore(tenantLine = "true")} 是必须的</h2>
     * 本查询**故意跨租户**（它的产物就是租户 id 列表）。留下的 WHERE 是纯字面条件、
     * 不读任何租户上下文 ⇒ 禁用拦截器**不削弱隔离**（与 {@code ProcessingOrderSetMapper} /
     * {@code UserMapper} 的同名处置一致）：租户数据面（池读 / 派单）仍逐租户显式带 {@code tenantId}。
     */
    @InterceptorIgnore(tenantLine = "true")
    @Select("SELECT DISTINCT tenant_id FROM orders WHERE status = 'confirmed' AND deleted = 0")
    List<Long> selectConfirmedTenantIds();
}
