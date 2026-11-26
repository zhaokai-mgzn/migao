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

    // ── 微信客服状态（issue #9198 / 母单 #9194 子项 2）──────────────────────────
    // 非微信客服会话这三个字段恒为 null（**不得**给普通人工会话伪造渠道标识）。

    /** 渠道标识：微信客服来源时为 {@code wechat_kf}，否则 null。 */
    private String channel;

    /** 该会话最新一条微信客服发送状态：pending / sending / accepted / failed / unknown。 */
    private String sendStatus;

    /** 48h 窗口内已用条数（窗口过期或无记录 ⇒ 0）。 */
    private Integer budgetUsed;

    /** 48h 窗口上限（恒 5，与 kf_send_budget 的 CHECK 同源）。 */
    private Integer budgetLimit;
}
