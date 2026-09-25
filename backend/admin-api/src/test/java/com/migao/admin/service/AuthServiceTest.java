// case_ids: API-010, CU-006, PG-021
package com.migao.admin.service;

import com.migao.admin.dto.LoginRequest;
import com.migao.admin.dto.LoginResponse;
import com.migao.admin.entity.Tenant;
import com.migao.admin.entity.User;
import com.migao.admin.mapper.PlatformAdminMapper;
import com.migao.admin.mapper.TenantMapper;
import com.migao.admin.mapper.UserIdentityMapper;
import com.migao.admin.mapper.UserMapper;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.security.JwtTokenProvider;
import com.migao.admin.security.LoginFailureGuard;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import jakarta.servlet.http.HttpServletResponse;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.Spy;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.List;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

/**
 * AuthService 单元测试
 */
@ExtendWith(MockitoExtension.class)
class AuthServiceTest {

    @InjectMocks
    private AuthService authService;

    @Mock
    private UserService userService;

    @Mock
    private RoleService roleService;

    @Mock
    private WechatService wechatService;

    @Mock
    private SmsService smsService;

    @Mock
    private JwtTokenProvider jwtTokenProvider;

    @Mock
    private PasswordEncoder passwordEncoder;

    @Mock
    private StringRedisTemplate redisTemplate;

    /** 真注册表（不是 mock）：断言「吊销检查不可执行」确实留下了可观测读数（issue #4866）。 */
    @Spy
    private SimpleMeterRegistry meterRegistry = new SimpleMeterRegistry();

    @Mock
    private ValueOperations<String, String> valueOperations;

    @Mock
    private PlatformAdminMapper platformAdminMapper;

    @Mock
    private UserMapper userMapper;

    @Mock
    private TenantMapper tenantMapper;

    @Mock
    private UserIdentityMapper userIdentityMapper;

    @Mock
    private CustomerService customerService;

    /** 登录失败计数（issue #5531）：本类不测它 ⇒ 用 mock（默认未锁定 ⇒ 既有行为不变）。 */
    @Mock
    private LoginFailureGuard loginFailureGuard;

    private User testUser;
    private LoginRequest loginRequest;

    @BeforeEach
    void setUp() {
        // 设置 @Value 字段
        ReflectionTestUtils.setField(authService, "cookieName", "access_token");
        ReflectionTestUtils.setField(authService, "cookieDomain", "");
        ReflectionTestUtils.setField(authService, "cookiePath", "/");
        ReflectionTestUtils.setField(authService, "cookieSecure", true);
        ReflectionTestUtils.setField(authService, "cookieHttpOnly", true);
        ReflectionTestUtils.setField(authService, "cookieSameSite", "strict");

        // 构造测试用户
        testUser = User.builder()
                .id("user-001")
                .tenantId(1L)
                .phone("13800138000")
                .passwordHash("$2a$10$hashedPassword")
                .nickname("测试管理员")
                .avatar("https://example.com/avatar.png")
                .role("admin")
                .status("active")
                .build();

        // 构造登录请求
        loginRequest = new LoginRequest();
        loginRequest.setUsername("13800138000");
        loginRequest.setPassword("password123");
        loginRequest.setTenantId(1L);
    }

    // ======================== 登录测试 ========================

    @Test
    @DisplayName("密码登录已禁用 - 抛出认证异常 (#375)")
    void adminLogin_Disabled() {
        HttpServletResponse response = mock(HttpServletResponse.class);
        assertThatThrownBy(() -> authService.adminLogin(loginRequest, response))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("密码登录已禁用");
    }

    // ======================== Token 刷新测试 ========================

