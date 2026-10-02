package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.dto.PageResponse;
import com.migao.admin.entity.Role;
import com.migao.admin.security.RequirePermission;
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

    // issue #5246（审计裁定「该放行」）曾被读成「三个 GET 一律不加注解」；issue #5980 按
    // `docs/wiki/RBAC.md` 的「放行策略现状」分支 ③（没有 `@RequirePermission` = 对**所有**商户员工开放，
    // 含 0 权限岗位）**收紧读面**，逐调用方核对后取**覆盖面最小但足够**的既有读码：
    //   · `GET /roles` → `system:view`
    //     —— 它是「岗位权限」页（`/roles`）的**第一屏**读端点（`roleApi.getRoles()`），
    //        而该页的节点码/路由守卫码就是 `system:view` ⇒ **该页回显零回归**；
    //   · `GET /roles/all` → `employee:list`
    //     —— 唯一调用方是「员工管理」页的岗位下拉（`employeeApi.loadPositions()`），
    //        而该页的节点码/路由守卫码就是 `employee:list` ⇒ **岗位下拉零回归**；
    //        （取 `system:view` 会让**运营**——持 `employee:list`、不持 `system:view`——的下拉变空）
    //   · `GET /roles/{id}` → `system:view`（「岗位权限」页回显，同上）。
    // ⚠️ `/roles`·`/roles/all` 因此对米宝 `role_manage` 工具构成**跨码**（该工具挂「岗位权限」页、
    // 声明 `system:view`）⇒ 具名登记在
    // `tests/unit_ci_workflows/test_agent_permission_parity.py` 的 `CODE_DIVERGENCE_EXCEPTIONS['role_manage']`
    // （结构事实：同一条 API 被两个守卫码不同的页面共用）。
    // 写面（POST/PUT/DELETE）仍是 `system:manage`。**不新增权限码、不改岗位矩阵。**

    /**
     * 分页查询角色列表
     *
     * GET /api/admin/roles?page=1&size=10&keyword=xxx
     * 权限：system:view（issue #5980 收窄；「岗位权限」页第一屏读端点，该页守卫码即本码）
     */
    @GetMapping
    @RequirePermission("system:view")
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
     * 权限：employee:list（issue #5980 收窄；「员工管理」页岗位下拉的数据源）
     */
    @GetMapping("/all")
    @RequirePermission("employee:list")
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
     * 权限：system:view（issue #5980 收窄；「岗位权限」页回显，该页守卫码即本码）
     */
    @GetMapping("/{id}")
    @RequirePermission("system:view")
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
     * 权限：system:manage
     */
    @PostMapping
    @RequirePermission("system:manage")
    public ApiResponse<Role> createRole(@RequestBody Map<String, Object> body) {
        Long tenantId = TenantContext.getTenantId();
        String name = (String) body.get("name");
        String code = (String) body.get("code");
        String description = (String) body.get("description");
        @SuppressWarnings("unchecked")
        List<String> permissionIds = (List<String>) body.get("permissionIds");

        log.info("创建角色: name={}, code={}, tenantId={}", name, code, tenantId);
        Role role = roleService.createRole(name, code, description, tenantId, permissionIds);
        return ApiResponse.success(role);
    }

    /**
     * 更新角色
     *
     * PUT /api/admin/roles/{id}
     * Body: { "name": "xxx", "description": "xxx", "permissionIds": [] }
     * 权限：system:manage
     */
    @PutMapping("/{id}")
    @RequirePermission("system:manage")
    public ApiResponse<Role> updateRole(@PathVariable String id, @RequestBody Map<String, Object> body) {
        String name = (String) body.get("name");
        String description = (String) body.get("description");
        @SuppressWarnings("unchecked")
        List<String> permissionIds = (List<String>) body.get("permissionIds");

        log.info("更新角色: id={}, name={}", id, name);
        Role role = roleService.updateRole(id, name, description, permissionIds);
        return ApiResponse.success(role);
    }

    /**
     * 删除角色
     *
     * DELETE /api/admin/roles/{id}
     */
    @DeleteMapping("/{id}")
    @RequirePermission("system:manage")  // 审计 07 P1-4: 角色删除属系统管理操作
    public ApiResponse<Void> deleteRole(@PathVariable String id) {
        log.info("删除角色: id={}", id);
        roleService.deleteRole(id);
        return ApiResponse.success();
    }
}
