// case_ids: PRC-001
package com.migao.admin.service;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 价格解析纯函数（issue #7375，P1-3 段 1）—— 优先级顺序 + **未定价 ≠ ¥0.00**。
 *
 * <p>为什么单独考：价格算错不会报错，只会静默少收钱或白送。两个最贵的错法：
 * ① 有协议价却按标准价收（客户投诉「说好的价呢」）；
 * ② 根本没有价却算出 0（SKU 的 `price` 列 `DEFAULT 0` ⇒ 「0 元成交」）。</p>
 *
 * <p>红证方向：把 {@link PriceResolution#resolve} 的优先级改成标准价优先 ⇒
 * {@link #protocolBeatsEverything} 当场红；把未定价返回 0 ⇒ {@link #unpricedIsNeverZero} 当场红。</p>
 */
@DisplayName("价格解析：协议 > 等级 > 阶梯 > 标准；未定价绝不给 0")
class PriceResolutionTest {

    private static PriceResolution.Tier tier(String min, String max, String price) {
        return new PriceResolution.Tier(
                new BigDecimal(min), max == null ? null : new BigDecimal(max), new BigDecimal(price));
    }

    @Test
    @DisplayName("🔴 协议价最高优先：同时有等级价 / 阶梯价 / 标准价也按协议价")
    void protocolBeatsEverything() {
        var r = PriceResolution.resolve(new BigDecimal("88.00"), new BigDecimal("92.00"),
                List.of(tier("1", "999", "95.00")), new BigDecimal("100.00"), new BigDecimal("10"));
        assertThat(r.source()).isEqualTo(PriceResolution.Source.PROTOCOL);
        assertThat(r.price()).isEqualByComparingTo("88.00");
        assertThat(r.priced()).isTrue();
    }

    @Test
    @DisplayName("没有协议价 ⇒ 等级价；等级价也没有 ⇒ 阶梯价（命中区间才生效）")
    void fallsBackThroughLayersInOrder() {
        var vip = PriceResolution.resolve(null, new BigDecimal("92.00"),
                List.of(tier("1", "99", "95.00")), new BigDecimal("100.00"), new BigDecimal("10"));
        assertThat(vip.source()).isEqualTo(PriceResolution.Source.VIP_LEVEL);
        assertThat(vip.price()).isEqualByComparingTo("92.00");

        var tiered = PriceResolution.resolve(null, null,
                List.of(tier("1", "99", "95.00")), new BigDecimal("100.00"), new BigDecimal("10"));
        assertThat(tiered.source()).isEqualTo(PriceResolution.Source.TIER);
        assertThat(tiered.price()).isEqualByComparingTo("95.00");
        assertThat(tiered.tierMinQty()).isEqualByComparingTo("1");

        var standard = PriceResolution.resolve(null, null,
                List.of(tier("50", null, "80.00")), new BigDecimal("100.00"), new BigDecimal("10"));
        assertThat(standard.source()).as("数量 10 不在 50 起的档内 ⇒ 落到标准价").isEqualTo(PriceResolution.Source.STANDARD);
        assertThat(standard.price()).isEqualByComparingTo("100.00");
    }

    @Test
    @DisplayName("阶梯边界：闭区间（等于上/下限都命中）；多档重叠取门槛更高的那档")
    void tierBoundariesAreInclusive() {
        var tiers = List.of(tier("1", "49.9", "100.00"), tier("50", "99.9", "95.00"), tier("100", null, "88.00"));
        assertThat(PriceResolution.resolve(null, null, tiers, null, new BigDecimal("49.9")).price())
                .isEqualByComparingTo("100.00");
        assertThat(PriceResolution.resolve(null, null, tiers, null, new BigDecimal("50")).price())
                .isEqualByComparingTo("95.00");
        assertThat(PriceResolution.resolve(null, null, tiers, null, new BigDecimal("99.9")).price())
                .isEqualByComparingTo("95.00");
        assertThat(PriceResolution.resolve(null, null, tiers, null, new BigDecimal("100")).price())
                .isEqualByComparingTo("88.00");
        assertThat(PriceResolution.resolve(null, null, tiers, null, new BigDecimal("999")).price())
                .isEqualByComparingTo("88.00");
    }

    @Test
    @DisplayName("🔴 未定价绝不给 0：四层皆无 ⇒ price = null、source = unpriced")
    void unpricedIsNeverZero() {
        var r = PriceResolution.resolve(null, null, List.of(), null, new BigDecimal("5"));
        assertThat(r.source()).isEqualTo(PriceResolution.Source.UNPRICED);
        assertThat(r.price()).as("0 元 = 白送；未定价必须留空").isNull();
        assertThat(r.priced()).isFalse();
    }

    @Test
    @DisplayName("标准价 0 视为「没有标准价」（列 DEFAULT 0 不是价格），仍落到未定价")
    void zeroStandardPriceIsNotAPrice() {
        var r = PriceResolution.resolve(null, null, List.of(), BigDecimal.ZERO, new BigDecimal("5"));
        assertThat(r.source()).isEqualTo(PriceResolution.Source.UNPRICED);
        assertThat(r.price()).isNull();
    }

    @Test
    @DisplayName("脏配置不崩：协议价/等级价为负或 0 一律跳过；数量为 null 时阶梯不参与")
    void dirtyConfigFallsThrough() {
        var r = PriceResolution.resolve(BigDecimal.ZERO, new BigDecimal("-1"),
                List.of(tier("1", null, "95.00")), new BigDecimal("100.00"), null);
        assertThat(r.source()).as("数量未知 ⇒ 阶梯区间无法判定").isEqualTo(PriceResolution.Source.STANDARD);

        var zeroTier = PriceResolution.resolve(null, null,
                List.of(tier("1", null, "0")), null, new BigDecimal("5"));
        assertThat(zeroTier.source()).isEqualTo(PriceResolution.Source.UNPRICED);
    }

    @Test
    @DisplayName("金额两位小数（售价分位，不给「半分钱」留口子）")
    void priceIsScaledToTwoDecimals() {
        var r = PriceResolution.resolve(new BigDecimal("88.123456"), null, List.of(), null, BigDecimal.ONE);
        assertThat(r.price()).isEqualByComparingTo("88.12");
        assertThat(r.price().scale()).isEqualTo(2);
    }
}
