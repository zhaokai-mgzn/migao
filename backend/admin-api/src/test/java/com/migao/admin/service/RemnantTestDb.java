// case_ids: PR-097, PR-098, PR-099
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.MybatisSqlSessionFactoryBuilder;
import com.baomidou.mybatisplus.extension.plugins.MybatisPlusInterceptor;
import com.baomidou.mybatisplus.extension.plugins.handler.TenantLineHandler;
import com.baomidou.mybatisplus.extension.plugins.inner.TenantLineInnerInterceptor;
import com.migao.admin.entity.FabricRemnant;
import com.migao.admin.mapper.FabricRemnantMapper;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProductSkuMapper;
import com.migao.admin.mapper.ProductionOperationMapper;
import com.migao.admin.mapper.ProductionOptionRoutingMapper;
import com.migao.admin.mapper.RemnantItemSizeMapper;
import com.migao.admin.mapper.StockBatchConsumptionMapper;
import com.migao.admin.mapper.StockBatchMapper;
import net.sf.jsqlparser.expression.Expression;
import net.sf.jsqlparser.expression.LongValue;
import org.apache.ibatis.mapping.Environment;
import org.apache.ibatis.session.LocalCacheScope;
import org.apache.ibatis.session.SqlSession;
import org.apache.ibatis.session.SqlSessionFactory;
import org.apache.ibatis.transaction.jdbc.JdbcTransactionFactory;
import org.springframework.jdbc.datasource.DriverManagerDataSource;

import javax.sql.DataSource;
import java.io.IOException;
import java.math.BigDecimal;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.sql.Connection;
import java.sql.ResultSet;
import java.sql.Statement;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 余料功能的**共用真库夹具**（V122 / issue #5146）—— 把 {@code PgCluster} 的装配收口到一处。
 *
 * <p>本仓纪律：真库判据的 PG 装配**不要复制第二份**（{@code PgCluster} 就是为此提取的共用件）。
 * 本类在那之上再收一层：余料相关的三个测试类（service / 两个 mapper）共用同一套
 * schema 与夹具，避免「第三份同源拷贝各自演化」。</p>
 *
 * <p>本类**不含任何断言**（它是夹具不是判据）：判据全在三个测试类里，各自带能单独变红的红证。</p>
 */
public final class RemnantTestDb {

    public static final Long TENANT_ID = 5147L;
    public static final Long SKU_ID = 5147L;
    public static final String PRODUCT_ID = "acc-5147-prod";
    public static final String SKU_CODE = "SKU-5147";
    public static final String DYE_LOT = "LOT-5147";

    private final PgCluster cluster;
    private final DataSource dataSource;
    private final SqlSession session;
    private final RemnantService remnantService;

    private RemnantTestDb(PgCluster cluster, DataSource dataSource, SqlSession session,
                          RemnantService remnantService) {
        this.cluster = cluster;
        this.dataSource = dataSource;
        this.session = session;
        this.remnantService = remnantService;
    }

