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

    /** 转人工时点 AI 会话上下文摘要（管理端可见；顾客端接口不含，GB/T 47746-2026） */
    private String aiContextSummary;

    /** 转人工前 AI 对话快照（管理端可见；顾客端接口不含） */
    private List<AgentAiContextMessage> aiContext;

    private String customerPhone;

    private String customerAvatarUrl;
}
