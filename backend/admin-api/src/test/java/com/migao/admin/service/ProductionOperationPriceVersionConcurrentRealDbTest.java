// case_ids: PP-022

package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.MybatisSqlSessionFactoryBuilder;
import com.baomidou.mybatisplus.extension.plugins.MybatisPlusInterceptor;
import com.baomidou.mybatisplus.extension.plugins.handler.TenantLineHandler;
import com.baomidou.mybatisplus.extension.plugins.inner.TenantLineInnerInterceptor;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.ProductionOperationMapper;
import com.migao.admin.mapper.ProductionOperationPositionMapper;
import com.migao.admin.mapper.ProductionOperationPriceVersionMapper;
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
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CyclicBarrier;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;

/**
 * 真库并发判据（issue #6238）：<b>工序改价的并发面 —— N=4 并发提交<b>同一次</b>调价
 * ⇒ 价格版本账恰追加 1 行（不是 4 行）</b>。
 *
 * <h2>核验的是哪一条主张</h2>
 * 台账 {@code after-sales-sideeffect-concurrency-ledger.json} 的 {@code unverified} 条目逐字写着：
 * 「{@code ProductionOperationCommandService#update}：⚠️ <b>涉钱面</b>：价格版本<b>追加 insert</b> +
 * 可选状态写 ⇒ 并发重复提交可能重复追加版本行；本单未核验」。本条判据把「可能」变成「读数」。
 *
 * <h2>为什么必须真库 + 真并发</h2>
 * 缺陷形态是<b>读-判-写</b>：{@code selectById} 读旧价 → 应用层判「价变了吗」→ 条件追加版本行。
 * 「两个请求是否都读到<b>同一个</b>旧价」这件事，只有真 PG 才有语义：
 * <b>① 行的排他锁</b>（{@code SELECT … FOR UPDATE} 命中行的锁持有到事务结束）与
 * <b>② READ COMMITTED 下的锁后重读</b>（后到者阻塞到前者提交后按<b>新版本行</b>重估谓词）。
 * mock 面结构上判不了：mock 的 {@code selectById} 恒返回同一份夹具对象、{@code insert} 恒被调用
 * ⇒「恰追加一行」在 mock 上恒绿（假绿）。而「几行版本账落库」本身就是<b>并发下的落库读数</b>。
 *
 * <h2>判据（每条都会红）</h2>
 * <ol>
 *   <li><b>版本账恰追加 1 行</b>（<b>主判据，取库内事实</b>）：{@code unit_price = 新价} 的行数 == 1；
 *       重复追加 ⇒ 等于 {@value #CONCURRENCY}；</li>
 *   <li><b>账目总行数 == 基线 1 + 追加 1</b>（独立算式，取夹具常量，<b>不读被测读面</b>）；</li>
 *   <li><b>当前价</b>：{@code production_operations.unit_price} == 新价；</li>
 *   <li><b>「当前价 = 最新版本行」契约在并发下仍成立</b>：{@code created_at} 最新那行的价 == 当前价
 *       （重复追加会造出「最新行说 200、行上说 300」这类自相矛盾的调价账）；</li>
 *   <li><b>4 个请求都不被误杀</b>：同价重复提交是<b>幂等空操作</b>（请求的意图「价 = 200」已达成），
 *       不是冲突 ⇒ 全部正常返回（这条与 1 合起来才是完整语义：<b>不重复追加、也不静默丢改动</b>）；</li>
 *   <li><b>串行正对照（闸不误杀）</b>：单请求串行改价必须真的追加 1 行；随后<b>同价重复提交</b>
 *       必须仍是 1 行（幂等空操作路径没被闸改坏）。</li>
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
 * <h2>库层兜底（可复核判据）</h2>
 * 本表除主键外<b>没有</b>唯一约束（{@code pg_indexes} 实测 + 「直接插两行同
 * {@code (operation_id, unit_price)} 被库接受」的反向自证）⇒ 「同一次调价只追加一行」<b>不可能</b>由
 * DDL 提供，只能由本方法自己的闸提供 —— 这就是这条判据存在的理由。
 *
 * <h2>判别力（红证，注入式 · 双向）</h2>
 * 把读旧价那一步退回<b>不加锁</b>的 {@code selectById}（= 本单修前的形态）⇒ 本判据必红，
 * 实测读数 = 4 个请求全成功 / {@code unit_price = 200.00} 的行 <b>4</b> 行 / 总行数 <b>5</b> 行
 * （基线 1 + 4）。注入方式与成对读数见 PR body（注入是手动的、一次性的动作，不落成常驻判据）。
 *
 * <p><b>边界（如实登记）</b>：① 本判据跑的是<b>真库并发</b>而非 HTTP 栈
 * （{@code PUT /api/admin/production/operations/{id}} 只是薄转发，读-判-写全在服务层）
 * —— 因此它<b>不</b>证 HTTP 层的行为；② <b>本端点没有 {@code Idempotency-Key} 入口</b>
 * （见 {@link #updateEndpointOffersNoIdempotencyKeyEntry()} 的实测），故「带幂等键的并发入口」这一格
 * <b>在对象上不存在</b>，不是漏测；③ 探针对象全部自建（tenant {@value #TENANT_ID} / 工序前缀
 * {@code op-6238-}），随一次性临时集群销毁，<b>不碰任何存量数据</b>；
 * ④ 同一工序的并发<b>异价</b>提交（A 改 200、B 改 300）不在本判据的断言面内 —— 修法把两者串行化
 * ⇒ 两次变更各自成行、当前价 = 后提交者，本判据只登记该语义、未逐值断言。</p>
 */
