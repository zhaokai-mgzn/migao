// case_ids: AS-011

package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.MybatisSqlSessionFactoryBuilder;
import com.baomidou.mybatisplus.extension.plugins.MybatisPlusInterceptor;
import com.baomidou.mybatisplus.extension.plugins.handler.TenantLineHandler;
import com.baomidou.mybatisplus.extension.plugins.inner.TenantLineInnerInterceptor;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.dto.AfterSalesStatusUpdateRequest;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.AfterSalesTicketMapper;
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
import com.migao.admin.mapper.TicketTimelineMapper;
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
 * 真库并发判据（issue #6220）：<b>同一张 {@code processing} 工单被 N=4 并发完结 ⇒ 恰一个赢家、
 * 库存回补恰一次、台账恰 1 行、时间线恰 2 行</b>。
 *
 * <h2>为什么必须真库 + 真并发</h2>
 * 缺陷形态是<b>读-判-写</b>：{@code selectById} 读到 {@code processing} → 应用层比对流转表 →
 * {@code updateById} <b>无条件覆盖</b> → 随后在同一分支里跑副作用（{@code linkRefundToOrderAndFinance}
 * 有 DB 原子条件更新；{@code maybeRestockOnReturn → OrderService.restoreStockForReturn} 零保护）。
 * ⇒ mock 面结构上判不了这件事：mock 的 {@code updateById} 恒返回 1、也不会因为「WHERE 条件不满足」
 * 而返回 0；「条件更新是否真的只放一个赢家过去」只有真 PG 的行锁 + 条件重估能给读数。
 *
 * <h2>装置（与 #5167/#5192/#3881 同源口径）</h2>
 * 一次性真 PG 集群（{@link PgCluster#startOrAbort()}），schema 取
 * {@code backend/admin-api/src/main/resources/db/init/schema.sql}（bootstrap 终态，<b>不手抄列清单</b>）。
 * 每个并发请求 = <b>自己的 SqlSession + 自己的连接 + 自己的事务</b>（{@code openSession(false)}
 * + 显式 commit/rollback）—— 生产侧同款边界由 {@code updateTicketStatus} 的
 * {@code @Transactional(rollbackFor = Exception.class)} 提供；共用一条连接会让 4 个请求串行化，
 * 那不是「并发」，判据会变成假绿。
 *
 * <h2>判据（每条都会红；红证 = 把条件更新摘回无条件 {@code updateById} ⇒ 第 1 条起全红）</h2>
 * <ol>
 *   <li>成功数 == {@value #CONCURRENCY} 里的 <b>1</b>（其余必须 409 CONFLICT + 中文文案）；</li>
 *   <li>{@code product_skus.stock} 增量 == <b>单次回补量</b>（独立算式 = 订单明细数量 {@value #EXPECTED_RESTOCK}，
 *       <b>不取被测读面</b>）；</li>
 *   <li>{@code stock_ledger_entries} 该 {@code ref_no} <b>恰 1 行</b>；</li>
 *   <li>{@code ticket_timeline} 的 {@code status_change} <b>恰 2 行</b>
 *       （{@code pending→processing} + {@code processing→resolved}）；</li>
 *   <li><b>正对照</b>：{@code orders.refund_amount} == 单次金额（同一事务里的另一个副作用有 DB 护栏
 *       ⇒ 它在修前也是绿的 —— 这条绿证明「判据有判别力」而不是「装置什么都判不出来」）。</li>
 * </ol>
 *
 * <p>重复 {@value #ROUNDS} 轮（缺陷是时序敏感的：单轮可能因调度恰好串行而侥幸变绿，
 * 见 issue #6220 的 C21 读数 {@code [[200,200,200,422],[200,200,200,200],[200,200,200,200]]}）。</p>
 *
 * <p><b>边界（如实登记）</b>：① 本判据跑的是<b>真库并发</b>而非 HTTP 栈（{@code PUT /status} 控制器
 * 只是薄转发，状态机/副作用全在服务层）；② 探针对象全部自建（tenant {@value #TENANT_ID} /
 * 商品前缀 {@code lb-6220}），用完即随临时集群销毁，<b>不碰任何存量数据</b>；
 * ③ 本文件<b>不改</b> {@code maybeRestockOnReturn} 的「整单回补 vs 商品开关」业务语义（那是产品裁定）。</p>
 */
@DisplayName("🔴 真库并发判据（#6220）：N=4 并发完结同一工单 ⇒ 恰一个赢家 + 回补恰一次")
class AfterSalesConcurrentResolveRealDbTest {

    private static final Long TENANT_ID = 6220L;
    private static final String PRODUCT_ID = "lb-6220-restock";
    private static final long SKU_ID = 622001L;
    private static final BigDecimal INITIAL_STOCK = new BigDecimal("98");

    /** 单次回补量的<b>独立算式</b>：订单明细数量（fixture 常量，不读被测读面） */
    private static final BigDecimal EXPECTED_RESTOCK = new BigDecimal("2");
    private static final BigDecimal REFUND_AMOUNT = new BigDecimal("300");

    private static final int CONCURRENCY = 4;
    private static final int ROUNDS = 3;

    /** 留给「正对照（护栏不误杀）」的探针工单号：**不参与**并发装置。 */
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
                    + TENANT_ID + ", 'lb-6220', 'lb-6220')");
            // 商品开关 allow_return_restock=TRUE ⇒ 完结时按 #2991 口径**回补整单库存**
            st.execute("INSERT INTO products (id, tenant_id, name, base_price, stock, allow_return_restock) VALUES ('"
                    + PRODUCT_ID + "', " + TENANT_ID + ", '线B验收-6220回补帘', 150.00, "
                    + INITIAL_STOCK.toPlainString() + ", TRUE)");
            st.execute("INSERT INTO product_skus (id, tenant_id, product_id, door_width, price, stock, sku_code) VALUES ("
                    + SKU_ID + ", " + TENANT_ID + ", '" + PRODUCT_ID + "', '2.8m', 150.00, "
                    + INITIAL_STOCK.toPlainString() + ", 'SKU-6220-R')");
            for (int r = 1; r <= SERIAL_ROUND; r++) {
                st.execute("INSERT INTO orders (id, tenant_id, order_no, status, total_amount, actual_amount, refund_amount) VALUES ('"
                        + orderId(r) + "', " + TENANT_ID + ", 'ORD-6220-R" + r + "', 'confirmed', "
                        + REFUND_AMOUNT.toPlainString() + ", " + REFUND_AMOUNT.toPlainString() + ", 0)");
                // processing_info 声明 skuId ⇒ 回补路径能定位到 SKU（#4090 的 matchSkuId 单一口径）
                st.execute("INSERT INTO order_items (id, tenant_id, order_id, product_id, product_name, quantity, unit_price, subtotal, processing_info) VALUES ('"
                        + itemId(r) + "', " + TENANT_ID + ", '" + orderId(r) + "', '" + PRODUCT_ID
                        + "', '线B验收-6220回补帘', " + EXPECTED_RESTOCK.toPlainString() + ", 150.00, "
                        + REFUND_AMOUNT.toPlainString() + ", '{\"skuId\": " + SKU_ID + "}'::jsonb)");
                st.execute("INSERT INTO after_sales_tickets (id, tenant_id, ticket_no, order_id, ticket_type, status, refund_amount) VALUES ('"
                        + ticketId(r) + "', " + TENANT_ID + ", '" + ticketNo(r) + "', '" + orderId(r)
                        + "', 'return', 'pending', " + REFUND_AMOUNT.toPlainString() + ")");
            }
        }

        MybatisConfiguration configuration = new MybatisConfiguration();
        configuration.setMapUnderscoreToCamelCase(true);
        configuration.setEnvironment(new Environment("lb-6220", new JdbcTransactionFactory(), dataSource));
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
        for (Class<?> mapper : List.of(AfterSalesTicketMapper.class, OrderMapper.class, OrderItemMapper.class,
                ProductMapper.class, ProductSkuMapper.class, TicketTimelineMapper.class, StockLedgerMapper.class)) {
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
    @DisplayName("N=4 并发 processing→resolved（3 轮）：成功数 1 / 库存 +2 / 台账 1 行 / 时间线 2 行 / 退款 300")
    void concurrentResolveHasExactlyOneWinnerAndOneRestock() throws Exception {
        for (int round = 1; round <= ROUNDS; round++) {
            // ── 前置：串行推进 pending → processing（这一步本身无钱/库存副作用，只造出可并发的起点）
            try (SqlSession s = factory.openSession(true)) {
                serviceOn(s).updateTicketStatus(ticketId(round), statusRequest("processing", "客服已受理"));
            }

            BigDecimal stockBefore = skuStock();
            List<Outcome> outcomes = runConcurrently(ticketId(round), "resolved", "客户已退货，完结");

            long success = outcomes.stream().filter(o -> o.success).count();
            List<Integer> loserStatus = outcomes.stream().filter(o -> !o.success)
                    .map(Outcome::httpStatus).toList();
            String ticketStatus = scalarString(
                    "SELECT status FROM after_sales_tickets WHERE id = '" + ticketId(round) + "'");
            BigDecimal stockAfter = skuStock();
            long ledgerRows = scalarLong("SELECT count(*) FROM stock_ledger_entries WHERE tenant_id = "
                    + TENANT_ID + " AND ref_no = '" + ticketNo(round) + "' AND reason = 'aftersales'");
            long timelineRows = scalarLong("SELECT count(*) FROM ticket_timeline WHERE ticket_id = '"
                    + ticketId(round) + "' AND action = 'status_change'");
            BigDecimal refund = scalarDecimal(
                    "SELECT refund_amount FROM orders WHERE id = '" + orderId(round) + "'");

            // 读数一次全打印（修前/修后都能逐字读出「到底重复了几次」——红的时候第一条断言就抛出，
            // 没有这行就只有「期望 1 实际 4」，看不到库存/台账/时间线的完整形态）
            System.out.println("[READING #6220 round " + round + "] 成功数=" + success
                    + " 落败状态码=" + loserStatus
                    + " 工单终态=" + ticketStatus
                    + " 库存=" + stockBefore.toPlainString() + "→" + stockAfter.toPlainString()
                    + " 台账行=" + ledgerRows + " 时间线行=" + timelineRows
                    + " 退款=" + (refund == null ? "null" : refund.toPlainString()));

            assertThat(success).as("并发完结同一工单必须恰一个赢家（其余 409「已被他人变更」）")
                    .isEqualTo(1L);
            assertThat(loserStatus).as("落败请求必须是 409 CONFLICT（不是 500 / 静默成功）")
                    .containsOnly(409);
            assertThat(ticketStatus).as("工单终态").isEqualTo("resolved");
            assertThat(stockAfter.subtract(stockBefore))
                    .as("库存增量必须 == 单次回补量（订单明细 2 米）；重复回补 ⇒ 会等于 4×2")
                    .isEqualByComparingTo(EXPECTED_RESTOCK);
            assertThat(ledgerRows).as("stock_ledger_entries 该 ref_no 恰 1 行（重复回补 ⇒ 4 行）")
                    .isEqualTo(1L);
            assertThat(timelineRows).as("status_change 恰 2 行（pending→processing + processing→resolved）")
                    .isEqualTo(2L);
            assertThat(refund).as("正对照：退款恰一次（同事务另一副作用有 DB 原子条件更新护栏）")
                    .isEqualByComparingTo(REFUND_AMOUNT);
        }
    }

    @Test
    @DisplayName("正对照（护栏不误杀）：单个请求串行 processing→resolved 必须成功，且 tenant_id 谓词非空")
    void serialResolveStillSucceeds() {
        // 条件更新把 tenant_id 也放进 WHERE ⇒ 若 ticket.getTenantId() 为 null，
        // SQL 会变成 `tenant_id = null`（恒 0 行）⇒ **所有**状态流转都会被 409 误杀（不是并发才 409）。
        // 这条正对照与上面那条并发判据合起来才是完整证据：谓词**拦得住并发**且**不误杀正常请求**。
        int round = SERIAL_ROUND;
        try (SqlSession s = factory.openSession(true)) {
            serviceOn(s).updateTicketStatus(ticketId(round), statusRequest("processing", "客服已受理"));
        }
        Object tenantId = scalar("SELECT tenant_id FROM after_sales_tickets WHERE id = '" + ticketId(round) + "'");
        BigDecimal stockBefore = skuStock();
        try (SqlSession s = factory.openSession(true)) {
            serviceOn(s).updateTicketStatus(ticketId(round), statusRequest("resolved", "客户已退货，完结"));
        }
        BigDecimal stockAfter = skuStock();
        String ticketStatus = scalarString(
                "SELECT status FROM after_sales_tickets WHERE id = '" + ticketId(round) + "'");
        long ledgerRows = scalarLong("SELECT count(*) FROM stock_ledger_entries WHERE tenant_id = "
                + TENANT_ID + " AND ref_no = '" + ticketNo(round) + "' AND reason = 'aftersales'");
        long timelineRows = scalarLong("SELECT count(*) FROM ticket_timeline WHERE ticket_id = '"
                + ticketId(round) + "' AND action = 'status_change'");
        System.out.println("[READING #6220 正对照 串行] tenant_id=" + tenantId + " 工单终态=" + ticketStatus
                + " 库存=" + stockBefore.toPlainString() + "→" + stockAfter.toPlainString()
                + " 台账行=" + ledgerRows + " 时间线行=" + timelineRows);

        assertThat(tenantId).as("条件更新谓词用到的 tenant_id 必须非空（null ⇒ `tenant_id = null` ⇒ 正常流转全被误杀）")
                .isNotNull();
        assertThat(ticketStatus).as("串行单请求必须真的流转成功（这条红了 = 谓词误杀正常请求）")
                .isEqualTo("resolved");
        assertThat(stockAfter.subtract(stockBefore)).as("串行单请求回补恰一次")
                .isEqualByComparingTo(EXPECTED_RESTOCK);
        assertThat(ledgerRows).as("串行单请求台账恰 1 行").isEqualTo(1L);
        assertThat(timelineRows).as("串行单请求时间线恰 2 行").isEqualTo(2L);
    }

    // ────────────────────────────────────────────── 并发装置

    /**
     * N=4 并发完结：每个请求<b>自己的 SqlSession + 自己的连接 + 自己的事务</b>，
     * 用 {@link CyclicBarrier} 把 4 个请求对齐到同一时刻起跑（否则线程调度会把它串行化 ⇒ 假绿）。
     */
    private static List<Outcome> runConcurrently(String ticketId, String status, String remark) throws Exception {
        ExecutorService pool = Executors.newFixedThreadPool(CONCURRENCY);
        CyclicBarrier barrier = new CyclicBarrier(CONCURRENCY);
        List<Future<Outcome>> futures = new ArrayList<>();
        try {
            for (int i = 0; i < CONCURRENCY; i++) {
                futures.add(pool.submit(() -> {
                    barrier.await(30, TimeUnit.SECONDS);
                    try (SqlSession s = factory.openSession(false)) {
                        serviceOn(s).updateTicketStatus(ticketId, statusRequest(status, remark));
                        s.commit();
                        return new Outcome(true, 200);
                    } catch (BusinessException e) {
                        return new Outcome(false, e.getHttpStatus());
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

    /** 一次并发请求的结果（成功 / 失败 + HTTP 业务码） */
    private record Outcome(boolean success, int httpStatus) {
    }

    private static AfterSalesStatusUpdateRequest statusRequest(String status, String remark) {
        AfterSalesStatusUpdateRequest request = new AfterSalesStatusUpdateRequest();
        request.setStatus(status);
        request.setRemark(remark);
        return request;
    }

    /** 真装配：本判据的对象（工单状态流转 + 退款联动 + 库存回补 + 台账）走<b>真库 mapper</b>。 */
    private static AfterSalesTicketService serviceOn(SqlSession s) {
        StockLedgerService stockLedgerService = new StockLedgerService(
                s.getMapper(StockLedgerMapper.class), s.getMapper(ProductSkuMapper.class));
        OrderService orderService = new OrderService(
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
        return new AfterSalesTicketService(
                s.getMapper(AfterSalesTicketMapper.class),
                s.getMapper(OrderMapper.class),
                s.getMapper(OrderItemMapper.class),
                s.getMapper(ProductMapper.class),
                s.getMapper(TicketTimelineMapper.class),
                mock(FinanceService.class),
                orderService,
                new ObjectMapper(),
                mock(NotificationService.class),
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

    private static long scalarLong(String sql) {
        Object v = scalar(sql);
        return v == null ? 0L : ((Number) v).longValue();
    }

    private static BigDecimal scalarDecimal(String sql) {
        return (BigDecimal) scalar(sql);
    }

    private static String scalarString(String sql) {
        Object v = scalar(sql);
        return v == null ? null : v.toString();
    }

    private static BigDecimal skuStock() {
        return scalarDecimal("SELECT stock FROM product_skus WHERE id = " + SKU_ID);
    }

    private static String ticketId(int round) {
        return "t-6220-r" + round;
    }

    private static String ticketNo(int round) {
        return "AS-6220-R" + round;
    }

    private static String orderId(int round) {
        return "o-6220-r" + round;
    }

    private static String itemId(int round) {
        return "oi-6220-r" + round;
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
