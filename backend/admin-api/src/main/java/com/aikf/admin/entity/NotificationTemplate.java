package com.aikf.admin.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.OffsetDateTime;

/**
 * 通知模板实体类
 * 对应表：notification_templates
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName("notification_templates")
public class NotificationTemplate {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    private String name;

    /** ticket_assigned / ticket_status_changed / refund_success / shipment / etc. */
    private String type;

    /** wechat / sms / email / internal */
    private String channel;

    private String templateContent;

    /** 可用变量列表（JSONB） */
    private String variables;

    /** active / inactive */
    private String status;

    @TableField(fill = FieldFill.INSERT)
    private OffsetDateTime createdAt;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private OffsetDateTime updatedAt;
}
