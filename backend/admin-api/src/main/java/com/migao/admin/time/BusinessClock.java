package com.migao.admin.time;

import org.springframework.stereotype.Component;

import java.time.Clock;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.time.OffsetDateTime;
import java.time.ZoneId;

/**
 * 业务时钟（issue #3802）：全仓「业务今天 / 业务现在」的**唯一来源**，口径固定 {@code Asia/Shanghai}。
 *
 * <p>缺陷形态（修复前）：生产侧 18 处无参 {@code LocalDate.now()} 取的是 <b>JVM 默认时区</b>，
 * 而简报/看板另写 {@code ZoneId.of("Asia/Shanghai")} —— 同一时刻两套口径在 UTC 16:00
 * （= +08 次日 00:00）这个边界前后**差一天**。更差的拼写是
 * {@code LocalDate.now().atStartOfDay().offset(ZoneOffset.ofHours(8))}：取的是 <b>UTC 日</b>边界、
 * 只是给它贴了 +08 标签（UTC 16:00–24:00 这 8 小时里整整早一天）。</p>
 *
 * <p><b>为什么是单点而不是 per-tenant 时区</b>：2026-09-26 用户裁定「业务『今天』统一为
 * {@code Asia/Shanghai} 单点」。多租户时区**已被明确否决**，此处不再讨论。</p>
 *
 * <p><b>注入的 {@link Clock} 只用来钉「时刻」，不参与定「时区」</b>：日历计算一律用
 * {@link #BUSINESS_ZONE}（经 {@code ofInstant}），因此即使有人注入一个时区为 UTC 的时钟，
 * 业务日期依旧是 +08 口径 —— 时区单点化不能靠「注入方记得传对时区」来保证。
 * 测试用 {@code Clock.fixed(instant, ZoneOffset.UTC)} 即可钉住时刻。</p>
 */
@Component
public class BusinessClock {

    /**
     * 业务时区（{@code Asia/Shanghai}）：**全仓唯一硬编码点**（issue #3802）。
     * 守卫见 {@code BusinessClockSourceGuardTest} —— {@code src/main} 下任何其它文件出现
     * {@code ZoneId.of("Asia/Shanghai")} / {@code "Asia/Shanghai"} 字面量 / 无参 now() 即判红。
     */
    public static final ZoneId BUSINESS_ZONE = ZoneId.of("Asia/Shanghai");

    private final Clock clock;

    /** 生产构造：真实业务时钟。 */
    public BusinessClock() {
        this(Clock.system(BUSINESS_ZONE));
    }

    /** 测试构造：注入钉住时刻的 {@link Clock}（只取时刻，时区恒为 {@link #BUSINESS_ZONE}）。 */
    public BusinessClock(Clock clock) {
        this.clock = clock;
    }

    /** 业务时区（单点常量，供无需时钟的调用方复用）。 */
    public ZoneId zone() {
        return BUSINESS_ZONE;
    }

    /** 业务「今天」。 */
    public LocalDate today() {
        return LocalDate.ofInstant(clock.instant(), BUSINESS_ZONE);
    }

    /** 业务「现在」（本地日期时间，不含偏移；用于 TTL / 展示串）。 */
    public LocalDateTime now() {
        return LocalDateTime.ofInstant(clock.instant(), BUSINESS_ZONE);
    }

    /** 业务「现在」（带偏移，用于与 {@code timestamptz} 比较）。 */
    public OffsetDateTime nowOffset() {
        return OffsetDateTime.ofInstant(clock.instant(), BUSINESS_ZONE);
    }

    /** 业务「现在」的墙上时间（用于「营业时段」这类只比时刻的场景）。 */
    public LocalTime time() {
        return now().toLocalTime();
    }

    /** 某业务日的 00:00:00+08:00（按业务时区规则求偏移，不是硬编码 +8）。 */
    public OffsetDateTime startOfDay(LocalDate date) {
        return date.atStartOfDay(BUSINESS_ZONE).toOffsetDateTime();
    }

    /** 业务今日 00:00:00+08:00。 */
    public OffsetDateTime startOfToday() {
        return startOfDay(today());
    }
}
