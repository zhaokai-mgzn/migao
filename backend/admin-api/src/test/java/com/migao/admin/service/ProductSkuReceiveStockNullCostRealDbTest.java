// case_ids: PR-121
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.MybatisSqlSessionFactoryBuilder;
import com.migao.admin.mapper.ProductSkuMapper;
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
import java.nio.file.Paths;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.Statement;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;

/**
 * {@code ProductSkuMapper.receiveStock} 的**真库**判据：全新 SKU 首次入库**不记单价**（issue #5975）。
 *
 * <h2>为什么必须真库（结构面看不见）</h2>
 * <p>缺陷不在 Java 逻辑里，而在 <b>PostgreSQL 的参数类型推断</b>上：{@code avg_cost = #{newAvgCost}}
 * 这一处 PG 能从目标列推出 {@code numeric}，但同一实参在 {@code CASE WHEN #{newAvgCost} IS NULL}
 * 里是<b>裸操作数</b>（左边没有列、没有 cast）—— 当实参为 <b>NULL</b> 时 PG 收到的是
 * <i>unspecified</i> 类型的参数，于是
 * {@code ERROR: could not determine data type of parameter $N} ⇒
 * {@code BadSqlGrammarException} ⇒ 接口 500。</p>
 * <p>实参<b>非</b> NULL 时 PG 按字面量类型推断，一切正常 —— 这正是「有的能过、有的不能过」的机制。
 * mock 掉 Mapper 之后「调了一次 mapper」在两种情况下是<b>同一个读数</b>，所以这个缺陷在
 * mock 面上<b>结构性地不可见</b>；只有真 PG 才会现形。</p>
 *
 * <h2>触发路径（生产上必然命中）</h2>
 * <p>新 SKU ⇒ {@code avg_cost} 为 NULL；明细留空单价 ⇒
 * {@code InboundOrderService.movingAverage(beforeQty, null, qty, null)} 返回 {@code beforeAvg} = NULL
 * ⇒ {@code receiveStock(id, qty, null, batchNo)}。入库页注释明示「不记单价请留空」
 * （{@code frontend/admin-web/src/app/(dashboard)/inbound-orders/new/page.tsx}）⇒
 * <b>商家按页面提示操作时，新 SKU 的第一次入库必然过账失败</b>。</p>
 *
 * <h2>红证（修前实测读数）</h2>
 * <ul>
 *   <li>{@code newSkuFirstPostWithoutUnitCostSucceeds} —— 修前：
 *       {@code PSQLException: ERROR: could not determine data type of parameter $3}
 *       （与 issue #5975 的服务端异常栈逐字相同）；</li>
 *   <li>{@code costUnknownStaysNullNotZeroAfterCostlessPost} —— 修前同一条 PSQLException；</li>
 *   <li>{@code costlessFirstPostThenCostedSecondPostAccumulates} —— 修前第一步即抛。</li>
 * </ul>
 * <p>把修复摘掉（或把 {@code jdbcType} / cast 去掉）⇒ 这三条必红；对照条
 * （带单价的那两条）修前修后都应绿 —— 它证明判据认的是「null 参数」而不是「SQL 变了没有」。</p>
 *
 * <h2>环境</h2>
 * <p>一次性真 PG（{@link PgCluster}，与其他真库判据<b>共用同一装配</b>），schema 取
 * {@code backend/admin-api/src/main/resources/db/init/schema.sql} 终态（不手抄列清单）。
 * 缺 PG 二进制 ⇒ {@code PgCluster.startOrAbort()}：CI（{@code MIGAO_REQUIRE_REALDB=1}）判红、
 * 本机显式 skip（「没跑」长得像「没跑」）。</p>
 */
@DisplayName("#5975 真库：全新 SKU 首次入库不记单价 ⇒ receiveStock 必须成功（PG 参数类型可推断）")
class ProductSkuReceiveStockNullCostRealDbTest {

    private static final long TENANT_ID = 5975L;
    private static final long OTHER_TENANT_ID = 59750L;
    private static final String PRODUCT_ID = "prod-5975-1";
    private static final String OTHER_PRODUCT_ID = "prod-5975-2";

