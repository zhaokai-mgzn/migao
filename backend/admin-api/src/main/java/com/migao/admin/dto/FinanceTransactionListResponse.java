package com.migao.admin.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.math.BigDecimal;
import java.time.OffsetDateTime;

/**
 * 资金流水列表响应 DTO
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class FinanceTransactionListResponse {

    private String id;

    private String transactionNo;

    private String orderId;

    private String orderNo;

    /** income / refund */
    private String type;

    private BigDecimal amount;

    private String paymentMethod;

    /** pending / success / failed */
    private String status;

    private String operator;

    private OffsetDateTime occurredAt;

    private String remark;

    private OffsetDateTime createdAt;
}
