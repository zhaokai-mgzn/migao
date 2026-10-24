package com.migao.admin.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.math.BigDecimal;
import java.util.List;

/**
 * 核销读面（issue #7370 段 3）：一笔收款**还剩多少没核销** + 已核销明细。
 *
 * <p>恒等式（判据复算）：{@code allocated == Σ lines[].amount}，{@code unallocated == transactionAmount − allocated}
 * —— 差额是**预收 / 待勾对**（先付后货的合法状态），不是错误。</p>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class ReceiptAllocationView {

    private String transactionId;

    private String transactionNo;

    /** 收款金额（现金真值源 = finance_transactions.amount） */
    private BigDecimal transactionAmount;

    /** 已核销合计 */
    private BigDecimal allocated;

    /** 未核销（= 收款金额 − 已核销）：预收 / 待勾对 */
    private BigDecimal unallocated;

    private List<Line> lines;

    /** 一行核销（订单 + 金额 + 该单当前余额）。 */
    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class Line {
        private String id;
        private String orderId;
        private String orderNo;
        /** 本行核销金额 */
        private BigDecimal amount;
        /** 该单当前剩余应收（货值 − 退款 − 已核销），供前端提示「还能冲多少」 */
        private BigDecimal orderOutstanding;
    }
}
