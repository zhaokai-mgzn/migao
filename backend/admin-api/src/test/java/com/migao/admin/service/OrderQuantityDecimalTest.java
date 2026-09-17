// case_ids: OR-028
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.OrderCreateRequest;
import com.migao.admin.dto.OrderDetailResponse;
import com.migao.admin.dto.agent.AgentOrderCreateRequest;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.mapper.FinanceTransactionMapper;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderLogisticsMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import com.migao.admin.mapper.ProductMapper;
import com.migao.admin.mapper.ProductSkuMapper;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.test.util.ReflectionTestUtils;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 订单数量语义放宽为 DECIMAL(10,2) / BigDecimal（issue #3666，用例 OR-028）。
 *
 * <p>为什么需要本测试：各计价方式的数量口径**不都是整数**
 * （docs/testing/acceptance-protocol.md:225 `quantity 按计价方式（per_meter=米数 /
 * per_set=1 / per_area=宽×高）`）。per_area 的合法面积可以是小数：门幅 2.8m × 3m =
 * 8.4 ㎡，刺绣工艺 30 元/㎡ → 正确 252.00 元；整数列只能表示 8 → 240.00 元 = **少收 12.00 元**。
 *
 * <p>本测试锁四条（三条判据 + 一条反向兼容）：
 * <ol>
 *   <li>per_area：请求数量 8.4 → <b>落库的 OrderItem.quantity 是 8.4</b>（不是 8），
 *       订单总额 = 30 × 8.4 + 面料 = <b>252.00</b>（不是 240.00）；</li>
 *   <li>加工项数量（processingInfo.processingItems[].quantity）透传解析<b>不做整数截断</b>
 *       —— 旧实现走 {@code toInteger()}（8.4 → 8）导致详情/列表加工费与落库金额不一致；</li>
 *   <li>整数数量 3 与 JSON 整数入参仍正常（向后兼容，不报 400、不丢精度）；</li>
 *   <li>per_meter 小数米数保真（2.5 米 → 打孔 8.00/m × 2.5 = 20.00）。</li>
 * </ol>
 */
@ExtendWith(MockitoExtension.class)
class OrderQuantityDecimalTest {

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
    private NotificationService notificationService;

    @Mock
    private ProcessingOrderMapper processingOrderMapper;

    /** spy：@InjectMocks 注入时 ObjectMapper 为空会 NPE（processingInfo 解析路径要用） */
    private final ObjectMapper objectMapper = new ObjectMapper();

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(1L);
        ReflectionTestUtils.setField(orderService, "objectMapper", objectMapper);

        MybatisConfiguration conf = new MybatisConfiguration();
        MapperBuilderAssistant assistant = new MapperBuilderAssistant(conf, "");
        TableInfoHelper.initTableInfo(assistant, Order.class);
        TableInfoHelper.initTableInfo(assistant, OrderItem.class);
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    // ======================== 1. per_area 小数面积端到端保真 ========================

    @Test
    @DisplayName("per_area 小数面积：数量 8.4 保真落库，加工费 30×8.4=252.00（不是 240.00）")
    void perAreaDecimalQuantity_isPersistedAndPricedWithoutTruncation() {
        // given：门幅 2.8m × 3m = 8.4 ㎡，刺绣工艺 30 元/㎡
        OrderCreateRequest.OrderItemRequest itemReq = new OrderCreateRequest.OrderItemRequest();
        itemReq.setProductId("prod-001");
        itemReq.setProductName("刺绣窗帘");
        itemReq.setQuantity(new BigDecimal("8.4"));
        itemReq.setUnitPrice(new BigDecimal("100.00"));
        itemReq.setWidth(new BigDecimal("2.8"));
        itemReq.setHeight(new BigDecimal("3.0"));
        itemReq.setProcessingInfo(processingInfo(processingItem("刺绣工艺", "30.00", "8.4", "per_area", "252.00")));
        itemReq.setSubtotal(new BigDecimal("1092.00"));

        OrderCreateRequest request = formRequest(itemReq);

        // when
        CapturedOrder captured = createAndCapture(request);

        // then ①：落库数量是 8.4，不是 8（容量缺陷的直接判据）
        assertThat(captured.item.getQuantity())
                .as("落库的订单明细数量必须是 8.4 原始值（Integer 列会截断成 8）")
                .isEqualByComparingTo(new BigDecimal("8.4"));

        // then ②：总额 = 面料 100×8.4 + 加工费 30×8.4 = 840.00 + 252.00 = 1092.00
        assertThat(captured.totalAmount)
                .as("订单总额必须按未截断的 8.4 计算（截断成 8 会得到 1040.00 = 少收 52.00）")
                .isEqualByComparingTo(new BigDecimal("1092.00"));
    }

