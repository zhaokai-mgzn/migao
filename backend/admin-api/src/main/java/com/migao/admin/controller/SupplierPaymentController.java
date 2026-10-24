package com.migao.admin.controller;

import com.migao.admin.dto.ApiResponse;
import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.SupplierPaymentRequest;
import com.migao.admin.dto.SupplierPaymentView;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.security.TenantOwnedResource;
import com.migao.admin.security.SecurityUser;
import com.migao.admin.service.SupplierPaymentService;
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
 * 供应商付款端点（issue #7369，P0-1 段 3-B）。
 *
 * <p>权限码用**既有的** {@code finance:create} / {@code finance:view}：付款是财务动作，
 * 而这两个码今天已有岗位持有（不像新造码那样「无人持有 ⇒ 谁都点不动」）。</p>
 */
@RestController
@RequiredArgsConstructor
public class SupplierPaymentController {

    private final SupplierPaymentService supplierPaymentService;

    /** 登记付款（可选同时冲抵多张入库单）。 */
    @PostMapping("/api/admin/supplier-payments")
    @RequirePermission("finance:create")
    public ApiResponse<SupplierPaymentView> create(@RequestBody SupplierPaymentRequest request) {
        Long tenantId = TenantContext.getTenantId();
        return ApiResponse.success(supplierPaymentService.create(request, tenantId, currentOperator()));
    }

    /** 作废付款（留痕，不物理删）。 */
    @PostMapping("/api/admin/supplier-payments/{id}/void")
    @RequirePermission("finance:create")
    @TenantOwnedResource("supplierPayment")
    public ApiResponse<SupplierPaymentView> voidPayment(@PathVariable String id,
                                                       @RequestBody(required = false) Map<String, String> body) {
        Long tenantId = TenantContext.getTenantId();
        String reason = body == null ? null : body.get("reason");
        return ApiResponse.success(supplierPaymentService.voidPayment(id, reason, tenantId, currentOperator()));
    }

    /** 付款流水（可按供应商过滤）。 */
    /** 操作人（与入库单同法：安全上下文里的用户名，取不到就 system）。 */
    private static String currentOperator() {
        Authentication auth = SecurityContextHolder.getContext().getAuthentication();
        if (auth != null && auth.getPrincipal() instanceof SecurityUser securityUser) {
            return StringUtils.hasText(securityUser.getUsername())
                    ? securityUser.getUsername() : securityUser.getUserId();
        }
        return "system";
    }

    @GetMapping("/api/admin/supplier-payments")
    @RequirePermission("finance:view")
    public ApiResponse<List<SupplierPaymentView>> list(@RequestParam(required = false) String supplierId) {
        Long tenantId = TenantContext.getTenantId();
        return ApiResponse.success(supplierPaymentService.list(tenantId, supplierId));
    }
}
