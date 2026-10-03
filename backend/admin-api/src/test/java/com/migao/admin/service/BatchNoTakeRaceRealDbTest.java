// case_ids: OR-059

package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.MybatisSqlSessionFactoryBuilder;
import com.baomidou.mybatisplus.extension.plugins.MybatisPlusInterceptor;
import com.baomidou.mybatisplus.extension.plugins.handler.TenantLineHandler;
import com.baomidou.mybatisplus.extension.plugins.inner.TenantLineInnerInterceptor;
import com.migao.admin.entity.StockBatch;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.InboundOrderItemMapper;
import com.migao.admin.mapper.InboundOrderMapper;
import com.migao.admin.mapper.InboundOrderQueryMapper;
import com.migao.admin.mapper.ProductMapper;
import com.migao.admin.mapper.ProductSkuMapper;
import com.migao.admin.mapper.StockBatchMapper;
import com.migao.admin.mapper.StockLedgerMapper;
import com.migao.admin.time.BusinessClock;
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
import java.lang.reflect.Field;
import java.math.BigDecimal;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.sql.Connection;
import java.sql.ResultSet;
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
import java.util.concurrent.atomic.AtomicInteger;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;

/**
 * 真库并发判据（issue #6248）：<b>入库批次号 {@code nextFreeBatchNo} 的<b>跨请求</b>取号竞争
 * —— 哪条路径可达、撞 {@code uk_stock_batches_no} 时用户侧看到什么</b>。
 *
 * <h2>核验的是哪一条主张</h2>
 * {@code #6237} 的核验包在台账 {@code after-sales-sideeffect-concurrency-ledger.json} 的
 * {@code coverage_boundary} 里逐字登记了这条<b>边界</b>：
 * 「{@code nextFreeBatchNo} 的跨请求批次号竞争（不同单并发取号撞 {@code uk_stock_batches_no}
 * ⇒ 那会显式失败并回滚，不是重复入库 —— 本单只登记该边界，<b>未开单核验其重试语义</b>）」。
 * 本单把这条边界变成读数。
 *
 * <h2>被核验的三段代码（{@code InboundOrderService}）</h2>
 * <ol>
 *   <li>{@code generateBatchNo()} = {@code AtomicInteger BATCH_SEQ.incrementAndGet() % 10_000}
 *       —— <b>进程内</b>原子计数器，取模 10000（当天号段 {@code 0001..9999, 0000} 循环）；</li>
 *   <li>{@code nextFreeBatchNo(tenantId)} = <b>check-then-insert</b>：{@code exists(tenant_id, batch_no)}
 *       为假就返回，重试上限 20 次，耗尽抛 {@code BATCH_NO_EXHAUSTED}(409)；</li>
 *   <li>过账主循环里<b>逐行</b>调用它（一个 SKU 行 = 一个批次，V111 裁定）</li>
 * </ol>
 *
 * <h2>本单先给出的逐字答案（读数在下面四条判据里，主判据取库内事实）</h2>
 * <ul>
 *   <li><b>同进程并发不可达</b>（判据 1）：{@code incrementAndGet()} 是原子的 ⇒ N=4 个不同单并发
 *       过账各自拿到<b>不同</b>候选，20 次重试只在候选被占时才触发；</li>
 *   <li><b>可达路径 = 多实例 / 重启</b>（判据 3）：计数器是<b>进程内</b>的 ⇒ 两个实例（或重启后的
 *       新进程）在同一位置取号会拿到<b>同一候选</b>；此时 {@code exists} 与 {@code insert} 之间的
 *       窗口可被另一事务利用 ⇒ 撞唯一索引；</li>
 *   <li><b>撞索引时用户看到的是 500</b>（判据 4）：{@code stock_batchMapper.insert(..)} 抛的
 *       {@code DuplicateKeyException} 在 {@code post(..)} 里<b>没有任何 catch</b>
 *       （本类唯一一处 {@code catch (DuplicateKeyException)} 在 {@code create(..)} 的单号路径上）
 *       ⇒ 20 次重试<b>只覆盖「生成时已存在」</b>，<b>不覆盖「插入时被抢」</b>；</li>
 *   <li><b>耗尽 20 次 ⇒ 409 语义正确</b>（判据 5）：{@code BATCH_NO_EXHAUSTED} 是显式拒绝
 *       （不静默用重复号），但文案「当天号段疑似被占满」只覆盖「号段满」这一种成因，
 *       不覆盖「计数器和库不同步」这一实际主因。</li>
 * </ul>
 *
 * <h2>为什么必须真 PG</h2>
 * 缺陷是<b>读-判-写</b>（{@code exists} 假 ⇒ 返回候选 ⇒ <b>之后</b>才 insert）。
 * 窗口的<b>可利用性</b>全部来自真 PG 的两件事：<b>① 唯一索引在插入那一刻的原子判定</b>
 * （{@code uk_stock_batches_no}）、<b>② 未提交行对并发事务的可见性规则</b>
 * （B 的 {@code SELECT} 看不见 A 未提交的行 ⇒ 两边 {@code exists} 都为假）。mock 面上
 * {@code exists} 恒返回 false、{@code insert} 恒成功 —— 「窗口能不能被利用」在 mock 上
 * <b>结构上不可见</b>。而「撞了之后库存 / 批次行 / 单终态变成什么样」只能从真库读。
 *
 * <h2>判别力（红证，注入式 · 双向）</h2>
 * 判据 4 内建<b>窗口注入</b>：用 {@code InboundOrderService} 的测试探针
 * {@code setBatchNoProbePauseMillisForTest(400)} 在 {@code exists} 判定与 insert 之间拉长 400ms，
 * 并让两个过账者的计数器都从同一位置起步（{@code BATCH_SEQ} = 0）⇒ 两边 {@code exists} 都为假
 * ⇒ 一个先提交、另一个的 insert 撞唯一索引。注入撤回（{@code 0}）后复绿。
 *
 * <p><b>边界（如实登记）</b>：① 本判据跑的是<b>服务层 + 真库</b>而非 HTTP 栈
 * （{@code PATCH /api/admin/inbound-orders/{id}} action=post 是薄转发，状态机与库存写入全在服务层）
 * ⇒ 它<b>不</b>证 HTTP 层，只证「异常类型 ⇒ 全局处理器把非 Business 异常读成 500」这条映射
 * （{@code GlobalExceptionHandler} 只对 {@code BusinessException} 取业务码，其余走
 * {@code @ExceptionHandler(Exception.class)}）；② 「两个实例」用<b>同一 JVM 内两份
 * {@code StockBatchMapper} 会话 + 同一进程内计数器</b>表达（计数器本就是进程内的 ⇒ 两实例同起点
 * 正是重启 / 多副本的真实形态）；③ 探针对象全部自建（tenant {@value #TENANT_ID} / 商品前缀
 * {@code lb-6248}），随一次性临时集群销毁，<b>不碰任何存量数据</b>。</p>
 */
