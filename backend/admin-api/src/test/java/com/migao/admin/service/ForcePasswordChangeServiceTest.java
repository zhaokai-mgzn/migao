// case_ids: AU-006
package com.migao.admin.service;

import com.migao.admin.dto.LoginResponse;
import com.migao.admin.entity.Tenant;
import com.migao.admin.entity.User;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.PlatformAdminMapper;
import com.migao.admin.mapper.TenantAiConfigMapper;
import com.migao.admin.mapper.TenantMapper;
import com.migao.admin.mapper.UserIdentityMapper;
import com.migao.admin.mapper.UserMapper;
import com.migao.admin.security.JwtTokenProvider;
import com.migao.admin.security.LoginFailureGuard;
import com.migao.admin.security.SecurityUser;
import jakarta.servlet.http.HttpServletResponse;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyBoolean;
import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 首登强制改密的**签发侧**单元测试（issue #5485 不变式 I4）。
 *
 * <p>拦截侧（403 与白名单）的证据在 {@code PasswordChangeEnforcementTest}；本文件钉的是
 * **JWT claim 的取值来源**：
 * <ul>
 *   <li>刷新 token 时（最容易漏的一条）标记必须按**数据库当前值**重算 —— 「只在登录时算」
 *       会被「刷新一次 token」直接绕过；</li>
 *   <li>改密成功后必须清除标记**并换发**一份不带标记的新 token（不把「记得再刷新一次」
 *       留给前端 —— 漏了就是「改完密码反而全站 403」）；</li>
 *   <li>密码策略不满足 ⇒ 422 明确文案；旧密码错 ⇒ 422；平台超管 ⇒ 明确业务错误（不是 NPE/404）。</li>
 * </ul>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("首登强制改密 - 签发侧")
class ForcePasswordChangeServiceTest {

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

    private final Tenant tenantA = Tenant.builder().id(1L).code("acme").name("甲公司").status("active").build();

    /** 管理员刚设过初始密码的员工：must_change_password = TRUE。 */
    private User pendingUser;
    /** 已自助改过密的同一员工：must_change_password = FALSE。 */
    private User clearedUser;

    @BeforeEach
    void setUp() {
        ReflectionTestUtils.setField(authService, "cookieName", "access_token");
        ReflectionTestUtils.setField(authService, "cookieDomain", "");
        ReflectionTestUtils.setField(authService, "cookiePath", "/");
        ReflectionTestUtils.setField(authService, "cookieSecure", true);
        ReflectionTestUtils.setField(authService, "cookieHttpOnly", true);
        ReflectionTestUtils.setField(authService, "cookieSameSite", "strict");

        pendingUser = User.builder().id("user-A").tenantId(1L).username("zhangsan").phone("13800000001")
                .passwordHash("$2a$10$oldHash").role("operator").status("active")
                .mustChangePassword(true).build();
        clearedUser = User.builder().id("user-A").tenantId(1L).username("zhangsan").phone("13800000001")
                .passwordHash("$2a$10$newHash").role("operator").status("active")
                .mustChangePassword(false).build();

        when(jwtTokenProvider.getAccessTokenExpiration()).thenReturn(7200L);
    }

    @AfterEach
    void tearDown() {
        SecurityContextHolder.clearContext();
    }

    private void authenticateAs(User user, String... roles) {
        SecurityUser securityUser = new SecurityUser(user.getId(), user.getTenantId(), user.getUsername(),
                List.of(roles),
                List.of(roles).stream().map(r -> new SimpleGrantedAuthority("ROLE_" + r)).toList());
        SecurityContextHolder.getContext().setAuthentication(
                new UsernamePasswordAuthenticationToken(securityUser, null, securityUser.getAuthorities()));
    }

    /** 捕获签发时传入的 {@code passwordChangeRequired} 第 6 个实参。 */
    private boolean capturedFlag() {
        ArgumentCaptor<Boolean> flag = ArgumentCaptor.forClass(Boolean.class);
        verify(jwtTokenProvider).generateAccessToken(anyString(), any(), anyString(), anyList(), anyList(),
                flag.capture());
        return Boolean.TRUE.equals(flag.getValue());
    }

    // ======================== 刷新路径（最容易漏） ========================

