package com.migao.admin.service;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;

/**
 * 质量成本的**构成与恒等式**（issue #7377，P1-5 段 1）—— 纯函数。
 *
 * <h3>质量成本 = 返工工时 + 报废工时 + 报废料 + 赔付（四项分列，不合并成一个黑盒数）</h3>
 * <p>合并成一个数最省事，但读者无法判断「这个月质量成本高」到底是返工多、报废多还是赔得多 ——
 * 三种成因对应三种完全不同的处置。所以报表必须分列，且**每一项都要自述已知/未知**。</p>
 *
 * <h3>🔴 未知不进合计，但必须被数出来</h3>
 * <ul>
 *   <li><b>返工工时</b>：`production_work_logs.work_type='rework'` × 单价快照；`price_state='unpriced'`
 *       的行**不计金额**（那是「没定价」，不是「0 元工时」）⇒ 该项标「部分未知」并给出未定价行数；</li>
 *   <li><b>报废工时</b>（issue #7377 段 8）：`production_work_logs.work_type='scrap'` × 单价快照 ——
 *       与返工同一张表、同一套定价字段 ⇒ **可采集**；窗口内一条报废报工都没有 ⇒ 未知（未发生 ≠ 0）；</li>
 *   <li><b>报废料</b>（物料成本）：本仓**没有**质检记录 → 批次的关联（`quality_inspections` 只到成品帘级）
 *       ⇒ 这一项**仍未采集**，恒为未知（不是 0！填 0 会被读成「本月没有报废损失」）。
 *       注意：报废**工时**可采不等于报废**料**可采，两者别混为一谈；</li>
 *   <li><b>赔付</b>：按订单退款流水口径（`finance_transactions` 无售后单关联列 ⇒ 无法按售后单归集），
 *       报表要注明这个口径差异。</li>
 * </ul>
 */
public final class QualityCostPolicy {

    /** 单个成本分项：金额（未知 ⇒ null）+ 是否已知 + 口径说明。 */
    public record Component(String code, String label, BigDecimal amount, boolean known,
                            String note, int unknownItems) {
    }

    /**
     * @param reworkAmount   返工工时金额（null = 完全未知）
     * @param reworkUnpriced 未定价的返工报工行数（> 0 ⇒ 该项「部分未知」）
     */
    public static Component reworkCost(BigDecimal reworkAmount, int reworkUnpriced) {
        boolean known = reworkAmount != null && reworkUnpriced == 0;
        return new Component("rework_labor", "返工工时",
                known ? scale(reworkAmount) : null, known,
                known ? "按返工报工 × 工序单价快照汇总"
                        : "有未定价的返工报工，金额不计入（未定价 ≠ 0 元）",
                reworkUnpriced);
    }

    /**
     * 报废**工时**（issue #7377 段 8）：报工三态里的 `scrap` × 工序单价快照。
     *
     * @param scrapAmount   报废工时金额（null = 完全未知）
     * @param scrapUnpriced 未定价的报废报工行数（> 0 ⇒ 该项「部分未知」）
     * @param hasScrap      窗口内是否有报废报工（false ⇒ 未知，不是「没报废」）
     */
    public static Component scrapLabor(BigDecimal scrapAmount, int scrapUnpriced, boolean hasScrap) {
        boolean known = hasScrap && scrapAmount != null && scrapUnpriced == 0;
        return new Component("scrap_labor", "报废工时",
                known ? scale(scrapAmount) : null, known,
                known ? "按报废报工（work_type=scrap）× 工序单价快照汇总"
                        : scrapUnpriced > 0 ? "有未定价的报废报工，金额不计入（未定价 ≠ 0 元）"
                        : "窗口内没有报废报工（未发生，不等于报废为 0）",
                scrapUnpriced);
    }

    /** 报废**料**成本：本仓未采集（无质检记录→批次关联），**恒未知**。 */
    public static Component scrapCost() {
        return new Component("scrap_material", "报废料", null, false,
                "本仓未采集：质检记录只到成品帘级，没有到批次 → 无法折算料成本（不填 0）", -1);
    }

    /**
     * @param refundAmount 按订单退款口径汇总的赔付金额
     * @param hasRefunds   是否命中退款流水（false ⇒ 未知，不是「没赔付」）
     */
    public static Component compensation(BigDecimal refundAmount, boolean hasRefunds) {
        return new Component("compensation", "赔付（退款口径）",
                hasRefunds ? scale(refundAmount) : null, hasRefunds,
                hasRefunds ? "按订单退款流水汇总（本仓无售后单→流水关联，故不是售后单维度）"
                        : "窗口内没有退款流水（未发生，不等于赔付为 0 的结论可复算）",
                0);
    }

    /**
     * 合计：**只累加已知项**；任一未知 ⇒ {@code complete=false}，并列出未知分项。
     *
     * <p>恒等式（判据复算）：{@code total == Σ(known components)}；{@code complete == (未知分项为空)}。</p>
     */
    public record Total(BigDecimal amount, boolean complete, List<String> unknownComponents) {
    }

    public static Total total(List<Component> components) {
        BigDecimal sum = BigDecimal.ZERO;
        List<String> unknown = new ArrayList<>();
        boolean any = false;
        for (Component component : components) {
            if (component == null) {
                continue;
            }
            if (component.known() && component.amount() != null) {
                sum = sum.add(component.amount());
                any = true;
            } else {
                unknown.add(component.code());
            }
        }
        return new Total(any ? scale(sum) : null, unknown.isEmpty(), unknown);
    }

    private static BigDecimal scale(BigDecimal value) {
        return value.setScale(2, java.math.RoundingMode.HALF_UP);
    }

    private QualityCostPolicy() {
    }
}
