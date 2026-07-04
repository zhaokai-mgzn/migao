package com.migao.admin.controller;

import com.migao.admin.dto.*;
import com.migao.admin.entity.OrderLogistics;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.service.OrderLogisticsService;
import com.migao.admin.service.OrderService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.Map;

import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

/**
 * OrderController 单元测试 — 覆盖统计/跟单/支付/退款等未在 OrderIntegrationTest 中覆盖的端点。
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("OrderController 订单管理测试")
class OrderControllerTest extends BaseControllerTest {

    private MockMvc mockMvc;

    @Mock private OrderService orderService;
    @Mock private OrderLogisticsService orderLogisticsService;

    @InjectMocks
    private OrderController orderController;

    private static final String BASE = "/api/admin/orders";
    private static final String ORDER_ID = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6";

    @BeforeEach
    void setUp() {
        super.baseSetUp();
        mockMvc = buildMockMvc(orderController);
    }

    @Override
    @org.junit.jupiter.api.AfterEach
    void baseTearDown() {
        super.baseTearDown();
    }

    private OrderDetailResponse buildOrder(String id, String status) {
        OrderDetailResponse d = new OrderDetailResponse();
        d.setId(id);
        d.setOrderNo("ORD20250616001");
        d.setCustomerName("张三");
        d.setCustomerPhone("13800138000");
        d.setTotalAmount(new BigDecimal("1500.00"));
        d.setStatus(status);
        d.setCreatedAt(OffsetDateTime.now());
        d.setUpdatedAt(OffsetDateTime.now());
        return d;
    }

    // ==================== GET /api/admin/orders/statistics ====================

    @Nested
    @DisplayName("GET /api/admin/orders/statistics — 订单统计")
    class Statistics {

        @Test
        @DisplayName("获取统计 -> 200 + 完整字段")
        void getStatistics() throws Exception {
            OrderStatisticsResponse stats = OrderStatisticsResponse.builder()
                    .totalCount(100L)
                    .pendingCount(10L)
                    .confirmedCount(30L)
                    .shippedCount(25L)
                    .build();

            when(orderService.getOrderStatistics(eq(TEST_TENANT_ID))).thenReturn(stats);

            mockMvc.perform(get(BASE + "/statistics"))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.data.totalCount").value(100))
                    .andExpect(jsonPath("$.data.pendingCount").value(10));
        }
    }

    // ==================== GET /api/admin/orders/follow-status/stats ====================

    @Nested
    @DisplayName("GET /api/admin/orders/follow-status/stats — 跟单统计")
    class FollowStatusStats {

        @Test
        @DisplayName("获取跟单状态统计 -> 200")
        void getFollowStatusStats() throws Exception {
            FollowStatusStatsResponse stats = FollowStatusStatsResponse.builder()
                    .pending(5L).following(20L).build();

            when(orderService.getFollowStatusStats(eq(TEST_TENANT_ID))).thenReturn(stats);

            mockMvc.perform(get(BASE + "/follow-status/stats"))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.data.pending").value(5));
        }
    }

    // ==================== PUT /api/admin/orders/{id}/payment ====================

    @Nested
    @DisplayName("PUT /api/admin/orders/{id}/payment — 确认收款")
    class Payment {

        @Test
        @DisplayName("确认收款成功 -> 200")
        void confirmPayment() throws Exception {
            doNothing().when(orderService).confirmPayment(ORDER_ID);

            mockMvc.perform(put(BASE + "/" + ORDER_ID + "/payment"))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.success").value(true));

            verify(orderService).confirmPayment(ORDER_ID);
        }

        @Test
        @DisplayName("订单不存在时确认收款 -> 404")
        void confirmPaymentNotFound() throws Exception {
            doThrow(new BusinessException("NOT_FOUND", "订单不存在", 404))
                    .when(orderService).confirmPayment("nonexistent");

            mockMvc.perform(put(BASE + "/nonexistent/payment"))
                    .andExpect(status().isNotFound());
        }
    }

    // ==================== PUT /api/admin/orders/{id}/refund ====================

    @Nested
    @DisplayName("PUT /api/admin/orders/{id}/refund — 退款")
    class Refund {

        @Test
        @DisplayName("退款成功 -> 200")
        void refund() throws Exception {
            doNothing().when(orderService).refundOrder(eq(ORDER_ID), isNull());

            mockMvc.perform(put(BASE + "/" + ORDER_ID + "/refund"))
                    .andExpect(status().isOk());

            verify(orderService).refundOrder(eq(ORDER_ID), isNull());
        }

        @Test
        @DisplayName("非可退款状态退款 -> 400")
        void refundInvalidStatus() throws Exception {
            doThrow(new BusinessException("INVALID_STATUS", "当前状态不允许退款", 400))
                    .when(orderService).refundOrder(eq(ORDER_ID), isNull());

            mockMvc.perform(put(BASE + "/" + ORDER_ID + "/refund"))
                    .andExpect(status().isBadRequest());
        }
    }

    // ==================== GET/PUT /api/admin/orders/{id}/follow-status ====================

    @Nested
    @DisplayName("GET/PUT /api/admin/orders/{id}/follow-status — 跟单状态")
    class FollowStatus {

        @Test
        @DisplayName("获取跟单状态 -> 200")
        void getFollowStatus() throws Exception {
            FollowStatusResponse resp = FollowStatusResponse.builder()
                    .followStatus("pending")
                    .updatedAt(OffsetDateTime.now())
                    .build();

            when(orderService.getFollowStatus(ORDER_ID)).thenReturn(resp);

            mockMvc.perform(get(BASE + "/" + ORDER_ID + "/follow-status"))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.data.followStatus").value("pending"));
        }

        @Test
        @DisplayName("更新跟单状态 -> 200")
        void updateFollowStatus() throws Exception {
            doNothing().when(orderService).updateFollowStatus(eq(ORDER_ID), eq("followed"));

            String body = "{\"followStatus\":\"followed\",\"remark\":\"已联系客户\"}";

            mockMvc.perform(put(BASE + "/" + ORDER_ID + "/follow-status")
                            .contentType(MediaType.APPLICATION_JSON).content(body))
                    .andExpect(status().isOk());
        }
    }

    // ==================== 租户隔离 ====================

    @Nested
    @DisplayName("租户隔离验证")
    class TenantIsolation {

        @Test
        @DisplayName("列表查询携带租户 ID")
        void listPassesTenantId() throws Exception {
            when(orderService.getOrderPage(anyLong(), anyLong(), isNull(), isNull(), isNull(),
                    isNull(), isNull(), isNull(), isNull(), isNull(), isNull(), isNull(), eq(TEST_TENANT_ID)))
                    .thenReturn(PageResponse.of(0L, 1L, 20L, List.of()));

            mockMvc.perform(get(BASE));

            verify(orderService).getOrderPage(anyLong(), anyLong(), isNull(), isNull(), isNull(),
                    isNull(), isNull(), isNull(), isNull(), isNull(), isNull(), isNull(), eq(TEST_TENANT_ID));
        }

        @Test
        @DisplayName("创建订单携带租户 ID")
        void createPassesTenantId() throws Exception {
            when(orderService.createOrder(any(OrderCreateRequest.class), eq(TEST_TENANT_ID)))
                    .thenReturn(buildOrder(ORDER_ID, "pending"));

            String body = """
                    {"customerName":"张三","customerPhone":"13800138000","items":[{"productId":"prod-001","productName":"窗帘","quantity":1,"unitPrice":100,"subtotal":100}]}
                    """;

            mockMvc.perform(post(BASE).contentType(MediaType.APPLICATION_JSON).content(body));

            verify(orderService).createOrder(any(OrderCreateRequest.class), eq(TEST_TENANT_ID));
        }
    }
}
