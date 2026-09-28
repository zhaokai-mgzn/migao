package com.migao.admin.dto;

import com.migao.admin.time.BusinessClock;
import java.math.BigDecimal;
import java.util.List;

/**
 * 省料度量 L2/L3 的汇总读面（issue #5159；L1 逐单落账见 #5158 / V119）。
 *
 * <h2>三层度量的分工（本类只负责 L2/L3 的**读面**）</h2>
 * <ul>
 *   <li><b>L1 逐单反事实</b>（已落地，{@code stock_batch_consumptions} 的
 *       {@code formula_meters} / {@code planned_meters} / {@code unit_cost}）—— 逐单可审计；</li>
 *   <li><b>L2 批次结构性</b>（{@link Board}）—— 剩余量四档 {@code ≤0.2m / 0.2~0.5 / 0.5~1 / >1}
 *       按<b>物料（商品 × 颜色 × 门幅）× 时间</b>聚合，并按<b>来源组</b>分开；</li>
 *   <li><b>L3 采购/财务口径</b>（{@link Trend}）—— <b>单位产出的面料消耗</b>（米/㎡、元/㎡）
 *       按周/月聚合，只做趋势、不逐单。</li>
 * </ul>
 *
 * <h2>🔴 两条指标必须并用（#5144 已锁，本读面同时给出）</h2>
 * <ol>
 *   <li><b>剩余 ≤0.2m 的批次占比 ↑</b>（治「用不尽」）—— {@link CohortSummary#le0_2Share()}
 *       / {@link BatchGroup#le0_2Share()}；</li>
 *   <li><b>入库/采购总米数 ↓</b>（治「买太多」）—— {@link ConsumptionPoint#purchasedMeters()}。</li>
 * </ol>
 * <b>单看①会被 A 类排料误导</b>：排料省料 ⇒ 批次<b>剩得更多</b> ⇒ 只留①会把效率提升<b>显示成变差</b>。
 * ⇒ 本读面**同时**回两条，页面**同时**渲染两条（判据 3 的落点；缺任一条 ⇒ 红）。
 *
 * <h2>🔴 存量导入批次必须单列成组（判据 2）</h2>
 * {@code inbound_orders.source = 'opening'} 的那批 = <b>切换前的历史包袱</b>（口径由 #5145 / #5149 锁定）。
 * 混进「切换后」的分子分母 ⇒ <b>改善永远看不出来</b>（历史包袱的余量结构天然更差）。
 * ⇒ 本读面的每一个聚合都以 {@link #COHORT_OPENING} 为<b>独立分组键</b>，
 * 且 {@link Board#cohorts()} <b>恒含</b>该组（哪怕它今天为空）—— 「没有这一组」与「这一组是空的」
 * 必须可区分（后者显示「无数据」，不是抹掉）。
 *
 * <h2>🔴 空数据不冒充 0（判据 4）</h2>
 * 所有<b>比率与合计</b>字段在「无数据」时为 {@code null}，**不回落成 0**
 * （0 会被读成「没有浪费」）。判据落点：{@code denominator = 0} ⇒ 比率 {@code null}；
 * 某组没有任何一行 ⇒ 合计 {@code null}。计数类字段（批次数 / 行数）保留 0 —— 计数为 0 是**事实**，
 * 与「比值读不出」是两件事。
 */
public final class SavingMetricViews {

    private SavingMetricViews() {
    }

    /** 切换后（采购 / 正常入库）—— 分母不许混进存量。 */
    public static final String COHORT_PURCHASE = "purchase";
    /** 存量导入（期初建账，{@code inbound_orders.source = 'opening'}）= 切换前的历史包袱，**单列**。 */
    public static final String COHORT_OPENING = "opening";
    /**
     * 来源未知（批次行没有入库单来源）。
     *
     * <p>本仓批次只由入库过账产生 ⇒ 现实上应为空；**单列而不并入 {@link #COHORT_PURCHASE}**：
     * 把「不知道从哪来的批次」算进「切换后采购」会让②（采购总米数）虚高，而账面上看不出。</p>
     */
    public static final String COHORT_UNKNOWN = "unknown";

    /** 分组口径的固定顺序（页面按此顺序渲染；`opening` 恒在，判据 2）。 */
    public static final List<String> COHORTS = List.of(COHORT_PURCHASE, COHORT_OPENING, COHORT_UNKNOWN);

