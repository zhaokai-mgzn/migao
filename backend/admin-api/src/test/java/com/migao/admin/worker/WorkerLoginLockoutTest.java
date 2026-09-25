// case_ids: AU-011
package com.migao.admin.worker;

import com.migao.admin.entity.User;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.UserMapper;
import com.migao.admin.mapper.WorkerSessionMapper;
import com.migao.admin.security.LoginFailureGuard;
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
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 工人端「工号 + PIN」登录的失败计数/锁定（issue #5531）。
 *
 * <p>与员工密码登录是**同一类**「可被猜解的凭据入口」⇒ 同一实现（{@link LoginFailureGuard}）、
 * 同一阈值、同一文案。工人端是车间共用 PAD，PIN 天然较短 ⇒ 这条防护在这里更必要。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("工人登录失败计数/锁定（防在线爆破，issue #5531）")
class WorkerLoginLockoutTest {

    @InjectMocks
    private WorkerSessionService workerSessionService;

    @Mock private WorkerSessionMapper workerSessionMapper;
    @Mock private UserMapper userMapper;
    @Mock private PasswordEncoder passwordEncoder;
    @Mock private StringRedisTemplate redisTemplate;

    /** 构造占位；真守卫在 setUp 里替换（@Spy 字段初始化早于 mock 注入）。 */
    @Mock
    private LoginFailureGuard loginFailureGuard;

    private LoginFailureGuard realGuard;

    private final Map<String, String> store = new HashMap<>();
    private static final long TENANT = 20L;
    private static final String WORKER_NO = "G0001";

    @BeforeEach
    @SuppressWarnings("unchecked")
    void setUp() {
        ReflectionTestUtils.setField(workerSessionService, "idleMinutes", 60);
        store.clear();
        realGuard = new LoginFailureGuard(redisTemplate, new io.micrometer.core.instrument.simple.SimpleMeterRegistry());
        ReflectionTestUtils.setField(workerSessionService, "loginFailureGuard", realGuard);

        ValueOperations<String, String> ops = mock(ValueOperations.class);
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

        User worker = User.builder().id("w1").tenantId(TENANT).workerNo(WORKER_NO)
                .passwordHash("$2a$10$pinhash").status("active").build();
        when(userMapper.selectOne(any())).thenReturn(worker);
        when(passwordEncoder.matches(eq("2468"), anyString())).thenReturn(true);
        when(passwordEncoder.matches(eq("0000"), anyString())).thenReturn(false);
    }

    private String key() {
        return LoginFailureGuard.keyOf("worker", String.valueOf(TENANT), WORKER_NO);
    }

    private void failOnce() {
        assertThatThrownBy(() -> workerSessionService.login(TENANT, WORKER_NO, "0000", "PAD-01"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("工号或 PIN 不正确");
    }

    @Test
    @DisplayName("🔴 连续 5 次错 PIN ⇒ 第 6 次即使 PIN 正确也被拒（可行动文案）")
    void fiveFailures_thenLocked() {
        for (int i = 1; i <= LoginFailureGuard.MAX_FAILS; i++) {
            failOnce();
        }
        assertThat(store.get(key())).isEqualTo(String.valueOf(LoginFailureGuard.MAX_FAILS));
        assertThatThrownBy(() -> workerSessionService.login(TENANT, WORKER_NO, "2468", "PAD-01"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining(LoginFailureGuard.LOCKED_MESSAGE);
    }

    @Test
    @DisplayName("🔴 锁定后不再查库（mapper 调用次数停在第 5 次）")
    void whenLocked_doesNotHitDatabase() {
        for (int i = 1; i <= LoginFailureGuard.MAX_FAILS; i++) {
            failOnce();
        }
        verify(userMapper, times(LoginFailureGuard.MAX_FAILS)).selectOne(any());
        // 第 6 次：应命中锁定分支（文案不同 ⇒ 不能复用 failOnce 的「工号或 PIN 不正确」断言）
        assertThatThrownBy(() -> workerSessionService.login(TENANT, WORKER_NO, "0000", "PAD-01"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining(LoginFailureGuard.LOCKED_MESSAGE);
        verify(userMapper, times(LoginFailureGuard.MAX_FAILS)).selectOne(any());
    }

    @Test
    @DisplayName("成功登录清零 ⇒ 之前打错的次数不会累积到锁定")
    void success_clearsCounter() {
        for (int i = 1; i <= LoginFailureGuard.MAX_FAILS - 1; i++) {
            failOnce();
        }
        workerSessionService.login(TENANT, WORKER_NO, "2468", "PAD-01");
        assertThat(store.get(key())).as("成功后计数应清零").isNull();
    }

    @Test
    @DisplayName("🔴 不存在的工号同样被计数（不泄露工号是否存在）")
    void unknownWorkerNo_isAlsoCounted() {
        when(userMapper.selectOne(any())).thenReturn(null);
        for (int i = 1; i <= LoginFailureGuard.MAX_FAILS; i++) {
            assertThatThrownBy(() -> workerSessionService.login(TENANT, "G9999", "0000", "PAD-01"))
                    .isInstanceOf(BusinessException.class);
        }
        assertThat(store.get(LoginFailureGuard.keyOf("worker", String.valueOf(TENANT), "G9999")))
                .isEqualTo(String.valueOf(LoginFailureGuard.MAX_FAILS));
        verify(workerSessionMapper, never()).insert(any(com.migao.admin.entity.WorkerSession.class));
    }
}
