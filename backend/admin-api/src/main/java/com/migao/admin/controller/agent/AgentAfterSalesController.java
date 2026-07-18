package com.migao.admin.controller.agent;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.dto.AfterSalesDetailResponse;
import com.migao.admin.dto.agent.AgentAfterSalesCreateRequest;
import com.migao.admin.security.SecurityUser;
import com.migao.admin.service.AfterSalesTicketService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.bind.annotation.*;

/**
 * Agent 专用售后工单控制器。
 * 与表单 API (/api/admin/after-sales) 的关键差异：
 * - orderId 可传 UUID 或订单号（ORD-xxx），服务端自动解析
 * - 订单所有权校验内置（仅 customer 角色需要）
 */
@Slf4j
@RestController
@RequestMapping("/api/admin/agent/after-sales")
@RequiredArgsConstructor
public class AgentAfterSalesController {

    private final AfterSalesTicketService afterSalesTicketService;

    /**
     * Agent 专用创建售后工单。
     * POST /api/admin/agent/after-sales
     */
    @PostMapping
    public ApiResponse<AfterSalesDetailResponse> createTicket(@RequestBody AgentAfterSalesCreateRequest request) {
        Long tenantId = TenantContext.getTenantId();
        String operator = getCurrentOperator();
        log.info("[Agent] 创建售后工单: orderId={}, type={}, tenantId={}",
                request.getOrderId(), request.getTicketType(), tenantId);
        try {
            AfterSalesDetailResponse result =
                    afterSalesTicketService.createTicketForAgent(request, tenantId, operator);
            return ApiResponse.success(result);
        } catch (Exception e) {
            log.warn("[Agent] 创建售后工单失败: {}", e.getMessage());
            throw e;
        }
    }

    /** 从 SecurityContext 提取当前操作人 */
    private String getCurrentOperator() {
        try {
            Authentication auth = SecurityContextHolder.getContext().getAuthentication();
            if (auth != null && auth.getPrincipal() instanceof SecurityUser securityUser) {
                return securityUser.getUsername();
            }
        } catch (Exception ignored) {
            // 非 Web 上下文或无认证信息时降级
        }
        throw new org.springframework.security.access.AccessDeniedException("未认证的用户无法创建售后工单");
    }
}
