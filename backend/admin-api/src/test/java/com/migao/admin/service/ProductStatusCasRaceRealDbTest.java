// case_ids: PG-077

package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.MybatisSqlSessionFactoryBuilder;
import com.baomidou.mybatisplus.extension.plugins.MybatisPlusInterceptor;
import com.baomidou.mybatisplus.extension.plugins.handler.TenantLineHandler;
import com.baomidou.mybatisplus.extension.plugins.inner.TenantLineInnerInterceptor;
import com.migao.admin.dto.ProductUpdateRequest;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.CategoryMapper;
import com.migao.admin.mapper.ProductAttributeMapper;
import com.migao.admin.mapper.ProductColorMapper;
import com.migao.admin.mapper.ProductMapper;
import com.migao.admin.mapper.ProductSkuMapper;
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
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.sql.Connection;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.List;
import java.util.concurrent.CyclicBarrier;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 🔴 真库并发判据（issue #6961）：<b>商品状态迁移「读判 × 写」无谓词 ⇒ 并发 on/off_sale 双双成功</b>
 * 与 <b>改品整实体回写 ⇒ 静默回滚并发的状态迁移</b>。
 *
 * <h2>核验的是哪两条主张</h2>
 * <ol>
 *   <li><b>迁移权无 CAS</b>：修前 {@code updateProductStatus} / {@code updateProductForAgent} /
 *       {@code batchOnShelf} / {@code batchOffShelf} 都是「先 {@code selectById} 读旧 status 过状态机
 *       （{@code STATUS_TRANSITIONS}），再 {@code updateById}（WHERE 仅主键 ⇒ <b>无谓词</b>）」
 *       ⇒ 读判与写之间没有任何互斥：同一件商品并发 {@code on_sale} × {@code off_sale}
 *       <b>两个请求都 200</b>，终态由后写者决定（另一个请求的 200 是谎话）。</li>
 *   <li><b>T2b 类级根因（本单最隐蔽的一半）</b>：{@code updateProduct} 走
 *       {@code productMapper.updateById(product)} 整实体回写，且显式
 *       {@code product.setStatus(originalStatus)} ⇒ 「改个名字」会把<b>这次请求开头读到的旧 status
 *       一起写回</b>，把并发的状态迁移<b>静默回滚</b>（迁移那条腿已经返回 200 并提交，status 却又变回去）。</li>
 * </ol>
 * 修后：四条迁移入口全部走 {@code ProductMapper#updateStatusIfFrom}（{@code WHERE id=? AND tenant_id=?
 * AND deleted=0 AND status=<状态机授权的前驱>}），按<b>影响行数</b>判谁抢到迁移权：0 行 ⇒ 409 +
 * 实际当前态；{@code updateProduct} 只 set 自己负责的列（status 显式置 null 后不进 SET）。
 *
 * <h2>为什么必须真库 + 窗口注入</h2>
 * CAS 的全部效力来自只有真 PG 才有的两件事：<b>① 行锁</b>（条件更新的判断与写入是同一条语句，
 * 命中行的锁持有到事务结束）、<b>② 条件重估</b>（后到者阻塞到前者提交后按新版本行重估谓词 ⇒
 * 影响行数 0）。mock 面结构上判不了：mock 的 {@code updateById} 恒返回 1、也不会因 WHERE 不满足而
 * 返回 0 ⇒ <b>修前形态在 mock 上恒绿</b>（假绿）。而窗口只有微秒级 ⇒ 用
 * {@link ProductService#setStatusMigrationProbePauseMillisForTest(long)}（生产恒为 0）把窗口放大，
 * 判据才是<b>确定性</b>的，而不是 flake。
 *
 * <h2>判据（每条都会红）</h2>
 * <ol>
 *   <li><b>迁移至多一个赢家</b>：同一件商品并发 {@code on_sale} × {@code off_sale}（3 轮）⇒ 成功数
 *       <b>恰 == 1</b>，落败方必须是 <b>409 CONFLICT</b>，终态 == 赢家的目标态（修前实测两个都 200 ⇒ 红）；</li>
 *   <li><b>改品不得回滚状态</b>：{@code updateProduct}（改名）与状态迁移（off_sale → on_sale）并发 ⇒
 *       终态必须仍是迁移后的 {@code on_sale}，且改名**真的生效**（判据不是「什么都没发生」）；
 *       修前实测：迁移 200 + status 落 on_sale，随后改品把它写回 off_sale ⇒ 红；</li>
 *   <li><b>串行正对照（护栏不误杀）</b>：无并发时 off_sale → on_sale → off_sale 串行各成功一次；
 *       非法迁移（draft → on_sale 之外的随机取）照旧 422 被拒。</li>
 * </ol>
 *
 * <h2>判别力（红证，注入式 · 双向）</h2>
 * 把四条写退回修前的无谓词 {@code updateById}：<b>探针开</b> ⇒ 判据 1/2 必红（逐字读数见 PR body）；
 * <b>探针关</b>（{@code pauseMillis=0}）⇒ 不红（窗口收窄回微秒级，碰不到；本批已实测「探针关也可能
 * 因负载碰巧红」⇒ 只取方向一致的读数当证据）。
 *
 * <p><b>边界（如实登记，不粉饰）</b>：① 本判据跑的是<b>服务层真库并发</b>而非 HTTP 栈
 * （{@code PUT /api/admin/products/{id}/status} 与 agent 端点只是薄转发，状态机与写入全在服务层）；
 * ② 探针对象全部自建（tenant {@value #TENANT_ID} / 商品 id 前缀 {@code p-6961-}），随一次性临时集群
 * 销毁，<b>不碰任何存量数据</b>；③ 判据 1 只用 {@code updateProductStatus} 一条入口代表四条
 * （四条都走同一个 {@code applyStatusTransition} → 同一条 CAS；另外三条的**登记**由
 * {@code ProductStatusCasMetaGuardTest}（MC-105）逐条钉住）；④ {@code batchOnShelf} /
 * {@code batchOffShelf} 的落败文案走 {@code BatchOperationResult.failed} 而不是 409（分部分成功语义），
 * 本判据**未**逐条断言它的影响行数分支（登记在 {@code product-status-cas-ledger.json} 的
 * {@code coverage_boundary}）。</p>
 */
@DisplayName("🔴 真库并发判据（#6961）：商品状态迁移 = CAS，恰一个赢家 + 改品不回滚状态")
class ProductStatusCasRaceRealDbTest {

    private static final Long TENANT_ID = 6961L;
    private static final String PRODUCT_PREFIX = "p-6961-";

    /** 形态 ① 的轮数（每轮一件独立商品）。 */
    private static final int ROUNDS = 3;
    /** 正对照的独立夹具轮号（**必须与竞态轮分开** —— 否则并发轮的库态被对照测试提前改掉 ⇒ 判据自伤）。 */
    private static final int SERIAL_ROUND = ROUNDS + 1;
    /** 形态 ② 的独立夹具轮号。 */
    private static final int ROLLBACK_ROUND = ROUNDS + 2;

    /** 窗口注入时长（毫秒）：必须显著大于另一条路的全程（实测 ~10~30ms）。 */
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
            for (int r = 1; r <= ROLLBACK_ROUND; r++) {
                st.execute("INSERT INTO products (id, tenant_id, name, status) VALUES ('"
                        + productId(r) + "', " + TENANT_ID + ", '6961 夹具商品 " + r + "', 'off_sale')");
            }
        }

        MybatisConfiguration configuration = new MybatisConfiguration();
        configuration.setMapUnderscoreToCamelCase(true);
        configuration.setEnvironment(new Environment("prod-6961", new JdbcTransactionFactory(), dataSource));
        // 多租户拦截器**必须在场**：生产 SQL 会经它重写 ⇒ 少了它就只测了 mapper 原文
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
        for (Class<?> mapper : List.of(ProductMapper.class, CategoryMapper.class, ProductColorMapper.class,
                ProductSkuMapper.class, ProductAttributeMapper.class, StockLedgerMapper.class)) {
            configuration.addMapper(mapper);
        }
        factory = new MybatisSqlSessionFactoryBuilder().build(configuration);
    }

    @AfterEach
    void clearProbe() {
        ProductService.setStatusMigrationProbePauseMillisForTest(0L);
    }

    @AfterAll
    static void stopRealPostgres() {
        ProductService.setStatusMigrationProbePauseMillisForTest(0L);
        if (cluster != null) {
            cluster.stop();
        }
    }

    // ────────────────────────────────── 判据 1：并发 on_sale × off_sale 恰一个赢家

    @Test
    @DisplayName("同一商品并发 on_sale × off_sale（3 轮）：恰一个赢家 + 落败方 409 + 终态与赢家一致")
    void concurrentOnAndOffShelfHasExactlyOneWinner() throws Exception {
        ProductService.setStatusMigrationProbePauseMillisForTest(PAUSE_MILLIS);
        for (int round = 1; round <= ROUNDS; round++) {
            final String id = productId(round);

            // 两条请求经 CyclicBarrier **同刻起跑**（各自独立连接 + 独立事务）⇒ 探针关掉时这也是一次
            // 真并发（只是窗口收窄回微秒级），而不是「一条跑完了另一条才开始」的假并发。
            CyclicBarrier barrier = new CyclicBarrier(2);
            ExecutorService pool = Executors.newFixedThreadPool(2);
            Future<Verdict> onSaleFuture = pool.submit(() -> {
                barrier.await(30, TimeUnit.SECONDS);
                awaitProbeEntered();
                return switchStatus(id, "on_sale");
            });
            Future<Verdict> offShelfFuture = pool.submit(() -> {
                barrier.await(30, TimeUnit.SECONDS);
                return switchStatus(id, "off_sale");
            });
            Verdict offShelf = offShelfFuture.get(60, TimeUnit.SECONDS);
            Verdict onSale = onSaleFuture.get(60, TimeUnit.SECONDS);
            pool.shutdown();

            String dbStatus = scalarString("SELECT status FROM products WHERE id = '" + id + "'");
            long successes = (onSale.status == 200 ? 1 : 0) + (offShelf.status == 200 ? 1 : 0);
            String winnerTarget = onSale.status == 200 ? "on_sale" : "off_sale";

            System.out.println("[READING #6961 形态① round " + round + "] on_sale=" + onSale.status
                    + "(" + onSale.detail + ") off_sale=" + offShelf.status + "(" + offShelf.detail + ")"
                    + " 成功数=" + successes + " 商品终态=" + dbStatus);

            assertThat(successes)
                    .as("on_sale 与 off_sale 争同一份状态迁移权 ⇒ **恰一个**赢家（两个都 200 就是修前的缺陷形态）")
                    .isEqualTo(1L);
            assertThat(onSale.status == 200 || onSale.status == 409)
                    .as("落败方必须是显式 409 CONFLICT（不是 500 / 不是静默成功），实得 " + onSale.status)
                    .isTrue();
            assertThat(offShelf.status == 200 || offShelf.status == 409)
                    .as("落败方必须是显式 409 CONFLICT（不是 500 / 不是静默成功），实得 " + offShelf.status)
                    .isTrue();
            assertThat(dbStatus)
                    .as("终态必须与赢家的目标态一致（on_sale 赢 ⇒ on_sale；off_sale 赢 ⇒ off_sale）")
                    .isEqualTo(winnerTarget);
            // 🔴 判别力的第三靶心（**最直接**的一条）：谁回了 200，终态就必须**是**它声称的那个态。
            // 修前实测：on_sale=200 而终态=off_sale（或反之）⇒ **200 是谎话**。
            if (onSale.status == 200) {
                assertThat(dbStatus).as("on_sale 回了 200 ⇒ 终态必须就是 on_sale（回 200 却落到别人的终态 = 谎报成功）")
                        .isEqualTo("on_sale");
            }
            if (offShelf.status == 200) {
                assertThat(dbStatus).as("off_sale 回了 200 ⇒ 终态必须就是 off_sale（回 200 却落到别人的终态 = 谎报成功）")
                        .isEqualTo("off_sale");
            }
        }
    }

    // ────────────────────────────────── 判据 2：改品不得静默回滚并发的状态迁移（T2b）

    @Test
    @DisplayName("updateProduct（改名）× 状态迁移（off_sale → on_sale）并发：status 不被回滚 + 改名生效")
    void updateProductDoesNotRollBackConcurrentStatusMigration() throws Exception {
        ProductService.setStatusMigrationProbePauseMillisForTest(PAUSE_MILLIS);
        final String id = productId(ROLLBACK_ROUND);
        final String newName = "6961 改名后的商品";

        // 改品腿：读旧实体 → （探针停住）→ 写自己负责的列。修前这一步会把读到的旧 status=off_sale 写回。
        CyclicBarrier barrier = new CyclicBarrier(2);
        ExecutorService pool = Executors.newFixedThreadPool(2);
        Future<Verdict> updateFuture = pool.submit(() -> {
            barrier.await(30, TimeUnit.SECONDS);
            awaitProbeEntered();
            return rename(id, newName);
        });
        // 迁移腿：等改品腿真的停进窗口（确定性时序）再起跑 ⇒ 它读到的是**旧** status，
        // 而改品腿恢复后写回的是**内存里的旧实体**（修前）或**不写 status**（修后）。
        Future<Verdict> migrateFuture = pool.submit(() -> {
            barrier.await(30, TimeUnit.SECONDS);
            return switchStatus(id, "on_sale");
        });
        Verdict rename = updateFuture.get(60, TimeUnit.SECONDS);
        Verdict migrate = migrateFuture.get(60, TimeUnit.SECONDS);
        pool.shutdown();

        String dbStatus = scalarString("SELECT status FROM products WHERE id = '" + id + "'");
        String dbName = scalarString("SELECT name FROM products WHERE id = '" + id + "'");
        System.out.println("[READING #6961 形态②] 改名=" + rename.status + "(" + rename.detail + ")"
                + " 迁移=" + migrate.status + "(" + migrate.detail + ")"
                + " 商品终态=" + dbStatus + " 商品名=" + dbName);

        assertThat(rename.status).as("改品必须成功（它不是本判据的落败方）").isEqualTo(200);
        assertThat(migrate.status).as("迁移 off_sale → on_sale 在探针窗口里起跑，必须成功").isEqualTo(200);
        // 🔴 判别力的**主靶心**（修前逐字实测这一条必红）：改品把读到的旧 status 写回 ⇒ 终态 = off_sale。
        assertThat(dbStatus)
                .as("改品**不得**回滚并发的状态迁移 —— 终态必须仍是迁移后的 on_sale"
                        + "（修前：updateProduct 整实体回写 + setStatus(originalStatus) ⇒ 静默写回 off_sale）")
                .isEqualTo("on_sale");
        assertThat(dbName).as("改品自己负责的列必须真的写进去（判据不是「什么都没发生」）")
                .isEqualTo(newName);
    }

    // ────────────────────────────────── 正对照：护栏不误杀

    @Test
    @DisplayName("正对照（护栏不误杀）：串行 off_sale → on_sale → off_sale 各成功一次；非法迁移照旧被拒")
    void serialTransitionsStillSucceed() {
        // 谓词带 status=<前驱> ⇒ 若谓词写错（常量 null / 错前驱），**所有**迁移都会被 409 误杀。
        // 这条与上面的判据合起来才是完整证据：CAS **拦得住并发**且**不误杀正常请求**。
        String id = productId(SERIAL_ROUND);
        ProductService.setStatusMigrationProbePauseMillisForTest(0L);

        Verdict onSale = switchStatus(id, "on_sale");
        String afterOnSale = scalarString("SELECT status FROM products WHERE id = '" + id + "'");
        Verdict offShelf = switchStatus(id, "off_sale");
        String afterOffShelf = scalarString("SELECT status FROM products WHERE id = '" + id + "'");
        // 非法迁移（off_sale 不能直接回 draft，也不接受未知枚举）—— CAS 不改变这条既有口径
        Verdict illegal = switchStatus(id, "under_review");
        System.out.println("[READING #6961 正对照] on_sale=" + onSale.status + "(" + onSale.detail + ") 终态="
                + afterOnSale + " → off_sale=" + offShelf.status + "(" + offShelf.detail + ") 终态="
                + afterOffShelf + " → under_review(非法)=" + illegal.status + "(" + illegal.detail + ")");

        assertThat(onSale.status).as("串行 off_sale → on_sale 必须成功（这条红了 = 谓词误杀正常请求）").isEqualTo(200);
        assertThat(afterOnSale).as("on_sale 后终态").isEqualTo("on_sale");
        assertThat(offShelf.status).as("串行 on_sale → off_sale 必须成功").isEqualTo(200);
        assertThat(afterOffShelf).as("off_sale 后终态").isEqualTo("off_sale");
        assertThat(illegal.status)
                .as("off_sale → under_review 不在状态机里 ⇒ 必须是既有校验错误（422/400），不是 409 也不是 200，实得 "
                        + illegal.status)
                .isNotEqualTo(200)
                .isNotEqualTo(409);
    }

    // ────────────────────────────────── 并发装置

    /** 一次请求的结果（业务码 + 文本锚；服务层用异常的业务码等价表达）。 */
    private record Verdict(int status, String detail) {
    }

    /** 一次状态迁移（真 ProductService + 真库 mapper；各自独立 session = 独立连接 + 独立事务）。 */
    private static Verdict switchStatus(String id, String target) {
        try (SqlSession s = factory.openSession(false)) {
            productServiceOn(s).updateProductStatus(id, target, TENANT_ID);
            s.commit();
            return new Verdict(200, "ok");
        } catch (BusinessException e) {
            return new Verdict(e.getHttpStatus(), "msg=" + e.getMessage());
        }
    }

    /** 一次改品（只带 name ⇒ 走 updateProduct 的整条路 + 窗口探针）。 */
    private static Verdict rename(String id, String name) {
        try (SqlSession s = factory.openSession(false)) {
            ProductUpdateRequest req = new ProductUpdateRequest();
            req.setName(name);
            productServiceOn(s).updateProduct(id, req, TENANT_ID);
            s.commit();
            return new Verdict(200, "ok");
        } catch (BusinessException e) {
            return new Verdict(e.getHttpStatus(), "msg=" + e.getMessage());
        }
    }

    /** 真装配：同一 session 的 ProductService（与 ProductUpdatePruneScopeRealDbTest 同口径）。 */
    private static ProductService productServiceOn(SqlSession s) {
        StockLedgerService stockLedgerService = new StockLedgerService(
                s.getMapper(StockLedgerMapper.class), s.getMapper(ProductSkuMapper.class));
        ProductService service = new ProductService(
                s.getMapper(ProductMapper.class),
                s.getMapper(CategoryMapper.class),
                s.getMapper(ProductColorMapper.class),
                s.getMapper(ProductSkuMapper.class),
                s.getMapper(ProductAttributeMapper.class),
                stockLedgerService,
                // 幂等键（issue #6209）：本类走无键路径 ⇒ 不需要幂等存储
                null);
        // 🔴 探针装到**本类读的那一个实例**上（探针是类级 static ⇒ 全仓共用一个，见 ProductService 的字段注释）
        return service;
    }

    /**
     * 等探针真的进入窗口（**确定性时序**：不是 sleep 猜时间）。超时 ⇒ 判据装置坏了（fail-closed）。
     */
    private static void awaitProbeEntered() throws Exception {
        ProductService.awaitStatusMigrationProbePausedForTest(PAUSE_WAIT_MILLIS);
        if (!ProductService.statusMigrationProbePausedForTest()) {
            throw new IllegalStateException(
                    "探针未在 " + PAUSE_WAIT_MILLIS + "ms 内进入窗口 —— 判据装置坏了");
        }
    }

    // ────────────────────────────────── 真值读取（裸 JDBC，不经被测读面）

    private static String scalarString(String sql) {
        try (Connection c = dataSource.getConnection();
             Statement st = c.createStatement();
             ResultSet rs = st.executeQuery(sql)) {
            return rs.next() ? rs.getString(1) : null;
        } catch (SQLException e) {
            throw new IllegalStateException("真值读取失败: " + sql, e);
        }
    }

    // ────────────────────────────────── 夹具命名

    private static String productId(int round) {
        return PRODUCT_PREFIX + round;
    }

    // ────────────────────────────────── schema

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
