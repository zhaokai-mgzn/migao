// case_ids: API-025
package com.migao.admin.service;

import ch.qos.logback.classic.Level;
import ch.qos.logback.classic.Logger;
import ch.qos.logback.classic.spi.ILoggingEvent;
import ch.qos.logback.core.read.ListAppender;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.slf4j.LoggerFactory;
import org.springframework.data.redis.RedisConnectionFailureException;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.web.client.RestTemplate;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.stream.Stream;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.contains;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * 微信 {@code access_token} 的**多实例**语义（集群就绪审计 P0-1，issue #9018）。
 *
 * <p><b>治的形态</b>：token 原先只缓存在 {@link WechatService} 的进程内字段里（注释原文
 * 「进程内缓存（单实例足够）」）。微信侧对一个 appid 只维持一把有效凭证 ⇒ 多实例下实例 A
 * 刷新后，实例 B 手里那把**立即作废**，但 B 仍按自己算的 TTL 继续用（最长约 2 小时）⇒
 * 表现为「一半流量间歇性登录 / 换手机号失败（40001）」，且**没有任何读数会先变红**。</p>
 *
 * <p><b>判据（双向，只判一半会假绿）</b></p>
 * <ol>
 *   <li>{@code legacyPerInstanceCache_twoInstancesRefreshTwice} —— **改前形态**：两个实例各自
 *       进程内缓存 ⇒ 供应商侧（{@code cgi-bin/token}）被调 <b>2 次</b>。这条不删，它是缺陷形态
 *       本身的回归证明（修复不得靠「删掉这条」实现）。</li>
 *   <li>{@code sharedRedis_twoInstances_refreshOnce} —— **改后形态**：两个实例共享同一个
 *       Redis ⇒ 只有抢到锁的那个真正刷新，另一个直接复用 ⇒ 供应商侧只调 <b>1 次</b>，
 *       且两边用的是**同一把** token。**修复前这条是红的**（读数 2 次）。</li>
 *   <li>{@code lockHeldByAnotherInstance_pollsAndReusesNewToken} —— 拿不到锁的实例**不来第二把**，
 *       短轮询等到别人的新 token 就复用。</li>
 *   <li>{@code errCode40001_clearsLocalCacheAndRefetchesNewToken} —— 收到 40001 后本地缓存被清、
 *       重取到**新** token（失效自愈；不再一路 40001 到自己 TTL 到期）。</li>
 *   <li>{@code redisUnavailable_degradesToInProcessWithWarn} —— Redis 挂掉 ⇒ 降级为原进程内行为
 *       （WARN），**登录不失败**。</li>
 * </ol>
 *
 * <p><b>离线</b>：不连真微信、不连真 Redis —— 微信侧用 {@link RestTemplate} mock 并**计数**，
 * Redis 侧用 {@link FakeRedis}（只实现 token 缓存用到的 4 个命令，NX 用 {@code putIfAbsent}
 * 保证原子，与 {@code SET NX PX} 同语义）。</p>
 */
@DisplayName("微信 access_token 多实例共享（集群 P0-1，issue #9018）")
class WechatAccessTokenProviderTest {

    private static final String APP_ID = "wx-cluster-appid";
    private static final String APP_SECRET = "cluster-secret";
    private static final String TOKEN_KEY = "wechat:access_token:" + APP_ID;
    private static final String LOCK_KEY = "wechat:access_token:lock:" + APP_ID;

    /** 供应商侧读数：{@code cgi-bin/token} 被真正调用的次数（跨两个实例共享） */
    private final AtomicInteger tokenEndpointCalls = new AtomicInteger();

    private ListAppender<ILoggingEvent> appender;
    private Logger providerLogger;

    @BeforeEach
    void attachAppender() {
        providerLogger = (Logger) LoggerFactory.getLogger(WechatAccessTokenProvider.class);
        appender = new ListAppender<>();
        appender.start();
        providerLogger.addAppender(appender);
    }

    @AfterEach
    void detachAppender() {
        providerLogger.detachAppender(appender);
        appender.stop();
    }

    // ============================ 判据 1：改前形态（红证的另一半） ============================

