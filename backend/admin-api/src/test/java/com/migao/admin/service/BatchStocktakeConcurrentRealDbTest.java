// case_ids: MC-081

package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.MybatisSqlSessionFactoryBuilder;
import com.baomidou.mybatisplus.extension.plugins.MybatisPlusInterceptor;
import com.baomidou.mybatisplus.extension.plugins.handler.TenantLineHandler;
import com.baomidou.mybatisplus.extension.plugins.inner.TenantLineInnerInterceptor;
import com.migao.admin.dto.BatchStockViews;
import com.migao.admin.dto.BatchStocktakeRequest;
import com.migao.admin.entity.StockBatchConsumption;
import com.migao.admin.mapper.ProductSkuMapper;
import com.migao.admin.mapper.StockBatchConsumptionMapper;
import com.migao.admin.mapper.StockBatchMapper;
import com.migao.admin.mapper.StockLedgerMapper;
import com.migao.admin.time.BusinessClock;
import net.sf.jsqlparser.expression.Expression;
import net.sf.jsqlparser.expression.LongValue;
import org.apache.ibatis.exceptions.PersistenceException;
import org.apache.ibatis.mapping.Environment;
import org.apache.ibatis.session.LocalCacheScope;
import org.apache.ibatis.session.SqlSession;
import org.apache.ibatis.session.SqlSessionFactory;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mybatis.spring.transaction.SpringManagedTransactionFactory;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

