package com.migao.admin.service;

import com.migao.admin.config.TenantContext;
import com.migao.admin.mapper.OrderMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.atomic.AtomicLong;

/**
 * 🔴 <b>「到点自愈」的到期扫描（issue #5184）—— 自动派单兜底的运行载体。</b>
 *
 * <h2>它补的是什么洞</h2>
 * #5182 的业务兜底（{@code 最晚派单日 = 到货日 − 标准生产周期}）**只在事件到达时被评估**：
 * 新单入池 / 新批次入库 / 改单取消。若一段时间内一个事件都不发生（周末 / 假期 / 淡季），
 * 已到期的单**不会被派** —— 而用户裁定「人工漏标不得压单」是一条**保证**，
 * 「下一次无关事件顺带补上」不是保证。本类就是那个**不依赖任何业务事件**的载体。
 *
 * <h2>它只做一件事（做反了就正好是用户要去掉的东西）</h2>
 * 逐租户调 {@link ProcessingOrderService#autoBatchDispatchDue(Long)} —— 那条路**只**判业务约束
 * （已过最晚派单日 ⇒ 必派），**不**判成批条件 ①②③（优化参数）、**不**读池化窗口 / 等待时长上限。
 * 主触发仍是业务事件（{@code AutoBatchDispatchListener}），本类是**兜底**、不是第二条主触发。
 *
 * <h2>默认关（判据 4）</h2>
 * 自动成批未启用 ⇒ 本方法**零读零写**立刻返回：连「有哪些租户」都不查
 * （记录期基线正建立在「不启用 ⇒ 行为与今天逐值相同」之上）。
 *
 * <h2>心跳可见（判据 5）</h2>
 * 这条腿**不靠日志心跳**（5 分钟一条 info 只会变成没人看的噪声），而是把
 * {@code rounds} / {@code last_success_at} / {@code last_failure_at} / {@code last_scanned_tenants}
 * / {@code last_dispatched} / {@code last_error} 记在这里，由
 * {@code AutoBatchDueScanHealthIndicator} 暴露到 {@code /actuator/health} 的 details 里
 * —— 与 {@code MigrationHealthIndicator}（#4517）同一范式：**停摆这件事必须有人看得见**。
 *
 * <h2>多实例 / 并发（判据 3）</h2>
 * 每个实例都会各自跑（本类不做分布式锁 —— 那要引入 Redis 租约，属过度建设）。
 * 安全来自**既有的三道闸**：{@code selectActiveByOrderId}（fail-closed）+ 部分唯一索引
 * {@code uk_processing_orders_active} + {@code uk_batch_consumption_line}
 * ⇒ 并发的第二路**派不出去也扣不动**（它记一条失败痕迹，不重复派、不重复扣）。
 * 与事件腿并发同形 —— #5182 已按同一口径设计。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class AutoBatchDueScanService {

    /** 定时腿派出加工单的痕迹标记（含张数；与 {@code generated_by} 同一份事实的日志面）。 */
    public static final String TRACE_DUE_SCAN = "AUTO_BATCH_DUE_SCAN";

    /** 定时腿失败的 incident 标记：`grep INCIDENT_PRODUCTION_AUTO_BATCH_DUE_SCAN_FAILED`。 */
    public static final String INCIDENT_DUE_SCAN_FAILED =
            "INCIDENT_PRODUCTION_AUTO_BATCH_DUE_SCAN_FAILED";

    private final ProcessingOrderService processingOrderService;
    private final OrderMapper orderMapper;

    /** 已完成的扫描轮数（心跳：这个数不动 = 定时腿停了）。 */
    private final AtomicLong rounds = new AtomicLong();
    private volatile OffsetDateTime lastSuccessAt;
    private volatile OffsetDateTime lastFailureAt;
    private volatile String lastError;
    private volatile int lastScannedTenants;
    private volatile int lastDispatched;

    /**
     * 一轮到期扫描的读数（判据 1/4 的审计面 + 判据 5 的心跳面）。
     *
     * @param enabled           本轮是否真的扫了（{@code false} ⇒ 缺省关、零动作）
     * @param scannedTenants    本轮扫到的候选租户数（超集预筛的结果，不是「全平台租户数」）
     * @param dispatchedOrderNos 本轮派出去的加工单号
     * @param failures          本轮失败（含逐租户异常与逐单派单失败），逐条可行动
     */
    public record DueScanOutcome(boolean enabled, int scannedTenants, List<String> dispatchedOrderNos,
                                 List<String> failures) {
    }

    /**
     * 🔴 <b>跑一轮到期扫描</b>（运行载体调它；测试也调它 —— 载体本身只负责「什么时候跑」）。
     *
     * <p>本方法**不抛异常**：整轮失败也只是一个读数（{@code failures} 非空 + 心跳记下失败时刻），
     * 因为「兜底这一轮没跑成」不能变成「把调度线程打死、以后每轮都不跑」。</p>
     */
    public DueScanOutcome scanDuePooledOrders() {
        if (!processingOrderService.autoBatchPolicy().enabled()) {
            // 🔴 判据 4：不启用 ⇒ **零读零写**（连租户都不查）⇒ 记录期基线零污染、零日志噪声
            return new DueScanOutcome(false, 0, List.of(), List.of());
        }
        rounds.incrementAndGet();
        try {
            return scanCandidateTenants();
        } catch (RuntimeException e) {
            lastFailureAt = OffsetDateTime.now();
            lastError = e.toString();
            log.error("{} 到期扫描整轮失败（下一轮照常重试；自动成批与业务主流程不受影响）: {}",
                    INCIDENT_DUE_SCAN_FAILED, e.toString(), e);
            return new DueScanOutcome(true, 0, List.of(), List.of(e.toString()));
        }
    }

    private DueScanOutcome scanCandidateTenants() {
        List<Long> tenants = orderMapper.selectConfirmedTenantIds();
        List<String> dispatched = new ArrayList<>();
        List<String> failures = new ArrayList<>();
        // 调度线程没有请求上下文 ⇒ 必须**显式**设置租户（issue #3957：漏了这一步，生产每轮调度整体夭折）。
        // 线程是复用的 ⇒ 退出时**必须**还原，不能把租户上下文漏给下一个用这条线程的任务。
        Long previous = TenantContext.getTenantId();
        int scanned = 0;
        try {
            for (Long tenantId : tenants == null ? List.<Long>of() : tenants) {
                if (tenantId == null) {
                    continue;
                }
                scanned++;
                TenantContext.setTenantId(tenantId);
                try {
                    collect(processingOrderService.autoBatchDispatchDue(tenantId), tenantId,
                            dispatched, failures);
                } catch (RuntimeException e) {
                    // 一个租户炸了不得让其余租户这一轮都不扫（同 DailyBriefingService 的逐租户处置）
                    failures.add("tenant=" + tenantId + ": " + e);
                    log.error("{} tenant={} 到期扫描失败（其余租户继续）: {}",
                            INCIDENT_DUE_SCAN_FAILED, tenantId, e.toString(), e);
                } finally {
                    reload(previous);
                }
            }
        } finally {
            reload(previous);
        }
        lastScannedTenants = scanned;
        lastDispatched = dispatched.size();
        lastSuccessAt = OffsetDateTime.now();
        lastError = failures.isEmpty() ? null : String.join(" | ", failures);
        if (!dispatched.isEmpty()) {
            log.info("{} 定时腿派出 {} 张（来源痕迹 {}{}:<规则>）: {}", TRACE_DUE_SCAN, dispatched.size(),
                    ProcessingOrderService.AUTO_BATCH_OPERATOR_PREFIX,
                    ProcessingOrderService.AUTO_BATCH_TRIGGER_DUE_SCAN, dispatched);
        }
        if (!failures.isEmpty()) {
            log.error("{} 定时腿本轮 {} 条失败: {}", INCIDENT_DUE_SCAN_FAILED, failures.size(),
                    failures);
        }
        return new DueScanOutcome(true, scanned, List.copyOf(dispatched), List.copyOf(failures));
    }

    private static void collect(ProcessingOrderService.AutoBatchOutcome outcome, Long tenantId,
                                List<String> dispatched, List<String> failures) {
        if (outcome == null || !outcome.enabled()) {
            return;
        }
        dispatched.addAll(outcome.dispatchedOrderNos());
        for (String failure : outcome.failures()) {
            failures.add("tenant=" + tenantId + ", " + failure);
        }
    }

    /** 还原调度线程进来的租户上下文（有则还原、无则清空）。 */
    private static void reload(Long previous) {
        if (previous != null) {
            TenantContext.setTenantId(previous);
        } else {
            TenantContext.clear();
        }
    }

    // ── 心跳读数（判据 5 的可观测面；消费方 = AutoBatchDueScanHealthIndicator）

    /** 这条腿当前是否启用（= 自动成批总开关；关着的时候它本来就不该跑）。 */
    public boolean isEnabled() {
        return processingOrderService.autoBatchPolicy().enabled();
    }

    /** 已完成的扫描轮数。 */
    public long getRounds() {
        return rounds.get();
    }

    public OffsetDateTime getLastSuccessAt() {
        return lastSuccessAt;
    }

    public OffsetDateTime getLastFailureAt() {
        return lastFailureAt;
    }

    public String getLastError() {
        return lastError;
    }

    public int getLastScannedTenants() {
        return lastScannedTenants;
    }

    public int getLastDispatched() {
        return lastDispatched;
    }
}
