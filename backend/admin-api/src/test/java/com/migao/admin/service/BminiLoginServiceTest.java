// case_ids: BM-001, BM-002, BM-003
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.Wrapper;
import com.migao.admin.dto.BminiLoginRequest;
import com.migao.admin.dto.LoginResponse;
import com.migao.admin.entity.Tenant;
import com.migao.admin.entity.User;
import com.migao.admin.entity.UserIdentity;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.PlatformAdminMapper;
import com.migao.admin.mapper.TenantMapper;
import com.migao.admin.mapper.UserIdentityMapper;
import com.migao.admin.mapper.UserMapper;
import com.migao.admin.security.JwtTokenProvider;
import jakarta.servlet.http.HttpServletResponse;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.Collections;
import java.util.List;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

/**
 * B 端员工小程序登录（bmini）单元测试
 *
 * 覆盖 issue #2977 登录绑定契约：
 * - BM-001 首次登录：code→openid 无绑定 → getPhoneNumber 换号 → 匹配员工 → 绑定 → 签发员工 JWT
 * - BM-002 二次登录：openid 已绑定 → 直接签发（不再要求 phoneCode）
 * - BM-003 手机号未匹配员工 → 拒绝且禁止自动建号（与 C 端 findOrCreate 语义相反）
 */
@ExtendWith(MockitoExtension.class)
class BminiLoginServiceTest {

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
    private UserIdentityMapper userIdentityMapper;
    @Mock
    private TenantMapper tenantMapper;
    @Mock
    private PlatformAdminMapper platformAdminMapper;
    @Mock
    private com.migao.admin.mapper.TenantAiConfigMapper tenantAiConfigMapper;

    private User employee;
    private BminiLoginRequest firstLoginRequest;

    @BeforeEach
    void setUp() {
        ReflectionTestUtils.setField(authService, "cookieName", "access_token");
        ReflectionTestUtils.setField(authService, "cookieDomain", "");
        ReflectionTestUtils.setField(authService, "cookiePath", "/");
        ReflectionTestUtils.setField(authService, "cookieSecure", true);
        ReflectionTestUtils.setField(authService, "cookieHttpOnly", true);
        ReflectionTestUtils.setField(authService, "cookieSameSite", "strict");
        // B 端小程序 appid（绑定 identity 时写入，与 C 端隔离）
        ReflectionTestUtils.setField(authService, "bminiAppId", "bmini-app-id");

        // 商户员工账号（role=operator，非 customer/agent）
        employee = User.builder()
                .id("emp-001")
                .tenantId(1L)
                .phone("13900000001")
                .nickname("运营小王")
                .role("operator")
                .status("active")
                .build();

        // 首次登录请求：wx.login code + getPhoneNumber 授权 code
        firstLoginRequest = new BminiLoginRequest();
        firstLoginRequest.setCode("wx-login-code-1");
        firstLoginRequest.setPhoneCode("phone-auth-code-1");
    }

    // ======================== BM-001 首次绑定登录 ========================