    /** 本机没有 PG 二进制 ⇒ 返回 {@code null}（调用方 {@code Assumptions.abort} —— 没跑 ≠ 通过）。 */
    public static RemnantTestDb start() throws Exception {
        PgCluster cluster = PgCluster.start();
        if (cluster == null) {
            return null;
        }
        DataSource dataSource = cluster.dataSource();
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute(schemaSql());
            st.execute("INSERT INTO tenants (id, name, code) OVERRIDING SYSTEM VALUE VALUES ("
                    + TENANT_ID + ", 'acc-5147', 'acc-5147')");
            st.execute("INSERT INTO products (id, tenant_id, name) VALUES ('" + PRODUCT_ID + "', "
                    + TENANT_ID + ", '布艺余料夹具商品')");
            st.execute("INSERT INTO product_skus (id, tenant_id, product_id, door_width, price, stock,"
                    + " sku_code, avg_cost, cost_amount) OVERRIDING SYSTEM VALUE VALUES (" + SKU_ID + ", "
                    + TENANT_ID + ", '" + PRODUCT_ID + "', '2.8米', 100, 60, '" + SKU_CODE + "', 12.5, 750)");
            st.execute("INSERT INTO craft_calc_configs (id, tenant_id) VALUES ('cfg-acc-5147', "
                    + TENANT_ID + ")");
            st.execute("INSERT INTO production_operations (id, tenant_id, name) VALUES"
                    + " ('op-5147-1', " + TENANT_ID + ", '绑带-布'),"
                    + " ('op-5147-2', " + TENANT_ID + ", '帘头制作')");
            st.execute("INSERT INTO production_option_routings"
                    + " (id, tenant_id, option_name, operation_name, after_operation, sort_order, status)"
                    + " VALUES ('or-5147-1', " + TENANT_ID + ", '余料做绑带', '绑带-布', '布帘车被', 8, 'active'),"
                    + " ('or-5147-2', " + TENANT_ID + ", '余料做帘头', '帘头制作', '布三边', 10, 'active')");
        }
        MybatisConfiguration configuration = new MybatisConfiguration();
        configuration.setMapUnderscoreToCamelCase(true);
        // 红证要用裸 JDBC 改库（绕过 session）⇒ 一级缓存必须是 STATEMENT 级，
        // 否则「改完再查」会拿到改前的结果（实测踩过：红证变成假绿）。
        configuration.setLocalCacheScope(LocalCacheScope.STATEMENT);
        configuration.setEnvironment(new Environment("acc-5147", new JdbcTransactionFactory(), dataSource));
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
        for (Class<?> mapper : List.of(StockBatchMapper.class, StockBatchConsumptionMapper.class,
                ProductSkuMapper.class, com.migao.admin.mapper.CraftCalcConfigMapper.class,
                FabricRemnantMapper.class, RemnantItemSizeMapper.class, ProductionOperationMapper.class,
                ProductionOptionRoutingMapper.class, OrderMapper.class, OrderItemMapper.class)) {
            configuration.addMapper(mapper);
        }
        SqlSessionFactory factory = new MybatisSqlSessionFactoryBuilder().build(configuration);
        SqlSession session = factory.openSession(true);
        RemnantService service = new RemnantService(session.getMapper(FabricRemnantMapper.class),
                session.getMapper(RemnantItemSizeMapper.class),
                session.getMapper(StockBatchMapper.class),
                session.getMapper(StockBatchConsumptionMapper.class),
                session.getMapper(ProductionOperationMapper.class),
                session.getMapper(ProductionOptionRoutingMapper.class),
                session.getMapper(OrderMapper.class),
                session.getMapper(OrderItemMapper.class));
        return new RemnantTestDb(cluster, dataSource, session, service);
    }

    public void stop() {
        if (session != null) {
            session.close();
        }
        if (cluster != null) {
            cluster.stop();
        }
    }

    public RemnantService remnantService() {
        return remnantService;
    }

    public <T> T mapperOf(Class<T> mapper) {
        return session.getMapper(mapper);
    }

    /** 建批次（数量 60 米 / 均价 12.5），返回 id。 */
    public long newBatch(String batchNo, String dyeLot) throws Exception {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery("INSERT INTO stock_batches (tenant_id, batch_no, product_id,"
                     + " sku_id, sku_code, quantity, unit_cost, dye_lot) VALUES (" + TENANT_ID + ", '"
                     + batchNo + "', '" + PRODUCT_ID + "', " + SKU_ID + ", '" + SKU_CODE + "', 60, 12.5, '"
                     + dyeLot + "') RETURNING id")) {
            assertThat(rs.next()).as("批次夹具必须落库").isTrue();
            return rs.getLong(1);
        }
    }

    /**
     * 直接插一块余料（绕开服务层：本方法只给**取数面**判据造数据，不走业务规则）。
     *
     * <p>⚠️ 两处**必须**照 DB 约束补齐，否则夹具自己就写不进去（V122 的
     * {@code ck_fabric_remnant_lifecycle} / {@code ck_fabric_remnant_amount} 是真的在拦）：
     * ① {@code source_batch_id} 必须指向真批次（回收额要从**批次均价**算，只写批次号取不到价）；
     * ② {@code used} / {@code scrapped} 必须带各自的留痕列（状态与留痕列互相解释得通）。</p>
     */
    public long insertRemnant(String orderNo, String batchNo, String dyeLot, String pieceKind,
                              String lengthM, String widthM, String status) throws Exception {
        StringBuilder cols = new StringBuilder("tenant_id, piece_seq, source_order_no,"
                + " source_processing_order_no, source_batch_id, source_batch_no, dye_lot,"
                + " product_id, sku_code, piece_kind, length_m, width_m, status");
        StringBuilder vals = new StringBuilder(TENANT_ID
                + ", (SELECT COALESCE(MAX(piece_seq), 0) + 1 FROM fabric_remnants), '" + orderNo
                + "', 'JG-" + orderNo + "', (SELECT id FROM stock_batches WHERE batch_no = '" + batchNo
                + "'), '" + batchNo + "', " + quote(dyeLot) + ", '" + PRODUCT_ID + "', '" + SKU_CODE
                + "', '" + pieceKind + "', " + lengthM + ", " + widthM + ", '" + status + "'");
        if (FabricRemnant.STATUS_USED.equals(status)) {
            cols.append(", used_by_order_no, recovered_meters, recovered_unit_cost, recovered_amount,"
                    + " recovered_at, recovered_by");
            vals.append(", '").append(orderNo).append("', ").append(lengthM).append(", 12.5, ")
                    .append("(").append(lengthM).append(" * 12.5), NOW(), 'system'");
        } else if (FabricRemnant.STATUS_SCRAPPED.equals(status)) {
            cols.append(", scrap_reason, scrapped_at, scrapped_by");
            vals.append(", '夹具报废', NOW(), 'system'");
        }
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery("INSERT INTO fabric_remnants (" + cols + ") VALUES ("
                     + vals + ") RETURNING id")) {
            assertThat(rs.next()).as("余料夹具必须落库").isTrue();
            return rs.getLong(1);
        }
    }

    /** 直接插一行小件用料尺寸（绕开服务层：给取数面判据用）。 */
    public void insertItemSize(String itemKey, String lengthM, String widthM) throws Exception {
        exec("INSERT INTO remnant_small_item_specs (tenant_id, item_key, length_m, width_m, operator)"
                + " VALUES (" + TENANT_ID + ", '" + itemKey + "', " + lengthM + ", " + widthM
                + ", 'system')");
    }

    public BigDecimal scalar(String sql) throws Exception {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery(sql)) {
            assertThat(rs.next()).as("查询必须有结果：" + sql).isTrue();
            return rs.getBigDecimal(1);
        }
    }

    public void exec(String sql) throws Exception {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute(sql);
        }
    }

    private static String quote(String value) {
        return value == null ? "NULL" : "'" + value + "'";
    }

    /** bootstrap 终态 schema（**不手抄列清单** ⇒ 列名 / 约束漂移会被抓）。 */
    private static String schemaSql() throws IOException {
        Path root = Paths.get(System.getProperty("user.dir")).toAbsolutePath();
        while (root != null && !Files.exists(root.resolve("docs/sql/schema.sql"))) {
            root = root.getParent();
        }
        assertThat(root).as("必须能定位 docs/sql/schema.sql").isNotNull();
        return Files.readString(root.resolve("docs/sql/schema.sql"));
    }
}
