// case_ids: MC-197

package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.MybatisSqlSessionFactoryBuilder;
import com.baomidou.mybatisplus.extension.plugins.MybatisPlusInterceptor;
import com.baomidou.mybatisplus.extension.plugins.handler.TenantLineHandler;
import com.baomidou.mybatisplus.extension.plugins.inner.TenantLineInnerInterceptor;
import com.migao.admin.config.TenantContext;
import com.migao.admin.mapper.AgentBatchItemMapper;
import com.migao.admin.mapper.AgentBatchMapper;
import net.sf.jsqlparser.expression.Expression;
import net.sf.jsqlparser.expression.LongValue;
import org.apache.ibatis.mapping.Environment;
import org.apache.ibatis.session.SqlSession;
import org.apache.ibatis.session.SqlSessionFactory;
import org.apache.ibatis.transaction.jdbc.JdbcTransactionFactory;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.datasource.DriverManagerDataSource;

import javax.sql.DataSource;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.sql.Connection;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import java.time.OffsetDateTime;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;

/**
 * 🔴 真库判据（issue #8285）：<b>批次后台 job 的执行租约 —— 心跳新鲜 ⇒ 回收 0 行 / 心跳超时或为空 ⇒
 * 回收成可撤销的 {@code partial}（幂等）/ 两个 executor 的活批次互不误伤 / 回收不覆盖终态</b>。
 *
 * <h2>为什么必须真库（mock 面结构上判不了）</h2>
 * 本单的四条主张全部落在**一条 SQL 的谓词**上（{@code AgentBatchMapper#markStaleExecutingPartial}：
 * {@code WHERE tenant_id=? AND status='executing' AND (heartbeat_at IS NULL OR heartbeat_at < 截止)}）。
 * mock 的 {@code @Update} 恒返回 1、也不会因谓词不满足而返回 0 ⇒ 修前形态（无时效谓词 / 无状态谓词）
 * 在 mock 上**恒绿**。只有真 PG 能证：谓词在、条件重估按真实行求值、重复执行影响 0 行。
 *
 * <h2>判据（每条都会红 · 见 PR body 的注入式红证读数）</h2>
 * <ol>
 *   <li><b>心跳新鲜 ⇒ 回收 0 行</b>：活 job（{@code heartbeat_at = now}）不被误杀（批次仍 {@code executing}、
 *       仍挂着它自己的 {@code executor_id}）；</li>
 *   <li><b>心跳超时 / 为空 ⇒ {@code partial}</b>：回收后状态可撤销（走既有 {@code revert} 路径逐条还原），
 *       且**重复回收幂等**（第二轮 0 行、状态与 {@code executed_at} 逐字不变）；</li>
 *   <li><b>两个实例各持 job ⇒ B 的回收扫不到 A 的活批次</b>：两个不同 {@code executor_id} 各持一个
 *       {@code executing} 批次，两个心跳都新鲜 ⇒ B 那一轮回收 0 行；把 A 的心跳改成超时后，
 *       B 的回收**只**动 A 那条，B 自己的仍 {@code executing} 且 executor 不变；</li>
 *   <li><b>回收不覆盖终态</b>：{@code done} / {@code partial} / {@code reverted} / {@code revert_partial}
 *       四条各一（心跳都为空）⇒ 回收 0 行、状态逐字不变；另证 <b>fencing</b>：被回收的僵尸 job 用自己的
 *       executor 写终态 ⇒ 0 行（不会把回收结果覆盖回 {@code done}）；</li>
 *   <li><b>不伪造 item 成功</b>：回收只改批次行，明细的 {@code status} 逐条不变。</li>
 * </ol>
 *
 * <h2>「两个实例」在单进程里怎么等价复算（如实交代）</h2>
 * 真多实例要两个 JVM；本判据不复算 JVM 数量，而是复算**判定依据**：回收那句 SQL 里**没有任何**
 * 「我是谁」的谓词（不看 {@code executor_id}），只认 {@code status} + {@code heartbeat_at} 两个客观事实
 * ⇒ 「A 与 B 是两个进程」和「A 与 B 是两个 {@code executor_id}」在判定面上**不可区分**。
 * 因此用**两个不同的 executor_id**（{@code instance-a#…/job-a} 与 {@code instance-b#…/job-b}）各持一个
 * 活批次，就能等价复算「B 的回收扫到 A 的活批次时会是 0 行」「A 死后 B 的回收只动 A」这两件事。
 * ⚠️ 本判据**不**证明的：跨进程时钟偏移、网络分区下的分区容忍、以及两个 JVM 各自的调度时序
 * （重启条件 = 真集群联调；见 PR body 的「未固化项」）。
 *
 * <h2>夹具自证</h2>
 * 一次性临时 PG 集群（{@link PgCluster}，测试结束销毁）；每条判据开头 {@code DELETE} 两张表 ⇒
 * 「回收扫全部租户」这件事不会把上一条判据留下的行读成自己的读数。存量数据一概不碰。
 */