    @Test
    @DisplayName("首次登录：openid 无绑定 → 换号匹配员工 → 绑定 identity → 签发员工 JWT (BM-001)")
    void firstLogin_BindsEmployee_AndIssuesJwt() {
        // Given: code2Session 返回 openid；无既有绑定
        WechatService.Code2SessionResult session = new WechatService.Code2SessionResult();
        session.setOpenid("openid-bmini-001");
        when(wechatService.bminiCode2Session("wx-login-code-1")).thenReturn(session);

        when(userIdentityMapper.selectOne(any(Wrapper.class))).thenReturn(null);

        // getPhoneNumber 换号 → 员工手机号
        WechatService.PhoneNumberResult phone = new WechatService.PhoneNumberResult();
        phone.setPurePhoneNumber("13900000001");
        when(wechatService.bminiGetPhoneNumber("phone-auth-code-1")).thenReturn(phone);

        // 手机号匹配到唯一员工（跨租户查询，operator 角色）
        when(userMapper.selectActiveEmployeesByPhoneIgnoreTenant("13900000001"))
                .thenReturn(List.of(employee));

        // 角色与权限
        when(userService.getUserRoles(employee)).thenReturn(List.of("operator"));
        when(roleService.getUserPermissions("emp-001")).thenReturn(List.of("dashboard:view", "agent:session"));

        // JWT
        when(jwtTokenProvider.generateAccessToken(eq("emp-001"), eq(1L), eq("13900000001"),
                anyList(), anyList())).thenReturn("access-token-bmini-1");
        when(jwtTokenProvider.generateRefreshToken("emp-001", 1L)).thenReturn("refresh-token-1");
        when(jwtTokenProvider.getAccessTokenExpiration()).thenReturn(7200L);
        when(tenantMapper.selectById(1L)).thenReturn(Tenant.builder().name("词元通达").build());

        HttpServletResponse response = mock(HttpServletResponse.class);

        // When
        LoginResponse result = authService.bminiLogin(firstLoginRequest, response);

        // Then: 返回员工 token + identityType=bmini
        assertThat(result).isNotNull();
        assertThat(result.getAccessToken()).isEqualTo("access-token-bmini-1");
        assertThat(result.getUser().getId()).isEqualTo("emp-001");
        assertThat(result.getUser().getRole()).isEqualTo("operator");
        assertThat(result.getUser().getIdentityType()).isEqualTo("bmini");

        // 绑定记录写入 user_identities（identityType=bmini_app + 员工 userId + tenantId）
        ArgumentCaptor<UserIdentity> captor = ArgumentCaptor.forClass(UserIdentity.class);
        verify(userIdentityMapper).insert(captor.capture());
        UserIdentity bound = captor.getValue();
        assertThat(bound.getIdentityType()).isEqualTo("bmini_app");
        assertThat(bound.getAppId()).isEqualTo("bmini-app-id");
        assertThat(bound.getOpenid()).isEqualTo("openid-bmini-001");
        assertThat(bound.getUserId()).isEqualTo("emp-001");
        assertThat(bound.getTenantId()).isEqualTo(1L);
    }

    @Test
    @DisplayName("首次登录缺 phoneCode：明确报错（无绑定必须授权手机号）")
    void firstLogin_NoPhoneCode_Rejects() {
        when(wechatService.bminiCode2Session("wx-login-code-1"))
                .thenReturn(Code2SessionWith("openid-bmini-001"));
        when(userIdentityMapper.selectOne(any(Wrapper.class))).thenReturn(null);

        BminiLoginRequest noPhone = new BminiLoginRequest();
        noPhone.setCode("wx-login-code-1");

        assertThatThrownBy(() -> authService.bminiLogin(noPhone, mock(HttpServletResponse.class)))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("手机号");
    }

    // ======================== BM-002 二次登录（已绑定） ========================

