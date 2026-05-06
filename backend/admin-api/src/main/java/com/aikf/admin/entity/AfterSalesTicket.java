package com.aikf.admin.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.math.BigDecimal;
import java.time.OffsetDateTime;

/**
 * 售后工单实体类
 * 对应表：after_sales_tickets
 * 说明：包含 001_init.sql 基础字段 + 002_complete_tables.sql 扩展字段
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName(value = "after_sales_tickets", autoResultMap = true)
public class AfterSalesTicket {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    private String orderId;

    private String customerId;

    /** return / exchange / repair / complaint */
    private String ticketType;

    /** pending / processing / resolved / rejected / closed */
    private String status;

    private String description;

    @TableField(typeHandler = com.baomidou.mybatisplus.extension.handlers.JacksonTypeHandler.class)
    private Object images;

    // --- 002 扩展字段 ---
    private String ticketNo;

    /** customer / agent */
    private String source;

    /** normal / urgent / critical */
    private String priority;

    private String handlerId;

    private OffsetDateTime assignedAt;

    private BigDecimal refundAmount;

    /** original_route / bank_transfer / balance */
    private String refundMethod;

    @TableField(typeHandler = com.baomidou.mybatisplus.extension.handlers.JacksonTypeHandler.class)
    private Object evidenceImages;

    private String internalNotes;

    private OffsetDateTime deadline;

    private OffsetDateTime closedAt;

    private String closeReason;

    @TableField(fill = FieldFill.INSERT)
    private OffsetDateTime createdAt;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private OffsetDateTime updatedAt;

    @TableLogic
    private Integer deleted;
}
