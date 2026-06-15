package com.migao.admin.service;

import com.migao.admin.dto.PageResponse;
import com.migao.admin.entity.Role;
import com.migao.admin.entity.User;
import com.migao.admin.entity.UserRole;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.RoleMapper;
import com.migao.admin.mapper.UserMapper;
import com.migao.admin.mapper.UserRoleMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.userdetails.UserDetails;
import org.springframework.security.core.userdetails.UserDetailsService;
import org.springframework.security.core.userdetails.UsernameNotFoundException;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.util.ArrayList;
import java.util.List;

/**
 * 用户服务类
 * 实现 UserDetailsService 接口，用于 Spring Security 认证
 * 同时提供用户管理功能（列表、创建、更新、禁用/启用、重置密码等）
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class UserService implements UserDetailsService {

    private final UserMapper userMapper;
    private final RoleMapper roleMapper;
    private final UserRoleMapper userRoleMapper;

    private static final BCryptPasswordEncoder PASSWORD_ENCODER = new BCryptPasswordEncoder();

    // ==================== 认证相关方法 ====================

    /**
     * 根据用户名和租户ID查询用户
     *
     * @param username 用户名（phone）
     * @param tenantId 租户ID
     * @return 用户实体
     */
    public User getUserByUsernameAndTenant(String username, Long tenantId) {
        LambdaQueryWrapper<User> wrapper = new LambdaQueryWrapper<>();
        wrapper.eq(User::getPhone, username)
                .eq(User::getTenantId, tenantId)
                .eq(User::getDeleted, 0);
        return userMapper.selectOne(wrapper);
    }

    /**
     * 根据用户ID查询用户
     *
     * @param userId 用户ID
     * @return 用户实体
     */
    public User getUserById(String userId) {
        User user = userMapper.selectById(userId);
        if (user == null) {
            throw BusinessException.notFound("用户");
        }
        return user;
    }

    /**
     * 加载用户角色
     *
     * @param user 用户实体
     * @return 角色列表
     */
    public List<String> getUserRoles(User user) {
        List<String> roles = new ArrayList<>();
        if (user.getRole() != null && !user.getRole().isEmpty()) {
            roles.add(user.getRole());
        }
        return roles;
    }

    /**
     * 获取角色的权限列表
     *
     * @param roleCode 角色代码
     * @return 权限列表
     */
    public List<String> getRolePermissions(String roleCode) {
        return switch (roleCode) {
            case "admin" -> List.of("*");
            case "agent" -> List.of(
                    "chat:read", "chat:write",
                    "customer:read"
            );
            case "customer" -> List.of(
                    "chat:write",
                    "order:read"
            );
            default -> List.of();
        };
    }

    /**
     * Spring Security 的 UserDetailsService 接口实现
     */
    @Override
    public UserDetails loadUserByUsername(String username) throws UsernameNotFoundException {
        String[] parts = username.split("@");
        if (parts.length != 2) {
            throw new UsernameNotFoundException("用户名格式错误，应为: phone@tenantId");
        }

        String phone = parts[0];
        Long tenantId = Long.valueOf(parts[1]);

        User user = getUserByUsernameAndTenant(phone, tenantId);
        if (user == null) {
            throw new UsernameNotFoundException("用户不存在: " + username);
        }

        if (!"active".equals(user.getStatus())) {
            throw new UsernameNotFoundException("用户状态异常: " + user.getStatus());
        }

        List<String> roles = getUserRoles(user);
        List<SimpleGrantedAuthority> authorities = new ArrayList<>();

        for (String role : roles) {
            authorities.add(new SimpleGrantedAuthority("ROLE_" + role.toUpperCase()));
            List<String> permissions = getRolePermissions(role);
            for (String permission : permissions) {
                authorities.add(new SimpleGrantedAuthority(permission));
            }
        }

        return org.springframework.security.core.userdetails.User.builder()
                .username(username)
                .password(user.getPasswordHash())
                .authorities(authorities)
                .accountLocked(!"active".equals(user.getStatus()))
                .disabled(!"active".equals(user.getStatus()))
                .build();
    }

    /**
     * 根据手机号和租户ID加载用户（用于认证）
     */
    public UserDetails loadUserByPhoneAndTenant(String phone, Long tenantId) {
        return loadUserByUsername(phone + "@" + tenantId);
    }

    // ==================== 用户管理方法 ====================

    /**
     * 分页查询用户列表
     *
     * @param page     页码
     * @param size     每页大小
     * @param role     角色筛选
     * @param status   状态筛选
     * @param keyword  关键词搜索（姓名/手机号）
     * @param tenantId 租户ID
     * @return 分页响应
     */
    public PageResponse<User> getUserPage(long page, long size, String role, String status, String keyword, Long tenantId) {
        LambdaQueryWrapper<User> wrapper = new LambdaQueryWrapper<>();

        // 角色筛选
        if (StringUtils.hasText(role)) {
            wrapper.eq(User::getRole, role);
        }

        // 状态筛选
        if (StringUtils.hasText(status)) {
            wrapper.eq(User::getStatus, status);
        }

        // 关键词搜索
        if (StringUtils.hasText(keyword)) {
            wrapper.and(w -> w.like(User::getNickname, keyword)
                    .or()
                    .like(User::getPhone, keyword));
        }

        wrapper.orderByDesc(User::getCreatedAt);

        Page<User> userPage = new Page<>(page, size);
        Page<User> resultPage = userMapper.selectPage(userPage, wrapper);

        // 脱敏：清除密码哈希
        resultPage.getRecords().forEach(u -> u.setPasswordHash(null));

        return PageResponse.of(resultPage.getTotal(), resultPage.getCurrent(), resultPage.getSize(), resultPage.getRecords());
    }

    /**
     * 查询用户详情（含角色信息）
     *
     * @param userId 用户ID
     * @return 用户实体（密码已脱敏）
     */
    public User getUserDetail(String userId) {
        User user = getUserById(userId);
        user.setPasswordHash(null);
        return user;
    }

    /**
     * 创建用户
     *
     * @param phone    手机号
     * @param password 密码（明文）
     * @param nickname 昵称
     * @param role     角色代码
     * @param permissions 菜单权限码 JSON（如 ["orders.list","products.create"]）
     * @param tenantId 租户ID
     * @return 创建的用户
     */
    @Transactional(rollbackFor = Exception.class)
    public User createUser(String phone, String password, String nickname, String role, String position, String permissions, Long tenantId) {
        // 验证手机号唯一性
        LambdaQueryWrapper<User> wrapper = new LambdaQueryWrapper<>();
        wrapper.eq(User::getPhone, phone)
                .eq(User::getTenantId, tenantId)
                .eq(User::getDeleted, 0);
        User existing = userMapper.selectOne(wrapper);
        if (existing != null) {
            throw BusinessException.validationError("手机号已被注册: " + phone);
        }

        // 创建用户
        // password 为 null 时不设密码（对应 #375 禁用密码登录，走 SMS 验证码）
        String passwordHash = StringUtils.hasText(password)
                ? PASSWORD_ENCODER.encode(password)
                : null;
        User user = User.builder()
                .tenantId(tenantId)
                .phone(phone)
                .passwordHash(passwordHash)
                .nickname(nickname)
                .role(role != null ? role : "operator")
                .position(StringUtils.hasText(position) ? position : (role != null ? role : "operator"))
                .permissions(permissions)
                .status("active")
                .build();

        userMapper.insert(user);

        // 如果有角色，同步到 user_roles 表
        if (StringUtils.hasText(role)) {
            assignRoleToUser(user.getId(), role, tenantId);
        }

        log.info("创建用户成功: id={}, phone={}, role={}", user.getId(), phone, role);
        user.setPasswordHash(null);
        return user;
    }

    /**
     * 更新用户基本信息
     *
     * @param userId   用户ID
     * @param nickname 昵称
     * @param avatar   头像
     * @param role     角色
     * @param permissions 菜单权限码 JSON（如 ["orders.list","products.create"]），null 表示不修改
     * @return 更新后的用户
     */
    @Transactional(rollbackFor = Exception.class)
    public User updateUser(String userId, String nickname, String avatar, String role, String permissions) {
        User user = getUserById(userId);

        if (StringUtils.hasText(nickname)) {
            user.setNickname(nickname);
        }
        if (avatar != null) {
            user.setAvatar(avatar);
        }
        if (StringUtils.hasText(role) && !role.equals(user.getRole())) {
            user.setRole(role);
            // 更新 user_roles 表
            updateUserRole(userId, role, user.getTenantId());
        }
        if (permissions != null) {
            user.setPermissions(permissions);
        }

        userMapper.updateById(user);
        log.info("更新用户信息成功: id={}", userId);
        user.setPasswordHash(null);
        return user;
    }

    /**
     * 修改用户密码
     *
     * @param userId      用户ID
     * @param newPassword 新密码（明文）
     */
    @Transactional(rollbackFor = Exception.class)
    public void changePassword(String userId, String newPassword) {
        User user = getUserById(userId);
        user.setPasswordHash(PASSWORD_ENCODER.encode(newPassword));
        userMapper.updateById(user);
        log.info("修改用户密码成功: id={}", userId);
    }

    /**
     * 管理员重置用户密码
     * 重置为默认密码（手机号后6位）
     *
     * @param userId 用户ID
     * @return 重置后的默认密码
     */
    @Transactional(rollbackFor = Exception.class)
    public String resetPassword(String userId) {
        User user = getUserById(userId);
        String phone = user.getPhone();
        // 默认密码：手机号后6位
        String defaultPassword = phone.length() >= 6 ? phone.substring(phone.length() - 6) : phone;
        user.setPasswordHash(PASSWORD_ENCODER.encode(defaultPassword));
        userMapper.updateById(user);
        log.info("重置用户密码成功: id={}", userId);
        return defaultPassword;
    }

    /**
     * 禁用用户
     *
     * @param userId 用户ID
     */
    @Transactional(rollbackFor = Exception.class)
    public void disableUser(String userId) {
        User user = getUserById(userId);
        if ("disabled".equals(user.getStatus())) {
            throw BusinessException.validationError("用户已处于禁用状态");
        }
        user.setStatus("disabled");
        userMapper.updateById(user);
        log.info("禁用用户成功: id={}", userId);
    }

    /**
     * 启用用户
     *
     * @param userId 用户ID
     */
    @Transactional(rollbackFor = Exception.class)
    public void enableUser(String userId) {
        User user = getUserById(userId);
        if ("active".equals(user.getStatus())) {
            throw BusinessException.validationError("用户已处于启用状态");
        }
        user.setStatus("active");
        userMapper.updateById(user);
        log.info("启用用户成功: id={}", userId);
    }

    /**
     * 删除用户（逻辑删除）
     *
     * @param userId 用户ID
     */
    @Transactional(rollbackFor = Exception.class)
    public void deleteUser(String userId) {
        User user = getUserById(userId);
        userMapper.deleteById(userId);

        // 同时删除 user_roles 关联
        LambdaQueryWrapper<UserRole> wrapper = new LambdaQueryWrapper<>();
        wrapper.eq(UserRole::getUserId, userId);
        userRoleMapper.delete(wrapper);

        log.info("删除用户成功: id={}", userId);
    }

    // ==================== 内部辅助方法 ====================

    /**
     * 为用户分配角色（写入 user_roles 表）
     */
    private void assignRoleToUser(String userId, String roleCode, Long tenantId) {
        // 查找角色ID
        LambdaQueryWrapper<Role> roleWrapper = new LambdaQueryWrapper<>();
        roleWrapper.eq(Role::getCode, roleCode)
                .eq(Role::getTenantId, tenantId)
                .eq(Role::getDeleted, 0);
        Role role = roleMapper.selectOne(roleWrapper);
        if (role == null) {
            // 角色不存在时仅记录日志，不阻断流程（因为可能依赖 User.role 字段）
            log.warn("角色不存在于 roles 表: code={}, tenantId={}", roleCode, tenantId);
            return;
        }

        UserRole userRole = UserRole.builder()
                .tenantId(tenantId)
                .userId(userId)
                .roleId(role.getId())
                .build();
        userRoleMapper.insert(userRole);
    }

    /**
     * 更新用户角色（先删旧关联，再插新关联）
     */
    private void updateUserRole(String userId, String roleCode, Long tenantId) {
        // 删除旧的角色关联
        LambdaQueryWrapper<UserRole> deleteWrapper = new LambdaQueryWrapper<>();
        deleteWrapper.eq(UserRole::getUserId, userId);
        userRoleMapper.delete(deleteWrapper);

        // 添加新的角色关联
        assignRoleToUser(userId, roleCode, tenantId);
    }
}
