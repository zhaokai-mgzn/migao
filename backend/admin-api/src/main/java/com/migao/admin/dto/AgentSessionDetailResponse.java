package com.migao.admin.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.OffsetDateTime;
import java.util.List;

/**
 * 会话详情响应 DTO
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class AgentSessionDetailResponse {

    private String id;

    private String customerId;

    private String customerName;

    private String employeeId;

    private String employeeName;

    private String aiSessionId;

    private String status;

    private Integer priority;

    private String reason;

    private Integer queuePosition;

    private Integer messageCount;

    private OffsetDateTime startedAt;

    private OffsetDateTime createdAt;

    private OffsetDateTime endedAt;

    /** 消息列表 */
    private List<AgentMessageResponse> messages;

    private String customerPhone;

    private String customerAvatarUrl;
}
