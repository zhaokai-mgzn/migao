package com.aikf.admin.controller;

import com.aikf.admin.dto.*;
import com.aikf.admin.config.TenantContext;
import com.aikf.admin.service.AfterSalesTicketService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
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
     */
    @GetMapping
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
     */
    @GetMapping("/{id}")
    public ApiResponse<AfterSalesDetailResponse> getTicket(@PathVariable String id) {
        log.info("查询售后工单详情: id={}", id);
        AfterSalesDetailResponse ticket = afterSalesTicketService.getTicketById(id);
        return ApiResponse.success(ticket);
    }

    /**
     * 创建售后工单
     *
     * POST /api/admin/after-sales
     */
    @PostMapping
    public ApiResponse<AfterSalesDetailResponse> createTicket(@Valid @RequestBody AfterSalesCreateRequest request) {
        log.info("创建售后工单: orderId={}, ticketType={}", request.getOrderId(), request.getTicketType());
        Long tenantId = TenantContext.getTenantId();
        AfterSalesDetailResponse ticket = afterSalesTicketService.createTicket(request, tenantId);
        return ApiResponse.success(ticket);
    }

    /**
     * 更新工单状态
     *
     * PUT /api/admin/after-sales/{id}/status
     */
    @PutMapping("/{id}/status")
    public ApiResponse<Void> updateTicketStatus(
            @PathVariable String id,
            @Valid @RequestBody AfterSalesStatusUpdateRequest request) {
        log.info("更新工单状态: id={}, status={}", id, request.getStatus());
        afterSalesTicketService.updateTicketStatus(id, request);
        return ApiResponse.success();
    }
}
