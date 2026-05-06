package com.aikf.admin.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.OffsetDateTime;

/**
 * 人工客服消息实体类 - 客服员工与客户的对话记录
 * 对应表：agent_messages
 * 区别于 SessionMessage（AI助手自动回复消息 - 面向企业内部员工）
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName("agent_messages")
public class AgentMessage {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    private String sessionId;

    /** customer / agent / system */
    private String senderType;

    private String senderId;

    private String contentType;

    private String content;

    private Boolean isInternal;

    @TableField(fill = FieldFill.INSERT)
    private OffsetDateTime createdAt;
}
