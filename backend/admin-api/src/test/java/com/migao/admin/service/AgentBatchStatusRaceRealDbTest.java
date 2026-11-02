// case_ids: PR-028

package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.MybatisSqlSessionFactoryBuilder;
import com.baomidou.mybatisplus.extension.plugins.MybatisPlusInterceptor;
import com.baomidou.mybatisplus.extension.plugins.handler.TenantLineHandler;
import com.baomidou.mybatisplus.extension.plugins.inner.TenantLineInnerInterceptor;
import com.migao.admin.dto.agent.AgentProductUpdateRequest;
import com.migao.admin.dto.agent.AgentBatchViews;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.AgentBatchItemMapper;
import com.migao.admin.mapper.AgentBatchMapper;
import net.sf.jsqlparser.expression.Expression;
import net.sf.jsqlparser.expression.LongValue;
import org.apache.ibatis.mapping.Environment;
import org.apache.ibatis.session.SqlSession;
import org.apache.ibatis.session.SqlSessionFactory;
import org.apache.ibatis.transaction.jdbc.JdbcTransactionFactory;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeAll;
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
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;

/**
 * 🔴 真库并发判据（issue #6960）：<b>Agent 批次「执行」「撤销」的准入必须是 DB 原子条件更新（CAS）
 * ⇒ 并发下**恰一轮** apply，商品终态可复算</b>。
 *
 * <h2>核验的是哪一条主张</h2>
 * {@code AgentBatchService#execute} / {@code #revert} 的准入 = {@code AgentBatchMapper#markExecuting} /
 * {@code #markReverting}（{@code WHERE id=? AND tenant_id=? AND status IN …}，0 行 ⇒ 409），
 * 且这道闸位于**逐条 apply 之前**。改前是「先读批次判 {@code preview}、再
 * {@code batchMapper.updateById(batch)}（WHERE 仅主键 ⇒ 无谓词）」⇒ 两个并发 execute 都能读到
 * {@code preview} 并各 apply **一轮**（对同一批商品重复 apply）。
 *
 * <h2>为什么必须真库 + 窗口注入</h2>
 * CAS 的全部效力来自只有真 PG 才有的两件事：<b>① 行锁</b>（条件更新的判断与写入是同一条语句）、
 * <b>② 条件重估</b>（后到者阻塞到前者提交后按新版本行重估 {@code status='preview'} ⇒ 影响行数 0）。
 * mock 面结构上判不了：mock 的 {@code updateById} 恒返回 1、也不会因 WHERE 不满足而返回 0
 * ⇒ 修前形态在 mock 上恒绿（假绿）。而窗口只有微秒级 ⇒ 用
 * {@link AgentBatchService#setBatchProbePauseMillisForTest}（生产恒为 0）把窗口放大，
 * 判据才是**确定性**的，而不是 flake。
 *
 * <h2>判据（每条都会红）</h2>
 * <ol>
 *   <li><b>恰一轮 apply</b>：并发两个 execute ⇒ 成功数 == 1、落败方 409，且**真的落到商品上的
 *       apply 调用数恰 1**（计数器现取，不由断言假设）；</li>
 *   <li><b>商品终态可复算</b>：批次终态 {@code done}、逐条 {@code success}、商品 {@code status}
 *       逐字等于 {@code newValue}（真库直读，不经被测读面）；</li>
 *   <li><b>撤销同款</b>：并发两个 revert ⇒ 成功数 == 1、apply 计数恰 1、商品被还原成 {@code oldValue}；</li>
 *   <li><b>正对照（护栏不误杀）</b>：无并发时 execute / revert 各成功一次（谓词非空 ⇒ 正常请求不被误杀）。</li>
 * </ol>
 *
 * <h2>判别力（红证，注入式 · 双向）</h2>
 * 注入 = {@code AgentBatchService.setBatchProbePauseMillisForTest(PAUSE_MILLIS)}（把「读-判」与
 * 「抢权」之间的窗口从微秒放大到 800ms）。修前（无 CAS）本判据 <b>必红</b>（两个请求都读到
 * {@code preview} ⇒ apply 计数 2）；修后 <b>必绿</b>（CAS 0 行 ⇒ 409 ⇒ apply 计数 1）。
 * 撤回注入（{@code pauseMillis=0}）后正对照仍绿 ⇒ 「注入放大」就是本判据确定性的来源。
 * 逐字读数见 PR body 的「修前红 / 修后绿」两段。
 *
 * <p><b>边界（如实登记）</b>：① 本判据跑的是<b>服务层真库并发</b>而非 HTTP 栈（controller 只是薄转发）；
 * ② 探针对象全部自建（tenant {@value #TENANT_ID} / 商品前缀 {@code ab-6960}），随一次性临时集群销毁，
 * <b>不碰任何存量数据</b>；③ 商品写入走真 {@link ProductService}（真库真写）—— apply 计数是对它的
 * **有界子类**（{@code CountingProductService}）记的，子类只加一个计数器、不改任何行为；
 * ④ 本判据与 {@code AgentBatchStatusCasMetaGuardTest}（形态面）**缺一不可**：
 * 形态面保证「写路径仍在册且带谓词」，本判据保证「并发下真的恰一轮」。</p>
 */
