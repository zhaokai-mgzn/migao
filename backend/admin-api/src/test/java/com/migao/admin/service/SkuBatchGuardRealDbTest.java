// case_ids: PR-076, PR-078
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.MybatisSqlSessionFactoryBuilder;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.MybatisPlusInterceptor;
import com.baomidou.mybatisplus.extension.plugins.handler.TenantLineHandler;
import com.baomidou.mybatisplus.extension.plugins.inner.TenantLineInnerInterceptor;
import com.migao.admin.entity.StockBatchConsumption;
import com.migao.admin.exception.BusinessException;
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
 * 🔴 <b>SKU 级批次护栏的**真库**判据（issue #5174）</b>。
 *
 * <h2>本单修的是什么</h2>
 * 「批次的 SKU 必须与订单行的 SKU 一致」这条护栏在生产路径上**从未生效**：加工单快照把 SKU 码写在
 * {@code sku} 键（{@code ProcessingOrderService#buildSnapshot} 的两行 {@code copyIfPresent} 落键同为
 * {@code sku}），而读侧取的是 {@code row.get("skuCode")} ⇒ **恒 null** ⇒
 * {@link StockBatchConsumptionService#plan} 里这条判据的第一个条件
 * （{@code StringUtils.hasText(d.skuCode())}）恒假 ⇒ 整条 no-op。后果：文员手选一个**同货号但错颜色/门幅**
 * 的批次 ⇒ **静默扣账**（用错料、账上不留痕）。对照：{@code productId} 那道判据独立成立（跨商品能拦），
 * 所以缺的正是「同货号、跨 SKU」这一格。
 *
 * <h2>为什么必须真库</h2>
 * 判据是「**台账上真的落了一行 / 真的没落**」与「**批次余量**真的被扣了没有」。mock 只能证明
 * 「抛了什么异常」：列名拼错 / 约束没生效 / 落账在半截事务里留下脏行，在 mock 面**结构上不可见**
 * （#5141 / #5148 / #5158 / #5169 同族教训）。
 *
 * <h2>判据（每条都带**同参数的对照读数**，不是「跑了就算」）</h2>
 * <ol>
 *   <li><b>判据 1·跨 SKU ⇒ 显式拒绝 + 零落账</b>：同一夹具下，**改前形态**（{@code skuCode = null}，
 *       = 改前读侧必然产出的值）**静默落账**（1 行 / 扣 3 米 / 余量 60 → 57，三个读数都打印）；
 *       **改后形态**（{@code skuCode} = 快照实际写入的 {@code sku} 键）⇒
 *       {@code BATCH_SKU_MISMATCH} + 400 + 可行动文案，且该批次**一行台账都没落**、余量一字不动。</li>
 *   <li><b>判据 2·合法路径逐值不变</b>：正确 SKU 的批次 ⇒ 通过，且两个米数（{@code formula} /
 *       {@code planned}）、{@code unit_cost} / {@code before_qty} / {@code after_qty} / 批次余量
 *       **逐值等于**改前口径 —— 其中 {@code planned = 1.5 ≠ formula = 3} 正是 <b>#5158 排料口径</b>
 *       仍在生效的证据（两扇矮窗并排），不是「一律按公式扣」的退化形态。</li>
 *   <li><b>判据 3·建议值按 SKU 过滤</b>：同货号、错门幅但**入库更早**的批次在改前形态下
 *       **会被建议**（FIFO 首选）；带上正确 SKU 码 ⇒ 建议值换成同 SKU 的那个批次。</li>
 *   <li><b>判据 4·不损失客户</b>：{@code product_skus.stock} / {@code price} 与
 *       {@code stock_ledger_entries} 指纹**一字不动**（批次护栏不碰销售账）。</li>
 *   <li><b>判据 5·幂等</b>：同一加工单重复落账 ⇒ 被 {@code uk_batch_consumption_line} 挡下
 *       （SQLSTATE 23505），行数与余量都不再变化（沿用 #5145 闸）。</li>
 * </ol>
 *
 * <h2>环境</h2>
 * 一次性真 PG 集群（{@code initdb} + {@code pg_ctl}，随机端口、跑完即停；共用 {@link PgCluster}），
 * schema 取自 {@code docs/sql/schema.sql}（bootstrap 终态，**不手抄列清单**）。本机没有 PG 二进制 ⇒
 * <b>显式 skip</b>（「没跑」必须长得像「没跑」，不是通过）。
 *
 * <p>范式与 {@code PooledDispatchRealDbTest}（#5169）/ {@code BatchAssignmentRuleRealDbTest}（#5167）
 * 同款：真库层把**批次账**钉死。「读侧取的是快照哪个键」这件装配事实由
 * {@code ProcessingOrderServiceTest}（PR-077）覆盖 —— 两条判据合起来才是完整的那条链
 * （读对键 ⇒ 护栏真的生效）。</p>
 */
@DisplayName("#5174 真库守卫：跨 SKU 的批次必须被拒（改前静默落账），同 SKU 落账逐值不变")
class SkuBatchGuardRealDbTest {

    private static final Long TENANT_ID = 5174L;
    /** **同一个货号**：跨 SKU 的两道判据都在同一个 productId 下 —— 跨商品那道（独立成立）拦不住本单这一格。 */
    private static final String PRODUCT_ID = "acc-5174-prod";
    /** 订单行真正要的 SKU：颜色 米白 × 门幅 2.8 米。 */
    private static final Long SKU_A_ID = 5174L;
    private static final String SKU_A = "SKU-A";
    /** 同货号的**另一个** SKU：颜色/门幅都不同（错料就是它）。 */
    private static final Long SKU_B_ID = 5175L;
    private static final String SKU_B = "SKU-B";
    private static final String DOOR_WIDTH_A = "2.8米";
    private static final String DOOR_WIDTH_B = "1.5米";
    /**
     * 「建议值过滤」那条判据的**独立物料面**：候选集合按 {@code productId} 取 ⇒ 与上面两个夹具的批次
     * 互不干扰（否则「FIFO 挑谁」会随同租户其它夹具的批次而变，判据就不再是确定性的）。
     */
    private static final String SUG_PRODUCT_ID = "acc-5174-sug-prod";
    private static final Long SUG_SKU_A_ID = 5176L;
    private static final String SUG_SKU_A = "SUG-SKU-A";
    private static final Long SUG_SKU_B_ID = 5177L;
    private static final String SUG_SKU_B = "SUG-SKU-B";
    private static final String UNIT_COST = "12.5";
    private static final BigDecimal FORMULA_METERS = new BigDecimal("3");
    private static final BigDecimal WINDOW_HEIGHT = new BigDecimal("1.1");

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
                    + TENANT_ID + ", 'acc-5174', 'acc-5174')");
            st.execute("INSERT INTO products (id, tenant_id, name) VALUES ('" + PRODUCT_ID + "', "
                    + TENANT_ID + ", '布艺遮光帘A')");
            // 同一货号下的两个 SKU（颜色 × 门幅 = SKU；`sku_code` 是它的编码，也是批次的 `sku_code`）
            st.execute(skuInsert(SKU_A_ID, PRODUCT_ID, DOOR_WIDTH_A, "100", "60", SKU_A));
            st.execute(skuInsert(SKU_B_ID, PRODUCT_ID, DOOR_WIDTH_B, "88", "60", SKU_B));
            // 建议值过滤判据的独立物料面（同构：一个正确 SKU + 一个同货号错门幅的 SKU）
            st.execute("INSERT INTO products (id, tenant_id, name) VALUES ('" + SUG_PRODUCT_ID + "', "
                    + TENANT_ID + ", '布艺遮光帘B')");
            st.execute(skuInsert(SUG_SKU_A_ID, SUG_PRODUCT_ID, DOOR_WIDTH_A, "100", "60", SUG_SKU_A));
            st.execute(skuInsert(SUG_SKU_B_ID, SUG_PRODUCT_ID, DOOR_WIDTH_B, "88", "60", SUG_SKU_B));
            // 租户算料配置：只给主键与租户 ⇒ 其余列取库默认值（hem_margin 默认 0.3，与引擎常量同值）
            st.execute("INSERT INTO craft_calc_configs (id, tenant_id) VALUES ('cfg-acc-5174', "
                    + TENANT_ID + ")");
        }
        MybatisConfiguration configuration = new MybatisConfiguration();
        configuration.setMapUnderscoreToCamelCase(true);
        configuration.setEnvironment(new Environment("acc-5174", new JdbcTransactionFactory(), dataSource));
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
                session.getMapper(ProductSkuMapper.class), null, configService);
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

    // ────────────────────────────────────────────── 判据 1：跨 SKU ⇒ 拒绝 + 零落账（含红证）

    @Test
    @DisplayName("🔴 判据1 真库：同货号错颜色/门幅的批次 ⇒ BATCH_SKU_MISMATCH 400 + 零落账"
            + "（红证：改前读侧产出的 null ⇒ 同一夹具静默扣账）")
    void crossSkuBatchIsRejectedWithZeroLanding() throws Exception {
        long silentlyDeducted = newBatch(PRODUCT_ID, "PC-5174-B1", SKU_B_ID, SKU_B, "60", "2026-09-01");

        // ── 红证（**改前形态**）：快照里没有 `skuCode` 键 ⇒ 改前读侧 `str(row.get("skuCode"))` 恒 null；
        //    而护栏第一个条件是 hasText(d.skuCode()) ⇒ 整条判据 no-op ⇒ 同一夹具**静默落账**。
        //    这三个读数是「改前是静默接受」的**实测**，不是推断。
        List<StockBatchConsumptionService.Deduction> silent = service.plan(TENANT_ID,
                List.of(designation("acc-5174-b1", null, "PC-5174-B1")));
        service.apply(TENANT_ID, "JG-5174-OLD", "ORD-5174", silent);
        System.out.println("[#5174 判别性实验] 改前形态（skuCode=null）⇒ 台账 "
                + countRowsOfBatch(silentlyDeducted) + " 行、扣减 " + deductedOf(silentlyDeducted)
                + " 米、批次余量 " + remainingOf(silentlyDeducted));
        assertThat(countRowsOfBatch(silentlyDeducted))
                .as("红证：null 形态下台账**真的落了行**（用错料且账上不留痕）").isEqualTo(1);
        assertThat(deductedOf(silentlyDeducted)).as("红证：静默扣掉的就是那 3 米")
                .isEqualByComparingTo("3");
        assertThat(remainingOf(silentlyDeducted)).as("红证：错 SKU 批次的余量已被扣到 57")
                .isEqualByComparingTo("57");

        // ── 改后形态：SKU 码 = 快照**实际写入的 `sku` 键**（非 null）⇒ 护栏第一个条件成立 ⇒ 显式拒绝
        long rejected = newBatch(PRODUCT_ID, "PC-5174-B2", SKU_B_ID, SKU_B, "60", "2026-09-03");
        Throwable failure = catchThrowable(() -> service.plan(TENANT_ID,
                List.of(designation("acc-5174-b2", SKU_A, "PC-5174-B2"))));

        assertThat(failure).as("同货号、错颜色/门幅 ⇒ 必须**显式拒绝**（不得静默扣账）")
                .isInstanceOf(BusinessException.class);
        BusinessException e = (BusinessException) failure;
        assertThat(e.getCode()).isEqualTo(StockBatchConsumptionService.ERR_BATCH_SKU_MISMATCH);
        assertThat(e.getHttpStatus()).as("400（可被前端/agent 当输入错误处置）").isEqualTo(400);
        assertThat(e.getMessage()).as("文案要点名对象：哪个批次、批次的 SKU、行要的 SKU")
                .contains("PC-5174-B2").contains(SKU_B).contains(SKU_A);
        assertThat(e.getSuggestion()).as("可行动：告诉文员该选什么").contains("颜色/门幅");

        // 零落账：拒绝发生在 plan（**只读**，写面在 apply）⇒ 该批次一行都不许落、余量一字不动
        assertThat(countRowsOfBatch(rejected)).as("🔴 零落账：被拒的批次台账行数 = 0").isEqualTo(0);
        assertThat(remainingOf(rejected)).as("被拒批次余量一字不动").isEqualByComparingTo("60");
        assertThat(countRows("JG-5174-OLD")).as("本单唯一那行台账仍只有红证那一行（拒绝没有留下半截写入）")
                .isEqualTo(1);
    }

    // ────────────────────────────────────────────── 判据 2 / 4 / 5：同 SKU ⇒ 逐值不变

    @Test
    @DisplayName("判据2/4/5 真库：同 SKU 的批次 ⇒ 落账逐值不变（排料口径仍生效 / 对客面不动 / 幂等闸在位）")
    void sameSkuBatchLandsValueByValue() throws Exception {
        long batchId = newBatch(PRODUCT_ID, "PC-5174-A1", SKU_A_ID, SKU_A, "60", "2026-09-02");
        Map<String, BigDecimal> stockBefore = fingerprint();

        // 两扇「窗高 1.1 + 卷边 0.3 = 占 1.4」的矮窗在门幅 2.8 上正好并排 ⇒ 各领 1.5 米（公式口径各 3）
        List<StockBatchConsumptionService.Designation> lines = List.of(
                pairable("acc-5174-h1", "PC-5174-A1"),
                pairable("acc-5174-h2", "PC-5174-A1"));
        List<StockBatchConsumptionService.Deduction> plan = service.plan(TENANT_ID, lines);
        System.out.println("[#5174] 同 SKU 计划读数 = " + readings(plan));

        assertThat(plan).extracting(StockBatchConsumptionService.Deduction::formulaMeters)
                .as("公式口径逐值不变（= 销售账同函数的米数）")
                .allSatisfy(m -> assertThat(m).isEqualByComparingTo("3"));
        assertThat(plan).extracting(StockBatchConsumptionService.Deduction::plannedMeters)
                .as("🔴 #5158 排料口径仍生效：并排后各领 1.5（**不是**退化成「一律按公式扣 3」）")
                .allSatisfy(m -> assertThat(m).isEqualByComparingTo("1.5"));
        assertThat(plan).extracting(StockBatchConsumptionService.Deduction::skuCode)
                .as("落账行的 SKU 码 = 批次/订单行一致的那个（护栏要求两边都有值才比）")
                .containsOnly(SKU_A);

        assertThat(service.apply(TENANT_ID, "JG-5174-A", "ORD-5174-A", plan)).isEqualTo(2);

        assertThat(countRows("JG-5174-A")).as("两扇窗两条台账行").isEqualTo(2);
        assertThat(deductedOf(batchId)).as("批次账上真的只扣了 3 米").isEqualByComparingTo("3");
        assertThat(sumOf("formula_meters", "JG-5174-A")).isEqualByComparingTo("6");
        assertThat(sumOf("planned_meters", "JG-5174-A")).isEqualByComparingTo("3");
        assertThat(sumOf("formula_meters - planned_meters", "JG-5174-A"))
                .as("省下的 3 米落成 saved_meters（#5158 口径，本单不碰）").isEqualByComparingTo("3");
        assertThat(remainingOf(batchId)).as("余量 60 → 57").isEqualByComparingTo("57");

        // 实体读回逐值（after_qty = before_qty − planned，按 id 序累积）
        List<StockBatchConsumption> rows = consumptionRows("JG-5174-A");
        assertThat(rows).hasSize(2);
        assertThat(rows.get(0).getBeforeQty()).isEqualByComparingTo("60");
        assertThat(rows.get(0).getAfterQty()).isEqualByComparingTo("58.5");
        assertThat(rows.get(1).getBeforeQty()).isEqualByComparingTo("58.5");
        assertThat(rows.get(1).getAfterQty()).isEqualByComparingTo("57");
        assertThat(rows).extracting(StockBatchConsumption::getUnitCost)
                .as("当时均价快照逐值不变").allSatisfy(c -> assertThat(c).isEqualByComparingTo(UNIT_COST));
        assertThat(rows).extracting(StockBatchConsumption::getSkuCode).containsOnly(SKU_A);

        // ── 判据 5·幂等：同一加工单重复落账 ⇒ 沿用 #5145 的唯一闸
        Throwable again = catchThrowable(() -> service.apply(TENANT_ID, "JG-5174-A", "ORD-5174-A",
                service.plan(TENANT_ID, lines)));
        assertThat(again).as("第二遍必须被挡下（不得静默二次扣减）").isNotNull();
        assertThat(sqlStateOf(again)).as("挡下它的就是 uk_batch_consumption_line（SQLSTATE 23505）")
                .isEqualTo("23505");
        assertThat(countRows("JG-5174-A")).as("台账行数不变").isEqualTo(2);
        assertThat(remainingOf(batchId)).as("🔴 余量不再变化（没有二次扣减）")
                .isEqualByComparingTo("57");

        // ── 判据 4·不损失客户：批次护栏不碰销售账
        assertThat(fingerprint()).as("product_skus.stock / price 与销售台账指纹一字不动")
                .isEqualTo(stockBefore);
    }

    // ────────────────────────────────────────────── 判据 3：建议值按 SKU 过滤（含红证）

    @Test
    @DisplayName("🔴 判据3 真库：跨 SKU 候选不再被建议（红证：读侧传 null ⇒ FIFO 挑中的正是那个错门幅批次）")
    void suggestedBatchNoFiltersBySku() throws Exception {
        // 本判据用**独立物料面**（候选集合按 productId 取）⇒ 「FIFO 挑谁」不随同租户其它夹具的批次而变
        newBatch(SUG_PRODUCT_ID, "PC-5174-W1", SUG_SKU_B_ID, SUG_SKU_B, "30", "2026-09-01");
        newBatch(SUG_PRODUCT_ID, "PC-5174-R1", SUG_SKU_A_ID, SUG_SKU_A, "30", "2026-09-05");

        // 错 SKU 的批次**入库更早** ⇒ 只要 SKU 过滤不生效，FIFO 必然挑它（判别性来自夹具顺序，不是巧合）
        assertThat(service.suggestedBatchNo(TENANT_ID, SUG_PRODUCT_ID, null, FORMULA_METERS, "fifo"))
                .as("红证：改前形态（读侧恒 null ⇒ 过滤条件整条 no-op）⇒ **错 SKU 的批次被建议**")
                .isEqualTo("PC-5174-W1");
        assertThat(service.suggestedBatchNo(TENANT_ID, SUG_PRODUCT_ID, SUG_SKU_A, FORMULA_METERS, "fifo"))
                .as("🔴 改后：只有同一个 SKU 的批次才进候选").isEqualTo("PC-5174-R1");
        assertThat(service.suggestedBatchNo(TENANT_ID, SUG_PRODUCT_ID, SUG_SKU_A, FORMULA_METERS,
                "best_fit"))
                .as("两条规则同源同一份候选（本单不改指派策略默认值：缺省仍是 fifo）")
                .isEqualTo("PC-5174-R1");
    }

    // ────────────────────────────────────────────── 判据 2 的反向护栏：不得「修成一律拒绝」

    @Test
    @DisplayName("🔴 判据2 反向护栏：批次侧 skuCode 为 null（导入批次未带色号）⇒ **不擅自收紧**，仍按 productId 放行")
    void batchWithoutSkuCodeIsNotTightened() throws Exception {
        // 边界（如实登记）：订单行侧读得到 SKU、批次侧没记色号 ⇒ 两边不可能「都有值」⇒ 判据不成立。
        // 本单**有意**不把这条收紧（收紧会让「导入批次未带色号」的存量数据全部派不出工）——
        // 这条断言就是那个边界的钉子：谁把 `hasText(batch.getSkuCode())` 那个条件去掉，它立刻变红。
        long batchId = newBatch(PRODUCT_ID, "PC-5174-N1", SKU_A_ID, null, "60", "2026-09-04");

        List<StockBatchConsumptionService.Deduction> plan = service.plan(TENANT_ID,
                List.of(designation("acc-5174-n1", SKU_A, "PC-5174-N1")));
        service.apply(TENANT_ID, "JG-5174-N", "ORD-5174-N", plan);

        assertThat(deductedOf(batchId)).as("批次无 SKU 码 ⇒ 不拦（只能靠 productId 那道判据）")
                .isEqualByComparingTo("3");
        assertThat(remainingOf(batchId)).isEqualByComparingTo("57");
    }

    // ────────────────────────────────────────────── 夹具与工具

    private static String skuInsert(long id, String productId, String doorWidth, String price,
                                    String stock, String skuCode) {
        return "INSERT INTO product_skus (id, tenant_id, product_id, door_width, price, stock, sku_code)"
                + " OVERRIDING SYSTEM VALUE VALUES (" + id + ", " + TENANT_ID + ", '" + productId
                + "', '" + doorWidth + "', " + price + ", " + stock + ", '" + skuCode + "')";
    }

    /**
     * 一行派工指定（{@code skuCode} 由调用方给）—— <b>本单的判别性全在这个参数上</b>：
     * {@code null} = 改前读侧必然产出的值（{@code str(row.get("skuCode"))}），
     * 非 null = 改后读的是快照实际写入的 {@code sku} 键。
     */
    private static StockBatchConsumptionService.Designation designation(String itemId, String skuCode,
                                                                       String batchNo) {
        return new StockBatchConsumptionService.Designation(itemId, PRODUCT_ID, skuCode, batchNo,
                FORMULA_METERS, null, null, null);
    }

    /** 定高买宽的矮窗（门幅 2.8：窗高 1.1 + 卷边 0.3 = 占 1.4 ⇒ 两扇正好并排），各需 3 米。 */
    private static StockBatchConsumptionService.Designation pairable(String itemId, String batchNo) {
        return new StockBatchConsumptionService.Designation(itemId, PRODUCT_ID, SKU_A, batchNo,
                FORMULA_METERS, "定高买宽", WINDOW_HEIGHT, null);
    }

    private static List<String> readings(List<StockBatchConsumptionService.Deduction> plan) {
        List<String> out = new ArrayList<>();
        for (StockBatchConsumptionService.Deduction d : plan) {
            out.add(d.orderItemId() + " batch=" + d.batchNo() + " formula="
                    + d.formulaMeters().toPlainString() + " planned=" + d.plannedMeters().toPlainString());
        }
        return out;
    }

    /**
     * 建一个批次（商品 / SKU / 数量 / 当时均价 / 入库日期固定），返回它的 id。
     *
     * <p>{@code skuCode == null} ⇒ 落 **SQL NULL**（= 导入批次未带色号那种形态，见
     * {@link #batchWithoutSkuCodeIsNotTightened()}）。</p>
     */
    private static long newBatch(String productId, String batchNo, long skuId, String skuCode,
                                 String meters, String receivedDate) throws Exception {
        String skuCodeSql = skuCode == null ? "NULL" : "'" + skuCode + "'";
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery("INSERT INTO stock_batches (tenant_id, batch_no, product_id,"
                     + " sku_id, sku_code, quantity, unit_cost, received_date) VALUES (" + TENANT_ID
                     + ", '" + batchNo + "', '" + productId + "', " + skuId + ", " + skuCodeSql + ", "
                     + meters + ", " + UNIT_COST + ", DATE '" + receivedDate + "') RETURNING id")) {
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

    private static BigDecimal deductedOf(long batchId) throws Exception {
        return scalar("SELECT COALESCE(-SUM(delta), 0) FROM stock_batch_consumptions WHERE batch_id = "
                + batchId + " AND deleted = 0");
    }

    private static long countRowsOfBatch(long batchId) throws Exception {
        return scalar("SELECT COUNT(*) FROM stock_batch_consumptions WHERE batch_id = " + batchId
                + " AND deleted = 0").longValue();
    }

    private static long countRows(String processingOrderNo) throws Exception {
        return scalar("SELECT COUNT(*) FROM stock_batch_consumptions WHERE processing_order_no = '"
                + processingOrderNo + "' AND deleted = 0").longValue();
    }

    private static BigDecimal sumOf(String expression, String processingOrderNo) throws Exception {
        return scalar("SELECT COALESCE(SUM(" + expression + "), 0) FROM stock_batch_consumptions"
                + " WHERE processing_order_no = '" + processingOrderNo + "' AND deleted = 0");
    }

    /** 按加工单读回台账行（走**实体**路径 ⇒ before/after/unit_cost 是读回来的）。 */
    private static List<StockBatchConsumption> consumptionRows(String processingOrderNo) {
        return session.getMapper(StockBatchConsumptionMapper.class).selectList(
                new LambdaQueryWrapper<StockBatchConsumption>()
                        .eq(StockBatchConsumption::getTenantId, TENANT_ID)
                        .eq(StockBatchConsumption::getProcessingOrderNo, processingOrderNo)
                        .orderByAsc(StockBatchConsumption::getId));
    }

    /** 「对客面 + 库存」指纹（判据 4：批次护栏不得碰销售账）。 */
    private static Map<String, BigDecimal> fingerprint() throws Exception {
        Map<String, BigDecimal> out = new LinkedHashMap<>();
        out.put("stockA", scalar("SELECT stock FROM product_skus WHERE id = " + SKU_A_ID));
        out.put("stockB", scalar("SELECT stock FROM product_skus WHERE id = " + SKU_B_ID));
        out.put("priceA", scalar("SELECT price FROM product_skus WHERE id = " + SKU_A_ID));
        out.put("ledger", scalar("SELECT COUNT(*) FROM stock_ledger_entries WHERE tenant_id = "
                + TENANT_ID));
        return out;
    }

    private static BigDecimal scalar(String sql) throws Exception {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery(sql)) {
            assertThat(rs.next()).as("查询必须有结果：" + sql).isTrue();
            return rs.getBigDecimal(1);
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
