// case_ids: OR-045
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.MybatisSqlSessionFactoryBuilder;
import com.baomidou.mybatisplus.extension.plugins.MybatisPlusInterceptor;
import com.baomidou.mybatisplus.extension.plugins.handler.TenantLineHandler;
import com.baomidou.mybatisplus.extension.plugins.inner.TenantLineInnerInterceptor;
import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.CustomerProfile;
import com.migao.admin.mapper.CustomerProfileMapper;
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
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.sql.Connection;
import java.sql.ResultSet;
import java.sql.Statement;
import java.time.OffsetDateTime;
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
 * issue #7257 真库判据：同一手机号 / 同一微信身份**只会有一条**客户档案。
 *
 * <h2>为什么必须真 PG</h2>
 * 修法的正确性全在「部分唯一索引的谓词」与 {@code ON CONFLICT … DO NOTHING} 的匹配行为里；
 * mock 面上没有约束，`selectOne` 判空永远"成功" ⇒ 并发双档案这个病在 mock 上**不可证**。
 *
 * <h2>三条判据</h2>
 * <ol>
 *   <li>并发 3 次按同一手机号建档 ⇒ 档案**恰好 1 条**、三次都不抛错；</li>
 *   <li>「已存在」路径只刷新 {@code last_active_at} 那一列（不整实体回写、不新增行）；</li>
 *   <li><b>判别力自证（确定性）</b>：摘掉唯一索引、按修法前的形状（一次空读 + 两次 insert）⇒ 必然 2 条。</li>
 * </ol>
 *
 * <p>夹具：`schema.sql` 是冻结基线（issue #5243），仍无这些索引 ⇒ {@code @BeforeAll} 显式执行 V167 的两条 DDL。</p>
 */
@DisplayName("7257 真库：同一手机号/微信身份只落一条档案（并发 + 判别力自证）")
class CustomerProfileDedupeRealDbTest {

    private static final Long TENANT = 7257L;
    private static final String PHONE = "13900007257";
    private static final String OPENID = "openid-7257";

    private static PgCluster cluster;
    private static DataSource dataSource;
    private static SqlSessionFactory factory;

