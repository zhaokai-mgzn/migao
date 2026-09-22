// case_ids: PR-086
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.InboundOrder;
import com.migao.admin.entity.InboundOrderItem;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.entity.ProductSku;
import com.migao.admin.mapper.FinanceTransactionMapper;
import com.migao.admin.mapper.InboundOrderItemMapper;
import com.migao.admin.mapper.InboundOrderMapper;
import com.migao.admin.mapper.InboundOrderQueryMapper;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderLogisticsMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import com.migao.admin.mapper.ProductMapper;
import com.migao.admin.mapper.ProductSkuMapper;
import com.migao.admin.mapper.StockBatchMapper;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InOrder;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.test.util.ReflectionTestUtils;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.inOrder;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 🔴 <b>三个事件挂载点的纪律（issue #5182 判据 1 / 判据 10）</b>。
 *
 * <h2>挂的是什么、不许挂什么</h2>
 * 确认支付 / 入库过账 / 改单 / 取消四处，**只允许在既有业务全部完成之后**
 * 追加一句 {@code PoolChangeNotifier.notifySafely(...)}。该方法的
 * <b>既有行为、事务边界、异常语义逐字不变</b> —— 本类把它钉成可判定的四条：
 *
 * <ol>
 *   <li><b>通知发生在既有业务之后</b>：{@code InOrder} 断言「状态流转 / 扣减」先发生、
 *       通知后发生（挂到前面就等于用一次评估阻塞主流程）。</li>
 *   <li><b>通知抛异常 ⇒ 主流程仍成功</b>（本类最关键的一条）：让 {@code notify} 直接抛
 *       {@code RuntimeException}，确认支付必须**照常返回**、且库存扣减的副作用**照旧发生**
 *       （{@code increaseSales} 仍被调到）—— 判据 1「不启用 ⇒ 与今天逐值相同」与判据 10
 *       「评估失败不影响主流程」在挂载点这一层的落点。</li>
 *   <li><b>触发原因是四类之一</b>（不回传订单载荷：评估自己会重算池）。</li>
 *   <li><b>通知点失败**留痕可查**</b>：{@code INCIDENT_PRODUCTION_POOL_NOTIFY_FAILED}
 *       出现在日志里（不静默）。</li>
 * </ol>
 *
 * <p>红证（两条，都可机械复算）：① 把 {@code notifySafely} 的 {@code catch} 去掉
 * ⇒「通知抛异常 ⇒ 主流程仍成功」当场红；② 把 {@code notifySafely(...)} 那行从
 * {@code confirmPayment} 里删掉 ⇒「通知发生了 + 触发原因正确」当场红。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("#5182 事件挂载点：只在既有业务之后 + fail-soft（抛异常也不影响主流程）+ 留痕")
class AutoBatchMountPointTest {

    private static final Long TENANT = 5182L;

    // ── OrderService 侧
    @Mock private OrderMapper orderMapper;
    @Mock private OrderItemMapper orderItemMapper;
    @Mock private OrderLogisticsMapper orderLogisticsMapper;
    @Mock private ProductMapper productMapper;
    @Mock private ProductSkuMapper productSkuMapper;
    @Mock private FinanceTransactionMapper financeTransactionMapper;
    @Mock private ProcessingOrderMapper processingOrderMapper;
    @Mock private ObjectMapper objectMapper;
    @Mock private com.migao.admin.service.NotificationService notificationService;
    @Mock private UserService userService;
    @Mock private ClientRequestIdService clientRequestIdService;
    @Mock private StockLedgerService stockLedgerService;
    @Mock private CustomerService customerService;
    @Mock private PoolChangeNotifier poolChangeNotifier;

    @InjectMocks
    private OrderService orderService;

    // ── InboundOrderService 侧
    @Mock private InboundOrderMapper inboundOrderMapper;
    @Mock private InboundOrderItemMapper inboundOrderItemMapper;
    @Mock private InboundOrderQueryMapper inboundOrderQueryMapper;
    @Mock private StockBatchMapper stockBatchMapper;

