package com.migao.admin.service;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.*;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.entity.OrderLogistics;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderLogisticsMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProductMapper;
import com.migao.admin.mapper.ProductSkuMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.math.BigDecimal;
import java.util.List;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

/**
 * OrderService 单元测试
 */
@ExtendWith(MockitoExtension.class)
class OrderServiceTest {

    @InjectMocks
    private OrderService orderService;

    @Mock
    private OrderMapper orderMapper;

    @Mock
    private OrderItemMapper orderItemMapper;

    @Mock
    private OrderLogisticsMapper orderLogisticsMapper;

    @Mock
    private ProductMapper productMapper;

    @Mock
    private ProductSkuMapper productSkuMapper;

    @Mock
    private ObjectMapper objectMapper;

    private Order testOrder;
    private OrderItem testOrderItem;

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(1L);

        testOrder = Order.builder()
                .id("order-001")
                .tenantId(1L)
                .orderNo("ORD-20260425-0001")
                .customerName("张三")
                .customerPhone("13800138000")
                .customerAddress("北京市朝阳区")
                .totalAmount(new BigDecimal("599.00"))
                .status("pending")
                .remark("测试订单")
                .build();

        testOrderItem = OrderItem.builder()
                .id("item-001")
                .tenantId(1L)
                .orderId("order-001")
                .productId("prod-001")
                .productName("蜂巢帘")
                .quantity(2)
                .unitPrice(new BigDecimal("299.50"))
                .subtotal(new BigDecimal("599.00"))
                .build();
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    // ======================== 分页查询测试 ========================

    @Test
    @DisplayName("订单分页查询 - 无筛选条件")
    void getOrderPage_DefaultPagination() {
        // given
        Page<Order> mockPage = new Page<>(1, 20);
        mockPage.setRecords(List.of(testOrder));
        mockPage.setTotal(1);

        when(orderMapper.selectPage(any(Page.class), any(LambdaQueryWrapper.class)))
                .thenReturn(mockPage);

        // when
        PageResponse<OrderListResponse> result = orderService.getOrderPage(1, 20, null, null, null, null, null, null, null, null, null, null, 1L);

        // then
        assertThat(result).isNotNull();
        assertThat(result.getTotal()).isEqualTo(1);
        assertThat(result.getItems()).hasSize(1);
        assertThat(result.getItems().get(0).getCustomerName()).isEqualTo("张三");
    }

    @Test
    @DisplayName("订单分页查询 - 按状态和关键词筛选")
    void getOrderPage_WithFilters() {
        // given
        Page<Order> mockPage = new Page<>(1, 10);
        mockPage.setRecords(List.of(testOrder));
        mockPage.setTotal(1);

        when(orderMapper.selectPage(any(Page.class), any(LambdaQueryWrapper.class)))
                .thenReturn(mockPage);

        // when
        PageResponse<OrderListResponse> result = orderService.getOrderPage(1, 10, "pending", "张三", null, null, null, null, null, null, null, null, 1L);

        // then
        assertThat(result).isNotNull();
        assertThat(result.getItems()).hasSize(1);
        verify(orderMapper).selectPage(any(Page.class), any(LambdaQueryWrapper.class));
    }

    @Test
    @DisplayName("订单分页查询 - 空结果")
    void getOrderPage_EmptyResult() {
        // given
        Page<Order> emptyPage = new Page<>(1, 20);
        emptyPage.setRecords(List.of());
        emptyPage.setTotal(0);

        when(orderMapper.selectPage(any(Page.class), any(LambdaQueryWrapper.class)))
                .thenReturn(emptyPage);

        // when
        PageResponse<OrderListResponse> result = orderService.getOrderPage(1, 20, null, null, null, null, null, null, null, null, null, null, 1L);

        // then
        assertThat(result.getTotal()).isEqualTo(0);
        assertThat(result.getItems()).isEmpty();
    }

    // ======================== 订单详情测试 ========================

