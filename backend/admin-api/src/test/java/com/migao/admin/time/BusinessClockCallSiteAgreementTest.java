// case_ids: DA-001, DA-002, DA-004
package com.migao.admin.time;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.conditions.AbstractWrapper;
import com.baomidou.mybatisplus.core.conditions.Wrapper;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.migao.admin.config.SmsConfig;
import com.migao.admin.controller.DashboardController;
import com.migao.admin.entity.AgentEmployee;
import com.migao.admin.entity.AgentSession;
import com.migao.admin.mapper.AgentEmployeeMapper;
import com.migao.admin.mapper.AgentMessageMapper;
import com.migao.admin.mapper.AgentSessionMapper;
import com.migao.admin.mapper.AfterSalesTicketMapper;
import com.migao.admin.mapper.CustomerProfileMapper;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProductMapper;
import com.migao.admin.mapper.ProductSkuMapper;
import com.migao.admin.mapper.SessionMapper;
import com.migao.admin.mapper.SessionMessageMapper;
import com.migao.admin.mapper.UserMapper;
import com.migao.admin.service.AgentEmployeeService;
import com.migao.admin.service.AgentSessionService;
import com.migao.admin.service.ProductService;
import com.migao.admin.service.SmsService;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.context.ApplicationEventPublisher;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;
import org.springframework.test.util.ReflectionTestUtils;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 跨日边界：<b>修复前互相不一致的各调用点，修复后必须给出同一个「今天」</b>（issue #3802）。
 *
 * <p>做法：把时钟钉在 UTC 15:59 / 16:01，<b>驱动真实生产方法</b>（不是复刻公式），断言它们
 * 落到同一个业务日上。期望值独立硬编码。</p>
 *
 * <p>覆盖的迁移形态（逐类代表）：</p>
 * <ul>
 *   <li>看板趋势 —— 同一方法内「SQL 窗口起点」与「日期标签」原本两种口径（无参 now() vs cst）；</li>
 *   <li>客服监控 / 员工今日统计 —— {@code LocalDate.now().atStartOfDay().offset(+08)} 的 UTC 日边界拼写；</li>
 *   <li>短信每日计数 TTL —— {@code Duration.between(LocalDateTime.now(), LocalDate.now()+1 日零点)}，
 *       两侧必须同一时区，否则 TTL 差 8 小时。</li>
 * </ul>
 *
 * <p>⚠️ <b>读 MyBatis-Plus 包装器参数的坑（实测）</b>：{@code LambdaQueryWrapper} 的参数是<b>惰性绑定</b>的
 * —— {@code ge(column, value)} 只是把一个 lambda 段挂进表达式，值要等 {@code getSqlSegment()} 被求值
 * 才落进 {@code paramNameValuePairs}（3.5.16 实测：不触发则恒为空 Map ⇒ 断言假绿）。故断言前必须先
 * 触发 SQL 段生成（代价 = 需要 {@code TableInfo}，见静态块）。</p>
 */
class BusinessClockCallSiteAgreementTest {

    private static final Instant BEFORE_MIDNIGHT = Instant.parse("2026-01-15T15:59:00Z"); // +08 01-15 23:59
    private static final Instant AFTER_MIDNIGHT = Instant.parse("2026-01-15T16:01:00Z");  // +08 01-16 00:01

    static {
        // 让 lambda 列名解析 + 惰性参数绑定可用（无 Spring/DB 的纯单测里 TableInfo 不会自动建立）
        TableInfoHelper.initTableInfo(
                new MapperBuilderAssistant(new MybatisConfiguration(), ""), AgentSession.class);
        TableInfoHelper.initTableInfo(
                new MapperBuilderAssistant(new MybatisConfiguration(), ""), AgentEmployee.class);
    }

    private static BusinessClock pinned(Instant instant) {
        return new BusinessClock(Clock.fixed(instant, ZoneOffset.UTC));
    }