    @Test
    @DisplayName("I4 刷新 token：库中仍为 true ⇒ 新 access token 仍带 pwd_change_required（刷一次不能绕过）")
    void refreshToken_stillFlagged_recomputesFlagAsTrue() {
        io.jsonwebtoken.Claims claims = mock(io.jsonwebtoken.Claims.class);
        when(claims.getId()).thenReturn(null);
        when(jwtTokenProvider.validateToken("rt")).thenReturn(true);
        when(jwtTokenProvider.isRefreshToken("rt")).thenReturn(true);
        when(jwtTokenProvider.getClaimsFromToken("rt")).thenReturn(claims);
        when(jwtTokenProvider.getUserIdFromToken("rt")).thenReturn("user-A");
        when(userService.getUserById("user-A")).thenReturn(pendingUser);
        when(userService.getUserRoles(pendingUser)).thenReturn(List.of("operator"));
        when(roleService.getUserPermissions("user-A")).thenReturn(List.of());
        when(jwtTokenProvider.generateAccessToken(anyString(), any(), anyString(), anyList(), anyList(), anyBoolean()))
                .thenReturn("new-access");
        when(jwtTokenProvider.generateRefreshToken("user-A", 1L)).thenReturn("new-refresh");

        LoginResponse result = authService.refreshToken("rt", mock(HttpServletResponse.class));

        assertThat(capturedFlag())
                .as("刷新时必须按数据库当前 must_change_password 重算（否则刷一次就绕过了强制改密）")
                .isTrue();
        assertThat(result.getUser().getMustChangePassword()).isTrue();
    }

    @Test
    @DisplayName("I4 刷新 token：改密后库中为 false ⇒ 新 access token 不再带标记")
    void refreshToken_afterChange_flagFalse() {
        io.jsonwebtoken.Claims claims = mock(io.jsonwebtoken.Claims.class);
        when(claims.getId()).thenReturn(null);
        when(jwtTokenProvider.validateToken("rt")).thenReturn(true);
        when(jwtTokenProvider.isRefreshToken("rt")).thenReturn(true);
        when(jwtTokenProvider.getClaimsFromToken("rt")).thenReturn(claims);
        when(jwtTokenProvider.getUserIdFromToken("rt")).thenReturn("user-A");
        when(userService.getUserById("user-A")).thenReturn(clearedUser);
        when(userService.getUserRoles(clearedUser)).thenReturn(List.of("operator"));
        when(roleService.getUserPermissions("user-A")).thenReturn(List.of());
        when(jwtTokenProvider.generateAccessToken(anyString(), any(), anyString(), anyList(), anyList(), anyBoolean()))
                .thenReturn("new-access");
        when(jwtTokenProvider.generateRefreshToken("user-A", 1L)).thenReturn("new-refresh");

        authService.refreshToken("rt", mock(HttpServletResponse.class));

        assertThat(capturedFlag()).isFalse();
    }

    // ======================== 改密路径 ========================

    @Test
    @DisplayName("I4 改密成功：清除标记 + **换发**不带标记的新 token（不依赖前端再刷新一次）")
    void changePassword_clearsFlag_andReissuesTokenWithoutFlag() {
        authenticateAs(pendingUser, "operator");
        when(userService.getUserById("user-A")).thenReturn(pendingUser);
        when(passwordEncoder.matches("old-pass1", "$2a$10$oldHash")).thenReturn(true);
        when(passwordEncoder.encode("new-pass1")).thenReturn("$2a$10$newHash");
        when(userService.getUserRoles(pendingUser)).thenReturn(List.of("operator"));
        when(roleService.getUserPermissions("user-A")).thenReturn(List.of("orders.list"));
        when(jwtTokenProvider.generateAccessToken(anyString(), any(), anyString(), anyList(), anyList(), anyBoolean()))
                .thenReturn("fresh-access");
        when(jwtTokenProvider.generateRefreshToken("user-A", 1L)).thenReturn("fresh-refresh");

        LoginResponse result = authService.changePassword(
                "old-pass1", "new-pass1", mock(HttpServletResponse.class));

        assertThat(capturedFlag()).as("换发的 token 不能带 pwd_change_required").isFalse();
        assertThat(result.getAccessToken()).isEqualTo("fresh-access");
        assertThat(result.getUser().getMustChangePassword()).isFalse();
        assertThat(pendingUser.getMustChangePassword()).isFalse();
        verify(userMapper).updateById(pendingUser);
    }

