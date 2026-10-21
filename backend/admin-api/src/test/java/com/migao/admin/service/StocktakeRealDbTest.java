// case_ids: STK-001
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.MybatisSqlSessionFactoryBuilder;
import com.baomidou.mybatisplus.extension.plugins.MybatisPlusInterceptor;
import com.baomidou.mybatisplus.extension.plugins.handler.TenantLineHandler;
import com.baomidou.mybatisplus.extension.plugins.inner.TenantLineInnerInterceptor;
import com.migao.admin.entity.StockBatch;
import com.migao.admin.mapper.ApprovalMapper;
import com.migao.admin.mapper.StockBatchMapper;
import com.migao.admin.mapper.StocktakeItemMapper;
import com.migao.admin.mapper.StocktakeMapper;
import com.migao.admin.mapper.WarehouseMapper;
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
import java.math.BigDecimal;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.sql.Connection;
import java.sql.Statement;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 盘点的**真库**判据（issue #7373 段 2）。
 *
 * <h3>为什么必须真库</h3>
 * <p>上一轮「采购单加载失败」的教训：单测把 Mapper 全 mock 掉，**实体列 ↔ 建库列**的不一致一条都测不出来
 * （云上 500 了两天）。盘点这条链读写的列更多（账面快照 / 实盘 / 差异 / 成本快照），更该在真库上跑一遍。</p>
 *
 * <h3>本判据钉什么</h3>
 * <ol>
 *   <li>出任务：账面数取**当刻**批次量，逐批次落明细；</li>
 *   <li>录实盘 + 完成（无差异）：状态转 completed 且库存不变；</li>
 *   <li>⚠️ 有差异的完成需要审批 —— 那条路径由单测（`StocktakeServiceTest`）覆盖，
 *       本判据只验「无差异直接完成」这条不依赖审批的路径，避免真库判据依赖审批表夹具。</li>
 * </ol>
 */
@DisplayName("真库：盘点出任务/录实盘/完成（无差异）在终态建库脚本上跑通")
class StocktakeRealDbTest {

    private static final Long TENANT_ID = 73731L;

    private static PgCluster cluster;
    private static SqlSession session;
    private static StocktakeService service;

    @BeforeAll
    static void startRealPostgresAndFixtures() throws Exception {
        cluster = PgCluster.startOrAbort();
        DataSource dataSource = cluster.dataSource();
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute(schemaSql());
            st.execute("INSERT INTO tenants (id, name, code) OVERRIDING SYSTEM VALUE VALUES ("
                    + TENANT_ID + ", 'acc-7373', 'acc-7373')");
            st.execute("INSERT INTO warehouses (id, tenant_id, code, name, warehouse_type, is_default, status)"
                    + " OVERRIDING SYSTEM VALUE VALUES (1, " + TENANT_ID + ", 'WH-A', '门店仓', 'store', TRUE, 'active')");
            // 批次要挂在一个商品上（`products` 是空库，先造一个最小商品）
            st.execute("INSERT INTO products (id, tenant_id, name, category_id, status)"
                    + " VALUES ('P-7373', " + TENANT_ID + ", '遮光布', NULL, 'active')");
            st.execute("INSERT INTO stock_batches (tenant_id, batch_no, product_id, quantity, unit_cost,"
                    + " warehouse, dye_lot) VALUES (" + TENANT_ID + ", 'PC-7373-1', 'P-7373', 100.0, 12.3456,"
                    + " 'WH-A', 'LOT-1')");
        }

        MybatisConfiguration configuration = new MybatisConfiguration();
        configuration.setMapUnderscoreToCamelCase(true);
        configuration.setEnvironment(new Environment("acc-7373-st", new JdbcTransactionFactory(), dataSource));
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
        for (Class<?> mapper : List.of(StocktakeMapper.class, StocktakeItemMapper.class,
                StockBatchMapper.class, WarehouseMapper.class, ApprovalMapper.class)) {
            configuration.addMapper(mapper);
        }
        SqlSessionFactory factory = new MybatisSqlSessionFactoryBuilder().build(configuration);
        session = factory.openSession(true);

        ApprovalService approvalService = new ApprovalService(session.getMapper(ApprovalMapper.class));
        WarehouseService warehouseService = new WarehouseService(session.getMapper(WarehouseMapper.class));
        service = new StocktakeService(session.getMapper(StocktakeMapper.class),
                session.getMapper(StocktakeItemMapper.class), session.getMapper(StockBatchMapper.class),
                warehouseService, approvalService, new com.migao.admin.time.BusinessClock());
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

    @Test
    @DisplayName("🔴 全链路（无差异）：出任务 → 录实盘 → 完成，库存不变、账面快照留档")
    void fullFlowWithoutDiff() {
        var opened = service.open(1L, "月末盘点", null);
        assertThat(opened.getItems()).as("该仓有货的批次要进盘点范围").hasSize(1);
        assertThat(opened.getItems().get(0).getBookQty()).isEqualByComparingTo("100");

        Long batchId = opened.getItems().get(0).getBatchId();
        service.record(opened.getId(), java.util.Map.of(batchId, new BigDecimal("100")));
        var completed = service.complete(opened.getId());

        assertThat(completed.getStatus()).isEqualTo("completed");
        assertThat(completed.getItems().get(0).getDiffQty()).isEqualByComparingTo("0");

        StockBatch batch = session.getMapper(StockBatchMapper.class).selectById(batchId);
        assertThat(batch.getQuantity()).as("账实相符 ⇒ 数量不变").isEqualByComparingTo("100");
        assertThat(batch.getUnitCost()).as("成本快照不动").isEqualByComparingTo("12.3456");
    }

    /** 终态建库脚本（不手抄列清单）。 */
    private static String schemaSql() throws Exception {
        Path root = Paths.get(System.getProperty("user.dir")).toAbsolutePath();
        Path candidate = root.resolve("src/main/resources/db/init/schema.sql");
        if (!Files.exists(candidate)) {
            candidate = root.resolve("backend/admin-api/src/main/resources/db/init/schema.sql");
        }
        assertThat(candidate).as("建库脚本必须存在（否则本判据在测空气）").exists();
        return Files.readString(candidate);
    }
}