@DisplayName("🔴 真库并发判据（#6248）：入库批次号跨请求取号 —— 单实例不撞 / 多实例同起点撞唯一索引 / 耗尽 409")
class BatchNoTakeRaceRealDbTest {

    private static final Long TENANT_ID = 6248L;
    private static final Long EXHAUST_TENANT_ID = 6249L;
    private static final String PRODUCT_ID = "lb-6248-inbound";
    private static final long SKU_ID = 624801L;
    private static final long EXHAUST_SKU_ID = 624901L;

    /** 过账前 SKU 库存（夹具常量，独立于被测读面）。 */
    private static final BigDecimal INITIAL_STOCK = new BigDecimal("100.0");
    /** 明细行的入库量。 */
    private static final BigDecimal QTY = new BigDecimal("3.0");

    private static final int CONCURRENCY = 4;
    private static final int ROUNDS = 3;

    /** 窗口注入的时长：把「{@code exists} 判定 → insert」之间的窗口拉长到必然可被另一事务利用。 */
    private static final long WINDOW_PAUSE_MILLIS = 400L;


    /** 判据 5 的号段耗尽构造：占用当天 {@code 0001..0020} 共 20 个号（= 重试上限）。 */
    private static final int EXHAUST_OCCUPIED = 20;

    private static final AtomicInteger ORDER_SEQ = new AtomicInteger(0);

    /**
     * 租户拦截器注入的租户（**按线程**）：拦截器把 {@code tenant_id} 追加进每条 SQL ⇒ 若把它写死成
     * {@value #TENANT_ID}，判据 5 的 {@value #EXHAUST_TENANT_ID} 夹具就<b>读不出来</b>
     * （生产里会变成 {@code AND tenant_id = 6248 AND tenant_id = 6249} ⇒ 恒 0 行 ⇒ 404），
     * 而那不是被测代码的缺陷、是装置的缺陷（本判据第一版正是这样红了一次）。
     */
    private static final ThreadLocal<Long> TENANT = ThreadLocal.withInitial(() -> TENANT_ID);

    /**
     * 注入面（**纯测试侧，两条**）：{@code delayMillis} 给「写号」那一步加延时；
     * {@code hazardMode} 让<b>占用检查恒答「没人占」</b>（= 模拟「另一事务刚在检查与写入之间抢走该号」
     * 这个窗口 —— 两个实例的进程内计数器从同一位置起步时，真实窗口正是这样被利用的）。
     *
     * <p>为什么不用 Mockito：判据必须打<b>真 mapper</b>（唯一索引的原子判定是主判据），mock 会把
     * 「DB 判占用」换成恒真返回 ⇒ 判据当场失去意义。这里用 {@link java.lang.reflect.Proxy} 包一层：
     * 除被注入的两个方法外<b>全部原样转发</b>给真 mapper（写入仍走真库、唯一索引仍是真判据）。</p>
     *
     * <p>两条注入对**两条路径**的语义：<br>
     * ① 旧路径（{@code exists} 判假 ⇒ 之后 {@code insert}）：hazard 让 exists 恒答假 ⇒ 必撞唯一索引
     * ⇒ {@code DuplicateKeyException} ⇒ 用户侧 500；<br>
     * ② 新路径（{@code update(} = 判占用 + 占用一条语句）：受影响行数 0 ⇒ 换候选重来 ⇒ 复绿。
     * 这正是「注入式 · 双向」的同一份注入。</p>
     */
    private static final AtomicInteger INSERT_DELAY_MILLIS = new AtomicInteger(0);
    private static final java.util.concurrent.atomic.AtomicBoolean HAZARD_MODE =
            new java.util.concurrent.atomic.AtomicBoolean(false);
    /**
     * 写号前的**会合点**（2 方）：两个过账者必须都先「取到候选号」，才允许任何一方去写。
     *
     * <p>为什么需要它：原子计数器本身会给两边**不同**的候选（各 +1）⇒ 天然不会撞；而真实的多实例
     * 竞争里两边的计数器是<b>各自</b>的、都从同一位置起步 ⇒ 两边拿到<b>同一个</b>候选。会合点就是把
     * 「两边同时取到同一个候选」这件事做出来（非注入形态下它由「两个进程各自的计数器」提供）。</p>
     */
    private static volatile CyclicBarrier candidateRendezvous = null;

    private static PgCluster cluster;
    private static DataSource dataSource;
    private static SqlSessionFactory factory;
    private static final BusinessClock BUSINESS_CLOCK = new BusinessClock();