    @Test
    @DisplayName("改前形态：两实例各自进程内缓存 ⇒ 供应商侧刷新 2 次（多实例互踢的根因）")
    void legacyPerInstanceCache_twoInstancesRefreshTwice() {
        WechatService instanceA = newService();
        WechatService instanceB = newService();
        RecordingWechat wechatA = serveWechat(instanceA, "TOKEN_A");
        RecordingWechat wechatB = serveWechat(instanceB, "TOKEN_B");

        instanceA.getPhoneNumber("code-a");
        instanceB.getPhoneNumber("code-b");

        // 这就是缺陷：两个实例各刷各的，后刷的那把会把先刷的作废
        assertThat(tokenEndpointCalls.get())
                .as("改前形态的读数：两实例各刷一次 = 供应商侧 2 次")
                .isEqualTo(2);
        assertThat(wechatA.phoneUrls).hasSize(1);
        assertThat(wechatB.phoneUrls).hasSize(1);
        assertThat(wechatA.phoneUrls.get(0)).contains("TOKEN_A");
        assertThat(wechatB.phoneUrls.get(0)).contains("TOKEN_B");
    }

    // ============================ 判据 2：改后形态（修复前为红） ============================

    @Test
    @DisplayName("改后形态：两实例共享同一 Redis ⇒ 只有一个实例刷新，另一个复用（供应商侧 1 次）")
    void sharedRedis_twoInstances_refreshOnce() {
        FakeRedis redis = new FakeRedis();
        WechatService instanceA = newService();
        WechatService instanceB = newService();
        bindSharedRedis(instanceA, redis);
        bindSharedRedis(instanceB, redis);

        RecordingWechat wechatA = serveWechat(instanceA, "TOKEN_A");
        RecordingWechat wechatB = serveWechat(instanceB, "TOKEN_B");

        instanceA.getPhoneNumber("code-a");
        instanceB.getPhoneNumber("code-b");

        assertThat(tokenEndpointCalls.get())
                .as("共享 Redis 后只应有一把有效 token：供应商侧只能被调 1 次"
                        + "（修复前读数 = 2，两实例各刷一次 ⇒ 后刷的把先刷的作废）")
                .isEqualTo(1);
        assertThat(redis.values.get(TOKEN_KEY))
                .as("共享存储里必须是唯一那把 token")
                .isEqualTo("TOKEN_A");
        assertThat(wechatA.phoneUrls.get(0)).contains("TOKEN_A");
        assertThat(wechatB.phoneUrls.get(0))
                .as("后到的实例必须复用共享存储里的 token，而不是自己再刷一把")
                .contains("TOKEN_A");
    }

    @Test
    @DisplayName("共享存储口径：key 按 appid 区分、TTL = expires_in - 300（不自己算 2 小时）")
    void sharedRedis_storesTokenUnderAppIdKeyWithRefreshTtl() {
        FakeRedis redis = new FakeRedis();
        WechatService service = newService();
        bindSharedRedis(service, redis);
        serveWechat(service, "TOKEN_A");

        long before = System.currentTimeMillis();
        service.getPhoneNumber("code-a");

        long expireAt = redis.expiresAtMillis.get(TOKEN_KEY);
        assertThat(expireAt - before)
                .as("TTL 必须是 expires_in(7200) - 300 = 6900s，而不是本进程拍脑袋的 2 小时")
                .isBetween(TimeUnit.SECONDS.toMillis(6900), TimeUnit.SECONDS.toMillis(6901));
        assertThat(WechatAccessTokenProvider.refreshTtlSeconds(7200)).isEqualTo(6900);
        assertThat(WechatAccessTokenProvider.LOCAL_TTL_SECONDS)
                .as("本地短缓存必须显著小于真实有效期（7200s），否则别的实例刷新后本实例会一直用废 token")
                .isLessThanOrEqualTo(60L);
    }

    // ============================ 判据 3：拿不到锁 ⇒ 轮询复用，不来第二把 ============================

