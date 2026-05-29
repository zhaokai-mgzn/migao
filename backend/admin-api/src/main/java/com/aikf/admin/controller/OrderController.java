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
 * 提供订单 CRUD、状态更新、支付/取消/退款等管理接口
 *
 * 路由设计说明：
 * - 所有 {id} 路径变量添加正则约束 [0-9a-fA-F-]+，仅匹配 UUID 格式
 * - 避免 "statistics"、"follow-status" 等字面路径被 {id} 误匹配
 * - 字面路径声明在参数化路径之前，确保路由优先级正确
 */
@Slf4j
@RestController
@RequestMapping("/api/admin/orders")
@RequiredArgsConstructor
public class OrderController {

    private final OrderService orderService;
    private final OrderLogisticsService orderLogisticsService;

    // ==================== 字面路径（无路径变量） ====================

    /**
     * 分页查询订单列表
     *
     * GET /api/admin/orders?page=1&size=20&status=pending&keyword=xxx&followStatus=pending
     */
    @GetMapping
    public ApiResponse<PageResponse<OrderListResponse>> getOrders(
            @RequestParam(defaultValue = "1") long page,
            @RequestParam(defaultValue = "20") long size,
            @RequestParam(required = false) String status,
            @RequestParam(required = false) String keyword,
            @RequestParam(required = false) String followStatus) {
        log.info("查询订单列表: page={}, size={}, status={}, keyword={}, followStatus={}", page, size, status, keyword, followStatus);
        Long tenantId = TenantContext.getTenantId();
        PageResponse<OrderListResponse> result = orderService.getOrderPage(page, size, status, keyword, followStatus, tenantId);
        return ApiResponse.success(result);
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
     * 获取订单统计
     *
     * GET /api/admin/orders/statistics
     */
    @GetMapping("/statistics")
    public ApiResponse<OrderStatisticsResponse> getOrderStatistics() {
        log.info("获取订单统计");
        Long tenantId = TenantContext.getTenantId();
        OrderStatisticsResponse statistics = orderService.getOrderStatistics(tenantId);
        return ApiResponse.success(statistics);
    }

    /**
     * 获取跟进状态统计
     *
     * GET /api/admin/orders/follow-status/stats
     */
    @GetMapping("/follow-status/stats")
    public ApiResponse<FollowStatusStatsResponse> getFollowStatusStats() {
        log.info("获取跟进状态统计");
        Long tenantId = TenantContext.getTenantId();
        FollowStatusStatsResponse stats = orderService.getFollowStatusStats(tenantId);
        return ApiResponse.success(stats);
    }

    // ==================== 参数化路径（含 {id} 路径变量） ====================

    /**
     * 查询订单详情
     *
     * GET /api/admin/orders/{id}
     */
    @GetMapping("/{id:[0-9a-fA-F-]+}")
    public ApiResponse<OrderDetailResponse> getOrderById(@PathVariable String id) {
        log.info("查询订单详情: id={}", id);
        OrderDetailResponse order = orderService.getOrderById(id);
        return ApiResponse.success(order);
    }

    /**
     * 更新订单状态
     *
     * PUT /api/admin/orders/{id}/status
     */
    @PutMapping("/{id:[0-9a-fA-F-]+}/status")
    public ApiResponse<Void> updateOrderStatus(
            @PathVariable String id,
            @Valid @RequestBody OrderStatusUpdateRequest request) {
        log.info("更新订单状态: id={}, status={}", id, request.getStatus());
        orderService.updateOrderStatus(id, request.getStatus());
        return ApiResponse.success();
    }

    /**
     * 确认支付
     *
     * PUT /api/admin/orders/{id}/payment
     */
    @PutMapping("/{id:[0-9a-fA-F-]+}/payment")
    public ApiResponse<Void> confirmPayment(@PathVariable String id) {
        log.info("确认支付: orderId={}", id);
        orderService.confirmPayment(id);
        return ApiResponse.success();
    }

    /**
     * 取消订单
     *
     * PUT /api/admin/orders/{id}/cancel
     */
    @PutMapping("/{id:[0-9a-fA-F-]+}/cancel")
    public ApiResponse<Void> cancelOrder(@PathVariable String id) {
        log.info("取消订单: orderId={}", id);
        orderService.cancelOrder(id);
        return ApiResponse.success();
    }

    /**
     * 退款
     *
     * PUT /api/admin/orders/{id}/refund
     */
    @PutMapping("/{id:[0-9a-fA-F-]+}/refund")
    public ApiResponse<Void> refundOrder(@PathVariable String id) {
        log.info("退款: orderId={}", id);
        orderService.refundOrder(id);
        return ApiResponse.success();
    }

    /**
     * 获取订单跟进状态
     *
     * GET /api/admin/orders/{id}/follow-status
     */
    @GetMapping("/{id:[0-9a-fA-F-]+}/follow-status")
    public ApiResponse<FollowStatusResponse> getFollowStatus(@PathVariable String id) {
        log.info("获取订单跟进状态: orderId={}", id);
        FollowStatusResponse response = orderService.getFollowStatus(id);
        return ApiResponse.success(response);
    }

    /**
     * 更新跟进状态
     *
     * PUT /api/admin/orders/{id}/follow-status
     */
    @PutMapping("/{id:[0-9a-fA-F-]+}/follow-status")
    public ApiResponse<Void> updateFollowStatus(
            @PathVariable String id,
            @Valid @RequestBody FollowStatusUpdateRequest request) {
        log.info("更新跟进状态: orderId={}, followStatus={}", id, request.getFollowStatus());
        orderService.updateFollowStatus(id, request.getFollowStatus());
        return ApiResponse.success();
    }

    /**
     * 删除订单
     *
     * DELETE /api/admin/orders/{id}
     */
    @DeleteMapping("/{id:[0-9a-fA-F-]+}")
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
    @PutMapping("/{id:[0-9a-fA-F-]+}/logistics")
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
