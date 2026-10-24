// case_ids: PRC-004
package com.migao.admin.service;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 改价闸门判定（issue #7375，P1-3 段 4）—— 「低于成本必须审批」的边界，含**成本未知不阻断**的取舍。
 *
 * <p>两边的错都很难发现：判松了 = 谁都能把价改到亏本；判紧了 = 存量商品（没录进价）全都改不了价，
 * 运营会绕开系统去改。</p>
 */
@DisplayName("改价闸门：低于成本需审批 / 等于成本放行 / 成本未知不阻断")
class PriceFloorPolicyTest {

    @Test
    @DisplayName("🔴 低于成本 ⇒ 需要审批，并给出缺口（差多少）")
    void belowCostNeedsApproval() {
        var decision = PriceFloorPolicy.evaluate(new BigDecimal("80"), new BigDecimal("100"));
        assertThat(decision.needsApproval()).isTrue();
        assertThat(decision.costUnknown()).isFalse();
        assertThat(decision.shortfall()).isEqualByComparingTo("20");
    }

    @Test
    @DisplayName("等于或高于成本 ⇒ 不需要审批（等于成本不是亏本）")
    void atOrAboveCostIsFine() {
        assertThat(PriceFloorPolicy.evaluate(new BigDecimal("100"), new BigDecimal("100")).needsApproval()).isFalse();
        assertThat(PriceFloorPolicy.evaluate(new BigDecimal("120"), new BigDecimal("100")).needsApproval()).isFalse();
    }

    @Test
    @DisplayName("🔴 成本未知（null / 0 / 负数）⇒ **不阻断**，但显式标 costUnknown")
    void unknownCostDoesNotBlockButIsLabelled() {
        var nullCost = PriceFloorPolicy.evaluate(new BigDecimal("1"), null);
        assertThat(nullCost.needsApproval()).as("拿未知当零成本会让闸门变假").isFalse();
        assertThat(nullCost.costUnknown()).as("但必须留痕「这次没有底价可依」").isTrue();

        assertThat(PriceFloorPolicy.evaluate(new BigDecimal("1"), BigDecimal.ZERO).costUnknown()).isTrue();
        assertThat(PriceFloorPolicy.evaluate(new BigDecimal("1"), new BigDecimal("-5")).costUnknown()).isTrue();
    }

    @Test
    @DisplayName("价格为 null ⇒ 交给上游「价格必填」校验，本判定不阻断也不撒谎")
    void nullPriceIsNotJudgedHere() {
        var decision = PriceFloorPolicy.evaluate(null, new BigDecimal("100"));
        assertThat(decision.needsApproval()).isFalse();
        assertThat(decision.costUnknown()).isTrue();
    }
}
