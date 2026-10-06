// case_ids: PR-093, PR-094
package com.migao.admin.service;

import com.migao.admin.dto.SavingMetricViews;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 🔴 <b>相邻两期对比（环比）的**定点判据**（issue #6430）—— 无 DB、无 Spring。</b>
 *
 * <h2>为什么这一层必须存在（真库判据覆盖不到的那一半）</h2>
 * 真库判据（{@code SavingMetricsBoardRealDbTest}）证明的是「对比值 == 同期既有分组行的值」——
 * 它<b>只有本夹具那几个期间</b>，而下面这些形态在夹具里<b>根本长不出来</b>：
 * ① 不足两期；② 标度不同而数值相等（{@code 1.5} vs {@code 1.50}）；
 * ③ 期间序列里夹着 {@code null}（该期这个指标没数据）。⇒ 全在纯函数上定点判。
 *
 * <h2>判据（每条都在自己的形态上会红）</h2>
 * <ol>
 *   <li><b>不足两期</b>：{@code previousPeriod} / {@code previous} 为 {@code null} 且
 *       {@code verdict = "unknown"}（**不造 0** —— 没数据的月份不生成 0，否则「没采购」会被读成「采购下降」）；</li>
 *   <li><b>数值相等 ⇒ {@code "same"}</b>：含<b>标度不同</b>（{@code 1.5} vs {@code 1.50}）—— 用
 *       {@code compareTo}，不是 {@code equals}（{@code new BigDecimal("1.5").equals(new BigDecimal("1.50")) == false}）；</li>
 *   <li><b>三个方向</b>：省料 ↑better / 采购 ↓better / 米每㎡ ↓better（**方向不许反**，故三个都判）；</li>
 *   <li><b>{@code le0_2Share.verdict} 恒 {@code null}</b>：与 {@code "unknown"} **可区分**
 *       （断言 {@code isNull()}，不是 {@code isEqualTo("unknown")}）—— 它会被排料省料反向污染，有意不给好坏；</li>
 *   <li><b>{@code null} 值的期间不参与「相邻两期」的选择</b>：跳过它取更早的一期，**不是把它当 0**。</li>
 * </ol>
 */
@DisplayName("#6430 定点：相邻两期对比（期间选择 / same / 三向 verdict / le0_2Share 恒 null）")
class SavingMetricsComparisonTest {

    private static final String BETTER = "better";
    private static final String WORSE = "worse";
    private static final String SAME = "same";
    private static final String UNKNOWN = "unknown";

    /** 本期更好：升序取值。 */
    private static final String UP_BETTER = "up";
    /** 本期更好：降序取值。 */
    private static final String DOWN_BETTER = "down";
    /** 有意不给好坏（`le0_2Share`）。 */
    private static final String NO_VERDICT = "none";

    // ───────────────────────────────────────── 判据 1：不足两期

    @Test
    @DisplayName("🔴 判据1：一个期间都没有 ⇒ 前后皆 null + verdict=unknown（不造 0）")
    void noPeriodAtAllYieldsUnknownWithoutInventingZero() {
        SavingMetricViews.MetricDelta d =
                StockBatchConsumptionService.delta(List.<String[]>of(), UP_BETTER);

        assertThat(d.period()).as("本期也没有 ⇒ null（不得回落成 0 / 空串）").isNull();
        assertThat(d.current()).isNull();
        assertThat(d.previousPeriod()).isNull();
        assertThat(d.previous()).isNull();
        assertThat(d.verdict())
                .as("🔴 判不了 ⇒ \"unknown\"（与 le0_2Share 的**有意不给** null 是两个东西）")
                .isEqualTo(UNKNOWN);
    }

    @Test
    @DisplayName("🔴 判据1：只有一期 ⇒ previousPeriod/previous 为 null、verdict=unknown，current 仍是该期值")
    void singlePeriodHasNoPrevious() {
        SavingMetricViews.MetricDelta d = StockBatchConsumptionService.delta(
                List.<String[]>of(new String[]{"2026-09", "3.5"}), UP_BETTER);

        assertThat(d.period()).isEqualTo("2026-09");
        assertThat(d.current()).isEqualByComparingTo("3.5");
        assertThat(d.previousPeriod())
                .as("🔴 不足两期 ⇒ previousPeriod 为 null（不许回填成 0 或编一个期间）").isNull();
        assertThat(d.previous()).isNull();
        assertThat(d.verdict()).isEqualTo(UNKNOWN);
    }

