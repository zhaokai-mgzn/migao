// case_ids: PG-077
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.MybatisSqlSessionFactoryBuilder;
import com.baomidou.mybatisplus.extension.plugins.MybatisPlusInterceptor;
import com.baomidou.mybatisplus.extension.plugins.inner.TenantLineInnerInterceptor;
import com.baomidou.mybatisplus.extension.plugins.handler.TenantLineHandler;
import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.QualityCheck;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.QualityCheckMapper;
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

import javax.sql.DataSource;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Connection;
import java.sql.ResultSet;
import java.sql.Statement;
import java.time.OffsetDateTime;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 质检记录的真库×真映射守卫（issue #5652 第一刀）。
 *
 * <p>对应用例：<b>PG-077</b>（.github/cases/processing-order.yml）。</p>
 *
 * <h2>为什么必须是「真库 + 真 SQL」</h2>
 * mock 只能证明「调了哪个方法」；本表的要害是「**那几个列真的落进了 PG，且值逐字正确**」
 * —— 列名拼错 / {@code inspection_result} 写错列 / 实体与 V157 的列集不一致，在 mock 面
 * 结构上不可见（本仓实证：V74 的 {@code orders.processing_info} 因迁移报错被静默跳过，
 * 部署照旧 success）。schema 取自 {@code backend/admin-api/src/main/resources/db/init/schema.sql}
 * （bootstrap 终态，含 V157）—— **不手抄列清单**（手抄会漂移）。
 *
 * <h2>判据不许恒真</h2>
 * ① 把 {@link QualityCheck} 的 {@code inspectionResult} 改名 / 把 V157 的列改名 ⇒
 * {@link #rowLandsInTheRealTableWithEveryFieldVerbatim()} 当场红（列不存在 / 值为 NULL）；
 * ② 摘掉租户拦截器（或把本表加进 {@code IGNORE_TENANT_TABLES}）⇒
 * {@link #tenantPredicateComesFromTheInterceptor()} 当场红（另一个租户读得到别人的质检记录）。
 *
 * <h2>环境（与既有真库族同款）</h2>
 * 缺 PG 二进制 ⇒ {@link PgCluster#startOrAbort()}：CI（{@code MIGAO_REQUIRE_REALDB=1}）⇒ 判红；
 * 本机未设该标记 ⇒ 显式 skip（「没跑」长得像「没跑」，**不是**通过）。
 */
@DisplayName("真库守卫：质检记录（成品帘级）落进 quality_inspections 且租户谓词由拦截器注入")
class QualityCheckMapperTest {

    private static final Long TENANT_ID = 5652L;
    private static final Long OTHER_TENANT_ID = 5653L;
    private static final String ORDER_ID = "acc-5652-order";
    private static final String ITEM_ID = "acc-5652-item";
    private static final String PO_ID = "acc-5652-po";
    private static final String ROW_ID = "acc-5652-qi-1";
    private static final OffsetDateTime AT = OffsetDateTime.parse("2026-10-16T09:15:00+08:00");

    private static PgCluster cluster;
    private static DataSource dataSource;
    private static SqlSession session;
    private static long tenantId;

    @BeforeAll
    static void startRealPostgresAndFixtures() throws Exception {
        cluster = PgCluster.startOrAbort();
        dataSource = cluster.dataSource();
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute(schemaSql());
            try (ResultSet rs = st.executeQuery(
                    "INSERT INTO tenants (id, name, code) OVERRIDING SYSTEM VALUE VALUES (" + TENANT_ID
                            + ", 'acc-5652', 'acc-5652') RETURNING id")) {
                assertThat(rs.next()).as("租户夹具必须落库").isTrue();
                tenantId = rs.getLong(1);
            }
            st.execute("INSERT INTO orders (id, tenant_id, order_no, status) VALUES ('" + ORDER_ID + "', "
                    + tenantId + ", 'ORD-acc-5652', 'confirmed')");
            st.execute("INSERT INTO order_items (id, tenant_id, order_id, product_name, quantity, deleted)"
                    + " VALUES ('" + ITEM_ID + "', " + tenantId + ", '" + ORDER_ID
                    + "', '布艺遮光帘A 米白', 1, 0)");
            st.execute("INSERT INTO processing_orders (id, tenant_id, order_id, processing_order_no, status)"
                    + " VALUES ('" + PO_ID + "', " + tenantId + ", '" + ORDER_ID + "', 'JG-20261016-5652',"
                    + " 'issued')");
        }
        MybatisConfiguration configuration = new MybatisConfiguration();
        configuration.setMapUnderscoreToCamelCase(true);
        configuration.setEnvironment(new Environment("acc-5652", new JdbcTransactionFactory(), dataSource));
        // 多租户拦截器**必须在场**：租户谓词是拦截器注入的（本表不在 IGNORE_TENANT_TABLES 里）
        MybatisPlusInterceptor tenantLine = new MybatisPlusInterceptor();
        tenantLine.addInnerInterceptor(new TenantLineInnerInterceptor(new TenantLineHandler() {
            @Override
            public Expression getTenantId() {
                return new LongValue(TenantContext.getTenantId());
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
        configuration.addMapper(QualityCheckMapper.class);
        configuration.addMapper(OrderItemMapper.class);
        SqlSessionFactory factory = new MybatisSqlSessionFactoryBuilder().build(configuration);
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

    @Test
    @DisplayName("🔴 一行质检记录真落库，且**逐列**等于「谁/何时/哪件成品帘/判了什么/为什么」")
    void rowLandsInTheRealTableWithEveryFieldVerbatim() throws Exception {
        QualityCheckMapper mapper = session.getMapper(QualityCheckMapper.class);
        QualityCheck row = QualityCheck.builder()
                .id(ROW_ID)
                .tenantId(tenantId)
                .processingOrderId(PO_ID)
                .orderItemId(ITEM_ID)
                .positionName("布艺遮光帘A 米白")
                .inspectorId("user-inspector-5652")
                .inspectorName("质检员小李")
                .inspectionResult("scrap")
                .reason("布面污渍无法清洗")
                .inspectedAt(AT)
                .deleted(0)
                .build();
        assertThat(mapper.insert(row)).as("插入必须影响 1 行").isEqualTo(1);

        // 真 SQL 读回（不经 mapper，直接 SELECT —— 证明列名与 V157 一致）
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery("SELECT tenant_id, processing_order_id, order_item_id,"
                     + " position_name, inspector_id, inspector_name, inspection_result, reason,"
                     + " inspected_at, deleted FROM quality_inspections WHERE id = '" + ROW_ID + "'")) {
            assertThat(rs.next()).as("这一行必须在真库里").isTrue();
            assertThat(rs.getLong("tenant_id")).isEqualTo(tenantId);
            assertThat(rs.getString("processing_order_id")).isEqualTo(PO_ID);
            assertThat(rs.getString("order_item_id")).as("颗粒度 = 一件成品帘").isEqualTo(ITEM_ID);
            assertThat(rs.getString("position_name")).isEqualTo("布艺遮光帘A 米白");
            assertThat(rs.getString("inspector_id")).isEqualTo("user-inspector-5652");
            assertThat(rs.getString("inspector_name")).isEqualTo("质检员小李");
            assertThat(rs.getString("inspection_result")).isEqualTo("scrap");
            assertThat(rs.getString("reason")).as("判定 ≠ 合格 ⇒ 原因逐字落库").isEqualTo("布面污渍无法清洗");
            assertThat(rs.getObject("inspected_at", OffsetDateTime.class).toInstant())
                    .isEqualTo(AT.toInstant());
            assertThat(rs.getInt("deleted")).isZero();
        }

        // mapper 读面同源（BaseMapper.selectById 经租户拦截器）
        QualityCheck back = mapper.selectById(ROW_ID);
        assertThat(back).isNotNull();
        assertThat(back.getInspectionResult()).isEqualTo("scrap");
        assertThat(back.getOrderItemId()).isEqualTo(ITEM_ID);
    }

    @Test
    @DisplayName("🔴 租户谓词来自拦截器：换一个租户上下文 ⇒ 读不到别人的质检记录")
    void tenantPredicateComesFromTheInterceptor() {
        QualityCheckMapper mapper = session.getMapper(QualityCheckMapper.class);
        TenantContext.setTenantId(OTHER_TENANT_ID);
        try {
            assertThat(mapper.selectById(ROW_ID))
                    .as("跨租户读必须为空 —— 谓词由 TenantLineInnerInterceptor 注入，摘掉它本条必红")
                    .isNull();
        } finally {
            TenantContext.setTenantId(tenantId);
        }
        assertThat(mapper.selectById(ROW_ID)).as("对照：本租户读得到（不是「表空了」）").isNotNull();
    }

    /** 建库脚本取自仓内唯一一份 bootstrap 终态（**不手抄列清单**）。 */
    private static String schemaSql() throws IOException {
        return Files.readString(
                Path.of("src", "main", "resources", "db", "init", "schema.sql"),
                StandardCharsets.UTF_8);
    }
}
