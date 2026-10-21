// case_ids: RPT-002
package com.migao.admin.service;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.time.LocalDate;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 库存滞销判定（issue #7376，P1-4 段 2）—— 「滞销」的口径写死在判据里，不留口头定义。
 *
 * <p>三条边界各有代价：把没货的批次算滞销 ⇒ 清单被空行淹没；从未出库的不按入库日算 ⇒
 * **最该被看见的货永远不出现**；缺日期时猜 0 天 ⇒ 报表看起来正常但结论是编的。</p>
 */
@DisplayName("滞销判定：满阈值才算 / 无货不算 / 从未出库按入库日 / 缺日期不猜")
class InventoryAgePolicyTest {

    private static final LocalDate TODAY = LocalDate.of(2026, 10, 22);

    @Test
    @DisplayName("满阈值（含第 90 天）⇒ 滞销；差一天不算")
    void thresholdIsInclusive() {
        var at90 = InventoryAgePolicy.evaluate(new BigDecimal("100"), TODAY.minusDays(90), TODAY, 90);
        assertThat(at90.slowMoving()).isTrue();
        assertThat(at90.daysSinceMovement()).isEqualTo(90);

        var at89 = InventoryAgePolicy.evaluate(new BigDecimal("100"), TODAY.minusDays(89), TODAY, 90);
        assertThat(at89.slowMoving()).as("差一天就不是滞销（阈值是实数边界）").isFalse();
    }

    @Test
    @DisplayName("🔴 没货的批次不参与滞销判定（0 库存谈压货没有意义）")
    void zeroOnHandIsNotSlowMoving() {
        var decision = InventoryAgePolicy.evaluate(BigDecimal.ZERO, TODAY.minusDays(400), TODAY, 90);
        assertThat(decision.slowMoving()).isFalse();
        assertThat(decision.reason()).contains("无库存");
    }

    @Test
    @DisplayName("🔴 缺日期（连入库日都没有）⇒ 不判定、不猜 0 天，如实说明")
    void missingDatesAreNotJudged() {
        var decision = InventoryAgePolicy.evaluate(new BigDecimal("100"), null, TODAY, 90);
        assertThat(decision.slowMoving()).isFalse();
        assertThat(decision.daysSinceMovement()).as("负数 = 未判定（不是 0 天）").isNegative();
        assertThat(decision.reason()).contains("无法判定");
    }

    @Test
    @DisplayName("未来日期（脏数据）⇒ 不判滞销，如实标记")
    void futureDatesAreNotJudged() {
        var decision = InventoryAgePolicy.evaluate(new BigDecimal("100"), TODAY.plusDays(5), TODAY, 90);
        assertThat(decision.slowMoving()).isFalse();
        assertThat(decision.reason()).contains("未来");
    }

    @Test
    @DisplayName("阈值参数：<=0 用默认 90 天；自定义阈值按传入算")
    void thresholdOverride() {
        var withDefault = InventoryAgePolicy.evaluate(new BigDecimal("10"), TODAY.minusDays(30), TODAY, 0);
        assertThat(withDefault.slowMoving()).as("默认 90 天 ⇒ 30 天不算滞销").isFalse();

        var custom = InventoryAgePolicy.evaluate(new BigDecimal("10"), TODAY.minusDays(30), TODAY, 30);
        assertThat(custom.slowMoving()).as("自定义 30 天 ⇒ 满 30 天算滞销").isTrue();
        assertThat(InventoryAgePolicy.SLOW_MOVING_DAYS).isEqualTo(90);
    }
}
