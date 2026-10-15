// case_ids: PR-023

package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.MybatisSqlSessionFactoryBuilder;
import com.baomidou.mybatisplus.extension.plugins.MybatisPlusInterceptor;
import com.baomidou.mybatisplus.extension.plugins.handler.TenantLineHandler;
import com.baomidou.mybatisplus.extension.plugins.inner.TenantLineInnerInterceptor;
import com.migao.admin.dto.RemnantViews;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.FabricRemnantMapper;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProductionOperationMapper;
import com.migao.admin.mapper.ProductionRouteRuleMapper;
import com.migao.admin.mapper.RemnantItemSizeMapper;
import com.migao.admin.mapper.StockBatchConsumptionMapper;
import com.migao.admin.mapper.StockBatchMapper;
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

/**
 * 🔴 真库并发判据（issue #6960）：<b>余料「回收」「报废」的准入必须是 DB 原子条件更新（CAS）
 * ⇒ 并发下**恰一次**回收额入账</b>。
 *
 * <h2>核验的是哪一条主张</h2>
 * {@code RemnantService#recover} / {@code #scrap} 的准入 = {@code FabricRemnantMapper#markRecovered} /
 * {@code #markScrapped}（{@code WHERE id=? AND tenant_id=? AND status='available' AND deleted=0}，
 * 0 行 ⇒ 409）。改前是「先读 status 判 {@code available}、再 {@code remnantMapper.updateById(patch)}
 * （WHERE 仅主键 ⇒ 无谓词）」⇒ 两个并发 recover 都能读到 {@code available} 并各写一次
 * {@code recovered_meters/unit_cost/amount}（**重复记回收额**，且涉钱、无任何 4xx）。
 *
 * <h2>为什么必须真库 + 窗口注入</h2>
 * CAS 的全部效力来自只有真 PG 才有的两件事：<b>① 行锁</b>（条件更新的判断与写入是同一条语句）、
 * <b>② 条件重估</b>（后到者阻塞到前者提交后按新版本行重估 {@code status='available'} ⇒ 影响行数 0）。
 * mock 面结构上判不了：mock 的 {@code updateById} 恒返回 1、也不会因 WHERE 不满足而返回 0
 * ⇒ 修前形态在 mock 上恒绿（假绿）。而窗口只有微秒级 ⇒ 用
 * {@link RemnantService#setRecoverProbePauseMillisForTest}（生产恒为 0）把窗口放大，
 * 判据才是**确定性**的，而不是 flake。
 *
 * <h2>判据（每条都会红）</h2>
 * <ol>
 *   <li><b>并发双 recover ⇒ 恰一次入账</b>：成功数 == 1、落败方 409、且
 *       {@code status='used'} 的行恰 1 行、{@code recovered_amount} 恰等于
 *       「米数 × 批次均价」（由夹具常量独立复算，**不读被测读面**）；</li>
 *   <li><b>回收 × 报废交叉 ⇒ 恰一个赢家</b>：两者争**同一份**状态迁移权，终态只能是其中一个
 *       （一个写面有 CAS、另一个没有 ⇒ 两者不互斥，正是本单要堵的形态）；</li>
 *   <li><b>串行正对照（护栏不误杀）</b>：无并发时 recover / scrap 各成功一次
 *       （谓词非空 ⇒ 正常请求不被 409 误杀）。</li>
 * </ol>
 *
 * <h2>判别力（红证，注入式 · 双向）</h2>
 * 注入 = {@code RemnantService.setRecoverProbePauseMillisForTest(PAUSE_MILLIS)}（把「读-判」与
 * 「写」之间的窗口从微秒放大到 800ms）。修前（无 CAS）本判据 <b>必红</b>（两个请求都读到
 * {@code available} ⇒ 两次写、成功数 2）；修后 <b>必绿</b>（CAS 0 行 ⇒ 409）。撤回注入
 * （{@code pauseMillis=0}）后正对照仍绿 ⇒ 「注入放大」就是本判据确定性的来源。
 * 逐字读数见 PR body 的「修前红 / 修后绿」两段。
 *
 * <p><b>边界（如实登记）</b>：① 本判据跑的是<b>服务层真库并发</b>而非 HTTP 栈（controller 只是薄转发）；
 * ② 探针对象全部自建（tenant {@value #TENANT_ID}），随一次性临时集群销毁，<b>不碰任何存量数据</b>；
 * ③ 本判据<b>不改回收额算法</b>（口径一字不动），只钉「并发恰一次」；
 * ④ 与 {@code RemnantStatusCasMetaGuardTest}（形态面）**缺一不可**。</p>
 */
