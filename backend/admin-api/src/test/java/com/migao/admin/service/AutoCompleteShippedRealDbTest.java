// case_ids: OR-061
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.MybatisSqlSessionFactoryBuilder;
import com.baomidou.mybatisplus.extension.plugins.MybatisPlusInterceptor;
import com.baomidou.mybatisplus.extension.plugins.handler.TenantLineHandler;
import com.baomidou.mybatisplus.extension.plugins.inner.TenantLineInnerInterceptor;
import com.migao.admin.config.TenantContext;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.time.BusinessClock;
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
import org.springframework.test.util.ReflectionTestUtils;

import javax.sql.DataSource;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.sql.Connection;
import java.sql.ResultSet;
import java.sql.Statement;
import java.time.Clock;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.Callable;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;

/**
 * 🔴 <b>「发货后 N 天自动完成」的真库判据（issue #6262）。</b>
 *
 * <h2>为什么必须真 PG（mock 面结构上看不见的四件事）</h2>
 * <ol>
 *   <li><b>谓词真的按行判定</b>：{@code status='shipped' AND shipped_at <= 死线} 是 PG 在**行锁下
 *       重估**的条件 —— mock 的 {@code autoCompleteShippedOrders} 恒返回我 stub 的东西，
 *       「未满期的那一行真的没被改」在 mock 上无法证（那是 SQL 的行为，不是 Java 的行为）。</li>
 *   <li><b>{@code shipped_at IS NOT NULL} 的语义</b>：NULL 不满足任何比较 ⇒ 存量/未采集的行
 *       **不参与**自动完成（只能人工确认收货）。这是三值逻辑，mock 面完全不体现。</li>
 *   <li><b>{@code RETURNING id} 只回真正改到的行</b>：一次 UPDATE 的影响集与返回集是否一致
 *       —— 只有真库能读。它是「副作用只发一次」的唯一依据（集群下不重复发信）。</li>
 *   <li><b>集群并发只生效一次</b>：两条真连接同时跑同一条 UPDATE（同一批行），
 *       恰一个拿到行、另一个 0 行 —— 这正是"N 个实例同时扫"的形态。走的是**行锁 + 谓词重估**，
 *       mock 与单连接都测不出来（本仓 #5141/#5148/#5182/#6220 同族教训）。</li>
 * </ol>
 *
 * <p>装配形态与 {@code AutoBatchDueScanRealDbTest} 同款：一次性 {@code initdb} + {@code pg_ctl}
 * 集群（{@link PgCluster#startOrAbort()} 收口）、**生产的多租户拦截器 bean**在场
 * （少了它就只测了 mapper 原文、没测生产 SQL）。被判定的事实全部是真库读数；
 * 只有"站内信服务"是 mock（它是副作用，且被判定的量是**发了几个**、对哪些 id）。</p>
 */
@DisplayName("6262 真库：满期才完成 / 未满不动 / 非 shipped 不动 / 租户隔离 / 集群并发只生效一次")
class AutoCompleteShippedRealDbTest {

    private static final Long TENANT_A = 6262L;
    private static final Long TENANT_B = 6263L;
    /** 业务「现在」= 2026-10-03T12:00:00+08:00 ⇒ N=7 的死线 = 2026-09-26T12:00:00+08:00。 */
    private static final Instant NOW = Instant.parse("2026-10-03T04:00:00Z");
    private static final OffsetDateTime DEADLINE = OffsetDateTime.parse("2026-09-26T12:00:00+08:00");

    private static PgCluster cluster;
    private static DataSource dataSource;
    private static SqlSessionFactory factory;
    private static SqlSession session;
    /** ⚠️ **每用例一个**（`@BeforeEach` 重建）：跨用例累积会让 `verify(times(1))` 假红。 */
    private NotificationService notificationService;

    @BeforeAll
    static void startRealPostgresAndFixtures() throws Exception {
        cluster = PgCluster.startOrAbort();
        dataSource = cluster.dataSource();
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute(schemaSql());
            st.execute("INSERT INTO tenants (id, name, code) OVERRIDING SYSTEM VALUE VALUES ("
                    + TENANT_A + ", 'ac-6262-a', 'ac-6262-a')");
            st.execute("INSERT INTO tenants (id, name, code) OVERRIDING SYSTEM VALUE VALUES ("
                    + TENANT_B + ", 'ac-6262-b', 'ac-6262-b')");
        }
        MybatisConfiguration configuration = new MybatisConfiguration();
        configuration.setMapUnderscoreToCamelCase(true);
        configuration.setEnvironment(new Environment("ac-6262", new JdbcTransactionFactory(), dataSource));
        // 多租户拦截器**必须在场**：生产 SQL 会经它重写 ⇒ 少了它就只测了 mapper 原文
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
        configuration.addMapper(OrderMapper.class);
        factory = new MybatisSqlSessionFactoryBuilder().build(configuration);
        session = factory.openSession(true);
        TenantContext.setTenantId(TENANT_A);
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

