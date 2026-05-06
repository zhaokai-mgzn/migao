package com.aikf.admin.controller;

import com.aikf.admin.dto.ApiResponse;
import com.aikf.admin.dto.UserInfoResponse;
import com.aikf.admin.entity.Tenant;
import com.aikf.admin.entity.User;
import com.aikf.admin.mapper.TenantMapper;
import com.aikf.admin.mapper.UserMapper;
import com.aikf.admin.security.SecurityUser;
import com.aikf.admin.service.RoleService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.ArrayList;
import java.util.List;

/**
 * 用户控制器
 * 处理用户信息、角色、权限、菜单等相关接口
 */
@Slf4j
@RestController
@RequestMapping("/api/admin/user")
@RequiredArgsConstructor
public class UserController {

    private final UserMapper userMapper;
    private final TenantMapper tenantMapper;
    private final RoleService roleService;

    /**
     * 获取当前登录用户信息
     * 包含用户信息、角色、权限和菜单
     *
     * GET /api/admin/user/info
     *
     * Response: {
     *   "success": true,
     *   "data": {
     *     "user": { "id": "...", "username": "admin", "nickname": "管理员", "avatar": "..." },
     *     "roles": ["super_admin"],
     *     "permissions": ["product:manage", "knowledge:manage", ...],
     *     "menus": [
     *       { "key": "dashboard", "name": "数据看板", "icon": "BarChart3", "path": "/dashboard" },
     *       { "key": "products", "name": "商品管理", "icon": "Package", "path": "/products" },
     *       ...
     *     ]
     *   }
     * }
     */
    @GetMapping("/info")
    public ApiResponse<UserInfoResponse> getUserInfo() {
        // 获取当前用户认证信息
        Authentication authentication = SecurityContextHolder.getContext().getAuthentication();
        if (authentication == null || !authentication.isAuthenticated()) {
            log.warn("获取用户信息失败：用户未认证");
            return ApiResponse.error("UNAUTHORIZED", "用户未认证");
        }

        // 提取用户ID
        String userId = extractUserId(authentication);
        if (userId == null) {
            log.warn("获取用户信息失败：无法获取用户ID");
            return ApiResponse.error("INVALID_USER", "无法获取用户信息");
        }

        // 查询用户信息
        User user = userMapper.selectById(userId);
        if (user == null) {
            log.warn("获取用户信息失败：用户不存在, userId={}", userId);
            return ApiResponse.error("USER_NOT_FOUND", "用户不存在");
        }

        // 获取用户角色
        List<String> roles = roleService.getUserRoleCodes(userId);

        // 获取用户权限
        List<String> permissions = roleService.getUserPermissions(userId);

        // 根据权限生成菜单
        List<UserInfoResponse.MenuItem> menus = generateMenus(permissions, roles);

        // 查询租户名称
        String tenantName = null;
        if (user.getTenantId() != null) {
            Tenant tenant = tenantMapper.selectById(user.getTenantId());
            if (tenant != null) {
                tenantName = tenant.getName();
            }
        }

        // 构建响应
        UserInfoResponse response = UserInfoResponse.builder()
                .user(UserInfoResponse.UserInfo.builder()
                        .id(user.getId())
                        .username(user.getPhone())
                        .nickname(user.getNickname())
                        .avatar(user.getAvatar())
                        .tenantId(user.getTenantId())
                        .tenantName(tenantName)
                        .status(user.getStatus())
                        .build())
                .roles(roles)
                .permissions(permissions)
                .menus(menus)
                .build();

        log.debug("获取用户信息成功: userId={}, roles={}, permissions={}", userId, roles, permissions);

        return ApiResponse.success(response);
    }

    /**
     * 从认证信息中提取用户ID
     *
     * @param authentication 认证信息
     * @return 用户ID
     */
    private String extractUserId(Authentication authentication) {
        Object principal = authentication.getPrincipal();
        if (principal instanceof SecurityUser securityUser) {
            return securityUser.getUserId();
        }
        return null;
    }

    /**
     * 根据用户权限生成菜单列表
     *
     * @param permissions 权限列表
     * @param roles       角色列表
     * @return 菜单列表
     */
    private List<UserInfoResponse.MenuItem> generateMenus(List<String> permissions, List<String> roles) {
        List<UserInfoResponse.MenuItem> menus = new ArrayList<>();

        // 检查是否为超级管理员（拥有所有权限）
        boolean isSuperAdmin = roles.contains("super_admin") || permissions.contains("*");

        // 数据看板菜单 - 需要 dashboard:view 权限或者是超级管理员
        if (isSuperAdmin || permissions.contains("dashboard:view")) {
            menus.add(UserInfoResponse.MenuItem.builder()
                    .key("dashboard")
                    .name("数据看板")
                    .icon("BarChart3")
                    .path("/dashboard")
                    .build());
        }

        // 商品管理菜单 - 需要 product:manage 权限或者是超级管理员
        if (isSuperAdmin || permissions.contains("product:manage")) {
            menus.add(UserInfoResponse.MenuItem.builder()
                    .key("products")
                    .name("商品管理")
                    .icon("Package")
                    .path("/products")
                    .build());
        }

        // 加工项管理菜单 - 需要 processing:manage 权限或者是超级管理员
        if (isSuperAdmin || permissions.contains("processing:manage")) {
            menus.add(UserInfoResponse.MenuItem.builder()
                    .key("processing")
                    .name("加工项管理")
                    .icon("Scissors")
                    .path("/processing")
                    .build());
        }

        // 知识库管理菜单 - 需要 knowledge:manage 权限或者是超级管理员
        if (isSuperAdmin || permissions.contains("knowledge:manage")) {
            menus.add(UserInfoResponse.MenuItem.builder()
                    .key("knowledge")
                    .name("知识库管理")
                    .icon("BookOpen")
                    .path("/knowledge")
                    .build());
        }

        // 系统设置菜单 - 需要 system:manage 权限或者是超级管理员
        if (isSuperAdmin || permissions.contains("system:manage")) {
            menus.add(UserInfoResponse.MenuItem.builder()
                    .key("settings")
                    .name("系统设置")
                    .icon("Settings")
                    .path("/settings")
                    .build());
        }

        return menus;
    }
}
