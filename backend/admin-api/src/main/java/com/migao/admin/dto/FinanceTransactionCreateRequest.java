package com.migao.admin.dto;

import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import lombok.Data;

import java.math.BigDecimal;

/**
 * 资金流水登记请求 DTO（手动登记线下收款/退款）
 */
@Data
public class FinanceTransactionCreateRequest {

    /** 收支类型：income=收款 / refund=退款 */
    @NotBlank(message = "收支类型不能为空")
    private String type;

    /** 金额（正数） */
    @NotNull(message = "金额不能为空")
    @DecimalMin(value = "0.01", message = "金额必须大于 0")
    private BigDecimal amount;

    /** 支付方式：wechat / alipay / bank_transfer / cash / other */
    private String paymentMethod;

    /** 关联订单 UUID 或订单号（可选） */
    private String orderId;

    /** 交易发生时间（ISO-8601，可选；缺省为当前时间） */
    private String occurredAt;

    private String remark;
}
