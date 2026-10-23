package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.dto.OrderMarginReportView;
import com.migao.admin.security.DataScope;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.security.SecurityUser;
import com.migao.admin.service.ReportService;
import com.migao.admin.service.RoleService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * 报表中心（issue #7376，P1-4 段 1）：**只读**面。
 *
 * <p>授权零 delta：读面沿用既有 `dashboard:view`（报表与看板同域，不新造权限码）。</p>
 */
@Slf4j
@RestController
@RequestMapping("/api/admin/reports")
@RequiredArgsConstructor
@RequirePermission("dashboard:view")
public class ReportController {

    private final ReportService reportService;

    /**
     * 订单毛利报表：`GET /api/admin/reports/order-margins?startDate=&endDate=`。
     *
     * <p>三条口径随响应自证：合计 = 明细之和；**空数据时合计为 null（不是 0）**；
     * 成本未知的单**不进毛利合计**但单独计数。</p>
     */
    @GetMapping("/order-margins")
    public ApiResponse<OrderMarginReportView> orderMargins(
            @RequestParam(required = false) String startDate,
            @RequestParam(required = false) String endDate) {
        String scopeOwnerId = com.migao.admin.security.DataScope.ownerFilter(
                roleService.resolveDataScope(currentUserId()), currentUserId());
        return ApiResponse.success(reportService.orderMargins(startDate, endDate, scopeOwnerId));
    }

    /**
     * 库存周转与滞销报表：`GET /api/admin/reports/inventory-aging?thresholdDays=&warehouseCode=`。
     *
     * <p>滞销口径自述（`slowMovingDays`）：满 N 天未出库且还有货；从未出库的按入库日起算。
     * 缺日期的行**不猜**，单独计数（`undeterminedRows`）。</p>
     */
    @GetMapping("/inventory-aging")
    public ApiResponse<com.migao.admin.dto.InventoryReportView> inventoryAging(
            @RequestParam(required = false) Integer thresholdDays,
            @RequestParam(required = false) String warehouseCode) {
        return ApiResponse.success(reportService.inventoryAging(thresholdDays, warehouseCode));
    }

    /**
     * 员工业绩报表：`GET /api/admin/reports/staff-performance?startDate=&endDate=`。
     *
     * <p>口径：按制单人归集单数与收入；**没有制单人的订单单独成档**（不摊给任何人）；客单价 = 收入/单数，
     * 单数为 0 ⇒ null。数据范围同 P0-4（`self` 只看自己的业绩）。</p>
     */
    @GetMapping("/staff-performance")
    public ApiResponse<com.migao.admin.dto.StaffPerformanceView> staffPerformance(
            @RequestParam(required = false) String startDate,
            @RequestParam(required = false) String endDate) {
        String scopeOwnerId = com.migao.admin.security.DataScope.ownerFilter(
                roleService.resolveDataScope(currentUserId()), currentUserId());
        return ApiResponse.success(reportService.staffPerformance(startDate, endDate, scopeOwnerId));
    }

    /**
     * 质量成本报表：`GET /api/admin/reports/quality-cost?startDate=&endDate=`。
     *
     * <p>三项分列（返工工时 / 报废料 / 赔付）；未知项**不折成 0**，合计只累加已知项，
     * `complete=false` 时页面必须标注「这是可算的那部分」。</p>
     */
    @GetMapping("/quality-cost")
    public ApiResponse<com.migao.admin.dto.QualityCostView> qualityCost(
            @RequestParam(required = false) String startDate,
            @RequestParam(required = false) String endDate) {
        return ApiResponse.success(reportService.qualityCost(startDate, endDate));
    }

    /**
     * 应收账龄报表：`GET /api/admin/reports/receivable-aging`（issue #7376 段 5）。
     *
     * <p>五档（未到期 / 1-30 / 31-60 / 61-90 / 90+）+ 按客户分行；**没有欠款时合计为 null（不是 0）**。
     * 到期日 = 下单业务日 + 客户账期，分档规则钉在纯函数 {@code ReceivableAging} 上（本端点不重算）。
     * 数据范围同 P0-4（`self` 只算本人创建的单）。</p>
     */
    @GetMapping("/receivable-aging")
    public ApiResponse<com.migao.admin.dto.ReceivableAgingReportView> receivableAging() {
        String scopeOwnerId = com.migao.admin.security.DataScope.ownerFilter(
                roleService.resolveDataScope(currentUserId()), currentUserId());
        return ApiResponse.success(reportService.receivableAging(
                com.migao.admin.config.TenantContext.getTenantId(), scopeOwnerId));
    }

    /** 数据范围解析（与 P0-4 同口径：仓储在 role.data_scope，读权在 RoleService）。 */
    private final RoleService roleService;

    private String currentUserId() {
        var authentication = SecurityContextHolder.getContext().getAuthentication();
        if (authentication != null
                && authentication.getPrincipal() instanceof SecurityUser user) {
            return user.getUserId();
        }
        return null;
    }
}