    @Test
    @DisplayName("Token 刷新成功")
    void refreshToken_Success() {
        // Given: 有效的 Refresh Token
        String refreshToken = "valid-refresh-token";
        when(jwtTokenProvider.validateToken(refreshToken)).thenReturn(true);
        when(jwtTokenProvider.isRefreshToken(refreshToken)).thenReturn(true);

        // Mock Claims
        io.jsonwebtoken.Claims mockClaims = mock(io.jsonwebtoken.Claims.class);
        when(mockClaims.getId()).thenReturn("jti-001");
        when(mockClaims.getExpiration()).thenReturn(new java.util.Date(System.currentTimeMillis() + 600000));
        when(jwtTokenProvider.getClaimsFromToken(refreshToken)).thenReturn(mockClaims);

        // Redis 黑名单检查：未吊销
        when(redisTemplate.hasKey("token:blacklist:jti-001")).thenReturn(false);

        when(jwtTokenProvider.getUserIdFromToken(refreshToken)).thenReturn("user-001");
        when(userService.getUserById("user-001")).thenReturn(testUser);
        when(userService.getUserRoles(testUser)).thenReturn(List.of("admin"));
        when(roleService.getUserPermissions("user-001")).thenReturn(List.of("*"));

        // issue #5485：刷新路径必须按数据库当前 must_change_password 重算标记 ⇒ 6 参重载
        when(jwtTokenProvider.generateAccessToken(eq("user-001"), eq(1L), eq("13800138000"),
                anyList(), anyList(), eq(false)))
                .thenReturn("new-access-token");
        when(jwtTokenProvider.generateRefreshToken("user-001", 1L))
                .thenReturn("new-refresh-token");
        when(jwtTokenProvider.getAccessTokenExpiration()).thenReturn(7200L);

        // 旧 Token 黑名单写入
        when(redisTemplate.opsForValue()).thenReturn(valueOperations);

        HttpServletResponse response = mock(HttpServletResponse.class);

        // When: 刷新 Token
        LoginResponse result = authService.refreshToken(refreshToken, response);

        // Then: 验证新 Token
        assertThat(result).isNotNull();
        assertThat(result.getAccessToken()).isEqualTo("new-access-token");
        assertThat(result.getRefreshToken()).isEqualTo("new-refresh-token");
        assertThat(result.getUser().getId()).isEqualTo("user-001");
    }

    @Test
    @DisplayName("Token 刷新失败 - 无效的 Refresh Token")
    void refreshToken_InvalidToken() {
        // Given: 无效的 Refresh Token
        String refreshToken = "invalid-refresh-token";
        when(jwtTokenProvider.validateToken(refreshToken)).thenReturn(false);

        HttpServletResponse response = mock(HttpServletResponse.class);

        // When & Then: 应抛出异常
        assertThatThrownBy(() -> authService.refreshToken(refreshToken, response))
                .isInstanceOf(BusinessException.class)
                .hasMessage("无效的 Refresh Token");
    }

    @Test
    @DisplayName("Token 刷新失败 - Token 类型不是 Refresh")
    void refreshToken_NotRefreshToken() {
        // Given: Token 有效但不是 Refresh Token
        String accessToken = "access-token";
        when(jwtTokenProvider.validateToken(accessToken)).thenReturn(true);
        when(jwtTokenProvider.isRefreshToken(accessToken)).thenReturn(false);

        HttpServletResponse response = mock(HttpServletResponse.class);

        // When & Then: 应抛出异常
        assertThatThrownBy(() -> authService.refreshToken(accessToken, response))
                .isInstanceOf(BusinessException.class)
                .hasMessage("无效的 Refresh Token");
    }

    @Test
    @DisplayName("Token 刷新失败 - Token 已被吊销")
    void refreshToken_BlacklistedToken() {
        // Given: Token 已在黑名单中
        String refreshToken = "blacklisted-refresh-token";
        when(jwtTokenProvider.validateToken(refreshToken)).thenReturn(true);
        when(jwtTokenProvider.isRefreshToken(refreshToken)).thenReturn(true);

        io.jsonwebtoken.Claims mockClaims = mock(io.jsonwebtoken.Claims.class);
        when(mockClaims.getId()).thenReturn("jti-002");
        when(jwtTokenProvider.getClaimsFromToken(refreshToken)).thenReturn(mockClaims);

        // Redis 返回已存在
        when(redisTemplate.hasKey("token:blacklist:jti-002")).thenReturn(true);

        HttpServletResponse response = mock(HttpServletResponse.class);

        // When & Then: 应抛出已吊销异常
        assertThatThrownBy(() -> authService.refreshToken(refreshToken, response))
                .isInstanceOf(BusinessException.class)
                .hasMessage("Refresh Token 已吊销");
    }

