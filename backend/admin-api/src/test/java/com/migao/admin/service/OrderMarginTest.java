// case_ids: AR-003
package com.migao.admin.service;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 订单毛利纯函数（issue #7371，P0-3 段 1）—— **「成本未知 ≠ 0」** 是这里的第一判据。
 *
 * <p>为什么单独考：未知当 0 会让屏幕上出现一个漂亮的毛利率，而它虚高（把成本当成没花钱）。
 * 这种错不会报错、不会崩，只会让老板按错的价格接单。</p>
 *
 * <p>红证方向：`compute` 里把 `fabricCost == null` 当成 0 ⇒ {@link #unknownCostIsNeverZero} 当场红。</p>
 */
@DisplayName("订单毛利：收入−退款−面料；成本未知绝不当 0；毛利率分母 = 净收入")
class OrderMarginTest {

    @Test
    @DisplayName("常规：收入 1000 · 退 100 · 面料 400 ⇒ 毛利 500，毛利率 500/900")
    void plainMargin() {
        var r = OrderMargin.compute(new BigDecimal("1000"), new BigDecimal("100"),
                new BigDecimal("400"), 0);
        assertThat(r.costKnown()).isTrue();
        assertThat(r.fabricCost()).isEqualByComparingTo("400");
        assertThat(r.grossMargin()).isEqualByComparingTo("500");
        // 毛利率 = 毛利 / 净收入（1000 − 100 = 900）⇒ 0.5556
        assertThat(r.marginRate()).isEqualByComparingTo("0.5556");
    }

    @Test
    @DisplayName("🔴 成本未知（有行缺进价）⇒ 毛利与毛利率都是 null，成本也不填 0")
    void unknownCostIsNeverZero() {
        var byUnknownLines = OrderMargin.compute(new BigDecimal("1000"), BigDecimal.ZERO,
                new BigDecimal("400"), 2);
        assertThat(byUnknownLines.costKnown()).isFalse();
        assertThat(byUnknownLines.fabricCost()).isNull();
        assertThat(byUnknownLines.grossMargin()).as("不能拿「收入全额」当毛利").isNull();
        assertThat(byUnknownLines.marginRate()).isNull();

        // fabricCost 直接传 null 也走同一条路（服务层的两种未知表达都要被兜住）
        var byNullCost = OrderMargin.compute(new BigDecimal("1000"), BigDecimal.ZERO, null, 0);
        assertThat(byNullCost.costKnown()).isFalse();
        assertThat(byNullCost.grossMargin()).isNull();
    }

    @Test
    @DisplayName("面料成本 0（还没领料）是**真 0**：毛利 = 净收入，不是「未知」")
    void zeroCostIsKnown() {
        var r = OrderMargin.compute(new BigDecimal("1000"), BigDecimal.ZERO, BigDecimal.ZERO, 0);
        assertThat(r.costKnown()).isTrue();
        assertThat(r.grossMargin()).isEqualByComparingTo("1000");
        assertThat(r.marginRate()).isEqualByComparingTo("1");
    }

    @Test
    @DisplayName("亏本单：毛利为负（不截断成 0）")
    void negativeMarginIsKept() {
        var r = OrderMargin.compute(new BigDecimal("1000"), BigDecimal.ZERO, new BigDecimal("1300"), 0);
        assertThat(r.grossMargin()).isEqualByComparingTo("-300");
        assertThat(r.marginRate()).isEqualByComparingTo("-0.3");
    }

    @Test
    @DisplayName("净收入 ≤ 0（退满 / 退超）⇒ 毛利率 null，但毛利照实给（不做 0 除）")
    void rateIsNullWhenNetRevenueIsNotPositive() {
        var r = OrderMargin.compute(new BigDecimal("1000"), new BigDecimal("1000"),
                new BigDecimal("400"), 0);
        assertThat(r.grossMargin()).isEqualByComparingTo("-400");
        assertThat(r.marginRate()).as("净收入 0 ⇒ 分母无意义，不许给 0 或负无穷").isNull();
    }

    @Test
    @DisplayName("空值兜底：收入/退款 null 当 0 但不产生 NPE（存量脏行不让页面 500）")
    void nullsAreTolerated() {
        var r = OrderMargin.compute(null, null, new BigDecimal("10"), 0);
        assertThat(r.costKnown()).isTrue();
        assertThat(r.grossMargin()).isEqualByComparingTo("-10");
        assertThat(r.marginRate()).isNull();   // 净收入 0 ⇒ null
    }

    @Test
    @DisplayName("口径自述常量：本段只算面料毛利（不许被读成完全成本毛利）")
    void scopeIsSelfDescribing() {
        assertThat(OrderMargin.SCOPE_FABRIC_ONLY).isEqualTo("revenue_minus_refund_minus_fabric");
    }
}
