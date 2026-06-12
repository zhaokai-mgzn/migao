package com.migao.admin.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.OffsetDateTime;

/**
 * 人工客服消息响应 DTO
 * 对应表：agent_messages
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class AgentMessageResponse {

    private String id;

    private String senderType;

    private String senderId;

    private String senderName;

    private String contentType;

    private String content;

    private Boolean isInternal;

    private OffsetDateTime createdAt;
}
