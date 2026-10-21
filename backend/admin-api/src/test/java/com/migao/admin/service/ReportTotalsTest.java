// case_ids: RPT-001
package com.migao.admin.service;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.util.Arrays;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 报表合计与「空数据 ≠ 0」（issue #7376，P1-4 段 1）—— 报表最容易被信任、也最容易做错的两件事。
 *
 * <p>老板看到「合计 12,000」不会去逐行加：合计算错没人发现，决策按错数走。
 * 而「没有数据」被画成 0 会被读成「这个月毛利是 0」—— 一个要追责、一个要重算，结论完全相反。</p>
 */
@DisplayName("报表合计：合计=明细之和 / 空集为 null 而非 0 / 缺值不参与求和")
class ReportTotalsTest {

    @Test
    @DisplayName("合计 = 明细之和（逐月/逐客户同一份函数，不写第二条聚合 SQL）")
    void sumEqualsDetails() {
        List<BigDecimal> details = List.of(new BigDecimal("100.00"), new BigDecimal("250.50"),
                new BigDecimal("-30.00"));
        BigDecimal total = ReportTotals.sum(details);

        assertThat(total).isEqualByComparingTo("320.50");
        assertThat(ReportTotals.totalsMatchDetails(total, details)).isTrue();
        // 红证方向：合计少算一行 ⇒ 复算立刻不成立
        assertThat(ReportTotals.totalsMatchDetails(new BigDecimal("220.50"), details)).isFalse();
    }

    @Test
    @DisplayName("🔴 空数据 ⇒ 合计为 null（**不是 0**）：没有数据与合计为零是两件事")
    void emptyIsNullNotZero() {
        assertThat(ReportTotals.sum(List.of())).isNull();
        assertThat(ReportTotals.sum(null)).isNull();
        assertThat(ReportTotals.totalsMatchDetails(null, List.of())).isTrue();
        assertThat(ReportTotals.totalsMatchDetails(BigDecimal.ZERO, List.of()))
                .as("空明细配 0 合计 ⇒ 判据必须红（有人把空当零了）").isFalse();
    }

    @Test
    @DisplayName("缺值（null 明细）不参与求和，也不当 0 记账")
    void nullDetailsAreSkipped() {
        List<BigDecimal> withNull = Arrays.asList(new BigDecimal("10"), null, new BigDecimal("5"));
        assertThat(ReportTotals.sum(withNull)).isEqualByComparingTo("15");
        assertThat(ReportTotals.sum(Arrays.asList(null, null))).as("全是缺值 ⇒ 没有合计").isNull();
    }

    @Test
    @DisplayName("hasData：有明细（哪怕值全为 0）⇒ true；没明细 ⇒ false")
    void hasDataDistinguishesZeroFromAbsent() {
        assertThat(ReportTotals.hasData(List.of(BigDecimal.ZERO))).isTrue();
        assertThat(ReportTotals.hasData(List.of())).isFalse();
        assertThat(ReportTotals.hasData(null)).isFalse();
    }
}
