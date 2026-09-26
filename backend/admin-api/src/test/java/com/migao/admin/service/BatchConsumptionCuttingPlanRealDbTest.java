// case_ids: PR-065, PR-063
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.MybatisSqlSessionFactoryBuilder;
import com.baomidou.mybatisplus.extension.plugins.MybatisPlusInterceptor;
import com.baomidou.mybatisplus.extension.plugins.handler.TenantLineHandler;
import com.baomidou.mybatisplus.extension.plugins.inner.TenantLineInnerInterceptor;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.migao.admin.entity.StockBatchConsumption;
import com.migao.admin.mapper.CraftCalcConfigMapper;
import com.migao.admin.mapper.ProductSkuMapper;
import com.migao.admin.mapper.StockBatchConsumptionMapper;
import com.migao.admin.mapper.StockBatchMapper;
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
import java.net.ServerSocket;
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
import java.util.function.Function;
import java.util.stream.Stream;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.catchThrowable;

/**
 * 🔴 <b>领料按排料结果落账的**真库**判据（issue #5158：把 A 类排料接进生成加工单）</b>。
 *
 * <h2>为什么必须真库（Mockito 测不出来）</h2>
 * 本单的判据是「**批次余量上真的少扣了 3 米**」与「**同一张加工单不会二次扣**」——
 * 前者要真的把行写进 {@code stock_batch_consumptions} 再由 {@code stock_batches.quantity + Σdelta}
 * 算出余量，后者靠的是**部分唯一索引** {@code uk_batch_consumption_line} 的原子性。
 * mock 只会证明「调了哪个方法」：列名拼错 / 约束没生效 / 幂等闸缺失在 mock 面**结构上不可见**
 * （#5141 / #5148 的教训同族）。
 *
 * <h2>判据（每条都带**同参数的对照读数**，不是「跑了就算」）</h2>
 * <ol>
 *   <li><b>并排成立 ⇒ 扣 3 米（不是 6 米）</b>：门幅 2.8 / 窗高各 1.1 / 各需 3 米的两扇矮窗指派到同一批次
 *       ⇒ 真库读数 {@code Σ(−delta) = 3}；**红证 = 同参数但不给定尺入参**（= 改前形态，
 *       扣减口径 = 公式米数）⇒ {@code Σ(−delta) = 6}。两个读数在同一个测试里对照打印
 *       —— 「3 而不是 6」这句话因此不是自说自话。</li>
 *   <li><b>不倒退</b>：不可并排的组合 ⇒ 逐行 {@code planned == formula}（真库逐值比对）。</li>
 *   <li><b>两个米数可逐单审计</b>：{@code formula_meters} / {@code planned_meters} / 当时均价
 *       {@code unit_cost} 三列真落库，{@code saved_meters}/{@code saved_amount} 由实体派生读回。</li>
 *   <li><b>单价口径</b>：改掉 {@code stock_batches.unit_cost} 之后，历史单的 {@code saved_amount}
 *       **一字不变**（用的是行内快照，不是现价）。</li>
 *   <li><b>汇总一致</b>：按加工单聚合与按批次聚合的 {@code Σ saved_meters} 逐值相等。</li>
 *   <li><b>幂等不二次扣</b>：同一加工单重复落账 ⇒ 被唯一闸挡下（SQLSTATE 23505）、
 *       台账行数不变、批次余量不变。</li>
 * </ol>
 *
 * <h2>环境</h2>
 * 一次性真 PG 集群（{@code initdb} + {@code pg_ctl}，随机端口、跑完即停），schema 取自
 * {@code backend/admin-api/src/main/resources/db/init/schema.sql}（bootstrap 终态，**不手抄列清单** ⇒ 列名/约束漂移会被抓）。
 * 缺 PG 二进制 ⇒ {@link PgCluster#startOrAbort()}：
 * CI（{@code MIGAO_REQUIRE_REALDB=1}）⇒ 判红；本机未设该标记 ⇒ 显式 skip（「没跑」长得像「没跑」，不是通过）。
 *
 * <p>范式与 {@code ProductionScanClaimRealDbTest}（#4967）同款。</p>
 */
