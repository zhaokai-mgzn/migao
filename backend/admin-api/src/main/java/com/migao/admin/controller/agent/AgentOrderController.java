package com.migao.admin.controller.agent;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.dto.OrderDetailResponse;
import com.migao.admin.dto.agent.AgentOrderCreateRequest;
import com.migao.admin.dto.agent.AgentOrderResolveResponse;
import com.migao.admin.dto.agent.AgentOrderUpdateRequest;
import com.migao.admin.service.OrderService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.*;

/**
 * Agent 专用订单管理控制器。
 * 与表单 API (/api/admin/orders) 的关键差异：
 * - ID 可传 UUID 或订单号（ORD-xxx），服务端自动解析
 * - 统一 PATCH 端点（一个接口覆盖 status/logistics/payment/cancel/refund）
 * - 提供订单号→UUID 解析端点
 */
@Slf4j
@RestController
@RequestMapping("/api/admin/agent/orders")
@RequiredArgsConstructor
public class AgentOrderController {

    private final OrderService orderService;

    /**
     * Agent 专用创建订单。
     * POST /api/admin/agent/orders
     * subtotal 服务端按 quantity × unitPrice 强制重算。
     */
    @PostMapping
    public ApiResponse<OrderDetailResponse> createOrder(@RequestBody AgentOrderCreateRequest request) {
        Long tenantId = TenantContext.getTenantId();
        log.info("[Agent] 创建订单: customer={}, items={}, tenantId={}",
                request.getCustomerName(),
                request.getItems() != null ? request.getItems().size() : 0, tenantId);
        try {
            OrderDetailResponse result = orderService.createOrderForAgent(request, tenantId);
            return ApiResponse.success(result);
        } catch (Exception e) {
            log.warn("[Agent] 创建订单失败: {}", e.getMessage());
            throw e;
        }
    }

    /**
     * Agent 专用统一订单更新。
     * PATCH /api/admin/agent/orders/{id}
     * id 可为 UUID 或订单号（ORD-xxx），服务端自动解析。
     */
    @PatchMapping("/{id}")
    public ApiResponse<OrderDetailResponse> updateOrder(@PathVariable String id,
                                                         @RequestBody AgentOrderUpdateRequest request) {
        Long tenantId = TenantContext.getTenantId();
        log.info("[Agent] 更新订单: id={}, action={}, tenantId={}", id, request.getAction(), tenantId);
        try {
            Object result = orderService.updateOrderForAgent(id, request, tenantId);
            return ApiResponse.success((OrderDetailResponse) result);
        } catch (Exception e) {
            log.warn("[Agent] 更新订单失败: id={}, error={}", id, e.getMessage());
            throw e;
        }
    }

    /**
     * 解析订单号/UUID/关键词 → 订单摘要。
     * GET /api/admin/agent/orders/resolve?keyword=ORD-xxx
     */
    @GetMapping("/resolve")
    public ApiResponse<AgentOrderResolveResponse> resolveOrder(@RequestParam String keyword) {
        Long tenantId = TenantContext.getTenantId();
        log.info("[Agent] 解析订单: keyword={}, tenantId={}", keyword, tenantId);
        try {
            AgentOrderResolveResponse result = orderService.resolveOrderId(keyword, tenantId);
            return ApiResponse.success(result);
        } catch (Exception e) {
            log.warn("[Agent] 解析订单失败: keyword={}, error={}", keyword, e.getMessage());
            throw e;
        }
    }
}