    /** 包装器<b>实际绑定</b>的参数值（先触发惰性 SQL 段生成，否则恒为空）。 */
    private static List<Object> boundParams(Wrapper<?> wrapper) {
        wrapper.getSqlSegment();
        return wrapper instanceof AbstractWrapper<?, ?, ?> aw
                ? List.copyOf(aw.getParamNameValuePairs().values())
                : List.of();
    }

    private static List<Object> allBoundParams(List<Wrapper<?>> wrappers) {
        return wrappers.stream().flatMap(wrapper -> boundParams(wrapper).stream()).toList();
    }

    @Test
    @DisplayName("看板订单趋势：窗口起点与日期标签同源 = 业务日（修复前 UTC 16:01 标签比窗口晚一天）")
    void dashboardTrendWindowAndLabelsAgree() {
        Map<Instant, List<String>> expectedLabels = Map.of(
                BEFORE_MIDNIGHT, List.of("2026-01-09", "2026-01-10", "2026-01-11", "2026-01-12",
                        "2026-01-13", "2026-01-14", "2026-01-15"),
                AFTER_MIDNIGHT, List.of("2026-01-10", "2026-01-11", "2026-01-12", "2026-01-13",
                        "2026-01-14", "2026-01-15", "2026-01-16"));

        for (Instant instant : List.of(BEFORE_MIDNIGHT, AFTER_MIDNIGHT)) {
            BusinessClock clock = pinned(instant);
            OrderMapper orderMapper = mock(OrderMapper.class);
            when(orderMapper.selectOrderTrend(any())).thenReturn(List.of());
            DashboardController controller = new DashboardController(
                    mock(ProductMapper.class), orderMapper, mock(UserMapper.class),
                    mock(AfterSalesTicketMapper.class), mock(SessionMapper.class), mock(OrderItemMapper.class),
                    mock(SessionMessageMapper.class), mock(ProductSkuMapper.class), mock(ProductService.class));
            ReflectionTestUtils.setField(controller, "businessClock", clock);

            var response = controller.getOrderTrend(7);
            List<String> labels = response.getData().stream().map(point -> point.getDate()).toList();

            assertThat(labels).as("日期标签 = 业务日（clock=%s）", instant).isEqualTo(expectedLabels.get(instant));
            var windowStart = org.mockito.ArgumentCaptor.forClass(OffsetDateTime.class);
            verify(orderMapper).selectOrderTrend(windowStart.capture());
            assertThat(windowStart.getValue())
                    .as("SQL 窗口起点 = 首个业务日 00:00+08（clock=%s）", instant)
                    .isEqualTo(clock.startOfDay(clock.today().minusDays(6)));
        }
    }

    @Test
    @DisplayName("员工今日统计：今日起点 = 业务日 00:00+08（修复前是 UTC 日边界贴 +08 标签）")
    void employeeTodayStatsStartAtBusinessMidnight() {
        for (Instant instant : List.of(BEFORE_MIDNIGHT, AFTER_MIDNIGHT)) {
            BusinessClock clock = pinned(instant);
            AgentEmployeeMapper employeeMapper = mock(AgentEmployeeMapper.class);
            AgentSessionMapper sessionMapper = mock(AgentSessionMapper.class);
            AgentEmployee employee = new AgentEmployee();
            employee.setId("emp-1");
            when(employeeMapper.selectById("emp-1")).thenReturn(employee);
            List<Wrapper<?>> wrappers = captureWrappers(sessionMapper);

            AgentEmployeeService service = new AgentEmployeeService(employeeMapper, sessionMapper);
            ReflectionTestUtils.setField(service, "businessClock", clock);
            service.getEmployeeStats("emp-1");

            OffsetDateTime expected = clock.startOfToday();
            assertThat(expected.toInstant())
                    .as("业务日零点（clock=%s）", instant)
                    .isEqualTo(instant.equals(BEFORE_MIDNIGHT)
                            ? Instant.parse("2026-01-14T16:00:00Z")   // +08 01-15 00:00
                            : Instant.parse("2026-01-15T16:00:00Z"));  // +08 01-16 00:00
            assertThat(allBoundParams(wrappers))
                    .as("「今日接待数」的 SQL 必须绑业务日零点（clock=%s）", instant)
                    .contains(expected);
        }
    }

