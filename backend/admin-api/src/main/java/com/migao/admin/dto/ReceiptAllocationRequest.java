package com.migao.admin.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.math.BigDecimal;
import java.util.List;

/**
 * 核销请求（issue #7370 段 3）：`POST /api/admin/finance/receipts/{transactionId}/allocations`。
 *
 * <p>一次可提交多行（一笔钱同时冲几张单是常态）。每一行都过 {@code ReceiptAllocationPolicy} 的双上限：
 * 收款剩余（流水金额 − 已核销）与订单剩余（货值 − 退款 − 已核销）。</p>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class ReceiptAllocationRequest {

    /** 核销明细（至少一行；空列表 = 400，不是「不核销」的合法表达） */
    private List<Line> lines;

    /** 单行：冲到哪张订单、多少钱。 */
    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class Line {
        private String orderId;
        private BigDecimal amount;
    }
}
