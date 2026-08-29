package com.migao.admin.controller;

import com.migao.admin.dto.AgentMessageResponse;
import com.migao.admin.dto.AgentMessageSendRequest;
import com.migao.admin.dto.AgentSessionDetailResponse;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.entity.AgentMessage;
import com.migao.admin.security.SecurityUser;
import com.migao.admin.service.AgentSessionService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.bind.annotation.*;

/**
 * 用户端人工客服会话控制器（C 端小程序）
 *
 * 转人工后，用户在此查询人工客服回复、发送消息。
 * 路由 /api/customer/**（非 /api/admin/**），customer 角色可访问；
 * 业务层按 customerId 归属校验，用户只能操作自己的会话。
 */
@Slf4j
@RestController
@RequestMapping("/api/customer/agent-sessions")
@RequiredArgsConstructor
public class CustomerAgentSessionController {

    private final AgentSessionService agentSessionService;

    /**
     * 用户按 AI 会话 ID 查询人工客服会话（含消息）
     *
     * GET /api/customer/agent-sessions/by-ai/{aiSessionId}
     */
    @GetMapping("/by-ai/{aiSessionId}")
    public ApiResponse<AgentSessionDetailResponse> getByAiSession(@PathVariable String aiSessionId) {
        String customerId = getCurrentUserId();
        log.info("用户查询人工会话: aiSessionId={}, customerId={}", aiSessionId, customerId);
        AgentSessionDetailResponse detail = agentSessionService.getSessionByAiSessionId(aiSessionId, customerId);
        return ApiResponse.success(detail);
    }

    /**
     * 用户在人工会话中发送消息
     *
     * POST /api/customer/agent-sessions/{id}/messages
     */
    @PostMapping("/{id}/messages")
    public ApiResponse<AgentMessageResponse> sendMessage(
            @PathVariable String id,
            @Valid @RequestBody AgentMessageSendRequest request) {
        String customerId = getCurrentUserId();
        log.info("用户发送人工会话消息: sessionId={}, customerId={}", id, customerId);
        AgentMessage msg = agentSessionService.sendMessage(
                id, "customer", customerId, request.getContent(), false);
        return ApiResponse.success(buildMessageResponse(msg));
    }

    /** 从 SecurityContext 提取当前用户 ID（JWT subject） */
    private String getCurrentUserId() {
        Authentication auth = SecurityContextHolder.getContext().getAuthentication();
        if (auth != null && auth.getPrincipal() instanceof SecurityUser securityUser) {
            return securityUser.getUserId();
        }
        throw new com.migao.admin.exception.BusinessException("UNAUTHORIZED", "未认证，请先登录", 401);
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
