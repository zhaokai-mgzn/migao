package com.migao.admin.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;

/**
 * 应收账龄**报表**读面（issue #7376 段 5，P1-4）：把 P0-2 的账龄真值源套进报表中心四条口径。
 *
 * <p>与 {@link ReceivableAgingResponse}（客户档案里的账龄页）**同一份底稿**：五档与按客户分行
 * 都是 {@code ReceivableAging.summarize} 的产物，本类只加报表侧的三件事：</p>
 *
 * <ol>
 *   <li><b>空数据 ≠ 0</b>：没有欠款单时 {@code hasData=false}、{@code totals=null} ——
 *       前端据此写「暂无数据」，而不是把「没有应收」画成「应收 0.00」；</li>
 *   <li><b>合计 = 明细之和</b>：{@code totals.outstanding} 直接取纯函数给的
 *       {@code totalOutstanding}（= Σ五档 = Σ客户行，恒等式由 {@code ReceivableAging} 承担）；</li>
 *   <li><b>客户数 / 单数单列</b>：报表要能回答「多少家在欠、多少张单」——这两个数不是金额，
 *       折进合计里就再也读不出来了。</li>
 * </ol>
 *
 * <p>⚠️ 本读面**不裁金额精度**：底稿已按两位小数 {@code HALF_UP} 落数，这里不再动。</p>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class ReceivableAgingReportView {

    /** 业务「今天」（分档基准，回显给前端 —— 两边各算一次必然差在跨日那一刻）。 */
    private LocalDate asOf;

    /** 有没有欠款单（{@code false} ⇒ {@code totals} 必为 {@code null}，页面写「暂无数据」）。 */
    private boolean hasData;

    /** 有欠款的客户数（不是订单数）。 */
    private int customerCount;

    /** 全局五档（顺序 = 上屏顺序：未到期 → 1-30 → 31-60 → 61-90 → 90+）。 */
    private List<ReceivableAgingResponse.BucketAmount> buckets;

    /** 按客户分行（金额倒序）。 */
    private List<ReceivableAgingResponse.CustomerAging> customers;

    /** 合计；{@code hasData=false} 时为 {@code null}（**不是 0**）。 */
    private Totals totals;

    /** 报表合计：应收 / 逾期 / 涉及单数。 */
    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class Totals {
        private BigDecimal outstanding;
        private BigDecimal overdue;
        private int orderCount;
    }
}
