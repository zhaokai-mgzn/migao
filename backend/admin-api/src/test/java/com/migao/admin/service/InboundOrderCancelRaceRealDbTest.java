// case_ids: OR-066

package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.MybatisSqlSessionFactoryBuilder;
import com.baomidou.mybatisplus.extension.plugins.MybatisPlusInterceptor;
import com.baomidou.mybatisplus.extension.plugins.handler.TenantLineHandler;
import com.baomidou.mybatisplus.extension.plugins.inner.TenantLineInnerInterceptor;
import com.migao.admin.dto.InboundOrderResponse;
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
import org.junit.jupiter.api.AfterEach;
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
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;

/**
 * 🔴 真库并发判据（issue #6928）：<b>入库单「过账 × 作废」交叉竞态 ⇒ 至多一个赢家，
 * 且「已作废的单」不得改库存 / 不得留下入库台账行</b>。
 *
 * <h2>核验的是哪一条主张</h2>
 * {@link InboundOrderService#post} 有过账权的**条件更新 CAS**（{@code InboundOrderMapper#markPosted}：
 * {@code … WHERE id=? AND tenant_id=? AND status='draft' AND deleted=0}，0 行 ⇒ 409），而修前
 * {@link InboundOrderService#cancel} **没有**：先读内存旧值判 {@code STATUS_DRAFT}，再
 * {@code inboundOrderMapper.updateById(order)}（WHERE 仅主键 ⇒ 无谓词）。两个写面**不互斥** ⇒
 * {@code post} 在窗口内抢到过账权并提交（库存 +5 米、台账 1 行），{@code cancel} 随后**无条件**
 * 把该单覆写成 {@code cancelled}：同一张单既回 200 又落在 {@code cancelled}，
 * 而库存与入库台账**静默留在库里**（账实不符、无任何 4xx）。生产复现读数 3/20（15%）。
 *
 * <h2>为什么必须真库 + 窗口注入</h2>
 * 缺陷形态是**读-判-写**。CAS 的全部效力来自只有真 PG 才有的两件事：<b>① 行锁</b>（条件更新的
 * 判断与写入是同一条语句，命中行的锁持有到事务结束）、<b>② 条件重估</b>（后到者阻塞到前者提交后
 * 按新版本行重估 {@code status='draft'} ⇒ 影响行数 0）。mock 面结构上判不了：mock 的
 * {@code updateById} 恒返回 1、也不会因 WHERE 不满足而返回 0 ⇒ 修前形态在 mock 上恒绿（假绿）。
 * 而窗口只有微秒级（HTTP 层 20 轮实测只命中 3 轮）⇒ 用
 * {@link InboundOrderService#setCancelProbePauseMillisForTest}（生产恒为 0）把窗口放大，
 * 判据才是**确定性**的，而不是 flake。
 *
 * <h2>判据（每条都会红）</h2>
 * <ol>
 *   <li><b>至多一个赢家</b>：{@code post} 与 {@code cancel} 并发 ⇒ 成功数 == 1，落败方必须是
 *       <b>409 CONFLICT</b>（不是 200 静默成功、不是 500）；</li>
 *   <li><b>终态与赢家一致</b>：赢家是 {@code post} ⇒ 终态 {@code posted}；赢家是 {@code cancel}
 *       ⇒ 终态 {@code cancelled}。**两个请求都回 200** ⇒ 直接判红（生产缺陷形态）；</li>
 *   <li><b>账实一致（独立算式）</b>：终态 {@code cancelled} ⇒ 库存变化 <b>0</b> 且该单号
 *       {@code reason='inbound'} 的 {@code stock_ledger_entries} <b>0</b> 行；终态 {@code posted}
 *       ⇒ 库存增量 == 明细行入库量（{@value #QTY}，取夹具常量、**不读被测读面**）且台账恰 1 行。
 *       「已作废的单改了库存 / 留了台账」= 修前实测形态 ⇒ 本条红；</li>
 *   <li><b>串行正对照（护栏不误杀）</b>：不作废、只并发过账的对照单必须真的过账成功
 *       （谓词非空 ⇒ 正常请求不被 409 误杀）。</li>
 * </ol>
 *
 * <p>重复 {@value #ROUNDS} 轮（每轮一张独立草稿单 + 独立单号）。</p>
 *
 * <h2>判别力（红证，注入式 · 双向）</h2>
 * 修前（{@code cancel} 走无谓词 {@code updateById}）本判据 <b>3/3 轮全红</b>，逐字读数
 * {@code post=200 cancel=200 db=cancelled delta=+5.0 ledger=1}；修后（{@code cancel} 走
 * {@code markCancelled} 的 CAS）<b>3/3 轮全绿</b>。撤回注入（{@code pauseMillis=0}）时
 * 两条控制判据仍绿 ⇒ 「注入放大」就是本判据确定性的来源。
 *
 * <p><b>边界（如实登记）</b>：① 本判据跑的是<b>服务层真库并发</b>而非 HTTP 栈
 * （{@code PATCH /api/admin/inbound-orders/{id}} 的 {@code action=post/cancel} 只是薄转发，
 * 状态机与库存写入全在服务层）—— 因此它<b>不</b>证 HTTP 层的行为（HTTP 层旁证见
 * {@code acceptance/2026-10-14/line3-aftersales-race/}）；② 探针对象全部自建
 * （tenant {@value #TENANT_ID} / 商品前缀 {@code lb-6928}），随一次性临时集群销毁，
 * <b>不碰任何存量数据</b>；③ 判定「两个请求都 200」用的不是响应体而是**落库事实**：两个请求
 * 都成功时 {@code post} 的库存/台账写入一定已提交 ⇒ 由第 2/3 条判红，无需额外埋点。</p>
 */
