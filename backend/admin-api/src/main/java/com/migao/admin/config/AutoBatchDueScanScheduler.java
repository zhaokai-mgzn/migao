package com.migao.admin.config;

import com.migao.admin.service.AutoBatchDueScanService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

/**
 * 🔴 <b>「到点自愈」的**运行载体**（issue #5184）—— 一个薄壳，判断全在
 * {@link AutoBatchDueScanService}。</b>
 *
 * <h2>为什么是这个载体（前置调研结论）</h2>
 * 仓内既有的定时腿范式就是它：{@code @EnableScheduling} 已在
 * {@code AdminApiApplication} 打开，{@code BriefingScheduler}（#3468，每日简报）用的正是
 * 「{@code @Scheduled(cron=…)} 薄壳 + 服务里做逐租户循环」这一形态 ⇒ 本单**复用同款**，
 * 不引入新的调度基础设施（不加 Quartz / 不加 ShedLock / 不新增 workflow）。
 *
 * <h2>周期怎么定（= 「约定窗口」）</h2>
 * 🔴 <b>约定窗口 = 一个扫描周期（缺省 5 分钟）+ 单轮耗时</b>：一张单过了最晚派单日之后，
 * 最迟在下一次扫描时被派出去。到期判定是**日粒度**（{@code today ≥ latestDispatchDate}），
 * 所以周期只需远小于一天；5 分钟是「够快、又不至于把池读放大成常态负载」的折中，
 * 可用 {@code migao.production.auto-batch.due-scan-cron} 覆盖（缺省值只有这一处）。
 *
 * <h2>它**没有**引入任何「池化窗口 / 等待时长上限」参数</h2>
 * 本类只决定「什么时候看一眼」；「看到什么就派」由
 * {@link com.migao.admin.service.ProcessingOrderService#autoBatchDispatchDue(Long)} 决定
 * —— 那条路只判业务约束（客户的到货日倒推 / 标准生产周期）。cron 是**扫描频率**，不是派单死线；
 * 把频率当死线正是用户逐字否掉的「池化窗口超时」。
 *
 * <h2>fail-soft</h2>
 * 兜底扫描是**优化**，不是主流程的正确性前提 ⇒ 本方法**吞掉**一切异常并留 incident 痕迹
 * （{@link AutoBatchDueScanService#INCIDENT_DUE_SCAN_FAILED}，可 grep），
 * 与 {@code BriefingScheduler} 同款：一次失败不许把调度线程打死。
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class AutoBatchDueScanScheduler {

    /**
     * 缺省扫描周期：每 5 分钟一轮（6 段 cron：秒 分 时 日 月 周）。
     *
     * <p>属性 {@code migao.production.auto-batch.due-scan-cron} 覆盖它 ——
     * 缺省值只有这一处（不在 yml 里再写一遍，两处缺省值必然漂移）。</p>
     */
    public static final String DUE_SCAN_DEFAULT_CRON = "0 */5 * * * *";

    private final AutoBatchDueScanService autoBatchDueScanService;

    /** 到期扫描（每轮只做一件事：已过最晚派单日的池内订单 ⇒ 必派）。 */
    @Scheduled(cron = "${migao.production.auto-batch.due-scan-cron:" + DUE_SCAN_DEFAULT_CRON + "}")
    public void scanDuePooledOrders() {
        try {
            autoBatchDueScanService.scanDuePooledOrders();
        } catch (Exception e) {
            // 服务自己已经不抛（整轮失败也只是读数）；这里是最后一道：调度线程不许被一次失败打死。
            log.error("{} 到期扫描载体异常: {}", AutoBatchDueScanService.INCIDENT_DUE_SCAN_FAILED,
                    e.getMessage(), e);
        }
    }
}
