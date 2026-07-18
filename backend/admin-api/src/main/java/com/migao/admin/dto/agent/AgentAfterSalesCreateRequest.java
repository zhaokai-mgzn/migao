package com.migao.admin.dto.agent;

import lombok.Data;

import java.math.BigDecimal;
import java.util.List;

/**
 * Agent 专用售后工单创建请求。
 * orderId 可传 UUID 或订单号（ORD-xxx），服务端自动解析。
 */
@Data
public class AgentAfterSalesCreateRequest {

    /** 关联订单 ID（可为 UUID 或 ORD-xxx） */
    private String orderId;

    /** 工单类型：refund / exchange / repair / complaint / other */
    private String ticketType;

    /** 原因说明（必填） */
    private String reason;

    /** 详细描述（可选） */
    private String description;

    /** 凭证图片 URL 列表（可选） */
    private List<String> images;

    /** 优先级（可选，默认 normal） */
    private String priority;

    /** 退款金额（退款类型时可选） */
    private BigDecimal refundAmount;
}
