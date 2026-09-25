// case_ids: AU-011
package com.migao.admin.security;

import com.migao.admin.entity.Tenant;
import com.migao.admin.entity.User;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.PlatformAdminMapper;
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
import io.micrometer.core.instrument.MeterRegistry;
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
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.TimeUnit;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 员工登录**失败计数 / 锁定**（issue #5531）。
 *
 * <p>防的形态（issue #5531 的实测读数）：连续 6 次错密码恒 401、无计数、无锁定 ⇒
 * 「用户名@企业编码 + 密码」这条可离线猜解的路**没有任何防爆破**，而同一认证链的短信侧有
 * {@code MAX_VERIFY_FAILS = 5} ⇒ 两条路防护强度不对称，弱的那条就是实际入口。</p>
 *
 * <p><b>与反枚举（I1）的相容性</b>：计数键是**被尝试的标识**（企业编码 + 规整后的用户名），
 * 与账号是否存在无关 ⇒ 「本来就不存在的用户名」同样会被计数与锁定 ⇒ 锁定文案
 * （{@code 尝试次数过多…}）**不泄露账号是否存在**。本类有一条判据专门钉这一点。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("员工登录失败计数/锁定（防在线爆破，issue #5531）")
class EmployeeLoginLockoutTest {

    @InjectMocks
    private AuthService authService;

    @Mock private UserService userService;
    @Mock private RoleService roleService;
    @Mock private WechatService wechatService;
    @Mock private SmsService smsService;
    @Mock private JwtTokenProvider jwtTokenProvider;
    @Mock private PasswordEncoder passwordEncoder;
    @Mock private UserMapper userMapper;
    @Mock private TenantMapper tenantMapper;
    @Mock private UserIdentityMapper userIdentityMapper;
    @Mock private PlatformAdminMapper platformAdminMapper;
    @Mock private TenantAiConfigMapper tenantAiConfigMapper;
    @Mock private CustomerService customerService;
    @Mock private StringRedisTemplate redisTemplate;

    /** 构造占位（@InjectMocks 需要）；真正的守卫在 setUp 里换成真实现。 */
    @Mock
    private LoginFailureGuard loginFailureGuard;

    /** 真计数逻辑 + Redis 内存假实现 ⇒ TTL/计数/清零都是真行为。 */
    private LoginFailureGuard realGuard;

    private final Map<String, String> store = new HashMap<>();

    private static final HttpServletResponse RESP = org.mockito.Mockito.mock(HttpServletResponse.class);
    private static final String TENANT_CODE = "acme";
    private static final String USERNAME = "zhangsan";

    @BeforeEach
    @SuppressWarnings("unchecked")
    void setUp() {
        ReflectionTestUtils.setField(authService, "cookieName", "access_token");
        ReflectionTestUtils.setField(authService, "cookieDomain", "");
        ReflectionTestUtils.setField(authService, "cookiePath", "/");
        ReflectionTestUtils.setField(authService, "cookieSecure", true);
        ReflectionTestUtils.setField(authService, "cookieHttpOnly", true);
        ReflectionTestUtils.setField(authService, "cookieSameSite", "strict");
        store.clear();
        // ⚠️ 必须在 mock 就绪**之后**构造真守卫：@Spy 的字段初始化早于 Mockito 注入
        //    ⇒ 那时 redisTemplate 仍是 null（实测踩过：守卫拿着 null redis）。
        realGuard = new LoginFailureGuard(redisTemplate, new SimpleMeterRegistry());
        ReflectionTestUtils.setField(authService, "loginFailureGuard", realGuard);

        ValueOperations<String, String> ops = org.mockito.Mockito.mock(ValueOperations.class);
        when(redisTemplate.opsForValue()).thenReturn(ops);
        when(ops.get(anyString())).thenAnswer(i -> store.get(i.getArgument(0, String.class)));
        when(ops.increment(anyString())).thenAnswer(i -> {
            String k = i.getArgument(0, String.class);
            long v = Long.parseLong(store.getOrDefault(k, "0")) + 1;
            store.put(k, String.valueOf(v));
            return v;
        });
        when(redisTemplate.expire(anyString(), anyLong(), any(TimeUnit.class))).thenReturn(true);
        when(redisTemplate.delete(anyString())).thenAnswer(i -> store.remove(i.getArgument(0, String.class)) != null);

        Tenant tenant = Tenant.builder().id(1L).code(TENANT_CODE).name("甲公司").status("active").build();
        User user = User.builder().id("u1").tenantId(1L).username(USERNAME).phone("13800000001")
                .passwordHash("$2a$10$hash").role("operator").status("active").mustChangePassword(false).build();
        when(tenantMapper.selectOne(any())).thenReturn(tenant);
        when(userMapper.selectActiveByTenantAndUsername(any(), anyString())).thenReturn(user);
        when(passwordEncoder.matches(eq("right-password"), anyString())).thenReturn(true);
        when(passwordEncoder.matches(eq("wrong-password"), anyString())).thenReturn(false);
        when(jwtTokenProvider.generateAccessToken(any(), any(), any(), any(), any(), anyBooleanSafe()))
                .thenReturn("access-token");
        when(jwtTokenProvider.getAccessTokenExpiration()).thenReturn(3600L);
    }

    /** {@code anyBoolean()} 的小包装（避免与业务断言混读）。 */
    private static boolean anyBooleanSafe() {
        return org.mockito.ArgumentMatchers.anyBoolean();
    }

    private String ident() {
        return USERNAME + "@" + TENANT_CODE;
    }