    private static PgCluster cluster;
    private static DataSource dataSource;
    private static SqlSessionFactory factory;

    @BeforeAll
    static void startRealPostgres() throws Exception {
        cluster = PgCluster.startOrAbort();
        dataSource = cluster.dataSource();
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute(readSchema());
            st.execute("INSERT INTO tenants (id, name, code) OVERRIDING SYSTEM VALUE VALUES ("
                    + TENANT_ID + ", 'acc-5975', 'acc-5975'), ("
                    + OTHER_TENANT_ID + ", 'acc-5975-other', 'acc-5975-other')");
            st.execute("INSERT INTO products (id, tenant_id, name) VALUES ('" + PRODUCT_ID + "', "
                    + TENANT_ID + ", '遮光窗帘布'), ('" + OTHER_PRODUCT_ID + "', "
                    + OTHER_TENANT_ID + ", '别家窗帘布')");
        }
        MybatisConfiguration configuration = new MybatisConfiguration();
        configuration.setMapUnderscoreToCamelCase(true);
        configuration.setEnvironment(new Environment("acc-5975", new JdbcTransactionFactory(), dataSource));
        configuration.addMapper(ProductSkuMapper.class);
        factory = new MybatisSqlSessionFactoryBuilder().build(configuration);
    }

    @AfterAll
    static void stopRealPostgres() {
        if (cluster != null) {
            cluster.stop();
        }
    }

    // ============================================================ 判据 1：本单的靶心

    @Test
    @DisplayName("🔴 全新 SKU（avg_cost NULL）+ 不记单价 ⇒ 首次过账必须成功，库存增加、生成批次号")
    void newSkuFirstPostWithoutUnitCostSucceeds() throws Exception {
        long skuId = seedSku(597_501L, TENANT_ID, PRODUCT_ID, "SKU-5975-NEW-A");

        assertThatCode(() -> receiveStock(skuId, "3", null, "PC-20261002-0001"))
                .as("全新 SKU 首次入库不记单价不得抛异常 —— 修前实测 "
                        + "PSQLException: ERROR: could not determine data type of parameter $3（issue #5975）")
                .doesNotThrowAnyException();

        Row row = readRow(skuId);
        assertThat(row.rowsUpdated).isEqualTo(1);
        assertThat(row.stock).isEqualByComparingTo("3");            // 库存 0 → 3：不能因为写成本失败而回滚
        assertThat(row.latestBatchNo).isEqualTo("PC-20261002-0001"); // 批次号必须生成
    }

    // ============================================================ 判据 2：成本未知的落值语义

    @Test
    @DisplayName("🔴 成本未知 ⇒ avg_cost / cost_amount 留 NULL（不用 0 冒充「成本为零」）")
    void costUnknownStaysNullNotZeroAfterCostlessPost() throws Exception {
        long skuId = seedSku(597_502L, TENANT_ID, PRODUCT_ID, "SKU-5975-NEW-B");

        receiveStock(skuId, "2.5", null, "PC-20261002-0002");

        Row row = readRow(skuId);
        assertThat(row.stock).isEqualByComparingTo("2.5");
        assertThat(row.avgCost).as("avg_cost 是「未知」而不是「成本为零」").isNull();
        assertThat(row.costAmount).as("cost_amount 是「未知」而不是「成本为零」").isNull();
        assertThat(row.latestBatchNo).isEqualTo("PC-20261002-0002");
    }

    // ============================================================ 判据 3：两次过账（先无价后有价）

    @Test
    @DisplayName("🔴 先不记单价过账、再带单价过账 ⇒ 均价取带价那次，成本金额 = 总库存 × 均价")
    void costlessFirstPostThenCostedSecondPostAccumulates() throws Exception {
        long skuId = seedSku(597_503L, TENANT_ID, PRODUCT_ID, "SKU-5975-NEW-C");

        receiveStock(skuId, "3", null, "PC-20261002-0003");           // 首次：不记单价
        assertThat(readRow(skuId).avgCost).isNull();                  // 仍未知

        // 第二次：beforeAvg 仍为 NULL ⇒ movingAverage 取进价 10（与 @5975 的服务端算法同源）
        receiveStock(skuId, "3", "10", "PC-20261002-0004");

        Row row = readRow(skuId);
        assertThat(row.stock).isEqualByComparingTo("6");              // 3 + 3
        assertThat(row.avgCost).isEqualByComparingTo("10");
        assertThat(row.costAmount).isEqualByComparingTo("60");        // ROUND(6 × 10, 4)
        assertThat(row.latestBatchNo).isEqualTo("PC-20261002-0004");
    }

    // ============================================================ 对照条（修前修后都应绿）

    @Test
    @DisplayName("对照：全新 SKU + 记单价 ⇒ avg_cost/cost_amount 正常落值（证明判据认的是 null 参数本身）")
    void newSkuFirstPostWithUnitCostWritesAvgCostAndAmount() throws Exception {
        long skuId = seedSku(597_504L, TENANT_ID, PRODUCT_ID, "SKU-5975-WITH-COST");

        receiveStock(skuId, "3", "9.9", "PC-20261002-0005");

        Row row = readRow(skuId);
        assertThat(row.stock).isEqualByComparingTo("3");
        assertThat(row.avgCost).isEqualByComparingTo("9.9");
        assertThat(row.costAmount).isEqualByComparingTo("29.7");      // ROUND(3 × 9.9, 4)
        assertThat(row.latestBatchNo).isEqualTo("PC-20261002-0005");
    }

    // ============================================================ 夹具

    /** surefire 的 cwd 是模块目录（{@code backend/admin-api}），仓根相对路径要退两级 —— 与既有真库判据同款。 */
    private static String readSchema() throws Exception {
        java.nio.file.Path path = Paths.get("backend/admin-api/src/main/resources/db/init/schema.sql");
        if (!Files.exists(path)) {
            path = Paths.get("..", "..").resolve(path).normalize();
        }
        return Files.readString(path);
    }

    /** 落一个**全新** SKU：stock 0、avg_cost / cost_amount / latest_batch_no 全 NULL（首次入库的真实起点）。 */
    private static long seedSku(long skuId, long tenantId, String productId, String skuCode)
            throws Exception {
        try (Connection conn = dataSource.getConnection();
             PreparedStatement ps = conn.prepareStatement(
                     "INSERT INTO product_skus (id, tenant_id, product_id, door_width, price, stock, "
                             + "sku_code, avg_cost) OVERRIDING SYSTEM VALUE VALUES (?, ?, ?, '2.8m', 0, 0, ?, NULL)")) {
            ps.setLong(1, skuId);
            ps.setLong(2, tenantId);
            ps.setString(3, productId);
            ps.setString(4, skuCode);
            ps.executeUpdate();
        }
        return skuId;
    }

    /** 真 Mapper 调用（不 mock）—— 走 MyBatis 参数绑定 + PG 真实类型推断，这正是缺陷发生的那一层。 */
    private static void receiveStock(long skuId, String quantity, String newAvgCost, String batchNo) {
        try (SqlSession session = factory.openSession(true)) {
            ProductSkuMapper mapper = session.getMapper(ProductSkuMapper.class);
            mapper.receiveStock(skuId,
                    new BigDecimal(quantity),
                    newAvgCost == null ? null : new BigDecimal(newAvgCost),
                    batchNo);
        }
    }

    private static Row readRow(long skuId) throws Exception {
        try (Connection conn = dataSource.getConnection();
             PreparedStatement ps = conn.prepareStatement(
                     "SELECT stock, avg_cost, cost_amount, latest_batch_no FROM product_skus WHERE id = ?")) {
            ps.setLong(1, skuId);
            try (ResultSet rs = ps.executeQuery()) {
                assertThat(rs.next()).as("SKU 行必须存在").isTrue();
                Row row = new Row();
                row.stock = rs.getBigDecimal("stock");
                row.avgCost = rs.getBigDecimal("avg_cost");
                row.costAmount = rs.getBigDecimal("cost_amount");
                row.latestBatchNo = rs.getString("latest_batch_no");
                row.rowsUpdated = 1;
                return row;
            }
        }
    }

    private static final class Row {
        BigDecimal stock;
        BigDecimal avgCost;
        BigDecimal costAmount;
        String latestBatchNo;
        int rowsUpdated;
    }
}
