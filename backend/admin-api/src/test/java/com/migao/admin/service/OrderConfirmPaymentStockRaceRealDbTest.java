// case_ids: OR-062

package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.MybatisSqlSessionFactoryBuilder;
import com.baomidou.mybatisplus.extension.plugins.MybatisPlusInterceptor;
import com.baomidou.mybatisplus.extension.plugins.handler.TenantLineHandler;
import com.baomidou.mybatisplus.extension.plugins.inner.TenantLineInnerInterceptor;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.FinanceTransactionMapper;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderLogisticsMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProcessingFeeCombinationMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import com.migao.admin.mapper.ProductMapper;
import com.migao.admin.mapper.ProductSkuMapper;
import com.migao.admin.mapper.ProductionRouteRuleMapper;
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
 * 真库并发判据（issue #6299）：<b>库存 10 米的 SKU、两张各 8 米的订单并发确认收款 ⇒ 恰一单成功、
 * 库存绝不为负、台账 before/after 首尾相接</b>。
 *
 * <h2>为什么必须真库 + 真并发</h2>
 * 缺陷形态是 <b>读-判-写</b>：{@code confirmPayment} 走
 * {@code validateStockSufficient}（SELECT 读快照 → 应用层比 {@code stock >= needed}）→
 * {@code transitionStatusAtomic} → {@code deductStock}。并发下两个请求都读到 10 米、都判「够」，
 * 而 {@code deductStock} 的 SQL 是
 * {@code SET stock = GREATEST(COALESCE(stock,0) - qty, 0)} —— <b>无下限谓词 + 静默钳 0</b>
 * ⇒ 两单都 200、库存被钳到 0（扣 10 而不是 16）⇒ <b>超卖 6 米且无任何 4xx</b>。
 * ⇒ mock 面结构上判不了：mock 的 {@code deductStock} 恒返回 1、也不会因为「WHERE 条件不满足」
 * 而返回 0；「条件更新是否真的只放一个赢家过去」只有真 PG 的行锁 + 条件重估能给读数。
 *
 * <p>生产现场读数（main，{@code sha-6838a05}）：
 * {@code acceptance/2026-10-04/replay-postdeploy/race/probe-write-raw.json::cases.W4} ——
 * {@code statuses=[200,200]}、{@code stockBefore=10.0}、{@code stockAfter=0.0}；
 * 同探针 {@code chainBad} 记 {@code prevAfter=2.0 curBefore=10.0}（台账同基、链断裂）。
 * 顺序路径的判别性对照 {@code control-seq-oversell.json}：首单 200（10→2）、第二单
 * <b>422「库存不足：需要 8 米，当前仅剩 2.0 米」</b> ⇒ 缺口只在并发路径。</p>
 *
 * <h2>装置（与 #6220 / #5167 同源口径）</h2>
 * 一次性真 PG 集群（{@link PgCluster#startOrAbort()}），schema 取
 * {@code backend/admin-api/src/main/resources/db/init/schema.sql}（bootstrap 终态，<b>不手抄列清单</b>）。
 * 每个并发请求 = <b>自己的 SqlSession + 自己的连接 + 自己的事务</b>（{@code openSession(false)}
 * + 显式 commit/rollback）—— 共用一条连接会把两个请求串行化，那不是「并发」，判据会变成假绿。
 *
 * <h2>判据（每条都会红）</h2>
 * <ol>
 *   <li><b>恰一个赢家</b>：成功数 == 1，落败方必须是 422（「库存不足」文案），<b>不是</b> 200、不是 500；</li>
 *   <li><b>库存不得超卖</b>：{@code stock_after == max(初始 - 成功单数量, 0)}，且 <b>{@code stock >= 0}</b>
 *       —— 独立算式，不取被测读面；修前读数是 {@code 0.0}（8+8=16 只扣了 10）；</li>
 *   <li><b>台账链式相接</b>：{@code stock_ledger_entries} 本 SKU 的 order 行按 id 升序，
 *       每一行的 {@code before_qty} 必须等于上一行的 {@code after_qty}，且首行 before == 初始库存、
 *       末行 after == 当前库存。修前两行 before 都是 {@code 10.0}（同基）⇒ 当场红。</li>
 * </ol>
 *
 * <p>重复 {@value #ROUNDS} 轮（缺陷是时序敏感的：单轮可能因调度恰好串行而侥幸变绿）。</p>
 *
 * <p><b>边界（如实登记）</b>：① 本判据跑的是<b>真库并发</b>而非 HTTP 栈（控制器只是薄转发）；
 * ② 探针对象全部自建（tenant {@value #TENANT_ID} / 商品前缀 {@code stock-race-6299}），
 * 用完随临时集群销毁，<b>不碰任何存量数据</b>；③ {@code financeTransactionMapper} 在夹具里是 mock
 * （本判据判的是库存与台账，不是资金流水线）。</p>
 */
@DisplayName("🔴 真库并发判据（#6299）：库存 10 米 / 两单各 8 米并发确认收款 ⇒ 恰一单成功 + 不超卖 + 台账链相接")
class OrderConfirmPaymentStockRaceRealDbTest {

    private static final Long TENANT_ID = 6299L;
    private static final String PRODUCT_ID = "stock-race-6299";
    private static final String SKU_CODE = "SKU-6299-R";
    /** 独立算式（fixture 常量，不读被测读面）：初始库存 10 米。 */
    private static final BigDecimal INITIAL_STOCK = new BigDecimal("10");
    /** 每单扣减量 = 8 米（{@link #ORDER_QTY}）。 */
    private static final BigDecimal ORDER_QTY = new BigDecimal("8");
    private static final int CONCURRENCY = 2;
    private static final int ROUNDS = 3;
    /** 留给「正对照（护栏不误杀）」的轮次：**不参与**并发装置。 */
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
            st.execute("INSERT INTO tenants (id, name, code) OVERRIDING SYSTEM VALUE VALUES ("
                    + TENANT_ID + ", 'stock-race-6299', 'stock-race-6299')");
            st.execute("INSERT INTO products (id, tenant_id, name, base_price, stock) VALUES ('"
                    + PRODUCT_ID + "', " + TENANT_ID + ", '线B验收-6299超卖帘', 150.00, "
                    + INITIAL_STOCK.toPlainString() + ")");
            // 每个轮次一个**独立 SKU**（同一 SKU 跨轮会互相污染库存读数）；
            // 每个 SKU 上挂 {@link #CONCURRENCY} 张各 {@link #ORDER_QTY} 米的 pending 单
            for (int r = 1; r <= SERIAL_ROUND; r++) {
                st.execute("INSERT INTO product_skus (id, tenant_id, product_id, door_width, price, stock, sku_code) VALUES ("
                        + skuId(r) + ", " + TENANT_ID + ", '" + PRODUCT_ID + "', '2.8m', 150.00, "
                        + INITIAL_STOCK.toPlainString() + ", '" + SKU_CODE + "-R" + r + "')");
                for (int i = 1; i <= CONCURRENCY; i++) {
                    st.execute("INSERT INTO orders (id, tenant_id, order_no, status, total_amount, actual_amount) VALUES ('"
                            + orderId(r, i) + "', " + TENANT_ID + ", '" + orderNo(r, i) + "', 'pending', "
                            + ORDER_QTY.multiply(new BigDecimal("150")).toPlainString() + ", "
                            + ORDER_QTY.multiply(new BigDecimal("150")).toPlainString() + ")");
                    // processing_info 声明 skuId ⇒ 扣减路径能定位到 SKU（#4090 的 matchSkuId 单一口径）
                    st.execute("INSERT INTO order_items (id, tenant_id, order_id, product_id, product_name, quantity, unit_price, subtotal, processing_info) VALUES ('"
                            + itemId(r, i) + "', " + TENANT_ID + ", '" + orderId(r, i) + "', '" + PRODUCT_ID
                            + "', '线B验收-6299超卖帘', " + ORDER_QTY.toPlainString() + ", 150.00, "
                            + ORDER_QTY.multiply(new BigDecimal("150")).toPlainString()
                            + ", '{\"skuId\": " + skuId(r) + "}'::jsonb)");
                }
            }
        }

        MybatisConfiguration configuration = new MybatisConfiguration();
        configuration.setMapUnderscoreToCamelCase(true);
        configuration.setEnvironment(new Environment("stock-race-6299", new JdbcTransactionFactory(), dataSource));
        // 多租户拦截器**必须在场**：生产 SQL 会经它重写（追加 tenant_id）⇒ 少了它就只测了 mapper 原文
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
        for (Class<?> mapper : List.of(OrderMapper.class, OrderItemMapper.class, ProductMapper.class,
                ProductSkuMapper.class, StockLedgerMapper.class)) {
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
    @DisplayName("两单各 8 米并发确认收款（3 轮）：成功数 1 / 落败 422 / 库存不为负 / 台账链相接")
    void concurrentConfirmPaymentCannotOversell() throws Exception {
        for (int round = 1; round <= ROUNDS; round++) {
            BigDecimal stockBefore = skuStock(round);
            List<Outcome> outcomes = runConcurrently(round);
            long success = outcomes.stream().filter(Outcome::success).count();
            List<Integer> loserStatus = outcomes.stream().filter(o -> !o.success)
                    .map(Outcome::httpStatus).toList();
            BigDecimal stockAfter = skuStock(round);
            List<LedgerRow> rows = ledgerRows(round);
            BigDecimal expectedAfter = INITIAL_STOCK.subtract(
                    ORDER_QTY.multiply(BigDecimal.valueOf(success)));

            System.out.println("[READING #6299 round " + round + "] 成功数=" + success
                    + " 落败状态码=" + loserStatus
                    + " 库存=" + stockBefore.toPlainString() + "→" + stockAfter.toPlainString()
                    + " 台账=" + rows);

            assertThat(success).as("并发确认收款：库存 10 米只够一单 8 米 ⇒ 恰一个赢家"
                            + "（修前读数 = [200,200]，两单都成功）")
                    .isEqualTo(1L);
            assertThat(loserStatus).as("落败请求必须是 422「库存不足」（不是 200 静默成功、也不是 500）")
                    .containsOnly(422);
            assertThat(stockAfter).as("库存绝不为负（修前被 GREATEST 静默钳到 0 —— 钳 0 掩盖了超扣）")
                    .isGreaterThanOrEqualTo(BigDecimal.ZERO);
            assertThat(stockAfter).as("库存 = 初始 − 成功单扣减量（独立算式；修前 = 0.0，扣了 10 而不是 16）")
                    .isEqualByComparingTo(expectedAfter);
            assertThat(rows).as("两单都落台账、且 before/after 首尾相接（修前两行 before 都是 10.0 —— 同基）")
                    .hasSize((int) success);
            assertChain(rows, round);
        }
    }

    @Test
    @DisplayName("正对照（护栏不误杀）：库存 10 米 / 单张 8 米串行确认收款必须成功，库存 10→2")
    void serialConfirmPaymentStillSucceeds() {
        int round = SERIAL_ROUND;
        Outcome outcome;
        try (SqlSession s = factory.openSession(false)) {
            outcome = confirmOn(s, orderId(round, 1));
            if (outcome.success()) {
                s.commit();
            } else {
                s.rollback();
            }
        }
        BigDecimal stockAfter = skuStock(round);
        List<LedgerRow> rows = ledgerRows(round);
        System.out.println("[READING #6299 正对照 串行] 状态=" + outcome.httpStatus()
                + " 库存=" + INITIAL_STOCK.toPlainString() + "→" + stockAfter.toPlainString()
                + " 台账=" + rows);

        assertThat(outcome.success()).as("串行单请求必须成功（这条红了 = 谓词/文案把正常请求误杀了）").isTrue();
        assertThat(stockAfter).as("串行单请求扣减恰一次（与 issue 正文的顺序对照读数逐值一致：10→2）")
                .isEqualByComparingTo("2");
        assertThat(rows).as("串行单请求台账恰 1 行").hasSize(1);
        assertChain(rows, round);
    }

    // ────────────────────────────────────────────── 判据 3 的判定本体

    /**
     * 台账链：按 id 升序，每行 before == 上一行 after，首行 before == 初始库存，末行 after == 当前库存。
     * 断言消息里带上**完整读数** —— 修前红的时候要能一眼看出「断在哪一行、差多少」。
     */
    private static void assertChain(List<LedgerRow> rows, int round) {
        for (int i = 1; i < rows.size(); i++) {
            assertThat(rows.get(i).beforeQty())
                    .as("台账第 " + (i + 1) + " 行的 before 必须等于第 " + i + " 行的 after"
                            + "（整条链=" + rows + "）")
                    .isEqualByComparingTo(rows.get(i - 1).afterQty());
        }
        if (!rows.isEmpty()) {
            assertThat(rows.get(0).beforeQty()).as("链首行的 before 必须等于初始库存")
                    .isEqualByComparingTo(INITIAL_STOCK);
            assertThat(rows.get(rows.size() - 1).afterQty()).as("链末行的 after 必须等于当前库存")
                    .isEqualByComparingTo(skuStock(round));
        }
    }

    // ────────────────────────────────────────────── 并发装置

    /**
     * {@value #CONCURRENCY} 张单并发确认收款：每个请求<b>自己的 SqlSession + 自己的连接 + 自己的事务</b>，
     * 用 {@link CyclicBarrier} 对齐到同一时刻起跑（否则线程调度会把它串行化 ⇒ 假绿）。
     */
    private static List<Outcome> runConcurrently(int round) throws Exception {
        ExecutorService pool = Executors.newFixedThreadPool(CONCURRENCY);
        CyclicBarrier barrier = new CyclicBarrier(CONCURRENCY);
        List<Future<Outcome>> futures = new ArrayList<>();
        try {
            for (int i = 1; i <= CONCURRENCY; i++) {
                String id = orderId(round, i);
                futures.add(pool.submit(() -> {
                    barrier.await(30, TimeUnit.SECONDS);
                    try (SqlSession s = factory.openSession(false)) {
                        Outcome outcome = confirmOn(s, id);
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

    /** 一次确认收款请求（真 OrderService + 真库 mapper）。 */
    private static Outcome confirmOn(SqlSession s, String orderId) {
        try {
            orderServiceOn(s).confirmPayment(orderId);
            return new Outcome(true, 200);
        } catch (BusinessException e) {
            return new Outcome(false, e.getHttpStatus());
        }
    }

    /** 一次请求的结果（成功 / 失败 + HTTP 业务码）。 */
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

    /** 真装配：本判据的对象（状态流转 + 库存扣减 + 台账）走<b>真库 mapper</b>。 */
    private static OrderService orderServiceOn(SqlSession s) {
        StockLedgerService stockLedgerService = new StockLedgerService(
                s.getMapper(StockLedgerMapper.class), s.getMapper(ProductSkuMapper.class));
        return new OrderService(
                s.getMapper(OrderMapper.class),
                s.getMapper(OrderItemMapper.class),
                mock(OrderLogisticsMapper.class),
                mock(CustomerService.class),
                s.getMapper(ProductMapper.class),
                s.getMapper(ProductSkuMapper.class),
                mock(FinanceTransactionMapper.class),
                new ObjectMapper(),
                mock(NotificationService.class),
                mock(ProcessingOrderMapper.class),
                mock(UserService.class),
                mock(ClientRequestIdService.class),
                stockLedgerService,
                new ProcessingFeeCalculator(mock(ProcessingFeeCombinationMapper.class),
                        mock(ProductionRouteRuleMapper.class)),
                mock(ProcessingFeeCombinationCommandService.class));
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
                     + " AND sku_id = " + skuId(round) + " ORDER BY id")) {
            while (rs.next()) {
                rows.add(new LedgerRow(rs.getLong(1), rs.getBigDecimal(2), rs.getBigDecimal(3),
                        rs.getBigDecimal(4), rs.getString(5)));
            }
        } catch (SQLException e) {
            throw new IllegalStateException("台账真值读取失败", e);
        }
        return rows;
    }

    private static long skuId(int round) {
        return 6299000L + round;
    }

    private static String orderId(int round, int index) {
        return "o-6299-r" + round + "-" + index;
    }

    private static String orderNo(int round, int index) {
        return "ORD-6299-R" + round + "-" + index;
    }

    private static String itemId(int round, int index) {
        return "oi-6299-r" + round + "-" + index;
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