@DisplayName("🔴 真库并发判据（#6960）：余料 recover/scrap 的 CAS ⇒ 并发恰一次回收额入账")
class RemnantRecoverRaceRealDbTest {

    private static final Long TENANT_ID = 6960L;
    private static final String PRODUCT_ID = "rm-6960-prod";
    private static final String SKU_CODE = "SKU-6960";
    private static final String BATCH_NO = "B-6960";
    /** 来源批次均价（夹具常量，独立于被测读面）。 */
    private static final BigDecimal UNIT_COST = new BigDecimal("12.5000");
    /** 余料沿卷长方向的米数（= 回收米数）。 */
    private static final BigDecimal METERS = new BigDecimal("4.00");
    /** 小件用料尺寸（必须装得下上面那块余料）。 */
    private static final String ITEM_KEY = "绑带-布";
    private static final String REMNANT_ORDER_NO = "SO-6960";

    /** 窗口注入时长（毫秒）：必须显著大于一次 recover 的全程（实测 ~10~40ms）。 */
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
                    + TENANT_ID + ", 'rm-6960', 'rm-6960')");
            st.execute("INSERT INTO products (id, tenant_id, name) VALUES ('" + PRODUCT_ID + "', "
                    + TENANT_ID + ", '余料回收竞态夹具商品')");
            st.execute("INSERT INTO stock_batches (tenant_id, batch_no, product_id, sku_code, quantity,"
                    + " unit_cost) VALUES (" + TENANT_ID + ", '" + BATCH_NO + "', '" + PRODUCT_ID + "', '"
                    + SKU_CODE + "', 60, " + UNIT_COST.toPlainString() + ")");
            // 小件用料尺寸（缺行 = 未配置 ⇒ recover 会在尺寸判据处 fail-closed，夹具必须配齐）
            st.execute("INSERT INTO remnant_small_item_specs (tenant_id, item_key, length_m, width_m,"
                    + " operator) VALUES (" + TENANT_ID + ", '" + ITEM_KEY + "', 3.00, 1.50, 'rm-6960')");
        }

        MybatisConfiguration configuration = new MybatisConfiguration();
        configuration.setMapUnderscoreToCamelCase(true);
        configuration.setEnvironment(new Environment("rm-6960", new JdbcTransactionFactory(), dataSource));
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
        for (Class<?> mapper : List.of(FabricRemnantMapper.class, RemnantItemSizeMapper.class,
                StockBatchMapper.class, StockBatchConsumptionMapper.class, ProductionOperationMapper.class,
                ProductionRouteRuleMapper.class, OrderMapper.class, OrderItemMapper.class)) {
            configuration.addMapper(mapper);
        }
        factory = new MybatisSqlSessionFactoryBuilder().build(configuration);
    }

    @AfterEach
    void clearProbe() {
        RemnantService.setRecoverProbePauseMillisForTest(0L);
    }

    @AfterAll
    static void stopRealPostgres() {
        RemnantService.setRecoverProbePauseMillisForTest(0L);
        if (cluster != null) {
            cluster.stop();
        }
    }

    // ────────────────────────────────────────────── 判据 1：并发双 recover

    @Test
    @DisplayName("并发双 recover（注入放大窗口）：恰一个赢家 + 回收额**恰入账一次**")
    void concurrentRecoverBooksTheAmountExactlyOnce() throws Exception {
        long remnantId = seedAvailableRemnant("rm-6960-race-1");
        Probe.installRecoverProbe();

        List<Verdict> outcomes = raceWithProbe(() -> recover(remnantId));

        long successes = outcomes.stream().filter(v -> v.status == 200).count();
        long conflicts = outcomes.stream().filter(v -> v.status == 409).count();
        System.out.println("[READING #6960 recover 竞态] 状态码="
                + outcomes.stream().map(v -> String.valueOf(v.status)).toList()
                + " 成功数=" + successes + " 409数=" + conflicts
                + " 终态=" + scalarString("SELECT status FROM fabric_remnants WHERE id = " + remnantId)
                + " 回收额=" + scalarString("SELECT recovered_amount FROM fabric_remnants WHERE id = "
                        + remnantId)
                + " 已用行数=" + scalarLong("SELECT count(*) FROM fabric_remnants WHERE id = " + remnantId
                        + " AND status = 'used'"));

        assertThat(successes)
                .as("两个并发 recover 争同一份回收权 ⇒ 恰一个赢家（两个都 200 就是修前的缺陷形态）")
                .isEqualTo(1L);
        assertThat(conflicts).as("落败方必须是显式 409 CONFLICT（不是 500 / 不是静默成功）").isEqualTo(1L);
        assertThat(scalarString("SELECT status FROM fabric_remnants WHERE id = " + remnantId))
                .as("终态 used").isEqualTo("used");
        assertThat(scalarDecimal("SELECT recovered_amount FROM fabric_remnants WHERE id = " + remnantId))
                .as("回收额 = 米数 × 批次均价（由夹具常量独立复算，不读被测读面）")
                .isEqualByComparingTo(METERS.multiply(UNIT_COST));
        assertThat(scalarDecimal("SELECT recovered_meters FROM fabric_remnants WHERE id = " + remnantId))
                .as("回收米数逐值等于余料米数").isEqualByComparingTo(METERS);
        // ⚠️ 「恰一次入账」的**直接读数**就是上面两条：恰 1 个赢家 + 金额逐值等于「米数 × 均价」。
        //    `uk_fabric_remnants_recovery` 是 (tenant_id, used_by_order_item_id, used_by_item_key)
        //    ⇒ 同一 order_item 只能有一块余料入账，故「本单入账行数」在这里恒为 1（夹具每条明细 id 唯一）
        //    —— 它是**结构性护栏**，不是本判据的判别面，故不再写一条恒真的计数断言。
    }

    // ────────────────────────────────────────────── 判据 2：回收 × 报废交叉

    @Test
    @DisplayName("回收 × 报废交叉竞态（注入放大窗口）：同一份状态迁移权 ⇒ 恰一个赢家、终态与之自洽")
    void recoverAndScrapHaveAtMostOneWinner() throws Exception {
        long remnantId = seedAvailableRemnant("rm-6960-race-2");
        Probe.installRecoverProbe();

        List<Verdict> outcomes = raceWithProbeTwo(
                () -> recover(remnantId),
                () -> scrap(remnantId));

        long successes = outcomes.stream().filter(v -> v.status == 200).count();
        String status = scalarString("SELECT status FROM fabric_remnants WHERE id = " + remnantId);
        System.out.println("[READING #6960 recover×scrap 竞态] 状态码="
                + outcomes.stream().map(v -> String.valueOf(v.status)).toList()
                + " 成功数=" + successes + " 终态=" + status
                + " 回收额=" + scalarString("SELECT recovered_amount FROM fabric_remnants WHERE id = "
                        + remnantId)
                + " 报废原因=" + scalarString("SELECT scrap_reason FROM fabric_remnants WHERE id = "
                        + remnantId));

        assertThat(successes)
                .as("回收与报废争**同一份**状态迁移权 ⇒ 恰一个赢家（一个写面有 CAS、另一个没有 ⇒ 不互斥）")
                .isEqualTo(1L);
        assertThat(status).as("终态只能是 used 或 scrapped（二选一，不是中间态、不是 available）")
                .isIn("used", "scrapped");
        if ("used".equals(status)) {
            assertThat(scalarDecimal("SELECT recovered_amount FROM fabric_remnants WHERE id = " + remnantId))
                    .as("回收赢 ⇒ 回收额恰入账一次").isEqualByComparingTo(METERS.multiply(UNIT_COST));
            assertThat(scalarString("SELECT scrap_reason FROM fabric_remnants WHERE id = " + remnantId))
                    .as("回收赢 ⇒ 报废留痕必须为空（ck_fabric_remnant_lifecycle 也钉住）").isNull();
        } else {
            assertThat(scalarString("SELECT scrap_reason FROM fabric_remnants WHERE id = " + remnantId))
                    .as("报废赢 ⇒ 报废原因非空").isNotBlank();
            assertThat(scalarString("SELECT recovered_amount FROM fabric_remnants WHERE id = " + remnantId))
                    .as("报废赢 ⇒ 回收列必须为空（与回收互斥，DB 约束同款）").isNull();
        }
    }

    // ────────────────────────────────────────────── 判据 3：正对照（护栏不误杀）

    @Test
    @DisplayName("正对照（护栏不误杀，无窗口注入）：串行 recover / scrap 各成功一次")
    void serialRecoverAndScrapStillSucceed() {
        long recoverTarget = seedAvailableRemnant("rm-6960-serial-1");
        long scrapTarget = seedAvailableRemnant("rm-6960-serial-2");

        Verdict recovered = recover(recoverTarget);
        Verdict scrapped = scrap(scrapTarget);
        System.out.println("[READING #6960 正对照 串行] recover=" + recovered.status + "(" + recovered.detail
                + ")" + " scrap=" + scrapped.status + "(" + scrapped.detail + ")"
                + " 回收终态=" + scalarString("SELECT status FROM fabric_remnants WHERE id = " + recoverTarget)
                + " 报废终态=" + scalarString("SELECT status FROM fabric_remnants WHERE id = " + scrapTarget));

        assertThat(recovered.status).as("串行 recover 必须成功（这条红了 = 谓词误杀正常请求）").isEqualTo(200);
        assertThat(scrapped.status).as("串行 scrap 必须成功").isEqualTo(200);
        assertThat(scalarString("SELECT status FROM fabric_remnants WHERE id = " + recoverTarget))
                .as("回收终态 used").isEqualTo("used");
        assertThat(scalarString("SELECT status FROM fabric_remnants WHERE id = " + scrapTarget))
                .as("报废终态 scrapped").isEqualTo("scrapped");
    }

    // ────────────────────────────────────────────── 并发装置

    /** 一次请求的结果（业务码 + 文本锚；服务层用异常的业务码等价表达 HTTP 4xx）。 */
    private record Verdict(int status, String detail) {
    }

    /** 探针安装（集中一处，免得三条判据各自写一遍而漂移）。 */
    private static final class Probe {
        private static void installRecoverProbe() {
            RemnantService.setRecoverProbePauseMillisForTest(PAUSE_MILLIS);
        }
    }

    /**
     * 注入窗口下的「先起跑者进窗口 → 对手走完全程 → 先起跑者续跑」时序。
     *
     * <p>这不是 {@code sleep} 猜时间：用 {@link RemnantService#recoverProbePausedForTest()}
     * 把「读-判已过、尚未写」这一刻钉住（超时 = 判据装置坏了 ⇒ 当场抛，不静默继续 ——
     * 静默继续会让本判据退化成 flake）。</p>
     */
    private static List<Verdict> raceWithProbe(java.util.concurrent.Callable<Verdict> action)
            throws Exception {
        ExecutorService pool = Executors.newSingleThreadExecutor();
        try {
            Future<Verdict> held = pool.submit(action);
            awaitProbePaused();
            Verdict opponent = action.call();
            Verdict first = held.get(60, TimeUnit.SECONDS);
            return List.of(first, opponent);
        } finally {
            pool.shutdownNow();
        }
    }

    /** 交叉竞态：先起跑者进窗口 → 对手（另一个动作）走完全程 → 先起跑者续跑。 */
    private static List<Verdict> raceWithProbeTwo(java.util.concurrent.Callable<Verdict> first,
                                                  java.util.concurrent.Callable<Verdict> second)
            throws Exception {
        ExecutorService pool = Executors.newSingleThreadExecutor();
        try {
            Future<Verdict> held = pool.submit(first);
            awaitProbePaused();
            Verdict opponent = second.call();
            Verdict winner = held.get(60, TimeUnit.SECONDS);
            return List.of(winner, opponent);
        } finally {
            pool.shutdownNow();
        }
    }

    /** 等「探针已进入暂停窗口」——**确定性时序**的锚点（不是 {@code sleep} 猜时间）。 */
    private static void awaitProbePaused() throws Exception {
        long deadline = System.nanoTime() + TimeUnit.MILLISECONDS.toNanos(PAUSE_WAIT_MILLIS);
        while (System.nanoTime() < deadline) {
            if (RemnantService.recoverProbePausedForTest()) {
                return;
            }
            Thread.sleep(1L);
        }
        throw new IllegalStateException(
                "探针未在 " + PAUSE_WAIT_MILLIS + "ms 内进入窗口（判据装置坏了：探针没插上 / 余料不是 available）");
    }

    private static Verdict recover(long remnantId) {
        try (SqlSession s = factory.openSession(true)) {
            // 明细行 id 逐块唯一：`uk_fabric_remnants_recovery (tenant_id, used_by_order_item_id,
            // used_by_item_key) WHERE deleted = 0 AND status = 'used'` 是**真的在拦** ——
            // 同一张单的同一个 itemKey 只能回收一块余料，夹具用同一个 id 会自己先撞唯一键。
            RemnantViews.RemnantLine line = serviceOn(s).recover(TENANT_ID, remnantId,
                    REMNANT_ORDER_NO + "-ITEM-" + remnantId, REMNANT_ORDER_NO, ITEM_KEY);
            return new Verdict(200, "status=" + line.status());
        } catch (BusinessException e) {
            return new Verdict(e.getHttpStatus(), "msg=" + e.getMessage());
        }
    }

    private static Verdict scrap(long remnantId) {
        try (SqlSession s = factory.openSession(true)) {
            RemnantViews.RemnantLine line = serviceOn(s).scrap(TENANT_ID, remnantId, "超期报废");
            return new Verdict(200, "status=" + line.status());
        } catch (BusinessException e) {
            return new Verdict(e.getHttpStatus(), "msg=" + e.getMessage());
        }
    }

    /** 真装配：本判据的对象（余料状态机 + 小件尺寸 + 批次均价）全部走<b>真库 mapper</b>。 */
    private static RemnantService serviceOn(SqlSession s) {
        return new RemnantService(s.getMapper(FabricRemnantMapper.class),
                s.getMapper(RemnantItemSizeMapper.class),
                s.getMapper(StockBatchMapper.class),
                s.getMapper(StockBatchConsumptionMapper.class),
                s.getMapper(ProductionOperationMapper.class),
                s.getMapper(ProductionRouteRuleMapper.class),
                s.getMapper(OrderMapper.class),
                s.getMapper(OrderItemMapper.class));
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

    private static String scalarString(String sql) {
        Object v = scalar(sql);
        return v == null ? null : v.toString();
    }

    private static long scalarLong(String sql) {
        Object v = scalar(sql);
        return v == null ? 0L : ((Number) v).longValue();
    }

    private static BigDecimal scalarDecimal(String sql) {
        return (BigDecimal) scalar(sql);
    }

    // ────────────────────────────────────────────── schema / 夹具

    /**
     * 插一块 {@code available} 余料（绕开服务层：本方法只造夹具，不走业务规则）。
     *
     * <p>⚠️ 两处**必须**照 DB 约束补齐，否则夹具自己就写不进去：{@code source_batch_id} 必须指向
     * 真批次（回收额要从**批次均价**算）；{@code available} 态下回收 / 报废列必须全 NULL
     * （{@code ck_fabric_remnant_lifecycle} 是真的在拦）。</p>
     */
    private static long seedAvailableRemnant(String orderNo) {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery("INSERT INTO fabric_remnants (tenant_id, piece_seq,"
                     + " source_order_no, source_processing_order_no, source_batch_id, source_batch_no,"
                     + " product_id, sku_code, piece_kind, length_m, width_m, status) VALUES (" + TENANT_ID
                     + ", (SELECT COALESCE(MAX(piece_seq), 0) + 1 FROM fabric_remnants), '" + orderNo
                     + "', 'JG-" + orderNo + "', (SELECT id FROM stock_batches WHERE batch_no = '"
                     + BATCH_NO + "'), '" + BATCH_NO + "', '" + PRODUCT_ID + "', '" + SKU_CODE
                     + "', 'width', " + METERS.toPlainString() + ", 2.00, 'available') RETURNING id")) {
            assertThat(rs.next()).as("余料夹具必须落库").isTrue();
            return rs.getLong(1);
        } catch (SQLException e) {
            throw new IllegalStateException("余料夹具落库失败: " + orderNo, e);
        }
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
