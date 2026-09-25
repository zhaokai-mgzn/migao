// case_ids: AU-006
package com.migao.admin.security;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.LoginResponse;
import com.migao.admin.entity.Tenant;
import com.migao.admin.entity.User;
import com.migao.admin.mapper.PlatformAdminMapper;
import com.migao.admin.security.LoginFailureGuard;
import com.migao.admin.mapper.TenantAiConfigMapper;
import com.migao.admin.mapper.TenantMapper;
import com.migao.admin.mapper.UserIdentityMapper;
import com.migao.admin.mapper.UserMapper;
import com.migao.admin.service.AuthService;
import com.migao.admin.service.CustomerService;
import com.migao.admin.service.RoleService;
import com.migao.admin.service.SmsService;
import com.migao.admin.service.UserService;
import com.migao.admin.service.WechatService;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import jakarta.servlet.FilterChain;
import jakarta.servlet.http.Cookie;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.Spy;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.core.io.DefaultResourceLoader;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.test.util.ReflectionTestUtils;

import java.nio.charset.StandardCharsets;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.when;

/**
 * 首登强制改密的**拦截侧全链路**测试（issue #5485 不变式 I4）。
 *
 * <p>这里刻意用**真实 RSA 密钥的 JwtTokenProvider** + **真实过滤链顺序**
 * （{@link JwtAuthenticationFilter} → {@link PasswordChangeRequiredFilter} → 业务链），
 * 而不是两边各 mock 一半 —— 「claim 确实写进了 token」「过滤器确实读到了 claim」这两件事
 * 只有串起来跑才成立（本仓的「局部绿 ≠ 整体绿」形态）。</p>
 *
 * <p>四条判据（每条都有会红的形态）：
 * <ol>
 *   <li>未改密 → 业务 API <b>403 + PASSWORD_CHANGE_REQUIRED</b>，请求**到不了业务链**；</li>
 *   <li><b>刷新一次也没用</b>（最容易漏的那条）：刷新签发的新 token 仍带 claim ⇒ 仍 403；</li>
 *   <li>改密 ⇒ 换发的新 token 访问同一业务 API <b>放行</b>（不是「客户端记得再刷新一次」）；</li>
 *   <li>白名单（改密 / 登出 / 读自己信息 / 刷新）放行 —— 否则用户会被自己的门禁困死。</li>
 * </ol>
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("首登强制改密 - 拦截侧全链路")
class PasswordChangeEnforcementTest {

    /** 真实 JWT provider（与生产同一份 classpath 测试密钥；accessTokenExpiration 手工设为 7200）。 */
    @Spy
    private JwtTokenProvider jwtTokenProvider = realJwtProvider();

    @Spy
    private SimpleMeterRegistry meterRegistry = new SimpleMeterRegistry();

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
    private PasswordEncoder passwordEncoder;
    @Mock
    private StringRedisTemplate redisTemplate;
    @Mock
    private ValueOperations<String, String> valueOperations;
    @Mock
    private UserMapper userMapper;
    @Mock
    private TenantMapper tenantMapper;
    @Mock
    private UserIdentityMapper userIdentityMapper;
    @Mock
    private PlatformAdminMapper platformAdminMapper;
    @Mock
    private TenantAiConfigMapper tenantAiConfigMapper;
    @Mock
    private CustomerService customerService;

    /** 登录失败计数（issue #5531）：本类不测它 ⇒ 用 mock（默认未锁定 ⇒ 既有行为不变）。 */
    @Mock
    private LoginFailureGuard loginFailureGuard;

    private static final String BUSINESS_API = "/api/admin/users";

    private static JwtTokenProvider realJwtProvider() {
        try {
            JwtTokenProvider provider = new JwtTokenProvider(new DefaultResourceLoader());
            ReflectionTestUtils.setField(provider, "privateKeyPem", read("/rsa/private.pem"));
            ReflectionTestUtils.setField(provider, "publicKeyPem", read("/rsa/public.pem"));
            ReflectionTestUtils.setField(provider, "accessTokenExpiration", 7200L);
            ReflectionTestUtils.setField(provider, "refreshTokenExpiration", 604800L);
            provider.init();
            return provider;
        } catch (Exception e) {
            throw new IllegalStateException("测试用 RSA 密钥加载失败", e);
        }
    }

    private static String read(String path) throws Exception {
        try (var in = PasswordChangeEnforcementTest.class.getResourceAsStream(path)) {
            return new String(in.readAllBytes(), StandardCharsets.UTF_8);
        }
    }

    @BeforeEach
    void setUp() {
        ReflectionTestUtils.setField(authService, "cookieName", "access_token");
        ReflectionTestUtils.setField(authService, "cookieDomain", "");
        ReflectionTestUtils.setField(authService, "cookiePath", "/");
        ReflectionTestUtils.setField(authService, "cookieSecure", true);
        ReflectionTestUtils.setField(authService, "cookieHttpOnly", true);
        ReflectionTestUtils.setField(authService, "cookieSameSite", "strict");
        SecurityContextHolder.clearContext();
    }

    @AfterEach
    void tearDown() {
        SecurityContextHolder.clearContext();
        TenantContext.clear();
    }

    /**
     * 真实过滤链：JWT 认证过滤器（写请求属性）→ 强制改密过滤器（判 403 / 放行）→ 业务链。
     *
     * @return {@code 200} 表示请求到达业务链；否则返回过滤器写下的状态码
     */
    private int runFilterChain(String accessToken, String uri, MockHttpServletResponse response) throws Exception {
        MockHttpServletRequest request = new MockHttpServletRequest("GET", uri);
        if (accessToken != null) {
            request.setCookies(new Cookie("access_token", accessToken));
        }
        JwtAuthenticationFilter jwtFilter = new JwtAuthenticationFilter(jwtTokenProvider, redisTemplate, meterRegistry);
        ReflectionTestUtils.setField(jwtFilter, "cookieName", "access_token");
        PasswordChangeRequiredFilter pwdFilter = new PasswordChangeRequiredFilter();

        boolean[] reached = {false};
        FilterChain terminal = (req, res) -> reached[0] = true;

        SecurityContextHolder.clearContext();
        jwtFilter.doFilter(request, response, (req, res) -> pwdFilter.doFilter(req, res, terminal));
        return reached[0] ? 200 : response.getStatus();
    }

    private User employee() {
        return User.builder().id("user-A").tenantId(1L).username("zhangsan").phone("13800000001")
                .passwordHash("$2a$10$initHash").role("operator").status("active")
                .mustChangePassword(true).build();
    }

    private void authenticateAs(User user) {
        SecurityUser securityUser = new SecurityUser(user.getId(), user.getTenantId(), user.getUsername(),
                List.of("operator"), List.of(new SimpleGrantedAuthority("ROLE_OPERATOR")));
        SecurityContextHolder.getContext().setAuthentication(
                new UsernamePasswordAuthenticationToken(securityUser, null, securityUser.getAuthorities()));
    }

    @Test
    @DisplayName("I4 未改密 → 业务 API 403；刷新后仍 403；改密换发的新 token → 放行")
    void mustChangePassword_blocksUntilChanged_evenAfterRefresh() throws Exception {
        User employee = employee();
        when(redisTemplate.hasKey(anyString())).thenReturn(false);
        when(redisTemplate.opsForValue()).thenReturn(valueOperations);
        when(tenantMapper.selectOne(any())).thenReturn(
                Tenant.builder().id(1L).code("acme").name("甲公司").status("active").build());
        when(userMapper.selectActiveByTenantAndUsername(1L, "zhangsan")).thenReturn(employee);
        when(passwordEncoder.matches("init-pass1", "$2a$10$initHash")).thenReturn(true);
        when(passwordEncoder.encode("new-pass1")).thenReturn("$2a$10$newHash");
        when(userService.getUserRoles(employee)).thenReturn(List.of("operator"));
        when(userService.getUserById("user-A")).thenReturn(employee);
        when(roleService.getUserPermissions("user-A")).thenReturn(List.of("orders.list"));

        // ① 员工用管理员设的初始密码登录 ⇒ 拿到的是**带标记**的真实 token
        MockHttpServletResponse loginResponse = new MockHttpServletResponse();
        authService.loginByEmployee("zhangsan@acme", "init-pass1", loginResponse);
        String flaggedAccess = loginResponse.getCookie("access_token").getValue();
        String refresh = loginResponse.getCookie("refresh_token").getValue();
        assertThat(jwtTokenProvider.getClaimsFromToken(flaggedAccess)
                .get(JwtTokenProvider.CLAIM_PWD_CHANGE_REQUIRED, Boolean.class))
                .as("未改密会话的 token 必须带 pwd_change_required")
                .isTrue();

        // ② 业务 API 被拦（403 + 明确错误码），请求到不了业务链
        MockHttpServletResponse blocked = new MockHttpServletResponse();
        assertThat(runFilterChain(flaggedAccess, BUSINESS_API, blocked)).isEqualTo(403);
        assertThat(blocked.getContentAsString())
                .contains(PasswordChangeRequiredFilter.ERROR_CODE)
                .contains("首次登录需先修改密码");

        // ③ 刷新一次**没用** —— 新 token 的标记按库当前值重算（仍是 true）
        MockHttpServletResponse refreshResponse = new MockHttpServletResponse();
        authService.refreshToken(refresh, refreshResponse);
        String refreshedAccess = refreshResponse.getCookie("access_token").getValue();
        assertThat(jwtTokenProvider.getClaimsFromToken(refreshedAccess)
                .get(JwtTokenProvider.CLAIM_PWD_CHANGE_REQUIRED, Boolean.class))
                .as("刷新路径若只在登录时算标记，这里就会是 false ⇒ 强制改密被绕过")
                .isTrue();
        assertThat(runFilterChain(refreshedAccess, BUSINESS_API, new MockHttpServletResponse())).isEqualTo(403);

        // ④ 自助改密 ⇒ 响应里**直接**给一份不带标记的新 token
        authenticateAs(employee);
        MockHttpServletResponse changeResponse = new MockHttpServletResponse();
        LoginResponse changed = authService.changePassword("init-pass1", "new-pass1", changeResponse);
        String clearedAccess = changeResponse.getCookie("access_token").getValue();
        assertThat(clearedAccess).isEqualTo(changed.getAccessToken());
        assertThat(jwtTokenProvider.getClaimsFromToken(clearedAccess)
                .get(JwtTokenProvider.CLAIM_PWD_CHANGE_REQUIRED, Boolean.class))
                .as("改密后换发的 token 不得再带标记")
                .isFalse();

        // ⑤ 用「改密响应里的那个 token」访问同一个业务 API ⇒ 放行（到达业务链）
        assertThat(runFilterChain(clearedAccess, BUSINESS_API, new MockHttpServletResponse())).isEqualTo(200);

        // ⑥ 而**旧 token** 仍然被拦（拦截侧只看 claim，不看库）—— 如实钉住这一性质：
        //    客户端必须用改密响应里的新 token（本单已让服务端直接下发，不依赖前端记忆）
        assertThat(runFilterChain(flaggedAccess, BUSINESS_API, new MockHttpServletResponse())).isEqualTo(403);
    }

    @Test
    @DisplayName("I4 白名单：改密/登出/读自己信息/刷新 放行；其余一律 403")
    void whitelist_minimalAndExplicit() throws Exception {
        when(redisTemplate.hasKey(anyString())).thenReturn(false);
        String flaggedAccess = jwtTokenProvider.generateAccessToken(
                "user-A", 1L, "zhangsan", List.of("operator"), List.of("orders.list"), true);

        for (String allowed : List.of("/api/auth/password/change", "/api/auth/logout",
                "/api/auth/me", "/api/auth/refresh")) {
            assertThat(runFilterChain(flaggedAccess, allowed, new MockHttpServletResponse()))
                    .as("白名单路径必须放行（否则用户被自己的门禁困死）: %s", allowed)
                    .isEqualTo(200);
        }
        for (String blockedUri : List.of("/api/admin/users", "/api/admin/orders",
                "/api/admin/settings", "/api/auth/employee/login")) {
            assertThat(runFilterChain(flaggedAccess, blockedUri, new MockHttpServletResponse()))
                    .as("白名单外一律 403: %s", blockedUri)
                    .isEqualTo(403);
        }
    }

    @Test
    @DisplayName("I4 不带标记的会话 / 未认证请求：不受本过滤器影响（不误伤）")
    void unflaggedSessions_areNotAffected() throws Exception {
        String cleanAccess = jwtTokenProvider.generateAccessToken(
                "user-A", 1L, "zhangsan", List.of("operator"), List.of("orders.list"), false);

        assertThat(runFilterChain(cleanAccess, BUSINESS_API, new MockHttpServletResponse())).isEqualTo(200);
        // 未认证（无 token）→ 不写 403（该由 SecurityConfig 的 entryPoint 给 401）
        assertThat(runFilterChain(null, BUSINESS_API, new MockHttpServletResponse())).isEqualTo(200);
    }
}