package com.migao.admin.config;

import com.migao.admin.service.AutoCompleteShippedScanService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

/**
 * 🔴 <b>「发货后 N 天自动完成订单」的**运行载体**（issue #6262）—— 一个薄壳，
 * 判断全在 {@link AutoCompleteShippedScanService}。</b>
 *
 * <h2>为什么是这个载体（照抄本仓既有范式，不引新基础设施）</h2>
 * 仓内既有的定时腿范式就是它：{@code @EnableScheduling} 已在 {@code AdminApiApplication} 打开，
 * {@link AutoBatchDueScanScheduler}（#5184）与 {@code BriefingScheduler}（#3468）用的正是
 * 「{@code @Scheduled(cron=…)} 薄壳 + 服务里做逐租户循环」这一形态 ⇒ 本单**复用同款**，
 * 不引入新的调度基础设施（**不加 Quartz / 不加 ShedLock / 不新增 workflow**）。
 *
 * <h2>周期怎么定</h2>
 * 到期判定是**天粒度**（{@code shipped_at <= 现在 − N 天}）⇒ 周期只需远小于一天。
 * 缺省每小时一轮（比 5 分钟档省，比每天一档快 —— 满期后**最迟 1 小时**被完成），
 * 可用 {@code migao.order.auto-complete-scan-cron} 覆盖（缺省值只有这一处）。
 *
 * <h2>单机部署 / 集群部署（同一套代码，无需开关）</h2>
 * 本载体**不判断"我是不是 leader"**：并发安全来自
 * {@link com.migao.admin.mapper.OrderMapper#autoCompleteShippedOrders} 那条
 * **带谓词的原子 UPDATE + RETURNING id** —— 单实例和多实例各自照常扫，每一行仍只有一个事务能改到，
 * 另一侧 0 行、静默；站内信只发给真正被改到的行 ⇒ 集群下不会重复完成、也不会重复发信
 * （判据：{@code AutoCompleteShippedScanServiceTest} 的并发/幂等两条 +
 * {@code AutoCompleteShippedRealDbTest} 的真库双连接并发）。
 *
 * <h2>fail-soft（只兜"整轮炸"这一档）</h2>
 * 逐租户失败已由服务自己记 ERROR 并继续（判据：失败要显式）；这里只兜最后一次 ——
 * 调度线程不许被一次失败打死（与 {@link AutoBatchDueScanScheduler} 同款）。
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class AutoCompleteShippedScanScheduler {

    /**
     * 缺省扫描周期：每小时一轮（6 段 cron：秒 分 时 日 月 周）。
     *
     * <p>属性 {@code migao.order.auto-complete-scan-cron} 覆盖它 —— 缺省值只有这一处
     * （不在 yml 里再写一遍，两处缺省值必然漂移）。</p>
     */
    public static final String SCAN_DEFAULT_CRON = "0 7 * * * *";

    private final AutoCompleteShippedScanService autoCompleteShippedScanService;

    /** 发货后 N 天自动完成（每轮只做一件事：满期且仍在 {@code shipped} 的单 ⇒ 原子流转 {@code completed}）。 */
    @Scheduled(cron = "${migao.order.auto-complete-scan-cron:" + SCAN_DEFAULT_CRON + "}")
    public void scanShippedOrders() {
        try {
            autoCompleteShippedScanService.scanAndComplete();
        } catch (Exception e) {
            // 服务自己已逐租户兜住并记读数；这里是最后一道：调度线程不许被一次失败打死。
            log.error("{} 自动完成载体异常: {}", AutoCompleteShippedScanService.INCIDENT_FAILED,
                    e.getMessage(), e);
        }
    }
}