    @Test
    @DisplayName("二次登录：openid 已绑定 bmini_app → 直接签发，无需 phoneCode (BM-002)")
    void secondLogin_AlreadyBound_NoPhoneCodeNeeded() {
        // Given: code 换 openid 后命中既有绑定
        when(wechatService.bminiCode2Session("wx-login-code-2"))
                .thenReturn(Code2SessionWith("openid-bmini-001"));

        UserIdentity existing = UserIdentity.builder()
                .id("identity-1")
                .tenantId(1L)
                .userId("emp-001")
                .identityType("bmini_app")
                .appId("bmini-app-id")
                .openid("openid-bmini-001")
                .build();
        when(userIdentityMapper.selectOne(any(Wrapper.class))).thenReturn(existing);
        when(userMapper.selectById("emp-001")).thenReturn(employee);

        when(userService.getUserRoles(employee)).thenReturn(List.of("operator"));
        when(roleService.getUserPermissions("emp-001")).thenReturn(List.of("dashboard:view"));
        when(jwtTokenProvider.generateAccessToken(eq("emp-001"), eq(1L), eq("13900000001"),
                anyList(), anyList())).thenReturn("access-token-bmini-2");
        when(jwtTokenProvider.generateRefreshToken("emp-001", 1L)).thenReturn("refresh-token-2");
        when(jwtTokenProvider.getAccessTokenExpiration()).thenReturn(7200L);
        when(tenantMapper.selectById(1L)).thenReturn(Tenant.builder().name("词元通达").build());

        // 二次登录请求：只有 wx.login code，不带 phoneCode
        BminiLoginRequest secondRequest = new BminiLoginRequest();
        secondRequest.setCode("wx-login-code-2");

        HttpServletResponse response = mock(HttpServletResponse.class);

        // When
        LoginResponse result = authService.bminiLogin(secondRequest, response);

        // Then: 登录成功且不触发换号/绑新 identity
        assertThat(result.getAccessToken()).isEqualTo("access-token-bmini-2");
        assertThat(result.getUser().getId()).isEqualTo("emp-001");
        verify(wechatService, never()).bminiGetPhoneNumber(anyString());
        verify(userIdentityMapper, never()).insert(any(UserIdentity.class));
    }

    // ======================== BM-003 未匹配员工 → 拒绝且不建号 ========================

    @Test
    @DisplayName("手机号未匹配员工：拒绝登录且不建号、不落 identity (BM-003)")
    void phone_NoEmployeeMatch_RejectsWithoutAutoCreate() {
        when(wechatService.bminiCode2Session("wx-login-code-1"))
                .thenReturn(Code2SessionWith("openid-bmini-001"));
        when(userIdentityMapper.selectOne(any(Wrapper.class))).thenReturn(null);

        WechatService.PhoneNumberResult phone = new WechatService.PhoneNumberResult();
        phone.setPurePhoneNumber("13800009999"); // 无员工账号
        when(wechatService.bminiGetPhoneNumber("phone-auth-code-1")).thenReturn(phone);
        when(userMapper.selectActiveEmployeesByPhoneIgnoreTenant("13800009999"))
                .thenReturn(Collections.emptyList());

        HttpServletResponse response = mock(HttpServletResponse.class);

        // When/Then: 明确业务错误，且绝不写库
        assertThatThrownBy(() -> authService.bminiLogin(firstLoginRequest, response))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("未匹配员工");
        verify(userIdentityMapper, never()).insert(any(UserIdentity.class));
        verify(userMapper, never()).insert(any(User.class));
        verify(jwtTokenProvider, never()).generateAccessToken(anyString(), any(), anyString(), anyList());
    }

    @Test
    @DisplayName("手机号仅匹配 customer 角色：同样拒绝（员工专属门禁）(BM-003)")
    void phone_OnlyCustomer_Rejects() {
        when(wechatService.bminiCode2Session("wx-login-code-1"))
                .thenReturn(Code2SessionWith("openid-bmini-001"));
        when(userIdentityMapper.selectOne(any(Wrapper.class))).thenReturn(null);

        WechatService.PhoneNumberResult phone = new WechatService.PhoneNumberResult();
        phone.setPurePhoneNumber("13800008888");
        when(wechatService.bminiGetPhoneNumber("phone-auth-code-1")).thenReturn(phone);
        // 只有 customer 角色的账号
        when(userMapper.selectActiveEmployeesByPhoneIgnoreTenant("13800008888"))
                .thenReturn(Collections.emptyList());

        assertThatThrownBy(() -> authService.bminiLogin(firstLoginRequest, mock(HttpServletResponse.class)))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("未匹配员工");
        verify(userIdentityMapper, never()).insert(any(UserIdentity.class));
    }

    // ======================== helpers ========================

    private WechatService.Code2SessionResult Code2SessionWith(String openid) {
        WechatService.Code2SessionResult session = new WechatService.Code2SessionResult();
        session.setOpenid(openid);
        return session;
    }
}