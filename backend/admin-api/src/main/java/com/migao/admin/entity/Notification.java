package com.migao.admin.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.OffsetDateTime;

/**
 * 通知记录实体类
 * 对应表：notifications
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName("notifications")
public class Notification {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    private String ruleId;

    private String templateId;

    private String recipientId;

    /** user / employee */
    private String recipientType;

    private String channel;

    private String title;

    private String content;

    /** pending / sent / failed / read */
    private String status;

    private OffsetDateTime sentAt;

    private OffsetDateTime readAt;

    private String errorMessage;

    private Integer retryCount;

    @TableField(fill = FieldFill.INSERT)
    private OffsetDateTime createdAt;
}
