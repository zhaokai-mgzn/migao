package com.migao.admin.service;

import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.AgentBatch;
import com.migao.admin.mapper.AgentBatchMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.UUID;

/**
 * 批次后台 job 的**执行租约**（issue #8285；表 {@code agent_batches} 的两列由迁移 V208 引入）。
 *
 * <h2>为什么它必须落库（而不是进程内）</h2>
 * #8283 的批次 job 跑在进程内线程池里，只有优雅停机罩着。JVM 崩溃 / 强杀 / 容器被摘后，进程里没有任何
 * 东西还记得「这批是谁在跑」⇒ 批次永远停在 {@code executing}（既不能重试也不能撤销）；多实例时更不能
 * 做全量回收（B 实例会误杀 A 实例正在跑的批次）。⇒ 判定依据只能是**跨进程可见的事实**：
 * {@code executor_id}（实例 + job）与 {@code heartbeat_at}（执行中定期刷新）。
 *
 * <h2>三个动作（判定全在 SQL 谓词里，不靠调用方自觉）</h2>
 * <ol>
 *   <li>{@link #newExecutorId()}：claim 时与状态迁移写在**同一条** UPDATE 里（不存在「executing 但心跳为空」
 *       的窗口 —— 那个窗口会被回收器当成崩溃遗留）；</li>
 *   <li>{@link #renewLease}：每条明细前续心跳 + 用 {@code executor_id} 谓词确认「仍归我跑」；0 行 ⇒ 停手；</li>
 *   <li>{@link #recoverStaleExecuting()}：把「心跳超时 / 从未心跳」的 {@code executing} 收回成
 *       <b>可撤销的 {@code partial}</b>。心跳新鲜 ⇒ 0 行（不误杀活 job）；状态已不是 executing ⇒ 0 行
 *       （幂等 + 不覆盖终态）；只改批次行、不碰明细（不伪造 item 成功）。</li>
 * </ol>
 *
 * <h2>边界（如实登记，不许读成「已精确复原」）</h2>
 * <ul>
 *   <li>回收时「已 apply 但 item 状态未落库」的窗口**仍然存在**（与进程内崩溃同族）—— 本类只保证
 *       <b>状态可回收 + 可撤销</b>，不承诺精确到条目的自动复原（需要时另开对账单）。</li>
 *   <li>心跳按**明细**刷新 ⇒ 单条明细耗时超过 {@link #LEASE_TIMEOUT_SECONDS} 时活 job 也可能被回收；
 *       那种情况下原 job 的终态写因 fencing 谓词（{@code executor_id}）落 0 行 —— 不会覆盖回收结果。</li>
 *   <li>不判断「我是不是 leader」：每个实例各自扫，幂等与互斥都来自那条原子 UPDATE。</li>
 * </ul>
 *
 * <p><b>为什么是独立类</b>：租约是**独立关切**（标识 / 续期 / 回收），且 {@code AgentBatchService}
 * 已越过仓内 800 行棘轮（{@code tests/unit_ci_workflows/test_loc_ratchet.py}）—— 把租约留在一个类里会
 * 逼着登记「大文件豁免」（那是门禁放宽）。拆开后两者各司其职：本类只碰租约三件事，
 * 批次状态机 / 逐条执行仍在 {@link AgentBatchService}。</p>
 */
@Slf4j
@Service
public class AgentBatchLeaseService {

    /**
     * 租约超时（秒）：超过它没有心跳的 {@code executing} 批次视为「执行者已死」⇒ 可回收成 {@code partial}。
     *
     * <p>为什么是 180s：心跳在**每条明细前**刷新，而单条明细是普通 DB 写（实测毫秒级）⇒ 正常执行时
     * 无心跳时长 ≈ 单条明细耗时。取 180s 是给「单条明细偶发慢（锁等待 / GC / 网络抖动）」留余量，
     * 同时把「崩溃后多久可撤销」压在 3 分钟内。</p>
     */
    public static final long LEASE_TIMEOUT_SECONDS = 180;

    /** 本进程的实例标识（只算一次）—— {@code executor_id} = 实例 + job，见 {@link #newExecutorId()}。 */
    private static final String INSTANCE_ID = resolveInstanceId();

    private final AgentBatchMapper batchMapper;

    public AgentBatchLeaseService(AgentBatchMapper batchMapper) {
        this.batchMapper = batchMapper;
    }

    /** 一轮回收的读数（调度载体打日志 / 判据复算用；**无副作用**）。 */
    public record LeaseRecoveryOutcome(int scannedTenants, int recoveredBatches) {
    }

    /**
     * 新 job 的执行者标识 = **实例 + job**（{@code <实例>#<pid>/<job uuid>}）。
     *
     * <p>两段都是必需的：实例段让「跨实例回收」能回答「这批复属于哪个进程」；job 段让**同一实例**上
     * 前后两条 job 不会互相认领（否则回收后重启的新 job 会被当成「还是它」⇒ 心跳伪造成功）。
     * 只写实例 = 同实例多 job 串号；只写 job = 跨实例不可归因。</p>
     */
    public String newExecutorId() {
        return INSTANCE_ID + "/" + UUID.randomUUID();
    }

