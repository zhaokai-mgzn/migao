package com.aikf.admin.controller;

import com.aikf.admin.config.GlobalExceptionHandler;
import com.aikf.admin.config.TenantContext;
import com.aikf.admin.dto.*;
import com.aikf.admin.exception.BusinessException;
import com.aikf.admin.service.OrderService;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.List;

import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

/**
 * 订单管理控制器集成测试
 * 覆盖：订单 CRUD、状态流转、非法状态流转拒绝
 */
@ExtendWith(MockitoExtension.class)
class OrderIntegrationTest {

    private MockMvc mockMvc;

    private final ObjectMapper objectMapper = new ObjectMapper();

    @Mock
    private OrderService orderService;

    @InjectMocks
    private OrderController orderController;

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(1L);
        mockMvc = MockMvcBuilders.standaloneSetup(orderController)
                .setControllerAdvice(new GlobalExceptionHandler())
                .build();
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    // ======================== 辅助方法 ========================

    private OrderDetailResponse buildOrderDetail(String id, String orderNo, String status) {
        OrderDetailResponse detail = new OrderDetailResponse();
        detail.setId(id);
        detail.setOrderNo(orderNo);
        detail.setCustomerName("张三");
        detail.setCustomerPhone("13800138000");
        detail.setCustomerAddress("北京市朝阳区");
        detail.setTotalAmount(new BigDecimal("1500.00"));
        detail.setStatus(status);
        detail.setRemark("测试订单");
        detail.setCreatedAt(OffsetDateTime.now());
        detail.setUpdatedAt(OffsetDateTime.now());

        OrderDetailResponse.OrderItemResponse item = new OrderDetailResponse.OrderItemResponse();
        item.setId("item-001");
        item.setProductId("prod-001");
        item.setProductName("遮光窗帘");
        item.setQuantity(2);
        item.setUnitPrice(new BigDecimal("500.00"));
        item.setWidth(new BigDecimal("2.5"));
        item.setHeight(new BigDecimal("2.8"));
        item.setSubtotal(new BigDecimal("1000.00"));
        detail.setItems(List.of(item));

        return detail;
    }

    private OrderCreateRequest buildCreateRequest() {
        OrderCreateRequest request = new OrderCreateRequest();
        request.setCustomerName("张三");
        request.setCustomerPhone("13800138000");
        request.setCustomerAddress("北京市朝阳区");
        request.setRemark("测试订单");

        OrderCreateRequest.OrderItemRequest item = new OrderCreateRequest.OrderItemRequest();
        item.setProductId("prod-001");
        item.setProductName("遮光窗帘");
        item.setQuantity(2);
        item.setUnitPrice(new BigDecimal("500.00"));
        item.setWidth(new BigDecimal("2.5"));
        item.setHeight(new BigDecimal("2.8"));
        item.setSubtotal(new BigDecimal("1000.00"));
        request.setItems(List.of(item));

        return request;
    }

    // ======================== 创建订单 ========================

