package com.migao.admin.controller;

import com.migao.admin.dto.*;
import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.OrderLogistics;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.service.OrderLogisticsService;
import com.migao.admin.service.OrderService;
import com.migao.admin.service.OrderShipmentService;
import com.migao.admin.security.RequirePermission;
import jakarta.validation.Valid;
import java.math.BigDecimal;
import java.util.Map;
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
    private final OrderShipmentService orderShipmentService;

    // ==================== 字面路径（无路径变量） ====================

    /**
     * 分页查询订单列表
     *
     * GET /api/admin/orders?page=1&size=20&status=pending&keyword=xxx&followStatus=pending&hasProcessing=true&startDate=2025-01-01&endDate=2025-12-31
     */
    @RequirePermission("order:list")
    @GetMapping
    public ApiResponse<PageResponse<OrderListResponse>> getOrders(
            @RequestParam(defaultValue = "1") long page,
            @RequestParam(defaultValue = "20") long size,
            @RequestParam(required = false) String status,
            @RequestParam(required = false) String keyword,
            @RequestParam(required = false) String followStatus,
            @RequestParam(required = false) Boolean hasProcessing,
            @RequestParam(required = false) String startDate,
            @RequestParam(required = false) String endDate,
            @RequestParam(required = false) String orderId,
            @RequestParam(required = false) String receiver,
            @RequestParam(required = false) String productCode,
            @RequestParam(required = false) String productTitle,
            @RequestParam(required = false) String userId,
            // 制单人（issue #5835）：文本框**模糊**匹配 created_by_name 快照列
            @RequestParam(required = false) String creator) {
        log.info("查询订单列表: page={}, size={}, status={}, keyword={}, orderId={}, receiver={}, startDate={}, endDate={}", page, size, status, keyword, orderId, receiver, startDate, endDate);
        Long tenantId = TenantContext.getTenantId();
        PageResponse<OrderListResponse> result = orderService.getOrderPage(page, size, status, keyword, followStatus, hasProcessing, startDate, endDate, orderId, receiver, productCode, productTitle, tenantId, userId, creator);
        return ApiResponse.success(result);
    }

    /**
     * 创建订单
     *
     * POST /api/admin/orders
     */
    @RequirePermission("order:create")  // issue #5246 追加单：建单与改单是两种授权粒度
    @PostMapping
    public ApiResponse<OrderDetailResponse> createOrder(@Valid @RequestBody OrderCreateRequest request) {
        log.info("创建订单: customerName={}", request.getCustomerName());
        Long tenantId = TenantContext.getTenantId();
        OrderDetailResponse order = orderService.createOrder(request, tenantId);
        return ApiResponse.success(order);
    }

    /**
     * **修改待付款订单内容**（issue #5842；用户 2026-10-01 裁定「买家未付款的订单要允许修改」）。
     *
     * <pre>PUT /api/admin/orders/{id}/content</pre>
     *
     * <p>改三面：收货信息（姓名/电话/地址）+ 商品明细（商品/数量/单价/宽高）+ 加工项；
     * 金额**服务端重算**（请求体里根本没有小计/总额字段 —— 见 {@link OrderContentUpdateRequest}）。</p>
     *
     * <p>🔴 <b>只有 {@code pending}（待付款）可改，其余状态 422 + 中文文案</b>
     * （判定 = {@code OrderStatusTransitions.assertContentEditable}，状态机唯一实现点）。
     * 权限码复用既有写码 {@code order:update}（与 status / payment / cancel / remark 同码，
     * 不新造权限）；{@code order:create} 是**建单**粒度，改单属于"改"。</p>
     */
    @RequirePermission("order:update")
    @PutMapping("/{id:[0-9a-fA-F-]+}/content")
    public ApiResponse<OrderDetailResponse> updateOrderContent(
            @PathVariable String id,
            @Valid @RequestBody OrderContentUpdateRequest request) {
        log.info("修改订单内容: id={}, customerName={}, items={}",
                id, request.getCustomerName(), request.getItems() != null ? request.getItems().size() : 0);
        return ApiResponse.success(orderService.updatePendingOrderContent(id, request));
    }

    /**
     * 获取订单统计
     *
     * GET /api/admin/orders/statistics
     */
    @RequirePermission("order:list")
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
    @RequirePermission("order:list")
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
    @RequirePermission("order:list")
    @GetMapping("/{id:[0-9a-fA-F-]+}")
    public ApiResponse<OrderDetailResponse> getOrderById(@PathVariable String id) {
        log.info("查询订单详情: id={}", id);
        OrderDetailResponse order = orderService.getOrderById(id);
        return ApiResponse.success(order);
    }

    /**
     * 查询订单的**发货读面**（发货单 + 逐行**实发**套/件/卷 + 汇总）—— issue #5651 收口。
     *
     * <pre>GET /api/admin/orders/{id}/shipments</pre>
     *
     * <h3>它补的是哪个洞（issue #5651 原话：「挂链差一步且原因已实测」）</h3>
     * <p>{@code order_shipment_items}（issue #5648）是「这一单实际发了多少」的<b>唯一真值载体</b>，
     * 但落地时只有<b>工人读面</b>（{@code GET /api/worker/shipment/orders/{orderId}}，工人 session
     * 准入）⇒ 跑在 admin-web 的销售单（三联纸 241mm × 140mm）拿不到实发数量，数量列只能退回
     * 订单行数量。<b>本端点就是那一步</b>。</p>
     *
     * <h3>🔴 响应形状：与工人读面**逐字同源**，不新造第二套</h3>
     * <p>直接回 {@link OrderShipmentService#readShipment}（该表 owner 指定的消费入口）——
     * 两个面共用一份实现 ⇒ 工人 H5 与桌面纸面看到的实发数量逐字相同。任何"顺手改一下字段名"
     * 都会让两份投影分叉（守卫：{@code tests/unit_ci_workflows/test_shipment_read_surface_guard.py}）。</p>
     *
     * <h3>🔴 权限码 = {@code order:list}（取**既有**码，不新造）</h3>
     * <p>与<b>同页既有读面</b> {@link #getOrderById} 同码：订单详情页读得开、页内单据读不开
     * 是比"没有读面"更坏的形态。#4727 权限注解面审计的口径是「该放行的登记为有意放行」，
     * 而本面<b>有</b>语义正确的既有码 ⇒ 挂注解、<b>不</b>登记豁免（漏注解会被
     * {@code test_agent_permission_parity.py} 判据 8 判红）。</p>
     * <p>{@code order:detail} 今天只是菜单节点码（{@code MenuController} / {@code RegistrationService}
     * 里的目录项），<b>没有任何端点在承载</b>；把新读面露挂在它上面等于凭空给一个菜单节点赋予
     * 端点语义，需连带岗位默认权限 / 菜单 / 目录多处对齐 ⇒ 不属本单范围。</p>
     *
     * <h3>🔴 租户隔离：跨租户 = <b>404</b>（不是 403），且与「订单不存在」逐字同一形态</h3>
     * <p>403 等于承认「这个 id 存在，只是不给你看」= 存在性泄露（P2 刚落的口径）。
     * 判定在 {@link OrderShipmentService#readShipment} 内（{@code loadOrder}）：
     * 订单查不到与租户不匹配走<b>同一个</b> {@code BusinessException.notFound("订单")}。</p>
     *
     * <p><b>只读</b>：本单只补读面，不新增任何写面（写面归 #5648 的 {@code /api/worker/shipment/**}）。</p>
     */
    @RequirePermission("order:list")
    @GetMapping("/{id:[0-9a-fA-F-]+}/shipments")
    public ApiResponse<Map<String, Object>> getOrderShipments(@PathVariable String id) {
        log.info("查询订单发货读面: id={}", id);
        return ApiResponse.success(orderShipmentService.readShipment(id, TenantContext.getTenantId()));
    }

    /**
     * 更新订单状态
     *
     * PUT /api/admin/orders/{id}/status
     *
     * issue #5246 追加单：改状态是**写** ⇒ order:update（原挂在读码 order:list 上，
     * 于是「能看订单列表」=「能改状态/取消/删除」，只读持有者被动拿到写能力）。
     */
    @RequirePermission("order:update")
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
    @RequirePermission("order:update")
    @PutMapping("/{id:[0-9a-fA-F-]+}/payment")
    public ApiResponse<Void> confirmPayment(@PathVariable String id) {
        log.info("确认支付: orderId={}", id);
        orderService.confirmPayment(id);
        return ApiResponse.success();
    }

    /**
     * 取消/关闭订单
     *
     * PUT /api/admin/orders/{id}/cancel
     * Body: { "closeReason": "缺货" } (可选)
     */
    @RequirePermission("order:update")  // issue #5246：取消是写（同 status/payment）
    @PutMapping("/{id:[0-9a-fA-F-]+}/cancel")
    public ApiResponse<Void> cancelOrder(
            @PathVariable String id,
            @RequestBody(required = false) java.util.Map<String, String> body) {
        String closeReason = (body != null && body.containsKey("closeReason")) ? body.get("closeReason") : null;
        log.info("取消订单: orderId={}, closeReason={}", id, closeReason);
        orderService.cancelOrder(id, closeReason);
        return ApiResponse.success();
    }

    /**
     * 添加订单备注
     *
     * POST /api/admin/orders/{id}/remark
     * Body: { "content": "备注内容" }
     */
    @RequirePermission("order:update")  // issue #5246：写备注是写
    @PostMapping("/{id:[0-9a-fA-F-]+}/remark")
    public ApiResponse<Void> addRemark(
            @PathVariable String id,
            @RequestBody java.util.Map<String, String> body) {
        String content = (body != null && body.containsKey("content")) ? body.get("content") : null;
        log.info("添加订单备注: orderId={}", id);
        orderService.addRemark(id, content);
        return ApiResponse.success();
    }

    /**
     * 退款
     *
     * PUT /api/admin/orders/{id}/refund
     * body 可选字段：refund_reason（退款原因）、refund_amount（退款金额，缺省=全额）
     */
    @RequirePermission("order:refund")
    @PutMapping("/{id:[0-9a-fA-F-]+}/refund")
    public ApiResponse<Void> refundOrder(@PathVariable String id,
                                         @RequestBody(required = false) Map<String, Object> body) {
        String refundReason = null;
        BigDecimal refundAmount = null;
        if (body != null) {
            if (body.containsKey("refund_reason")) {
                Object reason = body.get("refund_reason");
                if (reason != null && !reason.toString().isBlank()) {
                    refundReason = reason.toString().trim();
                }
            }
            if (body.containsKey("refund_amount")) {
                Object amount = body.get("refund_amount");
                if (amount != null && !amount.toString().isBlank()) {
                    try {
                        refundAmount = new BigDecimal(amount.toString().trim());
                    } catch (NumberFormatException e) {
                        throw BusinessException.validationError("退款金额格式不正确");
                    }
                }
            }
        }
        log.info("退款: orderId={}, refundAmount={}, refundReason={}", id, refundAmount, refundReason);
        orderService.refundOrder(id, refundAmount, refundReason);
        return ApiResponse.success();
    }

    /**
     * 获取订单跟进状态
     *
     * GET /api/admin/orders/{id}/follow-status
     */
    @RequirePermission("order:list")
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
    @RequirePermission("order:update")  // issue #5246：改跟进状态是写（其 GET 仍是 order:list）
    @PutMapping("/{id:[0-9a-fA-F-]+}/follow-status")
    public ApiResponse<Void> updateFollowStatus(
            @PathVariable String id,
            @Valid @RequestBody FollowStatusUpdateRequest request) {
        log.info("更新跟进状态: orderId={}, followStatus={}", id, request.getFollowStatus());
        orderService.updateFollowStatus(id, request.getFollowStatus());
        return ApiResponse.success();
    }

    /**
     * 更新订单级**加急标记 / 客户要求到货日**（V120，issue #5177）。
     *
     * <p>PUT /api/admin/orders/{id}/urgency</p>
     *
     * <p>权限复用 {@code order:list}（与订单其它写面 {@code follow-status} / {@code remark}
     * 同码，不新造权限点 —— 新权限点需要配角色/种子数据，本单不含权限模型变更）。</p>
     *
     * <p>🔴 两个字段**各自**遵循「不传 = 不改」；{@code requiredDeliveryDate} 传**空串**才表示
     * 清空（见 {@link OrderUrgencyUpdateRequest} 的三态语义）。</p>
     */
    // issue #5246 追加单：第 8 个写动作（加急 + 到货日，V120）此前也挂在读码 `order:list` 上
    // —— 与 status/logistics/cancel 同类，一并收口到写码 `order:update`。
    @RequirePermission("order:update")
    @PutMapping("/{id:[0-9a-fA-F-]+}/urgency")
    public ApiResponse<Void> updateUrgency(
            @PathVariable String id,
            @RequestBody OrderUrgencyUpdateRequest request) {
        log.info("更新订单加急/到货日: orderId={}, isUrgent={}, requiredDeliveryDate={}",
                id, request.getIsUrgent(), request.getRequiredDeliveryDate());
        orderService.updateUrgency(id, request.getIsUrgent(), request.getRequiredDeliveryDate());
        return ApiResponse.success();
    }

    /**
     * 删除订单
     *
     * DELETE /api/admin/orders/{id}
     */
    @RequirePermission("order:update")  // issue #5246：删除订单是写
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
    @RequirePermission("order:update")  // issue #5246：改物流是写
    @PutMapping("/{id:[0-9a-fA-F-]+}/logistics")
    public ApiResponse<Void> updateLogistics(
            @PathVariable String id,
            @RequestBody java.util.Map<String, String> body) {
        log.info("更新订单物流: orderId={}", id);
        Long tenantId = TenantContext.getTenantId();

        // 检查订单是否存在并校验状态
        OrderDetailResponse orderDetail = orderService.getOrderById(id);
        String orderStatus = orderDetail.getStatus();
        if (!"shipped".equals(orderStatus) && !"confirmed".equals(orderStatus) && !"producing".equals(orderStatus)) {
            throw com.migao.admin.exception.BusinessException.validationError(
                    "仅已确认/生产中/已发货状态可更新物流，当前状态: " + orderStatus);
        }

        String logisticsCompany = body.get("logisticsCompany");
        String trackingNo = body.get("trackingNo");
        String logisticsType = body.get("logisticsType"); // express / logistics（issue #3984，V47）
        // 发货人（issue #3768）：显式传入优先，否则取当前登录用户姓名兜底
        String providedShipper = body.get("shipperName");
        String shipperName = orderService.resolveShipperName(providedShipper);

        // 查询现有物流记录
        java.util.List<OrderLogistics> existing = orderLogisticsService.getByOrderId(id);
        if (!existing.isEmpty()) {
            // 更新第一条物流记录
            OrderLogistics logistics = existing.get(0);
            if (logisticsCompany != null) logistics.setLogisticsCompany(logisticsCompany);
            if (trackingNo != null) logistics.setTrackingNo(trackingNo);
            if (logisticsType != null) logistics.setLogisticsType(logisticsType);
            // 仅显式传入才覆盖：改运单号/纠错 ≠ 换发货人，也不为存量历史订单猜经手人
            if (org.springframework.util.StringUtils.hasText(providedShipper)) {
                logistics.setShipperName(shipperName);
            }
            orderLogisticsService.updateById(logistics);
        } else {
            // 创建新的物流记录
            OrderLogistics logistics = OrderLogistics.builder()
                    .tenantId(tenantId)
                    .orderId(id)
                    .logisticsCompany(logisticsCompany)
                    .trackingNo(trackingNo)
                    .logisticsType(logisticsType != null ? logisticsType : "express")
                    .shipperName(shipperName)
                    .status("in_transit")
                    .build();
            orderLogisticsService.save(logistics);
        }

        return ApiResponse.success();
    }
}
