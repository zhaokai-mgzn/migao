package com.migao.admin.controller;

import com.migao.admin.dto.ApiResponse;
import com.migao.admin.dto.UserInfoResponse;
import com.migao.admin.entity.Tenant;
import com.migao.admin.entity.User;
import com.migao.admin.mapper.TenantMapper;
import com.migao.admin.mapper.UserMapper;
import com.migao.admin.security.SecurityUser;
import com.migao.admin.service.RoleService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

/**
 * 用户控制器
 * 处理用户信息、角色、权限等相关接口
 */
@Slf4j
@RestController
@RequestMapping("/api/admin/user")
@RequiredArgsConstructor
public class UserController {

    private final UserMapper userMapper;
    private final TenantMapper tenantMapper;
    private final RoleService roleService;
    private final com.migao.admin.mapper.TenantAiConfigMapper tenantAiConfigMapper;

    /**
     * 获取当前登录用户信息
     * 包含用户信息、角色、权限
     *
     * GET /api/admin/user/info
     *
     * Response: {
     *   "success": true,
     *   "data": {
     *     "user": { "id": "...", "username": "admin", "nickname": "管理员", "avatar": "..." },
     *     "roles": ["admin"],
     *     "permissions": ["product:manage", "knowledge:manage", ...]
     *   }
     * }
     *
     * <p>issue #5246（审计裁定「该放行」）：本端点**有意不加权限注解** —— 它是登录后首屏的
     * 自助接口，返回的只有**调用方自己**的 roles / permissions（全部按 {@code userId}
     * 现算，无任何跨用户入参）；加码会让「没有任何菜单权限」的员工连首屏都拿不到，
     * 前端无法渲染 403/空态。</p>
     *
     * <p>⚠️ **本端点不下发菜单**（issue #5236，修正上一句里的 menus）：方法内原持有的私有菜单表
     * {@code generateMenus} 是「菜单三源同构」之外的**第四处菜单源**（只覆盖 dashboard / products /
     * processing / knowledge / settings 共 5 项，与 `frontend/admin-web/src/config/menu.ts`、
     * `backend/admin-api/src/main/java/com/migao/admin/controller/MenuController.java` 的
     * `MENU_TREE`、`backend/admin-api/src/main/java/com/migao/admin/service/AuthService.java`
     * 的 `buildMenusByPermissions` 三处**都不一致**），且**实测无任何消费方**
     * （前端 frontend/admin-web/src/lib/api.ts 只调 `/api/auth/me`；本端点无 HTTP 契约账本条目；
     * 测试只断言本端点的状态码、不断言其 `menus` 内容）⇒ 判为死代码，连同调用点整段删除。</p>
     *
     * <p>菜单的**服务端唯一下发面** = `AuthService.getCurrentUser()`（`GET /api/auth/me`）。
     * `UserInfoResponse.menus` 字段**保留**：它的消费方在前端
     * `frontend/admin-web/src/store/auth.ts`（生产读取点）与 `frontend/admin-web/src/types/index.ts`
     * （wire 声明），删字段会砍掉真实消费面。</p>
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

        // 查询租户名称
        String tenantName = null;
        if (user.getTenantId() != null) {
            Tenant tenant = tenantMapper.selectById(user.getTenantId());
            if (tenant != null) {
                tenantName = tenant.getName();
            }
        }

        // 查询智能客服名称（TenantAiConfig.botName，C 端思考中/空态/导航名展示；未配置为 null → 前端兜底「小布」）
        String botName = null;
        if (user.getTenantId() != null) {
            com.migao.admin.entity.TenantAiConfig aiConfig = tenantAiConfigMapper.selectOne(
                    new com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper<com.migao.admin.entity.TenantAiConfig>()
                            .eq(com.migao.admin.entity.TenantAiConfig::getTenantId, user.getTenantId())
                            .last("LIMIT 1"));
            if (aiConfig != null) {
                botName = aiConfig.getBotName();
            }
        }

        // 构建响应
        UserInfoResponse response = UserInfoResponse.builder()
                .user(UserInfoResponse.UserInfo.builder()
                        .id(user.getId())
                        .username(user.getPhone())
                        .nickname(user.getNickname())
                        .position(user.getPosition())
                        .avatar(user.getAvatar())
                        .tenantId(user.getTenantId())
                        .tenantName(tenantName)
                        .botName(botName)
                        .status(user.getStatus())
                        .build())
                .roles(roles)
                .permissions(permissions)
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
}
