// case_ids: DA-016, DA-017, PG-062
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.MybatisSqlSessionFactoryBuilder;
import com.baomidou.mybatisplus.extension.plugins.MybatisPlusInterceptor;
import com.baomidou.mybatisplus.extension.plugins.handler.TenantLineHandler;
import com.baomidou.mybatisplus.extension.plugins.inner.TenantLineInnerInterceptor;
import com.migao.admin.entity.AuditLog;
import com.migao.admin.mapper.AuditLogMapper;
import com.migao.admin.mapper.OrderMapper;
import net.sf.jsqlparser.expression.Expression;
import net.sf.jsqlparser.expression.LongValue;
import org.apache.ibatis.mapping.Environment;
import org.apache.ibatis.session.SqlSession;
import org.apache.ibatis.session.SqlSessionFactory;
import org.apache.ibatis.transaction.jdbc.JdbcTransactionFactory;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.datasource.DriverManagerDataSource;

import javax.sql.DataSource;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.sql.Connection;
import java.sql.Statement;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * issue #5388 真库判据：**改价审计读面**（`audit_logs.action_details` JSONB → 快照行）+ 让利订单读面。
 *
 * <h2>为什么必须真库（mock 面结构上看不见）</h2>
 * 本单的判据全部落在三个 mock **测不出来**的地方：
 * <ol>
 *   <li><b>JSONB 读回是不是真值</b>：`AuditLog.actionDetails` 走 MyBatis-Plus
 *       {@code JacksonTypeHandler}（{@code autoResultMap = true}）—— 这层「写进去的 Map
 *       读回来还是不是带数字的 Map」只有真库能测。⚠️ 本单的**前提证伪**正落在这里：
 *       改价幅度要用 `before_price`/`price` 的**数值**，而 `action_details.params` 按 PII 纪律
 *       只记类型占位（`<float>`）⇒ 真值走新增的 `priceChange` 键。占位串读回来是 `"<float>"`
 *       而不是数 ⇒ 必须由本判据钉住「占位 ⇒ null（**未判定**，不是 0）」。</li>
 *   <li><b>筛选与窗口的射程</b>：`tool_name ∈ {product_update, sku_update}`、`resource_type
 *       = 'agent_tool'`、时间窗、租户 —— 四条判据各自都要**有对照读数**（同一次读面里同时打印
 *       「窗口内有几条 agent_tool 行」与「其中几条是改价」），否则「筛对了」只是自说自话。</li>
 *   <li><b>两种「没有改价记录」的分界事实</b>：`audit_tool_logging` = 窗口内是否存在**任意**
 *       agent_tool 行。人工审计行（`resource_type='product'`）**不算**它 —— 这条差别决定了
 *       「该租户从没改过价」（正常的空）与「审计没在跑」（故障的空）能不能分开。</li>
 * </ol>
 *
 * <h2>环境</h2>
 * 一次性真 PG 集群（{@link PgCluster}，与既有真库判据**共用同一个装配**），schema 取
 * {@code backend/admin-api/src/main/resources/db/init/schema.sql}（终态，**不手抄列清单**），
 * 并装上与生产同源的多租户拦截器。缺 PG 二进制 ⇒ {@code PgCluster.startOrAbort()}：
 * CI（{@code MIGAO_REQUIRE_REALDB=1}）⇒ 判红；本机未设该标记 ⇒ 显式 skip（「没跑」长得像「没跑」）。
 */
@DisplayName("#5388 真库：改价审计读面（JSONB 真值 / 脱敏期历史行 / 工具筛选 / 窗口 / 租户）")
class AuditLogPriceChangeRealDbTest {

    private static final Long TENANT_ID = 5388L;
    private static final Long OTHER_TENANT_ID = 53880L;
    /** 只有**人工**审计行（`resource_type='product'`）的租户：`audit_tool_logging` 必须是 false。 */
    private static final Long MANUAL_ONLY_TENANT_ID = 53881L;

    private static PgCluster cluster;
    private static SqlSession session;
    private static DailyBriefingService service;
    private static AuditLogMapper auditLogMapper;
    private static OrderMapper orderMapper;

    /**
     * 多租户拦截器当前注入的租户 —— **可切**（默认 {@link #TENANT_ID}）。
     *
     * <p>🔴 为什么必须可切（两层闸教训）：只在别的租户上读会被拦截器挡住 ⇒ 那条断言**恒真**
     * （「人工审计行不算写工具审计」这条判据**根本测不到**：本机实测——把 `resource_type` 过滤
     * 摘掉后该测试**依然绿**）。⇒ 判据必须在**同一层**（同一会话的租户上下文）里做对照。</p>
     */
    private static final java.util.concurrent.atomic.AtomicLong CURRENT_TENANT =
            new java.util.concurrent.atomic.AtomicLong(TENANT_ID);

