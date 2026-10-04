// case_ids: PR-123

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
import org.springframework.jdbc.datasource.DriverManagerDataSource;

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
import java.util.concurrent.CyclicBarrier;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;

/**
 * 真库并发判据（issue #6300）：<b>两张同 SKU 草稿入库单并发过账 ⇒ 台账 before/after 必须首尾相接
 * （禁止同基）、净增量仍正确</b>。
 *
 * <h2>为什么必须真库 + 真并发</h2>
 * 缺陷形态是「<b>原子加总 + 非原子记账</b>」混用：
 * <pre>
 * BigDecimal beforeQty = StockQuantity.orZero(sku.getStock());   // ← 快照读（过账前）
 * productSkuMapper.receiveStock(sku.getId(), quantity, …);        // ← 原子自增（对）
 * stockLedgerService.record(…, beforeQty, beforeQty.add(quantity), …);  // ← 陈旧快照
 * </pre>
 * 两张单并发过账时两边都读到同一个 {@code beforeQty} ⇒ 台账两行<b>同基</b>、链断裂
 * （库存总数仍对，所以<b>只看库存查不出来</b>，只有查台账链才暴露）。
 * mock 面结构上判不了：mock 里两个请求各自跑自己的内存账本，不存在「读到的快照被别人改过」这件事。
 *
 * <p>生产现场读数（main）：
 * {@code acceptance/2026-10-04/race-sweep/out/probe-write-raw.json::cases.W3} —— 两单 10/15 米并发过账，
 * 台账 {@code [{delta=10, before=65.0, after=75.0}, {delta=15, before=65.0, after=80.0}]}、
 * {@code chainBad=[{at:2246, prevAfter:75.0, curBefore:65.0}]}、{@code sameBaseConcurrentRead=true}；
 * W7 同形（{@code 100.0→115.0} 与 {@code 100.0→110.0}）。顺序对照
 * {@code probe-redproof-raw.json::RP3}：台账 1 行、链正常。</p>
 *
 * <h2>判据（每条都会红）</h2>
 * <ol>
 *   <li><b>两单都成功</b>（它们是两张不同的单，过账幂等闸不该误杀）且库存净增量 == 两单数量之和
 *       （独立算式；这条在修前也是绿的 —— <b>正对照</b>：链断裂不是"装置什么都判不出来"）；</li>
 *   <li><b>台账链式相接</b>：本 SKU 的 inbound 行按 id 升序，每行 before == 上一行 after，
 *       首行 before == 初始库存，末行 after == 当前库存，行数 == 2；</li>
 *   <li><b>行内自洽</b>：每行 {@code delta == after - before}；</li>
 *   <li><b>顺序对照</b>（护栏不误杀）：单张草稿单串行过账仍成功、台账 1 行、链成立。</li>
 * </ol>
 *
 * <p>重复 {@value #ROUNDS} 轮（缺陷时序敏感：单轮可能因调度恰好串行而侥幸变绿）。</p>
 *
 * <p><b>边界（如实登记）</b>：① 本判据跑的是<b>真库并发</b>而非 HTTP 栈；
 * ② 探针对象全部自建（tenant {@value #TENANT_ID} / 商品前缀 {@code inbound-race-6300}），
 * 用完随临时集群销毁，<b>不碰任何存量数据</b>；③ 本判据判的是<b>数量链</b>；
 * {@code avg_cost} 的并发正确性（同一 SKU 并发入库时移动加权均价的读-算-写窗口）
 * <b>不在本单射程内</b>，已在 PR body 的「未固化项」如实登记。</p>
 */
@DisplayName("🔴 真库并发判据（#6300）：两张同 SKU 草稿单并发过账 ⇒ 台账 before/after 链式相接（禁止同基）")
class InboundPostLedgerChainRaceRealDbTest {

