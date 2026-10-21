// case_ids: PRC-002
package com.migao.admin.service;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 下单定价的覆盖判据（issue #7375，P1-3 段 2）。
 *
 * <p>核心取舍：**只有价格本命中才覆盖客户端价**。没有价格本依据时覆盖 = 凭空改单，
 * 且会让存量订单一夜之间全部变价 —— 这是本段最危险的错法，且不会报错。</p>
 */
@DisplayName("下单定价：只有价格本命中才覆盖；未改写不记客户端价")
class OrderPriceOverrideTest {

    @Test
    @DisplayName("协议价 / 等级价 / 阶梯价 ⇒ 覆盖（承诺过的价，客户端那个数本来就不该是它）")
    void priceBookHitsOverride() {
        assertThat(OrderPriceOverride.shouldOverride(PriceResolution.Source.PROTOCOL)).isTrue();
        assertThat(OrderPriceOverride.shouldOverride(PriceResolution.Source.VIP_LEVEL)).isTrue();
        assertThat(OrderPriceOverride.shouldOverride(PriceResolution.Source.TIER)).isTrue();
    }

    @Test
    @DisplayName("🔴 标准价 / 未定价 ⇒ **不覆盖**（没有价格本依据；覆盖 = 凭空改单 + 存量订单变价）")
    void standardAndUnpricedDoNotOverride() {
        assertThat(OrderPriceOverride.shouldOverride(PriceResolution.Source.STANDARD)).isFalse();
        assertThat(OrderPriceOverride.shouldOverride(PriceResolution.Source.UNPRICED)).isFalse();
    }

    @Test
    @DisplayName("落库标签是机器可读来源（不是中文），未定价单独一档")
    void sourceLabelsAreMachineReadable() {
        assertThat(OrderPriceOverride.sourceLabel(PriceResolution.Source.PROTOCOL)).isEqualTo("price_book_protocol");
        assertThat(OrderPriceOverride.sourceLabel(PriceResolution.Source.VIP_LEVEL)).isEqualTo("price_book_vip_level");
        assertThat(OrderPriceOverride.sourceLabel(PriceResolution.Source.TIER)).isEqualTo("price_book_tier");
        assertThat(OrderPriceOverride.sourceLabel(PriceResolution.Source.STANDARD)).isEqualTo("sku_standard_price");
        assertThat(OrderPriceOverride.sourceLabel(PriceResolution.Source.UNPRICED)).isEqualTo("no_price_book");
        assertThat(OrderPriceOverride.CLIENT_SOURCE).isEqualTo("client");
    }

    @Test
    @DisplayName("只记「真被改写」的客户端原价（未改写 ⇒ null，避免把一样的价写成「改过」）")
    void clientPriceRecordedOnlyWhenOverridden() {
        assertThat(OrderPriceOverride.clientPriceWhenOverridden(
                new BigDecimal("120.00"), new BigDecimal("88.00"), true)).isEqualByComparingTo("120.00");
        assertThat(OrderPriceOverride.clientPriceWhenOverridden(
                new BigDecimal("120.00"), new BigDecimal("120.00"), false)).isNull();
    }
}