@DisplayName("🔴 真库并发判据（#6928）：入库单「过账 × 作废」交叉竞态 ⇒ 至多一个赢家 + 账实一致")
class InboundOrderCancelRaceRealDbTest {

    private static final Long TENANT_ID = 6928L;
    private static final String PRODUCT_ID = "lb-6928-inbound";
    private static final long SKU_ID = 692801L;

    /** 过账前 SKU 库存（夹具常量，独立于被测读面）。 */
    private static final BigDecimal INITIAL_STOCK = new BigDecimal("100.0");
    /** 明细行入库量（单行单批次）。 */
    private static final BigDecimal QTY = new BigDecimal("5.0");

    /** 每轮的独立单（round 1..ROUNDS 走交叉竞态；SERIAL_ROUND 与 POST_ONLY_ROUND 走控制）。 */
    private static final int ROUNDS = 3;
    private static final int SERIAL_ROUND = ROUNDS + 1;
    private static final int POST_ONLY_ROUND = ROUNDS + 2;

    /** 窗口注入时长（毫秒）：必须显著大于 {@code post} 那条路的全程（实测 ~10~30ms）。 */
    private static final long PAUSE_MILLIS = 800L;
    /** 等「探针已进入窗口」的上限（确定性时序的护栏；超时 = 判据装置坏了）。 */
    private static final long PAUSE_WAIT_MILLIS = 10_000L;

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
                    + TENANT_ID + ", 'lb-6928', 'lb-6928')");
            st.execute("INSERT INTO products (id, tenant_id, name, base_price, stock) VALUES ('"
                    + PRODUCT_ID + "', " + TENANT_ID + ", '线③核验-6928入库帘', 150.00, "
                    + INITIAL_STOCK.toPlainString() + ")");
            st.execute("INSERT INTO product_skus (id, tenant_id, product_id, door_width, price, stock, sku_code) VALUES ("
                    + SKU_ID + ", " + TENANT_ID + ", '" + PRODUCT_ID + "', '2.8m', 150.00, "
                    + INITIAL_STOCK.toPlainString() + ", 'SKU-6928-IN')");
            for (int r = 1; r <= POST_ONLY_ROUND; r++) {
                // 过账前的起点：单据 draft + 一行明细（草稿态 batch_no = NULL，与建单路径同形态）
                st.execute("INSERT INTO inbound_orders (id, tenant_id, inbound_no, status, total_amount, source) VALUES ('"
                        + orderId(r) + "', " + TENANT_ID + ", '" + inboundNo(r) + "', 'draft', 750.0000, 'purchase')");
                st.execute("INSERT INTO inbound_order_items (tenant_id, inbound_order_id, sku_id, product_id, sku_code, quantity, unit_cost, amount) VALUES ("
                        + TENANT_ID + ", '" + orderId(r) + "', " + SKU_ID + ", '"
                        + PRODUCT_ID + "', 'SKU-6928-IN', " + QTY.toPlainString() + ", 150.0000, 750.0000)");
            }
        }

        MybatisConfiguration configuration = new MybatisConfiguration();
        configuration.setMapUnderscoreToCamelCase(true);
        configuration.setEnvironment(new Environment("lb-6928", new JdbcTransactionFactory(), dataSource));
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
        for (Class<?> mapper : List.of(InboundOrderMapper.class, InboundOrderItemMapper.class,
                StockBatchMapper.class, ProductSkuMapper.class, StockLedgerMapper.class, ProductMapper.class)) {
            configuration.addMapper(mapper);
        }
        factory = new MybatisSqlSessionFactoryBuilder().build(configuration);
    }

    @AfterEach
    void clearProbe() {
        InboundOrderService.setCancelProbePauseMillisForTest(0L);
    }

    @AfterAll
    static void stopRealPostgres() {
        InboundOrderService.setCancelProbePauseMillisForTest(0L);
        if (cluster != null) {
            cluster.stop();
        }
    }

    // ────────────────────────────────────────────── 判据 1~3：交叉竞态（注入放大窗口）

    @Test
    @DisplayName("过账 × 作废交叉竞态（3 轮）：至多一个赢家 + 终态与赢家一致 + 「已作废」不得改库存/留台账")
    void concurrentPostAndCancelHaveAtMostOneWinner() throws Exception {
        InboundOrderService.setCancelProbePauseMillisForTest(PAUSE_MILLIS);
        for (int round = 1; round <= ROUNDS; round++) {
            // 每轮的对象名先在循环外取成 effectively-final 常量（lambda 引用约束），
            // 也让「读到的单号」在整轮里逐字一致（不随 round 漂）
            final String target = orderId(round);
            BigDecimal stockBefore = skuStock();

            // ① cancel 先起跑：它会读到 draft、判定通过，然后**在窗口里暂停**
            ExecutorService pool = Executors.newSingleThreadExecutor();
            Future<Verdict> cancelFuture = pool.submit(() -> runOne("cancel", target));
            // ② 等它真的进了窗口（确定性时序 —— 不是 sleep 猜时间）
            awaitCancelProbePaused();

            // ③ 窗口内让 post 走完整条路（CAS + 库存 + 批次 + 台账），并提交
            Verdict post = runOne("post", target);
            Verdict cancel = cancelFuture.get(60, TimeUnit.SECONDS);
            pool.shutdown();

            BigDecimal stockAfter = skuStock();
            BigDecimal delta = stockAfter.subtract(stockBefore);
            long ledgerRows = ledgerRows(inboundNo(round));
            String dbStatus = scalarString("SELECT status FROM inbound_orders WHERE id = '" + orderId(round) + "'");
            long successes = (post.status == 200 ? 1 : 0) + (cancel.status == 200 ? 1 : 0);

            System.out.println("[READING #6928 round " + round + "] post=" + post.status + "(" + post.detail + ")"
                    + " cancel=" + cancel.status + "(" + cancel.detail + ")"
                    + " 成功数=" + successes
                    + " 单终态=" + dbStatus
                    + " 库存=" + stockBefore.toPlainString() + "→" + stockAfter.toPlainString()
                    + " 台账行=" + ledgerRows);

            assertThat(successes)
                    .as("过账与作废争同一份状态迁移权 ⇒ 至多一个赢家（两个都 200 就是修前的缺陷形态）")
                    .isLessThanOrEqualTo(1L);
            if (successes == 1) {
                assertThat(cancel.status == 200 || cancel.status == 409)
                        .as("落败方必须是显式 409 CONFLICT（不是 500 / 不是静默成功），实得 " + cancel.status)
                        .isTrue();
                assertThat(post.status == 200 || post.status == 409)
                        .as("落败方必须是显式 409 CONFLICT（不是 500 / 不是静默成功），实得 " + post.status)
                        .isTrue();
            }
            // 终态与赢家一致
            assertThat(dbStatus)
                    .as("单终态必须与赢家一致（cancel 赢 ⇒ cancelled；post 赢 ⇒ posted）")
                    .isEqualTo(cancel.status == 200 ? "cancelled" : "posted");
            if ("cancelled".equals(dbStatus)) {
                assertThat(delta)
                        .as("**已作废的单不得改库存**（修前实测 +5.0 —— 库存静默留在库里）")
                        .isEqualByComparingTo(BigDecimal.ZERO);
                assertThat(ledgerRows)
                        .as("**已作废的单不得留下入库台账行**（修前实测 1 行）")
                        .isZero();
            } else {
                assertThat(delta).as("过账赢 ⇒ 库存恰加一次 == 明细行入库量")
                        .isEqualByComparingTo(QTY);
                assertThat(ledgerRows).as("过账赢 ⇒ 该单号入库台账恰 1 行").isEqualTo(1L);
            }
        }
    }

    // ────────────────────────────────────────────── 判据 4：正对照（护栏不误杀）

    @Test
    @DisplayName("正对照（护栏不误杀）：无窗口注入时并发过账仍恰一个赢家、库存恰加一次")
    void concurrentPostOnlyStillHasExactlyOneWinner() throws Exception {
        int round = SERIAL_ROUND;
        BigDecimal stockBefore = skuStock();
        List<Verdict> outcomes = runBoth("post", "post", orderId(round));
        BigDecimal stockAfter = skuStock();
        long ledgerRows = ledgerRows(inboundNo(round));
        String dbStatus = scalarString("SELECT status FROM inbound_orders WHERE id = '" + orderId(round) + "'");
        long successes = outcomes.stream().filter(v -> v.status == 200).count();
        System.out.println("[READING #6928 正对照 串行] 各状态码="
                + outcomes.stream().map(v -> String.valueOf(v.status)).toList()
                + " 成功数=" + successes + " 单终态=" + dbStatus
                + " 库存=" + stockBefore.toPlainString() + "→" + stockAfter.toPlainString()
                + " 台账行=" + ledgerRows);

        assertThat(successes).as("并发过账同一草稿单必须恰一个赢家（其余 409）").isEqualTo(1L);
        assertThat(dbStatus).as("单终态").isEqualTo("posted");
        assertThat(stockAfter.subtract(stockBefore))
                .as("库存恰加一次 == {}；重复入库 ⇒ 会等于 2×", QTY.toPlainString())
                .isEqualByComparingTo(QTY);
        assertThat(ledgerRows).as("入库台账恰 1 行；重复过账 ⇒ 2 行").isEqualTo(1L);
    }

    @Test
    @DisplayName("正对照（作废侧护栏不误杀）：无并发时作废草稿单必须成功、库存与台账零变化")
    void serialCancelStillSucceeds() {
        // 谓词带 status='draft' ⇒ 若谓词写错（如把 status 写成常量 null），**所有**作废都会被 409 误杀。
        // 这条与上面的判据合起来才是完整证据：CAS **拦得住并发**且**不误杀正常请求**。
        int round = POST_ONLY_ROUND;
        BigDecimal stockBefore = skuStock();
        Verdict cancel = runOne("cancel", orderId(round));
        BigDecimal stockAfter = skuStock();
        long ledgerRows = ledgerRows(inboundNo(round));
        String dbStatus = scalarString("SELECT status FROM inbound_orders WHERE id = '" + orderId(round) + "'");
        System.out.println("[READING #6928 正对照 作废] cancel=" + cancel.status + "(" + cancel.detail + ")"
                + " 单终态=" + dbStatus + " 库存=" + stockBefore.toPlainString() + "→" + stockAfter.toPlainString()
                + " 台账行=" + ledgerRows);

        assertThat(cancel.status).as("串行单请求作废必须成功（这条红了 = 谓词误杀正常请求）").isEqualTo(200);
        assertThat(dbStatus).as("单终态").isEqualTo("cancelled");
        assertThat(stockAfter).as("作废不动库存").isEqualByComparingTo(stockBefore);
        assertThat(ledgerRows).as("作废不留入库台账").isZero();
    }

    // ────────────────────────────────────────────── 并发装置

    /** 一次请求的结果（HTTP 业务码 + 文本锚；服务层用异常的业务码等价表达）。 */
    private record Verdict(int status, long startNanos, long endNanos, String detail) {
    }

    private static Verdict runOne(String action, String orderId) {
        long start = System.nanoTime();
        try (SqlSession s = factory.openSession(false)) {
            InboundOrderService service = serviceOn(s);
            if ("post".equals(action)) {
                InboundOrderResponse resp = service.post(orderId, TENANT_ID, "admin-6928");
                s.commit();
                return new Verdict(200, start, System.nanoTime(), "resp=" + resp.getStatus());
            }
            InboundOrderResponse resp = service.cancel(orderId, "lb-6928-race", TENANT_ID, "admin-6928");
            s.commit();
            return new Verdict(200, start, System.nanoTime(), "resp=" + resp.getStatus());
        } catch (BusinessException e) {
            // 业务异常 = 显式 4xx（本判据只认 200 / 409 两种；500 会让下面的断言红）
            return new Verdict(e.getHttpStatus(), start, System.nanoTime(), "msg=" + e.getMessage());
        }
    }

    /** 两个动作并发起跑（各用**自己的连接 + 自己的事务**），用 CyclicBarrier 对齐同一时刻。 */
    private static List<Verdict> runBoth(String actionA, String actionB, String orderId) throws Exception {
        ExecutorService pool = Executors.newFixedThreadPool(2);
        java.util.concurrent.CyclicBarrier barrier = new java.util.concurrent.CyclicBarrier(2);
        try {
            Future<Verdict> a = pool.submit(() -> {
                barrier.await(30, TimeUnit.SECONDS);
                return runOne(actionA, orderId);
            });
            Future<Verdict> b = pool.submit(() -> {
                barrier.await(30, TimeUnit.SECONDS);
                return runOne(actionB, orderId);
            });
            return List.of(a.get(60, TimeUnit.SECONDS), b.get(60, TimeUnit.SECONDS));
        } finally {
            pool.shutdownNow();
        }
    }

    /**
     * 等「探针已进入暂停窗口」——**确定性时序**的锚点（不是 {@code sleep} 猜时间）。
     *
     * <p>进入窗口 = cancel 已经读到 {@code draft} 并判定通过，而尚未落库 ⇒ 此刻让 post 走完，
     * 正好落在缺陷的读-判-写窗口里。超时 ⇒ 判据装置坏了（探针没插上 / 单不是 draft），
     * 当场判红而不是静默继续（静默继续会让本判据退化成 flake）。</p>
     */
    private static void awaitCancelProbePaused() throws Exception {
        long deadline = System.nanoTime() + TimeUnit.MILLISECONDS.toNanos(PAUSE_WAIT_MILLIS);
        while (System.nanoTime() < deadline) {
            if (InboundOrderService.cancelProbePausedForTest()) {
                return;
            }
            Thread.sleep(1L);
        }
        throw new IllegalStateException(
                "探针未在 " + PAUSE_WAIT_MILLIS + "ms 内进入窗口（判据装置坏了：探针没插上 / 单不是 draft）");
    }

    /** 真装配：本判据的对象（状态机 + 库存 + 批次 + 台账）走<b>真库 mapper</b>。 */
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
                stockLedgerService, null, null);
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

    private static String scalarString(String sql) {
        Object v = scalar(sql);
        return v == null ? null : v.toString();
    }

    private static BigDecimal skuStock() {
        return (BigDecimal) scalar("SELECT stock FROM product_skus WHERE id = " + SKU_ID);
    }

    /** 该单号的入库台账行数（{@code ref_no} = 入库单号 ∧ {@code reason='inbound'}）。 */
    private static long ledgerRows(String inboundNo) {
        return scalarLong("SELECT count(*) FROM stock_ledger_entries WHERE tenant_id = " + TENANT_ID
                + " AND ref_no = '" + inboundNo + "' AND reason = 'inbound'");
    }

    private static String orderId(int round) {
        return "io-6928-r" + round;
    }

    private static String inboundNo(int round) {
        return "RK-6928-R" + round;
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
