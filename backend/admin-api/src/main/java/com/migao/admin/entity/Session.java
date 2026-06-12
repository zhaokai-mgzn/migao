package com.migao.admin.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.OffsetDateTime;

/**
 * 会话实体类
 * 对应表：sessions
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName(value = "sessions", autoResultMap = true)
public class Session {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    private String customerId;

    /** wechat_mini / wechat_h5 / web */
    private String channel;

    /** active / closed / waiting */
    private String status;

    private String assignedAgentId;

    private Boolean aiEnabled;

    @TableField(typeHandler = com.baomidou.mybatisplus.extension.handlers.JacksonTypeHandler.class)
    private Object metadata;

    private OffsetDateTime startedAt;

    private OffsetDateTime endedAt;

    @TableField(fill = FieldFill.INSERT)
    private OffsetDateTime createdAt;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private OffsetDateTime updatedAt;

    @TableLogic
    private Integer deleted;
}
