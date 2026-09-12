package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.dto.ProcessingOrderGenerateRequest;
import com.migao.admin.dto.ProcessingOrderResponse;
import com.migao.admin.dto.ProcessingOrderUpdateRequest;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.service.ProcessingOrderService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.*;

import java.util.List;

/**
 * 加工单 Controller（issue #3340）
 * 供 admin-web 与米宝 Agent 共同调用。
 */
@Slf4j
@RestController
@RequestMapping("/api/admin/processing-orders")
@RequiredArgsConstructor
public class ProcessingOrderController {

    private final ProcessingOrderService processingOrderService;

    /**
     * 批量生成加工单（写操作，权限 processing:update）
     * POST /api/admin/processing-orders/generate
     */
    @PostMapping("/generate")
    @RequirePermission("processing:update")
    public ApiResponse<List<ProcessingOrderService.GenerateResult>> generate(
            @RequestBody ProcessingOrderGenerateRequest request) {
        Long tenantId = TenantContext.getTenantId();
        return ApiResponse.success(processingOrderService.generate(request.getOrderIds(), tenantId, null));
    }

    /**
     * 加工单列表（权限 processing:view）
     * GET /api/admin/processing-orders?keyword=&status=
     */
    @GetMapping
    @RequirePermission("processing:view")
    public ApiResponse<List<ProcessingOrderResponse>> list(
            @RequestParam(required = false) String keyword,
            @RequestParam(required = false) String status) {
        Long tenantId = TenantContext.getTenantId();
        return ApiResponse.success(processingOrderService.list(keyword, status, tenantId));
    }

    /**
     * 加工单详情（权限 processing:view）
     * GET /api/admin/processing-orders/{id}   id 可为 UUID/加工单号/订单号
     */
    @GetMapping("/{id}")
    @RequirePermission("processing:view")
    public ApiResponse<ProcessingOrderResponse> detail(@PathVariable String id) {
        Long tenantId = TenantContext.getTenantId();
        return ApiResponse.success(processingOrderService.getDetail(id, tenantId));
    }

    /**
     * 加工单状态更新（权限 processing:update）
     * PATCH /api/admin/processing-orders/{id}  action: issue/start/complete/cancel
     */
    @PatchMapping("/{id}")
    @RequirePermission("processing:update")
    public ApiResponse<ProcessingOrderResponse> update(@PathVariable String id,
                                                       @RequestBody ProcessingOrderUpdateRequest request) {
        Long tenantId = TenantContext.getTenantId();
        return ApiResponse.success(processingOrderService.updateStatus(id, request, tenantId, null));
    }
}