    @Test
    @DisplayName("查询订单详情 - 订单存在")
    void getOrderById_Found() {
        // given
        when(orderMapper.selectById("order-001")).thenReturn(testOrder);
        when(orderItemMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of(testOrderItem));
        when(orderLogisticsMapper.selectByOrderId("order-001", 1L)).thenReturn(List.of());

        // when
        OrderDetailResponse result = orderService.getOrderById("order-001");

        // then
        assertThat(result).isNotNull();
        assertThat(result.getCustomerName()).isEqualTo("张三");
        assertThat(result.getItems()).hasSize(1);
        assertThat(result.getItems().get(0).getProductName()).isEqualTo("蜂巢帘");
        assertThat(result.getLogistics()).isNull();
    }

    @Test
    @DisplayName("查询订单详情 - 含物流信息")
    void getOrderById_WithLogistics() {
        // given
        OrderLogistics logistics = OrderLogistics.builder()
                .id("log-001")
                .orderId("order-001")
                .logisticsCompany("顺丰速运")
                .trackingNo("SF1234567890")
                .status("in_transit")
                .build();

        when(orderMapper.selectById("order-001")).thenReturn(testOrder);
        when(orderItemMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of(testOrderItem));
        when(orderLogisticsMapper.selectByOrderId("order-001", 1L)).thenReturn(List.of(logistics));

        // when
        OrderDetailResponse result = orderService.getOrderById("order-001");

        // then
        assertThat(result.getLogistics()).isNotNull();
        assertThat(result.getLogistics().getLogisticsCompany()).isEqualTo("顺丰速运");
        assertThat(result.getLogistics().getTrackingNo()).isEqualTo("SF1234567890");
    }

    @Test
    @DisplayName("查询订单详情 - 订单不存在")
    void getOrderById_NotFound() {
        // given
        when(orderMapper.selectById("nonexistent")).thenReturn(null);

        // when & then
        assertThatThrownBy(() -> orderService.getOrderById("nonexistent"))
                .isInstanceOf(BusinessException.class)
                .satisfies(ex -> {
                    BusinessException bex = (BusinessException) ex;
                    assertThat(bex.getCode()).isEqualTo("NOT_FOUND");
                    assertThat(bex.getHttpStatus()).isEqualTo(404);
                });
    }

    // ======================== 创建订单测试 ========================

    @Test
    @DisplayName("创建订单成功")
    void createOrder_Success() {
        // given
        OrderCreateRequest.OrderItemRequest itemReq = new OrderCreateRequest.OrderItemRequest();
        itemReq.setProductId("prod-001");
        itemReq.setProductName("蜂巢帘");
        itemReq.setQuantity(2);
        itemReq.setUnitPrice(new BigDecimal("299.50"));
        itemReq.setSubtotal(new BigDecimal("599.00"));

        OrderCreateRequest request = new OrderCreateRequest();
        request.setCustomerName("张三");
        request.setCustomerPhone("13800138000");
        request.setCustomerAddress("北京市朝阳区");
        request.setRemark("测试");
        request.setItems(List.of(itemReq));

        when(orderMapper.insert(any(Order.class))).thenAnswer(invocation -> {
            Order o = invocation.getArgument(0);
            o.setId("order-new");
            return 1;
        });
        when(orderItemMapper.insert(any(OrderItem.class))).thenReturn(1);

        // getOrderById 内部调用
        Order savedOrder = Order.builder()
                .id("order-new")
                .tenantId(1L)
                .orderNo("ORD-20260425-0001")
                .customerName("张三")
                .customerPhone("13800138000")
                .totalAmount(new BigDecimal("599.00"))
                .status("pending")
                .build();
        when(orderMapper.selectById("order-new")).thenReturn(savedOrder);
        when(orderItemMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of(testOrderItem));
        when(orderLogisticsMapper.selectByOrderId("order-new", 1L)).thenReturn(List.of());

        // when
        OrderDetailResponse result = orderService.createOrder(request, 1L);

        // then
        assertThat(result).isNotNull();
        assertThat(result.getCustomerName()).isEqualTo("张三");
        assertThat(result.getStatus()).isEqualTo("pending");
        verify(orderMapper).insert(any(Order.class));
        verify(orderItemMapper).insert(any(OrderItem.class));
    }

