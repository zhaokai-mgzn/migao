package com.migao.admin.controller.agent;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.dto.agent.AgentAuditLogRequest;
import com.migao.admin.security.SecurityUser;
import com.migao.admin.service.AuditLogService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/**
 * Agent 专用写审计落库控制器（issue #4039）。
 *
 * <p>ai-agent-service 的写工具执行（下单/建品/改库存/转人工…）经
 * {@code ToolRegistry.execute_tool} 与 {@code base_skill._execute_tool_safe} 上报到此，
 * 由 {@link AuditLogService} 落 {@code audit_logs} —— 工具层不直连 DB（本仓架构契约）。</p>
 *
 * <p>为什么身份不从 body 取：{@code audit_logs} 是取证材料，调用方自报身份等于可伪造；
 * tenant 取 {@link TenantContext}（X-Tenant-Id 解析）、user 取认证主体的 userId
 * （ServiceTokenFilter 已把 ai-agent 的 X-User-Id 透传进来）。</p>
 */
@Slf4j
@RestController
@RequestMapping("/api/admin/agent/audit-logs")
@RequiredArgsConstructor
public class AgentAuditLogController {

    private final AuditLogService auditLogService;

    /**
     * POST /api/admin/agent/audit-logs —— 写工具调用结果落库（成功/失败/异常都上报）。
     *
     * <p>字段落位（issue #4071 裁定 ①）：{@code action} = 动作**动词** → {@code audit_logs.action}，
     * {@code toolName} = 工具名 → {@code audit_logs.tool_name}（迁移 V52）。
     * 此前工具名塞在 {@code action} 里靠 {@code resourceType} 反推语义 —— 那是同一列两种语义。</p>
     */
    @PostMapping
    public ApiResponse<Map<String, Object>> record(@Valid @RequestBody AgentAuditLogRequest request) {
        Long tenantId = TenantContext.getTenantId();
        String userId = currentUserId();
        // 同步落库（不用 recordLogAsync）：调用方（ai-agent）据此确认「审计已落」，
        // 异步会让上报成功而表里没行（取证缺口原地复发）
        auditLogService.recordLog(tenantId, userId, null, request.getAction(),
                request.getResourceType(), request.getToolName(), null, null,
                request.getActionDetails(), null, null);
        return ApiResponse.success(Map.of(
                "action", request.getAction(),
                "toolName", String.valueOf(request.getToolName())));
    }

    /** 从 SecurityContext 提取当前真实用户 ID（ServiceTokenFilter 已透传 X-User-Id） */
    private String currentUserId() {
        Authentication authentication = SecurityContextHolder.getContext().getAuthentication();
        if (authentication != null && authentication.getPrincipal() instanceof SecurityUser securityUser) {
            return securityUser.getUserId();
        }
        return null;
    }
}