    @InjectMocks
    private InboundOrderService inboundOrderService;

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(TENANT);
        // MyBatis-Plus 的 lambda 缓存：LambdaUpdateWrapper 的 Order::getId 等方法引用要能解析
        MybatisConfiguration conf = new MybatisConfiguration();
        MapperBuilderAssistant assistant = new MapperBuilderAssistant(conf, "");
        TableInfoHelper.initTableInfo(assistant, Order.class);
        TableInfoHelper.initTableInfo(assistant, OrderItem.class);
        TableInfoHelper.initTableInfo(assistant, ProductSku.class);
        // 通知点是**字段注入**（不扩构造签名）⇒ 手工装配（同 stockBatchConsumptionService 的先例）
        ReflectionTestUtils.setField(orderService, "poolChangeNotifier", poolChangeNotifier);
        ReflectionTestUtils.setField(inboundOrderService, "poolChangeNotifier", poolChangeNotifier);
    }

    // ─────────────────────────────────────────── ① 确认支付

    @Test
    @DisplayName("🔴 挂载点① 确认支付：既有业务完成之后才通知（InOrder）+ 触发原因 = order_confirmed")
    void confirmPaymentNotifiesAfterBusinessIsDone() {
        Order pending = pendingOrder();
        when(orderMapper.selectById("order-001")).thenReturn(pending);
        when(orderMapper.update(any(), any())).thenReturn(1);
        when(orderItemMapper.selectList(any(LambdaQueryWrapper.class)))
                .thenReturn(List.of(deductibleItem()));

        orderService.confirmPayment("order-001");

        InOrder inOrder = inOrder(orderMapper, productMapper, poolChangeNotifier);
        inOrder.verify(orderMapper).update(any(), any());
        inOrder.verify(productMapper).increaseSales(anyString(), any(BigDecimal.class),
                any(BigDecimal.class));
        inOrder.verify(poolChangeNotifier).notify(TENANT, PoolChangeNotifier.TRIGGER_ORDER_CONFIRMED);
    }

    @Test
    @DisplayName("🔴 挂载点① 判据10：通知点**抛异常** ⇒ 确认支付仍成功、库存扣减照旧（库存指纹不变）")
    void confirmPaymentStillSucceedsWhenTheNotifierThrows() {
        Order pending = pendingOrder();
        when(orderMapper.selectById("order-001")).thenReturn(pending);
        when(orderMapper.update(any(), any())).thenReturn(1);
        when(orderItemMapper.selectList(any(LambdaQueryWrapper.class)))
                .thenReturn(List.of(deductibleItem()));
        doThrow(new IllegalStateException("夹具：通知点炸了")).when(poolChangeNotifier)
                .notify(any(), any());

        assertThatCode(() -> orderService.confirmPayment("order-001"))
                .as("🔴 通知点是**优化触发**，它炸了绝不能让确认支付失败（#5158 的 fail-soft 同口径）")
                .doesNotThrowAnyException();

        verify(productMapper).increaseSales(eq("prod-001"), eq(BigDecimal.valueOf(2)),
                any(BigDecimal.class));
        // 状态流转（既有行为）照旧发生 —— 库存/销量的副作用一字不动
        verify(orderMapper).update(any(), any());
    }

    @Test
    @DisplayName("挂载点① 边界：通知点**未装配**（既有手工装配的单测）⇒ 跳过，不影响主流程")
    void missingNotifierIsSkippedWithoutBreakingTheMainFlow() {
        ReflectionTestUtils.setField(orderService, "poolChangeNotifier", null);
        Order pending = pendingOrder();
        when(orderMapper.selectById("order-001")).thenReturn(pending);
        when(orderMapper.update(any(), any())).thenReturn(1);
        when(orderItemMapper.selectList(any(LambdaQueryWrapper.class)))
                .thenReturn(List.of(deductibleItem()));

        assertThatCode(() -> orderService.confirmPayment("order-001")).doesNotThrowAnyException();
        verify(orderMapper).update(any(), any());
    }

    // ─────────────────────────────────────────── ② 入库过账

    @Test
    @DisplayName("🔴 挂载点② 入库过账：过账完成之后才通知，触发原因 = inbound_posted")
    void inboundPostNotifiesAfterPostingIsDone() {
        InboundOrder draft = draftInbound();
        InboundOrderItem line = inboundLine();
        when(inboundOrderMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(draft);
        when(inboundOrderMapper.markPosted(anyString(), anyLong(), any(), any())).thenReturn(1);
        when(inboundOrderItemMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of(line));
        when(productSkuMapper.selectById(11L)).thenReturn(existingSku());

        inboundOrderService.post("RK-20260924-0001", TENANT, "op");

        InOrder inOrder = inOrder(inboundOrderMapper, productSkuMapper, poolChangeNotifier);
        inOrder.verify(inboundOrderMapper).markPosted(anyString(), anyLong(), any(), any());
        inOrder.verify(productSkuMapper).receiveStock(anyLong(), any(), any(), anyString());
        inOrder.verify(poolChangeNotifier).notify(TENANT, PoolChangeNotifier.TRIGGER_INBOUND_POSTED);
    }

    @Test
    @DisplayName("🔴 挂载点② 判据10：通知点抛异常 ⇒ 过账仍成功、库存照旧加（过账语义一字不变）")
    void inboundPostStillSucceedsWhenTheNotifierThrows() {
        InboundOrder draft = draftInbound();
        InboundOrderItem line = inboundLine();
        when(inboundOrderMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(draft);
        when(inboundOrderMapper.markPosted(anyString(), anyLong(), any(), any())).thenReturn(1);
        when(inboundOrderItemMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of(line));
        when(productSkuMapper.selectById(11L)).thenReturn(existingSku());
        doThrow(new IllegalStateException("夹具：通知点炸了")).when(poolChangeNotifier)
                .notify(any(), any());

        assertThatCode(() -> inboundOrderService.post("RK-20260924-0001", TENANT, "op"))
                .as("通知点是优化触发 ⇒ 过账的既有行为、异常语义逐字不变")
                .doesNotThrowAnyException();

        verify(productSkuMapper).receiveStock(eq(11L), any(BigDecimal.class), any(), anyString());
        assertThat(draft.getStatus()).isEqualTo(InboundOrder.STATUS_POSTED);
    }

    // ─────────────────────────────────────────── ③ 改单 / 取消

    @Test
    @DisplayName("🔴 挂载点③-a 改单（加急/到货日）：通知触发原因 = order_updated")
    void updateUrgencyNotifiesWithOrderUpdated() {
        Order confirmed = confirmedOrder();
        when(orderMapper.selectById("order-001")).thenReturn(confirmed);
        when(orderMapper.update(any(), any())).thenReturn(1);

        orderService.updateUrgency("order-001", Boolean.TRUE, LocalDate.now().plusDays(3).toString());

        verify(poolChangeNotifier).notify(TENANT, PoolChangeNotifier.TRIGGER_ORDER_UPDATED);
    }

    @Test
    @DisplayName("🔴 挂载点③-b 取消订单：通知触发原因 = order_cancelled（作废回补腾出的余量要能被重算）")
    void cancelOrderNotifiesWithOrderCancelled() {
        Order confirmed = confirmedOrder();
        when(orderMapper.selectById("order-001")).thenReturn(confirmed);
        when(processingOrderMapper.selectActiveByOrderId("order-001", TENANT)).thenReturn(null);
        when(orderMapper.update(any(), any())).thenReturn(1);
        when(orderItemMapper.selectList(any(LambdaQueryWrapper.class)))
                .thenReturn(List.of(deductibleItem()));

        orderService.cancelOrder("order-001", "客户不要了");

        verify(poolChangeNotifier).notify(TENANT, PoolChangeNotifier.TRIGGER_ORDER_CANCELLED);
    }

    @Test
    @DisplayName("挂载点③ 判据10：改单时通知点抛异常 ⇒ 改单仍成功（订单字段照旧写入）")
    void updateUrgencyStillSucceedsWhenTheNotifierThrows() {
        Order confirmed = confirmedOrder();
        when(orderMapper.selectById("order-001")).thenReturn(confirmed);
        when(orderMapper.update(any(), any())).thenReturn(1);
        doThrow(new IllegalStateException("夹具：通知点炸了")).when(poolChangeNotifier)
                .notify(any(), any());

        assertThatCode(() -> orderService.updateUrgency("order-001", Boolean.TRUE, null))
                .doesNotThrowAnyException();
        verify(orderMapper).update(any(), any());
    }

    // ─────────────────────────────────────────── 夹具

    /** 会真的触发销量累加的明细行（无 {@code processingInfo} ⇒ 不做 SKU 级扣减，与既有单测同形）。 */
    private OrderItem deductibleItem() {
        return OrderItem.builder().id("item-001").tenantId(TENANT).orderId("order-001")
                .productId("prod-001").productName("蜂巢帘").quantity(BigDecimal.valueOf(2))
                .unitPrice(new BigDecimal("299.50")).subtotal(new BigDecimal("599.00")).build();
    }

    private Order pendingOrder() {
        return Order.builder().id("order-001").tenantId(TENANT).orderNo("ORD-001")
                .status("pending").totalAmount(new BigDecimal("599.00")).build();
    }

    private Order confirmedOrder() {
        return Order.builder().id("order-001").tenantId(TENANT).orderNo("ORD-001")
                .status("confirmed").totalAmount(BigDecimal.ZERO).actualAmount(BigDecimal.ZERO)
                .build();
    }

    private InboundOrder draftInbound() {
        return InboundOrder.builder().id("inbound-uuid-1").tenantId(TENANT)
                .inboundNo("RK-20260924-0001").status(InboundOrder.STATUS_DRAFT)
                .inboundDate(LocalDate.now()).build();
    }

    private InboundOrderItem inboundLine() {
        InboundOrderItem line = new InboundOrderItem();
        line.setId(100L);
        line.setTenantId(TENANT);
        line.setInboundOrderId("inbound-uuid-1");
        line.setSkuId(11L);
        line.setSkuCode("SKU-A");
        line.setProductId("prod-1");
        line.setQuantity(new BigDecimal("30"));
        line.setUnitCost(new BigDecimal("12.50"));
        return line;
    }

    private ProductSku existingSku() {
        return ProductSku.builder().id(11L).tenantId(TENANT).productId("prod-1")
                .skuCode("SKU-A").stock(new BigDecimal("5")).build();
    }
}