    @Test
    @DisplayName("刷新锁被别的实例持有时：本实例短轮询等到新 token 并复用，自己一次都不刷")
    void lockHeldByAnotherInstance_pollsAndReusesNewToken() throws Exception {
        FakeRedis redis = new FakeRedis();
        redis.values.put(LOCK_KEY, "another-instance"); // 别人正在刷
        AtomicInteger refreshes = new AtomicInteger();
        WechatAccessTokenProvider provider = provider(redis, refreshes);
        provider.pollIntervalMillis = 10L;
        provider.pollTimeoutMillis = 2_000L;

        Thread refresherInstance = new Thread(() -> {
            sleepQuietly(60L);
            redis.values.put(TOKEN_KEY, "TOKEN_FROM_OTHER_INSTANCE");
        });
        refresherInstance.start();
        try {
            String token = provider.obtain(APP_ID, APP_SECRET, "C 端 mini");
            assertThat(token).isEqualTo("TOKEN_FROM_OTHER_INSTANCE");
            assertThat(refreshes.get())
                    .as("拿不到锁的实例必须等别人的新 token，绝不能自己也去刷")
                    .isZero();
        } finally {
            refresherInstance.join();
        }
    }

    @Test
    @DisplayName("刷新锁被占且等不到新 token：回落本地旧 token 直接尝试（记 WARN，不刷新）")
    void lockTimeout_fallsBackToStaleLocalToken() {
        FakeRedis redis = new FakeRedis();
        redis.values.put(TOKEN_KEY, "TOKEN_STALE");
        redis.values.put(LOCK_KEY, "another-instance");
        AtomicInteger refreshes = new AtomicInteger();
        WechatAccessTokenProvider provider = provider(redis, refreshes);
        provider.localTtlSeconds = 0L; // 本地短缓存立即过期（判据收窄，生产默认 60s）
        provider.pollIntervalMillis = 10L;
        provider.pollTimeoutMillis = 100L;

        assertThat(provider.obtain(APP_ID, APP_SECRET, "C 端 mini")).isEqualTo("TOKEN_STALE");
        redis.values.remove(TOKEN_KEY); // 共享存储里那把也没了，只剩本地旧 token

        String token = provider.obtain(APP_ID, APP_SECRET, "C 端 mini");

        assertThat(token)
                .as("超时回落：直接用本地旧 token 尝试（若已作废，会由 40001 自愈重取）")
                .isEqualTo("TOKEN_STALE");
        assertThat(refreshes.get()).isZero();
        assertThat(warnMessages()).anyMatch(message -> message.contains("回落到本地旧 token"));
    }

    // ============================ 判据 4：40001 失效自愈 ============================

    @Test
    @DisplayName("换号被判定 40001：本地缓存被清 + 从共享存储重取到新 token 并重试成功")
    void errCode40001_clearsLocalCacheAndRefetchesNewToken() {
        FakeRedis redis = new FakeRedis();
        redis.values.put(TOKEN_KEY, "TOKEN_EXPIRED");
        WechatService service = newService();
        bindSharedRedis(service, redis);

        RestTemplate restTemplate = mock(RestTemplate.class);
        AtomicInteger refreshes = new AtomicInteger();
        when(restTemplate.getForEntity(contains("cgi-bin/token"), eq(String.class)))
                .thenAnswer(inv -> json("{\"access_token\":\"TOKEN_FRESH_" + refreshes.incrementAndGet()
                        + "\",\"expires_in\":7200}"));
        List<String> phoneUrls = new ArrayList<>();
        when(restTemplate.postForEntity(anyString(), any(), eq(String.class))).thenAnswer(inv -> {
            phoneUrls.add(inv.getArgument(0, String.class));
            if (phoneUrls.size() == 1) {
                return json("{\"errcode\":40001,\"errmsg\":\"invalid credential\"}");
            }
            return json("{\"errcode\":0,\"errmsg\":\"ok\",\"phone_info\":{"
                    + "\"phoneNumber\":\"+8613800138000\",\"purePhoneNumber\":\"13800138000\","
                    + "\"countryCode\":\"86\"}}");
        });
        ReflectionTestUtils.setField(service, "restTemplate", restTemplate);

        WechatService.PhoneNumberResult result = service.getPhoneNumber("code-a");

        assertThat(result.getPurePhoneNumber()).isEqualTo("13800138000");
        assertThat(phoneUrls).hasSize(2);
        assertThat(phoneUrls.get(1))
                .as("第二次必须带上重取到的**新** token，而不是继续用那把废的")
                .contains("TOKEN_FRESH_1");
        assertThat(redis.values.get(TOKEN_KEY))
                .as("共享存储里的废 token 必须被换掉，否则下一个实例还会拿到它")
                .isEqualTo("TOKEN_FRESH_1");
    }

    // ============================ 判据 5：Redis 不可用 ⇒ 降级，不许登录失败 ============================

