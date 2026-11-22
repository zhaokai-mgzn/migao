// case_ids: PG-001, PG-002
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.MybatisSqlSessionFactoryBuilder;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.mapper.ProcessingOrderMapper;
import org.apache.ibatis.mapping.Environment;
import org.apache.ibatis.session.SqlSession;
import org.apache.ibatis.session.SqlSessionFactory;
import org.apache.ibatis.transaction.jdbc.JdbcTransactionFactory;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import javax.sql.DataSource;
import java.sql.Connection;
import java.sql.ResultSet;
import java.sql.Statement;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;

/**
 * 真库判据（P0-5）：加工单号「取号 + 占号」是不是<b>一条语句</b> —— 撞号会不会静默漏单。
 *
 * <h2>被核验的主张</h2>
 * 改前：进程内 {@code AtomicInteger}（随机起点）先发号、之后才 {@code insert(..)} ⇒ 撞
 * {@code uk_processing_orders_no} 抛 {@code DuplicateKeyException}，被 {@code commit} 一律翻成
 * 「加工单已生成（并发操作）」—— <b>单子没落库却报成功</b>。改后：{@code INSERT … ON CONFLICT DO NOTHING}
 * 一条语句占号（受影响行数 1/0），0 行时回查活跃单再决定「换号重试」还是「真的已生成」。
 *
 * <h2>为什么必须有真库判据（单测替不了的部分）</h2>
 * ① {@code ON CONFLICT} 的语义、② {@code CAST(#{itemsSnapshotJson} AS jsonb)} 与手写列清单、
 * ③ 无目标 {@code DO NOTHING} 会不会连 {@code uk_processing_orders_active}（<b>部分</b>唯一索引）
 * 也一并变成 0 行 —— 这三件事只有 PG 说了算；mock 只能测「调用了几次」。
 *
 * <p>⚠️ 本文件的 DDL 是 {@code db/init/schema.sql} 里 {@code processing_orders} 的**等价子集**
 * （同列、同类型、同两条唯一索引，去掉对 {@code tenants} / {@code orders} 的外键）：
 * 判据只需要这张表；外键与本缺陷无关，带着它就得把整张 schema 拖进来。</p>
 */
class ProcessingOrderNoConflictRealDbTest {

    private static final long TENANT_ID = 91051L;
    private static final long OTHER_TENANT_ID = 91052L;

    private static PgCluster cluster;
    private static SqlSessionFactory factory;

