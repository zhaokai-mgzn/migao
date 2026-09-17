package com.migao.admin.controller.agent;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.dto.OrderDetailResponse;
import com.migao.admin.dto.OrderListResponse;
import com.migao.admin.dto.PageResponse;
import com.migao.admin.dto.agent.AgentOrderCreateRequest;
import com.migao.admin.dto.agent.AgentOrderResolveResponse;
import com.migao.admin.dto.agent.AgentOrderUpdateRequest;
import com.migao.admin.security.SecurityUser;
import com.migao.admin.security.PermissionInterceptor;
import com.migao.admin.service.ClientRequestIdService;
import com.migao.admin.service.OrderService;
import com.migao.admin.security.RequirePermission;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.bind.annotation.*;

/**
 * Agent 专用订单管理控制器。
 * 与表单 API (/api/admin/orders) 的关键差异：
 * - ID 可传 UUID 或订单号（ORD-xxx），服务端自动解析
 * - 统一 PATCH 端点（一个接口覆盖 status/logistics/payment/cancel/refund）
 * - 提供订单号→UUID 解析端点
 *
 * <p>类级 {@code @RequirePermission("order:list")} 覆盖全部 action；**退款**是唯一的例外：
 * 它额外要求 {@code order:refund}（见 {@link #updateOrder}），与表单路径
 * {@code OrderController} 的退款路由同码。</p>
 */
@Slf4j
@RequirePermission("order:list")
@RestController
@RequestMapping("/api/admin/agent/orders")
@RequiredArgsConstructor
public class AgentOrderController {

    private final OrderService orderService;
    private final com.migao.admin.mapper.UserMapper userMapper;
    /**
     * 权限判定复用点（issue #4148）：统一 PATCH 里的 action 级权限复检。
     * 不在此类另写授权逻辑 —— 见 {@link PermissionInterceptor#requirePermission(String)}。
     */
    private final PermissionInterceptor permissionInterceptor;

    /**
     * Agent 专用创建订单。
     * POST /api/admin/agent/orders
     *
     * <p>`@Valid`（issue #3622，收敛于 #4089）：请求类型 {@link AgentOrderCreateRequest} 是表单路径
     * {@code OrderCreateRequest} 的**子类型**（只多一个幂等键），故两条路径共用同一组 Bean Validation
     * 约束与同一条文案 —— 这里是真的执行点，Service 不再手工 {@code new} 一个 DTO 再判一遍
     * （那正是「校验双写」）。校验失败由 {@code GlobalExceptionHandler} 统一返回 422
     * VALIDATION_ERROR（与表单路径 `/api/admin/orders` 同口径）。</p>
     *
     * <p>幂等键（issue #4037）：请求头 {@code X-Client-Request-Id} 透传到
     * {@link AgentOrderCreateRequest#getClientRequestId()}，由
     * {@code OrderService#createOrderForAgent} 做 (tenantId, 键) 去重与结果回放。
     * **缺省不报错**（向后兼容未升级的调用方，走原路径）。</p>
     */
    @PostMapping
    public ApiResponse<OrderDetailResponse> createOrder(
            @Valid @RequestBody AgentOrderCreateRequest request,
            @RequestHeader(value = ClientRequestIdService.HEADER, required = false) String clientRequestId) {
        Long tenantId = TenantContext.getTenantId();
        // C 端数据隔离：绑定当前真实用户（ServiceTokenFilter 从 X-User-Id 透传）
        request.setUserId(currentUserId());
        // 幂等键只认请求头（DTO 上 @JsonIgnore ⇒ body 里的同名字段被忽略，无法伪造）
        request.setClientRequestId(clientRequestId);
        log.info("[Agent] 创建订单: customer={}, items={}, tenantId={}, userId={}, clientRequestId={}",
                request.getCustomerName(),
                request.getItems() != null ? request.getItems().size() : 0, tenantId,
                request.getUserId(), clientRequestId);
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
     *
     * <p><b>action 级权限复检（issue #4148）</b>：本类只有类级 {@code order:list}，而这一个
     * 入口覆盖 status/logistics/payment/cancel/<b>refund</b> ⇒ 不复检就等于「仅持 order:list 的
     * 商户员工（内置岗位 customer_service/sales/finance 都没有 order:refund）可借米宝退款」，
     * 与表单路径 {@code OrderController} 的 {@code order:refund} 口径不一致。
     * 判据与类级注解**同一处**（{@link PermissionInterceptor#requirePermission(String)}）：
     * 旁路角色（平台管理员/内部服务）、{@code *} 通配、取码来源逐条一致；其余 action 不收窄。</p>
     */
    @PatchMapping("/{id}")
    public ApiResponse<OrderDetailResponse> updateOrder(@PathVariable String id,
                                                         @RequestBody AgentOrderUpdateRequest request) {
        if ("refund".equals(request.getAction())) {
            permissionInterceptor.requirePermission("order:refund");
        }
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

    /**
     * C 端（小布/customer 角色）"我的订单"查询。
     * GET /api/admin/agent/orders/mine?page=1&size=10&status=shipped
     *
     * 数据隔离强制点：无论调用方传什么筛选参数，都强制按当前登录用户（X-User-Id
     * 透传的 SecurityUser.userId）过滤，用户只能看到自己的订单。
     * 缺省 userId（内部服务占位）时直接拒绝，避免跨用户数据泄露。
     */
    @GetMapping("/mine")
    public ApiResponse<PageResponse<OrderListResponse>> getMyOrders(
            @RequestParam(defaultValue = "1") long page,
            @RequestParam(defaultValue = "10") long size,
            @RequestParam(required = false) String status) {
        Long tenantId = TenantContext.getTenantId();
        String userId = currentUserId();
        if (userId == null || userId.isBlank() || "internal-service".equals(userId)) {
            log.warn("[Agent] 拒绝 C 端订单查询: 缺少真实用户标识 tenantId={}", tenantId);
            throw com.migao.admin.exception.BusinessException.authFailed("缺少用户标识，无法查询订单");
        }
        log.info("[Agent] 查询我的订单: userId={}, page={}, size={}, status={}, tenantId={}",
                userId, page, size, status, tenantId);
        // 取当前用户已绑定手机号（用于名下商户代录订单的 phone 兜底；未绑定则仅 user_id 匹配）
        String userPhone = null;
        try {
            com.migao.admin.entity.User currentUser = userMapper.selectById(userId);
            if (currentUser != null && org.springframework.util.StringUtils.hasText(currentUser.getPhone())) {
                userPhone = currentUser.getPhone();
            }
        } catch (Exception e) {
            log.warn("[Agent] 查询当前用户手机号失败（不影响 user_id 直配查询）: userId={}", userId);
        }
        // 强制用户隔离 + 仅允许状态筛选（不允许 keyword/receiver 等模糊条件，避免跨用户试探）；
        // phone 兜底仅作用于 user_id IS NULL 且 customer_phone=本人绑定号的订单（商户代录/历史订单）
        PageResponse<OrderListResponse> result = orderService.getMyOrderPage(
                page, size, status, tenantId, userId, userPhone);
        return ApiResponse.success(result);
    }

    /** 从 SecurityContext 提取当前真实用户 ID（ServiceTokenFilter 已透传 X-User-Id） */
    private String currentUserId() {
        Authentication authentication = SecurityContextHolder.getContext().getAuthentication();
        if (authentication != null && authentication.getPrincipal() instanceof SecurityUser securityUser) {
            return securityUser.getUserId();
        }
        return null;
    }
}
