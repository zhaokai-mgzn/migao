// case_ids: MC-199
package com.migao.admin.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.dto.OrderCreateRequest;
import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.mapper.FinanceTransactionMapper;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderLogisticsMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.PrintLogMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import com.migao.admin.mapper.ProductMapper;
import com.migao.admin.mapper.ProductSkuMapper;
import com.migao.admin.time.BusinessClock;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.test.util.ReflectionTestUtils;

import java.lang.reflect.Method;
import java.lang.reflect.Modifier;
import java.math.BigDecimal;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * {@link OrderService} 切片（issue #8191，P2-1c）的<b>接线判据</b>：库存族与财务流水族搬到
 * {@link OrderStockService} / {@link OrderFeeSupport} 之后，门面**必须真的把它们转出去**。
 *
 * <p><b>为什么这条判据会红</b>：它先把门面的两个新字段替换成 Mockito 替身，再从**原有公开入口**
 * （{@code confirmPayment} / {@code cancelOrder} / {@code refundOrder} /
 * {@code restoreStockForReturn} / {@code validateStockSufficientForRequest}）驱动。
 * 一旦有人把委托改回内联实现（或换了目标服务），替身上就收不到那次调用 ⇒ 当场红。
 * 「拆分后既有测试仍然绿」不具备这个判别力：把门面整体内联回去，那 152 条也照样绿。</p>
 *
 * <p><b>覆盖口径</b>：本类只钉「谁被调用、带了什么参数」；行为等价由
 * {@code OrderServiceSliceSnapshotTest}（拆分前录制的快照）与既有 {@code OrderServiceTest}（152 条）承担。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class OrderServiceSliceWiringTest {

    @Mock
    private OrderStockService orderStockService;
    @Mock
    private OrderFeeSupport orderFeeSupport;

    @Mock
    private OrderMapper orderMapper;
    @Mock
    private OrderItemMapper orderItemMapper;
    @Mock
    private OrderLogisticsMapper orderLogisticsMapper;
    @Mock
    private CustomerService customerService;
    @Mock
    private ProductMapper productMapper;
    @Mock
    private ProductSkuMapper productSkuMapper;
    @Mock
    private FinanceTransactionMapper financeTransactionMapper;
    @Mock
    private NotificationService notificationService;
    @Mock
    private ProcessingOrderMapper processingOrderMapper;
    @Mock
    private UserService userService;
    @Mock
    private ClientRequestIdService clientRequestIdService;
    @Mock
    private StockLedgerService stockLedgerService;
    @Mock
    private ProcessingFeeCalculator processingFeeCalculator;
    @Mock
    private ProcessingFeeCombinationCommandService processingFeeCombinationCommandService;
    @Mock
    private PrintLogMapper printLogMapper;

    @InjectMocks
    private OrderService orderService;

    private Order order;

    @BeforeEach
    void setUp() {
        // 两个新服务是**字段注入**（本类构造签名被多处测试显式装配，加参数会把它们全改一遍）⇒
        // @InjectMocks 走构造注入后不再注入字段，必须显式装配（同 OrderServiceTest 的做法）。
        ReflectionTestUtils.setField(orderService, "orderStockService", orderStockService);
        ReflectionTestUtils.setField(orderService, "orderFeeSupport", orderFeeSupport);
        ReflectionTestUtils.setField(orderService, "businessClock",
                new BusinessClock(Clock.fixed(Instant.parse("2026-11-04T02:00:00Z"), ZoneOffset.UTC)));

        // Lambda 条件构造器需要实体 lambda 缓存（否则 MyBatis-Plus 抛
        // 「can not find lambda cache for this entity」），与 OrderServiceTest 同法。
        MybatisConfiguration configuration = new MybatisConfiguration();
        MapperBuilderAssistant assistant = new MapperBuilderAssistant(configuration, "");
        TableInfoHelper.initTableInfo(assistant, Order.class);
        TableInfoHelper.initTableInfo(assistant, OrderItem.class);

        order = Order.builder()
                .id("order-8191")
                .tenantId(1L)
                .orderNo("ORD-20261104-0001")
                .status("confirmed")
                .totalAmount(new BigDecimal("100.00"))
                .actualAmount(new BigDecimal("100.00"))
                .build();
    }

    /**
     * issue #8681（P2-1e 第八批）：{@code restoreStockForReturn} 的门面转发已<b>退休</b> ⇒ 原来那条
     * 「门面必须把它转出去」的判据<b>失去对象</b>。按本单既定范式<b>不删、不恒绿</b>，改成<b>直测实现点</b>：
     * 唯一实现点仍是 {@link OrderStockService#restoreStockForReturn}，且<b>事务注解逐字留在它身上</b>
     * —— 这正是「注解跟着方法走」这条硬约束在售后回补这一处的机械判据（转发删掉时最容易连注解一起丢）。
     */
    @Test
    @DisplayName("售后回补的实现在 OrderStockService，且 @Transactional(rollbackFor=Exception) 逐字跟随")
    void restoreStockForReturnIsImplementedAtTheStockServiceWithItsTransaction() throws NoSuchMethodException {
        Method method = OrderStockService.class.getDeclaredMethod("restoreStockForReturn", String.class);

        assertThat(method.getReturnType().getName()).isEqualTo("void");
        org.springframework.transaction.annotation.Transactional tx =
                method.getAnnotation(org.springframework.transaction.annotation.Transactional.class);
        assertThat(tx).as("售后回补的事务注解必须留在唯一实现点（转发退休不得连注解一起丢）").isNotNull();
        assertThat(tx.rollbackFor()).containsExactly(Exception.class);
    }

    @Test
    @DisplayName("门面委托：下单前置库存校验必须转到 OrderStockService（包内可见入口，调用方零改动）")
    void validateStockSufficientForRequestDelegates() {
        OrderCreateRequest request = new OrderCreateRequest();
        OrderCreateRequest.OrderItemRequest item = new OrderCreateRequest.OrderItemRequest();
        item.setProductId("prod-1");
        item.setQuantity(new BigDecimal("2.5"));
        request.setItems(List.of(item));

        orderService.sharedParts().validateStockSufficientForRequest(request, "下单");

        verify(orderStockService).validateStockSufficientForRequest(request, "下单");
    }

    @Test
    @DisplayName("门面委托：confirmPayment 的「校验 → 扣减 → 收款流水」三步都落在两个新服务上")
    void confirmPaymentDelegatesStockAndFee() {
        when(orderMapper.selectById("order-8191")).thenReturn(order);
        when(orderMapper.update(any(), any())).thenReturn(1);

        lifecycle().confirmPayment("order-8191");

        verify(orderStockService).validateStockSufficient(order);
        verify(orderStockService).deductStockAndIncreaseSales("order-8191");
        verify(orderStockService, never()).restoreStockAndDecreaseSales(anyString());
        // 收款点是 3 参重载（金额取订单实收，由 OrderFeeSupport 自己算）—— 门面不预先算金额
        verify(orderFeeSupport).recordFinanceTransaction(order, "income", "订单确认收款");
        verify(orderFeeSupport, never()).effectiveActualAmount(order);
    }

    @Test
    @DisplayName("门面委托：cancelOrder 的「回补库存 + 退款流水」两步都落在两个新服务上")
    void cancelOrderDelegatesRestoreAndRefund() {
        when(orderMapper.selectById("order-8191")).thenReturn(order);
        when(orderMapper.update(any(), any())).thenReturn(1);
        when(processingOrderMapper.selectActiveByOrderId(any(), any())).thenReturn(null);
        when(orderFeeSupport.effectiveActualAmount(order)).thenReturn(new BigDecimal("100.00"));

        lifecycle().cancelOrder("order-8191", "客户不要了", orderService.sharedParts());

        verify(orderStockService).restoreStockAndDecreaseSales("order-8191");
        verify(orderStockService, never()).deductStockAndIncreaseSales(anyString());
        verify(orderFeeSupport).effectiveActualAmount(order);
        verify(orderFeeSupport).recordFinanceTransaction(
                eq(order), eq(new BigDecimal("100.00")), eq("refund"), eq("订单取消退款"));
    }

    @Test
    @DisplayName("门面委托：refundOrder 的实收取数与退款流水都落在 OrderFeeSupport，且不碰库存族")
    void refundOrderDelegatesFeeSupport() {
        when(orderMapper.selectById("order-8191")).thenReturn(order);
        when(orderMapper.update(any(), any())).thenReturn(1);
        when(orderFeeSupport.effectiveActualAmount(order)).thenReturn(new BigDecimal("100.00"));

        lifecycle().refundOrder("order-8191", new BigDecimal("30.00"), "少发一件");

        verify(orderFeeSupport).effectiveActualAmount(order);
        verify(orderFeeSupport).recordFinanceTransaction(
                eq(order), eq(new BigDecimal("30.00")), eq("refund"), eq("订单退款: 少发一件"));
        // 退款不改订单状态、不动库存 —— 切片没有把这条语义挪进库存族
        verify(orderStockService, never()).restoreStockAndDecreaseSales(anyString());
        verify(orderStockService, never()).restoreStockForReturn(anyString());
    }

    /**
     * 同一批的另一半（**反射**夹住，与退休守护的源码扫描互为正交）：门面里<b>不再有</b>这个入口。
     * 它同时给上一条兜底 —— 「实现点还在」与「门面没了」两侧都判，才不会出现「两边都没了 ⇒ 恒绿」。
     */
    @Test
    @DisplayName("公开签名退休：门面不再声明 restoreStockForReturn（加回来 ⇒ 本判据红）")
    void restoreStockForReturnKeepsPublicSignature() {
        assertThatThrownBy(() -> OrderService.class.getMethod("restoreStockForReturn", String.class))
                .as("门面转发已退休（调用方直连 OrderStockService）；把它加回来 ⇒ 本判据当场红")
                .isInstanceOf(NoSuchMethodException.class);
    }

    /**
     * 门面**自己懒构造的那一份**生命周期实现点（issue #8681，P2-1e 第六批）：换的只是「谁被驱动」，
     * 同一条调用链、同一份协作者（Mapper / 库存 / 流水 / 时钟都是门面已装配的那几个）。
     */
    private OrderLifecycleService lifecycle() {
        return ReflectionTestUtils.invokeMethod(orderService, "lifecycleService");
    }

}
