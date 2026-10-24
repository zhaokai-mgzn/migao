// case_ids: STK-001
package com.migao.admin.service;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 盘点差异恒等式（issue #7373，P1-1 段 2）—— 「盘点结果可信」的唯一凭据。
 *
 * <p>这里写错不报错：少调一个批次、差异符号写反、把「还没数」当成「数了正好一样」——
 * 三种都让账面悄悄偏离实物，而账面看起来依然正常。</p>
 */
@DisplayName("盘点恒等式：逐批次差异 / 合计守恒 / 全数才可完成 / 调整不为负")
class StocktakePolicyTest {

    private static StocktakePolicy.Line line(String book, String counted) {
        return new StocktakePolicy.Line(new BigDecimal(book),
                counted == null ? null : new BigDecimal(counted));
    }

    @Test
    @DisplayName("逐批次差异 = 实盘 − 账面（盘亏为负，盘盈为正）")
    void diffPerLine() {
        assertThat(line("100", "97").diff()).isEqualByComparingTo("-3");
        assertThat(line("100", "104").diff()).isEqualByComparingTo("4");
        assertThat(line("100", "100").diff()).isEqualByComparingTo("0");
    }

    @Test
    @DisplayName("🔴 没录实盘 ⇒ 差异是 null（不是 0）：还没数 ≠ 数了正好一样")
    void uncountedIsNullNotZero() {
        assertThat(line("100", null).diff()).isNull();
        assertThat(line("100", null).counted()).isFalse();
        assertThat(line("100", null).differs()).isFalse();
    }

    @Test
    @DisplayName("🔴 落库三列自相一致：Σ(实盘−账面) == Σ存储差异（改了实盘没同步差异 ⇒ 抓出来）")
    void storedColumnsAgree() {
        var ok = List.of(
                new StocktakePolicy.StoredRow(new BigDecimal("100"), new BigDecimal("97"), new BigDecimal("-3")),
                new StocktakePolicy.StoredRow(new BigDecimal("50"), new BigDecimal("55"), new BigDecimal("5")));
        assertThat(StocktakePolicy.storedDiffsAgreeWithQuantities(ok)).isTrue();

        // 脏数据：实盘改成 96，但差异还是 -3（少同步了 1 米）
        var drift = List.of(
                new StocktakePolicy.StoredRow(new BigDecimal("100"), new BigDecimal("96"), new BigDecimal("-3")));
        assertThat(StocktakePolicy.storedDiffsAgreeWithQuantities(drift))
                .as("这类脏数据单看任何一列都正常，只有三列一起看才现形").isFalse();
    }

    @Test
    @DisplayName("差异绝对值合计 = 审批金额依据（盘盈盘亏都要有人看过）")
    void totalAbsDiff() {
        var rows = List.of(line("100", "97"), line("50", "55"));
        assertThat(StocktakePolicy.totalAbsDiff(rows)).isEqualByComparingTo("8");
    }

    @Test
    @DisplayName("🔴 有一条没数就不能完成盘点（否则等于默认它「一样」）")
    void allCountedRequired() {
        assertThat(StocktakePolicy.allCounted(List.of(line("10", "10"), line("20", "20")))).isTrue();
        assertThat(StocktakePolicy.allCounted(List.of(line("10", "10"), line("20", null)))).isFalse();
        assertThat(StocktakePolicy.allCounted(List.of())).as("空盘点不能算完成").isFalse();
    }

    @Test
    @DisplayName("调整后不为负（盘亏不能让库存变成负数）")
    void adjustmentNeverNegative() {
        assertThat(StocktakePolicy.adjustable(new BigDecimal("10"), new BigDecimal("-10"))).isTrue();
        assertThat(StocktakePolicy.adjustable(new BigDecimal("10"), new BigDecimal("-10.1"))).isFalse();
        assertThat(StocktakePolicy.adjustable(new BigDecimal("10"), new BigDecimal("5"))).isTrue();
    }
}
