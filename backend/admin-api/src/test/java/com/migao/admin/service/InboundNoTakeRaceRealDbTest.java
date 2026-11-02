// case_ids: OR-075

package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.MybatisSqlSessionFactoryBuilder;
import com.baomidou.mybatisplus.extension.plugins.MybatisPlusInterceptor;
import com.baomidou.mybatisplus.extension.plugins.handler.TenantLineHandler;
import com.baomidou.mybatisplus.extension.plugins.inner.TenantLineInnerInterceptor;
import com.migao.admin.dto.InboundOrderCreateRequest;
import com.migao.admin.dto.InboundOrderResponse;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.InboundOrderItemMapper;
import com.migao.admin.mapper.InboundOrderMapper;
import com.migao.admin.mapper.ProductMapper;
import com.migao.admin.mapper.ProductSkuMapper;
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
 * 真库并发判据（issue #6266）：<b>入库建单取号 {@code nextFreeInboundNo} 的「取号 → 占用」是不是原子的
 * —— 并发建单会不会撞号 / 会不会有一单建不成</b>。
 *
 * <h2>被核验的主张（issue 的「待核验 1」）</h2>
 * 改前 = <b>两步</b>：{@code nextFreeInboundNo} 先 {@code exists(tenant_id, inbound_no)} 判假 ⇒ 返回候选
 * ⇒ <b>之后</b>才 {@code insert(..)} 落库 ⇒ 窗口被利用时（两个实例 / 重启后计数器从同一位置起步，
 * 或另一事务正持着该号未提交）后到者撞 {@code uk_inbound_orders_no} ⇒ {@code create(..)} 的 catch
 * 把它变成 <b>409</b>：<b>这一单没建成</b>。
 *
 * <h2>修法（生产代码）</h2>
 * 取号与占用并成<b>一条语句</b>（{@code InboundOrderMapper#insertIgnoreInboundNoConflict} 的
 * {@code ON CONFLICT (tenant_id, inbound_no) WHERE deleted = 0 DO NOTHING}）：受影响行数 1 = 号归我、
 * 0 = 刚被抢走 ⇒ 换候选重来（上限 20，耗尽显式 409 {@code INBOUND_NO_EXHAUSTED}）。
 * 同族先例 = #6248 的批次号（{@code StockBatchMapper#update}）。
 *
 * <h2>为什么必须真 PG</h2>
 * 缺陷的可利用性全部来自真 PG 的两件事：<b>①</b> 唯一索引在插入那一刻的原子判定；<b>②</b> 未提交行
 * 对并发事务的可见性规则（别人的 {@code exists} 看不见我未提交的行 ⇒ 两边都判「没人占」）。
 * mock 面上 {@code exists} 恒假、{@code insert} 恒成功 —— 窗口<b>结构上不可见</b>
 * （mock 侧只能证「换号重试」这一半，见 {@code InboundOrderServiceTest#createRetriesWhenCandidate…}）。
 *
 * <h2>判别力（红证）</h2>
 * 主判据 = 判据 ②：另一事务<b>持有同一候选号且未提交</b>时建单必须换号成功。
 * 把修法退回两步形态（{@code exists} 判假 ⇒ {@code insert}）⇒ 该判据必红（插入撞唯一索引 ⇒ 409）。
 * 注入方式与逐字读数见 PR body 的「红证」段。
 *
 * <p><b>边界（如实登记）</b>：① 本判据打<b>服务层 + 真库</b>，不证 HTTP 层（{@code POST /api/admin/inbound-orders}
 * 是薄转发）；② 「两个实例」用「同一 JVM 内两份独立会话 + 钉住同一候选」表达（进程内计数器在同一 JVM 里
 * 天然给不同候选，不钉住就造不出同号竞争 —— 见 {@code InboundOrderService#setInboundNoProbeFirstCandidateForTest}）；
 * ③ 探针对象全部自建（租户 {@value #TENANT_ID} / 商品前缀 {@code rw-6266}），随一次性临时集群销毁，
 * <b>不碰任何存量数据</b>。</p>
 */
@DisplayName("🔴 真库并发判据（#6266）：入库建单取号 —— 并发 N 单恰 N 个不同单号 / 同候选被占 ⇒ 换号吸收 / 耗尽 409")
class InboundNoTakeRaceRealDbTest {

    private static final Long TENANT_ID = 6266L;
    private static final Long EXHAUST_TENANT_ID = 6267L;
    private static final String PRODUCT_ID = "rw-6266-inbound";
    /** 判据 ④ 的夹具租户也要有**自己的**商品（租户拦截器会把 productMapper.selectById 追加 tenant_id）。 */
    private static final String EXHAUST_PRODUCT_ID = "rw-6267-inbound";
    private static final long SKU_ID = 626601L;
    private static final long EXHAUST_SKU_ID = 626701L;

    /** 并发建单的线程数（= 期望落库行数 = 期望不同单号数）。 */
    private static final int CONCURRENCY = 4;

    /** 并发轮数（每轮独立标记，读数按轮聚合）。 */
    private static final int ROUNDS = 3;

    /**
     * 期望成功的判据都从这个序号起步：判据 ④ 会把当天头部 {@code 0001..0020} 占满（= 重试上限），
     * 从 0 起步的请求会把 20 次预算全耗在被占的头上 ⇒ 判据变成**执行顺序依赖**（#6248 在 CI 上就这样红过）。
     */
    private static final int SAFE_START = 5000;

    /** 判据 ④ 的号段占用量（= 重试上限 20）。 */
    private static final int EXHAUST_OCCUPIED = 20;

    /** 判据 ② 里「另一事务持号未提交」的持有时长：够建单线程走到 insert 并被唯一索引挡住。 */
    private static final long HOLDER_HOLD_MILLIS = 400L;

    private static final AtomicInteger ORDER_SEQ = new AtomicInteger(0);

    /** 租户拦截器注入的租户（**按线程**；判据 ④ 的夹具租户与主租户不同）。 */
    private static final ThreadLocal<Long> TENANT = ThreadLocal.withInitial(() -> TENANT_ID);

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
                    + TENANT_ID + ", 'rw-6266', 'rw-6266')");
            st.execute("INSERT INTO tenants (id, name, code) OVERRIDING SYSTEM VALUE VALUES ("
                    + EXHAUST_TENANT_ID + ", 'rw-6267', 'rw-6267')");
            st.execute("INSERT INTO products (id, tenant_id, name, base_price, stock) VALUES ('"
                    + PRODUCT_ID + "', " + TENANT_ID + ", '取号竞争核验-6266入库帘', 88.00, 0)");
            st.execute("INSERT INTO product_skus (id, tenant_id, product_id, door_width, price, stock, sku_code) VALUES ("
                    + SKU_ID + ", " + TENANT_ID + ", '" + PRODUCT_ID + "', '2.8m', 88.00, 0, 'SKU-6266-IN')");
            st.execute("INSERT INTO products (id, tenant_id, name, base_price, stock) VALUES ('"
                    + EXHAUST_PRODUCT_ID + "', " + EXHAUST_TENANT_ID + ", '取号竞争核验-6267入库帘', 88.00, 0)");
            st.execute("INSERT INTO product_skus (id, tenant_id, product_id, door_width, price, stock, sku_code) VALUES ("
                    + EXHAUST_SKU_ID + ", " + EXHAUST_TENANT_ID + ", '" + EXHAUST_PRODUCT_ID + "', '2.8m', 88.00, 0,"
                    + " 'SKU-6267-IN')");
        }

        MybatisConfiguration configuration = new MybatisConfiguration();
        configuration.setMapUnderscoreToCamelCase(true);
        configuration.setEnvironment(new Environment("rw-6266", new JdbcTransactionFactory(), dataSource));
        // 多租户拦截器**必须在场**：生产 SQL 会经它重写（追加 tenant_id）⇒ 少了它就只测了 mapper 原文。
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
                ProductSkuMapper.class, ProductMapper.class)) {
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

    // ────────────────────────────────────────────── 判据 ①：并发 N=4 建单（本轮的主读数）

    @Test
    @DisplayName("① N=4 并发建单（3 轮，**钉住同一候选**＝两个实例同起点）：全部成功、库里恰 N 行、N 个单号互不相同")
    void concurrentCreateTakesExactlyNDistinctInboundNos() throws Exception {
        for (int round = 1; round <= ROUNDS; round++) {
            int base = SAFE_START + round * 100;
            resetInboundSeq(base);
            String shared = inboundNo(base + 1);
            String marker = "rw-6266-n" + round;
            List<Outcome> outcomes;
            // 「另一个实例的计数器也停在同一位置」= 第一次取号都拿到同一个候选号；
            // 固定下来才有多实例可达形态（进程内原子计数器在同一 JVM 里天然给不同候选）。
            InboundOrderService.setInboundNoProbeFirstCandidateForTest(shared);
            try {
                outcomes = runConcurrently(CONCURRENCY, marker);
            } finally {
                InboundOrderService.setInboundNoProbeFirstCandidateForTest(null);
            }

            long success = outcomes.stream().filter(Outcome::success).count();
            List<String> statuses = outcomes.stream().map(o -> String.valueOf(o.httpStatus())).sorted().toList();
            List<String> nos = inboundNosOfMarker(marker);
            long rows = nos.size();
            long distinct = nos.stream().distinct().count();
            long sharedRows = scalarLong("SELECT count(*) FROM inbound_orders WHERE tenant_id = " + TENANT_ID
                    + " AND inbound_no = '" + shared + "' AND deleted = 0");
            long duplicateGroups = scalarLong("SELECT count(*) FROM (SELECT inbound_no FROM inbound_orders"
                    + " WHERE tenant_id = " + TENANT_ID + " AND deleted = 0 GROUP BY inbound_no"
                    + " HAVING count(*) > 1) d");
            long itemRows = scalarLong("SELECT count(*) FROM inbound_order_items i"
                    + " JOIN inbound_orders o ON o.id = i.inbound_order_id"
                    + " WHERE o.tenant_id = " + TENANT_ID + " AND o.remark = '" + marker + "'");

            System.out.println("[READING #6266 ① 并发建单 round " + round + "] 并发数=" + CONCURRENCY
                    + " 钉住候选=" + shared + " 成功数=" + success + " 状态码=" + statuses
                    + " 本轮行数=" + rows + " 本轮不同单号=" + distinct
                    + " 该候选被几单占用=" + sharedRows + " 全租户重号组=" + duplicateGroups
                    + " 明细行=" + itemRows + " 单号=" + nos);
            printOverlapEvidence("① round " + round, outcomes);

            assertThat(success).as("并发建单必须**全部建成**（撞号要被换号重试吸收，不许有一单 409）")
                    .isEqualTo(CONCURRENCY);
            assertThat(statuses).as("全部成功（不许出现 409 / 500）").containsOnly("200");
            assertThat(rows).as("库内事实：N 个并发 ⇒ 恰 N 行").isEqualTo(CONCURRENCY);
            assertThat(distinct).as("库内事实：N 个单号**互不相同**").isEqualTo(CONCURRENCY);
            assertThat(sharedRows).as("被钉住的同一候选只能被**一个**单占用（唯一的抢号冲突必须被裁决）")
                    .isEqualTo(1);
            assertThat(duplicateGroups).as("全租户零重号组（uk_inbound_orders_no 的库内事实）").isZero();
            assertThat(itemRows).as("每单恰 1 行明细 ⇒ N 行（没有半张单）").isEqualTo(CONCURRENCY);
        }
    }

    // ────────────────────────────────────────────── 判据 ②：另一事务持号未提交（**主判据**，确定性红证）

    @Test
    @DisplayName("🔴 ② 另一事务持有同一候选号且**未提交**：建单必须换号成功（两步形态 ⇒ 撞唯一索引 ⇒ 409）")
    void candidateHeldByAnUncommittedTransactionMustBeAbsorbedByRetry() throws Exception {
        resetInboundSeq(SAFE_START + 900);
        String held = inboundNo(SAFE_START + 901);
        String marker = "rw-6266-held";

        // 另一事务（= 另一个实例）先把这个号占了、但**还没提交**：
        // 任何 exists 查询都看不见它 ⇒ 两步形态会判「没人占」然后 insert；真正裁决的是唯一索引。
        Thread holder;
        long elapsedMillis;
        Outcome outcome;
        try (Connection holderConn = dataSource.getConnection()) {
            holderConn.setAutoCommit(false);
            try (Statement st = holderConn.createStatement()) {
                st.execute("INSERT INTO inbound_orders (id, tenant_id, inbound_no, status, total_amount, source,"
                        + " created_by) VALUES ('rw-6266-holder', " + TENANT_ID + ", '" + held + "', 'draft', 0,"
                        + " 'purchase', 'another-instance')");
            }
            InboundOrderService.setInboundNoProbeFirstCandidateForTest(held);
            try {
                long start = System.nanoTime();
                holder = new Thread(() -> {
                    try {
                        Thread.sleep(HOLDER_HOLD_MILLIS);
                        holderConn.commit();
                    } catch (Exception e) {
                        throw new IllegalStateException("持号事务提交失败", e);
                    }
                }, "rw-6266-holder-committer");
                holder.start();
                outcome = create(marker, TENANT_ID, "rw-6266-held-creator");
                elapsedMillis = (System.nanoTime() - start) / 1_000_000L;
            } finally {
                InboundOrderService.setInboundNoProbeFirstCandidateForTest(null);
            }
            holder.join(TimeUnit.SECONDS.toMillis(30));
            assertThat(holder.isAlive()).as("持号事务必须已提交").isFalse();
        }

        List<String> nos = inboundNosOfMarker(marker);
        String holderNo = scalarString("SELECT inbound_no FROM inbound_orders WHERE id = 'rw-6266-holder'");
        long holderRows = scalarLong("SELECT count(*) FROM inbound_orders WHERE tenant_id = " + TENANT_ID
                + " AND inbound_no = '" + held + "' AND deleted = 0");

        System.out.println("[READING #6266 ② 另一事务持号未提交] 持号候选=" + held
                + " 持号行仍在=" + holderNo + " 建单成功=" + outcome.success()
                + " 状态码=" + outcome.httpStatus() + " 异常码=" + outcome.errorCode()
                + " 建单耗时ms=" + elapsedMillis + " 建单落库单号=" + nos + " 该候选被几单占用=" + holderRows
                + " ⇒ " + (outcome.success() ? "唯一索引裁决后换号吸收" : "❌ 这一单没建成"));

        assertThat(outcome.success())
                .as("候选取号被**并发事务**抢走时必须换号重来（两步形态在这里必红："
                        + "exists 看不见未提交行 ⇒ insert 撞 uk_inbound_orders_no ⇒ create 的 catch 回 409）")
                .isTrue();
        assertThat(nos).as("新单落库恰 1 行，且**不占用**被抢走的那个号").hasSize(1);
        assertThat(nos.get(0)).as("换号成功（不重号）").isNotEqualTo(held);
        assertThat(holderNo).as("持号事务那一行必须仍在（它的号归它）").isEqualTo(held);
        assertThat(holderRows).as("同一 (tenant, inbound_no) 只许一行").isEqualTo(1);
        assertThat(elapsedMillis)
                .as("读数（不是断言时长）：建单确实被唯一索引挡住、等持号事务提交后才换号（≥ 持有时长）")
                .isGreaterThanOrEqualTo(HOLDER_HOLD_MILLIS - 50L);
    }

    // ────────────────────────────────────────────── 判据 ③：串行正对照 + 字段回读（列清单漂移的守）

    @Test
    @DisplayName("③ 串行建单（正对照）：单号成形、草稿态、建单字段逐列回读一致（不漏列）")
    void serialCreateStillSucceedsAndEveryColumnRoundTrips() {
        resetInboundSeq(SAFE_START + 700);
        String marker = "rw-6266-serial-remark";
        InboundOrderCreateRequest req = request(TENANT_ID, marker);
        req.setSupplier("柯桥××布行");
        req.setWarehouse("一号原料仓");
        req.setSupplierDocNo("DOC-6266");

        TENANT.set(TENANT_ID);
        InboundOrderResponse created;
        try (SqlSession s = factory.openSession(false)) {
            created = serviceOn(s).create(req, TENANT_ID, "rw-6266-serial");
            s.commit();
        }

        String no = created.getInboundNo();
        System.out.println("[READING #6266 ③ 串行正对照] 单号=" + no + " 状态=" + created.getStatus()
                + " 来源=" + created.getSource() + " 供应商=" + created.getSupplier()
                + " 仓库=" + created.getWarehouse() + " 明细行=" + created.getItems().size()
                + " 总额=" + created.getTotalAmount());

        assertThat(no).as("单号成形：RK-yyyyMMdd-NNNN").matches("RK-\\d{8}-\\d{4}");
        assertThat(created.getStatus()).as("建单 = 草稿态（不动库存）").isEqualTo("draft");
        assertThat(created.getSource()).as("采购收货（默认来源）").isEqualTo("purchase");
        assertThat(created.getItems()).as("明细行已落库").hasSize(1);
        assertThat(scalarString("SELECT supplier FROM inbound_orders WHERE id = '" + created.getId() + "'"))
                .as("supplier 列已写入（手写 INSERT 的列清单不许漏列）").isEqualTo("柯桥××布行");
        assertThat(scalarString("SELECT supplier_doc_no FROM inbound_orders WHERE id = '" + created.getId() + "'"))
                .as("supplier_doc_no 列已写入").isEqualTo("DOC-6266");
        assertThat(scalarString("SELECT warehouse FROM inbound_orders WHERE id = '" + created.getId() + "'"))
                .as("warehouse 列已写入").isEqualTo("一号原料仓");
        assertThat(scalarString("SELECT created_by FROM inbound_orders WHERE id = '" + created.getId() + "'"))
                .as("created_by 列已写入").isEqualTo("rw-6266-serial");
        assertThat(scalarString("SELECT biz_category FROM inbound_orders WHERE id = '" + created.getId() + "'"))
                .as("biz_category 未传 ⇒ DB 默认 fabric（COALESCE 口径）").isEqualTo("fabric");
        assertThat(scalarString("SELECT created_at FROM inbound_orders WHERE id = '" + created.getId() + "'"))
                .as("created_at 由 DB 默认 NOW() 承接（不靠手工传）").isNotNull();
        assertThat(scalarLong("SELECT deleted FROM inbound_orders WHERE id = '" + created.getId() + "'"))
                .as("deleted 默认 0").isZero();
    }

    // ────────────────────────────────────────────── 判据 ④：号段耗尽 ⇒ 显式 409（fail-closed，零残行）

    @Test
    @DisplayName("④ 重启落在「当天号段头部已被占满」：20 次重试耗尽 ⇒ 显式 409 INBOUND_NO_EXHAUSTED、零残行")
    void exhaustedSegmentFailsClosedWithoutLeavingAnything() throws Exception {
        // 装置自足（与执行顺序无关）：先把该租户当天 0001..0020 占满（一天 20 张入库单太容易），
        // 再把计数器归零（= 服务重启 / 新副本），建单就必然在 20 次预算里全撞已占号。
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            for (int i = 1; i <= EXHAUST_OCCUPIED; i++) {
                st.execute("INSERT INTO inbound_orders (id, tenant_id, inbound_no, status, total_amount, source)"
                        + " VALUES ('rw-6267-seed-" + i + "', " + EXHAUST_TENANT_ID + ", '" + inboundNo(i)
                        + "', 'draft', 0, 'purchase')");
            }
        }
        long before = scalarLong("SELECT count(*) FROM inbound_orders WHERE tenant_id = " + EXHAUST_TENANT_ID
                + " AND deleted = 0");
        resetInboundSeq(0); // = 模拟重启 / 新副本（从 0001 重新走）

        TENANT.set(EXHAUST_TENANT_ID);
        Outcome outcome;
        long start = System.nanoTime();
        try (SqlSession s = factory.openSession(false)) {
            outcome = createOn(s, EXHAUST_TENANT_ID, "rw-6266-exhaust", "rw-6266-exhaust-remark");
            s.commit();
        }
        long after = scalarLong("SELECT count(*) FROM inbound_orders WHERE tenant_id = " + EXHAUST_TENANT_ID
                + " AND deleted = 0");
        long items = scalarLong("SELECT count(*) FROM inbound_order_items WHERE tenant_id = " + EXHAUST_TENANT_ID);

        System.out.println("[READING #6266 ④ 号段耗尽] 已占号数=" + before + "（" + EXHAUST_OCCUPIED
                + " = 重试上限）· 建单成功=" + outcome.success() + " 状态码=" + outcome.httpStatus()
                + " 异常码=" + outcome.errorCode() + " 拒绝后行数=" + after + " 明细行=" + items
                + " 耗时ms=" + ((System.nanoTime() - start) / 1_000_000L)
                + " ⇒ " + (outcome.success() ? "❌ 静默成功了" : "显式拒绝（fail-closed）"));

        assertThat(before).as("装置前提：当天头部 20 个号必须已占满").isEqualTo(EXHAUST_OCCUPIED);
        assertThat(outcome.success()).as("耗尽必须**显式拒绝**（不许静默用一个可能重复的号）").isFalse();
        assertThat(outcome.httpStatus()).as("HTTP 状态码 = 409").isEqualTo(409);
        assertThat(outcome.errorCode()).as("错误码 = INBOUND_NO_EXHAUSTED").isEqualTo("INBOUND_NO_EXHAUSTED");
        assertThat(outcome.errorMessage()).as("文案说清「连续 20 次失败」并给出下一步").contains("20").contains("入库单号");
        assertThat(after).as("拒绝时**零残行**（整笔回滚）").isEqualTo(before);
        assertThat(items).as("拒绝时零明细行").isZero();
    }

    // ────────────────────────────────────────────── 判据 ⑤：唯一索引在场（修法成立的前提）

    @Test
    @DisplayName("⑤ 修法前提：uk_inbound_orders_no 是 (tenant_id, inbound_no) WHERE deleted = 0 的部分唯一索引")
    void thePartialUniqueIndexTheFixRestsOnIsPresent() {
        String def = scalarString("SELECT indexdef FROM pg_indexes WHERE schemaname = 'public'"
                + " AND tablename = 'inbound_orders' AND indexname = 'uk_inbound_orders_no'");
        System.out.println("[READING #6266 ⑤ 唯一索引] " + def);

        assertThat(def).as("ON CONFLICT 的冲突目标必须真的存在（否则修法退化成「永远 0 行」或报错）").isNotNull();
        assertThat(def).as("必须是 UNIQUE").contains("UNIQUE INDEX");
        assertThat(def).as("列必须恰好是 (tenant_id, inbound_no)").contains("(tenant_id, inbound_no)");
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
                    return create(marker, TENANT_ID, marker + "-" + System.nanoTime());
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

    /** 一次建单（真 service + 真 mapper + **独立会话 / 连接**）；每轮带独立 remark 便于按轮聚合读数。 */
    private static Outcome create(String marker, Long tenantId, String operator) {
        long start = System.nanoTime(); // 计时括号：只量时长，不投影业务日期
        TENANT.set(tenantId);
        try (SqlSession s = factory.openSession(false)) {
            Outcome outcome = createOn(s, tenantId, operator, marker);
            if (outcome.success()) {
                s.commit();
            } else {
                // 事务内已抛业务异常：回滚（= 生产里 @Transactional 的 rollbackFor=Exception）
                s.rollback(true);
            }
            return outcome.withEnd(System.nanoTime());
        } catch (Exception e) {
            return new Outcome(false, 500, e.getClass().getSimpleName(), e.getMessage(), start, System.nanoTime());
        }
    }

    private static Outcome createOn(SqlSession s, Long tenantId, String operator, String marker) {
        long start = System.nanoTime();
        try {
            serviceOn(s).create(request(tenantId, marker), tenantId, operator);
            return new Outcome(true, 200, null, null, start, System.nanoTime());
        } catch (BusinessException e) {
            return new Outcome(false, e.getHttpStatus(), e.getCode(), e.getMessage(), start, System.nanoTime());
        } catch (Exception e) {
            // 非 Business 异常（`DuplicateKeyException` 在这里）就是用户侧的 500
            return new Outcome(false, 500, e.getClass().getSimpleName(), e.getMessage(), start, System.nanoTime());
        }
    }

    /**
     * 「真重叠」证据：逐对区间求交 + 并集跨度 vs 各历时之和。
     *
     * <p>「发了 N 次」不是并发证据；<b>时间区间相交</b>才是。并集跨度 &lt; 各历时之和 ⇒ 同一时刻确有多个
     * 请求在飞（差值 = 被重叠掉的时间）。两者相等 ⇒ 这轮实际是串行，打印告警（不把串行轮当并发读数）。</p>
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
        System.out.println("[真重叠 #6266 " + label + "] 区间(ms, 同一起点)="
                + intervals.stream().map(iv -> "[" + iv.start() + "," + iv.end() + "]").toList()
                + " 相交对数=" + overlappingPairs + "/" + (intervals.size() * (intervals.size() - 1) / 2)
                + " 并集跨度=" + union + "ms 各历时之和=" + sum + "ms"
                + " ⇒ " + (union < sum ? "真重叠（并集 < 各历时之和）" : "⚠️ 本轮区间两两不交 = 实际串行"));
    }

    /** 一次建单请求的结果（成功 / 失败 + HTTP 业务码 + 异常码 + 自己的时间区间）。 */
    private record Outcome(boolean success, int httpStatus, String errorCode, String errorMessage,
                           long startNanos, long endNanos) {
        Outcome withEnd(long end) {
            return new Outcome(success, httpStatus, errorCode, errorMessage, startNanos, end);
        }
    }

    // ────────────────────────────────────────────── 测试装置

    /** 真装配：`create` 只用到这四个 mapper（建单不碰库存 / 批次 / 台账）。 */
    private static InboundOrderService serviceOn(SqlSession s) {
        return new InboundOrderService(
                s.getMapper(InboundOrderMapper.class),
                s.getMapper(InboundOrderItemMapper.class),
                null,
                null,
                s.getMapper(ProductSkuMapper.class),
                s.getMapper(ProductMapper.class),
                null, null, null);
    }

    private static InboundOrderCreateRequest request(Long tenantId, String marker) {
        InboundOrderCreateRequest.Item item = new InboundOrderCreateRequest.Item();
        item.setProductId(tenantId.equals(TENANT_ID) ? PRODUCT_ID : EXHAUST_PRODUCT_ID);
        item.setSkuId(tenantId.equals(TENANT_ID) ? SKU_ID : EXHAUST_SKU_ID);
        item.setQuantity(new BigDecimal("12.5"));
        item.setUnitCost(new BigDecimal("88.00"));
        InboundOrderCreateRequest req = new InboundOrderCreateRequest();
        req.setItems(List.of(item));
        req.setRemark(marker);
        return req;
    }

    /** 静态计数器置位 = 「重启到某个位置」（进程内计数器，issue #6266 可达形态的核心）。 */
    private static void resetInboundSeq(int ordinal) {
        try {
            java.lang.reflect.Field seq = InboundOrderService.class.getDeclaredField("INBOUND_SEQ");
            seq.setAccessible(true);
            ((AtomicInteger) seq.get(null)).set(ordinal);
        } catch (ReflectiveOperationException e) {
            throw new IllegalStateException("INBOUND_SEQ 计数器读取失败（字段被改名 ⇒ 判据必须一起改）", e);
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

    private static List<String> inboundNosOfMarker(String marker) {
        List<String> out = new ArrayList<>();
        try (Connection c = dataSource.getConnection();
             Statement st = c.createStatement();
             ResultSet rs = st.executeQuery("SELECT inbound_no FROM inbound_orders WHERE tenant_id = "
                     + TENANT_ID + " AND remark = '" + marker + "' AND deleted = 0 ORDER BY inbound_no")) {
            while (rs.next()) {
                out.add(rs.getString(1));
            }
        } catch (SQLException e) {
            throw new IllegalStateException("单号读取失败", e);
        }
        return out;
    }

    /** 当天第 i 个候选号（与生产 `generateInboundNo()` 同口径：`RK-yyyyMMdd-%04d`）。 */
    private static String inboundNo(int i) {
        return "RK-" + BUSINESS_CLOCK.today().format(DateTimeFormatter.ofPattern("yyyyMMdd"))
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
