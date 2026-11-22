package com.migao.admin.service;

import lombok.extern.slf4j.Slf4j;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.util.StringUtils;

import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.TimeUnit;

/**
 * 微信小程序 access_token 的**跨实例共享**缓存（集群就绪审计 P0-1，issue #9018）。
 *
 * <p><b>治的形态</b>：token 原先只缓存在 {@link WechatService} 的**进程内字段**里
 * （注释原文「进程内缓存（单实例足够）」）。微信侧对一个 appid 只维持一把有效调用凭证 ⇒
 * 多实例下实例 A 刷新后，实例 B 手里那把**立即作废**，而 B 仍按自己算的 TTL 继续用
 * （最长约 2 小时）⇒ 现场表现是「一半流量间歇性登录 / 换手机号失败（40001）」，
 * 而且**没有任何读数会先变红**。</p>
 *
 * <p><b>三层结构</b></p>
 * <ol>
 *   <li><b>本地短缓存</b>（{@link #LOCAL_TTL_SECONDS} = 60s，只为省 Redis 往返）：<b>不是权威</b>，
 *       TTL 必须**远小于**真实有效期（7200s）—— 别的实例刷新后，本地最多 60s 就跟上。</li>
 *   <li><b>Redis 共享 token</b>（权威）：key = {@code wechat:access_token:{appid}}（按 appid 区分渠道），
 *       TTL = {@code expires_in - 300}，到点由微信侧语义驱动重取，本进程不自己算「还剩多久」。</li>
 *   <li><b>刷新串行化</b>：{@code SET NX EX} 抢锁 ⇒ 只有**一个**实例真正去微信换；
 *       抢不到锁的实例**短轮询**共享 token（有上限），超时回落到「直接用本地旧 token 试」并记 WARN ——
 *       **不要**各自都去刷（那正是互踢本身）。</li>
 * </ol>
 *
 * <p><b>失效自愈</b>：微信回 {@code 40001 / 42001}（凭证失效）⇒ {@link #invalidate} 清本地短缓存；
 * 若共享存储里那把**就是**失效的这把，一并删掉（否则重取会拿回同一把坏 token）⇒ 下一次
 * {@link #obtain} 必然经锁重新换一把**新** token。</p>
 *
 * <p><b>降级</b>：Redis 未接线 / 连接失败 ⇒ 退回**原进程内行为**（WARN + 60s 静默期内不再试共享存储），
 * 绝不让「Redis 故障」升级成「登录失败」。</p>
 *
 * <p>本类不直接发 HTTP：真正去微信换 token 的动作由 {@link Refresher} 注入（{@link WechatService}
 * 提供），这样多实例 / 降级 / 失效自愈都能离线判（见
 * {@code WechatServiceAccessTokenClusterTest}）。</p>
 */
@Slf4j
class WechatAccessTokenProvider {

    /** 共享 token / 刷新锁的 key 前缀（按 appid 区分，C 端 mini 与 B 端 bmini 互不污染） */
    static final String TOKEN_KEY_PREFIX = "wechat:access_token:";
    static final String LOCK_KEY_PREFIX = "wechat:access_token:lock:";

    /** 微信侧真实有效期默认 7200s；提前 300s 视为过期（沿用原实现口径） */
    static final long DEFAULT_EXPIRES_IN_SECONDS = 7200L;
    static final long REFRESH_AHEAD_SECONDS = 300L;

    /** 本地短缓存上限：**必须显著小于**真实有效期 —— 别的实例刷新后本地很快就跟上 */
    static final long LOCAL_TTL_SECONDS = 60L;

    /** 刷新锁 TTL：覆盖一次 token 拉取；进程崩溃也不会把锁永久占住（到期自动释放） */
    static final long LOCK_TTL_SECONDS = 15L;

    /** Redis 故障后的静默期：期间直接走进程内降级，不逐次重试（否则每条请求都吃一次连接超时） */
    static final long REDIS_RETRY_COOLDOWN_MILLIS = 60_000L;

    /** 本地短缓存 TTL / 抢不到锁时的轮询参数（包级可见：判据可收窄到毫秒级，不必真等秒级） */
    long localTtlSeconds = LOCAL_TTL_SECONDS;
    long pollIntervalMillis = 100L;
    long pollTimeoutMillis = 3_000L;

    /** 一次成功刷新拿到的凭证 */
    record Token(String value, long expiresInSeconds) {
    }

    /** 真正去微信换 token 的动作（由 {@link WechatService} 注入） */
    interface Refresher {
        Token refresh(String appId, String appSecret, String channelLabel);
    }

