// case_ids: PR-093
package com.migao.admin.service;

import com.migao.admin.dto.SavingMetricViews;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 🔴 <b>批次结构趋势序列的定点判据（issue #6459）—— 无 DB、无 Spring。</b>
 *
 * <h2>这条序列是干什么的</h2>
 * 省料看板首屏那张「几乎用完的布（剩余 ≤0.2m）· 批数」表 —— 让读的人一眼看出「布有没有被用干净」，
 * 而不必先理解来源组 / 分档占比这些内部口径（用户逐字：「这个功能只需要用数据和规则说清楚
 * 我们是如何省下多少布料，节省了多少成本即可」）。
 *
 * <h2>真库判据覆盖不到的那一半</h2>
 * 真库夹具里只有「采购在 2026-09、存量在 2026-08」这一种形态。下面这些在夹具里<b>根本长不出来</b>：
 * ① 同一期间**多行相加**；② 期间乱序（输入顺序 ≠ 输出顺序）；③ 未记收货日期（{@code period == null}）；
 * ④ 占比的 4 位小数口径。⇒ 全在纯函数上定点判。
 *
 * <h2>判据（每条都在自己的形态上会红）</h2>
 * <ol>
 *   <li><b>只含采购腿</b>：存量导入（{@code opening}）与来源未知（{@code unknown}）**不进序列** ——
 *       红证 = 把 cohort 过滤摘掉 ⇒ 该期读数由 2 变成 5、占比由 0 变成 0.6；</li>
 *   <li><b>同期多行相加</b>：同一期间的多个（物料）分组必须相加成**一行**；</li>
 *   <li><b>期间升序</b>：输出按期间字典序（{@code 2026-09} 排在 {@code 2026-10} 前，与输入顺序无关）；</li>
 *   <li><b>未记收货日期不猜</b>：{@code period == null} 的分组单独成一行、{@code period} 回 {@code null}；</li>
 *   <li><b>占比口径与看板同源</b>：{@code le0_2Count / batchCount} 四位小数 HALF_UP（{@code 1/3 ⇒ 0.3333}）。</li>
 * </ol>
 */
@DisplayName("#6459 定点：批次结构趋势（只含采购腿 / 同期相加 / 期间升序 / 不猜日期）")
class SavingMetricsBatchTrendTest {

    private static SavingMetricViews.BatchGroup group(String period, String cohort,
                                                      int batchCount, int le0Count) {
        return new SavingMetricViews.BatchGroup(period, cohort,
                SavingMetricViews.cohortLabel(cohort),
                SavingMetricViews.COHORT_OPENING.equals(cohort),
                "p1|SKU-A", "p1", "SKU-A",
                batchCount, le0Count, null, null, List.of());
    }

    @Test
    @DisplayName("🔴 判据1：只含切换后采购 —— 存量导入 / 来源未知不进序列（混入 ⇒ 读数当场变）")
    void onlyThePurchaseCohortEntersTheSeries() {
        List<SavingMetricViews.BatchPeriodPoint> trend = StockBatchConsumptionService.batchTrendOf(List.of(
                group("2026-09", SavingMetricViews.COHORT_PURCHASE, 2, 0),
                group("2026-09", SavingMetricViews.COHORT_OPENING, 2, 2),
                group("2026-09", SavingMetricViews.COHORT_UNKNOWN, 1, 1)));

        assertThat(trend).as("三个来源组同月 ⇒ 序列只有采购那一期").hasSize(1);
        assertThat(trend.get(0).batchCount())
                .as("🔴 只算采购的 2 批（混入 = 5 批）").isEqualTo(2);
        assertThat(trend.get(0).le0_2Count())
                .as("🔴 只算采购的 0 批（混入 = 3 批）").isEqualTo(0);
        assertThat(trend.get(0).le0_2Share())
                .as("🔴 采购占比 = 0/2（混入 = 3/5 = 0.6000）").isEqualByComparingTo("0.0000");
    }

    @Test
    @DisplayName("🔴 判据2：同一期间的多个分组相加成一行（不是每行一期）")
    void rowsOfTheSamePeriodAreSummedIntoOnePoint() {
        List<SavingMetricViews.BatchPeriodPoint> trend = StockBatchConsumptionService.batchTrendOf(List.of(
                group("2026-09", SavingMetricViews.COHORT_PURCHASE, 2, 0),
                group("2026-09", SavingMetricViews.COHORT_PURCHASE, 3, 1)));

        assertThat(trend).hasSize(1);
        assertThat(trend.get(0).batchCount()).as("2 + 3").isEqualTo(5);
        assertThat(trend.get(0).le0_2Count()).as("0 + 1").isEqualTo(1);
        assertThat(trend.get(0).le0_2Share()).isEqualByComparingTo("0.2000");
    }

    @Test
    @DisplayName("🔴 判据3：期间按字典序升序（与输入顺序无关 —— 输入故意倒序）")
    void periodsAreSortedAscendingNotByInputOrder() {
        List<SavingMetricViews.BatchPeriodPoint> trend = StockBatchConsumptionService.batchTrendOf(List.of(
                group("2026-10", SavingMetricViews.COHORT_PURCHASE, 1, 1),
                group("2026-09", SavingMetricViews.COHORT_PURCHASE, 1, 0)));

        assertThat(trend).extracting(SavingMetricViews.BatchPeriodPoint::period)
                .containsExactly("2026-09", "2026-10");
    }

    @Test
    @DisplayName("🔴 判据4：未记收货日期 ⇒ period 回 null（不猜一个日期），且单独成行")
    void nullPeriodStaysNullAndKeepsItsOwnRow() {
        List<SavingMetricViews.BatchPeriodPoint> trend = StockBatchConsumptionService.batchTrendOf(List.of(
                group(null, SavingMetricViews.COHORT_PURCHASE, 2, 2),
                group("2026-09", SavingMetricViews.COHORT_PURCHASE, 3, 0)));

        assertThat(trend).hasSize(2);
        assertThat(trend).extracting(SavingMetricViews.BatchPeriodPoint::period)
                .containsExactly(null, "2026-09");
        assertThat(trend.get(0).batchCount()).as("未记日期的那组自己一行").isEqualTo(2);
    }

    @Test
    @DisplayName("🔴 判据5：占比 = le0_2Count / batchCount，四位小数 HALF_UP（口径与看板同源）")
    void shareKeepsTheSameFourDigitHalfUpRule() {
        List<SavingMetricViews.BatchPeriodPoint> trend = StockBatchConsumptionService.batchTrendOf(List.of(
                group("2026-09", SavingMetricViews.COHORT_PURCHASE, 3, 1)));

        assertThat(trend.get(0).le0_2Share())
                .as("1/3 ⇒ 0.3333（不是 0.33，也不是 0.333）").isEqualByComparingTo("0.3333");
    }

    @Test
    @DisplayName("空输入 ⇒ 空序列（不造一行 0）")
    void emptyInputYieldsEmptySeries() {
        assertThat(StockBatchConsumptionService.batchTrendOf(new ArrayList<>())).isEmpty();
    }
}
