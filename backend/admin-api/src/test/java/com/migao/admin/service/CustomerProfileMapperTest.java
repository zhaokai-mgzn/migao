// case_ids: OR-045
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.MybatisSqlSessionFactoryBuilder;
import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.CustomerProfile;
import com.migao.admin.mapper.CustomerProfileMapper;
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

import static org.assertj.core.api.Assertions.assertThat;

/**
 * {@link CustomerProfileMapper} 的条件写/条件读判据（issue #7257）—— 真 PG。
 *
 * <p>守 SQL 自身的行为（调用方契约由 {@code CustomerProfileWriterTest} 守）：</p>
 * <ol>
 *   <li>{@code insertIgnoreByPhone/ByOpenid}：撞**任一条**唯一索引都收敛为 0 行、不抛错
 *       （这正是本单第一次实现踩到的坑：写死 {@code ON CONFLICT (tenant_id, phone)} 时，
 *       撞 openid 那条索引仍会抛 ⇒ 必须用无目标形态）；</li>
 *   <li>{@code findFirstByPhone}：历史重复行存在时**不抛** {@code TooManyResultsException}，确定性取最早一条；</li>
 *   <li>{@code touchLastActiveAt}：只动 {@code last_active_at} 这一列（不再整实体回写）。</li>
 * </ol>
 */
@DisplayName("7257 CustomerProfileMapper：撞任意唯一键收敛 / 重复行下读不抛 / 只刷新活跃时刻（真 PG）")
class CustomerProfileMapperTest {

    private static final Long TENANT = 7257L;
    private static final String PHONE = "13900007258";
    private static final String OPENID = "openid-mapper-7257";

    private static PgCluster cluster;
    private static DataSource dataSource;
    private static SqlSessionFactory factory;