    @Test
    @DisplayName("Redis 不可用：降级为进程内缓存并记 WARN，登录照旧成功（单机行为不变）")
    void redisUnavailable_degradesToInProcessWithWarn() {
        WechatService service = newService();
        StringRedisTemplate brokenRedis = mock(StringRedisTemplate.class);
        when(brokenRedis.opsForValue())
                .thenThrow(new RedisConnectionFailureException("redis down (test)"));
        ReflectionTestUtils.setField(service, "redisTemplate", brokenRedis);
        serveWechat(service, "TOKEN_A");

        WechatService.PhoneNumberResult result = service.getPhoneNumber("code-a");

        assertThat(result.getPurePhoneNumber())
                .as("Redis 故障绝不允许升级成登录失败")
                .isEqualTo("13800138000");
        assertThat(warnMessages()).anyMatch(message -> message.contains("降级为进程内缓存"));
        // 降级后仍按原口径缓存（expires_in - 300），不会每条请求都去刷
        service.getPhoneNumber("code-b");
        assertThat(tokenEndpointCalls.get())
                .as("降级路径也必须复用本地缓存，而不是每次登录都刷一把 token")
                .isEqualTo(1);
    }

    // ============================ 类级元守卫（同类进不来） ============================

    /**
     * 类级元守卫：主代码里**不得再出现**「进程内 access_token 缓存」字段。
     *
     * <p>只修这一处 = 没修：本缺陷能被修掉、而「在 {@code service} 包里再写一个
     * {@code private volatile String cachedAccessToken}」谁都不会红。这里把「token 的存取只能经
     * {@link WechatAccessTokenProvider} 落共享存储」钉成判据 —— 复发即红，且**不需要人工维护清单**
     * （扫的是主代码全文，不是硬编码的历史文件名）。</p>
     */
    @Test
    @DisplayName("类级元守卫：admin-api 主代码不得再有进程内 access_token 缓存字段（同类进不来）")
    void metaGuard_noProcessLocalAccessTokenCacheField() throws Exception {
        List<String> bannedFields = List.of("cachedAccessToken", "bminiCachedAccessToken",
                "accessTokenExpireAt", "bminiAccessTokenExpireAt");
        List<String> offenders = new ArrayList<>();
        try (Stream<Path> files = Files.walk(Path.of("src/main/java"))) {
            for (Path file : files.filter(path -> path.toString().endsWith(".java")).toList()) {
                for (String line : Files.readAllLines(file)) {
                    String trimmed = line.strip();
                    if (trimmed.startsWith("private") && bannedFields.stream().anyMatch(trimmed::contains)) {
                        offenders.add(file + " :: " + trimmed);
                    }
                }
            }
        }
        assertThat(offenders)
                .as("微信 access_token 只能经 WechatAccessTokenProvider 走共享存储（Redis）；"
                        + "把进程内缓存字段加回来 = 多实例互踢复发（集群 P0-1）")
                .isEmpty();
    }

    // ============================ 夹具 ============================

    /** 一台 admin-api 实例（独立进程内状态），未注入 RestTemplate / Redis */
    private static WechatService newService() {
        WechatService service = new WechatService();
        ReflectionTestUtils.setField(service, "appId", APP_ID);
        ReflectionTestUtils.setField(service, "appSecret", APP_SECRET);
        ReflectionTestUtils.setField(service, "mockEnabled", false);
        return service;
    }

    /**
     * 把共享 Redis 绑给实例。
     *
     * <p>⚠️ **修复前** {@link WechatService} 根本没有 {@code redisTemplate} 字段 ⇒ 这里走到
     * catch 分支、实例保持「进程内单例缓存」（那就是缺陷形态本身，红证正是跑在这个分支上）。
     * 修复后字段存在 ⇒ 走 Redis 共享路径。保留 try/catch 的理由：将来若有人把共享存储摘掉，
     * 判据报的是**行为读数**（供应商侧 2 次），而不是一句「Could not find field」的反射异常 —— 红得可归因。</p>
     */
    private static void bindSharedRedis(WechatService service, FakeRedis redis) {
        try {
            ReflectionTestUtils.setField(service, "redisTemplate", redis.template());
        } catch (IllegalArgumentException noSuchField) {
            System.out.println("[RED] WechatService 没有 redisTemplate 字段 ⇒ 仍是「进程内单例缓存」（缺陷形态）");
        }
    }

