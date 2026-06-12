package com.migao.admin.controller;

import com.migao.admin.dto.ApiResponse;
import com.migao.admin.entity.Permission;
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
        log.info("查询所有权限列表");
        List<Permission> permissions = permissionService.getAllPermissions();
        return ApiResponse.success(permissions);
    }
}