    @BeforeAll
    static void startRealPostgresAndFixtures() throws Exception {
        cluster = PgCluster.startOrAbort();
        DataSource dataSource = cluster.dataSource();
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute(schemaSql());
            st.execute("INSERT INTO tenants (id, name, code) OVERRIDING SYSTEM VALUE VALUES ("
                    + TENANT_ID + ", 'acc-5388', 'acc-5388'), ("
                    + OTHER_TENANT_ID + ", 'acc-5388-other', 'acc-5388-other'), ("
                    + MANUAL_ONLY_TENANT_ID + ", 'acc-5388-manual', 'acc-5388-manual')");
            // ── 审计行（改价流水源）──────────────────────────────────────────────
            // ① 改价（商品级统一定价）：priceChange 带**真值** ⇒ 可判定
            audit(st, "A-5388-1", TENANT_ID, "agent_tool", "product_update", "1 day",
                    "{\"params\": {\"product_id\": \"<str>\", \"name\": \"<str>\", \"price\": \"<float>\","
                            + " \"before_price\": \"<float>\"},"
                            + " \"priceChange\": {\"product_id\": \"P-1\", \"price\": 120.0, \"before_price\": 200.0}}");
            // ② 改价（单 SKU 调价）：**另一个 tool_name 也是改价**（只筛 product_update 会漏一半）
            audit(st, "A-5388-2", TENANT_ID, "agent_tool", "sku_update", "2 days",
                    "{\"params\": {\"product_id\": \"<str>\", \"color\": \"<str>\", \"price\": \"<float>\","
                            + " \"before_price\": \"<float>\"},"
                            + " \"priceChange\": {\"product_id\": \"P-2\", \"color\": \"米白\","
                            + " \"price\": 250.0, \"before_price\": 500.0}}");
            // ③ **脱敏期**的历史改价行：params 里有 price 键（= 确实改过价），但没有 priceChange 真值
            //    ⇒ 该行价格必须落 null（**未判定**），**不是 0**
            audit(st, "A-5388-3", TENANT_ID, "agent_tool", "product_update", "3 days",
                    "{\"params\": {\"product_id\": \"<str>\", \"price\": \"<float>\", \"before_price\": \"<float>\"}}");
            // ④ 只改名：params 里**没有** price 键 ⇒ 不是改价事件（进数组就是把「改名」当「改价」）
            audit(st, "A-5388-4", TENANT_ID, "agent_tool", "product_update", "4 days",
                    "{\"params\": {\"product_id\": \"<str>\", \"name\": \"<str>\"}}");
            // ⑤ **对抗行**：非改价工具（order_create）却带 priceChange ⇒ 工具筛选必须是承重的
            //    （谁把 `tool_name IN (...)` 摘掉，这条就会混进结果 ⇒ 判据红）
            audit(st, "A-5388-5", TENANT_ID, "agent_tool", "order_create", "1 day",
                    "{\"params\": {\"customer_id\": \"<str>\"},"
                            + " \"priceChange\": {\"product_id\": \"P-9\", \"price\": 1.0, \"before_price\": 9.0}}");
            // ⑥ 窗口外（90 天前）：改价是真的，但不该进「近期」快照
            audit(st, "A-5388-6", TENANT_ID, "agent_tool", "product_update", "90 days",
                    "{\"params\": {\"price\": \"<float>\"},"
                            + " \"priceChange\": {\"product_id\": \"P-8\", \"price\": 10.0, \"before_price\": 100.0}}");
            // ⑦ 跨租户：同窗口、同工具 ⇒ 租户过滤必须是承重的
            audit(st, "A-5388-7", OTHER_TENANT_ID, "agent_tool", "product_update", "1 day",
                    "{\"params\": {\"price\": \"<float>\"},"
                            + " \"priceChange\": {\"product_id\": \"P-7\", \"price\": 10.0, \"before_price\": 100.0}}");
            // ⑧ **人工**审计行（resource_type != agent_tool）：不算「写工具审计在跑」
            audit(st, "A-5388-8", TENANT_ID, "product", null, "1 day",
                    "{\"action\": \"update\", \"params\": {\"name\": \"<str>\"}}");
            // ⑨ 只有人工审计的租户：`audit_tool_logging` 必须 false（否则「审计没在跑」读不出来）
            audit(st, "A-5388-9", MANUAL_ONLY_TENANT_ID, "product", null, "1 day",
                    "{\"action\": \"update\", \"params\": {\"name\": \"<str>\"}}");
            // ── 订单（让利源）─────────────────────────────────────────────────
            order(st, "O-5388-1", TENANT_ID, "SO-5388-1", "1000.00", "400.00", "1 day");
            order(st, "O-5388-2", TENANT_ID, "SO-5388-2", "1000.00", "0.00", "1 day");      // 无让利 ⇒ 不进数组
            order(st, "O-5388-3", TENANT_ID, "SO-5388-3", "1000.00", "400.00", "90 days");  // 窗口外
            order(st, "O-5388-4", TENANT_ID, "SO-5388-4", "1000.00", null, "1 day");        // NULL ≠ 让利
            order(st, "O-5388-5", OTHER_TENANT_ID, "SO-5388-5", "1000.00", "400.00", "1 day");
        }
        MybatisConfiguration configuration = new MybatisConfiguration();
        configuration.setMapUnderscoreToCamelCase(true);
        configuration.setEnvironment(new Environment("acc-5388", new JdbcTransactionFactory(), dataSource));
        // 多租户拦截器**必须在场**（生产装配同源）：少了它 = 只测了 mapper 原文
        MybatisPlusInterceptor tenantLine = new MybatisPlusInterceptor();
        tenantLine.addInnerInterceptor(new TenantLineInnerInterceptor(new TenantLineHandler() {
            @Override
            public Expression getTenantId() {
                return new LongValue(CURRENT_TENANT.get());
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
        for (Class<?> mapper : List.of(AuditLogMapper.class, OrderMapper.class)) {
            configuration.addMapper(mapper);
        }
        SqlSessionFactory factory = new MybatisSqlSessionFactoryBuilder().build(configuration);
        session = factory.openSession(true);
        auditLogMapper = session.getMapper(AuditLogMapper.class);
        orderMapper = session.getMapper(OrderMapper.class);
        // 真装配的 DailyBriefingService（只喂本判据用到的两个 mapper；其余依赖不参与这两条读面）
        service = new DailyBriefingService(null, null, orderMapper, null, null, null, null, null,
                null, null, null, null, auditLogMapper, new com.fasterxml.jackson.databind.ObjectMapper(),
                null);
    }

    @AfterAll
    static void stopRealPostgres() {
        if (session != null) {
            session.close();
        }
        if (cluster != null) {
            cluster.stop();
        }
    }

    /** 「近期」窗口起点：与 `aggregateSnapshot` 同一算式（同 `SNAPSHOT_RECENT_WINDOW_DAYS`）。 */
    private static OffsetDateTime windowStart() {
        return LocalDate.now(DailyBriefingService.CST).atStartOfDay()
                .atOffset(ZoneOffset.ofHours(8))
                .minusDays(DailyBriefingService.SNAPSHOT_RECENT_WINDOW_DAYS);
    }

    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> priceRows() {
        return (List<Map<String, Object>>) (List<?>) service
                .assemblePriceChangeRows(TENANT_ID, windowStart()).rows();
    }

    @Test
    @DisplayName("改价行 = 窗口内两个工具的**改价**审计行；JSONB 真值读回是**数**（不是占位串）")
    void priceRowsComeFromBothToolsWithRealValues() {
        List<Map<String, Object>> rows = priceRows();

        // 对照读数（同一个测试里都在）：窗口内的 agent_tool 行 6 条，其中**改价**只有 3 条
        // （A-1/A-2 带真值、A-3 是脱敏期历史行；A-4 只改名、A-5 是 order_create、A-6 窗口外）
        long agentToolRowsInWindow = auditLogMapper.selectCount(
                new com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper<AuditLog>()
                        .eq(AuditLog::getTenantId, TENANT_ID)
                        .eq(AuditLog::getResourceType, "agent_tool")
                        .ge(AuditLog::getCreatedAt, windowStart()));
        assertThat(agentToolRowsInWindow)
                .as("窗口内 agent_tool 行数（对照读数：筛选必须是承重的，否则计数会等于它）")
                .isEqualTo(5L);
        assertThat(rows).hasSize(3);

        Map<String, Object> productRow = rows.stream()
                .filter(r -> "A-5388-1".equals(r.get("change_no"))).findFirst().orElseThrow();
        assertThat(productRow)
                .containsEntry("tool_name", "product_update")
                .containsEntry("product_id", "P-1")
                .containsEntry("before_price", 200.0)
                .containsEntry("new_price", 120.0);
        Map<String, Object> skuRow = rows.stream()
                .filter(r -> "A-5388-2".equals(r.get("change_no"))).findFirst().orElseThrow();
        assertThat(skuRow)
                .as("🔴 单 SKU 调价也是改价（只筛 product_update 会漏掉这一条）")
                .containsEntry("tool_name", "sku_update")
                .containsEntry("before_price", 500.0)
                .containsEntry("new_price", 250.0);
        assertThat(rows).extracting(r -> r.get("change_no"))
                .doesNotContain("A-5388-4", "A-5388-5", "A-5388-6", "A-5388-7");
    }

    @Test
    @DisplayName("脱敏期历史行 ⇒ 价格落 **null**（未判定，不是 0）；占位串不得冒充商品标识")
    void desensitizedHistoryRowIsUnjudgedNotZero() {
        Map<String, Object> legacy = priceRows().stream()
                .filter(r -> "A-5388-3".equals(r.get("change_no"))).findFirst().orElseThrow();

        assertThat(legacy)
                .as("读不出数 ⇒ null（引擎按行级「未判定」处理），**不是 0**（0 会被读成「没改价」）")
                .containsEntry("before_price", null)
                .containsEntry("new_price", null)
                .containsEntry("product_id", null);   // "<str>" 占位串不得当取证文本
    }

    /** 在「本会话租户 = {@code tenantId}」的上下文里跑一段断言（跑完复原 ⇒ 与测试顺序无关）。 */
    private static void withTenant(long tenantId, Runnable assertions) {
        long previous = CURRENT_TENANT.getAndSet(tenantId);
        try {
            assertions.run();
        } finally {
            CURRENT_TENANT.set(previous);
        }
    }

    @Test
    @DisplayName("两种「没有改价记录」的分界事实：写工具审计在跑 ⇒ true；只有人工审计 ⇒ false")
    void auditToolLoggingFactSeparatesTheTwoKindsOfEmpty() {
        assertThat(service.auditToolLoggingAlive(TENANT_ID, windowStart()))
                .as("该租户窗口内有 agent_tool 行（对照读数：5 条）⇒ 「没有改价记录」是**正常的空**")
                .isTrue();
        // 🔴 同一层对照（见 CURRENT_TENANT 的说明）：切到「只有人工审计行」的租户上再读
        withTenant(MANUAL_ONLY_TENANT_ID, () -> {
            assertThat(service.auditToolLoggingAlive(MANUAL_ONLY_TENANT_ID, windowStart()))
                    .as("该租户只有**人工**审计行 ⇒ 证明不了「写工具审计在上报」⇒ false（故障/未知的空）")
                    .isFalse();
            assertThat(service.auditToolLoggingAlive(TENANT_ID, windowStart()))
                    .as("同一层反向读数：租户过滤承重（切了租户就读不到别人的行）")
                    .isFalse();
        });
        withTenant(OTHER_TENANT_ID, () -> assertThat(
                service.auditToolLoggingAlive(OTHER_TENANT_ID, windowStart()))
                .as("另一个租户自己的 agent_tool 行仍然算它自己的")
                .isTrue());
    }

    @Test
    @DisplayName("让利行 = 窗口内 discount_amount > 0 的订单；0 / NULL / 窗口外 / 跨租户都不进")
    void discountRowsAreBoundedAndTenantScoped() {
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> rows = (List<Map<String, Object>>) (List<?>) service
                .assembleDiscountRows(TENANT_ID, windowStart()).rows();

        assertThat(rows).hasSize(1);
        assertThat(rows.get(0))
                .containsEntry("order_no", "SO-5388-1")
                .containsEntry("total_amount", new java.math.BigDecimal("1000.00"))
                .containsEntry("discount_amount", new java.math.BigDecimal("400.00"));
    }

    private static void audit(Statement st, String id, Long tenantId, String resourceType,
                              String toolName, String ago, String actionDetails) throws Exception {
        st.execute("INSERT INTO audit_logs (id, tenant_id, user_id, action, resource_type, tool_name,"
                + " action_details, created_at) VALUES ('" + id + "', " + tenantId + ", 'u-5388', 'update', '"
                + resourceType + "', " + (toolName == null ? "NULL" : "'" + toolName + "'") + ", '"
                + actionDetails + "'::jsonb, NOW() - INTERVAL '" + ago + "')");
    }

    private static void order(Statement st, String id, Long tenantId, String orderNo,
                             String total, String discount, String ago) throws Exception {
        st.execute("INSERT INTO orders (id, tenant_id, order_no, total_amount, discount_amount,"
                + " created_at) VALUES ('" + id + "', " + tenantId + ", '" + orderNo + "', " + total + ", "
                + (discount == null ? "NULL" : discount) + ", NOW() - INTERVAL '" + ago + "')");
    }

    private static String schemaSql() throws Exception {
        Path root = Paths.get(System.getProperty("user.dir")).toAbsolutePath();
        while (root != null && !Files.exists(
                root.resolve("backend/admin-api/src/main/resources/db/init/schema.sql"))) {
            root = root.getParent();
        }
        assertThat(root).as("必须能定位 backend/admin-api/src/main/resources/db/init/schema.sql"
                + "（真库建表取终态 schema，不手抄列清单）").isNotNull();
        return Files.readString(root.resolve("backend/admin-api/src/main/resources/db/init/schema.sql"));
    }
}