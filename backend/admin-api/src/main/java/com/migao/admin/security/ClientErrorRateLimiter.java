package com.migao.admin.security;

import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;

/**
 * 公开错误上报端点的**进程内**限流（issue #8203 · P0-03）。
 *
 * <h3>为什么不是 Redis（与 {@code LoginFailureGuard} / {@code RegistrationService} 有意不同）</h3>
 * <p>那两处的计数是**安全护栏**（防爆破 / 防刷单），Redis 挂了必须 fail-closed —— 放行等于关掉防护。
 * 本处的计数是**日志面的防洪**，而它最需要工作的时刻恰恰是「服务出故障」：</p>
 * <ul>
 *   <li>Redis 挂了、数据库挂了、后端 5xx —— 那正是前端错误量最大、也最有价值的时候；</li>
 *   <li>若走 Redis 且 fail-closed ⇒ 恰恰在故障时**丢掉全部错误上报**，可观测性归零；</li>
 *   <li>若走 Redis 且 fail-open ⇒ 多一层网络依赖换来的只是「进程重启计数不丢」，不值得。</li>
 * </ul>
 * <p>⇒ 进程内固定窗口：**实例重启清零**是可接受的（上限仍是每实例 30 条/分钟/IP）。</p>
 *
 * <h3>两面都限</h3>
 * <ul>
 *   <li><b>按 IP</b>：{@link #MAX_PER_WINDOW} 条 / 窗口；</li>
 *   <li><b>全局</b>：{@link #MAX_GLOBAL_PER_WINDOW} 条 / 窗口 —— 防「大量 IP 各报几条」把日志刷爆。</li>
 * </ul>
 *
 * <h3>边界（照实登记）</h3>
 * <ul>
 *   <li>多实例部署下每个实例各有一份额度（总量 = 实例数 × 上限）；本仓当前单机 SWAS，可接受；</li>
 *   <li>键表上限 {@link #MAX_KEYS}（超了清过期 + 丢最旧）⇒ 内存有界，不会被打成 OOM；</li>
 *   <li>窗口是**固定窗口**（不是滑动）：窗口边界处最多可通过 2 倍额度 —— 对「防洪」足够，对「计费」不够（本处不是计费）。</li>
 * </ul>
 */
@Slf4j
@Component
public class ClientErrorRateLimiter {

    /** 单 IP 每窗口允许条数。 */
    public static final int MAX_PER_WINDOW = 30;

    /** 全局每窗口允许条数（所有 IP 合计）。 */
    public static final int MAX_GLOBAL_PER_WINDOW = 600;

    /** 窗口长度（ms）。 */
    public static final long WINDOW_MILLIS = 60_000L;

    /** 键表上限（内存有界）。 */
    public static final int MAX_KEYS = 2048;

    /** key ⇒ [窗口起点, 本窗口计数]。 */
    private final Map<String, long[]> windows = new ConcurrentHashMap<>();

    private final AtomicLong globalWindowStart = new AtomicLong(0L);
    private final AtomicInteger globalCount = new AtomicInteger(0);

    /**
     * 尝试为 {@code key}（= 客户端 IP）取一个额度。
     *
     * @return {@code true} = 放行；{@code false} = 超限（调用方回 429）
     */
    public boolean tryAcquire(String key) {
        long now = System.currentTimeMillis();
        if (!acquireGlobal(now)) {
            return false;
        }
        String bucketKey = (key == null || key.isBlank()) ? "unknown" : key;
        long[] slot = windows.compute(bucketKey, (ignored, current) -> {
            if (current == null || now - current[0] >= WINDOW_MILLIS) {
                return new long[] {now, 1L};
            }
            current[1] = current[1] + 1L;
            return current;
        });
        if (windows.size() > MAX_KEYS) {
            prune(now);
        }
        return slot != null && slot[1] <= MAX_PER_WINDOW;
    }

    private boolean acquireGlobal(long now) {
        long start = globalWindowStart.get();
        if (now - start >= WINDOW_MILLIS && globalWindowStart.compareAndSet(start, now)) {
            globalCount.set(0);
        }
        return globalCount.incrementAndGet() <= MAX_GLOBAL_PER_WINDOW;
    }

    /** 清掉过期窗口；仍超上限 ⇒ 丢最旧（Map 保插入顺序）。表有界是硬要求。 */
    private void prune(long now) {
        windows.entrySet().removeIf(entry -> now - entry.getValue()[0] >= WINDOW_MILLIS);
        while (windows.size() > MAX_KEYS) {
            var oldest = windows.keySet().stream().findFirst().orElse(null);
            if (oldest == null) {
                return;
            }
            windows.remove(oldest);
        }
        log.debug("CLIENT_ERROR 限流键表已回收，当前 {} 个键", windows.size());
    }

    /** 判据用：清空全部计数（不要在业务代码里调用）。 */
    public void reset() {
        windows.clear();
        globalWindowStart.set(0L);
        globalCount.set(0);
    }
}
