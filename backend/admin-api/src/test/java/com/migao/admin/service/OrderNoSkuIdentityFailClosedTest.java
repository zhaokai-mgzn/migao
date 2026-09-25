// case_ids: OR-011, OR-014, OR-017
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.migao.admin.dto.OrderCreateRequest;
import com.migao.admin.dto.OrderDetailResponse;
import com.migao.admin.dto.agent.AgentOrderCreateRequest;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.entity.Product;
import com.migao.admin.entity.ProductSku;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderLogisticsMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProductMapper;
import com.migao.admin.mapper.ProductSkuMapper;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.test.util.ReflectionTestUtils;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.Mockito.atLeastOnce;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 🔴 <b>「订单行没有 SKU 标识」⇒ 422 fail-closed（issue #3881 缺陷二 / #4025 F11，用户裁定 A①）</b>。
 *
 * <h2>改前形态（本类判据要钉的那一行）</h2>
 * {@code OrderService.validateAgentItemUnitPrice} 改前是：
 * <pre>boolean hasSkuKey = hasText(skuCode) || hasText(colorName);
 * if (!hasText(item.getProductId()) || !hasSkuKey) {
 *     return; // 无 SKU 标识，无法解析权威价 → 不拦截
 * }</pre>
 * ⇒ 明细**只有 product_name**（或只有 {@code processingInfo.skuId} —— 工具层声明的「首选键」，
 * 而守卫此前只认 skuCode/colorName）时，单价**一次都没被核对**就落库；
 * {@code order_items.product_id} 落 NULL、编造价照进总额（#3881 缺陷二原文）。
 *
 * <h2>改后判据（**只拦真正无从核价的那种**，合法形态不受影响）</h2>
 * <ol>
 *   <li><b>权威价唯一可得 ⇒ 必须一致</b>：商品可解析（{@code product_id}，或商品名**唯一**匹配 ——
 *       ai-agent 工具层接地解析本来就是这套口径）且其 SKU 价集合唯一（或无 SKU 记录但有商品级价
 *       的简单商品 = 卖布行形态）⇒ 该价即权威价，与「声明了键族」的行**同一口径**严格核对；</li>
 *   <li><b>无从确定 ⇒ 422</b>（{@code VALIDATION_ERROR} + 可行动 suggestion）：多个不同规格价而
 *       未声明规格 / 商品解析不到 / 完全无价。绝不再静默放过 —— 这是本单要关掉的口子。</li>
 * </ol>
 *
 * <h2>红证（改前必红，逐条见各 {@code @DisplayName}）</h2>
 * 判据 1/2/3/4/6 在改前**全部不抛异常**（静默放过 = 订单照建），即「改前红」；
 * 判据 5/7/8/9 是**合法形态不得被拦**的反向钉（改前改后都必须绿）—— 防把口子堵成误杀。
 *
 * <p>表单路径（{@code POST /api/admin/orders} → {@link OrderService#createOrder}）**不经**本守卫
 * ⇒ 同一份「无 SKU 标识」请求在表单路径上行为逐字不变（判据 9）——这是本单的调用方影响边界。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("无 SKU 标识订单行的服务端取价校验：fail-open → 422 fail-closed（issue #3881 / F11）")
class OrderNoSkuIdentityFailClosedTest {

    private static final Long TENANT_ID = 1L;
    private static final String PRODUCT_ID = "p-nosku-3881";

    @InjectMocks
    private OrderService orderService;

    /** 加工费取价依赖（本类不涉及加工费口径 ⇒ 空价目表 ⇒ 未定价 0） */
    @Mock(lenient = true)
    private com.migao.admin.mapper.ProcessingFeeCombinationMapper processingFeeCombinationMapper;
    @Mock(lenient = true)
    private com.migao.admin.mapper.ProductionRouteRuleMapper routeRuleMapper;

    @Mock
    private OrderMapper orderMapper;
    @Mock
    private OrderItemMapper orderItemMapper;
    @Mock
    private OrderLogisticsMapper orderLogisticsMapper;
    @Mock(lenient = true)
    private ProductMapper productMapper;
    @Mock(lenient = true)
    private ProductSkuMapper productSkuMapper;

    /** 刚插入的那份订单（回读用）—— 让金额断言断言**落库口径**而不是另造的桩。 */
    private final Order[] saved = new Order[1];

    @BeforeEach
    void setUp() {
        // issue #4406：取价点用**真实**对象（只桩价目表 Mapper）—— 金额算法仍走生产代码
        ReflectionTestUtils.setField(orderService, "processingFeeCalculator",
                new ProcessingFeeCalculator(processingFeeCombinationMapper, routeRuleMapper));
        MybatisConfiguration conf = new MybatisConfiguration();
        MapperBuilderAssistant assistant = new MapperBuilderAssistant(conf, "");
        TableInfoHelper.initTableInfo(assistant, Order.class);
        TableInfoHelper.initTableInfo(assistant, OrderItem.class);

        when(orderMapper.insert(any(Order.class))).thenAnswer(inv -> {
            Order o = inv.getArgument(0);
            o.setId("order-3881");
            saved[0] = o;
            return 1;
        });
        // 回读**刚插入的那一份**（而不是另造一份固定额），否则金额断言断言的是桩、不是落库口径
        when(orderMapper.selectById("order-3881")).thenAnswer(inv -> saved[0]);
        when(orderMapper.selectById(any())).thenAnswer(inv -> saved[0]);
        when(orderItemMapper.insert(any(OrderItem.class))).thenReturn(1);
        when(orderItemMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of());
        when(orderLogisticsMapper.selectByOrderId(any(), anyLong())).thenReturn(List.of());
    }

    // ──────────────────────────── 请求构造（明细的 SKU 标识形态是各判据的唯一变量）

    /** Agent 路径请求：明细只有 productId/商品名 + 单价；{@code processingInfo} 由各判据给定。 */
    private AgentOrderCreateRequest agentRequest(String productId, String productName,
                                                 BigDecimal unitPrice, Object processingInfo) {
        AgentOrderCreateRequest req = new AgentOrderCreateRequest();
        req.setCustomerName("张三");
        req.setCustomerPhone("13800138000");
        OrderCreateRequest.OrderItemRequest item = new OrderCreateRequest.OrderItemRequest();
        item.setProductId(productId);
        item.setProductName(productName);
        item.setQuantity(BigDecimal.valueOf(2));
        item.setUnitPrice(unitPrice);
        item.setSubtotal(unitPrice.multiply(BigDecimal.valueOf(2)));
        item.setProcessingInfo(processingInfo);
        req.setItems(List.of(item));
        return req;
    }

    /** 表单路径请求（{@code POST /api/admin/orders}）—— 同一份「无 SKU 标识」明细形态。 */
    private OrderCreateRequest formRequest(String productId, String productName, BigDecimal unitPrice) {
        OrderCreateRequest req = new OrderCreateRequest();
        req.setCustomerName("张三");
        req.setCustomerPhone("13800138000");
        OrderCreateRequest.OrderItemRequest item = new OrderCreateRequest.OrderItemRequest();
        item.setProductId(productId);
        item.setProductName(productName);
        item.setQuantity(BigDecimal.valueOf(2));
        item.setUnitPrice(unitPrice);
        item.setSubtotal(unitPrice.multiply(BigDecimal.valueOf(2)));
        req.setItems(List.of(item));
        return req;
    }

    private Product product(String id, String name, String basePrice) {
        return Product.builder().id(id).tenantId(TENANT_ID).name(name)
                .basePrice(basePrice == null ? null : new BigDecimal(basePrice)).build();
    }

    private ProductSku sku(Long id, String skuCode, String price) {
        return ProductSku.builder().id(id).productId(PRODUCT_ID).skuCode(skuCode)
                .price(new BigDecimal(price)).stock(BigDecimal.valueOf(100)).build();
    }

    /** 422 + {@code VALIDATION_ERROR} + 可行动 suggestion —— 判「拒绝」时三条一起断言（不是只看抛没抛）。 */
    private void assertFailClosed(BusinessException ex, String messageFragment) {
        assertThat(ex.getHttpStatus()).isEqualTo(422);
        assertThat(ex.getCode()).isEqualTo("VALIDATION_ERROR");
        assertThat(ex.getMessage()).contains(messageFragment).contains("fail-closed");
        assertThat(ex.getSuggestion()).contains("product_detail");
    }

    // ──────────────────────────── 判据 1：多规格多价 + 未声明规格 ⇒ 422（改前静默放过）

    @Test
    @DisplayName("🔴 判据1 无 SKU 标识 + 商品有多个不同规格价 ⇒ 422（红证：改前静默放过、订单照建）")
    void multiPriceProductWithoutSpecIsRejected() {
        when(productMapper.selectById(PRODUCT_ID)).thenReturn(product(PRODUCT_ID, "遮光窗帘", "168"));
        when(productSkuMapper.selectList(any(LambdaQueryWrapper.class)))
                .thenReturn(List.of(sku(1L, "SKU-150", "150"), sku(2L, "SKU-180", "180")));

        assertThatThrownBy(() -> orderService.createOrderForAgent(
                agentRequest(PRODUCT_ID, "遮光窗帘", new BigDecimal("150"), null), TENANT_ID))
                .isInstanceOfSatisfying(BusinessException.class, ex -> {
                    assertFailClosed(ex, "多个不同规格价");
                    assertThat(ex.getMessage()).contains("遮光窗帘");
                });
        // 拒绝必须**零落库**：不能「先建单再报错」
        verify(orderMapper, never()).insert(any(Order.class));
    }

    // ──────────────────────────── 判据 2：只有商品名 + 编造价 ⇒ 422（= OR-014 的真实形态）

    @Test
    @DisplayName("🔴 判据2 明细只有商品名（无 product_id / 无规格键）+ 单价≠库价 ⇒ 422"
            + "（红证：改前静默放过 = #3881 原文「product_id 落库为 NULL、编造价一路进总额」）")
    void nameOnlyLineWithMismatchedPriceIsRejected() {
        // 商品名唯一匹配（工具层接地解析同款退路）：库价 168，明细编造 150
        when(productMapper.selectList(any(LambdaQueryWrapper.class)))
                .thenReturn(List.of(product(PRODUCT_ID, "遮光窗帘", "168")));
        when(productSkuMapper.selectList(any(LambdaQueryWrapper.class)))
                .thenReturn(List.of(sku(1L, "SKU-168", "168")));

        assertThatThrownBy(() -> orderService.createOrderForAgent(
                agentRequest(null, "遮光窗帘", new BigDecimal("150"), null), TENANT_ID))
                .isInstanceOfSatisfying(BusinessException.class, ex -> {
                    assertThat(ex.getHttpStatus()).isEqualTo(422);
                    assertThat(ex.getMessage()).contains("单价与系统价格不一致")
                            .contains("请求 150.00 元").contains("系统价 168.00 元");
                });
        verify(orderMapper, never()).insert(any(Order.class));
    }

    // ──────────────────────────── 判据 3：商品解析不到 ⇒ 422（不猜是哪一个商品）

    @Test
    @DisplayName("🔴 判据3 商品名在库中匹配不到唯一商品 ⇒ 422 且指名补 product_id（红证：改前静默放过）")
    void unresolvableProductIsRejected() {
        when(productMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of());

        assertThatThrownBy(() -> orderService.createOrderForAgent(
                agentRequest(null, "不存在的商品", new BigDecimal("150"), null), TENANT_ID))
                .isInstanceOfSatisfying(BusinessException.class,
                        ex -> assertFailClosed(ex, "匹配不到唯一商品"));
        verify(orderMapper, never()).insert(any(Order.class));
    }

    // ──────────────────────────── 判据 4：工具层「首选键」skuId 此前不被守卫识别 ⇒ 一并修

    @Test
    @DisplayName("🔴 判据4 只声明 processingInfo.skuId（工具层首选键）+ 单价≠该 SKU 价 ⇒ 422"
            + "（红证：改前守卫只认 skuCode/colorName ⇒ skuId 被当成「无标识」放过）")
    void skuIdOnlyLineIsChecked() {
        ProductSku target = ProductSku.builder().id(77L).productId(PRODUCT_ID).skuCode("SKU-77")
                .price(new BigDecimal("168")).stock(BigDecimal.valueOf(10)).build();
        when(productSkuMapper.selectById(77L)).thenReturn(target);

        assertThatThrownBy(() -> orderService.createOrderForAgent(
                agentRequest(PRODUCT_ID, "遮光窗帘", new BigDecimal("150"), Map.of("skuId", 77L)), TENANT_ID))
                .isInstanceOfSatisfying(BusinessException.class, ex -> {
                    assertThat(ex.getHttpStatus()).isEqualTo(422);
                    assertThat(ex.getMessage()).contains("单价与系统价格不一致").contains("系统价 168.00");
                });
        verify(orderMapper, never()).insert(any(Order.class));
    }

    // ──────────────────────────── 判据 5/6：单规格价商品（合法形态）⇒ 不拦，但要真核对

    @Test
    @DisplayName("判据5 合法形态：商品 SKU 价唯一 + 未声明规格 ⇒ **不得拦**（单价一致即落单）")
    void singlePriceProductWithoutSpecIsNotBlocked() {
        when(productMapper.selectById(PRODUCT_ID)).thenReturn(product(PRODUCT_ID, "遮光窗帘", "150"));
        when(productSkuMapper.selectList(any(LambdaQueryWrapper.class)))
                .thenReturn(List.of(sku(1L, "SKU-A", "150"), sku(2L, "SKU-B", "150")));

        OrderDetailResponse result = orderService.createOrderForAgent(
                agentRequest(PRODUCT_ID, "遮光窗帘", new BigDecimal("150"), null), TENANT_ID);

        assertThat(result.getStatus()).isEqualTo("pending");
        assertThat(result.getTotalAmount()).isEqualByComparingTo("300.00");
        verify(orderMapper, atLeastOnce()).insert(any(Order.class));
    }

    @Test
    @DisplayName("🔴 判据6 合法形态同一夹具、单价改成 151 ⇒ 422"
            + "（红证：改前「无标识 ⇒ 零核对」，151 也能落单）")
    void singlePriceProductWithWrongPriceIsRejected() {
        when(productMapper.selectById(PRODUCT_ID)).thenReturn(product(PRODUCT_ID, "遮光窗帘", "150"));
        when(productSkuMapper.selectList(any(LambdaQueryWrapper.class)))
                .thenReturn(List.of(sku(1L, "SKU-A", "150"), sku(2L, "SKU-B", "150")));

        assertThatThrownBy(() -> orderService.createOrderForAgent(
                agentRequest(PRODUCT_ID, "遮光窗帘", new BigDecimal("151"), null), TENANT_ID))
                .isInstanceOfSatisfying(BusinessException.class, ex -> {
                    assertThat(ex.getHttpStatus()).isEqualTo(422);
                    assertThat(ex.getMessage()).contains("系统价 150.00");
                });
        verify(orderMapper, never()).insert(any(Order.class));
    }

    // ──────────────────────────── 判据 7：无 SKU 记录的简单商品（卖布行形态）⇒ 商品级价

    @Test
    @DisplayName("判据7 合法形态：商品**没有 SKU 记录**（简单商品/卖布行）+ 单价 = 商品级价 ⇒ 不得拦")
    void simpleProductWithoutSkuRowsUsesBasePrice() {
        when(productMapper.selectById(PRODUCT_ID)).thenReturn(product(PRODUCT_ID, "纯色布", "30"));
        when(productSkuMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of());

        OrderDetailResponse result = orderService.createOrderForAgent(
                agentRequest(PRODUCT_ID, "纯色布", new BigDecimal("30"), null), TENANT_ID);

        assertThat(result.getStatus()).isEqualTo("pending");
        assertThat(result.getTotalAmount()).isEqualByComparingTo("60.00");
    }

    // ──────────────────────────── 判据 8：无加工项行不受影响（加工项与 SKU 标识是两个维度）

    @Test
    @DisplayName("判据8 合法形态：无加工项行（processing_info 无 processingItems）+ 已声明 skuId "
            + "⇒ 与声明键族同口径，单价一致即落单")
    void lineWithoutProcessingItemsIsUnaffected() {
        ProductSku target = ProductSku.builder().id(88L).productId(PRODUCT_ID).skuCode("SKU-88")
                .price(new BigDecimal("150")).stock(BigDecimal.valueOf(10)).build();
        when(productSkuMapper.selectById(88L)).thenReturn(target);

        OrderDetailResponse result = orderService.createOrderForAgent(
                agentRequest(PRODUCT_ID, "遮光窗帘", new BigDecimal("150"), Map.of("skuId", 88L)), TENANT_ID);

        assertThat(result.getStatus()).isEqualTo("pending");
        assertThat(result.getTotalAmount()).isEqualByComparingTo("300.00");
    }

    // ──────────────────────────── 判据 9：表单路径不经本守卫 ⇒ 调用方影响边界

    @Test
    @DisplayName("判据9 调用方边界：表单路径（createOrder，POST /api/admin/orders）同一份无标识明细"
            + "**逐字不变**（不经 Agent 取价守卫）")
    void formPathIsUnaffected() {
        // 表单路径根本不查商品/规格：同样的「无 SKU 标识」明细照样落单（改前改后一致）
        OrderDetailResponse result = orderService.createOrder(
                formRequest(PRODUCT_ID, "遮光窗帘", new BigDecimal("150")), TENANT_ID);

        assertThat(result.getStatus()).isEqualTo("pending");
        assertThat(result.getTotalAmount()).isEqualByComparingTo("300.00");
        verify(productSkuMapper, never()).selectList(any(LambdaQueryWrapper.class));
        verify(productMapper, never()).selectList(any(LambdaQueryWrapper.class));
    }
}