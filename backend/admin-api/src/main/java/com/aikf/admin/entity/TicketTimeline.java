package com.aikf.admin.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.OffsetDateTime;

/**
 * 工单处理时间线实体类
 * 对应表：ticket_timeline
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName(value = "ticket_timeline", autoResultMap = true)
public class TicketTimeline {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    private String ticketId;

    /** created / assigned / processed / notified / confirmed / closed / rejected */
    private String action;

    private String actorId;

    /** agent / system / customer */
    private String actorType;

    @TableField(typeHandler = com.baomidou.mybatisplus.extension.handlers.JacksonTypeHandler.class)
    private Object content;

    @TableField(fill = FieldFill.INSERT)
    private OffsetDateTime createdAt;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private OffsetDateTime updatedAt;
}
