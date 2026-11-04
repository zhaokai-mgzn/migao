// case_ids: MC-197
package com.migao.admin.service;

import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.AgentBatch;
import com.migao.admin.mapper.AgentBatchMapper;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import java.time.OffsetDateTime;
import java.util.Arrays;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 批次**执行租约**的单元判据（issue #8285；真库谓词面在 {@code AgentBatchLeaseRecoveryRealDbTest}）。
 *
 * <p>本类只裁「Java 侧必须自己保证」的三件事 —— 它们都不是 SQL 能替代的：</p>
 * <ol>
 *   <li>{@code executor_id} = <b>实例段 + job 段</b>：两段缺一都不行（只写实例 ⇒ 同实例多 job 串号；
 *       只写 job ⇒ 跨实例不可归因）；</li>
 *   <li>心跳 CAS 0 行 ⇒ {@link AgentBatchLeaseService#renewLease} 必须返回 {@code false} 且**不刷新**内存心跳
 *       （调用方据此停手；这里判「信号是否可信」，停手后的行为由 {@code AgentBatchServiceTest} 判）；</li>
 *   <li>回收的**编排**：跨租户取数 → 逐租户设/还原上下文 → 逐租户失败不打断整轮（fail-soft）→ 汇总读数。
 *       SQL 谓词本身（心跳新鲜 0 行 / 幂等 / 不覆盖终态）由真库判据裁，这里**不重复**替它背书。</li>
 * </ol>
 *
 * <p>⚠️ 边界（照实登记）：本类用 mock mapper ⇒ 它证明的是「服务层怎么调、怎么算、怎么兜」，
 * 不证明「SQL 谓词真的拦住活 job」—— 后者只能在真 PG 上判（mock 的 {@code @Update} 恒返回 1）。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class AgentBatchLeaseServiceTest {

    private static final Long TENANT = 8285L;

    private static final Long OTHER_TENANT = 8286L;

    @Mock
    AgentBatchMapper batchMapper;

    @InjectMocks
    AgentBatchLeaseService leaseService;

    @AfterEach
    void clearTenant() {
        TenantContext.clear();
    }

    @Test
    @DisplayName("executor_id = 实例 + job：同一进程实例段一致、job 段逐条唯一")
    void executorIdIsInstancePlusJob() {
        String first = leaseService.newExecutorId();
        String second = leaseService.newExecutorId();
        System.out.println("[READING #8285 executor] first=" + first + " second=" + second);
        assertThat(first).as("形态必须是 <实例>#<pid>/<job>（实例段用 # 分进程、job 段用 / 分隔）")
                .contains("#").contains("/");
        assertThat(first.substring(0, first.lastIndexOf('/')))
                .as("同一进程的实例段必须一致（跨实例回收靠它归因）")
                .isEqualTo(second.substring(0, second.lastIndexOf('/')));
        assertThat(second.substring(second.lastIndexOf('/')))
                .as("job 段必须逐 job 唯一（否则同实例的后一条 job 会被当成「还是它」⇒ 心跳伪造成功）")
                .isNotEqualTo(first.substring(first.lastIndexOf('/')));
    }

    @Test
    @DisplayName("🔴 心跳 CAS 0 行 ⇒ renewLease 返回 false，且内存心跳不被刷新（调用方据此停手）")
    void heartbeatZeroRowsMeansLeaseLost() {
        AgentBatch batch = executingBatch("instance-c#303/job-c");
        OffsetDateTime before = batch.getHeartbeatAt();
        when(batchMapper.heartbeat(eq("b-1"), eq(TENANT), eq("instance-c#303/job-c"), any()))
                .thenReturn(0);

        boolean renewed = leaseService.renewLease(TENANT, batch);

        System.out.println("[READING #8285 续期失败] renewed=" + renewed + " 心跳=" + batch.getHeartbeatAt());
        assertThat(renewed).as("0 行 = 已被回收 / 换人 ⇒ 必须明确说「没续上」").isFalse();
        assertThat(batch.getHeartbeatAt())
                .as("没续上就不许刷新内存心跳（否则日志/判据会显示成一个仍然健康的租约）")
                .isEqualTo(before);
    }

    @Test
    @DisplayName("心跳 1 行 ⇒ renewLease 返回 true 且内存心跳跟进（与落库值一致）")
    void heartbeatOneRowRenewsLease() {
        AgentBatch batch = executingBatch("instance-a#101/job-a");
        when(batchMapper.heartbeat(anyString(), any(), anyString(), any())).thenReturn(1);

        boolean renewed = leaseService.renewLease(TENANT, batch);

        ArgumentCaptor<OffsetDateTime> at = ArgumentCaptor.forClass(OffsetDateTime.class);
        verify(batchMapper).heartbeat(eq("b-1"), eq(TENANT), eq("instance-a#101/job-a"), at.capture());
        System.out.println("[READING #8285 续期成功] renewed=" + renewed + " 心跳=" + at.getValue());
        assertThat(renewed).as("1 行 = 仍归本 job").isTrue();
        assertThat(batch.getHeartbeatAt())
                .as("内存心跳必须与落库值一致（同一时刻，不许各记一份）")
                .isEqualTo(at.getValue());
    }

    @Test
    @DisplayName("回收编排：跨租户取数 → 逐租户回收 → 汇总读数；租户上下文退出时还原")
    void recoveryLoopsEveryActiveTenantAndRestoresContext() {
        when(batchMapper.selectExecutingTenantIds()).thenReturn(List.of(TENANT, OTHER_TENANT));
        when(batchMapper.markStaleExecutingPartial(eq(TENANT), any(), any())).thenReturn(2);
        when(batchMapper.markStaleExecutingPartial(eq(OTHER_TENANT), any(), any())).thenReturn(0);
        TenantContext.setTenantId(999L);

        AgentBatchLeaseService.LeaseRecoveryOutcome outcome = leaseService.recoverStaleExecuting();

        System.out.println("[READING #8285 回收编排] 扫描=" + outcome.scannedTenants()
                + " 回收=" + outcome.recoveredBatches() + " 退出上下文=" + TenantContext.getTenantId());
        assertThat(outcome.scannedTenants()).as("两个租户都要扫（活批次可能在任一租户）").isEqualTo(2);
        assertThat(outcome.recoveredBatches()).as("汇总是各行数的和").isEqualTo(2);
        assertThat(TenantContext.getTenantId())
                .as("调度线程会复用 ⇒ 退出必须还原调用方的租户，不许把租户漏给下一个任务")
                .isEqualTo(999L);
    }

    @Test
    @DisplayName("🔴 逐租户失败不打断整轮（fail-soft）：前一个租户抛错，后一个照旧被回收")
    void oneTenantFailureDoesNotAbortTheRound() {
        when(batchMapper.selectExecutingTenantIds()).thenReturn(List.of(TENANT, OTHER_TENANT));
        when(batchMapper.markStaleExecutingPartial(eq(TENANT), any(), any()))
                .thenThrow(new IllegalStateException("boom"));
        when(batchMapper.markStaleExecutingPartial(eq(OTHER_TENANT), any(), any())).thenReturn(1);

        AgentBatchLeaseService.LeaseRecoveryOutcome outcome = leaseService.recoverStaleExecuting();

        System.out.println("[READING #8285 回收 fail-soft] 扫描=" + outcome.scannedTenants()
                + " 回收=" + outcome.recoveredBatches());
        assertThat(outcome.scannedTenants()).as("抛错的那个租户也算扫过").isEqualTo(2);
        assertThat(outcome.recoveredBatches())
                .as("另一个租户的崩溃遗留不许因为别人抛错就留在 executing")
                .isEqualTo(1);
    }

    @Test
    @DisplayName("取数面为空 / 为 null ⇒ 0 扫 0 收（不抛、不写）")
    void emptyTenantListIsANoOp() {
        when(batchMapper.selectExecutingTenantIds()).thenReturn(null);

        AgentBatchLeaseService.LeaseRecoveryOutcome outcome = leaseService.recoverStaleExecuting();

        verify(batchMapper, never()).markStaleExecutingPartial(any(), any(), any());
        assertThat(Arrays.asList(outcome.scannedTenants(), outcome.recoveredBatches()))
                .as("没有 executing 批次时既不扫也不收（这是正常结果，不是「没跑」）")
                .containsExactly(0, 0);
    }

    private static AgentBatch executingBatch(String executorId) {
        AgentBatch batch = new AgentBatch();
        batch.setId("b-1");
        batch.setTenantId(TENANT);
        batch.setStatus(AgentBatchService.STATUS_EXECUTING);
        batch.setExecutorId(executorId);
        batch.setHeartbeatAt(OffsetDateTime.now().minusMinutes(5));
        return batch;
    }
}
