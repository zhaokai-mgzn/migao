// case_ids: PR-071
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.MybatisSqlSessionFactoryBuilder;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.MybatisPlusInterceptor;
import com.baomidou.mybatisplus.extension.plugins.handler.TenantLineHandler;
import com.baomidou.mybatisplus.extension.plugins.inner.TenantLineInnerInterceptor;
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
import org.junit.jupiter.api.Assumptions;
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
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.catchThrowable;

/**
 * 🔴 <b>跨订单成组派单的**真库**判据（issue #5169 判据 2 —— 本单的存在理由）</b>。
 *
 * <h2>为什么必须真库（Mockito 测不出来）</h2>
 * 本单的判据是「**池内两张单各一扇可并排的矮窗 ⇒ 批次账上真的只扣了 3 米，不是 6 米**」。
 * 它要真的把行写进 {@code stock_batch_consumptions}、再由
 * {@code stock_batches.quantity + Σdelta} 算出余量才读得出来；而「重复成批不重复扣」
 * 靠的是**部分唯一索引** {@code uk_batch_consumption_line} 的原子性。
 * mock 只会证明「调了哪个方法」：列名拼错 / 约束没生效 / 幂等闸缺失在 mock 面**结构上不可见**
 * （#5141 / #5148 / #5158 的教训同族）。
 *
 * <h2>判据（每条都带**同参数的对照读数**，不是「跑了就算」）</h2>
 * <ol>
 *   <li><b>跨订单并排成立 ⇒ 3 米而不是 6 米</b>：两张单（A / B）各一扇矮窗、同一批次、同一加工类型
 *       ⇒ 池级一次求解后 {@code Σ(−delta) = 3}；**红证 = 逐单派**（同一对行，各调一次
 *       {@code plan}）⇒ {@code Σ(−delta) = 6}。两个读数在同一个测试里对照打印 ——
 *       「3 而不是 6」因此不是自说自话；而「池化到底改了什么」= 这两次调用次数的差别。</li>
 *   <li><b>落账仍按**各自的加工单**</b>：3 米拆成 2 行、两行分属 {@code JG-…-A} 与 {@code JG-…-B}
 *       （「一单一加工单」的约束不变，池化只改「排料与批次分配在池级求解」）。</li>
 *   <li><b>预览不说谎</b>：预览口径（{@code Σ(formula − planned)}，与
 *       {@code ProductionPoolViews.Preview.savedMeters} 同一算式）**逐值等于**真库里的
 *       {@code Σ(formula_meters − planned_meters)} 与实体派生的 {@code Σ saved_meters}；
 *       且**对照**逐单派口径得到的是 0（⇒ 这条断言有判别力：两套口径会给出不同的数）。</li>
 *   <li><b>不倒退（跨批次不得成组）</b>：两张单若分属**不同批次**，池级求解与逐单派**逐值相同**
 *       （每行 {@code planned == formula}）—— 成组键含批次（#5158 口径），本单不动它。</li>
 *   <li><b>幂等</b>：重复落同一张单的台账 ⇒ 被唯一闸挡下（SQLSTATE 23505）、行数不变、余量不变。</li>
 *   <li><b>不损失客户</b>：{@code product_skus.stock} 与 {@code stock_ledger_entries} 指纹
 *       **一字不动**；公式口径（{@code Σ formula_meters}）在「池化派」与「逐单派」下**逐值相同**
 *       （对客口径不由排料方式决定）。</li>
 * </ol>
 *
 * <h2>环境</h2>
 * 一次性真 PG 集群（{@code initdb} + {@code pg_ctl}，随机端口、跑完即停；共用 {@link PgCluster}），
 * schema 取自 {@code docs/sql/schema.sql}（bootstrap 终态，**不手抄列清单** ⇒ 列名/约束漂移会被抓）。
 * 本机没有 PG 二进制 ⇒ <b>显式 skip</b>（「没跑」必须长得像「没跑」，不是通过）。
 *
 * <p>范式与 {@code BatchAssignmentRuleRealDbTest}（#5167）/ {@code BatchConsumptionCuttingPlanRealDbTest}
 * （#5158）同款：真库层把**批次账**钉死，而「池级只调一次 plan」这件事在
 * {@code ProcessingOrderServiceTest}（PR-070）里以「{@code plan} 被调用几次、入参是哪些行」的
 * 装配判据覆盖 —— 两条判据合起来才是完整的跨订单成组。</p>
 */