    @Test
    @DisplayName("加工项数量透传解析不截断：processingItems[].quantity=8.4 → 金额 252.00（旧 toInteger 截断成 8 → 240.00）")
    void processingItemQuantityParsedWithoutIntegerTruncation() {
        // given：已落库明细（模拟从 order_items 读回），processingInfo 含 per_area 加工项 8.4 ㎡
        OrderItem stored = OrderItem.builder()
                .id("item-001")
                .tenantId(1L)
                .orderId("order-001")
                .productId("prod-001")
                .productName("刺绣窗帘")
                .quantity(new BigDecimal("8.4"))
                .unitPrice(new BigDecimal("100.00"))
                .subtotal(new BigDecimal("1092.00"))
                .processingInfo(processingInfo(processingItem("刺绣工艺", "30.00", "8.4", "per_area", "252.00")))
                .build();

        Order order = Order.builder()
                .id("order-001")
                .tenantId(1L)
                .orderNo("ORD-20260425-0002")
                .customerName("张三")
                .customerPhone("13800138000")
                .totalAmount(new BigDecimal("1092.00"))
                .status("pending")
                .build();
        lenient().when(orderMapper.selectById("order-001")).thenReturn(order);
        lenient().when(orderItemMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of(stored));
        lenient().when(orderLogisticsMapper.selectByOrderId(anyString(), anyLong())).thenReturn(List.of());

        // when
        OrderDetailResponse detail = orderService.getOrderById("order-001");

        // then：详情里的加工项数量与金额都按 8.4 计（旧实现 Integer quantity=8 → amount=240.00）
        assertThat(detail.getItems()).hasSize(1);
        OrderDetailResponse.OrderItemResponse itemResponse = detail.getItems().get(0);
        assertThat(itemResponse.getQuantity())
                .as("明细数量必须是 8.4")
                .isEqualByComparingTo(new BigDecimal("8.4"));
        assertThat(itemResponse.getAmount())
                .as("明细金额 = 100 × 8.4 = 840.00")
                .isEqualByComparingTo(new BigDecimal("840.00"));

        assertThat(itemResponse.getProcessingInfo()).isInstanceOf(Map.class);
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> procItems =
                (List<Map<String, Object>>) ((Map<String, Object>) itemResponse.getProcessingInfo()).get("processingItems");
        assertThat(procItems).hasSize(1);
        assertThat(new BigDecimal(String.valueOf(procItems.get(0).get("quantity"))))
                .as("加工项数量必须是 8.4（旧 toInteger 会截断成 8）")
                .isEqualByComparingTo(new BigDecimal("8.4"));
    }

    // ======================== 2. 向后兼容：整数数量 ========================

    @Test
    @DisplayName("向后兼容：整数数量 3 仍正常落库并正确计价")
    void integerQuantityStillWorks() {
        OrderCreateRequest.OrderItemRequest itemReq = new OrderCreateRequest.OrderItemRequest();
        itemReq.setProductId("prod-001");
        itemReq.setProductName("蜂巢帘");
        itemReq.setQuantity(new BigDecimal("3"));
        itemReq.setUnitPrice(new BigDecimal("299.50"));
        itemReq.setProcessingInfo(processingInfo(processingItem("打孔", "8.00", "3", "per_meter", "24.00")));
        itemReq.setSubtotal(new BigDecimal("922.50"));

        CapturedOrder captured = createAndCapture(formRequest(itemReq));

        assertThat(captured.item.getQuantity())
                .as("整数数量 3 仍能落库")
                .isEqualByComparingTo(new BigDecimal("3"));
        assertThat(captured.totalAmount)
                .as("总额 = 299.50×3 + 8×3 = 898.50 + 24.00 = 922.50")
                .isEqualByComparingTo(new BigDecimal("922.50"));
    }