@DisplayName("🔴 真库判据（#8285）：批次执行租约 —— 心跳新鲜不误杀 / 超时可回收且幂等 / 跨实例不误伤 / 不覆盖终态")
class AgentBatchLeaseRecoveryRealDbTest {

    private static final Long TENANT_ID = 8285L;
    /** 判据 3 用的第二个租户（同一个判据里跨实例 + 跨租户取数面一起过一遍）。 */
    private static final Long OTHER_TENANT_ID = 8286L;

    /** A 实例（活 job）的 executor_id：实例段 + job 段（与 {@code AgentBatchService#newExecutorId} 同形）。 */
    private static final String EXECUTOR_A = "instance-a#101/job-a";
    /** B 实例的 executor_id —— 与 A 不同，这是判据 3 的「两个实例」。 */
    private static final String EXECUTOR_B = "instance-b#202/job-b";

    private static PgCluster cluster;
    private static DataSource dataSource;
    private static SqlSessionFactory factory;
    /** 长活会话（autoCommit）：夹具与直接 mapper 调用都走它 —— mapper 代理不能挂在已关闭的 session 上。 */
    private static SqlSession session;
    private static AgentBatchService batchService;
    /** 租约服务（issue #8285 拆出的独立类）：回收 / 心跳都走它，装配与生产一致（真 mapper）。 */
    private static AgentBatchLeaseService leaseService;

    @BeforeAll
    static void startRealPostgresAndFixtures() throws Exception {
        cluster = PgCluster.startOrAbort();
        dataSource = cluster.dataSource();
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute(schemaSql());
            for (Long tenantId : List.of(TENANT_ID, OTHER_TENANT_ID)) {
                st.execute("INSERT INTO tenants (id, name, code) OVERRIDING SYSTEM VALUE VALUES ("
                        + tenantId + ", 'ab-8285-" + tenantId + "', 'ab-8285-" + tenantId + "')");
            }
        }