    private static final Long TENANT_ID = 6300L;
    private static final String PRODUCT_ID = "inbound-race-6300";
    private static final BigDecimal INITIAL_STOCK = new BigDecimal("50");
    /** 两张单的数量（独立算式常量，不读被测读面）。 */
    private static final BigDecimal[] QUANTITIES = {new BigDecimal("10"), new BigDecimal("15")};
    private static final int CONCURRENCY = 2;
    private static final int ROUNDS = 3;
    private static final int SERIAL_ROUND = ROUNDS + 1;

    private static PgCluster cluster;
    private static DataSource dataSource;
    private static SqlSessionFactory factory;

    @BeforeAll
    static void startRealPostgresAndFixtures() throws Exception {
        cluster = PgCluster.startOrAbort();
        dataSource = cluster.dataSource();
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute(schemaSql());
            st.execute("INSERT INTO tenants (id, name, code) OVERRIDING SYSTEM VALUE VALUES ( "
                    + TENANT_ID + ", 'inbound-race-6300', 'inbound-race-6300')");
            st.execute("INSERT INTO products (id, tenant_id, name, base_price, stock) VALUES ('"
                    + PRODUCT_ID + "', " + TENANT_ID + ", '线B验收-6300入库帘', 150.00, "
                    + INITIAL_STOCK.toPlainString() + ")");
            // 每个轮次一个独立 SKU（同一 SKU 跨轮会互相污染库存/台账读数）
            for (int r = 1; r <= SERIAL_ROUND; r++) {
                st.execute("INSERT INTO product_skus (id, tenant_id, product_id, door_width, price, stock, sku_code) VALUES ( "
                        + skuId(r) + ", " + TENANT_ID + ", '" + PRODUCT_ID + "', '2.8m', 150.00, "
                        + INITIAL_STOCK.toPlainString() + ", 'SKU-6300-R" + r + "')");
                for (int i = 0; i < CONCURRENCY; i++) {
                    st.execute("INSERT INTO inbound_orders (id, tenant_id, inbound_no, supplier, warehouse, status) VALUES ('"
                            + orderId(r, i) + "', " + TENANT_ID + ", '" + inboundNo(r, i)
                            + "', '线B验收供应商', '主仓', 'draft')");
                    // inbound_order_items.id 是 GENERATED ALWAYS AS IDENTITY ⇒ 显式写 DEFAULT 占位
                    st.execute("INSERT INTO inbound_order_items (id, tenant_id, inbound_order_id, sku_id, product_id, sku_code, quantity, unit_cost) VALUES ("
                            + "DEFAULT, " + TENANT_ID + ", '" + orderId(r, i) + "', " + skuId(r)
                            + ", '" + PRODUCT_ID + "', 'SKU-6300-R" + r + "', "
                            + QUANTITIES[i].toPlainString() + ", 12.0000)");
                }
            }
        }

        MybatisConfiguration configuration = new MybatisConfiguration();
        configuration.setMapUnderscoreToCamelCase(true);
        configuration.setEnvironment(new Environment("inbound-race-6300", new JdbcTransactionFactory(), dataSource));
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

    @Test
    @DisplayName("两张同 SKU 草稿单并发过账（3 轮）：净增量 = 25 且台账链首尾相接（修前两行同基）")
    void concurrentPostKeepsLedgerChainConnected() throws Exception {
        for (int round = 1; round <= ROUNDS; round++) {
            BigDecimal stockBefore = skuStock(round);
            List<Outcome> outcomes = runConcurrently(round);
            long success = outcomes.stream().filter(Outcome::success).count();
            List<Integer> loserStatus = outcomes.stream().filter(o -> !o.success)
                    .map(Outcome::httpStatus).toList();
            BigDecimal stockAfter = skuStock(round);
            List<LedgerRow> rows = ledgerRows(round);

            System.out.println("[READING #6300 round " + round + "] 成功数=" + success
                    + " 落败状态码=" + loserStatus
                    + " 库存=" + stockBefore.toPlainString() + "→" + stockAfter.toPlainString()
                    + " 台账=" + rows);

            // 正对照：库存净增量在修前也是对的（链断裂是"查得到但看不出来"的隐性缺陷）
            assertThat(success).as("两张不同的单都必须过账成功（幂等闸只该拦重复过账同一张单）")
                    .isEqualTo(CONCURRENCY);
            assertThat(stockAfter.subtract(stockBefore))
                    .as("正对照：库存净增量 == 两单数量之和（修前也绿 —— 证明装置有判别力，不是什么都判不出来）")
                    .isEqualByComparingTo(quantitiesSum());
            assertThat(rows).as("两名同 SKU 的过账各落一行台账").hasSize(CONCURRENCY);
            assertChain(rows, round);
            for (LedgerRow row : rows) {
                assertThat(row.delta()).as("行内自洽：delta == after - before（" + row + "）")
                        .isEqualByComparingTo(row.afterQty().subtract(row.beforeQty()));
            }
        }
    }

