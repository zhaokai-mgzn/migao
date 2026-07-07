package com.migao.admin.service;

import com.migao.admin.dto.PageResponse;
import com.migao.admin.entity.Permission;
import com.migao.admin.entity.Role;
import com.migao.admin.entity.User;
import com.migao.admin.entity.UserRole;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.PermissionMapper;
import com.migao.admin.mapper.RoleMapper;
import com.migao.admin.mapper.UserMapper;
import com.migao.admin.mapper.UserRoleMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.stream.Collectors;

/**
 * 角色服务类
 * 处理角色 CRUD、用户角色关联、角色权限等业务逻辑
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class RoleService {

    private final RoleMapper roleMapper;
    private final PermissionMapper permissionMapper;
    private final UserRoleMapper userRoleMapper;
    private final UserMapper userMapper;

    // ==================== 角色查询 ====================

    /**
     * 根据用户ID查询用户的所有角色
     *
     * @param userId 用户ID
     * @return 角色列表
     */
    public List<Role> getUserRoles(String userId) {
        LambdaQueryWrapper<UserRole> wrapper = new LambdaQueryWrapper<>();
        wrapper.eq(UserRole::getUserId, userId)
                .eq(UserRole::getDeleted, 0);
        List<UserRole> userRoles = userRoleMapper.selectList(wrapper);

        if (userRoles.isEmpty()) {
            return List.of();
        }

        List<String> roleIds = userRoles.stream()
                .map(UserRole::getRoleId)
                .collect(Collectors.toList());

        return roleMapper.selectBatchIds(roleIds);
    }

    /**
     * 根据用户ID查询用户的所有角色代码
     *
     * @param userId 用户ID
     * @return 角色代码列表
     */
    public List<String> getUserRoleCodes(String userId) {
        List<Role> roles = getUserRoles(userId);
        if (roles.isEmpty()) {
            // 回退到 User 表的 role 字段
            User user = userMapper.selectById(userId);
            if (user != null && StringUtils.hasText(user.getRole())) {
                return List.of(user.getRole());
            }
            return List.of();
        }
        return roles.stream()
                .map(Role::getCode)
                .collect(Collectors.toList());
    }

    // ==================== 权限查询 ====================

    /**
     * 根据角色ID查询角色的所有权限
     *
     * @param roleId 角色ID
     * @return 权限列表
     */
    public List<Permission> getRolePermissions(String roleId) {
        Role role = roleMapper.selectById(roleId);
        if (role == null) {
            return List.of();
        }
        return getPermissionsByRoleCode(role.getCode());
    }

    /**
     * 根据角色代码查询权限列表
     *
     * @param roleCode 角色代码
     * @return 权限列表
     */
    public List<Permission> getPermissionsByRoleCode(String roleCode) {
        List<String> permissionCodes = switch (roleCode) {
            case "admin" -> List.of("*");
            case "operator" -> List.of(
                    "dashboard:view",
                    "order:list", "order:detail", "order:refund",
                    "product:list", "product:create", "product:category",
                    "processing:manage",
                    "customer:view",
                    "finance:view",
                    "agent:session", "agent:quickreply",
                    "employee:list",
                    "system:manage"
            );
            case "product_manager" -> List.of(
                    "dashboard:view",
                    "product:list", "product:create", "product:category",
                    "processing:manage"
            );
            case "knowledge_editor" -> List.of(
                    "dashboard:view"
            );
            default -> List.of();
        };

        if (permissionCodes.isEmpty() || permissionCodes.contains("*")) {
            return List.of();
        }

        LambdaQueryWrapper<Permission> wrapper = new LambdaQueryWrapper<>();
        wrapper.in(Permission::getCode, permissionCodes)
                .eq(Permission::getDeleted, 0);
        return permissionMapper.selectList(wrapper);
    }

    /**
     * 根据用户ID查询用户的所有权限（合并所有角色的权限）
     *
     * @param userId 用户ID
     * @return 权限代码列表
     */
    public List<String> getUserPermissions(String userId) {
        List<Role> roles = getUserRoles(userId);

        // 如果用户没有通过 user_roles 分配角色，尝试从 User 表的 role 字段获取
        if (roles.isEmpty()) {
            User user = userMapper.selectById(userId);
            if (user != null && StringUtils.hasText(user.getRole())) {
                if ("admin".equals(user.getRole())) {
                    return List.of("*");  // admin 始终拥有全部权限
                }
                Set<String> permSet = new HashSet<>(getPermissionCodesForRole(user.getRole()));
                mergeUserPermissions(user, permSet);
                return new ArrayList<>(permSet);
            }
            if (user != null) {
                Set<String> permSet = new HashSet<>();
                mergeUserPermissions(user, permSet);
                return new ArrayList<>(permSet);
            }
            return List.of();
        }

        // 检查是否为 admin 角色——admin 始终拥有全部权限
        for (Role role : roles) {
            if ("admin".equals(role.getCode())) {
                return List.of("*");
            }
        }

        // 非 admin 角色：合并角色权限 + 用户个人权限
        Set<String> permissionSet = new HashSet<>();
        for (Role role : roles) {
            permissionSet.addAll(getPermissionCodesForRole(role.getCode()));
        }

        // 合并 User.permissions 字段（细粒度菜单权限）
        User user = userMapper.selectById(userId);
        if (user != null) {
            mergeUserPermissions(user, permissionSet);
        }

        return new ArrayList<>(permissionSet);
    }

    /**
     * 根据角色代码获取权限码列表（直接返回字符串，不依赖 DB 查询）
     */
    private List<String> getPermissionCodesForRole(String roleCode) {
        return switch (roleCode) {
            case "admin" -> List.of("*");
            case "operator" -> List.of(
                    "dashboard:view",
                    "order:list", "order:detail", "order:refund",
                    "product:list", "product:create", "product:category",
                    "processing:manage",
                    "customer:view",
                    "finance:view",
                    "agent:session", "agent:quickreply",
                    "employee:list",
                    "system:manage"
            );
            case "product_manager" -> List.of(
                    "dashboard:view",
                    "product:list", "product:create", "product:category",
                    "processing:manage"
            );
            case "knowledge_editor" -> List.of(
                    "dashboard:view",
                    "product:list"
            );
            default -> List.of();
        };
    }

    /**
     * 合并 User.permissions 字段（JSON 数组）到权限集合
     */
    private void mergeUserPermissions(User user, Set<String> permissionSet) {
        if (user.getPermissions() != null && !user.getPermissions().isEmpty()) {
            try {
                List<String> userPerms = OBJECT_MAPPER.readValue(
                        user.getPermissions(), new TypeReference<List<String>>() {});
                permissionSet.addAll(userPerms);
            } catch (Exception e) {
                log.warn("解析用户 {} 权限 JSON 失败: {}", user.getId(), e.getMessage());
            }
        }
    }

    private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();

    /**
     * 检查用户是否拥有指定权限
     */
    public boolean hasPermission(String userId, String permission) {
        List<String> permissions = getUserPermissions(userId);
        return permissions.contains("*") || permissions.contains(permission);
    }

    /**
     * 检查用户是否拥有指定角色
     */
    public boolean hasRole(String userId, String roleCode) {
        List<String> roles = getUserRoleCodes(userId);
        return roles.contains(roleCode);
    }

    // ==================== 角色 CRUD ====================

    /**
     * 分页查询角色列表
     *
     * @param page     页码
     * @param size     每页大小
     * @param keyword  关键词搜索
     * @param tenantId 租户ID
     * @return 分页响应
     */
    public PageResponse<Role> getRolePage(long page, long size, String keyword, Long tenantId) {
        LambdaQueryWrapper<Role> wrapper = new LambdaQueryWrapper<>();

        if (StringUtils.hasText(keyword)) {
            wrapper.and(w -> w.like(Role::getName, keyword)
                    .or()
                    .like(Role::getCode, keyword));
        }

        wrapper.orderByAsc(Role::getCode);

        Page<Role> rolePage = new Page<>(page, size);
        Page<Role> resultPage = roleMapper.selectPage(rolePage, wrapper);

        return PageResponse.of(resultPage.getTotal(), resultPage.getCurrent(), resultPage.getSize(), resultPage.getRecords());
    }

    /**
     * 查询所有角色列表
     *
     * @param tenantId 租户ID
     * @return 角色列表
     */
    public List<Role> getAllRoles(Long tenantId) {
        LambdaQueryWrapper<Role> wrapper = new LambdaQueryWrapper<>();
        wrapper.eq(Role::getDeleted, 0)
                .orderByAsc(Role::getCode);
        return roleMapper.selectList(wrapper);
    }

    /**
     * 根据ID查询角色详情
     *
     * @param roleId 角色ID
     * @return 角色实体
     */
    public Role getRoleById(String roleId) {
        Role role = roleMapper.selectById(roleId);
        if (role == null) {
            throw BusinessException.notFound("角色");
        }
        return role;
    }

    /**
     * 创建角色
     *
     * @param name        角色名称
     * @param code        角色代码
     * @param description 描述
     * @param tenantId    租户ID
     * @return 创建的角色
     */
    @Transactional(rollbackFor = Exception.class)
    public Role createRole(String name, String code, String description, Long tenantId) {
        // 验证 code 唯一性
        LambdaQueryWrapper<Role> wrapper = new LambdaQueryWrapper<>();
        wrapper.eq(Role::getCode, code)
                .eq(Role::getTenantId, tenantId)
                .eq(Role::getDeleted, 0);
        Role existing = roleMapper.selectOne(wrapper);
        if (existing != null) {
            throw BusinessException.validationError("角色代码已存在: " + code);
        }

        Role role = Role.builder()
                .tenantId(tenantId)
                .name(name)
                .code(code)
                .description(description)
                .status("active")
                .build();

        roleMapper.insert(role);
        log.info("创建角色成功: id={}, code={}", role.getId(), code);
        return role;
    }

    /**
     * 更新角色
     *
     * @param roleId      角色ID
     * @param name        角色名称
     * @param description 描述
     * @return 更新后的角色
     */
    @Transactional(rollbackFor = Exception.class)
    public Role updateRole(String roleId, String name, String description) {
        Role role = getRoleById(roleId);

        if (StringUtils.hasText(name)) {
            role.setName(name);
        }
        if (description != null) {
            role.setDescription(description);
        }

        roleMapper.updateById(role);
        log.info("更新角色成功: id={}", roleId);
        return role;
    }

    /**
     * 删除角色（逻辑删除）
     * 删除前检查是否有用户使用该角色
     *
     * @param roleId 角色ID
     */
    @Transactional(rollbackFor = Exception.class)
    public void deleteRole(String roleId) {
        Role role = getRoleById(roleId);

        // 检查是否有用户使用该角色
        LambdaQueryWrapper<UserRole> wrapper = new LambdaQueryWrapper<>();
        wrapper.eq(UserRole::getRoleId, roleId)
                .eq(UserRole::getDeleted, 0);
        long count = userRoleMapper.selectCount(wrapper);
        if (count > 0) {
            throw BusinessException.validationError("该角色下有 " + count + " 个用户，无法删除");
        }

        roleMapper.deleteById(roleId);
        log.info("删除角色成功: id={}, code={}", roleId, role.getCode());
    }

    // ==================== 角色用户查询 ====================

    /**
     * 查询某角色下的用户列表
     *
     * @param roleId 角色ID
     * @param page   页码
     * @param size   每页大小
     * @return 用户分页列表
     */
    public PageResponse<User> getRoleUsers(String roleId, long page, long size) {
        // 先查 user_roles 关联
        LambdaQueryWrapper<UserRole> urWrapper = new LambdaQueryWrapper<>();
        urWrapper.eq(UserRole::getRoleId, roleId)
                .eq(UserRole::getDeleted, 0);
        List<UserRole> userRoles = userRoleMapper.selectList(urWrapper);

        if (userRoles.isEmpty()) {
            return PageResponse.of(0L, page, size, List.of());
        }

        List<String> userIds = userRoles.stream()
                .map(UserRole::getUserId)
                .collect(Collectors.toList());

        // 分页查询用户
        LambdaQueryWrapper<User> userWrapper = new LambdaQueryWrapper<>();
        userWrapper.in(User::getId, userIds)
                .eq(User::getDeleted, 0)
                .orderByDesc(User::getCreatedAt);

        Page<User> userPage = new Page<>(page, size);
        Page<User> resultPage = userMapper.selectPage(userPage, userWrapper);

        // 脱敏
        resultPage.getRecords().forEach(u -> u.setPasswordHash(null));

        return PageResponse.of(resultPage.getTotal(), resultPage.getCurrent(), resultPage.getSize(), resultPage.getRecords());
    }

    // ==================== 权限分配 ====================

    /**
     * 为角色分配权限
     * TODO: 当实现 role_permissions 中间表后，改为从中间表管理
     * 当前权限是基于角色代码的硬编码映射
     *
     * @param roleId        角色ID
     * @param permissionIds 权限ID列表
     */
    @Transactional(rollbackFor = Exception.class)
    public void assignPermissions(String roleId, List<String> permissionIds) {
        // TODO: 实现 role_permissions 中间表的权限分配
        // 当前权限是基于角色代码的硬编码映射，待后续数据库驱动的权限管理实现后替换
        Role role = getRoleById(roleId);
        log.info("为角色分配权限（占位实现）: roleId={}, roleCode={}, permissionCount={}",
                roleId, role.getCode(), permissionIds.size());
    }

    /**
     * 为用户分配角色
     *
     * @param userId   用户ID
     * @param roleId   角色ID
     * @param tenantId 租户ID
     */
    @Transactional(rollbackFor = Exception.class)
    public void assignRoleToUser(String userId, String roleId, Long tenantId) {
        // 检查是否已分配
        LambdaQueryWrapper<UserRole> wrapper = new LambdaQueryWrapper<>();
        wrapper.eq(UserRole::getUserId, userId)
                .eq(UserRole::getRoleId, roleId)
                .eq(UserRole::getDeleted, 0);
        UserRole existing = userRoleMapper.selectOne(wrapper);
        if (existing != null) {
            throw BusinessException.validationError("用户已拥有该角色");
        }

        UserRole userRole = UserRole.builder()
                .tenantId(tenantId)
                .userId(userId)
                .roleId(roleId)
                .build();
        userRoleMapper.insert(userRole);
        log.info("为用户分配角色成功: userId={}, roleId={}", userId, roleId);
    }

    /**
     * 移除用户角色
     *
     * @param userId 用户ID
     * @param roleId 角色ID
     */
    @Transactional(rollbackFor = Exception.class)
    public void removeRoleFromUser(String userId, String roleId) {
        LambdaQueryWrapper<UserRole> wrapper = new LambdaQueryWrapper<>();
        wrapper.eq(UserRole::getUserId, userId)
                .eq(UserRole::getRoleId, roleId);
        int deleted = userRoleMapper.delete(wrapper);
        if (deleted == 0) {
            throw BusinessException.validationError("用户未拥有该角色");
        }
        log.info("移除用户角色成功: userId={}, roleId={}", userId, roleId);
    }
}
