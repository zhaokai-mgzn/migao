// case_ids: OR-057

package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.MybatisSqlSessionFactoryBuilder;
import com.baomidou.mybatisplus.extension.plugins.MybatisPlusInterceptor;
import com.baomidou.mybatisplus.extension.plugins.handler.TenantLineHandler;
import com.baomidou.mybatisplus.extension.plugins.inner.TenantLineInnerInterceptor;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.dto.WorkerInboundPostRequest;
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
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;

import javax.sql.DataSource;
import java.io.IOException;
import java.math.BigDecimal;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.sql.Connection;import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.concurrent.CyclicBarrier;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * 真库并发判据（issue #6237）：<b>入库过账的并发面 —— N=4 并发过账同一张 draft 单
 * ⇒ 恰一个赢家、库存恰加一次、{@code stock_batches} / {@code stock_ledger_entries} 各恰 2 行</b>。
 *
 * <h2>核验的是哪一条主张</h2>
 * 台账 {@code after-sales-sideeffect-concurrency-ledger.json} 的 {@code unverified} 条目逐字写着：
 * 「入库过账 = <b>无条件置 POSTED</b> + 逐行 insert {@code stock_batches} ⇒ 并发重复过账可能重复建批次 /
 * 重复入库；本单未核验」。而 issue #5148（V117）已经把过账改成了<b>DB 原子条件更新</b>
 * （{@code InboundOrderMapper#markPosted}：{@code UPDATE … SET status='posted' … WHERE id=? AND
 * tenant_id=? AND status='draft' AND deleted=0}，按影响行数判谁抢到过账权，闸在<b>任何</b>库存写入之前）。
 * ⇒ 本条判据把「主张」变成「读数」：断言那个 CAS 闸在真并发下确实只放一个赢家过去。
 *
 * <h2>为什么必须真库 + 真并发</h2>
 * 缺陷形态是<b>读-判-写</b>。CAS 闸的全部效力来自两件只有真 PG 才有的东西：
 * <b>① 行锁</b>（条件更新的判断与写入是同一条语句，命中行的锁持有到事务结束）、
 * <b>② 条件重估</b>（后到者阻塞到前者提交后，按新版本行重估 {@code status='draft'} ⇒ 影响行数 0）。
 * mock 面结构上判不了：mock 的 {@code updateById} 恒返回 1、也不会因 WHERE 不满足而返回 0
 * ⇒ 「恰一个赢家」在 mock 上恒绿（假绿）。而「一个赢家 ⇒ 库存只加一次 / 批次恰 2 行 / 台账恰 2 行」
 * 是<b>并发下的落库读数</b>，只能从真库取。
 *
 * <h2>判据（每条都会红）</h2>
 * <ol>
 *   <li><b>恰一个赢家</b>：N=4 里成功数 == 1，其余必须 409 CONFLICT（不是 500 / 不是静默成功）；</li>
 *   <li><b>库存恰加一次</b>：{@code product_skus.stock} 增量 == <b>独立算式</b>
 *       （明细两行 {@value #QTY_A} + {@value #QTY_B} = {@value #EXPECTED_STOCK_DELTA}，取夹具常量，
 *       <b>不读被测读面</b>）；重复过账 ⇒ 会等于 4×；</li>
 *   <li><b>批次台账恰 2 行</b>（一个 SKU 行 = 一个批次）× <b>批次号唯一的 DB 约束</b>
 *       （{@code uk_stock_batches_no} 实测在场）⇒ 重复建批次会具名撞红；</li>
 *   <li><b>库存台账恰 2 行</b>（{@code ref_no} = 本单号 ∧ {@code reason='inbound'}）；</li>
 *   <li><b>终态唯一</b>：{@code inbound_orders.status='posted'}，且 {@code posted_by} 恰是那一个赢家的操作人
 *       （重复过账会把「谁在何时过账」覆盖掉）；</li>
 *   <li><b>串行正对照（护栏不误杀）</b>：单个请求串行过账必须成功（{@code tenant_id} / {@code status}
 *       谓词非空 ⇒ 正常请求不被 409 误杀）。</li>
 * </ol>
 *
 * <p>重复 {@value #ROUNDS} 轮（缺陷时序敏感：单轮可能因调度恰好串行而侥幸变绿）。</p>
 *
 * <h2>「真重叠」证据（不是「发了 4 次」就算并发）</h2>
 * 每个请求记录自己的<b>时间区间</b> {@code [start,end]}（同一 {@code System.nanoTime} 基准，单位 ms），
 * 逐轮打印并计算：① 逐对区间求交（有几对真的在时间上重叠）；② <b>并集跨度</b>
 * （{@code max(end) - min(start)}）vs <b>各历时之和</b> —— 并集 &lt; 各历时之和即「同一时刻有多个请求在飞」的
 * 直接读数；若两者相等（区间两两不交）⇒ 这轮是<b>串行</b>，本判据拒绝把它当并发读数（打印告警）。
 *
 * <h2>判别力（红证，注入式 · 双向）</h2>
 * 把 {@code InboundOrderMapper#markPosted} 的 {@code AND status = 'draft'} 谓词摘掉
 * （= 退回「无条件置 POSTED」形态，即台账所疑的那一种）⇒ 本判据必红，
 * 实测读数 = 成功数 <b>4</b> / 库存 <b>+20.0</b> / 批次 <b>8</b> 行 / 台账 <b>8</b> 行。
 * 注入方式与成对读数见 PR body（注入是手动的、一次性的动作，不落成常驻判据）。
 *
 * <p><b>边界（如实登记）</b>：① 本判据跑的是<b>真库并发</b>而非 HTTP 栈
 * （{@code PATCH /api/admin/inbound-orders/{id}} action=post 只是薄转发，状态机与库存写入全在服务层）
 * —— 因此它<b>不</b>证 HTTP 层的行为；② 探针对象全部自建（tenant {@value #TENANT_ID} /
 * 商品前缀 {@code lb-6237}），随一次性临时集群销毁，<b>不碰任何存量数据</b>；
 * ③ 「工人过账」入口（带 {@code Idempotency-Key}）另有一条并发判据见
 * {@link #concurrentPostWithSharedIdempotencyKeyAlsoAddsStockOnce()}，它证的是同键并发下库存也只加一次。</p>
 */
@DisplayName("🔴 真库并发判据（#6237）：N=4 并发过账同一入库单 ⇒ 恰一个赢家 + 库存恰加一次")
class InboundPostConcurrentRealDbTest {

    private static final Long TENANT_ID = 6237L;
    private static final String PRODUCT_ID = "lb-6237-inbound";
    private static final long SKU_ID = 623701L;

    /** 过账前 SKU 库存（夹具常量，独立于被测读面）。 */
    private static final BigDecimal INITIAL_STOCK = new BigDecimal("100.0");
    /** 明细行 A 的入库量。 */
    private static final BigDecimal QTY_A = new BigDecimal("3.0");
    /** 明细行 B 的入库量（**同一 SKU 两行** = 两个批次；覆盖「逐行取批次号」的多行路径）。 */
    private static final BigDecimal QTY_B = new BigDecimal("2.0");

    /** 独立算式：一批次一次库存增量 ⇒ 单次过账的库存增量 = 两行之和。 */
    private static final BigDecimal EXPECTED_STOCK_DELTA = QTY_A.add(QTY_B);
    /** 一个 SKU 行 = 一个批次 ⇒ 单次过账产生 2 行批次 / 2 行台账。 */
    private static final long EXPECTED_ROWS = 2L;

    private static final int CONCURRENCY = 4;
    private static final int ROUNDS = 3;

    /** 留给「串行正对照（护栏不误杀）」的探针单：**不参与**并发装置。 */
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
                    + TENANT_ID + ", 'lb-6237', 'lb-6237')");
            st.execute("INSERT INTO products (id, tenant_id, name, base_price, stock) VALUES ('"
                    + PRODUCT_ID + "', " + TENANT_ID + ", '线B核验-6237入库帘', 150.00, "
                    + INITIAL_STOCK.toPlainString() + ")");
            st.execute("INSERT INTO product_skus (id, tenant_id, product_id, door_width, price, stock, sku_code) VALUES ("
                    + SKU_ID + ", " + TENANT_ID + ", '" + PRODUCT_ID + "', '2.8m', 150.00, "
                    + INITIAL_STOCK.toPlainString() + ", 'SKU-6237-IN')");
            for (int r = 1; r <= SERIAL_ROUND; r++) {
                // 过账前的起点：单据 draft + 两行明细（草稿态 batch_no = NULL，与建单路径同形态）
                st.execute("INSERT INTO inbound_orders (id, tenant_id, inbound_no, status, total_amount, source) VALUES ('"
                        + orderId(r) + "', " + TENANT_ID + ", '" + inboundNo(r) + "', 'draft', 750.0000, 'purchase')");
                st.execute("INSERT INTO inbound_order_items (tenant_id, inbound_order_id, sku_id, product_id, sku_code, quantity, unit_cost, amount) VALUES ("
                        + TENANT_ID + ", '" + orderId(r) + "', " + SKU_ID + ", '"
                        + PRODUCT_ID + "', 'SKU-6237-IN', " + QTY_A.toPlainString() + ", 150.0000, 450.0000)");
                st.execute("INSERT INTO inbound_order_items (tenant_id, inbound_order_id, sku_id, product_id, sku_code, quantity, unit_cost, amount) VALUES ("
                        + TENANT_ID + ", '" + orderId(r) + "', " + SKU_ID + ", '"
                        + PRODUCT_ID + "', 'SKU-6237-IN', " + QTY_B.toPlainString() + ", 150.0000, 300.0000)");
            }
        }

        MybatisConfiguration configuration = new MybatisConfiguration();
        configuration.setMapUnderscoreToCamelCase(true);
        configuration.setEnvironment(new Environment("lb-6237", new JdbcTransactionFactory(), dataSource));
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

    @AfterAll
    static void stopRealPostgres() {
        if (cluster != null) {
            cluster.stop();
        }
    }

    // ────────────────────────────────────────────── 判据 1~5：真库并发

    @Test
    @DisplayName("N=4 并发过账同一入库单（3 轮）：成功数 1 / 库存 +5.0 / 批次 2 行 / 台账 2 行 / 终态 posted")
    void concurrentPostHasExactlyOneWinnerAndOneStockIncrease() throws Exception {
        for (int round = 1; round <= ROUNDS; round++) {
            BigDecimal stockBefore = skuStock();
            List<Outcome> outcomes = runConcurrently(orderId(round), "admin-6237-" + round);

            long success = outcomes.stream().filter(Outcome::success).count();
            List<Integer> loserStatus = outcomes.stream().filter(o -> !o.success)
                    .map(Outcome::httpStatus).toList();
            BigDecimal stockAfter = skuStock();
            long batchRows = scalarLong("SELECT count(*) FROM stock_batches WHERE tenant_id = " + TENANT_ID
                    + " AND inbound_order_id = '" + orderId(round) + "' AND deleted = 0");
            long ledgerRows = scalarLong("SELECT count(*) FROM stock_ledger_entries WHERE tenant_id = "
                    + TENANT_ID + " AND ref_no = '" + inboundNo(round) + "' AND reason = 'inbound'");
            String orderStatus = scalarString(
                    "SELECT status FROM inbound_orders WHERE id = '" + orderId(round) + "'");
            String postedBy = scalarString(
                    "SELECT posted_by FROM inbound_orders WHERE id = '" + orderId(round) + "'");
            long rowsWithBatchNo = scalarLong("SELECT count(*) FROM inbound_order_items WHERE tenant_id = "
                    + TENANT_ID + " AND inbound_order_id = '" + orderId(round) + "' AND batch_no IS NOT NULL");

            // 读数一次全打印（红的时候第一条断言就抛出，没有这行就只有「期望 1 实际 4」，
            // 看不到库存/批次/台账的完整形态）
            System.out.println("[READING #6237 round " + round + "] 成功数=" + success
                    + " 落败状态码=" + loserStatus
                    + " 单终态=" + orderStatus + " posted_by=" + postedBy
                    + " 库存=" + stockBefore.toPlainString() + "→" + stockAfter.toPlainString()
                    + " 批次行=" + batchRows + " 台账行=" + ledgerRows + " 行上批次号=" + rowsWithBatchNo);
            printOverlapEvidence(round, outcomes);

            assertThat(success).as("并发过账同一入库单必须恰一个赢家（其余 409「只有草稿可以过账」）")
                    .isEqualTo(1L);
            assertThat(loserStatus).as("落败请求必须是 409 CONFLICT（不是 500 / 不是静默成功）")
                    .containsOnly(409);
            assertThat(orderStatus).as("单据终态").isEqualTo("posted");
            assertThat(stockAfter.subtract(stockBefore))
                    .as("库存增量必须 == 单次过账量（两行 3.0 + 2.0）；重复入库 ⇒ 会等于 4×5.0 = 20.0")
                    .isEqualByComparingTo(EXPECTED_STOCK_DELTA);
            assertThat(batchRows).as("stock_batches 该单恰 2 行（一个 SKU 行 = 一个批次）；重复过账 ⇒ 8 行")
                    .isEqualTo(EXPECTED_ROWS);
            assertThat(ledgerRows).as("stock_ledger_entries 该单号恰 2 行；重复过账 ⇒ 8 行")
                    .isEqualTo(EXPECTED_ROWS);
            assertThat(rowsWithBatchNo).as("明细行回写批次号恰 2 行（草稿为 NULL ⇒ 过账才有）")
                    .isEqualTo(EXPECTED_ROWS);
            assertThat(postedBy).as("posted_by 必须是那一个赢家的操作人（谁过账的可追责）")
                    .isEqualTo("admin-6237-" + round);
        }
    }

    @Test
    @DisplayName("正对照（护栏不误杀）：单请求串行过账必须成功，且谓词列非空")
    void serialPostStillSucceeds() {
        // 条件更新把 tenant_id / status 放进 WHERE ⇒ 若谓词用到的值为空，SQL 会变成 `tenant_id = null`
        // / `status = null`（恒 0 行）⇒ **所有**过账都会被 409 误杀（不是并发才 409）。
        // 这条正对照与上面那条并发判据合起来才是完整证据：谓词**拦得住并发**且**不误杀正常请求**。
        int round = SERIAL_ROUND;
        Object tenantId = scalar("SELECT tenant_id FROM inbound_orders WHERE id = '" + orderId(round) + "'");
        BigDecimal stockBefore = skuStock();
        try (SqlSession s = factory.openSession(false)) {
            serviceOn(s).post(orderId(round), TENANT_ID, "admin-6237-serial");
            s.commit();
        }
        BigDecimal stockAfter = skuStock();
        String orderStatus = scalarString("SELECT status FROM inbound_orders WHERE id = '" + orderId(round) + "'");
        long batchRows = scalarLong("SELECT count(*) FROM stock_batches WHERE tenant_id = " + TENANT_ID
                + " AND inbound_order_id = '" + orderId(round) + "' AND deleted = 0");
        System.out.println("[READING #6237 正对照 串行] tenant_id=" + tenantId + " 单终态=" + orderStatus
                + " 库存=" + stockBefore.toPlainString() + "→" + stockAfter.toPlainString()
                + " 批次行=" + batchRows);

        assertThat(tenantId).as("条件更新谓词用到的 tenant_id 必须非空（null ⇒ `tenant_id = null` ⇒ 正常过账全被误杀）")
                .isNotNull();
        assertThat(orderStatus).as("串行单请求必须真的过账成功（这条红了 = 谓词误杀正常请求）")
                .isEqualTo("posted");
        assertThat(stockAfter.subtract(stockBefore)).as("串行单请求库存恰加一次")
                .isEqualByComparingTo(EXPECTED_STOCK_DELTA);
        assertThat(batchRows).as("串行单请求批次恰 2 行").isEqualTo(EXPECTED_ROWS);
    }

    // ────────────────────────────────────────────── 判据 6：带 Idempotency-Key 的入口

    @Test
    @DisplayName("带同一个 Idempotency-Key 并发过账（工人入口）：库存仍只加一次 + 恰一份批次/台账")
    void concurrentPostWithSharedIdempotencyKeyAlsoAddsStockOnce() throws Exception {
        // 「工人过账」入口（WorkerInboundService#postDraft）在 InboundOrderService#post 之外还有一层
        // 幂等键闸（ClientRequestIdService.claim = `INSERT … ON CONFLICT (tenant_id, client_request_id)
        // DO NOTHING`，原子性由 DDL 的 UNIQUE 约束提供）。本条证的是：**这一层也挡得住并发**，
        // 且与内层 CAS 闸叠加后，库存/批次/台账仍然只加一次（两层都在，缺任何一层的读数都会变）。
        int round = ROUNDS; // 复用第 3 轮那张单会已被过账 ⇒ 另建一张（tenant 内单号唯一，用 r=0 位）
        // 这里单独建一张只有一行的单，避免与并发装置互踩
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute("INSERT INTO inbound_orders (id, tenant_id, inbound_no, status, total_amount, source, created_by) VALUES ('"
                    + keyOrderId() + "', " + TENANT_ID + ", '" + keyInboundNo() + "', 'draft', 450.0000, 'purchase', 'worker-6237')");
            st.execute("INSERT INTO inbound_order_items (tenant_id, inbound_order_id, sku_id, product_id, sku_code, quantity, unit_cost, amount) VALUES ("
                    + TENANT_ID + ", '" + keyOrderId() + "', " + SKU_ID + ", '"
                    + PRODUCT_ID + "', 'SKU-6237-IN', " + QTY_A.toPlainString() + ", 150.0000, 450.0000)");
        }
        assertThat(round).as("夹具不变量：幂等入口判据独立于并发装置轮次").isPositive();

        String key = "IDEM-6237-CONCURRENT";
        BigDecimal stockBefore = skuStock();
        List<Outcome> outcomes = new ArrayList<>();
        ExecutorService pool = Executors.newFixedThreadPool(CONCURRENCY);
        CyclicBarrier barrier = new CyclicBarrier(CONCURRENCY);
        List<Future<Outcome>> futures = new ArrayList<>();
        try {
            for (int i = 0; i < CONCURRENCY; i++) {
                futures.add(pool.submit(() -> {
                    barrier.await(30, TimeUnit.SECONDS);
                    long start = System.nanoTime();
                    try (SqlSession s = factory.openSession(false)) {
                        workerServiceOn(s).postDraft(keyOrderId(), postRequest(), TENANT_ID, "worker-6237", key);
                        s.commit();
                        return new Outcome(true, 200, start, System.nanoTime());
                    } catch (BusinessException e) {
                        return new Outcome(false, e.getHttpStatus(), start, System.nanoTime());
                    }
                }));
            }
            for (Future<Outcome> f : futures) {
                outcomes.add(f.get(60, TimeUnit.SECONDS));
            }
        } finally {
            pool.shutdownNow();
        }

        long success = outcomes.stream().filter(Outcome::success).count();
        List<Integer> statuses = outcomes.stream().map(Outcome::httpStatus).sorted().toList();
        BigDecimal stockAfter = skuStock();
        long batchRows = scalarLong("SELECT count(*) FROM stock_batches WHERE tenant_id = " + TENANT_ID
                + " AND inbound_order_id = '" + keyOrderId() + "' AND deleted = 0");
        long ledgerRows = scalarLong("SELECT count(*) FROM stock_ledger_entries WHERE tenant_id = "
                + TENANT_ID + " AND ref_no = '" + keyInboundNo() + "' AND reason = 'inbound'");
        long keyRows = scalarLong("SELECT count(*) FROM client_request_keys WHERE tenant_id = " + TENANT_ID
                + " AND client_request_id = '" + key + "' AND endpoint = '" + WorkerInboundService.ENDPOINT_POST + "'");
        System.out.println("[READING #6237 幂等键并发] 成功数=" + success + " 各请求状态码=" + statuses
                + " 库存=" + stockBefore.toPlainString() + "→" + stockAfter.toPlainString()
                + " 批次行=" + batchRows + " 台账行=" + ledgerRows + " 幂等键行=" + keyRows);
        printOverlapEvidence(0, outcomes);

        // 幂等键层在并发下会分出两类落败（都是显式 409，不是静默）：抢到占位者胜；同键落败者
        // 若是占位在飞 ⇒ replay 抛「在途」409；若内层 CAS 先挡下 ⇒ 409「只有草稿可以过账」。
        // 本判据只钉**落库事实**：成功数 ≤ 1 且库存/批次/台账恰一份。
        assertThat(success).as("同键并发过账最多一个请求真正执行（其余走占位/回放 409）")
                .isLessThanOrEqualTo(1L);
        assertThat(statuses).as("非成功请求必须是显式 409（不是 500 / 不是静默成功）")
                .allSatisfy(code -> assertThat(code == 200 || code == 409)
                        .as("状态码只许是 200（赢家）或 409（显式拒绝），实得 " + code).isTrue());
        assertThat(stockAfter.subtract(stockBefore))
                .as("库存必须恰加一次（幂等键层 + 内层 CAS 闸叠加下仍不得重复入库）")
                .isEqualByComparingTo(QTY_A);
        assertThat(batchRows).as("批次恰 1 行（重复入库 ⇒ 4 行）").isEqualTo(1L);
        assertThat(ledgerRows).as("台账恰 1 行（重复入库 ⇒ 4 行）").isEqualTo(1L);
        assertThat(keyRows).as("幂等键恰 1 行（DB UNIQUE (tenant_id, client_request_id) 兜底）").isEqualTo(1L);
    }

    // ────────────────────────────────────────────── 并发装置

    /**
     * N=4 并发过账：每个请求<b>自己的 SqlSession + 自己的连接 + 自己的事务</b>，
     * 用 {@link CyclicBarrier} 把 4 个请求对齐到同一时刻起跑（否则线程调度会把它串行化 ⇒ 假绿）。
     */
    private static List<Outcome> runConcurrently(String orderId, String operator) throws Exception {
        ExecutorService pool = Executors.newFixedThreadPool(CONCURRENCY);
        CyclicBarrier barrier = new CyclicBarrier(CONCURRENCY);
        List<Future<Outcome>> futures = new ArrayList<>();
        try {
            for (int i = 0; i < CONCURRENCY; i++) {
                futures.add(pool.submit(() -> {
                    barrier.await(30, TimeUnit.SECONDS);
                    long start = System.nanoTime();
                    try (SqlSession s = factory.openSession(false)) {
                        serviceOn(s).post(orderId, TENANT_ID, operator);
                        s.commit();
                        return new Outcome(true, 200, start, System.nanoTime());
                    } catch (BusinessException e) {
                        return new Outcome(false, e.getHttpStatus(), start, System.nanoTime());
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

    /**
     * 「真重叠」证据：逐对区间求交 + 并集跨度 vs 各历时之和。
     *
     * <p>「发了 4 次」不是并发证据；<b>时间区间相交</b>才是。并集跨度 &lt; 各历时之和
     * ⇒ 同一时刻确有多个请求在飞（差值 = 被重叠掉的时间）。两者相等 ⇒ 这轮实际是串行，
     * 打印告警（本判据不把串行轮当并发读数）。</p>
     */
    private static void printOverlapEvidence(int round, List<Outcome> outcomes) {
        long base = outcomes.stream().mapToLong(Outcome::startNanos).min().orElse(0L);
        record Interval(long start, long end) {
        }
        List<Interval> intervals = outcomes.stream()
                .map(o -> new Interval((o.startNanos() - base) / 1_000_000L, (o.endNanos() - base) / 1_000_000L))
                .sorted(Comparator.comparingLong(Interval::start)).toList();
        int overlappingPairs = 0;
        for (int i = 0; i < intervals.size(); i++) {
            for (int j = i + 1; j < intervals.size(); j++) {
                if (Math.min(intervals.get(i).end(), intervals.get(j).end())
                        > Math.max(intervals.get(i).start(), intervals.get(j).start())) {
                    overlappingPairs++;
                }
            }
        }
        long sum = intervals.stream().mapToLong(iv -> iv.end() - iv.start()).sum();
        long union = intervals.isEmpty() ? 0L
                : intervals.get(intervals.size() - 1).end() - intervals.get(0).start();
        boolean trulyOverlapping = union < sum;
        System.out.println("[真重叠 #6237 " + (round == 0 ? "幂等键并发" : "round " + round) + "] 区间(ms, 同一起点)="
                + intervals.stream().map(iv -> "[" + iv.start() + "," + iv.end() + "]").toList()
                + " 相交对数=" + overlappingPairs + "/" + (intervals.size() * (intervals.size() - 1) / 2)
                + " 并集跨度=" + union + "ms 各历时之和=" + sum + "ms"
                + " ⇒ " + (trulyOverlapping ? "真重叠（并集 < 各历时之和）" : "⚠️ 本轮区间两两不交 = 实际串行"));
    }

    /** 一次并发请求的结果（成功 / 失败 + HTTP 业务码 + 自己的时间区间）。 */
    private record Outcome(boolean success, int httpStatus, long startNanos, long endNanos) {
    }

    /** 真装配：本判据的对象（过账状态机 + 库存 + 批次 + 台账）走<b>真库 mapper</b>。 */
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

    /**
     * 工人过账入口的真装配（{@link WorkerInboundService#postDraft}）：内层过账走真库 mapper，
     * 幂等键层走<b>真</b> {@link ClientRequestIdService}（真 JdbcTemplate ⇒ 真
     * {@code client_request_keys} 行与 ON CONFLICT 判据）。
     */
    private static WorkerInboundService workerServiceOn(SqlSession s) {
        // ObjectProvider 不是函数式接口（它继承 ObjectFactory 之外还带静态字段与多个 default 方法）
        // ⇒ 这里只实现唯一抽象方法 getObject()（getIfAvailable() 的 default 实现就是委托给它）
        ObjectProvider<JdbcTemplate> provider = new ObjectProvider<>() {
            @Override
            public JdbcTemplate getObject() {
                return new JdbcTemplate(dataSource);
            }
        };
        ClientRequestIdService clientRequestIdService = new ClientRequestIdService(provider, new ObjectMapper());
        InboundLabelService inboundLabelService = mock(InboundLabelService.class);
        when(inboundLabelService.ensureLabels(any(Long.class), any(String.class),
                anyList(), any(String.class))).thenReturn(List.of());
        return new WorkerInboundService(serviceOn(s), mock(ImageRecognitionClient.class),
                clientRequestIdService, s.getMapper(ProductMapper.class), s.getMapper(ProductSkuMapper.class),
                inboundLabelService);
    }

    private static WorkerInboundPostRequest postRequest() {
        WorkerInboundPostRequest req = new WorkerInboundPostRequest();
        req.setConfirmed(Boolean.TRUE);
        return req;
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

    private static String orderId(int round) {
        return "io-6237-r" + round;
    }

    private static String inboundNo(int round) {
        return "RK-6237-R" + round;
    }

    private static String keyOrderId() {
        return "io-6237-idem";
    }

    private static String keyInboundNo() {
        return "RK-6237-IDEM";
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
