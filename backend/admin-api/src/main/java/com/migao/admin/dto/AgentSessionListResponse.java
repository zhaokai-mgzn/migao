package com.migao.admin.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.OffsetDateTime;

/**
 * 会话列表项响应 DTO
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class AgentSessionListResponse {

    private String id;

    private String customerId;

    /** 客户名称（关联查询） */
    private String customerName;

    private String employeeId;

    /** 客服名称（关联查询） */
    private String employeeName;

    private String aiSessionId;

    private String status;

    private Integer priority;

    private String reason;

    private Integer queuePosition;

    /** 消息数量（聚合查询） */
    private Integer messageCount;

    private OffsetDateTime startedAt;

    private OffsetDateTime createdAt;
}
