package com.migao.admin.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.OffsetDateTime;

/**
 * 审计日志实体类
 * 对应表：audit_logs
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName(value = "audit_logs", autoResultMap = true)
public class AuditLog {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    private String userId;

    private String userName;

    /** create / update / delete / login / logout / assign etc. */
    private String action;

    /** product / order / ticket / ai_config / employee etc. */
    private String resourceType;

    private String resourceId;

    private String resourceName;

    @TableField(typeHandler = com.baomidou.mybatisplus.extension.handlers.JacksonTypeHandler.class)
    private Object actionDetails;

    private String ipAddress;

    private String userAgent;

    @TableField(fill = FieldFill.INSERT)
    private OffsetDateTime createdAt;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private OffsetDateTime updatedAt;
}
