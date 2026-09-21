package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.dto.InboundBatchView;
import com.migao.admin.dto.InboundOrderActionRequest;
import com.migao.admin.dto.InboundOrderCreateRequest;
import com.migao.admin.dto.InboundOrderLine;
import com.migao.admin.dto.InboundOrderResponse;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.security.SecurityUser;
import com.migao.admin.service.InboundOrderService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.util.StringUtils;
import org.springframework.web.bind.annotation.*;

import java.util.List;

/**
 * 入库单 Controller（V111，issue #5034）
 *
 * <p>端点：建单 / 列表 / 详情 / 动作（过账·作废）/ 批次查询。</p>
 */
@Slf4j
@RestController
@RequestMapping("/api/admin/inbound-orders")
@RequiredArgsConstructor
public class InboundOrderController {

    private final InboundOrderService inboundOrderService;

    /**
     * 入库单列表（权限 inbound:view）
     * GET /api/admin/inbound-orders?keyword=&status=
     */
    @GetMapping
    @RequirePermission("inbound:view")
    public ApiResponse<List<InboundOrderLine>> list(@RequestParam(required = false) String keyword,
                                                    @RequestParam(required = false) String status) {
        return ApiResponse.success(inboundOrderService.list(keyword, status, TenantContext.getTenantId()));
    }

    /**
     * 批次查询（权限 inbound:view）
     * GET /api/admin/inbound-orders/batches?skuId=&dyeLot=&inboundNo=
     */
    @GetMapping("/batches")
    @RequirePermission("inbound:view")
    public ApiResponse<List<InboundBatchView>> batches(@RequestParam(required = false) Long skuId,
                                                       @RequestParam(required = false) String dyeLot,
                                                       @RequestParam(required = false) String inboundNo) {
        return ApiResponse.success(
                inboundOrderService.batches(skuId, dyeLot, inboundNo, TenantContext.getTenantId()));
    }

    /**
     * 建单（权限 inbound:create）—— 草稿态，**不动库存**
     * POST /api/admin/inbound-orders
     */
    @PostMapping
    @RequirePermission("inbound:create")
    public ApiResponse<InboundOrderResponse> create(@RequestBody InboundOrderCreateRequest request) {
        return ApiResponse.success(
                inboundOrderService.create(request, TenantContext.getTenantId(), currentOperator()));
    }

    /**
     * 入库单详情（权限 inbound:view）
     * GET /api/admin/inbound-orders/{id}   id 可为 UUID / 入库单号 / 单号前缀
     */
    @GetMapping("/{id}")
    @RequirePermission("inbound:view")
    public ApiResponse<InboundOrderResponse> detail(@PathVariable String id) {
        return ApiResponse.success(inboundOrderService.detail(id, TenantContext.getTenantId()));
    }

    /**
     * 过账 / 作废（权限 inbound:create）
     * PATCH /api/admin/inbound-orders/{id}   action: post | cancel
     */
    @PatchMapping("/{id}")
    @RequirePermission("inbound:create")
    public ApiResponse<InboundOrderResponse> act(@PathVariable String id,
                                                 @RequestBody InboundOrderActionRequest request) {
        Long tenantId = TenantContext.getTenantId();
        String operator = currentOperator();
        String action = request == null ? null : request.getAction();
        if ("post".equalsIgnoreCase(action)) {
            return ApiResponse.success(inboundOrderService.post(id, tenantId, operator));
        }
        if ("cancel".equalsIgnoreCase(action)) {
            return ApiResponse.success(
                    inboundOrderService.cancel(id, request.getReason(), tenantId, operator));
        }
        throw BusinessException.validationError("action 只支持 post（过账）/ cancel（作废）");
    }

    /** 操作人：登录用户名（手机号）；无认证上下文 = system（同 StockLedgerService 口径） */
    private static String currentOperator() {
        Authentication auth = SecurityContextHolder.getContext().getAuthentication();
        if (auth != null && auth.getPrincipal() instanceof SecurityUser securityUser) {
            return StringUtils.hasText(securityUser.getUsername())
                    ? securityUser.getUsername() : securityUser.getUserId();
        }
        return "system";
    }
}