    /** {@code null} ⇒ 共享存储未接线（单机 / 本地开发 / 判据注入），直接走进程内降级 */
    private final StringRedisTemplate redis;
    private final Refresher refresher;
    private final Map<String, LocalToken> localCache = new ConcurrentHashMap<>();
    private final Map<String, Object> localLocks = new ConcurrentHashMap<>();
    /** 到此时刻前不再碰 Redis（0 = 可用） */
    private volatile long redisSuspendedUntil;

    private record LocalToken(String value, long expiresAtMillis) {
    }

    WechatAccessTokenProvider(StringRedisTemplate redis, Refresher refresher) {
        this.redis = redis;
        this.refresher = refresher;
    }

    /**
     * 取一把可用的 access_token（多实例共享）。
     *
     * @return 可直接拼进微信接口 URL 的 token
     */
    String obtain(String appId, String appSecret, String channelLabel) {
        LocalToken local = freshLocal(appId);
        if (local != null) {
            return local.value();
        }
        if (!redisUsable()) {
            return obtainInProcess(appId, appSecret, channelLabel, "共享存储未接线");
        }

        String tokenKey = TOKEN_KEY_PREFIX + appId;
        String shared = sharedToken(tokenKey);
        if (StringUtils.hasText(shared)) {
            cacheLocally(appId, shared, localTtlSeconds);
            return shared;
        }
        if (!redisUsable()) {
            // 刚才那次读把 Redis 判死了 ⇒ 立刻降级，不要在故障 Redis 上排队
            return obtainInProcess(appId, appSecret, channelLabel, "共享存储读取失败");
        }

        String lockKey = LOCK_KEY_PREFIX + appId;
        if (tryLock(lockKey)) {
            try {
                shared = sharedToken(tokenKey); // 双检：抢锁期间别的实例可能刚写好
                if (StringUtils.hasText(shared)) {
                    cacheLocally(appId, shared, localTtlSeconds);
                    return shared;
                }
                Token fresh = refresher.refresh(appId, appSecret, channelLabel);
                storeShared(tokenKey, fresh);
                cacheLocally(appId, fresh.value(), localTtlSeconds);
                return fresh.value();
            } finally {
                unlock(lockKey);
            }
        }
        if (!redisUsable()) {
            return obtainInProcess(appId, appSecret, channelLabel, "共享存储加锁失败");
        }

        // 别人正在刷新 ⇒ 短轮询等新 token（有上限），不要各自都去刷
        String polled = pollSharedToken(tokenKey);
        if (StringUtils.hasText(polled)) {
            cacheLocally(appId, polled, localTtlSeconds);
            return polled;
        }
        LocalToken stale = localCache.get(appId);
        if (stale != null) {
            log.warn("微信 access_token 刷新锁被占用且 {}ms 内未等到新 token（appId={}，{}渠道），"
                            + "回落到本地旧 token 直接尝试；若它已被微信作废，会由 40001 自愈重取",
                    pollTimeoutMillis, appId, channelLabel);
            return stale.value();
        }
        // 冷启动撞锁：连旧 token 都没有 ⇒ 宁可多刷一次，也不让登录失败
        log.warn("微信 access_token 刷新锁被占用且本地无旧 token（appId={}，{}渠道）⇒ 降级自行刷新一次",
                appId, channelLabel);
        Token fresh = refresher.refresh(appId, appSecret, channelLabel);
        storeShared(tokenKey, fresh);
        cacheLocally(appId, fresh.value(), localTtlSeconds);
        return fresh.value();
    }

    /**
     * 微信回 {@code 40001 / 42001}（凭证失效）后调用：清本地短缓存，并从共享存储重取。
     *
     * <p>关键细节：**只有当共享存储里那把就是刚刚失效的这把时才删**。否则（共享存储里已经是
     * 别的实例刚换好的新 token）删掉它等于把好凭证也扔了 —— 那会凭空制造一次多余刷新。</p>
     */
    void invalidate(String appId, String failedToken) {
        localCache.remove(appId);
        if (!redisUsable()) {
            return;
        }
        String tokenKey = TOKEN_KEY_PREFIX + appId;
        try {
            if (failedToken != null && failedToken.equals(redis.opsForValue().get(tokenKey))) {
                redis.delete(tokenKey);
                log.info("微信 access_token 已失效（40001/42001）：删除共享存储里的坏 token（appId={}）", appId);
            }
        } catch (RuntimeException e) {
            suspendRedis("失效清理", e);
        }
    }

    // ============================ 进程内降级（= 修复前的行为，但不能让登录失败） ============================