    @Test
    @DisplayName("向后兼容：JSON 里的整数数量 3 反序列化为 BigDecimal(\"3\")，不报 400、不丢精度")
    void integerJsonDeserializesToBigDecimal() throws Exception {
        // 表单路径 DTO
        OrderCreateRequest form = objectMapper.readValue("""
                {"customerName":"张三","customerPhone":"13800138000",
                 "items":[{"productName":"蜂巢帘","quantity":3,"unitPrice":299.50,"subtotal":898.50}]}
                """, OrderCreateRequest.class);
        assertThat(form.getItems().get(0).getQuantity())
                .as("JSON 整数 3 必须反序列化为 BigDecimal 3（不得 400 / 不得精度异常）")
                .isEqualByComparingTo(new BigDecimal("3"));

        // Agent 路径 DTO（ai-agent 唯一实走入口：quantity 由 LLM 给出，可能是 3 也可能是 8.4）
        AgentOrderCreateRequest agent = objectMapper.readValue("""
                {"customerName":"张三","customerPhone":"13800138000",
                 "items":[{"productName":"蜂巢帘","quantity":3,"unitPrice":299.50,"subtotal":898.50},
                          {"productName":"刺绣窗帘","quantity":8.4,"unitPrice":100.00,"subtotal":1092.00}]}
                """, AgentOrderCreateRequest.class);
        assertThat(agent.getItems().get(0).getQuantity())
                .as("Agent JSON 整数 3 必须反序列化为 BigDecimal 3")
                .isEqualByComparingTo(new BigDecimal("3"));
        assertThat(agent.getItems().get(1).getQuantity())
                .as("Agent JSON 小数 8.4 必须反序列化为 BigDecimal 8.4")
                .isEqualByComparingTo(new BigDecimal("8.4"));
    }

    @Test
    @DisplayName("Agent 路径端到端：小数数量 8.4 经 createOrderForAgent 透传落库且小计按原值重算")
    void agentPathKeepsDecimalQuantity() {
        OrderCreateRequest.OrderItemRequest agentItem = new OrderCreateRequest.OrderItemRequest();
        agentItem.setProductName("刺绣窗帘");
        agentItem.setQuantity(new BigDecimal("8.4"));
        agentItem.setUnitPrice(new BigDecimal("100.00"));
        // subtotal 必填（issue #4089 收敛）；server 侧仍按 quantity × unitPrice 重算（见用例断言）
        agentItem.setSubtotal(new BigDecimal("840.00"));
        agentItem.setWidth(new BigDecimal("2.8"));
        agentItem.setHeight(new BigDecimal("3.0"));
        agentItem.setProcessingInfo(processingInfo(processingItem("刺绣工艺", "30.00", "8.4", "per_area", "252.00")));

        AgentOrderCreateRequest agentRequest = new AgentOrderCreateRequest();
        agentRequest.setCustomerName("张三");
        agentRequest.setCustomerPhone("13800138000");
        agentRequest.setItems(List.of(agentItem));

        CapturedOrder captured = new CapturedOrder();
        when(orderMapper.insert(any(Order.class))).thenAnswer(invocation -> {
            Order o = invocation.getArgument(0);
            o.setId("order-agent");
            captured.totalAmount = o.getTotalAmount();
            return 1;
        });
        doCaptureOrderItem(captured);
        when(orderMapper.selectById("order-agent")).thenAnswer(invocation -> Order.builder()
                .id("order-agent").tenantId(1L).orderNo("ORD-20260425-0003")
                .customerName("张三").customerPhone("13800138000").status("pending")
                .totalAmount(captured.totalAmount).build());
        when(orderItemMapper.selectList(any(LambdaQueryWrapper.class)))
                .thenAnswer(invocation -> List.of(captured.item));
        lenient().when(orderLogisticsMapper.selectByOrderId(anyString(), anyLong())).thenReturn(List.of());

        OrderDetailResponse result = orderService.createOrderForAgent(agentRequest, 1L);

        assertThat(result).isNotNull();
        assertThat(captured.item.getQuantity())
                .as("Agent 路径也必须保真落库 8.4")
                .isEqualByComparingTo(new BigDecimal("8.4"));
        assertThat(captured.item.getSubtotal())
                .as("Agent 路径小计由服务端按 quantity × unitPrice 重算 = 840.00")
                .isEqualByComparingTo(new BigDecimal("840.00"));
        assertThat(captured.totalAmount)
                .as("Agent 路径总额 = 840.00 + 252.00 = 1092.00")
                .isEqualByComparingTo(new BigDecimal("1092.00"));
    }

