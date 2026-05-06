package com.aikf.admin.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.OffsetDateTime;

/**
 * 通知规则实体类
 * 对应表：notification_rules
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName("notification_rules")
public class NotificationRule {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    /** ticket_assigned / ticket_status_changed / refund_success / etc. */
    private String eventType;

    /** customer / handler / supervisor / manager */
    private String recipientType;

    /** 通知渠道列表（JSONB），如 ["wechat", "sms"] */
    private String channels;

    private Boolean enabled;

    private String templateId;

    @TableField(fill = FieldFill.INSERT)
    private OffsetDateTime createdAt;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private OffsetDateTime updatedAt;
}
