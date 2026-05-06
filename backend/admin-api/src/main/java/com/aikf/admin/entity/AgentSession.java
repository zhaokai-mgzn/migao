package com.aikf.admin.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.OffsetDateTime;

/**
 * 人工客服会话实体类 - 企业内部客服员工使用
 * 对应表：agent_sessions
 * 区别于 Session（AI助手会话 - 管理后台右下角悬浮入口，面向企业内部员工）
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName(value = "agent_sessions", autoResultMap = true)
public class AgentSession {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    private String customerId;

    private String employeeId;

    private String aiSessionId;

    /** waiting / active / closed / transferred */
    private String status;

    private Integer priority;

    private String reason;

    private Integer queuePosition;

    private OffsetDateTime startedAt;

    private OffsetDateTime endedAt;

    @TableField(fill = FieldFill.INSERT)
    private OffsetDateTime createdAt;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private OffsetDateTime updatedAt;

    @TableLogic
    private Integer deleted;
}
