package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.dto.PageResponse;
import com.migao.admin.entity.Role;
import com.migao.admin.entity.User;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.security.SecurityUser;
import com.migao.admin.service.RoleService;
import com.migao.admin.service.UserService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.bind.annotation.*;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

/**
 * 员工（用户）管理控制器
 * 提供用户 CRUD、状态切换、密码重置等管理接口
 *
 * 前端路径前缀: /api/admin/users
 */
@Slf4j
@RestController
@RequestMapping("/api/admin/users")
@RequiredArgsConstructor
public class AdminUserController {

    private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();

    private final UserService userService;
    private final RoleService roleService;

    /**
     * 分页查询用户列表
     *
     * GET /api/admin/users?page=1&size=10&keyword=xxx&status=active
     */
    @GetMapping
    public ApiResponse<PageResponse<Map<String, Object>>> getUsers(
            @RequestParam(defaultValue = "1") long page,
            @RequestParam(defaultValue = "10") long size,
            @RequestParam(required = false) String keyword,
            @RequestParam(required = false) String status,
            @RequestParam(required = false) String role) {
        Long tenantId = TenantContext.getTenantId();
        log.info("查询用户列表: page={}, size={}, keyword={}, status={}, tenantId={}", page, size, keyword, status, tenantId);
        PageResponse<User> result = userService.getUserPage(page, size, role, status, keyword, tenantId);

        // 转换为前端期望的 Employee 格式
        List<Map<String, Object>> items = result.getItems().stream()
                .map(this::toEmployeeMap)
                .collect(Collectors.toList());

        PageResponse<Map<String, Object>> mapped = PageResponse.of(
                result.getTotal(), result.getPage(), result.getSize(), items);
        return ApiResponse.success(mapped);
    }

    /**
     * 查询用户详情
     *
     * GET /api/admin/users/{id}
     */
    @GetMapping("/{id}")
    public ApiResponse<Map<String, Object>> getUser(@PathVariable String id) {
        log.info("查询用户详情: id={}", id);
        User user = userService.getUserDetail(id);
        return ApiResponse.success(toEmployeeMap(user));
    }

    /**
     * 校验当前用户是否为管理员，非管理员抛出权限异常
     */
    private void requireAdmin() {
        var auth = SecurityContextHolder.getContext().getAuthentication();
        if (auth == null || !(auth.getPrincipal() instanceof SecurityUser)) {
            throw BusinessException.permissionDenied();
        }
        SecurityUser user = (SecurityUser) auth.getPrincipal();
        if (user.getRoles() == null || !user.getRoles().contains("admin")) {
            throw BusinessException.permissionDenied();
        }
    }

    /**
     * 创建用户
     *
     * POST /api/admin/users
     * Body: { "username": "xxx", "password": "xxx", "name": "xxx", "phone": "xxx", "roleIds": [] }
     */
    @PostMapping
    public ApiResponse<User> createUser(@RequestBody Map<String, Object> body) {
        requireAdmin();
        Long tenantId = TenantContext.getTenantId();
        String phone = body.containsKey("phone") ? (String) body.get("phone") : (String) body.get("username");
        if (phone == null || phone.isBlank()) {
            throw BusinessException.validationError("手机号不能为空");
        }
        String password = (String) body.get("password"); // 可选，不传则默认用手机号
        String name = (String) body.getOrDefault("name", "");
        String position = (String) body.getOrDefault("position", "");

        // 从请求体读取角色，支持 role 字段（字符串）或 roleIds（数组取第一个对应的角色代码）
        String role = "operator"; // 默认角色
        List<?> roleIdList = null;
        if (body.containsKey("role") && body.get("role") != null) {
            role = (String) body.get("role");
        } else if (body.containsKey("roleIds") && body.get("roleIds") != null) {
            roleIdList = (List<?>) body.get("roleIds");
            if (!roleIdList.isEmpty()) {
                String roleId = String.valueOf(roleIdList.get(0));
                try {
                    Role roleEntity = roleService.getRoleById(roleId);
                    role = roleEntity.getCode();
                } catch (Exception e) {
                    log.warn("根据 roleId 查找角色失败: {}", roleId, e);
                }
            }
        }

        // 岗位必须
        if (position.isBlank()) {
            position = role; // fallback: 岗位 = 角色名
        }

        // 从请求体读取权限列表（前端 TreeCheckbox 发送的菜单权限码 JSON 数组）
        String permissions = null;
        Object permsObj = body.get("permissions");
        if (permsObj instanceof List<?> list && !list.isEmpty()) {
            try {
                permissions = OBJECT_MAPPER.writeValueAsString(list);
            } catch (Exception e) {
                log.warn("序列化 permissions 失败", e);
            }
        }

        log.info("创建用户: phone={}, name={}, role={}, position={}, tenantId={}", phone, name, role, position, tenantId);
        User user = userService.createUser(phone, password, name, role, position, permissions, tenantId);

        // 如果传了 roleIds，同步写入 user_roles 关联表
        if (roleIdList != null && !roleIdList.isEmpty()) {
            for (Object rid : roleIdList) {
                try {
                    roleService.assignRoleToUser(user.getId(), String.valueOf(rid), tenantId);
                } catch (Exception e) {
                    log.warn("为用户分配角色失败: userId={}, roleId={}", user.getId(), rid, e);
                }
            }
        }

        return ApiResponse.success(user);
    }

