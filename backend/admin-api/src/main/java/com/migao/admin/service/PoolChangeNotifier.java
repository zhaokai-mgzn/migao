package com.migao.admin.service;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.context.ApplicationEventPublisher;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;

/**
 * 池组成变化的**通知点**（issue #5182 = 阶段 2b-3 的 ① 事件驱动触发）。
 *
 * <h2>它是什么 / 不是什么</h2>
 * <ul>
 *   <li>它是：主流程（确认支付 / 入库过账 / 改单 / 取消）**既有业务完成之后**追加的一句
 *       「池的候选集可能变了」的通知；真正的评估与成批在
 *       {@link AutoBatchDispatchListener} 里，**在事务提交之后**跑。</li>
 *   <li>🔴 它<b>不是</b>派单死线、也<b>不是</b>计时器：本类与
 *       {@link AutoBatchDispatchListener} 里<b>没有</b> {@code @Scheduled}、
 *       没有 {@code TaskScheduler}、没有「等池化窗口到点」这类语义 ——
 *       用户裁定要去掉的正是「把优化参数当派单死线」。</li>
 * </ul>
 *
 * <h2>fail-soft（判据 10）</h2>
 * 通知是**优化触发**，不是主流程的正确性前提（同 #5158 排料的 fail-soft 口径）。
 * 观察者见 {@link #notifySafely}：**它绝不抛**，失败只留痕（
 * {@link #INCIDENT_NOTIFY_FAILED}，incident 级、可 grep）。
 *
 * <h2>为什么发布事件而不是直接调用评估</h2>
 * ① 三个挂载点都在 {@code @Transactional} 方法里，而「新单入池」这件事在<b>提交之前</b>
 * 对另一个连接不可见 —— 直接同事务评估会读到「还没确认支付」的订单 ⇒ 判据 2 结构上不成立；
 * {@link AutoBatchDispatchListener} 的 {@code AFTER_COMMIT} 相位正好解决可见性。
 * ② 反过来，直接注入 {@code ProcessingOrderService} 会形成
 * {@code OrderService → ProcessingOrderService → OrderService} 的循环依赖。
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class PoolChangeNotifier {

    /** 池变化的触发原因（**唯一**取值表；落进 {@code processing_orders.generated_by} 的痕迹里）。 */
    public static final String TRIGGER_ORDER_CONFIRMED = "order_confirmed";
    public static final String TRIGGER_INBOUND_POSTED = "inbound_posted";
    public static final String TRIGGER_ORDER_UPDATED = "order_updated";
    public static final String TRIGGER_ORDER_CANCELLED = "order_cancelled";

    /** 通知点自身失败（含未装配）的 incident 标记：`grep INCIDENT_PRODUCTION_POOL_NOTIFY_FAILED`。 */
    public static final String INCIDENT_NOTIFY_FAILED = "INCIDENT_PRODUCTION_POOL_NOTIFY_FAILED";

    private final ApplicationEventPublisher events;

    /** 池组成可能变化（租户 + 触发原因；**不含**任何订单载荷 —— 评估自己会重算池）。 */
    public record PoolChanged(Long tenantId, String trigger) {
    }

    /** 发布「池可能变了」。空租户 / 空原因 ⇒ 无动作（无对象可评估，不造噪声事件）。 */
    public void notify(Long tenantId, String trigger) {
        if (tenantId == null || !StringUtils.hasText(trigger)) {
            return;
        }
        events.publishEvent(new PoolChanged(tenantId, trigger));
    }

    /**
     * 🔴 <b>fail-soft 的唯一落点</b>：挂载点只写这一行，且**它绝不抛**
     * —— 通知点抛异常 / 未装配，都必须对主流程<b>逐字无影响</b>
     * （判据 1「不启用 ⇒ 与今天逐值相同」与判据 10「失败不影响主流程」）。
     *
     * <p>红证：把本方法的 {@code catch} 去掉 ⇒ 「通知抛异常 ⇒ 确认支付仍成功、库存照旧」
     * 那条判据当场红（见 {@code AutoBatchDispatchTest} 的注入式红证）。</p>
     *
     * @param notifier 由调用方字段注入（{@code @Autowired(required = false)}）——
     *                 {@code null} = 本次装配里没有通知点（如既有单测的手工装配）⇒ 跳过并留痕
     */
    public static void notifySafely(PoolChangeNotifier notifier, Long tenantId, String trigger) {
        try {
            if (notifier != null) {
                notifier.notify(tenantId, trigger);
            }
        } catch (RuntimeException e) {
            log.error("{} 池化通知点失败 ⇒ 本次不触发自动成批（业务主流程不受影响）:"
                            + " tenant={}, trigger={}, error={}",
                    INCIDENT_NOTIFY_FAILED, tenantId, trigger, e.toString());
        }
    }
}