    // ======================== 3. per_meter 小数米数保真 ========================

    @Test
    @DisplayName("per_meter 小数米数：数量 2.5 米 → 打孔 8.00/m × 2.5 = 20.00")
    void perMeterDecimalQuantityKeepsPrecision() {
        OrderCreateRequest.OrderItemRequest itemReq = new OrderCreateRequest.OrderItemRequest();
        itemReq.setProductId("prod-001");
        itemReq.setProductName("遮光窗帘");
        itemReq.setQuantity(new BigDecimal("2.5"));
        itemReq.setUnitPrice(new BigDecimal("168.00"));
        itemReq.setProcessingInfo(processingInfo(processingItem("打孔", "8.00", "2.5", "per_meter", "20.00")));
        itemReq.setSubtotal(new BigDecimal("440.00"));

        CapturedOrder captured = createAndCapture(formRequest(itemReq));

        assertThat(captured.item.getQuantity())
                .as("per_meter 的 2.5 米必须保真（旧 Integer 列会失败/截断）")
                .isEqualByComparingTo(new BigDecimal("2.5"));
        assertThat(captured.totalAmount)
                .as("总额 = 168×2.5 + 8×2.5 = 420.00 + 20.00 = 440.00")
                .isEqualByComparingTo(new BigDecimal("440.00"));
    }

    // ======================== helpers ========================

    private static final class CapturedOrder {
        OrderItem item;
        BigDecimal totalAmount;
    }

    private CapturedOrder createAndCapture(OrderCreateRequest request) {
        CapturedOrder captured = new CapturedOrder();
        when(orderMapper.insert(any(Order.class))).thenAnswer(invocation -> {
            Order o = invocation.getArgument(0);
            o.setId("order-new");
            captured.totalAmount = o.getTotalAmount();
            return 1;
        });
        doCaptureOrderItem(captured);
        when(orderMapper.selectById("order-new")).thenAnswer(invocation -> Order.builder()
                .id("order-new").tenantId(1L).orderNo("ORD-20260425-0004")
                .customerName(request.getCustomerName()).customerPhone(request.getCustomerPhone())
                .status("pending").totalAmount(captured.totalAmount).build());
        when(orderItemMapper.selectList(any(LambdaQueryWrapper.class)))
                .thenAnswer(invocation -> List.of(captured.item));
        lenient().when(orderLogisticsMapper.selectByOrderId(anyString(), anyLong())).thenReturn(List.of());

        orderService.createOrder(request, 1L);
        verify(orderItemMapper).insert(any(OrderItem.class));
        return captured;
    }

    private void doCaptureOrderItem(CapturedOrder captured) {
        when(orderItemMapper.insert(any(OrderItem.class))).thenAnswer(invocation -> {
            captured.item = invocation.getArgument(0);
            if (captured.item.getId() == null) {
                captured.item.setId("item-new");
            }
            return 1;
        });
    }

    private static OrderCreateRequest formRequest(OrderCreateRequest.OrderItemRequest itemReq) {
        OrderCreateRequest request = new OrderCreateRequest();
        request.setCustomerName("张三");
        request.setCustomerPhone("13800138000");
        request.setCustomerAddress("北京市朝阳区");
        request.setItems(List.of(itemReq));
        return request;
    }

    /** processingInfo 真实形态：{ processingFee, processingItems:[{id,name,unitPrice,quantity,unit,pricingMethod,subtotal}] } */
    private static Map<String, Object> processingInfo(Map<String, Object> processingItem) {
        Map<String, Object> info = new LinkedHashMap<>();
        info.put("processingItems", new ArrayList<>(List.of(processingItem)));
        info.put("processingFee", processingItem.get("subtotal"));
        info.put("sellingMethod", "bulk_cut");
        info.put("doorWidth", "2.8米");
        return info;
    }

    private static Map<String, Object> processingItem(String name, String unitPrice, String quantity,
                                                      String pricingMethod, String subtotal) {
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("id", "pi-" + name);
        entry.put("name", name);
        entry.put("unitPrice", new BigDecimal(unitPrice));
        entry.put("quantity", new BigDecimal(quantity));
        entry.put("unit", "per_area".equals(pricingMethod) ? "㎡" : "米");
        entry.put("pricingMethod", pricingMethod);
        entry.put("subtotal", new BigDecimal(subtotal));
        return entry;
    }
}
