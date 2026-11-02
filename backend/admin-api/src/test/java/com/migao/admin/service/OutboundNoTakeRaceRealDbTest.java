// case_ids: OR-076

package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.MybatisSqlSessionFactoryBuilder;
import com.baomidou.mybatisplus.extension.plugins.MybatisPlusInterceptor;
import com.baomidou.mybatisplus.extension.plugins.handler.TenantLineHandler;
import com.baomidou.mybatisplus.extension.plugins.inner.TenantLineInnerInterceptor;
import com.migao.admin.entity.FinishedGoodsStock;
import com.migao.admin.entity.OutboundOrder;
import com.migao.admin.entity.Warehouse;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.OutboundOrderItemMapper;
import com.migao.admin.mapper.OutboundOrderMapper;
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
import java.math.BigDecimal;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.sql.Connection;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import java.time.format.DateTimeFormatter;
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

/**
 * 真库并发判据（issue #8490）：<b>出库建单取号 {@code nextFreeOutboundNo} 的两步竞争</b>
 * —— 撞 {@code uk_outbound_orders_no} 时用户侧到底看到什么。
 *
 * <h2>本单核验的主张（issue #8490 的原文）</h2>
 * <ol>
 *   <li>{@code exists(tenant_id, outbound_no)} 判假 ⇒ 返回候选；</li>
 *   <li>调用方 {@code createAndPost(..)} / {@code createScanOutbound(..)} / {@code createFinishedOutbound(..)}
 *       在<b>之后</b>才 {@code outboundOrderMapper.insert(..)}；</li>
 *   <li>该 insert <b>没有任何 catch</b> ⇒ 窗口被利用时 {@code DuplicateKeyException} 直抛到全局处理器
 *       ⇒ 用户侧 <b>500</b>（整笔回滚、零残行 —— 比入库单的 409 更糟：商家会以为「出库没成功」而重复操作）。</li>
 * </ol>
 *
 * <h2>修法（与 #6266 入库单号同一形态，同一份重试骨架 {@link AtomicNoAllocator}）</h2>
 * 取号与占号并成<b>一条语句</b>（{@code OutboundOrderMapper#insertIgnoreOutboundNoConflict} 的
 * {@code ON CONFLICT (tenant_id, outbound_no) WHERE deleted = 0 DO NOTHING}）：受影响行数 1 = 号归我、
 * 0 = 刚被抢走 ⇒ 换候选重来（上限 20），耗尽显式 409 {@code OUTBOUND_NO_EXHAUSTED}。
 *
 * <h2>为什么必须真 PG（mock 上这五条一条都证不了）</h2>
 * mock 的 {@code insert} 恒成功 ⇒「窗口能不能被利用」<b>结构上不可见</b>；而「撞了之后单 / 明细 /
 * 行数变成什么样」也只能从库内读。本类装配真 service + 真 mapper + 真租户拦截器 + <b>独立会话 / 连接</b>。
 */
@DisplayName("真库并发（#8490）：出库建单取号 ← 两步 exists+insert ⇒ 一条语句占号（并发 / 未提交持号 / 耗尽 409）")
class OutboundNoTakeRaceRealDbTest {

    private static final long TENANT_ID = 849001L;
    /** 判据 ④ 的夹具租户（与主租户分开：耗尽号段不能污染其它判据）。 */
    private static final long EXHAUST_TENANT_ID = 849002L;

    /** 并发建单的线程数（= 期望落库行数 = 期望不同单号数）。 */
    private static final int CONCURRENCY = 4;

    /** 并发轮数（每轮独立标记，读数按轮聚合）。 */
    private static final int ROUNDS = 3;

    /** 判据 ④ 会把当天头部 {@code 0001..0020} 占满（= 重试上限）⇒ 其它判据从这个序号起步，不与其抢号。 */
    private static final int SAFE_START = 5000;

    /** 判据 ④ 的号段占用量（= 重试上限 20）。 */
    private static final int EXHAUST_OCCUPIED = 20;

    /** 判据 ② 里「另一事务持号未提交」的持有时长：够建单线程走到 insert 并被唯一索引挡住。 */
    private static final long HOLDER_HOLD_MILLIS = 400L;

