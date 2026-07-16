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
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;

import static org.mockito.ArgumentMatchers.any;
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

        @Test
        @DisplayName("返回完整统计数据 -> 200")
        void returnFullStats() throws Exception {
            // given: 所有 mapper count 返回合理数值
            when(productMapper.selectCount(any())).thenReturn(100L);
            when(orderMapper.selectCount(any())).thenReturn(50L, 5L, 3L, 10L, 5L);  // total, today, yesterday, month, pendingShipOrders
            when(orderMapper.selectList(any())).thenReturn(
                    List.of(mockOrder(1000L)),
                    List.of(mockOrder(800L)),
                    List.of(),
                    List.of(),
                    List.of()  // shipOrderIds for #387
            );
            when(userMapper.selectCount(any())).thenReturn(200L, 10L);
            when(afterSalesTicketMapper.selectCount(any())).thenReturn(15L);
            when(sessionMapper.selectCount(any())).thenReturn(3L, 2L);
            // #387: 待处理区 3 卡片
            when(orderItemMapper.selectList(any())).thenReturn(List.of());
            // #1396: 待补库存改用 ProductService 统一口径（排除已删除+已下架商品下的 SKU）
            when(productService.getLowStockSkuCount(eq(1L), eq(100))).thenReturn(8L);

            // when & then
            mockMvc.perform(get("/api/admin/dashboard/stats"))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.success").value(true))
                    .andExpect(jsonPath("$.data.totalProducts").isNumber())
                    .andExpect(jsonPath("$.data.totalOrders").isNumber())
                    .andExpect(jsonPath("$.data.todayOrders").isNumber())
                    .andExpect(jsonPath("$.data.totalCustomers").isNumber())
                    .andExpect(jsonPath("$.data.activeSessions").isNumber());
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
            when(orderItemMapper.selectList(any())).thenReturn(List.of());

            mockMvc.perform(get("/api/admin/dashboard/product-ranking"))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.success").value(true))
                    .andExpect(jsonPath("$.data").isArray());
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
}
