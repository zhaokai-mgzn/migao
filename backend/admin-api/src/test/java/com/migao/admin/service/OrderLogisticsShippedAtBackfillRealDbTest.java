// case_ids: OR-064
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.MybatisSqlSessionFactoryBuilder;
import com.baomidou.mybatisplus.extension.plugins.MybatisPlusInterceptor;
import com.baomidou.mybatisplus.extension.plugins.handler.TenantLineHandler;
import com.baomidou.mybatisplus.extension.plugins.inner.TenantLineInnerInterceptor;
import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.OrderLogistics;
import com.migao.admin.mapper.OrderLogisticsMapper;
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

import javax.sql.DataSource;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.sql.Connection;
import java.sql.ResultSet;
import java.sql.Statement;
import java.time.OffsetDateTime;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 🔴 <b>物流「首次发货时刻」的真库判据（issue #6276；用户 2026-10-10 已裁定口径）。</b>
 *
 * <h2>口径（用户逐字：{@code shipped_at} = <b>首次发货时刻</b>）</h2>
 * 这条裁定**排除了**另一种口径（「最近一次改物流时刻」）⇒ 两条不变量（判据两侧夹住，缺一不可）：
 * <ol>
 *   <li><b>已有非空值一律不得被覆盖</b>（改一次运单号 <b>不许</b>改发货时刻）；</li>
 *   <li>只有「该行没有首次发货时刻」时才补，且补进去的必须是<b>首次发货时刻</b>、且<b>只补一次</b>。</li>
 * </ol>
 *
 * <h2>为什么必须真 PG（mock 面结构上看不见的三件事）</h2>
 * <ol>
 *   <li><b>「不覆盖」是 SQL 谓词的行为</b>：修法是一条
 *       {@code UPDATE order_logistics SET shipped_at = created_at WHERE … AND shipped_at IS NULL}。
 *       mock 的 mapper 恒返回我 stub 的值 ⇒「已有值时那一行<b>真的没被改</b>」在 mock 上**不可证**
 *       （而那正是本单要守的全部内容）。</li>
 *   <li><b>补进去的值取的是「该行自己的 {@code created_at}」</b>（列对列），不是调用方时钟：
 *       只有真库能读「补出来的值 == 建行时刻」这条等式（本判据把建行时刻种成**过去**的一个月前，
 *       与「跑判据的当下」可区分 ⇒ 若实现写成 {@code now()} 当场红），也才能证「补第二次 0 行」。</li>
 *   <li><b>补写必须发生在 {@code updateById} <b>之前</b></b>：顺序写反时，实体里读到的旧
 *       {@code shipped_at} 会把刚补的值盖回去（判据 ③ 直接复刻这个坏顺序并证明它会红）。</li>
 * </ol>
 *
 * <p>装配形态与 {@code AutoCompleteShippedRealDbTest} 同款：一次性 {@code initdb} + {@code pg_ctl}
 * 集群（{@link PgCluster#startOrAbort()} 收口）、<b>生产的多租户拦截器 bean</b>在场
 * （少了它就只测了 mapper 原文、没测生产 SQL）。被判定的事实全部是真库读数。</p>
 */
@DisplayName("6276 真库：空值补首次发货时刻（只补一次）/ 已有值逐字不变 / 补写必须先于 updateById")
class OrderLogisticsShippedAtBackfillRealDbTest {

    private static final Long TENANT_A = 6276L;
    private static final Long TENANT_B = 6277L;
    /** 建行时刻（= 首次发货时刻的表内真值）；刻意取**一个月前**，与「跑判据的当下」在读数上可区分。 */
    private static final OffsetDateTime FIRST_SHIP =
            OffsetDateTime.parse("2026-09-09T18:00:00+08:00");

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
                    + TENANT_A + ", 'ol-6276-a', 'ol-6276-a')");
            st.execute("INSERT INTO tenants (id, name, code) OVERRIDING SYSTEM VALUE VALUES ("
                    + TENANT_B + ", 'ol-6276-b', 'ol-6276-b')");
        }
        MybatisConfiguration configuration = new MybatisConfiguration();
        configuration.setMapUnderscoreToCamelCase(true);
        configuration.setEnvironment(new Environment("ol-6276", new JdbcTransactionFactory(), dataSource));
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
        configuration.addMapper(OrderLogisticsMapper.class);
        factory = new MybatisSqlSessionFactoryBuilder().build(configuration);
        TenantContext.setTenantId(TENANT_A);
    }

    @AfterAll
    static void stopRealPostgres() {
        TenantContext.clear();
        if (cluster != null) {
            cluster.stop();
        }
    }

    /** 每个用例从干净夹具开始（共用一个集群 ⇒ 前一个用例的行不得串味）。 */
    @BeforeEach
    void resetFixtures() throws Exception {
        for (String table : List.of("order_logistics", "orders")) {
            try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
                st.executeUpdate("DELETE FROM " + table + " WHERE tenant_id IN ("
                        + TENANT_A + "," + TENANT_B + ")");
            }
        }
    }

    // ────────────────────────────────────────────── 两侧判据（缺一不可）

    @Test
    @DisplayName("🔴 判据 ②：空值 + 一次更新 ⇒ 补上**首次发货时刻**（= 该行 created_at），且**只补一次**")
    void nullShippedAtIsBackfilledWithFirstShipMomentExactlyOnce() throws Exception {
        seedOrder("ol-null", TENANT_A);
        seedLogistics("ol-null-1", TENANT_A, "ol-null", "SF-OLD", null, FIRST_SHIP);

        upsert("ol-null", "SF-NEW");

        assertThat(readShippedAt("ol-null-1"))
                .as("空值必须补上，且取值 = 该行的 created_at（首次发货时刻）—— 不是 now()")
                .isEqualTo(FIRST_SHIP);

        // 「只补一次」：第二次更新不得再改变它
        upsert("ol-null", "SF-AGAIN");
        assertThat(readShippedAt("ol-null-1"))
                .as("第二次更新不得改变已补上的首次发货时刻").isEqualTo(FIRST_SHIP);
        assertThat(readTrackingNo("ol-null-1")).isEqualTo("SF-AGAIN");

        int secondCallRows;
        try (SqlSession s = factory.openSession(true)) {
            secondCallRows = s.getMapper(OrderLogisticsMapper.class)
                    .backfillShippedAtIfAbsent("ol-null", TENANT_A);
        }
        assertThat(secondCallRows)
                .as("幂等：第二次补写 0 行（`shipped_at IS NULL` 谓词对自己已补的行不成立）").isZero();
    }

    @Test
    @DisplayName("🔴 判据 ①：已有值 + 一次更新 ⇒ 该值**逐字不变**（改运单号 ≠ 改发货时刻）")
    void existingShippedAtIsNeverOverwrittenByAnUpdate() throws Exception {
        OffsetDateTime realFirstShip = OffsetDateTime.parse("2026-08-01T09:30:00+08:00");
        seedOrder("ol-kept", TENANT_A);
        // 建行时刻（created_at）与「真实首次发货时刻」刻意**不同**：若实现用 created_at（或 now()）
        // 覆盖已有值，读数会变成 FIRST_SHIP（或当下）⇒ 当场红。这就是本判据的判别力所在。
        seedLogistics("ol-kept-1", TENANT_A, "ol-kept", "SF-OLD", realFirstShip, FIRST_SHIP);

        // 🔴 先单独盯住**补写语句本身**（不经 updateById）：它的 `shipped_at IS NULL` 谓词是
        // 「绝不覆盖」的**唯一**守卫。⚠️ 这一步不可省 —— 只看端到端结果会被 `updateById` **掩盖**
        // （实体里读到的是已有的非空值，它会把任何一次越权覆盖原样写回去 ⇒ 端到端读数照样"不变"）。
        // 实测过的假绿形态：把谓词摘掉（无条件下 `now()`）⇒ 端到端断言**照样绿**，只有这一条当场红。
        int rows;
        try (SqlSession s = factory.openSession(true)) {
            rows = s.getMapper(OrderLogisticsMapper.class).backfillShippedAtIfAbsent("ol-kept", TENANT_A);
        }
        assertThat(rows).as("已有值 ⇒ 补写必须 **0 行**（谓词 `shipped_at IS NULL` 说它不成立）").isZero();
        assertThat(readShippedAt("ol-kept-1"))
                .as("补写语句不得动已有值（这一条断言不经 updateById ⇒ 不被掩盖）")
                .isEqualTo(realFirstShip);

        // 再看端到端：走完整 upsert 之后仍逐字不变
        upsert("ol-kept", "SF-NEW");
        assertThat(readShippedAt("ol-kept-1"))
                .as("已有非空值一律不得被覆盖（不得被 created_at 顶掉、更不得被 now() 顶掉）")
                .isEqualTo(realFirstShip);
        assertThat(readTrackingNo("ol-kept-1")).isEqualTo("SF-NEW");
    }

    // ────────────────────────────────────────────── 顺序（补写必须先于 updateById）

    @Test
    @DisplayName("🔴 判据 ③：顺序不可互换 —— 「先 updateById 再补写」会把**非空旧值**写回去，补写救不回来")
    void badOrderingLosesTheBackfill() throws Exception {
        // 这一条用一个**首次发货时刻被写坏成过去某个错值**的行来演示：
        // 若把补写排在 updateById 之后，updateById 会先把实体里那个错值写回库里，
        // 而补写又因为「已有值」而 0 行 ⇒ **错值被固化**（这才是不变量 ② 的真实失败形态）。
        OffsetDateTime wrongValue = OffsetDateTime.parse("2026-07-01T00:00:00+08:00");
        seedOrder("ol-seq", TENANT_A);
        seedLogistics("ol-seq-1", TENANT_A, "ol-seq", "SF-OLD", wrongValue, FIRST_SHIP);

        OrderLogistics loaded;
        try (SqlSession s = factory.openSession(true)) {
            loaded = s.getMapper(OrderLogisticsMapper.class).selectByOrderId("ol-seq", TENANT_A).get(0);
        }
        // 模拟「补写排在后面且实体带着一个陈旧/错误的值」：实体里把 shipped_at 改成错值
        loaded.setShippedAt(wrongValue.plusDays(1));
        loaded.setTrackingNo("SF-NEW");
        try (SqlSession s = factory.openSession(true)) {
            s.getMapper(OrderLogisticsMapper.class).updateById(loaded);
        }
        assertThat(readShippedAt("ol-seq-1"))
                .as("updateById 会把实体里的**非 null** 值原样写回 ⇒ 谁在它之后补写都救不回来"
                        + "（故生产的顺序是：补写 → updateById，且补写只认 `IS NULL`）")
                .isEqualTo(wrongValue.plusDays(1));
    }

    // ────────────────────────────────────────────── 多租户隔离

    @Test
    @DisplayName("判据：补写带显式 tenant_id 谓词 ⇒ 跨租户调用改不到别人的行（反向对照）")
    void backfillIsTenantScoped() throws Exception {
        seedOrder("ol-a", TENANT_A);
        seedLogistics("ol-a-1", TENANT_A, "ol-a", "SF-A", null, FIRST_SHIP);
        seedOrder("ol-b", TENANT_B);
        seedLogistics("ol-b-1", TENANT_B, "ol-b", "SF-B", null, FIRST_SHIP);

        // 上下文 = A，显式参数 = A ⇒ 只动 A（1 行）
        int rows;
        try (SqlSession s = factory.openSession(true)) {
            rows = s.getMapper(OrderLogisticsMapper.class).backfillShippedAtIfAbsent("ol-a", TENANT_A);
        }
        assertThat(rows).as("本租户自己的行必须补到（否则判据是空跑）").isEqualTo(1);
        assertThat(readShippedAt("ol-a-1")).isEqualTo(FIRST_SHIP);

        // 上下文 = A，显式参数 = B ⇒ 拦截器与显式谓词都不允许改到 B 的行
        try (SqlSession s = factory.openSession(true)) {
            assertThat(s.getMapper(OrderLogisticsMapper.class).backfillShippedAtIfAbsent("ol-b", TENANT_B))
                    .as("在 A 上下文里对 B 的行调用 ⇒ **0 行**，不得顺手改到别人的行").isZero();
        }
        assertThat(readShippedAt("ol-b-1"))
                .as("B 的行必须纹丝不动（跨租户隔离有牙齿）").isNull();
    }

    // ────────────────────────────────────────────── 夹具

    /** 走与生产**同一个** {@link OrderLogisticsWriter#upsert}（更新分支）—— 不另写一份调用序列。 */
    private void upsert(String orderId, String trackingNo) {
        try (SqlSession s = factory.openSession(true)) {
            OrderLogisticsWriter.upsert(s.getMapper(OrderLogisticsMapper.class), TENANT_A,
                    orderId, "顺丰", trackingNo, null, () -> null);
        }
    }

    private void seedOrder(String orderId, Long tenantId) throws Exception {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.executeUpdate("INSERT INTO orders (id, tenant_id, order_no, status) VALUES ('"
                    + orderId + "', " + tenantId + ", 'NO-" + orderId + "', 'shipped')");
        }
    }

    /**
     * 建物流行：{@code shipped_at} 与 {@code created_at} **分别**显式给值
     * （{@code shippedAt == null} 即「该行没有首次发货时刻」）。
     */
    private void seedLogistics(String id, Long tenantId, String orderId, String trackingNo,
                               OffsetDateTime shippedAt, OffsetDateTime createdAt) throws Exception {
        String shipped = shippedAt == null ? "NULL" : "TIMESTAMPTZ '" + shippedAt + "'";
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.executeUpdate("INSERT INTO order_logistics (id, tenant_id, order_id, logistics_company,"
                    + " tracking_no, status, shipped_at, created_at, updated_at, deleted) VALUES ('" + id + "', "
                    + tenantId + ", '" + orderId + "', '顺丰', '" + trackingNo + "', 'in_transit', "
                    + shipped + ", TIMESTAMPTZ '" + createdAt + "', TIMESTAMPTZ '" + createdAt + "', 0)");
        }
    }

    private OffsetDateTime readShippedAt(String id) throws Exception {
        return readTimestamp(id, "shipped_at");
    }

    private String readTrackingNo(String id) throws Exception {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery("SELECT tracking_no FROM order_logistics WHERE id = '" + id + "'")) {
            assertThat(rs.next()).as("行必须存在（夹具/写面出问题 ⇒ 具名红，不是空跑通过）").isTrue();
            return rs.getString(1);
        }
    }

    private OffsetDateTime readTimestamp(String id, String column) throws Exception {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery("SELECT " + column + " FROM order_logistics WHERE id = '" + id + "'")) {
            assertThat(rs.next()).as("行必须存在（夹具/写面出问题 ⇒ 具名红，不是空跑通过）").isTrue();
            return rs.getObject(1, OffsetDateTime.class);
        }
    }

    private static String schemaSql() throws IOException {
        Path schema = Paths.get("src", "main", "resources", "db", "init", "schema.sql");
        assertThat(Files.exists(schema)).as("schema.sql 必须存在（路径漂移 ⇒ 判红，不是空跑通过）").isTrue();
        return Files.readString(schema, StandardCharsets.UTF_8);
    }
}