    @BeforeAll
    static void startRealPostgresAndApplyV167() throws Exception {
        cluster = PgCluster.startOrAbort();
        dataSource = cluster.dataSource();
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute(schemaSql());
            st.execute("INSERT INTO tenants (id, name, code) OVERRIDING SYSTEM VALUE VALUES ("
                    + TENANT + ", 'cp-7257', 'cp-7257')");
        }
        MybatisConfiguration configuration = new MybatisConfiguration();
        configuration.setMapUnderscoreToCamelCase(true);
        configuration.setEnvironment(new Environment("cp-7257", new JdbcTransactionFactory(), dataSource));
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
        configuration.addMapper(CustomerProfileMapper.class);
        factory = new MybatisSqlSessionFactoryBuilder().build(configuration);
        TenantContext.setTenantId(TENANT);
        applyV167();
    }

    @AfterAll
    static void stopRealPostgres() {
        TenantContext.clear();
        if (cluster != null) {
            cluster.stop();
        }
    }

    @BeforeEach
    void cleanProfiles() throws Exception {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.executeUpdate("DELETE FROM customer_profiles WHERE tenant_id = " + TENANT);
        }
        applyV167();
    }

    // ────────────────────────────────────────────── 判据 1：并发只落一条

    @Test
    @DisplayName("🔴 判据 1：并发 3 次按同一手机号建档 ⇒ 档案恰好 1 条，三次都不抛错")
    void concurrentCreatesByPhoneLeaveOneProfile() throws Exception {
        List<Throwable> failures = runConcurrently(
                () -> { ensureByPhone(); return null; },
                () -> { ensureByPhone(); return null; },
                () -> { ensureByPhone(); return null; });

        assertThat(failures).as("并发建档不许抛错（撞唯一键要收敛为回读对手那条）").isEmpty();
        assertThat(count("SELECT COUNT(*) FROM customer_profiles WHERE tenant_id = " + TENANT
                + " AND phone = '" + PHONE + "'"))
                .as("同一手机号必须恰好 1 条档案（否则消费总额会被劈成两行）")
                .isEqualTo(1);
        assertThat(count("SELECT COUNT(*) FROM customer_profiles WHERE tenant_id = " + TENANT
                + " AND wechat_openid = '" + OPENID + "'"))
                .as("同一微信身份同样只许 1 条").isEqualTo(1);
    }

    // ────────────────────────────────────────────── 判据 2：命中既有只刷新活跃时刻

    @Test
    @DisplayName("🔴 判据 2：已存在 ⇒ 只刷新 last_active_at（不新增行、不改手机号外的业务列）")
    void existingProfileOnlyTouchesLastActiveAt() throws Exception {
        ensureByPhone();
        OffsetDateTime before = readTimestamp("last_active_at");
        Thread.sleep(20);
        ensureByPhone();

        assertThat(count("SELECT COUNT(*) FROM customer_profiles WHERE tenant_id = " + TENANT)).isEqualTo(1);
        assertThat(readTimestamp("last_active_at")).as("最后活跃时刻必须被刷新").isAfter(before);
        assertThat(count("SELECT COUNT(*) FROM customer_profiles WHERE tenant_id = " + TENANT
                + " AND phone = '" + PHONE + "' AND wechat_openid = '" + OPENID + "'"))
                .as("手机号与微信身份仍是同一条档案（没有被拆成两条）").isEqualTo(1);
    }

    // ────────────────────────────────────────────── 判据 3：旧形状确定性判红

    @Test
    @DisplayName("🔴 判据 3（判别力自证）：摘掉唯一索引 + 旧形状（一次空读 + 两次 insert）⇒ 必落 2 条")
    void legacyShapeCreatesTwoProfiles() throws Exception {
        dropV167();
        try {
            // 旧形状用**裸 JDBC** 复刻（insertIgnore* 依赖唯一索引，索引已被摘掉 ⇒ 不能用它来证旧形态）
            try (SqlSession s = factory.openSession(true)) {
                CustomerProfileMapper mapper = s.getMapper(CustomerProfileMapper.class);
                assertThat(mapper.findFirstByPhone(TENANT, PHONE))
                        .as("并发窗口里两个请求都读到空（旧实现据此各自 insert）").isNull();
            }
            try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
                for (int i = 0; i < 2; i++) {
                    st.executeUpdate("INSERT INTO customer_profiles (id, tenant_id, phone, wechat_nickname) "
                            + "VALUES ('legacy-" + i + "', " + TENANT + ", '" + PHONE + "', '旧形态')");
                }
            }
            assertThat(count("SELECT COUNT(*) FROM customer_profiles WHERE tenant_id = " + TENANT
                    + " AND phone = '" + PHONE + "'"))
                    .as("没有唯一索引时读改写必然落两条 —— 证明这个病真实存在，不是我在修一个不存在的问题")
                    .isEqualTo(2);
        } finally {
            try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
                st.executeUpdate("DELETE FROM customer_profiles WHERE tenant_id = " + TENANT);
            }
            applyV167();
        }
    }

    // ────────────────────────────────────────────── 工具

    private void ensureByPhone() {
        try (SqlSession s = factory.openSession(true)) {
            CustomerProfileMapper mapper = s.getMapper(CustomerProfileMapper.class);
            CustomerProfileWriter.ensureByPhone(mapper, CustomerProfileWriter.candidate(TENANT)
                    .phone(PHONE).wechatOpenid(OPENID).wechatNickname("张三").build());
        }
    }

    private void dropV167() throws Exception {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute("DROP INDEX IF EXISTS uk_customer_profiles_phone");
            st.execute("DROP INDEX IF EXISTS uk_customer_profiles_openid");
        }
    }

    /** V167 的两条部分唯一索引（schema.sql 是冻结基线，迁移不进去 ⇒ 判据自己造出「迁移之后」的形态）。 */
    private static void applyV167() throws Exception {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            // 本表没有 deleted 列（不做逻辑删除）⇒ 普通唯一索引；PG 的唯一索引不约束 NULL
            st.execute("CREATE UNIQUE INDEX IF NOT EXISTS uk_customer_profiles_phone "
                    + "ON customer_profiles (tenant_id, phone)");
            st.execute("CREATE UNIQUE INDEX IF NOT EXISTS uk_customer_profiles_openid "
                    + "ON customer_profiles (tenant_id, wechat_openid)");
        }
    }

    private int count(String sql) throws Exception {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery(sql)) {
            assertThat(rs.next()).isTrue();
            return rs.getInt(1);
        }
    }

    private OffsetDateTime readTimestamp(String column) throws Exception {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery("SELECT " + column + " FROM customer_profiles WHERE tenant_id = "
                     + TENANT + " AND phone = '" + PHONE + "'")) {
            assertThat(rs.next()).as("档案必须存在").isTrue();
            return rs.getObject(1, OffsetDateTime.class);
        }
    }

    private List<Throwable> runConcurrently(Callable<Void> a, Callable<Void> b, Callable<Void> c) throws Exception {
        CountDownLatch start = new CountDownLatch(1);
        ExecutorService pool = Executors.newFixedThreadPool(3);
        List<Throwable> errors = new ArrayList<>();
        try {
            List<Future<Void>> futures = new ArrayList<>();
            for (Callable<Void> task : List.of(a, b, c)) {
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

    private static String schemaSql() throws Exception {
        Path schema = Paths.get("src", "main", "resources", "db", "init", "schema.sql");
        assertThat(Files.exists(schema)).as("schema.sql 必须存在（路径漂移 ⇒ 判红）").isTrue();
        return Files.readString(schema, StandardCharsets.UTF_8);
    }
}