    @BeforeAll
    static void startRealPostgresAndFixtures() throws Exception {
        cluster = PgCluster.startOrAbort();
        dataSource = cluster.dataSource();
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute(schemaSql());
            st.execute("INSERT INTO tenants (id, name, code) OVERRIDING SYSTEM VALUE VALUES ("
                    + TENANT_ID + ", 'lb-6248', 'lb-6248')");
            st.execute("INSERT INTO tenants (id, name, code) OVERRIDING SYSTEM VALUE VALUES ("
                    + EXHAUST_TENANT_ID + ", 'lb-6249', 'lb-6249')");
            st.execute("INSERT INTO products (id, tenant_id, name, base_price, stock) VALUES ('"
                    + PRODUCT_ID + "', " + TENANT_ID + ", '取号竞争核验-6248入库帘', 150.00, "
                    + INITIAL_STOCK.toPlainString() + ")");
            st.execute("INSERT INTO product_skus (id, tenant_id, product_id, door_width, price, stock, sku_code) VALUES ("
                    + SKU_ID + ", " + TENANT_ID + ", '" + PRODUCT_ID + "', '2.8m', 150.00, "
                    + INITIAL_STOCK.toPlainString() + ", 'SKU-6248-IN')");
            st.execute("INSERT INTO product_skus (id, tenant_id, product_id, door_width, price, stock, sku_code) VALUES ("
                    + EXHAUST_SKU_ID + ", " + EXHAUST_TENANT_ID + ", '" + PRODUCT_ID + "', '2.8m', 150.00, "
                    + INITIAL_STOCK.toPlainString() + ", 'SKU-6249-IN')");
        }

