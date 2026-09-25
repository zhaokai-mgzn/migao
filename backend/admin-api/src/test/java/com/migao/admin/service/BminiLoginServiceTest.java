// case_ids: BM-001, BM-002, BM-003
package com.migao.admin.service;

import com.migao.admin.dto.BminiLoginRequest;
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
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.test.util.ReflectionTestUtils;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyBoolean;
import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;

/**
 * B 端小程序登录（{@code POST /api/auth/bmini/login}）—— issue #5485 **收口后的新契约**。
 *
 * <p>🔴 本文件在 #5485 里被**整体改写**（旧内容是 #2977 的「微信手机号匹配员工 → 绑定 openid →
 * 签发员工 JWT」三条用例）。改判依据：员工登录统一为「用户名@企业编码 + 密码」，
 * 微信手机号匹配员工那条路径**已删除**（它按手机号跨租户匹配账号，正是本次要消灭的形态）。</p>
 *
 * <p>新真值（沿用 #375「密码登录已禁用」的同款范式：**接口保留、抛 AUTH_FAILED + 引导文案**）：
 * <ul>
 *   <li><b>BM-001</b> 首次登录（带 phoneCode）⇒ 明确拒绝，**不换号、不建号、不落 identity、不发 token**；</li>
 *   <li><b>BM-002</b> 二次登录（openid 已绑定）⇒ 同样拒绝（「免手机号授权直接登录」已不存在）；</li>
 *   <li><b>BM-003</b> 「手机号未匹配员工」这一旧语义已退场：拒绝理由与匹配结果无关，
 *       且**没有任何手机号匹配查询**发生（方法本身已从 UserMapper 删除）。</li>
 * </ul>
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("B 端小程序登录：已废弃并明确拒绝")
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
    private TenantAiConfigMapper tenantAiConfigMapper;
    @Mock
    private CustomerService customerService;

    /** 登录失败计数（issue #5531）：本类不测它 ⇒ 用 mock（默认未锁定 ⇒ 既有行为不变）。 */
    @Mock
    private LoginFailureGuard loginFailureGuard;

    private BminiLoginRequest firstLoginRequest;

    @BeforeEach
    void setUp() {
        ReflectionTestUtils.setField(authService, "cookieName", "access_token");
        ReflectionTestUtils.setField(authService, "cookieDomain", "");
        ReflectionTestUtils.setField(authService, "cookiePath", "/");
        ReflectionTestUtils.setField(authService, "cookieSecure", true);
        ReflectionTestUtils.setField(authService, "cookieHttpOnly", true);
        ReflectionTestUtils.setField(authService, "cookieSameSite", "strict");

        firstLoginRequest = new BminiLoginRequest();
        firstLoginRequest.setCode("wx-login-code");
        firstLoginRequest.setPhoneCode("wx-phone-code");
    }

    private void assertRejectedWithGuidance(BminiLoginRequest request) {
        assertThatThrownBy(() -> authService.bminiLogin(request, mock(HttpServletResponse.class)))
                .isInstanceOf(BusinessException.class)
                .hasFieldOrPropertyWithValue("code", "AUTH_FAILED")
                .hasFieldOrPropertyWithValue("httpStatus", 401)
                .hasMessageContaining("已禁用")
                .hasMessageContaining("员工登录")
                .hasMessageContaining("用户名@企业编码");
    }

    @Test
    @DisplayName("BM-001 首次登录（带 phoneCode）⇒ 明确拒绝；不换号、不建号、不落 identity、不发 token")
    void firstLogin_rejected_noSideEffects() {
        assertRejectedWithGuidance(firstLoginRequest);

        // 「换号匹配员工」整段已退场：一次微信调用都不该发生
        verifyNoInteractions(wechatService);
        verifyNoInteractions(userIdentityMapper);
        verify(userMapper, never()).insert(any(com.migao.admin.entity.User.class));
        verify(jwtTokenProvider, never()).generateAccessToken(
                anyString(), any(), anyString(), anyList(), anyList(), anyBoolean());
        verify(jwtTokenProvider, never()).generateRefreshToken(anyString(), any());
    }

    @Test
    @DisplayName("BM-002 二次登录（无 phoneCode / openid 已绑定）⇒ 同样拒绝，不再有「免授权直接登录」")
    void secondLogin_rejected_too() {
        BminiLoginRequest second = new BminiLoginRequest();
        second.setCode("wx-login-code");

        assertRejectedWithGuidance(second);

        verify(userIdentityMapper, never()).selectOne(any());
        verify(jwtTokenProvider, never()).generateAccessToken(
                anyString(), any(), anyString(), anyList(), anyList(), anyBoolean());
    }

    @Test
    @DisplayName("BM-003 「手机号未匹配员工」旧语义已退场：拒绝理由与匹配结果无关，且不存在手机号匹配查询")
    void phoneMatchingPath_isGone() throws Exception {
        // 无论是否传 phoneCode、无论库里有没有员工，出口都是同一句「已废弃」
        assertRejectedWithGuidance(firstLoginRequest);

        // 该查询方法本身已从 UserMapper 删除（留在那里 = 跨租户按手机号找账号的入口又回来了）
        assertThatThrownBy(() -> UserMapper.class.getMethod(
                "selectActiveEmployeesByPhoneIgnoreTenant", String.class))
                .as("按手机号跨租户匹配员工的方法必须已删除（issue #5485 收口）")
                .isInstanceOf(NoSuchMethodException.class);

        // 而新的员工定位方式只有一处：带 tenant_id 的用户名查询
        assertThat(UserMapper.class.getMethod("selectActiveByTenantAndUsername", Long.class, String.class))
                .as("员工登录的唯一查找入口必须是租户内的用户名查询")
                .isNotNull();
    }
}