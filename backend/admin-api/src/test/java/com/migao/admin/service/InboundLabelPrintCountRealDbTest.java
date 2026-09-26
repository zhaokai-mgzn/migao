// case_ids: PR-113, PR-114
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.MybatisSqlSessionFactoryBuilder;
import com.migao.admin.entity.InboundLabel;
import com.migao.admin.mapper.InboundLabelMapper;
import com.migao.admin.mapper.ProductMapper;
import org.apache.ibatis.mapping.Environment;
import org.apache.ibatis.session.SqlSession;
import org.apache.ibatis.session.SqlSessionFactory;
import org.apache.ibatis.transaction.jdbc.JdbcTransactionFactory;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import javax.sql.DataSource;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.sql.Connection;
import java.sql.SQLException;
import java.sql.Statement;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * 入库标签**真库**判据（issue #5052 P2，V134）—— 打印计数并发不丢 / 部分唯一索引兜底 / 撤销置 NULL。
 *
 * <h2>为什么必须真库（mock 面结构上看不见）</h2>
 * <ol>
 *   <li><b>并发不丢计数是 SQL 语义</b>：{@code SET print_count = COALESCE(print_count,0)+1} 与
 *       「读出来 +1 再写回」在**单线程 mock 下逐字相同**（都是「调了一次 mapper」）——
 *       只有 N 个连接真并发打同一行，丢更新才会现形。计数是打印留痕的**唯一来源**，丢了就等于
 *       「这次打印没发生」（§7.3）。</li>
 *   <li><b>部分唯一索引与 CHECK 是 DB 对象</b>：`uk_inbound_labels_code`（建在**有效码**
 *       `COALESCE(short_code, revoked_code)` 上 ⇒ 活码 / 留档码 / 交叉都唯一）/ `uk_inbound_labels_item`（一行一标签）/
 *       `ck_inbound_labels_code_exactly_one` / `ck_inbound_labels_code_shape`（字母表外字符写不进来）
 *       —— mock 里它们**不存在**，写错了也永远绿。</li>
 *   <li><b>V134 必须在真库上可重复执行</b>（{@code MigrationRunner} 硬要求；新库上建库脚本先出终态、
 *       迁移再跑一遍）：只有当真的 PG 执行两遍不报错、且终止块（DO $$ … RAISE）不误报，才算数。</li>
 * </ol>
 *
 * <h2>环境</h2>
 * 一次性真 PG 集群（{@link PgCluster}，与既有真库判据**共用同一个装配**），schema 取
 * {@code backend/admin-api/src/main/resources/db/init/schema.sql}（终态，**不手抄列清单**）。
 * 缺 PG 二进制 ⇒ {@code PgCluster.startOrAbort()}：CI（{@code MIGAO_REQUIRE_REALDB=1}）⇒ 判红；
 * 本机未设该标记 ⇒ 显式 skip（「没跑」长得像「没跑」）。
 *
 * <h2>红证（把实现改坏 ⇒ 本类必红，实测见 PR body）</h2>
 * <ul>
 *   <li>{@code incrementPrintCount} 改成读改写 ⇒ {@code concurrentPrintsDoNotLoseCount}（mapper 层）
 *       与 {@code concurrentRecordPrintThroughTheServiceKeepsEveryCount}（**服务调用链**层）都必须红
 *       （后者是红证实测补上的：只测 mapper 时，「服务读改写 + mapper 仍原子」这种退化不会变红）；</li>
 *   <li>SQL 里去掉 {@code tenant_id = #{tenantId}} ⇒ {@code crossTenantIncrementTouchesNoRow} 红；</li>
 *   <li>{@code revoke} 只置 {@code short_code = NULL} 不留档（或漏掉 {@code short_code IS NOT NULL}）
 *       ⇒ {@code revokeKeepsTheArchivedCodeSoTheScanIsStillGone} 红；</li>
 *   <li>迁移里漏掉任一索引 / CHECK ⇒ 本类的真库断言红（DB 层没有兜底）。</li>
 * </ul>
 */
@DisplayName("#5052 P2 真库：入库标签（并发计数 / 唯一索引 / 撤销留档 / V134 幂等）")
class InboundLabelPrintCountRealDbTest {

    private static final Long TENANT_ID = 5052L;
    private static final Long OTHER_TENANT_ID = 50520L;
    private static final String ORDER_ID = "order-5052-1";

    /** 并发线程数（工人多设备 / 多工人同时打同一张标签的现实上限远小于它）。 */
    private static final int CONCURRENCY = 24;

    private static PgCluster cluster;
    private static SqlSessionFactory factory;

    @BeforeAll
    static void startRealPostgres() throws Exception {
        cluster = PgCluster.startOrAbort();
        DataSource dataSource = cluster.dataSource();
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute(read("backend/admin-api/src/main/resources/db/init/schema.sql"));
            // 🔴 真库上跑**两遍**迁移：① 迁移本身能执行；② 它可重复执行（MigrationRunner 的要求），
            //    且终止块（DO $$ … RAISE EXCEPTION）在「终态已由建库脚本建好」时不误报
            st.execute(read("backend/admin-api/src/main/resources/db/migration/"
                    + "V134__create_inbound_labels.sql"));
            st.execute(read("backend/admin-api/src/main/resources/db/migration/"
                    + "V134__create_inbound_labels.sql"));
            st.execute("INSERT INTO tenants (id, name, code) OVERRIDING SYSTEM VALUE VALUES ("
                    + TENANT_ID + ", 'acc-5052', 'acc-5052'), ("
                    + OTHER_TENANT_ID + ", 'acc-5052-other', 'acc-5052-other')");
            st.execute("INSERT INTO inbound_orders (id, tenant_id, inbound_no, status) VALUES "
                    + "('" + ORDER_ID + "', " + TENANT_ID + ", 'RK-20260926-0001', 'posted')");
        }
        MybatisConfiguration configuration = new MybatisConfiguration();
        configuration.setMapUnderscoreToCamelCase(true);
        configuration.setEnvironment(new Environment("acc-5052", new JdbcTransactionFactory(), dataSource));
        configuration.addMapper(InboundLabelMapper.class);
        factory = new MybatisSqlSessionFactoryBuilder().build(configuration);
    }

    @AfterAll
    static void stopRealPostgres() {
        if (cluster != null) {
            cluster.stop();
        }
    }

    // ============================================================ ① 并发计数不丢（§7.3）

    @Test
    @DisplayName("🔴 24 个连接并发打同一张标签 ⇒ 计数 == 成功次数（丢更新 ⇒ 必红）")
    void concurrentPrintsDoNotLoseCount() throws Exception {
        String id = "label-concurrency-1";
        String code = "AAAABBB2";
        insertLabel(id, TENANT_ID, 1L, code);
        assertThat(printCountOf(id)).isZero();

        ExecutorService pool = Executors.newFixedThreadPool(CONCURRENCY);
        CountDownLatch start = new CountDownLatch(1);
        CountDownLatch done = new CountDownLatch(CONCURRENCY);
        AtomicInteger affected = new AtomicInteger();
        List<Throwable> failures = java.util.Collections.synchronizedList(new ArrayList<>());
        try {
            for (int i = 0; i < CONCURRENCY; i++) {
                pool.submit(() -> {
                    try (SqlSession session = factory.openSession(true)) {
                        start.await();
                        InboundLabelMapper mapper = session.getMapper(InboundLabelMapper.class);
                        affected.addAndGet(mapper.incrementPrintCount(id, TENANT_ID));
                    } catch (Throwable t) {
                        failures.add(t);
                    } finally {
                        done.countDown();
                    }
                });
            }
            start.countDown();
            assertThat(done.await(60, TimeUnit.SECONDS)).as("并发打印必须在 60s 内全部完成").isTrue();
        } finally {
            pool.shutdownNow();
        }

        assertThat(failures).as("并发写不应有异常（丢更新是计数变小，不是报错）").isEmpty();
        assertThat(affected.get()).as("每次都该命中 1 行").isEqualTo(CONCURRENCY);
        assertThat(printCountOf(id))
                .as("🔴 丢更新在这里现形：读改写实现下这里会远小于 %d", CONCURRENCY)
                .isEqualTo(CONCURRENCY);
    }

    @Test
    @DisplayName("🔴 服务调用链上的并发打印：24 并发 recordPrint ⇒ 计数 == 成功次数（不只测 mapper 那一层）")
    void concurrentRecordPrintThroughTheServiceKeepsEveryCount() throws Exception {
        String id = "label-service-concurrency";
        String code = "TTTVVV44";
        insertLabel(id, TENANT_ID, 80L, code);
        assertThat(printCountOf(id)).isZero();

        ExecutorService pool = Executors.newFixedThreadPool(CONCURRENCY);
        CountDownLatch start = new CountDownLatch(1);
        CountDownLatch done = new CountDownLatch(CONCURRENCY);
        AtomicInteger served = new AtomicInteger();
        List<Throwable> failures = Collections.synchronizedList(new ArrayList<>());
        try {
            for (int i = 0; i < CONCURRENCY; i++) {
                final int worker = i;
                pool.submit(() -> {
                    // 每个线程自己的会话（SqlSession 不是线程安全的）+ 真的 InboundLabelService
                    try (SqlSession session = factory.openSession(true)) {
                        InboundLabelService service = new InboundLabelService(
                                session.getMapper(InboundLabelMapper.class),
                                org.mockito.Mockito.mock(InboundOrderService.class),
                                org.mockito.Mockito.mock(ProductMapper.class),
                                org.mockito.Mockito.mock(AuditLogService.class));
                        start.await();
                        service.recordPrint(code, TENANT_ID, "w-" + worker, "工人", "127.0.0.1", "ua");
                        served.incrementAndGet();
                    } catch (Throwable t) {
                        failures.add(t);
                    } finally {
                        done.countDown();
                    }
                });
            }
            start.countDown();
            assertThat(done.await(60, TimeUnit.SECONDS)).as("并发打印必须在 60s 内全部完成").isTrue();
        } finally {
            pool.shutdownNow();
        }

        assertThat(failures).as("并发打印不应有异常：%s", failures).isEmpty();
        assertThat(served.get()).isEqualTo(CONCURRENCY);
        assertThat(printCountOf(id))
                .as("🔴 服务链路上的丢更新在这里现形（只测 mapper 时它看不见：服务改读改写、mapper 仍原子 ⇒ 本条必红）")
                .isEqualTo(CONCURRENCY);
    }

    @Test
    @DisplayName("🔴 跨租户自增一行都不动（租户谓词是承重的，不是装饰）")
    void crossTenantIncrementTouchesNoRow() throws Exception {
        String id = "label-tenant-1";
        insertLabel(id, TENANT_ID, 2L, "AAAABBB3");

        try (SqlSession session = factory.openSession(true)) {
            InboundLabelMapper mapper = session.getMapper(InboundLabelMapper.class);
            assertThat(mapper.incrementPrintCount(id, OTHER_TENANT_ID)).isZero();
            assertThat(mapper.incrementPrintCount("label-not-exist", TENANT_ID)).isZero();
        }
        assertThat(printCountOf(id)).isZero();
        assertThat(printCountOf(id, OTHER_TENANT_ID)).as("跨租户回读也不该命中").isNull();
    }

    // ============================================================ ② 部分唯一索引兜底（§7.1）

    @Test
    @DisplayName("🔴 一行一标签：同一明细行重复请求复用同一张纸（不插第二行、不换码）")
    void oneLabelPerInboundItemReusesTheSameCode() throws Exception {
        String first = "label-item-1";
        insertLabel(first, TENANT_ID, 30L, "AAAABBB4");

        InboundLabel competitor = InboundLabel.builder()
                .id("label-item-1-second").tenantId(TENANT_ID).inboundOrderId(ORDER_ID)
                .inboundItemId(30L).shortCode("CCCCDDD5").printCount(0).createdBy("w-2").deleted(0).build();
        try (SqlSession session = factory.openSession(true)) {
            InboundLabelMapper mapper = session.getMapper(InboundLabelMapper.class);
            assertThat(mapper.insertIgnoreConflict(competitor))
                    .as("撞 uk_inbound_labels_item ⇒ 不插（否则一张纸两个码）").isZero();
            InboundLabel existing = mapper.selectByItem(TENANT_ID, 30L);
            assertThat(existing.getId()).isEqualTo(first);
            assertThat(existing.getShortCode()).isEqualTo("AAAABBB4");
        }
    }

    @Test
    @DisplayName("🔴 短码全局唯一 + 已撤销的码**永不复发**（老纸不会指到新单上）")
    void shortCodeAndRevokedCodeAreGloballyUnique() throws Exception {
        String code = "EEEFFF66";
        insertLabel("label-unique-1", TENANT_ID, 40L, code);
        insertLabel("label-unique-2", TENANT_ID, 41L, "GGGHHH77");

        // ① 活码撞车（另一个租户也不行：公开入口没有租户上下文 ⇒ 跨租户也必须唯一）
        assertThatThrownBy(() -> insertLabel("label-unique-3", OTHER_TENANT_ID, 42L, code))
                .isInstanceOf(SQLException.class)
                .hasMessageContaining("uk_inbound_labels_code");

        // ② 撤销 1 号 ⇒ 该码进留档列；新标签**不得**再用这个码（否则老纸会指到新单上）
        assertThat(revoke("label-unique-1", TENANT_ID, "w-9")).isEqualTo(1);
        assertThatThrownBy(() -> insertLabel("label-unique-4", TENANT_ID, 43L, code))
                .isInstanceOf(SQLException.class)
                .hasMessageContaining("uk_inbound_labels_code");
    }

    @Test
    @DisplayName("🔴 码形状由 DB 兜底：字母表外字符（I/L/O/U）与小写**写不进去**")
    void codeShapeCheckRejectsConfusableLetters() throws Exception {
        assertThatThrownBy(() -> insertLabel("label-shape-1", TENANT_ID, 50L, "IIIIIIII"))
                .isInstanceOf(SQLException.class)
                .hasMessageContaining("ck_inbound_labels_code_shape");
        assertThatThrownBy(() -> insertLabel("label-shape-2", TENANT_ID, 51L, "AAAABBBO"))
                .isInstanceOf(SQLException.class)
                .hasMessageContaining("ck_inbound_labels_code_shape");
        assertThatThrownBy(() -> insertLabel("label-shape-3", TENANT_ID, 52L, "aaaabbb2"))
                .isInstanceOf(SQLException.class)
                .hasMessageContaining("ck_inbound_labels_code_shape");
        assertThatThrownBy(() -> insertLabel("label-shape-4", TENANT_ID, 53L, "AAAABBB"))
                .isInstanceOf(SQLException.class)
                .hasMessageContaining("ck_inbound_labels_code_shape");
    }

    @Test
    @DisplayName("🔴 活码与留档码**恰有一个**非空（两个都空 / 两个都有 ⇒ 写不进去）")
    void exactlyOneOfLiveAndArchivedCode() throws Exception {
        try (Connection conn = cluster.dataSource().getConnection(); Statement st = conn.createStatement()) {
            assertThatThrownBy(() -> st.execute("INSERT INTO inbound_labels "
                    + "(id, tenant_id, inbound_order_id, inbound_item_id, short_code, revoked_code) VALUES "
                    + "('label-both-null', " + TENANT_ID + ", '" + ORDER_ID + "', 60, NULL, NULL)"))
                    .isInstanceOf(SQLException.class)
                    .hasMessageContaining("ck_inbound_labels_code_exactly_one");
            assertThatThrownBy(() -> st.execute("INSERT INTO inbound_labels "
                    + "(id, tenant_id, inbound_order_id, inbound_item_id, short_code, revoked_code) VALUES "
                    + "('label-both-set', " + TENANT_ID + ", '" + ORDER_ID + "', 61, 'JJJKKK88', 'MMMPPP99')"))
                    .isInstanceOf(SQLException.class)
                    .hasMessageContaining("ck_inbound_labels_code_exactly_one");
        }
    }

    // ============================================================ ③ 撤销 ⇒ 置 NULL ⇒ 410（§7.3）

    @Test
    @DisplayName("🔴 撤销 = 短码置 NULL + 原码留档 ⇒ 扫码仍能判 410（而不是 404「没这个码」）")
    void revokeKeepsTheArchivedCodeSoTheScanIsStillGone() throws Exception {
        String id = "label-revoke-1";
        String code = "QQQRRR22";
        insertLabel(id, TENANT_ID, 70L, code);

        try (SqlSession session = factory.openSession(true)) {
            InboundLabelMapper mapper = session.getMapper(InboundLabelMapper.class);
            assertThat(mapper.revoke(id, TENANT_ID, OffsetDateTime.now(), "w-9")).isEqualTo(1);

            InboundLabel revoked = mapper.selectByCode(code);
            assertThat(revoked).as("撤销后按原码仍必须查得到（否则 410 会退化成 404）").isNotNull();
            assertThat(revoked.getShortCode()).as("§7.3「撤销 ⇒ 短码置 NULL」").isNull();
            assertThat(revoked.getRevokedCode()).isEqualTo(code);
            assertThat(revoked.isRevoked()).isTrue();
            assertThat(revoked.getPrintCount()).as("撤销不得抹掉打印历史").isZero();

            // 重复撤销幂等（第二次 0 行 ⇒ 留档码不会被冲掉）
            assertThat(mapper.revoke(id, TENANT_ID, OffsetDateTime.now(), "w-9")).isZero();
            assertThat(mapper.selectByCode(code).getRevokedCode()).isEqualTo(code);
            // 撤销后不再计数（服务层据此判 410 且不计不审）
            assertThat(mapper.incrementPrintCount(id, TENANT_ID)).isZero();
            // 跨租户撤销一行不动
            insertLabel("label-revoke-2", TENANT_ID, 71L, "SSSTTT33");
            assertThat(mapper.revoke("label-revoke-2", OTHER_TENANT_ID, OffsetDateTime.now(), "w-9")).isZero();
        }
    }

    // ============================================================ 夹具

    private static void insertLabel(String id, Long tenantId, Long itemId, String code) throws SQLException {
        try (Connection conn = cluster.dataSource().getConnection(); Statement st = conn.createStatement()) {
            st.execute("INSERT INTO inbound_labels "
                    + "(id, tenant_id, inbound_order_id, inbound_item_id, short_code, print_count, created_by, deleted)"
                    + " VALUES ('" + id + "', " + tenantId + ", '" + ORDER_ID + "', " + itemId
                    + ", '" + code + "', 0, 'w-1', 0)");
        }
    }

    private static int revoke(String id, Long tenantId, String operator) {
        try (SqlSession session = factory.openSession(true)) {
            return session.getMapper(InboundLabelMapper.class)
                    .revoke(id, tenantId, OffsetDateTime.now(), operator);
        }
    }

    private static Integer printCountOf(String id) {
        return printCountOf(id, TENANT_ID);
    }

    private static Integer printCountOf(String id, Long tenantId) {
        try (SqlSession session = factory.openSession(true)) {
            return session.getMapper(InboundLabelMapper.class).selectPrintCount(id, tenantId);
        }
    }

    private static String read(String relative) throws Exception {
        Path root = Paths.get(System.getProperty("user.dir")).toAbsolutePath();
        while (root != null && !Files.exists(root.resolve(relative))) {
            root = root.getParent();
        }
        assertThat(root).as("必须能定位 %s（真库建表取终态 schema / 迁移原文，不手抄）", relative).isNotNull();
        Path file = root.resolve(relative);
        assertThat(Files.isRegularFile(file)).as("%s 必须存在", relative).isTrue();
        return Files.readString(file);
    }
}