    /** 时间粒度：按月（{@code YYYY-MM}）。 */
    public static final String GRANULARITY_MONTH = "month";
    /** 时间粒度：按周（ISO 周，{@code IYYY-"W"IW}，如 {@code 2026-W39}）。 */
    public static final String GRANULARITY_WEEK = "week";

    /** 时区口径（与 {@code application.yml} 的 {@code spring.jackson.time-zone} 同源）。 */
    public static final String TIMEZONE = BusinessClock.BUSINESS_ZONE.getId();

    /** 剩余量一档（{@code key} 机器可判、{@code label} 给人看）。 */
    public record Bucket(String key, String label, int batchCount, BigDecimal share,
                         BigDecimal remainingMeters) {
    }

    /**
     * L2 批次分档聚合组：<b>（时间桶 × 来源组 × 物料）</b>。
     *
     * <p>{@code period} = 批次<b>收货月份</b>（{@code stock_batches.received_date}；未记日期 ⇒ {@code null}，
     * 页面渲染「未记收货日期」——<b>不猜</b>）。</p>
     *
     * <p>{@code le0_2Share} = <b>指标①</b>（本组「剩余 ≤0.2m」的批次占比）；
     * {@code batchCount == 0} ⇒ {@code null}（无数据，不是 0）。</p>
     */
    public record BatchGroup(String period, String cohort, String cohortLabel, boolean opening,
                             String materialKey, String productId, String skuCode,
                             int batchCount, int le0_2Count, BigDecimal le0_2Share,
                             BigDecimal remainingMeters, List<Bucket> buckets) {
    }

    /**
     * L1 汇总（逐单省料的**分组聚合**）：<b>（消耗时间桶 × 来源组 × 物料）</b>。
     *
     * <p>🔴 {@code savedMeters} / {@code savedAmount} 与「逐单读面」
     * （{@code GET /api/admin/batch-stock/consumptions} 逐行 {@code savedMeters} / {@code savedAmount} 求和）
     * <b>逐值相等</b>（判据 1）—— 两条路聚合的是同一批行、同一列族，不许是两套口径。
     * 金额腿在 SQL 里就按<b>逐行</b> {@code ROUND(…, 2)} 再求和，与实体的
     * {@code getSavedAmount()}（{@code setScale(2, HALF_UP)}）逐值一致；
     * 「先整段求和再取整」会与逐单口径差几分钱 —— 那就是两套口径。</p>
     *
     * <p>{@code savedAmount} 只含 <b>{@code unit_cost} 有值</b>的行；{@code unknownCostLines} 显式回
     * 「有几行读不出金额」（V119 之前的历史行均价未知，一律不回填、不猜）
     * ⇒ 读的人不会把「部分行没有均价」误读成「只省了这么点钱」。
     * {@code lineCount == 0} ⇒ 两个合计均为 {@code null}（无数据）。</p>
     */
    public record SavedGroup(String period, String cohort, String cohortLabel, boolean opening,
                             String materialKey, String productId, String skuCode,
                             BigDecimal formulaMeters, BigDecimal plannedMeters, BigDecimal savedMeters,
                             BigDecimal savedAmount, int lineCount, int unknownCostLines) {
    }

    /**
     * 一个来源组的汇总卡（页面顶部两张卡 = ① 指标 + 该组省料合计）。
     *
     * <p>🔴 {@code opening == true} 的那张 = <b>存量导入</b>，与「切换后」<b>并列而不是相加</b>
     * （判据 2：混入 ⇒ 红）。</p>
     */
    public record CohortSummary(String cohort, String cohortLabel, boolean opening,
                                int batchCount, int le0_2Count, BigDecimal le0_2Share,
                                BigDecimal remainingMeters,
                                BigDecimal savedMeters, BigDecimal savedAmount,
                                int lineCount, int unknownCostLines, List<Bucket> buckets) {
    }

    /**
     * L2 看板（+ L1 的分组汇总）。
     *
     * @param granularity 时间粒度（{@link #GRANULARITY_MONTH} / {@link #GRANULARITY_WEEK}）
     * @param timezone    时间口径（{@link #TIMEZONE}）—— 显式回给读的人，避免「这是 UTC 还是本地」的猜测
     * @param cohorts     来源组汇总（**恒含** {@link #COHORT_OPENING} 一行；判据 2）
     * @param batchGroups L2 批次分档聚合（时间 × 来源 × 物料）
     * @param savedGroups L1 逐单省料的分组聚合（时间 × 来源 × 物料）
     * @param total      全租户合计（= 各 {@code cohorts} 之和；判据 1 的对照读数）
     */
    public record Board(String granularity, String timezone,
                        List<CohortSummary> cohorts,
                        List<BatchGroup> batchGroups,
                        List<SavedGroup> savedGroups,
                        Total total) {
    }