    /**
     * 心跳续期 + **租约校验**：{@code 1} 行 = 仍归本 job；{@code 0} 行 = 已被回收 / 换人 ⇒ 调用方
     * **立刻停手**（不再 apply，也不落终态 —— 已 apply 的照旧是 success，未动的保持 pending）。
     *
     * <p>按明细续期而不是起后台心跳线程：明细是普通 DB 写（秒级），逐条续期已把「无心跳时长」压到
     * 单条明细的行时间；独立线程要多一份生命周期与关停面（最少代码阶梯）。</p>
     */
    public boolean renewLease(Long tenantId, AgentBatch batch) {
        OffsetDateTime now = OffsetDateTime.now();
        if (batchMapper.heartbeat(batch.getId(), tenantId, batch.getExecutorId(), now) == 0) {
            log.warn("[Agent] 批次租约已失效（心跳 CAS 0 行 ⇒ 已被回收 / 换人），停止剩余条目: "
                    + "batchId={}, executor={}", batch.getId(), batch.getExecutorId());
            return false;
        }
        batch.setHeartbeatAt(now);
        return true;
    }

    /**
     * 🔴 **崩溃回收**（运行载体 = {@code AgentBatchLeaseRecoveryScheduler}）：把「心跳超时 / 从未心跳」的
     * {@code executing} 批次收回成 {@code partial}（可撤销）。
     *
     * <p>判定**全在那一条 SQL 的谓词里**（见 {@link AgentBatchMapper#markStaleExecutingPartial}）——
     * 于是并发 / 多实例下不需要任何锁或 leader 选举：心跳新鲜 ⇒ 0 行；重复回收 ⇒ 0 行；终态不在谓词内。
     * 调度线程没有请求上下文 ⇒ 先取「有活跃批次的租户」超集清单，再逐租户回收；逐租户失败只记 ERROR、
     * 不打断整轮，租户上下文退出即还原。</p>
     *
     * @return 本轮扫了几个租户、真正回收了几批（0 是正常结果：没有崩溃遗留）
     */
    public LeaseRecoveryOutcome recoverStaleExecuting() {
        OffsetDateTime now = OffsetDateTime.now();
        OffsetDateTime staleBefore = now.minusSeconds(LEASE_TIMEOUT_SECONDS);
        List<Long> tenants = batchMapper.selectExecutingTenantIds();
        int scanned = 0;
        int recovered = 0;
        Long previous = TenantContext.getTenantId();
        try {
            for (Long tenantId : tenants == null ? List.<Long>of() : tenants) {
                if (tenantId == null) {
                    continue;
                }
                scanned++;
                TenantContext.setTenantId(tenantId);
                try {
                    // 一条语句就是全部判定：心跳新鲜 / 已进终态 / 已回收过 ⇒ 0 行
                    int rows = batchMapper.markStaleExecutingPartial(tenantId, staleBefore, now);
                    if (rows == 0) {
                        continue;
                    }
                    recovered += rows;
                    log.warn("[Agent] 回收心跳超时的 executing 批次（执行者已死，状态置 partial 可撤销）: "
                            + "tenantId={}, rows={}, 截止={}", tenantId, rows, staleBefore);
                } catch (RuntimeException e) {
                    log.error("[Agent] 批次回收逐租户失败（其余租户继续）: tenantId={}, error={}",
                            tenantId, e.toString(), e);
                } finally {
                    restoreTenant(previous);
                }
            }
        } finally {
            restoreTenant(previous);
        }
        if (recovered > 0) {
            log.warn("[Agent] 本轮批次回收汇总: 扫描租户={}, 回收批次={}, 超时={}s",
                    scanned, recovered, LEASE_TIMEOUT_SECONDS);
        }
        return new LeaseRecoveryOutcome(scanned, recovered);
    }

    /** 实例标识：显式 {@code MIGAO_INSTANCE_ID}（容器编排可注入）优先，否则 {@code HOSTNAME#pid}。 */
    private static String resolveInstanceId() {
        String explicit = System.getenv("MIGAO_INSTANCE_ID");
        if (explicit != null && !explicit.isBlank()) {
            return explicit.trim();
        }
        String host = System.getenv("HOSTNAME");
        if (host == null || host.isBlank()) {
            host = "local";
        }
        return host + "#" + ProcessHandle.current().pid();
    }

    /** 还原调度线程的租户上下文（线程复用 —— 不许把租户漏给下一个任务）。 */
    private static void restoreTenant(Long tenantId) {
        if (tenantId == null) {
            TenantContext.clear();
        } else {
            TenantContext.setTenantId(tenantId);
        }
    }
}
