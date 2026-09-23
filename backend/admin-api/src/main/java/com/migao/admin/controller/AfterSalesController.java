package com.migao.admin.controller;

import com.migao.admin.dto.*;
import com.migao.admin.config.TenantContext;
import com.migao.admin.security.SecurityUser;
import com.migao.admin.service.AfterSalesTicketService;
import com.migao.admin.security.RequirePermission;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.bind.annotation.*;

/**
 * 售后工单管理控制器
 * 提供售后工单 CRUD、状态更新等管理接口
 *
 * 前端对齐：afterSalesApi (frontend/admin-web/src/lib/api.ts)
 * - GET    /api/admin/after-sales          → getTickets
 * - GET    /api/admin/after-sales/{id}     → getTicket
 * - POST   /api/admin/after-sales          → createTicket
 * - PUT    /api/admin/after-sales/{id}/status → updateTicketStatus
 */
@Slf4j
@RestController
@RequestMapping("/api/admin/after-sales")
@RequiredArgsConstructor
public class AfterSalesController {

    private final AfterSalesTicketService afterSalesTicketService;

    /**
     * 分页查询售后工单列表
     *
     * GET /api/admin/after-sales?page=1&size=20&status=pending&ticketType=return&keyword=xxx
     *
     * issue #5246：读/写拆码 —— 查列表是**读**，用 after_sales:view（原类级 order:refund
     * 是「处理退款」的**写**码，会让只想看工单的客服拿不到菜单，或被迫连写权一起授予）。
     */
    @GetMapping
    @RequirePermission("after_sales:view")
    public ApiResponse<PageResponse<AfterSalesListResponse>> getTickets(
            @RequestParam(defaultValue = "1") long page,
            @RequestParam(defaultValue = "20") long size,
            @RequestParam(required = false) String status,
            @RequestParam(required = false) String ticketType,
            @RequestParam(required = false) String keyword) {
        log.info("查询售后工单列表: page={}, size={}, status={}, ticketType={}, keyword={}", page, size, status, ticketType, keyword);
        Long tenantId = TenantContext.getTenantId();
        PageResponse<AfterSalesListResponse> result = afterSalesTicketService.getTicketPage(page, size, status, ticketType, keyword, tenantId);
        return ApiResponse.success(result);
    }

    /**
     * 查询售后工单详情
     *
     * GET /api/admin/after-sales/{id}
     *
     * issue #5246：查详情同为**读** ⇒ after_sales:view（与列表同码）。
     */
    @GetMapping("/{id}")
    @RequirePermission("after_sales:view")
    public ApiResponse<AfterSalesDetailResponse> getTicket(@PathVariable String id) {
        log.info("查询售后工单详情: id={}", id);
        AfterSalesDetailResponse ticket = afterSalesTicketService.getTicketById(id);
        return ApiResponse.success(ticket);
    }

    /**
     * 创建售后工单
     *
     * POST /api/admin/after-sales
     *
     * issue #3686：该 URL 的唯一调用方是 admin-web 工单页（frontend/admin-web/src/lib/api.ts ←
     * after-sales/page.tsx），即后台**人工建单** ⇒ 真实来源 {@code merchant}
     * （原实现恒写 "agent"，把人工建单与顾客工单都标成 Agent）。
     *
     * issue #5246：建单是**写**（产生工单事实）⇒ 保留写码 order:refund（不降级到 after_sales:view，
     * 否则「能看工单」就等于「能建单」）。
     */
    @PostMapping
    @RequirePermission("order:refund")
    public ApiResponse<AfterSalesDetailResponse> createTicket(@Valid @RequestBody AfterSalesCreateRequest request) {
        log.info("创建售后工单: orderId={}, ticketType={}", request.getOrderId(), request.getTicketType());
        Long tenantId = TenantContext.getTenantId();
        String operator = getCurrentOperator();
        AfterSalesDetailResponse ticket = afterSalesTicketService.createTicket(
                request, tenantId, operator, AfterSalesTicketService.SOURCE_MERCHANT);
        return ApiResponse.success(ticket);
    }

    /** 从 SecurityContext 提取当前操作人信息 */
    private String getCurrentOperator() {
        try {
            Authentication auth = SecurityContextHolder.getContext().getAuthentication();
            if (auth != null && auth.getPrincipal() instanceof SecurityUser securityUser) {
                return securityUser.getUsername();
            }
        } catch (Exception ignored) {
            // 非 Web 上下文或无认证信息时降级
        }
        return "系统";
    }

    /**
     * 更新工单状态
     *
     * PUT /api/admin/after-sales/{id}/status
     *
     * issue #5246：改状态是**写**（推进工单流转，可能触发退款/回补）⇒ 写码 order:refund。
     */
    @PutMapping("/{id}/status")
    @RequirePermission("order:refund")
    public ApiResponse<Void> updateTicketStatus(
            @PathVariable String id,
            @Valid @RequestBody AfterSalesStatusUpdateRequest request) {
        log.info("更新工单状态: id={}, status={}", id, request.getStatus());
        afterSalesTicketService.updateTicketStatus(id, request);
        return ApiResponse.success();
    }
}
