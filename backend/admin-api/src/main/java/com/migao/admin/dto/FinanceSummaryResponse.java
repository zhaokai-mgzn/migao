package com.migao.admin.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.math.BigDecimal;
import java.util.List;

/**
 * 财务对账汇总响应 DTO
 *
 * <p>收入/退款/净收入基于资金流水（finance_transactions）按时间范围聚合；
 * pendingReceivable（待收款）基于订单维度的应收-实收差额，为累计余额。</p>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class FinanceSummaryResponse {

    private String startDate;

    private String endDate;

    /** 本期总收入 */
    private BigDecimal totalIncome;

    /** 本期总退款 */
    private BigDecimal totalRefund;

    /** 净收入 = 收入 - 退款 */
    private BigDecimal netIncome;

    /** 收款笔数 */
    private Long incomeCount;

    /** 退款笔数 */
    private Long refundCount;

    /** 待收款（累计未收差额，订单维度） */
    private BigDecimal pendingReceivable;

    /** 按支付方式汇总 */
    private List<MethodSummary> byPaymentMethod;

    /** 按日趋势 */
    private List<DailySummary> dailyTrend;

    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class MethodSummary {
        private String paymentMethod;
        private BigDecimal income;
        private BigDecimal refund;
        private BigDecimal net;
    }

    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class DailySummary {
        private String date;
        private BigDecimal income;
        private BigDecimal refund;
        private BigDecimal net;
    }
}
