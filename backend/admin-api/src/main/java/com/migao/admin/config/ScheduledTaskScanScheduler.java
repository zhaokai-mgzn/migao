package com.migao.admin.config;

import com.migao.admin.service.ScheduledTaskService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

/**
 * 定时任务（用户「预约」）的**扫描载体** —— issue #6486 包 1。
 *
 * <p>一个薄壳，判断全在 {@link ScheduledTaskService#scanDue()}。这与仓内既有定时腿
 * （{@code BriefingScheduler} #3468 / {@code AutoBatchDueScanScheduler} #5184）**同款**：
 * {@code @EnableScheduling} 已在 {@code AdminApiApplication} 打开 ⇒ 本单**不引入新的调度基础设施**
 * （不加 Quartz / 不加 ShedLock / 不新增 workflow）。</p>
 *
 * <h2>周期怎么定</h2>
 * 缺省**每分钟**一轮。到期判定是**时刻级**（{@code fire_at <= now}，不是日粒度）⇒ 用户看到的
 * 「到点提醒」最迟延迟一个扫描周期（≤1 分钟）。可用属性
 * {@code migao.agent.scheduled-task.scan-cron} 覆盖；缺省值**只有这一处**（不在 yml 里再写一遍
 * —— 两处缺省值必然漂移）。</p>
 *
 * <h2>fail-soft</h2>
 * 兜底扫描是**优化**，不是主流程的正确性前提 ⇒ 本方法**吞掉**一切异常并留 incident 痕迹
 * （{@link ScheduledTaskService#INCIDENT_SCAN_FAILED}，可 grep），与另外两条定时腿同款：
 * 一次失败不许把调度线程打死。
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class ScheduledTaskScanScheduler {

    /**
     * 缺省扫描周期：每分钟一轮（6 段 cron：秒 分 时 日 月 周）。
     *
     * <p>属性 {@code migao.agent.scheduled-task.scan-cron} 覆盖它 —— 缺省值只有这一处。</p>
     */
    public static final String DUE_SCAN_DEFAULT_CRON = "0 * * * * *";

    private final ScheduledTaskService scheduledTaskService;

    /** 到期扫描（每轮只做一件事：到期的待办 ⇒ 投递成站内通知）。 */
    @Scheduled(cron = "${migao.agent.scheduled-task.scan-cron:" + DUE_SCAN_DEFAULT_CRON + "}")
    public void scanDueTasks() {
        try {
            int delivered = scheduledTaskService.scanDue();
            if (delivered > 0) {
                log.info("[ScheduledTask] 本分钟投递 {} 条到期待办", delivered);
            }
        } catch (Exception e) {
            // 服务自己已逐租户 fail-soft；这里是最后一道：调度线程不许被一次失败打死。
            log.error("{} 扫描载体异常: {}", ScheduledTaskService.INCIDENT_SCAN_FAILED, e.getMessage(), e);
        }
    }
}
