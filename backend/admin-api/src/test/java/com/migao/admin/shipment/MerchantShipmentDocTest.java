// case_ids: OR-045, OR-046, DF-017
package com.migao.admin.shipment;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.entity.OrderShipment;
import com.migao.admin.entity.OrderShipmentItem;
import com.migao.admin.entity.Product;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderLogisticsMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.OrderShipmentItemMapper;
import com.migao.admin.mapper.OrderShipmentMapper;
import com.migao.admin.mapper.OrderShipmentQueryMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import com.migao.admin.mapper.ProductMapper;
import com.migao.admin.service.ClientRequestIdService;
import com.migao.admin.service.ImageRecognitionClient;
import com.migao.admin.service.OrderShipmentService;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import java.math.BigDecimal;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 🔴 <b>商家/生产发货路必须产出可查的发货单</b>（issue #6171，用户 2026-10-03 裁定「要建」）。
 *
 * <h2>病根（本单现场）</h2>
 * <p>{@code POST /api/admin/production/orders/{orderId}/ship} 修前**不产生任何发货单**
 * （实测 {@code order_shipments=0}）⇒ 该订单在「发货单」列表读面（{@code GET /api/admin/shipments}）
 * 里永远查不到、无实发数量（#5939 新功能的漏单形态）。</p>
 *
 * <h2>实发数量口径（本单的集成方裁定，包内已核）</h2>
 * <p>该端点请求体只有运单号 / 承运商、<b>没有数量</b> ⇒ 逐 {@code order_item} 记
 * {@code 订单量 − 已发合计}（判定本体 = {@code ShipmentInvariants.remainingLines}，
 * 与「累计已发 ≤ 订单量」共用同一份累计口径）。{@code order_shipment_items} 的必填列
 * （{@code shipped_quantity} / {@code shipment_id} / {@code order_id} / {@code unit}）逐列都有来源：
 * 数量 = 余量、单位 = 订单行商品的计价单位（{@code products.unit}，缺 ⇒ 列默认同值
 * {@code "件"}）、套/卷数**不填**（缺值不填 0）。单位取自商品货号这一来源可核 —— 它正是
 * 商家在商品页定价时用的那一个数（{@code UnitSourceIsProductUnit}）。
 *
 * <h2>它锁什么（每条都能单独变红）</h2>
 * <table>
 *   <tr><th>#</th><th>判据</th><th>怎么让它单独红</th></tr>
 *   <tr><td>1</td><td>成功发货 ⇒ 恰一张发货单 + 逐 {@code order_item} 的一行明细，
 *       数量 = 订单未发余量、{@code source='admin'}（{@link #shipCreatesExactlyOneDocumentWithRemainingQuantities}）</td>
 *       <td>不建单 ⇒ {@code insert} 零调用（红）；写全量而不是余量 ⇒ 数量断言红</td></tr>
 *   <tr><td>2</td><td><b>部分已发</b> ⇒ 余量 = 订单量 − 已发（不是再发一次订单量）</td>
 *       <td>{@link #remainingIsOrderQuantityMinusAlreadyShipped}</td></tr>
 *   <tr><td>3</td><td>余量为 0 ⇒ 4xx 且**零写**（不静默建空单）</td>
 *       <td>{@link #zeroRemainingIsRejectedWithoutWritingAnything}</td></tr>
 *   <tr><td>4</td><td>订单已 {@code shipped}（本路已无流转）⇒ 4xx 且零写 ⇒ 重复调用建不出第二张</td>
 *       <td>{@link #alreadyShippedOrderIsRejectedSoSecondCallCannotCreateSecondDocument}</td></tr>
 *   <tr><td>5</td><td>单位有可核来源（商品货号计价单位；取不到 ⇒ 列默认同值兜底，
 *       不编第二种口径）</td>
 *       <td>{@link #unitComesFromProductPricingUnit} / {@link #unitFallsBackToColumnDefault}</td></tr>
 *   <tr><td>6</td><td>跨租户 ⇒ 4xx（不落库）</td>
 *       <td>{@link #otherTenantOrderIsNotFoundAndNothingIsWritten}</td></tr>
 * </table>
 *
 * <h2>与另外两处判据的分工（不互为副本）</h2>
 * <ul>
 *   <li>{@code ProductionControllerTest}：**端点面** —— 写序（零写拒绝 / ③ 步在后）、
 *       同键回放时发货单恰一张、拒绝时不建单；</li>
 *   <li>{@code MerchantShipmentDocGuardTest}：**类级面** —— 每一条发货路都必须登记
 *       「它怎么建可查的发货单」，新增第三条路而漏建单 ⇒ 红；</li>
 *   <li>本类：**服务面** —— 建单语义本身（数量口径 / 零写 / 单位来源）。</li>
 * </ul>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("商家发货路：产出可查的发货单（数量 = 未发余量，与 S1 不变量共存）")
class MerchantShipmentDocTest {

    private static final Long TENANT = 1L;
    private static final Long OTHER_TENANT = 2L;
    private static final String ORDER_ID = "order-6171";
    private static final String ORDER_NO = "CSO261003-0001";
    private static final String ITEM_ID = "item-a";
    private static final String PRODUCT_ID = "prod-a";
    private static final String SHIPMENT_ID = "ship-6171";

    @Mock private OrderMapper orderMapper;
    @Mock private OrderItemMapper orderItemMapper;
    @Mock private OrderLogisticsMapper orderLogisticsMapper;
    @Mock private OrderShipmentMapper orderShipmentMapper;
    @Mock private OrderShipmentItemMapper orderShipmentItemMapper;
    @Mock private OrderShipmentQueryMapper orderShipmentQueryMapper;
    @Mock private ProcessingOrderMapper processingOrderMapper;
    @Mock private ClientRequestIdService clientRequestIdService;
    @Mock private ImageRecognitionClient imageRecognitionClient;
    @Mock private ProductMapper productMapper;

    private OrderShipmentService service;

    @BeforeAll
    static void initLambdaCache() {
        TableInfoHelper.initTableInfo(new MapperBuilderAssistant(new MybatisConfiguration(), ""), Order.class);
    }

    @BeforeEach
    void setUp() {
        // 真实服务（只 mock Mapper）—— 本类断言的是服务层口径，用 mock 服务会把判据退化成断言桩
        service = new OrderShipmentService(orderMapper, orderItemMapper, orderLogisticsMapper,
                orderShipmentMapper, orderShipmentItemMapper, processingOrderMapper,
                clientRequestIdService, imageRecognitionClient, new ObjectMapper(),
                productMapper, orderShipmentQueryMapper);
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order(TENANT, "confirmed"));
        when(orderShipmentMapper.selectByOrderId(ORDER_ID, TENANT)).thenReturn(List.of());
        when(orderShipmentItemMapper.selectByOrderId(ORDER_ID, TENANT)).thenReturn(List.of());
        when(orderShipmentMapper.insert(any(OrderShipment.class))).thenAnswer(inv -> {
            OrderShipment row = inv.getArgument(0);
            if (row.getId() == null) {
                row.setId(SHIPMENT_ID);
            }
            return 1;
        });
        when(productMapper.selectById(PRODUCT_ID)).thenReturn(product("米"));
    }

    // ══════════════════════════════════════════════════════════════════════════
    // 判据 1 / 2：建单 + 数量 = 未发余量
    // ══════════════════════════════════════════════════════════════════════════

    @Test
    @DisplayName("判据 1：发货成功 ⇒ 恰一张发货单（source=admin）+ 明细数量 = 订单量、单位 = 商品计价单位")
    void shipCreatesExactlyOneDocumentWithRemainingQuantities() {
        when(orderItemMapper.selectList(any())).thenReturn(List.of(orderItem(ITEM_ID, "12.50")));

        OrderShipment shipment = service.recordMerchantShipment(ORDER_ID, "SF6171", "顺丰", TENANT);

        assertThat(shipment.getSource())
                .as("source 必须是 schema 既有取值 admin（用户裁定：不许新造取值）")
                .isEqualTo(OrderShipmentService.SOURCE_ADMIN);
        assertThat(shipment.getTrackingNo()).isEqualTo("SF6171");
        assertThat(shipment.getLogisticsCompany()).isEqualTo("顺丰");
        assertThat(shipment.getOrderNo()).isEqualTo(ORDER_NO);
        assertThat(shipment.getShippedAt()).as("发货单必须记发货时刻（否则「发货了没有」不可核）").isNotNull();
        verify(orderShipmentMapper, times(1)).insert(any(OrderShipment.class));

        ArgumentCaptor<OrderShipmentItem> captor = ArgumentCaptor.forClass(OrderShipmentItem.class);
        verify(orderShipmentItemMapper, times(1)).insert(captor.capture());
        OrderShipmentItem line = captor.getValue();
        assertThat(line.getShipmentId()).isEqualTo(SHIPMENT_ID);
        assertThat(line.getOrderId()).isEqualTo(ORDER_ID);
        assertThat(line.getOrderItemId()).isEqualTo(ITEM_ID);
        assertThat(line.getShippedQuantity())
                .as("实发数量 = 订单未发余量（请求体没有数量，余量是唯一不编造的来源）")
                .isEqualByComparingTo("12.50");
        assertThat(line.getUnit()).isEqualTo("米");
        assertThat(line.getSetCount()).as("缺值不填 0（套数不由数量推算）").isNull();
        assertThat(line.getRollCount()).as("缺值不填 0（卷数不由数量推算）").isNull();
    }

    @Test
    @DisplayName("判据 2：部分已发 ⇒ 余量 = 订单量 − 已发合计（不是再发一次订单量）")
    void remainingIsOrderQuantityMinusAlreadyShipped() {        when(orderItemMapper.selectList(any())).thenReturn(List.of(orderItem(ITEM_ID, "10")));
        OrderShipmentItem earlier = OrderShipmentItem.builder()
                .shipmentId("ship-earlier").orderId(ORDER_ID).orderItemId(ITEM_ID)
                .shippedQuantity(new BigDecimal("4.50")).unit("米").build();
        when(orderShipmentItemMapper.selectByOrderId(ORDER_ID, TENANT)).thenReturn(List.of(earlier));

        service.recordMerchantShipment(ORDER_ID, "SF-REST", "顺丰", TENANT);

        ArgumentCaptor<OrderShipmentItem> captor = ArgumentCaptor.forClass(OrderShipmentItem.class);
        verify(orderShipmentItemMapper).insert(captor.capture());
        assertThat(captor.getValue().getShippedQuantity())
                .as("10 − 4.5 = 5.5（既发合计跨全部发货单，含工人路发的那些）")
                .isEqualByComparingTo("5.50");
    }

    @Test
    @DisplayName("判据 1/2：多订单行**逐行**各落一行明细（两行余量不同 ⇒ 两行数量各自正确）")
    void everyOrderItemGetsItsOwnLineWithItsOwnRemaining() {
        String secondItemId = "item-b";
        String secondProductId = "prod-b";
        when(orderItemMapper.selectList(any())).thenReturn(List.of(
                orderItem(ITEM_ID, PRODUCT_ID, "10"), orderItem(secondItemId, secondProductId, "5")));
        when(productMapper.selectById(secondProductId)).thenReturn(product("套"));
        OrderShipmentItem earlier = OrderShipmentItem.builder()
                .shipmentId("ship-earlier").orderId(ORDER_ID).orderItemId(ITEM_ID)
                .shippedQuantity(new BigDecimal("4")).unit("米").build();
        when(orderShipmentItemMapper.selectByOrderId(ORDER_ID, TENANT)).thenReturn(List.of(earlier));

        service.recordMerchantShipment(ORDER_ID, "SF-MULTI", "顺丰", TENANT);

        ArgumentCaptor<OrderShipmentItem> captor = ArgumentCaptor.forClass(OrderShipmentItem.class);
        verify(orderShipmentItemMapper, times(2)).insert(captor.capture());
        Map<String, OrderShipmentItem> byItem = new LinkedHashMap<>();
        for (OrderShipmentItem line : captor.getAllValues()) {
            byItem.put(line.getOrderItemId(), line);
        }
        assertThat(byItem.keySet())
                .as("逐 order_item 各一行（不是把余量合计成一行）")
                .containsExactlyInAnyOrder(ITEM_ID, secondItemId);
        assertThat(byItem.get(ITEM_ID).getShippedQuantity())
                .as("已部分发过的那行 ⇒ 10 − 4 = 6").isEqualByComparingTo("6");
        assertThat(byItem.get(secondItemId).getShippedQuantity())
                .as("没发过的那行 ⇒ 5（订单量）").isEqualByComparingTo("5");
        assertThat(byItem.get(secondItemId).getUnit())
                .as("单位逐行取该行商品的计价单位（不同行的单位可以不同）").isEqualTo("套");
    }

    // ══════════════════════════════════════════════════════════════════════════
    // 判据 3 / 4：拒绝分支**零写**（字段级快照：insert 一次都不许发生）
    // ══════════════════════════════════════════════════════════════════════════

    @Test
    @DisplayName("判据 3：未发余量为 0 ⇒ 4xx 且零写（不静默建空单）")
    void zeroRemainingIsRejectedWithoutWritingAnything() {
        when(orderItemMapper.selectList(any())).thenReturn(List.of(orderItem(ITEM_ID, "10")));
        OrderShipmentItem earlier = OrderShipmentItem.builder()
                .shipmentId("ship-earlier").orderId(ORDER_ID).orderItemId(ITEM_ID)
                .shippedQuantity(new BigDecimal("10")).unit("米").build();
        when(orderShipmentItemMapper.selectByOrderId(ORDER_ID, TENANT)).thenReturn(List.of(earlier));

        assertThatThrownBy(() -> service.recordMerchantShipment(ORDER_ID, "SF-DUP", "顺丰", TENANT))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("未发余量为 0")
                .extracting(e -> ((BusinessException) e).getHttpStatus()).isEqualTo(422);
        verify(orderShipmentMapper, never()).insert(any(OrderShipment.class));
        verify(orderShipmentItemMapper, never()).insert(any(OrderShipmentItem.class));
    }

    @Test
    @DisplayName("判据 4：订单已 shipped ⇒ 拒绝且零写（重复调用建不出第二张发货单）")
    void alreadyShippedOrderIsRejectedSoSecondCallCannotCreateSecondDocument() {
        when(orderItemMapper.selectList(any())).thenReturn(List.of(orderItem(ITEM_ID, "10")));

        // 第一次：订单处于可发货状态 ⇒ 建一张
        service.recordMerchantShipment(ORDER_ID, "SF-1", "顺丰", TENANT);
        // 第二次：订单已 shipped（本路不再流转）⇒ 不得再建（否则「一张订单两张单」）
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order(TENANT, "shipped"));

        assertThatThrownBy(() -> service.recordMerchantShipment(ORDER_ID, "SF-2", "顺丰", TENANT))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("未新增发货单")
                .extracting(e -> ((BusinessException) e).getHttpStatus()).isEqualTo(422);
        verify(orderShipmentMapper, times(1)).insert(any(OrderShipment.class));
        verify(orderShipmentItemMapper, times(1)).insert(any(OrderShipmentItem.class));
    }

    @Test
    @DisplayName("判据 6：跨租户订单 ⇒ 404 且零写（别的租户的单 = 不存在）")
    void otherTenantOrderIsNotFoundAndNothingIsWritten() {
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order(OTHER_TENANT, "confirmed"));

        assertThatThrownBy(() -> service.recordMerchantShipment(ORDER_ID, "SF-X", "顺丰", TENANT))
                .isInstanceOf(BusinessException.class)
                .extracting(e -> ((BusinessException) e).getHttpStatus()).isEqualTo(404);
        verify(orderShipmentMapper, never()).insert(any(OrderShipment.class));
        verify(orderShipmentItemMapper, never()).insert(any(OrderShipmentItem.class));
    }

    // ══════════════════════════════════════════════════════════════════════════
    // 判据 5：单位来源可核（不是编的）
    // ══════════════════════════════════════════════════════════════════════════

    @Test
    @DisplayName("判据 5a：单位 = 订单行商品的计价单位（products.unit）")
    void unitComesFromProductPricingUnit() {
        when(productMapper.selectById(PRODUCT_ID)).thenReturn(product("套"));
        when(orderItemMapper.selectList(any())).thenReturn(List.of(orderItem(ITEM_ID, "3")));

        service.recordMerchantShipment(ORDER_ID, "SF-UNIT", "顺丰", TENANT);

        ArgumentCaptor<OrderShipmentItem> captor = ArgumentCaptor.forClass(OrderShipmentItem.class);
        verify(orderShipmentItemMapper).insert(captor.capture());
        assertThat(captor.getValue().getUnit()).isEqualTo("套");
    }

    @Test
    @DisplayName("判据 5b：商品查不到 ⇒ 回落到列默认同值「件」（不编第二种口径、也不拒绝发货）")
    void unitFallsBackToColumnDefault() {
        when(productMapper.selectById(PRODUCT_ID)).thenReturn(null);
        when(orderItemMapper.selectList(any())).thenReturn(List.of(orderItem(ITEM_ID, "3")));

        service.recordMerchantShipment(ORDER_ID, "SF-UNIT2", "顺丰", TENANT);

        ArgumentCaptor<OrderShipmentItem> captor = ArgumentCaptor.forClass(OrderShipmentItem.class);
        verify(orderShipmentItemMapper).insert(captor.capture());
        assertThat(captor.getValue().getUnit()).isEqualTo(OrderShipmentService.UNIT_FALLBACK);
    }

    // ══════════════════════════════════════════════════════════════════════════
    // fixtures
    // ══════════════════════════════════════════════════════════════════════════

    private Order order(Long tenantId, String status) {
        Order order = new Order();
        order.setId(ORDER_ID);
        order.setTenantId(tenantId);
        order.setOrderNo(ORDER_NO);
        order.setStatus(status);
        return order;
    }

    private OrderItem orderItem(String id, String quantity) {
        return orderItem(id, PRODUCT_ID, quantity);
    }

    private OrderItem orderItem(String id, String productId, String quantity) {
        OrderItem item = new OrderItem();
        item.setId(id);
        item.setTenantId(TENANT);
        item.setOrderId(ORDER_ID);
        item.setProductId(productId);
        item.setProductName("雪尼尔窗帘布");
        item.setQuantity(new BigDecimal(quantity));
        return item;
    }

    private Product product(String unit) {
        Product product = new Product();
        product.setId(PRODUCT_ID);
        product.setUnit(unit);
        return product;
    }
}
