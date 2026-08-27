package com.migao.admin.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.math.BigDecimal;
import java.time.OffsetDateTime;

/**
 * 应收对账响应 DTO（订单维度）
 *
 * <p>对账口径：difference = 应收（receivableAmount） - 实收（receivedAmount） + 已退（refundAmount）。
 * difference > 0 表示净应收未完全收回，< 0 表示多收，= 0 表示已对平。
 * 已退款金额计入差额，退款订单的差额不应显示 0。</p>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class ReceivableReconciliationResponse {

    private String orderId;

    private String orderNo;

    private String customerName;

    private String customerPhone;

    /** 订单状态 */
    private String status;

    /** 应收金额 = totalAmount */
    private BigDecimal receivableAmount;

    /** 实收金额 = actualAmount */
    private BigDecimal receivedAmount;

    /** 已退金额 = 该订单退款流水合计 */
    private BigDecimal refundAmount;

    /** 差额 = 应收 - 实收 + 已退（净应收口径） */
    private BigDecimal difference;

    private OffsetDateTime createdAt;
}
