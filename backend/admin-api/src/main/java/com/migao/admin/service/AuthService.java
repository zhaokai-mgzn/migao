package com.migao.admin.service;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.BminiLoginRequest;
import com.migao.admin.dto.LoginRequest;
import com.migao.admin.dto.LoginResponse;
import com.migao.admin.dto.UserInfoResponse;
import com.migao.admin.entity.PlatformAdmin;
import com.migao.admin.entity.Tenant;
import com.migao.admin.entity.User;
import com.migao.admin.entity.UserIdentity;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.PlatformAdminMapper;
import com.migao.admin.mapper.TenantMapper;
import com.migao.admin.mapper.UserIdentityMapper;
import com.migao.admin.mapper.UserMapper;
import com.migao.admin.security.JwtTokenProvider;
import com.migao.admin.security.SecurityUser;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import io.jsonwebtoken.Claims;
import io.micrometer.core.instrument.MeterRegistry;
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
    private final MeterRegistry meterRegistry;
    private final UserMapper userMapper;
    private final UserIdentityMapper userIdentityMapper;
    private final TenantMapper tenantMapper;
    private final PlatformAdminMapper platformAdminMapper;
    private final com.migao.admin.mapper.TenantAiConfigMapper tenantAiConfigMapper;
    private final CustomerService customerService;

    /**
     * Redis Token 黑名单 key 前缀
     */
    private static final String TOKEN_BLACKLIST_PREFIX = "token:blacklist:";

    /**
     * 吊销检查「不可执行」的可观测读数（Micrometer counter）。
     * 与 {@code JwtAuthenticationFilter} 使用**同一个**字面量（由
     * {@code tests/unit_ci_workflows/test_declared_vs_effective.py} 钉住，防两处各自演化）。
     */
    public static final String BLACKLIST_CHECK_UNAVAILABLE_METRIC = "migao.security.revocation_check_unavailable";

    /** 吊销检查不可执行时的日志关键词（告警规则按它匹配 —— 静默降级换绿必红）。 */
    public static final String BLACKLIST_CHECK_UNAVAILABLE_KEYWORD = "REVOCATION_CHECK_UNAVAILABLE";

    /**
     * Refresh Token Cookie 名（审计 07 P1-5/P1-F1）：
     * refresh token 只经 HttpOnly Cookie 承载，禁止下发到响应体（防前端存储进 localStorage/XSS 窃取）。
     */
    private static final String REFRESH_TOKEN_COOKIE = "refresh_token";

    /** Refresh Token Cookie 有效期（秒）：7 天，与 JWT refresh-token-expiration 对齐 */
    private static final int REFRESH_TOKEN_COOKIE_MAX_AGE = 604800;

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

    /** B 端员工小程序 appid（issue #2977：绑定/查询 user_identities 时隔离渠道） */
    @Value("${wechat.bmini.appid:}")
    private String bminiAppId;

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
     * @param tenantId 租户 ID（可选）。同手机号存在于多个租户时必填（审计 07 P1-2）
     * @param response HTTP 响应（用于设置 Cookie）
     * @return 登录响应
     */
    @Transactional(rollbackFor = Exception.class)
    public LoginResponse loginBySms(String phone, String code, Long tenantId, HttpServletResponse response) {
        log.info("短信验证码登录: phone={}", phone);

        // 1. 校验短信验证码
        boolean verified = smsService.verifyCode(phone, code);
        if (!verified) {
            throw BusinessException.authFailed("短信验证码错误或已过期");
        }

        // 2. 先查平台管理员表（platform_admins，无租户归属）
        PlatformAdmin platformAdmin = platformAdminMapper.selectOne(
            new LambdaQueryWrapper<PlatformAdmin>()
                .eq(PlatformAdmin::getPhone, phone)
        );
        if (platformAdmin != null) {
            if (!"active".equals(platformAdmin.getStatus())) {
                log.warn("平台管理员短信登录失败，状态异常: phone={}, status={}", phone, platformAdmin.getStatus());
                throw BusinessException.authFailed("账号状态异常");
            }

            // 平台管理员 JWT，tenantId=-1 表示无租户归属
            List<String> roles = List.of("super_admin");
            String accessToken = jwtTokenProvider.generateAccessToken(
                    platformAdmin.getId(),
                    -1L,
                    platformAdmin.getPhone(),
                    roles
            );
            String refreshToken = jwtTokenProvider.generateRefreshToken(
                    platformAdmin.getId(),
                    -1L
            );

            setTokenCookie(response, accessToken, (int) jwtTokenProvider.getAccessTokenExpiration());
            // 审计 07 P1-5：refresh token 仅经 HttpOnly cookie 下发，不进响应体
            setRefreshTokenCookie(response, refreshToken);

            // 更新最后登录时间
            platformAdmin.setLastLoginAt(OffsetDateTime.now());
            platformAdminMapper.updateById(platformAdmin);

            log.info("平台管理员登录成功: phone={}", phone);
            return LoginResponse.builder()
                    .user(LoginResponse.UserInfo.builder()
                            .id(platformAdmin.getId())
                            .nickname(platformAdmin.getNickname())
                            .role("super_admin")
                            .identityType("sms")
                            .roles(roles)
                            .tenantId(-1L)
                            .tenantName("米高平台管理")
                            .build())
                    .accessToken(accessToken)
                    .refreshToken(null)  // 审计 07 P1-5: 不下发，仅 HttpOnly cookie
                    .expiresIn(jwtTokenProvider.getAccessTokenExpiration())
                    .build();
        }

        // 3. 根据手机号查找租户用户（跨租户查询，使用 @InterceptorIgnore 绕过多租户拦截器）
        List<User> users = userMapper.selectActiveUsersByPhoneIgnoreTenant(phone);
        if (users.isEmpty()) {
            log.warn("短信登录失败，用户不存在或已禁用: phone={}", maskPhone(phone));
            throw BusinessException.authFailed("该手机号未注册");
        }

        // 3.1 同手机号多租户歧义处理（审计 07 P1-2：禁止静默 LIMIT 1 落错租户）
        User user;
        if (users.size() == 1) {
            user = users.get(0);
        } else {
            if (tenantId == null) {
                log.warn("短信登录失败，手机号关联多个租户且未指定租户: phone={}", maskPhone(phone));
                throw BusinessException.authFailed(
                        "该手机号关联多个租户账号，请通过对应租户入口登录或指定租户后重试");
            }
            user = users.stream()
                    .filter(u -> tenantId.equals(u.getTenantId()))
                    .findFirst()
                    .orElseThrow(() -> BusinessException.authFailed("该手机号在该租户下未注册"));
        }

        // 4. 校验用户状态
        if (!"active".equals(user.getStatus())) {
            log.warn("短信登录失败，用户状态异常: phone={}, status={}", phone, user.getStatus());
            throw BusinessException.authFailed("用户状态异常");
        }

        // 5. 设置租户上下文
        TenantContext.setTenantId(user.getTenantId());

        // 6. 获取用户角色和权限
        List<String> roles = userService.getUserRoles(user);
        List<String> permissions = roleService.getUserPermissions(user.getId());

        // 7. 签发 JWT Token（含细粒度权限）
        String accessToken = jwtTokenProvider.generateAccessToken(
                user.getId(),
                user.getTenantId(),
                user.getPhone(),
                roles,
                permissions
        );

        String refreshToken = jwtTokenProvider.generateRefreshToken(
                user.getId(),
                user.getTenantId()
        );

        // 8. 设置 HttpOnly Cookie
        setTokenCookie(response, accessToken, (int) jwtTokenProvider.getAccessTokenExpiration());
        // 审计 07 P1-5：refresh token 仅经 HttpOnly cookie 下发，不进响应体
        setRefreshTokenCookie(response, refreshToken);

        // 9. 查询租户名称
        String tenantName = getTenantName(user.getTenantId());

        // 10. 构建响应
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
                        .botName(getBotName(user.getTenantId()))
                        .build())
                .accessToken(accessToken)
                .refreshToken(null)  // 审计 07 P1-5: 不下发，仅 HttpOnly cookie
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

        // 0. 租户存在性校验（审计 07 P1-1）：拒绝向不存在的租户自动建号/注入用户。
        //    注意：租户 ID 仍由客户端传入，完整修复需服务端按微信 appid→租户绑定解析（技术债），
        //    此处先封堵"任意数字即可建号"与 Mock 伪造 openid 两条捷径。
        if (tenantId == null) {
            throw BusinessException.validationError("租户标识不能为空");
        }
        Tenant tenant = tenantMapper.selectById(tenantId);
        if (tenant == null || !"active".equals(tenant.getStatus())) {
            throw BusinessException.authFailed("租户不存在或未启用");
        }

        // 0.1 设置租户上下文
        TenantContext.setTenantId(tenantId);

        // 1. 调用微信 code2Session 接口，用 code 换取 openid + session_key
        WechatService.Code2SessionResult sessionResult = wechatService.code2Session(code);
        String openid = sessionResult.getOpenid();

        // 2. 根据 openid + tenantId 查找用户身份
        User user = findOrCreateMiniProgramUser(openid, tenantId);
        // C 端登录自动落 CRM 客户档案（issue #3011）：幂等 upsert（openid 已存在则刷新
        // last_active_at 并返回既有档案）；建档失败不阻断登录（客户台账为增量能力）
        try {
            customerService.createFromSession(tenantId, openid, user.getNickname(), "wechat_mini");
        } catch (Exception e) {
            log.warn("小程序登录自动建档失败（不阻断登录）: userId={}, openid={}", user.getId(), openid, e);
        }

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
        // 审计 07 P1-5：refresh token 仅经 HttpOnly cookie 下发，不进响应体
        setRefreshTokenCookie(response, refreshToken);

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
                        .botName(getBotName(user.getTenantId()))
                        .build())
                .accessToken(accessToken)
                .refreshToken(null)  // 审计 07 P1-5: 不下发，仅 HttpOnly cookie
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

    // ======================== B 端员工小程序登录（bmini，issue #2977） ========================

    /**
     * B 端员工小程序登录（手机号绑定式，非自动建号）。
     *
     * 与 C 端 miniProgramLogin 语义相反：
     * - C 端：openid 无绑定 → 自动创建 customer 用户（拉新）
     * - B 端：openid 无绑定 → 微信授权手机号换号 → <b>跨租户匹配员工账号</b>（role 非
     *   customer/agent，UserMapper.selectActiveEmployeesByPhoneIgnoreTenant 门禁）→ 绑定
     *   user_identities(bmini_app) → 签发员工 JWT（含 roles+permissions，工具级鉴权同源）
     * - 匹配不到员工：明确拒绝，绝不建号、绝不下发 token（BM-003）
     *
     * @param request  {code: wx.login code（必填）, phoneCode: getPhoneNumber 授权 code（首次必填）}
     * @param response HTTP 响应（Set-Cookie）
     * @return 员工登录响应
     */
    @Transactional(rollbackFor = Exception.class)
    public LoginResponse bminiLogin(BminiLoginRequest request, HttpServletResponse response) {
        log.info("B 端员工小程序登录: hasPhoneCode={}", StringUtils.hasText(request.getPhoneCode()));

        // 1. code2Session（bmini 渠道 appid）换 openid
        WechatService.Code2SessionResult sessionResult = wechatService.bminiCode2Session(request.getCode());
        String openid = sessionResult.getOpenid();

        // 2. 查既有 bmini 绑定（identityType + appId 双隔离，杜绝与 C 端 openid 串用）
        UserIdentity identity = userIdentityMapper.selectOne(
                new LambdaQueryWrapper<UserIdentity>()
                        .eq(UserIdentity::getOpenid, openid)
                        .eq(UserIdentity::getIdentityType, "bmini_app")
                        .eq(UserIdentity::getAppId, bminiAppId)
                        .eq(UserIdentity::getDeleted, 0));

        if (identity != null) {
            // 二次登录：已有绑定 → 校验员工 → 直接签发（无需 phoneCode，BM-002）
            User user = userMapper.selectById(identity.getUserId());
            if (user == null || user.getDeleted() != null && user.getDeleted() == 1) {
                throw BusinessException.authFailed("员工账号不存在，请联系管理员");
            }
            validateBminiEmployee(user);
            TenantContext.setTenantId(user.getTenantId());
            log.info("B 端员工已绑定，直接登录: userId={}, tenantId={}", user.getId(), user.getTenantId());
            return buildBminiLoginResponse(user, response);
        }

        // 3. 首次登录：必须授权手机号换号匹配员工
        if (!StringUtils.hasText(request.getPhoneCode())) {
            throw BusinessException.authFailed("首次登录需授权手机号绑定员工账号");
        }
        WechatService.PhoneNumberResult phoneResult = wechatService.bminiGetPhoneNumber(request.getPhoneCode());
        String purePhone = phoneResult != null ? phoneResult.getPurePhoneNumber() : null;
        if (!StringUtils.hasText(purePhone)) {
            throw BusinessException.authFailed("微信未返回有效手机号，请重新授权");
        }

        // 4. 跨租户匹配员工（SQL 已门禁 role NOT IN ('customer','agent')，customer 撞号也拒绝）
        List<User> employees = userMapper.selectActiveEmployeesByPhoneIgnoreTenant(purePhone);
        if (employees.isEmpty()) {
            log.warn("B 端员工登录失败，手机号未匹配员工账号: phone={}****{}", maskPhone(purePhone));
            throw BusinessException.authFailed("手机号未匹配员工账号，请联系管理员开通");
        }
        if (employees.size() > 1) {
            log.warn("B 端员工登录歧义，手机号关联多个员工账号: phone={}****{}", maskPhone(purePhone));
            throw BusinessException.authFailed("手机号关联多个员工账号，请通过管理后台登录");
        }
        User employee = employees.get(0);
        validateBminiEmployee(employee);
        TenantContext.setTenantId(employee.getTenantId());

        // 5. 绑定 openid ↔ 员工（identityType=bmini_app + appId 隔离渠道）
        UserIdentity newIdentity = UserIdentity.builder()
                .tenantId(employee.getTenantId())
                .userId(employee.getId())
                .identityType("bmini_app")
                .appId(bminiAppId)
                .openid(openid)
                .build();
        userIdentityMapper.insert(newIdentity);
        log.info("B 端员工首次登录绑定成功: userId={}, tenantId={}, openid=masked",
                employee.getId(), employee.getTenantId());

        return buildBminiLoginResponse(employee, response);
    }

    /**
     * 校验 bmini 员工账号可登录（active + 非 C 端角色双保险）。
     */
    private void validateBminiEmployee(User user) {
        if (!"active".equals(user.getStatus())) {
            throw BusinessException.authFailed("员工账号状态异常");
        }
        String role = user.getRole();
        if (role == null || "customer".equals(role) || "agent".equals(role)) {
            // SQL 已门禁，这里是纵深防御：customer/agent 永不通过 bmini 入口
            log.warn("B 端员工登录拒绝：角色非员工 userId={}, role={}", user.getId(), role);
            throw BusinessException.authFailed("手机号未匹配员工账号，请联系管理员开通");
        }
    }

    /**
     * 签发 B 端员工 JWT 并构建登录响应（与 smsLogin 同源：roles + permissions + HttpOnly cookie）。
     */
    private LoginResponse buildBminiLoginResponse(User user, HttpServletResponse response) {
        // 角色与权限
        List<String> roles = userService.getUserRoles(user);
        List<String> permissions = roleService.getUserPermissions(user.getId());

        // 签发 JWT（username 放手机号，含权限 → 米宝 ToolContext 工具级鉴权可用）
        String accessToken = jwtTokenProvider.generateAccessToken(
                user.getId(), user.getTenantId(), user.getPhone(), roles, permissions);
        String refreshToken = jwtTokenProvider.generateRefreshToken(user.getId(), user.getTenantId());

        // HttpOnly Cookie（审计 07 P1-5：refresh token 仅经 cookie 下发）
        setTokenCookie(response, accessToken, (int) jwtTokenProvider.getAccessTokenExpiration());
        setRefreshTokenCookie(response, refreshToken);

        String tenantName = getTenantName(user.getTenantId());

        return LoginResponse.builder()
                .user(LoginResponse.UserInfo.builder()
                        .id(user.getId())
                        .nickname(user.getNickname())
                        .avatar(user.getAvatar())
                        .role(user.getRole())
                        .identityType("bmini")
                        .roles(roles)
                        .tenantId(user.getTenantId())
                        .tenantName(tenantName)
                        .botName(getBotName(user.getTenantId()))
                        .build())
                .accessToken(accessToken)
                .refreshToken(null)
                .expiresIn(jwtTokenProvider.getAccessTokenExpiration())
                .build();
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
        // 检查结果 `null` = **不可执行**（Redis 异常）⇒ 显式降级：拒绝，且用与「已吊销」不同的状态码/文案，
        // 让「吊销检查失效中」在客户端与告警面都看得见（fail-closed，issue #4866）。
        Boolean revoked = jti != null ? isTokenBlacklisted(jti) : Boolean.FALSE;
        if (revoked == null) {
            throw new BusinessException("AUTH_UNAVAILABLE",
                    "吊销状态不可判定（Redis 不可用），已按 fail-closed 拒绝本次刷新", 503);
        }
        if (revoked) {
            throw BusinessException.authFailed("Refresh Token 已吊销");
        }

        // 从 Token 中提取用户信息
        String userId = jwtTokenProvider.getUserIdFromToken(refreshToken);
        // refresh 端点是公开的，JWT 过滤器不会设置 TenantContext，
        // 需从 refreshToken claims 中手动提取 tenantId 后注入上下文
        Object tidObj = claims.get(JwtTokenProvider.CLAIM_TENANT_ID);
        if (tidObj != null) {
            Long tid = tidObj instanceof Number ? ((Number) tidObj).longValue()
                    : Long.valueOf(tidObj.toString());
            TenantContext.setTenantId(tid);
        }

        // 先查平台管理员表，再查租户用户表
        PlatformAdmin platformAdmin = platformAdminMapper.selectById(userId);
        if (platformAdmin != null) {
            return refreshPlatformAdminToken(platformAdmin, jti, claims, response);
        }

        // 查询用户
        User user = userService.getUserById(userId);
        if (user == null) {
            throw BusinessException.authFailed("用户不存在");
        }

        if (!"active".equals(user.getStatus())) {
            throw BusinessException.authFailed("用户状态异常");
        }

        // 获取用户角色和权限
        List<String> roles = userService.getUserRoles(user);
        List<String> permissions = roleService.getUserPermissions(user.getId());

        // 签发新的 Token（含细粒度权限）
        String newAccessToken = jwtTokenProvider.generateAccessToken(
                user.getId(),
                user.getTenantId(),
                user.getPhone(),
                roles,
                permissions
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
        // 审计 07 P1-5：refresh token 仅经 HttpOnly cookie 轮换下发
        setRefreshTokenCookie(response, newRefreshToken);

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

        // 平台管理员 — 从 platform_admins 表查询
        if (securityUser.getRoles() != null && securityUser.getRoles().contains("super_admin")) {
            PlatformAdmin platformAdmin = platformAdminMapper.selectById(securityUser.getUserId());
            if (platformAdmin == null) {
                throw BusinessException.authFailed("平台管理员不存在");
            }
            if (!"active".equals(platformAdmin.getStatus())) {
                throw BusinessException.authFailed("账号状态异常");
            }
            List<String> permissions = List.of("*");
            List<UserInfoResponse.MenuItem> menus = buildPlatformAdminMenus();

            return UserInfoResponse.builder()
                    .user(UserInfoResponse.UserInfo.builder()
                            .id(platformAdmin.getId())
                            .username(platformAdmin.getPhone())
                            .nickname(platformAdmin.getNickname())
                            .avatar(platformAdmin.getAvatar())
                            .tenantId(-1L)
                            .tenantName("米高平台管理")
                            .status(platformAdmin.getStatus())
                            .build())
                    .roles(securityUser.getRoles())
                    .permissions(permissions)
                    .menus(menus)
                    .build();
        }

        // 商户管理员 — 从 users 表查询
        User user = userService.getUserById(securityUser.getUserId());
        if (user == null) {
            throw BusinessException.authFailed("用户不存在");
        }

        // 查询用户权限
        List<String> permissions = roleService.getUserPermissions(user.getId());

        // 构建菜单列表（根据权限）
        List<UserInfoResponse.MenuItem> menus = buildMenusByPermissions(permissions);

        // 查询租户名称与 Logo（「企业基础信息」设置，用于前端品牌展示）
        String tenantName = getTenantName(user.getTenantId());
        String tenantLogo = getTenantLogo(user.getTenantId());

        return UserInfoResponse.builder()
                .user(UserInfoResponse.UserInfo.builder()
                        .id(user.getId())
                        .username(user.getPhone())
                        .nickname(user.getNickname())
                        .position(user.getPosition())
                        .avatar(user.getAvatar())
                        .tenantId(user.getTenantId())
                        .tenantName(tenantName)
                        .botName(getBotName(user.getTenantId()))
                        .tenantLogo(tenantLogo)
                        .status(user.getStatus())
                        .build())
                .roles(securityUser.getRoles())
                .permissions(permissions)
                .menus(menus)
                .build();
    }

    // ======================== 平台管理员 Token 刷新 ========================

    /**
     * 平台管理员 Token 刷新
     */
    private LoginResponse refreshPlatformAdminToken(PlatformAdmin platformAdmin, String jti,
                                                     Claims claims, HttpServletResponse response) {
        if (!"active".equals(platformAdmin.getStatus())) {
            throw BusinessException.authFailed("账号状态异常");
        }

        List<String> roles = List.of("super_admin");

        String newAccessToken = jwtTokenProvider.generateAccessToken(
                platformAdmin.getId(), -1L, platformAdmin.getPhone(), roles);
        String newRefreshToken = jwtTokenProvider.generateRefreshToken(
                platformAdmin.getId(), -1L);

        // 吊销旧 Refresh Token
        if (jti != null) {
            long ttl = claims.getExpiration().getTime() - System.currentTimeMillis();
            if (ttl > 0) {
                blacklistToken(jti, ttl);
            }
        }

        setTokenCookie(response, newAccessToken, (int) jwtTokenProvider.getAccessTokenExpiration());
        // 审计 07 P1-5：refresh token 仅经 HttpOnly cookie 轮换下发
        setRefreshTokenCookie(response, newRefreshToken);

        return LoginResponse.builder()
                .user(LoginResponse.UserInfo.builder()
                        .id(platformAdmin.getId())
                        .nickname(platformAdmin.getNickname())
                        .role("super_admin")
                        .identityType("account")
                        .roles(roles)
                        .tenantId(-1L)
                        .tenantName("米高平台管理")
                        .build())
                .accessToken(newAccessToken)
                .refreshToken(newRefreshToken)
                .expiresIn(jwtTokenProvider.getAccessTokenExpiration())
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
        if (tenantId == null || tenantId == -1L) {
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

    /**
     * 查询智能客服名称（TenantAiConfig.botName，C 端思考中/空态/导航名展示）
     *
     * @param tenantId 租户ID
     * @return 智能客服名称，未配置或查询失败返回 null（前端兜底「小布」）
     */
    private String getBotName(Long tenantId) {
        if (tenantId == null || tenantId == -1L) {
            return null;
        }
        try {
            com.migao.admin.entity.TenantAiConfig config = tenantAiConfigMapper.selectOne(
                    new LambdaQueryWrapper<com.migao.admin.entity.TenantAiConfig>()
                            .eq(com.migao.admin.entity.TenantAiConfig::getTenantId, tenantId)
                            .last("LIMIT 1"));
            return config != null ? config.getBotName() : null;
        } catch (Exception e) {
            log.warn("查询智能客服名称失败: tenantId={}, error={}", tenantId, e.getMessage());
            return null;
        }
    }

    /**
     * 查询租户 Logo（「企业基础信息」设置的企业 Logo）
     *
     * @param tenantId 租户ID
     * @return 租户 Logo URL，不存在则返回 null
     */
    private String getTenantLogo(Long tenantId) {
        if (tenantId == null || tenantId == -1L) {
            return null;
        }
        try {
            Tenant tenant = tenantMapper.selectById(tenantId);
            return tenant != null ? tenant.getLogo() : null;
        } catch (Exception e) {
            log.warn("查询租户 Logo 失败: tenantId={}, error={}", tenantId, e.getMessage());
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
     *
     * @return {@code TRUE}=已吊销 / {@code FALSE}=未吊销 / {@code null}=**检查不可执行**（Redis 异常）
     *         —— 调用方必须按已吊销处理（fail-closed，issue #4866）
     */
    private Boolean isTokenBlacklisted(String jti) {
        try {
            return Boolean.TRUE.equals(redisTemplate.hasKey(TOKEN_BLACKLIST_PREFIX + jti));
        } catch (Exception e) {
            // ⛔ 不许改回「异常 ⇒ 未吊销（放行）」：那会让 Redis 不可用期间的已吊销/已登出 token 继续可用
            //（issue #4866）。降级方向登记在 tests/unit_ci_workflows/declared_effective_registry.json 的
            // security_degradation 台账 —— 改方向 / 去掉读数 ⇒ 判据必红。
            log.error("{}（吊销检查不可执行 ⇒ 按已吊销拒绝，fail-closed）: jti={}",
                    BLACKLIST_CHECK_UNAVAILABLE_KEYWORD, jti, e);
            meterRegistry.counter(BLACKLIST_CHECK_UNAVAILABLE_METRIC).increment();
            return null;
        }
    }

    // ======================== Cookie 操作 ========================

    /**
     * 设置 Token Cookie（含 SameSite 属性）
     */
    private void setTokenCookie(HttpServletResponse response, String token, int maxAge) {
        setCookie(response, cookieName, token, maxAge);
    }

    /**
     * 设置 Refresh Token Cookie（HttpOnly+Secure+SameSite，7 天）。
     * refresh token 仅经此通道下发（审计 07 P1-5），不进入响应体。
     */
    private void setRefreshTokenCookie(HttpServletResponse response, String refreshToken) {
        setCookie(response, REFRESH_TOKEN_COOKIE, refreshToken, REFRESH_TOKEN_COOKIE_MAX_AGE);
    }

    /**
     * 通用 Cookie 写入（HttpOnly/Secure/SameSite/Domain 与 access_token 一致）
     */
    private void setCookie(HttpServletResponse response, String name, String value, int maxAge) {
        StringBuilder cookieValue = new StringBuilder();
        cookieValue.append(name).append("=").append(value);
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
        clearCookie(response, cookieName);
        // 审计 07 P1-5：登出时一并清除 refresh token cookie
        clearCookie(response, REFRESH_TOKEN_COOKIE);
    }

    /**
     * 通用 Cookie 清除
     */
    private void clearCookie(HttpServletResponse response, String name) {
        StringBuilder cookieValue = new StringBuilder();
        cookieValue.append(name).append("=");
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
    //
    // 🔴 issue #5217 裁决：**图标是前端专属 —— 服务端不下发图标**。
    // 真实侧边栏 `frontend/admin-web/src/config/menu.ts` 是图标的唯一真值源；本类只下发
    // key / name / path / children。依据（实测，非推断）：前端对「登录下发菜单」的读取点只有
    // 类型声明与 store 透传（`frontend/admin-web/src/types/index.ts` 的 `User.menus` 与
    // `frontend/admin-web/src/store/auth.ts`），**没有任何生产读取点**读 `menus[].icon`；
    // 真实侧边栏 `frontend/admin-web/src/components/layout/Sidebar.tsx` 的图标解析（`iconMap[...]`）
    // 取自 `@/config/menu`。故此前服务端那份 `icon` 是**无人消费、只会与前端漂移**的雷
    // （实证：`production-piecework` 前端 `Calculator` / 服务端 `Coins`）。
    // 守卫：`tests/unit_ci_workflows/test_menu_three_sources_are_isomorphic.py`。

    /**
     * 平台管理员菜单
     */
    private List<UserInfoResponse.MenuItem> buildPlatformAdminMenus() {
        List<UserInfoResponse.MenuItem> menus = new java.util.ArrayList<>();

        // 注：入驻审批页已废弃（2026-08-30 起商家入驻由 AI 自动甄别开通，
        // 不再需要人工审批页面；审批接口仍保留供 API 兜底应急）。
        menus.add(UserInfoResponse.MenuItem.builder()
                .key("platform-dashboard").name("平台概览").path("/platform-dashboard").build());
        menus.add(UserInfoResponse.MenuItem.builder()
                .key("tenants").name("租户管理").path("/tenants").build());
        menus.add(UserInfoResponse.MenuItem.builder()
                .key("platform-settings").name("平台设置").path("/platform-settings").build());

        return menus;
    }

    /**
     * 根据权限构建菜单列表（匹配前端侧边栏结构 — #2969 七大组）
     */
    private List<UserInfoResponse.MenuItem> buildMenusByPermissions(List<String> permissions) {
        boolean isAll = permissions.contains("*");

        List<UserInfoResponse.MenuItem> menus = new java.util.ArrayList<>();

        // 🔴 issue #5271 菜单重设计：本方法**逐组、逐项镜像**前端
        // `frontend/admin-web/src/config/menu.ts` 的 `menuGroups` + `standaloneItems`
        // —— 组 key / 组名 / 组顺序 / 组内 key / name / path / 顺序全一致，权限判定与 `permissionCode` 同码。
        // 本列表是登录后下发的侧边栏菜单面（`UserInfoResponse.menus`），与 `MenuController.MENU_TREE`
        // （岗位权限/员工权限页消费）、前端 `config/menu.ts`（真实侧边栏）**三处同构**；
        // 判据：tests/unit_ci_workflows/test_menu_three_sources_are_isomorphic.py。
        // 🔴 issue #5217 裁决：**图标是前端专属**（服务端不下发 icon）—— `menuItem` 只有 key/name/path。

        // 工作台（#5271：由「独立项」改为**组**，含 经营看板 + 每日简报 两项）
        List<UserInfoResponse.MenuItem> workspaceChildren = new java.util.ArrayList<>();
        // 经营看板：全员可见（无权限码，与 menu.ts 一致）
        workspaceChildren.add(menuItem("dashboard", "经营看板", "/dashboard"));
        // 每日简报（issue #3468）：按 dashboard:view 判定（与 menu.ts 的 permissionCode 同码）。
        // ⚠️ **企业开关有意不在此实现** —— 服务端拿不到该开关；开关由前端按 `menu.ts` 的
        // `briefingToggle` 读取后过滤显隐，服务端只负责权限这一维。
        if (isAll || permissions.contains("dashboard:view")) {
            workspaceChildren.add(menuItem("briefing", "每日简报", "/briefing"));
        }
        if (!workspaceChildren.isEmpty()) {
            menus.add(menuGroup("workspace", "工作台", workspaceChildren));
        }

        // 智能客服分组（在线接待 / 知识库；#3081 AI 客服配置已合并进企业基础信息）。
        // 🔴 #5271 收口：旧实现多一个 `chat`「米宝 · 在线对话」节点（#3094 从侧边栏移除后服务端没跟）——
        // 本次删除，本组与前端 menu.ts 一致为 2 项。
        List<UserInfoResponse.MenuItem> csChildren = new java.util.ArrayList<>();
        if (isAll || permissions.contains("agent:session")) {
            csChildren.add(menuItem("human-sessions", "在线接待", "/agent-workspace/human-sessions"));
        }
        // issue #5246（已合入 main）：知识库节点用**读**码 `knowledge:view`。
        if (isAll || permissions.contains("knowledge:view")) {
            csChildren.add(menuItem("knowledge", "知识库", "/knowledge"));
        }
        if (!csChildren.isEmpty()) {
            menus.add(menuGroup("smart-customer-service", "智能客服", csChildren));
        }

        // 商品与加工项分组（#5271：组名由「商品管理」改判；组 key `product-center` 不变）
        List<UserInfoResponse.MenuItem> productChildren = new java.util.ArrayList<>();
        if (isAll || permissions.contains("product:list")) {
            productChildren.add(menuItem("products", "商品列表", "/products"));
        }
        if (isAll || permissions.contains("processing:manage")) {
            // #4490/#4542：加工项管理与加工费管理**合并为单一入口**（该页两个 tab）；
            // 路径 = `/production/processing`（旧 `/processing`、`/production/processing-fees`
            // 由前端重定向兜底）—— 逐字镜像 menu.ts（本处此前是 `/processing`，属三源路径漂移，本次收口）。
            productChildren.add(menuItem("processing", "加工项管理", "/production/processing"));
        }
        if (!productChildren.isEmpty()) {
            menus.add(menuGroup("product-center", "商品与加工项", productChildren));
        }

        // 交易管理分组（#5271：原「订单管理」+ 原「客户管理」组的客户列表 / 财务对账 → 一条动线：
        // 谁下单 → 单到哪 → 售后 → 收款对账）。组 key `trade-center` 不变；
        // 「客户管理」组（`customer-center`）**不再存在**。
        List<UserInfoResponse.MenuItem> tradeChildren = new java.util.ArrayList<>();
        if (isAll || permissions.contains("order:list")) {
            tradeChildren.add(menuItem("orders", "订单列表", "/orders"));
        }
        // issue #5246（已合入 main）：售后工单节点用**读**码 `after_sales:view`（原写码 `order:refund`）。
        if (isAll || permissions.contains("after_sales:view")) {
            tradeChildren.add(menuItem("after-sales", "售后工单", "/after-sales"));
        }
        if (isAll || permissions.contains("customer:view")) {
            tradeChildren.add(menuItem("customers", "客户列表", "/customers"));
        }
        if (isAll || permissions.contains("finance:view")) {
            tradeChildren.add(menuItem("finance", "财务对账", "/finance"));
        }
        if (!tradeChildren.isEmpty()) {
            menus.add(menuGroup("trade-center", "交易管理", tradeChildren));
        }

        // 生产管理分组（issue #4203/#4205 后端半边）：#5271 起**由 7 项降到 4 项** ——
        // 面料进出与消耗（入库单 / 余料台账 / 省料看板）拆到「仓储与物料」组；
        // 本组只留「加工执行 + 工艺配置 + 结算」，四项权限码统一 processing:manage。
        // 四个节点**必须与 MenuController 的静态权限树、前端 config/menu.ts 三处同构**；漏一处
        // 就是「岗位权限页勾得动、侧边栏看不到」（#4203 点名的同族坑）。
        List<UserInfoResponse.MenuItem> productionChildren = new java.util.ArrayList<>();
        if (isAll || permissions.contains("processing:manage")) {
            // /production = 加工单唯一入口（issue #4357 与原「加工单」菜单合并）
            productionChildren.add(menuItem("production-board", "生产看板", "/production"));
            // 池看板（issue #5177）：池化派单的决策屏，与「生产看板」同权（processing:manage）
            productionChildren.add(menuItem("production-pool", "池看板", "/production/pool"));
            // 🔴 issue #4440/#4416：「工序库」+「工艺路线」已合并为单入口「工艺配置」
            // （旧路径 /production/operations 是重定向）—— 服务端此前仍是合并前的两个节点。
            productionChildren.add(menuItem("production-process", "工艺配置", "/production/routings"));
            productionChildren.add(menuItem("production-piecework", "计件工资", "/production/piecework"));
        }
        if (!productionChildren.isEmpty()) {
            menus.add(menuGroup("production-center", "生产管理", productionChildren));
        }

        // 仓储与物料分组（#5271 **新组**）：面料进出与消耗 —— 入库 → 批次 → 余料 → 省料，
        // 与「生产管理」组拆开（一个仓管找「入库单」时不该在「生产看板」旁边找）。
        // 🔴 入库单（V111，issue #5034）权限码**独立**（inbound:view）且必须落在**自己的 if** 里：
        // 入库是仓储动作、不是加工动作 —— 塞进下面 processing:manage 的判定会让
        // 「有 inbound:view、没有 processing:manage」的仓管看不到菜单（#4203 同族坑）。
        List<UserInfoResponse.MenuItem> inventoryChildren = new java.util.ArrayList<>();
        if (isAll || permissions.contains("inbound:view")) {
            inventoryChildren.add(menuItem("inbound-orders", "入库单", "/inbound-orders"));
        }
        // 余料台账（issue #5191）/ 省料看板（issue #5159）：权限码沿用 processing:manage ——
        // 与各自页面的类级 @RequirePermission 同码（门禁不放宽也不收紧）。
        if (isAll || permissions.contains("processing:manage")) {
            inventoryChildren.add(menuItem("production-remnants", "余料台账", "/production/remnants"));
            inventoryChildren.add(menuItem("production-saving-board", "省料看板", "/production/saving-board"));
        }
        if (!inventoryChildren.isEmpty()) {
            menus.add(menuGroup("inventory-center", "仓储与物料", inventoryChildren));
        }

        // 组织管理分组（员工管理 / 岗位权限 / 企业基础信息）
        List<UserInfoResponse.MenuItem> orgChildren = new java.util.ArrayList<>();
        if (isAll || permissions.contains("employee:list")) {
            orgChildren.add(menuItem("employees", "员工管理", "/employees"));
        }
        if (isAll || permissions.contains("system:manage")) {
            orgChildren.add(menuItem("roles", "岗位权限", "/roles"));
        }
        if (isAll || permissions.contains("system:manage")) {
            orgChildren.add(menuItem("settings", "企业基础信息", "/settings"));
        }
        if (!orgChildren.isEmpty()) {
            menus.add(menuGroup("org-center", "组织管理", orgChildren));
        }

        // 通知中心：全员可见（与顶栏铃铛一致，无权限码限制）
        menus.add(menuItem("notifications", "通知中心", "/notifications"));

        return menus;
    }

    private UserInfoResponse.MenuItem menuItem(String key, String name, String path) {
        return UserInfoResponse.MenuItem.builder()
                .key(key).name(name).path(path).build();
    }

    private UserInfoResponse.MenuItem menuGroup(String key, String name,
                                                 List<UserInfoResponse.MenuItem> children) {
        return UserInfoResponse.MenuItem.builder()
                .key(key).name(name).children(children).build();
    }

    /**
     * 手机号脱敏（日志用）：138****8000
     */
    private String maskPhone(String phone) {
        if (phone == null || phone.length() < 7) {
            return phone;
        }
        return phone.substring(0, 3) + "****" + phone.substring(phone.length() - 4);
    }
}
