// case_ids: PR-121, PR-123

package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.MybatisSqlSessionFactoryBuilder;
import com.baomidou.mybatisplus.extension.plugins.MybatisPlusInterceptor;
import com.baomidou.mybatisplus.extension.plugins.handler.TenantLineHandler;
import com.baomidou.mybatisplus.extension.plugins.inner.TenantLineInnerInterceptor;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.InboundOrderItemMapper;
import com.migao.admin.mapper.InboundOrderMapper;
import com.migao.admin.mapper.InboundOrderQueryMapper;
import com.migao.admin.mapper.ProductMapper;
import com.migao.admin.mapper.ProductSkuMapper;
import com.migao.admin.mapper.StockBatchMapper;
import com.migao.admin.mapper.StockLedgerMapper;
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
import java.math.BigDecimal;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.sql.Connection;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;

/**
 * 真库判据（issue #6816）：<b>小数库存下，台账 {@code before_qty} 必须是精确值、{@code delta} 必须等于本次实际变更量</b>。
 *
 * <h2>为什么必须真库</h2>
 * 缺陷不在 Java 逻辑里，而在<b>那条 SQL 的 {@code RETURNING} 表达式</b>上：
 * {@code receiveStock} / {@code deductStock} 曾写
 * {@code RETURNING CEIL(stock - #{quantity}) AS "beforeQuantity"} —— 库存列已是
 * {@code NUMERIC(12,1)}（V115 / issue #5063 起 0.1 米粒度合法），而 {@code CEIL} 把它
 * <b>向上取整到整数</b> ⇒ {@code before} 偏大（最多 +0.9）、
 * {@code StockLedger.delta = after − before} 随之偏小。mock 面结构上看不见：mock 恒返回
 * 自己造的数，不存在「PG 的取整函数改了读数」这件事。
 *
 * <p>生产现场读数（issue #6816，租户 25 / SKU {@code MG-JGM-280-14}，2026-10-13）：
 * <pre>
 * 台账 4097  RK-20261013-0001  before 0.0    after 67.2   delta 67.2  （0 → 67.2 ✔）
 * 台账 4098  RK-20261013-0002  before 68.0   after 68.2   delta 0.2   （本次加了 1.0 米 ✘）
 * 台账 4101  RK-20261013-0003  before 69.0   after 135.4  delta 66.4  （本次加了 67.2 米 ✘）
 * </pre>
 * 0002 = {@code CEIL(68.2 − 1) = CEIL(67.2) = 68}；0003 = {@code CEIL(135.4 − 67.2) = CEIL(68.2) = 69}。
 * 三列列类型皆为 {@code NUMERIC(12,1)}（{@code information_schema} 已核）⇒ 没有任何一列要求整数，
 * 取整是整数时代的残留写法（当时 {@code stock} 是整数，{@code CEIL} 恰好是空操作）。</p>
 *
 * <h2>判据（每条都会红）</h2>
 * <ol>
 *   <li><b>入库台账链（靶心，走真 {@code InboundOrderService.post}）</b>：同一个 SKU 按现场读数的顺序过三张单
 *       —— 0 → 67.2（正对照）→ 68.2（入库 1.0）→ 135.4（入库 67.2）。三条台账行里：
 *       第一行 {@code before_qty = 0.0 / delta = 67.2}（取整对它是空操作，修前修后必须一字不变）；
 *       第二行 {@code before_qty = 67.2}、{@code after_qty = 68.2}、{@code delta = 1.0}；
 *       第三行 {@code before_qty = 68.2}（= 第二行 after，链式相接）、{@code after_qty = 135.4}、
 *       {@code delta = 67.2}。</li>
 *   <li><b>扣减读数（走真 mapper 的 {@code deductStock}）</b>：另一个同起点的小数库存 SKU，67.2 扣 0.5 ⇒
 *       {@code beforeQuantity} 必须是精确的 <b>67.2</b>（修前 {@code CEIL(66.7) = 67}），
 *       且扣后真库 {@code product_skus.stock} 必须等于 {@code afterQuantity}（66.7）。</li>
 * </ol>
 *
 * <p><b>为什么不用云 dev 库</b>：真库判据在本仓的统一形态是 {@code PgCluster.startOrAbort()}
 * ——一次性真 PG（{@code initdb} + {@code pg_ctl}，随机端口，跑完即停），见 issue #5167/#5192 与
 * {@code backend/admin-api/src/test/java/com/migao/admin/service/PgCluster.java}。
 * 本单沿用同一装配：<b>可重复、零残留、绝不碰云端任何存量数据</b>（含租户 25 的证据单）。</p>
 *
 * <p><b>方向说明（照实登记）</b>：{@code delta} 的语义<b>不变</b>（仍是 {@code after − before}，
 * 由 {@code StockLedgerService.record} 从根上算，见其类注释）；本单只让 {@code after − before}
 * 这个差值重新等于「本次到底变了多少」。存量已写入的台账行<b>不回填</b>
 * （append-only 台账；回填需要单独的裁定）。</p>
 *
 * <p><b>边界（如实登记）</b>：① 探针对象全部自建（tenant {@value #TENANT_ID}），
 * 用完随临时集群销毁，<b>不碰任何存量数据</b>（含租户 25 的证据单 RK-20261013-0001/0002/0003）；
 * ② 本判据判的是<b>数量读数</b>，{@code avg_cost} 不在射程内；
 * ③ 判据跑真 PG 而非 HTTP 栈；④ 类级元守卫（防同类再犯）=
 * {@code LedgerBeforeQuantityRoundingMetaGuardTest}。</p>
 */