@DisplayName("#5158 真库守卫：领料按排料结果落账（并排 ⇒ 3 米）+ 两米数落库 + 幂等闸")
class BatchConsumptionCuttingPlanRealDbTest {

    private static final Long TENANT_ID = 5158L;
    private static final Long SKU_ID = 5158L;
    private static final String PRODUCT_ID = "acc-5158-prod";
    private static final String SKU_CODE = "SKU-A";
    /** 门幅 2.8 米 —— 两扇「窗高 1.1 + 卷边 0.3 = 占 1.4」的矮窗正好并排（1.4 + 1.4 = 2.8 ✓）。 */
    private static final String DOOR_WIDTH = "2.8米";
    private static final String UNIT_COST = "12.5";
    private static final String HEM_MARGIN = "0.3";

    private static PgCluster cluster;
    private static DataSource dataSource;
    private static SqlSessionFactory factory;
    private static SqlSession session;
    private static StockBatchConsumptionService service;

    @BeforeAll
    static void startRealPostgresAndFixtures() throws Exception {
        cluster = PgCluster.startOrAbort();
        dataSource = cluster.dataSource();
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute(schemaSql());
            st.execute("INSERT INTO tenants (id, name, code) OVERRIDING SYSTEM VALUE VALUES ("
                    + TENANT_ID + ", 'acc-5158', 'acc-5158')");
            st.execute("INSERT INTO products (id, tenant_id, name) VALUES ('" + PRODUCT_ID + "', "
                    + TENANT_ID + ", '布艺遮光帘A')");
            st.execute("INSERT INTO product_skus (id, tenant_id, product_id, door_width, price, stock,"
                    + " sku_code) OVERRIDING SYSTEM VALUE VALUES (" + SKU_ID + ", " + TENANT_ID + ", '"
                    + PRODUCT_ID + "', '" + DOOR_WIDTH + "', 100, 60, '" + SKU_CODE + "')");
            // 租户算料配置：只给主键与租户 ⇒ 其余列取**库默认值**（hem_margin 默认 0.3，
            // 与引擎常量 HEM_MARGIN 同值）—— 顺带证明「缺行 = 用默认值」这条路径也是通的。
            st.execute("INSERT INTO craft_calc_configs (id, tenant_id) VALUES ('cfg-acc-5158', "
                    + TENANT_ID + ")");
        }
        MybatisConfiguration configuration = new MybatisConfiguration();
        configuration.setMapUnderscoreToCamelCase(true);
        configuration.setEnvironment(new Environment("acc-5158", new JdbcTransactionFactory(), dataSource));
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
        for (Class<?> mapper : List.of(StockBatchMapper.class, StockBatchConsumptionMapper.class,
                ProductSkuMapper.class, CraftCalcConfigMapper.class)) {
            configuration.addMapper(mapper);
        }
        factory = new MybatisSqlSessionFactoryBuilder().build(configuration);
        session = factory.openSession(true);
        // 真装配：上下卷边走**算料配置的单一读面**（真库里的配置行），不是测试里塞的常量
        CraftCalcConfigService configService = new CraftCalcConfigService(
                session.getMapper(CraftCalcConfigMapper.class), null,
                // 审计腿（§22 P6）显式不装：本判据只读配置 / 排料，不写配置
                null);
        service = new StockBatchConsumptionService(session.getMapper(StockBatchMapper.class),
                session.getMapper(StockBatchConsumptionMapper.class),
                session.getMapper(ProductSkuMapper.class), null, configService,
                // 余料腿显式不装（V122 / issue #5146）：本判据覆盖的是**批次账**，余料是附加事实
                // —— null ⇒ 不登记余料，批次账行为与 #5158 逐字相同
                null);
    }

    @AfterAll
    static void stopRealPostgres() {
        if (session != null) {
            session.close();
        }
        if (cluster != null) {
            cluster.stop();
        }
    }

    // ────────────────────────────────────────────── 判据 1 / 2 / 3：并排 ⇒ 3 米

    @Test
    @DisplayName("🔴 判据1/红证：并排成立 ⇒ Σ(−delta) = 3 米；不给定尺入参（改前形态）⇒ 6 米")
    void pairableWindowsDeductThreeMetersNotSix() throws Exception {
        long batchId = newBatch("PC-5158-A", "60");
        List<StockBatchConsumptionService.Designation> pairable = List.of(
                fixedHeight("acc-5158-a1", "PC-5158-A", "3"),
                fixedHeight("acc-5158-a2", "PC-5158-A", "3"));
        // **改前形态**：同一对行、同一批次，只是扣减口径 = 公式米数（排料未接线）
        List<StockBatchConsumptionService.Designation> legacy = List.of(
                formulaOnly("acc-5158-a1", "PC-5158-A", "3"),
                formulaOnly("acc-5158-a2", "PC-5158-A", "3"));

        var legacyPlan = service.plan(TENANT_ID, legacy);
        System.out.println("[#5158 判别性实验] 改前形态（公式口径）逐行 = " + readings(legacyPlan));
        assertThat(sum(legacyPlan, StockBatchConsumptionService.Deduction::plannedMeters))
                .as("红证：不接线时两行各扣 3 米 ⇒ 合计 6 米").isEqualByComparingTo("6");

        var plan = service.plan(TENANT_ID, pairable);
        System.out.println("[#5158 判别性实验] 接线后（排料口径）逐行 = " + readings(plan));
        assertThat(sum(plan, StockBatchConsumptionService.Deduction::formulaMeters))
                .as("公式口径合计仍是 6（两个米数都要落库）").isEqualByComparingTo("6");
        assertThat(sum(plan, StockBatchConsumptionService.Deduction::plannedMeters))
                .as("🔴 本单的核心读数：并排后应领 3 米").isEqualByComparingTo("3");

        service.apply(TENANT_ID, "JG-5158-A", "ORD-5158-A", plan);

        // 真库读数（直读 SQL，不经过实体映射 ⇒ 列名/约束漂移也会被抓）
        assertThat(scalar("SELECT COALESCE(-SUM(delta), 0) FROM stock_batch_consumptions"
                + " WHERE processing_order_no = 'JG-5158-A' AND tenant_id = " + TENANT_ID))
                .as("🔴 真库落账：批次扣减 3 米（不是 6 米）").isEqualByComparingTo("3");
        assertThat(scalar("SELECT COALESCE(SUM(formula_meters), 0) FROM stock_batch_consumptions"
                + " WHERE processing_order_no = 'JG-5158-A'"))
                .as("公式口径 6 米也落了库（逐单可审计）").isEqualByComparingTo("6");
        assertThat(scalar("SELECT COALESCE(SUM(planned_meters), 0) FROM stock_batch_consumptions"
                + " WHERE processing_order_no = 'JG-5158-A'")).isEqualByComparingTo("3");
        assertThat(remainingOf(batchId)).as("省下的 3 米**留在批次余量上**（60 − 3）")
                .isEqualByComparingTo("57");
    }

    @Test
    @DisplayName("判据2 不倒退：不可并排（窗高 2.7 + 卷边 0.3 > 门幅 2.8）⇒ 逐行 planned == formula")
    void nonPairableKeepsFormulaExactly() throws Exception {
        long batchId = newBatch("PC-5158-B", "60");
        var plan = service.plan(TENANT_ID, List.of(
                fixedHeightOfHeight("acc-5158-b1", "PC-5158-B", "2.7", "2.7"),
                fixedHeightOfHeight("acc-5158-b2", "PC-5158-B", "2.7", "2.7")));

        assertThat(plan).allSatisfy(d -> assertThat(d.plannedMeters())
                .as("排不下就是排不下：口径与公式米数**逐值相同**（宁可为 0，不许估）")
                .isEqualByComparingTo(d.formulaMeters()));
        service.apply(TENANT_ID, "JG-5158-B", "ORD-5158-B", plan);
        assertThat(scalar("SELECT COALESCE(-SUM(delta), 0) FROM stock_batch_consumptions"
                + " WHERE processing_order_no = 'JG-5158-B'")).isEqualByComparingTo("5.4");
        assertThat(scalar("SELECT COALESCE(SUM(formula_meters - planned_meters), 0)"
                + " FROM stock_batch_consumptions WHERE processing_order_no = 'JG-5158-B'"))
                .as("saved_meters 恒为 0").isEqualByComparingTo("0");
        assertThat(remainingOf(batchId)).isEqualByComparingTo("54.6");
    }

    // ────────────────────────────────────────────── 判据 3 / 5：两个米数 + 当时均价

    @Test
    @DisplayName("🔴 判据3/单价口径：三列真落库；改批次均价后历史单 saved_amount 一字不变")
    void savedAmountUsesSnapshotCost() throws Exception {
        long batchId = newBatch("PC-5158-C", "60");
        var plan = service.plan(TENANT_ID, List.of(
                fixedHeight("acc-5158-c1", "PC-5158-C", "3"),
                fixedHeight("acc-5158-c2", "PC-5158-C", "3")));
        service.apply(TENANT_ID, "JG-5158-C", "ORD-5158-C", plan);

        assertThat(scalar("SELECT COALESCE(SUM(unit_cost), 0) / COUNT(*) FROM stock_batch_consumptions"
                + " WHERE processing_order_no = 'JG-5158-C'"))
                .as("当时该批次均价随行快照").isEqualByComparingTo(UNIT_COST);

        // 读面（实体派生）：逐单审计的两个米数与省钱数
        List<StockBatchConsumption> rows = consumptionRows("JG-5158-C");
        assertThat(rows).as("按加工单查回两行").hasSize(2);
        assertThat(rows.stream().map(StockBatchConsumption::getSavedMeters)
                .reduce(BigDecimal.ZERO, BigDecimal::add))
                .as("逐单可读：saved_meters = 3").isEqualByComparingTo("3");
        assertThat(rows.stream().map(StockBatchConsumption::getSavedAmount)
                .reduce(BigDecimal.ZERO, BigDecimal::add))
                .as("逐单可读：saved_amount = 3 × 12.5").isEqualByComparingTo("37.50");

        // 🔴 换价（调价 / 成本订正）⇒ 批次价变了，**历史单的省钱数不得变**
        exec("UPDATE stock_batches SET unit_cost = 99 WHERE id = " + batchId);
        List<StockBatchConsumption> afterRepricing = consumptionRows("JG-5158-C");
        assertThat(afterRepricing.stream().map(StockBatchConsumption::getSavedAmount)
                .reduce(BigDecimal.ZERO, BigDecimal::add))
                .as("🔴 用的是**当时**均价（行内快照）⇒ 换价后历史数不变").isEqualByComparingTo("37.50");
    }

    // ────────────────────────────────────────────── 判据 6：汇总一致

    @Test
    @DisplayName("判据6 汇总一致：按加工单聚合 == 按批次聚合（逐值相等，不许两套口径）")
    void summaryByOrderEqualsSummaryByBatch() throws Exception {
        newBatch("PC-5158-D", "60");
        var plan = service.plan(TENANT_ID, List.of(
                fixedHeight("acc-5158-d1", "PC-5158-D", "3"),
                fixedHeight("acc-5158-d2", "PC-5158-D", "3")));
        service.apply(TENANT_ID, "JG-5158-D", "ORD-5158-D", plan);

        BigDecimal byOrder = scalar("SELECT COALESCE(SUM(formula_meters - planned_meters), 0)"
                + " FROM stock_batch_consumptions WHERE processing_order_no = 'JG-5158-D'");
        BigDecimal byBatch = scalar("SELECT COALESCE(SUM(formula_meters - planned_meters), 0)"
                + " FROM stock_batch_consumptions WHERE batch_no = 'PC-5158-D'");
        System.out.println("[#5158 判别性实验] 按加工单汇总 = " + byOrder + "，按批次汇总 = " + byBatch);
        assertThat(byOrder).isEqualByComparingTo("3");
        assertThat(byBatch).as("两条路聚合的是同一批行、同一个列族").isEqualByComparingTo(byOrder);
    }

    // ────────────────────────────────────────────── 判据 8：幂等

    @Test
    @DisplayName("🔴 判据8 幂等：同一加工单重复落账 ⇒ 唯一闸挡下（23505）、行数不变、余量不变")
    void repeatedApplyIsRejectedByUniqueGate() throws Exception {
        long batchId = newBatch("PC-5158-E", "60");
        var plan = service.plan(TENANT_ID, List.of(
                fixedHeight("acc-5158-e1", "PC-5158-E", "3"),
                fixedHeight("acc-5158-e2", "PC-5158-E", "3")));
        service.apply(TENANT_ID, "JG-5158-E", "ORD-5158-E", plan);
        BigDecimal remainingAfterFirst = remainingOf(batchId);
        long rowsAfterFirst = countRows("JG-5158-E");

        // 重新规划同一张单（等价于「重复生成加工单」走到落账这一步）再落一次
        var replanned = service.plan(TENANT_ID, List.of(
                fixedHeight("acc-5158-e1", "PC-5158-E", "3"),
                fixedHeight("acc-5158-e2", "PC-5158-E", "3")));
        Throwable failure = catchThrowable(() ->
                service.apply(TENANT_ID, "JG-5158-E", "ORD-5158-E", replanned));

        assertThat(failure).as("第二遍必须被挡下（不得静默二次扣减）").isNotNull();
        assertThat(sqlStateOf(failure)).as("挡下它的就是 uk_batch_consumption_line（SQLSTATE 23505）")
                .isEqualTo("23505");
        assertThat(countRows("JG-5158-E")).as("台账行数不变").isEqualTo(rowsAfterFirst);
        assertThat(remainingOf(batchId)).as("🔴 余量不再变化（没有二次扣减）")
                .isEqualByComparingTo(remainingAfterFirst);
    }

    // ────────────────────────────────────────────── 夹具与工具

    /** 定高买宽的两扇矮窗（门幅 2.8：窗高 1.1 + 卷边 0.3 = 各占 1.4 ⇒ 并排成立）。 */
    private static StockBatchConsumptionService.Designation fixedHeight(String itemId, String batchNo,
                                                                        String meters) {
        return fixedHeightOfHeight(itemId, batchNo, meters, "1.1");
    }

    private static StockBatchConsumptionService.Designation fixedHeightOfHeight(String itemId,
                                                                               String batchNo,
                                                                               String meters,
                                                                               String height) {
        return new StockBatchConsumptionService.Designation(itemId, PRODUCT_ID, SKU_CODE, batchNo,
                new BigDecimal(meters), "定高买宽", new BigDecimal(height), null);
    }

    /** **改前形态**：只给公式米数（没有定尺入参 ⇒ 不排料 ⇒ 扣减口径 = 公式米数）。 */
    private static StockBatchConsumptionService.Designation formulaOnly(String itemId, String batchNo,
                                                                       String meters) {
        return new StockBatchConsumptionService.Designation(itemId, PRODUCT_ID, SKU_CODE, batchNo,
                new BigDecimal(meters), null, null, null);
    }

    private static List<String> readings(List<StockBatchConsumptionService.Deduction> plan) {
        List<String> out = new ArrayList<>();
        for (StockBatchConsumptionService.Deduction d : plan) {
            out.add(d.orderItemId() + " formula=" + d.formulaMeters().toPlainString()
                    + " planned=" + d.plannedMeters().toPlainString());
        }
        return out;
    }

    private static BigDecimal sum(List<StockBatchConsumptionService.Deduction> plan,
                                  Function<StockBatchConsumptionService.Deduction, BigDecimal> getter) {
        BigDecimal total = BigDecimal.ZERO;
        for (StockBatchConsumptionService.Deduction d : plan) {
            total = total.add(getter.apply(d));
        }
        return total;
    }

    /** 按加工单读回台账行（走**实体**路径 ⇒ saved_meters / saved_amount 这两个派生值是读回来的）。 */
    private static List<StockBatchConsumption> consumptionRows(String processingOrderNo) {
        return session.getMapper(StockBatchConsumptionMapper.class).selectList(
                new LambdaQueryWrapper<StockBatchConsumption>()
                        .eq(StockBatchConsumption::getTenantId, TENANT_ID)
                        .eq(StockBatchConsumption::getProcessingOrderNo, processingOrderNo));
    }

    /** 建一个批次（数量 / 当时均价固定），返回它的 id。 */
    private static long newBatch(String batchNo, String meters) throws Exception {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery("INSERT INTO stock_batches (tenant_id, batch_no, product_id,"
                     + " sku_id, sku_code, quantity, unit_cost) VALUES (" + TENANT_ID + ", '" + batchNo
                     + "', '" + PRODUCT_ID + "', " + SKU_ID + ", '" + SKU_CODE + "', " + meters + ", "
                     + UNIT_COST + ") RETURNING id")) {
            assertThat(rs.next()).as("批次夹具必须落库").isTrue();
            return rs.getLong(1);
        }
    }

    /** 批次余量 = {@code stock_batches.quantity + Σ(delta)}（与生产读面同一条公式）。 */
    private static BigDecimal remainingOf(long batchId) throws Exception {
        return scalar("SELECT (SELECT quantity FROM stock_batches WHERE id = " + batchId + ")"
                + " + COALESCE((SELECT SUM(delta) FROM stock_batch_consumptions WHERE batch_id = "
                + batchId + " AND deleted = 0), 0)");
    }

    private static long countRows(String processingOrderNo) throws Exception {
        return scalar("SELECT COUNT(*) FROM stock_batch_consumptions WHERE processing_order_no = '"
                + processingOrderNo + "'").longValue();
    }

    private static BigDecimal scalar(String sql) throws Exception {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery(sql)) {
            assertThat(rs.next()).as("查询必须有结果：" + sql).isTrue();
            return rs.getBigDecimal(1);
        }
    }

    private static void exec(String sql) throws Exception {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute(sql);
        }
    }

    /** 沿 cause 链找 SQLSTATE（唯一闸的证据必须是数据库给的，不是文案匹配）。 */
    private static String sqlStateOf(Throwable failure) {
        Throwable current = failure;
        while (current != null) {
            if (current instanceof SQLException sqlException) {
                return sqlException.getSQLState();
            }
            current = current.getCause();
        }
        return null;
    }

    private static String schemaSql() throws IOException {
        Path root = Paths.get(System.getProperty("user.dir")).toAbsolutePath();
        while (root != null && !Files.exists(root.resolve("backend/admin-api/src/main/resources/db/init/schema.sql"))) {
            root = root.getParent();
        }
        assertThat(root).as("必须能定位 backend/admin-api/src/main/resources/db/init/schema.sql（真库建表取终态 schema，不手抄列清单）").isNotNull();
        return Files.readString(root.resolve("backend/admin-api/src/main/resources/db/init/schema.sql"));
    }
}