@DisplayName("#5169 真库守卫：跨订单成组派单（两张单并排 ⇒ 1 行 3 米，而不是 2 行 6 米）")
class PooledDispatchRealDbTest {

    private static final Long TENANT_ID = 5169L;
    private static final Long SKU_ID = 5169L;
    private static final String PRODUCT_ID = "acc-5169-prod";
    private static final String SKU_CODE = "SKU-A";
    /** 门幅 2.8 米 —— 两张单各一扇「窗高 1.1 + 卷边 0.3 = 占 1.4」的矮窗正好并排（1.4 + 1.4 = 2.8 ✓）。 */
    private static final String DOOR_WIDTH = "2.8米";
    private static final String UNIT_COST = "12.5";

    private static PgCluster cluster;
    private static DataSource dataSource;
    private static SqlSessionFactory factory;
    private static SqlSession session;
    private static StockBatchConsumptionService service;

    @BeforeAll
    static void startRealPostgresAndFixtures() throws Exception {
        cluster = PgCluster.start();
        if (cluster == null) {
            Assumptions.abort("本机没有 PG 二进制（initdb/pg_ctl）⇒ 真库判据**未跑**（不是通过）");
        }
        dataSource = cluster.dataSource();
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute(schemaSql());
            st.execute("INSERT INTO tenants (id, name, code) OVERRIDING SYSTEM VALUE VALUES ("
                    + TENANT_ID + ", 'acc-5169', 'acc-5169')");
            st.execute("INSERT INTO products (id, tenant_id, name) VALUES ('" + PRODUCT_ID + "', "
                    + TENANT_ID + ", '布艺遮光帘A')");
            st.execute("INSERT INTO product_skus (id, tenant_id, product_id, door_width, price, stock,"
                    + " sku_code) OVERRIDING SYSTEM VALUE VALUES (" + SKU_ID + ", " + TENANT_ID + ", '"
                    + PRODUCT_ID + "', '" + DOOR_WIDTH + "', 100, 60, '" + SKU_CODE + "')");
            // 租户算料配置：只给主键与租户 ⇒ 其余列取库默认值（hem_margin 默认 0.3，与引擎常量同值）
            st.execute("INSERT INTO craft_calc_configs (id, tenant_id) VALUES ('cfg-acc-5169', "
                    + TENANT_ID + ")");
        }
        MybatisConfiguration configuration = new MybatisConfiguration();
        configuration.setMapUnderscoreToCamelCase(true);
        configuration.setEnvironment(new Environment("acc-5169", new JdbcTransactionFactory(), dataSource));
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
                session.getMapper(CraftCalcConfigMapper.class), null);
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

    // ────────────────────────────────────────────── 判据 2 / 4 / 5 / 7：跨订单并排

    @Test
    @DisplayName("🔴 判据2/4/5/7 真库：池级一次求解 ⇒ 两单合计 1 行 3 米（对照逐单派 2 行 6 米）")
    void crossOrderPairingDeductsThreeMetersNotSix() throws Exception {
        long batchId = newBatch("PC-5169-A", "60");
        // 池内两张单各一行：itemId 不同（= 两张加工单各自的明细行），同批次 / 同加工类型 / 各需 3 米
        List<StockBatchConsumptionService.Designation> orderA = List.of(
                pairable("acc-5169-a1", "PC-5169-A"));
        List<StockBatchConsumptionService.Designation> orderB = List.of(
                pairable("acc-5169-b1", "PC-5169-A"));

        // ── 对照：**逐单派**（改前形态 = 池化没开）——每张单各调一次 plan
        BigDecimal perOrderTotal = BigDecimal.ZERO;
        for (List<StockBatchConsumptionService.Designation> one : List.of(orderA, orderB)) {
            perOrderTotal = perOrderTotal.add(sum(service.plan(TENANT_ID, one),
                    StockBatchConsumptionService.Deduction::plannedMeters));
        }
        System.out.println("[#5169 判别性实验] 逐单派（两张单各调一次 plan）合计应领 = " + perOrderTotal);
        assertThat(perOrderTotal).as("红证：逐单派时两张单各自各占一行 ⇒ 6 米").isEqualByComparingTo("6");

        // ── 池化：**一次** plan，入参 = 池内两张单的行（服务层的「只调一次」由 PR-070 钉住）
        List<StockBatchConsumptionService.Designation> pooledLines = new ArrayList<>();
        pooledLines.addAll(orderA);
        pooledLines.addAll(orderB);
        List<StockBatchConsumptionService.Deduction> pooledPlan = service.plan(TENANT_ID, pooledLines);
        System.out.println("[#5169 判别性实验] 池化后逐行 = " + readings(pooledPlan));
        assertThat(sum(pooledPlan, StockBatchConsumptionService.Deduction::formulaMeters))
                .as("公式口径合计仍是 6（两个米数都要落库；对客口径不由排料方式决定）")
                .isEqualByComparingTo("6");
        assertThat(sum(pooledPlan, StockBatchConsumptionService.Deduction::plannedMeters))
                .as("🔴 本单的核心读数：跨订单并排后合计应领 3 米").isEqualByComparingTo("3");

        // 「1 行 vs 2 行」的字面读数（排料器的**行数**）：池级 = 两块料同一行；
        // 逐单派 = 两块各占一行（各占一段卷长 ⇒ 6 米）
        CuttingPlanCalculator.Piece pieceA = new CuttingPlanCalculator.Piece("acc-5169-a1#1",
                CuttingPlanCalculator.MODE_FIXED_HEIGHT, 1.4, 3);
        CuttingPlanCalculator.Piece pieceB = new CuttingPlanCalculator.Piece("acc-5169-b1#1",
                CuttingPlanCalculator.MODE_FIXED_HEIGHT, 1.4, 3);
        assertThat(CuttingPlanCalculator.plan(List.of(pieceA, pieceB), 2.8, 0.3).rows())
                .as("🔴 池级：两块并排进**同一行**（1 行，行长度 = 最大值 3 米）").hasSize(1);
        assertThat(CuttingPlanCalculator.plan(List.of(pieceA), 2.8, 0.3).rows().size()
                + CuttingPlanCalculator.plan(List.of(pieceB), 2.8, 0.3).rows().size())
                .as("对照：逐单派 = **2 行**（两段卷长之和 6 米）").isEqualTo(2);

        // ── 落库：**各自**的加工单号（一单一加工单的约束不变）
        Map<String, BigDecimal> stockBefore = fingerprint();
        long ledgerBefore = countStockLedger();
        applyOf("JG-5169-A", "ORD-5169-A", pooledPlan, "acc-5169-a1");
        applyOf("JG-5169-B", "ORD-5169-B", pooledPlan, "acc-5169-b1");

        assertThat(scalar("SELECT COALESCE(-SUM(delta), 0) FROM stock_batch_consumptions"
                + " WHERE tenant_id = " + TENANT_ID + " AND batch_no = 'PC-5169-A'"))
                .as("🔴 真库落账：两张单合计只扣 3 米（不是 6 米）").isEqualByComparingTo("3");
        assertThat(scalar("SELECT COUNT(*) FROM stock_batch_consumptions WHERE processing_order_no"
                + " IN ('JG-5169-A','JG-5169-B')"))
                .as("3 米拆成 2 行 —— 每张单各自一条台账（一单一加工单）").isEqualByComparingTo("2");
        assertThat(scalar("SELECT COUNT(DISTINCT processing_order_no) FROM stock_batch_consumptions"
                + " WHERE processing_order_no IN ('JG-5169-A','JG-5169-B')"))
                .as("两行分属两张加工单（不是把两张单塞进一张）").isEqualByComparingTo("2");
        assertThat(remainingOf(batchId)).as("省下的 3 米**留在批次余量上**（60 − 3）")
                .isEqualByComparingTo("57");

        // ── 判据 4：预览口径 == 落账口径（三腿同值：预览算式 / 真库 SQL / 实体派生）
        assertThat(previewSavedMeters(pooledPlan))
                .as("预览「预计节省」（与 ProductionPoolViews.Preview.savedMeters 同一算式）")
                .isEqualByComparingTo("3");
        assertThat(scalar("SELECT COALESCE(SUM(formula_meters - planned_meters), 0)"
                + " FROM stock_batch_consumptions WHERE processing_order_no IN"
                + " ('JG-5169-A','JG-5169-B')"))
                .as("🔴 真库落账的 Σ saved_meters 与预览**逐值相等**（不是两套口径）")
                .isEqualByComparingTo(previewSavedMeters(pooledPlan));
        assertThat(consumptionRows().stream().map(StockBatchConsumption::getSavedMeters)
                .reduce(BigDecimal.ZERO, BigDecimal::add))
                .as("实体派生读回的 Σ saved_meters 同值").isEqualByComparingTo("3");
        assertThat(previewSavedMeters(service.plan(TENANT_ID, orderA)))
                .as("对照：**逐单派**口径下这张单的节省 = 0（⇒ 上面那条断言有判别力）")
                .isEqualByComparingTo("0");

        // ── 判据 7：不损失客户（销售账与库存指纹一字不动）
        assertThat(fingerprint()).as("product_skus.stock 一字不动（池化不碰销售账）")
                .isEqualTo(stockBefore);
        assertThat(countStockLedger()).as("stock_ledger_entries 行数一字不动")
                .isEqualTo(ledgerBefore);
    }

    @Test
    @DisplayName("判据3 不倒退：跨批次不得成组 ⇒ 池级求解与逐单派**逐值相同**")
    void crossBatchDoesNotGroupAndMatchesPerOrder() throws Exception {
        long batchA = newBatch("PC-5169-C", "60");
        long batchB = newBatch("PC-5169-D", "60");
        List<StockBatchConsumptionService.Designation> orderA = List.of(pairable("acc-5169-c1", "PC-5169-C"));
        List<StockBatchConsumptionService.Designation> orderB = List.of(pairable("acc-5169-d1", "PC-5169-D"));

        // 池化：一次 plan，但两行分属不同批次 ⇒ 成组键（批次 × 加工类型）不同 ⇒ 各占一行
        List<StockBatchConsumptionService.Designation> pooledLines = new ArrayList<>(orderA);
        pooledLines.addAll(orderB);
        List<StockBatchConsumptionService.Deduction> pooled = service.plan(TENANT_ID, pooledLines);
        System.out.println("[#5169 判别性实验] 跨批次池化逐行 = " + readings(pooled));
        assertThat(pooled).allSatisfy(d -> assertThat(d.plannedMeters())
                .as("跨批次不得成组（两块料裁自不同卷，各自都得占一段卷长）⇒ 逐值退回公式口径")
                .isEqualByComparingTo(d.formulaMeters()));
        assertThat(sum(pooled, StockBatchConsumptionService.Deduction::plannedMeters))
                .isEqualByComparingTo("6");

        // 与逐单派逐值相同（逐行、逐字段）
        List<StockBatchConsumptionService.Deduction> perOrder = new ArrayList<>(service.plan(TENANT_ID, orderA));
        perOrder.addAll(service.plan(TENANT_ID, orderB));
        assertThat(readings(pooled)).as("池级求解与逐单派**逐值相同**").isEqualTo(readings(perOrder));

        applyOf("JG-5169-C", "ORD-5169-C", pooled, "acc-5169-c1");
        applyOf("JG-5169-D", "ORD-5169-D", pooled, "acc-5169-d1");
        assertThat(remainingOf(batchA)).isEqualByComparingTo("57");
        assertThat(remainingOf(batchB)).isEqualByComparingTo("57");
        assertThat(scalar("SELECT COALESCE(SUM(formula_meters - planned_meters), 0)"
                + " FROM stock_batch_consumptions WHERE processing_order_no IN"
                + " ('JG-5169-C','JG-5169-D')")).as("不成组 ⇒ 节省恒为 0").isEqualByComparingTo("0");
    }

    // ────────────────────────────────────────────── 判据 6：幂等

    @Test
    @DisplayName("🔴 判据6 幂等：重复成批（同一张单重复落账）⇒ 唯一闸挡下（23505）、行数不变、余量不变")
    void repeatedPooledApplyIsRejectedByUniqueGate() throws Exception {
        long batchId = newBatch("PC-5169-E", "60");
        List<StockBatchConsumptionService.Designation> lines = List.of(
                pairable("acc-5169-e1", "PC-5169-E"),
                pairable("acc-5169-e2", "PC-5169-E"));
        List<StockBatchConsumptionService.Deduction> plan = service.plan(TENANT_ID, lines);
        service.apply(TENANT_ID, "JG-5169-E", "ORD-5169-E", plan);
        BigDecimal remainingAfterFirst = remainingOf(batchId);
        long rowsAfterFirst = countRows("JG-5169-E");

        // 重复成批（等价于「同一张单被再派一次」走到落账这一步）—— 沿用 #5145 的幂等闸
        Throwable failure = catchThrowable(() -> service.apply(TENANT_ID, "JG-5169-E", "ORD-5169-E",
                service.plan(TENANT_ID, lines)));

        assertThat(failure).as("第二遍必须被挡下（不得静默二次扣减）").isNotNull();
        assertThat(sqlStateOf(failure)).as("挡下它的就是 uk_batch_consumption_line（SQLSTATE 23505）")
                .isEqualTo("23505");
        assertThat(countRows("JG-5169-E")).as("台账行数不变").isEqualTo(rowsAfterFirst);
        assertThat(remainingOf(batchId)).as("🔴 余量不再变化（没有二次扣减）")
                .isEqualByComparingTo(remainingAfterFirst);
    }

    // ────────────────────────────────────────────── 判据 6：幂等（注入式红证）

    @Test
    @DisplayName("注入式红证：拆掉 uk_batch_consumption_line ⇒ 第二遍落账就**真的会进账**")
    void injectedWithoutUniqueGateTheSecondWriteWouldLand() throws Exception {
        long batchId = newBatch("PC-5169-F", "60");
        List<StockBatchConsumptionService.Designation> lines = List.of(
                pairable("acc-5169-f1", "PC-5169-F"));
        List<StockBatchConsumptionService.Deduction> plan = service.plan(TENANT_ID, lines);
        service.apply(TENANT_ID, "JG-5169-F", "ORD-5169-F", plan);

        String ddl = uniqueGateDdl();
        exec("DROP INDEX uk_batch_consumption_line");
        try {
            // 闸不在 ⇒ 同一 (加工单 × 明细行 × 批次 × reason) 的第二次落账真的进账 = 静默二次扣减。
            // 这条红证是「上面那条判据拦下它的**确实是这个闸**」的证据（不是靠文案匹配）。
            service.apply(TENANT_ID, "JG-5169-F", "ORD-5169-F", plan);
            assertThat(countRows("JG-5169-F")).as("拆掉闸之后台账真的多了一行").isEqualTo(2);
            assertThat(remainingOf(batchId)).as("余量被二次扣成 57 − 3 = 54").isEqualByComparingTo("54");
        } finally {
            // 复原：先去掉注入造成的重复行（唯一索引建不起来 = 账已经坏了），再用 **schema.sql 原文**装回闸
            exec("DELETE FROM stock_batch_consumptions WHERE id NOT IN (SELECT min(id)"
                    + " FROM stock_batch_consumptions GROUP BY tenant_id, processing_order_no,"
                    + " batch_id, order_item_id, reason)");
            exec(ddl);
        }
        assertThat(scalar("SELECT COUNT(*) FROM pg_indexes WHERE indexname ="
                + " 'uk_batch_consumption_line'").longValue()).as("闸已复原").isEqualTo(1);
    }

    // ────────────────────────────────────────────── 夹具与工具

    /** 定高买宽的矮窗（门幅 2.8：窗高 1.1 + 卷边 0.3 = 占 1.4 ⇒ 两扇正好并排），各需 3 米。 */
    private static StockBatchConsumptionService.Designation pairable(String itemId, String batchNo) {
        return new StockBatchConsumptionService.Designation(itemId, PRODUCT_ID, SKU_CODE, batchNo,
                new BigDecimal("3"), "定高买宽", new BigDecimal("1.1"), null);
    }

    /** 把池级计划里**属于某一行**的那些扣减落成该行所属加工单的账（同生产路径的拆分口径）。 */
    private static void applyOf(String processingOrderNo, String orderNo,
                                List<StockBatchConsumptionService.Deduction> plan, String itemId) {
        List<StockBatchConsumptionService.Deduction> mine = new ArrayList<>();
        for (StockBatchConsumptionService.Deduction d : plan) {
            if (d.orderItemId().equals(itemId)) {
                mine.add(d);
            }
        }
        assertThat(mine).as("该行必须在池级计划里有扣减（itemId=" + itemId + "）").isNotEmpty();
        service.apply(TENANT_ID, processingOrderNo, orderNo, mine);
    }

    /**
     * 预览口径 = {@code Σ(formula − planned)} —— 与
     * {@code ProductionPoolViews.Preview.savedMeters}（{@code formulaMeters − pooledPlannedMeters}）
     * **同一算式**；这里再算一遍是为了与真库读数对照（三腿同值，判据 4）。
     */
    private static BigDecimal previewSavedMeters(List<StockBatchConsumptionService.Deduction> plan) {
        BigDecimal saved = BigDecimal.ZERO;
        for (StockBatchConsumptionService.Deduction d : plan) {
            saved = saved.add(d.formulaMeters().subtract(d.plannedMeters()));
        }
        return saved;
    }

    private static List<String> readings(List<StockBatchConsumptionService.Deduction> plan) {
        List<String> out = new ArrayList<>();
        for (StockBatchConsumptionService.Deduction d : plan) {
            out.add(d.orderItemId() + " batch=" + d.batchNo() + " formula="
                    + d.formulaMeters().toPlainString() + " planned=" + d.plannedMeters().toPlainString());
        }
        return out;
    }

    private static BigDecimal sum(List<StockBatchConsumptionService.Deduction> plan,
                                  java.util.function.Function<StockBatchConsumptionService.Deduction,
                                          BigDecimal> getter) {
        BigDecimal total = BigDecimal.ZERO;
        for (StockBatchConsumptionService.Deduction d : plan) {
            total = total.add(getter.apply(d));
        }
        return total;
    }

    /** 按加工单读回台账行（走**实体**路径 ⇒ saved_meters 这个派生值是读回来的）。 */
    private static List<StockBatchConsumption> consumptionRows() {
        return session.getMapper(StockBatchConsumptionMapper.class).selectList(
                new LambdaQueryWrapper<StockBatchConsumption>()
                        .eq(StockBatchConsumption::getTenantId, TENANT_ID));
    }

    /** 「销售账 + 库存」指纹（判据 7：池化不得碰对客面）。 */
    private static Map<String, BigDecimal> fingerprint() throws Exception {
        Map<String, BigDecimal> out = new LinkedHashMap<>();
        out.put("stock", scalar("SELECT stock FROM product_skus WHERE id = " + SKU_ID));
        out.put("ledger", scalar("SELECT COUNT(*) FROM stock_ledger_entries WHERE tenant_id = "
                + TENANT_ID));
        return out;
    }

    private static long countStockLedger() throws Exception {
        return scalar("SELECT COUNT(*) FROM stock_ledger_entries WHERE tenant_id = " + TENANT_ID)
                .longValue();
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

    /** 注入式红证用：唯一闸的 DDL **取自 schema.sql 原文**（不手抄，抄错就等于换了被测对象）。 */
    private static String uniqueGateDdl() throws IOException {
        java.util.regex.Matcher matcher = java.util.regex.Pattern
                .compile("CREATE UNIQUE INDEX[^;]*uk_batch_consumption_line[^;]*;",
                        java.util.regex.Pattern.DOTALL)
                .matcher(schemaSql());
        assertThat(matcher.find()).as("schema.sql 必须有 uk_batch_consumption_line 的定义").isTrue();
        return matcher.group();
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
        while (root != null && !Files.exists(root.resolve("docs/sql/schema.sql"))) {
            root = root.getParent();
        }
        assertThat(root).as("必须能定位 docs/sql/schema.sql（真库建表取终态 schema，不手抄列清单）").isNotNull();
        return Files.readString(root.resolve("docs/sql/schema.sql"));
    }
}
