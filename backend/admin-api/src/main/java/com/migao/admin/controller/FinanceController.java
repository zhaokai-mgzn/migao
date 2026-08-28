package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.*;
import com.migao.admin.security.SecurityUser;
import com.migao.admin.service.FinanceService;
import com.migao.admin.security.RequirePermission;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.bind.annotation.*;

/**
 * 财务对账控制器
 *
 * 前端对齐：financeApi (frontend/admin-web/src/lib/api.ts)
 * - GET  /api/admin/finance/summary        → getSummary（收支汇总）
 * - GET  /api/admin/finance/transactions   → getTransactions（资金流水）
 * - POST /api/admin/finance/transactions   → createTransaction（手动登记）
 * - GET  /api/admin/finance/reconciliation → getReconciliation（应收对账）
 */
@Slf4j
@RequirePermission("finance:view")
@RestController
@RequestMapping("/api/admin/finance")
@RequiredArgsConstructor
public class FinanceController {

    private final FinanceService financeService;

    /**
     * 收支汇总
     *
     * GET /api/admin/finance/summary?startDate=2025-01-01&endDate=2025-12-31
     */
    @GetMapping("/summary")
    public ApiResponse<FinanceSummaryResponse> getSummary(
            @RequestParam(required = false) String startDate,
            @RequestParam(required = false) String endDate) {
        log.info("查询收支汇总: startDate={}, endDate={}", startDate, endDate);
        Long tenantId = TenantContext.getTenantId();
        FinanceSummaryResponse summary = financeService.getSummary(startDate, endDate, tenantId);
        return ApiResponse.success(summary);
    }

    /**
     * 分页查询资金流水
     *
     * GET /api/admin/finance/transactions?page=1&size=20&type=income&paymentMethod=wechat&keyword=xxx
     */
    @GetMapping("/transactions")
    public ApiResponse<PageResponse<FinanceTransactionListResponse>> getTransactions(
            @RequestParam(defaultValue = "1") long page,
            @RequestParam(defaultValue = "20") long size,
            @RequestParam(required = false) String type,
            @RequestParam(required = false) String paymentMethod,
            @RequestParam(required = false) String status,
            @RequestParam(required = false) String startDate,
            @RequestParam(required = false) String endDate,
            @RequestParam(required = false) String keyword) {
        log.info("查询资金流水: page={}, size={}, type={}, paymentMethod={}, keyword={}", page, size, type, paymentMethod, keyword);
        Long tenantId = TenantContext.getTenantId();
        PageResponse<FinanceTransactionListResponse> result = financeService.getTransactionPage(
                page, size, type, paymentMethod, status, startDate, endDate, keyword, tenantId);
        return ApiResponse.success(result);
    }

    /**
     * 手动登记一笔收支（线下收款/退款）
     *
     * POST /api/admin/finance/transactions
     */
    @PostMapping("/transactions")
    public ApiResponse<FinanceTransactionListResponse> createTransaction(
            @Valid @RequestBody FinanceTransactionCreateRequest request) {
        log.info("登记资金流水: type={}, amount={}, paymentMethod={}", request.getType(), request.getAmount(), request.getPaymentMethod());
        Long tenantId = TenantContext.getTenantId();
        String operator = getCurrentOperator();
        FinanceTransactionListResponse txn = financeService.createTransaction(request, tenantId, operator);
        return ApiResponse.success(txn);
    }

    /**
     * 应收对账（订单维度）
     *
     * GET /api/admin/finance/reconciliation?page=1&size=20&startDate=&endDate=&keyword=
     */
    @GetMapping("/reconciliation")
    public ApiResponse<PageResponse<ReceivableReconciliationResponse>> getReconciliation(
            @RequestParam(defaultValue = "1") long page,
            @RequestParam(defaultValue = "20") long size,
            @RequestParam(required = false) String startDate,
            @RequestParam(required = false) String endDate,
            @RequestParam(required = false) String keyword) {
        log.info("查询应收对账: page={}, size={}, startDate={}, endDate={}, keyword={}", page, size, startDate, endDate, keyword);
        Long tenantId = TenantContext.getTenantId();
        PageResponse<ReceivableReconciliationResponse> result = financeService.getReconciliation(
                page, size, startDate, endDate, keyword, tenantId);
        return ApiResponse.success(result);
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
}
