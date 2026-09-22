package com.migao.admin.service;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;
import org.springframework.transaction.event.TransactionPhase;
import org.springframework.transaction.event.TransactionalEventListener;

/**
 * 「池可能变了」的**评估与按需成批**（issue #5182 = 阶段 2b-3）。
 *
 * <h2>相位 = AFTER_COMMIT（为什么必须是它）</h2>
 * 三个挂载点都在 {@code @Transactional} 方法里：确认支付 / 入库过账 / 改单 / 取消
 * 写下的那几行，在**提交之前**对别的连接不可见。若在事务内评估，池里根本看不到刚入池的单
 * ⇒ 「事件到达即刻重算」就变成了「下一件事之后才算」。
 *
 * <h2>🔴 计时器在这里**不是**主触发</h2>
 * 本类没有任何定时器；主触发是**业务事件**（{@link PoolChangeNotifier} 的四类）。
 * 「到货日 / 标准工期」那条业务约束在 {@code ProcessingOrderService.autoBatchDispatch}
 * 里被**每次事件评估时**检查 —— 到期就有事件来评估，无事件也在下一次事件上补上
 * （看板侧的「超上限告警」是同一个口径的人工可见面，见 {@code pool()} 的 warnings）。
 * ⇒ 「无单可配时永远不派」不成立：兜底是**每次评估都跑**的业务约束判定，不是窗口超时。
 *
 * <h2>fail-soft（判据 10）</h2>
 * 评估/成批是**优化**（同 #5158 排料口径），不是主流程的正确性前提 ⇒ 本方法**吞掉**异常
 * 并留 incident 痕迹（{@link #INCIDENT_AUTO_BATCH_FAILED}，可 grep）。
 * 这一点不是可选的：{@code AFTER_COMMIT} 的监听器抛出的异常会**逸出到 {@code commit()}
 * 的调用方**（= 确认支付那一侧），从而让「确认支付成功但报错」。红证 = 去掉
 * 这里的 {@code catch} ⇒ 「通知抛异常 ⇒ 确认支付仍成功」那条判据当场红。
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class AutoBatchDispatchListener {

    /** 评估/成批失败的 incident 标记：`grep INCIDENT_PRODUCTION_AUTO_BATCH_DISPATCH_FAILED`。 */
    public static final String INCIDENT_AUTO_BATCH_FAILED =
            "INCIDENT_PRODUCTION_AUTO_BATCH_DISPATCH_FAILED";

    /** 成批成功的痕迹标记（含触发原因 / 规则 / 单号；与 {@code generated_by} 同一份事实的日志面）。 */
    public static final String TRACE_AUTO_BATCH_DISPATCHED = "AUTO_BATCH_DISPATCH";

    private final ProcessingOrderService processingOrderService;

    @TransactionalEventListener(phase = TransactionPhase.AFTER_COMMIT)
    public void onPoolChanged(PoolChangeNotifier.PoolChanged event) {
        if (event == null || event.tenantId() == null) {
            return;
        }
        ProcessingOrderService.AutoBatchOutcome outcome;
        try {
            outcome = processingOrderService.autoBatchDispatch(event.tenantId(), event.trigger());
        } catch (RuntimeException e) {
            log.error("{} tenant={}, trigger={}, error={}",
                    INCIDENT_AUTO_BATCH_FAILED, event.tenantId(), event.trigger(), e.toString(), e);
            return;
        }
        if (outcome == null || !outcome.enabled()) {
            // 缺省关（判据 1）：不启用 ⇒ **零落库零日志噪声**，与今天逐值相同
            return;
        }
        if (!outcome.dispatchedOrderNos().isEmpty()) {
            log.info("{} tenant={}, trigger={}, rule={}, reasons={}, processingOrderNos={}",
                    TRACE_AUTO_BATCH_DISPATCHED, event.tenantId(), event.trigger(), outcome.rule(),
                    outcome.reasons(), outcome.dispatchedOrderNos());
        }
        if (!outcome.failures().isEmpty()) {
            log.error("{} tenant={}, trigger={}, failedOrderIds={}, failures={}",
                    INCIDENT_AUTO_BATCH_FAILED, event.tenantId(), event.trigger(),
                    outcome.failedOrderIds(), outcome.failures());
        }
    }
}
