// case_ids: WH-010
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.MybatisSqlSessionFactoryBuilder;
import com.migao.admin.entity.WarehouseLocation;
import com.migao.admin.mapper.FinishedGoodsStockMapper;
import com.migao.admin.mapper.WarehouseLocationMapper;
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
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.Statement;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 🔴 V198 真库判据（issue #7791）：水位选仓 + {@code FOR UPDATE} 并发容量闸门。
 *
 * <h2>本类要拦住的缺陷</h2>
 * <ul>
 *   <li><b>SQL 只在 mock 面看着对</b>：{@code FOR UPDATE} 与相关子查询 / ORDER BY 组合在真 PG 上
 *       可能直接报错；mock 单测完全看不见；</li>
 *   <li><b>等锁期间被填满</b>：两个过账事务同时看到「空仓」，先拿到锁的填满后，后一个若不复核件数
 *       就会把同一仓塞过容量（V198 去掉 bin 唯一索引后，DB 不再兜底）；</li>
 *   <li><b>「全满才新建」</b>：后一个事务必须在复核后顺延建 A-02，而不是返回已满的 A-01。</li>
 * </ul>
 *
 * <h2>红证形态</h2>
 * 把 {@code WarehouseLocationService.nextFreeBin} 里的「拿到行锁后复核件数」删掉 ⇒
 * {@link #secondAllocationWaitsForLockThenCreatesNextBin()} 仍会拿到 A-02（因为查询谓词可能重判），
 * 但把 {@code selectBestBinForAllocation} 的 {@code FOR UPDATE OF l} 去掉 ⇒ 第二个事务
 * **不会阻塞**，{@code isDone()} 立即为 true ⇒ 本判据红。
 *
 * <h2>环境</h2>
 * 一次性 PG（{@link PgCluster}）；缺二进制且未设 {@code MIGAO_REQUIRE_REALDB=1} ⇒ 显式 skip。
 */
@DisplayName("#7791 真库：水位分配 + FOR UPDATE 容量闸门")
class WarehouseLocationAllocationRealDbTest {

    private static final long TENANT = 7791L;
    private static final String TENANT_CODE = "acc-7791";
    /** 并发用独立租户：bin_code 是**租户内**唯一，两个成品仓同租户会共用号段。 */
    private static final long RACE_TENANT = 7792L;
    private static final String RACE_TENANT_CODE = "acc-7792";

    private static PgCluster cluster;
    private static DataSource dataSource;
    private static SqlSessionFactory factory;
    private static long mainWarehouseId;
    private static long raceWarehouseId;

    @BeforeAll
    static void startRealPostgres() throws Exception {
        cluster = PgCluster.startOrAbort();
        dataSource = cluster.dataSource();
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute(Files.readString(Path.of("src/main/resources/db/init/schema.sql")));
            st.execute("INSERT INTO tenants (id, name, code) OVERRIDING SYSTEM VALUE VALUES ("
                    + TENANT + ", '" + TENANT_CODE + "', '" + TENANT_CODE + "'), ("
                    + RACE_TENANT + ", '" + RACE_TENANT_CODE + "', '" + RACE_TENANT_CODE + "')");
            try (ResultSet rs = st.executeQuery("INSERT INTO warehouses (tenant_id, code, name, warehouse_type) "
                    + "VALUES (" + TENANT + ", 'CP-7791', '成品仓', 'finished') RETURNING id")) {
                assertThat(rs.next()).isTrue();
                mainWarehouseId = rs.getLong(1);
            }
            try (ResultSet rs = st.executeQuery("INSERT INTO warehouses (tenant_id, code, name, warehouse_type) "
                    + "VALUES (" + RACE_TENANT + ", 'RACE-7791', '并发成品仓', 'finished') RETURNING id")) {
                assertThat(rs.next()).isTrue();
                raceWarehouseId = rs.getLong(1);
            }
            st.execute("INSERT INTO warehouse_locations (tenant_id, warehouse_id, bin_code, capacity) VALUES ("
                    + TENANT + ", " + mainWarehouseId + ", 'A-01', 2), ("
                    + TENANT + ", " + mainWarehouseId + ", 'A-02', 2)");
            st.execute("INSERT INTO warehouse_locations (tenant_id, warehouse_id, bin_code, capacity) VALUES ("
                    + RACE_TENANT + ", " + raceWarehouseId + ", 'A-01', 1)");
            st.execute("INSERT INTO finished_goods_stock "
                    + "(tenant_id, warehouse_id, location_id, bin_code, order_id, order_item_id, quantity) "
                    + "SELECT " + TENANT + ", " + mainWarehouseId + ", id, 'A-01', 'ORD-7791', 'ITEM-7791', 1 "
                    + "FROM warehouse_locations WHERE tenant_id = " + TENANT
                    + " AND warehouse_id = " + mainWarehouseId + " AND bin_code = 'A-01'");

            MybatisConfiguration configuration = new MybatisConfiguration();
            configuration.setMapUnderscoreToCamelCase(true);
            configuration.setEnvironment(new Environment("realdb", new JdbcTransactionFactory(), dataSource));
            configuration.addMapper(WarehouseLocationMapper.class);
            configuration.addMapper(FinishedGoodsStockMapper.class);
            factory = new MybatisSqlSessionFactoryBuilder().build(configuration);
        }
    }

    @AfterAll
    static void stopRealPostgres() {
        if (cluster != null) {
            cluster.stop();
        }
    }

    @Test
    @DisplayName("水位最低的未满仓优先：A-01 已 1/2、A-02 空 ⇒ 选 A-02（不是最小号 A-01）")
    void waterLevelPicksLeastLoadedBin() {
        try (SqlSession session = factory.openSession(false)) {
            WarehouseLocation best = session.getMapper(WarehouseLocationMapper.class)
                    .selectBestBinForAllocation(TENANT, mainWarehouseId);
            assertThat(best).isNotNull();
            assertThat(best.getBinCode()).isEqualTo("A-02");
            assertThat(best.getCapacity()).isEqualTo(2);
            session.rollback();
        }
    }

    @Test
    @DisplayName("🔴 第二个事务在 FOR UPDATE 上等待；第一个填满 A-01 后，第二个复核并新建 A-02")
    void secondAllocationWaitsForLockThenCreatesNextBin() throws Exception {
        SqlSession first = factory.openSession(false);
        SqlSession second = factory.openSession(false);
        ExecutorService pool = Executors.newSingleThreadExecutor();
        try {
            WarehouseLocationMapper firstMapper = first.getMapper(WarehouseLocationMapper.class);
            WarehouseLocation locked = firstMapper.selectBestBinForAllocation(RACE_TENANT, raceWarehouseId);
            assertThat(locked).isNotNull();
            assertThat(locked.getBinCode()).isEqualTo("A-01");
            try (PreparedStatement insert = first.getConnection().prepareStatement(
                    "INSERT INTO finished_goods_stock "
                            + "(tenant_id, warehouse_id, location_id, bin_code, order_id, order_item_id, quantity) "
                            + "VALUES (?, ?, ?, 'A-01', 'ORD-RACE', 'ITEM-RACE', 1)")) {
                insert.setLong(1, RACE_TENANT);
                insert.setLong(2, raceWarehouseId);
                insert.setLong(3, locked.getId());
                assertThat(insert.executeUpdate()).isEqualTo(1);
            }

            CountDownLatch started = new CountDownLatch(1);
            Future<WarehouseLocation> allocation = pool.submit(() -> {
                WarehouseLocationMapper mapper = second.getMapper(WarehouseLocationMapper.class);
                FinishedGoodsStockMapper stock = second.getMapper(FinishedGoodsStockMapper.class);
                WarehouseLocationService service = new WarehouseLocationService(mapper, stock, null);
                started.countDown();
                return service.nextFreeBin(RACE_TENANT, raceWarehouseId);
            });
            assertThat(started.await(5, TimeUnit.SECONDS)).isTrue();
            Thread.sleep(500);
            assertThat(allocation.isDone())
                    .as("第二个分配事务必须在 FOR UPDATE 行锁上等待（isDone=true 说明锁没生效）")
                    .isFalse();

            // 原始 JDBC insert 不会把 MyBatis 的 dirty 标记置上 ⇒ first.commit() 会是 no-op；
            // 必须直接提交底层连接（否则 T2 永远等 T1 的 transactionid 锁）。
            first.getConnection().commit();
            WarehouseLocation allocated = allocation.get(10, TimeUnit.SECONDS);
            assertThat(allocated.getBinCode())
                    .as("A-01 容量 1 已被第一个事务填满 ⇒ 第二个事务必须顺延 A-02")
                    .isEqualTo("A-02");
            second.commit();

            try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement();
                 ResultSet rs = st.executeQuery(
                         "SELECT count(*) AS n FROM finished_goods_stock "
                                 + "WHERE tenant_id = " + RACE_TENANT + " AND warehouse_id = " + raceWarehouseId
                                 + " AND status = 'in_stock' AND deleted = 0 AND bin_code = 'A-01'")) {
                assertThat(rs.next()).isTrue();
                assertThat(rs.getInt("n")).isEqualTo(1);
            }
        } finally {
            pool.shutdownNow();
            first.close();
            second.close();
        }
    }
}
