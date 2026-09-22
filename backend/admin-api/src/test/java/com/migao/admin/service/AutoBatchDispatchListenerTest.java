// case_ids: PR-086
package com.migao.admin.service;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.transaction.event.TransactionPhase;
import org.springframework.transaction.event.TransactionalEventListener;

import java.lang.reflect.Method;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.when;

/**
 * 🔴 <b>「池可能变了」的评估与按需成批 —— 监听器侧（issue #5182 判据 2 / 判据 10）</b>。
 *
 * <h2>判据 2：事件驱动，不是计时器</h2>
 * ① <b>结构性</b>：监听器必须是 {@code @TransactionalEventListener(phase = AFTER_COMMIT)}
 * —— 相位不是可选项：三个挂载点都在事务里，提交前评估会读到「还没入池」的单（判据 2 结构上不成立）。
 * ② <b>没有计时器</b>：触发链三个类上**没有任何 {@code @Scheduled}**（反射逐方法断言）。
 *
 * <h2>判据 10：失败不影响主流程，但必须留痕</h2>
 * {@code AFTER_COMMIT} 的监听器抛出的异常会**逸出到 {@code commit()} 的调用方**
 * （= 确认支付那一侧 ⇒ 「支付成功却报错」）⇒ 监听器必须吞掉并留 incident 痕迹。
 * 红证 = 去掉监听器的 {@code catch} 或那行 {@code log.error} ⇒ 本类对应判据红
 * （见 {@code scripts/auto-batch-red-proof.py}）。
 *
 * <p>本类用**桩服务**把监听器单独钉住（真链路的读数在 {@code AutoBatchDispatchTest} 与
 * 真库的 {@code AutoBatchDispatchRealDbTest}）。</p>
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("#5182 监听器：AFTER_COMMIT（无计时器）+ 失败吞掉并留痕 + 成功留痕迹")
class AutoBatchDispatchListenerTest {

    private static final Long TENANT = 5182L;

    @Mock
    private ProcessingOrderService processingOrderService;

    @Test
    @DisplayName("🔴 判据2 结构性：@TransactionalEventListener(AFTER_COMMIT) + 触发链上没有任何 @Scheduled")
    void listenerIsAnAfterCommitEventListenerAndTheChainHasNoTimer() throws Exception {
        Method listener = AutoBatchDispatchListener.class
                .getMethod("onPoolChanged", PoolChangeNotifier.PoolChanged.class);
        TransactionalEventListener annotation = listener.getAnnotation(TransactionalEventListener.class);

        assertThat(annotation).as("触发靠**事件**：监听器必须是 @TransactionalEventListener").isNotNull();
        assertThat(annotation.phase())
                .as("相位 = AFTER_COMMIT（提交前评估会读到「还没入池」的单 ⇒ 相位是正确性的一部分）")
                .isEqualTo(TransactionPhase.AFTER_COMMIT);

        for (Class<?> type : List.of(AutoBatchDispatchListener.class, PoolChangeNotifier.class,
                ProcessingOrderService.class)) {
            for (Method method : type.getDeclaredMethods()) {
                assertThat(method.isAnnotationPresent(Scheduled.class))
                        .as("🔴 不得有任何计时器：%s.%s 上出现了 @Scheduled",
                                type.getSimpleName(), method.getName())
                        .isFalse();
            }
        }
    }

    @Test
    @DisplayName("🔴 判据10：评估抛异常 ⇒ 监听器**吞掉**并留 INCIDENT 痕迹（否则确认支付那侧会「成功却报错」）")
    void evaluationFailureIsSwallowedAndLeavesAnIncidentTrail() {
        when(processingOrderService.autoBatchDispatch(eq(TENANT), any()))
                .thenThrow(new IllegalStateException("夹具：评估炸了"));

        assertThatCode(() -> new AutoBatchDispatchListener(processingOrderService)
                .onPoolChanged(new PoolChangeNotifier.PoolChanged(TENANT, "t")))
                .as("红证：去掉监听器的 catch ⇒ 本断言红")
                .doesNotThrowAnyException();

        assertThat(capture(() -> new AutoBatchDispatchListener(processingOrderService)
                .onPoolChanged(new PoolChangeNotifier.PoolChanged(TENANT, "t"))))
                .as("🔴 不静默：grep INCIDENT_PRODUCTION_AUTO_BATCH_DISPATCH_FAILED 必须捞得到")
                .anySatisfy(message -> assertThat(message)
                        .contains(AutoBatchDispatchListener.INCIDENT_AUTO_BATCH_FAILED)
                        .contains("t"));
    }

    @Test
    @DisplayName("逐单失败 ⇒ 留 INCIDENT 痕迹（失败单号 + 原因同一行）；派出去的留成功痕迹")
    void perOrderFailuresAndSuccessesBothLeaveTrails() {
        when(processingOrderService.autoBatchDispatch(eq(TENANT), any()))
                .thenReturn(new ProcessingOrderService.AutoBatchOutcome(true, "t", "fifo",
                        List.of("order=ORD-1:business_due=2026-09-01"),
                        List.of("JG-1"), List.of("o-2"), List.of("trigger=t, orderId=o-2: 夹具失败")));

        List<String> messages = capture(() -> new AutoBatchDispatchListener(processingOrderService)
                .onPoolChanged(new PoolChangeNotifier.PoolChanged(TENANT, "t")));

        assertThat(messages).anySatisfy(message -> assertThat(message)
                .contains(AutoBatchDispatchListener.INCIDENT_AUTO_BATCH_FAILED)
                .contains("o-2"));
        assertThat(messages).anySatisfy(message -> assertThat(message)
                .contains(AutoBatchDispatchListener.TRACE_AUTO_BATCH_DISPATCHED)
                .contains("JG-1"));
    }

    @Test
    @DisplayName("缺省关（enabled=false）⇒ **一条日志都不打**（不启用 ⇒ 与今天逐值相同，不造噪声）")
    void disabledOutcomeLogsNothing() {
        when(processingOrderService.autoBatchDispatch(eq(TENANT), any()))
                .thenReturn(new ProcessingOrderService.AutoBatchOutcome(false, "t", null,
                        List.of(), List.of(), List.of(), List.of()));

        assertThat(capture(() -> new AutoBatchDispatchListener(processingOrderService)
                .onPoolChanged(new PoolChangeNotifier.PoolChanged(TENANT, "t"))))
                .as("不启用 ⇒ 零日志噪声").isEmpty();
    }

    @Test
    @DisplayName("空事件 / 空租户 ⇒ 无动作（不评估、不抛、不打日志）")
    void blankEventIsANoOp() {
        AutoBatchDispatchListener listener = new AutoBatchDispatchListener(processingOrderService);

        assertThat(capture(() -> {
            listener.onPoolChanged(null);
            listener.onPoolChanged(new PoolChangeNotifier.PoolChanged(null, "t"));
        })).isEmpty();
    }

    // ─────────────────────────────────────────── 夹具

    /** 跑一次动作并把它写进监听器 logger 的消息**逐条**读回来（不常驻 appender，避免跨用例串味）。 */
    private static List<String> capture(Runnable action) {
        ch.qos.logback.classic.Logger logger = (ch.qos.logback.classic.Logger)
                org.slf4j.LoggerFactory.getLogger(AutoBatchDispatchListener.class);
        ch.qos.logback.core.read.ListAppender<ch.qos.logback.classic.spi.ILoggingEvent> appender =
                new ch.qos.logback.core.read.ListAppender<>();
        appender.start();
        logger.addAppender(appender);
        try {
            action.run();
            return appender.list.stream()
                    .map(ch.qos.logback.classic.spi.ILoggingEvent::getFormattedMessage).toList();
        } finally {
            logger.detachAppender(appender);
        }
    }
}