import javax.sql.DataSource;
import java.io.IOException;
import java.lang.reflect.InvocationHandler;
import java.lang.reflect.Method;
import java.lang.reflect.Proxy;
import java.math.BigDecimal;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.sql.Connection;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;
import java.util.concurrent.CyclicBarrier;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 🔴 <b>同一个 run id 的盘点**并发/重复请求**必须拿到**幂等回执**（不是 500）</b> ——
 * issue #6301 的真库判据（类级元守卫在 {@code tests/unit_ci_workflows/test_idempotent_unique_write_guard.py}）。
 *
 * <h2>缺陷（已在 main 上复现，两个构建点都红）</h2>
 * 同一 run id 的盘点请求**并发 6 次** ⇒ 回执 {@code [200,500,500,500,500,500]}：本应是
 * 「一次生效 + 其余幂等回放」，实际 5 条变成 HTTP 500。**防双记本身有效**（分录终态 1 行、
 * 库存 Δ 正确）⇒ 缺陷在**错误映射/回执语义**，不在数据正确性。
 *
 * <p>根因：{@code stocktakeRecordedBatchIds} 是「先查是否已记 → 再插入」的**非原子读**；
 * 并发时多个请求同时判定「未记」，随后争抢部分唯一索引 {@code uk_batch_consumption_stocktake}，
 * 落库时抛 {@code DuplicateKeyException} —— 而该异常**未映射成幂等回执**，直接冒泡成 500。</p>
 *
 * <h2>为什么必须真 PG（mock 面结构上不可见）</h2>
 * 「两个请求同时在『查』之后、『插』之前」这件事只由真 PG 的两件事决定：① 唯一索引在**插入那一刻**
 * 的原子判定；② 未提交行对并发事务的可见性（B 的 SELECT 看不见 A 未提交的行）。mock 面上
 * {@code selectList} 恒返回空、{@code insert} 恒成功 ⇒ 窗口**结构上不存在**。
 *
 * <h2>判别力（红证 = 注入式 · 双向）</h2>
 * ① <b>并发窗口是判据本身</b>（{@code sameRunIdConcurrentRequestsAllGetIdempotentReceipt}）：
 * {@link CyclicBarrier} 把 6 个请求**全部压过「查」这一步**才放行提交 ⇒ 窗口从「偶发」变「必现」。
 * 修前读数 = 5/6 拿到 {@code PersistenceException}（PG 23505）⇒ 用户侧 500；修后 = 6/6 幂等回执。
 * ② <b>注入式红证</b>（{@code naiveInsertStillHitsTheUniqueIndex}）：把生产写入路径换回
 * 「朴素 {@code insert}」（{@link java.lang.reflect.Proxy} 只替换一个方法、其余原样转发真 mapper）
 * ⇒ 第二条同 run × 批次当场 23505。这条读数自证「唯一索引真的会拒第二行」不是空断言。
 *
 * <p><b>边界（如实登记，§19.1）</b>：① 本判据跑的是<b>服务层 + 真库</b>而非 HTTP 栈；「服务层的
 * 唯一键异常 ⇒ 全局处理器读成 500」这条映射由既有 {@code BatchNoTakeRaceRealDbTest}（#6248）
 * 在**同类异常**上核过，本文件**不复制**那条判据；② 并发度 6 与探针 W5 逐字一致；③ 探针对象全部自建
 * （tenant {@value #TENANT_ID} / 货号 {@value #PRODUCT_ID}），随一次性临时集群销毁，
 * <b>不碰任何存量数据</b>；④ 它**不**证「两个**不同** run id 并发盘同一批次的取数口径」
 * —— 那是实现自己登记的既有边界（本单**不动**它、也不假装它被修了）。</p>
 */
@DisplayName("🔴 真库并发判据（#6301）：同 run id 并发/重复盘点 ⇒ 幂等回执（replayed + 不双记）")
class BatchStocktakeConcurrentRealDbTest {

    private static final Long TENANT_ID = 6301L;
    private static final String PRODUCT_ID = "acc-6301-stocktake";
    private static final Long SKU_ID = 630101L;
    private static final String SKU_CODE = "SKU-6301-C";
    private static final BigDecimal STOCK_BEFORE = new BigDecimal("60.0");

    /** 并发度 = issue #6301 探针 W5 的读数口径（6 次并发 ⇒ 修前 `[200,500×5]`）。 */
    private static final int CONCURRENCY = 6;

    private static PgCluster cluster;
    private static DataSource dataSource;
    private static SqlSessionFactory factory;
    private static TransactionTemplate txTemplate;

    @BeforeAll
    static void startRealPostgresAndFixtures() throws Exception {
        cluster = PgCluster.startOrAbort();
        dataSource = cluster.dataSource();
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute(schemaSql());
            st.execute("INSERT INTO tenants (id, name, code) OVERRIDING SYSTEM VALUE VALUES ("
                    + TENANT_ID + ", 'acc-6301', 'acc-6301')");
            st.execute("INSERT INTO products (id, tenant_id, name) VALUES ('" + PRODUCT_ID + "', "
                    + TENANT_ID + ", '布艺遮光帘-盘点并发')");
            st.execute("INSERT INTO product_skus (id, tenant_id, product_id, door_width, price, stock,"
                    + " sku_code) OVERRIDING SYSTEM VALUE VALUES (" + SKU_ID + ", " + TENANT_ID
                    + ", '" + PRODUCT_ID + "', '2.8米', 100, " + STOCK_BEFORE.toPlainString()
                    + ", '" + SKU_CODE + "')");
        }
        MybatisConfiguration configuration = new MybatisConfiguration();
        configuration.setMapUnderscoreToCamelCase(true);
        // STATEMENT 级一级缓存：判据里会用裸 JDBC 读数（SESSION 级缓存会让「改完再查」读回改前的值）
        configuration.setLocalCacheScope(LocalCacheScope.STATEMENT);
        // Spring 事务工厂（判据要在**真事务**里跑生产写入路径；生产侧同款边界由
        // `BatchStocktakeService#stocktake` 的 `@Transactional` 提供 —— 与 BatchStocktakeRealDbTest 同款）
        configuration.setEnvironment(new Environment("acc-6301",
                new SpringManagedTransactionFactory(), dataSource));
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
        for (Class<?> mapper : List.of(StockBatchMapper.class, StockBatchConsumptionMapper.class,
                ProductSkuMapper.class, StockLedgerMapper.class)) {
            configuration.addMapper(mapper);
        }
        factory = new MybatisSqlSessionFactoryBuilder().build(configuration);
        txTemplate = new TransactionTemplate(new DataSourceTransactionManager(dataSource));
    }

    @AfterAll
    static void stopRealPostgres() {
        if (cluster != null) {
            cluster.stop();
        }
    }

    /**
     * 每个判据开始前把 SKU 库存复位（判据之间共享同一个租户 / SKU ⇒ 不复位会让读数互相污染：
     * 实测「库存是 57.0 而不是 58.5」正是上一条判据留下的 Δ，不是被测代码的缺陷）。
     */
    @BeforeEach
    void resetSkuStock() {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute("UPDATE product_skus SET stock = " + STOCK_BEFORE.toPlainString()
                    + " WHERE id = " + SKU_ID);
        } catch (SQLException e) {
            throw new IllegalStateException("库存复位失败", e);
        }
    }

    // ══════════════════════════════════ 判据 ①（主判据）：同 run id 并发 ⇒ 幂等回执

    /**
     * 🔴 <b>6 个**同一 run id、同一批次**的并发盘点全部必须拿到幂等回执</b>（无故障、无异常），
     * 且分录终态**恰好一行**、库存 Δ 恰好一次。
     *
     * <p>注入方式（= 让窗口必现的那个动作）：{@link CyclicBarrier} 把 6 个请求**全部压过「查已记批次」
     * 这一步**之后才放行提交 ⇒ 6 个请求必然都判定「未记」⇒ 修前必然争抢唯一索引。</p>
     */
    @Test
    @DisplayName("🔴 判据①：同 run id 并发 6 次 ⇒ 全部幂等回执（1 applied + 5 replayed）、分录 1 行、库存 Δ 一次")
    void sameRunIdConcurrentRequestsAllGetIdempotentReceipt() throws Exception {
        long batchId = newBatch("PC-6301-C1");
        CyclicBarrier afterPreRead = new CyclicBarrier(CONCURRENCY);
        List<Outcome> outcomes = runConcurrently(CONCURRENCY,
                () -> stocktakeAfterPreRead("PD-6301-C1", batchId, "58.5", afterPreRead));

        System.out.println("[#6301 判据①] 并发 6 次的逐请求回执 = " + statusesOf(outcomes));
        assertThat(statusesOf(outcomes))
                .as("同 run id 的并发请求**不得**出现故障（修前 = 唯一键异常 ⇒ 500）")
                .containsOnly("OK");
        assertThat(appliedCount(outcomes)).as("恰好一次生效").isEqualTo(1);
        assertThat(replayedCount(outcomes)).as("其余 5 次必须是幂等回放").isEqualTo(CONCURRENCY - 1);

        assertThat(entriesOfRun("PD-6301-C1")).as("防双记：分录终态恰好 1 行").isEqualTo(1);
        // 🔴 库存面：**本次 run** 只许有**一条** 60.0→58.5 的库存链（销售账的不变式 = 相邻行首尾相接）。
        // 修前 / 摘掉并发回放处理时会是两条（每个并发请求各写一次 `stock += delta`）或终点漂到 57.0。
        List<String> chain = ledgerChainOfRun("PD-6301-C1");
        System.out.println("[#6301 判据①] 本次 run 的库存链读数 = " + chain);
        assertThat(chain).as("库存 Δ 只发生一次（恰好一条 60.0→58.5）")
                .containsExactly(STOCK_BEFORE.toPlainString() + "->58.5");
        assertThat(skuStock()).as("SKU 库存终态 = 58.5").isEqualByComparingTo("58.5");
    }

    // ══════════════════════════════════ 判据 ②：顺序重复（回归防误伤）

    /**
     * 顺序对照（issue #6301 的 RP1 读数）：同 run id **顺序**两次 ⇒ 第二次是幂等回放（{@code changed=0}）。
     *
     * <p>它是**防误伤**的那一半：把并发修成幂等时，不许把「已记过就跳过」这条既有语义改掉。</p>
     */
    @Test
    @DisplayName("判据②（顺序对照）：同 run id 第二次 ⇒ replayed=1 且真库零写入（既有语义不得被改掉）")
    void sequentialReplayStaysIdempotent() throws Exception {
        long batchId = newBatch("PC-6301-C2");
        try (SqlSession s = factory.openSession(true)) {
            BatchStockViews.StocktakeResult first = serviceOn(s).stocktake(TENANT_ID, PRODUCT_ID,
                    "PD-6301-C2", List.of(line(batchId, "58.5")));
            assertThat(first.changedCount()).isEqualTo(1);
        }
        int entriesBefore = entriesOfRun("PD-6301-C2");
        BigDecimal stockBefore = skuStock();

        try (SqlSession s = factory.openSession(true)) {
            BatchStockViews.StocktakeResult replay = serviceOn(s).stocktake(TENANT_ID, PRODUCT_ID,
                    "PD-6301-C2", List.of(line(batchId, "58.5")));
            System.out.println("[#6301 判据②] 顺序第二次读数：changed=" + replay.changedCount()
                    + ", replayed=" + replay.replayedCount());
            assertThat(replay.replayedCount()).isEqualTo(1);
            assertThat(replay.changedCount()).isZero();
        }
        assertThat(entriesOfRun("PD-6301-C2")).as("重放不得双记").isEqualTo(entriesBefore);
        assertThat(skuStock()).as("重放不得再动库存").isEqualByComparingTo(stockBefore);
    }

    // ══════════════════════════════════ 判据 ③：唯一索引的注入式红证

    /**
     * 🔴 <b>判据③：唯一索引真的会拒第二行（注入式红证的自证）</b>。
     *
     * <p>做法：用 {@link Proxy} 把真 mapper 的 **{@code insertStocktakeIfAbsent} 换回朴素
     * {@code BaseMapper.insert}**（其余方法原样转发真 mapper ⇒ 写入仍走真库）⇒ 同一 run × 批次的
     * 第二行当场 23505（{@code PersistenceException}）。</p>
     *
     * <p>为什么必须留这条：并发判据的「修后全绿」必须能区分「修好了」与「本来就不撞」。
     * 这条读数证明**撞是真的**（唯一索引在场且生效），于是判据①的绿才有意义。</p>
     */
    @Test
    @DisplayName("🔴 判据③：把原子插入换回朴素 insert ⇒ 第二条同 run×批次当场 23505（唯一索引真的在场）")
    void naiveInsertStillHitsTheUniqueIndex() throws Exception {
        long batchId = newBatch("PC-6301-C3");
        try (SqlSession s = factory.openSession(true)) {
            StockBatchConsumptionService plain = naiveInsertServiceOn(s);
            List<StockBatchConsumptionService.StocktakeAdjustment> one = List.of(adjustmentOf(s, batchId));
            Set<Long> first = plain.applyStocktake(TENANT_ID, "PD-6301-C3", one);
            assertThat(first).as("第一条必须落库（否则下面的注入读数没有判别力）").containsExactly(batchId);

            boolean hit = false;
            try {
                plain.applyStocktake(TENANT_ID, "PD-6301-C3", one);
            } catch (RuntimeException expected) {
                // 真库原始会话不经过 Spring 的异常翻译 ⇒ 这里期待 PersistenceException（PG 23505 的包装）
                hit = expected instanceof PersistenceException
                        || String.valueOf(expected.getMessage()).contains("23505")
                        || String.valueOf(expected.getCause()).contains("duplicate key");
                System.out.println("[#6301 判据③] 朴素 insert 注入下第二条的异常 = "
                        + expected.getClass().getName() + " / 撞唯一索引 = " + hit);
            }
            assertThat(hit).as("注入必须真的能拦住第二条同 run×批次的行（否则判据无判别力）").isTrue();
        }
        assertThat(entriesOfRun("PD-6301-C3")).as("注入下仍只有 1 行（唯一索引在真库上生效）").isEqualTo(1);
    }

    // ══════════════════════════════════ 装置

    /** 一次请求的**可读结果**：状态 + applied/replayed 计数（把「拿到什么回执」变成可断言的读数）。 */
    private record Outcome(String status, int applied, int replayed) {
    }

    /**
     * 跑一次「先查已记批次（会合）→ 再提交」的请求，返回可读结果。
     *
     * <p>会合点为什么在**查之后**：这正是缺陷窗口（TOCTOU）的位置 —— 6 个请求全部越过「查」，
     * 谁也没看到别人未提交的行，才谈得上争抢唯一索引。</p>
     */
    private static Outcome stocktakeAfterPreRead(String runId, long batchId, String meters,
                                                 CyclicBarrier afterPreRead) {
        try (SqlSession s = factory.openSession(true)) {
            batchServiceOn(s).stocktakeRecordedBatchIds(TENANT_ID, runId);   // 「查」这一步按生产顺序先跑
            afterPreRead.await(30, TimeUnit.SECONDS);                        // 6 个请求对齐 ⇒ 窗口必现
            return txTemplate.execute(status -> {
                try (SqlSession tx = factory.openSession(true)) {
                    BatchStockViews.StocktakeResult r = serviceOn(tx).stocktake(TENANT_ID, PRODUCT_ID,
                            runId, List.of(line(batchId, meters)));
                    return new Outcome("OK", r.changedCount(), r.replayedCount());
                }
            });
        } catch (Exception e) {
            // 回执语义的读数：修前这里是唯一键异常（⇒ 全局处理器读成 500）
            return new Outcome("FAIL:" + e.getClass().getSimpleName(), 0, 0);
        }
    }

    private static List<Outcome> runConcurrently(int n, Task task) throws Exception {
        ExecutorService pool = Executors.newFixedThreadPool(n);
        try {
            List<Future<Outcome>> futures = new ArrayList<>();
            CyclicBarrier start = new CyclicBarrier(n);
            for (int i = 0; i < n; i++) {
                futures.add(pool.submit(() -> {
                    start.await(30, TimeUnit.SECONDS);
                    return task.run();
                }));
            }
            List<Outcome> out = new ArrayList<>();
            for (Future<Outcome> f : futures) {
                out.add(f.get(60, TimeUnit.SECONDS));
            }
            return out;
        } finally {
            pool.shutdownNow();
        }
    }

    /** 一次并发请求（无参数：批次 id / 会合点由闭包带）。 */
    private interface Task {
        Outcome run() throws Exception;
    }

    private static List<String> statusesOf(List<Outcome> outcomes) {
        List<String> out = new ArrayList<>();
        for (Outcome o : outcomes) {
            out.add(o.status());
        }
        return out;
    }

    private static int appliedCount(List<Outcome> outcomes) {
        int n = 0;
        for (Outcome o : outcomes) {
            n += o.applied();
        }
        return n;
    }

    private static int replayedCount(List<Outcome> outcomes) {
        int n = 0;
        for (Outcome o : outcomes) {
            n += o.replayed();
        }
        return n;
    }

    // ══════════════════════════════════ 装配

    private static BatchStocktakeService serviceOn(SqlSession s) {
        return new BatchStocktakeService(batchServiceOn(s), s.getMapper(ProductSkuMapper.class),
                new StockLedgerService(s.getMapper(StockLedgerMapper.class),
                        s.getMapper(ProductSkuMapper.class)));
    }

    private static StockBatchConsumptionService batchServiceOn(SqlSession s) {
        return new StockBatchConsumptionService(s.getMapper(StockBatchMapper.class),
                s.getMapper(StockBatchConsumptionMapper.class), s.getMapper(ProductSkuMapper.class),
                s.getMapper(StockLedgerMapper.class), null, null, new BusinessClock());
    }

    /**
     * **注入面**（纯测试侧）：把真 mapper 的原子落账 {@code insertStocktakeIfAbsent} 换回朴素的
     * {@code BaseMapper.insert}（= 修前形态），其余方法<b>全部原样转发</b>真 mapper。
     *
     * <p>不用 Mockito：判据必须打**真 mapper**（唯一索引的原子判定就是主判据），mock 会把
     * 「DB 判冲突」换成恒成功 ⇒ 判据当场失去意义。</p>
     */
    private static StockBatchConsumptionService naiveInsertServiceOn(SqlSession s) {
        StockBatchConsumptionMapper real = s.getMapper(StockBatchConsumptionMapper.class);
        StockBatchConsumptionMapper naive = (StockBatchConsumptionMapper) Proxy.newProxyInstance(
                StockBatchConsumptionMapper.class.getClassLoader(),
                new Class<?>[]{StockBatchConsumptionMapper.class},
                new InvocationHandler() {
                    @Override
                    public Object invoke(Object proxy, Method method, Object[] args) throws Throwable {
                        if ("insertStocktakeIfAbsent".equals(method.getName()) && args != null
                                && args.length == 1 && args[0] instanceof StockBatchConsumption row) {
                            return real.insert(row);      // ← 注入：没有 ON CONFLICT ⇒ 第二条撞唯一索引
                        }
                        return method.invoke(real, args);
                    }
                });
        return new StockBatchConsumptionService(s.getMapper(StockBatchMapper.class), naive,
                s.getMapper(ProductSkuMapper.class), s.getMapper(StockLedgerMapper.class), null, null, new BusinessClock());
    }

    /** 造一条盘点调整（盘前余量按真库现值读，测试不自己算第二份余量口径）。 */
    private static StockBatchConsumptionService.StocktakeAdjustment adjustmentOf(SqlSession s, long batchId) {
        for (BatchStockViews.BatchRemaining r : batchServiceOn(s).remaining(TENANT_ID, PRODUCT_ID, null, false)) {
            if (r.batchId() == batchId) {
                return new StockBatchConsumptionService.StocktakeAdjustment(r, new BigDecimal("-1.5"));
            }
        }
        throw new IllegalStateException("批次 " + batchId + " 不在余量读面里");
    }

    // ══════════════════════════════════ 夹具与读数

    private static BatchStocktakeRequest.Line line(long batchId, String meters) {
        BatchStocktakeRequest.Line l = new BatchStocktakeRequest.Line();
        l.setBatchId(batchId);
        l.setActualMeters(new BigDecimal(meters));
        return l;
    }

    private static final AtomicInteger BATCH_SEQ = new AtomicInteger(0);

    private static long newBatch(String batchNoPrefix) throws SQLException {
        String batchNo = batchNoPrefix + "-" + BATCH_SEQ.incrementAndGet();
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery("INSERT INTO stock_batches (tenant_id, batch_no, product_id,"
                     + " sku_id, sku_code, quantity, unit_cost) VALUES (" + TENANT_ID + ", '" + batchNo
                     + "', '" + PRODUCT_ID + "', " + SKU_ID + ", '" + SKU_CODE + "', "
                     + STOCK_BEFORE.toPlainString() + ", 12.5) RETURNING id")) {
            assertThat(rs.next()).as("批次夹具必须落库").isTrue();
            return rs.getLong(1);
        }
    }

    private static int entriesOfRun(String runId) {
        return count("SELECT count(*) FROM stock_batch_consumptions WHERE stocktake_run_id = '"
                + runId + "'");
    }

    private static BigDecimal skuStock() {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery("SELECT stock FROM product_skus WHERE id = " + SKU_ID)) {
            assertThat(rs.next()).isTrue();
            return rs.getBigDecimal(1);
        } catch (SQLException e) {
            throw new IllegalStateException(e);
        }
    }

    /**
     * **本次 run** 的库存链读数（逐行 {@code before→after}，按 {@code ref_no} 关联到本 run 的批次）：
     * 销售账的不变式是「相邻两行首尾相接」⇒「只发生一次 Δ」= 恰好一条链。
     */
    private static List<String> ledgerChainOfRun(String runId) {
        List<String> out = new ArrayList<>();
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery("SELECT before_qty || '->' || after_qty"
                     + " FROM stock_ledger_entries WHERE tenant_id = " + TENANT_ID
                     + " AND ref_no IN (SELECT batch_no FROM stock_batch_consumptions"
                     + " WHERE stocktake_run_id = '" + runId + "') ORDER BY id")) {
            while (rs.next()) {
                out.add(rs.getString(1));
            }
        } catch (SQLException e) {
            throw new IllegalStateException("库存链读数失败", e);
        }
        return out;
    }

    private static int count(String sql) {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery(sql)) {
            assertThat(rs.next()).isTrue();
            return rs.getInt(1);
        } catch (SQLException e) {
            throw new IllegalStateException("读数 SQL 失败: " + sql, e);
        }
    }

    /** bootstrap 终态 schema（**不手抄列清单** ⇒ 列名 / 约束漂移会被抓）。 */
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
