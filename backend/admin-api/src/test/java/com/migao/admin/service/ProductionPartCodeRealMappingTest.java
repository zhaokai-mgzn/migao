// case_ids: PG-056
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.MybatisSqlSessionFactoryBuilder;
import com.baomidou.mybatisplus.extension.plugins.MybatisPlusInterceptor;
import com.baomidou.mybatisplus.extension.plugins.handler.TenantLineHandler;
import com.baomidou.mybatisplus.extension.plugins.inner.TenantLineInnerInterceptor;
import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import com.migao.admin.mapper.ProcessingOrderSetMapper;
import com.migao.admin.mapper.ProcessingPositionOperationMapper;
import com.migao.admin.mapper.ProcessingSetPartTokenMapper;
import com.migao.admin.mapper.ProductionWorkLogMapper;
import org.apache.ibatis.mapping.Environment;
import org.apache.ibatis.mapping.MappedStatement;
import org.apache.ibatis.mapping.ResultMap;
import org.apache.ibatis.mapping.ResultMapping;
import org.apache.ibatis.session.SqlSession;
import org.apache.ibatis.session.SqlSessionFactory;
import net.sf.jsqlparser.expression.Expression;
import net.sf.jsqlparser.expression.LongValue;
import org.apache.ibatis.transaction.jdbc.JdbcTransactionFactory;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.Assumptions;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.test.util.ReflectionTestUtils;

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
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Stream;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 🔴 **#4865 防再犯守卫（集成级：真 PG + 真 MyBatis 映射 + 真列内容 + 真实例化路径）**。
 *
 * <h2>本类要拦住的缺陷（#4865 实测）</h2>
 * {@code ProductionService.ensureSetsFor} 把**非空**的 {@code processing_orders.items_snapshot} 判成空
 * ⇒ 套号分配整段跳过 ⇒ {@code ensurePartTokens} 拿不到套 ⇒ **正常实例化永远产不出部位码/短码**。
 * 根因**不在** {@code ensureSetsFor} 的判空写法，而在**映射**：{@code ProcessingOrderMapper} 的
 * 自定义 {@code @Select} 未绑定 MyBatis-Plus 的 autoResultMap ⇒ `items_snapshot` 不过
 * {@code JacksonTypeHandler} ⇒ 运行时类型是 {@code PGobject}（不是 {@code List}）。
 *
 * <h2>为什么必须是「真库 + 真映射」（而不是 mock 出来的 List）</h2>
 * 既有 {@code ProductionSetAllocationWiringTest} 用 {@code when(…selectActiveByOrderId(…)).thenReturn(po)}
 * 喂一个**在 Java 里 new 出来的** {@code ProcessingOrder}（其 {@code itemsSnapshot} 是真 {@code List}）
 * ⇒ **整条链路绕过了 MyBatis**，缺陷在这一层**结构上不可见**。本类反过来：真 PG 建表 + 真行（JSONB 列）
 * + 真 {@code MybatisConfiguration} 注册真 mapper ⇒ 断言**运行时类型**与**落库结果**。
 *
 * <h2>判据不许恒真（红证形态）</h2>
 * 把 {@code ProcessingOrderMapper.selectActiveByOrderId} 的 {@code @ResultMap} 去掉（= 回到未绑
 * resultMap 的形态）⇒ {@link #snapshotColumnsHydrateThroughJacksonTypeHandler()} 与
 * {@link #instantiateWritesPartTokensWithShortCode()} **必红**（见 PR body 的红证读数）。
 *
 * <h2>环境</h2>
 * 本类**自建一次性 PG 集群**（{@code initdb} + {@code pg_ctl}，随机端口、跑完即停），
 * 与 {@code tests/unit_ci_workflows/test_v9x_*.py} 的真库判据同款；本机没有 PG 二进制 ⇒
 * **显式 skip**（"没跑"必须长得像"没跑"，不是通过）。schema 取自 {@code docs/sql/schema.sql}
 * （= docker 栈的 bootstrap 终态，含 V92/V99 的列）—— **不手抄列清单**（手抄会漂移）。
 */
@DisplayName("#4865 真库×真映射守卫：实例化 ⇒ processing_set_part_tokens 有行且 short_code 非空")
class ProductionPartCodeRealMappingTest {

    private static final Long TENANT_ID = 4865L;
    private static final String ORDER_ID = "acc-fix4865-order";
    private static final String PO_ID = "acc-fix4865-po";
    private static final String PO_NO = "JG-20260921-4865";
    private static final String CRAFT_LINE = "acc-fix4865-cl-A";

    private static PgCluster cluster;
    private static DataSource dataSource;
    private static SqlSessionFactory factory;
    private static MybatisConfiguration configuration;
    private static SqlSession session;
    private static long tenantId;

    // ────────────────────────────────────────────── 夹具：一次性真库

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
                            + ", 'acc-fix4865', 'acc-fix4865') RETURNING id")) {
                assertThat(rs.next()).as("租户夹具必须落库").isTrue();
                tenantId = rs.getLong(1);
            }
            st.execute("INSERT INTO orders (id, tenant_id, order_no, status) VALUES ('" + ORDER_ID + "', "
                    + tenantId + ", 'ORD-acc-fix4865', 'confirmed')");
            for (String itemId : List.of("acc-fix4865-i1", "acc-fix4865-i2", "acc-fix4865-i3")) {
                st.execute("INSERT INTO order_items (id, tenant_id, order_id, quantity, processing_info) VALUES ('"
                        + itemId + "', " + tenantId + ", '" + ORDER_ID + "', 1, CAST('{\"craftLineId\":\""
                        + CRAFT_LINE + "\"}' AS jsonb))");
            }
            st.execute("INSERT INTO processing_orders (id, tenant_id, order_id, processing_order_no, status,"
                    + " items_snapshot) VALUES ('" + PO_ID + "', " + tenantId + ", '" + ORDER_ID + "', '"
                    + PO_NO + "', 'generated', CAST('" + snapshotJson() + "' AS jsonb))");
        }
        configuration = new MybatisConfiguration();
        configuration.setMapUnderscoreToCamelCase(true);
        configuration.setEnvironment(new Environment("acc-fix4865", new JdbcTransactionFactory(), dataSource));
        // 🔴 多租户拦截器**必须在场**：生产 SQL 会经它（JSqlParser 往返 + 追加 tenant_id）重写，
        // 而 #4865 的第二个缺陷（`FOR UPDATE` 被重排到 `ORDER BY` 之前 ⇒ 语法错误）**只在这条路径上显形**。
        // 少了它，本守卫会漏掉整个「SQL 重写」面（= 只测了 mapper 原文，没测真正执行的 SQL）。
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

    // ────────────────────────────────────────────── 判据 1：真映射（JSONB 列必须过 typeHandler）

    @Test
    @DisplayName("自定义 @Select 的 items_snapshot 必须经 JacksonTypeHandler 落成 List（不是 PGobject）")
    void snapshotColumnsHydrateThroughJacksonTypeHandler() {
        {
            ProcessingOrderMapper mapper = mapper(ProcessingOrderMapper.class);

            ProcessingOrder active = mapper.selectActiveByOrderId(ORDER_ID, tenantId);
            assertThat(active).as("真库必须能取到活跃加工单").isNotNull();
            Object raw = active.getItemsSnapshot();
            System.out.println("[#4865 判别性实验] selectActiveByOrderId → itemsSnapshot 运行时类型 = "
                    + describe(raw) + "；resultMap 类型处理器 = "
                    + typeHandlerNames("com.migao.admin.mapper.ProcessingOrderMapper.selectActiveByOrderId"));
            assertThat(raw)
                    .as("快照必须反序列化为 List —— 否则 ensureSetsFor 判空、套号/部位码/短码全部不产出")
                    .isInstanceOf(List.class);
            assertThat((List<?>) raw).as("快照内容不得为空（真库那一列非空）").hasSize(3);

            List<ProcessingOrder> byKeyword = mapper.selectByKeyword(PO_NO, tenantId);
            assertThat(byKeyword).as("按加工单号必须能解析到该单").isNotEmpty();
            assertThat(byKeyword.get(0).getItemsSnapshot())
                    .as("同一个 mapper 的**另一处**自定义 @Select（selectByKeyword）同样必须过 typeHandler")
                    .isInstanceOf(List.class);

            List<OrderItem> items = mapper(OrderItemMapper.class).selectByOrderId(ORDER_ID, tenantId);
            assertThat(items).as("订单行必须能取到").hasSize(3);
            assertThat(items.get(0).getProcessingInfo())
                    .as("order_items.processing_info 也必须过 typeHandler（否则 craftLineId 取不到 ⇒ 归不到套）")
                    .isInstanceOf(Map.class);
        }
    }

    // ────────────────────────────────────────────── 判据 2：真实例化路径 ⇒ 部位码 + 短码

    @Test
    @DisplayName("实例化后 processing_set_part_tokens 有行，且 short_code 非空且为 8 位 Crockford Base32")
    void instantiateWritesPartTokensWithShortCode() throws Exception {
        ProductionService service = realProductionService();

        Map<String, Object> result = service.instantiate(ORDER_ID, body(), tenantId);
        assertThat(result).as("实例化必须成功返回").isNotNull();
        System.out.println("[#4865 判别性实验] instantiate 返回 = " + result);

        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            assertThat(count(st, "SELECT count(*) FROM processing_order_sets WHERE processing_order_id = '"
                    + PO_ID + "' AND deleted = 0"))
                    .as("套号必须落库（套号是码的前置）").isEqualTo(1);
            long tokens = count(st, "SELECT count(*) FROM processing_set_part_tokens WHERE processing_order_id = '"
                    + PO_ID + "' AND deleted = 0");
            long withCode = count(st, "SELECT count(*) FROM processing_set_part_tokens WHERE processing_order_id = '"
                    + PO_ID + "' AND deleted = 0 AND short_code IS NOT NULL");
            System.out.println("[#4865 判别性实验] processing_set_part_tokens 行数 = " + tokens
                    + "，其中 short_code 非空 = " + withCode);
            assertThat(tokens).as("一部位一码 ⇒ 3 个部位 3 行").isEqualTo(3);
            assertThat(withCode)
                    .as("🔴 本守卫的核心判据：实例化必须产出**可印刷的短码**（否则需求⑤的短链是纸面能力）")
                    .isEqualTo(tokens);

            try (ResultSet rs = st.executeQuery("SELECT short_code FROM processing_set_part_tokens"
                    + " WHERE processing_order_id = '" + PO_ID + "' AND deleted = 0")) {
                while (rs.next()) {
                    String code = rs.getString(1);
                    assertThat(code).as("短码长度 = 8（设计 §1.4）")
                            .hasSize(WorkerShortLinkService.CODE_LENGTH);
                    for (char c : code.toCharArray()) {
                        assertThat(WorkerShortLinkService.ALPHABET.indexOf(c))
                                .as("短码字符集 = Crockford Base32 去 I/L/O/U；实测非法字符 " + c + "（码=" + code + "）")
                                .isGreaterThanOrEqualTo(0);
                    }
                }
            }
        }
    }

    // ────────────────────────────────────────────── 判据 3：存量单补码（幂等早返回路径也要补）

    @Test
    @DisplayName("存量单补码：已实例化的单再次实例化 ⇒ 补出短码；已打印的码一字不变")
    void reInstantiateBackfillsCodesForLegacyOrderWithoutInvalidatingPrintedCodes() throws Exception {
        ProductionService service = realProductionService();
        service.instantiate(ORDER_ID, body(), tenantId);

        String printedToken;
        String printedCode;
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            // 造「存量单」形态：已实例化、工序配置未变，但**没有码**（= #4865 实测的症状）。
            // 保留一行当作「已打印的码」⇒ 复查它必须一字不变（只补缺失行，不换已发的码）。
            try (ResultSet rs = st.executeQuery("SELECT order_item_id, token, short_code FROM"
                    + " processing_set_part_tokens WHERE processing_order_id = '" + PO_ID
                    + "' AND deleted = 0 ORDER BY order_item_id")) {
                assertThat(rs.next()).as("首次实例化必须已产出码行").isTrue();
                String keep = rs.getString(1);
                printedToken = rs.getString(2);
                printedCode = rs.getString(3);
                st.execute("DELETE FROM processing_set_part_tokens WHERE processing_order_id = '" + PO_ID
                        + "' AND order_item_id <> '" + keep + "'");
                System.out.println("[#4865 存量单补码] 保留「已打印」行 order_item=" + keep
                        + "，token=" + printedToken + "，short_code=" + printedCode);
            }
        }

        // 工序配置未变 ⇒ 走 instantiate 的**幂等早返回**路径（#4865 的第二处缺陷所在）
        service.instantiate(ORDER_ID, body(), tenantId);

        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            long tokens = count(st, "SELECT count(*) FROM processing_set_part_tokens WHERE processing_order_id = '"
                    + PO_ID + "' AND deleted = 0");
            long withCode = count(st, "SELECT count(*) FROM processing_set_part_tokens WHERE processing_order_id = '"
                    + PO_ID + "' AND deleted = 0 AND short_code IS NOT NULL");
            System.out.println("[#4865 存量单补码] 幂等早返回后再实例化：行数 = " + tokens
                    + "，short_code 非空 = " + withCode);
            assertThat(tokens).as("幂等早返回路径也必须补出缺失的码行").isEqualTo(3);
            assertThat(withCode).as("补出的码必须带 short_code").isEqualTo(3);
            try (ResultSet rs = st.executeQuery("SELECT token, short_code FROM processing_set_part_tokens"
                    + " WHERE processing_order_id = '" + PO_ID + "' AND deleted = 0 AND token = '"
                    + printedToken + "'")) {
                assertThat(rs.next()).as("已打印的码行必须仍在").isTrue();
                assertThat(rs.getString(1)).as("已打印的 token 不得改变").isEqualTo(printedToken);
                assertThat(rs.getString(2)).as("已打印的 short_code 不得改变（已印的纸不作废）")
                        .isEqualTo(printedCode);
            }
        }
    }

    // ────────────────────────────────────────────── 夹具与工具

    private static ProductionService realProductionService() {
        ProcessingOrderMapper poMapper = mapper(ProcessingOrderMapper.class);
        ProcessingOrderSetMapper setMapper = mapper(ProcessingOrderSetMapper.class);
        ProcessingSetPartTokenMapper tokenMapper = mapper(ProcessingSetPartTokenMapper.class);
        ProductionService service = new ProductionService(poMapper,
                mapper(ProcessingPositionOperationMapper.class),
                mapper(ProductionWorkLogMapper.class),
                mapper(OrderMapper.class),
                mapper(OrderItemMapper.class),
                null); // instantiate 路径不触碰幂等键服务（#4865 的判据面不含它）
        ReflectionTestUtils.setField(service, "orderSetAllocator", new ProcessingOrderSetAllocator(setMapper));
        ReflectionTestUtils.setField(service, "orderSetMapper", setMapper);
        ReflectionTestUtils.setField(service, "setPartTokenMapper", tokenMapper);
        return service;
    }

    private static <T> T mapper(Class<T> type) {
        return session.getMapper(type);
    }

    private static long count(Statement st, String sql) throws Exception {
        try (ResultSet rs = st.executeQuery(sql)) {
            rs.next();
            return rs.getLong(1);
        }
    }

    private static String describe(Object value) {
        return value == null ? "null" : value.getClass().getName();
    }

    /** 该 statement 的 resultMap 里**非空**的类型处理器（证据行：未绑 resultMap ⇒ 空集）。 */
    private static String typeHandlerNames(String statementId) {
        MappedStatement ms = configuration.getMappedStatement(statementId);
        List<String> names = new ArrayList<>();
        for (ResultMap rm : ms.getResultMaps()) {
            for (ResultMapping mapping : rm.getResultMappings()) {
                if (mapping.getTypeHandler() != null) {
                    names.add(mapping.getProperty() + "=" + mapping.getTypeHandler().getClass().getSimpleName());
                }
            }
        }
        return names.isEmpty() ? "（无 —— 未绑 resultMap）" : names.toString();
    }

    private static String snapshotJson() {
        StringBuilder sb = new StringBuilder("[");
        List<String> ids = List.of("acc-fix4865-i1", "acc-fix4865-i2", "acc-fix4865-i3");
        for (int i = 0; i < ids.size(); i++) {
            sb.append(i > 0 ? "," : "")
                    .append("{\"itemId\":\"").append(ids.get(i))
                    .append("\",\"craftLineId\":\"").append(CRAFT_LINE)
                    .append("\",\"processingItems\":[{\"name\":\"韩褶\"}]}");
        }
        return sb.append("]").toString().replace("'", "''");
    }

    /** 3 个部位同属一樘窗（同一个 craftLineId）⇒ 1 个套、3 个部位码。 */
    private static Map<String, Object> body() {
        List<Map<String, Object>> positions = new ArrayList<>();
        positions.add(position("布帘", "acc-fix4865-i1", "布帘"));
        positions.add(position("纱帘", "acc-fix4865-i2", "纱帘"));
        positions.add(position("帘头", "acc-fix4865-i3", "帘头"));
        return Map.of("positions", positions);
    }

    private static Map<String, Object> position(String name, String itemId, String kind) {
        Map<String, Object> position = new LinkedHashMap<>();
        position.put("position_name", name);
        position.put("order_item_id", itemId);
        position.put("position_kind", kind);
        position.put("operations", List.of(Map.of(
                "seq", 1, "operation", "精裁-布", "group", "裁剪", "unit", "米",
                "qty", BigDecimal.ONE, "unit_price", new BigDecimal("0.40"),
                "factor", BigDecimal.ONE, "is_must_finish", false, "is_start_marker", true)));
        return position;
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
            Path base = Files.createTempDirectory("migao4865pg");
            Path dataDir = base.resolve("data");
            Path sockDir = Files.createTempDirectory("pg4865"); // socket 路径有 ~104 字节上限
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
                walk.sorted(java.util.Comparator.reverseOrder()).forEach(p -> {
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