@DisplayName("🔴 真库并发判据（#6238）：N=4 并发提交同一工序的同一次调价 ⇒ 价格版本账只追加 1 行")
class ProductionOperationPriceVersionConcurrentRealDbTest {

    private static final Long TENANT_ID = 6238L;

    /** 改价前单价（夹具常量，独立于被测读面）。 */
    private static final BigDecimal OLD_PRICE = new BigDecimal("100.00");
    /** 本次提交的新单价。 */
    private static final BigDecimal NEW_PRICE = new BigDecimal("200.00");

    /** 独立算式：基线 1 行（V55/V96 口径下活跃工序恒有一行「当前价 = 最新版本行」）+ 追加 1 行。 */
    private static final long EXPECTED_TOTAL_ROWS = 2L;
    /** 同一次调价只追加 1 行版本账。 */
    private static final long EXPECTED_APPENDED_ROWS = 1L;

    private static final int CONCURRENCY = 4;
    private static final int ROUNDS = 3;

    /** 留给「串行正对照（闸不误杀）」的探针工序：<b>不参与</b>并发装置。 */
    private static final int SERIAL_ROUND = ROUNDS + 1;

    /** 留给「库层零兜底」探针的专用工序（**不参与**并发装置与正对照 ⇒ 计数不受测试执行顺序影响）。 */
    private static final String PROBE_OP_ID = "op-6238-probe";

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
                    + TENANT_ID + ", 'pv-6238', 'pv-6238')");
            for (int r = 1; r <= SERIAL_ROUND; r++) {
                // 起点 = 活跃工序 + 一行基线版本账（与 V96 回填后的生产形态同构：当前价 = 最新版本行）
                st.execute("INSERT INTO production_operations "
                        + "(id, tenant_id, name, group_name, unit, unit_price, status, deleted) VALUES ('"
                        + operationId(r) + "', " + TENANT_ID + ", '工序-6238-r" + r
                        + "', '其他', '米', " + OLD_PRICE.toPlainString() + ", 'active', 0)");
                st.execute("INSERT INTO production_operation_price_versions "
                        + "(id, tenant_id, operation_id, unit_price, deleted) VALUES ('"
                        + baselineVersionId(r) + "', " + TENANT_ID + ", '" + operationId(r) + "', "
                        + OLD_PRICE.toPlainString() + ", 0)");
            }
            st.execute("INSERT INTO production_operations "
                    + "(id, tenant_id, name, group_name, unit, unit_price, status, deleted) VALUES ('"
                    + PROBE_OP_ID + "', " + TENANT_ID + ", '工序-6238-probe', '其他', '米', "
                    + OLD_PRICE.toPlainString() + ", 'active', 0)");
        }

        MybatisConfiguration configuration = new MybatisConfiguration();
        configuration.setMapUnderscoreToCamelCase(true);
        configuration.setEnvironment(new Environment("pv-6238", new JdbcTransactionFactory(), dataSource));
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
        for (Class<?> mapper : List.of(ProductionOperationMapper.class,
                ProductionOperationPriceVersionMapper.class, ProductionOperationPositionMapper.class)) {
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
    @DisplayName("N=4 并发提交同一工序的同一次调价（3 轮）：版本账恰追加 1 行 / 当前价 200.00 / 账目自洽")
    void concurrentSamePriceSubmissionAppendsExactlyOneVersionRow() throws Exception {
        // 3 轮**全部跑完再断言**（断言写在循环里会在第 1 轮抛 ⇒ 看不到 2/3 轮的读数，
        // 而「缺陷时序敏感、单轮可能侥幸变绿」正是要 3 轮的理由）
        List<Long> appendedPerRound = new ArrayList<>();
        List<Long> totalPerRound = new ArrayList<>();
        List<BigDecimal> pricePerRound = new ArrayList<>();
        List<BigDecimal> newestVersionPerRound = new ArrayList<>();
        List<Long> successPerRound = new ArrayList<>();
        for (int round = 1; round <= ROUNDS; round++) {
            String opId = operationId(round);
            List<Outcome> outcomes = runConcurrently(opId);

            long success = outcomes.stream().filter(Outcome::success).count();
            List<Integer> statuses = outcomes.stream().map(Outcome::httpStatus).sorted().toList();
            BigDecimal currentPrice = scalarDecimal(
                    "SELECT unit_price FROM production_operations WHERE id = '" + opId + "'");
            long totalRows = versionRowCount(opId, null);
            long appendedRows = versionRowCount(opId, NEW_PRICE);
            BigDecimal newestVersionPrice = scalarDecimal(
                    "SELECT unit_price FROM production_operation_price_versions WHERE operation_id = '"
                            + opId + "' AND deleted = 0 ORDER BY created_at DESC, id DESC LIMIT 1");

            System.out.println("[READING #6238 round " + round + "] 成功数=" + success
                    + " 各请求状态码=" + statuses
                    + " 当前价=" + currentPrice + " 版本账总行数=" + totalRows
                    + " 其中新价行=" + appendedRows + " 最新版本行价=" + newestVersionPrice);
            printOverlapEvidence(round, outcomes);

            appendedPerRound.add(appendedRows);
            totalPerRound.add(totalRows);
            pricePerRound.add(currentPrice);
            newestVersionPerRound.add(newestVersionPrice);
            successPerRound.add(success);
            assertThat(statuses).as("状态码只许是 200（幂等成功）").containsOnly(200);
        }

        assertThat(appendedPerRound)
                .as("同一次调价只许追加 1 行版本账（涉钱追加型不可逆）；重复追加 ⇒ 会等于 " + CONCURRENCY)
                .containsOnly(EXPECTED_APPENDED_ROWS);
        assertThat(totalPerRound)
                .as("版本账总行数必须 == 基线 1 + 追加 1（独立算式，取夹具常量）")
                .containsOnly(EXPECTED_TOTAL_ROWS);
        assertThat(pricePerRound).as("当前价").allSatisfy(
                p -> assertThat(p).isEqualByComparingTo(NEW_PRICE));
        assertThat(newestVersionPerRound)
                .as("「当前价 = 最新版本行」契约必须在并发下仍成立（重复追加会造出自相矛盾的调价账）")
                .containsExactlyElementsOf(pricePerRound);
        assertThat(successPerRound)
                .as("同价重复提交是**幂等空操作**（意图已达成），4 个请求都不得被误杀；"
                        + "落败请求必须在状态码上显式（若将来改为拒绝，须同步改本判据与台账）")
                .containsOnly((long) CONCURRENCY);
    }

    @Test
    @DisplayName("正对照（闸不误杀）：单请求串行改价真追加 1 行；随后同价重复提交仍是 1 行")
    void serialPriceChangeStillAppendsExactlyOneRow() {
        // 这条正对照与并发判据合起来才是完整证据：闸**拦得住并发**且**不误杀正常请求**
        // （也不把「同价重复提交」这条既有的幂等空操作路径改坏）。
        int round = SERIAL_ROUND;
        String opId = operationId(round);
        try (SqlSession s = factory.openSession(false)) {
            serviceOn(s).update(opId, Map.of("unit_price", NEW_PRICE), TENANT_ID);
            s.commit();
        }
        long appendedAfterFirst = versionRowCount(opId, NEW_PRICE);
        BigDecimal priceAfterFirst = scalarDecimal(
                "SELECT unit_price FROM production_operations WHERE id = '" + opId + "'");
        // 第二次**同价**提交（串行到达）：既有的「单价没变 ⇒ 不追加」路径必须仍然生效
        try (SqlSession s = factory.openSession(false)) {
            serviceOn(s).update(opId, Map.of("unit_price", NEW_PRICE), TENANT_ID);
            s.commit();
        }
        long appendedAfterSecond = versionRowCount(opId, NEW_PRICE);
        System.out.println("[READING #6238 正对照 串行] 当前价=" + priceAfterFirst
                + " 首次追加行=" + appendedAfterFirst + " 同价重复提交后追加行=" + appendedAfterSecond);

        assertThat(priceAfterFirst).as("串行单请求必须真的改价成功（这条红了 = 闸误杀正常请求）")
                .isEqualByComparingTo(NEW_PRICE);
        assertThat(appendedAfterFirst).as("串行单请求恰追加 1 行版本账").isEqualTo(EXPECTED_APPENDED_ROWS);
        assertThat(appendedAfterSecond).as("同价重复提交是幂等空操作（既有口径，不许被本单改坏）")
                .isEqualTo(EXPECTED_APPENDED_ROWS);
        assertThat(versionRowCount(opId, null)).as("两次提交后总量仍是基线 1 + 追加 1")
                .isEqualTo(EXPECTED_TOTAL_ROWS);
    }

    // ────────────────────────────────────────────── 判据 6：库层兜底实测

    @Test
    @DisplayName("库层零兜底（可复核判据）：除主键外无唯一约束 ⇒ 重复版本行只能靠应用层的闸挡住")
    void priceVersionTableHasNoUniqueBackstop() throws Exception {
        List<String> uniqueIndexes = scalarList(
                "SELECT indexname FROM pg_indexes WHERE tablename = 'production_operation_price_versions'"
                        + " AND indexdef LIKE '%UNIQUE%' ORDER BY indexname");
        List<String> allIndexes = scalarList(
                "SELECT indexname FROM pg_indexes WHERE tablename = 'production_operation_price_versions'"
                        + " ORDER BY indexname");
        // 反向自证：库里**直接**插两行同 (operation_id, unit_price) 被接受（回滚 ⇒ 零残留）
        long acceptedDuplicates;
        try (Connection c = dataSource.getConnection()) {
            c.setAutoCommit(false);
            try (Statement st = c.createStatement()) {
                for (int i = 0; i < 2; i++) {
                    st.execute("INSERT INTO production_operation_price_versions "
                            + "(id, tenant_id, operation_id, unit_price, deleted) VALUES ('pv-6238-probe-" + i
                            + "', " + TENANT_ID + ", '" + PROBE_OP_ID + "', " + NEW_PRICE.toPlainString() + ", 0)");
                }
            }
            // 计数必须在**同一个连接 / 同一个未提交事务**里做：另开连接看不到未提交行（会恒得 0）
            try (Statement st = c.createStatement();
                 ResultSet rs = st.executeQuery(
                         "SELECT count(*) FROM production_operation_price_versions WHERE operation_id = '"
                                 + PROBE_OP_ID + "' AND unit_price = " + NEW_PRICE.toPlainString())) {
                acceptedDuplicates = rs.next() ? rs.getLong(1) : 0L;
            }
            c.rollback();
        }
        // 收尾核对：回滚后探针行**零残留**（共享 dev 库上不做破坏性写）
        assertThat(versionRowCount(PROBE_OP_ID, NEW_PRICE)).as("探针事务回滚后必须零残留").isZero();
        System.out.println("[READING #6238 库层兜底] 全部索引=" + allIndexes
                + " 唯一索引=" + uniqueIndexes + " 直接插入同键重复行被接受数=" + acceptedDuplicates);

        assertThat(allIndexes).as("索引清单非空（判据不做空跑）").isNotEmpty();
        assertThat(uniqueIndexes)
                .as("本表除主键外**无**唯一约束 ⇒ DDL 兜不住重复版本行 —— 若将来加了唯一索引，"
                        + "两条读数都会变（撞约束是 500 还是 409 须重新裁定）⇒ 本判据转红即是复核信号")
                .containsExactly("production_operation_price_versions_pkey");
        assertThat(acceptedDuplicates)
                .as("库**接受**两行同 (operation_id, unit_price)：这就是「应用层的闸是唯一防线」的实测")
                .isEqualTo(2L);
    }

    // ────────────────────────────────────────────── 判据 7：入口面（幂等键）

    @Test
    @DisplayName("入口面（可复核）：PUT /operations/{id} 无 Idempotency-Key ⇒ 重复提交唯一防线是服务层自身的闸")
    void updateEndpointOffersNoIdempotencyKeyEntry() throws IOException {
        String controller = Files.readString(repoRoot().resolve(
                "backend/admin-api/src/main/java/com/migao/admin/controller/ProductionController.java"));
        int at = controller.indexOf("updateOperation(");
        assertThat(at).as("端点方法必须仍在场（改名 ⇒ 判据失明要当场暴露，不是静默通过）").isNotNegative();
        String window = controller.substring(at, Math.min(at + 400, controller.length()));
        boolean hasKey = window.contains("Idempotency");
        System.out.println("[READING #6238 入口面] updateOperation 窗口含 Idempotency-Key = " + hasKey);
        assertThat(window)
                .as("本端点**没有**幂等键入口 ⇒ 「并发重复提交只追加一次」只能由服务层自己的闸提供"
                        + "（无第二道防线）。若将来加了 Idempotency-Key，本判据转红 ⇒ 须复核同键并发的语义")
                .doesNotContain("Idempotency");
    }

    // ────────────────────────────────────────────── 并发装置

    /**
     * N=4 并发改价：每个请求<b>自己的 SqlSession + 自己的连接 + 自己的事务</b>，
     * 用 {@link CyclicBarrier} 把 4 个请求对齐到同一时刻起跑（否则线程调度会把它串行化 ⇒ 假绿）。
     * 4 个请求提交的是<b>同一个新价</b>（= 「同一次调价被重复提交」）。
     */
    private static List<Outcome> runConcurrently(String opId) throws Exception {
        ExecutorService pool = Executors.newFixedThreadPool(CONCURRENCY);
        CyclicBarrier barrier = new CyclicBarrier(CONCURRENCY);
        List<Future<Outcome>> futures = new ArrayList<>();
        try {
            for (int i = 0; i < CONCURRENCY; i++) {
                futures.add(pool.submit(() -> {
                    barrier.await(30, TimeUnit.SECONDS);
                    long start = System.nanoTime();
                    try (SqlSession s = factory.openSession(false)) {
                        serviceOn(s).update(opId, Map.of("unit_price", NEW_PRICE), TENANT_ID);
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
        System.out.println("[真重叠 #6238 round " + round + "] 区间(ms, 同一起点)="
                + intervals.stream().map(iv -> "[" + iv.start() + "," + iv.end() + "]").toList()
                + " 相交对数=" + overlappingPairs + "/" + (intervals.size() * (intervals.size() - 1) / 2)
                + " 并集跨度=" + union + "ms 各历时之和=" + sum + "ms"
                + " ⇒ " + (trulyOverlapping ? "真重叠（并集 < 各历时之和）" : "⚠️ 本轮区间两两不交 = 实际串行"));
    }

    /** 一次并发请求的结果（成功 / 失败 + HTTP 业务码 + 自己的时间区间）。 */
    private record Outcome(boolean success, int httpStatus, long startNanos, long endNanos) {
    }

    /**
     * 真装配：本判据的对象（改价状态机 + 版本账追加）走<b>真库 mapper</b>。
     * 读面 {@link ProductionOperationQueryService} 只用于拼响应视图，与库内事实无关 ⇒ mock
     * （响应体不是本判据的断言面；把它换成真对象会把读面的依赖整片拖进来）。
     */
    private static ProductionOperationCommandService serviceOn(SqlSession s) {
        return new ProductionOperationCommandService(
                s.getMapper(ProductionOperationMapper.class),
                s.getMapper(ProductionOperationPriceVersionMapper.class),
                s.getMapper(ProductionOperationPositionMapper.class),
                mock(ProductionOperationQueryService.class));
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

    private static List<String> scalarList(String sql) {
        List<String> values = new ArrayList<>();
        try (Connection c = dataSource.getConnection();
             Statement st = c.createStatement();
             ResultSet rs = st.executeQuery(sql)) {
            while (rs.next()) {
                values.add(rs.getString(1));
            }
        } catch (SQLException e) {
            throw new IllegalStateException("真值读取失败: " + sql, e);
        }
        return values;
    }

    private static long versionRowCount(String opId, BigDecimal price) {
        return scalarLong("SELECT count(*) FROM production_operation_price_versions WHERE operation_id = '"
                + opId + "' AND deleted = 0" + (price == null ? "" : " AND unit_price = " + price.toPlainString()));
    }

    private static String operationId(int round) {
        return "op-6238-r" + round;
    }

    private static String baselineVersionId(int round) {
        return "pv-6238-base-r" + round;
    }

    // ────────────────────────────────────────────── schema

    private static String schemaSql() throws IOException {
        return Files.readString(repoRoot().resolve(
                "backend/admin-api/src/main/resources/db/init/schema.sql"));
    }

    private static Path repoRoot() {
        Path root = Paths.get(System.getProperty("user.dir")).toAbsolutePath();
        while (root != null
                && !Files.exists(root.resolve("backend/admin-api/src/main/resources/db/init/schema.sql"))) {
            root = root.getParent();
        }
        assertThat(root).as("必须能定位仓库根（backend/admin-api/src/main/resources/db/init/schema.sql）")
                .isNotNull();
        return root;
    }
}