    @Test
    @DisplayName("客服会话监控：今日总会话的起点 = 业务日 00:00+08（与员工统计同源）")
    void monitorTodayTotalStartsAtBusinessMidnight() {
        for (Instant instant : List.of(BEFORE_MIDNIGHT, AFTER_MIDNIGHT)) {
            BusinessClock clock = pinned(instant);
            AgentSessionMapper sessionMapper = mock(AgentSessionMapper.class);
            AgentEmployeeMapper employeeMapper = mock(AgentEmployeeMapper.class);
            when(employeeMapper.selectList(any())).thenReturn(List.of());
            List<Wrapper<?>> wrappers = captureWrappers(sessionMapper);

            AgentSessionService service = new AgentSessionService(sessionMapper,
                    mock(AgentMessageMapper.class), employeeMapper, mock(CustomerProfileMapper.class),
                    mock(ApplicationEventPublisher.class));
            ReflectionTestUtils.setField(service, "businessClock", clock);
            service.getMonitorStats(1L);

            assertThat(allBoundParams(wrappers))
                    .as("「今日总会话数」的 SQL 必须绑业务日零点（clock=%s）", instant)
                    .contains(clock.startOfToday());
        }
    }

    @Test
    @DisplayName("短信每日计数 TTL：到业务日零点为止（UTC 15:59 ⇒ 1 分钟；UTC 16:01 ⇒ 23h59m）")
    void smsDailyCounterTtlEndsAtBusinessMidnight() {
        Map<Instant, Duration> expectedTtl = Map.of(
                BEFORE_MIDNIGHT, Duration.ofMinutes(1),                 // +08 23:59 → 次日 00:00
                AFTER_MIDNIGHT, Duration.ofHours(23).plusMinutes(59));  // +08 00:01 → 次日 00:00

        for (Instant instant : List.of(BEFORE_MIDNIGHT, AFTER_MIDNIGHT)) {
            StringRedisTemplate redisTemplate = mock(StringRedisTemplate.class);
            @SuppressWarnings("unchecked")
            ValueOperations<String, String> valueOps = mock(ValueOperations.class);
            when(redisTemplate.opsForValue()).thenReturn(valueOps);
            when(redisTemplate.hasKey(anyString())).thenReturn(false);
            when(valueOps.get(anyString())).thenReturn(null);
            when(valueOps.increment(anyString())).thenReturn(1L);

            SmsService smsService = new SmsService(redisTemplate, mock(SmsConfig.class), null);
            ReflectionTestUtils.setField(smsService, "businessClock", pinned(instant));
            smsService.sendVerificationCode("13800000000");

            var ttl = org.mockito.ArgumentCaptor.forClass(Duration.class);
            verify(redisTemplate).expire(eq("sms:daily:13800000000"), ttl.capture());
            assertThat(ttl.getValue())
                    .as("每日计数 TTL 到业务日零点（clock=%s）—— 修复前两侧时区不同，UTC 15:59 会得到 8h01m", instant)
                    .isEqualTo(expectedTtl.get(instant));
        }
    }

    /** 收集 {@code selectCount(...)} 收到的全部包装器（值要在断言里再触发惰性绑定）。 */
    @SuppressWarnings("unchecked")
    private static List<Wrapper<?>> captureWrappers(AgentSessionMapper sessionMapper) {
        List<Wrapper<?>> wrappers = new ArrayList<>();
        when(sessionMapper.selectCount(any())).thenAnswer(invocation -> {
            wrappers.add((Wrapper<AgentSession>) invocation.getArgument(0));
            return 0L;
        });
        return wrappers;
    }
}
