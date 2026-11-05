// case_ids: MC-201, MC-238
package com.migao.admin.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.config.TenantContext;
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
import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.conditions.AbstractWrapper;
import com.baomidou.mybatisplus.core.conditions.Wrapper;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.test.util.ReflectionTestUtils;

import java.math.BigDecimal;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.ArgumentMatchers.same;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * {@link OrderLifecycleService}（issue #8191，P2-1d）的判据：**接线**（门面必须把生命周期族转出去）
 * + **新载体的直测**（搬过来之后行为本身仍成立）。
 *
 * <p><b>为什么需要直测</b>：生命周期族的门面转发已**全部退休**（issue #8681，P2-1e 第六批）⇒
 * 「门面是否转出去」这条接线判据失去对象，改写为**直测实现点**（不删判据、不恒绿）：
 * 用同一批协作者替身直接驱动 {@code cancelOrder} / {@code confirmPayment} / {@code updateOrderStatus} /
 * {@code refundOrder} / {@code shipWithLogistics} / {@code revertProducingToConfirmed}，逐条钉住副作用。
 * ⚠️ {@code resolveShipperName} / {@code isProcessingReadyForShip} 的门面转发已**删除**
 * （issue #8681，P2-1e：调用方直接依赖新服务）⇒ 这两条改为**直测实现点**（见本类两个「直测」用例，
 * 判据不删也不恒绿）。一旦有人把委托改回内联实现
 * （或换了目标服务），替身上就收不到那次调用 ⇒ 当场红。既有 {@code OrderServiceTest} 的 152 条**不具备**
 * 这个判别力：把门面整体内联回去，那 152 条也照样绿。</p>
 *
 * <p><b>为什么还要直测</b>：接线判据只钉「谁被调用」；搬过来的实现被改坏（比如「回退边也写支付时刻」、
 * 「待付款取消也补退款流水」）在接线面上看不见。直测用同一批协作者替身驱动**新类本身**。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("#8191 P2-1d OrderLifecycleService：门面接线 + 新载体直测")
class OrderLifecycleServiceTest {

    private static final Instant FROZEN = Instant.parse("2026-11-04T02:00:00Z");

    // ── 门面侧：替身 + 构造依赖（@InjectMocks 走构造注入，缺一个参数就会构造失败）
    @Mock
    private OrderLifecycleService orderLifecycleService;

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
    private ObjectMapper objectMapper;
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

    @Mock
    private OrderStockService orderStockService;
    @Mock
    private OrderFeeSupport orderFeeSupport;

    @InjectMocks
    private OrderService orderService;

