package com.migao.admin.controller.agent;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.dto.AfterSalesDetailResponse;
import com.migao.admin.dto.agent.AgentAfterSalesCreateRequest;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.security.SecurityUser;
import com.migao.admin.service.AfterSalesTicketService;
import com.migao.admin.service.ClientRequestIdService;
import com.migao.admin.security.RequirePermission;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.util.StringUtils;
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
    /** 写请求幂等键（issue #4037）：去重 / 结果回放 / 占位释放（与订单写路径复用同一实现） */
    private final ClientRequestIdService clientRequestIdService;

    /** 幂等端点标识（issue #4037）：三个建单工具（aftersale_create / after_sales_manage / human_handoff）同打本端点 */
    private static final String ENDPOINT_CREATE_TICKET = "POST /api/admin/agent/after-sales";

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
     *
     * <p>幂等键（issue #4037，F19）：请求头 {@code X-Client-Request-Id} 非空时按
     * {@code (tenantId, 键)} 去重 —— 同一键的同键请求**只建一张工单**，重复到达时回放首次
     * {@link AfterSalesDetailResponse}。无键 ⇒ 原路径逐字不变（向后兼容未升级的调用方）。</p>
     *
     * <p><b>接线位置与并发语义（如实登记）</b>：本端点的幂等接线放在 Controller 而非
     * {@code AfterSalesTicketService#createTicketForAgent}，因为该方法是被三个工具 +
     * 既有测试共同引用的稳定签名（改动会波及既有 source 契约测试）。代价是占位/快照
     * **不在建单事务内**：并发同键时第二个请求不会被阻塞，而是立刻拿到
     * 「正在处理中」的 fail-closed 409（不重复建单）；执行失败由 {@code discard} 释放占位。</p>
     */
    @PostMapping
    public ApiResponse<AfterSalesDetailResponse> createTicket(
            @RequestBody AgentAfterSalesCreateRequest request,
            @RequestHeader(value = CLIENT_HEADER, required = false) String clientSource,
            @RequestHeader(value = ClientRequestIdService.HEADER, required = false) String clientRequestId) {
        Long tenantId = TenantContext.getTenantId();
        String operator = getCurrentOperator();
        // 未知/缺省 → agent（既有行为）：只有内部调用方显式声明才改变来源语义
        String source = AfterSalesTicketService.resolveSource(
                clientSource, AfterSalesTicketService.SOURCE_AGENT);
        log.info("[Agent] 创建售后工单: orderId={}, type={}, tenantId={}, source={}, clientRequestId={}",
                request.getOrderId(), request.getTicketType(), tenantId, source, clientRequestId);
        if (!StringUtils.hasText(clientRequestId)) {
            return ApiResponse.success(
                    afterSalesTicketService.createTicketForAgent(request, tenantId, operator, source));
        }
        // ① 原子占位：同键已有占位 ⇒ 本次不建单
        if (!clientRequestIdService.claim(tenantId, clientRequestId, ENDPOINT_CREATE_TICKET)) {
            // ② 回放首次工单快照（无快照时 replay fail-closed 抛错，不返回空结果）
            return ApiResponse.success(clientRequestIdService
                    .replay(tenantId, clientRequestId, AfterSalesDetailResponse.class)
                    .orElseThrow(() -> new BusinessException("REQUEST_IN_PROGRESS",
                            "同一 X-Client-Request-Id 的工单请求正在处理中，本次未重复建单",
                            409,
                            "请勿重复提交；请稍后用售后查询工具确认工单是否已创建（换新幂等键重试会重复建单）")));
        }
        AfterSalesDetailResponse result;
        try {
            result = afterSalesTicketService.createTicketForAgent(request, tenantId, operator, source);
        } catch (Exception e) {
            log.warn("[Agent] 创建售后工单失败: {}", e.getMessage());
            // ④ 失败释放占位（否则该键永久占死，后续同键重试全被误判为「重复」），异常原样抛出
            clientRequestIdService.discard(tenantId, clientRequestId);
            throw e;
        }
        // ③ 落结果快照；放在 try 之外：快照写失败时**不得**释放占位（工单已经建出来了），
        //    宁可让同键请求 fail-closed 报错，也不能让重试建出第二张工单
        clientRequestIdService.complete(tenantId, clientRequestId, result);
        return ApiResponse.success(result);
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
