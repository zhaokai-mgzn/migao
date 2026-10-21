// case_ids: PRC-002
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.migao.admin.dto.OrderCreateRequest;
import com.migao.admin.entity.CustomerProfile;
import com.migao.admin.entity.ProductSku;
import com.migao.admin.mapper.CustomerProfileMapper;
import com.migao.admin.mapper.ProductSkuMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;

import java.math.BigDecimal;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;

/**
 * 下单定价服务（issue #7375 段 2）—— **服务端为准**的落地形态与「没有 SKU 就不动价」的边界。
 *
 * <p>三条风险各对应一个用例：</p>
 * <ol>
 *   <li>有协议价但客户端价更低/更高 ⇒ 必须按协议价收，并记下改前值；</li>
 *   <li>没有价格本依据（仅标准价）⇒ **不动**客户端价（否则存量订单全部变价）；</li>
 *   <li>没有 SKU / SKU 定位不到 ⇒ 不参与定价、不报错（手工行与存量调用零回归）。</li>
 * </ol>
 */
@DisplayName("下单定价：协议价覆盖 / 无价格本不动 / 无 SKU 不参与")
class OrderPricingServiceTest {

    private PriceService priceService;
    private ProductSkuMapper productSkuMapper;
    private CustomerProfileMapper customerProfileMapper;
    private OrderPricingService service;

    @BeforeEach
    void setUp() {
        priceService = Mockito.mock(PriceService.class);
        productSkuMapper = Mockito.mock(ProductSkuMapper.class);
        customerProfileMapper = Mockito.mock(CustomerProfileMapper.class);
        service = new OrderPricingService(priceService, productSkuMapper, customerProfileMapper);

        CustomerProfile customer = new CustomerProfile();
        customer.setId("c-1");
        customer.setPhone("13800000000");
        when(customerProfileMapper.findFirstByPhone(any(), any())).thenReturn(customer);

        ProductSku sku = new ProductSku();
        sku.setId(7L);
        sku.setTenantId(1L);
        sku.setSkuCode("SKU-A");
        when(productSkuMapper.selectById(7L)).thenReturn(sku);
        when(productSkuMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of(sku));
    }

    /** SKU 走 `processingInfo` 的既有键族（D1 判据：不加顶层死字段）。 */
    private static OrderCreateRequest.OrderItemRequest item(Object skuId, String skuCode, String price) {
        OrderCreateRequest.OrderItemRequest row = new OrderCreateRequest.OrderItemRequest();
        row.setProductId("p-1");
        java.util.Map<String, Object> info = new java.util.HashMap<>();
        if (skuId != null) {
            info.put("skuId", skuId);
        }
        if (skuCode != null) {
            info.put("skuCode", skuCode);
        }
        row.setProcessingInfo(info);
        row.setQuantity(new BigDecimal("10"));
        row.setUnitPrice(new BigDecimal(price));
        return row;
    }

    @Test
    @DisplayName("🔴 协议价命中 ⇒ 覆盖客户端价，并记下改前值（事后对账靠它）")
    void protocolPriceOverridesClientPrice() {
        when(priceService.resolvePrice(any(), any(), any()))
                .thenReturn(new PriceResolution.Result(new BigDecimal("88.00"),
                        PriceResolution.Source.PROTOCOL, null));
        OrderCreateRequest.OrderItemRequest row = item(7, null, "120.00");

        var trace = service.applyServerPrices(List.of(row), "13800000000", 1L);

        assertThat(row.getUnitPrice()).isEqualByComparingTo("88.00");
        assertThat(trace.get(0).priceSource()).isEqualTo("price_book_protocol");
        assertThat(trace.get(0).clientPrice()).as("改前是多少必须留痕").isEqualByComparingTo("120.00");
    }

    @Test
    @DisplayName("只有标准价（无价格本依据）⇒ 不动客户端价，也不记「改前价」")
    void standardPriceDoesNotTouchClientPrice() {
        when(priceService.resolvePrice(any(), any(), any()))
                .thenReturn(new PriceResolution.Result(new BigDecimal("100.00"),
                        PriceResolution.Source.STANDARD, null));
        OrderCreateRequest.OrderItemRequest row = item(7, null, "120.00");

        var trace = service.applyServerPrices(List.of(row), "13800000000", 1L);

        assertThat(row.getUnitPrice()).as("标准价不覆盖：表单上业务员看到的就是它").isEqualByComparingTo("120.00");
        assertThat(trace.get(0).clientPrice()).isNull();
        assertThat(trace.get(0).priceSource()).isEqualTo("sku_standard_price");
    }

    @Test
    @DisplayName("没有 SKU ⇒ 不参与定价、不报错（手工行与存量调用零回归）")
    void itemWithoutSkuIsNotPriced() {
        OrderCreateRequest.OrderItemRequest row = item(null, null, "120.00");

        var trace = service.applyServerPrices(List.of(row), "13800000000", 1L);

        assertThat(row.getUnitPrice()).isEqualByComparingTo("120.00");
        assertThat(trace.get(0).priceSource()).isEqualTo(OrderPriceOverride.CLIENT_SOURCE);
        assertThat(trace.get(0).skuId()).isNull();
        Mockito.verify(priceService, Mockito.never()).resolvePrice(any(), any(), any());
    }

    @Test
    @DisplayName("只给 skuCode ⇒ 按货号定位 SKU 后再定价（SKU 会硬删重建，货号更耐久）")
    void skuCodeResolvesSku() {
        when(priceService.resolvePrice(any(), any(), any()))
                .thenReturn(new PriceResolution.Result(new BigDecimal("92.00"),
                        PriceResolution.Source.VIP_LEVEL, null));
        OrderCreateRequest.OrderItemRequest row = item(null, "SKU-A", "120.00");

        var trace = service.applyServerPrices(List.of(row), "13800000000", 1L);

        assertThat(trace.get(0).skuId()).as("定位成功后带上 SKU（落库存 order_items.sku_id）").isEqualTo(7L);
        assertThat(row.getUnitPrice()).isEqualByComparingTo("92.00");
        assertThat(trace.get(0).priceSource()).isEqualTo("price_book_vip_level");
    }

    @Test
    @DisplayName("未定价（价格本没有、SKU 标准价也是 0）⇒ 不动客户端价，标签 no_price_book")
    void unpricedKeepsClientPriceButIsLabelled() {
        when(priceService.resolvePrice(any(), any(), any()))
                .thenReturn(new PriceResolution.Result(null, PriceResolution.Source.UNPRICED, null));
        OrderCreateRequest.OrderItemRequest row = item(7, null, "120.00");

        var trace = service.applyServerPrices(List.of(row), "13800000000", 1L);

        assertThat(row.getUnitPrice()).isEqualByComparingTo("120.00");
        assertThat(trace.get(0).priceSource()).isEqualTo("no_price_book");
        assertThat(trace.get(0).clientPrice()).isNull();
    }

    @Test
    @DisplayName("没有手机号 ⇒ 没有客户 ⇒ 仍能定价（散客按标准价，不崩）")
    void noPhoneStillResolves() {
        when(priceService.resolvePrice(any(), any(), any()))
                .thenReturn(new PriceResolution.Result(new BigDecimal("100.00"),
                        PriceResolution.Source.STANDARD, null));
        OrderCreateRequest.OrderItemRequest row = item(7L, null, "100.00");

        var trace = service.applyServerPrices(List.of(row), null, 1L);

        assertThat(trace).hasSize(1);
        assertThat(trace.get(0).priceSource()).isEqualTo("sku_standard_price");
    }
}
