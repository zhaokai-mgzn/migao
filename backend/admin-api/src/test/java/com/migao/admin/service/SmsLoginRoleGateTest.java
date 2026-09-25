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
import jakarta.servlet.http.HttpServletResponse;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
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
 */
@ExtendWith(MockitoExtension.class)
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
        when(jwtTokenProvider.generateAccessToken(anyString(), any(), anyString(), anyList(), anyList(), any()))
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
        verify(jwtTokenProvider, never()).generateAccessToken(anyString(), any(), anyString(), anyList(), anyList(), any());
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