// case_ids: DA-001, DA-002, DA-004
package com.migao.admin.time;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.time.Clock;
import java.time.Instant;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.time.ZoneOffset;
import java.time.temporal.ChronoUnit;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 业务时钟单点（issue #3802）—— <b>跨日边界判据</b>。
 *
 * <p>预期值一律<b>独立硬编码</b>（UTC 字面量 + {@code +08} 日历日）—— 不拿被测时钟自己算期望，
 * 否则判据对「时区口径整体错掉」这种缺陷<b>恒绿</b>（空断言）。</p>
 *
 * <p>修复前形态（两种拼写，均在 {@code src/main} 的 18 处里）：</p>
 * <ol>
 *   <li>无参 {@code LocalDate.now()} = <b>JVM 默认时区</b>（issue #3802 记录的容器口径 = UTC）；</li>
 *   <li>{@code LocalDate.now().atStartOfDay().offset(ZoneOffset.ofHours(8))} = 取 <b>UTC 日</b>边界、
 *       只给它贴 +08 标签 —— 在 UTC 16:00–24:00（= +08 次日 00:00–08:00）里整整早一天。</li>
 * </ol>
 */
class BusinessClockTest {

    /** UTC 2026-01-15 15:59 = +08 2026-01-15 23:59（边界<b>前</b>一分钟）。 */
    private static final Instant BEFORE_MIDNIGHT = Instant.parse("2026-01-15T15:59:00Z");
    /** UTC 2026-01-15 16:01 = +08 2026-01-16 00:01（边界<b>后</b>一分钟）。 */
    private static final Instant AFTER_MIDNIGHT = Instant.parse("2026-01-15T16:01:00Z");

    /** 钉住时刻：注入的 Clock **只钉时刻**，时区故意给 UTC —— 业务时区必须是 +08（单点，不受注入方影响）。 */
    private static BusinessClock pinned(Instant instant) {
        return new BusinessClock(Clock.fixed(instant, ZoneOffset.UTC));
    }

    @Test
    @DisplayName("业务日恰好在 UTC 16:00 翻一次：15:59 仍是 01-15，16:01 已是 01-16")
    void businessDateFlipsExactlyOnceAtUtcSixteen() {
        assertThat(pinned(BEFORE_MIDNIGHT).today()).isEqualTo(LocalDate.of(2026, 1, 15));
        assertThat(pinned(AFTER_MIDNIGHT).today()).isEqualTo(LocalDate.of(2026, 1, 16));
        assertThat(ChronoUnit.DAYS.between(
                pinned(BEFORE_MIDNIGHT).today(), pinned(AFTER_MIDNIGHT).today()))
                .as("边界两侧只差一天（不是不翻、也不是翻两天）")
                .isEqualTo(1L);
    }

    @Test
    @DisplayName("业务时区单点 = Asia/Shanghai，偏移 +08:00（无夏令时）")
    void businessZoneIsShanghai() {
        assertThat(BusinessClock.BUSINESS_ZONE).isEqualTo(ZoneId.of("Asia/Shanghai"));
        assertThat(BusinessClock.BUSINESS_ZONE.getRules().getOffset(Instant.EPOCH))
                .isEqualTo(ZoneOffset.ofHours(8));
        assertThat(pinned(AFTER_MIDNIGHT).zone()).isEqualTo(BusinessClock.BUSINESS_ZONE);
    }

    @Test
    @DisplayName("业务「现在」是 +08 墙上时间（不是注入时钟的 UTC 墙上时间）")
    void businessNowUsesBusinessZoneNotClockZone() {
        assertThat(pinned(AFTER_MIDNIGHT).now().toString()).isEqualTo("2026-01-16T00:01");
        assertThat(pinned(BEFORE_MIDNIGHT).now().toString()).isEqualTo("2026-01-15T23:59");
        assertThat(pinned(AFTER_MIDNIGHT).nowOffset())
                .isEqualTo(OffsetDateTime.parse("2026-01-16T00:01:00+08:00"));
        assertThat(pinned(BEFORE_MIDNIGHT).time().toString()).isEqualTo("23:59");
    }

    @Test
    @DisplayName("业务日 00:00 = +08 零点（= UTC 前一日 16:00），不是 UTC 日零点")
    void startOfBusinessDayIsShanghaiMidnight() {
        assertThat(pinned(AFTER_MIDNIGHT).startOfToday())
                .isEqualTo(OffsetDateTime.parse("2026-01-16T00:00:00+08:00"));
        assertThat(pinned(AFTER_MIDNIGHT).startOfToday().toInstant())
                .as("+08 2026-01-16 00:00 == UTC 2026-01-15 16:00")
                .isEqualTo(Instant.parse("2026-01-15T16:00:00Z"));
        assertThat(pinned(BEFORE_MIDNIGHT).startOfToday())
                .as("边界前：业务日 01-15 的零点")
                .isEqualTo(pinned(BEFORE_MIDNIGHT).startOfDay(LocalDate.of(2026, 1, 15)))
                .isEqualTo(OffsetDateTime.parse("2026-01-15T00:00:00+08:00"));
    }

    @Test
    @DisplayName("修复前的两种拼写与业务日对照：边界前恰好相同，边界后差一天（缺陷只在 8 小时窗口内显现）")
    void legacySpellingsDisagreeWithBusinessDate() {
        // 逐字复刻修复前的生产形态，仅作对照（主代码里已无此形态，见 BusinessClockSourceGuardTest）。
        for (Instant instant : List.of(BEFORE_MIDNIGHT, AFTER_MIDNIGHT)) {
            Clock jvmDefaultUtc = Clock.fixed(instant, ZoneOffset.UTC);   // 修复前 JVM 默认时区 = UTC
            LocalDate legacyNoArgNow = LocalDate.now(jvmDefaultUtc);
            OffsetDateTime legacyUtcDayLabelledPlus8 = LocalDate.now(jvmDefaultUtc)
                    .atStartOfDay().atOffset(ZoneOffset.ofHours(8));
            BusinessClock business = pinned(instant);

            if (instant.equals(BEFORE_MIDNIGHT)) {
                assertThat(legacyNoArgNow).as("边界前：两种口径恰好同一天 —— 所以这个缺陷只在 8 小时窗口里出现")
                        .isEqualTo(business.today());
            } else {
                assertThat(legacyNoArgNow).as("边界后：无参 now()（UTC）仍是 01-15，业务日已是 01-16")
                        .isEqualTo(LocalDate.of(2026, 1, 15)).isNotEqualTo(business.today());
                assertThat(legacyUtcDayLabelledPlus8.toInstant())
                        .as("边界后：UTC 日边界贴 +08 标签 = +08 01-15 00:00，比业务日边界早 24h")
                        .isEqualTo(Instant.parse("2026-01-14T16:00:00Z"))
                        .isNotEqualTo(business.startOfToday().toInstant());
            }
        }
    }
}
