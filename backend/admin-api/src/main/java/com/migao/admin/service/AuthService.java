package com.migao.admin.service;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.LoginRequest;
import com.migao.admin.dto.LoginResponse;
import com.migao.admin.dto.UserInfoResponse;
import com.migao.admin.entity.Tenant;
import com.migao.admin.entity.User;
import com.migao.admin.entity.UserIdentity;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.TenantMapper;
import com.migao.admin.mapper.UserIdentityMapper;
import com.migao.admin.mapper.UserMapper;
import com.migao.admin.security.JwtTokenProvider;
import com.migao.admin.security.SecurityUser;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import io.jsonwebtoken.Claims;
import jakarta.servlet.http.Cookie;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.time.Duration;
import java.time.OffsetDateTime;
import java.util.List;

/**
 * 认证服务类
 * 处理登录、登出、Token 刷新、获取当前用户信息等认证相关逻辑
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class AuthService {

    private final UserService userService;
    private final RoleService roleService;
    private final WechatService wechatService;
    private final SmsService smsService;
    private final JwtTokenProvider jwtTokenProvider;
    private final PasswordEncoder passwordEncoder;
    private final StringRedisTemplate redisTemplate;
    private final UserMapper userMapper;
    private final UserIdentityMapper userIdentityMapper;
    private final TenantMapper tenantMapper;

    /**
     * Redis Token 黑名单 key 前缀
     */
    private static final String TOKEN_BLACKLIST_PREFIX = "token:blacklist:";

    @Value("${jwt.cookie.name:access_token}")
    private String cookieName;

    @Value("${jwt.cookie.domain:}")
    private String cookieDomain;

    @Value("${jwt.cookie.path:/}")
    private String cookiePath;

    @Value("${jwt.cookie.secure:true}")
    private boolean cookieSecure;

    @Value("${jwt.cookie.http-only:true}")
    private boolean cookieHttpOnly;

    @Value("${jwt.cookie.same-site:strict}")
    private String cookieSameSite;

    // ======================== 账号密码登录 ========================

    /**
     * 管理后台登录（账号密码）
     *
     * @param request  登录请求
     * @param response HTTP 响应（用于设置 Cookie）
     * @return 登录响应
     */
    @Deprecated // #375
    public LoginResponse adminLogin(LoginRequest request, HttpServletResponse response) {
        throw BusinessException.authFailed("密码登录已禁用，请使用短信验证码登录");
    }

    /**
     * 验证用户凭据
     */
    private User authenticateUser(String username, String password, Long tenantId) {
        User user = userService.getUserByUsernameAndTenant(username, tenantId);
        if (user == null) {
            log.warn("用户不存在: username={}, tenantId={}", username, tenantId);
            throw BusinessException.authFailed("用户名或密码错误");
        }

        if (!passwordEncoder.matches(password, user.getPasswordHash())) {
            log.warn("密码错误: username={}, tenantId={}", username, tenantId);
            throw BusinessException.authFailed("用户名或密码错误");
        }

        if (!"active".equals(user.getStatus())) {
            log.warn("用户状态异常: username={}, status={}", username, user.getStatus());
            throw BusinessException.authFailed("用户状态异常");
        }

        return user;
    }

    // ======================== 短信验证码登录 ========================

    /**
     * 短信验证码登录
     * 仅允许企业管理员（admin 角色）通过短信验证码登录
     *
     * @param phone    手机号
     * @param code     短信验证码
     * @param response HTTP 响应（用于设置 Cookie）
     * @return 登录响应
     */
    @Transactional(rollbackFor = Exception.class)
    public LoginResponse loginBySms(String phone, String code, HttpServletResponse response) {
        log.info("短信验证码登录: phone={}", phone);

        // 1. 校验短信验证码
        boolean verified = smsService.verifyCode(phone, code);
        if (!verified) {
            throw BusinessException.authFailed("短信验证码错误或已过期");
        }

        // 2. 根据手机号查找用户（跨租户查询，使用 @InterceptorIgnore 绕过多租户拦截器）
        User user = userMapper.selectAdminByPhoneIgnoreTenant(phone);
        if (user == null) {
            log.warn("短信登录失败，用户不存在或不是管理员: phone={}", phone);
            throw BusinessException.authFailed("该手机号未注册或无管理员权限");
        }

        // 3. 校验用户状态
        if (!"active".equals(user.getStatus())) {
            log.warn("短信登录失败，用户状态异常: phone={}, status={}", phone, user.getStatus());
            throw BusinessException.authFailed("用户状态异常");
        }

        // 4. 设置租户上下文
        TenantContext.setTenantId(user.getTenantId());

        // 5. 获取用户角色
        List<String> roles = userService.getUserRoles(user);

        // 6. 签发 JWT Token
        String accessToken = jwtTokenProvider.generateAccessToken(
                user.getId(),
                user.getTenantId(),
                user.getPhone(),
                roles
        );

        String refreshToken = jwtTokenProvider.generateRefreshToken(
                user.getId(),
                user.getTenantId()
        );

        // 7. 设置 HttpOnly Cookie
        setTokenCookie(response, accessToken, (int) jwtTokenProvider.getAccessTokenExpiration());

        // 8. 查询租户名称
        String tenantName = getTenantName(user.getTenantId());

        // 9. 构建响应
        return LoginResponse.builder()
                .user(LoginResponse.UserInfo.builder()
                        .id(user.getId())
                        .nickname(user.getNickname())
                        .avatar(user.getAvatar())
                        .role(user.getRole())
                        .identityType("sms")
                        .roles(roles)
                        .tenantId(user.getTenantId())
                        .tenantName(tenantName)
                        .build())
                .accessToken(accessToken)
                .refreshToken(refreshToken)
                .expiresIn(jwtTokenProvider.getAccessTokenExpiration())
                .build();
    }

    // ======================== 微信小程序登录 ========================

    /**
     * 微信小程序登录
     *
     * @param code     微信小程序登录 code（wx.login() 获取）
     * @param tenantId 租户ID
     * @param response HTTP 响应
     * @return 登录响应
     */
    @Transactional(rollbackFor = Exception.class)
    public LoginResponse miniProgramLogin(String code, Long tenantId, HttpServletResponse response) {
        log.info("微信小程序登录: tenantId={}", tenantId);

        // 0. 设置租户上下文
        TenantContext.setTenantId(tenantId);

        // 1. 调用微信 code2Session 接口，用 code 换取 openid + session_key
        WechatService.Code2SessionResult sessionResult = wechatService.code2Session(code);
        String openid = sessionResult.getOpenid();

        // 2. 根据 openid + tenantId 查找用户身份
        User user = findOrCreateMiniProgramUser(openid, tenantId);

        // 3. 获取用户角色
        List<String> roles = userService.getUserRoles(user);

        // 4. 签发 JWT Token（username 字段放 openid）
        String accessToken = jwtTokenProvider.generateAccessToken(
                user.getId(),
                user.getTenantId(),
                openid,
                roles
        );

        String refreshToken = jwtTokenProvider.generateRefreshToken(
                user.getId(),
                user.getTenantId()
        );

        // 5. 设置 HttpOnly Cookie
        setTokenCookie(response, accessToken, (int) jwtTokenProvider.getAccessTokenExpiration());

        // 6. 查询租户名称
        String tenantNameVal = getTenantName(user.getTenantId());

        // 7. 构建响应
        return LoginResponse.builder()
                .user(LoginResponse.UserInfo.builder()
                        .id(user.getId())
                        .nickname(user.getNickname())
                        .avatar(user.getAvatar())
                        .role(user.getRole())
                        .identityType("mini_program")
                        .roles(roles)
                        .tenantId(user.getTenantId())
                        .tenantName(tenantNameVal)
                        .build())
                .accessToken(accessToken)
                .refreshToken(refreshToken)
                .expiresIn(jwtTokenProvider.getAccessTokenExpiration())
                .build();
    }

    /**
     * 根据 openid + tenantId 查找或创建微信小程序用户
     */
    private User findOrCreateMiniProgramUser(String openid, Long tenantId) {
        // 在 user_identities 表中查找
        LambdaQueryWrapper<UserIdentity> identityWrapper = new LambdaQueryWrapper<>();
        identityWrapper.eq(UserIdentity::getOpenid, openid)
                .eq(UserIdentity::getTenantId, tenantId)
                .eq(UserIdentity::getIdentityType, "mini_program")
                .eq(UserIdentity::getDeleted, 0);
        UserIdentity identity = userIdentityMapper.selectOne(identityWrapper);

        if (identity != null) {
            // 用户已存在，更新最后登录时间
            User user = userMapper.selectById(identity.getUserId());
            if (user == null || user.getDeleted() != null && user.getDeleted() == 1) {
                log.warn("用户身份记录存在但用户不存在: openid={}, userId={}", openid, identity.getUserId());
                throw BusinessException.authFailed("用户账号异常，请联系客服");
            }
            if (!"active".equals(user.getStatus())) {
                throw BusinessException.authFailed("用户状态异常");
            }
            // 更新最后活跃时间
            user.setUpdatedAt(OffsetDateTime.now());
            userMapper.updateById(user);
            log.info("微信小程序用户已存在，更新登录时间: userId={}, openid={}", user.getId(), openid);
            return user;
        }

        // 用户不存在，自动创建
        User newUser = User.builder()
                .tenantId(tenantId)
                .nickname("微信用户")
                .role("customer")
                .status("active")
                .build();
        userMapper.insert(newUser);

        // 创建身份关联记录
        UserIdentity newIdentity = UserIdentity.builder()
                .tenantId(tenantId)
                .userId(newUser.getId())
                .identityType("mini_program")
                .openid(openid)
                .build();
        userIdentityMapper.insert(newIdentity);

        log.info("自动创建微信小程序用户: userId={}, openid={}", newUser.getId(), openid);
        return newUser;
    }

    // ======================== 微信公众号 OAuth 登录（占位） ========================

    /**
     * 构建微信公众号 OAuth 授权跳转 URL（占位实现）
     *
     * TODO: 接入微信公众号 OAuth 2.0 接口
     *
     * @param tenantCode  租户编码
     * @param redirectUri 授权回调地址
     * @return 微信 OAuth 授权 URL
     */
    public String buildWechatH5AuthorizeUrl(String tenantCode, String redirectUri) {
        log.info("构建微信公众号 OAuth URL: tenantCode={}, redirectUri={}", tenantCode, redirectUri);

        // TODO: 实现步骤
        // 1. 根据 tenantCode 查询租户的公众号 AppID
        // 2. 生成 state 参数（含 tenantCode，用于 CSRF 防护）
        // 3. 构建微信 OAuth 授权 URL

        throw new BusinessException("NOT_IMPLEMENTED", "微信公众号 OAuth 尚未实现", 501);
    }

    /**
     * 微信公众号 OAuth 回调处理（占位实现）
     *
     * TODO: 接入微信 OAuth 回调，用 code 换取 access_token 和用户信息
     *
     * @param code     微信 OAuth 回调的临时 code
     * @param state    状态参数（含 tenantCode）
     * @param response HTTP 响应
     * @return 重定向 URL
     */
    public String handleWechatH5Callback(String code, String state, HttpServletResponse response) {
        log.info("微信公众号 OAuth 回调: code={}, state={}", code, state);

        // TODO: 实现步骤
        // 1. 验证 state 参数（CSRF 防护）
        // 2. 用 code 换取 access_token + openid
        // 3. 获取用户信息（昵称、头像等）
        // 4. 通过 openid/unionid 查找或创建用户
        // 5. 签发 JWT Token，通过 Set-Cookie 写入

        throw new BusinessException("NOT_IMPLEMENTED", "微信公众号 OAuth 尚未实现", 501);
    }

    // ======================== Token 刷新 ========================

    /**
     * 刷新 Token
     *
     * @param refreshToken 刷新 Token
     * @param response     HTTP 响应（用于设置 Cookie）
     * @return 新的登录响应
     */
    public LoginResponse refreshToken(String refreshToken, HttpServletResponse response) {
        log.info("刷新 Token");

        // 验证 Refresh Token
        if (!jwtTokenProvider.validateToken(refreshToken) || !jwtTokenProvider.isRefreshToken(refreshToken)) {
            throw BusinessException.authFailed("无效的 Refresh Token");
        }

        // 检查 Refresh Token 是否被吊销
        Claims claims = jwtTokenProvider.getClaimsFromToken(refreshToken);
        String jti = claims.getId();
        if (jti != null && isTokenBlacklisted(jti)) {
            throw BusinessException.authFailed("Refresh Token 已吊销");
        }

        // 从 Token 中提取用户信息
        String userId = jwtTokenProvider.getUserIdFromToken(refreshToken);

        // 查询用户
        User user = userService.getUserById(userId);
        if (user == null) {
            throw BusinessException.authFailed("用户不存在");
        }

        if (!"active".equals(user.getStatus())) {
            throw BusinessException.authFailed("用户状态异常");
        }

        // 获取用户角色
        List<String> roles = userService.getUserRoles(user);

        // 签发新的 Token
        String newAccessToken = jwtTokenProvider.generateAccessToken(
                user.getId(),
                user.getTenantId(),
                user.getPhone(),
                roles
        );

        String newRefreshToken = jwtTokenProvider.generateRefreshToken(
                user.getId(),
                user.getTenantId()
        );

        // 将旧的 Refresh Token 加入黑名单（防止重复使用）
        if (jti != null) {
            long ttl = claims.getExpiration().getTime() - System.currentTimeMillis();
            if (ttl > 0) {
                blacklistToken(jti, ttl);
            }
        }

        // 设置新的 Cookie
        setTokenCookie(response, newAccessToken, (int) jwtTokenProvider.getAccessTokenExpiration());

        // 查询租户名称
        String tenantName = getTenantName(user.getTenantId());

        return LoginResponse.builder()
                .user(LoginResponse.UserInfo.builder()
                        .id(user.getId())
                        .nickname(user.getNickname())
                        .avatar(user.getAvatar())
                        .role(user.getRole())
                        .identityType("account")
                        .roles(roles)
                        .tenantId(user.getTenantId())
                        .tenantName(tenantName)
                        .build())
                .accessToken(newAccessToken)
                .refreshToken(newRefreshToken)
                .expiresIn(jwtTokenProvider.getAccessTokenExpiration())
                .build();
    }

    // ======================== 登出 ========================

    /**
     * 登出
     * 将当前 Token 加入 Redis 黑名单，清除 Cookie
     *
     * @param request  HTTP 请求
     * @param response HTTP 响应（用于清除 Cookie）
     */
    public void logout(HttpServletRequest request, HttpServletResponse response) {
        log.info("用户登出");

        // 从请求中获取 Token 并加入黑名单
        String token = extractTokenFromRequest(request);
        if (StringUtils.hasText(token)) {
            try {
                Claims claims = jwtTokenProvider.getClaimsFromToken(token);
                String jti = claims.getId();
                if (jti != null) {
                    long ttl = claims.getExpiration().getTime() - System.currentTimeMillis();
                    if (ttl > 0) {
                        blacklistToken(jti, ttl);
                        log.info("Token 已加入黑名单: jti={}", jti);
                    }
                }
            } catch (Exception e) {
                log.warn("Token 解析失败（可能已过期），跳过黑名单: {}", e.getMessage());
            }
        }

        // 清除 Cookie
        clearTokenCookie(response);
    }

    // ======================== 获取当前用户信息 ========================

    /**
     * 获取当前登录用户信息（含角色、权限）
     *
     * @return 用户信息响应
     */
    public UserInfoResponse getCurrentUser() {
        Authentication authentication = SecurityContextHolder.getContext().getAuthentication();
        if (authentication == null || !authentication.isAuthenticated()) {
            throw BusinessException.authFailed("用户未认证");
        }

        Object principal = authentication.getPrincipal();
        if (!(principal instanceof SecurityUser securityUser)) {
            throw BusinessException.authFailed("无法获取用户信息");
        }

        // 查询用户详细信息
        User user = userService.getUserById(securityUser.getUserId());
        if (user == null) {
            throw BusinessException.authFailed("用户不存在");
        }

        // 查询用户权限
        List<String> permissions = roleService.getUserPermissions(user.getId());

        // 构建菜单列表（根据权限）
        List<UserInfoResponse.MenuItem> menus = buildMenusByPermissions(permissions);

        // 查询租户名称
        String tenantName = getTenantName(user.getTenantId());

        return UserInfoResponse.builder()
                .user(UserInfoResponse.UserInfo.builder()
                        .id(user.getId())
                        .username(user.getPhone())
                        .nickname(user.getNickname())
                        .avatar(user.getAvatar())
                        .tenantId(user.getTenantId())
                        .tenantName(tenantName)
                        .status(user.getStatus())
                        .build())
                .roles(securityUser.getRoles())
                .permissions(permissions)
                .menus(menus)
                .build();
    }

    // ======================== 租户名称查询 ========================

    /**
     * 根据租户ID查询租户名称
     *
     * @param tenantId 租户ID
     * @return 租户名称，不存在则返回 null
     */
    private String getTenantName(Long tenantId) {
        if (tenantId == null) {
            return null;
        }
        try {
            Tenant tenant = tenantMapper.selectById(tenantId);
            return tenant != null ? tenant.getName() : null;
        } catch (Exception e) {
            log.warn("查询租户名称失败: tenantId={}, error={}", tenantId, e.getMessage());
            return null;
        }
    }

    // ======================== Redis 黑名单 ========================

    /**
     * 将 Token 加入 Redis 黑名单
     *
     * @param jti    Token 唯一标识
     * @param ttlMs  剩余有效期（毫秒）
     */
    private void blacklistToken(String jti, long ttlMs) {
        try {
            redisTemplate.opsForValue().set(
                    TOKEN_BLACKLIST_PREFIX + jti,
                    "1",
                    Duration.ofMillis(ttlMs)
            );
        } catch (Exception e) {
            log.error("Token 加入黑名单失败: jti={}, error={}", jti, e.getMessage());
        }
    }

    /**
     * 检查 Token 是否在黑名单中
     */
    private boolean isTokenBlacklisted(String jti) {
        try {
            return Boolean.TRUE.equals(redisTemplate.hasKey(TOKEN_BLACKLIST_PREFIX + jti));
        } catch (Exception e) {
            log.warn("Redis 黑名单检查异常: {}", e.getMessage());
            return false;
        }
    }

    // ======================== Cookie 操作 ========================

    /**
     * 设置 Token Cookie（含 SameSite 属性）
     */
    private void setTokenCookie(HttpServletResponse response, String token, int maxAge) {
        StringBuilder cookieValue = new StringBuilder();
        cookieValue.append(cookieName).append("=").append(token);
        cookieValue.append("; Max-Age=").append(maxAge);
        cookieValue.append("; Path=").append(cookiePath);

        if (cookieHttpOnly) {
            cookieValue.append("; HttpOnly");
        }
        if (cookieSecure) {
            cookieValue.append("; Secure");
        }
        if (StringUtils.hasText(cookieDomain)) {
            cookieValue.append("; Domain=").append(cookieDomain);
        }
        if (StringUtils.hasText(cookieSameSite)) {
            cookieValue.append("; SameSite=").append(cookieSameSite);
        }

        response.addHeader("Set-Cookie", cookieValue.toString());
    }

    /**
     * 清除 Token Cookie
     */
    private void clearTokenCookie(HttpServletResponse response) {
        StringBuilder cookieValue = new StringBuilder();
        cookieValue.append(cookieName).append("=");
        cookieValue.append("; Max-Age=0");
        cookieValue.append("; Path=").append(cookiePath);

        if (cookieHttpOnly) {
            cookieValue.append("; HttpOnly");
        }
        if (cookieSecure) {
            cookieValue.append("; Secure");
        }
        if (StringUtils.hasText(cookieDomain)) {
            cookieValue.append("; Domain=").append(cookieDomain);
        }
        if (StringUtils.hasText(cookieSameSite)) {
            cookieValue.append("; SameSite=").append(cookieSameSite);
        }

        response.addHeader("Set-Cookie", cookieValue.toString());
    }

    /**
     * 从请求中提取 Token
     */
    private String extractTokenFromRequest(HttpServletRequest request) {
        // 从 Cookie 中提取
        Cookie[] cookies = request.getCookies();
        if (cookies != null) {
            for (Cookie cookie : cookies) {
                if (cookieName.equals(cookie.getName())) {
                    return cookie.getValue();
                }
            }
        }

        // 从 Authorization Header 中提取
        String bearerToken = request.getHeader("Authorization");
        if (StringUtils.hasText(bearerToken) && bearerToken.startsWith("Bearer ")) {
            return bearerToken.substring(7);
        }

        return null;
    }

    // ======================== 菜单构建 ========================

    /**
     * 根据权限构建菜单列表
     */
    private List<UserInfoResponse.MenuItem> buildMenusByPermissions(List<String> permissions) {
        boolean isAllPermission = permissions.contains("*");

        List<UserInfoResponse.MenuItem> menus = new java.util.ArrayList<>();

        // 仪表板（所有角色可见）
        menus.add(UserInfoResponse.MenuItem.builder()
                .key("dashboard").name("数据概览").icon("LayoutDashboard").path("/dashboard").build());

        if (isAllPermission || permissions.contains("product:manage")) {
            menus.add(UserInfoResponse.MenuItem.builder()
                    .key("products").name("商品管理").icon("Package").path("/products").build());
        }

        if (isAllPermission || permissions.contains("processing:manage")) {
            menus.add(UserInfoResponse.MenuItem.builder()
                    .key("processing").name("加工管理").icon("Wrench").path("/processing").build());
        }

        if (isAllPermission || permissions.contains("knowledge:manage")) {
            menus.add(UserInfoResponse.MenuItem.builder()
                    .key("knowledge").name("知识库").icon("BookOpen").path("/knowledge").build());
        }

        if (isAllPermission || permissions.contains("system:manage")) {
            menus.add(UserInfoResponse.MenuItem.builder()
                    .key("settings").name("系统设置").icon("Settings").path("/settings").build());
        }

        return menus;
    }
}
