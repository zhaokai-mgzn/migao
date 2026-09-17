package com.migao.admin.dto.agent;

import jakarta.validation.constraints.NotBlank;
import lombok.Data;

import java.util.Map;

/**
 * ai-agent-service 写操作审计上报请求（POST /api/admin/agent/audit-logs，issue #4039）。
 *
 * <p>身份（tenant_id / user_id）**不在本 DTO 内**：一律取自认证上下文
 * （Service Token 经 X-Tenant-Id/X-User-Id 透传后写入 SecurityUser），
 * 以免 body 伪造他人身份写入审计行。</p>
 */
@Data
public class AgentAuditLogRequest {

    /** 工具名（如 order_create / product_manage）→ audit_logs.action */
    @NotBlank(message = "action 不能为空")
    private String action;

    /** 资源类型（固定 agent_tool：区分 AI 工具写操作与人工表单审计） */
    private String resourceType;

    /**
     * 审计详情 → audit_logs.action_details（JSONB）。
     * 约定键：params（**已脱敏**：字段名 → 类型占位 `<str>`/`<int>`）、success、
     * durationMs、role、sessionId（表无 session_id 列，暂落此处）。
     */
    private Map<String, Object> actionDetails;
}