@DisplayName("🔴 真库判据（#6816）：小数库存下台账 before_qty 必须精确、delta == 本次实际变更量")
class LedgerBeforeQuantityPrecisionRealDbTest {

    private static final long TENANT_ID = 6816L;
    private static final String PRODUCT_ID = "prod-6816-1";

    /** 第一单的入库量：0 → 67.2（现场 0001 单，整数/零起点路径 = 正对照）。 */
    private static final BigDecimal ZERO_START_QTY = new BigDecimal("67.2");
    /** 起点小数库存：现场读数里第二次入库前的 67.2 米（issue #6816）。 */
    private static final BigDecimal DECIMAL_STOCK = new BigDecimal("67.2");
    /** 第一次入库量：1.0 米（现场 0002 单）。 */
    private static final BigDecimal FIRST_INBOUND_QTY = new BigDecimal("1.0");
    /** 第二次入库量：67.2 米（现场 0003 单）。 */
    private static final BigDecimal SECOND_INBOUND_QTY = new BigDecimal("67.2");
    /** 扣减量：0.5 米（0.1 米粒度下的典型半米）。 */
    private static final BigDecimal DEDUCT_QTY = new BigDecimal("0.5");

    private static final long INBOUND_SKU_ID = 6_816_001L;
    private static final long DEDUCT_SKU_ID = 6_816_002L;

    private static PgCluster cluster;
    private static DataSource dataSource;
    private static SqlSessionFactory factory;