    /**
     * 来源原值（{@code inbound_orders.source}）→ 分组键。
     *
     * <p><b>唯一映射处</b>：任何地方再写一份「是不是存量」的判断，就是第二份会漂的口径
     * （漂移的表现 = 看板把存量算进切换后，而改善**永远看不出来** —— 判据 2 的红证形态）。</p>
     *
     * @param source {@code purchase} / {@code opening}；{@code null}/其它 ⇒ {@link #COHORT_UNKNOWN}
     *               （**不回落成 purchase**：来源不明不等于「这是切换后的采购」）
     */
    public static String cohortOf(String source) {
        if (COHORT_OPENING.equals(source)) {
            return COHORT_OPENING;
        }
        return COHORT_PURCHASE.equals(source) ? COHORT_PURCHASE : COHORT_UNKNOWN;
    }

    /** 分组键 → 给人看的标签（页面上「存量单列」那张卡就靠它，不是前端各写一份文案）。 */
    public static String cohortLabel(String cohort) {
        return switch (cohort) {
            case COHORT_PURCHASE -> "切换后（采购入库）";
            case COHORT_OPENING -> "存量导入（切换前历史包袱）";
            default -> "来源未知";
        };
    }

    /** 与 {@code ProcessingOrderService.materialKey} 同口径的物料键（商品 × 颜色 × 门幅）。 */
    public static String materialKeyOf(String productId, String skuCode) {
        return (productId == null ? "" : productId) + "|" + (skuCode == null ? "" : skuCode);
    }

    /**
     * L3 趋势的一个时间点（**采购/财务口径**，不做逐单）。
     *
     * <p>{@code purchasedMeters} = <b>指标②</b>（入库/采购总米数），**只含** {@link #COHORT_PURCHASE}；
     * {@code openingMeters} = 存量导入的入库米数，<b>单列</b>（判据 2：它不是「这个月的采购」，
     * 是切换前的历史包袱；混进来 ⇒ ②永远被历史量压着，改善看不出来）。</p>
     *
     * <p>{@code outputAreaM2} = 分母：同期派工明细覆盖的<b>窗户面积</b>（{@code Σ 窗宽 × 窗高}，㎡）——
     * 口径 = 「这批派工单实际做出的东西有多大」，与分子<b>同源同集</b>（同一批扣减行的订单明细行）。
     * 分母为 0 / 无数据 ⇒ {@code metersPerM2} 为 {@code null}（判据 4）。</p>
     *
     * <p>⚠️ 分母口径的取舍（照实登记）：窗户面积<b>跨品类不可比</b>
     * （纱帘 / 遮光布 / 工程单单位面积用料天然不同）⇒ 只做<b>同物料/同期的趋势</b>，
     * 不做「全店一个数」的横比。口径与残余风险见本单 PR body「残余风险」节。</p>
     */
    public record ConsumptionPoint(String period,
                                   BigDecimal purchasedMeters,
                                   BigDecimal openingMeters,
                                   BigDecimal consumedMeters,
                                   BigDecimal outputAreaM2,
                                   BigDecimal metersPerM2,
                                   int outputLines) {
    }

    /**
     * 全租户合计（= 各 {@link CohortSummary} 之和，判据 1 的对照读数）。
     *
     * <p>两个米数口径都<b>跨来源组</b>（合计就是合计），来源维度的拆分在 {@link Board#cohorts()} /
     * {@link Board#batchGroups()} 里逐组给出 —— 合计里再分一次会与分组两处各算一份。</p>
     */
    public record Total(BigDecimal formulaMeters, BigDecimal plannedMeters, BigDecimal savedMeters,
                        BigDecimal savedAmount, int lineCount, int unknownCostLines,
                        int batchCount, int le0_2Count, BigDecimal le0_2Share) {
    }

    /**
     * L3 趋势读面（按周/月）。
     *
     * <p>{@code purchasedTotalMeters} / {@code consumedTotalMeters} = 全期合计（采购腿同样只含
     * {@link #COHORT_PURCHASE}）；{@code openingTotalMeters} 单列（判据 2）。无数据的腿为 {@code null}。</p>
     */
    public record Trend(String granularity, String timezone, List<ConsumptionPoint> points,
                        BigDecimal purchasedTotalMeters, BigDecimal consumedTotalMeters,
                        BigDecimal openingTotalMeters) {
    }
}
