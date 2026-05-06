package com.aikf.admin.controller;

import com.aikf.admin.dto.*;
import com.aikf.admin.config.TenantContext;
import com.aikf.admin.entity.OrderLogistics;
import com.aikf.admin.service.OrderLogisticsService;
import com.aikf.admin.service.OrderService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.*;

/**
 * 订单管理控制器
 * 提供订单 CRUD、状态更新等管理接口
 */
@Slf4j
@RestController
@RequestMapping("/api/admin/orders")
@RequiredArgsConstructor
public class OrderController {

    private final OrderService orderService;
    private final OrderLogisticsService orderLogisticsService;

    /**
     * 分页查询订单列表
     *
     * GET /api/admin/orders?page=1&size=20&status=pending&keyword=xxx
     */
    @GetMapping
    public ApiResponse<PageResponse<OrderListResponse>> getOrders(
            @RequestParam(defaultValue = "1") long page,
            @RequestParam(defaultValue = "20") long size,
            @RequestParam(required = false) String status,
            @RequestParam(required = false) String keyword) {
        log.info("查询订单列表: page={}, size={}, status={}, keyword={}", page, size, status, keyword);
        Long tenantId = TenantContext.getTenantId();
        PageResponse<OrderListResponse> result = orderService.getOrderPage(page, size, status, keyword, tenantId);
        return ApiResponse.success(result);
    }

    /**
     * 查询订单详情
     *
     * GET /api/admin/orders/{id}
     */
    @GetMapping("/{id}")
    public ApiResponse<OrderDetailResponse> getOrderById(@PathVariable String id) {
        log.info("查询订单详情: id={}", id);
        OrderDetailResponse order = orderService.getOrderById(id);
        return ApiResponse.success(order);
    }

    /**
     * 创建订单
     *
     * POST /api/admin/orders
     */
    @PostMapping
    public ApiResponse<OrderDetailResponse> createOrder(@Valid @RequestBody OrderCreateRequest request) {
        log.info("创建订单: customerName={}", request.getCustomerName());
        Long tenantId = TenantContext.getTenantId();
        OrderDetailResponse order = orderService.createOrder(request, tenantId);
        return ApiResponse.success(order);
    }

    /**
     * 更新订单状态
     *
     * PUT /api/admin/orders/{id}/status
     */
    @PutMapping("/{id}/status")
    public ApiResponse<Void> updateOrderStatus(
            @PathVariable String id,
            @Valid @RequestBody OrderStatusUpdateRequest request) {
        log.info("更新订单状态: id={}, status={}", id, request.getStatus());
        orderService.updateOrderStatus(id, request.getStatus());
        return ApiResponse.success();
    }

    /**
     * 删除订单
     *
     * DELETE /api/admin/orders/{id}
     */
    @DeleteMapping("/{id}")
    public ApiResponse<Void> deleteOrder(@PathVariable String id) {
        log.info("删除订单: id={}", id);
        orderService.deleteOrder(id);
        return ApiResponse.success();
    }

    /**
     * 更新订单物流信息
     *
     * PUT /api/admin/orders/{id}/logistics
     */
    @PutMapping("/{id}/logistics")
    public ApiResponse<Void> updateLogistics(
            @PathVariable String id,
            @RequestBody java.util.Map<String, String> body) {
        log.info("更新订单物流: orderId={}", id);
        Long tenantId = TenantContext.getTenantId();

        // 检查订单是否存在
        orderService.getOrderById(id);

        String logisticsCompany = body.get("logisticsCompany");
        String trackingNo = body.get("trackingNo");

        // 查询现有物流记录
        java.util.List<OrderLogistics> existing = orderLogisticsService.getByOrderId(id);
        if (!existing.isEmpty()) {
            // 更新第一条物流记录
            OrderLogistics logistics = existing.get(0);
            if (logisticsCompany != null) logistics.setLogisticsCompany(logisticsCompany);
            if (trackingNo != null) logistics.setTrackingNo(trackingNo);
            orderLogisticsService.updateById(logistics);
        } else {
            // 创建新的物流记录
            OrderLogistics logistics = OrderLogistics.builder()
                    .tenantId(tenantId)
                    .orderId(id)
                    .logisticsCompany(logisticsCompany)
                    .trackingNo(trackingNo)
                    .status("in_transit")
                    .build();
            orderLogisticsService.save(logistics);
        }

        return ApiResponse.success();
    }
}
