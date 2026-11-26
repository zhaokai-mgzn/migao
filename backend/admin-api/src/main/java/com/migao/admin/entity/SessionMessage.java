package com.migao.admin.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.OffsetDateTime;

/**
 * 会话消息实体类
 * 对应表：session_messages
 * 说明：AI对话消息持久化表
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName(value = "session_messages", autoResultMap = true)
public class SessionMessage {

    public static final String ROLE_USER = "user";

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    private String sessionId;

    private String role;

    private String contentType;

    private String content;

    /** 微信客服 msgid（幂等键）；其他通道为空。 */
    private String externalMsgId;

    @TableField(typeHandler = com.baomidou.mybatisplus.extension.handlers.JacksonTypeHandler.class)
    private Object metadata;

    private Integer tokenCount;

    @TableField(fill = FieldFill.INSERT)
    private OffsetDateTime createdAt;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private OffsetDateTime updatedAt;

    @TableLogic
    private Integer deleted;
}
