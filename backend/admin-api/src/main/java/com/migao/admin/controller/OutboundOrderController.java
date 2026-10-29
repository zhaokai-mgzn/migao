package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.dto.OutboundOrderCreateRequest;
import com.migao.admin.dto.OutboundOrderView;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.security.SecurityUser;
import com.migao.admin.service.OutboundOrderService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.util.StringUtils;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

/**
 * 出库单 Controller（V196，issue #7750）—— 与入库单对称：列表 / 详情 / **建单（即过账）**。
 *
 * <p>权限码**复用**入库域的 {@code inbound:view} / {@code inbound:create}（零授权 delta）：
 * 仓管这个岗位既收也发；新造 {@code outbound:*} 今天没有任何角色持有 ⇒ 菜单与接口对所有人
 * 不可见（#4203 同族坑）。真要拆分收发权限时，那是独立的一单。</p>
 */
@Slf4j
@RestController
@RequestMapping("/api/admin/outbound-orders")
@RequiredArgsConstructor
public class OutboundOrderController {

    private final OutboundOrderService outboundOrderService;

    /**
     * 出库单列表（权限 inbound:view）
     * GET /api/admin/outbound-orders?keyword=&bizCategory=
     */
    @GetMapping
    @RequirePermission("stock:view")
    public ApiResponse<List<OutboundOrderView>> list(@RequestParam(required = false) String keyword,
                                                     @RequestParam(required = false) String bizCategory) {
        return ApiResponse.success(
                outboundOrderService.list(keyword, bizCategory, TenantContext.getTenantId()));
    }

    /**
     * 出库单详情（权限 inbound:view）
     * GET /api/admin/outbound-orders/{id}
     */
    @GetMapping("/{id}")
    @RequirePermission("stock:view")
    public ApiResponse<OutboundOrderView> detail(@PathVariable String id) {
        return ApiResponse.success(outboundOrderService.detail(id, TenantContext.getTenantId()));
    }

    /**
     * 建出库单（权限 inbound:create）—— **建单即过账**（出库单没有草稿态，见 V196 头注）。
     * POST /api/admin/outbound-orders
     */
    @PostMapping
    @RequirePermission("inbound:create")
    public ApiResponse<OutboundOrderView> create(@RequestBody OutboundOrderCreateRequest request) {
        return ApiResponse.success(outboundOrderService.createAndPost(
                request, TenantContext.getTenantId(), currentOperator()));
    }

    /** 操作人：登录用户名（手机号）；无认证上下文 = system（与入库单同口径）。 */
    private static String currentOperator() {
        Authentication auth = SecurityContextHolder.getContext().getAuthentication();
        if (auth != null && auth.getPrincipal() instanceof SecurityUser securityUser) {
            return StringUtils.hasText(securityUser.getUsername())
                    ? securityUser.getUsername() : securityUser.getUserId();
        }
        return "system";
    }
}