@DisplayName("🔴 真库并发判据（#6960）：Agent 批次 execute/revert 的 CAS ⇒ 并发恰一轮 apply + 终态可复算")
class AgentBatchStatusRaceRealDbTest {

    private static final Long TENANT_ID = 6960L;
    private static final String PRODUCT_ID = "ab-6960-prod";
    private static final String CATEGORY_ID = "ab-6960-cat";
    /** 商品起始状态（= 批次的 oldValue）。 */
    private static final String OLD_STATUS = "off_sale";
    /** 批次要写的目标状态（= newValue）。 */
    private static final String NEW_STATUS = "on_sale";

    /** 窗口注入时长（毫秒）：必须显著大于一次 execute 的全程（实测 ~10~40ms）。 */
    private static final long PAUSE_MILLIS = 800L;
    /** 等「探针已进入窗口」的上限（确定性时序的护栏；超时 = 判据装置坏了）。 */
    private static final long PAUSE_WAIT_MILLIS = 10_000L;

    private static PgCluster cluster;
    private static DataSource dataSource;
    private static SqlSessionFactory factory;

    @BeforeAll
    static void startRealPostgresAndFixtures() throws Exception {
        cluster = PgCluster.startOrAbort();
        dataSource = cluster.dataSource();
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute(schemaSql());
            st.execute("INSERT INTO tenants (id, name, code) OVERRIDING SYSTEM VALUE VALUES ("
                    + TENANT_ID + ", 'ab-6960', 'ab-6960')");
            st.execute("INSERT INTO categories (id, tenant_id, name) VALUES ('" + CATEGORY_ID + "', "
                    + TENANT_ID + ", 'ab-6960 分类')");
            st.execute("INSERT INTO products (id, tenant_id, name, category_id, base_price, status) VALUES ('"
                    + PRODUCT_ID + "', " + TENANT_ID + ", '批量状态竞态夹具商品', '" + CATEGORY_ID
                    + "', 150.00, '" + OLD_STATUS + "')");
        }

