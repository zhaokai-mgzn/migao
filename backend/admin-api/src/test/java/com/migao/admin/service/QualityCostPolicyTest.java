// case_ids: QC-001
package com.migao.admin.service;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 质量成本构成（issue #7377，P1-5 段 1）—— **未知不进合计、也不折成 0**。
 *
 * <p>三种未知各有代价：未定价的返工按 0 计 ⇒ 成本看起来很低（其实是没定价）；报废料按 0 计 ⇒
 * 「本月没有报废损失」这种结论凭空出现；没有退款流水就写 0 ⇒ 把「未发生」当成「已核实为零」。</p>
 */
@DisplayName("质量成本：三项分列 / 未定价不计金额 / 报废恒未知 / 合计只加已知项")
class QualityCostPolicyTest {

    @Test
    @DisplayName("返工工时：有价 ⇒ 已知；有未定价行 ⇒ 该项未知（不按 0 计）")
    void reworkCostHonoursUnpricedRows() {
        var priced = QualityCostPolicy.reworkCost(new BigDecimal("120.5"), 0);
        assertThat(priced.known()).isTrue();
        assertThat(priced.amount()).isEqualByComparingTo("120.50");

        var partiallyUnpriced = QualityCostPolicy.reworkCost(new BigDecimal("120.5"), 3);
        assertThat(partiallyUnpriced.known()).as("有未定价行 ⇒ 金额不可信").isFalse();
        assertThat(partiallyUnpriced.amount()).isNull();
        assertThat(partiallyUnpriced.unknownItems()).isEqualTo(3);
    }

    @Test
    @DisplayName("🔴 报废料恒未知：本仓没有质检记录→批次关联，不能填 0")
    void scrapIsAlwaysUnknown() {
        var scrap = QualityCostPolicy.scrapCost();
        assertThat(scrap.known()).isFalse();
        assertThat(scrap.amount()).isNull();
        assertThat(scrap.note()).contains("不填 0");
    }

    @Test
    @DisplayName("赔付：没有退款流水 ⇒ 未知（不是「赔付为 0」的结论）")
    void compensationWithoutRefundsIsUnknown() {
        assertThat(QualityCostPolicy.compensation(BigDecimal.ZERO, false).known()).isFalse();
        assertThat(QualityCostPolicy.compensation(BigDecimal.ZERO, true).known()).isTrue();
    }

    @Test
    @DisplayName("🔴 合计只累加已知项，并列出未知分项（complete=false）")
    void totalOnlySumsKnownComponents() {
        var components = List.of(
                QualityCostPolicy.reworkCost(new BigDecimal("100"), 0),
                QualityCostPolicy.scrapCost(),
                QualityCostPolicy.compensation(new BigDecimal("50"), true));

        var total = QualityCostPolicy.total(components);

        assertThat(total.amount()).as("100 + 50 = 150（报废未知，不进合计）").isEqualByComparingTo("150");
        assertThat(total.complete()).isFalse();
        assertThat(total.unknownComponents()).containsExactly("scrap_material");
    }

    @Test
    @DisplayName("三项都未知 ⇒ 合计为 null（不是 0），未知项全列出")
    void allUnknownGivesNullTotal() {
        var total = QualityCostPolicy.total(List.of(
                QualityCostPolicy.reworkCost(null, 5),
                QualityCostPolicy.scrapCost(),
                QualityCostPolicy.compensation(BigDecimal.ZERO, false)));

        assertThat(total.amount()).isNull();
        assertThat(total.complete()).isFalse();
        assertThat(total.unknownComponents()).containsExactly("rework_labor", "scrap_material", "compensation");
    }
}