    @BeforeAll
    static void startRealPostgresAndFixtures() throws Exception {
        cluster = PgCluster.startOrAbort();
        DataSource dataSource = cluster.dataSource();
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute("""
                    CREATE TABLE processing_orders (
                        id VARCHAR(64) PRIMARY KEY,
                        tenant_id BIGINT NOT NULL,
                        order_id VARCHAR(36) NOT NULL,
                        processing_order_no VARCHAR(32) NOT NULL,
                        processor VARCHAR(128),
                        processor_supplier_id VARCHAR(64),
                        expected_delivery_date DATE,
                        status VARCHAR(32) NOT NULL DEFAULT 'generated',
                        items_snapshot JSONB NOT NULL DEFAULT '[]',
                        remark TEXT,
                        template_version INT DEFAULT 1,
                        generated_by VARCHAR(64),
                        generated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                        print_count INT DEFAULT 0,
                        qr_token VARCHAR(64),
                        short_code CHAR(8),
                        route_key VARCHAR(32),
                        route_requested_key VARCHAR(32),
                        route_source VARCHAR(16),
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                        deleted INT DEFAULT 0,
                        order_kind VARCHAR(16) NOT NULL DEFAULT 'processing'
                    )
                    """);
            // 与 schema.sql 逐字同义：一个是**全局**单号唯一（无 deleted 谓词），一个是**活跃单**部分唯一
            st.execute("CREATE UNIQUE INDEX uk_processing_orders_no ON processing_orders (processing_order_no)");
            st.execute("CREATE UNIQUE INDEX uk_processing_orders_active ON processing_orders (order_id) "
                    + "WHERE deleted = 0 AND status IN ('generated', 'issued', 'in_processing', 'completed')");
        }
        MybatisConfiguration configuration = new MybatisConfiguration();
        configuration.setMapUnderscoreToCamelCase(true);
        configuration.setEnvironment(new Environment("p0-5", new JdbcTransactionFactory(), dataSource));
        configuration.addMapper(ProcessingOrderMapper.class);
        factory = new MybatisSqlSessionFactoryBuilder().build(configuration);
    }

    @AfterAll
    static void stopRealPostgres() {
        if (cluster != null) {
            cluster.stop();
        }
    }

    @Test
    @DisplayName("P0-5 真库①：同号第二次插入返回 0 行（不抛异常），换号后 1 行 —— 单子真的在库里")
    void duplicateNoBecomesZeroRowsThenFreshNoLands() throws Exception {
        String taken = "JG-20990101-0001";
        String fresh = "JG-20990101-0002";
        try (SqlSession session = factory.openSession(true)) {
            ProcessingOrderMapper mapper = session.getMapper(ProcessingOrderMapper.class);

            assertThat(mapper.insertIgnoreProcessingNoConflict(
                    po("p05-po-a", "p05-order-0001", taken, List.of(Map.of("k", 1))),
                    "[{\"k\":1}]"))
                    .as("第一次占号：号归我").isEqualTo(1);
            assertThat(mapper.insertIgnoreProcessingNoConflict(
                    po("p05-po-b", "p05-order-0002", taken, List.of()),
                    "[]"))
                    .as("同号第二次：必须**返回 0 行**（不是 DuplicateKeyException —— 否则同一事务已被标坏，没法换号重试）")
                    .isZero();
            assertThat(mapper.insertIgnoreProcessingNoConflict(
                    po("p05-po-c", "p05-order-0002", fresh, List.of(Map.of("k", 2))),
                    "[{\"k\":2}]"))
                    .as("换号后落库成功").isEqualTo(1);
        }

        // 真值从库里读回（不信返回值）：两行、两个不同单号、JSONB 快照可用
        try (SqlSession session = factory.openSession()) {
            ProcessingOrderMapper mapper = session.getMapper(ProcessingOrderMapper.class);
            assertThat(mapper.selectMaxProcessingOrderNo("JG-20990101-"))
                    .as("取号起点 = 库内当日最大号（跨租户全局）").isEqualTo(fresh);
        }
        try (Connection conn = cluster.dataSource().getConnection(); Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery("SELECT count(*), count(DISTINCT processing_order_no) "
                     + "FROM processing_orders WHERE processing_order_no LIKE 'JG-20990101-%'")) {
            rs.next();
            assertThat(rs.getLong(1)).as("库里恰 2 行").isEqualTo(2);
            assertThat(rs.getLong(2)).as("两个单号互不相同").isEqualTo(2);
        }
        try (Connection conn = cluster.dataSource().getConnection(); Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery("SELECT items_snapshot->0->>'k' FROM processing_orders "
                     + "WHERE id = 'p05-po-c'")) {
            rs.next();
            assertThat(rs.getString(1)).as("items_snapshot 经 CAST(… AS jsonb) 落的是真 JSONB").isEqualTo("2");
        }
    }

    @Test
    @DisplayName("P0-5 真库②：活跃单唯一键冲突也变成 0 行（不是异常）⇒ 事务仍可回查真诊断")
    void activeOrderConflictIsAlsoZeroRowsNotException() throws Exception {
        String orderId = "p05-order-active";
        try (SqlSession session = factory.openSession(true)) {
            ProcessingOrderMapper mapper = session.getMapper(ProcessingOrderMapper.class);
            assertThat(mapper.insertIgnoreProcessingNoConflict(
                    po("p05-po-active-1", orderId, "JG-20990102-0001", List.of()), "[]")).isEqualTo(1);

            assertThatCode(() -> mapper.insertIgnoreProcessingNoConflict(
                    po("p05-po-active-2", orderId, "JG-20990102-0002", List.of()), "[]"))
                    .as("撞 uk_processing_orders_active 时**不得抛异常**（无目标 DO NOTHING 吞掉全部唯一冲突）")
                    .doesNotThrowAnyException();
            assertThat(mapper.insertIgnoreProcessingNoConflict(
                    po("p05-po-active-2", orderId, "JG-20990102-0002", List.of()), "[]"))
                    .as("同一订单第二张活跃单 ⇒ 0 行（调用方据此回查活跃单、报「确实已生成」）")
                    .isZero();
        }
        try (Connection conn = cluster.dataSource().getConnection(); Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery("SELECT count(*) FROM processing_orders WHERE order_id = '"
                     + orderId + "' AND deleted = 0")) {
            rs.next();
            assertThat(rs.getLong(1)).as("活跃单仍恰 1 张（没有半张单）").isEqualTo(1);
        }
    }

    @Test
    @DisplayName("P0-5 真库③：取号起点跨租户、且**算上软删行**（唯一索引没有 deleted 谓词）")
    void maxNoSpansTenantsAndIncludesSoftDeletedRows() throws Exception {
        try (SqlSession session = factory.openSession(true)) {
            ProcessingOrderMapper mapper = session.getMapper(ProcessingOrderMapper.class);
            ProcessingOrder mine = po("p05-po-t1", "p05-order-t1", "JG-20990103-0005", List.of());
            mine.setTenantId(TENANT_ID);
            mapper.insertIgnoreProcessingNoConflict(mine, "[]");
            ProcessingOrder deleted = po("p05-po-t2", "p05-order-t2", "JG-20990103-0009", List.of());
            deleted.setTenantId(OTHER_TENANT_ID);
            deleted.setDeleted(1);
            mapper.insertIgnoreProcessingNoConflict(deleted, "[]");
        }
        try (SqlSession session = factory.openSession()) {
            ProcessingOrderMapper mapper = session.getMapper(ProcessingOrderMapper.class);
            assertThat(mapper.selectMaxProcessingOrderNo("JG-20990103-"))
                    .as("别的租户、已软删的号仍然占着唯一索引 ⇒ 必须计入最大号（否则反复生成已废号）")
                    .isEqualTo("JG-20990103-0009");
        }
    }

    /** 最小可插入行（只填建单会写的列；其余列吃 DB 默认值）。 */
    private static ProcessingOrder po(String id, String orderId, String no, Object snapshot) {
        return ProcessingOrder.builder()
                .id(id)
                .tenantId(TENANT_ID)
                .orderId(orderId)
                .processingOrderNo(no)
                .status("generated")
                .itemsSnapshot(snapshot)
                .templateVersion(1)
                .generatedBy("p0-5")
                .printCount(0)
                .build();
    }
}
