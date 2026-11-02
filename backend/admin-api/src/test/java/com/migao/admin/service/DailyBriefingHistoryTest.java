// case_ids: DA-031

package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.conditions.AbstractWrapper;
import com.baomidou.mybatisplus.core.conditions.Wrapper;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.migao.admin.entity.DailyBriefing;
import com.migao.admin.mapper.DailyBriefingMapper;
import com.migao.admin.time.BusinessClock;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import java.lang.reflect.Field;
import java.time.Clock;
import java.time.LocalDate;
import java.time.ZoneOffset;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 简报历史回溯（issue #8253）。
 *
 * <p>主判据不是「能查出东西」（那是 SQL 的事），而是三条**边界**：
 * ① `days` 必须被钳制（否则一次 10000 天能把全表读出来）；
 * ② 窗口起点必须按 {@link BusinessClock} 的业务今天算（UTC 16:00 边界前后差一天的坑，
 *    已由 issue #3802 在全仓钉死，这里不许另开一套）；
 * ③ 查不到历史 ⇒ 空列表（调用方据条数自己说「没有历史」），**不许**返回 null 让上层 NPE。
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("简报历史回溯（issue #8253）")
class DailyBriefingHistoryTest {

    @Mock
    private DailyBriefingMapper dailyBriefingMapper;

    @InjectMocks
    private DailyBriefingService service;

    private static final LocalDate TODAY = LocalDate.of(2026, 10, 31);

    @BeforeEach
    void setUp() {
        // `businessClock` 是字段初始化（非注入）⇒ 反射钉死，避免用例跨日抖动
        // MyBatis-Plus 的 LambdaQueryWrapper 需要先注册 TableInfo，否则报
        // 「can not find lambda cache for this entity」（同 OrderServiceTest / DailyBriefingServiceTest 做法）
        MybatisConfiguration conf = new MybatisConfiguration();
        TableInfoHelper.initTableInfo(new MapperBuilderAssistant(conf, ""), DailyBriefing.class);

        BusinessClock fixed = new BusinessClock(Clock.fixed(
                TODAY.atTime(10, 0).atZone(BusinessClock.BUSINESS_ZONE).toInstant(), ZoneOffset.UTC));
        try {
            Field field = DailyBriefingService.class.getDeclaredField("businessClock");
            field.setAccessible(true);
            field.set(service, fixed);
        } catch (ReflectiveOperationException e) {
            throw new IllegalStateException("钉不住业务时钟，用例不可信", e);
        }
    }

    @SuppressWarnings("unchecked")
    private AbstractWrapper<DailyBriefing, ?, ?> captureWrapper() {
        ArgumentCaptor<Wrapper<DailyBriefing>> captor = ArgumentCaptor.forClass(Wrapper.class);
        verify(dailyBriefingMapper).selectList(captor.capture());
        AbstractWrapper<DailyBriefing, ?, ?> wrapper = (AbstractWrapper<DailyBriefing, ?, ?>) captor.getValue();
        // MyBatis-Plus 的取值是**懒填充**的：值在 `formatParam` 里才进 `paramNameValuePairs`，
        // 而 `formatParam` 由 `getSqlSegment()` 触发。不先调它，params 永远是空 Map（实测踩过）。
        wrapper.getSqlSegment();
        return wrapper;
    }

    @Test
    @DisplayName("默认 30 天：窗口起点 = 业务今天 - 29 天（含今天正好 30 个自然日）")
    void default_window_starts_29_days_before_business_today() {
        when(dailyBriefingMapper.selectList(any())).thenReturn(List.of());

        service.getBriefingHistory(7L, 30);

        AbstractWrapper<DailyBriefing, ?, ?> wrapper = captureWrapper();
        assertThat(wrapper.getParamNameValuePairs().values())
                .as("业务今天 = %s ⇒ 起点应为 %s", TODAY, TODAY.minusDays(29))
                .contains(TODAY.minusDays(29));
    }

    @Test
    @DisplayName("days 超过上限 ⇒ 钳到 90，不是原样透传")
    void days_are_clamped_to_the_hard_cap() {
        when(dailyBriefingMapper.selectList(any())).thenReturn(List.of());

        service.getBriefingHistory(7L, 10_000);

        AbstractWrapper<DailyBriefing, ?, ?> wrapper = captureWrapper();
        assertThat(wrapper.getSqlSegment()).contains("LIMIT " + DailyBriefingService.HISTORY_MAX_DAYS);
        assertThat(wrapper.getParamNameValuePairs().values()).contains(TODAY.minusDays(89));
    }

    @Test
    @DisplayName("days <= 0 ⇒ 至少查 1 天（不允许退化成「查全表」或空窗口）")
    void non_positive_days_degrade_to_one_day() {
        when(dailyBriefingMapper.selectList(any())).thenReturn(List.of());

        service.getBriefingHistory(7L, 0);

        AbstractWrapper<DailyBriefing, ?, ?> wrapper = captureWrapper();
        assertThat(wrapper.getSqlSegment()).contains("LIMIT 1");
        assertThat(wrapper.getParamNameValuePairs().values()).contains(TODAY);
    }

    @Test
    @DisplayName("按业务日期倒序（最新在前）—— 老板先看最近几天发生了什么")
    void rows_are_ordered_newest_first() {
        when(dailyBriefingMapper.selectList(any())).thenReturn(List.of());

        service.getBriefingHistory(7L, 7);

        assertThat(captureWrapper().getSqlSegment()).containsIgnoringCase("ORDER BY").containsIgnoringCase("DESC");
    }

    @Test
    @DisplayName("查不到历史 ⇒ 空列表（不是 null）⇒ 上层据此说「没有历史」，不把 0 条当成功")
    void empty_history_returns_empty_list_not_null() {
        when(dailyBriefingMapper.selectList(any())).thenReturn(null);

        assertThat(service.getBriefingHistory(7L, 30)).isNotNull().isEmpty();
    }
}
