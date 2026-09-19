package com.migao.admin.service;
// case_ids: OR-016, OR-011

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.OrderDetailResponse;
import com.migao.admin.dto.agent.AgentOrderCreateRequest;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.entity.ProductSku;
import com.migao.admin.entity.StockLedger;
import com.migao.admin.exception.BusinessException;
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
import org.mockito.Spy;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.test.util.ReflectionTestUtils;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.ArgumentMatchers.anyMap;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 规格键族 × 库存路径（issue #4090）。
 *
 * <p>病根：agent 路径的 {@code processing_info} **只能产出字符串族**
 * （{@code skuCode / colorName / sellingMethod / doorWidth} —— {@code product_detail._format_skus}
 * 不返回 {@code color_id}，也不返回 {@code skuId}），而 Java 库存匹配只认
 * <b>ID 族</b>（{@code skuId}，或 {@code colorId + sellingMethod + doorWidth}）⇒
 * 键族不相交 ⇒ {@code matchSkuId} 返回 null ⇒ <b>库存校验 / 扣减 / 销量三处全部静默跳过</b>
 * （订单照样成交、SKU 库存不动、SKU 销量不涨、无任何失败）。</p>
 *
 * <p>本类钉住修后的口径：</p>
 * <ol>
 *   <li><b>能定位的（字符串族）必须命中</b> —— 进入库存路径的订单必须产生「扣减 + 销量」的效果层证据；</li>
 *   <li><b>声明了规格却定位不到 ⇒ 显式失败</b>（fail-closed + 可行动 suggestion），不许静默放行；</li>
 *   <li><b>负例</b>：不带 SKU 身份键（只有加工信息 / 售卖方式 / 门幅）的合法订单不得被拒 ——
 *       它没有「选了哪个 SKU」的语义，本就不该有 SKU 级库存调整（商品级销量照记）。</li>
 * </ol>
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("agent 规格键族 → 库存校验/扣减/销量的单一判据（issue #4090）")
class OrderStockSkuKeyFamilyTest {

    private static final String PRODUCT_ID = "prod-001";
    private static final String PRODUCT_NAME = "蜂巢帘";
    private static final Long SKU_ID = 5001L;
    private static final String ORDER_ID = "order-agent-4090";

    /** 线上形态的 payload 序列化器（测试侧独立于注入 OrderService 的 ObjectMapper） */
    private static final ObjectMapper WIRE_JSON = new ObjectMapper();

    @InjectMocks
    private OrderService orderService;
    /** 加工费组合价目表（issue #4406 的取价依赖；本类不涉及加工费口径 ⇒ 空表 ⇒ 未定价 0） */
    @Mock(lenient = true)
    private com.migao.admin.mapper.ProcessingFeeCombinationMapper processingFeeCombinationMapper;

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

    @Spy
    private ObjectMapper objectMapper = new ObjectMapper();

    @Mock
    private NotificationService notificationService;

    @Mock
    private ProcessingOrderMapper processingOrderMapper;

    /** 台账（issue #4137）：订单腿也落台账行 —— 效果层证据的第三个维度 */
    @Mock
    private StockLedgerService stockLedgerService;

