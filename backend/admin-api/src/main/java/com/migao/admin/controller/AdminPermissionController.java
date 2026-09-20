package com.migao.admin.controller;

import com.migao.admin.dto.ApiResponse;
import com.migao.admin.entity.Permission;
import com.migao.admin.config.TenantContext;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.service.PermissionService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

/**
 * 权限管理控制器
 * 提供权限查询接口
 *
 * 前端路径前缀: /api/admin/permissions
 *
 * <p><b>权限（issue #4727 权限注解面审计）</b>：本端点此前**无任何 {@code @RequirePermission}**，
 * 而 {@code /api/admin/**} 对非 customer/agent 角色一律放行进入 ⇒ 最低权限员工可读取权限目录
 * （且本端点带写副作用：{@code ensureFullPermissionCatalog} 懒补种）。补 {@code system:manage}：
 * ① 唯一前端调用方是「岗位权限」页（{@code ROUTE_PERMISSION_MAP} 已要求 {@code system:manage}）；
 * ② 唯一 ai-agent 调用方是 {@code role_manage} 工具，其 {@code required_permissions} 本就是
 * {@code ["system:manage"]} ⇒ 两条既有调用链在注解落地后**逐字不变**（零回归）。</p>
 */
@Slf4j
@RestController
@RequestMapping("/api/admin/permissions")
@RequirePermission("system:manage")
@RequiredArgsConstructor
public class AdminPermissionController {

    private final PermissionService permissionService;

    /**
     * 查询所有权限列表
     *
     * GET /api/admin/permissions
     */
    @GetMapping
    public ApiResponse<List<Permission>> getPermissions() {
        Long tenantId = TenantContext.getTenantId();
        // RBAC 修复：存量租户懒补种完整权限目录（幂等），使角色管理页可勾选细粒度权限码
        if (tenantId != null && tenantId > 0) {
            int inserted = permissionService.ensureFullPermissionCatalog(tenantId);
            if (inserted > 0) {
                log.info("权限目录懒补种: tenantId={}, inserted={}", tenantId, inserted);
            }
        }
        List<Permission> permissions = permissionService.getAllPermissions();
        return ApiResponse.success(permissions);
    }
}