    @Test
    @DisplayName("创建订单 - 多个订单明细")
    void createOrder_MultipleItems() {
        // given
        OrderCreateRequest.OrderItemRequest item1 = new OrderCreateRequest.OrderItemRequest();
        item1.setProductId("prod-001");
        item1.setProductName("蜂巢帘");
        item1.setQuantity(1);
        item1.setUnitPrice(new BigDecimal("299.00"));
        item1.setSubtotal(new BigDecimal("299.00"));

        OrderCreateRequest.OrderItemRequest item2 = new OrderCreateRequest.OrderItemRequest();
        item2.setProductId("prod-002");
        item2.setProductName("百叶帘");
        item2.setQuantity(1);
        item2.setUnitPrice(new BigDecimal("199.00"));
        item2.setSubtotal(new BigDecimal("199.00"));

        OrderCreateRequest request = new OrderCreateRequest();
        request.setCustomerName("李四");
        request.setCustomerPhone("13900139000");
        request.setItems(List.of(item1, item2));

        when(orderMapper.insert(any(Order.class))).thenAnswer(invocation -> {
            Order o = invocation.getArgument(0);
            o.setId("order-multi");
            return 1;
        });
        when(orderItemMapper.insert(any(OrderItem.class))).thenReturn(1);

        Order savedOrder = Order.builder()
                .id("order-multi")
                .tenantId(1L)
                .customerName("李四")
                .totalAmount(new BigDecimal("498.00"))
                .status("pending")
                .build();
        when(orderMapper.selectById("order-multi")).thenReturn(savedOrder);
        when(orderItemMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of());
        when(orderLogisticsMapper.selectByOrderId("order-multi", 1L)).thenReturn(List.of());

        // when
        OrderDetailResponse result = orderService.createOrder(request, 1L);

        // then
        assertThat(result).isNotNull();
        verify(orderItemMapper, times(2)).insert(any(OrderItem.class));
    }

    // ======================== 更新订单状态测试 ========================

    @Test
    @DisplayName("更新订单状态 - pending -> confirmed 成功")
    void updateOrderStatus_PendingToConfirmed() {
        // given
        when(orderMapper.selectById("order-001")).thenReturn(testOrder);
        when(orderMapper.updateById(any(Order.class))).thenReturn(1);

        // when
        orderService.updateOrderStatus("order-001", "confirmed");

        // then
        verify(orderMapper).updateById(argThat((Order o) -> "confirmed".equals(o.getStatus())));
    }

    @Test
    @DisplayName("更新订单状态 - pending -> cancelled 成功")
    void updateOrderStatus_PendingToCancelled() {
        // given
        when(orderMapper.selectById("order-001")).thenReturn(testOrder);
        when(orderMapper.updateById(any(Order.class))).thenReturn(1);

        // when
        orderService.updateOrderStatus("order-001", "cancelled");

        // then
        verify(orderMapper).updateById(argThat((Order o) -> "cancelled".equals(o.getStatus())));
    }

    @Test
    @DisplayName("更新订单状态 - 订单不存在")
    void updateOrderStatus_OrderNotFound() {
        // given
        when(orderMapper.selectById("nonexistent")).thenReturn(null);

        // when & then
        assertThatThrownBy(() -> orderService.updateOrderStatus("nonexistent", "confirmed"))
                .isInstanceOf(BusinessException.class)
                .satisfies(ex -> {
                    BusinessException bex = (BusinessException) ex;
                    assertThat(bex.getCode()).isEqualTo("NOT_FOUND");
                });
    }

