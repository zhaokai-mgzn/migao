// case_ids: PG-018
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.MybatisSqlSessionFactoryBuilder;
import com.baomidou.mybatisplus.extension.plugins.MybatisPlusInterceptor;
import com.baomidou.mybatisplus.extension.plugins.handler.TenantLineHandler;
import com.baomidou.mybatisplus.extension.plugins.inner.TenantLineInnerInterceptor;
import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.entity.ProcessingPositionOperation;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import com.migao.admin.mapper.ProcessingOrderSetMapper;
import com.migao.admin.mapper.ProcessingPositionOperationMapper;
import com.migao.admin.mapper.ProcessingSetPartTokenMapper;
import com.migao.admin.mapper.ProductionWorkLogMapper;
import com.migao.admin.worker.WorkerIdentity;
import net.sf.jsqlparser.expression.Expression;
import net.sf.jsqlparser.expression.LongValue;
import org.apache.ibatis.mapping.Environment;
import org.apache.ibatis.session.SqlSession;
import org.apache.ibatis.session.SqlSessionFactory;
import org.apache.ibatis.transaction.jdbc.JdbcTransactionFactory;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.Assumptions;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.datasource.DriverManagerDataSource;

import javax.sql.DataSource;
import java.io.IOException;
import java.math.BigDecimal;
import java.net.ServerSocket;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.sql.Connection;
import java.sql.ResultSet;
import java.sql.Statement;
import java.sql.Timestamp;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Stream;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 🔴 <b>领活三列的**真库**判据（issue #4967；用户逐字裁定①「工人都是先扫码报工后再真实进行生产」）</b>。
 *
 * <h2>本类要拦住的缺陷</h2>
 * {@code processing_position_operations} 的 {@code started_at} / {@code worker_id} /
 * {@code worker_name} 三列在 V92 就建好了，但当时的列注释逐字写的是「<b>C 模式预留</b>
 * （A 模式默认路径<b>不读不写</b>，设计 D15）」⇒ 默认路径（工人扫码）走完之后，
 * <b>{@code started_at} 恒为 NULL</b>：系统根本不知道「谁在什么时候领走了这道活」。
 *
 * <h2>为什么必须是「真库 + 真 SQL」（而不是 mock 出来的调用面）</h2>
 * mock 只能证明「调了哪个方法」；本单的判据是「**那一列真的落进了 PG、且值正确**」——
 * 列名拼错 / SET 子句漏项 / {@code COALESCE} 幂等写错，在 mock 面**结构上不可见**。
 * 与 {@code ProductionPartCodeRealMappingTest}（#4865 真库×真映射守卫）同款：一次性真 PG 集群
 * （{@code initdb} + {@code pg_ctl}，随机端口、跑完即停），schema 取自 {@code docs/sql/schema.sql}
 * （bootstrap 终态，含 V92 三列）—— <b>不手抄列清单</b>（手抄会漂移）。
 *
 * <h2>判据不许恒真（红证形态）</h2>
 * 把 {@code ProcessingPositionOperationMapper#recordReporter} 的 SET 子句去掉
 * {@code started_at = COALESCE(started_at, #{startedAt})}（= 回到改前形态），或把
 * {@code ProductionService#applyScanComplete} 里那次调用删掉 ⇒
 * {@link #claimWritesStartedAtAndWorkerIntoTheRealTable()} <b>必红</b>
 * （{@code started_at} 为 NULL）。
 *
 * <h2>环境</h2>
 * 本机没有 PG 二进制（{@code initdb}/{@code pg_ctl}）⇒ <b>显式 skip</b>
 * （「没跑」必须长得像「没跑」，不是通过）。
 */
@DisplayName("#4967 真库守卫：扫码 = 开工/领活 ⇒ started_at / worker_id / worker_name 落进 processing_position_operations")
class ProductionScanClaimRealDbTest {

    private static final Long TENANT_ID = 4967L;
    private static final String ORDER_ID = "acc-4967-order";
    private static final String PO_ID = "acc-4967-po";
    private static final String PO_NO = "JG-20260921-4967";
    private static final String OP_ID = "acc-4967-op-1";
    private static final String WORKER_ID = "acc-4967-w1";
    private static final String WORKER_NAME = "张三";
    /** 刻意用非密钥形态字面量（32 位 hex 会被 gitleaks 误判为密钥）。 */
    private static final String SESSION_ID = "sess-4967-a";

    private static PgCluster cluster;
    private static DataSource dataSource;
    private static SqlSessionFactory factory;
    private static SqlSession session;
    private static long tenantId;

    @BeforeAll
    static void startRealPostgresAndFixtures() throws Exception {
        cluster = PgCluster.start();
        if (cluster == null) {
            Assumptions.abort("本机没有 PG 二进制（initdb/pg_ctl）⇒ 真库判据**未跑**（不是通过）");
        }
        dataSource = cluster.dataSource();
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute(schemaSql());
            try (ResultSet rs = st.executeQuery(
                    "INSERT INTO tenants (id, name, code) OVERRIDING SYSTEM VALUE VALUES (" + TENANT_ID
                            + ", 'acc-4967', 'acc-4967') RETURNING id")) {
                assertThat(rs.next()).as("租户夹具必须落库").isTrue();
                tenantId = rs.getLong(1);
            }
            st.execute("INSERT INTO orders (id, tenant_id, order_no, status) VALUES ('" + ORDER_ID + "', "
                    + tenantId + ", 'ORD-acc-4967', 'confirmed')");
            st.execute("INSERT INTO processing_orders (id, tenant_id, order_id, processing_order_no, status)"
                    + " VALUES ('" + PO_ID + "', " + tenantId + ", '" + ORDER_ID + "', '" + PO_NO
                    + "', 'issued')");
            // 一道待做工序：应做 11 米、已报 0 ⇒ 扫码报满 ⇒ status='done' + done_at 落笔
            st.execute("INSERT INTO processing_position_operations (id, tenant_id, processing_order_id,"
                    + " order_item_id, position_name, position_kind, seq, operation_name, group_name,"
                    + " unit, qty, unit_price, is_must_finish, is_start_marker, status, done_qty, deleted)"
                    + " VALUES ('" + OP_ID + "', " + tenantId + ", '" + PO_ID + "', 'acc-4967-i1',"
                    + " '布艺遮光帘A', '布帘', 1, '精裁-布', '裁剪', '米', 11, 3.50, true, true,"
                    + " 'pending', 0, 0)");
        }
        MybatisConfiguration configuration = new MybatisConfiguration();
        configuration.setMapUnderscoreToCamelCase(true);
        configuration.setEnvironment(new Environment("acc-4967", new JdbcTransactionFactory(), dataSource));
        // 多租户拦截器**必须在场**：生产 SQL 会经它重写（追加 tenant_id）⇒ 少了它就只测了 mapper 原文
        MybatisPlusInterceptor tenantLine = new MybatisPlusInterceptor();
        tenantLine.addInnerInterceptor(new TenantLineInnerInterceptor(new TenantLineHandler() {
            @Override
            public Expression getTenantId() {
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
        for (Class<?> mapper : List.of(ProcessingOrderMapper.class, OrderMapper.class, OrderItemMapper.class,
                ProcessingOrderSetMapper.class, ProcessingSetPartTokenMapper.class,
                ProcessingPositionOperationMapper.class, ProductionWorkLogMapper.class)) {
            configuration.addMapper(mapper);
        }
        factory = new MybatisSqlSessionFactoryBuilder().build(configuration);
        session = factory.openSession(true);
        TenantContext.setTenantId(tenantId);
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

    // ────────────────────────────────────────────── 判据：默认路径（applyScanComplete）写三列

    @Test
    @DisplayName("🔴 扫码=领活：applyScanComplete 之后 started_at / worker_id / worker_name 三列**真落库**")
    void claimWritesStartedAtAndWorkerIntoTheRealTable() throws Exception {
        Map<String, Object> claimBefore = row();
        System.out.println("[#4967 判别性实验] 领活前该行 = " + claimBefore);
        assertThat(claimBefore.get("started_at"))
                .as("夹具必须是「还没人领活」的形态（本判据的对照面）").isNull();

        OffsetDateTime claimedAt = OffsetDateTime.parse("2026-09-21T08:30:00+08:00");
        realService().applyScanComplete(order(), processingOrder(), operation(), new BigDecimal("11"),
                new BigDecimal("11"), "normal",
                new WorkerIdentity(WORKER_ID, WORKER_NAME, WorkerIdentity.SOURCE_SERVER_SESSION, SESSION_ID),
                tenantId);

        Map<String, Object> claimAfter = row();
        System.out.println("[#4967 判别性实验] 领活后该行 = " + claimAfter);
        assertThat(claimAfter.get("started_at"))
                .as("🔴 本守卫的核心判据：扫码 = 开工/领活 ⇒ started_at 不得再是 NULL（改前恒 NULL ⇒ 必红）")
                .isNotNull();
        assertThat(claimAfter.get("worker_id")).as("领活人 id（服务端从 session 解，非 body）")
                .isEqualTo(WORKER_ID);
        assertThat(claimAfter.get("worker_name")).as("领活人姓名（工资凭证的根）")
                .isEqualTo(WORKER_NAME);
        // 记账时点**不变**（issue #4967 的要害）：这一次仍然推进进度 + 落完工时刻
        assertThat(claimAfter.get("status")).isEqualTo("done");
        assertThat(claimAfter.get("done_qty")).isEqualTo(new BigDecimal("11.00"));
        assertThat(claimAfter.get("done_at")).as("记账时点不变 ⇒ done_at 仍在这一笔落笔").isNotNull();
    }

    @Test
    @DisplayName("🔴 重复领活/重扫 ⇒ started_at 一字不改（COALESCE 幂等），worker 更新为最新领活人")
    void repeatedClaimKeepsTheFirstStartedAt() throws Exception {
        String firstStartedAt;
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            try (ResultSet rs = st.executeQuery(
                    "SELECT started_at FROM processing_position_operations WHERE id = '" + OP_ID + "'")) {
                assertThat(rs.next()).as("夹具行必须存在").isTrue();
                Timestamp ts = rs.getTimestamp(1);
                assertThat(ts).as("前一条判据已落笔（同 JVM 内顺序执行）").isNotNull();
                firstStartedAt = ts.toInstant().toString();
            }
        }

        ProcessingPositionOperationMapper mapper = mapper(ProcessingPositionOperationMapper.class);
        // 第二次领活（换人再扫 / 续报）：时刻刻意更晚、工人刻意换人
        mapper.recordReporter(OP_ID, tenantId, "acc-4967-w2", "李四",
                OffsetDateTime.parse("2026-09-21T20:00:00+08:00"), OffsetDateTime.now());

        Map<String, Object> after = row();
        System.out.println("[#4967 判别性实验] 第二次领活后 = " + after);
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery(
                     "SELECT started_at FROM processing_position_operations WHERE id = '" + OP_ID + "'")) {
            assertThat(rs.next()).isTrue();
            assertThat(rs.getTimestamp(1).toInstant().toString())
                    .as("🔴 「开工时刻」只有一个：COALESCE ⇒ 第二次领活**不得**改写已记下的时刻")
                    .isEqualTo(firstStartedAt);
        }
        assertThat(after.get("worker_name"))
                .as("领活人跟最新一次（谁现在在做）—— 与 started_at 的「第一次」口径有意不同，如实登记")
                .isEqualTo("李四");
    }

    // ────────────────────────────────────────────── 夹具与工具

    private static ProductionService realService() {
        return new ProductionService(mapper(ProcessingOrderMapper.class),
                mapper(ProcessingPositionOperationMapper.class),
                mapper(ProductionWorkLogMapper.class),
                mapper(OrderMapper.class),
                mapper(OrderItemMapper.class),
                null); // applyScanComplete 路径不触碰幂等键服务（占位在调用方外层）
    }

    private static Order order() {
        return Order.builder().id(ORDER_ID).tenantId(tenantId).orderNo("ORD-acc-4967").deleted(0).build();
    }

    private static ProcessingOrder processingOrder() {
        return ProcessingOrder.builder().id(PO_ID).tenantId(tenantId).orderId(ORDER_ID)
                .processingOrderNo(PO_NO).status("issued").deleted(0).build();
    }

    private static ProcessingPositionOperation operation() {
        return mapper(ProcessingPositionOperationMapper.class).selectById(OP_ID);
    }

    /** 真库快照：该工序行的领活相关列（直读 SQL，不经过实体映射 ⇒ 列名拼错也会被抓到）。 */
    private static Map<String, Object> row() throws Exception {
        Map<String, Object> row = new LinkedHashMap<>();
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery("SELECT started_at, worker_id, worker_name, status, done_qty,"
                     + " done_at FROM processing_position_operations WHERE id = '" + OP_ID + "'")) {
            assertThat(rs.next()).as("工序行必须存在（id=" + OP_ID + "）").isTrue();
            row.put("started_at", rs.getTimestamp("started_at"));
            row.put("worker_id", rs.getString("worker_id"));
            row.put("worker_name", rs.getString("worker_name"));
            row.put("status", rs.getString("status"));
            row.put("done_qty", rs.getBigDecimal("done_qty"));
            row.put("done_at", rs.getTimestamp("done_at"));
        }
        return row;
    }

    private static <T> T mapper(Class<T> type) {
        return session.getMapper(type);
    }

    private static String schemaSql() throws IOException {
        Path root = Paths.get(System.getProperty("user.dir")).toAbsolutePath();
        while (root != null && !Files.exists(root.resolve("docs/sql/schema.sql"))) {
            root = root.getParent();
        }
        assertThat(root).as("必须能定位 docs/sql/schema.sql（真库建表取终态 schema，不手抄列清单）").isNotNull();
        return Files.readString(root.resolve("docs/sql/schema.sql"));
    }

    // ────────────────────────────────────────────── 一次性 PG 集群

    /** 一次性 PG 集群（{@code initdb} + {@code pg_ctl}；随机端口、跑完即停、不留残留）。 */
    private static final class PgCluster {

        private static final List<String> BIN_DIRS = List.of(
                "/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/usr/lib/postgresql/16/bin",
                "/usr/lib/postgresql/15/bin", "/usr/lib/postgresql/14/bin");

        private final Path dataDir;
        private final Path sockDir;
        private final Path logFile;
        private final int port;
        private final String binDir;

        private PgCluster(String binDir, Path dataDir, Path sockDir, Path logFile, int port) {
            this.binDir = binDir;
            this.dataDir = dataDir;
            this.sockDir = sockDir;
            this.logFile = logFile;
            this.port = port;
        }

        static PgCluster start() throws Exception {
            String binDir = findBinDir();
            if (binDir == null) {
                return null;
            }
            Path base = Files.createTempDirectory("migao4967pg");
            Path dataDir = base.resolve("data");
            Path sockDir = Files.createTempDirectory("pg4967"); // socket 路径有 ~104 字节上限
            Path logFile = base.resolve("pg.log");
            int port = freePort();
            run(binDir, List.of("initdb", "-D", dataDir.toString(), "-U", "postgres", "-A", "trust"));
            run(binDir, List.of("pg_ctl", "-D", dataDir.toString(), "-l", logFile.toString(), "-o",
                    "-p " + port + " -c listen_addresses=127.0.0.1 -k " + sockDir, "start"));
            return new PgCluster(binDir, dataDir, sockDir, logFile, port);
        }

        DataSource dataSource() {
            DriverManagerDataSource ds = new DriverManagerDataSource(
                    "jdbc:postgresql://127.0.0.1:" + port + "/postgres?stringtype=unspecified",
                    "postgres", "");
            ds.setDriverClassName("org.postgresql.Driver");
            return ds;
        }

        void stop() {
            try {
                run(binDir, List.of("pg_ctl", "-D", dataDir.toString(), "-m", "immediate", "stop"));
            } catch (Exception ignored) {
                // 停机失败不影响判据；临时目录随后清理
            }
            deleteRecursively(sockDir);
            deleteRecursively(dataDir.getParent());
        }

        private static String findBinDir() {
            List<String> candidates = new ArrayList<>(BIN_DIRS);
            String path = System.getenv("PATH");
            if (path != null) {
                candidates.addAll(0, List.of(path.split(":")));
            }
            for (String dir : candidates) {
                if (dir.isBlank()) {
                    continue;
                }
                Path initdb = Paths.get(dir, "initdb");
                Path pgCtl = Paths.get(dir, "pg_ctl");
                if (Files.isExecutable(initdb) && Files.isExecutable(pgCtl)) {
                    return dir;
                }
            }
            return null;
        }

        private static int freePort() throws IOException {
            try (ServerSocket socket = new ServerSocket(0)) {
                return socket.getLocalPort();
            }
        }

        private static void run(String binDir, List<String> args) throws Exception {
            List<String> command = new ArrayList<>(args);
            command.set(0, Paths.get(binDir, args.get(0)).toString());
            Process process = new ProcessBuilder(command).redirectErrorStream(true).start();
            String output = new String(process.getInputStream().readAllBytes());
            int exit = process.waitFor();
            assertThat(exit).as("`" + String.join(" ", args) + "` 必须成功（PG 临时集群）：\n" + output)
                    .isZero();
        }

        private static void deleteRecursively(Path dir) {
            if (dir == null || !Files.exists(dir)) {
                return;
            }
            try (Stream<Path> walk = Files.walk(dir)) {
                walk.sorted(Comparator.reverseOrder()).forEach(p -> {
                    try {
                        Files.deleteIfExists(p);
                    } catch (IOException ignored) {
                        // 尽力而为
                    }
                });
            } catch (IOException ignored) {
                // 尽力而为
            }
        }
    }
}
