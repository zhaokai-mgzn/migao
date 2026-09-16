package com.migao.admin.controller.agent;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.dto.AfterSalesDetailResponse;
import com.migao.admin.dto.agent.AgentAfterSalesCreateRequest;
import com.migao.admin.security.SecurityUser;
import com.migao.admin.service.AfterSalesTicketService;
import com.migao.admin.security.RequirePermission;
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
@RequirePermission("order:refund")
@RestController
@RequestMapping("/api/admin/agent/after-sales")
@RequiredArgsConstructor
public class AgentAfterSalesController {

    private final AfterSalesTicketService afterSalesTicketService;

    /**
     * 内部调用方声明工单真实来源的请求头（issue #3686）。
     *
     * <p>服务端在本端点**无法自行判定**真实来源：三个 Agent 建单工具
     * （小布 `aftersale_create` / 米宝 `after_sales_manage` / 转人工 `human_handoff`）
     * 打的是同一个 URL、同一组 header，且都以 Service Token 认证 ⇒
     * `getCurrentOperator()` 恒为 `internal-service`、body 无 source（#3605 已删）。
     * 故由**内部调用方**声明，服务端只在值属于白名单时采纳，缺省/未知一律回退
     * {@code agent}（= 既有行为，向后兼容未升级的调用方）。
     */
    private static final String CLIENT_HEADER = "X-Agent-Client";

    /**
     * Agent 专用创建售后工单。
     * POST /api/admin/agent/after-sales
     */
    @PostMapping
    public ApiResponse<AfterSalesDetailResponse> createTicket(
            @RequestBody AgentAfterSalesCreateRequest request,
            @RequestHeader(value = CLIENT_HEADER, required = false) String clientSource) {
        Long tenantId = TenantContext.getTenantId();
        String operator = getCurrentOperator();
        // 未知/缺省 → agent（既有行为）：只有内部调用方显式声明才改变来源语义
        String source = AfterSalesTicketService.resolveSource(
                clientSource, AfterSalesTicketService.SOURCE_AGENT);
        log.info("[Agent] 创建售后工单: orderId={}, type={}, tenantId={}, source={}",
                request.getOrderId(), request.getTicketType(), tenantId, source);
        try {
            AfterSalesDetailResponse result =
                    afterSalesTicketService.createTicketForAgent(request, tenantId, operator, source);
            return ApiResponse.success(result);
        } catch (Exception e) {
            log.warn("[Agent] 创建售后工单失败: {}", e.getMessage());
            throw e;
        }
    }

    /**
     * C 端（小布/customer 角色）"我的售后"查询。
     * GET /api/admin/agent/after-sales/mine?page=1&size=10
     *
     * 数据隔离强制点：无论调用方传什么参数，都只返回「当前登录用户订单上的
     * 售后工单」（X-User-Id 透传 → SecurityUser.userId）。缺省 userId（内部
     * 服务占位）时直接拒绝，避免跨用户数据泄露。
     */
    @GetMapping("/mine")
    public ApiResponse<com.migao.admin.dto.PageResponse<com.migao.admin.dto.AfterSalesListResponse>> getMyTickets(
            @RequestParam(defaultValue = "1") long page,
            @RequestParam(defaultValue = "10") long size) {
        Long tenantId = TenantContext.getTenantId();
        String userId = currentUserId();
        if (userId == null || userId.isBlank() || "internal-service".equals(userId)) {
            log.warn("[Agent] 拒绝 C 端售后查询: 缺少真实用户标识 tenantId={}", tenantId);
            throw com.migao.admin.exception.BusinessException.authFailed("缺少用户标识，无法查询售后工单");
        }
        log.info("[Agent] 查询我的售后工单: userId={}, page={}, size={}, tenantId={}",
                userId, page, size, tenantId);
        com.migao.admin.dto.PageResponse<com.migao.admin.dto.AfterSalesListResponse> result =
                afterSalesTicketService.getTicketPageForUser(tenantId, userId, page, size);
        return ApiResponse.success(result);
    }

    /** 从 SecurityContext 提取当前真实用户 ID（ServiceTokenFilter 已透传 X-User-Id） */
    private String currentUserId() {
        Authentication auth = SecurityContextHolder.getContext().getAuthentication();
        if (auth != null && auth.getPrincipal() instanceof SecurityUser securityUser) {
            return securityUser.getUserId();
        }
        return null;
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