    // ───────────────────────────────────────── 判据 2：same（含标度陷阱）

    @Test
    @DisplayName("🔴 判据2：current == previous（标度不同：1.5 vs 1.50）⇒ same —— compareTo 而非 equals")
    void equalValuesDespiteDifferentScaleAreSame() {
        // 判别性自证：这条断言就是「不能用 equals」的理由（equals 会在这里给 false）
        assertThat(new BigDecimal("1.5").equals(new BigDecimal("1.50")))
                .as("判别性对照：equals 在标度不同时为 false ⇒ 用它判等会把「没变」读成「变了」")
                .isFalse();

        SavingMetricViews.MetricDelta up = StockBatchConsumptionService.delta(
                List.of(new String[]{"2026-08", "1.50"}, new String[]{"2026-09", "1.5"}), UP_BETTER);
        assertThat(up.current()).isEqualByComparingTo("1.5");
        assertThat(up.previous()).isEqualByComparingTo("1.50");
        assertThat(up.verdict())
                .as("🔴 数值相等（标度不同）⇒ same —— 用 compareTo 判等，不是 equals")
                .isEqualTo(SAME);

        SavingMetricViews.MetricDelta down = StockBatchConsumptionService.delta(
                List.of(new String[]{"2026-08", "5.8000"}, new String[]{"2026-09", "5.8"}), DOWN_BETTER);
        assertThat(down.verdict()).as("降序方向同理：相等恒 same，与方向无关").isEqualTo(SAME);
    }

    // ───────────────────────────────────────── 判据 3：三个方向

    @Test
    @DisplayName("🔴 判据3：省料 ↑better（涨 = 变好）")
    void savingUpIsBetter() {
        SavingMetricViews.MetricDelta d = StockBatchConsumptionService.delta(
                List.of(new String[]{"2026-08", "10"}, new String[]{"2026-09", "12"}), UP_BETTER);
        assertThat(d.period()).isEqualTo("2026-09");
        assertThat(d.previousPeriod()).isEqualTo("2026-08");
        assertThat(d.verdict()).isEqualTo(BETTER);
    }

    @Test
    @DisplayName("🔴 判据3：采购 ↓better（涨 = 变差 —— 方向不许反）")
    void purchaseUpIsWorse() {
        SavingMetricViews.MetricDelta d = StockBatchConsumptionService.delta(
                List.of(new String[]{"2026-08", "10"}, new String[]{"2026-09", "15"}), DOWN_BETTER);
        assertThat(d.verdict()).as("买多了 = 变差").isEqualTo(WORSE);

        SavingMetricViews.MetricDelta less = StockBatchConsumptionService.delta(
                List.of(new String[]{"2026-08", "15"}, new String[]{"2026-09", "10"}), DOWN_BETTER);
        assertThat(less.verdict()).as("买少了 = better").isEqualTo(BETTER);
    }

    @Test
    @DisplayName("🔴 判据3：米每㎡ ↓better（单位产出用料降 = 变好）")
    void metersPerSquareMeterDownIsBetter() {
        SavingMetricViews.MetricDelta d = StockBatchConsumptionService.delta(
                List.of(new String[]{"2026-08", "0.9000"}, new String[]{"2026-09", "0.8276"}), DOWN_BETTER);
        assertThat(d.verdict()).isEqualTo(BETTER);
    }

    // ───────────────────────────────────────── 判据 4：le0_2Share 恒 null