    /**
     * 更新用户
     *
     * PUT /api/admin/users/{id}
     * Body: { "name": "xxx", "phone": "xxx", "password": "xxx" }
     */
    @PutMapping("/{id}")
    public ApiResponse<User> updateUser(@PathVariable String id, @RequestBody Map<String, Object> body) {
        requireAdmin();
        String name = (String) body.get("name");
        String avatar = (String) body.get("avatar");
        String role = (String) body.get("role");

        // 如果有密码，同步修改
        String password = (String) body.get("password");
        if (password != null && !password.isEmpty()) {
            userService.changePassword(id, password);
        }

        // 从请求体读取权限列表
        String permissions = null;
        Object permsObj = body.get("permissions");
        if (permsObj instanceof List<?> list) {
            try {
                permissions = OBJECT_MAPPER.writeValueAsString(list);
            } catch (Exception e) {
                log.warn("序列化 permissions 失败", e);
            }
        }

        log.info("更新用户: id={}, name={}", id, name);
        User user = userService.updateUser(id, name, avatar, role, permissions);
        return ApiResponse.success(user);
    }

    /**
     * 删除用户
     *
     * DELETE /api/admin/users/{id}
     */
    @DeleteMapping("/{id}")
    public ApiResponse<Void> deleteUser(@PathVariable String id) {
        requireAdmin();
        log.info("删除用户: id={}", id);
        userService.deleteUser(id);
        return ApiResponse.success();
    }

    /**
     * 重置用户密码
     *
     * PUT /api/admin/users/{id}/reset-password
     * Body: { "newPassword": "xxx" }
     */
    @PutMapping("/{id}/reset-password")
    public ApiResponse<Map<String, String>> resetPassword(@PathVariable String id,
                                                           @RequestBody(required = false) Map<String, String> body) {
        requireAdmin();
        String newPassword = null;
        if (body != null) {
            newPassword = body.get("newPassword");
        }

        if (newPassword != null && !newPassword.isEmpty()) {
            userService.changePassword(id, newPassword);
            log.info("重置用户密码(自定义): id={}", id);
            return ApiResponse.success(Map.of("message", "密码已重置"));
        } else {
            String defaultPwd = userService.resetPassword(id);
            log.info("重置用户密码(默认): id={}", id);
            return ApiResponse.success(Map.of("message", "密码已重置", "defaultPassword", defaultPwd));
        }
    }

    /**
     * 切换用户状态（启用/禁用）
     *
     * PUT /api/admin/users/{id}/status
     * Body: { "status": "active" | "disabled" }
     */
    @PutMapping("/{id}/status")
    public ApiResponse<Void> toggleUserStatus(@PathVariable String id, @RequestBody Map<String, String> body) {
        requireAdmin();
        String status = body.get("status");
        log.info("切换用户状态: id={}, status={}", id, status);
        if ("active".equals(status)) {
            userService.enableUser(id);
        } else {
            userService.disableUser(id);
        }
        return ApiResponse.success();
    }

    /**
     * 将 User 实体转换为前端 Employee 格式
     */
    private Map<String, Object> toEmployeeMap(User user) {
        Map<String, Object> map = new HashMap<>();
        map.put("id", user.getId());
        map.put("username", user.getPhone());
        map.put("name", user.getNickname());
        map.put("phone", user.getPhone());
        map.put("email", null);
        map.put("role", user.getRole());
        // position 为空时回退到 role 名称
        String position = user.getPosition();
        if (position == null || position.isBlank()) {
            position = user.getRole() != null ? user.getRole() : "";
        }
        map.put("position", position);
        map.put("status", user.getStatus());
        map.put("createdAt", user.getCreatedAt());
        map.put("updatedAt", user.getUpdatedAt());

        // 构建 roles 数组
        List<Role> roles = roleService.getUserRoles(user.getId());
        if (roles.isEmpty() && user.getRole() != null) {
            // 回退到 User.role 字段构造伪角色对象
            map.put("roles", List.of(Map.of("id", 0, "name", user.getRole(), "code", user.getRole())));
        } else {
            map.put("roles", roles.stream().map(r -> {
                Map<String, Object> rm = new HashMap<>();
                rm.put("id", r.getId());
                rm.put("name", r.getName());
                rm.put("code", r.getCode());
                return rm;
            }).collect(Collectors.toList()));
        }

        // 解析 permissions JSON 数组，返回给前端
        try {
            if (user.getPermissions() != null && !user.getPermissions().isEmpty()) {
                map.put("permissions", OBJECT_MAPPER.readValue(
                    user.getPermissions(), List.class));
            } else {
                map.put("permissions", List.of());
            }
        } catch (Exception e) {
            map.put("permissions", List.of());
        }

        return map;
    }
}
