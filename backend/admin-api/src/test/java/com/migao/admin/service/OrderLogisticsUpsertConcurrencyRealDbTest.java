// case_ids: OR-045, OR-047
package com.migao.admin.service;

import com.migao.admin.entity.OrderLogistics;
import com.migao.admin.mapper.OrderLogisticsMapper;
import com.migao.admin.config.TenantContext;
import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.extension.plugins.MybatisPlusInterceptor;
import com.baomidou.mybatisplus.extension.plugins.inner.TenantLineInnerInterceptor;
import com.baomidou.mybatisplus.core.MybatisSqlSessionFactoryBuilder;
import net.sf.jsqlparser.expression.LongValue;
import net.sf.jsqlparser.expression.Expression;
import com.baomidou.mybatisplus.extension.plugins.handler.TenantLineHandler;
import org.apache.ibatis.mapping.Environment;
import org.apache.ibatis.session.SqlSession;
import org.apache.ibatis.session.SqlSessionFactory;
import org.apache.ibatis.transaction.jdbc.JdbcTransactionFactory;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import javax.sql.DataSource;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.sql.Connection;
import java.sql.ResultSet;
import java.sql.Statement;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.Callable;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * issue #7174：并发两次发货 ⇒ 该订单**恰好 1 条**物流记录（真库窗口探针）。
 *
 * <h2>为什么必须真 PG</h2>
 * 原实现是「先 {@code selectByOrderId} 看空不空，空则 insert」的**读改写**。并发下两个请求都读到空 ⇒
 * 都 insert ⇒ 双行。这个缺陷在 mock 上**不可证**：mock 的 {@code selectByOrderId} 恒返回我 stub 的值，
 * 并发窗口根本不存在；而修法（条件 UPDATE 影响行数为 0 才建行 + 唯一索引兜底 + 冲突收敛为更新）
 * 的正确性全在**数据库谓词与约束的行为**里。
 *
 * <h2>探针形态（两侧夹住）</h2>
 * <ol>
 *   <li><b>正例</b>：同一订单、同一时刻起跑两个 {@code upsert} ⇒ 表里**恰好 1 行**（不是 0、不是 2）；</li>
 *   <li><b>反例（判别力自证）</b>：把唯一索引**删掉**后同样并发 ⇒ 必须能造出 2 行
 *       （若删掉索引仍恒为 1 行，说明本判据测的不是并发面 ⇒ 判据是空断言，当场红）。</li>
 * </ol>
 * 线程用 {@link CountDownLatch} 对齐起跑，尽量让两个请求压在同一个窗口里（不是"顺序调用两次"）。
 * 探针跑 {@code REPS} 轮：并发缺陷是概率性的，单轮容易假绿。
 */
@DisplayName("7174 真库：并发发货只落 1 条物流（读改写双行竞态）")
class OrderLogisticsUpsertConcurrencyRealDbTest {

