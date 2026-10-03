// case_ids: OR-061
package com.migao.admin.service;

import ch.qos.logback.classic.Level;
import ch.qos.logback.classic.Logger;
import ch.qos.logback.classic.spi.ILoggingEvent;
import ch.qos.logback.core.read.ListAppender;
import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.Order;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.time.BusinessClock;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.slf4j.LoggerFactory;
import org.springframework.test.util.ReflectionTestUtils;

import java.time.Clock;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 「发货后 N 天自动完成订单」判定本体的判据（issue #6262，用户 2026-10-03 逐字裁定 **B**）。
 *
 * <h2>本文件判什么（每条都对应一个会红的判据）</h2>
 * <ol>
 *   <li><b>未满 N 天 ⇒ 不动</b>（钉住，防误杀）：断言传给写面的<b>死线</b>逐值等于
 *       「业务现在 − N 天」—— 而"不动"由 SQL 谓词 {@code shipped_at <= 死线} 保证
 *       （谓词本体在 {@code OrderAutoCompleteSqlGuardTest} 与真库
 *       {@code AutoCompleteShippedRealDbTest} 里各判一次）。</li>
 *   <li><b>满 N 天 ⇒ 完成</b>：写面回 {@code RETURNING id} 的行 ⇒ 本轮结果里有它们。</li>
 *   <li><b>只动 shipped</b>：{@link OrderStatusTransitions#assertTransitionAllowed} 是跑之前的
 *       fail-closed 断言（{@code shipped → completed} 是流转表里<b>既有</b>的边）；SQL 谓词里
 *       写死 {@code status='shipped'}（SQL 文本判据）。</li>
 *   <li><b>多租户隔离 + 逐租户显式上下文</b>：每个租户一次写面调用、租户 id 逐值；退出时
 *       租户上下文**还原**（不泄漏给下一个用这条线程的任务）。</li>
 *   <li><b>并发只生效一次</b>：另一侧拿 0 行 ⇒ <b>静默</b>（不抛、不告警、不发站内信）。</li>
 *   <li><b>幂等</b>：同一轮连跑两次 ⇒ 第二轮 0 行、零副作用重放。</li>
 *   <li><b>副作用只绑定 RETURNING 的行</b>（集群下不重复发信）。</li>
 *   <li><b>时间源走 businessClock</b>：注入固定时钟 ⇒ 死线逐值可复算（生产路径里没有墙钟拼写）。</li>
 *   <li><b>可观测</b>：每轮 INFO 读数含扫描租户数 / 完成张数 / N / 死线。</li>
 *   <li><b>失败显式</b>：一个租户抛 ⇒ 记进 {@code failures} + ERROR，其余租户照扫、整轮不抛。</li>
 * </ol>
 */
@DisplayName("#6262 发货后 N 天自动完成：判定与执行本体（死线/静默/幂等/隔离/副作用/可观测/失败显式）")
class AutoCompleteShippedScanServiceTest {

    /** 固定业务时刻：2026-10-03T12:00:00+08:00（= 04:00Z），与业务时区无关地钉住"现在"。 */
    private static final Instant FIXED_INSTANT = Instant.parse("2026-10-03T04:00:00Z");

    private static final Long TENANT_A = 20L;
    private static final Long TENANT_B = 21L;

    private final OrderMapper orderMapper = mock(OrderMapper.class);
    private final NotificationService notificationService = mock(NotificationService.class);
    private final AutoCompleteShippedScanService service = newService(7);

    private AutoCompleteShippedScanService newService(int days) {
        AutoCompleteShippedScanService built = new AutoCompleteShippedScanService(orderMapper,
                notificationService, new BusinessClock(Clock.fixed(FIXED_INSTANT, ZoneOffset.UTC)));
        ReflectionTestUtils.setField(built, "autoCompleteDays", days);
        return built;
    }

    @AfterEach
    void clearTenant() {
        TenantContext.clear();
    }

    private static Order order(String id, Long tenantId, String userId) {
        Order order = new Order();
        order.setId(id);
        order.setTenantId(tenantId);
        order.setOrderNo("ORD-" + id);
        order.setUserId(userId);
        return order;
    }

    // ────────────────────────────────────────────── 判据 8：时间源 = businessClock

    @Test
    @DisplayName("判据 8·死线 = 业务「现在」− N 天（时间源走 businessClock；N 可配置 ⇒ 改值不改码）")
    void deadlineComesFromBusinessClockAndConfiguredDays() {
        AutoCompleteShippedScanService threeDays = newService(3);
        when(orderMapper.selectShippedTenantIds()).thenReturn(List.of());

        assertThat(service.deadline())
                .isEqualTo(OffsetDateTime.parse("2026-09-26T12:00:00+08:00"));
        assertThat(service.days()).isEqualTo(7);

        // N 可配置：同一个固定时钟下，N=3 ⇒ 死线是 09-30（而不是装配时写死的 7 天）
        assertThat(threeDays.deadline())
                .isEqualTo(OffsetDateTime.parse("2026-09-30T12:00:00+08:00"));
        assertThat(threeDays.days()).isEqualTo(3);
    }

    // ────────────────────────────────────────────── 判据 1 / 2：未满不动 vs 满期完成

    @Test
    @DisplayName("判据 1+2+3·满期单被原子完成；未满期的单不在 RETURNING 里 ⇒ 不动（同一轮里两种形态都在）")
    void onlyOverdueShippedOrdersAreCompleted() {
        when(orderMapper.selectShippedTenantIds()).thenReturn(List.of(TENANT_A));
        // 写面（= 带谓词的原子 UPDATE + RETURNING id）只回**真的满期**的那一张；
        // 未满期的那张由 SQL 谓词挡住（它不在返回值里）—— 本判据钉住"回什么就完成什么"。
        when(orderMapper.autoCompleteShippedOrders(eq(TENANT_A), any()))
                .thenReturn(List.of("overdue-order"));
        when(orderMapper.selectById("overdue-order"))
                .thenReturn(order("overdue-order", TENANT_A, "user-1"));

        AutoCompleteShippedScanService.Outcome outcome = service.scanAndComplete();

        assertThat(outcome.completedOrders()).containsExactly("overdue-order");
        assertThat(outcome.completedCount()).isEqualTo(1);
        assertThat(outcome.failures()).isEmpty();

        // 判据 1：传给写面的死线**逐值** = 业务现在 − 7 天（未满 7 天的行不可能满足它）
        ArgumentCaptor<OffsetDateTime> deadline = ArgumentCaptor.forClass(OffsetDateTime.class);
        verify(orderMapper).autoCompleteShippedOrders(eq(TENANT_A), deadline.capture());
        assertThat(deadline.getValue()).isEqualTo(OffsetDateTime.parse("2026-09-26T12:00:00+08:00"));
    }

    // ────────────────────────────────────────────── 判据 4：多租户隔离

    @Test
    @DisplayName("判据 4·逐租户隔离：每租户各一次写面调用（租户 id 逐值），退出时租户上下文还原")
    void eachTenantIsScannedWithItsOwnExplicitContext() {
        TenantContext.setTenantId(999L);
        when(orderMapper.selectShippedTenantIds()).thenReturn(List.of(TENANT_A, TENANT_B));
        when(orderMapper.autoCompleteShippedOrders(eq(TENANT_A), any())).thenAnswer(inv -> {
            // 🔴 调用**发生在**该租户的上下文里（调度线程没有请求上下文 ⇒ 必须显式设置）
            assertThat(TenantContext.getTenantId()).isEqualTo(TENANT_A);
            return List.of();
        });
        when(orderMapper.autoCompleteShippedOrders(eq(TENANT_B), any())).thenAnswer(inv -> {
            assertThat(TenantContext.getTenantId()).isEqualTo(TENANT_B);
            return List.of();
        });

        AutoCompleteShippedScanService.Outcome outcome = service.scanAndComplete();

        assertThat(outcome.scannedTenants()).isEqualTo(2);
        verify(orderMapper).autoCompleteShippedOrders(eq(TENANT_A), any());
        verify(orderMapper).autoCompleteShippedOrders(eq(TENANT_B), any());
        // 线程是复用的 ⇒ 退出时必须还原（不能把租户上下文漏给下一个任务）
        assertThat(TenantContext.getTenantId()).isEqualTo(999L);
    }

    // ────────────────────────────────────────────── 判据 5 + 6 + 7：静默 / 幂等 / 副作用绑定

    @Test
    @DisplayName("判据 5·并发只生效一次：人工「确认收货」抢先 ⇒ 自动这一侧 0 行、**静默**（不抛、不发信）")
    void losingSideOfConcurrencyIsSilent() {
        when(orderMapper.selectShippedTenantIds()).thenReturn(List.of(TENANT_A));
        // 人工路先改了状态 ⇒ 谓词不再满足 ⇒ SQL 返回 0 行（这正是生产里的并发形态）
        when(orderMapper.autoCompleteShippedOrders(eq(TENANT_A), any())).thenReturn(List.of());

        AutoCompleteShippedScanService.Outcome outcome = service.scanAndComplete();

        assertThat(outcome.completedOrders()).isEmpty();
        assertThat(outcome.failures()).isEmpty();
        // 静默 = 没有站内信、也没有"完成"读数
        verify(notificationService, never()).triggerByEvent(anyLong(), any(), any());
    }

    @Test
    @DisplayName("判据 6+7·幂等且副作用只绑定 RETURNING 的行：连跑两轮 ⇒ 只完成一次、只发一封")
    void secondRoundIsIdempotentAndSideEffectsFollowReturnedRows() {
        when(orderMapper.selectShippedTenantIds()).thenReturn(List.of(TENANT_A));
        when(orderMapper.autoCompleteShippedOrders(eq(TENANT_A), any()))
                .thenReturn(List.of("o-1"), List.of());
        when(orderMapper.selectById("o-1")).thenReturn(order("o-1", TENANT_A, "user-1"));

        service.scanAndComplete();
        AutoCompleteShippedScanService.Outcome second = service.scanAndComplete();

        assertThat(second.completedOrders()).isEmpty();
        // 副作用只对"真的被改到的行"发一次 —— 集群下 N 个实例各跑一轮也只会有一封
        verify(notificationService, times(1))
                .triggerByEvent(eq(TENANT_A), eq("order_status_changed"), any());
    }

    @Test
    @DisplayName("判据 7 的反向对照·无归属用户（商户代录）⇒ 不发站内信（与人工路逐字同口径）")
    void noNotificationWhenOrderHasNoOwnerUser() {
        when(orderMapper.selectShippedTenantIds()).thenReturn(List.of(TENANT_A));
        when(orderMapper.autoCompleteShippedOrders(eq(TENANT_A), any())).thenReturn(List.of("o-2"));
        when(orderMapper.selectById("o-2")).thenReturn(order("o-2", TENANT_A, null));

        assertThat(service.scanAndComplete().completedOrders()).containsExactly("o-2");
        verify(notificationService, never()).triggerByEvent(anyLong(), any(), any());
    }

    @Test
    @DisplayName("判据 7·站内信内容与既有语义一致：order_status_changed 事件 + 中文标签「已完成」")
    void notificationKeepsExistingSemantics() {
        when(orderMapper.selectShippedTenantIds()).thenReturn(List.of(TENANT_A));
        when(orderMapper.autoCompleteShippedOrders(eq(TENANT_A), any())).thenReturn(List.of("o-3"));
        when(orderMapper.selectById("o-3")).thenReturn(order("o-3", TENANT_A, "user-9"));

        service.scanAndComplete();

        @SuppressWarnings("unchecked")
        ArgumentCaptor<Map<String, String>> ctx = ArgumentCaptor.forClass(Map.class);
        verify(notificationService).triggerByEvent(eq(TENANT_A), eq("order_status_changed"), ctx.capture());
        assertThat(ctx.getValue())
                .containsEntry("recipientId", "user-9")
                .containsEntry("recipientType", "user")
                .containsEntry("orderNo", "ORD-o-3")
                .containsEntry("status", "已完成");
    }

    @Test
    @DisplayName("判据 7·发信失败不改变结果（状态已落库；失败只留痕迹，不回滚不抛出）")
    void notificationFailureDoesNotBreakTheRound() {
        when(orderMapper.selectShippedTenantIds()).thenReturn(List.of(TENANT_A));
        when(orderMapper.autoCompleteShippedOrders(eq(TENANT_A), any())).thenReturn(List.of("o-4"));
        when(orderMapper.selectById("o-4")).thenReturn(order("o-4", TENANT_A, "user-4"));
        org.mockito.Mockito.doThrow(new IllegalStateException("站内信服务炸了"))
                .when(notificationService).triggerByEvent(anyLong(), any(), any());

        AutoCompleteShippedScanService.Outcome outcome = service.scanAndComplete();

        assertThat(outcome.completedOrders()).containsExactly("o-4");
        assertThat(outcome.failures()).isEmpty();
    }

    // ────────────────────────────────────────────── 判据 9：可观测

    @Test
    @DisplayName("判据 9·可观测：每轮 INFO 读数含 [扫描租户数 / 完成张数 / N / 死线]；Outcome 同值")
    void eachRoundLeavesAReadableTrace() {
        when(orderMapper.selectShippedTenantIds()).thenReturn(List.of(TENANT_A, TENANT_B));
        when(orderMapper.autoCompleteShippedOrders(eq(TENANT_A), any())).thenReturn(List.of("o-5"));
        when(orderMapper.autoCompleteShippedOrders(eq(TENANT_B), any())).thenReturn(List.of());
        when(orderMapper.selectById("o-5")).thenReturn(order("o-5", TENANT_A, "user-5"));

        Logger logger = (Logger) LoggerFactory.getLogger(AutoCompleteShippedScanService.class);
        ListAppender<ILoggingEvent> appender = new ListAppender<>();
        appender.start();
        logger.addAppender(appender);
        try {
            AutoCompleteShippedScanService.Outcome outcome = service.scanAndComplete();

            assertThat(outcome.scannedTenants()).isEqualTo(2);
            assertThat(outcome.completedCount()).isEqualTo(1);
            List<String> logs = appender.list.stream()
                    .filter(e -> e.getLevel() == Level.INFO)
                    .map(ILoggingEvent::getFormattedMessage)
                    .toList();
            assertThat(logs).anySatisfy(msg -> assertThat(msg)
                    .contains(AutoCompleteShippedScanService.TRACE_AUTO_COMPLETE)
                    .contains("扫描租户=2")
                    .contains("自动完成=1 张")
                    .contains("失败=0 条")
                    .contains("N=7 天"));
        } finally {
            logger.detachAppender(appender);
        }
    }

    // ────────────────────────────────────────────── 判据 10：失败显式

    @Test
    @DisplayName("判据 10·失败显式：一个租户抛 ⇒ 记进 failures + ERROR，其余租户照扫、整轮不抛")
    void tenantFailureIsRecordedAndOtherTenantsContinue() {
        AtomicInteger calls = new AtomicInteger();
        when(orderMapper.selectShippedTenantIds()).thenReturn(List.of(TENANT_A, TENANT_B));
        when(orderMapper.autoCompleteShippedOrders(eq(TENANT_A), any()))
                .thenThrow(new IllegalStateException("坏数据"));
        when(orderMapper.autoCompleteShippedOrders(eq(TENANT_B), any())).thenAnswer(inv -> {
            calls.incrementAndGet();
            return List.of("o-6");
        });
        when(orderMapper.selectById("o-6")).thenReturn(order("o-6", TENANT_B, "user-6"));

        Logger logger = (Logger) LoggerFactory.getLogger(AutoCompleteShippedScanService.class);
        ListAppender<ILoggingEvent> appender = new ListAppender<>();
        appender.start();
        logger.addAppender(appender);
        try {
            AutoCompleteShippedScanService.Outcome outcome = service.scanAndComplete();

            assertThat(outcome.failures()).hasSize(1);
            assertThat(outcome.failures().get(0))
                    .contains("tenant=" + TENANT_A)
                    .contains("坏数据");
            // 一个租户炸了不得让其余租户这一轮都不扫
            assertThat(calls.get()).isEqualTo(1);
            assertThat(outcome.completedOrders()).containsExactly("o-6");
            assertThat(appender.list.stream()
                    .filter(e -> e.getLevel() == Level.ERROR)
                    .map(ILoggingEvent::getFormattedMessage)
                    .toList())
                    .anySatisfy(msg -> assertThat(msg)
                            .contains(AutoCompleteShippedScanService.INCIDENT_FAILED)
                            .contains("tenant=" + TENANT_A));
        } finally {
            logger.detachAppender(appender);
        }
        // 整轮不抛（载体那一层只兜"整轮炸"，本层已把逐租户失败变成读数）
        TenantContext.clear();
    }

    @Test
    @DisplayName("判据 3·跑之前过唯一状态机：shipped→completed 是合法边（本类不自建第二张流转表）")
    void transitionIsAssertedAgainstTheSingleStateMachine() {
        // 正向：既有边存在 ⇒ 不抛（本单**不改** STATUS_TRANSITIONS）
        OrderStatusTransitions.assertTransitionAllowed("shipped", "completed");
        assertThat(OrderStatusTransitions.allowedTargets("shipped")).containsExactly("completed");
        // 反向对照：自动完成**不是**任何其它状态的出口（只动 shipped）
        assertThat(OrderStatusTransitions.allowedTargets("completed")).isEmpty();
        assertThat(OrderStatusTransitions.allowedTargets("cancelled")).isEmpty();
    }

    @Test
    @DisplayName("判据 4 的反向对照·无候选租户 ⇒ 零写面调用（不空转）")
    void noCandidatesMeansNoWrites() {
        when(orderMapper.selectShippedTenantIds()).thenReturn(List.of());

        AutoCompleteShippedScanService.Outcome outcome = service.scanAndComplete();

        assertThat(outcome.scannedTenants()).isZero();
        assertThat(outcome.completedOrders()).isEmpty();
        verify(orderMapper, never()).autoCompleteShippedOrders(any(), any());
    }
}
