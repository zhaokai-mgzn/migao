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

    /** 客户收款核销（issue #7370 段 3）：现金真值仍只认 finance_transactions，本服务只记核销去向。 */
    private final com.migao.admin.service.ReceiptAllocationService receiptAllocationService;

    /** 订单毛利（issue #7371 段 1）：只读算得出，不落派生列。 */
    private final com.migao.admin.service.OrderMarginService orderMarginService;

    // issue #5246 追加单：写面（登记收支流水）用方法级 finance:create 覆盖类级读码 ——
    // PermissionInterceptor 的解析顺序是**方法级优先、其次类级**，故 GET 三个读面仍吃 finance:view，
    // 而记账不再需要把 finance:view 当写权用（原形态：能看账 = 能记账）。
    // 有意**不**新造 finance:update：财务域目前只有「登记流水」这一个写动作，多造一个码没有持有者。

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
     *
     * issue #5246 追加单：登记流水是**写** ⇒ finance:create（覆盖类级读码 finance:view）。
     */
    @PostMapping("/transactions")
    @RequirePermission("finance:create")
    public ApiResponse<FinanceTransactionListResponse> createTransaction(
            @Valid @RequestBody FinanceTransactionCreateRequest request) {
        log.info("登记资金流水: type={}, amount={}, paymentMethod={}", request.getType(), request.getAmount(), request.getPaymentMethod());
        Long tenantId = TenantContext.getTenantId();
        String operator = getCurrentOperator();
        FinanceTransactionListResponse txn = financeService.createTransaction(request, tenantId, operator);
        return ApiResponse.success(txn);
    }

    /**
     * 客户收款核销（issue #7370，P0-2 段 3）：把一笔收入流水冲抵到一张或多张订单。
     *
     * <p>两条硬约束都在服务层（纯函数 `ReceiptAllocationPolicy` 判定）：
     * 同一流水 Σ核销 ≤ 流水金额（差额 = 预收 / 待勾对）、同一订单 Σ核销 ≤ 货值 − 退款。</p>
     */
    @PostMapping("/receipts/{transactionId}/allocations")
    @RequirePermission("finance:create")
    @com.migao.admin.security.TenantOwnedResource("receiptTransaction")
    public ApiResponse<ReceiptAllocationView> allocateReceipt(
            @PathVariable String transactionId,
            @RequestBody ReceiptAllocationRequest request) {
        String operator = currentOperator();
        return ApiResponse.success(receiptAllocationService.allocate(
                transactionId, request, TenantContext.getTenantId(), operator));
    }

    /**
     * 订单毛利（issue #7371，P0-3 段 1）：收入 − 退款 − **面料成本**。
     *
     * <p>🔴 成本未知（有扣料行缺批次进价）⇒ `grossMargin` / `marginRate` 返回 null、
     * `costKnown=false`，前端显示「成本未知」。**绝不当 0**：那会让毛利率虚高。</p>
     *
     * <p>本段只算面料毛利（`scope` 自述）：加工费与运费尚未计入。</p>
     */
    @GetMapping("/orders/{orderId}/margin")
    public ApiResponse<OrderMarginView> orderMargin(@PathVariable String orderId) {
        return ApiResponse.success(orderMarginService.margin(orderId));
    }

    /** 核销读面：这笔收款已核销多少、还剩多少未核销（预收 / 待勾对）。 */
    @GetMapping("/receipts/{transactionId}/allocations")
    public ApiResponse<ReceiptAllocationView> receiptAllocations(@PathVariable String transactionId) {
        return ApiResponse.success(receiptAllocationService.view(transactionId));
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

    /** 当前登录用户名（核销要能追到人；与流水登记的取法同源）。 */
    private String currentOperator() {
        Authentication auth = SecurityContextHolder.getContext().getAuthentication();
        if (auth != null && auth.getPrincipal() instanceof SecurityUser user) {
            return user.getUsername();
        }
        return null;
    }
}