    @BeforeAll
    static void startRealPostgres() throws Exception {
        cluster = PgCluster.startOrAbort();
        dataSource = cluster.dataSource();
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            Path schema = Paths.get("src", "main", "resources", "db", "init", "schema.sql");
            assertThat(Files.exists(schema)).as("schema.sql 必须存在（路径漂移 ⇒ 判红）").isTrue();
            st.execute(Files.readString(schema, StandardCharsets.UTF_8));
            st.execute("INSERT INTO tenants (id, name, code) OVERRIDING SYSTEM VALUE VALUES ("
                    + TENANT + ", 'cpm-7257', 'cpm-7257')");
            // V167 的两条普通唯一索引（schema.sql 是冻结基线 ⇒ 判据自己造出「迁移之后」的形态）
            st.execute("CREATE UNIQUE INDEX IF NOT EXISTS uk_customer_profiles_phone "
                    + "ON customer_profiles (tenant_id, phone)");
            st.execute("CREATE UNIQUE INDEX IF NOT EXISTS uk_customer_profiles_openid "
                    + "ON customer_profiles (tenant_id, wechat_openid)");
        }
        MybatisConfiguration configuration = new MybatisConfiguration();
        configuration.setMapUnderscoreToCamelCase(true);
        configuration.setEnvironment(new Environment("cpm-7257", new JdbcTransactionFactory(), dataSource));
        configuration.addMapper(CustomerProfileMapper.class);
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
    void clean() throws Exception {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.executeUpdate("DELETE FROM customer_profiles WHERE tenant_id = " + TENANT);
        }
    }

    @Test
    @DisplayName("🔴 撞**手机号**唯一索引 ⇒ 0 行；再撞**openid**唯一索引 ⇒ 也 0 行（无目标 ON CONFLICT 才能两边都收敛）")
    void insertIgnoreConvergesOnEitherUniqueIndex() throws Exception {
        try (SqlSession s = factory.openSession(true)) {
            CustomerProfileMapper mapper = s.getMapper(CustomerProfileMapper.class);
            assertThat(mapper.insertIgnoreByPhone(CustomerProfileWriter.candidate(TENANT)
                    .id("p1").phone(PHONE).wechatOpenid(OPENID).build()))
                    .as("首次插入必须命中 1 行").isEqualTo(1);
            assertThat(mapper.insertIgnoreByPhone(CustomerProfileWriter.candidate(TENANT)
                    .id("p2").phone(PHONE).wechatOpenid("openid-other").build()))
                    .as("撞手机号索引 ⇒ 0 行（幂等）").isZero();
            assertThat(mapper.insertIgnoreByOpenid(CustomerProfileWriter.candidate(TENANT)
                    .id("p3").wechatOpenid(OPENID).build()))
                    .as("撞 openid 索引 ⇒ 0 行（若写死 ON CONFLICT (tenant_id, phone) 这里会抛错）").isZero();
        }
        assertThat(count("SELECT COUNT(*) FROM customer_profiles WHERE tenant_id = " + TENANT)).isEqualTo(1);
    }

    @Test
    @DisplayName("🔴 历史重复行存在 ⇒ findFirstByPhone 不抛错，确定性取最早那条")
    void findFirstSurvivesLegacyDuplicates() throws Exception {
        // 造两条同手机号的历史行（用于复刻「修法前已经产生的重复数据」；索引先摘掉才插得进去）
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute("DROP INDEX IF EXISTS uk_customer_profiles_phone");
            st.executeUpdate("INSERT INTO customer_profiles (id, tenant_id, phone, registered_at) VALUES "
                    + "('old-1', " + TENANT + ", '" + PHONE + "', TIMESTAMPTZ '2026-01-01T00:00:00+08:00'), "
                    + "('old-2', " + TENANT + ", '" + PHONE + "', TIMESTAMPTZ '2026-02-01T00:00:00+08:00')");
        }
        try {
            CustomerProfile found;
            try (SqlSession s = factory.openSession(true)) {
                found = s.getMapper(CustomerProfileMapper.class).findFirstByPhone(TENANT, PHONE);
            }
            assertThat(found).as("重复行下必须能读到（selectOne 在这里会抛 TooManyResultsException）").isNotNull();
            assertThat(found.getId()).as("确定性取最早的一条").isEqualTo("old-1");
        } finally {
            try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
                st.executeUpdate("DELETE FROM customer_profiles WHERE tenant_id = " + TENANT);
                st.execute("CREATE UNIQUE INDEX IF NOT EXISTS uk_customer_profiles_phone "
                        + "ON customer_profiles (tenant_id, phone)");
            }
        }
    }

    @Test
    @DisplayName("🔴 touchLastActiveAt 只刷新 last_active_at（不整实体回写、不改业务列）")
    void touchOnlyUpdatesLastActiveAt() throws Exception {
        try (SqlSession s = factory.openSession(true)) {
            CustomerProfileMapper mapper = s.getMapper(CustomerProfileMapper.class);
            mapper.insertIgnoreByPhone(CustomerProfileWriter.candidate(TENANT)
                    .id("touch-1").phone(PHONE).wechatNickname("原名").build());
        }
        OffsetDateTime before = readTimestamp("last_active_at", "touch-1");
        Thread.sleep(20);
        try (SqlSession s = factory.openSession(true)) {
            assertThat(s.getMapper(CustomerProfileMapper.class).touchLastActiveAt(TENANT, "touch-1"))
                    .as("刷新必须命中 1 行").isEqualTo(1);
        }
        assertThat(readTimestamp("last_active_at", "touch-1")).isAfter(before);
        assertThat(readString("wechat_nickname", "touch-1")).as("业务列不得被改动").isEqualTo("原名");
        assertThat(readTimestamp("registered_at", "touch-1")).as("建档时刻不得被改动").isNotNull();
    }

    // ────────────────────────────────────────────── 工具

    private int count(String sql) throws Exception {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery(sql)) {
            assertThat(rs.next()).isTrue();
            return rs.getInt(1);
        }
    }

    private OffsetDateTime readTimestamp(String column, String id) throws Exception {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery("SELECT " + column + " FROM customer_profiles WHERE id = '" + id + "'")) {
            assertThat(rs.next()).isTrue();
            return rs.getObject(1, OffsetDateTime.class);
        }
    }

    private String readString(String column, String id) throws Exception {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery("SELECT " + column + " FROM customer_profiles WHERE id = '" + id + "'")) {
            assertThat(rs.next()).isTrue();
            return rs.getString(1);
        }
    }
}
