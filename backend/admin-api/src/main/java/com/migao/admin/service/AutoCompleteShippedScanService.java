package com.migao.admin.service;

import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.Order;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.time.BusinessClock;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * 🔴 <b>「发货后 N 天自动完成订单」的判定与执行本体（issue #6262）——
 * 运行载体只负责"什么时候跑"，判断全在这里。</b>
 *
 * <h2>产品口径（用户 2026-10-03 逐字裁定，四选项中的 <b>B</b>）</h2>
 * 「<b>发货后 N 天自动完成，保留人工「确认收货」提前完成</b>」—— 否决了 A（发货即完成）/
 * C（保持现状）/ D（先接快递轨迹回写）。背景读数：真库 {@code status='shipped'} **21** 条 vs
 * {@code completed} **7** 条 ⇒ 订单积压在「已发货」等人点一下。
 *
 * <h2>判定锚点 = {@code orders.shipped_at}（V148）</h2>
 * 它由**两条发货路各自的条件 UPDATE**写入（{@code OrderService.transitionStatusAtomic} /
 * {@code OrderShipmentService.transition}）。为什么不复用既有列（现取读数，非推断）：
 * {@code order_logistics.shipped_at} 只在**新建物流行**时写（{@code OrderLogisticsWriter} 的 insert 分支），
 * 真库 21 条在架 shipped 里只有 15 条非空、全表 29 行里只有 16 条非空 ⇒ 拿它当锚点会静默漏单；
 * {@code order_shipments.shipped_at} 更差（全表 9 行、非空 1 行，只覆盖工人路）。
 *
 * <h2>并发安全（人工确认收货 vs 自动；<b>单机与集群同一套代码</b>）</h2>
 * 核心是<b>一条带谓词的原子 UPDATE</b>（{@link OrderMapper#autoCompleteShippedOrders}）：
 * {@code WHERE tenant_id=? AND status='shipped' AND shipped_at <= 死线 ... RETURNING id}。
 * <ul>
 *   <li><b>只生效一次</b>：PG 在行锁下重估谓词 ⇒ 人工先改完，自动这一侧 {@code status} 已不是
 *       {@code shipped} ⇒ 条件不满足 ⇒ **0 行**。反之亦然。</li>
 *   <li><b>拿 0 行的那一侧静默</b>：本类对 0 行**不抛错、不告警**（那是正常的并发结果，不是故障）。</li>
 *   <li><b>集群安全不靠锁</b>：N 个实例同时扫，每一行仍只有一个事务能改到；
 *       站内信只发给 {@code RETURNING} 回来的 id ⇒ 不会 N 份。**不需要** leader 选举 /
 *       advisory lock / ShedLock / Quartz（本仓既有立场：不加调度基础设施）。</li>
 * </ul>
 *
 * <h2>只动 {@code shipped}</h2>
 * 谓词里写死 {@code status = 'shipped'} ⇒ {@code pending/confirmed/producing/packed/cancelled/completed}
 * 一律不动。流转表也**不改**：{@code shipped → completed} 是 {@code OrderStatusTransitions}
 * 里**既有**的一条边，本类跑之前先过 {@link OrderStatusTransitions#assertTransitionAllowed}
 * （判定本体只有那一份，本类不自建第二张流转表）。
 *
 * <h2>N 可配置（缺省 7 天，<b>待人工确认的参数</b>）</h2>
 * 属性 {@code migao.order.auto-complete-days}，缺省值只有这一处
 * （{@link #DEFAULT_DAYS}；不在 yml 里再写一遍 —— 两处缺省值必然漂移）。改值**不必改码**。
 * 本单先按 7 天登记（issue 的「待人工确认」项）。
 *
 * <h2>时间源（判据：墙钟拼写守卫）</h2>
 * 「现在」只从 {@link BusinessClock} 取（本仓 {@code BusinessClockTestSourceGuardTest} 把
 * 无参的「今天 / 现在」读取（日期、日期时间、时刻三种）判为 FORBIDDEN）—— 定时任务里最容易撞这条。
 *
 * <h2>可观测 + 失败显式（不静默吞异常）</h2>
 * 每轮发一条 INFO 读数（扫了几个租户 / 完成了几张 / 失败几条）并返回
 * {@link Outcome}；逐租户失败**逐条**记 ERROR（一个租户炸了不影响其余租户），
 * 载体的兜底 catch 只兜"整轮炸"这一档。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class AutoCompleteShippedScanService {

    /** 缺省 N = 7 天（**待人工确认的参数**；属性 {@code migao.order.auto-complete-days} 覆盖它）。 */
    public static final int DEFAULT_DAYS = 7;

    /** 定时腿完成订单的痕迹标记（可 grep：这一行日志 = 自动完成的动作面）。 */
    public static final String TRACE_AUTO_COMPLETE = "AUTO_COMPLETE_SHIPPED_ORDERS";

    /** 定时腿失败的 incident 标记：`grep INCIDENT_AUTO_COMPLETE_SHIPPED_FAILED`。 */
    public static final String INCIDENT_FAILED = "INCIDENT_AUTO_COMPLETE_SHIPPED_FAILED";

    /**
     * N 天（发货后满 N 天自动完成）。缺省 {@link #DEFAULT_DAYS}。
     *
     * <p>可配置是硬要求（issue #6262）：改配置即可调参，不必改代码 —— PR body 里显式登记
     * 「缺省值待人工确认」。</p>
     */
    @Value("${migao.order.auto-complete-days:" + DEFAULT_DAYS + "}")
    private int autoCompleteDays = DEFAULT_DAYS;

    private final OrderMapper orderMapper;
    private final NotificationService notificationService;
    private final BusinessClock businessClock;

    /**
     * 一轮扫描的读数（可观测面：出问题时能归因到"扫到多少 / 完成多少 / 谁失败了"）。
     *
     * @param scannedTenants  本轮扫到的候选租户数（超集预筛的结果）
     * @param completedOrders 本轮**真的**被自动完成的订单 id（= SQL {@code RETURNING} 回来的行）
     * @param failures        本轮失败（逐租户；逐条可行动）
     */
    public record Outcome(int scannedTenants, List<String> completedOrders, List<String> failures) {

        public int completedCount() {
            return completedOrders.size();
        }
    }

    /** 当前的 N（天）—— 可观测 / 测试可读。 */
    public int days() {
        return autoCompleteDays;
    }

    /** 当前轮次的死线 = 业务「现在」 − N 天（**只判负向**：更晚发货的单不会被碰到）。 */
    public OffsetDateTime deadline() {
        return businessClock.nowOffset().minusDays(autoCompleteDays);
    }

    /**
     * 🔴 <b>跑一轮自动完成</b>（运行载体调它；测试也调它）。
     *
     * <p>本方法**不抛**「某个租户失败」：逐租户失败记进 {@link Outcome#failures()} 并逐条 ERROR，
     * 其余租户继续扫 —— 一个租户的坏数据不许把这条腿整轮打死（同 {@code AutoBatchDueScanService}
     * 的逐租户处置）。整轮级别的异常（连候选租户都查不出来）仍会抛出，由载体兜底。</p>
     */
    public Outcome scanAndComplete() {
        // 🔴 判定本体只有一份（本仓唯一的状态机实现）：动手之前先按流转表断言本次动作合法。
        // 这条断言让「流转表被改小 / shipped 不再是 completed 的出口」当场抛 —— 而不是让本类
        // 悄悄把一批单改成流转表里不存在的目标态（本单**不改** STATUS_TRANSITIONS）。
        OrderStatusTransitions.assertTransitionAllowed("shipped", "completed");
        List<Long> tenants = orderMapper.selectShippedTenantIds();
        List<String> completed = new ArrayList<>();
        List<String> failures = new ArrayList<>();
        // 调度线程没有请求上下文 ⇒ 必须**显式**设置租户（漏了这一步会让经拦截器的 SQL 拿不到租户）。
        // 线程是复用的 ⇒ 退出时**必须**还原，不能把租户上下文漏给下一个用这条线程的任务。
        Long previous = TenantContext.getTenantId();
        OffsetDateTime deadline = deadline();
        int scanned = 0;
        try {
            for (Long tenantId : tenants == null ? List.<Long>of() : tenants) {
                if (tenantId == null) {
                    continue;
                }
                scanned++;
                TenantContext.setTenantId(tenantId);
                try {
                    completed.addAll(completeTenant(tenantId, deadline));
                } catch (RuntimeException e) {
                    failures.add("tenant=" + tenantId + ": " + e);
                    log.error("{} tenant={} 自动完成失败（其余租户继续）: {}",
                            INCIDENT_FAILED, tenantId, e.toString(), e);
                } finally {
                    reload(previous);
                }
            }
        } finally {
            reload(previous);
        }
        // 判据 6（可观测）：每轮都留读数 —— 「扫了几个租户 / 完成几张 / 失败几条」。
        log.info("{} 本轮扫描租户={}, 自动完成={} 张, 失败={} 条, N={} 天, 死线={}",
                TRACE_AUTO_COMPLETE, scanned, completed.size(), failures.size(), autoCompleteDays,
                deadline);
        if (!failures.isEmpty()) {
            log.error("{} 本轮 {} 条失败: {}", INCIDENT_FAILED, failures.size(), failures);
        }
        return new Outcome(scanned, List.copyOf(completed), List.copyOf(failures));
    }

    /**
     * 单租户一轮：**一条**原子 UPDATE 拿回"真正被完成的行"，再对**这些行**发站内信。
     *
     * <p>⚠️ 顺序是刻意的：副作用绑定 {@code RETURNING} 的 id，**不是**绑定"本轮扫到多少单"
     * —— 后者在集群下会让每个实例各发一遍（本单最易踩的坑）。</p>
     */
    private List<String> completeTenant(Long tenantId, OffsetDateTime deadline) {
        List<String> completedIds = orderMapper.autoCompleteShippedOrders(tenantId, deadline);
        if (completedIds == null || completedIds.isEmpty()) {
            // 0 行 = 本轮无单满期，**或**人工确认收货已经抢先改了（并发正常结果）⇒ 静默，不报错不告警。
            return List.of();
        }
        for (String orderId : completedIds) {
            notifyCompleted(tenantId, orderId);
        }
        log.info("{} tenant={} 自动完成 {} 张: {}", TRACE_AUTO_COMPLETE, tenantId,
                completedIds.size(), completedIds);
        return completedIds;
    }

    /**
     * 站内信：与人工路的既有语义一致（{@code order_status_changed} 事件 + 中文状态标签）。
     *
     * <p>标签取自 {@link OrderStatusTransitions#label} —— 与 {@code OrderService} 的
     * {@code notifyOrderStatusChanged} **同一个**单一来源（不抄第二份状态文案表）。</p>
     *
     * <p>发信失败**不**回滚 / 不抛出：状态已经落库（SQL 已提交），这里失败只该是一条可检索的
     * 痕迹 —— 与 {@code OrderService.notifyOrderStatusChanged} 同口径（站内信是副作用，不是正确性前提）。</p>
     */
    private void notifyCompleted(Long tenantId, String orderId) {
        try {
            Order order = orderMapper.selectById(orderId);
            if (order == null || order.getUserId() == null || order.getUserId().isBlank()) {
                // 无归属用户（商户代录）⇒ 无收件人，跳过（与人工路逐字同口径）
                return;
            }
            Map<String, String> ctx = new HashMap<>();
            ctx.put("recipientId", order.getUserId());
            ctx.put("recipientType", "user");
            ctx.put("orderNo", order.getOrderNo() != null ? order.getOrderNo() : order.getId());
            ctx.put("status", OrderStatusTransitions.label("completed"));
            notificationService.triggerByEvent(tenantId, "order_status_changed", ctx);
        } catch (RuntimeException e) {
            log.warn("[notify] 自动完成站内信发送失败，忽略: orderId={}, error={}", orderId, e.getMessage());
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
}