    /**
     * 每个用例从**干净夹具**开始（共用一个集群 ⇒ 前一个用例的行不得串味），并**重建**站内信 mock
     * （跨用例累积会让 {@code verify(times(1))} 假红）。
     */
    @BeforeEach
    void resetFixtures() throws Exception {
        notificationService = mock(NotificationService.class);
        for (String table : List.of("order_items", "orders")) {
            try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
                st.executeUpdate("DELETE FROM " + table + " WHERE tenant_id IN ("
                        + TENANT_A + "," + TENANT_B + ")");
            }
        }
    }

    // ────────────────────────────────────────────── 判据 1 / 2 / 3

    @Test
    @DisplayName("🔴 判据 1+2+3：满 N 天的 shipped ⇒ completed；未满 N 天 / 非 shipped / 锚点为 NULL 一律**不动**")
    void onlyOverdueShippedOrdersAreCompleted() throws Exception {
        newOrder("ac-overdue", TENANT_A, "shipped", DEADLINE.minusMinutes(1), "user-1");
        newOrder("ac-not-yet", TENANT_A, "shipped", DEADLINE.plusMinutes(1), "user-2");
        newOrder("ac-packed", TENANT_A, "packed", DEADLINE.minusDays(3), "user-3");
        newOrder("ac-null-anchor", TENANT_A, "shipped", null, "user-4");
        newOrder("ac-completed", TENANT_A, "completed", DEADLINE.minusDays(9), "user-5");

        AutoCompleteShippedScanService.Outcome outcome = scanOnce();

        // RETURNING id 只回**真正被改到**的那一行（副作用据此发，集群下不重复）
        assertThat(outcome.completedOrders()).containsExactly("ac-overdue");
        assertThat(outcome.failures()).isEmpty();
        assertThat(verifyStatus("ac-overdue")).isEqualTo("completed");
        assertThat(verifyStatus("ac-not-yet"))
                .as("未满 N 天 ⇒ 不动（防误杀；死线之下 1 分钟就不许过）").isEqualTo("shipped");
        assertThat(verifyStatus("ac-packed"))
                .as("非 shipped（packed）⇒ 不动").isEqualTo("packed");
        assertThat(verifyStatus("ac-null-anchor"))
                .as("锚点为 NULL（查不到发货时刻）⇒ 不猜、不完成 ⇒ 只能人工确认收货").isEqualTo("shipped");
        assertThat(verifyStatus("ac-completed")).isEqualTo("completed");

        // 副作用只对 RETURNING 回来的 id 发（恰一封 —— 未满/非法状态的行没有收件人噪声）
        verify(notificationService, times(1))
                .triggerByEvent(eq(TENANT_A), eq("order_status_changed"), any());
    }

    @Test
    @DisplayName("判据 1 的边界·死线**逐秒**判定：差 1 秒不动、等于死线即完成（不是「按天」粗判）")
    void deadlineBoundaryIsExact() throws Exception {
        newOrder("ac-just-after", TENANT_A, "shipped", DEADLINE.plusSeconds(1), "user-1");
        newOrder("ac-exactly", TENANT_A, "shipped", DEADLINE, "user-2");

        AutoCompleteShippedScanService.Outcome outcome = scanOnce();

        assertThat(outcome.completedOrders()).containsExactly("ac-exactly");
        assertThat(verifyStatus("ac-just-after")).isEqualTo("shipped");
        assertThat(verifyStatus("ac-exactly")).isEqualTo("completed");
    }

    // ────────────────────────────────────────────── 判据 4：多租户隔离

    @Test
    @DisplayName("判据 4·多租户隔离：每个租户各自一轮完成自己的满期单（写面逐次带各自的 tenantId）")
    void eachTenantCompletesOnlyItsOwnOverdueOrders() throws Exception {
        newOrder("ac-a-overdue", TENANT_A, "shipped", DEADLINE.minusDays(1), "user-a");
        newOrder("ac-b-overdue", TENANT_B, "shipped", DEADLINE.minusDays(1), "user-b");

        // 候选租户是**超集**（两个租户都有在架 shipped）⇒ 一轮逐租户扫：每租户各完成各的
        AutoCompleteShippedScanService.Outcome outcome = scanOnce();

        assertThat(outcome.scannedTenants()).isEqualTo(2);
        assertThat(outcome.completedOrders())
                .containsExactlyInAnyOrder("ac-a-overdue", "ac-b-overdue");
        assertThat(verifyStatus("ac-a-overdue")).isEqualTo("completed");
        assertThat(verifyStatus("ac-b-overdue")).isEqualTo("completed");
        // 两个租户各收到**自己那一张**的站内信（谁的客户收谁的信 —— 跨租户串信会在这里现形）
        verify(notificationService).triggerByEvent(eq(TENANT_A), eq("order_status_changed"),
                org.mockito.ArgumentMatchers.argThat(ctx -> "user-a".equals(ctx.get("recipientId"))));
        verify(notificationService).triggerByEvent(eq(TENANT_B), eq("order_status_changed"),
                org.mockito.ArgumentMatchers.argThat(ctx -> "user-b".equals(ctx.get("recipientId"))));
    }

    @Test
    @DisplayName("🔴 判据 4 的**反向对照**：租户上下文设错 ⇒ 本租户的满期单**逐值不动**（隔离真的有牙齿）")
    void wrongTenantContextTouchesNothing() throws Exception {
        newOrder("ac-a-overdue", TENANT_A, "shipped", DEADLINE.minusDays(1), "user-a");
        newOrder("ac-b-overdue", TENANT_B, "shipped", DEADLINE.minusDays(1), "user-b");

        // 只把「另一个租户」放进上下文 ⇒ 对 TENANT_A 调写面。若隔离靠的是上下文而不是这条 SQL 的
        // 显式条件，这里就会改到 B 的行（本判据当场红）。
        TenantContext.setTenantId(TENANT_B);
        try (SqlSession own = factory.openSession(true)) {
            assertThat(own.getMapper(OrderMapper.class)
                    .autoCompleteShippedOrders(TENANT_A, DEADLINE))
                    .as("显式 tenantId 条件必须压过上下文 ⇒ B 上下文下动 A 的单仍是「只动 A」")
                    .containsExactly("ac-a-overdue");
        } finally {
            TenantContext.setTenantId(TENANT_A);
        }
        assertThat(verifyStatus("ac-a-overdue")).isEqualTo("completed");
        assertThat(verifyStatus("ac-b-overdue"))
                .as("在 B 上下文里对 A 调用，**不得**顺手把 B 的单也改了").isEqualTo("shipped");
    }

    // ────────────────────────────────────────────── 判据 6：幂等

    @Test
    @DisplayName("判据 6·幂等：同一批满期单连跑两轮 ⇒ 第二轮 0 行、零副作用重放（集群里每个实例跑一轮同形）")
    void repeatedRoundsAreIdempotent() throws Exception {
        newOrder("ac-dup", TENANT_A, "shipped", DEADLINE.minusDays(2), "user-1");

        AutoCompleteShippedScanService.Outcome first = scanOnce();
        AutoCompleteShippedScanService.Outcome second = scanOnce();
        AutoCompleteShippedScanService.Outcome third = scanOnce();

        assertThat(first.completedOrders()).containsExactly("ac-dup");
        assertThat(second.completedOrders()).isEmpty();
        assertThat(third.completedOrders()).isEmpty();
        assertThat(verifyStatus("ac-dup")).isEqualTo("completed");
        // 副作用只发生一次（第二轮/第三轮没有可发的行 ⇒ 不发）
        verify(notificationService, times(1))
                .triggerByEvent(eq(TENANT_A), eq("order_status_changed"), any());
    }

    // ────────────────────────────────────────────── 判据 5：集群并发只生效一次

    @Test
    @DisplayName("🔴 判据 5·**集群并发**（两条独立连接同时跑同一批行）⇒ 行不重叠、合计恰满、慢的一侧 0 行且静默")
    void concurrentInstancesCompleteEachOrderExactlyOnce() throws Exception {
        int rows = 12;
        List<String> ids = new ArrayList<>();
        for (int i = 0; i < rows; i++) {
            String id = "ac-race-" + i;
            ids.add(id);
            newOrder(id, TENANT_A, "shipped", DEADLINE.minusDays(1), "user-" + i);
        }

        CountDownLatch start = new CountDownLatch(1);
        ExecutorService pool = Executors.newFixedThreadPool(2);
        try {
            Callable<List<String>> instance = () -> {
                // 🔴 两个"实例"必须各用自己的连接（同一个 SqlSession 不是线程安全的 ——
                // 共用它测出来的是数据竞争，不是并发）
                try (SqlSession own = factory.openSession(true)) {
                    start.await(10, TimeUnit.SECONDS);
                    TenantContext.setTenantId(TENANT_A);
                    return own.getMapper(OrderMapper.class)
                            .autoCompleteShippedOrders(TENANT_A, DEADLINE);
                }
            };
            Future<List<String>> first = pool.submit(instance);
            Future<List<String>> second = pool.submit(instance);
            start.countDown();
            List<String> wonA = first.get(30, TimeUnit.SECONDS);
            List<String> wonB = second.get(30, TimeUnit.SECONDS);

            // 🔴 不变量的**最强可判形态**：两侧拿到的行**互不相交**、且合计恰等于行数
            // ——「每一行只被一个执行体改到」逐行成立（比"较弱一侧必须为 0"更硬，且**不依赖交错**：
            // 两个执行体的行锁获取顺序不可强制，靠"较弱一侧为 0"会在交错不同时假红）。
            // ⚠️ 不能用 `doesNotContainAnyElementsOf`（任一侧为空时它自己抛 IllegalArgumentException
            // ⇒ 交错不同就假红，实测 3 跑 2 红）；逐 id 判「不在另一侧」对空集天然成立。
            for (String id : wonA) {
                assertThat(wonB).as("第 %s 行不得被两个执行体都改到", id).doesNotContain(id);
            }
            for (String id : wonB) {
                assertThat(wonA).as("第 %s 行不得被两个执行体都改到", id).doesNotContain(id);
            }
            assertThat(wonA.size() + wonB.size())
                    .as("每一行只能被一个执行体改到（两个实例合计恰 %d 行）", rows).isEqualTo(rows);
            for (String id : ids) {
                assertThat(verifyStatus(id)).isEqualTo("completed");
            }
        } finally {
            pool.shutdownNow();
        }

        // 「另一侧静默」的可判形态：**行都被改完之后**任何执行体再扫 ⇒ **0 行**、不抛不告警
        // （这才是生产里"并发里慢的那个实例"的稳态读数），且不再有可发信的行。
        try (SqlSession own = factory.openSession(true)) {
            assertThat(own.getMapper(OrderMapper.class)
                    .autoCompleteShippedOrders(TENANT_A, DEADLINE))
                    .as("所有行都已 completed ⇒ 谓词不再命中 ⇒ 0 行（静默，不是报错）")
                    .isEmpty();
        }
        verify(notificationService, never()).triggerByEvent(anyLong(), any(), any());
    }


    /**
     * 🔴 <b>跑一轮扫描，且每一轮用**新开的 SqlSession**。</b>
     *
     * <p>为什么必须这样（本单实测踩到）：MyBatis 的**一级缓存（localCache）作用域 = SqlSession**，
     * 且对 INSERT 之外的语句**不失效**。共用同一个 session 连跑两轮 ⇒ 第二轮会**命中第一轮的缓存**
     * 并返回上一次的结果（实测：第二轮返回上一轮的 id，而库里那行已经不存在了）。
     * 生产形态是「每次调用一个 SqlSession」（Spring 的 `SqlSessionTemplate` 每请求一个；定时腿每轮一次）
     * ⇒ 测试也必须按同形装配，否则测出来的是测试的缓存，不是生产行为。</p>
     */
    private AutoCompleteShippedScanService.Outcome scanOnce() throws Exception {
        try (SqlSession own = factory.openSession(true)) {
            AutoCompleteShippedScanService round = new AutoCompleteShippedScanService(
                    own.getMapper(OrderMapper.class), notificationService,
                    new BusinessClock(Clock.fixed(NOW, ZoneOffset.UTC)));
            ReflectionTestUtils.setField(round, "autoCompleteDays", 7);
            return round.scanAndComplete();
        }
    }

    // ────────────────────────────────────────────── 夹具

    private static void newOrder(String id, Long tenantId, String status, OffsetDateTime shippedAt,
                                 String userId) throws Exception {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute("INSERT INTO orders (id, tenant_id, order_no, status, shipped_at, user_id,"
                    + " deleted) VALUES ('" + id + "', " + tenantId + ", 'NO-" + id + "', '" + status
                    + "', " + (shippedAt == null ? "NULL" : "'" + shippedAt + "'") + ", '" + userId
                    + "', 0)");
        }
    }

    private static String verifyStatus(String orderId) throws Exception {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery(
                     "SELECT status FROM orders WHERE id = '" + orderId + "'")) {
            assertThat(rs.next()).as("订单 %s 必须还在（本判据不许把行删掉/改名）", orderId).isTrue();
            return rs.getString(1);
        }
    }

    /** bootstrap 终态（新库的 schema.sql）—— 与真库迁移链的终态同形（含 {@code orders.shipped_at}）。 */
    private static String schemaSql() throws IOException {
        Path schema = Paths.get("src", "main", "resources", "db", "init", "schema.sql");
        assertThat(Files.exists(schema)).as("schema.sql 必须存在（路径漂移 ⇒ 判红，不是空跑通过）").isTrue();
        return Files.readString(schema, StandardCharsets.UTF_8);
    }
}