        MybatisConfiguration configuration = new MybatisConfiguration();
        configuration.setMapUnderscoreToCamelCase(true);
        configuration.setEnvironment(new Environment("ab-8285", new JdbcTransactionFactory(), dataSource));
        // 多租户拦截器**必须在场**：生产 SQL 会经它重写（追加 tenant_id）⇒ 少了它只测了 mapper 原文，
        // 而回收的取数面（selectExecutingTenantIds）恰恰是唯一一处**故意跨租户**的 @InterceptorIgnore。
        MybatisPlusInterceptor tenantLine = new MybatisPlusInterceptor();
        tenantLine.addInnerInterceptor(new TenantLineInnerInterceptor(new TenantLineHandler() {
            @Override
            public Expression getTenantId() {
                Long tenantId = TenantContext.getTenantId();
                if (tenantId == null) {
                    throw new IllegalStateException("Tenant context not initialized");
                }
                return new LongValue(tenantId);
            }

            @Override
            public String getTenantIdColumn() {
                return "tenant_id";
            }

            @Override
            public boolean ignoreTable(String tableName) {
                return false;
            }
        }));
        configuration.addInterceptor(tenantLine);
        configuration.addMapper(AgentBatchMapper.class);
        configuration.addMapper(AgentBatchItemMapper.class);
        factory = new MybatisSqlSessionFactoryBuilder().build(configuration);
        session = factory.openSession(true);
        batchService = serviceOn();
        leaseService = leaseService();
    }

    @AfterAll
    static void stopRealPostgres() {
        TenantContext.clear();
        if (session != null) {
            session.close();
        }
        if (cluster != null) {
            cluster.stop();
        }
    }

    /** 每条判据从**空表**起跑：回收扫的是全库 {@code executing} 行，残留会把读数串台。 */
    @BeforeEach
    void cleanBatchesAndRestoreTenant() {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute("DELETE FROM agent_batch_items");
            st.execute("DELETE FROM agent_batches");
        } catch (SQLException e) {
            throw new IllegalStateException("清理批次夹具失败", e);
        }
        flushSessionCache();
        TenantContext.setTenantId(TENANT_ID);
    }

    // ────────────────────────────────────────────── 判据 1：心跳新鲜 ⇒ 回收 0 行

    @Test
    @DisplayName("判据 1：活 job 的心跳新鲜 ⇒ 回收 0 行，批次仍 executing 且 executor 不被清空")
    void freshHeartbeatIsNeverCollected() {
        seedExecuting("b-fresh", TENANT_ID, EXECUTOR_A, OffsetDateTime.now());

        AgentBatchLeaseService.LeaseRecoveryOutcome outcome = leaseService.recoverStaleExecuting();

        System.out.println("[READING #8285 判据1 心跳新鲜] 扫描租户=" + outcome.scannedTenants()
                + " 回收=" + outcome.recoveredBatches()
                + " 批次状态=" + batchStatus("b-fresh") + " executor=" + executorId("b-fresh")
                + " 心跳=" + heartbeatAt("b-fresh"));

        assertThat(outcome.recoveredBatches())
                .as("心跳新鲜的 executing 批次是**活 job** —— 回收必须是 0 行（否则等于把正在跑的批次踢掉）")
                .isZero();
        assertThat(batchStatus("b-fresh")).isEqualTo(AgentBatchService.STATUS_EXECUTING);
        assertThat(executorId("b-fresh"))
                .as("活批次的 executor 不许被回收清空（清空 = 原 job 的心跳/终态写全部落空）")
                .isEqualTo(EXECUTOR_A);
    }

    // ────────────────────────────────────────────── 判据 2：超时/为空 ⇒ partial + 可撤销 + 幂等

    @Test
    @DisplayName("判据 2：心跳超时 / 为空 ⇒ 回收成 partial（可撤销），且重复回收幂等、明细一条不动")
    void staleOrMissingHeartbeatIsCollectedAsPartialIdempotently() {
        OffsetDateTime longAgo = OffsetDateTime.now().minusHours(2);
        seedExecuting("b-stale", TENANT_ID, EXECUTOR_A, longAgo);
        seedExecuting("b-null", TENANT_ID, EXECUTOR_B, null);
        // 明细三种状态各一条：回收**只改批次**，任何一条都不许被改成 success
        seedItem("b-stale", 1L, "success");
        seedItem("b-stale", 2L, "pending");
        seedItem("b-stale", 3L, "failed");

        AgentBatchLeaseService.LeaseRecoveryOutcome first = leaseService.recoverStaleExecuting();
        String staleExecutedAt = str(scalar("SELECT executed_at FROM agent_batches WHERE id = 'b-stale'"));

        System.out.println("[READING #8285 判据2 回收] 扫描租户=" + first.scannedTenants()
                + " 回收=" + first.recoveredBatches()
                + " b-stale=" + batchStatus("b-stale") + "(" + staleExecutedAt + ")"
                + " b-null=" + batchStatus("b-null")
                + " executor(stale)=" + executorId("b-stale")
                + " 明细=" + itemStatuses("b-stale"));

        assertThat(first.recoveredBatches()).as("两条（超时 + 从未心跳）都应被回收").isEqualTo(2);
        assertThat(batchStatus("b-stale")).isEqualTo(AgentBatchService.STATUS_PARTIAL);
        assertThat(batchStatus("b-null"))
                .as("heartbeat_at 为 NULL = 旧版本遗留 / 崩溃在 claim 之前 ⇒ 同样可回收").isEqualTo(
                        AgentBatchService.STATUS_PARTIAL);
        assertThat(executorId("b-stale"))
                .as("回收后「无主」：executor 置 NULL 是僵尸 job 停手的前提").isNull();
        assertThat(staleExecutedAt).as("回收时刻落在 executed_at（不覆盖已有值，此处本来为空）").isNotNull();
        assertThat(itemStatuses("b-stale"))
                .as("🔴 回收**只改批次状态**，不伪造 item 成功：三条明细逐条不变")
                .containsExactly("success", "pending", "failed");

        // 幂等：第二轮必须是 0 行，且状态 / executed_at 逐字不变（重复回收不产生副作用）
        AgentBatchLeaseService.LeaseRecoveryOutcome second = leaseService.recoverStaleExecuting();
        System.out.println("[READING #8285 判据2 幂等] 第二轮回收=" + second.recoveredBatches()
                + " b-stale=" + batchStatus("b-stale")
                + " executed_at=" + str(scalar("SELECT executed_at FROM agent_batches WHERE id = 'b-stale'")));
        assertThat(second.recoveredBatches()).as("重复回收同一批必须是 0 行（幂等）").isZero();
        assertThat(batchStatus("b-stale")).isEqualTo(AgentBatchService.STATUS_PARTIAL);
        assertThat(str(scalar("SELECT executed_at FROM agent_batches WHERE id = 'b-stale'")))
                .as("第二轮不许改写 executed_at（0 行 = 一个字节都没动）").isEqualTo(staleExecutedAt);

        // 可撤销：收回来的 partial 走**既有**撤销路径逐条还原（success → reverted，pending → skipped）
        TenantContext.setTenantId(TENANT_ID);
        var reverted = batchService.revert(TENANT_ID, "b-stale");
        System.out.println("[READING #8285 判据2 可撤销] 撤销后批次=" + reverted.getStatus()
                + " 明细=" + itemStatuses("b-stale")
                + " reverted_at=" + str(scalar("SELECT reverted_at FROM agent_batches WHERE id = 'b-stale'")));
        assertThat(reverted.getStatus())
                .as("被别人回收成 partial 的批次必须**可撤销**（这正是「回收成 partial 而不是 done」的理由）")
                .isEqualTo(AgentBatchService.STATUS_REVERTED);
        assertThat(itemStatuses("b-stale"))
                .as("逐条还原：执行成功的还原成 reverted；从未生效的置 skipped（不误写）")
                .containsExactly("reverted", "skipped", "skipped");
    }

    // ────────────────────────────────────────────── 判据 3：两个实例各持 job

    @Test
    @DisplayName("判据 3：两个实例各持活 job ⇒ B 的回收扫不到 A 的活批次；A 死后只动 A、B 仍 executing")
    void otherInstanceLiveBatchIsNotCollected() {
        OffsetDateTime fresh = OffsetDateTime.now();
        seedExecuting("b-owner-a", TENANT_ID, EXECUTOR_A, fresh);
        seedExecuting("b-owner-b", TENANT_ID, EXECUTOR_B, fresh);

        AgentBatchLeaseService.LeaseRecoveryOutcome bothLive = leaseService.recoverStaleExecuting();
        System.out.println("[READING #8285 判据3 两侧都活] 回收=" + bothLive.recoveredBatches()
                + " A=" + batchStatus("b-owner-a") + "/" + executorId("b-owner-a")
                + " B=" + batchStatus("b-owner-b") + "/" + executorId("b-owner-b"));
        assertThat(bothLive.recoveredBatches())
                .as("两个实例的批次心跳都新鲜 ⇒ **任何**实例跑回收都是 0 行（B 不许扫掉 A 的活批次）")
                .isZero();
        assertThat(batchStatus("b-owner-a")).isEqualTo(AgentBatchService.STATUS_EXECUTING);
        assertThat(batchStatus("b-owner-b")).isEqualTo(AgentBatchService.STATUS_EXECUTING);

        // A 所在的进程死了（心跳停在 2 小时前）；B 的 job 仍在跑（心跳新鲜）
        setHeartbeat("b-owner-a", OffsetDateTime.now().minusHours(2));
        AgentBatchLeaseService.LeaseRecoveryOutcome afterAKilled = leaseService.recoverStaleExecuting();
        System.out.println("[READING #8285 判据3 A 死后] 回收=" + afterAKilled.recoveredBatches()
                + " A=" + batchStatus("b-owner-a") + " B=" + batchStatus("b-owner-b")
                + "/" + executorId("b-owner-b"));
        assertThat(afterAKilled.recoveredBatches())
                .as("只回收 A 那一条（B 的活 job 心跳新鲜 ⇒ 仍是 0 行）").isEqualTo(1);
        assertThat(batchStatus("b-owner-a")).isEqualTo(AgentBatchService.STATUS_PARTIAL);
        assertThat(batchStatus("b-owner-b"))
                .as("🔴 B 自己的活批次必须完好无损（这正是「跨实例不误伤」）")
                .isEqualTo(AgentBatchService.STATUS_EXECUTING);
        assertThat(executorId("b-owner-b")).as("B 的 executor 不被别人清空").isEqualTo(EXECUTOR_B);

        // 另一个租户里的活批次同样不在射程内（回收的取数面是跨租户的，误伤面必须一起判）
        seedExecuting("b-other-tenant", OTHER_TENANT_ID, EXECUTOR_A, OffsetDateTime.now());
        AgentBatchLeaseService.LeaseRecoveryOutcome again = leaseService.recoverStaleExecuting();
        System.out.println("[READING #8285 判据3 跨租户活批次] 回收=" + again.recoveredBatches()
                + " 另一租户批次=" + batchStatus("b-other-tenant"));
        assertThat(again.scannedTenants())
                .as("回收的取数面必须**跨租户**（两个租户都有 executing 行 ⇒ 扫到 2 个）；"
                        + "退回单租户扫描 = 别的租户的崩溃批次永远收不回来")
                .isEqualTo(2);
        assertThat(again.recoveredBatches()).as("另一个租户的活批次也不许被误回收").isZero();
        assertThat(batchStatus("b-other-tenant")).isEqualTo(AgentBatchService.STATUS_EXECUTING);
    }

    // ────────────────────────────────────────────── 判据 4：不覆盖终态 + fencing

    @Test
    @DisplayName("判据 4：回收不覆盖终态（done/partial/reverted/revert_partial），僵尸终态写被 fencing 挡回")
    void terminalStatesAreNeverOverwritten() {
        for (String terminal : List.of(AgentBatchService.STATUS_DONE,
                AgentBatchService.STATUS_PARTIAL,
                AgentBatchService.STATUS_REVERTED,
                AgentBatchService.STATUS_REVERT_PARTIAL)) {
            seedBatch("b-" + terminal, TENANT_ID, terminal, EXECUTOR_A, null);
        }
        // 🔴 必须再放一条**活** executing：回收的取数面只按 executing 行挑租户
        // ⇒ 没有它，这个租户压根不会被扫到，本判据对「终态不被覆盖」就是**空的**（实测踩过）。
        seedExecuting("b-live-anchor", TENANT_ID, EXECUTOR_B, OffsetDateTime.now());

        AgentBatchLeaseService.LeaseRecoveryOutcome outcome = leaseService.recoverStaleExecuting();
        System.out.println("[READING #8285 判据4 终态] 回收=" + outcome.recoveredBatches()
                + " done=" + batchStatus("b-done") + " partial=" + batchStatus("b-partial")
                + " reverted=" + batchStatus("b-reverted")
                + " revert_partial=" + batchStatus("b-revert_partial"));
        assertThat(outcome.recoveredBatches())
                .as("终态批次（哪怕心跳为空）一律不在回收射程内 —— 谓词 status='executing' 就是这条判据")
                .isZero();
        assertThat(outcome.scannedTenants()).as("夹具自证：该租户确实进了取数面（否则本条判据是空的）")
                .isEqualTo(1);
        assertThat(batchStatus("b-live-anchor")).as("同租户的活批次不受影响").isEqualTo(
                AgentBatchService.STATUS_EXECUTING);
        for (String terminal : List.of(AgentBatchService.STATUS_DONE,
                AgentBatchService.STATUS_PARTIAL,
                AgentBatchService.STATUS_REVERTED,
                AgentBatchService.STATUS_REVERT_PARTIAL)) {
            assertThat(batchStatus("b-" + terminal)).as("终态 %s 被回收改写了", terminal).isEqualTo(terminal);
        }

        // ── fencing：僵尸 job 在**回收后**再写终态必须 0 行
        // 场景（这才是 fencing 真正要挡的交错）：A 的心跳超时 ⇒ 批次被回收成 partial ⇒ 用户发起撤销
        // （撤销 claim 又把它置回 executing，但 executor 已换人 C）⇒ 此时 A 还活着，跑完最后一条后写终态。
        // 只靠 `status='executing'` 挡不住它（那时确实是 executing）⇒ 必须靠 executor 谓词。
        seedFencingBatch("b-fencing");
        assertThat(leaseService.recoverStaleExecuting().recoveredBatches())
                .as("夹具前提：A 的批次先被回收成 partial").isEqualTo(1);
        int newOwnerClaim = mapper().markReverting("b-fencing", TENANT_ID,
                AgentBatchService.STATUS_DONE, AgentBatchService.STATUS_PARTIAL,
                "instance-c#303/job-c", OffsetDateTime.now());
        assertThat(newOwnerClaim).as("夹具前提：用户撤销抢到撤销权（批次回到 executing，executor = C）").isEqualTo(1);
        int zombieWrites = mapper().markExecutedDone("b-fencing", TENANT_ID, 1, 0,
                OffsetDateTime.now(), EXECUTOR_A);
        System.out.println("[READING #8285 判据4 僵尸终态写] 影响行数=" + zombieWrites
                + " 批次状态=" + batchStatus("b-fencing") + " executor=" + executorId("b-fencing"));
        assertThat(zombieWrites)
                .as("🔴 僵尸 job（旧 executor）的终态写必须 0 行 —— 否则它会把用户正在进行的撤销覆盖成 done")
                .isZero();
        assertThat(batchStatus("b-fencing"))
                .as("回收 + 换人之后的执行态不许被旧 executor 覆盖").isEqualTo(AgentBatchService.STATUS_EXECUTING);
        assertThat(mapper().markReverted("b-fencing", TENANT_ID, OffsetDateTime.now(), "instance-c#303/job-c"))
                .as("正对照：**当前** executor 的终态写必须成功（护栏不误杀正常路径）").isEqualTo(1);
        assertThat(batchStatus("b-fencing")).isEqualTo(AgentBatchService.STATUS_REVERTED);

        // 正对照 2：回收后的批次可以走**既有**撤销服务路径（逐条还原，与人工撤销同一套语义）
        TenantContext.setTenantId(TENANT_ID);
        var reverted = batchService.revert(TENANT_ID, "b-done");
        System.out.println("[READING #8285 判据4 正对照] 回收后撤销 b-done=" + reverted.getStatus());
        assertThat(reverted.getStatus()).isEqualTo(AgentBatchService.STATUS_REVERTED);
    }

    // ────────────────────────────────────────────── 装置

    /** 装配：批次状态机走**真库 mapper**；明细写与商品写与本单无关（ProdService mock 只为满足构造）。 */
    private static AgentBatchLeaseService leaseService() {
        if (leaseService == null) {
            leaseService = new AgentBatchLeaseService(mapper());
        }
        return leaseService;
    }

    private static AgentBatchService serviceOn() {
        return new AgentBatchService(mapper(), itemMapper(), mock(ProductService.class), job -> job.run(),
                leaseService());
    }

    /** 清 MyBatis 一级缓存：夹具写入走的是别的连接 ⇒ 会话本地缓存必须显式作废。 */
    private static void flushSessionCache() {
        if (session != null) {
            session.clearCache();
        }
    }

    private static AgentBatchMapper mapper() {
        return session.getMapper(AgentBatchMapper.class);
    }

    private static AgentBatchItemMapper itemMapper() {
        return session.getMapper(AgentBatchItemMapper.class);
    }

    /** fencing 夹具：{@code executing} + {@code item_count=1}（让「僵尸终态写 1 行」在约束上可成立）。 */
    private static void seedFencingBatch(String batchId) {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute("INSERT INTO agent_batches (id, tenant_id, batch_type, status, item_count,"
                    + " success_count, fail_count, created_by, executor_id, heartbeat_at) VALUES ('"
                    + batchId + "', " + TENANT_ID + ", 'product_status', 'executing', 1, 0, 0, 'ab-8285', '"
                    + EXECUTOR_A + "', '" + OffsetDateTime.now().minusHours(2) + "')");
        } catch (SQLException e) {
            throw new IllegalStateException("fencing 夹具落库失败: " + batchId, e);
        }
        flushSessionCache();
    }

    private static void seedExecuting(String batchId, Long tenantId, String executorId, OffsetDateTime heartbeat) {
        seedBatch(batchId, tenantId, AgentBatchService.STATUS_EXECUTING, executorId, heartbeat);
    }

    /** 直接落一行批次（绕开服务层：本节判的是**回收 SQL**，不是创建/准入路径）。 */
    private static void seedBatch(String batchId, Long tenantId, String status,
                                  String executorId, OffsetDateTime heartbeat) {
        String heartbeatSql = heartbeat == null ? "NULL" : "'" + heartbeat + "'";
        String executorSql = executorId == null ? "NULL" : "'" + executorId + "'";
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute("INSERT INTO agent_batches (id, tenant_id, batch_type, status, item_count,"
                    + " success_count, fail_count, created_by, executor_id, heartbeat_at) VALUES ('"
                    + batchId + "', " + tenantId + ", 'product_status', '" + status + "', 0, 0, 0, 'ab-8285', "
                    + executorSql + ", " + heartbeatSql + ")");
        } catch (SQLException e) {
            throw new IllegalStateException("批次夹具落库失败: " + batchId, e);
        }
        // 🔴 夹具走裸 JDBC（另一条连接）⇒ MyBatis 一级缓存不会失效；不清缓存时
        // `selectExecutingTenantIds()` 会返回**上一轮的租户清单**（实测：第二轮回收静默 0 行）。
        flushSessionCache();
    }

    private static void seedItem(String batchId, long id, String status) {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute("INSERT INTO agent_batch_items (id, batch_id, tenant_id, resource_id, field,"
                    + " old_value, new_value, status) OVERRIDING SYSTEM VALUE VALUES (" + id + ", '"
                    + batchId + "', " + TENANT_ID + ", 'prod-" + id + "', 'status', 'off_sale', 'on_sale', '"
                    + status + "')");
        } catch (SQLException e) {
            throw new IllegalStateException("明细夹具落库失败: " + batchId + "/" + id, e);
        }
        flushSessionCache();
    }

    private static void setHeartbeat(String batchId, OffsetDateTime heartbeat) {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute("UPDATE agent_batches SET heartbeat_at = '" + heartbeat + "' WHERE id = '" + batchId + "'");
        } catch (SQLException e) {
            throw new IllegalStateException("心跳夹具改写失败: " + batchId, e);
        }
        flushSessionCache();
    }

    // ────────────────────────────────────────────── 真值读取（裸 JDBC，不经被测读面）

    private static Object scalar(String sql) {
        try (Connection c = dataSource.getConnection();
             Statement st = c.createStatement();
             ResultSet rs = st.executeQuery(sql)) {
            return rs.next() ? rs.getObject(1) : null;
        } catch (SQLException e) {
            throw new IllegalStateException("真值读取失败: " + sql, e);
        }
    }

    private static String str(Object value) {
        return value == null ? null : value.toString();
    }

    private static String batchStatus(String batchId) {
        return str(scalar("SELECT status FROM agent_batches WHERE id = '" + batchId + "'"));
    }

    private static String executorId(String batchId) {
        return str(scalar("SELECT executor_id FROM agent_batches WHERE id = '" + batchId + "'"));
    }

    private static String heartbeatAt(String batchId) {
        return str(scalar("SELECT heartbeat_at FROM agent_batches WHERE id = '" + batchId + "'"));
    }

    private static List<String> itemStatuses(String batchId) {
        Object v = scalar("SELECT array_agg(status ORDER BY id)::text FROM agent_batch_items"
                + " WHERE batch_id = '" + batchId + "'");
        if (v == null) {
            return List.of();
        }
        String inner = v.toString().substring(1, v.toString().length() - 1);
        return inner.isEmpty() ? List.of() : List.of(inner.split(","));
    }

    private static String schemaSql() throws IOException {
        Path root = Paths.get(System.getProperty("user.dir")).toAbsolutePath();
        while (root != null
                && !Files.exists(root.resolve("backend/admin-api/src/main/resources/db/init/schema.sql"))) {
            root = root.getParent();
        }
        assertThat(root).as("必须能定位 backend/admin-api/src/main/resources/db/init/schema.sql").isNotNull();
        return Files.readString(root.resolve("backend/admin-api/src/main/resources/db/init/schema.sql"));
    }
}