        MybatisConfiguration configuration = new MybatisConfiguration();
        configuration.setMapUnderscoreToCamelCase(true);
        configuration.setEnvironment(new Environment("ab-6960", new JdbcTransactionFactory(), dataSource));
        // 多租户拦截器**必须在场**：生产 SQL 会经它重写（追加 tenant_id）⇒ 少了它就只测了 mapper 原文
        MybatisPlusInterceptor tenantLine = new MybatisPlusInterceptor();
        tenantLine.addInnerInterceptor(new TenantLineInnerInterceptor(new TenantLineHandler() {
            @Override
            public Expression getTenantId() {
                return new LongValue(TENANT_ID);
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
        // 商品写入走真 ProductService ⇒ 它的整条依赖链上的 mapper 都必须在场（少一个就是
        // `Binding Type interface … is not known to the MybatisPlusMapperRegistry`）
        for (Class<?> mapper : List.of(AgentBatchMapper.class, AgentBatchItemMapper.class,
                com.migao.admin.mapper.ProductMapper.class,
                com.migao.admin.mapper.ProductSkuMapper.class,
                com.migao.admin.mapper.CategoryMapper.class,
                com.migao.admin.mapper.ProductColorMapper.class,
                com.migao.admin.mapper.ProductAttributeMapper.class)) {
            configuration.addMapper(mapper);
        }
        factory = new MybatisSqlSessionFactoryBuilder().build(configuration);
    }

    @AfterEach
    void clearProbe() {
        AgentBatchService.setBatchProbePauseMillisForTest(0L);
    }

    @AfterAll
    static void stopRealPostgres() {
        AgentBatchService.setBatchProbePauseMillisForTest(0L);
        if (cluster != null) {
            cluster.stop();
        }
    }

    // ────────────────────────────────────────────── 判据 1~2：并发 execute（注入放大窗口）

    @Test
    @DisplayName("并发 execute（注入放大窗口）：恰一个赢家 + 恰一轮 apply + 商品终态 == newValue")
    void concurrentExecuteAppliesExactlyOneRound() throws Exception {
        AgentBatchService.setBatchProbePauseMillisForTest(PAUSE_MILLIS);
        // 1 条明细 = 1 轮 apply 的读数（N 条明细时「一轮」= N 次调用，读不出「跑了几轮」）
        String batchId = seedPreviewBatch("ab-6960-exec-race", OLD_STATUS, NEW_STATUS, 1);
        CountingProductService.APPLIES.set(0);

        List<Verdict> outcomes = runRaceWithProbe(batchId, RaceAction.EXECUTE);

        long successes = outcomes.stream().filter(v -> v.status == 200).count();
        long conflicts = outcomes.stream().filter(v -> v.status == 409).count();
        System.out.println("[READING #6960 execute 竞态] 状态码="
                + outcomes.stream().map(v -> String.valueOf(v.status)).toList()
                + " 成功数=" + successes + " 409数=" + conflicts
                + " apply次数=" + CountingProductService.APPLIES.get()
                + " 批次终态=" + batchStatus(batchId)
                + " 商品终态=" + productStatus());

        assertThat(successes)
                .as("两个并发 execute 争同一份执行权 ⇒ 恰一个赢家（两个都 200 就是修前的缺陷形态）")
                .isEqualTo(1L);
        assertThat(conflicts).as("落败方必须是显式 409 CONFLICT（不是 500 / 不是静默成功）").isEqualTo(1L);
        assertThat(CountingProductService.APPLIES.get())
                .as("🔴 本判据的钉：**真的落到商品上的 apply 恰一轮**（1 条明细 ⇒ 恰 1 次；2 次 = 重复 apply）")
                .isEqualTo(1);
        assertThat(batchStatus(batchId)).as("批次终态 done（preview→executing→done 走完）").isEqualTo("done");
        assertThat(productStatus()).as("商品终态可复算：逐字等于 newValue").isEqualTo(NEW_STATUS);
        assertThat(itemStatuses(batchId)).as("逐条落 success（apply 真跑过）").containsExactly("success");
    }

    // ────────────────────────────────────────────── 判据 3：并发 revert

    @Test
    @DisplayName("并发 revert（注入放大窗口）：恰一个赢家 + 恰一轮 apply + 商品还原为 oldValue")
    void concurrentRevertAppliesExactlyOneRound() throws Exception {
        // 批次的 oldValue = 商品起点 OLD_STATUS，newValue = NEW_STATUS ⇒ 撤销 = 还原成 OLD_STATUS
        String batchId = seedPreviewBatch("ab-6960-revert-race", OLD_STATUS, NEW_STATUS, 1);
        // 先无并发执行一轮（夹具前提：批次必须真的可撤销），并把计数器归零只观测 revert 那一段
        runOne(RaceAction.EXECUTE, batchId);
        CountingProductService.APPLIES.set(0);
        assertThat(batchStatus(batchId)).as("夹具前提：串行 execute 成功 ⇒ 批次可撤销").isEqualTo("done");
        assertThat(productStatus()).as("夹具前提：执行后商品 == newValue").isEqualTo(NEW_STATUS);

        AgentBatchService.setBatchProbePauseMillisForTest(PAUSE_MILLIS);
        List<Verdict> outcomes = runRaceWithProbe(batchId, RaceAction.REVERT);

        long successes = outcomes.stream().filter(v -> v.status == 200).count();
        System.out.println("[READING #6960 revert 竞态] 状态码="
                + outcomes.stream().map(v -> String.valueOf(v.status)).toList()
                + " 成功数=" + successes
                + " apply次数=" + CountingProductService.APPLIES.get()
                + " 批次终态=" + batchStatus(batchId)
                + " 商品终态=" + productStatus());

        assertThat(successes).as("两个并发 revert 争同一份撤销权 ⇒ 恰一个赢家").isEqualTo(1L);
        assertThat(CountingProductService.APPLIES.get())
                .as("🔴 撤销的 apply 也恰一轮（两轮 = 同一批 oldValue 被重复还原）")
                .isEqualTo(1);
        assertThat(batchStatus(batchId)).as("批次终态 reverted").isEqualTo("reverted");
        assertThat(productStatus()).as("商品被还原成批次的 oldValue").isEqualTo(OLD_STATUS);
    }

    /**
     * 无探针的并发对照：**确定性的那一半**（与探针注入合起来才是完整的双向证据）。
     *
     * <p>探针把窗口放大 ⇒ 探针档是「必红/必绿」的确定性读数。本档把探针关掉，用
     * {@link java.util.concurrent.CyclicBarrier} 让两个请求尽可能同时起跑：**断言与探针档同款**
     * （恰一个赢家 + 恰一轮 apply）。它证明 CAS 在有真实并发、但窗口没被放大时**也不会漏**
     * —— 「关掉探针 ⇒ 判据失效退化」这件事被这条挡住（探针档证明必红，本档证明不含注入也守得住）。</p>
     */
    @Test
    @DisplayName("并发对照（无探针，CyclicBarrier 同时起跑）：仍恰一个赢家 + 恰一轮 apply")
    void concurrentExecuteWithoutProbeStillHasExactlyOneWinner() throws Exception {
        String batchId = seedPreviewBatch("ab-6960-exec-noprobe", OLD_STATUS, NEW_STATUS, 1);
        CountingProductService.APPLIES.set(0);

        List<Verdict> outcomes = runBothWithBarrier(batchId, RaceAction.EXECUTE);

        long successes = outcomes.stream().filter(v -> v.status == 200).count();
        System.out.println("[READING #6960 execute 无探针对照] 状态码="
                + outcomes.stream().map(v -> String.valueOf(v.status)).toList()
                + " 成功数=" + successes + " apply次数=" + CountingProductService.APPLIES.get()
                + " 批次终态=" + batchStatus(batchId) + " 商品终态=" + productStatus());

        assertThat(successes).as("无探针的真实并发下仍恰一个赢家（CAS 不依赖注入）").isEqualTo(1L);
        assertThat(CountingProductService.APPLIES.get()).as("无探针下 apply 仍恰一轮").isEqualTo(1);
        assertThat(batchStatus(batchId)).isEqualTo("done");
        assertThat(productStatus()).isEqualTo(NEW_STATUS);
    }

    // ────────────────────────────────────────────── 判据 4：正对照（护栏不误杀）

    @Test
    @DisplayName("正对照（护栏不误杀，无窗口注入）：串行 execute + revert 各成功一次、状态来回")
    void serialExecuteAndRevertStillSucceed() {
        String batchId = seedPreviewBatch("ab-6960-serial", OLD_STATUS, NEW_STATUS, 1);
        CountingProductService.APPLIES.set(0);

        Verdict executed = runOne(RaceAction.EXECUTE, batchId);
        String midStatus = productStatus();
        Verdict reverted = runOne(RaceAction.REVERT, batchId);
        System.out.println("[READING #6960 正对照 串行] execute=" + executed.status + "(" + executed.detail + ")"
                + " revert=" + reverted.status + "(" + reverted.detail + ")"
                + " 商品=" + midStatus + "→" + productStatus()
                + " 批次终态=" + batchStatus(batchId) + " apply次数=" + CountingProductService.APPLIES.get());

        assertThat(executed.status).as("串行 execute 必须成功（这条红了 = 谓词误杀正常请求）").isEqualTo(200);
        assertThat(midStatus).as("执行后商品 == newValue").isEqualTo(NEW_STATUS);
        assertThat(reverted.status).as("串行 revert 必须成功").isEqualTo(200);
        assertThat(productStatus()).as("撤销后商品回到 oldValue").isEqualTo(OLD_STATUS);
        assertThat(batchStatus(batchId)).as("批次终态 reverted").isEqualTo("reverted");
        assertThat(CountingProductService.APPLIES.get()).as("串行两轮 = execute 一次 + revert 一次").isEqualTo(2);
    }

    // ────────────────────────────────────────────── 并发装置

    private enum RaceAction { EXECUTE, REVERT }

    /** 一次请求的结果（业务码 + 文本锚；服务层用异常的业务码等价表达 HTTP 4xx）。 */
    private record Verdict(int status, String detail) {
    }

    /**
     * 无探针的并发装置：两个请求各用**自己的连接 + 自己的事务**，用
     * {@link java.util.concurrent.CyclicBarrier} 对齐到同一时刻起跑（窗口不被放大）。
     */
    private static List<Verdict> runBothWithBarrier(String batchId, RaceAction action) throws Exception {
        ExecutorService pool = Executors.newFixedThreadPool(2);
        java.util.concurrent.CyclicBarrier barrier = new java.util.concurrent.CyclicBarrier(2);
        try {
            Future<Verdict> a = pool.submit(() -> {
                barrier.await(30, TimeUnit.SECONDS);
                return runOne(action, batchId);
            });
            Future<Verdict> b = pool.submit(() -> {
                barrier.await(30, TimeUnit.SECONDS);
                return runOne(action, batchId);
            });
            return List.of(a.get(60, TimeUnit.SECONDS), b.get(60, TimeUnit.SECONDS));
        } finally {
            pool.shutdownNow();
        }
    }

    /**
     * 注入窗口下的**两段式确定性时序**：起跑者先进窗口（钉住「读-判已过、尚未抢权」）→
     * 对手在窗口内走完整条路并提交 → 起跑者续跑去抢权。
     *
     * <p>这不是 {@code sleep} 猜时间：起跑者由 {@link AgentBatchService#batchProbePausedForTest()}
     * 钉住（超时 = 判据装置坏了 ⇒ 当场抛，不静默继续 —— 静默继续会让本判据退化成 flake）。
     * ⚠️ 探针只让**第一个**到达者停顿 ⇒ 对手会直接穿过（它要跑的正是「读-判 → 抢权（0 行）→ 409」
     * 这条完整路径）。</p>
     *
     * <p><b>修前为什么必红</b>：无 CAS 时对手的「读-判」看到 {@code preview} ⇒ 它照样跑完 apply
     * ⇒ 起跑者续跑又跑一轮 ⇒ 计数 2（对同一批商品重复 apply）。<b>修后为什么必绿</b>：
     * 对手的 CAS 0 行 ⇒ 409 ⇒ 一条 apply 都不跑；起跑者续跑拿到执行权 ⇒ 恰一轮。</p>
     */
    private static List<Verdict> runRaceWithProbe(String batchId, RaceAction action) throws Exception {
        ExecutorService pool = Executors.newSingleThreadExecutor();
        try {
            // ① 起跑者先进窗口（它会停在「读-判已过、尚未抢权」那一刻）
            Future<Verdict> held = pool.submit(() -> runOne(action, batchId));
            awaitProbePaused();
            // ② 对手在窗口内走完全程（读-判 → 抢权 → 0 行 ⇒ 409；修前 ⇒ 照样 apply 一轮）
            Verdict opponent = runOne(action, batchId);
            // ③ 起跑者续跑：抢到权 ⇒ 恰一轮 apply（这 800ms 里窗口一直开着，故对手早于起跑者落库）
            Verdict first = held.get(60, TimeUnit.SECONDS);
            return List.of(first, opponent);
        } finally {
            pool.shutdownNow();
        }
    }

    /** 等「探针已进入暂停窗口」——**确定性时序**的锚点（不是 {@code sleep} 猜时间）。 */    private static void awaitProbePaused() throws Exception {
        long deadline = System.nanoTime() + TimeUnit.MILLISECONDS.toNanos(PAUSE_WAIT_MILLIS);
        while (System.nanoTime() < deadline) {
            if (AgentBatchService.batchProbePausedForTest()) {
                return;
            }
            Thread.sleep(1L);
        }
        throw new IllegalStateException(
                "探针未在 " + PAUSE_WAIT_MILLIS + "ms 内进入窗口（判据装置坏了：探针没插上 / 批次不是可执行态）");
    }

    /** 一次请求：自己的连接 + 自己的事务（服务层无事务 ⇒ 每次 mapper 调用即时提交）。 */
    private static Verdict runOne(RaceAction action, String batchId) {
        try (SqlSession s = factory.openSession(true)) {
            AgentBatchService service = serviceOn(s);
            AgentBatchViews.Batch view = action == RaceAction.EXECUTE
                    ? service.execute(TENANT_ID, batchId)
                    : service.revert(TENANT_ID, batchId);
            return new Verdict(200, "status=" + view.getStatus());
        } catch (BusinessException e) {
            return new Verdict(e.getHttpStatus(), "msg=" + e.getMessage());
        }
    }

    /**
     * 真装配：批次状态机走<b>真库 mapper</b>；商品写入走**真 {@link ProductService}**（真库真写），
     * 外面套一层只加计数器的有界子类 ⇒ 「恰一轮 apply」是**现取读数**，不是断言假设。
     */
    private static AgentBatchService serviceOn(SqlSession s) {
        CountingProductService productService =
                new CountingProductService(s.getMapper(com.migao.admin.mapper.ProductMapper.class),
                        s.getMapper(com.migao.admin.mapper.ProductSkuMapper.class));
        return new AgentBatchService(s.getMapper(AgentBatchMapper.class),
                s.getMapper(AgentBatchItemMapper.class), productService, job -> job.run());
    }

    /**
     * 只给 {@code updateProductForAgent} 加一个计数器、其余行为一字不改的有界子类。
     *
     * <p>为什么不用 {@code mock()}：mock 会把真库真写换掉 ⇒ 判据只剩「调用了几次」这一半，
     * 「商品终态可复算」那一半就没有载体了。本子类让两条判据在同一装置上同时成立。</p>
     */
    static class CountingProductService extends ProductService {
        static final AtomicInteger APPLIES = new AtomicInteger();

        CountingProductService(com.migao.admin.mapper.ProductMapper productMapper,
                               com.migao.admin.mapper.ProductSkuMapper productSkuMapper) {
            super(productMapper, mock(com.migao.admin.mapper.CategoryMapper.class),
                    mock(com.migao.admin.mapper.ProductColorMapper.class), productSkuMapper,
                    mock(com.migao.admin.mapper.ProductAttributeMapper.class),
                    mock(StockLedgerService.class), mock(ClientRequestIdService.class));
        }

        @Override
        public com.migao.admin.dto.ProductResponse updateProductForAgent(
                String id, AgentProductUpdateRequest request, Long tenantId) {
            APPLIES.incrementAndGet();
            return super.updateProductForAgent(id, request, tenantId);
        }
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

    private static String batchStatus(String batchId) {
        Object v = scalar("SELECT status FROM agent_batches WHERE id = '" + batchId + "'");
        return v == null ? null : v.toString();
    }

    private static String productStatus() {
        Object v = scalar("SELECT status FROM products WHERE id = '" + PRODUCT_ID + "'");
        return v == null ? null : v.toString();
    }

    private static List<String> itemStatuses(String batchId) {
        Object v = scalar("SELECT array_agg(status ORDER BY id)::text FROM agent_batch_items"
                + " WHERE batch_id = '" + batchId + "'");
        if (v == null) {
            return List.of();
        }
        String raw = v.toString();
        String inner = raw.substring(1, raw.length() - 1);
        return inner.isEmpty() ? List.of() : List.of(inner.split(","));
    }

    // ────────────────────────────────────────────── schema / 夹具

    /**
     * 插一个 {@code preview} 批次 + N 条 {@code pending} 明细（绕开服务层：本方法只造夹具，
     * 不走业务规则）。每条明细的 {@code oldValue} = 当前 DB 值、{@code newValue} = 目标值。
     */
    private static String seedPreviewBatch(String batchId, String oldValue, String newValue, int items) {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute("INSERT INTO agent_batches (id, tenant_id, batch_type, status, item_count,"
                    + " success_count, fail_count, created_by) VALUES ('" + batchId + "', " + TENANT_ID
                    + ", 'product_status', 'preview', " + items + ", 0, 0, 'ab-6960')");
            for (int i = 0; i < items; i++) {
                st.execute("INSERT INTO agent_batch_items (batch_id, tenant_id, resource_id, field,"
                        + " old_value, new_value, status) VALUES ('" + batchId + "', " + TENANT_ID
                        + ", '" + PRODUCT_ID + "', 'status', '" + oldValue + "', '" + newValue
                        + "', 'pending')");
            }
        } catch (SQLException e) {
            throw new IllegalStateException("批次夹具落库失败: " + batchId, e);
        }
        // 商品起点与批次的 oldValue 对齐（每条明细都指向同一商品 ⇒ 终态可复算）
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute("UPDATE products SET status = '" + oldValue + "' WHERE id = '" + PRODUCT_ID + "'");
        } catch (SQLException e) {
            throw new IllegalStateException("商品起点复位失败", e);
        }
        return batchId;
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
