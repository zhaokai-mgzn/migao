package com.migao.admin.controller;

import com.migao.admin.dto.ApiResponse;
import com.migao.admin.entity.Permission;
import com.migao.admin.config.TenantContext;
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
 */
@Slf4j
@RestController
@RequestMapping("/api/admin/permissions")
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