    @BeforeAll
    static void startRealPostgresAndFixtures() throws Exception {
        cluster = PgCluster.startOrAbort();
        dataSource = cluster.dataSource();
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute(readSchema());
            st.execute("INSERT INTO tenants (id, name, code) OVERRIDING SYSTEM VALUE VALUES ("
                    + TENANT_ID + ", 'ledger-before-6816', 'ledger-before-6816')");
            st.execute("INSERT INTO products (id, tenant_id, name) VALUES ('" + PRODUCT_ID + "', "
                    + TENANT_ID + ", '遮光窗帘布-6816')");
            // 入库腿：起点就是小数库存 67.2（与现场 0002 单一致）——一个 SKU 串起两条台账行
            seedSku(INBOUND_SKU_ID, "SKU-6816-IN", BigDecimal.ZERO);
            // 扣减腿：另起一个同起点的小数库存 SKU（与入库腿零共享，读数互不污染）
            seedSku(DEDUCT_SKU_ID, "SKU-6816-OUT", DECIMAL_STOCK);
            // 三张待过账的草稿单（各一行明细）——按现场读数的顺序排在同一个 SKU 上，读出台账链
            seedDraftOrder("io-6816-z", "RK-6816-0001", INBOUND_SKU_ID, ZERO_START_QTY);
            seedDraftOrder("io-6816-a", "RK-6816-0002", INBOUND_SKU_ID, FIRST_INBOUND_QTY);
            seedDraftOrder("io-6816-b", "RK-6816-0003", INBOUND_SKU_ID, SECOND_INBOUND_QTY);
        }
        MybatisConfiguration configuration = new MybatisConfiguration();
        configuration.setMapUnderscoreToCamelCase(true);
        configuration.setEnvironment(new Environment("ledger-before-6816", new JdbcTransactionFactory(), dataSource));
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
        for (Class<?> mapper : List.of(InboundOrderMapper.class, InboundOrderItemMapper.class,
                StockBatchMapper.class, ProductSkuMapper.class, ProductMapper.class, StockLedgerMapper.class)) {
            configuration.addMapper(mapper);
        }
        factory = new MybatisSqlSessionFactoryBuilder().build(configuration);
    }

    @AfterAll
    static void stopRealPostgres() {
        if (cluster != null) {
            cluster.stop();
        }
    }

    // ============================================================ 判据 1：靶心（入库台账，真过账链）

    @Test
    @DisplayName("🔴 小数库存 67.2 → 入库 1.0 → 入库 67.2：台账 before_qty 必须精确（67.2 / 68.2 链式相接）、"
            + "delta 必须等于本次变更量（1.0 / 67.2）—— 现场 0002/0003 单读数 68.0/0.2 与 69.0/66.4")
    void decimalStockInboundKeepsLedgerBeforeAndDeltaExact() {
        // 第一单：0 → 67.2（整数/零起点路径，正对照），第二单 67.2 → 68.2，第三单 68.2 → 135.4
        assertThat(post("io-6816-z")).as("全新 SKU（0）首次入库 67.2 —— 正对照路径必须成功").isTrue();
        assertThat(post("io-6816-a")).as("小数库存 67.2 入库 1.0 必须成功").isTrue();
        assertThat(post("io-6816-b")).as("小数库存 68.2 入库 67.2 必须成功").isTrue();

        List<LedgerRow> rows = ledgerRows(INBOUND_SKU_ID);
        System.out.println("[READING #6816 入库链 0→67.2→68.2→135.4] 库存="
                + skuStock(INBOUND_SKU_ID).toPlainString() + " 台账=" + rows);
        assertThat(rows).as("三次过账三条台账行").hasSize(3);

        // 判据 3（正对照·双向回归）：整数/零起点路径的读数修前修后一字不变
        LedgerRow zeroStart = rows.get(0);
        assertThat(zeroStart.beforeQty()).as("0 起点：before 必须是 0.0（取整对它是空操作 ⇒ 读数必须不变）")
                .isEqualByComparingTo(BigDecimal.ZERO);
        assertThat(zeroStart.afterQty()).as("0 起点：after 必须是 67.2").isEqualByComparingTo(DECIMAL_STOCK);
        assertThat(zeroStart.delta()).as("0 起点：delta 必须是 67.2").isEqualByComparingTo(DECIMAL_STOCK);

        // 判据 1（靶心）：小数库存下 before 精确 + delta == 本次变更量
        LedgerRow firstInbound = rows.get(1);
        assertThat(firstInbound.beforeQty())
                .as("台账 before_qty 必须是变更前的精确库存 67.2 —— 修前 CEIL(68.2 − 1) = 68 判入 68.0"
                        + "（现场 0002 单同形；整条链=" + rows + "）")
                .isEqualByComparingTo(DECIMAL_STOCK);
        assertThat(firstInbound.afterQty()).as("after_qty 必须是变更后的精确库存 68.2")
                .isEqualByComparingTo(DECIMAL_STOCK.add(FIRST_INBOUND_QTY));
        assertThat(firstInbound.delta()).as("delta 必须等于本次实际变更量 1.0 —— 修前记 0.2")
                .isEqualByComparingTo(FIRST_INBOUND_QTY);
        assertThat(firstInbound.delta()).as("行内自洽：delta == after − before（读数=" + firstInbound + "）")
                .isEqualByComparingTo(firstInbound.afterQty().subtract(firstInbound.beforeQty()));

        // 判据 1（续）：第二行 before 必须 = 第一行 after（链式相接）
        LedgerRow secondInbound = rows.get(2);
        BigDecimal expectedFinal = DECIMAL_STOCK.add(FIRST_INBOUND_QTY).add(SECOND_INBOUND_QTY);
        assertThat(secondInbound.beforeQty())
                .as("第二行 before_qty 必须 = 第一行 after_qty（链式相接）—— 修前 69.0 ≠ 68.2，链断")
                .isEqualByComparingTo(firstInbound.afterQty());
        assertThat(secondInbound.afterQty()).as("第二行 after_qty 必须是精确库存 135.4")
                .isEqualByComparingTo(expectedFinal);
        assertThat(secondInbound.delta()).as("delta 必须等于本次实际变更量 67.2 —— 修前记 66.4")
                .isEqualByComparingTo(SECOND_INBOUND_QTY);
        assertThat(skuStock(INBOUND_SKU_ID)).as("真库库存 == 链末行的 after（台账链不撒谎）")
                .isEqualByComparingTo(secondInbound.afterQty());
    }

    // ============================================================ 判据 2：扣减腿的 before 读数

    @Test
    @DisplayName("🔴 小数库存 67.2 扣 0.5 ⇒ deductStock 返回 beforeQuantity = 67.2（修前 CEIL(66.7) = 67）")
    void decimalStockDeductReturnsExactBeforeQuantity() {
        Map<String, Object> row;
        try (SqlSession session = factory.openSession(true)) {
            row = session.getMapper(ProductSkuMapper.class)
                    .deductStock(DEDUCT_SKU_ID, DEDUCT_QTY, TENANT_ID);
        }
        assertThat(row).as("库存 67.2 ≥ 0.5 ⇒ 扣减必须成功（0 行/ null = 库存不足）").isNotNull();

        BigDecimal before = decimal(row.get("beforeQuantity"));
        BigDecimal after = decimal(row.get("afterQuantity"));
        BigDecimal expectedAfter = DECIMAL_STOCK.subtract(DEDUCT_QTY);
        System.out.println("[READING #6816 扣减 0.5] 返回 before=" + before.toPlainString()
                + " after=" + after.toPlainString() + " 真库 stock=" + skuStock(DEDUCT_SKU_ID).toPlainString());

        assertThat(before).as("deductStock 的 beforeQuantity 必须是精确的 67.2 —— 修前 CEIL(66.7) = 67")
                .isEqualByComparingTo(DECIMAL_STOCK);
        assertThat(after).as("afterQuantity 必须是精确的 66.7").isEqualByComparingTo(expectedAfter);
        assertThat(after.subtract(before)).as("扣减腿的净变更量必须是 −0.5（修前 67 − 66.7 = −0.3）")
                .isEqualByComparingTo(DEDUCT_QTY.negate());
        assertThat(skuStock(DEDUCT_SKU_ID)).as("真库库存与 RETURNING 的 afterQuantity 必须逐值一致")
                .isEqualByComparingTo(after);
    }

    // ============================================================ 夹具

    private static void seedSku(long skuId, String skuCode, BigDecimal stock) throws Exception {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute("INSERT INTO product_skus (id, tenant_id, product_id, door_width, price, stock, sku_code) "
                    + "VALUES (" + skuId + ", " + TENANT_ID + ", '" + PRODUCT_ID + "', '2.8m', 150.00, "
                    + stock.toPlainString() + ", '" + skuCode + "')");
        }
    }

    /** 一张草稿入库单 + 一行明细（真过账链的入口数据）。 */
    private static void seedDraftOrder(String orderId, String inboundNo, long skuId,
                                       BigDecimal quantity) throws Exception {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute("INSERT INTO inbound_orders (id, tenant_id, inbound_no, supplier, warehouse, status) VALUES ('"
                    + orderId + "', " + TENANT_ID + ", '" + inboundNo + "', '线A供应商', '主仓', 'draft')");
            // inbound_order_items.id 是 GENERATED ALWAYS AS IDENTITY ⇒ 不写主键
            st.execute("INSERT INTO inbound_order_items (tenant_id, inbound_order_id, sku_id, product_id, sku_code,"
                    + " quantity, unit_cost) VALUES (" + TENANT_ID + ", '" + orderId + "', " + skuId + ", '"
                    + PRODUCT_ID + "', 'SKU-6816-IN', " + quantity.toPlainString() + ", 12.0000)");
        }
    }

    /** 一次真过账（真 InboundOrderService + 真库 mapper + 真台账）；返回是否成功。 */
    private static boolean post(String orderId) {
        try (SqlSession session = factory.openSession(false)) {
            serviceOn(session).post(orderId, TENANT_ID, "tester");
            session.commit();
            return true;
        } catch (BusinessException e) {
            System.out.println("[READING #6816 过账失败] order=" + orderId
                    + " status=" + e.getHttpStatus() + " msg=" + e.getMessage());
            return false;
        }
    }

    /** 真装配：过账闸 + 加库存 + 台账全部走<b>真库 mapper</b>。 */
    private static InboundOrderService serviceOn(SqlSession s) {
        StockLedgerService stockLedgerService = new StockLedgerService(
                s.getMapper(StockLedgerMapper.class), s.getMapper(ProductSkuMapper.class));
        return new InboundOrderService(
                s.getMapper(InboundOrderMapper.class),
                s.getMapper(InboundOrderItemMapper.class),
                mock(InboundOrderQueryMapper.class),
                s.getMapper(StockBatchMapper.class),
                s.getMapper(ProductSkuMapper.class),
                s.getMapper(ProductMapper.class),
                stockLedgerService);
    }

    private static BigDecimal decimal(Object value) {
        return value == null ? null : new BigDecimal(value.toString());
    }

    private static BigDecimal skuStock(long skuId) {
        return (BigDecimal) scalar("SELECT stock FROM product_skus WHERE id = " + skuId);
    }

    private static Object scalar(String sql) {
        try (Connection c = dataSource.getConnection();
             Statement st = c.createStatement();
             ResultSet rs = st.executeQuery(sql)) {
            return rs.next() ? rs.getObject(1) : null;
        } catch (SQLException e) {
            throw new IllegalStateException("真值读取失败: " + sql, e);
        }
    }

    private static List<LedgerRow> ledgerRows(long skuId) {
        List<LedgerRow> rows = new ArrayList<>();
        try (Connection c = dataSource.getConnection();
             Statement st = c.createStatement();
             ResultSet rs = st.executeQuery("SELECT id, before_qty, after_qty, delta, ref_no"
                     + " FROM stock_ledger_entries WHERE tenant_id = " + TENANT_ID
                     + " AND sku_id = " + skuId + " ORDER BY id")) {
            while (rs.next()) {
                rows.add(new LedgerRow(rs.getLong(1), rs.getBigDecimal(2), rs.getBigDecimal(3),
                        rs.getBigDecimal(4), rs.getString(5)));
            }
        } catch (SQLException e) {
            throw new IllegalStateException("台账真值读取失败", e);
        }
        return rows;
    }

    /** 台账一行（真值读取，裸 JDBC 不经被测读面）。 */
    private record LedgerRow(long id, BigDecimal beforeQty, BigDecimal afterQty, BigDecimal delta, String refNo) {
        @Override
        public String toString() {
            return "#" + id + "{before=" + beforeQty.toPlainString() + ", after=" + afterQty.toPlainString()
                    + ", delta=" + delta.toPlainString() + ", ref=" + refNo + "}";
        }
    }

    /** schema 定位：Surefire 的 cwd 是模块目录（{@code backend/admin-api}），向上找到仓根。 */
    private static String readSchema() throws IOException {
        Path root = Paths.get(System.getProperty("user.dir")).toAbsolutePath();
        while (root != null
                && !Files.exists(root.resolve("backend/admin-api/src/main/resources/db/init/schema.sql"))) {
            root = root.getParent();
        }
        assertThat(root).as("必须能定位 backend/admin-api/src/main/resources/db/init/schema.sql").isNotNull();
        return Files.readString(root.resolve("backend/admin-api/src/main/resources/db/init/schema.sql"));
    }
}
