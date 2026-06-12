package com.migao.admin.dto;

import lombok.Data;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.List;

/**
 * 售后工单列表响应 DTO
 * 对齐前端 AfterSalesTicket 类型
 */
@Data
public class AfterSalesListResponse {

    private String id;
    private String ticketNo;
    private String orderId;
    private String orderNo;
    private String customerId;
    private String customerName;
    private String customerPhone;
    private String ticketType;
    private String status;
    private String description;
    private List<String> images;
    private String source;
    private String priority;
    private String handlerId;
    private String handlerName;
    private OffsetDateTime assignedAt;
    private BigDecimal refundAmount;
    private String refundMethod;
    private List<String> evidenceImages;
    private String internalNotes;
    private OffsetDateTime deadline;
    private OffsetDateTime closedAt;
    private String closeReason;
    private OffsetDateTime createdAt;
    private OffsetDateTime updatedAt;
}
