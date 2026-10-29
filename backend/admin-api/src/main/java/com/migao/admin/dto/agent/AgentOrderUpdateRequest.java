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

    /**
     * 物流类型（update_logistics 时可选，issue #8080）：{@code express} 快递 / {@code logistics} 物流专线。
     *
     * <p>缺省（null / 空白）⇒ <b>不覆盖</b>：写面 {@code OrderLogisticsWriter} 的既有语义是
     * 「新建写入、更新仅在显式非空时覆盖」—— 只改运单号/纠错不该把客户已记录的「物流专线」
     * 静默改回快递。取值的白名单由智能体侧工具 schema / 校验闸门保证（与表单路径
     * {@code PUT /api/admin/orders/{id}/logistics} 同口径，本 DTO 不做二次校验）。</p>
     */
    private String logisticsType;

    /** 取消/关闭原因（cancel 时可选） */
    private String cancelReason;

    /** 退款金额（refund 时可选） */
    private BigDecimal refundAmount;

    /** 退款原因（refund 时可选） */
    private String refundReason;
}
