package com.migao.admin.service;
// case_ids: OR-006, FN-001, OR-001

import com.baomidou.mybatisplus.core.conditions.update.UpdateWrapper;
import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.*;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.entity.OrderLogistics;
import com.migao.admin.entity.FinanceTransaction;
import com.migao.admin.entity.ProductSku;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.FinanceTransactionMapper;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderLogisticsMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProductMapper;
import com.migao.admin.mapper.ProductSkuMapper;
import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.test.util.ReflectionTestUtils;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.Map;

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
    private FinanceTransactionMapper financeTransactionMapper;

    @Mock
    private ObjectMapper objectMapper;

    private Order testOrder;
    private OrderItem testOrderItem;

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(1L);

        // 初始化 MyBatis-Plus 实体 lambda 缓存，使 LambdaUpdateWrapper 的 Order::getId 等方法引用可解析
        MybatisConfiguration conf = new MybatisConfiguration();
        MapperBuilderAssistant assistant = new MapperBuilderAssistant(conf, "");
        TableInfoHelper.initTableInfo(assistant, Order.class);
        TableInfoHelper.initTableInfo(assistant, OrderItem.class);

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

    @Test
    @DisplayName("订单分页查询 - 含加工项过滤：子查询投影必须包含 processing_info（回归：漏投影导致恒为空集）")
    void getOrderPage_HasProcessingFilter_SubQueryProjectionIncludesProcessingInfo() {
        // when：hasProcessing=true 触发 order_items 子查询过滤
        orderService.getOrderPage(1, 20, null, null, null, true, null, null, null, null, null, null, 1L);

        // then：子查询 SELECT 必须同时取回 processingInfo 列。
        //   根因（2026-08-29 真实数据复现）：之前只 select(orderId)，MyBatis-Plus 只投影 order_id 一列，
        //   返回实体中 processingInfo 为 null → extractProcessingItems 恒返回空列表 → orderIdsWithProcessing 恒为空
        //   → hasProcessing=true 恒返回 0 条（基线 4 条含加工订单，过滤后 total=0），
        //     hasProcessing=false 的 notIn 也恒被跳过（含加工订单漏出）。
        ArgumentCaptor<LambdaQueryWrapper<OrderItem>> captor = ArgumentCaptor.forClass(LambdaQueryWrapper.class);
        verify(orderItemMapper, atLeastOnce()).selectList(captor.capture());
        List<String> sqlSelects = captor.getAllValues().stream()
                .map(w -> String.valueOf(w.getSqlSelect()).toLowerCase())
                .collect(java.util.stream.Collectors.toList());
        assertThat(sqlSelects)
                .as("order_items 子查询 SELECT 列必须包含加工信息列（order_id, processing_info）")
                .anyMatch(s -> s.contains("processing"));
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
    @DisplayName("更新订单状态 - pending -> confirmed 触发扣减库存（委托 confirmPayment）")
    void updateOrderStatus_PendingToConfirmed() {
        // given
        when(orderMapper.selectById("order-001")).thenReturn(testOrder);
        when(orderMapper.update(any(), any())).thenReturn(1);
        when(orderItemMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of(testOrderItem));

        // when
        orderService.updateOrderStatus("order-001", "confirmed");

        // then: 委托 confirmPayment → 扣减库存/增加销量（此前此路径会跳过副作用）
        verify(productMapper).increaseSales(eq("prod-001"), eq(2), any(BigDecimal.class));
    }

    @Test
    @DisplayName("更新订单状态 - pending -> cancelled 委托取消，无库存恢复")
    void updateOrderStatus_PendingToCancelled() {
        // given
        when(orderMapper.selectById("order-001")).thenReturn(testOrder);
        when(orderMapper.update(any(), any())).thenReturn(1);

        // when
        orderService.updateOrderStatus("order-001", "cancelled");

        // then: pending 取消不恢复库存
        verify(orderMapper).update(any(), any());
        verify(productMapper, never()).decreaseSales(anyString(), anyInt(), any(BigDecimal.class));
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
    @DisplayName("更新订单状态 - 错误消息用中文状态术语（面向企业客户）")
    void updateOrderStatus_ErrorMessagesUseChinese() {
        // given: 非法流转 pending → shipped
        when(orderMapper.selectById("order-001")).thenReturn(testOrder);

        // when & then: 报错不得暴露英文枚举 pending/shipped
        assertThatThrownBy(() -> orderService.updateOrderStatus("order-001", "shipped"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("待付款")
                .hasMessageContaining("已发货")
                .hasMessageNotContaining("pending")
                .hasMessageNotContaining("shipped");
    }

    @Test
    @DisplayName("更新订单状态 - 无效状态值报错不含英文枚举")
    void updateOrderStatus_InvalidStatus_ChineseOnly() {
        // given
        when(orderMapper.selectById("order-001")).thenReturn(testOrder);

        // when & then: invalid_status 不是合法枚举，报错展示原始值 + 中文提示
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

    @Test
    @DisplayName("生成订单号 - 连续两次不同（原子序列保证）")
    void generateOrderNo_Uniqueness() {
        // when: 直接调用私有 generateOrderNo 两次
        String no1 = (String) ReflectionTestUtils.invokeMethod(orderService, "generateOrderNo");
        String no2 = (String) ReflectionTestUtils.invokeMethod(orderService, "generateOrderNo");

        // then: 均为 17 位且互不相同
        assertThat(no1).matches("\\d{17}");
        assertThat(no2).matches("\\d{17}");
        assertThat(no1).isNotEqualTo(no2);
    }

    // ======================== 确认支付（库存扣减）测试 ========================

    @Test
    @DisplayName("确认支付 - pending → confirmed 并扣减库存和销量")
    void confirmPayment_deductsStockAndIncreasesSales() {
        // given
        when(orderMapper.selectById("order-001")).thenReturn(testOrder);
        when(orderMapper.update(any(), any())).thenReturn(1);
        when(orderItemMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of(testOrderItem));

        // when
        orderService.confirmPayment("order-001");

        // then: 原子流转 + 商品级 increaseSales + 自动登记收款流水
        verify(orderMapper).update(any(), any());
        verify(productMapper).increaseSales(eq("prod-001"), eq(2), any(BigDecimal.class));
        verify(financeTransactionMapper).insert(any(FinanceTransaction.class));
    }

    // ======================== 取消订单（库存恢复）测试 ========================

    @Test
    @DisplayName("取消 confirmed 订单 - 恢复库存和销量")
    void cancelOrder_restoresStock_confirmedOrder() {
        // given
        testOrder.setStatus("confirmed");
        when(orderMapper.selectById("order-001")).thenReturn(testOrder);
        when(orderMapper.update(any(), any())).thenReturn(1);
        when(orderItemMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of(testOrderItem));

        // when
        orderService.cancelOrder("order-001", "缺货");

        // then: 原子流转 + 恢复库存
        verify(orderMapper).update(any(), any());
        verify(productMapper).decreaseSales(eq("prod-001"), eq(2), any(BigDecimal.class));
    }

    @Test
    @DisplayName("取消 pending 订单 - 不恢复库存")
    void cancelOrder_noStockRestore_pendingOrder() {
        // given
        when(orderMapper.selectById("order-001")).thenReturn(testOrder);
        when(orderMapper.update(any(), any())).thenReturn(1);

        // when
        orderService.cancelOrder("order-001", null);

        // then: pending 订单取消不应调用库存恢复
        verify(orderMapper).update(any(), any());
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

    // ======================== 退款（新语义：财务叠加，不改状态）测试 ========================

    @Test
    @DisplayName("部分退款 - 保持原状态，落 refundAmount/refundAt，登记退款流水，不恢复库存")
    void refundOrder_partialRefund_keepsStatusAndRecordsAmount() {
        // given
        testOrder.setStatus("confirmed");
        testOrder.setActualAmount(new BigDecimal("599.00"));
        when(orderMapper.selectById("order-001")).thenReturn(testOrder);
        when(orderMapper.update(any(), any(UpdateWrapper.class))).thenReturn(1);

        // when
        orderService.refundOrder("order-001", new BigDecimal("100.00"), "部分退款");

        // then: 状态保持 confirmed，不再硬改为 cancelled
        assertThat(testOrder.getStatus()).isEqualTo("confirmed");
        assertThat(testOrder.getRefundAmount()).isEqualByComparingTo("100.00");
        assertThat(testOrder.getRefundAt()).isNotNull();
        // 原子条件更新（防并发双花，审计 07 P1-10）
        verify(orderMapper).update(isNull(), any(UpdateWrapper.class));
        verify(productMapper, never()).decreaseSales(anyString(), anyInt(), any(BigDecimal.class));
        // 登记退款流水（金额=本次退款额）
        verify(financeTransactionMapper).insert(argThat((FinanceTransaction t) ->
                "refund".equals(t.getType())
                        && t.getAmount().compareTo(new BigDecimal("100.00")) == 0));
    }

    @Test
    @DisplayName("全额退款 - refundAmount 为 null 时默认退实际收款额")
    void refundOrder_fullRefundWhenAmountNull() {
        // given
        testOrder.setStatus("completed");
        testOrder.setActualAmount(new BigDecimal("599.00"));
        when(orderMapper.selectById("order-001")).thenReturn(testOrder);
        when(orderMapper.update(any(), any(UpdateWrapper.class))).thenReturn(1);

        // when
        orderService.refundOrder("order-001", null, "全额退款");

        // then
        assertThat(testOrder.getRefundAmount()).isEqualByComparingTo("599.00");
        assertThat(testOrder.getRefundAt()).isNotNull();
        verify(financeTransactionMapper).insert(argThat((FinanceTransaction t) ->
                "refund".equals(t.getType())
                        && t.getAmount().compareTo(new BigDecimal("599.00")) == 0));
    }

    @Test
    @DisplayName("退款金额累计 - 多次退款累加且不超过实收款")
    void refundOrder_accumulatesAndCapsAtActualAmount() {
        // given: 已有退款 400，再退 300 → 累计应封顶在 actualAmount=599
        testOrder.setStatus("shipped");
        testOrder.setActualAmount(new BigDecimal("599.00"));
        testOrder.setRefundAmount(new BigDecimal("400.00"));
        when(orderMapper.selectById("order-001")).thenReturn(testOrder);
        when(orderMapper.update(any(), any(UpdateWrapper.class))).thenReturn(1);

        // when
        orderService.refundOrder("order-001", new BigDecimal("300.00"), "再次退款");

        // then
        assertThat(testOrder.getRefundAmount()).isEqualByComparingTo("599.00");
        verify(financeTransactionMapper).insert(argThat((FinanceTransaction t) ->
                "refund".equals(t.getType())
                        && t.getAmount().compareTo(new BigDecimal("199.00")) == 0));
    }

    @Test
    @DisplayName("退款 - 并发下原子更新失败（更新 0 行）→ 拒绝重复退款（防双花，审计 07 P1-10）")
    void refundOrder_concurrentAtomicUpdateFails_rejectsDuplication() {
        // given: 并发场景下 update 条件不满足（refund_amount 已被其他请求累加满）
        testOrder.setStatus("shipped");
        testOrder.setActualAmount(new BigDecimal("599.00"));
        testOrder.setRefundAmount(new BigDecimal("400.00"));
        when(orderMapper.selectById("order-001")).thenReturn(testOrder);
        when(orderMapper.update(any(), any(UpdateWrapper.class))).thenReturn(0);

        // when & then
        assertThatThrownBy(() -> orderService.refundOrder("order-001", new BigDecimal("300.00"), "并发退款"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("已全额退款");
        // 不登记资金流水（防止虚增退款）
        verify(financeTransactionMapper, never()).insert(any(FinanceTransaction.class));
    }

    @Test
    @DisplayName("退款 - 负数金额被拒绝")
    void refundOrder_rejectsNegativeAmount() {
        // given
        testOrder.setStatus("confirmed");
        when(orderMapper.selectById("order-001")).thenReturn(testOrder);

        // when & then
        assertThatThrownBy(() -> orderService.refundOrder("order-001", new BigDecimal("-1.00"), null))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("退款金额");
    }

    @Test
    @DisplayName("退款 - 金额超过实收款被拒绝")
    void refundOrder_rejectsAmountAboveActual() {
        // given
        testOrder.setStatus("confirmed");
        testOrder.setActualAmount(new BigDecimal("599.00"));
        when(orderMapper.selectById("order-001")).thenReturn(testOrder);

        // when & then
        assertThatThrownBy(() -> orderService.refundOrder("order-001", new BigDecimal("600.00"), null))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("退款金额");
    }

    @Test
    @DisplayName("退款 confirmed 订单 - 保持原状态且不恢复库存/销量（退款为财务叠加态）")
    void refundOrder_keepsStatusAndDoesNotRestoreStock() {
        // given
        testOrder.setStatus("confirmed");
        testOrder.setActualAmount(new BigDecimal("599.00"));
        when(orderMapper.selectById("order-001")).thenReturn(testOrder);
        when(orderMapper.update(any(), any(UpdateWrapper.class))).thenReturn(1);

        // when
        orderService.refundOrder("order-001", null, null);

        // then: 不再把状态硬改为 cancelled，也不恢复库存
        assertThat(testOrder.getStatus()).isEqualTo("confirmed");
        verify(orderMapper).update(isNull(), any(UpdateWrapper.class));
        verify(productMapper, never()).decreaseSales(anyString(), anyInt(), any(BigDecimal.class));
        verify(financeTransactionMapper).insert(any(FinanceTransaction.class));
    }

    @Test
    @DisplayName("退款 - pending 状态不允许退款")
    void refundOrder_rejectsPendingStatus() {
        // given
        when(orderMapper.selectById("order-001")).thenReturn(testOrder);

        // when & then
        assertThatThrownBy(() -> orderService.refundOrder("order-001", null, null))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("不允许退款");
    }

    // ======================== 添加备注测试 ========================

    @Test
    @DisplayName("添加备注 - 追加带时间戳的备注")
    void addRemark_appendsWithTimestamp() {
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
    @DisplayName("添加备注 - 已有备注时换行追加")
    void addRemark_appendsToExistingRemark() {
        // given
        testOrder.setRemark("[2026-06-01 10:00] 旧备注");
        when(orderMapper.selectById("order-001")).thenReturn(testOrder);
        when(orderMapper.updateById(any(Order.class))).thenReturn(1);

        // when
        orderService.addRemark("order-001", "新备注");

        // then
        verify(orderMapper).updateById(argThat((Order o) ->
                o.getRemark() != null && o.getRemark().contains("\n") && o.getRemark().contains("新备注")));
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
    @DisplayName("创建订单 - actualAmount 被持久化（用户输入实收款=0，优惠金额抵消差额）")
    void createOrder_persistsActualAmount_zero() {
        // given: 用户输入实收款 = 0，优惠金额 = 599（与 totalAmount=599 相抵，保持 应收-优惠=实收 一致）
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
        request.setDiscountAmount(new BigDecimal("599.00")); // 全免
        request.setItems(List.of(itemReq));

        when(orderMapper.insert(any(Order.class))).thenAnswer(invocation -> {
            Order o = invocation.getArgument(0);
            // 验证 actualAmount 与 discountAmount 被传入 Order entity
            assertThat(o.getActualAmount()).isEqualTo(BigDecimal.ZERO);
            assertThat(o.getDiscountAmount()).isEqualByComparingTo("599.00");
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
                .discountAmount(new BigDecimal("599.00"))
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

    // ======================== 优惠金额（discountAmount）测试 ========================

    private OrderCreateRequest buildCreateRequestWithAmounts(BigDecimal actualAmount, BigDecimal discountAmount) {
        OrderCreateRequest.OrderItemRequest itemReq = new OrderCreateRequest.OrderItemRequest();
        itemReq.setProductId("prod-001");
        itemReq.setProductName("蜂巢帘");
        itemReq.setQuantity(2);
        itemReq.setUnitPrice(new BigDecimal("299.50"));
        itemReq.setSubtotal(new BigDecimal("599.00"));

        OrderCreateRequest request = new OrderCreateRequest();
        request.setCustomerName("张三");
        request.setCustomerPhone("13800138000");
        request.setActualAmount(actualAmount);
        request.setDiscountAmount(discountAmount);
        request.setItems(List.of(itemReq));
        return request;
    }

    @Test
    @DisplayName("创建订单 - discountAmount 落库并返回详情（应收-优惠=实收）")
    void createOrder_persistsDiscountAmount() {
        // given: totalAmount=599, 优惠 99, 实收 500 → 一致
        OrderCreateRequest request = buildCreateRequestWithAmounts(new BigDecimal("500.00"), new BigDecimal("99.00"));

        when(orderMapper.insert(any(Order.class))).thenAnswer(invocation -> {
            Order o = invocation.getArgument(0);
            assertThat(o.getDiscountAmount()).isEqualByComparingTo("99.00");
            assertThat(o.getActualAmount()).isEqualByComparingTo("500.00");
            o.setId("order-discount");
            return 1;
        });
        when(orderItemMapper.insert(any(OrderItem.class))).thenReturn(1);

        Order savedOrder = Order.builder()
                .id("order-discount")
                .tenantId(1L)
                .customerName("张三")
                .totalAmount(new BigDecimal("599.00"))
                .actualAmount(new BigDecimal("500.00"))
                .discountAmount(new BigDecimal("99.00"))
                .status("pending")
                .build();
        when(orderMapper.selectById("order-discount")).thenReturn(savedOrder);
        when(orderItemMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of(testOrderItem));
        when(orderLogisticsMapper.selectByOrderId("order-discount", 1L)).thenReturn(List.of());

        // when
        OrderDetailResponse result = orderService.createOrder(request, 1L);

        // then: 详情返回 discountAmount
        assertThat(result.getDiscountAmount()).isEqualByComparingTo("99.00");
        assertThat(result.getActualAmount()).isEqualByComparingTo("500.00");
    }

    @Test
    @DisplayName("创建订单 - 优惠金额未传时默认 0")
    void createOrder_discountAmountDefaultsToZero() {
        // given: 不传 discountAmount / actualAmount
        OrderCreateRequest.OrderItemRequest itemReq = new OrderCreateRequest.OrderItemRequest();
        itemReq.setProductId("prod-001");
        itemReq.setProductName("蜂巢帘");
        itemReq.setQuantity(2);
        itemReq.setUnitPrice(new BigDecimal("299.50"));
        itemReq.setSubtotal(new BigDecimal("599.00"));

        OrderCreateRequest request = new OrderCreateRequest();
        request.setCustomerName("张三");
        request.setCustomerPhone("13800138000");
        request.setItems(List.of(itemReq));

        when(orderMapper.insert(any(Order.class))).thenAnswer(invocation -> {
            Order o = invocation.getArgument(0);
            assertThat(o.getDiscountAmount()).isEqualByComparingTo(BigDecimal.ZERO);
            o.setId("order-discount-default");
            return 1;
        });
        when(orderItemMapper.insert(any(OrderItem.class))).thenReturn(1);

        Order savedOrder = Order.builder()
                .id("order-discount-default")
                .tenantId(1L)
                .customerName("张三")
                .totalAmount(new BigDecimal("599.00"))
                .status("pending")
                .build();
        when(orderMapper.selectById("order-discount-default")).thenReturn(savedOrder);
        when(orderItemMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of(testOrderItem));
        when(orderLogisticsMapper.selectByOrderId("order-discount-default", 1L)).thenReturn(List.of());

        // when
        orderService.createOrder(request, 1L);

        // then
        verify(orderMapper).insert(argThat((Order o) ->
                o.getDiscountAmount() != null && o.getDiscountAmount().compareTo(BigDecimal.ZERO) == 0));
    }

    @Test
    @DisplayName("创建订单 - 实收与 应收-优惠 不一致被拒绝（超出容差 0.01）")
    void createOrder_rejectsInconsistentActualAmount() {
        // given: totalAmount=599, 优惠 99 → 应收 500，但实收传 480（差 20 > 0.01）
        OrderCreateRequest request = buildCreateRequestWithAmounts(new BigDecimal("480.00"), new BigDecimal("99.00"));

        // when & then
        assertThatThrownBy(() -> orderService.createOrder(request, 1L))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("实收金额");
    }

    @Test
    @DisplayName("创建订单 - 实收与应收的偏差在容差 0.01 内允许")
    void createOrder_acceptsActualAmountWithinTolerance() {
        // given: totalAmount=599, 优惠 99 → 应收 500，实收 499.99（差 0.01）
        OrderCreateRequest request = buildCreateRequestWithAmounts(new BigDecimal("499.99"), new BigDecimal("99.00"));

        when(orderMapper.insert(any(Order.class))).thenAnswer(invocation -> {
            Order o = invocation.getArgument(0);
            o.setId("order-tolerance");
            return 1;
        });
        when(orderItemMapper.insert(any(OrderItem.class))).thenReturn(1);

        Order savedOrder = Order.builder()
                .id("order-tolerance")
                .tenantId(1L)
                .customerName("张三")
                .totalAmount(new BigDecimal("599.00"))
                .actualAmount(new BigDecimal("499.99"))
                .discountAmount(new BigDecimal("99.00"))
                .status("pending")
                .build();
        when(orderMapper.selectById("order-tolerance")).thenReturn(savedOrder);
        when(orderItemMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of(testOrderItem));
        when(orderLogisticsMapper.selectByOrderId("order-tolerance", 1L)).thenReturn(List.of());

        // when & then: 不抛异常
        OrderDetailResponse result = orderService.createOrder(request, 1L);
        assertThat(result).isNotNull();
    }

    @Test
    @DisplayName("查询订单详情 - 返回退款/优惠字段")
    void getOrderById_returnsRefundAndDiscountFields() {
        // given
        testOrder.setRefundAmount(new BigDecimal("100.00"));
        testOrder.setRefundAt(OffsetDateTime.parse("2026-07-01T10:00:00Z"));
        testOrder.setDiscountAmount(new BigDecimal("99.00"));
        when(orderMapper.selectById("order-001")).thenReturn(testOrder);
        when(orderItemMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of(testOrderItem));
        when(orderLogisticsMapper.selectByOrderId("order-001", 1L)).thenReturn(List.of());

        // when
        OrderDetailResponse result = orderService.getOrderById("order-001");

        // then
        assertThat(result.getRefundAmount()).isEqualByComparingTo("100.00");
        assertThat(result.getRefundAt()).isEqualTo(OffsetDateTime.parse("2026-07-01T10:00:00Z"));
        assertThat(result.getDiscountAmount()).isEqualByComparingTo("99.00");
    }

    // ======================== 取消订单补记退款流水测试 ========================

    @Test
    @DisplayName("取消 confirmed 订单 - 补记 refund 流水（与 income 对冲）")
    void cancelOrder_confirmedOrder_recordsRefundTransaction() {
        // given
        testOrder.setStatus("confirmed");
        testOrder.setActualAmount(new BigDecimal("599.00"));
        when(orderMapper.selectById("order-001")).thenReturn(testOrder);
        when(orderMapper.update(any(), any())).thenReturn(1);
        when(orderItemMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of(testOrderItem));

        // when
        orderService.cancelOrder("order-001", "客户取消");

        // then: 状态流转 + 恢复库存 + 登记退款流水
        verify(orderMapper).update(any(), any());
        verify(productMapper).decreaseSales(eq("prod-001"), eq(2), any(BigDecimal.class));
        verify(financeTransactionMapper).insert(argThat((FinanceTransaction t) ->
                "refund".equals(t.getType())
                        && t.getAmount().compareTo(new BigDecimal("599.00")) == 0));
    }

    @Test
    @DisplayName("取消 pending 订单 - 未收款不补记退款流水")
    void cancelOrder_pendingOrder_noRefundTransaction() {
        // given
        when(orderMapper.selectById("order-001")).thenReturn(testOrder);
        when(orderMapper.update(any(), any())).thenReturn(1);

        // when
        orderService.cancelOrder("order-001", null);

        // then
        verify(orderMapper).update(any(), any());
        verify(financeTransactionMapper, never()).insert(any(FinanceTransaction.class));
    }

    // ======================== 超卖校验测试 ========================

    private OrderItem buildItemWithSku(Long skuId, int quantity) {
        return OrderItem.builder()
                .id("item-sku-" + skuId)
                .tenantId(1L)
                .orderId("order-001")
                .productId("prod-001")
                .productName("蜂巢帘")
                .quantity(quantity)
                .unitPrice(new BigDecimal("299.50"))
                .subtotal(new BigDecimal("299.50").multiply(BigDecimal.valueOf(quantity)))
                .processingInfo(Map.of("skuId", skuId))
                .build();
    }

    @Test
    @DisplayName("确认支付 - SKU 库存不足拒绝确认，不扣减库存")
    void confirmPayment_rejectsInsufficientStock() {
        // given: 订单 2 件，SKU 库存仅 1
        testOrder.setStatus("pending");
        OrderItem skuItem = buildItemWithSku(100L, 2);
        ProductSku sku = ProductSku.builder().id(100L).stock(1).build();

        when(orderMapper.selectById("order-001")).thenReturn(testOrder);
        when(orderItemMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of(skuItem));
        when(productSkuMapper.selectById(100L)).thenReturn(sku);

        // when & then
        assertThatThrownBy(() -> orderService.confirmPayment("order-001"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("库存不足");
        verify(productSkuMapper, never()).deductStock(anyLong(), anyInt());
        verify(productMapper, never()).increaseSales(anyString(), anyInt(), any(BigDecimal.class));
    }

    @Test
    @DisplayName("确认支付 - SKU 库存充足正常扣减")
    void confirmPayment_sufficientStock_deducts() {
        // given: 订单 2 件，SKU 库存 5 充足
        testOrder.setStatus("pending");
        OrderItem skuItem = buildItemWithSku(100L, 2);
        ProductSku sku = ProductSku.builder().id(100L).stock(5).build();

        when(orderMapper.selectById("order-001")).thenReturn(testOrder);
        when(orderMapper.update(any(), any())).thenReturn(1);
        when(orderItemMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of(skuItem));
        when(productSkuMapper.selectById(100L)).thenReturn(sku);

        // when
        orderService.confirmPayment("order-001");

        // then: 正常扣减 SKU 库存 + 商品销量
        verify(productSkuMapper).deductStock(100L, 2);
        verify(productMapper).increaseSales(eq("prod-001"), eq(2), any(BigDecimal.class));
    }

    @Test
    @DisplayName("确认支付 - 非 pending 状态拒绝（原子流转返回 0 行）")
    void confirmPayment_rejectsNonPendingStatus() {
        // given: 订单已确认，原子条件更新（WHERE status=pending）未命中
        testOrder.setStatus("confirmed");
        when(orderMapper.selectById("order-001")).thenReturn(testOrder);
        when(orderMapper.update(any(), any())).thenReturn(0);

        // when & then
        assertThatThrownBy(() -> orderService.confirmPayment("order-001"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("只有待确认状态");
    }
}
