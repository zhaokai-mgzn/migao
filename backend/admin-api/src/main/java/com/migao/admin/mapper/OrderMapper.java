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
     * 一次查询返回：总订单数 / 今日订单数+销售额 / 昨日订单数+销售额 / 本月营收 / 上月营收 / 待发货订单数 / 待支付订单数。
     *
     * <p>🔴 issue #5792：**本月营收必须带上界**（`created_at < nextMonthStart`）——
     * 改前只有下界，而上月那条**有**上界 ⇒ 同页两个口径不对称：任何**未来创建时间**的订单
     * 都会落进「本月」，使「环比」系统性偏高。本参数与 {@code lastMonthStart} 的右界写法对称。</p>
     * 租户条件由 TenantLineInnerInterceptor 自动注入（与 selectOrderTrend 同模式）。
     */
    @Select("SELECT " +
            "COUNT(*) AS total_orders, " +
            "COUNT(*) FILTER (WHERE created_at >= #{todayStart} AND created_at < #{tomorrowStart}) AS today_orders, " +
            "COUNT(*) FILTER (WHERE created_at >= #{yesterdayStart} AND created_at < #{todayStart}) AS yesterday_orders, " +
            // 🔴 issue #5792 口径整改：销售额**只算四态**（confirmed/producing/shipped/completed），
            // 与「本月营收」同口径。改前今日/昨日销售额**无状态过滤** ⇒ 未付款、已取消/关闭的单也算进
            // 「今日销售额」，而同页的「本月销售额」不含 ⇒ 两个「销售额」用两套口径，商家无法解释差异。
            "COALESCE(SUM(total_amount) FILTER (WHERE created_at >= #{todayStart} AND created_at < #{tomorrowStart} AND status IN ('confirmed','producing','shipped','completed')), 0) AS today_sales, " +
            "COALESCE(SUM(total_amount) FILTER (WHERE created_at >= #{yesterdayStart} AND created_at < #{todayStart} AND status IN ('confirmed','producing','shipped','completed')), 0) AS yesterday_sales, " +
            "COALESCE(SUM(total_amount) FILTER (WHERE created_at >= #{monthStart} AND created_at < #{nextMonthStart} AND status IN ('confirmed','producing','shipped','completed')), 0) AS month_revenue, " +
            "COALESCE(SUM(total_amount) FILTER (WHERE created_at >= #{lastMonthStart} AND created_at < #{monthStart} AND status IN ('confirmed','producing','shipped','completed')), 0) AS last_month_revenue, " +
            "COUNT(*) FILTER (WHERE status IN ('confirmed','producing')) AS pending_ship, " +
            // issue #5792 第二阶段：待支付订单数（问题面：钱还没到）。
            // ⚠️ 不能用 `/dashboard/pending-tasks` 代替 —— 那是**任务列表**且每类上限 5 条，
            //    拿它当计数会把「≤5」误报成总数。
            "COUNT(*) FILTER (WHERE status = 'pending') AS pending_payment_orders " +
            "FROM orders WHERE deleted = 0")
    Map<String, Object> selectDashboardOrderStats(
            @Param("todayStart") OffsetDateTime todayStart,
            @Param("tomorrowStart") OffsetDateTime tomorrowStart,
            @Param("yesterdayStart") OffsetDateTime yesterdayStart,
            @Param("monthStart") OffsetDateTime monthStart,
            @Param("nextMonthStart") OffsetDateTime nextMonthStart,
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

    /**
     * 定时腿（发货后 N 天自动完成，issue #6262）的**租户入口**：哪些租户可能还有在架的已发货单。
     *
     * <p>调度线程没有请求上下文（也就没有租户上下文），而 {@code orders} 是租户隔离表 ⇒
     * 要逐个租户去扫，先得知道「有哪些租户可能有在架 shipped」。本查询就是那个入口
     * —— **一条索引查询**（{@code idx_orders_tenant_status_shipped_at}）替代「遍历全部租户」。</p>
     *
     * <p>它是**超集**预筛（只按状态 + 未删，不看是否满 N 天）—— 方向是刻意的：
     * 预筛若比判定更严，就会造出「到期却永远扫不到」的静默漏单。</p>
     *
     * <p>{@code @InterceptorIgnore(tenantLine = "true")} 是必须的（本查询**故意跨租户**，
     * 它的产物就是租户 id 列表），留下的 WHERE 是纯字面条件、不读租户上下文 ⇒
     * 禁用拦截器**不削弱隔离**（与 {@link #selectConfirmedTenantIds()} 同款处置）。</p>
     */
    @InterceptorIgnore(tenantLine = "true")
    @Select("SELECT DISTINCT tenant_id FROM orders WHERE status = 'shipped' AND deleted = 0")
    List<Long> selectShippedTenantIds();

    /**
     * 🔴 <b>自动完成的核心写面（issue #6262）：<u>一条</u>带谓词的原子 UPDATE + {@code RETURNING id}。</b>
     *
     * <p><b>为什么必须是这个形态</b>（不是"看着优雅"）：</p>
     * <ul>
     *   <li><b>并发只生效一次</b>：谓词 {@code status='shipped' AND shipped_at <= 死线} 由
     *       PG 在**行锁下重估** ⇒ 人工「确认收货」与自动扫描（乃至**集群里 N 个实例**同时扫）
     *       并发时，每一行只有一个事务能改到；拿 0 行的那一侧**什么都不发生**（不是报错）。</li>
     *   <li><b>副作用绑定"真正改了行"</b>：{@code RETURNING id} 只回**本次真的被流转的行**
     *       ⇒ 站内信只对它们发（否则集群下每个实例各发一遍）。</li>
     *   <li><b>单机与集群同一套代码</b>：不需要 leader 选举 / 分布式锁 / 开关
     *       —— 幂等来自这条 SQL 本身，不来自"哪个实例在跑"。</li>
     *   <li><b>不靠 {@code OrderStatusTransitions} 之外的第二张流转表</b>：本 SQL 的
     *       {@code 'shipped' → 'completed'} 与流转表同一条边（既有边，本单**不扩充**流转表）；
     *       调用方在跑之前先过 {@code OrderStatusTransitions.assertTransitionAllowed("shipped","completed")}
     *       —— 判定本体仍只有一份。</li>
     * </ul>
     *
     * <p>{@code @InterceptorIgnore(tenantLine = "true")} + <b>显式</b> {@code tenant_id = #{tenantId}}：
     * 定制 SQL 的租户条件由调用方显式给出（与 {@code selectShippedTenantIds} 同一套口径），
     * 不靠拦截器替我加 —— 少一层"条件到底加没加"的不可见性。</p>
     *
     * <p>{@code deleted = 0} 是显式写出的（逻辑删除表）—— 不指望别的层替我过滤。</p>
     *
     * <p>🔴 <b>为什么是 {@code @Select} + CTE 而不是 {@code @Update}</b>（实测，不是口味）：
     * MyBatis 的 {@code @Update} **只接受 int/long/boolean/void 返回类型** —— 想要
     * {@code RETURNING id} 的行，声明 {@code List<String>} 会当场抛
     * {@code BindingException: unsupported return type}（本单第一版实测撞到，真库判据整类红）。
     * 把 {@code WITH done AS (UPDATE ... RETURNING id) SELECT id FROM done} 写成 {@code @Select}
     * 就同时拿到两样东西：<b>仍然只有一条 SQL 语句</b>（PG 的 CTE 里 UPDATE 与 SELECT 同一快照、
     * 同一事务），且返回类型是 MyBatis 支持的 {@code List<String>}。</p>
     *
     * @param tenantId 只动本租户（多租户隔离的**显式**条件）
     * @param deadline 死线 = 业务「现在」− N 天（由调用方用 {@code BusinessClock} 算出）
     * @return 本次**真正**被流转成 {@code completed} 的订单 id（0 行 = 本轮无单满期 / 已被人工抢先）
     */
    @InterceptorIgnore(tenantLine = "true")
    @Select("WITH done AS ("
            + "UPDATE orders SET status = 'completed', updated_at = NOW() "
            + "WHERE tenant_id = #{tenantId} AND status = 'shipped' AND deleted = 0 "
            + "AND shipped_at IS NOT NULL AND shipped_at <= #{deadline} "
            + "RETURNING id"
            + ") SELECT id FROM done")
    List<String> autoCompleteShippedOrders(@Param("tenantId") Long tenantId,
                                           @Param("deadline") OffsetDateTime deadline);
}
