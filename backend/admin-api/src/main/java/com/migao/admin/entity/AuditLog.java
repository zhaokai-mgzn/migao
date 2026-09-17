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

    /** 动作**动词**：create / update / delete / toggle_status / confirm_payment etc.（issue #4071 裁定 ①） */
    private String action;

    /** product / order / ticket / ai_config / employee / agent_tool etc. */
    private String resourceType;

    /**
     * AI 工具名（如 order_create / product_manage）；仅 {@code resourceType='agent_tool'} 有值。
     * 迁移 V52 新增：此前工具名塞在 {@link #action} 里，同一列两种语义（issue #4071）。
     */
    private String toolName;

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