    private String obtainInProcess(String appId, String appSecret, String channelLabel, String reason) {
        LocalToken local = freshLocal(appId);
        if (local != null) {
            return local.value();
        }
        Object lock = localLocks.computeIfAbsent(appId, key -> new Object());
        synchronized (lock) {
            local = freshLocal(appId);
            if (local != null) {
                return local.value();
            }
            log.warn("微信 access_token 共享存储不可用（{}），降级为进程内缓存（appId={}，{}渠道）："
                            + "多实例下 token 仍可能各刷各的（最长 {}s 后才会发现作废），登录本身不受影响",
                    reason, appId, channelLabel, REDIS_RETRY_COOLDOWN_MILLIS / 1000);
            Token fresh = refresher.refresh(appId, appSecret, channelLabel);
            cacheLocally(appId, fresh.value(), refreshTtlSeconds(fresh.expiresInSeconds()));
            return fresh.value();
        }
    }

    // ============================ 共享存储读写（任何异常都不许冒泡成登录失败） ============================

    private String sharedToken(String tokenKey) {
        try {
            return redis.opsForValue().get(tokenKey);
        } catch (RuntimeException e) {
            suspendRedis("读取", e);
            return null;
        }
    }

    private void storeShared(String tokenKey, Token token) {
        try {
            redis.opsForValue().set(tokenKey, token.value(),
                    refreshTtlSeconds(token.expiresInSeconds()), TimeUnit.SECONDS);
        } catch (RuntimeException e) {
            // 共享写失败只影响别的实例（它们会重试），本次登录照常
            suspendRedis("写入", e);
        }
    }

    private boolean tryLock(String lockKey) {
        try {
            return Boolean.TRUE.equals(redis.opsForValue().setIfAbsent(
                    lockKey, UUID.randomUUID().toString(), LOCK_TTL_SECONDS, TimeUnit.SECONDS));
        } catch (RuntimeException e) {
            suspendRedis("加锁", e);
            return false;
        }
    }

    /**
     * 释放刷新锁（无条件 DEL）。
     *
     * <p>不额外用 Lua 做「值比对再删」：锁 TTL 只有 {@link #LOCK_TTL_SECONDS}s，远大于一次 token
     * 拉取；即便极端超时后误删了别人刚拿到的锁，后果也只是**多刷一次**（换出来的 token 仍写回
     * 共享存储，全实例读的是同一把），不会退回「每实例各刷各的」形态。</p>
     */
    private void unlock(String lockKey) {
        if (!redisUsable()) {
            return;
        }
        try {
            redis.delete(lockKey);
        } catch (RuntimeException e) {
            suspendRedis("解锁", e); // 锁会由 TTL 自动过期，不影响正确性
        }
    }

    private String pollSharedToken(String tokenKey) {
        long deadline = System.currentTimeMillis() + pollTimeoutMillis;
        while (System.currentTimeMillis() < deadline) {
            try {
                Thread.sleep(Math.max(1L, pollIntervalMillis));
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                return null;
            }
            if (!redisUsable()) {
                return null;
            }
            String token = sharedToken(tokenKey);
            if (StringUtils.hasText(token)) {
                return token;
            }
        }
        return null;
    }

    private boolean redisUsable() {
        return redis != null && System.currentTimeMillis() >= redisSuspendedUntil;
    }

    private void suspendRedis(String action, RuntimeException cause) {
        redisSuspendedUntil = System.currentTimeMillis() + REDIS_RETRY_COOLDOWN_MILLIS;
        log.warn("⚠️ 微信 access_token 共享存储（Redis）{}失败 ⇒ 降级为进程内缓存 {}s（期间不再重试共享存储）：{}。"
                        + "影响：多实例下 token 可能再次各刷各的（每实例最长 {}s 后才会发现作废），登录不受影响；"
                        + "{}s 后自动重试共享存储",
                action, REDIS_RETRY_COOLDOWN_MILLIS / 1000, cause.getMessage(),
                localTtlSeconds, REDIS_RETRY_COOLDOWN_MILLIS / 1000);
    }

    // ============================ 本地短缓存 ============================

    private LocalToken freshLocal(String appId) {
        LocalToken local = localCache.get(appId);
        if (local == null || System.currentTimeMillis() >= local.expiresAtMillis()) {
            // 过期条目**不删**：抢不到刷新锁且等不到新 token 时，它就是「旧 token 直接试」的兜底
            // （若它已被微信作废，下一次 40001 会把本地清空并重取）
            return null;
        }
        return local;
    }

    private void cacheLocally(String appId, String token, long ttlSeconds) {
        localCache.put(appId, new LocalToken(token,
                System.currentTimeMillis() + Math.max(0L, ttlSeconds) * 1000L));
    }

    /** 共享存储 / 进程内缓存共用的有效期口径：expires_in 提前 300s，最短 60s */
    static long refreshTtlSeconds(long expiresInSeconds) {
        long expiresIn = expiresInSeconds > 0 ? expiresInSeconds : DEFAULT_EXPIRES_IN_SECONDS;
        return Math.max(expiresIn - REFRESH_AHEAD_SECONDS, LOCAL_TTL_SECONDS);
    }
}
