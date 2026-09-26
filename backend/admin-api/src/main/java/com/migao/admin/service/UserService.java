package com.migao.admin.service;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.PageResponse;
import com.migao.admin.entity.Role;
import com.migao.admin.entity.User;
import com.migao.admin.entity.UserRole;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.RoleMapper;
import com.migao.admin.mapper.UserMapper;
import com.migao.admin.mapper.UserRoleMapper;
import com.migao.admin.security.PermissionInterceptor;
import com.migao.admin.security.SecurityUser;
import com.migao.admin.support.LoginIdentifiers;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
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
    private final PermissionInterceptor permissionInterceptor;

    private static final BCryptPasswordEncoder PASSWORD_ENCODER = new BCryptPasswordEncoder();

    private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();

    /**
     * 系统保留角色：商户侧员工管理禁止赋值（防垂直越权，审计 07 P0-2）。
     * super_admin 平台超管仅由 platform_admins 表管理；service 为内部服务角色；
     * customer/agent 为 B2C 角色；tenant_admin 为历史遗留管理角色。
     */
    private static final java.util.Set<String> FORBIDDEN_USER_ROLES = java.util.Set.of(
            "super_admin", "service", "customer", "agent", "tenant_admin"
    );

    /**
     * 校验角色/权限是否允许由商户侧员工管理赋值。
     *
     * <p>三条护栏（第 3 条 = issue #4104，用户 2026-09-26 裁定
     * 「授予的权限码必须 ⊆ 操作者自身权限」）：</p>
     * <ol>
     *   <li>禁止系统保留角色（防垂直越权，审计 07 P0-2）；</li>
     *   <li>禁止通配权限码 {@code "*"}（超管 / 内部服务全权限）；</li>
     *   <li><b>授予集 ⊆ 操作者自身生效权限</b> —— 委托
     *       {@link PermissionInterceptor#assertGrantable} 判定（与 {@code @RequirePermission}
     *       同一份身份口径，不写第二份授权实现，issue #4148）。不满足 ⇒ 403
     *       {@code PERMISSION_ESCALATION_DENIED} + 点名违规码，且**在写库之前抛出**（不落半条）。</li>
     * </ol>
     *
     * @param role        角色代码（可能为 null，null 表示不指定）
     * @param permissions 权限码 JSON 数组字符串（可能为 null）
     * @param tenantId    目标租户 ID（所授角色**隐含**的权限码按该租户解析）
     */
    private void assertAssignableRoleAndPermissions(String role, String permissions, Long tenantId) {
        if (StringUtils.hasText(role) && FORBIDDEN_USER_ROLES.contains(role)) {
            throw BusinessException.validationError("角色 " + role + " 为系统保留角色，禁止在员工管理中分配");
        }
        if (permissions != null && permissions.contains("*")) {
            throw BusinessException.validationError("禁止授予通配权限 (*)，请勾选具体权限码");
        }
        permissionInterceptor.assertGrantable(role, parsePermissionSnapshot(permissions), tenantId);
    }

    /**
     * 解析 {@code users.permissions} 快照（JSON 数组字符串）为权限码列表。
     *
     * <p>解析不出来（不是合法 JSON 数组）⇒ 把整串当成**一个未知权限码**返回：调用方的 ⊆ 门禁
     * 必然判它「操作者不具备」⇒ 拒绝。**有意 fail-closed** —— 判不出授予集就不放行，
     * 不静默退化成「没人管」（旧形态：字符串原样落库，运行时
     * {@code RoleService.parseSnapshotPermissions} 同样解析不出 ⇒ 悄悄回退角色权限，
     * 谁都不知道实际写进去了什么）。</p>
     */
    private static List<String> parsePermissionSnapshot(String permissions) {
        if (!StringUtils.hasText(permissions)) {
            return List.of();
        }
        try {
            List<String> codes = OBJECT_MAPPER.readValue(permissions, new TypeReference<List<String>>() { });
            return codes == null ? List.of() : codes;
        } catch (Exception e) {
            log.warn("权限快照不是合法 JSON 数组，按未知权限码处理（fail-closed）: {}", permissions);
            return List.of(permissions.trim());
        }
    }

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
     * 当前登录用户的展示姓名（操作人留痕用，如发货单「发货人」，issue #3768）。
     *
     * <p>用 {@link SecurityUser#getUserId()} 查 users.nickname —— <b>不能</b>直接取
     * {@code SecurityUser.displayName}：内部服务调用（agent 代发）时它恒为
     * "internal-service"，B 端登录时它是 JWT 的 username（通常是手机号），都不是「姓名」。
     *
     * <p>真实操作人由两条路径共同保证：B 端 JWT（subject = users.id）、ai-agent 透传的
     * {@code X-User-Id}（{@code ServiceTokenFilter} 落到 {@code SecurityUser.userId}）。
     *
     * @return 姓名（昵称优先，退化为手机号）；解析不到（未认证 / 平台管理员 / 用户不存在）
     *         返回 null —— 这是尽力而为的展示字段，不抛异常打断发货主流程
     */
    public String resolveCurrentUserDisplayName() {
        Authentication auth = SecurityContextHolder.getContext().getAuthentication();
        if (auth == null || !(auth.getPrincipal() instanceof SecurityUser securityUser)) {
            return null;
        }
        String userId = securityUser.getUserId();
        if (!StringUtils.hasText(userId)) {
            return null;
        }
        User user = userMapper.selectById(userId);
        if (user == null) {
            return null;
        }
        if (StringUtils.hasText(user.getNickname())) {
            return user.getNickname();
        }
        return StringUtils.hasText(user.getPhone()) ? user.getPhone() : null;
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
            case "super_admin" -> List.of("*");
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

        // 员工管理范畴（issue #3004）：默认排除 C 端消费者账号（role=customer —— 微信小程序登录
        // 自动建号产生的账号，见 AuthService.findOrCreateMiniProgramUser），避免消费者混入 B 端员工列表。
        // 显式传 role=customer 筛选同样不返回：消费者不属于员工范畴，员工管理不管理消费者。
        wrapper.ne(User::getRole, "customer");

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
        return createUser(phone, password, nickname, role, position, permissions, tenantId, null, false);
    }

    /**
     * 创建员工账号（含员工登录用户名，issue #5485）。
     *
     * @param username           员工登录用户名（可空；非空时转小写 + 格式校验 + **租户内**唯一校验）
     * @param forceChangePassword 是否置 {@code must_change_password=true}
     *                           （⚠️ 只在「确实设了初始密码」时置 true：没有密码的账号被标成强制改密
     *                           会**永久锁死** —— 改密要校验旧密码，而旧密码是 null）
     */
    @Transactional(rollbackFor = Exception.class)
    public User createUser(String phone, String password, String nickname, String role, String position,
                           String permissions, Long tenantId, String username, boolean forceChangePassword) {
        // 安全校验：禁止商户侧分配系统保留角色/通配权限（审计 07 P0-2）+ 授予集 ⊆ 操作者自身权限（#4104）
        assertAssignableRoleAndPermissions(role, permissions, tenantId);

        // 验证手机号唯一性
        LambdaQueryWrapper<User> wrapper = new LambdaQueryWrapper<>();
        wrapper.eq(User::getPhone, phone)
                .eq(User::getTenantId, tenantId)
                .eq(User::getDeleted, 0);
        User existing = userMapper.selectOne(wrapper);
        if (existing != null) {
            throw BusinessException.validationError("手机号已被注册: " + phone);
        }

        String normalizedUsername = assertUsernameAssignable(username, tenantId, null);

        // 创建用户
        // password 为 null 时不设密码（对应 #375 禁用密码登录，走 SMS 验证码）
        String passwordHash = StringUtils.hasText(password)
                ? PASSWORD_ENCODER.encode(password)
                : null;
        User user = User.builder()
                .tenantId(tenantId)
                .phone(phone)
                .username(normalizedUsername)
                .passwordHash(passwordHash)
                // 强制改密只对「确实设了密码」的账号生效（见方法 javadoc）
                .mustChangePassword(forceChangePassword && passwordHash != null)
                .nickname(nickname)
                .role(role != null ? role : "operator")
                .position(StringUtils.hasText(position) ? position : (role != null ? role : "operator"))
                .permissions(permissions)
                .status("active")
                .build();

        try {
            userMapper.insert(user);
        } catch (org.springframework.dao.DuplicateKeyException e) {
            // 数据库唯一索引是**并发下的兜底**（应用层校验挡不住两个请求同时通过）
            throw BusinessException.validationError(usernameConflictMessage(normalizedUsername));
        }

        // 如果有角色，同步到 user_roles 表
        if (StringUtils.hasText(role)) {
            assignRoleToUser(user.getId(), role, tenantId);
        }

        log.info("创建用户成功: id={}, phone={}, role={}, hasUsername={}", user.getId(), phone, role,
                normalizedUsername != null);
        user.setPasswordHash(null);
        return user;
    }

    /**
     * 更新用户基本信息（兼容签名，不修改岗位/手机号）
     */
    @Transactional(rollbackFor = Exception.class)
    public User updateUser(String userId, String nickname, String avatar, String role, String permissions) {
        return updateUser(userId, nickname, avatar, role, null, permissions, null);
    }

    /**
     * 更新用户基本信息（兼容签名，不修改手机号）
     */
    @Transactional(rollbackFor = Exception.class)
    public User updateUser(String userId, String nickname, String avatar, String role, String position, String permissions) {
        return updateUser(userId, nickname, avatar, role, position, permissions, null);
    }

    /**
     * 更新用户基本信息
     *
     * @param userId   用户ID
     * @param nickname 昵称
     * @param avatar   头像
     * @param role     角色
     * @param position 岗位（null 表示不修改；岗位=角色体系 #2969，编辑切岗位时随角色联动）
     * @param permissions 菜单权限码 JSON（如 ["orders.list","products.create"]），null 表示不修改
     * @param phone    手机号（null/空白/与原值相同 表示不修改；变更时校验租户内唯一。
     *                 issue #3550：ai-agent 员工管理与 admin-web 员工编辑都下发 phone，
     *                 原先被静默忽略 → 200 假成功）
     * @return 更新后的用户
     */
    @Transactional(rollbackFor = Exception.class)
    public User updateUser(String userId, String nickname, String avatar, String role, String position,
                           String permissions, String phone) {
        return updateUser(userId, nickname, avatar, role, position, permissions, phone, null);
    }

    /**
     * 更新用户基本信息（含员工登录用户名，issue #5485）。
     *
     * @param username 员工登录用户名：{@code null} 表示不修改；非空时转小写 + 格式校验 +
     *                 **租户内**唯一校验（排除自己）—— A 企业的 zhangsan 不妨碍 B 企业的 zhangsan（I3）
     */
    @Transactional(rollbackFor = Exception.class)
    public User updateUser(String userId, String nickname, String avatar, String role, String position,
                           String permissions, String phone, String username) {
        // 安全校验：禁止商户侧分配系统保留角色/通配权限（审计 07 P0-2）+ 授予集 ⊆ 操作者自身权限（#4104）
        // 租户取自 TenantContext（员工管理写面恒在租户上下文内），且**保持在读取目标用户之前**：
        // 校验不通过时连目标行都不查（既有语义：越权请求不泄露"该 userId 存不存在"）。
        assertAssignableRoleAndPermissions(role, permissions, TenantContext.getTenantId());

        User user = getUserById(userId);

        if (StringUtils.hasText(nickname)) {
            user.setNickname(nickname);
        }
        if (avatar != null) {
            user.setAvatar(avatar);
        }
        if (position != null) {
            user.setPosition(position);
        }
        // 手机号变更（issue #3550）：与创建口径一致，校验租户内唯一
        if (StringUtils.hasText(phone) && !phone.equals(user.getPhone())) {
            LambdaQueryWrapper<User> phoneWrapper = new LambdaQueryWrapper<>();
            phoneWrapper.eq(User::getPhone, phone)
                    .eq(User::getTenantId, user.getTenantId())
                    .eq(User::getDeleted, 0);
            User existing = userMapper.selectOne(phoneWrapper);
            if (existing != null && !existing.getId().equals(userId)) {
                throw BusinessException.validationError("手机号已被注册: " + phone);
            }
            user.setPhone(phone);
        }
        // 用户名变更（issue #5485）：与创建口径一致，校验**租户内**唯一（排除自己）
        String normalizedUsername = assertUsernameAssignable(username, user.getTenantId(), userId);
        if (normalizedUsername != null) {
            user.setUsername(normalizedUsername);
        }
        if (StringUtils.hasText(role) && !role.equals(user.getRole())) {
            user.setRole(role);
            // 更新 user_roles 表
            updateUserRole(userId, role, user.getTenantId());
        }
        if (permissions != null) {
            // 快照式（#2969）：员工权限 = 员工管理保存的勾选
            user.setPermissions(permissions);
        }

        try {
            userMapper.updateById(user);
        } catch (org.springframework.dao.DuplicateKeyException e) {
            // 数据库唯一索引兜底（并发下应用层校验可能双双通过）
            throw BusinessException.validationError(usernameConflictMessage(normalizedUsername));
        }
        log.info("更新用户信息成功: id={}, hasUsername={}", userId, normalizedUsername != null);
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
        changePassword(userId, newPassword, true);
    }

    /**
     * 修改用户密码（可指定是否要求首登改密，issue #5485）。
     *
     * @param forceChangePassword {@code true} ⇒ 置 {@code must_change_password=true}
     *        （管理员设的密码是「初始密码」，员工首登必须改掉）
     */
    @Transactional(rollbackFor = Exception.class)
    public void changePassword(String userId, String newPassword, boolean forceChangePassword) {
        User user = getUserById(userId);
        user.setPasswordHash(PASSWORD_ENCODER.encode(newPassword));
        user.setMustChangePassword(forceChangePassword);
        userMapper.updateById(user);
        log.info("修改用户密码成功: id={}, forceChange={}", userId, forceChangePassword);
    }

    /**
     * 员工用户名可赋值性校验（issue #5485）：规整 → 格式 → **租户内**唯一。
     *
     * @param username   原始输入（null / 空白 ⇒ 返回 null，表示「不设置/不修改」）
     * @param tenantId   目标租户（唯一性**只到租户内** —— 不同企业可同名，这是 I3 的实现点）
     * @param excludeUserId 唯一性校验时排除的用户（改自己时排除自己；创建传 null）
     * @return 规整后的用户名（小写）
     */
    private String assertUsernameAssignable(String username, Long tenantId, String excludeUserId) {
        if (username == null || username.isBlank()) {
            return null;
        }
        String normalized = LoginIdentifiers.normalize(username);
        if (!LoginIdentifiers.isValidUsername(normalized)) {
            throw BusinessException.validationError(LoginIdentifiers.USERNAME_RULE);
        }
        LambdaQueryWrapper<User> wrapper = new LambdaQueryWrapper<>();
        wrapper.eq(User::getUsername, normalized)
                .eq(User::getTenantId, tenantId)
                .eq(User::getDeleted, 0);
        User existing = userMapper.selectOne(wrapper);
        if (existing != null && !existing.getId().equals(excludeUserId)) {
            throw BusinessException.validationError(usernameConflictMessage(normalized));
        }
        return normalized;
    }

    /** 用户名租户内重复的**明确文案**（422，不靠数据库异常裸抛 500；提示「换一个」）。 */
    private static String usernameConflictMessage(String username) {
        return "用户名「" + username + "」在本企业已被占用，请换一个（不同企业之间可以同名）";
    }

    /**
     * 管理员重置用户密码
     * 重置为默认密码（手机号后6位）
     *
     * <p>issue #5485：重置后**必须**置 {@code must_change_password=true} —— 管理员知道这个密码，
     * 它只是「初始密码」，员工首登必须改成自己的。</p>
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
        user.setMustChangePassword(true);
        userMapper.updateById(user);
        log.info("重置用户密码成功（已置强制改密）: id={}", userId);
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