    /** 租户拦截器注入的租户（**按线程**；判据 ④ 的夹具租户与主租户不同）。 */
    private static final ThreadLocal<Long> TENANT = ThreadLocal.withInitial(() -> TENANT_ID);

    private static final BusinessClock BUSINESS_CLOCK = new BusinessClock();
    private static final DateTimeFormatter DATE_FMT = DateTimeFormatter.ofPattern("yyyyMMdd");

    private static PgCluster cluster;
    private static DataSource dataSource;
    private static SqlSessionFactory factory;
    /** 夹具仓库（成品仓）：{@code outbound_orders.warehouse_id} 有 FK ⇒ 必须真建一行才能回读该列。 */
    private static long warehouseId;

    @BeforeAll
    static void startRealPostgresAndFixtures() throws Exception {
        cluster = PgCluster.startOrAbort();
        dataSource = cluster.dataSource();
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute(schemaSql());
            st.execute("INSERT INTO tenants (id, name, code) OVERRIDING SYSTEM VALUE VALUES ("
                    + TENANT_ID + ", 'rw-8490', 'rw-8490')");
            st.execute("INSERT INTO tenants (id, name, code) OVERRIDING SYSTEM VALUE VALUES ("
                    + EXHAUST_TENANT_ID + ", 'rw-8492', 'rw-8492')");
            st.execute("INSERT INTO warehouses (tenant_id, code, name, warehouse_type) VALUES ("
                    + TENANT_ID + ", 'WH-8490', '成品仓', 'finished')");
        }
        warehouseId = scalarLong("SELECT id FROM warehouses WHERE tenant_id = " + TENANT_ID
                + " AND code = 'WH-8490'");

