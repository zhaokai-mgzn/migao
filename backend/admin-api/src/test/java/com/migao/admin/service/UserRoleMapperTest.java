// case_ids: OR-045
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.MybatisSqlSessionFactoryBuilder;
import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.UserRole;
import com.migao.admin.mapper.UserRoleMapper;
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

import static org.assertj.core.api.Assertions.assertThat;

/**
 * {@link UserRoleMapper} 的两条条件写判据（issue #7256）—— 真 PG。
 *
 * <p>守 SQL 自身的行为（不是调用方契约，那由 {@code UserRoleReviveRealDbTest} / {@code UserRoleWriterTest} 守）：</p>
 * <ol>
 *   <li>{@code reviveSoftDeleted}：只复活**软删**行、且只碰那一行（活跃行不动，别的租户不动）；</li>
 *   <li>{@code insertIfAbsent}：撞**活跃行**唯一键时返回 0（幂等），不抛错 —— 这依赖
 *       {@code ON CONFLICT (user_id, role_id) WHERE deleted = 0} 与 V166 的部分唯一索引**谓词匹配**
 *       （谓词不匹配时 PG 直接报「没有匹配 ON CONFLICT 说明的唯一或者排除约束」）。</li>
 * </ol>
 */
@DisplayName("7256 UserRoleMapper：复活软删行 / 撞活跃行唯一键不插（真 PG）")
class UserRoleMapperTest {

    private static final Long TENANT = 7256L;
    private static final String OTHER_TENANT_USER = "u-other";

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
                    + TENANT + ", 'urm-7256', 'urm-7256')");
            st.execute("INSERT INTO users (id, tenant_id, nickname, role) VALUES ('u-1', " + TENANT + ", 'u1', 'worker')");
            st.execute("INSERT INTO users (id, tenant_id, nickname, role) VALUES ('u-2', " + TENANT + ", 'u2', 'worker')");
            st.execute("INSERT INTO roles (id, tenant_id, name, code) VALUES ('r-1', " + TENANT + ", '角色1', 'r1')");
            // V166 的两条 DDL（schema.sql 是冻结基线 ⇒ 判据自己造出「迁移之后」的形态）
            st.execute("ALTER TABLE user_roles DROP CONSTRAINT IF EXISTS user_roles_user_id_role_id_key");
            st.execute("CREATE UNIQUE INDEX IF NOT EXISTS uk_user_roles_active "
                    + "ON user_roles (user_id, role_id) WHERE deleted = 0");
        }
        MybatisConfiguration configuration = new MybatisConfiguration();
        configuration.setMapUnderscoreToCamelCase(true);
        configuration.setEnvironment(new Environment("urm-7256", new JdbcTransactionFactory(), dataSource));
        configuration.addMapper(UserRoleMapper.class);
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
            st.executeUpdate("DELETE FROM user_roles");
        }
    }

    @Test
    @DisplayName("🔴 reviveSoftDeleted：只复活软删行（活跃行不动），影响 1 行；第二次 0 行")
    void reviveOnlyTouchesSoftDeletedRow() throws Exception {
        insertRaw("ur-1", "u-1", "r-1", 1);   // 软删行

        int first;
        int second;
        try (SqlSession s = factory.openSession(true)) {
            first = s.getMapper(UserRoleMapper.class).reviveSoftDeleted(TENANT, "u-1", "r-1");
            second = s.getMapper(UserRoleMapper.class).reviveSoftDeleted(TENANT, "u-1", "r-1");
        }

        assertThat(first).as("软删行必须被复活（影响 1 行）").isEqualTo(1);
        assertThat(second).as("已复活 ⇒ 第二次 0 行（幂等）").isZero();
        assertThat(deletedFlag("u-1", "r-1")).as("复活后 deleted 必须是 0").isZero();
    }

    @Test
    @DisplayName("🔴 insertIfAbsent：活跃行已存在 ⇒ 返回 0（幂等），不抛唯一键冲突")
    void insertIfAbsentIsIdempotentOnActiveRow() throws Exception {
        insertRaw("ur-2", "u-1", "r-1", 0);   // 活跃行

        int rows;
        try (SqlSession s = factory.openSession(true)) {
            rows = s.getMapper(UserRoleMapper.class).insertIfAbsent(UserRole.builder()
                    .id("ur-dup").tenantId(TENANT).userId("u-1").roleId("r-1").build());
        }

        assertThat(rows).as("撞活跃行唯一键 ⇒ 0 行（ON CONFLICT DO NOTHING 与 V166 的部分唯一索引谓词匹配）")
                .isZero();
        assertThat(countRows("u-1", "r-1")).as("不得多出行").isEqualTo(1);
    }

    @Test
    @DisplayName("🔴 insertIfAbsent：软删行存在 ⇒ 仍可插入活跃行（唯一性只看活跃行）")
    void insertIfAbsentAllowsNewActiveRowWhenOnlySoftDeletedExists() throws Exception {
        insertRaw("ur-3", "u-1", "r-1", 1);   // 只有软删行

        int rows;
        try (SqlSession s = factory.openSession(true)) {
            rows = s.getMapper(UserRoleMapper.class).insertIfAbsent(UserRole.builder()
                    .id("ur-4").tenantId(TENANT).userId("u-1").roleId("r-1").build());
        }

        assertThat(rows).as("软删行不参与唯一性 ⇒ 活跃行可插入").isEqualTo(1);
        assertThat(countActiveRows("u-1", "r-1")).isEqualTo(1);
    }

    // ────────────────────────────────────────────── 工具

    private void insertRaw(String id, String userId, String roleId, int deleted) throws Exception {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.executeUpdate("INSERT INTO user_roles (id, tenant_id, user_id, role_id, deleted) VALUES ('"
                    + id + "', " + TENANT + ", '" + userId + "', '" + roleId + "', " + deleted + ")");
        }
    }

    private int deletedFlag(String userId, String roleId) throws Exception {
        return queryInt("SELECT deleted FROM user_roles WHERE user_id = '" + userId
                + "' AND role_id = '" + roleId + "' ORDER BY deleted LIMIT 1");
    }

    private int countRows(String userId, String roleId) throws Exception {
        return queryInt("SELECT COUNT(*) FROM user_roles WHERE user_id = '" + userId
                + "' AND role_id = '" + roleId + "'");
    }

    private int countActiveRows(String userId, String roleId) throws Exception {
        return queryInt("SELECT COUNT(*) FROM user_roles WHERE user_id = '" + userId
                + "' AND role_id = '" + roleId + "' AND deleted = 0");
    }

    private int queryInt(String sql) throws Exception {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery(sql)) {
            assertThat(rs.next()).isTrue();
            return rs.getInt(1);
        }
    }
}