    @Test
    @DisplayName("I4 改密：密码策略不满足（纯字母 / 少于 8 位）⇒ 422 + 明确文案")
    void changePassword_weakPassword_rejectedWith422() {
        authenticateAs(pendingUser, "operator");
        when(userService.getUserById("user-A")).thenReturn(pendingUser);
        when(passwordEncoder.matches("old-pass1", "$2a$10$oldHash")).thenReturn(true);

        assertThatThrownBy(() -> authService.changePassword(
                "old-pass1", "abcdefgh", mock(HttpServletResponse.class)))
                .isInstanceOf(BusinessException.class)
                .hasFieldOrPropertyWithValue("code", "VALIDATION_ERROR")
                .hasFieldOrPropertyWithValue("httpStatus", 422)
                .hasMessage(AuthService.PASSWORD_POLICY_MESSAGE);

        assertThatThrownBy(() -> authService.changePassword(
                "old-pass1", "ab1", mock(HttpServletResponse.class)))
                .isInstanceOf(BusinessException.class)
                .hasFieldOrPropertyWithValue("httpStatus", 422)
                .hasMessage(AuthService.PASSWORD_POLICY_MESSAGE);

        // 策略不通过 ⇒ 一个字节都不许写库
        verify(userMapper, never()).updateById(any(User.class));
    }

    @Test
    @DisplayName("I4 改密：旧密码不正确 ⇒ 422，不泄露、不写库")
    void changePassword_wrongOldPassword_rejected() {
        authenticateAs(pendingUser, "operator");
        when(userService.getUserById("user-A")).thenReturn(pendingUser);
        when(passwordEncoder.matches("bad-old", "$2a$10$oldHash")).thenReturn(false);

        assertThatThrownBy(() -> authService.changePassword(
                "bad-old", "new-pass1", mock(HttpServletResponse.class)))
                .isInstanceOf(BusinessException.class)
                .hasFieldOrPropertyWithValue("code", "VALIDATION_ERROR")
                .hasMessage("原密码不正确");

        verify(userMapper, never()).updateById(any(User.class));
    }

    @Test
    @DisplayName("I4 改密：平台超管（platform_admins，无 users 行）⇒ 明确业务错误，不是 NPE/404")
    void changePassword_platformSuperAdmin_clearBusinessError() {
        SecurityUser platformSuperAdmin = new SecurityUser("admin-1", -1L, "13800138000",
                List.of("super_admin"), List.of(new SimpleGrantedAuthority("ROLE_SUPER_ADMIN")));
        SecurityContextHolder.getContext().setAuthentication(
                new UsernamePasswordAuthenticationToken(platformSuperAdmin, null,
                        platformSuperAdmin.getAuthorities()));

        assertThatThrownBy(() -> authService.changePassword(
                "whatever", "new-pass1", mock(HttpServletResponse.class)))
                .isInstanceOf(BusinessException.class)
                .hasFieldOrPropertyWithValue("code", "AUTH_FAILED")
                .hasMessage("平台管理员账号不支持在本入口修改密码");

        verify(userService, never()).getUserById(anyString());
    }

    @Test
    @DisplayName("I4 改密：未认证 ⇒ 401（不是 500）")
    void changePassword_unauthenticated_rejected() {
        SecurityContextHolder.clearContext();

        assertThatThrownBy(() -> authService.changePassword(
                "old-pass1", "new-pass1", mock(HttpServletResponse.class)))
                .isInstanceOf(BusinessException.class)
                .hasFieldOrPropertyWithValue("code", "AUTH_FAILED")
                .hasMessage("用户未认证");
    }

    @Test
    @DisplayName("I4 员工登录时标记取自数据库（true ⇒ 响应与 claim 都为 true）")
    void employeeLogin_carriesFlagFromDatabase() {
        pendingUser.setUsername("zhangsan");
        when(tenantMapper.selectOne(any())).thenReturn(tenantA);
        when(userMapper.selectActiveByTenantAndUsername(1L, "zhangsan")).thenReturn(pendingUser);
        when(passwordEncoder.matches("init-pass1", "$2a$10$oldHash")).thenReturn(true);
        when(userService.getUserRoles(pendingUser)).thenReturn(List.of("operator"));
        when(roleService.getUserPermissions("user-A")).thenReturn(List.of());
        when(jwtTokenProvider.generateAccessToken(anyString(), any(), anyString(), anyList(), anyList(), anyBoolean()))
                .thenReturn("access");
        when(jwtTokenProvider.generateRefreshToken("user-A", 1L)).thenReturn("refresh");

        LoginResponse result = authService.loginByEmployee(
                "zhangsan@acme", "init-pass1", mock(HttpServletResponse.class));

        assertThat(capturedFlag()).isTrue();
        assertThat(result.getUser().getMustChangePassword()).isTrue();
        assertThat(result.getUser().getIdentityType()).isEqualTo("employee");
        verify(jwtTokenProvider).generateAccessToken(eq("user-A"), eq(1L), eq("zhangsan"),
                anyList(), anyList(), eq(true));
    }
}