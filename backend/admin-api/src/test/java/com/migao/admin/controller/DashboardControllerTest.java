// case_ids: DA-001, DA-002, DA-003, DA-006

package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.config.GlobalExceptionHandler;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.entity.*;
import com.migao.admin.mapper.*;
import com.migao.admin.service.ProductService;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import com.migao.admin.time.BusinessClock;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Map;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

/**
 * DashboardController 单元测试
 * 验证统计数据接口的正确响应结构和租户隔离
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("DashboardController 统计接口测试")
class DashboardControllerTest {

    private MockMvc mockMvc;
    private final ObjectMapper objectMapper = new ObjectMapper();

    @Mock
    private ProductMapper productMapper;

    @Mock
    private OrderMapper orderMapper;

    @Mock
    private UserMapper userMapper;

    @Mock
    private AfterSalesTicketMapper afterSalesTicketMapper;

    @Mock
    private SessionMapper sessionMapper;

    @Mock
    private OrderItemMapper orderItemMapper;

    @Mock
    private SessionMessageMapper sessionMessageMapper;

    @Mock
    private ProductSkuMapper productSkuMapper;

    @Mock
    private ProductService productService;

    @InjectMocks
    private DashboardController dashboardController;

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(1L);
        mockMvc = MockMvcBuilders.standaloneSetup(dashboardController)
                .setControllerAdvice(new GlobalExceptionHandler())
                .build();
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    @Nested
    @DisplayName("GET /api/admin/dashboard/stats")
    class GetStats {

        /** #2886：一次性 stub 聚合查询（原 17 次串行查询的 mock 全部移除） */
        private void stubAggregations() {
            when(orderMapper.selectDashboardOrderStats(any(), any(), any(), any(), any(), any())).thenReturn(Map.of(
                    "total_orders", 50L,
                    "today_orders", 5L,
                    "yesterday_orders", 3L,
                    "today_sales", new BigDecimal("1000"),
                    "yesterday_sales", new BigDecimal("800"),
                    "month_revenue", new BigDecimal("10000"),
                    "last_month_revenue", new BigDecimal("9000"),
                    "pending_ship", 10L));
            when(userMapper.selectDashboardUserStats(any())).thenReturn(Map.of(
                    "total_customers", 200L,
                    "new_customers_today", 10L));
            when(sessionMapper.selectDashboardSessionStats(any())).thenReturn(Map.of(
                    "active_sessions", 3L,
                    "ai_sessions", 2L));
            when(orderItemMapper.selectProcessingPendingOrdersCount()).thenReturn(5L);
            when(productMapper.selectCount(any())).thenReturn(100L);
            when(afterSalesTicketMapper.selectCount(any())).thenReturn(15L);
            when(productService.getLowStockSkuCount(eq(1L), eq(100))).thenReturn(8L);
        }

        @Test
        @DisplayName("返回完整统计数据 -> 200（#2886 聚合查询）")
        void returnFullStats() throws Exception {
            stubAggregations();

            // when & then
            mockMvc.perform(get("/api/admin/dashboard/stats"))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.success").value(true))
                    .andExpect(jsonPath("$.data.totalProducts").value(100))
                    .andExpect(jsonPath("$.data.totalOrders").value(50))
                    .andExpect(jsonPath("$.data.todayOrders").value(5))
                    .andExpect(jsonPath("$.data.todaySales").value(1000))
                    .andExpect(jsonPath("$.data.todayOrdersChange").value(66.7))
                    .andExpect(jsonPath("$.data.totalCustomers").value(200))
                    .andExpect(jsonPath("$.data.newCustomersToday").value(10))
                    .andExpect(jsonPath("$.data.activeSessions").value(3))
                    .andExpect(jsonPath("$.data.aiSessionRate").value(66.7))
                    .andExpect(jsonPath("$.data.monthRevenue").value(10000))
                    .andExpect(jsonPath("$.data.totalTickets").value(15))
                    .andExpect(jsonPath("$.data.pendingShipOrders").value(10))
                    .andExpect(jsonPath("$.data.processingPendingOrders").value(5))
                    .andExpect(jsonPath("$.data.lowStockItems").value(8));
        }

        @Test
        @DisplayName("小数销售额舍入口径一致：todaySales 与 monthRevenue 均四舍五入（P2-3）")
        void decimalSalesRoundingConsistent() throws Exception {
            // given: 今日订单 119.8 元（如 59.9×2），本月订单 100.2 元
            when(orderMapper.selectDashboardOrderStats(any(), any(), any(), any(), any(), any())).thenReturn(Map.of(
                    "total_orders", 50L,
                    "today_orders", 5L,
                    "yesterday_orders", 3L,
                    "today_sales", new BigDecimal("119.8"),
                    "yesterday_sales", new BigDecimal("0"),
                    "month_revenue", new BigDecimal("100.2"),
                    "last_month_revenue", new BigDecimal("0"),
                    "pending_ship", 10L));
            when(userMapper.selectDashboardUserStats(any())).thenReturn(Map.of(
                    "total_customers", 200L,
                    "new_customers_today", 10L));
            when(sessionMapper.selectDashboardSessionStats(any())).thenReturn(Map.of(
                    "active_sessions", 3L,
                    "ai_sessions", 2L));
            when(orderItemMapper.selectProcessingPendingOrdersCount()).thenReturn(5L);
            when(productMapper.selectCount(any())).thenReturn(100L);
            when(afterSalesTicketMapper.selectCount(any())).thenReturn(15L);
            when(productService.getLowStockSkuCount(eq(1L), eq(100))).thenReturn(8L);

            // when & then
            mockMvc.perform(get("/api/admin/dashboard/stats"))
                    .andExpect(status().isOk())
                    // todaySales: 119.8 → HALF_UP → 120（不得截断为 119）
                    .andExpect(jsonPath("$.data.todaySales").value(120))
                    // monthRevenue: 100.2 → HALF_UP → 100
                    .andExpect(jsonPath("$.data.monthRevenue").value(100));
        }

        @Test
        @DisplayName("#2886 回归防护：stats 订单维度只发 1 次聚合查询，不再触发逐指标 selectCount/selectList")
        void singleAggregationQueryForOrders() throws Exception {
            stubAggregations();

            mockMvc.perform(get("/api/admin/dashboard/stats"))
                    .andExpect(status().isOk());

            // 聚合一次；不得回退到原 17 次串行查询模式
            verify(orderMapper, times(1)).selectDashboardOrderStats(any(), any(), any(), any(), any(), any());
            verify(orderMapper, never()).selectCount(any());
            verify(orderMapper, never()).selectList(any());
            verify(orderItemMapper, never()).selectList(any());
            verify(userMapper, never()).selectCount(any());
            verify(sessionMapper, never()).selectCount(any());
        }

        @Test
        @DisplayName("issue #5792：本月营收窗口**必须有上界**（与上月窗口对称）—— 未来创建时间的单不得虚增本月")
        void monthRevenueWindowHasUpperBound() throws Exception {
            stubAggregations();

            mockMvc.perform(get("/api/admin/dashboard/stats"))
                    .andExpect(status().isOk());

            ArgumentCaptor<OffsetDateTime> monthStart = ArgumentCaptor.forClass(OffsetDateTime.class);
            ArgumentCaptor<OffsetDateTime> nextMonthStart = ArgumentCaptor.forClass(OffsetDateTime.class);
            // 🔴 缺陷形态（改前）：`month_revenue` 的 FILTER 只有 `created_at >= monthStart`，
            //    而上月那条**有**上界 ⇒ 同页两个口径不对称：任何未来时间的单都落进「本月」，
            //    「环比」因此系统性偏高。判据 = 控制器必须把**本月上界**也传下去。
            // ⚠️ 参数序（与接口签名逐字对齐）：todayStart, tomorrowStart, yesterdayStart,
            //    monthStart, nextMonthStart, lastMonthStart —— captor 必须在第 4/5 位
            verify(orderMapper, times(1)).selectDashboardOrderStats(
                    any(), any(), any(), monthStart.capture(), nextMonthStart.capture(), any());

            BusinessClock clock = new BusinessClock();
            LocalDate today = clock.today();
            LocalDate firstOfMonth = today.withDayOfMonth(1);
            // 参数语义逐条钉死：本月起点 = 当月 1 日 00:00（含）、本月上界 = 下月 1 日 00:00（不含）
            org.junit.jupiter.api.Assertions.assertEquals(
                    firstOfMonth, monthStart.getValue().toLocalDate(),
                    "monthStart 必须是当月 1 日 00:00（业务时区）");
            // ⚠️ 本仓 `BusinessClock.startOfDay()` 返回的是**带 +08 偏移**的 OffsetDateTime（不是 UTC 0）
            //    —— 我第一版把它按 UTC 偏移断言，属于**判据写错**（不是实现错），此处按真实约定钉死。
            org.junit.jupiter.api.Assertions.assertEquals(8 * 3600, monthStart.getValue().getOffset().getTotalSeconds(),
                    "monthStart 的偏移必须是 +08（业务时区）；写成 UTC 会让「本月」边界与页面口径差 8 小时");
            org.junit.jupiter.api.Assertions.assertEquals(8 * 3600, nextMonthStart.getValue().getOffset().getTotalSeconds(),
                    "本月上界的偏移同样必须是 +08");
            org.junit.jupiter.api.Assertions.assertNotNull(nextMonthStart.getValue(),
                    "本月上界（下月 1 日 00:00）必须传给 SQL —— 缺失即未来单虚增本月（issue #5792）");
            org.junit.jupiter.api.Assertions.assertEquals(
                    firstOfMonth.plusMonths(1), nextMonthStart.getValue().toLocalDate(),
                    "本月上界必须是下月 1 日 00:00（不含），与上月窗口的右界写法对称");
        }
    }

    @Nested
    @DisplayName("GET /api/admin/dashboard/order-trend")
    class GetOrderTrend {

        @Test
        @DisplayName("返回7天趋势数据 -> 200")
        void return7DayTrend() throws Exception {
            when(orderMapper.selectOrderTrend(any())).thenReturn(List.of());

            mockMvc.perform(get("/api/admin/dashboard/order-trend"))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.success").value(true))
                    .andExpect(jsonPath("$.data").isArray())
                    .andExpect(jsonPath("$.data.length()").value(7));
        }

        @Test
        @DisplayName("支持自定义天数参数 -> 200")
        void customDays() throws Exception {
            when(orderMapper.selectOrderTrend(any())).thenReturn(List.of());

            mockMvc.perform(get("/api/admin/dashboard/order-trend").param("days", "30"))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.data.length()").value(30));
        }
    }

    @Nested
    @DisplayName("GET /api/admin/dashboard/order-status")
    class GetOrderStatusDistribution {

        @Test
        @DisplayName("返回状态分布数据 -> 200")
        void returnStatusDistribution() throws Exception {
            when(orderMapper.selectOrderStatusDistribution()).thenReturn(List.of());

            mockMvc.perform(get("/api/admin/dashboard/order-status"))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.success").value(true))
                    .andExpect(jsonPath("$.data").isArray());
        }

        @Test
        @DisplayName("真实订单状态映射为中文标签 -> 200")
        void returnRealStatusLabels() throws Exception {
            when(orderMapper.selectOrderStatusDistribution()).thenReturn(List.of(
                    Map.of("status", "confirmed", "count", 3L),
                    Map.of("status", "producing", "count", 2L),
                    Map.of("status", "pending", "count", 1L)
            ));

            mockMvc.perform(get("/api/admin/dashboard/order-status"))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.success").value(true))
                    .andExpect(jsonPath("$.data[0].status").value("confirmed"))
                    .andExpect(jsonPath("$.data[0].label").value("待发货"))
                    .andExpect(jsonPath("$.data[0].count").value(3))
                    .andExpect(jsonPath("$.data[1].status").value("producing"))
                    .andExpect(jsonPath("$.data[1].label").value("生产中"))
                    .andExpect(jsonPath("$.data[2].status").value("pending"))
                    .andExpect(jsonPath("$.data[2].label").value("待付款"));
        }
    }

    @Nested
    @DisplayName("GET /api/admin/dashboard/recent-orders")
    class GetRecentOrders {

        @Test
        @DisplayName("返回最近订单列表 -> 200")
        void returnRecentOrders() throws Exception {
            when(orderMapper.selectList(any())).thenReturn(List.of());

            mockMvc.perform(get("/api/admin/dashboard/recent-orders"))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.success").value(true))
                    .andExpect(jsonPath("$.data").isArray());
        }
    }

    @Nested
    @DisplayName("GET /api/admin/dashboard/active-sessions")
    class GetActiveSessions {

        @Test
        @DisplayName("返回活跃会话列表 -> 200")
        void returnActiveSessions() throws Exception {
            when(sessionMapper.selectList(any())).thenReturn(List.of());

            mockMvc.perform(get("/api/admin/dashboard/active-sessions"))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.success").value(true))
                    .andExpect(jsonPath("$.data").isArray());
        }

        @Test
        @DisplayName("#2886 批量取客户与最后消息（替代 N+1），并回填名称与摘要")
        void batchResolveCustomerAndLastMessage() throws Exception {
            // given: 2 个会话，1 个有客户、1 个无客户
            Session s1 = new Session();
            s1.setId("sess-1");
            s1.setCustomerId("cust-1");
            s1.setChannel("web");
            s1.setAiEnabled(true);
            s1.setStartedAt(OffsetDateTime.now(ZoneOffset.UTC).minusMinutes(10));
            Session s2 = new Session();
            s2.setId("sess-2");
            s2.setCustomerId(null);
            when(sessionMapper.selectList(any())).thenReturn(List.of(s1, s2));
            User c1 = new User();
            c1.setId("cust-1");
            c1.setNickname("王老板");
            when(userMapper.selectBatchIds(any())).thenReturn(List.of(c1));
            when(sessionMessageMapper.selectLastMessageBySessionIds(any())).thenReturn(List.of(
                    Map.of("session_id", "sess-1", "content", "这批面料多少钱")));

            mockMvc.perform(get("/api/admin/dashboard/active-sessions"))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.data[0].customerName").value("王老板"))
                    .andExpect(jsonPath("$.data[0].lastMessage").value("这批面料多少钱"))
                    .andExpect(jsonPath("$.data[0].ai").value(true))
                    .andExpect(jsonPath("$.data[1].customerName").value("未知客户"));

            // #2886 回归防护：不再走每会话 selectById / selectList 的 N+1
            verify(userMapper, never()).selectById(any());
            verify(sessionMessageMapper, never()).selectList(any());
        }
    }

    @Nested
    @DisplayName("GET /api/admin/dashboard/pending-tasks")
    class GetPendingTasks {

        @Test
        @DisplayName("返回待处理任务列表 -> 200")
        void returnPendingTasks() throws Exception {
            when(orderMapper.selectList(any())).thenReturn(List.of());
            when(afterSalesTicketMapper.selectList(any())).thenReturn(List.of());

            mockMvc.perform(get("/api/admin/dashboard/pending-tasks"))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.success").value(true))
                    .andExpect(jsonPath("$.data").isArray());
        }
    }

    @Nested
    @DisplayName("GET /api/admin/dashboard/product-ranking")
    class GetProductRanking {

        @Test
        @DisplayName("返回商品销量排行 -> 200")
        void returnProductRanking() throws Exception {
            when(orderItemMapper.selectProductRanking(any(), anyInt())).thenReturn(List.of());

            mockMvc.perform(get("/api/admin/dashboard/product-ranking"))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.success").value(true))
                    .andExpect(jsonPath("$.data").isArray());
        }

        @Test
        @DisplayName("#2886 排行聚合 + 上期销量 IN 批量 + dailyChange 计算")
        void rankingAggregationAndPrevQty() throws Exception {
            when(orderItemMapper.selectProductRanking(any(), anyInt())).thenReturn(List.of(
                    Map.of("product_id", "p1", "product_name", "2699色卡", "qty", 30L, "amt", 12000L),
                    Map.of("product_id", "p2", "product_name", "窗帘轨道", "qty", 20L, "amt", 8000L)));
            when(orderItemMapper.selectPrevPeriodQuantities(any(), any(), any())).thenReturn(List.of(
                    Map.of("product_id", "p1", "qty", 20L)));

            mockMvc.perform(get("/api/admin/dashboard/product-ranking"))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.data[0].rank").value(1))
                    .andExpect(jsonPath("$.data[0].productId").value("p1"))
                    .andExpect(jsonPath("$.data[0].productName").value("2699色卡"))
                    .andExpect(jsonPath("$.data[0].salesQty").value(30))
                    .andExpect(jsonPath("$.data[0].salesAmount").value(12000))
                    // (30-20)/20*100 = 50.0
                    .andExpect(jsonPath("$.data[0].dailyChange").value(50.0))
                    // p2 无上期数据 → 0
                    .andExpect(jsonPath("$.data[1].dailyChange").value(0.0));

            // #2886 回归防护：上期销量只查一次（IN 批量），不再每商品一次
            verify(orderItemMapper, times(1)).selectPrevPeriodQuantities(any(), any(), any());
            verify(orderItemMapper, never()).selectList(any());
        }

        @Test
        @DisplayName("issue #5792：排行窗口 = **近 7 天**（含今天），不是 8 天 —— 与文案/`title` 对外承诺取齐")
        void rankingWindowIsSevenDaysInclusive() throws Exception {
            // ⚠️ 判据自证：必须有**真实商品行** —— 上期查询只在 productIds 非空时才发
            //    （stub 成空列表 ⇒ `selectPrevPeriodQuantities` 压根不调用，断言会在「没发生」上失败，
            //     那是我判据写错、不是实现错。第一次就是这么错的）
            when(orderItemMapper.selectProductRanking(any(), anyInt())).thenReturn(List.of(
                    Map.of("product_id", "p1", "product_name", "测试商品", "qty", 10L, "amt", 1000L)));

            mockMvc.perform(get("/api/admin/dashboard/product-ranking"))
                    .andExpect(status().isOk());

            ArgumentCaptor<OffsetDateTime> periodStart = ArgumentCaptor.forClass(OffsetDateTime.class);
            ArgumentCaptor<OffsetDateTime> prevStart = ArgumentCaptor.forClass(OffsetDateTime.class);
            verify(orderItemMapper, times(1)).selectProductRanking(periodStart.capture(), anyInt());
            verify(orderItemMapper, times(1)).selectPrevPeriodQuantities(any(), prevStart.capture(), periodStart.capture());

            BusinessClock clock = new BusinessClock();
            LocalDate today = clock.today();
            // 🔴 缺陷形态（改前）：`startOfDay(today - 7d)` 且查询无上界 ⇒ 窗口 = 今天 + 前 7 天 = **8 天**，
            //    而前端文案与 th 的 title 都写「近7天」⇒「近 7 天含今天」= 起点应为 today-6。
            org.junit.jupiter.api.Assertions.assertEquals(
                    today.minusDays(6), periodStart.getValue().toLocalDate(),
                    "排行本期起点必须是 today-6（近 7 天**含今天**）；today-7 即 8 天，与文案不符");
            // 上一统计周期 = 紧邻的等长 7 天：[today-13, today-7)
            org.junit.jupiter.api.Assertions.assertEquals(
                    today.minusDays(13), prevStart.getValue().toLocalDate(),
                    "上一统计周期必须与本期**等长**（7 天）且紧邻其前");
            org.junit.jupiter.api.Assertions.assertEquals(
                    7, java.time.temporal.ChronoUnit.DAYS.between(
                            prevStart.getValue().toLocalDate(), periodStart.getValue().toLocalDate()),
                    "本期起点 - 上期起点 = 7 天（两窗等长且不重叠）");
        }
    }

    private static Order mockOrder(long amount) {
        Order o = new Order();
        o.setId("order-1");
        o.setOrderNo("ORD-001");
        o.setTotalAmount(BigDecimal.valueOf(amount));
        o.setStatus("completed");
        o.setCustomerName("测试客户");
        o.setCustomerPhone("13800000000");
        return o;
    }

    private static Order mockOrderDecimal(String amount) {
        Order o = mockOrder(0L);
        o.setTotalAmount(new BigDecimal(amount));
        return o;
    }
}
