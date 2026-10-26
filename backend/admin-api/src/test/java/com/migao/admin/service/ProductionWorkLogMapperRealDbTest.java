// case_ids: PG-018, PG-046
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.MybatisSqlSessionFactoryBuilder;
import com.migao.admin.mapper.ProductionWorkLogMapper;
import org.apache.ibatis.mapping.Environment;
import org.apache.ibatis.session.SqlSession;
import org.apache.ibatis.session.SqlSessionFactory;
import org.apache.ibatis.transaction.jdbc.JdbcTransactionFactory;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import javax.sql.DataSource;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.sql.Connection;
import java.sql.Statement;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 真库判据（issue #7874）：扫水洗唛的「打包工序」判据在 **PostgreSQL** 上必须真的能跑。
 *
 * <h2>为什么必须真库（H2 结构上看不见）</h2>
 * 生产连接串带 {@code stringtype=unspecified}（{@code application.yml}）⇒ 字符串参数以
 * <b>UNSPECIFIED</b> 类型下发；而 PostgreSQL 的 {@code CONCAT} 是 {@code VARIADIC "any"}
 * ⇒ 解析期**无法推断参数类型**，直接报
 * {@code ERROR: could not determine data type of parameter $4}。
 * H2 会替参数推断类型 ⇒ 同一条 SQL 在单测里**永远是绿的**，于是 2026-10-26 生产上
 * 「扫码即报工」整条 500（工人端红字「服务器内部错误」），而 PR 的 CI 全绿。
 *
 * <h2>判据</h2>
 * <ol>
 *   <li>三参重载（关键词 = {@code 打包}）在真库上能跑通，且计数**按人**分流
 *       （打包工 = 1、只做过「韩褶」的缝纫工 = 0）；</li>
 *   <li>关键词参数是**承重**的（换成不在工序名里的词 ⇒ 0，不是恒 1）——
 *       防「把关键词写成字面量后测不出来」的退化。</li>
 * </ol>
 *
 * <h2>环境</h2>
 * 一次性真 PG 集群（{@link PgCluster}，与既有真库判据共用同一装配；连接串同样带
 * {@code stringtype=unspecified}），schema 取 {@code db/init/schema.sql} 终态
 * （**不手抄列清单**）。缺 PG 二进制时：CI（{@code MIGAO_REQUIRE_REALDB=1}）判红、
 * 本机未设该标记 ⇒ 显式 skip（「没跑」长得像「没跑」）。
 */
@DisplayName("#7874 真库：扫水洗唛的打包工序判据（CONCAT 参数类型推断）")
class ProductionWorkLogMapperRealDbTest {

    private static final Long TENANT_ID = 7874L;
    private static final String PROCESSING_ORDER_ID = "PO-7874-A";
    private static final String PACKER = "W-7874-PACK";
    private static final String SEWER = "W-7874-SEW";

    private static PgCluster cluster;
    private static SqlSession session;
    private static ProductionWorkLogMapper mapper;

    @BeforeAll
    static void startRealPostgresAndFixtures() throws Exception {
        cluster = PgCluster.startOrAbort();
        DataSource dataSource = cluster.dataSource();
        try (Connection conn = dataSource.getConnection()) {
            try (Statement st = conn.createStatement()) {
                st.execute(schemaSql());
                // 本判据只测**这条 SQL 的参数类型推断**，与既有行的外键无关：在一次性库里摘掉两条 FK，
                // 否则夹具要造 tenant → order → processing_order 三层（噪音盖过判据本身）。
                st.execute("ALTER TABLE production_work_logs "
                        + "DROP CONSTRAINT IF EXISTS production_work_logs_tenant_id_fkey");
                st.execute("ALTER TABLE production_work_logs "
                        + "DROP CONSTRAINT IF EXISTS production_work_logs_processing_order_id_fkey");
                // ① 打包工在本单做过「打包」；② 缝纫工在本单只做过「韩褶」；
                // ③ 打包工**在别的加工单**做过「打包」（加工单这一维必须是承重的）。
                st.execute("INSERT INTO production_work_logs (id, tenant_id, processing_order_id, "
                        + "operation_id, operation_name, worker_id, worker_name, qty, qualified_qty, work_type) VALUES ("
                        + "'WL-7874-1', " + TENANT_ID + ", '" + PROCESSING_ORDER_ID + "', 'OP-1', '打包', '"
                        + PACKER + "', '打包工', 1, 1, 'normal'),"
                        + "('WL-7874-2', " + TENANT_ID + ", '" + PROCESSING_ORDER_ID + "', 'OP-2', '韩褶', '"
                        + SEWER + "', '缝纫工', 1, 1, 'normal'),"
                        + "('WL-7874-3', " + TENANT_ID + ", 'PO-7874-OTHER', 'OP-1', '打包', '"
                        + PACKER + "', '打包工', 1, 1, 'normal')");
            }
        }
        MybatisConfiguration configuration = new MybatisConfiguration();
        configuration.setMapUnderscoreToCamelCase(true);
        configuration.setEnvironment(new Environment("pg-7874", new JdbcTransactionFactory(), dataSource));
        // 本 mapper 的方法自带 @InterceptorIgnore(tenantLine=true)（租户由参数显式给）⇒ 不装多租户拦截器，
        // 判据落在**这条 SQL 本身**上。
        configuration.addMapper(ProductionWorkLogMapper.class);
        SqlSessionFactory factory = new MybatisSqlSessionFactoryBuilder().build(configuration);
        session = factory.openSession(true);
        mapper = session.getMapper(ProductionWorkLogMapper.class);
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

    @Test
    @DisplayName("三参重载在真库跑通：打包工 = 1、非打包工 = 0（按人分流）")
    void packerCountRunsOnPostgres() {
        assertThat(mapper.countPackerLogs(TENANT_ID, PROCESSING_ORDER_ID, PACKER))
                .as("打包工在这张加工单上做过「打包」⇒ 必须数到 1（改前：解析期 PSQLException，整条 500）")
                .isEqualTo(1);
        assertThat(mapper.countPackerLogs(TENANT_ID, PROCESSING_ORDER_ID, SEWER))
                .as("缝纫工只做过「韩褶」⇒ 0（`worker_id` 这一维必须是承重的）")
                .isZero();
    }

    @Test
    @DisplayName("关键词参数是承重的：换词 ⇒ 0，回「打包」⇒ 1")
    void keywordIsLoadBearing() {
        assertThat(mapper.countPackerLogs(TENANT_ID, PROCESSING_ORDER_ID, PACKER, "裁剪"))
                .as("关键词不在工序名里 ⇒ 0（关键词写成字面量/被忽略时这条会变 1）")
                .isZero();
        assertThat(mapper.countPackerLogs(TENANT_ID, PROCESSING_ORDER_ID, PACKER, "打包"))
                .as("显式关键词「打包」⇒ 1（与三参重载同源）")
                .isEqualTo(1);
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
