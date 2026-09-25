package com.migao.admin.security;

import com.migao.admin.exception.BusinessException;
import io.micrometer.core.instrument.MeterRegistry;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;

import java.time.Duration;
import java.util.concurrent.TimeUnit;

/**
 * 登录失败计数（在线爆破防护，issue #5531）。
 *
 * <p><b>为什么要有它</b>：本单把员工从「手机号 + 短信」迁到「用户名@企业编码 + 密码」后，
 * 攻击面从「需拿到手机号且受短信频控」变成「知道用户名 + 企业编码即可无限次猜测」——
 * 而短信侧本来就有 {@code SmsService.MAX_VERIFY_FAILS = 5}。同一认证链上两条路防护强度必须对齐，
 * 否则弱的那条就是实际入口（issue #5531 的实测读数：连续 6 次错密码恒 401、无计数、无锁定）。</p>
 *
 * <p><b>范式同源</b>：键前缀 {@code login:fail:} 与 {@code SmsService} 的 {@code sms:fail:} 同构
 * （increment + 首次 expire + 成功 delete）。刻意**不**把两处合并成一个类：短信侧还耦合验证码 TTL /
 * 一次性消费 / 每日上限等语义，合并会牵动既有行为；这里只做「防爆破计数」这一件事。</p>
 *
 * <p><b>计的是「被尝试的标识」，不是「已匹配到的账号」</b>：计数键由调用方用**规整后的输入**构造
 * （如 企业编码 + 用户名），**与账号是否存在无关** ⇒ 「本来就不存在的用户名」同样会被计数与锁定
 * ⇒ 锁定文案**不泄露账号是否存在**（反枚举不变式 I1 的一部分）。调用方不得改成「查到用户后才计数」。</p>
 *
 * <p><b>Redis 不可用时 fail-closed</b>（与 {@code AuthService.isTokenBlacklisted} 的 #4866 口径一致）：
 * 抛 {@code AUTH_UNAVAILABLE}(503) 并打 {@link #UNAVAILABLE_KEYWORD} + 计数 {@link #UNAVAILABLE_METRIC}
 * —— 不许「异常 ⇒ 放行」，那会让 Redis 一挂就等于关掉防护而无人知晓。
 * 降级方向已登记在 {@code tests/unit_ci_workflows/declared_effective_registry.json} 的
 * {@code security_degradation} 台账（改方向 / 去掉读数 ⇒ 判据必红）。</p>
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class LoginFailureGuard {

    /** Redis 键前缀（与 {@code SmsService} 的 {@code sms:fail:} 同范式、互不干扰）。 */
    public static final String KEY_PREFIX = "login:fail:";

    /** 窗口内允许的最大失败次数（与短信侧 {@code MAX_VERIFY_FAILS} 对齐）。 */
    public static final int MAX_FAILS = 5;

    /** 计数窗口（首次失败起算；期间每次失败都会刷新 TTL，即"持续尝试则持续锁"）。 */
    public static final Duration WINDOW = Duration.ofMinutes(5);

    /**
     * 锁定文案。**可以**与「账号或密码错误」不同：因为计数键是「被尝试的标识」而非「已存在的账号」，
     * 任何标识（含不存在的）都会被同样锁定 ⇒ 这句话不泄露账号是否存在，同时给真人一个可行动的出口
     * （否则他会一直重试、一直续锁）。
     */
    public static final String LOCKED_MESSAGE = "尝试次数过多，请 5 分钟后再试";

    /** 降级读数（与 declared_effective_registry 的 security_degradation 台账同源）。 */
    public static final String UNAVAILABLE_METRIC = "migao.auth.login_guard_unavailable";
    public static final String UNAVAILABLE_KEYWORD = "LOGIN_GUARD_UNAVAILABLE";

    private final StringRedisTemplate redisTemplate;
    private final MeterRegistry meterRegistry;

    /** 构造计数键：调用方用自己的**规整后输入**拼（大小写/空白差异必须共享同一计数）。 */
    public static String keyOf(String scope, String... parts) {
        StringBuilder sb = new StringBuilder(KEY_PREFIX).append(scope);
        for (String p : parts) {
            sb.append(':').append(p == null ? "-" : p);
        }
        return sb.toString();
    }

    /** 是否已达阈值（达阈值 ⇒ 调用方直接拒绝，不必再查库）。 */
    public boolean isLocked(String key) {
        try {
            String v = redisTemplate.opsForValue().get(key);
            return v != null && Integer.parseInt(v) >= MAX_FAILS;
        } catch (Exception e) {
            throw unavailable(e, "读");
        }
    }

    /** 记一次失败（首次置 TTL；后续失败刷新 TTL ⇒ 持续尝试持续锁）。 */
    public void recordFailure(String key) {
        try {
            Long n = redisTemplate.opsForValue().increment(key);
            if (n != null && n == 1L) {
                redisTemplate.expire(key, WINDOW.toSeconds(), TimeUnit.SECONDS);
            } else {
                redisTemplate.expire(key, WINDOW.toSeconds(), TimeUnit.SECONDS);
            }
            if (n != null && n == MAX_FAILS) {
                log.warn("[登录防护] 失败达阈值，该标识进入锁定窗口: key={}", key);
            }
        } catch (Exception e) {
            throw unavailable(e, "写");
        }
    }

    /** 登录成功 ⇒ 清零（否则"成功前打错几次"会累积到锁定）。 */
    public void clear(String key) {
        try {
            redisTemplate.delete(key);
        } catch (Exception e) {
            throw unavailable(e, "清");
        }
    }

    private BusinessException unavailable(Exception cause, String phase) {
        log.error("{}（登录失败计数**不可执行**（{}），按 fail-closed 拒绝本次登录）: {}",
                UNAVAILABLE_KEYWORD, phase, cause.getMessage());
        meterRegistry.counter(UNAVAILABLE_METRIC).increment();
        return new BusinessException("AUTH_UNAVAILABLE",
                "登录防护不可用（Redis 异常），已按 fail-closed 拒绝", 503);
    }
}