    @Test
    @DisplayName("🔴 判据4：le0_2Share 的 verdict 恒 null（有意不给），且与 \"unknown\" 可区分")
    void le0_2ShareNeverGetsAVerdict() {
        // 即便数值一升一降、期数充足 —— verdict 仍然是 null（不是 better / worse / unknown）
        SavingMetricViews.MetricDelta worseLooking = StockBatchConsumptionService.delta(
                List.of(new String[]{"2026-08", "0.1000"}, new String[]{"2026-09", "0.5000"}), NO_VERDICT);
        assertThat(worseLooking.period()).as("期间与数值照常给出（不给的是**好坏**）").isEqualTo("2026-09");
        assertThat(worseLooking.current()).isEqualByComparingTo("0.5");
        assertThat(worseLooking.verdict())
                .as("🔴 恒 null（有意不给好坏）：它会被排料省料反向污染（排料省 ⇒ 批次剩更多 ⇒ 占比更差）")
                .isNull();
        assertThat(worseLooking.verdict())
                .as("🔴 null 与 \"unknown\" 是两个不同的东西：判不了才写 unknown")
                .isNotEqualTo(UNKNOWN);

        SavingMetricViews.MetricDelta downLooking = StockBatchConsumptionService.delta(
                List.of(new String[]{"2026-08", "0.5000"}, new String[]{"2026-09", "0.1000"}), NO_VERDICT);
        assertThat(downLooking.verdict()).as("另一个方向同样不给（不是「降了就写成 better」）").isNull();

        SavingMetricViews.MetricDelta tooFew = StockBatchConsumptionService.delta(
                List.<String[]>of(new String[]{"2026-09", "0.1000"}), NO_VERDICT);
        assertThat(tooFew.verdict())
                .as("🔴 缺值这一条**先于**「有意不给」生效 ⇒ 这里仍如实回 \"unknown\""
                        + "（「判不了」优先于「不表态」；只有判得了时才给 null）")
                .isEqualTo(UNKNOWN);
        assertThat(tooFew.verdict())
                .as("对照：\"unknown\" 是非 null ⇒ 与 le0_2Share 判得了时的 null 可区分")
                .isNotNull();
    }

    // ───────────────────────────────────────── 判据 5：null 期间不参与选择

    @Test
    @DisplayName("🔴 判据5：该指标为 null 的期间**不参与**相邻两期的选择（跳过它取更早的一期，不当 0）")
    void nullValuedPeriodsAreSkippedNotTreatedAsZero() {
        // 2026-09 这一期该指标没有数据（null）⇒ 相邻两期 = 2026-07 / 2026-08，不是 2026-08 / 2026-09
        SavingMetricViews.MetricDelta d = StockBatchConsumptionService.delta(List.of(
                new String[]{"2026-07", "10"},
                new String[]{"2026-08", "12"},
                new String[]{"2026-09", null}), UP_BETTER);

        assertThat(d.period())
                .as("🔴 本期 = 最后一个**有数据**的期间（2026-09 是 null ⇒ 跳过）").isEqualTo("2026-08");
        assertThat(d.previousPeriod()).isEqualTo("2026-07");
        assertThat(d.current()).isEqualByComparingTo("12");
        assertThat(d.previous()).isEqualByComparingTo("10");
        assertThat(d.verdict())
                .as("🔴 若把 null 当 0，这里会变成 12 vs 0 = better —— 而真相是「没有可比的两期」")
                .isEqualTo(BETTER);

        // 前面还有 null 的期间同理（跳过的逻辑不看位置）
        SavingMetricViews.MetricDelta withHole = StockBatchConsumptionService.delta(List.of(
                new String[]{"2026-06", null},
                new String[]{"2026-07", "10"},
                new String[]{"2026-08", "8"}), DOWN_BETTER);
        assertThat(withHole.period()).isEqualTo("2026-08");
        assertThat(withHole.previousPeriod()).as("夹在中间的 null 不参与").isEqualTo("2026-07");
        assertThat(withHole.verdict()).isEqualTo(BETTER);
    }

    @Test
    @DisplayName("🔴 判据5：期间按字典序排序取最后两个（与传入顺序无关）")
    void periodsAreSortedLexicographicallyNotByInputOrder() {
        SavingMetricViews.MetricDelta d = StockBatchConsumptionService.delta(List.of(
                new String[]{"2026-10", "7"},
                new String[]{"2026-08", "9"},
                new String[]{"2026-09", "8"}), UP_BETTER);
        assertThat(d.period()).as("字典序最大者 = 本期").isEqualTo("2026-10");
        assertThat(d.previousPeriod()).isEqualTo("2026-09");
        assertThat(d.previous()).isEqualByComparingTo("8");
        assertThat(d.verdict()).as("7 < 8 ⇒ 变差（升序口径）").isEqualTo(WORSE);
    }

