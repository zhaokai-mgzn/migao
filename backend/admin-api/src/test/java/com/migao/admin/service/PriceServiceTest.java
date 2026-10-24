// case_ids: PRC-001
package com.migao.admin.service;

import com.migao.admin.entity.CustomerProfile;
import com.migao.admin.entity.ProductSku;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.CustomerProfileMapper;
import com.migao.admin.mapper.ProductSkuMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;
import org.springframework.jdbc.core.JdbcTemplate;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.contains;
import static org.mockito.Mockito.when;

/**
 * 价格解析服务（issue #7375 段 1）—— 取数口径与「三张价格本各自出现在哪一层」。
 *
 * <p>纯函数已验过优先级；本文件验的是**取数**：协议价按客户、等级价按 `vip_level`、
 * 阶梯价按 SKU 数量区间，且客户/SKU 缺数据时不会崩、不会把「查不到」读成 0。</p>
 */
@DisplayName("价格服务：三表取数 / 客户不存在仍可报价 / SKU 不存在 404")
class PriceServiceTest {

    private ProductSkuMapper productSkuMapper;
    private CustomerProfileMapper customerProfileMapper;
    private JdbcTemplate jdbcTemplate;
    private PriceService service;

    @BeforeEach
    void setUp() {
        productSkuMapper = Mockito.mock(ProductSkuMapper.class);
        customerProfileMapper = Mockito.mock(CustomerProfileMapper.class);
        jdbcTemplate = Mockito.mock(JdbcTemplate.class);
        service = new PriceService(productSkuMapper, customerProfileMapper, jdbcTemplate);

        ProductSku sku = new ProductSku();
        sku.setId(10L);
        sku.setTenantId(1L);
        sku.setPrice(new BigDecimal("100.00"));
        when(productSkuMapper.selectById(10L)).thenReturn(sku);

        CustomerProfile customer = new CustomerProfile();
        customer.setId("c-1");
        customer.setTenantId(1L);
        customer.setVipLevel("vip2");
        when(customerProfileMapper.selectById("c-1")).thenReturn(customer);
    }

    /** 按 SQL 文本分派价格本读数（避免 JdbcTemplate 重载的匹配歧义）。 */
    private void stubPriceBook(BigDecimal protocol, BigDecimal vip) {
        when(jdbcTemplate.query(Mockito.anyString(),
                Mockito.<org.springframework.jdbc.core.RowMapper<BigDecimal>>any(),
                Mockito.any(Object[].class)))
                .thenAnswer(inv -> {
                    String sql = inv.getArgument(0);
                    BigDecimal value = sql.contains("customer_sku_prices") ? protocol : vip;
                    return value == null ? List.of() : List.of(value);
                });
    }

    private void stubNoTiers() {
        when(jdbcTemplate.queryForList(anyString(), Mockito.any(Object[].class))).thenReturn(List.of());
    }

    @Test
    @DisplayName("协议价命中 ⇒ 按协议价（客户 × SKU 是最具体的承诺）")
    void protocolWins() {
        stubPriceBook(new BigDecimal("88.00"), new BigDecimal("92.00"));
        stubNoTiers();

        var r = service.resolvePrice("c-1", 10L, new BigDecimal("5"));

        assertThat(r.source()).isEqualTo(PriceResolution.Source.PROTOCOL);
        assertThat(r.price()).isEqualByComparingTo("88.00");
    }

    @Test
    @DisplayName("没有协议价 ⇒ 等级价（按客户当前的 vip_level 取，不是按客户 id）")
    void vipLevelPriceUsedWhenNoProtocol() {
        stubPriceBook(null, new BigDecimal("92.00"));
        stubNoTiers();

        var r = service.resolvePrice("c-1", 10L, new BigDecimal("5"));

        assertThat(r.source()).isEqualTo(PriceResolution.Source.VIP_LEVEL);
        assertThat(r.price()).isEqualByComparingTo("92.00");
    }

    @Test
    @DisplayName("两个专属价都没有 ⇒ 阶梯价按数量命中")
    void tierPriceMatchesQuantity() {
        stubPriceBook(null, null);
        when(jdbcTemplate.queryForList(anyString(), Mockito.any(Object[].class)))
                .thenReturn(List.of(Map.of("min_qty", new BigDecimal("50"), "max_qty", new BigDecimal("99.9"),
                        "price", new BigDecimal("90.00"))));

        var r = service.resolvePrice("c-1", 10L, new BigDecimal("60"));

        assertThat(r.source()).isEqualTo(PriceResolution.Source.TIER);
        assertThat(r.price()).isEqualByComparingTo("90.00");
        assertThat(r.tierMinQty()).isEqualByComparingTo("50");
    }

    @Test
    @DisplayName("没有客户 ⇒ 跳过专属价，仍能报价（散客按阶梯/标准价）")
    void noCustomerStillQuotes() {
        stubPriceBook(null, null);
        stubNoTiers();

        var r = service.resolvePrice(null, 10L, new BigDecimal("1"));

        assertThat(r.source()).isEqualTo(PriceResolution.Source.STANDARD);
        assertThat(r.price()).isEqualByComparingTo("100.00");
    }

    @Test
    @DisplayName("标准价 0 且无专属价 ⇒ 未定价（不是 0 元成交）")
    void zeroStandardPriceIsUnpriced() {
        ProductSku sku = new ProductSku();
        sku.setId(11L);
        sku.setTenantId(1L);
        sku.setPrice(BigDecimal.ZERO);
        when(productSkuMapper.selectById(11L)).thenReturn(sku);
        stubNoTiers();

        var r = service.resolvePrice(null, 11L, new BigDecimal("1"));

        assertThat(r.source()).isEqualTo(PriceResolution.Source.UNPRICED);
        assertThat(r.price()).isNull();
    }

    @Test
    @DisplayName("SKU 不存在 ⇒ 404（报价面不是空结果）")
    void missingSkuIsNotFound() {
        when(productSkuMapper.selectById(99L)).thenReturn(null);
        assertThatThrownBy(() -> service.resolvePrice(null, 99L, BigDecimal.ONE))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("SKU");
    }
}
