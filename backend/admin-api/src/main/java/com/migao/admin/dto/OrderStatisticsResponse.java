package com.migao.admin.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * 订单统计响应 DTO
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class OrderStatisticsResponse {

    private long totalCount;
    private long pendingCount;
    private long confirmedCount;
    private long producingCount;
    private long shippedCount;
    private long completedCount;
    private long cancelledCount;
    private long unpaidCount;
    private long paidCount;
    private long refundedCount;
}
