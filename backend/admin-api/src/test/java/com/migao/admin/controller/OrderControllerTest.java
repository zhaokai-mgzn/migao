// case_ids: OR-001, OR-002, OR-003, OR-004, OR-005, OR-006, OR-011

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
            doNothing().when(orderService).refundOrder(eq(ORDER_ID), isNull(), isNull());

            mockMvc.perform(put(BASE + "/" + ORDER_ID + "/refund"))
                    .andExpect(status().isOk());

            verify(orderService).refundOrder(eq(ORDER_ID), isNull(), isNull());
        }

        @Test
        @DisplayName("退款成功 - 携带金额与原因 -> 200")
        void refundWithAmountAndReason() throws Exception {
            doNothing().when(orderService).refundOrder(eq(ORDER_ID),
                    argThat(bd -> bd != null && bd.compareTo(new BigDecimal("100.00")) == 0),
                    eq("部分退款"));

            mockMvc.perform(put(BASE + "/" + ORDER_ID + "/refund")
                            .contentType(MediaType.APPLICATION_JSON)
                            .content("{\"refund_amount\": 100.00, \"refund_reason\": \"部分退款\"}"))
                    .andExpect(status().isOk());

            verify(orderService).refundOrder(eq(ORDER_ID),
                    argThat(bd -> bd != null && bd.compareTo(new BigDecimal("100.00")) == 0),
                    eq("部分退款"));
        }

        @Test
        @DisplayName("非可退款状态退款 -> 400")
        void refundInvalidStatus() throws Exception {
            doThrow(new BusinessException("INVALID_STATUS", "当前状态不允许退款", 400))
                    .when(orderService).refundOrder(eq(ORDER_ID), isNull(), isNull());

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
                    isNull(), isNull(), isNull(), isNull(), isNull(), isNull(), isNull(), eq(TEST_TENANT_ID), isNull()))
                    .thenReturn(PageResponse.of(0L, 1L, 20L, List.of()));

            mockMvc.perform(get(BASE));

            verify(orderService).getOrderPage(anyLong(), anyLong(), isNull(), isNull(), isNull(),
                    isNull(), isNull(), isNull(), isNull(), isNull(), isNull(), isNull(), eq(TEST_TENANT_ID), isNull());
        }

        @Test
        @DisplayName("列表查询支持按 userId 过滤（C 端数据隔离）")
        void listPassesUserIdFilter() throws Exception {
            when(orderService.getOrderPage(anyLong(), anyLong(), isNull(), isNull(), isNull(),
                    isNull(), isNull(), isNull(), isNull(), isNull(), isNull(), isNull(), eq(TEST_TENANT_ID), eq("user-abc")))
                    .thenReturn(PageResponse.of(0L, 1L, 20L, List.of()));

            mockMvc.perform(get(BASE).param("userId", "user-abc"));

            verify(orderService).getOrderPage(anyLong(), anyLong(), isNull(), isNull(), isNull(),
                    isNull(), isNull(), isNull(), isNull(), isNull(), isNull(), isNull(), eq(TEST_TENANT_ID), eq("user-abc"));
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

        @Test
        @DisplayName("创建订单 — 手机号格式非法 -> 400（订单必须携带有效手机号）")
        void createRejectsInvalidPhone() throws Exception {
            String body = """
                    {"customerName":"张三","customerPhone":"12345","items":[{"productId":"prod-001","productName":"窗帘","quantity":1,"unitPrice":100,"subtotal":100}]}
                    """;

            mockMvc.perform(post(BASE).contentType(MediaType.APPLICATION_JSON).content(body))
                    .andExpect(status().isUnprocessableEntity());

            verifyNoInteractions(orderService);
        }
    }

    // ==================== POST /api/admin/orders 数量下限（issue #3682） ====================

    /**
     * 表单路径的**订单数量下限**（issue #3682 方案 A：下限 = 1）。
     *
     * <p>为什么表单路径也要拦：`items[].quantity` 直接驱动服务端库存/销量，而
     * `OrderService` 对 `BigDecimal quantity` 取整数部分（`:1051` 库存校验 / `:1408`
     * `deductStock` / `:1409` `increaseSalesCount`）——数量 0.5 → `needed=0` 校验恒通过、
     * `deductStock(0)` 不减库存、销量 +0，**订单成交但库存/销量零变动且无告警**。</p>
     *
     * <p>表单页虽有 `min={1}`，但该页面**没有 `&lt;form&gt;` 元素**（提交按钮是
     * `Button onClick={handleSubmit}`），原生 `min` 不参与校验，页面 JS 判据是
     * `quantity &lt;= 0` → 0.5 在表单路径同样可达。故服务端下限是这条路径的唯一硬拦。</p>
     */
    @Nested
    @DisplayName("POST /api/admin/orders — 数量下限 1（#3682）")
    class QuantityLowerBound {

        private String bodyWithQuantity(String quantity, String subtotal) {
            return String.format("""
                    {"customerName":"张三","customerPhone":"13800138000","items":[{"productId":"prod-001","productName":"窗帘","quantity":%s,"unitPrice":100,"subtotal":%s}]}
                    """, quantity, subtotal);
        }

        @Test
        @DisplayName("quantity=0.5 → 422「数量不能小于 1」（0.5 会被库存/销量按 0 件计 → 静默漏扣）")
        void subOneQuantityRejected() throws Exception {
            mockMvc.perform(post(BASE).contentType(MediaType.APPLICATION_JSON)
                            .content(bodyWithQuantity("0.5", "50")))
                    .andExpect(status().isUnprocessableEntity())
                    .andExpect(jsonPath("$.success").value(false))
                    .andExpect(jsonPath("$.error.code").value("VALIDATION_ERROR"))
                    .andExpect(jsonPath("$.error.details[0].field").value("items[0].quantity"))
                    .andExpect(jsonPath("$.error.details[0].message").value("数量不能小于 1"));

            verifyNoInteractions(orderService);
        }

        @Test
        @DisplayName("quantity=0 → 422（0 元明细与 <1 同口径）")
        void zeroQuantityRejected() throws Exception {
            // 小计用正值：否则 subtotal 的 @Positive 也会失败，字段错误顺序不确定 → 断言不稳
            mockMvc.perform(post(BASE).contentType(MediaType.APPLICATION_JSON)
                            .content(bodyWithQuantity("0", "100")))
                    .andExpect(status().isUnprocessableEntity())
                    .andExpect(jsonPath("$.error.details[0].field").value("items[0].quantity"))
                    .andExpect(jsonPath("$.error.details[0].message").value("数量不能小于 1"));

            verifyNoInteractions(orderService);
        }

        @Test
        @DisplayName("quantity=1 → 200（下限值本身必须放行）")
        void minimumQuantityOnePasses() throws Exception {
            when(orderService.createOrder(any(OrderCreateRequest.class), eq(TEST_TENANT_ID)))
                    .thenReturn(buildOrder(ORDER_ID, "pending"));

            mockMvc.perform(post(BASE).contentType(MediaType.APPLICATION_JSON)
                            .content(bodyWithQuantity("1", "100")))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.success").value(true));

            verify(orderService).createOrder(any(OrderCreateRequest.class), eq(TEST_TENANT_ID));
        }

        @Test
        @DisplayName("quantity=3 → 200（整数数量不误伤）")
        void integerQuantityPasses() throws Exception {
            when(orderService.createOrder(any(OrderCreateRequest.class), eq(TEST_TENANT_ID)))
                    .thenReturn(buildOrder(ORDER_ID, "pending"));

            mockMvc.perform(post(BASE).contentType(MediaType.APPLICATION_JSON)
                            .content(bodyWithQuantity("3", "300")))
                    .andExpect(status().isOk());

            verify(orderService).createOrder(any(OrderCreateRequest.class), eq(TEST_TENANT_ID));
        }

        @Test
        @DisplayName("quantity=8.4 → 200（OR-028 小数数量 ≥1 不误伤，仍走 DECIMAL 口径）")
        void decimalQuantityPasses() throws Exception {
            when(orderService.createOrder(any(OrderCreateRequest.class), eq(TEST_TENANT_ID)))
                    .thenReturn(buildOrder(ORDER_ID, "pending"));

            mockMvc.perform(post(BASE).contentType(MediaType.APPLICATION_JSON)
                            .content(bodyWithQuantity("8.4", "840")))
                    .andExpect(status().isOk());

            verify(orderService).createOrder(any(OrderCreateRequest.class), eq(TEST_TENANT_ID));
        }
    }
}