    @Test
    @DisplayName("创建订单 - 包含商品明细")
    void testCreateOrder() throws Exception {
        // Given
        OrderCreateRequest request = buildCreateRequest();
        OrderDetailResponse response = buildOrderDetail("order-001", "ORD20250425001", "pending");

        when(orderService.createOrder(any(OrderCreateRequest.class), eq(1L)))
                .thenReturn(response);

        // When & Then
        mockMvc.perform(post("/api/admin/orders")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.id").value("order-001"))
                .andExpect(jsonPath("$.data.orderNo").value("ORD20250425001"))
                .andExpect(jsonPath("$.data.status").value("pending"))
                .andExpect(jsonPath("$.data.customerName").value("张三"))
                .andExpect(jsonPath("$.data.items").isArray())
                .andExpect(jsonPath("$.data.items[0].productName").value("遮光窗帘"));

        verify(orderService).createOrder(any(OrderCreateRequest.class), eq(1L));
    }

    // ======================== 查询订单列表 ========================

    @Test
    @DisplayName("获取订单列表 - 分页查询")
    void testGetOrderList() throws Exception {
        // Given
        OrderListResponse order1 = new OrderListResponse();
        order1.setId("order-001");
        order1.setOrderNo("ORD20250425001");
        order1.setCustomerName("张三");
        order1.setStatus("pending");
        order1.setTotalAmount(new BigDecimal("1500.00"));

        OrderListResponse order2 = new OrderListResponse();
        order2.setId("order-002");
        order2.setOrderNo("ORD20250425002");
        order2.setCustomerName("李四");
        order2.setStatus("confirmed");
        order2.setTotalAmount(new BigDecimal("2000.00"));

        PageResponse<OrderListResponse> pageResponse = PageResponse.of(2L, 1L, 20L, List.of(order1, order2));

        when(orderService.getOrderPage(eq(1L), eq(20L), isNull(), isNull(), eq(1L)))
                .thenReturn(pageResponse);

        // When & Then
        mockMvc.perform(get("/api/admin/orders")
                        .param("page", "1")
                        .param("size", "20")
                        .contentType(MediaType.APPLICATION_JSON))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.total").value(2))
                .andExpect(jsonPath("$.data.page").value(1))
                .andExpect(jsonPath("$.data.items").isArray())
                .andExpect(jsonPath("$.data.items[0].orderNo").value("ORD20250425001"))
                .andExpect(jsonPath("$.data.items[1].customerName").value("李四"));
    }

    // ======================== 查询订单详情 ========================

    @Test
    @DisplayName("获取订单详情 - 包含明细和物流信息")
    void testGetOrderDetail() throws Exception {
        // Given
        OrderDetailResponse detail = buildOrderDetail("order-001", "ORD20250425001", "shipped");

        OrderDetailResponse.LogisticsInfo logistics = new OrderDetailResponse.LogisticsInfo();
        logistics.setId("log-001");
        logistics.setLogisticsCompany("顺丰速运");
        logistics.setTrackingNo("SF1234567890");
        logistics.setStatus("in_transit");
        logistics.setShippedAt(OffsetDateTime.now());
        detail.setLogistics(logistics);

        when(orderService.getOrderById("order-001")).thenReturn(detail);

        // When & Then
        mockMvc.perform(get("/api/admin/orders/order-001")
                        .contentType(MediaType.APPLICATION_JSON))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.id").value("order-001"))
                .andExpect(jsonPath("$.data.status").value("shipped"))
                .andExpect(jsonPath("$.data.logistics.logisticsCompany").value("顺丰速运"))
                .andExpect(jsonPath("$.data.logistics.trackingNo").value("SF1234567890"));
    }

    // ======================== 删除（更新）订单 ========================

    @Test
    @DisplayName("删除订单 - 成功")
    void testUpdateOrder() throws Exception {
        // Given
        doNothing().when(orderService).deleteOrder("order-001");

        // When & Then
        mockMvc.perform(delete("/api/admin/orders/order-001")
                        .contentType(MediaType.APPLICATION_JSON))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true));

        verify(orderService).deleteOrder("order-001");
    }

    // ======================== 订单状态流转 ========================

    @Test
    @DisplayName("订单确认 - pending -> confirmed")
    void testUpdateOrderStatus_Confirm() throws Exception {
        // Given
        doNothing().when(orderService).updateOrderStatus("order-001", "confirmed");

        // When & Then
        mockMvc.perform(put("/api/admin/orders/order-001/status")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"status\":\"confirmed\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true));

        verify(orderService).updateOrderStatus("order-001", "confirmed");
    }

    @Test
    @DisplayName("订单进入生产 - confirmed -> producing")
    void testUpdateOrderStatus_Ship() throws Exception {
        // Given: confirmed 状态的订单进入生产
        doNothing().when(orderService).updateOrderStatus("order-001", "producing");

        // When & Then
        mockMvc.perform(put("/api/admin/orders/order-001/status")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"status\":\"producing\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true));

        verify(orderService).updateOrderStatus("order-001", "producing");
    }

    @Test
    @DisplayName("订单完成 - shipped -> completed")
    void testUpdateOrderStatus_Complete() throws Exception {
        // Given
        doNothing().when(orderService).updateOrderStatus("order-001", "completed");

        // When & Then
        mockMvc.perform(put("/api/admin/orders/order-001/status")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"status\":\"completed\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true));

        verify(orderService).updateOrderStatus("order-001", "completed");
    }

    @Test
    @DisplayName("非法状态流转被拒绝 - completed 不能回退到 pending")
    void testOrderStatusFlowValidation() throws Exception {
        // Given: Service 层抛出业务异常
        doThrow(new BusinessException("INVALID_STATUS", "非法的状态流转: completed -> pending", 400))
                .when(orderService).updateOrderStatus("order-001", "pending");

        // When & Then
        mockMvc.perform(put("/api/admin/orders/order-001/status")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"status\":\"pending\"}"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.error.code").value("INVALID_STATUS"));
    }
}