    private static WechatAccessTokenProvider provider(FakeRedis redis, AtomicInteger refreshes) {
        return new WechatAccessTokenProvider(redis.template(), (appId, secret, label) -> {
            refreshes.incrementAndGet();
            return new WechatAccessTokenProvider.Token("TOKEN_" + refreshes.get(), 7200L);
        });
    }

    private List<String> warnMessages() {
        return appender.list.stream()
                .filter(event -> event.getLevel() == Level.WARN)
                .map(ILoggingEvent::getFormattedMessage)
                .toList();
    }

    /** 记录换号请求的真实 URL（用于断言「用的是哪一把 token」） */
    private static final class RecordingWechat {
        final List<String> phoneUrls = new ArrayList<>();
    }

    /** 微信侧 mock：token 接口按次返回 {@code tokenValue}，换号接口成功 */
    private RecordingWechat serveWechat(WechatService service, String tokenValue) {
        RecordingWechat recording = new RecordingWechat();
        RestTemplate restTemplate = mock(RestTemplate.class);
        when(restTemplate.getForEntity(contains("cgi-bin/token"), eq(String.class))).thenAnswer(inv -> {
            tokenEndpointCalls.incrementAndGet();
            return json("{\"access_token\":\"" + tokenValue + "\",\"expires_in\":7200}");
        });
        when(restTemplate.postForEntity(anyString(), any(), eq(String.class))).thenAnswer(inv -> {
            recording.phoneUrls.add(inv.getArgument(0, String.class));
            return json("{\"errcode\":0,\"errmsg\":\"ok\",\"phone_info\":{"
                    + "\"phoneNumber\":\"+8613800138000\",\"purePhoneNumber\":\"13800138000\","
                    + "\"countryCode\":\"86\"}}");
        });
        ReflectionTestUtils.setField(service, "restTemplate", restTemplate);
        return recording;
    }

    private static ResponseEntity<String> json(String body) {
        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        return new ResponseEntity<>(body, headers, HttpStatus.OK);
    }

    private static void sleepQuietly(long millis) {
        try {
            Thread.sleep(millis);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }

    /**
     * 离线 Redis 替身：只实现本缺陷用到的四个命令
     * （{@code GET} / {@code SET ... EX} / {@code SET NX ... EX} / {@code DEL}）。
     *
     * <p>NX 用 {@code putIfAbsent} 保证原子性 —— 两个实例「同时」抢锁时只有一个能拿到，
     * 与真实 Redis 的 {@code SET NX PX} 同语义（这正是判据 2 要压的性质）。</p>
     */
    private static final class FakeRedis {
        final Map<String, String> values = new ConcurrentHashMap<>();
        /** key → 过期时刻（毫秒），供 TTL 断言 */
        final Map<String, Long> expiresAtMillis = new ConcurrentHashMap<>();

        @SuppressWarnings("unchecked")
        StringRedisTemplate template() {
            StringRedisTemplate template = mock(StringRedisTemplate.class);
            ValueOperations<String, String> ops = mock(ValueOperations.class);
            when(template.opsForValue()).thenReturn(ops);
            when(ops.get(anyString())).thenAnswer(inv -> values.get(inv.getArgument(0, String.class)));
            doAnswer(inv -> {
                String key = inv.getArgument(0);
                values.put(key, inv.getArgument(1));
                long ttl = inv.getArgument(2);
                TimeUnit unit = inv.getArgument(3);
                expiresAtMillis.put(key, System.currentTimeMillis() + unit.toMillis(ttl));
                return null;
            }).when(ops).set(anyString(), anyString(), anyLong(), any(TimeUnit.class));
            when(ops.setIfAbsent(anyString(), anyString(), anyLong(), any(TimeUnit.class)))
                    .thenAnswer(inv -> {
                        String key = inv.getArgument(0);
                        if (values.putIfAbsent(key, inv.getArgument(1)) != null) {
                            return Boolean.FALSE;
                        }
                        long ttl = inv.getArgument(2);
                        TimeUnit unit = inv.getArgument(3);
                        expiresAtMillis.put(key, System.currentTimeMillis() + unit.toMillis(ttl));
                        return Boolean.TRUE;
                    });
            when(template.delete(anyString()))
                    .thenAnswer(inv -> values.remove(inv.getArgument(0, String.class)) != null);
            return template;
        }
    }
}
