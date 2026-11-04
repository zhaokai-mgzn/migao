package com.migao.admin.config;

import com.migao.admin.service.AgentBatchLeaseService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

/**
 * 🔴 <b>批次执行租约的**回收载体**（issue #8285）—— 一个薄壳，判断全在
 * {@link AgentBatchLeaseService#recoverStaleExecuting()}。</b>
 *
 * <h2>为什么要有这条定时腿</h2>
 * #8283 的批次 job 是**进程内**线程池：JVM 崩溃 / 强杀 / 容器被摘时，进程里没有任何东西还记得
 * 「这批是谁在跑」⇒ 批次永远停在 {@code status=executing}（既不能重试也不能撤销，用户只能重启后
 * 手工找库）。有了租约（{@code executor_id} + {@code heartbeat_at}，迁移 V208），**任何一个实例**
 * 都能凭一条客观事实把它收回成可撤销的 {@code partial}：心跳超时 ⇒ 执行者已死。
 *
 * <h2>为什么是「薄壳 + 服务里逐租户循环」（照抄本仓既有范式，不引新基础设施）</h2>
 * 仓内既有定时腿范式就是它：{@code BriefingScheduler}（#3468）、{@code AutoBatchDueScanScheduler}
 * （#5184）、{@code AutoCompleteShippedScanScheduler}（#6262）、{@code ScheduledTaskScanScheduler}
 * （#6486）—— {@code @EnableScheduling} 已在 {@code AdminApiApplication} 打开 ⇒ 本单**复用同款**，
 * 不引入 Quartz / ShedLock / 新 workflow，也不判断「我是不是 leader」。
 *
 * <h2>周期怎么定</h2>
 * 缺省**每分钟**一轮：回收判定的时效是 {@code 心跳超时 = 180s}（{@link AgentBatchLeaseService#LEASE_TIMEOUT_SECONDS}）
 * ⇒ 崩溃后**最迟约 3~4 分钟**批次变成可撤销。可用属性 {@code migao.agent.batch.lease-scan-cron}
 * 覆盖；缺省值**只有这一处**（不在 yml 里再写一遍 —— 两处缺省值必然漂移）。
 *
 * <h2>多实例 / 幂等（同一套代码，无需开关）</h2>
 * 每个实例都各自扫：{@code AgentBatchMapper#markStaleExecutingPartial} 是**一条带时效谓词的原子
 * UPDATE** ⇒ 每一行只有一个事务能改到，另一侧 0 行、静默；回收后状态已不是 {@code executing}
 * ⇒ 重复回收 0 行（幂等）。**活 job 的心跳（每条明细前刷新）是唯一的豁免** —— 心跳新鲜就是 0 行。
 *
 * <h2>fail-soft（只兜「整轮炸」这一档）</h2>
 * 逐租户失败已由服务自己记 ERROR 并继续；这里只兜最后一次 —— 调度线程不许被一次失败打死
 * （与另外几条定时腿同款）。
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class AgentBatchLeaseRecoveryScheduler {

    /**
     * 缺省扫描周期：每分钟一轮（6 段 cron：秒 分 时 日 月 周）。
     *
     * <p>属性 {@code migao.agent.batch.lease-scan-cron} 覆盖它 —— 缺省值只有这一处。</p>
     */
    public static final String LEASE_SCAN_DEFAULT_CRON = "0 * * * * *";

    private final AgentBatchLeaseService leaseService;

    /** 回收一轮：只把「心跳超时 / 从未心跳」的 executing 批次收回成 partial（明细一条都不碰）。 */
    @Scheduled(cron = "${migao.agent.batch.lease-scan-cron:" + LEASE_SCAN_DEFAULT_CRON + "}")
    public void recoverStaleBatches() {
        try {
            AgentBatchLeaseService.LeaseRecoveryOutcome outcome = leaseService.recoverStaleExecuting();
            if (outcome.recoveredBatches() > 0) {
                log.warn("[Agent] 批次租约回收：扫描租户={}, 回收批次={}（已置 partial，可撤销）",
                        outcome.scannedTenants(), outcome.recoveredBatches());
            }
        } catch (Exception e) {
            // 服务自己已逐租户兜住并记读数；这里是最后一道：调度线程不许被一次失败打死。
            log.error("[Agent] 批次租约回收载体异常: {}", e.getMessage(), e);
        }
    }
}