    @Test
    @DisplayName("Token 刷新失败 - Redis 不可用 ⇒ fail-closed 拒绝（503 + 可观测读数）(#4866)")
    void refreshToken_RevocationCheckUnavailable_FailsClosed() {
        // Given: 吊销检查（Redis hasKey）抛异常 ⇒ 吊销状态**不可判定**
        String refreshToken = "valid-refresh-token";
        when(jwtTokenProvider.validateToken(refreshToken)).thenReturn(true);
        when(jwtTokenProvider.isRefreshToken(refreshToken)).thenReturn(true);

        io.jsonwebtoken.Claims mockClaims = mock(io.jsonwebtoken.Claims.class);
        when(mockClaims.getId()).thenReturn("jti-redis-down");
        when(jwtTokenProvider.getClaimsFromToken(refreshToken)).thenReturn(mockClaims);
        when(redisTemplate.hasKey("token:blacklist:jti-redis-down"))
                .thenThrow(new RuntimeException("Redis down"));

        HttpServletResponse response = mock(HttpServletResponse.class);

        // When & Then: 必须拒绝（改回「异常 ⇒ 放行」时本判据必红），且状态码/文案与实际「已吊销」不同
        assertThatThrownBy(() -> authService.refreshToken(refreshToken, response))
                .isInstanceOf(BusinessException.class)
                .hasFieldOrPropertyWithValue("code", "AUTH_UNAVAILABLE")
                .hasFieldOrPropertyWithValue("httpStatus", 503);
        // 且必须留下可观测读数（不许静默）
        assertThat(meterRegistry.counter(AuthService.BLACKLIST_CHECK_UNAVAILABLE_METRIC).count()).isEqualTo(1.0);
    }

    @Test
    @DisplayName("Token 刷新失败 - 用户不存在")
    void refreshToken_UserNotFound() {
        // Given: Token 有效但用户已被删除
        String refreshToken = "valid-refresh-token";
        when(jwtTokenProvider.validateToken(refreshToken)).thenReturn(true);
        when(jwtTokenProvider.isRefreshToken(refreshToken)).thenReturn(true);

        io.jsonwebtoken.Claims mockClaims = mock(io.jsonwebtoken.Claims.class);
        when(mockClaims.getId()).thenReturn(null); // 无 jti
        when(jwtTokenProvider.getClaimsFromToken(refreshToken)).thenReturn(mockClaims);

        when(jwtTokenProvider.getUserIdFromToken(refreshToken)).thenReturn("user-deleted");
        when(userService.getUserById("user-deleted")).thenReturn(null);

        HttpServletResponse response = mock(HttpServletResponse.class);

        // When & Then: 应抛出用户不存在异常
        assertThatThrownBy(() -> authService.refreshToken(refreshToken, response))
                .isInstanceOf(BusinessException.class)
                .hasMessage("用户不存在");
    }

    // ======================== 登出测试 ========================

    @Test
    @DisplayName("登出 - 成功，Token 加入黑名单并清除 Cookie")
    void logout_Success() {
        // Given: 请求包含有效的 Cookie Token
        jakarta.servlet.http.HttpServletRequest request = mock(jakarta.servlet.http.HttpServletRequest.class);
        HttpServletResponse response = mock(HttpServletResponse.class);

        jakarta.servlet.http.Cookie tokenCookie = new jakarta.servlet.http.Cookie("access_token", "valid-token");
        when(request.getCookies()).thenReturn(new jakarta.servlet.http.Cookie[]{tokenCookie});

        io.jsonwebtoken.Claims mockClaims = mock(io.jsonwebtoken.Claims.class);
        when(mockClaims.getId()).thenReturn("jti-logout");
        when(mockClaims.getExpiration()).thenReturn(new java.util.Date(System.currentTimeMillis() + 600000));
        when(jwtTokenProvider.getClaimsFromToken("valid-token")).thenReturn(mockClaims);

        when(redisTemplate.opsForValue()).thenReturn(valueOperations);

        // When: 登出
        authService.logout(request, response);

        // Then: Token 被加入黑名单
        verify(valueOperations).set(eq("token:blacklist:jti-logout"), eq("1"), any(java.time.Duration.class));
    }

    @Test
    @DisplayName("登出 - 无 Token 时仅清除 Cookie")
    void logout_NoToken() {
        // Given: 请求无 Cookie 无 Authorization header
        jakarta.servlet.http.HttpServletRequest request = mock(jakarta.servlet.http.HttpServletRequest.class);
        HttpServletResponse response = mock(HttpServletResponse.class);

        when(request.getCookies()).thenReturn(null);
        when(request.getHeader("Authorization")).thenReturn(null);

        // When: 登出（不应抛异常）
        authService.logout(request, response);

        // Then: 未尝试操作 Redis
        verify(redisTemplate, never()).opsForValue();
    }

    // ======================== 微信公众号 OAuth 占位实现测试 ========================

