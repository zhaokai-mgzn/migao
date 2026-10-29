package com.migao.admin.controller;

import com.migao.admin.dto.ApiResponse;
import com.migao.admin.dto.PurchaseOrderCreateRequest;
import com.migao.admin.dto.PurchaseOrderReceiveRequest;
import com.migao.admin.dto.PurchaseOrderView;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.security.SecurityUser;
import com.migao.admin.security.TenantOwnedResource;
import com.migao.admin.config.TenantContext;
import com.migao.admin.service.PurchaseOrderService;
import lombok.RequiredArgsConstructor;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.util.StringUtils;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;

/**
 * 采购单端点（issue #7369，P0-1 段 4）。
 *
 * <p>权限码复用**既有** {@code inbound:view} / {@code inbound:create}：采购与入库是同一个岗位
 * （仓管/采购），而新造 {@code purchase:*} 今天没有岗位持有 ⇒ 菜单与页面会对所有人不可见（#4203 同族坑）。</p>
 */
@RestController
@RequiredArgsConstructor
public class PurchaseOrderController {

    private final PurchaseOrderService purchaseOrderService;

    /** 采购单列表（可按状态 / 供应商过滤）。 */
    @GetMapping("/api/admin/purchase-orders")
    @RequirePermission("purchase:view")
    public ApiResponse<List<PurchaseOrderView>> list(@RequestParam(required = false) String status,
                                                    @RequestParam(required = false) String supplierId) {
        return ApiResponse.success(
                purchaseOrderService.list(TenantContext.getTenantId(), status, supplierId));
    }

    /** 采购单详情（含逐行已收/未收与收货记录）。 */
    @GetMapping("/api/admin/purchase-orders/{id}")
    @RequirePermission("purchase:view")
    @TenantOwnedResource("purchaseOrder")
    public ApiResponse<PurchaseOrderView> detail(@PathVariable String id) {
        return ApiResponse.success(purchaseOrderService.detail(id, TenantContext.getTenantId()));
    }

    /** 建采购单（状态一律 ordered）。 */
    @PostMapping("/api/admin/purchase-orders")
    @RequirePermission("inbound:create")
    public ApiResponse<PurchaseOrderView> create(@RequestBody PurchaseOrderCreateRequest request) {
        return ApiResponse.success(
                purchaseOrderService.create(request, TenantContext.getTenantId(), currentOperator()));
    }

    /** 登记收货（一次可多行；收齐/部分收齐由服务层派生）。 */
    @PostMapping("/api/admin/purchase-orders/{id}/receive")
    @RequirePermission("inbound:create")
    @TenantOwnedResource("purchaseOrder")
    public ApiResponse<PurchaseOrderView> receive(@PathVariable String id,
                                                 @RequestBody PurchaseOrderReceiveRequest request) {
        return ApiResponse.success(
                purchaseOrderService.receive(id, request, TenantContext.getTenantId(), currentOperator()));
    }

    /** 关闭采购单（断货 / 取消 / 到不齐；**必须写原因**）。 */
    @PostMapping("/api/admin/purchase-orders/{id}/close")
    @RequirePermission("inbound:create")
    @TenantOwnedResource("purchaseOrder")
    public ApiResponse<PurchaseOrderView> close(@PathVariable String id,
                                               @RequestBody(required = false) Map<String, String> body) {
        String reason = body == null ? null : body.get("reason");
        return ApiResponse.success(
                purchaseOrderService.close(id, reason, TenantContext.getTenantId(), currentOperator()));
    }

    /** 操作人（与入库单同法：安全上下文里的用户名，取不到就 system）。 */
    private static String currentOperator() {
        Authentication auth = SecurityContextHolder.getContext().getAuthentication();
        if (auth != null && auth.getPrincipal() instanceof SecurityUser securityUser) {
            return StringUtils.hasText(securityUser.getUsername())
                    ? securityUser.getUsername() : securityUser.getUserId();
        }
        return "system";
    }
}