        // 判据 5 的号段耗尽夹具：把当天 0001..0020 一次性占用（20 个号 = 重试上限）⇒ 第 21 个候选
        // 就开始全撞，20 次重试必耗尽。占用行直接落库（不经被测取号面 ⇒ 不做循环依赖的假夹具）。
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            for (int i = 1; i <= EXHAUST_OCCUPIED; i++) {
                st.execute("INSERT INTO stock_batches (tenant_id, batch_no, product_id, sku_id, sku_code,"
                        + " inbound_no, quantity, unit_cost, amount) VALUES ("
                        + EXHAUST_TENANT_ID + ", '" + batchNo(i) + "', '" + PRODUCT_ID + "', "
                        + EXHAUST_SKU_ID + ", 'SKU-6249-IN', 'RK-6249-SEED', 1.0, 150.0000, 150.0000)");
            }
        }

        MybatisConfiguration configuration = new MybatisConfiguration();
        configuration.setMapUnderscoreToCamelCase(true);
        configuration.setEnvironment(new Environment("lb-6248", new JdbcTransactionFactory(), dataSource));
        // 多租户拦截器**必须在场**：生产 SQL 会经它重写（追加 tenant_id）⇒ 少了它就只测了 mapper 原文，
        // 而 `exists(tenant_id, batch_no)` 的租户维度恰恰是本判据要证的（跨租户不该互相占号）。
        MybatisPlusInterceptor tenantLine = new MybatisPlusInterceptor();
        tenantLine.addInnerInterceptor(new TenantLineInnerInterceptor(new TenantLineHandler() {
            @Override
            public Expression getTenantId() {
                return new LongValue(TENANT.get());
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

    // ────────────────────────────────────────────── 判据 1：单实例并发（不可达路径的读数）

    @Test
    @DisplayName("① 单实例 N=4 个**不同**入库单并发过账（3 轮）：全部成功、批次号两两不同、库里零重复")
    void singleProcessConcurrentPostAlwaysPicksDistinctBatchNo() throws Exception {
        for (int round = 1; round <= ROUNDS; round++) {
            BigDecimal stockBefore = skuStock();
            List<Outcome> outcomes = runConcurrently(
                    List.of(orderIdFor(round, 1), orderIdFor(round, 2), orderIdFor(round, 3), orderIdFor(round, 4)),
                    "admin-6248-single-" + round, -1, false);

            long success = outcomes.stream().filter(Outcome::success).count();
            List<Integer> statuses = outcomes.stream().map(Outcome::httpStatus).sorted().toList();
            BigDecimal stockAfter = skuStock();
            long batchRows = scalarLong("SELECT count(*) FROM stock_batches WHERE tenant_id = " + TENANT_ID
                    + " AND inbound_order_id LIKE 'io-6248-s" + round + "-%' AND deleted = 0");
            long distinctNos = scalarLong("SELECT count(DISTINCT batch_no) FROM stock_batches WHERE tenant_id = "
                    + TENANT_ID + " AND inbound_order_id LIKE 'io-6248-s" + round + "-%' AND deleted = 0");
            long globalDuplicate = scalarLong("SELECT count(*) FROM (SELECT batch_no FROM stock_batches WHERE tenant_id = "
                    + TENANT_ID + " GROUP BY batch_no HAVING count(*) > 1) d");

            System.out.println("[READING #6248 ① 单实例并发 round " + round + "] 成功数=" + success
                    + " 状态码=" + statuses
                    + " 库存=" + stockBefore.toPlainString() + "→" + stockAfter.toPlainString()
                    + " 本轮批次行=" + batchRows + " 本轮不同批次号=" + distinctNos
                    + " 全租户重号组=" + globalDuplicate);
            printOverlapEvidence("① round " + round, outcomes);

            assertThat(success).as("单实例 + 原子递增计数器 ⇒ 4 个不同单应全部过账成功（不该撞唯一索引）")
                    .isEqualTo(CONCURRENCY);
            assertThat(statuses).as("全部 200（无 409 / 无 500）").containsOnly(200);
            assertThat(batchRows).as("4 单 × 每单 1 行 = 4 行批次").isEqualTo(CONCURRENCY);
            assertThat(distinctNos)
                    .as("库内事实：本轮 4 个批次号两两不同 —— 撞唯一索引的话这里是 3 或更少（且会有 500）")
                    .isEqualTo(CONCURRENCY);
            assertThat(globalDuplicate).as("全租户范围零重号组（`uk_stock_batches_no` 的库内事实）")
                    .isZero();
            assertThat(stockAfter.subtract(stockBefore))
                    .as("库存增量 == 独立算式 4 × 3.0 = 12.0（每单一次）")
                    .isEqualByComparingTo(QTY.multiply(BigDecimal.valueOf(CONCURRENCY)));
        }
    }

    // ────────────────────────────────────────────── 判据 2：串行正对照

    @Test
    @DisplayName("② 串行正对照（护栏不误杀）：单请求过账成功，且当天号段未被无谓耗尽")
    void serialPostStillSucceeds() {
        String orderId = newOrder(1);
        BigDecimal stockBefore = skuStock();
        Outcome outcome = post(orderId, "admin-6248-serial", false);
        BigDecimal stockAfter = skuStock();
        long batchRows = scalarLong("SELECT count(*) FROM stock_batches WHERE tenant_id = " + TENANT_ID
                + " AND inbound_order_id = '" + orderId + "' AND deleted = 0");
        String orderStatus = scalarString("SELECT status FROM inbound_orders WHERE id = '" + orderId + "'");

        System.out.println("[READING #6248 ② 串行正对照] 成功=" + outcome.success()
                + " 状态码=" + outcome.httpStatus() + " 异常=" + outcome.errorCode()
                + " 明细=" + outcome.errorMessage() + " 单终态=" + orderStatus
                + " 库存=" + stockBefore.toPlainString() + "→" + stockAfter.toPlainString()
                + " 批次行=" + batchRows);

        assertThat(outcome.success()).as("串行单请求必须真的过账成功（红了 = 取号把正常请求误杀）").isTrue();
        assertThat(orderStatus).as("单据终态").isEqualTo("posted");
        assertThat(batchRows).as("串行单请求批次恰 1 行").isEqualTo(1L);
        assertThat(stockAfter.subtract(stockBefore)).as("串行单请求库存恰加一次")
                .isEqualByComparingTo(QTY);
    }

    // ────────────────────────────────────────────── 判据 3：重启 / 多实例同起点（可达路径）

    @Test
    @DisplayName("③ 重启落在「当天号段头部已被占」时：20 次重试耗尽 ⇒ 显式 409（**不**静默用重复号）")
    void restartIntoAnOccupiedHeadFailsClosedInsteadOfSilentlyReusing() {
        // 真实形态：服务重启（或新副本启动）⇒ BATCH_SEQ 从 0 开始，而当天已用过 0001..00NN
        // （NN ≥ 重试上限 20：一天的入库行数破 20 太容易了 —— 每张多行单就吃好几个号）。
        // 本判据把「重启」直接做出来（静态计数器置 0），而不是靠推理。
        //
        // ⚠️ 这条同时是本设计的**已知代价**（如实登记，不是被测缺陷）：重试上限 20 + 「从头重试」
        //    意味着「当天已用号 ≥ 20 时，重启后的第一批过账会被显式拒绝」。修前那条「单次重试上限内
        //    跳过已占号」的语义仍在（判据 ④/⑥ 的两个实例从同一位置起步 ⇒ 落败者换号成功、
        //    两单都落库），但**不覆盖**这个饱和形态 —— 故本判据要求它 **fail-closed（409）**，
        //    而不是退化成「静默复用已占号」（那才会真的重号）。
        // 装置自足（与执行顺序无关）：先把当天号段头部 0001..0020 填满（一天破 20 行太容易了 ——
        // 每张多行单就吃好几个号），再模拟重启从 0001 重走。
        // ⚠️ 计数器是**进程内静态**的（同类其它判据 / 别的测试类都可能把它推高）⇒ 先把起点归零，
        //    否则填充循环的候选越过 0020，永远填不满头部（本判据第一版就是这样红的）。
        resetBatchSeq();
        int fill = 0;
        while (occupiedBatchNos() < 20 && fill < 40) {
            post(newOrder(1), "admin-6248-fill-head-" + (++fill), false);
        }
        int occupied = occupiedBatchNos();
        String orderId = newOrder(1);
        resetBatchSeq(); // = 模拟重启 / 新副本（从 0001 重新走）
        Outcome outcome = post(orderId, "admin-6248-restart-saturated", false);

        String orderStatus = scalarString("SELECT status FROM inbound_orders WHERE id = '" + orderId + "'");
        long batchRows = scalarLong("SELECT count(*) FROM stock_batches WHERE tenant_id = " + TENANT_ID
                + " AND inbound_order_id = '" + orderId + "' AND deleted = 0");
        int headOccupied = occupiedBatchNos();
        System.out.println("[READING #6248 ③ 重启落在已占头部] 当天已占号数=" + occupied
                + "（≥ 重试上限 20 ⇒ 从 0001 重走必然耗尽）· 重启后过账单=" + outcome.httpStatus()
                + " 异常码=" + outcome.errorCode() + " 本单批次行=" + batchRows
                + " 单终态=" + orderStatus + " 之后已占号数=" + headOccupied
                + " ⇒ " + (outcome.success() ? "❌ 静默成功了" : "显式拒绝（fail-closed）"));

        assertThat(occupied).as("装置前提：当天已占号数必须 ≥ 重试上限，否则构造不出饱和形态")
                .isGreaterThanOrEqualTo(20);
        assertThat(outcome.success()).as("饱和形态必须显式拒绝（许静默用一个可能重复的号）").isFalse();
        assertThat(outcome.httpStatus()).as("显式拒绝的 HTTP 状态码 = 409").isEqualTo(409);
        assertThat(outcome.errorCode()).as("错误码 = BATCH_NO_EXHAUSTED").isEqualTo("BATCH_NO_EXHAUSTED");
        assertThat(batchRows).as("拒绝时零批次落库").isZero();
        assertThat(orderStatus).as("拒绝时单据回到 draft").isEqualTo("draft");
        assertThat(headOccupied).as("拒绝不得消耗新号（已占号数不变）").isEqualTo(occupied);
    }

    // ────────────────────────────────────────────── 判据 4：跨请求窗口（注入式红证的核心）

    @Test
    @DisplayName("④ 两实例同起点并发取号（注入「检查到写入之间被抢」窗口）：恰一个赢家，落败者**必须被重试吸收**")
    void twoInstancesRacingOnTheSameCandidateMustBeAbsorbedByRetry() throws Exception {
        // **可达路径的真实形态**：实例 A / B 各自维护进程内计数器 ⇒ 重启 / 多副本后两者从**同一位置**
        //   起步；两边同时过账**不同**的单 ⇒ 两边生成**同一个候选**；`exists` 都在 insert 之前跑完
        //   （都为假）⇒ 后提交的那个 insert 撞 `uk_stock_batches_no`。
        // 注入（**纯测试侧，不改被测语义**）：① `exists` 恒答「没人占」（= 窗口被利用的那一瞬间）；
        //   ② 写号那一步延时 400ms（让「一边已提交、另一边才写」必然发生，否则窗口只有微秒级、
        //   判据会退化成碰运气的 flake）。同一份注入对两条路径的读数见 PR body 的成对表。
        resetBatchSeq();
        String orderA = newOrder(1);
        String orderB = newOrder(1);
        List<Outcome> outcomes;
        try {
            setProbePause(WINDOW_PAUSE_MILLIS);
            setHazardMode(true);
            candidateRendezvous = new CyclicBarrier(2);
            outcomes = runConcurrently(List.of(orderA, orderB), "admin-6248-window", -1, false);
        } finally {
            candidateRendezvous = null;
            setHazardMode(false);
            setProbePause(0L);
        }

        long success = outcomes.stream().filter(Outcome::success).count();
        List<Integer> statuses = outcomes.stream().map(Outcome::httpStatus).toList();
        List<String> errorCodes = outcomes.stream().filter(o -> !o.success())
                .map(Outcome::errorCode).toList();
        long batchRows = scalarLong("SELECT count(*) FROM stock_batches WHERE tenant_id = " + TENANT_ID
                + " AND inbound_order_id IN ('" + orderA + "','" + orderB + "') AND deleted = 0");
        List<String> nos = batchRows("inbound_order_id IN ('" + orderA + "','" + orderB + "')");
        List<String> orderStatuses = orderStatuses(orderA, orderB);
        String aNo = scalarString("SELECT batch_no FROM stock_batches WHERE tenant_id = " + TENANT_ID
                + " AND inbound_order_id = '" + orderA + "' AND deleted = 0");
        String bNo = scalarString("SELECT batch_no FROM stock_batches WHERE tenant_id = " + TENANT_ID
                + " AND inbound_order_id = '" + orderB + "' AND deleted = 0");

        System.out.println("[READING #6248 ④ 两实例同起点（hazard + " + WINDOW_PAUSE_MILLIS + "ms 窗口）]"
                + " 成功数=" + success + " 状态码=" + statuses + " 落败异常=" + errorCodes
                + " 批次行=" + batchRows + " 批次号=" + nos + " 单终态=" + orderStatuses
                + " ⇒ " + (success == 2 ? "重试吸收了写号冲突（两单都落库、号不同）"
                        : "❌ 写号冲突未被吸收（" + errorCodes + " ⇒ 用户侧 500）"));

        assertThat(success)
                .as("撞唯一索引必须被**重试**吸收：两个不同单最终都应过账成功（失败 = 落败者拿到 "
                        + "DuplicateKeyException ⇒ 全局处理器读成 500）")
                .isEqualTo(2L);
        assertThat(statuses).as("状态码必须是 200/200（不许出现 500）").containsOnly(200);
        assertThat(batchRows).as("两个单各 1 行批次 = 2 行").isEqualTo(2L);
        assertThat(nos).as("库内事实：两行批次号不同（重试换号成功）").doesNotHaveDuplicates();
        assertThat(orderStatuses).as("两个单都必须落到 posted（落败者回滚 ⇒ 会停在 draft）")
                .containsOnly("posted");
        assertThat(aNo).as("A 的批次号").isNotNull();
        assertThat(bNo).as("B 的批次号（必须与 A 不同）").isNotNull().isNotEqualTo(aNo);
    }

    // ────────────────────────────────────────────── 判据 5：20 次耗尽 ⇒ 显式 409

    @Test
    @DisplayName("⑤ 当天号段被占满 ⇒ 20 次重试耗尽，显式 409 BATCH_NO_EXHAUSTED（不是静默重号 / 不是 500）")
    void exhaustedBatchNoSegmentRejectsExplicitly() {
        resetBatchSeq(); // 让第一个候选就落进被占的 0001..0020
        String orderId = newExhaustOrder();
        Outcome outcome = postExhaust(orderId, "admin-6248-exhaust");
        long batchRows = scalarLong("SELECT count(*) FROM stock_batches WHERE tenant_id = " + EXHAUST_TENANT_ID
                + " AND inbound_no = '" + exhaustInboundNo(orderId) + "'");
        String orderStatus = scalarString("SELECT status FROM inbound_orders WHERE id = '" + orderId + "'");
        BigDecimal stockAfter = scalarDecimal("SELECT stock FROM product_skus WHERE id = " + EXHAUST_SKU_ID);

        System.out.println("[READING #6248 ⑤ 号段耗尽] 成功=" + outcome.success()
                + " 状态码=" + outcome.httpStatus() + " 异常码=" + outcome.errorCode()
                + " 异常类型=" + outcome.errorCode()
                + " 本单批次行=" + batchRows + " 单终态=" + orderStatus
                + " 占用后 SKU 库存=" + stockAfter.toPlainString());

        assertThat(outcome.success()).as("耗尽必须**显式拒绝**（不许静默用一个可能重复的号）").isFalse();
        assertThat(outcome.httpStatus()).as("HTTP 状态码必须是 409（与 BusinessException 的 httpStatus 同值）")
                .isEqualTo(409);
        assertThat(outcome.errorCode()).as("错误码 = BATCH_NO_EXHAUSTED（用户/前端可按码处理）")
                .isEqualTo("BATCH_NO_EXHAUSTED");
        assertThat(outcome.errorMessage()).as("文案必须可懂（说清「连续 20 次生成失败」并给出下一步）")
                .contains("20").contains("批次号");
        assertThat(batchRows).as("拒绝时本单零批次落库（事务回滚）").isZero();
        assertThat(orderStatus).as("拒绝时单据回到 draft（过账权 CAS 也一并回滚）").isEqualTo("draft");
        assertThat(stockAfter).as("拒绝时库存不变（仍为夹具初值）").isEqualByComparingTo(INITIAL_STOCK);
    }

    // ────────────────────────────────────────────── 判据 6：不注入的同一形态（供修前红双向对照）

    @Test
    @DisplayName("⑥ 两实例同起点并发（**零注入**，5 轮）：同样必须全部落库且号不同（修前这条会 500）")
    void twoInstancesRacingWithNoInjectionMustAlsoSurvive() throws Exception {
        // 与判据 4 同形态，但**不注入任何延时**：两边从同一计数器位置起步并发取同一个候选。
        // 改后这条由 DB 原子裁决（`update(` 的受影响行数）；改前它走「exists 判假 ⇒ insert」
        // ⇒ 是否撞唯一索引取决于「一边提交、另一边还没 insert」这个微秒级窗口 ⇒ 本轮里可能偶尔变绿。
        // 故本判据的**主判据**仍是判据 4（注入式、双向可复算）；本条只在修前红对照时给出
        // 「同一份装置、不注入也能撞」的读数（见 PR body 的成对读数）。
        resetBatchSeq();
        List<Integer> allStatuses = new ArrayList<>();
        for (int round = 1; round <= 3; round++) {
            String orderC = newOrder(1);
            String orderD = newOrder(1);
            List<Outcome> outcomes = runConcurrently(List.of(orderC, orderD), "admin-6248-natural-" + round, -1, false);
            long success = outcomes.stream().filter(Outcome::success).count();
            List<Integer> statuses = outcomes.stream().map(Outcome::httpStatus).toList();
            List<String> errorTypes = outcomes.stream().filter(o -> !o.success())
                    .map(Outcome::errorCode).toList();
            List<String> nos = batchRows("inbound_order_id IN ('" + orderC + "','" + orderD + "')");
            List<String> states = orderStatuses(orderC, orderD);
            allStatuses.addAll(statuses);

            System.out.println("[READING #6248 ⑥ 零注入 round " + round + "] 成功数=" + success
                    + " 状态码=" + statuses + " 落败异常类型=" + errorTypes
                    + " 批次行=" + nos.size() + " 批次号=" + nos + " 单终态=" + states);
            printOverlapEvidence("⑥ round " + round, outcomes);

            assertThat(success).as("零注入下两个不同单也必须都落库（改前：撞唯一索引 ⇒ 500）").isEqualTo(2L);
            assertThat(statuses).as("状态码必须是 200/200（不许出现 500）").containsOnly(200);
            assertThat(nos).as("库内事实：两行批次号不同").doesNotHaveDuplicates();
            assertThat(states).as("两个单都必须落到 posted").containsOnly("posted");
        }
        System.out.println("[READING #6248 ⑥ 汇总] 3 轮 × 2 请求 = " + allStatuses.size()
                + " 个结局，状态码集合=" + allStatuses.stream().distinct().sorted().toList());
    }

    // ────────────────────────────────────────────── 并发装置

    /**
     * 并发过账装置：N 个线程各开一个<b>独立会话 / 连接</b>（真并发，不是同一会话内串行），
     * 记录各自的时间区间；`pauseIndex &gt;= 0` 时只让<b>该下标</b>的线程在窗口里被探针暂停
     * （= 真实形态里「B 的 exists 先跑完、A 才提交」的那一侧）。
     */
    private static List<Outcome> runConcurrently(List<String> orderIds, String operator,
                                                 int pauseIndex, boolean pauseEnabled) throws Exception {
        ExecutorService pool = Executors.newFixedThreadPool(orderIds.size());
        CyclicBarrier barrier = new CyclicBarrier(orderIds.size());
        List<Future<Outcome>> futures = new ArrayList<>();
        try {
            for (int i = 0; i < orderIds.size(); i++) {
                final String orderId = orderIds.get(i);
                final boolean withPause = pauseEnabled && (pauseIndex < 0 || pauseIndex == i);
                futures.add(pool.submit(() -> {
                    barrier.await(30, TimeUnit.SECONDS);
                    return post(orderId, operator + "-" + orderId, withPause);
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

    /** 一次过账（真 service + 真 mapper + 独立会话/连接）；`withPause` 时在取号窗口里暂停（注入）。 */
    private static Outcome post(String orderId, String operator, boolean withPause) {
        long start = System.nanoTime(); // 计时括号：只量时长，不投影业务日期（见 BusinessClockTestSourceGuardTest 的 OUT_OF_SCOPE 登记）
        TENANT.set(TENANT_ID);
        try (SqlSession s = factory.openSession(false)) {
            if (withPause) {
                setProbePause(WINDOW_PAUSE_MILLIS);
            }
            serviceOn(s).post(orderId, TENANT_ID, operator);
            s.commit();
            return new Outcome(true, 200, null, null, start, System.nanoTime());
        } catch (BusinessException e) {
            return new Outcome(false, e.getHttpStatus(), e.getCode(), e.getMessage(), start, System.nanoTime());
        } catch (Exception e) {
            // 关键读数：非 Business 异常（`DuplicateKeyException` 在这里）就是用户侧的 500
            return new Outcome(false, 500, e.getClass().getSimpleName(), e.getMessage(),
                    start, System.nanoTime());
        } finally {
            setProbePause(0L);
        }
    }

    /** 号段耗尽租户的过账（tenant / 单号与判据 1~4 的装置隔离）。 */
    private static Outcome postExhaust(String orderId, String operator) {
        long start = System.nanoTime();
        TENANT.set(EXHAUST_TENANT_ID);
        try (SqlSession s = factory.openSession(false)) {
            serviceOn(s).post(orderId, EXHAUST_TENANT_ID, operator);
            s.commit();
            return new Outcome(true, 200, null, null, start, System.nanoTime());
        } catch (BusinessException e) {
            return new Outcome(false, e.getHttpStatus(), e.getCode(), e.getMessage(), start, System.nanoTime());
        } catch (Exception e) {
            return new Outcome(false, 500, e.getClass().getSimpleName(), e.getMessage(), start, System.nanoTime());
        } finally {
            setProbePause(0L);
        }
    }

    /**
     * 「真重叠」证据：逐对区间求交 + 并集跨度 vs 各历时之和。
     *
     * <p>「发了 N 次」不是并发证据；<b>时间区间相交</b>才是。并集跨度 &lt; 各历时之和
     * ⇒ 同一时刻确有多个请求在飞（差值 = 被重叠掉的时间）。两者相等 ⇒ 这轮实际是串行，
     * 打印告警（本判据不把串行轮当并发读数）。</p>
     */
    private static void printOverlapEvidence(String label, List<Outcome> outcomes) {
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
        System.out.println("[真重叠 #6248 " + label + "] 区间(ms, 同一起点)="
                + intervals.stream().map(iv -> "[" + iv.start() + "," + iv.end() + "]").toList()
                + " 相交对数=" + overlappingPairs + "/" + (intervals.size() * (intervals.size() - 1) / 2)
                + " 并集跨度=" + union + "ms 各历时之和=" + sum + "ms"
                + " ⇒ " + (trulyOverlapping ? "真重叠（并集 < 各历时之和）" : "⚠️ 本轮区间两两不交 = 实际串行"));
    }

    /** 一次过账请求的结果（成功 / 失败 + HTTP 业务码 + 异常码 + 自己的时间区间）。 */
    private record Outcome(boolean success, int httpStatus, String errorCode, String errorMessage,
                           long startNanos, long endNanos) {
    }

    // ────────────────────────────────────────────── 测试探针（生产侧的唯一测试缝）

    /** 在「{@code exists} 判定 → insert」之间暂停（0 = 不暂停）；见生产侧探针的说明。 */
    private static void setProbePause(long millis) {
        INSERT_DELAY_MILLIS.set((int) millis);
        InboundOrderService.setBatchNoProbePauseMillisForTest(millis);
    }

    /** 打开/关闭 hazard 注入（见 {@link #HAZARD_MODE}）。 */
    private static void setHazardMode(boolean on) {
        HAZARD_MODE.set(on);
    }

    /** 静态计数器归零 = 模拟「服务重启 / 新副本从 0 开始」（进程内计数器，issue #6248 主张的核心）。 */
    private static void resetBatchSeq() {
        try {
            Field seq = InboundOrderService.class.getDeclaredField("BATCH_SEQ");
            seq.setAccessible(true);
            ((AtomicInteger) seq.get(null)).set(0);
        } catch (ReflectiveOperationException e) {
            throw new IllegalStateException("BATCH_SEQ 计数器读取失败（字段被改名 ⇒ 判据必须一起改）", e);
        }
    }

    /** 真装配：本判据的对象（过账状态机 + 库存 + 批次 + 台账）走<b>真库 mapper</b>。 */
    private static InboundOrderService serviceOn(SqlSession s) {
        StockLedgerService stockLedgerService = new StockLedgerService(
                s.getMapper(StockLedgerMapper.class), s.getMapper(ProductSkuMapper.class));
        return new InboundOrderService(
                s.getMapper(InboundOrderMapper.class),
                s.getMapper(InboundOrderItemMapper.class),
                mock(InboundOrderQueryMapper.class),
                delayedStockBatchMapper(s.getMapper(StockBatchMapper.class)),
                s.getMapper(ProductSkuMapper.class),
                s.getMapper(ProductMapper.class),
                stockLedgerService);
    }

    /**
     * 见 {@link #INSERT_DELAY_MILLIS} / {@link #HAZARD_MODE}：把「占用检查」与「写号」两步
     * 注到真 mapper 外面，其余方法原样转发。
     *
     * <p>方法名同时匹配 {@code insert}（旧路径）与 {@code update(}（新路径）——
     * 注入的是「同一件事」：候选号在写入那一刻已被别人占。</p>
     */
    private static StockBatchMapper delayedStockBatchMapper(StockBatchMapper real) {
        return (StockBatchMapper) java.lang.reflect.Proxy.newProxyInstance(
                BatchNoTakeRaceRealDbTest.class.getClassLoader(),
                new Class<?>[]{StockBatchMapper.class},
                (proxy, method, args) -> {
                    String name = method.getName();
                    if ("exists".equals(name) && HAZARD_MODE.get()) {
                        // = 「另一个事务在我检查之后、写入之前抢走了这个号」（窗口被利用）
                        return Boolean.FALSE;
                    }
                    if (HAZARD_MODE.get() && ("insert".equals(name) || "update(".equals(name))) {
                        CyclicBarrier rendezvous = candidateRendezvous;
                        if (rendezvous != null) {
                            // 两个过账者都取到候选号了才放行 ⇒ 两边拿的是**同一个**候选（真实多实例形态）
                            rendezvous.await(30, TimeUnit.SECONDS);
                        }
                        Thread.sleep(Math.max(1, INSERT_DELAY_MILLIS.get()));
                    } else if ("insert".equals(name) && INSERT_DELAY_MILLIS.get() > 0) {
                        Thread.sleep(INSERT_DELAY_MILLIS.get());
                    }
                    try {
                        return method.invoke(real, args);
                    } catch (java.lang.reflect.InvocationTargetException e) {
                        throw e.getTargetException();
                    }
                });
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

    private static List<String> batchRows(String where) {
        List<String> out = new ArrayList<>();
        try (Connection c = dataSource.getConnection();
             Statement st = c.createStatement();
             ResultSet rs = st.executeQuery("SELECT batch_no FROM stock_batches WHERE tenant_id = " + TENANT_ID
                     + " AND " + where + " ORDER BY id")) {
            while (rs.next()) {
                out.add(rs.getString(1));
            }
        } catch (SQLException e) {
            throw new IllegalStateException("批次号读取失败", e);
        }
        return out;
    }

    private static List<String> orderStatuses(String... orderIds) {
        List<String> out = new ArrayList<>();
        for (String id : orderIds) {
            out.add(scalarString("SELECT status FROM inbound_orders WHERE id = '" + id + "'"));
        }
        return out;
    }

    // ────────────────────────────────────────────── 夹具

    /** 建一张 draft 单 + 1 行明细（草稿态 batch_no = NULL，与建单路径同形态）。 */
    private static String newOrder(int lines) {
        String orderId = "io-6248-o" + ORDER_SEQ.incrementAndGet();
        insertDraft(TENANT_ID, orderId, "RK-6248-" + orderId.substring("io-6248-o".length()), SKU_ID, lines);
        return orderId;
    }

    /** 判据 1 用的固定单号（每轮独立，便于按 `inbound_order_id LIKE` 聚合读数）。 */
    private static String orderIdFor(int round, int idx) {
        String orderId = "io-6248-s" + round + "-" + idx;
        insertDraft(TENANT_ID, orderId, "RK-6248-S" + round + idx, SKU_ID, 1);
        return orderId;
    }

    private static String newExhaustOrder() {
        String orderId = "io-6249-x" + ORDER_SEQ.incrementAndGet();
        insertDraft(EXHAUST_TENANT_ID, orderId, exhaustInboundNo(orderId), EXHAUST_SKU_ID, 1);
        return orderId;
    }

    private static String exhaustInboundNo(String orderId) {
        return "RK-6249-" + orderId.substring("io-6249-x".length());
    }

    private static void insertDraft(Long tenantId, String orderId, String inboundNo, long skuId, int lines) {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute("INSERT INTO inbound_orders (id, tenant_id, inbound_no, status, total_amount, source) VALUES ('"
                    + orderId + "', " + tenantId + ", '" + inboundNo + "', 'draft', "
                    + QTY.multiply(BigDecimal.valueOf(lines)).toPlainString() + ", 'purchase')");
            for (int i = 0; i < lines; i++) {
                st.execute("INSERT INTO inbound_order_items (tenant_id, inbound_order_id, sku_id, product_id,"
                        + " sku_code, quantity, unit_cost, amount) VALUES ("
                        + tenantId + ", '" + orderId + "', " + skuId + ", '" + PRODUCT_ID + "', '"
                        + (tenantId.equals(TENANT_ID) ? "SKU-6248-IN" : "SKU-6249-IN") + "', " + QTY.toPlainString()
                        + ", 150.0000, 450.0000)");
            }
        } catch (SQLException e) {
            throw new IllegalStateException("夹具建单失败: " + orderId, e);
        }
    }

    /**
     * 当天**递增序号 ≤ 重试上限**（即 {@code 0001..0020}）里已被占用的号数 —— 判据 ③ 的装置前提
     * （「重启从 0001 重走」会不会必然耗尽，只取决于这一段，与更大的号无关）。
     */
    private static int occupiedBatchNos() {
        return (int) scalarLong("SELECT count(DISTINCT batch_no) FROM stock_batches WHERE tenant_id = "
                + TENANT_ID + " AND batch_no IN ("
                + java.util.stream.IntStream.rangeClosed(1, 20)
                        .mapToObj(i -> "'" + batchNo(i) + "'").collect(java.util.stream.Collectors.joining(","))
                + ")");
    }

    /** 当天第 i 个候选号（与生产 `generateBatchNo()` 同口径：`PC-yyyyMMdd-%04d`）。 */
    private static String batchNo(int i) {
        return "PC-" + BUSINESS_CLOCK.today().format(java.time.format.DateTimeFormatter.ofPattern("yyyyMMdd"))
                + "-" + String.format("%04d", i);
    }

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
