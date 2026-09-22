// case_ids: PR-086
package com.migao.admin.service;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;

/**
 * 🔴 <b>池化通知点的纪律（issue #5182 判据 1 / 判据 10 的挂载点侧）</b>。
 *
 * <p>通知点是**优化触发**，不是主流程的正确性前提（同 #5158 排料的 fail-soft 口径）
 * ⇒ 它必须满足三条，本类逐条钉住：</p>
 * <ol>
 *   <li><b>发布的是「池可能变了」这一件事</b>（租户 + 触发原因；**不带订单载荷**
 *       —— 评估自己会重算池，带载荷就有第二份会漂的真相）；空租户 / 空原因 ⇒ 不造噪声事件。</li>
 *   <li>🔴 <b>{@code notifySafely} 绝不抛</b>：通知点炸了 / 发布器炸了 / 未装配
 *       ⇒ 主流程**逐字不受影响**。红证 = 把 {@code catch} 去掉 ⇒ 本类当场红。</li>
 *   <li><b>失败留痕可查</b>：{@code INCIDENT_PRODUCTION_POOL_NOTIFY_FAILED} 出现在日志里（不静默）。</li>
 * </ol>
 */
@DisplayName("#5182 通知点：发布口径 + 绝不抛（fail-soft）+ 失败留痕")
class PoolChangeNotifierTest {

    private static final Long TENANT = 5182L;

    @Test
    @DisplayName("发布口径：租户 + 触发原因原样发布（不带订单载荷）")
    void notifyPublishesTenantAndTrigger() {
        List<Object> published = new ArrayList<>();
        PoolChangeNotifier notifier = new PoolChangeNotifier(published::add);

        notifier.notify(TENANT, PoolChangeNotifier.TRIGGER_INBOUND_POSTED);

        assertThat(published).hasSize(1);
        assertThat(published.get(0)).isInstanceOf(PoolChangeNotifier.PoolChanged.class);
        PoolChangeNotifier.PoolChanged event = (PoolChangeNotifier.PoolChanged) published.get(0);
        assertThat(event.tenantId()).isEqualTo(TENANT);
        assertThat(event.trigger()).isEqualTo(PoolChangeNotifier.TRIGGER_INBOUND_POSTED);
    }

    @Test
    @DisplayName("空租户 / 空原因 ⇒ 无动作（无对象可评估，不造噪声事件）")
    void blankTenantOrTriggerIsANoOp() {
        List<Object> published = new ArrayList<>();
        PoolChangeNotifier notifier = new PoolChangeNotifier(published::add);

        notifier.notify(null, PoolChangeNotifier.TRIGGER_ORDER_CONFIRMED);
        notifier.notify(TENANT, null);
        notifier.notify(TENANT, "   ");

        assertThat(published).isEmpty();
    }

    @Test
    @DisplayName("🔴 判据10：发布器炸了 ⇒ notifySafely **不抛**，且留 INCIDENT 痕迹（不静默）")
    void notifySafelyNeverThrowsAndLeavesAnIncidentTrail() {
        ch.qos.logback.classic.Logger logger = (ch.qos.logback.classic.Logger)
                org.slf4j.LoggerFactory.getLogger(PoolChangeNotifier.class);
        ch.qos.logback.core.read.ListAppender<ch.qos.logback.classic.spi.ILoggingEvent> appender =
                new ch.qos.logback.core.read.ListAppender<>();
        appender.start();
        logger.addAppender(appender);
        try {
            PoolChangeNotifier broken = new PoolChangeNotifier(event -> {
                throw new IllegalStateException("夹具：发布器炸了");
            });

            assertThatCode(() -> PoolChangeNotifier.notifySafely(broken, TENANT,
                    PoolChangeNotifier.TRIGGER_ORDER_CONFIRMED))
                    .as("🔴 通知点是优化触发 ⇒ 它炸了绝不能让主流程失败（红证：去掉 catch ⇒ 本断言红）")
                    .doesNotThrowAnyException();

            assertThat(appender.list).anySatisfy(event -> assertThat(event.getFormattedMessage())
                    .as("🔴 不静默：grep INCIDENT_PRODUCTION_POOL_NOTIFY_FAILED 必须捞得到")
                    .contains(PoolChangeNotifier.INCIDENT_NOTIFY_FAILED)
                    .contains(PoolChangeNotifier.TRIGGER_ORDER_CONFIRMED));
        } finally {
            logger.detachAppender(appender);
        }
    }

    @Test
    @DisplayName("通知点**未装配**（既有手工装配的单测）⇒ 跳过，不抛、也不造事件")
    void missingNotifierIsSkipped() {
        assertThatCode(() -> PoolChangeNotifier.notifySafely(null, TENANT,
                PoolChangeNotifier.TRIGGER_ORDER_CANCELLED))
                .as("字段注入 @Autowired(required=false) ⇒ 可能为 null；通知点缺失不得影响主流程")
                .doesNotThrowAnyException();
    }

    @Test
    @DisplayName("四类触发原因各是一个独立取值（痕迹里能分辨「哪件事触发的」）")
    void triggerVocabularyIsDistinct() {
        assertThat(List.of(PoolChangeNotifier.TRIGGER_ORDER_CONFIRMED,
                        PoolChangeNotifier.TRIGGER_INBOUND_POSTED,
                        PoolChangeNotifier.TRIGGER_ORDER_UPDATED,
                        PoolChangeNotifier.TRIGGER_ORDER_CANCELLED))
                .as("取值必须互不相同（否则 generated_by 上的痕迹分辨不出触发原因）")
                .doesNotHaveDuplicates();
    }
}