    @Test
    @DisplayName("微信 H5 授权 URL 构建 - 抛出未实现异常")
    void buildWechatH5AuthorizeUrl_NotImplemented() {
        assertThatThrownBy(() -> authService.buildWechatH5AuthorizeUrl("tenant123", "https://example.com/callback"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("尚未实现");
    }

    @Test
    @DisplayName("微信 H5 OAuth 回调 - 抛出未实现异常")
    void handleWechatH5Callback_NotImplemented() {
        HttpServletResponse response = mock(HttpServletResponse.class);
        assertThatThrownBy(() -> authService.handleWechatH5Callback("auth-code", "state-123", response))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("尚未实现");
    }

    // ======================== 短信登录 - 同手机号跨租户歧义（审计 07 P1-2） ========================

    @Test
    @DisplayName("短信登录 - 同手机号多租户且未指定租户 → 拒绝（防登录落错租户）")
    void loginBySms_MultiTenantAmbiguity_Rejected() {
        User u1 = User.builder().id("u1").tenantId(1L).phone("13800138000").role("admin").status("active").build();
        User u2 = User.builder().id("u2").tenantId(2L).phone("13800138000").role("admin").status("active").build();

        when(smsService.verifyCode("13800138000", "123456")).thenReturn(true);
        when(platformAdminMapper.selectOne(any())).thenReturn(null);
        when(userMapper.selectActiveUsersByPhoneIgnoreTenant("13800138000")).thenReturn(List.of(u1, u2));

        assertThatThrownBy(() -> authService.loginBySms(
                "13800138000", "123456", null, mock(HttpServletResponse.class)))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("多个租户");
    }

    @Test
    @DisplayName("短信登录 - 多租户时按指定 tenantId 精确匹配")
    void loginBySms_MultiTenant_WithTenantId_SelectsCorrectTenant() {
        User u1 = User.builder().id("u1").tenantId(1L).phone("13800138000").role("admin").status("active").build();
        User u2 = User.builder().id("u2").tenantId(2L).phone("13800138000").role("admin").status("active").build();

        when(smsService.verifyCode("13800138000", "123456")).thenReturn(true);
        when(platformAdminMapper.selectOne(any())).thenReturn(null);
        when(userMapper.selectActiveUsersByPhoneIgnoreTenant("13800138000")).thenReturn(List.of(u1, u2));
        when(jwtTokenProvider.generateAccessToken(anyString(), anyLong(), anyString(), anyList(), anyList(), anyBoolean()))
                .thenReturn("jwt-token-2");
        when(jwtTokenProvider.generateRefreshToken(anyString(), anyLong())).thenReturn("refresh-token-2");
        when(jwtTokenProvider.getAccessTokenExpiration()).thenReturn(7200L);
        when(userService.getUserRoles(any())).thenReturn(List.of("admin"));
        when(roleService.getUserPermissions(anyString())).thenReturn(List.of("*"));
        when(tenantMapper.selectById(2L)).thenReturn(null); // 租户名查询可空

        LoginResponse resp = authService.loginBySms(
                "13800138000", "123456", 2L, mock(HttpServletResponse.class));

        assertThat(resp.getUser().getId()).isEqualTo("u2");
        verify(userService).getUserRoles(u2);
        // 审计 07 P1-5：登录响应不下发 refresh token（仅 HttpOnly cookie 承载）
        assertThat(resp.getRefreshToken()).isNull();
    }

    @Test
    @DisplayName("短信登录 - 多租户指定不存在的租户 → 拒绝")
    void loginBySms_MultiTenant_WrongTenantId_Rejected() {
        User u1 = User.builder().id("u1").tenantId(1L).phone("13800138000").role("admin").status("active").build();
        User u2 = User.builder().id("u2").tenantId(2L).phone("13800138000").role("admin").status("active").build();

        when(smsService.verifyCode("13800138000", "123456")).thenReturn(true);
        when(platformAdminMapper.selectOne(any())).thenReturn(null);
        when(userMapper.selectActiveUsersByPhoneIgnoreTenant("13800138000")).thenReturn(List.of(u1, u2));

        assertThatThrownBy(() -> authService.loginBySms(
                "13800138000", "123456", 9L, mock(HttpServletResponse.class)))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("未注册");
    }

    // ======================== 小程序登录（C 端，issue #3011） ========================

    @Test
    @DisplayName("小程序登录 - 新 openid 自动建号并落 CRM 客户档案")
    void miniProgramLogin_NewUser_CreatesCustomerProfile() {
        // given：租户存在且 active
        Tenant tenant = new Tenant();
        tenant.setId(1L);
        tenant.setStatus("active");
        when(tenantMapper.selectById(1L)).thenReturn(tenant);

        // 微信 code2Session 返回 openid
        WechatService.Code2SessionResult sessionResult = new WechatService.Code2SessionResult();
        sessionResult.setOpenid("openid_c_end_001");
        when(wechatService.code2Session("wx-code")).thenReturn(sessionResult);

        // 无既有身份 → 自动建号
        when(userIdentityMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(null);
        when(userMapper.insert(any(User.class))).thenAnswer(inv -> {
            inv.getArgument(0, User.class).setId("user-mini-c-001");
            return 1;
        });
        when(userService.getUserRoles(any())).thenReturn(List.of("customer"));
        when(jwtTokenProvider.generateAccessToken(anyString(), anyLong(), anyString(), anyList()))
                .thenReturn("mini-jwt");
        when(jwtTokenProvider.generateRefreshToken(anyString(), anyLong())).thenReturn("mini-rt");
        when(jwtTokenProvider.getAccessTokenExpiration()).thenReturn(7200L);

        // when
        LoginResponse resp = authService.miniProgramLogin(
                "wx-code", 1L, mock(HttpServletResponse.class));

        // then：登录成功 + 自动创建 CRM 客户档案（幂等 upsert，渠道 wechat_mini）
        assertThat(resp).isNotNull();
        assertThat(resp.getUser().getId()).isEqualTo("user-mini-c-001");
        verify(customerService).createFromSession(eq(1L), eq("openid_c_end_001"), any(), eq("wechat_mini"));
    }

    @Test
    @DisplayName("小程序登录 - 已有 openid 登录同样刷新客户档案（createFromSession 幂等）")
    void miniProgramLogin_ExistingUser_RefreshesCustomerProfile() {
        // given：租户存在
        Tenant tenant = new Tenant();
        tenant.setId(1L);
        tenant.setStatus("active");
        when(tenantMapper.selectById(1L)).thenReturn(tenant);

        WechatService.Code2SessionResult sessionResult = new WechatService.Code2SessionResult();
        sessionResult.setOpenid("openid_existing");
        when(wechatService.code2Session("wx-code")).thenReturn(sessionResult);

        // 已存在身份 → 返回既有用户
        User existing = User.builder()
                .id("user-existing")
                .tenantId(1L)
                .nickname("微信用户")
                .role("customer")
                .status("active")
                .build();
        when(userIdentityMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(
                com.migao.admin.entity.UserIdentity.builder()
                        .userId("user-existing")
                        .tenantId(1L)
                        .openid("openid_existing")
                        .identityType("mini_program")
                        .build());
        when(userMapper.selectById("user-existing")).thenReturn(existing);
        when(userMapper.updateById(any(User.class))).thenReturn(1);
        when(userService.getUserRoles(any())).thenReturn(List.of("customer"));
        when(jwtTokenProvider.generateAccessToken(anyString(), anyLong(), anyString(), anyList()))
                .thenReturn("mini-jwt");
        when(jwtTokenProvider.generateRefreshToken(anyString(), anyLong())).thenReturn("mini-rt");
        when(jwtTokenProvider.getAccessTokenExpiration()).thenReturn(7200L);

        // when
        authService.miniProgramLogin("wx-code", 1L, mock(HttpServletResponse.class));

        // then：既有用户同样触发建档（刷新 last_active_at 语义）
        verify(customerService).createFromSession(eq(1L), eq("openid_existing"), any(), eq("wechat_mini"));
    }

    // ======================== 菜单 IA（issue #5271 七大组重排） ========================

    /**
     * 商户管理员菜单的**真值源**是前端 `frontend/admin-web/src/config/menu.ts` ——
     * 侧边栏由 {@code AuthService.buildMenusByPermissions} 生成，而「员工/岗位权限」页读的是
     * {@code MenuController} 的静态树；两边不同构就会出现「勾了权限却看不到菜单」/「菜单点不进」
     * （issue #4203 交付面表格）。本批用例把 menu.ts 的新 IA **逐组逐项抄成 Java 侧精确期望**。
     */

    /** 以指定权限集取回「商户管理员」的菜单面（即 buildMenusByPermissions 的输出）。 */
    private List<com.migao.admin.dto.UserInfoResponse.MenuItem> menusForPermissions(String... permissions) {
        authenticateAs("user-001", 1L);
        when(userService.getUserById("user-001")).thenReturn(testUser);
        when(roleService.getUserPermissions("user-001")).thenReturn(List.of(permissions));
        com.migao.admin.dto.UserInfoResponse info = authService.getCurrentUser();
        clearAuthentication();
        return info.getMenus();
    }

    private static com.migao.admin.dto.UserInfoResponse.MenuItem groupByKey(
            List<com.migao.admin.dto.UserInfoResponse.MenuItem> menus, String key) {
        return menus.stream()
                .filter(m -> key.equals(m.getKey()))
                .findFirst()
                .orElseThrow(() -> new AssertionError("菜单缺少组 key = " + key + "（实得 keys = "
                        + menus.stream()
                        .map(com.migao.admin.dto.UserInfoResponse.MenuItem::getKey).toList() + "）"));
    }

    private static List<String> keysOf(List<com.migao.admin.dto.UserInfoResponse.MenuItem> items) {
        return items.stream().map(com.migao.admin.dto.UserInfoResponse.MenuItem::getKey).toList();
    }

    private static List<String> namesOf(List<com.migao.admin.dto.UserInfoResponse.MenuItem> items) {
        return items.stream().map(com.migao.admin.dto.UserInfoResponse.MenuItem::getName).toList();
    }

    private static List<String> pathsOf(List<com.migao.admin.dto.UserInfoResponse.MenuItem> items) {
        return items.stream().map(com.migao.admin.dto.UserInfoResponse.MenuItem::getPath).toList();
    }

    /** 组名 + 全部子项名的扁平表 —— 负控必须看扁平表（只看顶层名会漏掉「组还在、项没了」）。 */
    private static List<String> allNames(List<com.migao.admin.dto.UserInfoResponse.MenuItem> menus) {
        List<String> out = new java.util.ArrayList<>();
        for (com.migao.admin.dto.UserInfoResponse.MenuItem m : menus) {
            out.add(m.getName());
            if (m.getChildren() != null) {
                m.getChildren().forEach(c -> out.add(c.getName()));
            }
        }
        return out;
    }

    @Test
    @DisplayName("全权账号：七个组 + 通知中心**逐组逐项**镜像 menu.ts（组 key/名/顺序/组内 key/名/路径/顺序）")
    void currentUserMenusMirrorFrontendIaForAllPermissions() {
        List<com.migao.admin.dto.UserInfoResponse.MenuItem> menus = menusForPermissions("*");

        assertThat(keysOf(menus)).containsExactly(
                "workspace", "smart-customer-service", "product-center", "trade-center",
                "production-center", "inventory-center", "org-center", "notifications");
        assertThat(namesOf(menus)).containsExactly(
                "工作台", "智能客服", "商品与加工项", "交易管理",
                "生产管理", "仓储与物料", "组织管理", "通知中心");

        // 工作台（#5271 由「独立项」改为组）
        var workspace = groupByKey(menus, "workspace");
        assertThat(namesOf(workspace.getChildren())).containsExactly("经营看板", "每日简报");
        assertThat(pathsOf(workspace.getChildren())).containsExactly("/dashboard", "/briefing");

        var cs = groupByKey(menus, "smart-customer-service");
        assertThat(keysOf(cs.getChildren())).containsExactly("human-sessions", "knowledge");
        assertThat(pathsOf(cs.getChildren()))
                .containsExactly("/agent-workspace/human-sessions", "/knowledge");

        var product = groupByKey(menus, "product-center");
        assertThat(keysOf(product.getChildren())).containsExactly("products", "processing");
        assertThat(namesOf(product.getChildren())).containsExactly("商品列表", "加工项管理");
        // #4490/#4542：加工项管理与加工费管理合并为单入口，路径 /production/processing
        assertThat(pathsOf(product.getChildren())).containsExactly("/products", "/production/processing");

        var trade = groupByKey(menus, "trade-center");
        assertThat(keysOf(trade.getChildren()))
                .containsExactly("orders", "after-sales", "customers", "finance");
        assertThat(pathsOf(trade.getChildren()))
                .containsExactly("/orders", "/after-sales", "/customers", "/finance");

        var production = groupByKey(menus, "production-center");
        assertThat(keysOf(production.getChildren())).containsExactly(
                "production-board", "production-pool", "production-process", "production-piecework");
        assertThat(pathsOf(production.getChildren())).containsExactly(
                "/production", "/production/pool", "/production/routings", "/production/piecework");

        var inventory = groupByKey(menus, "inventory-center");
        assertThat(keysOf(inventory.getChildren())).containsExactly(
                "inbound-orders", "production-remnants", "production-saving-board");
        assertThat(pathsOf(inventory.getChildren())).containsExactly(
                "/inbound-orders", "/production/remnants", "/production/saving-board");

        var org = groupByKey(menus, "org-center");
        assertThat(keysOf(org.getChildren())).containsExactly("employees", "roles", "settings");
        assertThat(pathsOf(org.getChildren())).containsExactly("/employees", "/roles", "/settings");

        // #3094/#5271：旧 `chat`「米宝 · 在线对话」节点已删除；「会话监控」从来不在侧边栏里
        assertThat(allNames(menus)).doesNotContain("米宝 · 在线对话", "会话监控");
        // #5271：旧「客户管理」组不再存在（其两项已并入交易管理组）
        assertThat(keysOf(menus)).doesNotContain("customer-center");
        assertThat(allNames(menus)).doesNotContain("客户管理");
    }

    @Test
    @DisplayName("生产管理组：生产看板/工艺配置/计件工资 = 读码 production:view；智能派单 = processing:manage（#5291）")
    void currentUserMenusExposeProductionGroup() {
        // issue #5291：生产域新增**读**码 `production:view` —— 「看得见这一页」与「改得动生产数据」
        // 就此分开；**智能派单**仍按 `processing:manage`（同组不同权，其读端点用 processing:view、
        // 且无 Agent 工具调用 ⇒ 不在本单射程）。
        List<com.migao.admin.dto.UserInfoResponse.MenuItem> readOnly = menusForPermissions("production:view");

        var production = groupByKey(readOnly, "production-center");
        assertThat(production.getName()).isEqualTo("生产管理");
        assertThat(namesOf(production.getChildren()))
                .containsExactly("生产看板", "工艺配置", "计件工资");
        assertThat(pathsOf(production.getChildren())).containsExactly(
                "/production", "/production/routings", "/production/piecework");
        // 同组不同权：智能派单**不**随读码一起出现（拆码没有变成「一组一起放行」）
        assertThat(allNames(readOnly)).doesNotContain("智能派单");
        // 加工项管理（product-center 组）同批改用读码 ⇒ 也随 production:view 可见
        assertThat(allNames(readOnly)).contains("加工项管理");

        // 反向（原管理码持有者仍看得见它本来那几页）：只持 processing:manage ⇒ 生产组只剩智能派单，
        // 「仓储与物料」组只剩余料台账/省料看板；入库单（inbound:view）**不出现** —— 证明入库单
        // 确实挂在**独立的**权限判定上，而不是被并进了 processing:manage。
        List<com.migao.admin.dto.UserInfoResponse.MenuItem> manageOnly = menusForPermissions("processing:manage");
        var productionManageOnly = groupByKey(manageOnly, "production-center");
        assertThat(namesOf(productionManageOnly.getChildren())).containsExactly("智能派单");
        var inventory = groupByKey(manageOnly, "inventory-center");
        assertThat(namesOf(inventory.getChildren())).containsExactly("余料台账", "省料看板");
        assertThat(allNames(manageOnly)).doesNotContain("入库单");
    }

    @Test
    @DisplayName("工作台组：经营看板（全员）+ 每日简报（dashboard:view）")
    void currentUserMenusGateBriefingByDashboardView() {
        List<com.migao.admin.dto.UserInfoResponse.MenuItem> menus = menusForPermissions("dashboard:view");

        var workspace = groupByKey(menus, "workspace");
        assertThat(workspace.getName()).isEqualTo("工作台");
        assertThat(namesOf(workspace.getChildren())).containsExactly("经营看板", "每日简报");
        assertThat(pathsOf(workspace.getChildren())).containsExactly("/dashboard", "/briefing");
        // 除工作台外只有独立项「通知中心」（dashboard:view 不点亮任何其它组）
        assertThat(keysOf(menus)).containsExactly("workspace", "notifications");
    }

    @Test
    @DisplayName("负控：无 dashboard:view ⇒ 每日简报不出现（经营看板仍在）；无权限的组整组不出现")
    void currentUserMenusHideGroupsWithoutPermission() {
        List<com.migao.admin.dto.UserInfoResponse.MenuItem> menus = menusForPermissions("order:list");

        // 顶层只有「工作台 + 交易管理 + 通知中心」
        assertThat(keysOf(menus)).containsExactly("workspace", "trade-center", "notifications");
        // 无 dashboard:view ⇒ 每日简报隐藏（但工作台组因经营看板仍在）
        var workspace = groupByKey(menus, "workspace");
        assertThat(namesOf(workspace.getChildren())).containsExactly("经营看板");
        // 负控（整组不出现，不得漏权限门控）
        assertThat(allNames(menus)).doesNotContain(
                "每日简报", "生产管理", "智能客服", "商品与加工项", "仓储与物料", "组织管理");
        assertThat(keysOf(menus)).doesNotContain(
                "production-center", "smart-customer-service", "product-center",
                "inventory-center", "org-center", "customer-center");
    }

    @Test
    @DisplayName("仓储与物料组：入库单落在**独立的** inbound:view 判定里（不得塞进 processing:manage）")
    void currentUserMenusGateInboundOrdersIndependently() {
        // 只有 inbound:view、没有 processing:manage ⇒ 入库单必须可见（否则仓管看不到菜单），
        // 且该组只含它一项
        List<com.migao.admin.dto.UserInfoResponse.MenuItem> menus = menusForPermissions("inbound:view");

        assertThat(keysOf(menus)).containsExactly("workspace", "inventory-center", "notifications");
        var inventory = groupByKey(menus, "inventory-center");
        assertThat(inventory.getName()).isEqualTo("仓储与物料");
        assertThat(namesOf(inventory.getChildren())).containsExactly("入库单");
        assertThat(pathsOf(inventory.getChildren())).containsExactly("/inbound-orders");
        // 自证渲染面非空 + 反向：processing:manage 的两项确实被门控挡在外面
        assertThat(allNames(menus)).contains("经营看板");
        assertThat(allNames(menus)).doesNotContain("余料台账", "省料看板", "生产看板");
    }

    @Test
    @DisplayName("交易管理组吸收客户列表/财务对账；「客户管理」组（customer-center）不再存在")
    void currentUserMenusAbsorbCustomerCenterIntoTrade() {
        List<com.migao.admin.dto.UserInfoResponse.MenuItem> menus =
                menusForPermissions("customer:view", "finance:view");

        assertThat(keysOf(menus)).containsExactly("workspace", "trade-center", "notifications");
        var trade = groupByKey(menus, "trade-center");
        assertThat(trade.getName()).isEqualTo("交易管理");
        assertThat(namesOf(trade.getChildren())).containsExactly("客户列表", "财务对账");
        assertThat(pathsOf(trade.getChildren())).containsExactly("/customers", "/finance");
        assertThat(keysOf(menus)).doesNotContain("customer-center", "customers", "finance");
    }

    @Test
    @DisplayName("智能客服组：只剩在线接待 + 知识库（旧「米宝 · 在线对话」节点已删除，无权限则整组不出现）")
    void currentUserMenusDropRemovedChatEntry() {
        List<com.migao.admin.dto.UserInfoResponse.MenuItem> menus =
                // issue #5246（已合入 main）：知识库节点码 = 读码 knowledge:view
                menusForPermissions("agent:session", "knowledge:view");

        var cs = groupByKey(menus, "smart-customer-service");
        assertThat(cs.getName()).isEqualTo("智能客服");
        assertThat(namesOf(cs.getChildren())).containsExactly("在线接待", "知识库");
        assertThat(pathsOf(cs.getChildren()))
                .containsExactly("/agent-workspace/human-sessions", "/knowledge");
        assertThat(allNames(menus)).doesNotContain("米宝 · 在线对话", "会话监控");
    }

    private void authenticateAs(String userId, Long tenantId) {
        com.migao.admin.security.SecurityUser securityUser = new com.migao.admin.security.SecurityUser(
                userId, tenantId, "13800138000", List.of("admin"),
                List.of(new org.springframework.security.core.authority.SimpleGrantedAuthority("ROLE_admin")));
        org.springframework.security.core.Authentication authentication =
                mock(org.springframework.security.core.Authentication.class);
        when(authentication.isAuthenticated()).thenReturn(true);
        when(authentication.getPrincipal()).thenReturn(securityUser);
        org.springframework.security.core.context.SecurityContextHolder.getContext().setAuthentication(authentication);
    }

    private void clearAuthentication() {
        org.springframework.security.core.context.SecurityContextHolder.clearContext();
    }
}