    private void failOnce() {
        assertThatThrownBy(() -> authService.loginByEmployee(ident(), "wrong-password", RESP))
                .isInstanceOf(BusinessException.class);
    }

    private static String key() {
        return LoginFailureGuard.keyOf("employee", TENANT_CODE, USERNAME);
    }

    @Test
    @DisplayName("🔴 连续 5 次失败 ⇒ 第 6 次即使密码正确也被拒，且文案是可行动的锁定文案")
    void fiveFailures_thenLocked() {
        for (int i = 1; i <= LoginFailureGuard.MAX_FAILS; i++) {
            failOnce();
            assertThat(store.get(key())).as("第 %d 次失败后应已计数", i).isEqualTo(String.valueOf(i));
        }
        assertThatThrownBy(() -> authService.loginByEmployee(ident(), "right-password", RESP))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining(LoginFailureGuard.LOCKED_MESSAGE);
    }

    @Test
    @DisplayName("🔴 锁定后**不再查库**（判据：mapper 调用次数停在第 5 次，第 6 次为 0）")
    void whenLocked_doesNotHitDatabase() {
        for (int i = 1; i <= LoginFailureGuard.MAX_FAILS; i++) {
            failOnce();
        }
        verify(userMapper, times(LoginFailureGuard.MAX_FAILS)).selectActiveByTenantAndUsername(any(), anyString());
        failOnce();   // 第 6 次：直接命中锁定分支
        verify(userMapper, times(LoginFailureGuard.MAX_FAILS)).selectActiveByTenantAndUsername(any(), anyString());
    }

    @Test
    @DisplayName("🔴 **不存在的用户名同样被计数与锁定** ⇒ 锁定文案不泄露账号是否存在（与反枚举 I1 相容）")
    void nonexistentUsername_isAlsoCounted() {
        when(userMapper.selectActiveByTenantAndUsername(any(), anyString())).thenReturn(null);
        for (int i = 1; i <= LoginFailureGuard.MAX_FAILS; i++) {
            assertThatThrownBy(() -> authService.loginByEmployee("nobody@" + TENANT_CODE, "wrong-password", RESP))
                    .isInstanceOf(BusinessException.class)
                    .hasMessageContaining("账号或密码错误");
        }
        assertThat(store.get(LoginFailureGuard.keyOf("employee", TENANT_CODE, "nobody")))
                .as("不存在的用户名也必须被计数").isEqualTo(String.valueOf(LoginFailureGuard.MAX_FAILS));
        assertThatThrownBy(() -> authService.loginByEmployee("nobody@" + TENANT_CODE, "wrong-password", RESP))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining(LoginFailureGuard.LOCKED_MESSAGE);
        // 且：不存在的用户名与存在的用户名在**达阈值前的文案**上仍然逐字相同（反枚举面未被破坏）
        assertThat(store.get(key())).as("存在账号的计数不受影响").isNull();
    }

    @Test
    @DisplayName("🔴 大小写/空白差异共享同一计数（防「换大小写绕过计数」）")
    void caseVariantSharesCounter() {
        failOnce();   // zhangsan@acme
        assertThatThrownBy(() -> authService.loginByEmployee("ZHANGSAN@ACME", "wrong-password", RESP))
                .isInstanceOf(BusinessException.class);
        assertThat(store.get(key())).as("大小写变体应累加同一计数键").isEqualTo("2");
    }

    @Test
    @DisplayName("🔴 成功登录清零（否则「成功前打错几次」会累积到锁定）")
    void success_clearsCounter() {
        for (int i = 1; i <= LoginFailureGuard.MAX_FAILS - 1; i++) {
            failOnce();
        }
        authService.loginByEmployee(ident(), "right-password", RESP);   // 成功
        assertThat(store.get(key())).as("成功后计数应清零").isNull();
        for (int i = 1; i <= LoginFailureGuard.MAX_FAILS - 1; i++) {
            failOnce();   // 再打错 4 次仍不该锁
        }
        authService.loginByEmployee(ident(), "right-password", RESP);
    }

    @Test
    @DisplayName("窗口语义：首次失败即置 TTL（= 计数窗口），后续失败刷新 TTL")
    void failure_setsWindowTtl() {
        failOnce();
        verify(redisTemplate, times(1)).expire(eq(key()), eq(LoginFailureGuard.WINDOW.toSeconds()), eq(TimeUnit.SECONDS));
        failOnce();
        verify(redisTemplate, times(2)).expire(eq(key()), eq(LoginFailureGuard.WINDOW.toSeconds()), eq(TimeUnit.SECONDS));
    }

    @Test
    @DisplayName("🔴 Redis 不可用 ⇒ **fail-closed**（503 AUTH_UNAVAILABLE + 读数），不放行")
    void redisUnavailable_failsClosed() {
        MeterRegistry meters = new SimpleMeterRegistry();
        LoginFailureGuard guard = new LoginFailureGuard(redisTemplate, meters);
        ReflectionTestUtils.setField(authService, "loginFailureGuard", guard);
        when(redisTemplate.opsForValue()).thenThrow(new RuntimeException("redis down"));

        assertThatThrownBy(() -> authService.loginByEmployee(ident(), "right-password", RESP))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("fail-closed");
        assertThat(meters.counter(LoginFailureGuard.UNAVAILABLE_METRIC).count())
                .as("降级必须留下可观测读数（否则等于静默关掉防护）").isEqualTo(1.0);
        verify(userMapper, never()).selectActiveByTenantAndUsername(any(), anyString());
    }
}
