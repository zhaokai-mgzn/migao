// case_ids: MC-161
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.MybatisSqlSessionFactoryBuilder;
import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.Role;
import com.migao.admin.mapper.RoleMapper;
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
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * issue #7255：{@code RoleMapper#insertIfAbsent} 的** mapper 级**契约（真 PG）。
 *
 * <h2>为什么单列一个 mapper 判据</h2>
 * 服务层判据（{@code PaymentQrcodeAndRoleUniqueWriteRealDbTest}）证的是「并发下只落一行 + 幂等 +
 * 摘掉唯一键必红」这条**行为链**；这里证的是**这一条 SQL** 自身的三件事 —— 任何一件塌了，
 * 上面的行为链都会以「500」或「静默双行」的形态坏掉，但报错点会离这里很远：
 * <ol>
 *   <li>首次插入返回 1（语句真的落库，不是被 {@code ON CONFLICT} 误判成冲突）；</li>
 *   <li>同 {@code (tenant_id, code)} 再插返回 <b>0 且不抛</b>（幂等；换成裸 {@code insert} 时这里会抛
 *       {@code 23505}）—— 且**不覆盖**既有行的 {@code name}；</li>
 *   <li>不同 tenant / 不同 code 各自可插（唯一键只钉业务键，没做太宽）。</li>
 * </ol>
 *
 * <p>⚠️ 依赖 {@code roles (tenant_id, code)} 的**唯一键在场**（建库脚本的表内 {@code UNIQUE}，
 * 或 V206 的 {@code uk_roles_tenant_code}）。缺了它，{@code ON CONFLICT (tenant_id, code)} 会被 PG
 * 拒绝并报「没有匹配 ON CONFLICT 说明的唯一或者排除约束」—— 本判据在删掉索引时会红一次，
 * 那正是「迁移没跑 / 库漂移」的真实症状（不是本判据写错）。</p>
 */
@DisplayName("7255 RoleMapper：insertIfAbsent 撞唯一键不插（真 PG）")
class RoleMapperTest {

    private static final Long TENANT = 7255L;
    private static final Long OTHER_TENANT = 9255L;

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
                    + TENANT + ", 'rm-7255', 'rm-7255')");
            st.execute("INSERT INTO tenants (id, name, code) OVERRIDING SYSTEM VALUE VALUES ("
                    + OTHER_TENANT + ", 'rm-9255', 'rm-9255')");
        }
        MybatisConfiguration configuration = new MybatisConfiguration();
        configuration.setMapUnderscoreToCamelCase(true);
        configuration.setEnvironment(new Environment("rm-7255", new JdbcTransactionFactory(), dataSource));
        configuration.addMapper(RoleMapper.class);
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
            st.executeUpdate("DELETE FROM roles WHERE tenant_id IN (" + TENANT + ", " + OTHER_TENANT + ")");
        }
    }

    @Test
    @DisplayName("🔴 insertIfAbsent：首次插入返回 1，行真的在")
    void firstInsertLands() throws Exception {
        assertThat(insert(TENANT, "operator", "运营")).as("首次插入必须落库（影响 1 行）").isEqualTo(1);
        assertThat(rowCount(TENANT, "operator")).isEqualTo(1);
    }

    @Test
    @DisplayName("🔴 insertIfAbsent：同 (tenant, code) 再插 ⇒ 0 行、不抛错、不产生第二行、不覆盖既有行")
    void duplicateInsertIsIdempotentAndDoesNotOverwrite() throws Exception {
        assertThat(insert(TENANT, "operator", "运营")).isEqualTo(1);

        // 换成裸 insert 时这一行会抛 23505（= 用户看到的 500）；条件插入必须收敛成 0 行
        int rows = insert(TENANT, "operator", "另一个名字");

        assertThat(rows).as("已存在 ⇒ 0 行（ON CONFLICT (tenant_id, code) DO NOTHING）").isZero();
        assertThat(rowCount(TENANT, "operator")).as("不得多出行").isEqualTo(1);
        assertThat(nameOf(TENANT, "operator")).as("既有行不被第二次请求的 name 覆盖").isEqualTo("运营");
    }

    @Test
    @DisplayName("🔴 insertIfAbsent（负控）：不同 tenant / 不同 code 各自可插")
    void theUniqueKeyDoesNotBlockLegitimateRows() throws Exception {
        assertThat(insert(TENANT, "operator", "运营")).isEqualTo(1);
        assertThat(insert(TENANT, "finance", "财务")).as("同租户不同 code ⇒ 可插").isEqualTo(1);
        assertThat(insert(OTHER_TENANT, "operator", "运营B")).as("不同租户同 code ⇒ 可插").isEqualTo(1);

        assertThat(rowCount(TENANT, "operator")).isEqualTo(1);
        assertThat(rowCount(TENANT, "finance")).isEqualTo(1);
        assertThat(rowCount(OTHER_TENANT, "operator")).isEqualTo(1);
    }

    // ────────────────────────────────────────────── 工具

    private int insert(Long tenantId, String code, String name) {
        TenantContext.setTenantId(tenantId);
        try (SqlSession s = factory.openSession(true)) {
            return s.getMapper(RoleMapper.class).insertIfAbsent(Role.builder()
                    .id(UUID.randomUUID().toString().replace("-", ""))
                    .tenantId(tenantId)
                    .name(name)
                    .code(code)
                    .status("active")
                    .build());
        }
    }

    private int rowCount(Long tenantId, String code) throws Exception {
        return count("SELECT COUNT(*) FROM roles WHERE tenant_id = " + tenantId + " AND code = '" + code + "'");
    }

    private String nameOf(Long tenantId, String code) throws Exception {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery("SELECT name FROM roles WHERE tenant_id = " + tenantId
                     + " AND code = '" + code + "'")) {
            assertThat(rs.next()).isTrue();
            return rs.getString(1);
        }
    }

    private int count(String sql) throws Exception {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery(sql)) {
            assertThat(rs.next()).isTrue();
            return rs.getInt(1);
        }
    }
}