        MybatisConfiguration configuration = new MybatisConfiguration();
        configuration.setMapUnderscoreToCamelCase(true);
        configuration.setEnvironment(new Environment("rw-8490", new JdbcTransactionFactory(), dataSource));
        // 多租户拦截器**必须在场**：生产 SQL 会经它重写（追加 tenant_id）⇒ 少了它就只测了 mapper 原文。
        // 手写 INSERT 自带 tenant_id ⇒ mapper 上标了 @InterceptorIgnore（与入库单同一批写面同口径）。
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
        for (Class<?> mapper : List.of(OutboundOrderMapper.class, OutboundOrderItemMapper.class)) {
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

    // ────────────────────────────────────────────── 判据 ①：并发 N=4 建单（主读数）

    @Test
    @DisplayName("① N=4 并发建单（3 轮，**钉住同一候选**＝两个实例同起点）：全部成功、库里恰 N 行、N 个单号互不相同")
    void concurrentCreateTakesExactlyNDistinctOutboundNos() throws Exception {
        for (int round = 1; round <= ROUNDS; round++) {
            int base = SAFE_START + round * 100;
            resetOutboundSeq(base);
            String shared = outboundNo(base + 1);
            String marker = "rw-8490-n" + round;
            List<Outcome> outcomes;
            // 「另一个实例的计数器也停在同一位置」= 第一次取号都拿到同一个候选号；
            // 固定下来才有多实例可达形态（进程内原子计数器在同一 JVM 里天然给不同候选）。
            OutboundOrderService.setOutboundNoProbeFirstCandidateForTest(shared);
            try {
                outcomes = runConcurrently(CONCURRENCY, marker);
            } finally {
                OutboundOrderService.setOutboundNoProbeFirstCandidateForTest(null);
            }

            long success = outcomes.stream().filter(Outcome::success).count();
            List<String> statuses = outcomes.stream().map(o -> String.valueOf(o.httpStatus())).sorted().toList();
            List<String> nos = outboundNosOfMarker(marker);
            long sharedRows = scalarLong("SELECT count(*) FROM outbound_orders WHERE tenant_id = " + TENANT_ID
                    + " AND outbound_no = '" + shared + "' AND deleted = 0");
            long duplicateGroups = scalarLong("SELECT count(*) FROM (SELECT outbound_no FROM outbound_orders"
                    + " WHERE tenant_id = " + TENANT_ID + " AND deleted = 0 GROUP BY outbound_no"
                    + " HAVING count(*) > 1) d");
            long itemRows = scalarLong("SELECT count(*) FROM outbound_order_items i"
                    + " JOIN outbound_orders o ON o.id = i.outbound_order_id"
                    + " WHERE o.tenant_id = " + TENANT_ID + " AND o.order_no = '" + marker + "'");

            System.out.println("[READING #8490 ① 并发建单 round " + round + "] 并发数=" + CONCURRENCY
                    + " 钉住候选=" + shared + " 成功数=" + success + " 状态码=" + statuses
                    + " 本轮行数=" + nos.size() + " 本轮不同单号=" + nos.stream().distinct().count()
                    + " 该候选被几单占用=" + sharedRows + " 全租户重号组=" + duplicateGroups
                    + " 明细行=" + itemRows + " 单号=" + nos);
            printOverlapEvidence("① round " + round, outcomes);

            assertThat(success).as("并发建单必须**全部建成**（撞号要被换号重试吸收，不许有一单 409 / 500）")
                    .isEqualTo(CONCURRENCY);
            assertThat(statuses).as("全部成功（不许出现 500）").containsOnly("200");
            assertThat(nos).as("库内事实：N 个并发 ⇒ 恰 N 行").hasSize(CONCURRENCY);
            assertThat(nos.stream().distinct().count()).as("库内事实：N 个单号**互不相同**").isEqualTo(CONCURRENCY);
            assertThat(sharedRows).as("被钉住的同一候选只能被**一个**单占用（唯一的抢号冲突必须被裁决）")
                    .isEqualTo(1);
            assertThat(duplicateGroups).as("全租户零重号组（uk_outbound_orders_no 的库内事实）").isZero();
            assertThat(itemRows).as("每单恰 1 行明细 ⇒ N 行（没有半张单）").isEqualTo(CONCURRENCY);
        }
    }

    // ────────────────────────────────────────────── 判据 ②：另一事务持号未提交（确定性红证）

    @Test
    @DisplayName("🔴 ② 另一事务持有同一候选号且**未提交**：建单必须换号成功（两步形态 ⇒ 撞唯一索引 ⇒ 500）")
    void candidateHeldByAnUncommittedTransactionMustBeAbsorbedByRetry() throws Exception {
        resetOutboundSeq(SAFE_START + 900);
        String held = outboundNo(SAFE_START + 901);
        String marker = "rw-8490-held";

        // 另一事务（= 另一个实例）先把这个号占了、但**还没提交**：
        // 任何 exists 查询都看不见它 ⇒ 两步形态会判「没人占」然后 insert；真正裁决的是唯一索引。
        Thread holder;
        long elapsedMillis;
        Outcome outcome;
        try (Connection holderConn = dataSource.getConnection()) {
            holderConn.setAutoCommit(false);
            try (Statement st = holderConn.createStatement()) {
                st.execute("INSERT INTO outbound_orders (id, tenant_id, outbound_no, biz_category, source,"
                        + " status, total_amount, created_by) VALUES ('rw-8490-holder', " + TENANT_ID + ", '"
                        + held + "', 'finished', 'scan', 'posted', 0, 'another-instance')");
            }
            OutboundOrderService.setOutboundNoProbeFirstCandidateForTest(held);
            try {
                long start = System.nanoTime();
                holder = new Thread(() -> {
                    try {
                        Thread.sleep(HOLDER_HOLD_MILLIS);
                        holderConn.commit();
                    } catch (Exception e) {
                        throw new IllegalStateException("持号事务提交失败", e);
                    }
                }, "rw-8490-holder-committer");
                holder.start();
                outcome = createScan(marker, TENANT_ID, "rw-8490-held-creator");
                elapsedMillis = (System.nanoTime() - start) / 1_000_000L;
            } finally {
                OutboundOrderService.setOutboundNoProbeFirstCandidateForTest(null);
            }
            holder.join(TimeUnit.SECONDS.toMillis(30));
            assertThat(holder.isAlive()).as("持号事务必须已提交").isFalse();
        }

        List<String> nos = outboundNosOfMarker(marker);
        String holderNo = scalarString("SELECT outbound_no FROM outbound_orders WHERE id = 'rw-8490-holder'");
        long holderRows = scalarLong("SELECT count(*) FROM outbound_orders WHERE tenant_id = " + TENANT_ID
                + " AND outbound_no = '" + held + "' AND deleted = 0");

        System.out.println("[READING #8490 ② 另一事务持号未提交] 持号候选=" + held
                + " 持号行仍在=" + holderNo + " 建单成功=" + outcome.success()
                + " 状态码=" + outcome.httpStatus() + " 异常码=" + outcome.errorCode()
                + " 建单耗时ms=" + elapsedMillis + " 建单落库单号=" + nos + " 该候选被几单占用=" + holderRows
                + " ⇒ " + (outcome.success() ? "唯一索引裁决后换号吸收" : "❌ 这一单没建成"));

        assertThat(outcome.success())
                .as("候选取号被**并发事务**抢走时必须换号重来（两步形态在这里必红："
                        + "exists 看不见未提交行 ⇒ insert 撞 uk_outbound_orders_no ⇒ 没有 catch ⇒ 500）")
                .isTrue();
        assertThat(outcome.httpStatus()).as("用户侧状态码必须仍是 200（不许 500）").isEqualTo(200);
        assertThat(nos).as("新单落库恰 1 行，且**不占用**被抢走的那个号").hasSize(1);
        assertThat(nos.get(0)).as("换号成功（不重号）").isNotEqualTo(held);
        assertThat(holderNo).as("持号事务那一行必须仍在（它的号归它）").isEqualTo(held);
        assertThat(holderRows).as("同一 (tenant, outbound_no) 只许一行").isEqualTo(1);
        assertThat(elapsedMillis)
                .as("读数（不是断言时长）：建单确实被唯一索引挡住、等持号事务提交后才换号（≥ 持有时长）")
                .isGreaterThanOrEqualTo(HOLDER_HOLD_MILLIS - 50L);
    }

    // ────────────────────────────────────────────── 判据 ③：串行正对照 + 字段回读（列清单漂移的守）

    @Test
    @DisplayName("③ 串行建单（正对照）：单号成形、已过账、建单字段逐列回读一致（不漏列）")
    void serialCreateStillSucceedsAndEveryColumnRoundTrips() throws Exception {
        resetOutboundSeq(SAFE_START + 700);
        String marker = "rw-8490-serial";

        TENANT.set(TENANT_ID);
        OutboundOrder created;
        try (SqlSession s = factory.openSession(false)) {
            created = serviceOn(s).createScanOutbound(marker, row(), warehouse(), TENANT_ID, "rw-8490-serial");
            s.commit();
        }

        String no = created.getOutboundNo();
        System.out.println("[READING #8490 ③ 串行正对照] 单号=" + no + " 状态=" + created.getStatus()
                + " 来源=" + created.getSource() + " 类别=" + created.getBizCategory()
                + " 仓库=" + created.getWarehouse() + " 订单=" + created.getOrderNo()
                + " 过账人=" + created.getPostedBy());

        assertThat(no).as("单号成形：CK-yyyyMMdd-NNNN").matches("CK-\\d{8}-\\d{4}");
        assertThat(created.getStatus()).as("建单即过账（出库没有草稿态）").isEqualTo(OutboundOrder.STATUS_POSTED);
        assertThat(created.getBizCategory()).as("成品出库").isEqualTo(OutboundOrder.BIZ_FINISHED);
        assertThat(created.getSource()).as("扫水洗唛出库").isEqualTo(OutboundOrder.SOURCE_SCAN);
        assertThat(scalarString("SELECT biz_category FROM outbound_orders WHERE id = '" + created.getId() + "'"))
                .as("biz_category 列已写入（手写 INSERT 的列清单不许漏列）").isEqualTo("finished");
        assertThat(scalarString("SELECT source FROM outbound_orders WHERE id = '" + created.getId() + "'"))
                .as("source 列已写入").isEqualTo("scan");
        assertThat(scalarString("SELECT warehouse FROM outbound_orders WHERE id = '" + created.getId() + "'"))
                .as("warehouse 文本快照已写入").isEqualTo("成品仓");
        assertThat(scalarLong("SELECT warehouse_id FROM outbound_orders WHERE id = '" + created.getId() + "'"))
                .as("warehouse_id 引用已写入（FK 仍有指向）").isEqualTo(warehouseId);
        assertThat(scalarString("SELECT order_no FROM outbound_orders WHERE id = '" + created.getId() + "'"))
                .as("order_no 列已写入").isEqualTo(marker);
        assertThat(scalarString("SELECT posted_by FROM outbound_orders WHERE id = '" + created.getId() + "'"))
                .as("posted_by 列已写入").isEqualTo("rw-8490-serial");
        assertThat(scalarString("SELECT created_by FROM outbound_orders WHERE id = '" + created.getId() + "'"))
                .as("created_by 列已写入").isEqualTo("rw-8490-serial");
        assertThat(scalarString("SELECT posted_at FROM outbound_orders WHERE id = '" + created.getId() + "'"))
                .as("posted_at 已写入").isNotNull();
        assertThat(scalarString("SELECT outbound_date FROM outbound_orders WHERE id = '" + created.getId() + "'"))
                .as("outbound_date 已写入（业务时钟）").isEqualTo(BUSINESS_CLOCK.today().toString());
        assertThat(scalarString("SELECT created_at FROM outbound_orders WHERE id = '" + created.getId() + "'"))
                .as("created_at 由 DB 默认 NOW() 承接（不靠手工传）").isNotNull();
        assertThat(scalarLong("SELECT deleted FROM outbound_orders WHERE id = '" + created.getId() + "'"))
                .as("deleted 默认 0").isZero();
        assertThat(scalarLong("SELECT count(*) FROM outbound_order_items WHERE outbound_order_id = '"
                + created.getId() + "'")).as("明细恰 1 行").isEqualTo(1L);
    }

    // ────────────────────────────────────────────── 判据 ④：号段耗尽 ⇒ 显式 409（fail-closed，零残行）

    @Test
    @DisplayName("④ 重启落在「当天号段头部已被占满」：20 次重试耗尽 ⇒ 显式 409 OUTBOUND_NO_EXHAUSTED、零残行")
    void exhaustedSegmentFailsClosedWithoutLeavingAnything() throws Exception {
        // 装置自足（与执行顺序无关）：先把该租户当天 0001..0020 占满，再把计数器归零
        // （= 服务重启 / 新副本），建单就必然在 20 次预算里全撞已占号。
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            for (int i = 1; i <= EXHAUST_OCCUPIED; i++) {
                st.execute("INSERT INTO outbound_orders (id, tenant_id, outbound_no, biz_category, source,"
                        + " status, total_amount) VALUES ('rw-8492-seed-" + i + "', " + EXHAUST_TENANT_ID + ", '"
                        + outboundNo(i) + "', 'finished', 'scan', 'posted', 0)");
            }
        }
        long before = scalarLong("SELECT count(*) FROM outbound_orders WHERE tenant_id = " + EXHAUST_TENANT_ID
                + " AND deleted = 0");
        resetOutboundSeq(0); // = 模拟重启 / 新副本（从 0001 重新走）

        TENANT.set(EXHAUST_TENANT_ID);
        Outcome outcome;
        long start = System.nanoTime();
        try (SqlSession s = factory.openSession(false)) {
            outcome = createScanOn(s, "rw-8490-exhaust", EXHAUST_TENANT_ID, "rw-8490-exhaust");
            s.commit();
        }
        long after = scalarLong("SELECT count(*) FROM outbound_orders WHERE tenant_id = " + EXHAUST_TENANT_ID
                + " AND deleted = 0");
        long items = scalarLong("SELECT count(*) FROM outbound_order_items WHERE tenant_id = " + EXHAUST_TENANT_ID);

        System.out.println("[READING #8490 ④ 号段耗尽] 已占号数=" + before + "（" + EXHAUST_OCCUPIED
                + " = 重试上限）· 建单成功=" + outcome.success() + " 状态码=" + outcome.httpStatus()
                + " 异常码=" + outcome.errorCode() + " 拒绝后行数=" + after + " 明细行=" + items
                + " 耗时ms=" + ((System.nanoTime() - start) / 1_000_000L)
                + " ⇒ " + (outcome.success() ? "❌ 静默成功了" : "显式拒绝（fail-closed）"));

        assertThat(before).as("装置前提：当天头部 20 个号必须已占满").isEqualTo(EXHAUST_OCCUPIED);
        assertThat(outcome.success()).as("耗尽必须**显式拒绝**（不许静默用一个可能重复的号）").isFalse();
        assertThat(outcome.httpStatus()).as("HTTP 状态码 = 409（不是 500）").isEqualTo(409);
        assertThat(outcome.errorCode()).as("错误码 = OUTBOUND_NO_EXHAUSTED").isEqualTo("OUTBOUND_NO_EXHAUSTED");
        assertThat(outcome.errorMessage()).as("文案说清「连续 20 次失败」并给出下一步")
                .contains("20").contains("出库单号");
        assertThat(after).as("拒绝时**零残行**（整笔回滚）").isEqualTo(before);
        assertThat(items).as("拒绝时零明细行").isZero();
    }

