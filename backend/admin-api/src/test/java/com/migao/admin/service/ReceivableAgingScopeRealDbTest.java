// case_ids: RPT-005
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.MybatisSqlSessionFactoryBuilder;
import com.baomidou.mybatisplus.extension.plugins.MybatisPlusInterceptor;
import com.baomidou.mybatisplus.extension.plugins.handler.TenantLineHandler;
import com.baomidou.mybatisplus.extension.plugins.inner.TenantLineInnerInterceptor;
import com.migao.admin.dto.ReceivableAgingRow;
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
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 真库：账龄取数 SQL 的**可选范围参数**与「余额 &gt; 0」过滤（issue #7376 段 5）。
 *
 * <h3>为什么必须真库</h3>
 * <p>报表侧给 {@code selectReceivableRows} 加了一个可选参数 {@code createdBy}（P0-4 数据范围）。
 * 这条 SQL 里它出现在 <b>{@code #{createdBy} IS NULL}</b> 的**主语位**—— issue #5975 的形态：
 * 实参为 NULL 时 PG 拿到的是 *unspecified* 类型的参数，直接
 * {@code could not determine data type of parameter} ⇒ 500。而**单测把 Mapper 全 mock 掉**，
 * 这种故障只在真库上现形（云上「财务看账龄 500」就是这么来的）。</p>
 *
 * <p>本判据同时钉住三件事：① 传 {@code null} 不炸（全量口径）；② 传制单人只回他那张单；
 * ③ 传一个没有单的制单人 ⇒ 空集（不是全量 —— 参数被吞掉时这里会红）。</p>
 */
@DisplayName("真库：账龄取数 SQL 的可选范围参数（null 不炸 / 非空收窄 / 无单为空）")
class ReceivableAgingScopeRealDbTest {

    private static final Long TENANT_ID = 73760L;

    private static PgCluster cluster;
    private static SqlSession session;
    private static OrderMapper orderMapper;

    @BeforeAll
    static void startRealPostgresAndFixtures() throws Exception {
        cluster = PgCluster.startOrAbort();
        DataSource dataSource = cluster.dataSource();
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute(schemaSql());
            st.execute("INSERT INTO tenants (id, name, code) OVERRIDING SYSTEM VALUE VALUES ("
                    + TENANT_ID + ", 'acc-7376', 'acc-7376')");
            // 两张未结清单：一张 u-a 创建、一张 u-b 创建（金额不同 ⇒ 排序也能判）
            st.execute(order("ORD-7376-A", "SO-7376-A", "u-a", "1200.0000"));
            st.execute(order("ORD-7376-B", "SO-7376-B", "u-b", "800.0000"));
            // 已结清的单**不该进账龄面**（paid_at 非空）
            st.execute("INSERT INTO orders (id, tenant_id, order_no, customer_name, customer_phone,"
                    + " total_amount, status, paid_at, deleted, created_by, created_at) VALUES"
                    + " ('ORD-7376-PAID', " + TENANT_ID + ", 'SO-7376-PAID', '已结清', '13800000009',"
                    + " 500.0000, 'completed', now(), 0, 'u-a', now())");
        }

        MybatisConfiguration configuration = new MybatisConfiguration();
        configuration.setMapUnderscoreToCamelCase(true);
        configuration.setEnvironment(new Environment("acc-7376", new JdbcTransactionFactory(), dataSource));
        // 多租户拦截器必须在场（与生产装配同源）：少了它 = 只测了 SQL 原文
        MybatisPlusInterceptor tenantLine = new MybatisPlusInterceptor();
        tenantLine.addInnerInterceptor(new TenantLineInnerInterceptor(new TenantLineHandler() {
            @Override
            public Expression getTenantId() {
                return new LongValue(TENANT_ID);
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
        SqlSessionFactory factory = new MybatisSqlSessionFactoryBuilder().build(configuration);
        session = factory.openSession(true);
        orderMapper = session.getMapper(OrderMapper.class);
    }

    @AfterAll
    static void tearDown() {
        if (session != null) {
            session.close();
        }
        if (cluster != null) {
            cluster.stop();
        }
    }

    private static String order(String id, String no, String createdBy, String amount) {
        return "INSERT INTO orders (id, tenant_id, order_no, customer_name, customer_phone,"
                + " total_amount, status, paid_at, deleted, created_by, created_at) VALUES"
                + " ('" + id + "', " + TENANT_ID + ", '" + no + "', '张记布艺', '13800000001',"
                + " " + amount + ", 'completed', NULL, 0, '" + createdBy + "', now())";
    }

    /** 终态建库脚本（不手抄列清单：库改了这里自动跟上）。 */
    private static String schemaSql() throws Exception {
        Path root = Paths.get(System.getProperty("user.dir")).toAbsolutePath();
        Path candidate = root.resolve("src/main/resources/db/init/schema.sql");
        if (!Files.exists(candidate)) {
            candidate = root.resolve("backend/admin-api/src/main/resources/db/init/schema.sql");
        }
        assertThat(candidate).as("建库脚本必须存在（否则本判据在测空气）").exists();
        return Files.readString(candidate);
    }

    @Test
    @DisplayName("🔴 传 null（全量口径）**不炸**：两张未结清的单都回来，已结清的不在")
    void nullScopeIsUsableAndStillFiltersSettledOrders() {
        List<ReceivableAgingRow> rows = orderMapper.selectReceivableRows(TENANT_ID, null);

        assertThat(rows).extracting(ReceivableAgingRow::getOrderNo)
                .containsExactlyInAnyOrder("SO-7376-A", "SO-7376-B");
        // 已结清（paid_at 非空）不进账龄面
        assertThat(rows).extracting(ReceivableAgingRow::getOrderNo).doesNotContain("SO-7376-PAID");
        // 余额字段由 SQL 算出（两张单都没退款/核销 ⇒ 余额 = 货值）
        assertThat(rows).allSatisfy(row -> assertThat(row.getRemaining()).isPositive());
    }

    @Test
    @DisplayName("传制单人 ⇒ 只回他创建的那张单（范围真的被 SQL 用上了）")
    void scopeOwnerNarrowsToThatOwner() {
        List<ReceivableAgingRow> rows = orderMapper.selectReceivableRows(TENANT_ID, "u-a");

        assertThat(rows).extracting(ReceivableAgingRow::getOrderNo).containsExactly("SO-7376-A");
    }

    @Test
    @DisplayName("传一个没有单的制单人 ⇒ 空集（不是全量 —— 参数被吞掉时这里会红）")
    void unknownOwnerYieldsEmptyNotEverything() {
        assertThat(orderMapper.selectReceivableRows(TENANT_ID, "u-nobody")).isEmpty();
    }
}