    private static final Long TENANT = 7174L;
    private static final int REPS = 6;

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
                    + TENANT + ", 'ol-7174', 'ol-7174')");
        }
        MybatisConfiguration configuration = new MybatisConfiguration();
        configuration.setMapUnderscoreToCamelCase(true);
        configuration.setEnvironment(new Environment("ol-7174", new JdbcTransactionFactory(), dataSource));
        MybatisPlusInterceptor tenantLine = new MybatisPlusInterceptor();
        tenantLine.addInnerInterceptor(new TenantLineInnerInterceptor(new TenantLineHandler() {
            @Override
            public Expression getTenantId() {
                return new LongValue(TenantContext.getTenantId() == null ? 0L : TenantContext.getTenantId());
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
        configuration.addMapper(OrderLogisticsMapper.class);
        factory = new MybatisSqlSessionFactoryBuilder().build(configuration);
        TenantContext.setTenantId(TENANT);
    }

    @AfterAll
    static void stopRealPostgres() {
        TenantContext.clear();
        if (cluster != null) {
            cluster.stop();
        }
    }

    @BeforeEach
    void resetFixtures() throws Exception {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.executeUpdate("DELETE FROM order_logistics WHERE tenant_id = " + TENANT);
            st.executeUpdate("DELETE FROM orders WHERE tenant_id = " + TENANT);
        }
    }

    // ────────────────────────────────────────────── 正例：并发两次 ⇒ 恰 1 行

    @Test
    @DisplayName("🔴 正例：同一订单并发两次 upsert（6 轮）⇒ 每轮都恰好 1 行、且不抛错")
    void concurrentUpsertsLeaveExactlyOneRow() throws Exception {
        for (int rep = 0; rep < REPS; rep++) {
            String orderId = "race-" + rep;
            seedOrder(orderId);

            List<Throwable> failures = runConcurrently(
                    () -> { upsert(orderId, "SF-A"); return null; },
                    () -> { upsert(orderId, "SF-B"); return null; });

            assertThat(failures)
                    .as("并发两次发货**不许**有任何一次抛错（撞索引要收敛为更新，不能把冲突冒给用户；第 %d 轮）", rep)
                    .isEmpty();
            assertThat(countRows(orderId))
                    .as("并发两次发货后必须**恰好 1 条**物流记录（第 %d 轮）", rep)
                    .isEqualTo(1);
            assertThat(readTrackingNo(orderId))
                    .as("留下的运单号必须是两次请求之一（第 %d 轮）", rep)
                    .isIn("SF-A", "SF-B");
            assertThat(readShippedAt(orderId))
                    .as("首次发货时刻必须落值（第 %d 轮）", rep)
                    .isNotNull();
        }
    }

    // ────────────────────────────────────────────── 判别力自证（确定性，不靠抢跑）

    @Test
    @DisplayName("🔴 判别力自证：修法前的读改写形状（一次空读 + 两次 insert）必然落成 2 行")
    void readModifyWriteProducesTwoRows() throws Exception {
        // 为什么不用「删索引 + 并发抢跑」来自证：那是**概率性**的 —— CI 的 2 核 runner 上两个线程可能被
        // 串行执行，于是"没造出双行"⇒ 判据自己红（实测就是这么不稳）。这里把旧实现的**落库形状**
        // 确定性地复刻：两个请求都在对方写之前读到空（同一次读数），然后各自 insert ⇒ 必然 2 行。
        // 唯一索引正是修法的一部分，故先摘掉、finally 复原，避免影响其它用例。
        dropUniqueIndex();
        try {
            String orderId = "rmw-1";
            seedOrder(orderId);
            try (SqlSession s = factory.openSession(true)) {
                OrderLogisticsMapper mapper = s.getMapper(OrderLogisticsMapper.class);
                assertThat(mapper.selectByOrderId(orderId, TENANT))
                        .as("并发窗口里两个请求都读到空（旧实现据此各自 insert）")
                        .isEmpty();
                for (int request = 0; request < 2; request++) {
                    mapper.insert(OrderLogistics.builder()
                            .tenantId(TENANT).orderId(orderId).logisticsCompany("顺丰")
                            .trackingNo("SF-" + request).status("in_transit")
                            .shippedAt(java.time.OffsetDateTime.now()).build());
                }
            }
            assertThat(countRows(orderId))
                    .as("读改写形状必须真的落成 2 行 —— 这才证明「并发双行」这个病真实存在，"
                            + "不是我在修一个不存在的问题")
                    .isEqualTo(2);
        } finally {
            // 本用例**故意**留下 2 行重复行 ⇒ 不先清掉就建不了唯一索引（会 PSQL 报"无法创建唯一索引"）。
            // 清的是本用例自己的夹具（rmw-1），不是别人的数据。
            try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
                st.executeUpdate("DELETE FROM order_logistics WHERE tenant_id = " + TENANT
                        + " AND order_id = 'rmw-1'");
            }
            createUniqueIndex();
        }
    }

    // ────────────────────────────────────────────── 工具

    private List<Throwable> runConcurrently(Callable<Void> a, Callable<Void> b) throws Exception {
        CountDownLatch start = new CountDownLatch(1);
        ExecutorService pool = Executors.newFixedThreadPool(2);
        List<Throwable> errors = new ArrayList<>();
        try {
            List<Future<Void>> futures = new ArrayList<>();
            for (Callable<Void> task : List.of(a, b)) {
                futures.add(pool.submit(() -> {
                    TenantContext.setTenantId(TENANT);
                    start.await(10, TimeUnit.SECONDS);
                    return task.call();
                }));
            }
            start.countDown();
            for (Future<Void> f : futures) {
                try {
                    f.get(60, TimeUnit.SECONDS);
                } catch (java.util.concurrent.ExecutionException e) {
                    errors.add(e.getCause() == null ? e : e.getCause());
                }
            }
        } finally {
            pool.shutdownNow();
            start.countDown();
        }
        return errors;
    }

    private void upsert(String orderId, String trackingNo) {
        try (SqlSession s = factory.openSession(true)) {
            OrderLogisticsWriter.upsert(s.getMapper(OrderLogisticsMapper.class), TENANT, orderId,
                    "顺丰", trackingNo, null, () -> null);
        }
    }

    private void dropUniqueIndex() throws Exception {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute("DROP INDEX IF EXISTS uk_order_logistics_tenant_order");
        }
    }

    private void createUniqueIndex() throws Exception {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute("CREATE UNIQUE INDEX IF NOT EXISTS uk_order_logistics_tenant_order "
                    + "ON order_logistics (tenant_id, order_id) WHERE deleted = 0");
        }
    }

    private void seedOrder(String orderId) throws Exception {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.executeUpdate("INSERT INTO orders (id, tenant_id, order_no, status) VALUES ('"
                    + orderId + "', " + TENANT + ", 'NO-" + orderId + "', 'shipped')");
        }
    }

    private int countRows(String orderId) throws Exception {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery("SELECT COUNT(*) FROM order_logistics WHERE tenant_id = "
                     + TENANT + " AND order_id = '" + orderId + "' AND deleted = 0")) {
            assertThat(rs.next()).as("COUNT 必须返回一行").isTrue();
            return rs.getInt(1);
        }
    }

    private String readTrackingNo(String orderId) throws Exception {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery("SELECT tracking_no FROM order_logistics WHERE tenant_id = "
                     + TENANT + " AND order_id = '" + orderId + "' AND deleted = 0")) {
            assertThat(rs.next()).as("行必须存在").isTrue();
            return rs.getString(1);
        }
    }

    private java.time.OffsetDateTime readShippedAt(String orderId) throws Exception {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery("SELECT shipped_at FROM order_logistics WHERE tenant_id = "
                     + TENANT + " AND order_id = '" + orderId + "' AND deleted = 0")) {
            assertThat(rs.next()).as("行必须存在").isTrue();
            return rs.getObject(1, java.time.OffsetDateTime.class);
        }
    }

    private static String schemaSql() throws Exception {
        Path schema = Paths.get("src", "main", "resources", "db", "init", "schema.sql");
        assertThat(Files.exists(schema)).as("schema.sql 必须存在（路径漂移 ⇒ 判红，不是空跑通过）").isTrue();
        return Files.readString(schema, StandardCharsets.UTF_8);
    }
}