    @Test
    @DisplayName("顺序对照（护栏不误杀）：单张草稿单串行过账仍成功，台账 1 行且链成立")
    void serialPostStillSucceeds() {
        int round = SERIAL_ROUND;
        Outcome outcome;
        try (SqlSession s = factory.openSession(false)) {
            outcome = postOn(s, orderId(round, 0));
            if (outcome.success()) {
                s.commit();
            } else {
                s.rollback();
            }
        }
        BigDecimal stockAfter = skuStock(round);
        List<LedgerRow> rows = ledgerRows(round);
        System.out.println("[READING #6300 正对照 串行] 状态=" + outcome.httpStatus()
                + " 库存=" + INITIAL_STOCK.toPlainString() + "→" + stockAfter.toPlainString()
                + " 台账=" + rows);

        assertThat(outcome.success()).as("串行过账必须成功（这条红了 = 过账闸误杀了正常请求）").isTrue();
        assertThat(stockAfter).as("串行过账单张：库存 = 初始 + 该单数量")
                .isEqualByComparingTo(INITIAL_STOCK.add(QUANTITIES[0]));
        assertThat(rows).as("串行过账台账恰 1 行").hasSize(1);
        assertChain(rows, round);
    }

    // ────────────────────────────────────────────── 判据 2 的判定本体

    /**
     * 台账链：按 id 升序，每行 before == 上一行 after，首行 before == 初始库存，末行 after == 当前库存。
     * 断言消息里带**完整读数** —— 红的时候要能一眼看出「断在哪一行、差多少」。
     */
    private static void assertChain(List<LedgerRow> rows, int round) {
        for (int i = 1; i < rows.size(); i++) {
            assertThat(rows.get(i).beforeQty())
                    .as("台账第 " + (i + 1) + " 行的 before 必须等于第 " + i + " 行的 after"
                            + "（整条链=" + rows + "）—— 修前两行同基（都等于过账前的快照）")
                    .isEqualByComparingTo(rows.get(i - 1).afterQty());
        }
        if (!rows.isEmpty()) {
            assertThat(rows.get(0).beforeQty()).as("链首行的 before 必须等于初始库存（原样读数=" + rows + "）")
                    .isEqualByComparingTo(INITIAL_STOCK);
            assertThat(rows.get(rows.size() - 1).afterQty()).as("链末行的 after 必须等于当前库存")
                    .isEqualByComparingTo(skuStock(round));
        }
    }

    // ────────────────────────────────────────────── 并发装置

    /**
     * {@value #CONCURRENCY} 张单并发过账：每个请求<b>自己的 SqlSession + 自己的连接 + 自己的事务</b>，
     * 用 {@link CyclicBarrier} 对齐到同一时刻起跑（否则线程调度会把它串行化 ⇒ 假绿）。
     */
    private static List<Outcome> runConcurrently(int round) throws Exception {
        ExecutorService pool = Executors.newFixedThreadPool(CONCURRENCY);
        CyclicBarrier barrier = new CyclicBarrier(CONCURRENCY);
        List<Future<Outcome>> futures = new ArrayList<>();
        try {
            for (int i = 0; i < CONCURRENCY; i++) {
                String id = orderId(round, i);
                futures.add(pool.submit(() -> {
                    barrier.await(30, TimeUnit.SECONDS);
                    try (SqlSession s = factory.openSession(false)) {
                        Outcome outcome = postOn(s, id);
                        if (outcome.success()) {
                            s.commit();
                        } else {
                            s.rollback();
                        }
                        return outcome;
                    }
                }));
            }
            List<Outcome> outcomes = new ArrayList<>();
            for (Future<Outcome> f : futures) {
                outcomes.add(f.get(60, TimeUnit.SECONDS));
            }
            return outcomes;
        } finally {
            pool.shutdownNow();
        }
    }