    @Test
    @DisplayName("更新订单状态 - 无效状态值")
    void updateOrderStatus_InvalidStatus() {
        // given
        when(orderMapper.selectById("order-001")).thenReturn(testOrder);

        // when & then
        assertThatThrownBy(() -> orderService.updateOrderStatus("order-001", "invalid_status"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("无效的订单状态");
    }

    @Test
    @DisplayName("更新订单状态 - 非法状态流转 pending -> shipped")
    void updateOrderStatus_IllegalTransition() {
        // given
        when(orderMapper.selectById("order-001")).thenReturn(testOrder);

        // when & then
        assertThatThrownBy(() -> orderService.updateOrderStatus("order-001", "shipped"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("不允许从");
    }

    @Test
    @DisplayName("更新订单状态 - 已完成订单不能再变更")
    void updateOrderStatus_CompletedCannotChange() {
        // given
        testOrder.setStatus("completed");
        when(orderMapper.selectById("order-001")).thenReturn(testOrder);

        // when & then
        assertThatThrownBy(() -> orderService.updateOrderStatus("order-001", "cancelled"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("不允许从");
    }

    // ======================== 删除订单测试 ========================

    @Test
    @DisplayName("删除订单成功 - pending 状态")
    void deleteOrder_Success() {
        // given
        when(orderMapper.selectById("order-001")).thenReturn(testOrder);
        when(orderMapper.deleteById("order-001")).thenReturn(1);
        when(orderItemMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of(testOrderItem));
        when(orderItemMapper.deleteById("item-001")).thenReturn(1);

        // when
        orderService.deleteOrder("order-001");

        // then
        verify(orderMapper).deleteById("order-001");
        verify(orderItemMapper).deleteById("item-001");
    }

    @Test
    @DisplayName("删除订单失败 - 订单不存在")
    void deleteOrder_NotFound() {
        // given
        when(orderMapper.selectById("nonexistent")).thenReturn(null);

        // when & then
        assertThatThrownBy(() -> orderService.deleteOrder("nonexistent"))
                .isInstanceOf(BusinessException.class)
                .satisfies(ex -> {
                    BusinessException bex = (BusinessException) ex;
                    assertThat(bex.getCode()).isEqualTo("NOT_FOUND");
                });
    }

    @Test
    @DisplayName("删除订单失败 - 非 pending 状态不允许删除")
    void deleteOrder_NotPendingStatus() {
        // given
        testOrder.setStatus("confirmed");
        when(orderMapper.selectById("order-001")).thenReturn(testOrder);

        // when & then
        assertThatThrownBy(() -> orderService.deleteOrder("order-001"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("仅允许删除待确认状态的订单");
    }

    // ======================== 生成订单号测试 ========================

    @Test
    @DisplayName("生成订单号 - 格式正确")
    void generateOrderNo_Format() {
        // given: 通过 createOrder 间接调用 generateOrderNo
        OrderCreateRequest.OrderItemRequest itemReq = new OrderCreateRequest.OrderItemRequest();
        itemReq.setProductId("prod-001");
        itemReq.setProductName("蜂巢帘");
        itemReq.setQuantity(1);
        itemReq.setUnitPrice(new BigDecimal("100.00"));
        itemReq.setSubtotal(new BigDecimal("100.00"));

        OrderCreateRequest request = new OrderCreateRequest();
        request.setCustomerName("测试");
        request.setCustomerPhone("13000000000");
        request.setItems(List.of(itemReq));

        when(orderMapper.insert(any(Order.class))).thenAnswer(invocation -> {
            Order o = invocation.getArgument(0);
            o.setId("order-gen");
            // 验证订单号格式
            assertThat(o.getOrderNo()).matches("\\d{17}");
            return 1;
        });
        when(orderItemMapper.insert(any(OrderItem.class))).thenReturn(1);

        Order savedOrder = Order.builder()
                .id("order-gen")
                .customerName("测试")
                .status("pending")
                .build();
        when(orderMapper.selectById("order-gen")).thenReturn(savedOrder);
        when(orderItemMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of());
        when(orderLogisticsMapper.selectByOrderId("order-gen", 1L)).thenReturn(List.of());

        // when
        orderService.createOrder(request, 1L);

        // then
        verify(orderMapper).insert(argThat((Order o) -> o.getOrderNo() != null && o.getOrderNo().matches("\\d{17}")));
    }

    // ======================== 确认支付（库存扣减）测试 ========================

    @Test
    @DisplayName("确认支付 - pending → confirmed 并扣减库存和销量")
    void confirmPayment_deductsStockAndIncreasesSales() {
        // given
        when(orderMapper.selectById("order-001")).thenReturn(testOrder);
        when(orderMapper.updateById(any(Order.class))).thenReturn(1);
        when(orderItemMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of(testOrderItem));

        // when
        orderService.confirmPayment("order-001");

        // then
        verify(orderMapper).updateById(argThat((Order o) -> "confirmed".equals(o.getStatus())));
        // 商品级：increaseSales 被调用
        verify(productMapper).increaseSales(eq("prod-001"), eq(2), any(BigDecimal.class));
    }

    @Test
    @DisplayName("确认支付 - 非 pending 状态拒绝")
    void confirmPayment_rejectsNonPendingStatus() {
        // given
        testOrder.setStatus("confirmed");
        when(orderMapper.selectById("order-001")).thenReturn(testOrder);

        // when & then
        assertThatThrownBy(() -> orderService.confirmPayment("order-001"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("只有待确认状态");
    }

    // ======================== 取消订单（库存恢复）测试 ========================

    @Test
    @DisplayName("取消 confirmed 订单 - 恢复库存和销量")
    void cancelOrder_restoresStock_confirmedOrder() {
        // given
        testOrder.setStatus("confirmed");
        when(orderMapper.selectById("order-001")).thenReturn(testOrder);
        when(orderMapper.updateById(any(Order.class))).thenReturn(1);
        when(orderItemMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of(testOrderItem));

        // when
        orderService.cancelOrder("order-001", "缺货");

        // then
        verify(orderMapper).updateById(argThat((Order o) ->
                "cancelled".equals(o.getStatus()) && "缺货".equals(o.getCloseReason())));
        verify(productMapper).decreaseSales(eq("prod-001"), eq(2), any(BigDecimal.class));
    }

    @Test
    @DisplayName("取消 pending 订单 - 不恢复库存")
    void cancelOrder_noStockRestore_pendingOrder() {
        // given
        when(orderMapper.selectById("order-001")).thenReturn(testOrder);
        when(orderMapper.updateById(any(Order.class))).thenReturn(1);

        // when
        orderService.cancelOrder("order-001", null);

        // then
        verify(orderMapper).updateById(argThat((Order o) -> "cancelled".equals(o.getStatus())));
        // pending 订单取消不应调用库存恢复
        verify(productMapper, never()).decreaseSales(anyString(), anyInt(), any(BigDecimal.class));
    }

    @Test
    @DisplayName("取消订单 - closeReason 超长被拒绝")
    void cancelOrder_closeReasonTooLong() {
        // given
        when(orderMapper.selectById("order-001")).thenReturn(testOrder);
        String longReason = "x".repeat(501);

        // when & then
        assertThatThrownBy(() -> orderService.cancelOrder("order-001", longReason))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("500");
    }

    @Test
    @DisplayName("取消订单 - 不允许从 shipped/completed 状态取消")
    void cancelOrder_rejectsNonCancellableStatus() {
        // given
        testOrder.setStatus("shipped");
        when(orderMapper.selectById("order-001")).thenReturn(testOrder);

        // when & then
        assertThatThrownBy(() -> orderService.cancelOrder("order-001", null))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("当前状态不允许取消");
    }

    // ======================== 退款（库存恢复）测试 ========================

    @Test
    @DisplayName("退款 confirmed 订单 - 恢复库存并设置 closeReason=退款")
    void refundOrder_restoresStockAndDecreasesSales() {
        // given
        testOrder.setStatus("confirmed");
        when(orderMapper.selectById("order-001")).thenReturn(testOrder);
        when(orderMapper.updateById(any(Order.class))).thenReturn(1);
        when(orderItemMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of(testOrderItem));

        // when
        orderService.refundOrder("order-001", null);

        // then
        verify(orderMapper).updateById(argThat((Order o) ->
                "cancelled".equals(o.getStatus()) && "退款".equals(o.getCloseReason())));
        verify(productMapper).decreaseSales(eq("prod-001"), eq(2), any(BigDecimal.class));
    }

    @Test
    @DisplayName("退款 - pending 状态不允许退款")
    void refundOrder_rejectsPendingStatus() {
        // given
        when(orderMapper.selectById("order-001")).thenReturn(testOrder);

        // when & then
        assertThatThrownBy(() -> orderService.refundOrder("order-001", null))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("不允许退款");
    }

    // ======================== 添加备注测试 ========================

    @Test
    @DisplayName("添加备注 - 新备注前插带时间戳")
    void addRemark_prependsWithTimestamp() {
        // given
        when(orderMapper.selectById("order-001")).thenReturn(testOrder);
        when(orderMapper.updateById(any(Order.class))).thenReturn(1);

        // when
        orderService.addRemark("order-001", "客户催单");

        // then
        verify(orderMapper).updateById(argThat((Order o) -> {
            String remark = o.getRemark();
            return remark != null
                    && remark.contains("客户催单")
                    && remark.matches("(?s).*\\[\\d{4}-\\d{2}-\\d{2} \\d{2}:\\d{2}\\] 客户催单.*");
        }));
    }

    @Test
    @DisplayName("添加备注 - 已有备注时新备注前插（最新在前）")
    void addRemark_prependsToExistingRemark() {
        // given
        testOrder.setRemark("[2026-06-01 10:00] 旧备注");
        when(orderMapper.selectById("order-001")).thenReturn(testOrder);
        when(orderMapper.updateById(any(Order.class))).thenReturn(1);

        // when
        orderService.addRemark("order-001", "新备注");

        // then: 新备注应该在前（prepend），旧备注在后
        verify(orderMapper).updateById(argThat((Order o) -> {
            String remark = o.getRemark();
            if (remark == null) return false;
            int newRemarkPos = remark.indexOf("新备注");
            int oldRemarkPos = remark.indexOf("旧备注");
            return remark.contains("\n")
                    && newRemarkPos >= 0
                    && oldRemarkPos >= 0
                    && newRemarkPos < oldRemarkPos; // 新备注在前
        }));
    }

    @Test
    @DisplayName("添加备注 - 多条已有备注时最新备注仍然在前")
    void addRemark_prependsWhenMultipleExisting() {
        // given: 已有两条旧备注（按时间倒序模拟）
        testOrder.setRemark("[2026-06-03 14:00] 第二次备注\n[2026-06-01 10:00] 第一次备注");
        when(orderMapper.selectById("order-001")).thenReturn(testOrder);
        when(orderMapper.updateById(any(Order.class))).thenReturn(1);

        // when
        orderService.addRemark("order-001", "第三次备注");

        // then: 最新备注（第三次）应该在最前面
        verify(orderMapper).updateById(argThat((Order o) -> {
            String remark = o.getRemark();
            if (remark == null) return false;
            int thirdPos = remark.indexOf("第三次备注");
            int secondPos = remark.indexOf("第二次备注");
            int firstPos = remark.indexOf("第一次备注");
            return thirdPos >= 0 && secondPos >= 0 && firstPos >= 0
                    && thirdPos < secondPos
                    && secondPos < firstPos; // 第三次 < 第二次 < 第一次
        }));
    }

    @Test
    @DisplayName("添加备注 - 空内容被拒绝")
    void addRemark_rejectsEmptyContent() {
        // given
        when(orderMapper.selectById("order-001")).thenReturn(testOrder);

        // when & then
        assertThatThrownBy(() -> orderService.addRemark("order-001", ""))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("备注内容不能为空");
    }

    @Test
    @DisplayName("添加备注 - 超长内容被拒绝")
    void addRemark_rejectsTooLongContent() {
        // given
        when(orderMapper.selectById("order-001")).thenReturn(testOrder);
        String longContent = "x".repeat(2001);

        // when & then
        assertThatThrownBy(() -> orderService.addRemark("order-001", longContent))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("2000");
    }

    // ======================== 跟进状态校验测试 ========================

    @Test
    @DisplayName("更新跟进状态 - 无效值被拒绝")
    void updateFollowStatus_rejectsInvalidValue() {
        // given
        when(orderMapper.selectById("order-001")).thenReturn(testOrder);

        // when & then
        assertThatThrownBy(() -> orderService.updateFollowStatus("order-001", "invalid"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("无效的跟进状态");
    }

    // ======================== actualAmount 持久化测试 ========================

    @Test
    @DisplayName("创建订单 - actualAmount 被持久化（用户输入实收款=0）")
    void createOrder_persistsActualAmount_zero() {
        // given: 用户输入实收款 = 0（与 totalAmount=599 不同）
        OrderCreateRequest.OrderItemRequest itemReq = new OrderCreateRequest.OrderItemRequest();
        itemReq.setProductId("prod-001");
        itemReq.setProductName("蜂巢帘");
        itemReq.setQuantity(2);
        itemReq.setUnitPrice(new BigDecimal("299.50"));
        itemReq.setSubtotal(new BigDecimal("599.00"));

        OrderCreateRequest request = new OrderCreateRequest();
        request.setCustomerName("张三");
        request.setCustomerPhone("13800138000");
        request.setActualAmount(BigDecimal.ZERO); // 实收款 = 0
        request.setItems(List.of(itemReq));

        when(orderMapper.insert(any(Order.class))).thenAnswer(invocation -> {
            Order o = invocation.getArgument(0);
            // 验证 actualAmount 被传入 Order entity
            assertThat(o.getActualAmount()).isEqualTo(BigDecimal.ZERO);
            o.setId("order-actual-zero");
            return 1;
        });
        when(orderItemMapper.insert(any(OrderItem.class))).thenReturn(1);

        Order savedOrder = Order.builder()
                .id("order-actual-zero")
                .tenantId(1L)
                .orderNo("ORD-20260621-0003")
                .customerName("张三")
                .customerPhone("13800138000")
                .totalAmount(new BigDecimal("599.00"))
                .actualAmount(BigDecimal.ZERO)
                .status("pending")
                .build();
        when(orderMapper.selectById("order-actual-zero")).thenReturn(savedOrder);
        when(orderItemMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of(testOrderItem));
        when(orderLogisticsMapper.selectByOrderId("order-actual-zero", 1L)).thenReturn(List.of());

        // when
        OrderDetailResponse result = orderService.createOrder(request, 1L);

        // then: 详情返回的 actualAmount 应该是 0，不是 totalAmount
        assertThat(result.getActualAmount()).isEqualTo(BigDecimal.ZERO);
        assertThat(result.getTotalAmount()).isEqualTo(new BigDecimal("599.00"));
    }

    @Test
    @DisplayName("创建订单 - actualAmount 未传时默认等于 totalAmount")
    void createOrder_persistsActualAmount_defaultToTotal() {
        // given: 不传 actualAmount
        OrderCreateRequest.OrderItemRequest itemReq = new OrderCreateRequest.OrderItemRequest();
        itemReq.setProductId("prod-001");
        itemReq.setProductName("蜂巢帘");
        itemReq.setQuantity(2);
        itemReq.setUnitPrice(new BigDecimal("299.50"));
        itemReq.setSubtotal(new BigDecimal("599.00"));

        OrderCreateRequest request = new OrderCreateRequest();
        request.setCustomerName("张三");
        request.setCustomerPhone("13800138000");
        // actualAmount 不设置
        request.setItems(List.of(itemReq));

        when(orderMapper.insert(any(Order.class))).thenAnswer(invocation -> {
            Order o = invocation.getArgument(0);
            // 验证 actualAmount 默认等于 totalAmount
            assertThat(o.getActualAmount()).isEqualByComparingTo(new BigDecimal("599.00"));
            o.setId("order-actual-default");
            return 1;
        });
        when(orderItemMapper.insert(any(OrderItem.class))).thenReturn(1);

        Order savedOrder = Order.builder()
                .id("order-actual-default")
                .tenantId(1L)
                .orderNo("ORD-20260621-0004")
                .customerName("张三")
                .customerPhone("13800138000")
                .totalAmount(new BigDecimal("599.00"))
                .actualAmount(new BigDecimal("599.00"))
                .status("pending")
                .build();
        when(orderMapper.selectById("order-actual-default")).thenReturn(savedOrder);
        when(orderItemMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of(testOrderItem));
        when(orderLogisticsMapper.selectByOrderId("order-actual-default", 1L)).thenReturn(List.of());

        // when
        OrderDetailResponse result = orderService.createOrder(request, 1L);

        // then
        assertThat(result.getActualAmount()).isEqualByComparingTo(new BigDecimal("599.00"));
        assertThat(result.getTotalAmount()).isEqualByComparingTo(new BigDecimal("599.00"));
    }

    @Test
    @DisplayName("查询订单详情 - 返回存储的 actualAmount 而非 totalAmount")
    void getOrderById_returnsStoredActualAmount() {
        // given: 订单 actualAmount=0, totalAmount=599
        testOrder.setActualAmount(BigDecimal.ZERO);
        testOrder.setTotalAmount(new BigDecimal("599.00"));
        when(orderMapper.selectById("order-001")).thenReturn(testOrder);
        when(orderItemMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of(testOrderItem));
        when(orderLogisticsMapper.selectByOrderId("order-001", 1L)).thenReturn(List.of());

        // when
        OrderDetailResponse result = orderService.getOrderById("order-001");

        // then
        assertThat(result.getActualAmount()).isEqualTo(BigDecimal.ZERO);
        assertThat(result.getTotalAmount()).isEqualTo(new BigDecimal("599.00"));
    }

    @Test
    @DisplayName("查询订单详情 - actualAmount 为空时 fallback 到 totalAmount")
    void getOrderById_actualAmountNull_fallbackToTotal() {
        // given: 老订单没有 actualAmount
        testOrder.setActualAmount(null);
        testOrder.setTotalAmount(new BigDecimal("599.00"));
        when(orderMapper.selectById("order-001")).thenReturn(testOrder);
        when(orderItemMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of(testOrderItem));
        when(orderLogisticsMapper.selectByOrderId("order-001", 1L)).thenReturn(List.of());

        // when
        OrderDetailResponse result = orderService.getOrderById("order-001");

        // then
        assertThat(result.getActualAmount()).isEqualByComparingTo(new BigDecimal("599.00"));
    }

    @Test
    @DisplayName("更新跟进状态 - 有效值成功")
    void updateFollowStatus_acceptsValidValue() {
        // given
        when(orderMapper.selectById("order-001")).thenReturn(testOrder);
        when(orderMapper.updateById(any(Order.class))).thenReturn(1);

        // when
        orderService.updateFollowStatus("order-001", "following");

        // then
        verify(orderMapper).updateById(argThat((Order o) -> "following".equals(o.getFollowStatus())));
    }
}
