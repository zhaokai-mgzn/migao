// case_ids: OR-045
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.MybatisSqlSessionFactoryBuilder;
import com.baomidou.mybatisplus.extension.plugins.MybatisPlusInterceptor;
import com.baomidou.mybatisplus.extension.plugins.handler.TenantLineHandler;
import com.baomidou.mybatisplus.extension.plugins.inner.TenantLineInnerInterceptor;
import com.migao.admin.config.TenantContext;
import com.migao.admin.mapper.UserRoleMapper;
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
 * issue #7256 真库判据：`user_roles` 的唯一性必须只约束**活跃行**。
 *
 * <h2>病（本单的主症状，真库才能证）</h2>
 * 原表是**全表** {@code UNIQUE(user_id, role_id)}，而删除是逻辑删除（{@code @TableLogic}）⇒
 * 「移除角色」只把 {@code deleted} 置 1、行还在 ⇒ 再授权同一角色**撞唯一键 ⇒ 500**。
 * 这个病的观测点是**约束与谓词的行为**：mock 面上没有约束，`selectOne` 判空永远"成功"。
 *
 * <h2>三条判据</h2>
 * <ol>
 *   <li><b>移除后能再加回来</b>：写入 → 逻辑删 → 再 ensureGranted ⇒ 成功、活跃行恰 1、软删行仍在（历史不丢）；</li>
 *   <li><b>并发两次只落一条活跃行</b>（条件插入 + 活跃行唯一索引兜底）；</li>
 *   <li><b>判别力自证（确定性）</b>：把唯一性还原成修法前的**全表**约束、并用旧写法（逻辑删后裸 insert）⇒
 *       必然抛唯一键冲突 —— 证明「移除后加不回来」这个病真实存在，不是我在修一个不存在的问题。</li>
 * </ol>
 *
 * <p>夹具说明：`schema.sql` 是**冻结基线**（issue #5243），它在测试库里仍带全表 UNIQUE ⇒
 * {@code @BeforeAll} 里显式执行 V166 的两条 DDL（删旧约束 + 建活跃行部分唯一索引），
 * 让判据跑在「迁移之后」的形态上。判据 3 会把它临时还原。</p>
 */
@DisplayName("7256 真库：移除角色后能再授权（活跃行唯一）/ 并发只落一行 / 旧形态确定性判红")
class UserRoleReviveRealDbTest {

    private static final Long TENANT = 7256L;
    private static final String USER = "u-7256";
    private static final String ROLE = "r-7256";

    private static PgCluster cluster;
    private static DataSource dataSource;
    private static SqlSessionFactory factory;