    @BeforeEach
    void setUp() {
        // issue #4406：取价点用**真实**对象（只桩价目表 Mapper）—— 金额算法仍走生产代码。
        // 为什么不用 @Mock：@InjectMocks 的构造注入发生在本方法之前 ⇒ 直接塞 mock 会把
        // 「谁发射加工费」这条接线本身也 mock 掉（接线判据就失去意义）。
        ReflectionTestUtils.setField(orderService, "processingFeeCalculator",
                new ProcessingFeeCalculator(processingFeeCombinationMapper));
        TenantContext.setTenantId(1L);
        // LambdaQueryWrapper<ProductSku> 需要 lambda 缓存才能解析列名
        MybatisConfiguration conf = new MybatisConfiguration();
        MapperBuilderAssistant assistant = new MapperBuilderAssistant(conf, "");
        TableInfoHelper.initTableInfo(assistant, Order.class);
        TableInfoHelper.initTableInfo(assistant, OrderItem.class);
        TableInfoHelper.initTableInfo(assistant, ProductSku.class);
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    // ======================== 形态构造（唯一生产者 = ai-agent order_create） ========================

    /**
     * agent 路径的**真实** processing_info 形态：只有字符串族。
     *
     * <p>{@code product_detail._format_skus} 输出 {@code sku_code / color_name / selling_method /
     * door_width}（**没有** {@code color_id}），{@code order_create} 的 parameters 也不声明
     * {@code skuId} —— 模型既拿不到也没被教 ID 族，落库的就是这一形态。</p>
     */
    private static Map<String, Object> agentSpecInfo() {
        Map<String, Object> info = new LinkedHashMap<>();
        info.put("skuCode", "SKU-MB-28");
        info.put("colorName", "米白");
        info.put("sellingMethod", "bulk_cut");
        info.put("doorWidth", "2.8米");
        return info;
    }

    /**
     * 负例形态：只带加工信息（{@code processingFee + processingItems}）与规格**属性**
     * （售卖方式 / 门幅），**没有任何 SKU 身份键**（skuId/skuCode/colorId/colorName）。
     * 这是本仓既有的合法订单形态（见 {@code OrderQuantityDecimalTest} 的 fixture）。
     */
    private static Map<String, Object> processingOnlyInfo() {
        Map<String, Object> item = new LinkedHashMap<>();
        item.put("name", "打孔");
        item.put("unitPrice", new BigDecimal("8.00"));
        item.put("quantity", new BigDecimal("2"));
        item.put("pricingMethod", "per_meter");
        item.put("subtotal", new BigDecimal("16.00"));
        Map<String, Object> info = new LinkedHashMap<>();
        info.put("processingItems", new ArrayList<>(List.of(item)));
        info.put("processingFee", new BigDecimal("16.00"));
        info.put("sellingMethod", "bulk_cut");
        info.put("doorWidth", "2.8米");
        return info;
    }

    /** 库内 SKU 行（与 product_detail 同源：color_name / selling_method / door_width 原值） */
    private static ProductSku storedSku() {
        return ProductSku.builder()
                .id(SKU_ID).tenantId(1L).productId(PRODUCT_ID)
                .colorId(11L).colorName("米白")
                .sellingMethod("bulk_cut").doorWidth("2.8")
                .skuCode("SKU-MB-28")
                .price(new BigDecimal("168.00")).stock(10).salesCount(5)
                .build();
    }

    private static AgentOrderCreateRequest agentRequest(Object processingInfo, int quantity) {
        // 用**线上真实形态**（ai-agent 发来的 JSON）构造请求，而不是 new 嵌套 Item 类型：
        // ① 更贴近缺陷来源（payload 由 order_create 序列化发出）；
        // ② 与 #4089 的 DTO 收敛（items 元素类型由 AgentOrderCreateRequest.AgentOrderItem
        //    改为共享的 OrderCreateRequest.OrderItemRequest）**前向兼容** —— 同一个 JSON 形态两边都成立。
        Map<String, Object> item = new LinkedHashMap<>();
        item.put("productName", PRODUCT_NAME);
        item.put("productId", PRODUCT_ID);
        item.put("quantity", BigDecimal.valueOf(quantity));
        item.put("unitPrice", new BigDecimal("168.00"));
        item.put("subtotal", new BigDecimal("168.00").multiply(BigDecimal.valueOf(quantity)));
        item.put("processingInfo", processingInfo);
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("customerName", "张三");
        body.put("customerPhone", "13800138000");
        body.put("items", List.of(item));
        try {
            return WIRE_JSON.readValue(WIRE_JSON.writeValueAsString(body), AgentOrderCreateRequest.class);
        } catch (JsonProcessingException e) {
            throw new IllegalStateException("测试 payload 序列化失败", e);
        }
    }

    /** 下单落库后的回读（订单 + 明细），confirmPayment/cancelOrder 都用同一份明细。 */
    private OrderItem[] mockCreatedOrder(String status) {
        OrderItem[] captured = new OrderItem[1];
        when(orderMapper.insert(any(Order.class))).thenAnswer(invocation -> {
            Order o = invocation.getArgument(0);
            o.setId(ORDER_ID);
            return 1;
        });
        when(orderItemMapper.insert(any(OrderItem.class))).thenAnswer(invocation -> {
            OrderItem item = invocation.getArgument(0);
            item.setId("item-4090");
            captured[0] = item;
            return 1;
        });
        when(orderMapper.selectById(ORDER_ID)).thenAnswer(invocation -> Order.builder()
                .id(ORDER_ID).tenantId(1L).orderNo("ORD-20260918-4090")
                .customerName("张三").customerPhone("13800138000")
                .status(status).totalAmount(new BigDecimal("336.00")).build());
        when(orderItemMapper.selectList(any(LambdaQueryWrapper.class)))
                .thenAnswer(invocation -> List.of(captured[0]));
        lenient().when(orderLogisticsMapper.selectByOrderId(anyString(), anyLong())).thenReturn(List.of());
        // 台账（issue #4137）：订单腿扣减/回补前会取「变更前快照」；与真实语义一致地返回该商品 SKU 行
        lenient().when(stockLedgerService.snapshotSkus(anyList())).thenReturn(Map.of(SKU_ID, storedSku()));
        return captured;
    }

    // ======================== 1. 能够定位 ⇒ 必须命中（效果层证据） ========================

    @Test
    @DisplayName("agent 字符串键族（skuCode+colorName+售卖方式+门幅）下单 → 确认支付必须扣减库存 + 涨销量 + 落台账行")
    void agentStringSpecKeyFamily_deductsStockAndSales() {
        // given: 明细是 agent 唯一能产出的字符串族；库内 SKU 行有对应的 sku_code/color_name/门幅
        when(productSkuMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of(storedSku()));
        when(productSkuMapper.selectById(SKU_ID)).thenReturn(storedSku());
        when(orderMapper.update(any(), any())).thenReturn(1);
        mockCreatedOrder("confirmed");

        // when: 下单成功 → 确认支付
        OrderDetailResponse created = orderService.createOrderForAgent(agentRequest(agentSpecInfo(), 2), 1L);
        assertThat(created).isNotNull();
        orderService.confirmPayment(ORDER_ID);

        // then: 效果层证据三件套 —— 库存真的减了、销量真的涨了、台账真的落了行
        // （修前这三处一起静默跳过：订单成交但库存不动/销量不涨/台账无行 ⇒ 红）
        verify(productSkuMapper).deductStock(SKU_ID, 2);
        verify(productSkuMapper).increaseSalesCount(SKU_ID, 2);
        verify(stockLedgerService).recordChangesAgainstSnapshot(
                eq(1L), anyMap(), eq(StockLedger.REASON_ORDER), eq("ORD-20260918-4090"), anyString());
        verify(productMapper).increaseSales(eq(PRODUCT_ID), eq(2), any(BigDecimal.class));
    }

    @Test
    @DisplayName("取消订单回补：同一字符串键族必须回补 SKU 库存 + 减记销量 + 落台账行（与扣减侧同一判据）")
    void cancelOrder_stringSpecKeyFamily_restoresStockAndSales() {
        OrderItem[] captured = mockCreatedOrder("confirmed");
        when(productSkuMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of(storedSku()));
        when(productSkuMapper.selectById(SKU_ID)).thenReturn(storedSku());
        when(orderMapper.update(any(), any())).thenReturn(1);

        orderService.createOrderForAgent(agentRequest(agentSpecInfo(), 2), 1L);
        assertThat(captured[0]).isNotNull();
        orderService.cancelOrder(ORDER_ID, "客户不要了");

        verify(productSkuMapper).restoreStock(SKU_ID, 2);
        verify(productSkuMapper).decreaseSalesCount(SKU_ID, 2);
        verify(stockLedgerService).recordChangesAgainstSnapshot(
                eq(1L), anyMap(), eq(StockLedger.REASON_ORDER), eq("ORD-20260918-4090"), anyString());
    }

    // ======================== 2. 声明了规格却定位不到 ⇒ 显式失败（fail-closed） ========================

    @Test
    @DisplayName("声明了 SKU 规格但库内定位不到 ⇒ 显式拒绝（可行动 suggestion），不得静默放行")
    void specDeclaredButUnresolvable_failsClosed() {
        // given: 明细声明了规格（skuCode/colorName/门幅），但该商品下没有任何匹配的 SKU 行
        when(productSkuMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of());

        assertThatThrownBy(() -> orderService.createOrderForAgent(agentRequest(agentSpecInfo(), 2), 1L))
                .isInstanceOf(BusinessException.class)
                // 可行动：说清声明了哪些键、该补什么
                .hasMessageContaining("SKU")
                .hasMessageContaining("skuCode=SKU-MB-28")
                .hasMessageContaining("colorName=米白");
        verify(orderMapper, never()).insert(any(Order.class));
    }

    @Test
    @DisplayName("确认支付侧同一判据：规格定位不到时拒绝确认，不得「订单成交但库存不动」")
    void confirmPayment_specUnresolvable_failsClosed() {
        OrderItem[] captured = mockCreatedOrder("pending");
        when(productSkuMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of(storedSku()));
        when(productSkuMapper.selectById(SKU_ID)).thenReturn(storedSku());
        orderService.createOrderForAgent(agentRequest(agentSpecInfo(), 2), 1L);

        // 下单后该规格的 SKU 行被删/改名（规格漂移）⇒ 确认支付必须显式失败
        when(productSkuMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of());

        assertThat(captured[0]).isNotNull();
        assertThatThrownBy(() -> orderService.confirmPayment(ORDER_ID))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("SKU");
        verify(productSkuMapper, never()).deductStock(anyLong(), anyInt());
    }

    // ======================== 3. 负例（R2）：无 SKU 身份的合法订单不得被拒 ========================

    @Test
    @DisplayName("负例：只带加工信息/规格属性（无 SKU 身份键）的合法订单不得被拒 —— 合法跳过 SKU 级库存")
    void noSkuIdentity_isLegalSkip_notRejected() {
        // 该商品**确有** SKU 行（stub 成匹配行）—— 证明跳过不是「没查到」，而是「本就没有 SKU 身份语义」
        lenient().when(productSkuMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of(storedSku()));
        when(orderMapper.update(any(), any())).thenReturn(1);
        mockCreatedOrder("confirmed");

        OrderDetailResponse created = orderService.createOrderForAgent(agentRequest(processingOnlyInfo(), 2), 1L);
        assertThat(created).as("无 SKU 身份的合法订单不得被拒").isNotNull();
        orderService.confirmPayment(ORDER_ID);

        // 合法跳过：不猜 SKU（不扣减、不记 SKU 销量、不落台账行）——这是设计，不是缺陷
        verify(productSkuMapper, never()).deductStock(anyLong(), anyInt());
        verify(productSkuMapper, never()).increaseSalesCount(anyLong(), anyInt());
        verify(stockLedgerService, never()).recordChangesAgainstSnapshot(
                anyLong(), anyMap(), anyString(), anyString(), anyString());
        // 但商品级销量照记（订单本身是有效的）
        verify(productMapper).increaseSales(eq(PRODUCT_ID), eq(2), any(BigDecimal.class));
    }
}