    // ────────────────────────────────────────────── 判据 ⑤：唯一索引在场（修法成立的前提）

    @Test
    @DisplayName("⑤ 修法前提：uk_outbound_orders_no 是 (tenant_id, outbound_no) WHERE deleted = 0 的部分唯一索引")
    void thePartialUniqueIndexTheFixRestsOnIsPresent() {
        String def = scalarString("SELECT indexdef FROM pg_indexes WHERE schemaname = 'public'"
                + " AND tablename = 'outbound_orders' AND indexname = 'uk_outbound_orders_no'");
        System.out.println("[READING #8490 ⑤ 唯一索引] " + def);

        assertThat(def).as("ON CONFLICT 的冲突目标必须真的存在（否则修法退化成「永远 0 行」或报错）").isNotNull();
        assertThat(def).as("必须是 UNIQUE").contains("UNIQUE INDEX");
        assertThat(def).as("列必须恰好是 (tenant_id, outbound_no)").contains("(tenant_id, outbound_no)");
        assertThat(def).as("必须是带谓词的部分唯一索引（ON CONFLICT 的推断要求谓词匹配）")
                .contains("WHERE (deleted = 0)");
    }

    // ────────────────────────────────────────────── 并发装置

    private static List<Outcome> runConcurrently(int n, String marker) throws Exception {
        ExecutorService pool = Executors.newFixedThreadPool(n);
        CyclicBarrier barrier = new CyclicBarrier(n);
        List<Future<Outcome>> futures = new ArrayList<>();
        try {
            for (int i = 0; i < n; i++) {
                futures.add(pool.submit(() -> {
                    barrier.await(30, TimeUnit.SECONDS);
                    return createScan(marker, TENANT_ID, marker + "-" + System.nanoTime());
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

    /** 一次出库建单（真 service + 真 mapper + **独立会话 / 连接**）；每轮带独立 orderNo 便于按轮聚合读数。 */
    private static Outcome createScan(String orderNo, Long tenantId, String operator) {
        TENANT.set(tenantId);
        try (SqlSession s = factory.openSession(false)) {
            Outcome outcome = createScanOn(s, orderNo, tenantId, operator);
            if (outcome.success()) {
                s.commit();
            } else {
                // 事务内已抛业务异常：回滚（= 生产里 @Transactional 的 rollbackFor=Exception）
                s.rollback(true);
            }
            return outcome;
        } catch (Exception e) {
            // 非 Business 异常（唯一的 500 面）：装配 / 连接级失败
            return new Outcome(false, 500, e.getClass().getSimpleName(), e.getMessage(), 0L, 0L);
        }
    }

    private static Outcome createScanOn(SqlSession s, String orderNo, Long tenantId, String operator) {
        long start = System.nanoTime();
        try {
            serviceOn(s).createScanOutbound(orderNo, row(), warehouse(), tenantId, operator);
            return new Outcome(true, 200, null, null, start, System.nanoTime());
        } catch (BusinessException e) {
            return new Outcome(false, e.getHttpStatus(), e.getCode(), e.getMessage(), start, System.nanoTime());
        } catch (Exception e) {
            // 非 Business 异常（真库裸装配下 DuplicateKeyException 表现为 PersistenceException）
            // 就是用户侧的 500 —— 这就是本单的病。
            return new Outcome(false, 500, e.getClass().getSimpleName(), e.getMessage(), start, System.nanoTime());
        }
    }

    /**
     * 「真重叠」证据：逐对区间求交 + 并集跨度 vs 各历时之和。
     *
     * <p>「发了 N 次」不是并发证据；<b>时间区间相交</b>才是。并集跨度 &lt; 各历时之和 ⇒ 同一时刻确有多个
     * 请求在飞；两者相等 ⇒ 这轮实际是串行，打印告警（不把串行轮当并发读数）。</p>
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
        System.out.println("[真重叠 #8490 " + label + "] 区间(ms, 同一起点)="
                + intervals.stream().map(iv -> "[" + iv.start() + "," + iv.end() + "]").toList()
                + " 相交对数=" + overlappingPairs + "/" + (intervals.size() * (intervals.size() - 1) / 2)
                + " 并集跨度=" + union + "ms 各历时之和=" + sum + "ms"
                + " ⇒ " + (union < sum ? "真重叠（并集 < 各历时之和）" : "⚠️ 本轮区间两两不相交 = 实际串行"));
    }

    /** 一次建单请求的结果（成功 / 失败 + HTTP 业务码 + 异常码 + 自己的时间区间）。 */
    private record Outcome(boolean success, int httpStatus, String errorCode, String errorMessage,
                           long startNanos, long endNanos) {
    }

    // ────────────────────────────────────────────── 测试装置

    /** 真装配：`createScanOutbound` 只用到这两个 mapper（单据 + 明细；不碰 SKU / 库存 / 台账 / 仓库表）。 */
    private static OutboundOrderService serviceOn(SqlSession s) {
        return new OutboundOrderService(
                s.getMapper(OutboundOrderMapper.class),
                s.getMapper(OutboundOrderItemMapper.class),
                null, null, null, null);
    }

    /** 扫水洗唛的在库行（成品单据的行来源；本类只读它的字段，不落 finished_goods_stock）。 */
    private static FinishedGoodsStock row() {
        return FinishedGoodsStock.builder()
                .orderId("rw-8490-order")
                .orderItemId("rw-8490-order-item")
                .locationId(7L)
                .binCode("A-01")
                .productId("rw-8490-product")
                .productName("取号竞争核验-8490成品帘")
                .quantity(new BigDecimal("1.00"))
                .unit("set")
                .build();
    }

    private static Warehouse warehouse() {
        Warehouse warehouse = new Warehouse();
        warehouse.setId(warehouseId);
        warehouse.setName("成品仓");
        return warehouse;
    }

    /** 静态计数器置位 = 「重启到某个位置」（进程内计数器，本单可达形态的核心）。 */
    private static void resetOutboundSeq(int ordinal) {
        try {
            java.lang.reflect.Field seq = OutboundOrderService.class.getDeclaredField("OUTBOUND_SEQ");
            seq.setAccessible(true);
            ((AtomicInteger) seq.get(null)).set(ordinal);
        } catch (ReflectiveOperationException e) {
            throw new IllegalStateException("OUTBOUND_SEQ 计数器读取失败（字段被改名 ⇒ 判据必须一起改）", e);
        }
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

    private static List<String> outboundNosOfMarker(String marker) {
        List<String> out = new ArrayList<>();
        try (Connection c = dataSource.getConnection();
             Statement st = c.createStatement();
             ResultSet rs = st.executeQuery("SELECT outbound_no FROM outbound_orders WHERE tenant_id = "
                     + TENANT_ID + " AND order_no = '" + marker + "' AND deleted = 0 ORDER BY outbound_no")) {
            while (rs.next()) {
                out.add(rs.getString(1));
            }
        } catch (SQLException e) {
            throw new IllegalStateException("单号读取失败", e);
        }
        return out;
    }

    /** 当天第 i 个候选号（与生产 `generateOutboundNo()` 同口径：`CK-yyyyMMdd-%04d`）。 */
    private static String outboundNo(int i) {
        return "CK-" + BUSINESS_CLOCK.today().format(DATE_FMT) + "-" + String.format("%04d", i);
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
