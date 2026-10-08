// case_ids: AU-004, AU-005
package com.migao.admin.service;

import com.migao.admin.dto.LoginResponse;
import com.migao.admin.entity.PlatformAdmin;
import com.migao.admin.entity.User;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.PlatformAdminMapper;
import com.migao.admin.mapper.TenantAiConfigMapper;
import com.migao.admin.mapper.TenantMapper;
import com.migao.admin.mapper.UserIdentityMapper;
import com.migao.admin.mapper.UserMapper;
import com.migao.admin.security.JwtTokenProvider;
import com.migao.admin.security.LoginFailureGuard;
import jakarta.servlet.http.HttpServletResponse;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.data.redis.core.StringRedisTemplate;
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
 * 短信登录的**角色门禁**测试（issue #5485 不变式 I2）。
 *
 * <p>改前：{@code loginBySms} 对角色没有任何门禁 —— 普通员工手机号对得上就能短信登录。
 * 改后：短信登录**只**服务平台超管（{@code platform_admins}）与企业管理员（{@code role='admin'}）；
 * 其余角色一律拒绝，并**明确引导**改用员工登录入口。</p>
 *
 * <p>红证形态：把门禁删掉（或改成 {@code role != null}）⇒ 下面三条拒绝用例立刻变绿/不抛，
 * 测试即红；把门禁扩到平台超管路径 ⇒ AU-005 两条立刻红。</p>
 *
 * <p>🔴 <b>issue #6159（同租户内同号）</b>：{@code loginBySms} 的**手机号歧义**口径在此一并钉住 ——
 * 指定了 {@code tenantId} 之后，同一租户内命中**多于一条**同样 fail-closed（逐字文案见
 * {@code PHONE_AMBIGUOUS_MESSAGE} 的断言），**不得**回到 {@code .findFirst()} 那种「按返回顺序
 * 静默选一条」的形态。红证形态：把该口径改回 {@code findFirst()} ⇒
 * {@link #sameTenantSamePhoneAmbiguity_rejected_orderIndependent} 当场红（两种返回顺序里必有一种
 * 会成功登录出另一个账号）。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("短信登录角色门禁（仅管理员）")
class SmsLoginRoleGateTest {

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

    private static final String PHONE = "13800138000";
    private static final String CODE = "123456";

    @BeforeEach
    void setUp() {
        ReflectionTestUtils.setField(authService, "cookieName", "access_token");
        ReflectionTestUtils.setField(authService, "cookieDomain", "");
        ReflectionTestUtils.setField(authService, "cookiePath", "/");
        ReflectionTestUtils.setField(authService, "cookieSecure", true);
        ReflectionTestUtils.setField(authService, "cookieHttpOnly", true);
        ReflectionTestUtils.setField(authService, "cookieSameSite", "strict");
        when(smsService.verifyCode(PHONE, CODE)).thenReturn(true);
    }

    private User tenantUser(String role) {
        return User.builder().id("user-1").tenantId(1L).phone(PHONE)
                .passwordHash(null).role(role).status("active").build();
    }

    private void stubTenantUserLogin() {
        when(jwtTokenProvider.generateAccessToken(anyString(), any(), anyString(), anyList(), anyList(), anyBoolean()))
                .thenReturn("access");
        when(jwtTokenProvider.generateRefreshToken(anyString(), any())).thenReturn("refresh");
        when(jwtTokenProvider.getAccessTokenExpiration()).thenReturn(7200L);
    }

    // ======================== AU-004：非管理员一律拒绝 ========================

    @Test
    @DisplayName("AU-004 普通员工（role=operator）走短信 ⇒ 拒绝 + 引导员工登录入口")
    void nonAdminOperator_rejected() {
        User operator = tenantUser("operator");
        when(userMapper.selectActiveUsersByPhoneIgnoreTenant(PHONE)).thenReturn(List.of(operator));
        when(userService.getUserRoles(operator)).thenReturn(List.of("operator"));

        assertThatThrownBy(() -> authService.loginBySms(PHONE, CODE, null, mock(HttpServletResponse.class)))
                .isInstanceOf(BusinessException.class)
                .hasFieldOrPropertyWithValue("code", "AUTH_FAILED")
                .hasFieldOrPropertyWithValue("httpStatus", 401)
                .hasMessage("该账号非管理员，请使用员工登录入口（用户名@企业编码 + 密码）");

        // 拒绝必须是**签发前**的：一个 token 都不许发
        verify(jwtTokenProvider, never()).generateAccessToken(anyString(), any(), anyString(), anyList(), anyList(), anyBoolean());
        verify(jwtTokenProvider, never()).generateRefreshToken(anyString(), any());
    }

    @Test
    @DisplayName("AU-004 员工（role=employee，评测种子 debug_employee_wangwu 的形态）同样被拒")
    void nonAdminEmployeeRole_rejected() {
        User employee = tenantUser("employee");
        when(userMapper.selectActiveUsersByPhoneIgnoreTenant("13700137000")).thenReturn(List.of(employee));
        when(smsService.verifyCode("13700137000", CODE)).thenReturn(true);
        when(userService.getUserRoles(employee)).thenReturn(List.of("employee"));

        assertThatThrownBy(() -> authService.loginBySms("13700137000", CODE, null, mock(HttpServletResponse.class)))
                .isInstanceOf(BusinessException.class)
                .hasFieldOrPropertyWithValue("code", "AUTH_FAILED")
                .hasMessageContaining("非管理员");
    }

    @Test
    @DisplayName("AU-004 C 端顾客（role=customer）走短信 ⇒ 同样拒绝（不是「有账号就行」）")
    void customerRole_rejected() {
        User customer = tenantUser("customer");
        when(userMapper.selectActiveUsersByPhoneIgnoreTenant(PHONE)).thenReturn(List.of(customer));
        when(userService.getUserRoles(customer)).thenReturn(List.of("customer"));

        assertThatThrownBy(() -> authService.loginBySms(PHONE, CODE, null, mock(HttpServletResponse.class)))
                .isInstanceOf(BusinessException.class)
                .hasFieldOrPropertyWithValue("code", "AUTH_FAILED")
                .hasMessageContaining("非管理员");
    }

    @Test
    @DisplayName("AU-004 多租户歧义口径不回退（审计 07 P1-2）：未指定租户仍拒绝落错租户")
    void multiTenantAmbiguity_stillRejected() {
        User a = User.builder().id("u-a").tenantId(1L).phone(PHONE).role("admin").status("active").build();
        User b = User.builder().id("u-b").tenantId(2L).phone(PHONE).role("admin").status("active").build();
        when(userMapper.selectActiveUsersByPhoneIgnoreTenant(PHONE)).thenReturn(List.of(a, b));

        assertThatThrownBy(() -> authService.loginBySms(PHONE, CODE, null, mock(HttpServletResponse.class)))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("多个租户");
    }

    // ================== AU-004：同一租户内同号歧义（issue #6159） ==================

    /**
     * issue #6159 的逐字文案（唯一来源）：既证明「拒绝」发生了，也证明拒绝的是**同租户歧义**
     * 而不是别的病因（例如「用户不存在」/「非管理员」——那两条各有自己的文案）。
     */
    private static final String PHONE_AMBIGUOUS_MESSAGE =
            "该手机号在本企业内对应多个账号，无法确定登录身份，请联系企业管理员核对账号手机号";

    @Test
    @DisplayName("AU-004 同一租户内同号两账号 + 指定 tenantId ⇒ 拒绝（顺序无关：两种返回顺序都不许登进去）")
    void sameTenantSamePhoneAmbiguity_rejected_orderIndependent() {
        // 开发库租户 1 的形态：13800138000 同时命中 user_admin_001 与 user_superadmin
        User a = User.builder().id("user_admin_001").tenantId(1L).phone(PHONE).role("admin").status("active").build();
        User b = User.builder().id("user_superadmin").tenantId(1L).phone(PHONE).role("admin").status("active").build();
        // 🔴 两条都是**合法管理员**、签发链完整配好 —— 于是「改前会不会登进去」不再被别的
        //    病因（非管理员 / 缺桩）遮住：唯一能拦住它们的就是本单加的歧义判据。
        when(userService.getUserRoles(a)).thenReturn(List.of("admin"));
        when(userService.getUserRoles(b)).thenReturn(List.of("admin"));
        when(roleService.getUserPermissions("user_admin_001")).thenReturn(List.of("*"));
        when(roleService.getUserPermissions("user_superadmin")).thenReturn(List.of("*"));
        stubTenantUserLogin();

        // 两种返回顺序都必须给出**同一个**结论 —— 这才是「不依赖查询顺序」的可执行形态。
        // 红证（把同租户歧义判据摘掉 ⇒ 回到 `.findFirst()`）：两轮**都**没有歧义文案，
        // 且各自把 rows.get(0) 登进去、签发了一份 token ⇒ 本条当场红（第一轮拿 a、第二轮拿 b，
        // 「我登进去的是谁」随 SQL 返回顺序漂移）。
        int round = 0;
        for (List<User> rows : List.of(List.of(a, b), List.of(b, a))) {
            round++;
            org.mockito.Mockito.clearInvocations(jwtTokenProvider);
            when(userMapper.selectActiveUsersByPhoneIgnoreTenant(PHONE)).thenReturn(rows);
            final String expectedFirstId = rows.get(0).getId();

            Throwable thrown = org.assertj.core.api.Assertions.catchThrowable(
                    () -> authService.loginBySms(PHONE, CODE, 1L, mock(HttpServletResponse.class)));

            // 判据一：必须抛，且抛的是**同租户歧义**（逐字文案；不是「非管理员」/「未注册」）
            assertThat(thrown)
                    .as("第 %d 轮（返回顺序首行 = %s）必须拒绝同租户内同号歧义", round, expectedFirstId)
                    .isInstanceOf(BusinessException.class)
                    .hasFieldOrPropertyWithValue("code", "AUTH_FAILED")
                    .hasFieldOrPropertyWithValue("httpStatus", 401)
                    .hasMessage(PHONE_AMBIGUOUS_MESSAGE);

            // 判据二：歧义判据在**签发之前** —— 一个 token 都不许发（否则「拒绝」是假的）
            verify(jwtTokenProvider, never()).generateAccessToken(
                    anyString(), any(), anyString(), anyList(), anyList(), anyBoolean());
            verify(jwtTokenProvider, never()).generateRefreshToken(anyString(), any());
        }
    }

    @Test
    @DisplayName("AU-004 对照：同号跨租户 + 指定 tenantId 仍照旧放行（不误伤既有跨租户口径）")
    void samePhoneCrossTenant_withTenantId_notOverRejected() {
        User t1 = User.builder().id("u-t1").tenantId(1L).phone(PHONE).role("admin").status("active").build();
        // 选中的这条**状态非 active** ⇒ 只允许走到第 4 步「状态校验」才发现 —— 用来证明它
        // 没被新加的**同租户歧义**判据拦下（拦下的话文案是 PHONE_AMBIGUOUS_MESSAGE）
        User t2 = User.builder().id("u-t2").tenantId(2L).phone(PHONE).role("admin").status("disabled").build();
        when(userMapper.selectActiveUsersByPhoneIgnoreTenant(PHONE)).thenReturn(List.of(t1, t2));

        assertThatThrownBy(() -> authService.loginBySms(PHONE, CODE, 2L, mock(HttpServletResponse.class)))
                .isInstanceOf(BusinessException.class)
                .hasFieldOrPropertyWithValue("code", "AUTH_FAILED")
                .hasMessage("用户状态异常");
    }

    // ======================== AU-005：管理员两条路径继续可用 ========================

    @Test
    @DisplayName("AU-005 平台超管（platform_admins）短信登录照旧：tenantId=-1、role=super_admin")
    void platformSuperAdmin_stillCanLoginBySms() {
        PlatformAdmin platformAdmin = PlatformAdmin.builder()
                .id("pa-1").phone(PHONE).nickname("平台超管").status("active").build();
        when(platformAdminMapper.selectOne(any())).thenReturn(platformAdmin);
        when(jwtTokenProvider.generateAccessToken(eq("pa-1"), eq(-1L), anyString(), anyList())).thenReturn("pa-access");
        when(jwtTokenProvider.generateRefreshToken(eq("pa-1"), eq(-1L))).thenReturn("pa-refresh");
        when(jwtTokenProvider.getAccessTokenExpiration()).thenReturn(7200L);

        LoginResponse result = authService.loginBySms(PHONE, CODE, null, mock(HttpServletResponse.class));

        assertThat(result.getUser().getRole()).isEqualTo("super_admin");
        assertThat(result.getUser().getTenantId()).isEqualTo(-1L);
        assertThat(result.getUser().getIdentityType()).isEqualTo("sms");
        // 平台管理员**没有** users 行 ⇒ 不得被角色门禁拦下（那条门禁只管租户用户）
        verify(userService, never()).getUserRoles(any(User.class));
    }

    @Test
    @DisplayName("AU-005 企业管理员（role=admin）短信登录照旧可用（并带 mustChangePassword 字段）")
    void tenantAdmin_stillCanLoginBySms() {
        User admin = tenantUser("admin");
        when(userMapper.selectActiveUsersByPhoneIgnoreTenant(PHONE)).thenReturn(List.of(admin));
        when(userService.getUserRoles(admin)).thenReturn(List.of("admin"));
        when(roleService.getUserPermissions("user-1")).thenReturn(List.of("*"));
        stubTenantUserLogin();

        LoginResponse result = authService.loginBySms(PHONE, CODE, null, mock(HttpServletResponse.class));

        assertThat(result.getUser().getId()).isEqualTo("user-1");
        assertThat(result.getUser().getRole()).isEqualTo("admin");
        assertThat(result.getUser().getTenantId()).isEqualTo(1L);
        assertThat(result.getUser().getMustChangePassword()).isFalse();
        verify(jwtTokenProvider).generateAccessToken("user-1", 1L, PHONE, List.of("admin"), List.of("*"), false);
    }
}