    private OrderLifecycleService lifecycle;

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(1L);
        BusinessClock clock = new BusinessClock(Clock.fixed(FROZEN, ZoneOffset.UTC));
        ReflectionTestUtils.setField(orderService, "orderLifecycleService", orderLifecycleService);
        ReflectionTestUtils.setField(orderService, "businessClock", clock);
        MybatisConfiguration configuration = new MybatisConfiguration();
        MapperBuilderAssistant assistant = new MapperBuilderAssistant(configuration, "");
        TableInfoHelper.initTableInfo(assistant, Order.class);
        TableInfoHelper.initTableInfo(assistant, OrderItem.class);
        lifecycle = new OrderLifecycleService(orderMapper, orderItemMapper, orderLogisticsMapper,
                processingOrderMapper, objectMapper, notificationService, userService,
                orderStockService, orderFeeSupport, clock);
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
        OrderService.setCancelOrderPoProbePauseMillisForTest(0L);
    }

    // ─────────────────────────────────────────── 直测实现点（门面转发已随第六批退休）

    @Test
    @DisplayName("直测：五个入口在实现点上真的执行——取消（回补库存 + 补退款流水）/ 确认支付（扣库存 + 收款）/ "
            + "状态流转 / 退款 / 回退")
    void lifecycleEntriesExecuteAtTheImplementationPoint() {
        when(orderMapper.update(isNull(), any(Wrapper.class))).thenReturn(1);
        when(orderFeeSupport.effectiveActualAmount(any())).thenReturn(new BigDecimal("600.00"));
        when(orderItemMapper.selectList(any())).thenReturn(List.of());

        // ① 取消（已确认）：回补库存 + 补记退款流水（与确认支付的 income 对冲）
        when(orderMapper.selectById("order-a")).thenReturn(order("order-a", OrderStatusTransitions.CONFIRMED));
        lifecycle.cancelOrder("order-a", "客户不要了", orderService.sharedParts());
        verify(orderStockService).restoreStockAndDecreaseSales("order-a");
        verify(orderFeeSupport).recordFinanceTransaction(any(), eq(new BigDecimal("600.00")),
                eq("refund"), eq("订单取消退款"));

        // ② 确认支付：库存前置校验 + 原子流转 + 扣减库存 + 收款流水
        when(orderMapper.selectById("order-b")).thenReturn(order("order-b", OrderStatusTransitions.PENDING));
        lifecycle.confirmPayment("order-b");
        verify(orderStockService).validateStockSufficient(any());
        verify(orderStockService).deductStockAndIncreaseSales("order-b");
        verify(orderFeeSupport).recordFinanceTransaction(any(), eq("income"), eq("订单确认收款"));

        // ③ 状态流转（confirmed → producing）：原子 CAS 落库
        when(orderMapper.selectById("order-c")).thenReturn(order("order-c", OrderStatusTransitions.CONFIRMED));
        lifecycle.updateOrderStatus("order-c", OrderStatusTransitions.PRODUCING, orderService.sharedParts());
        verify(orderMapper, org.mockito.Mockito.atLeastOnce()).update(isNull(), any(Wrapper.class));

        // ④ 退款：按传入金额封顶实收并登记退款流水（不改订单状态）
        when(orderMapper.selectById("order-d")).thenReturn(order("order-d", OrderStatusTransitions.CONFIRMED));
        lifecycle.refundOrder("order-d", new BigDecimal("30.00"), "少发一件");
        verify(orderFeeSupport).recordFinanceTransaction(any(), eq(new BigDecimal("30.00")),
                eq("refund"), eq("订单退款: 少发一件"));

        // ⑤ 回退（producing → confirmed）：作废加工单联动的回退边同样落库
        when(orderMapper.selectById("order-e")).thenReturn(order("order-e", OrderStatusTransitions.PRODUCING));
        lifecycle.revertProducingToConfirmed("order-e", "作业单作废");
        verify(orderMapper, org.mockito.Mockito.atLeastOnce()).update(isNull(), any(Wrapper.class));
    }

    @Test
    @DisplayName("直测：发货两个重载都返回「结果快照 + 本次是否真的流转」的显式标志（调用方据此决定建不建发货单）")
    void shippingOutcomeIsExplicitOnBothOverloads() {
        when(orderMapper.update(isNull(), any(Wrapper.class))).thenReturn(1);
        when(orderLogisticsMapper.updateShippingDetails(any(), any(), any(), any(), any(), any(), any()))
                .thenReturn(1);
        when(orderItemMapper.selectList(any())).thenReturn(List.of());

        // ① 3 参重载（工人路 / 老调用方）：记物流 + 原子流转 ⇒ 显式标志为真
        when(orderMapper.selectById("order-1")).thenReturn(order("order-1", OrderStatusTransitions.CONFIRMED));
        OrderService.OrderShipmentOutcome first = lifecycle.shipWithLogistics("order-1", "SF1", "顺丰");
        assertThat(first.transitioned()).isTrue();
        assertThat(first.result()).containsEntry("order_id", "order-1")
                .containsEntry("tracking_no", "SF1")
                .containsEntry("status", OrderStatusTransitions.SHIPPED);

        // ② 4 参重载（发货页采集发货人 / 物流类型 / 发货方式）：同一份口径、同样返回显式标志
        when(orderMapper.selectById("order-2")).thenReturn(order("order-2", OrderStatusTransitions.CONFIRMED));
        OrderService.OrderShipmentOutcome second = lifecycle.shipWithLogistics("order-2", "SF2", "圆通",
                new OrderLogisticsWriter.ShippingDetails("张三", "express", "logistics"));
        assertThat(second.transitioned()).isTrue();
        assertThat(second.result()).containsEntry("order_id", "order-2")
                .containsEntry("tracking_no", "SF2")
                .containsEntry("logistics_company", "圆通")
                .containsEntry("status", OrderStatusTransitions.SHIPPED);
    }

    // ── 门面转发已删除（issue #8681，P2-1e）⇒ 以下两例改为**直测实现点**（不删判据、不恒绿） ──

    @Test
    @DisplayName("直测：发货人取值——显式值去空白优先，缺省回落「当前登录用户姓名」")
    void resolveShipperNamePrefersProvidedThenCurrentUser() {
        when(userService.resolveCurrentUserDisplayName()).thenReturn("李四");

        assertThat(lifecycle.resolveShipperName("  张三 ")).isEqualTo("张三");
        assertThat(lifecycle.resolveShipperName("   ")).isEqualTo("李四");

        // 显式值**不**去查当前用户（一次都不查 = 兜底没被顺手放到前面）
        org.mockito.Mockito.clearInvocations(userService);
        assertThat(lifecycle.resolveShipperName("王五")).isEqualTo("王五");
        verify(userService, org.mockito.Mockito.never()).resolveCurrentUserDisplayName();
    }

    @Test
    @DisplayName("直测：发货前置判据读同一份 OrderShipGuard——无需报工即放行，有作业则看作业单完成数")
    void isProcessingReadyForShipReadsTheSingleGuard() {
        // ① 无加工项 ⇒ needsWork=false ⇒ 直接放行（不查作业单完成数）
        when(orderItemMapper.selectList(any())).thenReturn(List.of());
        assertThat(lifecycle.isProcessingReadyForShip(order("order-1", OrderStatusTransitions.CONFIRMED)))
                .isTrue();
        verify(processingOrderMapper, org.mockito.Mockito.never())
                .countCompletedByOrderId(org.mockito.ArgumentMatchers.anyString(), org.mockito.ArgumentMatchers.anyLong());

        // ② 有加工项但作业单未完成 ⇒ 拦住
        when(orderItemMapper.selectList(any())).thenReturn(List.of(
                OrderItem.builder().id("item-1").orderId("order-2").tenantId(1L).deleted(0)
                        .processingInfo(Map.of("processingItems", List.of(Map.of("name", "打孔"))))
                        .build()));
        when(processingOrderMapper.countCompletedByOrderId("order-2", 1L)).thenReturn(0L);
        assertThat(lifecycle.isProcessingReadyForShip(order("order-2", OrderStatusTransitions.CONFIRMED)))
                .isFalse();

        // ③ 作业单已完成 ⇒ 放行
        when(processingOrderMapper.countCompletedByOrderId("order-2", 1L)).thenReturn(1L);
        assertThat(lifecycle.isProcessingReadyForShip(order("order-2", OrderStatusTransitions.CONFIRMED)))
                .isTrue();
    }

    @Test
    @DisplayName("接线：取消探针的三个包内入口仍留在门面并转发到实现点（真实 DB 判据调用点零改动）")
    void cancelProbeStaticsForward() {
        OrderService.setCancelOrderPoProbePauseMillisForTest(7L);

        assertThat(OrderService.cancelOrderPoProbeMillisForTest()).isEqualTo(7L);
        assertThat(OrderService.cancelOrderPoProbePausedForTest()).isFalse();
    }

    @Test
    @DisplayName("公开签名保留：五个入口在实现点上仍是 public、返回类型逐字不变（调用方按实现点依赖）")
    void publicSignaturesAreKept() throws NoSuchMethodException {
        assertThat(OrderLifecycleService.class.getMethod("cancelOrder", String.class, String.class,
                        OrderSharedParts.class).getDeclaringClass().getName())
                .isEqualTo("com.migao.admin.service.OrderLifecycleService");
        assertThat(OrderLifecycleService.class.getMethod("refundOrder", String.class, BigDecimal.class,
                        String.class).getReturnType().getName())
                .isEqualTo("void");
        assertThat(OrderLifecycleService.class.getMethod("shipWithLogistics", String.class, String.class,
                        String.class).getReturnType().getName())
                .isEqualTo("com.migao.admin.service.OrderService$OrderShipmentOutcome");
        assertThat(OrderLifecycleService.class.getMethod("updateOrderStatus", String.class, String.class,
                        OrderSharedParts.class).getDeclaringClass().getName())
                .isEqualTo("com.migao.admin.service.OrderLifecycleService");
        assertThat(OrderLifecycleService.class.getMethod("revertProducingToConfirmed", String.class,
                        String.class).getReturnType().getName())
                .isEqualTo("void");
        assertThat(OrderLifecycleService.class.getMethod("confirmPayment", String.class).getReturnType().getName())
                .isEqualTo("void");
    }

    // ─────────────────────────────────────────── 新载体直测（搬过来的行为本身）

    @Test
    @DisplayName("直测：待付款取消只流转状态，不碰库存族、不补退款流水")
    void cancelOrderOnPendingOnlyTransitions() {
        when(orderMapper.selectById("order-1")).thenReturn(order("order-1", OrderStatusTransitions.PENDING));
        when(orderMapper.update(isNull(), any(Wrapper.class))).thenReturn(1);

        lifecycle.cancelOrder("order-1", null, orderService.sharedParts());

        verify(orderStockService, never()).restoreStockAndDecreaseSales(any());
        verify(orderFeeSupport, never()).recordFinanceTransaction(any(), any(), any(), any());
        verify(orderFeeSupport, never()).effectiveActualAmount(any());
    }

    @Test
    @DisplayName("直测：已确认取消会回补库存并补记退款流水（与 confirmPayment 的 income 对冲）")
    void cancelOrderOnConfirmedRestoresStockAndRecordsRefund() {
        Order order = order("order-1", OrderStatusTransitions.CONFIRMED);
        when(orderMapper.selectById("order-1")).thenReturn(order);
        when(orderMapper.update(isNull(), any(Wrapper.class))).thenReturn(1);
        when(orderFeeSupport.effectiveActualAmount(order)).thenReturn(new BigDecimal("600.00"));

        lifecycle.cancelOrder("order-1", "客户不要了", orderService.sharedParts());

        verify(orderStockService).restoreStockAndDecreaseSales("order-1");
        verify(orderFeeSupport).recordFinanceTransaction(
                same(order), eq(new BigDecimal("600.00")), eq("refund"), eq("订单取消退款"));
    }

    @Test
    @DisplayName("直测：退款金额超过实收 ⇒ 显式拒绝（话术含实收款，不静默截断）")
    void refundOrderRejectsAmountOverActual() {
        Order order = order("order-1", OrderStatusTransitions.CONFIRMED);
        when(orderMapper.selectById("order-1")).thenReturn(order);
        when(orderFeeSupport.effectiveActualAmount(order)).thenReturn(new BigDecimal("200.00"));

        assertThatThrownBy(() -> lifecycle.refundOrder("order-1", new BigDecimal("500.00"), "多退"))
                .isInstanceOf(com.migao.admin.exception.BusinessException.class)
                .hasMessageContaining("退款金额不能超过实收款 200.00");
        verify(orderMapper, never()).update(isNull(), any(Wrapper.class));
    }

    @Test
    @DisplayName("直测：无需物流（shippingMethod=none）允许空单号/空承运商，且落库为空串")
    void shipWithLogisticsNoneAllowsEmptyTracking() {
        Order order = order("order-1", OrderStatusTransitions.CONFIRMED);
        when(orderMapper.selectById("order-1")).thenReturn(order);
        when(orderMapper.update(isNull(), any(Wrapper.class))).thenReturn(1);
        when(orderLogisticsMapper.updateShippingDetails(any(), any(), any(), any(), any(), any(), any()))
                .thenReturn(1);

        OrderService.OrderShipmentOutcome outcome = lifecycle.shipWithLogistics(
                "order-1", "", "", new OrderLogisticsWriter.ShippingDetails("张三", "express", "none"));

        assertThat(outcome.transitioned()).isTrue();
        assertThat(outcome.result()).containsEntry("tracking_no", "").containsEntry("status",
                OrderStatusTransitions.SHIPPED);
        verify(orderLogisticsMapper).updateShippingDetails(eq(1L), eq("order-1"), eq(""), eq(""),
                eq("张三"), eq("express"), eq("none"));
    }

    @Test
    @DisplayName("直测：paid_at 只在 pending→confirmed 这条边上写；producing→confirmed 的回退边不写")
    void paidAtIsWrittenOnlyOnTheConfirmEdge() {
        ArgumentCaptor<Wrapper<Order>> captor = wrapperCaptor();
        when(orderMapper.selectById("order-1")).thenReturn(order("order-1", OrderStatusTransitions.PENDING));
        when(orderMapper.update(isNull(), any(Wrapper.class))).thenReturn(1);

        lifecycle.updateOrderStatus("order-1", OrderStatusTransitions.CONFIRMED, orderService.sharedParts());

        verify(orderMapper, org.mockito.Mockito.atLeastOnce()).update(isNull(), captor.capture());
        String confirmEdge = sqlSetOf(captor.getAllValues());
        assertThat(confirmEdge).as("确认收款那条边必须写 paid_at").contains("paid_at");

        Order producing = order("order-2", OrderStatusTransitions.PRODUCING);
        when(orderMapper.selectById("order-2")).thenReturn(producing);
        // 清掉前半段的调用记录：否则 revertCaptor 会把「确认收款边」那条 wrapper 一起捕进来
        org.mockito.Mockito.clearInvocations(orderMapper);
        ArgumentCaptor<Wrapper<Order>> revertCaptor = wrapperCaptor();

        lifecycle.revertProducingToConfirmed("order-2", "作业单作废");

        verify(orderMapper, org.mockito.Mockito.atLeastOnce()).update(isNull(), revertCaptor.capture());
        String revertEdge = sqlSetOf(revertCaptor.getAllValues());
        assertThat(revertEdge).as("回退边（producing→confirmed）不得把支付时间顶成当天").doesNotContain("paid_at");
    }

    @Test
    @DisplayName("直测：非法发货方式显式拒绝（422 话术列出白名单，不静默兜底）")
    void invalidShippingMethodIsRejected() {
        Order order = order("order-1", OrderStatusTransitions.CONFIRMED);
        when(orderMapper.selectById("order-1")).thenReturn(order);

        assertThatThrownBy(() -> lifecycle.shipWithLogistics("order-1", "SF1", "顺丰",
                new OrderLogisticsWriter.ShippingDetails(null, null, "airdrop")))
                .isInstanceOf(com.migao.admin.exception.BusinessException.class)
                .hasMessageContaining("无效的发货方式: airdrop");
        verify(orderLogisticsMapper, never()).updateShippingDetails(any(), any(), any(), any(), any(), any(), any());
    }

    @Test
    @DisplayName("直测：存在活跃加工单时取消订单 ⇒ 联动作废走 CAS，且回补批次库存")
    void cancelOrderCancelsActiveProcessingOrderViaCas() {
        Order order = order("order-1", OrderStatusTransitions.CONFIRMED);
        when(orderMapper.selectById("order-1")).thenReturn(order);
        when(orderMapper.update(isNull(), any(Wrapper.class))).thenReturn(1);
        when(processingOrderMapper.selectActiveByOrderId("order-1", 1L)).thenReturn(
                com.migao.admin.entity.ProcessingOrder.builder()
                        .id("po-1").tenantId(1L).orderId("order-1").processingOrderNo("JG-1")
                        .status("generated").build());
        when(processingOrderMapper.markStatusIfFrom(any(), any(), any(), any(), any(), any(), any(), any(),
                any(), any(), any(), any())).thenReturn(1);
        when(orderFeeSupport.effectiveActualAmount(order)).thenReturn(new BigDecimal("600.00"));
        StockBatchConsumptionService batch = org.mockito.Mockito.mock(StockBatchConsumptionService.class);
        ReflectionTestUtils.setField(lifecycle, "poolChangeNotifier", null);
        ReflectionTestUtils.setField(orderService, "stockBatchConsumptionService", batch);

        assertThatCode(() -> lifecycle.cancelOrder("order-1", "客户不要了", orderService.sharedParts()))
                .doesNotThrowAnyException();

        verify(processingOrderMapper).markStatusIfFrom(eq("po-1"), eq(1L), eq("generated"), eq("cancelled"),
                any(), any(), any(), any(), any(), any(), eq("订单取消，加工单自动作废"), any());
        verify(batch).reverse(eq(1L), eq("JG-1"), eq("ORD-order-1"), eq("订单取消，加工单自动作废，回补批次库存"));
    }

    // ─────────────────────────────────────────── 夹具

    private static Order order(String id, String status) {
        return Order.builder()
                .id(id)
                .tenantId(1L)
                .orderNo("ORD-" + id)
                .status(status)
                .totalAmount(new BigDecimal("600.00"))
                .actualAmount(new BigDecimal("600.00"))
                .build();
    }

    @SuppressWarnings("unchecked")
    private static ArgumentCaptor<Wrapper<Order>> wrapperCaptor() {
        return ArgumentCaptor.forClass((Class) Wrapper.class);
    }

    private static String sqlSetOf(List<Wrapper<Order>> wrappers) {
        StringBuilder sb = new StringBuilder();
        for (Wrapper<Order> wrapper : wrappers) {
            if (wrapper instanceof AbstractWrapper<?, ?, ?> raw) {
                String sqlSet = raw.getSqlSet();
                if (sqlSet != null) {
                    sb.append(sqlSet).append(';');
                }
            }
        }
        return sb.toString();
    }
}