    /** 一次过账请求（真 InboundOrderService + 真库 mapper）。 */
    private static Outcome postOn(SqlSession s, String orderId) {
        try {
            serviceOn(s).post(orderId, TENANT_ID, "tester");
            return new Outcome(true, 200);
        } catch (BusinessException e) {
            return new Outcome(false, e.getHttpStatus());
        }
    }

    private record Outcome(boolean success, int httpStatus) {
    }

    /** 台账一行（真值读取，裸 JDBC 不经被测读面）。 */
    private record LedgerRow(long id, BigDecimal beforeQty, BigDecimal afterQty, BigDecimal delta, String refNo) {
        @Override
        public String toString() {
            return "#" + id + "{before=" + beforeQty.toPlainString() + ", after=" + afterQty.toPlainString()
                    + ", delta=" + delta.toPlainString() + ", ref=" + refNo + "}";
        }
    }

    /** 真装配：本判据的对象（过账闸 + 加库存 + 台账）走<b>真库 mapper</b>。 */
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

    // ────────────────────────────────────────────── 真值读取（裸 JDBC，不经被测读面）

    private static Object scalar(String sql) {
        try (Connection c = dataSource.getConnection();
             Statement st = c.createStatement();
             ResultSet rs = st.executeQuery(sql)) {
            return rs.next() ? rs.getObject(1) : null;
        } catch (SQLException e) {
            throw new IllegalStateException("真值读取失败: " + sql, e);
        }
    }

    private static BigDecimal skuStock(int round) {
        return (BigDecimal) scalar("SELECT stock FROM product_skus WHERE id = " + skuId(round));
    }

    private static List<LedgerRow> ledgerRows(int round) {
        List<LedgerRow> rows = new ArrayList<>();
        try (Connection c = dataSource.getConnection();
             Statement st = c.createStatement();
             ResultSet rs = st.executeQuery("SELECT id, before_qty, after_qty, delta, ref_no"
                     + " FROM stock_ledger_entries WHERE tenant_id = " + TENANT_ID
                     + " AND sku_id = " + skuId(round) + " AND reason = 'inbound' ORDER BY id")) {
            while (rs.next()) {
                rows.add(new LedgerRow(rs.getLong(1), rs.getBigDecimal(2), rs.getBigDecimal(3),
                        rs.getBigDecimal(4), rs.getString(5)));
            }
        } catch (SQLException e) {
            throw new IllegalStateException("台账真值读取失败", e);
        }
        return rows;
    }

    private static BigDecimal quantitiesSum() {
        BigDecimal sum = BigDecimal.ZERO;
        for (BigDecimal q : QUANTITIES) {
            sum = sum.add(q);
        }
        return sum;
    }

    private static long skuId(int round) {
        return 6300000L + round;
    }

    private static String orderId(int round, int index) {
        return "io-6300-r" + round + "-" + index;
    }

    private static String inboundNo(int round, int index) {
        return "RK-6300-R" + round + "-" + index;
    }

    private static long itemId(int round, int index) {
        return 6300000L + round * 10L + index;
    }

    // ────────────────────────────────────────────── schema

    private static String schemaSql() throws IOException {
        Path root = Paths.get(System.getProperty("user.dir")).toAbsolutePath();
        while (root != null
                && !Files.exists(root.resolve("backend/admin-api/src/main/resources/db/init/schema.sql"))) {
            root = root.getParent();
        }
        assertThat(root).as("必须能定位 backend/admin-api/src/main/resources/db/init/schema.sql").isNotNull();
        return Files.readString(root.resolve("backend/admin-api/src/main/resources/db/init/schema.sql"));
    }
}
