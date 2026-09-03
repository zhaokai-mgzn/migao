package com.migao.admin.controller;

import com.migao.admin.dto.*;
import com.migao.admin.entity.AgentMessage;
import com.migao.admin.entity.AgentSession;
import com.migao.admin.config.TenantContext;
import com.migao.admin.service.AgentSessionService;
import com.migao.admin.security.RequirePermission;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.*;

/**
 * 客服工作台会话管理控制器
 * 提供会话列表查询、详情、分配、结束、监控等管理接口
 *
 * 前端对齐：agentSessionApi (frontend/admin-web/src/lib/api.ts)
 * - GET    /api/admin/agent-sessions             → getSessions
 * - GET    /api/admin/agent-sessions/monitor      → getMonitorStats
 * - GET    /api/admin/agent-sessions/{id}         → getSession
 * - POST   /api/admin/agent-sessions/{id}/assign  → assignSession
 * - POST   /api/admin/agent-sessions/{id}/end     → endSession
 */
@Slf4j
@RequirePermission("agent:session")
@RestController
@RequestMapping("/api/admin/agent-sessions")
@RequiredArgsConstructor
public class AgentSessionController {

    private final AgentSessionService agentSessionService;

    /**
     * 分页查询客服工作台会话列表
     *
     * GET /api/admin/agent-sessions?page=1&size=20&status=waiting&employeeId=xxx&keyword=xxx
     */
    @GetMapping
    public ApiResponse<PageResponse<AgentSessionListResponse>> getSessions(
            @RequestParam(defaultValue = "1") long page,
            @RequestParam(defaultValue = "20") long size,
            @RequestParam(required = false) String status,
            @RequestParam(required = false) String employeeId,
            @RequestParam(required = false) String keyword) {
        log.info("查询客服会话列表: page={}, size={}, status={}, employeeId={}, keyword={}", page, size, status, employeeId, keyword);
        Long tenantId = TenantContext.getTenantId();
        PageResponse<AgentSessionListResponse> result = agentSessionService.getSessionPage(page, size, status, employeeId, keyword, tenantId);
        return ApiResponse.success(result);
    }

    /**
     * 获取监控面板数据（在线员工数、活跃会话数、排队数、今日统计）
     * 注意：此路由必须放在 /{id} 之前，避免 Spring 将 "monitor" 当作 id 匹配
     *
     * GET /api/admin/agent-sessions/monitor
     */
    @GetMapping("/monitor")
    public ApiResponse<AgentMonitorResponse> getMonitorStats() {
        Long tenantId = TenantContext.getTenantId();
        log.info("查询监控面板数据: tenantId={}", tenantId);
        AgentMonitorResponse result = agentSessionService.getMonitorStats(tenantId);
        return ApiResponse.success(result);
    }

    /**
     * 获取会话详情（含消息列表）
     *
     * GET /api/admin/agent-sessions/{id}
     */
    @GetMapping("/{id}")
    public ApiResponse<AgentSessionDetailResponse> getSession(@PathVariable String id) {
        log.info("查询会话详情: id={}", id);
        AgentSessionDetailResponse detail = agentSessionService.getSessionDetail(id);
        return ApiResponse.success(detail);
    }

    /**
     * 手动分配会话给客服员工
     *
     * POST /api/admin/agent-sessions/{id}/assign
     */
    @PostMapping("/{id}/assign")
    public ApiResponse<Void> assignSession(
            @PathVariable String id,
            @Valid @RequestBody AgentSessionAssignRequest request) {
        log.info("分配会话: sessionId={}, employeeId={}", id, request.getEmployeeId());
        agentSessionService.assignSession(id, request.getEmployeeId());
        return ApiResponse.success();
    }

    /**
     * 结束会话
     *
     * POST /api/admin/agent-sessions/{id}/end
     */
    @PostMapping("/{id}/end")
    public ApiResponse<Void> endSession(@PathVariable String id) {
        log.info("结束会话: sessionId={}", id);
        agentSessionService.endSession(id);
        return ApiResponse.success();
    }

    /**
     * 转人工创建会话（AI 客服 → 人工客服桥接）
     *
     * 由 ai-agent-service 的 human_handoff 工具调用（service token 或管理员）。
     * POST /api/admin/agent-sessions
     */
    @PostMapping
    public ApiResponse<AgentSessionDetailResponse> createSessionForHandoff(
            @Valid @RequestBody AgentSessionCreateRequest request) {
        Long tenantId = TenantContext.getTenantId();
        log.info("转人工创建会话: aiSessionId={}, customerId={}, tenantId={}, aiContextTurns={}",
                request.getAiSessionId(), request.getCustomerId(), tenantId,
                request.getAiContextMessages() == null ? 0 : request.getAiContextMessages().size());
        AgentSession session = agentSessionService.createSessionForHandoff(
                request.getAiSessionId(), request.getCustomerId(), tenantId, request.getReason(),
                request.getAiContextSummary(), request.getAiContextMessages());
        AgentSessionDetailResponse detail = agentSessionService.getSessionDetail(session.getId());
        return ApiResponse.success(detail);
    }

    /**
     * 客服发送消息（人工会话）
     *
     * POST /api/admin/agent-sessions/{id}/messages
     */
    @PostMapping("/{id}/messages")
    public ApiResponse<AgentMessageResponse> sendMessage(
            @PathVariable String id,
            @Valid @RequestBody AgentMessageSendRequest request) {
        log.info("客服发送消息: sessionId={}, isInternal={}", id, request.getIsInternal());
        // 从 SecurityContext 取当前员工（客服）
        String employeeId = getCurrentOperator();
        AgentMessage msg = agentSessionService.sendMessage(
                id, "agent", employeeId, request.getContent(), request.getIsInternal());
        return ApiResponse.success(buildMessageResponse(msg));
    }

    /** 从 SecurityContext 提取当前操作人信息 */
    private String getCurrentOperator() {
        try {
            var auth = org.springframework.security.core.context.SecurityContextHolder
                    .getContext().getAuthentication();
            if (auth != null && auth.getPrincipal() instanceof com.migao.admin.security.SecurityUser securityUser) {
                return securityUser.getUsername();
            }
        } catch (Exception ignored) {
            // 非 Web 上下文或无认证信息时降级
        }
        return "system";
    }

    private AgentMessageResponse buildMessageResponse(AgentMessage msg) {
        return AgentMessageResponse.builder()
                .id(msg.getId())
                .senderType(msg.getSenderType())
                .senderId(msg.getSenderId())
                .contentType(msg.getContentType())
                .content(msg.getContent())
                .isInternal(msg.getIsInternal())
                .createdAt(msg.getCreatedAt())
                .build();
    }
}
