package com.migao.admin.entity;

import com.baomidou.mybatisplus.annotation.*;
import com.baomidou.mybatisplus.extension.handlers.JacksonTypeHandler;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.LocalDate;
import java.time.OffsetDateTime;

/**
 * 加工单实体（issue #3340）
 * 对应表：processing_orders —— 订单 producing 阶段的子进度。
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName(value = "processing_orders", autoResultMap = true)
public class ProcessingOrder {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    private String orderId;

    /** 业务单号 JG-YYYYMMDD-序号（DB 唯一约束防重号） */
    private String processingOrderNo;

    /** 加工方（文本，MVP 不建主数据） */
    private String processor;

    /** 交期（手工填写，决策 3） */
    private LocalDate expectedDeliveryDate;

    /** generated/issued/in_processing/completed/cancelled */
    private String status;

    /** 生成时快照：不含销售价（决策 2），加工项含 options */
    @TableField(typeHandler = JacksonTypeHandler.class)
    private Object itemsSnapshot;

    private String remark;

    private Integer templateVersion;

    private String generatedBy;

    private OffsetDateTime generatedAt;

    private OffsetDateTime issuedAt;

    private OffsetDateTime inProcessingAt;

    private OffsetDateTime completedAt;

    private OffsetDateTime cancelledAt;

    private String cancelledReason;

    private Integer printCount;

    @TableField(fill = FieldFill.INSERT)
    private OffsetDateTime createdAt;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private OffsetDateTime updatedAt;

    private Integer deleted;
}
