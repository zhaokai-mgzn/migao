package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.dto.PageResponse;
import com.migao.admin.entity.Role;
import com.migao.admin.service.RoleService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

/**
 * 角色管理控制器
 * 提供角色 CRUD、权限分配等管理接口
 *
 * 前端路径前缀: /api/admin/roles
 */
@Slf4j
@RestController
@RequestMapping("/api/admin/roles")
@RequiredArgsConstructor
public class AdminRoleController {

    private final RoleService roleService;

    /**
     * 分页查询角色列表
     *
     * GET /api/admin/roles?page=1&size=10&keyword=xxx
     */
    @GetMapping
    public ApiResponse<PageResponse<Role>> getRoles(
            @RequestParam(defaultValue = "1") long page,
            @RequestParam(defaultValue = "100") long size,
            @RequestParam(required = false) String keyword) {
        Long tenantId = TenantContext.getTenantId();
        log.info("查询角色列表: page={}, size={}, keyword={}, tenantId={}", page, size, keyword, tenantId);
        PageResponse<Role> result = roleService.getRolePage(page, size, keyword, tenantId);
        return ApiResponse.success(result);
    }

    /**
     * 查询所有角色（不分页，用于下拉选择）
     *
     * GET /api/admin/roles/all
     */
    @GetMapping("/all")
    public ApiResponse<List<Role>> getAllRoles() {
        Long tenantId = TenantContext.getTenantId();
        log.info("查询所有角色: tenantId={}", tenantId);
        List<Role> roles = roleService.getAllRoles(tenantId);
        return ApiResponse.success(roles);
    }

    /**
     * 查询角色详情
     *
     * GET /api/admin/roles/{id}
     */
    @GetMapping("/{id}")
    public ApiResponse<Role> getRole(@PathVariable String id) {
        log.info("查询角色详情: id={}", id);
        Role role = roleService.getRoleById(id);
        return ApiResponse.success(role);
    }

    /**
     * 创建角色
     *
     * POST /api/admin/roles
     * Body: { "name": "xxx", "code": "xxx", "description": "xxx", "permissionIds": [] }
     */
    @PostMapping
    public ApiResponse<Role> createRole(@RequestBody Map<String, Object> body) {
        Long tenantId = TenantContext.getTenantId();
        String name = (String) body.get("name");
        String code = (String) body.get("code");
        String description = (String) body.get("description");

        log.info("创建角色: name={}, code={}, tenantId={}", name, code, tenantId);
        Role role = roleService.createRole(name, code, description, tenantId);
        return ApiResponse.success(role);
    }

    /**
     * 更新角色
     *
     * PUT /api/admin/roles/{id}
     * Body: { "name": "xxx", "description": "xxx", "permissionIds": [] }
     */
    @PutMapping("/{id}")
    public ApiResponse<Role> updateRole(@PathVariable String id, @RequestBody Map<String, Object> body) {
        String name = (String) body.get("name");
        String description = (String) body.get("description");

        log.info("更新角色: id={}, name={}", id, name);
        Role role = roleService.updateRole(id, name, description);
        return ApiResponse.success(role);
    }

    /**
     * 删除角色
     *
     * DELETE /api/admin/roles/{id}
     */
    @DeleteMapping("/{id}")
    public ApiResponse<Void> deleteRole(@PathVariable String id) {
        log.info("删除角色: id={}", id);
        roleService.deleteRole(id);
        return ApiResponse.success();
    }
}
