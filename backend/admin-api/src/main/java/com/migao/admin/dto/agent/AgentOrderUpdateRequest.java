package com.migao.admin.dto.agent;

import lombok.Data;

import java.math.BigDecimal;

/**
 * Agent 专用订单更新请求（统一 PATCH 端点）。
 * ID 可传 UUID 或订单号（ORD-xxx），服务端自动解析。
 */
@Data
public class AgentOrderUpdateRequest {

    /**
     * 操作类型：
     * - update_status：更新订单状态
     * - update_logistics：更新物流信息
     * - confirm_payment：确认支付
     * - cancel：取消订单
     * - refund：退款
     */
    private String action;

    /** 目标状态（update_status 时必填） */
    private String status;

    /** 快递公司（update_logistics 时必填） */
    private String logisticsCompany;

    /** 运单号（update_logistics 时必填） */
    private String trackingNumber;

    /** 取消/关闭原因（cancel 时可选） */
    private String cancelReason;

    /** 退款金额（refund 时可选） */
    private BigDecimal refundAmount;

    /** 退款原因（refund 时可选） */
    private String refundReason;
}