    @Test
    @DisplayName("🔴 判据6：本期还没过完（period == 当前所在期间）⇒ verdict=partial，不给方向")
    void inProgressPeriodGetsPartialInsteadOfADirection() {
        // 同一份序列：把「当前所在期间」设成本期 ⇒ partial；设成更晚的期间 ⇒ 正常给方向
        // （注入式的当前期间 ⇒ 判据与「今天几号」解耦，不会下个月自己变红）
        List<String[]> series = List.of(
                new String[]{"2026-09", "100"},
                new String[]{"2026-10", "8"});

        SavingMetricViews.MetricDelta partial =
                StockBatchConsumptionService.delta(series, DOWN_BETTER, "2026-10");
        assertThat(partial.verdict())
                .as("本期（2026-10）还没过完 ⇒ 不给方向（半截月份比整月会把「还没进货」读成「买得更克制」）")
                .isEqualTo("partial");

        SavingMetricViews.MetricDelta done =
                StockBatchConsumptionService.delta(series, DOWN_BETTER, "2026-11");
        assertThat(done.verdict()).as("本期已过完 ⇒ 正常给方向（8 < 100，↓ better ⇒ better）").isEqualTo(BETTER);

        // 覆盖面：unknown（缺上期）与 null（有意不给）**都不许**被 partial 盖掉
        SavingMetricViews.MetricDelta unknown = StockBatchConsumptionService.delta(
                List.<String[]>of(new String[]{"2026-10", "8"}), DOWN_BETTER, "2026-10");
        assertThat(unknown.verdict()).as("判不了比「没过完」更具体 ⇒ 保持 unknown").isEqualTo(UNKNOWN);
        SavingMetricViews.MetricDelta noVerdict =
                StockBatchConsumptionService.delta(series, NO_VERDICT, "2026-10");
        assertThat(noVerdict.verdict()).as("有意不给（le0_2Share）⇒ 仍是 null，不被 partial 顶掉").isNull();
    }

    @Test
    @DisplayName("🔴 判据6c：行级序列按期间汇总 —— 同一期间的多行必须相加（否则相邻两期会是同一个月）")
    void rowsOfTheSamePeriodAreSummedIntoOneEntry() {
        List<String[]> series = StockBatchConsumptionService.aggregateByPeriod(List.of(
                new String[]{"2026-10", "7.3"},
                new String[]{"2026-10", "5.4"},      // 同月第二行（另一个来源组/物料）
                new String[]{"2026-09", "1.25"},
                new String[]{"2026-08", null}));      // 该期读不出 ⇒ 不进序列（不是当 0）

        assertThat(series).as("一期一行：2026-10 的两行合一条，2026-08 整条不进").hasSize(2);
        assertThat(series.get(0)[0]).isEqualTo("2026-10");
        assertThat(new BigDecimal(series.get(0)[1])).as("同月多行**相加**：7.3 + 5.4").isEqualByComparingTo("12.7");
        assertThat(series.get(1)[0]).isEqualTo("2026-09");

        // 判别性：汇总后再判环比 ⇒ 两期必不相同（修复前这里是 2026-10 → 2026-10）
        SavingMetricViews.MetricDelta d = StockBatchConsumptionService.delta(series, UP_BETTER, null);
        assertThat(d.period()).isEqualTo("2026-10");
        assertThat(d.previousPeriod())
                .as("🔴 相邻两期必须是**不同的期间**（修复前会取到同月的另一行 ⇒ 这条会红）")
                .isEqualTo("2026-09")
                .isNotEqualTo(d.period());
    }

    @Test
    @DisplayName("🔴 判据6b：当前所在期间的期间键与 SQL 的 to_char 同口径（月 / ISO 周历年）")
    void openPeriodMatchesSqlPeriodKeys() {
        assertThat(StockBatchConsumptionService.openPeriod("month", LocalDate.of(2026, 10, 6)))
                .isEqualTo("2026-10");
        // 2026-10-06 属 ISO 周 2026-W41（周一起算）
        assertThat(StockBatchConsumptionService.openPeriod("week", LocalDate.of(2026, 10, 6)))
                .isEqualTo("2026-W41");
        // 跨年周：2027-01-01 属 ISO 周 2026-W53 —— IYYY 是**周历年**，写成日历年就错一格
        assertThat(StockBatchConsumptionService.openPeriod("week", LocalDate.of(2027, 1, 1)))
                .isEqualTo("2026-W53");
    }
}
