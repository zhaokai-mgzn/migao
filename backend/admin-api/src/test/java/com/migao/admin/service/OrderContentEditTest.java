// case_ids: OR-055

package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.OrderContentUpdateRequest;
import com.migao.admin.dto.OrderDetailResponse;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.entity.ProductSku;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.FinanceTransactionMapper;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderLogisticsMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProcessingFeeCombinationMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import com.migao.admin.mapper.ProductMapper;
import com.migao.admin.mapper.ProductSkuMapper;
import com.migao.admin.mapper.ProductionRouteRuleMapper;
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
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.ArgumentMatchers.nullable;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

/**
 * 待付款订单**内容编辑**（issue #5842；用户 2026-10-01 裁定「范围 = 全改」）。
 *
 * <p>判据六条（与 {@code OrderService.updatePendingOrderContent} 的六道闸门一一对应）：
 * ① 只有 {@code pending} 可改，其余 422 且**不写任何数据**；② 已有加工单 ⇒ 拒绝；
 * ③ 金额**服务端重算**（客户端金额一律不参与）；④ 库存前置校验按**新明细**重跑；
 * ⑤ 明细整体替换 + 审计留痕（前后差异）；⑥ **接线**：发货路径真的会调漂移守卫。</p>
 *
 * <h3>红证方向（每条判据"没有它会怎样"）</h3>
 * <ul>
 *   <li>删掉 ① 的 {@code assertContentEditable} ⇒ {@link #nonPendingOrderIsRejectedWith422AndWritesNothing}
 *       红（已收款单也能被改 = 改完金额与已收的钱对不上）；</li>
 *   <li>把 ③ 换成读请求里的金额 ⇒ {@link #amountIsRecalculatedOnServerSide} 红；</li>
 *   <li>删掉 ④ ⇒ {@link #stockIsRevalidatedAgainstNewItems} 红（改完买不起也能成立）；</li>
 *   <li>删掉 ⑥ ⇒ {@link #shipPathEnforcesDriftGuard} 红（守卫变成只有符号、没有接线）。</li>
 * </ul>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("待付款订单内容编辑（issue #5842）")
class OrderContentEditTest {

    private static final Long TENANT = 1L;
    private static final String ORDER_ID = "order-001";
    private static final String SKU_ID_RAW = "9001";

    @InjectMocks
    private OrderService orderService;

    @Mock private OrderMapper orderMapper;
    @Mock private OrderItemMapper orderItemMapper;
    @Mock private OrderLogisticsMapper orderLogisticsMapper;
    @Mock private ProcessingOrderMapper processingOrderMapper;
    @Mock private ProductMapper productMapper;
    @Mock private ProductSkuMapper productSkuMapper;
    @Mock private FinanceTransactionMapper financeTransactionMapper;
    @Mock private ProcessingFeeCombinationMapper processingFeeCombinationMapper;
    @Mock private ProductionRouteRuleMapper routeRuleMapper;
    @Mock private ProcessingFeeCombinationCommandService processingFeeCombinationCommandService;
    @Mock private StockLedgerService stockLedgerService;
    @Mock private ClientRequestIdService clientRequestIdService;
    @Mock private NotificationService notificationService;
    @Mock private CustomerService customerService;
    @Mock private UserService userService;
    @Mock private StockBatchConsumptionService stockBatchConsumptionService;
    /** 审计留痕（issue #5842）：内容编辑必须留下前后差异（字段注入，见 OrderService 的字段注释）。 */
    @Mock private AuditLogService auditLogService;

    private final ObjectMapper objectMapper = new ObjectMapper();

    private Order order;
    private OrderItem oldItem;

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(TENANT);
        ReflectionTestUtils.setField(orderService, "processingFeeCalculator",
                new ProcessingFeeCalculator(processingFeeCombinationMapper, routeRuleMapper));
        ReflectionTestUtils.setField(orderService, "stockBatchConsumptionService", stockBatchConsumptionService);
        ReflectionTestUtils.setField(orderService, "objectMapper", objectMapper);
        // 审计留痕是**字段注入**（不进构造签名）⇒ Mockito 的 @InjectMocks 不装配它，必须显式给
        ReflectionTestUtils.setField(orderService, "auditLogService", auditLogService);

        MybatisConfiguration conf = new MybatisConfiguration();
        MapperBuilderAssistant assistant = new MapperBuilderAssistant(conf, "");
        TableInfoHelper.initTableInfo(assistant, Order.class);
        TableInfoHelper.initTableInfo(assistant, OrderItem.class);

        order = Order.builder()
                .id(ORDER_ID)
                .tenantId(TENANT)
                .orderNo("ORD-20261001-0001")
                .customerName("张三")
                .customerPhone("13800138000")
                .customerAddress("北京市朝阳区")
                .totalAmount(new BigDecimal("599.00"))
                .actualAmount(new BigDecimal("599.00"))
                .discountAmount(BigDecimal.ZERO)
                .status("pending")
                .build();
        oldItem = OrderItem.builder()
                .id("item-old")
                .tenantId(TENANT)
                .orderId(ORDER_ID)
                .productId("prod-1")
                .productName("蜂巢帘")
                .quantity(new BigDecimal("2"))
                .unitPrice(new BigDecimal("299.50"))
                .subtotal(new BigDecimal("599.00"))
                .deleted(0)
                .build();
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    // ──────────────────────────── 夹具 ────────────────────────────

    /** 请求：1 行 × 数量 3 × 单价 50（服务端应收 = 150.00）。 */
    private OrderContentUpdateRequest request(String quantity, String unitPrice, String actualAmount) {
        OrderContentUpdateRequest request = new OrderContentUpdateRequest();
        request.setCustomerName("李四");
        request.setCustomerPhone("13900139000");
        request.setCustomerAddress("上海市浦东新区");
        request.setActualAmount(actualAmount == null ? null : new BigDecimal(actualAmount));
        OrderContentUpdateRequest.Item item = new OrderContentUpdateRequest.Item();
        item.setProductId("prod-1");
        item.setProductName("蜂巢帘");
        item.setQuantity(new BigDecimal(quantity));
        item.setUnitPrice(new BigDecimal(unitPrice));
        // 声明 SKU 身份 ⇒ 库存校验会真的走到 matchSkuId（判据 ④ 需要它）
        item.setProcessingInfo(new LinkedHashMap<>(Map.of("skuId", SKU_ID_RAW, "skuCode", "HC-01")));
        request.setItems(List.of(item));
        return request;
    }

    private void givenSkuStock(String stock) {
        ProductSku sku = new ProductSku();
        sku.setId(9001L);
        sku.setProductId("prod-1");
        sku.setStock(new BigDecimal(stock));
        when(productSkuMapper.selectById(9001L)).thenReturn(sku);
    }

    private void givenOrderItems(OrderItem... items) {
        when(orderItemMapper.selectList(any())).thenReturn(new ArrayList<>(List.of(items)));
    }

    // ──────────────────────────── 判据 ①：状态闸门 ────────────────────────────

    @Test
    @DisplayName("① 非 pending（已确认/生产中/已发货…）⇒ 422 + 中文文案，且**不写任何数据**")
    void nonPendingOrderIsRejectedWith422AndWritesNothing() {
        for (String status : List.of("confirmed", "producing", "packed", "shipped", "completed", "cancelled")) {
            order.setStatus(status);
            when(orderMapper.selectById(ORDER_ID)).thenReturn(order);

            assertThatThrownBy(() -> orderService.updatePendingOrderContent(ORDER_ID, request("3", "50", "150")))
                    .as("状态 %s 必须被拒", status)
                    .isInstanceOf(BusinessException.class)
                    .hasMessageContaining("只有「待付款」的订单可以修改内容");

            BusinessException e = (BusinessException) org.assertj.core.api.Assertions
                    .catchThrowable(() -> orderService.updatePendingOrderContent(ORDER_ID, request("3", "50", "150")));
            assertThat(e.getHttpStatus()).as("422（不是 400/500）").isEqualTo(422);
        }
        verify(orderMapper, never()).updateById(any(Order.class));
        verify(orderItemMapper, never()).insert(any(OrderItem.class));
        verify(orderItemMapper, never()).delete(any());
    }

    @Test
    @DisplayName("① 待付款（pending）⇒ 放行：收货信息与三金额都改成新值")
    void pendingOrderIsEditable() {
        givenSkuStock("999");
        givenOrderItems(oldItem);
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order);

        OrderDetailResponse detail = orderService.updatePendingOrderContent(ORDER_ID, request("3", "50", "150"));

        assertThat(detail).isNotNull();
        assertThat(order.getCustomerName()).isEqualTo("李四");
        assertThat(order.getCustomerPhone()).isEqualTo("13900139000");
        assertThat(order.getCustomerAddress()).isEqualTo("上海市浦东新区");
        assertThat(order.getActualAmount()).isEqualByComparingTo("150");
        verify(orderMapper).updateById(order);
    }

    // ──────────────────────────── 判据 ③：金额服务端重算 ────────────────────────────

    @Test
    @DisplayName("③ 金额一律服务端重算：应收 = 单价 × 数量（请求里根本没有小计字段）")
    void amountIsRecalculatedOnServerSide() {
        givenSkuStock("999");
        givenOrderItems(oldItem);
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order);

        orderService.updatePendingOrderContent(ORDER_ID, request("3", "50", "150"));

        assertThat(order.getTotalAmount()).isEqualByComparingTo("150");
        ArgumentCaptor<OrderItem> captor = ArgumentCaptor.forClass(OrderItem.class);
        verify(orderItemMapper).insert(captor.capture());
        assertThat(captor.getValue().getSubtotal()).isEqualByComparingTo("150");
        assertThat(captor.getValue().getQuantity()).isEqualByComparingTo("3");
        assertThat(captor.getValue().getUnitPrice()).isEqualByComparingTo("50");
    }

    @Test
    @DisplayName("③ 应收 − 优惠 ≈ 实收（容差 0.01）：不一致 ⇒ 422，且不落库")
    void amountMismatchIsRejected() {
        givenSkuStock("999");
        givenOrderItems(oldItem);
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order);

        assertThatThrownBy(() -> orderService.updatePendingOrderContent(ORDER_ID, request("3", "50", "100")))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("实收金额与应收不一致");
        verify(orderMapper, never()).updateById(any(Order.class));
    }

    // ──────────────────────────── 判据 ④：库存按新明细重跑 ────────────────────────────

    @Test
    @DisplayName("④ 改明细后库存不足 ⇒ 422（前置校验按**新明细**重跑，与建单同一套口径）")
    void stockIsRevalidatedAgainstNewItems() {
        givenSkuStock("1"); // 新明细要 3 米，只够 1 米
        givenOrderItems(oldItem);
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order);

        assertThatThrownBy(() -> orderService.updatePendingOrderContent(ORDER_ID, request("3", "50", "150")))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("库存不足")
                .hasMessageContaining("修改订单");
        verify(orderMapper, never()).updateById(any(Order.class));
    }

    @Test
    @DisplayName("④ pending 单**尚未扣库存** ⇒ 编辑明细不回滚库存（不写库存/台账）")
    void editDoesNotRollbackStock() {
        givenSkuStock("999");
        givenOrderItems(oldItem);
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order);

        orderService.updatePendingOrderContent(ORDER_ID, request("3", "50", "150"));

        verify(productSkuMapper, never()).updateById(any(ProductSku.class));
        verifyNoInteractions(stockLedgerService);
    }

    // ──────────────────────────── 判据 ②：已有加工单 ────────────────────────────

    @Test
    @DisplayName("② 已生成活跃加工单 ⇒ 422（内容已固化进快照，改订单会造成漂移）")
    void editRejectedWhenProcessingOrderExists() {
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order);
        when(processingOrderMapper.selectActiveByOrderId(ORDER_ID, TENANT)).thenReturn(
                ProcessingOrder.builder().id("po-1").orderId(ORDER_ID).tenantId(TENANT)
                        .processingOrderNo("JG-20261001-0001").status("generated").build());

        assertThatThrownBy(() -> orderService.updatePendingOrderContent(ORDER_ID, request("3", "50", "150")))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("已生成加工单")
                .hasMessageContaining("JG-20261001-0001");
        verify(orderMapper, never()).updateById(any(Order.class));
    }

    // ──────────────────────────── 判据 ⑤：明细替换 + 审计留痕 ────────────────────────────

    @Test
    @DisplayName("⑤ 明细整体替换：旧行软删 + 新行落库")
    void itemsAreReplaced() {
        givenSkuStock("999");
        givenOrderItems(oldItem);
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order);

        orderService.updatePendingOrderContent(ORDER_ID, request("3", "50", "150"));

        verify(orderItemMapper).delete(any());
        verify(orderItemMapper).insert(any(OrderItem.class));
    }

    @Test
    @DisplayName("⑤ 审计留痕：action=update_content / resourceType=order，且**带前后差异**")
    void auditLogCarriesBeforeAndAfter() {
        givenSkuStock("999");
        OrderItem newItem = OrderItem.builder().id("item-new").tenantId(TENANT).orderId(ORDER_ID)
                .productId("prod-1").productName("蜂巢帘").quantity(new BigDecimal("3"))
                .unitPrice(new BigDecimal("50")).subtotal(new BigDecimal("150")).deleted(0).build();
        // 第 1 次 = 改前快照；第 2 次 = 改后快照；第 3 次 = getOrderById 的明细读面
        when(orderItemMapper.selectList(any())).thenReturn(
                new ArrayList<>(List.of(oldItem)),
                new ArrayList<>(List.of(newItem)),
                new ArrayList<>(List.of(newItem)));
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order);

        orderService.updatePendingOrderContent(ORDER_ID, request("3", "50", "150"));

        @SuppressWarnings("unchecked")
        ArgumentCaptor<Map<String, Object>> detailsCaptor = ArgumentCaptor.forClass(Map.class);
        verify(auditLogService).recordLog(eq(TENANT), nullable(String.class), nullable(String.class),
                eq("update_content"), eq("order"), isNull(), eq(ORDER_ID), eq("ORD-20261001-0001"),
                detailsCaptor.capture(), isNull(), isNull());
        Map<String, Object> details = detailsCaptor.getValue();
        @SuppressWarnings("unchecked")
        Map<String, Object> before = (Map<String, Object>) details.get("before");
        @SuppressWarnings("unchecked")
        Map<String, Object> after = (Map<String, Object>) details.get("after");
        assertThat(before).containsEntry("customerName", "张三");
        // 金额按**数值**比（BigDecimal 的 equals 连 scale 一起比；金额只认值，同族纪律见 ProcessingFeeCalculator.money）
        assertThat((BigDecimal) before.get("totalAmount")).isEqualByComparingTo("599.00");
        assertThat(after).containsEntry("customerName", "李四");
        assertThat((BigDecimal) after.get("totalAmount")).isEqualByComparingTo("150");
        assertThat((List<?>) before.get("items")).hasSize(1);
    }

    // ──────────────────────────── 判据 ⑥：守卫接线（选项 B） ────────────────────────────

    @Test
    @DisplayName("⑥ 接线：发货路径上「订单加工项 ≠ 加工单快照」被拦下（守卫不是只有符号）")
    void shipPathEnforcesDriftGuard() {
        Order producing = Order.builder().id(ORDER_ID).tenantId(TENANT).orderNo("ORD-20261001-0001")
                .status("producing").build();
        // 订单行：两个加工项（加工单生成后被加了一项）
        OrderItem drifted = OrderItem.builder().id("item-1").orderId(ORDER_ID).tenantId(TENANT)
                .productName("蜂巢帘").quantity(new BigDecimal("3")).deleted(0)
                .processingInfo(Map.of("processingItems", List.of(
                        Map.of("id", "p1", "name", "韩褶", "quantity", new BigDecimal("1")),
                        Map.of("id", "p2", "name", "加铅块", "quantity", new BigDecimal("1")))))
                .build();
        when(orderMapper.selectById(ORDER_ID)).thenReturn(producing);
        when(orderItemMapper.selectList(any())).thenReturn(new ArrayList<>(List.of(drifted)));
        when(processingOrderMapper.countCompletedByOrderId(ORDER_ID, TENANT)).thenReturn(1L);
        when(processingOrderMapper.selectActiveByOrderId(ORDER_ID, TENANT)).thenReturn(
                ProcessingOrder.builder().id("po-1").orderId(ORDER_ID).tenantId(TENANT)
                        .processingOrderNo("JG-20261001-0001").status("completed")
                        .itemsSnapshot(List.of(Map.of("itemId", "item-1", "processingItems",
                                List.of(Map.of("id", "p1", "name", "韩褶", "quantity", new BigDecimal("1"))))))
                        .build());

        assertThatThrownBy(() -> orderService.updateOrderStatus(ORDER_ID, "shipped"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("与加工单快照不一致");
    }

    @Test
    @DisplayName("⑥ 对照：快照与订单一致 ⇒ 漂移守卫**不**拦（判据不是「含加工项就一律拒」）")
    void matchingSnapshotIsNotDrift() {
        Order producing = Order.builder().id(ORDER_ID).tenantId(TENANT).status("producing").build();
        OrderItem same = OrderItem.builder().id("item-1").orderId(ORDER_ID).tenantId(TENANT)
                .processingInfo(Map.of("processingItems", List.of(
                        Map.of("id", "p1", "name", "韩褶", "quantity", new BigDecimal("1")))))
                .build();
        when(orderItemMapper.selectList(any())).thenReturn(new ArrayList<>(List.of(same)));
        when(processingOrderMapper.countCompletedByOrderId(ORDER_ID, TENANT)).thenReturn(1L);
        when(processingOrderMapper.selectActiveByOrderId(ORDER_ID, TENANT)).thenReturn(
                ProcessingOrder.builder().id("po-1").orderId(ORDER_ID).tenantId(TENANT)
                        .itemsSnapshot(List.of(Map.of("itemId", "item-1", "processingItems",
                                List.of(Map.of("id", "p1", "name", "韩褶", "quantity", new BigDecimal("1"))))))
                        .build());

        assertThat(OrderShipGuard.hasProcessingDrift(orderItemMapper, processingOrderMapper, objectMapper, producing))
                .isFalse();
        org.assertj.core.api.Assertions.assertThatCode(() -> OrderShipGuard.assertProcessingCompletedBeforeShip(
                orderItemMapper, processingOrderMapper, objectMapper, producing)).doesNotThrowAnyException();
    }

    @Test
    @DisplayName("⑥ 边界：无加工单 ⇒ 无漂移可比（拦货由「须先完成加工单」那条管，不在这里误拦）")
    void noProcessingOrderMeansNoDrift() {
        Order producing = Order.builder().id(ORDER_ID).tenantId(TENANT).status("producing").build();
        when(processingOrderMapper.selectActiveByOrderId(anyString(), any())).thenReturn(null);
        assertThat(OrderShipGuard.hasProcessingDrift(orderItemMapper, processingOrderMapper, objectMapper, producing))
                .isFalse();
    }
}