    @BeforeAll
    static void startRealPostgresAndApplyV166() throws Exception {
        cluster = PgCluster.startOrAbort();
        dataSource = cluster.dataSource();
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute(schemaSql());
            st.execute("INSERT INTO tenants (id, name, code) OVERRIDING SYSTEM VALUE VALUES ("
                    + TENANT + ", 'ur-7256', 'ur-7256')");
            st.execute("INSERT INTO users (id, tenant_id, nickname, role) VALUES ('"
                    + USER + "', " + TENANT + ", 'ur-7256-user', 'worker')");
            st.execute("INSERT INTO roles (id, tenant_id, name, code) VALUES ('"
                    + ROLE + "', " + TENANT + ", '测试角色', 'r7256')");
        }
        MybatisConfiguration configuration = new MybatisConfiguration();
        configuration.setMapUnderscoreToCamelCase(true);
        configuration.setEnvironment(new Environment("ur-7256", new JdbcTransactionFactory(), dataSource));
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
        configuration.addMapper(UserRoleMapper.class);
        factory = new MybatisSqlSessionFactoryBuilder().build(configuration);
        TenantContext.setTenantId(TENANT);
        applyV166();
    }

    @AfterAll
    static void stopRealPostgres() {
        TenantContext.clear();
        if (cluster != null) {
            cluster.stop();
        }
    }

    @BeforeEach
    void cleanUserRoles() throws Exception {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.executeUpdate("DELETE FROM user_roles WHERE tenant_id = " + TENANT);
        }
    }

    // ────────────────────────────────────────────── 判据 1：移除后能再加回来

    @Test
    @DisplayName("🔴 判据 1：授权 → 逻辑删（= 移除角色）→ 再授权 ⇒ 成功，活跃行恰 1，软删行仍在")
    void removedRoleCanBeGrantedAgain() throws Exception {
        grant();
        logicallyRevoke();
        assertThat(activeRows()).as("移除后活跃行为 0（逻辑删）").isZero();
        assertThat(allRows()).as("软删行仍在（历史不丢）").isEqualTo(1);

        grant();   // ← 修法前这里必撞全表唯一键 ⇒ 500

        assertThat(activeRows()).as("重新授权后活跃行恰 1").isEqualTo(1);
        assertThat(allRows()).as("复活而不是插新行（不制造同一个人同一角色的两条历史）").isEqualTo(1);
    }

    // ────────────────────────────────────────────── 判据 2：并发只落一行

    @Test
    @DisplayName("🔴 判据 2：并发两次授权同一 (user, role) ⇒ 活跃行恰 1，两次都不抛错")
    void concurrentGrantsLeaveExactlyOneActiveRow() throws Exception {
        List<Throwable> failures = runConcurrently(
                () -> { grant(); return null; },
                () -> { grant(); return null; });

        assertThat(failures).as("并发重复授权不许抛错（撞唯一键要幂等收敛）").isEmpty();
        assertThat(activeRows()).as("活跃行必须恰好 1 条").isEqualTo(1);
    }

    // ────────────────────────────────────────────── 判据 3：旧形态确定性判红

    @Test
    @DisplayName("🔴 判据 3（判别力自证）：还原修法前的「全表唯一 + 逻辑删后裸 insert」⇒ 必抛唯一键冲突")
    void legacyShapeIsReproduciblyBroken() throws Exception {
        restoreFullTableUnique();
        try {
            grant();
            logicallyRevoke();
            boolean threw = false;
            try {
                // 旧写法：直接 insert 同一 (user_id, role_id)（行仍在、deleted = 1）
                try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
                    st.executeUpdate("INSERT INTO user_roles (id, tenant_id, user_id, role_id, deleted) "
                            + "VALUES ('legacy-dup', " + TENANT + ", '" + USER + "', '" + ROLE + "', 0)");
                }
            } catch (java.sql.SQLException expected) {
                threw = true;
                // 判 SQLState 而不是报错文案（PG 的错误信息随 lc_messages 变：本机中文、CI 英文）
                assertThat(expected.getSQLState())
                        .as("必须是唯一键冲突 SQLState 23505，不是别的错")
                        .isEqualTo("23505");
            }
            assertThat(threw)
                    .as("修法前的形态必须能复现「移除后加不回来」—— 否则本判据测不到这个病")
                    .isTrue();
        } finally {
            try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
                st.executeUpdate("DELETE FROM user_roles WHERE tenant_id = " + TENANT);
            }
            applyV166();
        }
    }

    // ────────────────────────────────────────────── 工具

    private void grant() {
        try (SqlSession s = factory.openSession(true)) {
            UserRoleWriter.ensureGranted(s.getMapper(UserRoleMapper.class), TENANT, USER, ROLE);
        }
    }

    /** 复刻「移除角色」：MyBatis-Plus 逻辑删除（{@code deleted = 1}，行仍在）。 */
    private void logicallyRevoke() throws Exception {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.executeUpdate("UPDATE user_roles SET deleted = 1 WHERE tenant_id = " + TENANT
                    + " AND user_id = '" + USER + "' AND role_id = '" + ROLE + "'");
        }
    }

    private int activeRows() throws Exception {
        return count("SELECT COUNT(*) FROM user_roles WHERE tenant_id = " + TENANT
                + " AND user_id = '" + USER + "' AND role_id = '" + ROLE + "' AND deleted = 0");
    }

    private int allRows() throws Exception {
        return count("SELECT COUNT(*) FROM user_roles WHERE tenant_id = " + TENANT
                + " AND user_id = '" + USER + "' AND role_id = '" + ROLE + "'");
    }

    private int count(String sql) throws Exception {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery(sql)) {
            assertThat(rs.next()).isTrue();
            return rs.getInt(1);
        }
    }

    /** V166 的两条 DDL（schema.sql 是冻结基线，迁移不进去 ⇒ 判据自己造出「迁移之后」的形态）。 */
    private static void applyV166() throws Exception {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute("ALTER TABLE user_roles DROP CONSTRAINT IF EXISTS user_roles_user_id_role_id_key");
            st.execute("CREATE UNIQUE INDEX IF NOT EXISTS uk_user_roles_active "
                    + "ON user_roles (user_id, role_id) WHERE deleted = 0");
        }
    }

    /** 还原修法前的形态：全表唯一、无部分索引。 */
    private void restoreFullTableUnique() throws Exception {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute("DROP INDEX IF EXISTS uk_user_roles_active");
            st.execute("ALTER TABLE user_roles ADD CONSTRAINT user_roles_user_id_role_id_key "
                    + "UNIQUE (user_id, role_id)");
        }
    }

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

    private static String schemaSql() throws Exception {
        Path schema = Paths.get("src", "main", "resources", "db", "init", "schema.sql");
        assertThat(Files.exists(schema)).as("schema.sql 必须存在（路径漂移 ⇒ 判红，不是空跑通过）").isTrue();
        return Files.readString(schema, StandardCharsets.UTF_8);
    }
}
