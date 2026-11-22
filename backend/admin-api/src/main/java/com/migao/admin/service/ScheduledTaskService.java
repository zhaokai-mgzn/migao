package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.migao.admin.time.BusinessClock;
import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.CreateNotificationRequest;
import com.migao.admin.dto.agent.AgentScheduledTaskRequest;
import com.migao.admin.entity.ScheduledTask;
import com.migao.admin.entity.Tenant;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.ScheduledTaskMapper;
import com.migao.admin.mapper.TenantMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.time.Duration;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/**
 * 定时任务（用户「预约」）服务 —— issue #6486 包 1。
 *
 * <p><b>一句话</b>：把「到点该提醒的事」存成待办，由 {@link com.migao.admin.config.ScheduledTaskScanScheduler}
 * 每分钟把到期的投递成站内通知。</p>
 *
 * <h2>三条不变量（改这个类之前先读）</h2>
 * <ol>
 *   <li><b>三件套 fail-closed</b>：{@code criterion} / {@code actionLabel} / {@code actionUrl} 任一为空 ⇒
 *       <b>不建单</b>（抛 {@link BusinessException}）。库里那三列也是 {@code NOT NULL}（双保险）。
 *       理由：主动引擎的「没有处置入口的不发」在本能力里**前移为建单期拒绝** ——
 *       运行期丢弃会让「为什么这条没发」变成不可见的静默面，建单期拒绝则当场可归因。</li>
 *   <li><b>幂等</b>：同租户 + 同 {@code dedupKey} ⇒ 只建一条（命中即返回既有行，不抛错 ——
 *       重复建单是调用方的正常重试，不是业务错误）。</li>
 *   <li><b>只读投递</b>：到点只写 {@code notifications}，<b>不执行任何业务写</b>（不下单 / 不改价 /
 *       不发货）。要写必须回到会话等人点确认 —— 这是 L1 提醒型的硬边界，别在本类里加业务写。</li>
 * </ol>
 *
 * <h2>疲劳控制（与主动引擎同口径）</h2>
 * 只有 {@code status='pending'} 会被投递；投递后置 {@code fired}（<b>不重投</b>）、可被
 * {@link #cancel} 置 {@code cancelled}；单轮每租户有条数上限（超出的下轮再投，<b>不丢，只延后</b>）。
 *
 * <h2>多实例（集群 P0-2 / issue #9019）：原子领取 + 通知幂等 + 租约回收</h2>
 * 本类的扫描腿**不是**「读 pending → 发通知 → 改状态」的 read-modify-write（那样 N 个实例会发 N 条
 * 重复提醒）。三层合起来才有「恰好一次」的**可观察效果**：
 * <ol>
 *   <li><b>原子领取</b>（{@code ScheduledTaskMapper#claimDueByTenant}）：一条
 *       {@code UPDATE … WHERE status='pending' … RETURNING} 完成「判定 + 占位（{@code firing}）+ 取回」
 *       ⇒ 同一行只有一个实例领得到，输家 0 行静默跳过；</li>
 *   <li><b>通知幂等</b>：投递带稳定 {@code dedupeKey = scheduled_task:{taskId}}（V187 的唯一索引兜底）
 *       ⇒ 租约回收后的**重投**、或崩溃前已插入但未置终态的重放，都不会变成第二条站内信；</li>
 *   <li><b>租约回收</b>（{@link #CLAIM_LEASE_TIMEOUT}）：领取后实例崩溃 ⇒ 行停在 {@code firing}；
 *       每轮扫描先把超过租约仍未终态的行放回 {@code pending}，下次重新领取（不永久卡死）。</li>
 * </ol>
 * ⇒ 语义是「**至少投递一次 + 幂等**」，员工侧看到的就是「恰好一条」。
 *
 * <h2>fail-soft</h2>
 * 与 {@code AutoBatchDueScanService} / {@code DailyBriefingService} 同款：单条失败不拖垮整轮、
 * 单租户失败不拖垮其它租户。incident 常量可 grep：
 * {@link #INCIDENT_SCAN_FAILED} / {@link #INCIDENT_DELIVER_FAILED}。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class ScheduledTaskService {

    /** 扫描轮级失败（可 grep）。 */
    public static final String INCIDENT_SCAN_FAILED = "SCHEDULED_TASK_SCAN_FAILED";

    /** 单条投递失败（可 grep）。 */
    public static final String INCIDENT_DELIVER_FAILED = "SCHEDULED_TASK_DELIVER_FAILED";

    /** 租约回收失败（可 grep）：回收腿自身出错不拖垮本轮扫描。 */
    public static final String INCIDENT_LEASE_RECLAIM_FAILED = "SCHEDULED_TASK_LEASE_RECLAIM_FAILED";

    /** 领取租约已失效（可 grep）：投递完成了但终态写不进去（行已被回收/被别的实例领走）。 */
    public static final String INCIDENT_CLAIM_LOST = "SCHEDULED_TASK_CLAIM_LOST";

    /**
     * 领取租约超时：领取后超过这么久仍停在 {@code firing} ⇒ 视为领取实例已死，回收成 {@code pending}。
     *
     * <p>定 5 分钟的理由：扫描周期是 1 分钟，一条投递是「一次 insert + 一次 update」的量级
     * （毫秒级）；5 分钟 ≫ 正常投递耗时，又 ≪ 「用户能忍多久没收到提醒」的尺度
     * ⇒ 崩溃后最迟约 5~6 分钟自动重投。**不能定得太小**：活得慢的实例会被误回收
     * （虽然通知幂等键会兜住重复提醒，但会白白多打一轮）。</p>
     */
    static final Duration CLAIM_LEASE_TIMEOUT = Duration.ofMinutes(5);

    /**
     * 单轮单租户最多投递条数。
     *
     * <p>这是**疲劳控制**的一半（另一半是投递后不再重投）：一次扫描不许把积压全推给用户。
     * 超出的仍是 {@code pending} ⇒ 下一轮继续，**不丢**。</p>
     */
    static final int SCAN_BATCH_LIMIT = 50;

    /** 读面单次上限。 */
    static final int LIST_LIMIT = 200;

    private final ScheduledTaskMapper scheduledTaskMapper;
    private final TenantMapper tenantMapper;
    private final NotificationService notificationService;
    private final BusinessClock businessClock;

    /**
     * 本实例的领取者标识（写进 {@code claimed_by}；同时是终态 CAS 的 fencing token）。
     *
     * <p>每实例一个随机值（不是 hostname：同机多进程也要区分）。不持久化 —— 实例重启就是新的领取者，
     * 旧领取留下的 {@code firing} 行走租约回收（这正是回收存在的理由）。</p>
     */
    private final String claimOwner = "sched-" + UUID.randomUUID();

    // ==================== 写面（建单 / 取消） ====================

    /**
     * 建一条待办。
     *
     * @param tenantId    租户（取自认证上下文，调用方不得从 body 取）
     * @param recipientId 收件人（= 建单者自己；取自认证上下文，body 伪造不了）
     * @return 新建的待办；**幂等命中时返回既有那一行**
     */
    @Transactional
    public ScheduledTask create(Long tenantId, String recipientId, AgentScheduledTaskRequest request) {
        // ① 三件套 fail-closed（不变量 1）—— 字段校验之外的第二道：
        //    本方法也可被非 HTTP 调用方直达（包 2 的工具走的就是内部端点）
        requireText(request.getCriterion(), "criterion", "判据");
        requireText(request.getActionLabel(), "actionLabel", "处置入口文案");
        requireText(request.getActionUrl(), "actionUrl", "处置入口地址");
        if (request.getFireAt() == null) {
            throw new BusinessException("VALIDATION_ERROR", "触发时刻不能为空", 422);
        }
        requireText(request.getTaskType(), "taskType", "任务类型");
        requireText(recipientId, "recipientId", "收件人");

        // ② 幂等（不变量 2）
        String dedupKey = StringUtils.hasText(request.getDedupKey())
                ? request.getDedupKey()
                : deriveDedupKey(recipientId, request);
        ScheduledTask existing = scheduledTaskMapper.selectByDedupKey(tenantId, dedupKey);
        if (existing != null) {
            log.info("[ScheduledTask] 幂等命中，不重复建单: tenantId={}, dedupKey={}", tenantId, dedupKey);
            return existing;
        }

        ScheduledTask task = ScheduledTask.builder()
                .tenantId(tenantId)
                .taskType(request.getTaskType())
                .subjectType(StringUtils.hasText(request.getSubjectType())
                        ? request.getSubjectType() : "employee")
                .subjectId(StringUtils.hasText(request.getSubjectId())
                        ? request.getSubjectId() : recipientId)
                .fireAt(request.getFireAt())
                .criterion(request.getCriterion())
                .impact(request.getImpact() != null ? request.getImpact() : Map.of())
                .actionLabel(request.getActionLabel())
                .actionUrl(request.getActionUrl())
                .payload(request.getPayload() != null ? request.getPayload() : Map.of())
                .source(ScheduledTask.SOURCE_USER)
                .status(ScheduledTask.STATUS_PENDING)
                .dedupKey(dedupKey)
                .deleted(0)
                .build();
        try {
            scheduledTaskMapper.insert(task);
        } catch (DuplicateKeyException e) {
            // 🔴 并发下的**冲突映射**（不是重复的防御性代码）：两个请求可以**同时**通过上面的
            // `selectByDedupKey` 检查（检查-再插入之间的窗口），此时唯一索引
            // `uk_scheduled_tasks_tenant_dedup` 兜底拦下第二条 —— 把它映射回「返回既有行」，
            // 语义与第一次命中完全相同（幂等）。不映射 ⇒ 并发重试暴露成 500。
            // 判据：`tests/unit_ci_workflows/test_idempotent_unique_write_guard.py`
            // （唯一键写入点必须**登记**：要么原子写、要么冲突映射；本处 = 冲突映射）。
            ScheduledTask raced = scheduledTaskMapper.selectByDedupKey(tenantId, dedupKey);
            if (raced == null) {
                // 不是本键的冲突（比如主键重复）⇒ 照常抛，不吞
                throw e;
            }
            log.info("[ScheduledTask] 并发建单撞唯一索引，返回既有行: tenantId={}, dedupKey={}",
                    tenantId, dedupKey);
            return raced;
        }
        log.info("[ScheduledTask] 建单: id={}, tenantId={}, fireAt={}, type={}",
                task.getId(), tenantId, task.getFireAt(), task.getTaskType());
        return task;
    }

    /**
     * 取消一条待办。
     *
     * @return {@code true} = 本次真的取消了；{@code false} = 不存在 / 不属于本租户 / 已不是 pending
     */
    @Transactional
    public boolean cancel(Long tenantId, String taskId) {
        ScheduledTask task = scheduledTaskMapper.selectById(taskId);
        // 租户归属显式比对（RLS + 拦截器已保证，但换数据源时不能靠它们静默兜底）
        if (task == null || !tenantId.equals(task.getTenantId())
                || !Integer.valueOf(0).equals(task.getDeleted())) {
            return false;
        }
        // 已 fired 的取消没有意义：消息已发出（notifications 不可撤回）
        if (!ScheduledTask.STATUS_PENDING.equals(task.getStatus())) {
            return false;
        }
        scheduledTaskMapper.updateById(task.toBuilder()
                .status(ScheduledTask.STATUS_CANCELLED)
                .updatedAt(businessClock.nowOffset())
                .build());
        log.info("[ScheduledTask] 取消: id={}, tenantId={}", taskId, tenantId);
        return true;
    }

    // ==================== 读面 ====================

    public List<ScheduledTask> list(Long tenantId, String status) {
        return scheduledTaskMapper.selectByTenant(tenantId, status, LIST_LIMIT);
    }

    // ==================== 扫描与投递（调度线程） ====================

    /**
     * 扫描所有租户的到期待办并投递。返回本轮真的投出去几条。
     *
     * <p>🔴 <b>必须逐租户设置 {@link TenantContext}</b>：调度线程没有 JWT Filter，
     * {@code TenantLineInnerInterceptor} 在无上下文时抛「Tenant context not initialized」
     * （issue #3957 —— 生产上曾让每轮调度整体夭折）。本方法照 {@code DailyBriefingService#generateDueTenants}
     * 的同款写法（内层再设同值为幂等 no-op）。</p>
     */
    public int scanDue() {
        OffsetDateTime now = businessClock.nowOffset();
        // 补偿腿：先把「领取后实例崩溃」的超时 firing 放回 pending（跨租户一条原子 UPDATE）。
        // 放在逐租户循环**之前**：回收对象是「所有租户里已超时的领取」，不需要租户上下文。
        reclaimStaleClaims(now);
        List<Tenant> tenants = tenantMapper.selectList(new LambdaQueryWrapper<>());
        int delivered = 0;
        for (Tenant tenant : tenants) {
            Long previousTenantId = TenantContext.getTenantId();
            TenantContext.setTenantId(tenant.getId());
            try {
                delivered += deliverDueForTenant(tenant.getId(), now);
            } catch (Exception e) {
                // 单租户失败不拖垮其它租户（fail-soft）
                log.error("{} tenantId={}: {}", INCIDENT_SCAN_FAILED, tenant.getId(), e.getMessage(), e);
            } finally {
                if (previousTenantId != null) {
                    TenantContext.setTenantId(previousTenantId);
                } else {
                    TenantContext.clear();
                }
            }
        }
        return delivered;
    }

    private int deliverDueForTenant(Long tenantId, OffsetDateTime now) {
        // 🔴 原子领取（集群 P0-2）：判定 + 占位 + 取回同一条语句 ⇒ 同一行只有一个实例领得到。
        // 拿不到行 = 本轮无到期，或全被别的实例先领走 —— 都不是错误，静默跳过（下一轮再看）。
        List<ScheduledTask> due = scheduledTaskMapper.claimDueByTenant(
                tenantId, now, SCAN_BATCH_LIMIT, claimOwner);
        int delivered = 0;
        for (ScheduledTask task : due) {
            try {
                if (deliver(task, now)) {
                    delivered++;
                }
            } catch (Exception e) {
                log.error("{} taskId={} tenantId={}: {}",
                        INCIDENT_DELIVER_FAILED, task.getId(), tenantId, e.getMessage(), e);
                markFailed(task, now);
            }
        }
        return delivered;
    }

    /**
     * 投递一条：写站内通知 + 置 {@code fired}。
     *
     * <p>🔴 <b>本方法是「只读投递」的落点</b>：它只想 {@code notifications}，不做任何业务写。
     * 加业务写 = 越过 L1 边界（见类 javadoc 不变量 3）。</p>
     *
     * <p>通知带**稳定幂等键**（{@code scheduled_task:{taskId}}）：租约回收后的重投、崩溃前插入但未置
     * 终态的重放，都只会落一条站内信（V187 的 {@code uk_notifications_dedupe} 是最终保证，
     * {@link NotificationService} 把唯一冲突映射成「已发」）。</p>
     *
     * @return {@code true} = 本次投递成功且终态写入成功；{@code false} = 租约已失效（不算投递成功）
     */
    private boolean deliver(ScheduledTask task, OffsetDateTime now) {
        CreateNotificationRequest request = new CreateNotificationRequest();
        request.setRecipientId(task.getSubjectId());
        request.setRecipientType(StringUtils.hasText(task.getSubjectType())
                ? task.getSubjectType() : "employee");
        request.setTitle(task.getActionLabel());
        request.setContent(task.getCriterion());
        request.setChannel("internal");
        notificationService.createNotification(task.getTenantId(), request, notificationDedupeKey(task));

        int updated = scheduledTaskMapper.markFiredIfClaimed(
                task.getId(), task.getTenantId(), claimOwner, now);
        if (updated == 0) {
            // 行已被回收（租约超时）或被我之外的领取者重新领走 ⇒ 终态不该由我写。
            // 通知那条已被幂等键挡住，不会重复提醒；这里只留可 grep 的痕迹。
            log.warn("{} taskId={}：租约已失效，跳过置 fired", INCIDENT_CLAIM_LOST, task.getId());
            return false;
        }
        return true;
    }

    /**
     * 投递幂等键：一条待办只允许落**一条**站内通知。
     *
     * <p>稳定的原因：{@code scheduled_tasks.id} 是建单期生成的 UUID，投递/重投/回收重放都指向同一行
     * ⇒ 同一个键。V187 的唯一索引 {@code uk_notifications_dedupe} 只对非 NULL 键生效。</p>
     */
    static String notificationDedupeKey(ScheduledTask task) {
        return "scheduled_task:" + task.getId();
    }

    /**
     * 租约回收一轮：把「领取后实例崩溃」留下的 {@code firing} 行放回 {@code pending}。
     *
     * <p>一条跨租户原子 UPDATE（时效谓词在 SQL 里，见
     * {@code ScheduledTaskMapper#reclaimStaleClaims}）⇒ 幂等、活实例不被误回收。</p>
     *
     * @return 本轮回收行数（0 = 没有僵尸领取）
     */
    int reclaimStaleClaims(OffsetDateTime now) {
        try {
            int reclaimed = scheduledTaskMapper.reclaimStaleClaims(
                    now.minus(CLAIM_LEASE_TIMEOUT), now);
            if (reclaimed > 0) {
                log.warn("[ScheduledTask] 租约回收：{} 条 firing 超过 {} 未终态，已放回 pending",
                        reclaimed, CLAIM_LEASE_TIMEOUT);
            }
            return reclaimed;
        } catch (Exception e) {
            // 补偿腿失败**不拖垮**本轮扫描（fail-soft）：回收是兜底，不是投递的前提。
            log.error("{} : {}", INCIDENT_LEASE_RECLAIM_FAILED, e.getMessage(), e);
            return 0;
        }
    }

    /** 单条投递失败 ⇒ 置 {@code failed}（可归因；不静默留 pending 反复重试打扰用户）。 */
    private void markFailed(ScheduledTask task, OffsetDateTime now) {
        try {
            scheduledTaskMapper.markFailedIfClaimed(task.getId(), task.getTenantId(), claimOwner, now);
        } catch (Exception e) {
            log.error("{} 置 failed 亦失败 taskId={}: {}",
                    INCIDENT_DELIVER_FAILED, task.getId(), e.getMessage());
        }
    }

    // ==================== 工具方法 ====================

    /**
     * 派生幂等键：收件人 + 任务类型 + 触发时刻（秒级精度）。
     *
     * <p>调用方愿意的话可以传自己的 {@code dedupKey} 覆盖它。派生键的语义 = 「同一个人、
     * 同一类事、同一个时刻 ⇒ 只提醒一次」。</p>
     */
    private static String deriveDedupKey(String recipientId, AgentScheduledTaskRequest request) {
        long epochSecond = request.getFireAt().toEpochSecond();
        return recipientId + ":" + request.getTaskType() + ":" + epochSecond;
    }

    private static void requireText(String value, String field, String label) {
        if (!StringUtils.hasText(value)) {
            throw new BusinessException("VALIDATION_ERROR", label + "（" + field + "）不能为空", 422);
        }
    }
}
