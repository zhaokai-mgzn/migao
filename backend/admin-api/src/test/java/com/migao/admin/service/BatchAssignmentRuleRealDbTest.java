// case_ids: PR-067
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

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.catchThrowable;

/**
 * 🔴 <b>best-fit 指派策略的真库判据（issue #5167）</b>。
 *
 * <h2>为什么必须真库（Mockito 测不出来）</h2>
 * 本单的判据有两处是**数据库自己的行为**，mock 面结构上不可见：
 * <ol>
 *   <li><b>FIFO 的候选顺序来自 SQL 的 {@code ORDER BY received_date, id}</b>（含 PG 的 NULLS LAST 语义）
 *       —— 而 best-fit 的「余量最接近需求」是拿这份**真序**再挑的：序错了，两个策略的结论会一起错，
 *       而 mock 里那份列表是测试自己摆的顺序（#5141 / #5148 的教训同族）。</li>
 *   <li><b>「用尽」是 NUMERIC(12,1) 上的算术结论</b>：3.0 − 3.0 在真 PG 里必须逐值归零
 *       （否则「≤0.2 米档」的读数会因为 0.1 的尾巴而失真 —— 那正是母单 #5144 的效果指标）。</li>
 * </ol>
 *
 * <h2>判据（每条都带**同夹具的对照读数**）</h2>
 * <ol>
 *   <li><b>判据2 策略可判别且驱动落账</b>：同一夹具（先入库 30 米 / 后入库 3 米、需求 3 米）下
 *       FIFO 建议 = 先入库那批、best-fit 建议 = 余量 3.0 那批；把 best-fit 的建议当指派用 ⇒
 *       **真库扣的就是它**（台账 {@code batch_no} + 余量 3.0 → 0.0 + 分布读面「≤0.2 米」= 1 批）。</li>
 *   <li><b>判据1 默认不变</b>：不传规则与显式 {@code fifo} **逐值相同**；落账走先入库那批
 *       ⇒ 3.0 的那批**原封不动留在账上**（对照读数：「≤0.2 米」= 0 批）—— 这就是用户痛点「剩了
 *       大量 0.5 米左右」在真库里的形态，也是 best-fit 要治的东西。</li>
 *   <li><b>判据6 不损失客户 / 不回退 #5158 口径</b>：best-fit 选出的批次上，两扇可并排的矮窗
 *       仍按**排料结果**领料（逐行 1.5 米、合计 3.0 而不是公式的 6.0）；
 *       {@code product_skus.stock} 与 {@code stock_ledger_entries} 一字不动。</li>
 *   <li><b>判据5 幂等</b>：同一加工单重复落账 ⇒ 被 {@code uk_batch_consumption_line} 挡下
 *       （SQLSTATE 23505）、台账行数不变、批次余量不变。</li>
 * </ol>
 *
 * <h2>环境</h2>
 * 一次性真 PG 集群（{@code PgCluster}，与 #5158 的真库守卫共用），schema 取自
 * {@code docs/sql/schema.sql}（bootstrap 终态，**不手抄列清单** ⇒ 列名/约束漂移会被抓）。
 * 缺 PG 二进制 ⇒ {@link PgCluster#startOrAbort()}：
 * CI（{@code MIGAO_REQUIRE_REALDB=1}）⇒ 判红；本机未设该标记 ⇒ 显式 skip（「没跑」长得像「没跑」，不是通过）。
 */
@DisplayName("#5167 真库守卫：best-fit 挑「用尽」的批次 / 默认 FIFO 逐值不变")
class BatchAssignmentRuleRealDbTest {

    private static final Long TENANT_ID = 5167L;
    private static final Long SKU_ID = 5167L;
    private static final String SKU_CODE = "SKU-A";
    /** 门幅 2.8 米（与 #5158 同口径）：两扇「窗高 1.1 + 卷边 0.3 = 占 1.4」的矮窗正好并排。 */
    private static final String DOOR_WIDTH = "2.8米";
    private static final String UNIT_COST = "12.5";
    /** 每个用例一个**独立商品** ⇒ 分布读面（按商品统计）的读数互不串味、与用例顺序无关。 */
    private static final String PRODUCT_BEST_FIT = "acc-5167-bestfit";
    private static final String PRODUCT_DEFAULT = "acc-5167-default";
    private static final String PRODUCT_PLAN = "acc-5167-plan";
    private static final String PRODUCT_IDEMPOTENT = "acc-5167-idem";

    private static PgCluster cluster;
    private static DataSource dataSource;
    private static SqlSessionFactory factory;
    private static SqlSession session;
    private static StockBatchConsumptionService service;
    private static CraftCalcConfigService configService;

    @BeforeAll
    static void startRealPostgresAndFixtures() throws Exception {
        cluster = PgCluster.startOrAbort();
        dataSource = cluster.dataSource();
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute(schemaSql());
            st.execute("INSERT INTO tenants (id, name, code) OVERRIDING SYSTEM VALUE VALUES ("
                    + TENANT_ID + ", 'acc-5167', 'acc-5167')");
            for (String productId : List.of(PRODUCT_BEST_FIT, PRODUCT_DEFAULT, PRODUCT_PLAN,
                    PRODUCT_IDEMPOTENT)) {
                st.execute("INSERT INTO products (id, tenant_id, name) VALUES ('" + productId + "', "
                        + TENANT_ID + ", '布艺遮光帘-5167')");
            }
            // 库存 100 米 = **销售账**（本单一个字节都不该改它）
            st.execute("INSERT INTO product_skus (id, tenant_id, product_id, door_width, price, stock,"
                    + " sku_code) OVERRIDING SYSTEM VALUE VALUES (" + SKU_ID + ", " + TENANT_ID + ", '"
                    + PRODUCT_BEST_FIT + "', '" + DOOR_WIDTH + "', 100, 100, '" + SKU_CODE + "')");
            // 算料配置：只给主键与租户 ⇒ 其余列取库默认（hem_margin 默认 0.3，排料定尺要用）
            st.execute("INSERT INTO craft_calc_configs (id, tenant_id) VALUES ('cfg-acc-5167', "
                    + TENANT_ID + ")");
        }
        MybatisConfiguration configuration = new MybatisConfiguration();
        configuration.setMapUnderscoreToCamelCase(true);
        configuration.setEnvironment(new Environment("acc-5167", new JdbcTransactionFactory(), dataSource));
        // 多租户拦截器必须在场（生产 SQL 经它重写）—— 少了它只测了 mapper 原文
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
        configService = new CraftCalcConfigService(
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

    // ────────────────────────────────────────────── 判据 2：best-fit 生效且驱动落账

    @Test
    @DisplayName("🔴 判据2/真库：同一夹具 FIFO 挑 30 米批、best_fit 挑 3.0 米批，落账扣的就是它且**用尽**")
    void bestFitSuggestionIsWhatTheLedgerDeducts() throws Exception {
        // 夹具：先入库的余量大（30.0），后入库的余量正好等于需求（3.0）⇒ 两策略结论必然相反
        long earlyId = newBatch(PRODUCT_BEST_FIT, "PC-5167-BF-EARLY", "30", "2026-08-01");
        long lateId = newBatch(PRODUCT_BEST_FIT, "PC-5167-BF-LATE", "3", "2026-09-01");
        BigDecimal need = new BigDecimal("3");

        var fifo = service.candidates(TENANT_ID, PRODUCT_BEST_FIT, SKU_ID, need, "fifo");
        var bestFit = service.candidates(TENANT_ID, PRODUCT_BEST_FIT, SKU_ID, need, "best_fit");
        System.out.println("[#5167 判别性实验] fifo 建议 = " + fifo.suggestedBatchNo()
                + "（" + fifo.suggestionRule() + "）；best_fit 建议 = " + bestFit.suggestedBatchNo()
                + "（" + bestFit.suggestionRule() + "）");
        assertThat(fifo.suggestedBatchNo()).as("FIFO = 先入库者（真库 ORDER BY received_date, id）")
                .isEqualTo("PC-5167-BF-EARLY");
        assertThat(bestFit.suggestedBatchNo()).as("🔴 best-fit = 余量最接近需求者（3.0）")
                .isEqualTo("PC-5167-BF-LATE");
        assertThat(bestFit.suggestedBatchNo()).as("两策略必须结论相反，否则本判据不可判别")
                .isNotEqualTo(fifo.suggestedBatchNo());
        assertThat(bestFit.candidates()).extracting(
                com.migao.admin.dto.BatchStockViews.Candidate::batchNo)
                .as("候选集合与顺序不因策略而变（不得漏候选）")
                .containsExactly("PC-5167-BF-EARLY", "PC-5167-BF-LATE");

        // 把建议当指派用（= 生成加工单侧 auto-fill 的产物）⇒ 真库扣的就是这一批
        var plan = service.plan(TENANT_ID, List.of(
                formulaOnly(PRODUCT_BEST_FIT, "acc-5167-bf-1", bestFit.suggestedBatchNo(), "3")));
        service.apply(TENANT_ID, "JG-5167-BF", "ORD-5167-BF", plan);

        assertThat(ledgerBatchNos("JG-5167-BF")).as("🔴 落账扣的是 best-fit 建议的那一批")
                .isEqualTo("PC-5167-BF-LATE");
        assertThat(scalar("SELECT COALESCE(-SUM(delta), 0) FROM stock_batch_consumptions"
                + " WHERE processing_order_no = 'JG-5167-BF'")).isEqualByComparingTo("3");
        assertThat(remainingOf(lateId)).as("🔴 用尽：3.0 − 3.0 在 NUMERIC(12,1) 上逐值归零")
                .isEqualByComparingTo("0");
        assertThat(remainingOf(earlyId)).as("没被挑中的批次一动不动").isEqualByComparingTo("30");
        assertThat(exhaustedBatches(PRODUCT_BEST_FIT))
                .as("母单 #5144 的效果读数：≤0.2 米的批次数 = 1（用尽了一个）").isEqualTo(1);
    }

    // ────────────────────────────────────────────── 判据 1：默认（FIFO）逐值不变

    @Test
    @DisplayName("🔴 判据1/真库：不传规则 == 显式 fifo（逐值），落账走先入库那批 ⇒ 尾料留在账上")
    void defaultRuleIsFifoAndLeavesTheTail() throws Exception {
        long earlyId = newBatch(PRODUCT_DEFAULT, "PC-5167-DF-EARLY", "30", "2026-08-01");
        long lateId = newBatch(PRODUCT_DEFAULT, "PC-5167-DF-LATE", "3", "2026-09-01");
        BigDecimal need = new BigDecimal("3");
        long stockBefore = scalar("SELECT stock FROM product_skus WHERE id = " + SKU_ID).longValue();
        String salesLedgerBefore = salesLedgerFingerprint();

        var defaulted = service.candidates(TENANT_ID, PRODUCT_DEFAULT, SKU_ID, need);
        var explicit = service.candidates(TENANT_ID, PRODUCT_DEFAULT, SKU_ID, need, "fifo");
        // 判据 1 本体：缺省路径与 fifo **逐值**相同（含候选顺序、建议标记、米数、口径名）
        assertThat(defaulted).usingRecursiveComparison().isEqualTo(explicit);
        assertThat(defaulted.suggestionRule()).isEqualTo("FIFO_RECEIVED_DATE");
        assertThat(defaulted.suggestedBatchNo()).isEqualTo("PC-5167-DF-EARLY");

        var plan = service.plan(TENANT_ID, List.of(
                formulaOnly(PRODUCT_DEFAULT, "acc-5167-df-1", defaulted.suggestedBatchNo(), "3")));
        service.apply(TENANT_ID, "JG-5167-DF", "ORD-5167-DF", plan);

        assertThat(ledgerBatchNos("JG-5167-DF")).as("缺省 = FIFO：扣的是先入库那批").isEqualTo("PC-5167-DF-EARLY");
        assertThat(remainingOf(earlyId)).isEqualByComparingTo("27");
        assertThat(remainingOf(lateId)).as("🔴 对照读数：3.0 的那批原封不动 —— 正是「剩了 3 米尾料」的形态")
                .isEqualByComparingTo("3");
        assertThat(exhaustedBatches(PRODUCT_DEFAULT)).as("对照读数：≤0.2 米 = 0 批（没治到痛点）")
                .isZero();
        // 不损失客户：销售账与对客库存一字不动
        assertThat(scalar("SELECT stock FROM product_skus WHERE id = " + SKU_ID).longValue())
                .as("销售账（product_skus.stock）不因批次指派而变").isEqualTo(stockBefore);
        assertThat(salesLedgerFingerprint()).as("stock_ledger_entries 不因批次指派而增行（两本账不串）")
                .isEqualTo(salesLedgerBefore);
    }

    // ────────────────────────────────────────────── 判据 6：米数口径仍是排料结果

    @Test
    @DisplayName("🔴 判据6/真库：best-fit 选出的批次上仍按**排料结果**领料（并排 ⇒ 3 米而不是公式 6 米）")
    void deductionStillFollowsTheCuttingPlanUnderBestFit() throws Exception {
        newBatch(PRODUCT_PLAN, "PC-5167-PL-EARLY", "30", "2026-08-01");
        long lateId = newBatch(PRODUCT_PLAN, "PC-5167-PL-LATE", "3", "2026-09-01");
        // 口径对照用的富裕批次（**只用来读口径、不落账**）：2×3 米的公式口径在 3.0 米的批次上本来就装不下，
        // 拿它当对照会把「装不下」误读成「口径没接线」。
        newBatch(PRODUCT_PLAN, "PC-5167-PL-CONTROL", "60", "2026-07-01");
        String chosen = service.candidates(TENANT_ID, PRODUCT_PLAN, SKU_ID, new BigDecimal("3"),
                "best_fit").suggestedBatchNo();
        assertThat(chosen).as("best-fit 挑的是余量 3.0 的那批").isEqualTo("PC-5167-PL-LATE");

        // 口径对照（同一批次、同一对行，只差定尺入参）：改前形态 = 公式口径 6 米
        var legacy = service.plan(TENANT_ID, List.of(
                formulaOnly(PRODUCT_PLAN, "acc-5167-pl-c1", "PC-5167-PL-CONTROL", "3"),
                formulaOnly(PRODUCT_PLAN, "acc-5167-pl-c2", "PC-5167-PL-CONTROL", "3")));
        // 接线后：两扇矮窗（各占门幅 1.4 ⇒ 并排成立）⇒ 逐行 1.5 米
        var plan = service.plan(TENANT_ID, List.of(
                fixedHeight(PRODUCT_PLAN, "acc-5167-pl-1", chosen, "3"),
                fixedHeight(PRODUCT_PLAN, "acc-5167-pl-2", chosen, "3")));
        System.out.println("[#5167 判别性实验] 改前形态（公式口径）合计 = "
                + sum(legacy, StockBatchConsumptionService.Deduction::plannedMeters)
                + " 米；排料口径合计 = " + sum(plan, StockBatchConsumptionService.Deduction::plannedMeters)
                + " 米（逐行 = " + plan.stream().map(d -> d.formulaMeters().toPlainString() + "/"
                + d.plannedMeters().toPlainString()).toList() + "）");

        service.apply(TENANT_ID, "JG-5167-PL", "ORD-5167-PL", plan);

        assertThat(scalar("SELECT COALESCE(SUM(formula_meters), 0) FROM stock_batch_consumptions"
                + " WHERE processing_order_no = 'JG-5167-PL'")).as("公式口径 6 米也落了库").isEqualByComparingTo("6");
        assertThat(scalar("SELECT COALESCE(-SUM(delta), 0) FROM stock_batch_consumptions"
                + " WHERE processing_order_no = 'JG-5167-PL'"))
                .as("🔴 实际扣减 = 排料结果 3 米（#5158 口径不得因换指派策略而回退到公式米数）")
                .isEqualByComparingTo("3");
        // best-fit + 并排 ⇒ 恰好用尽 3.0：不多领（不回归公式口径）、不少领（不为负）
        assertThat(remainingOf(lateId)).as("用尽且不多领（余量不得为负）").isEqualByComparingTo("0");
    }

    // ────────────────────────────────────────────── 判据 5：幂等闸

    @Test
    @DisplayName("🔴 判据5/真库：best-fit 指派下重复落账 ⇒ 唯一闸挡下（23505）、行数不变、余量不变")
    void repeatedApplyUnderBestFitIsRejectedByUniqueGate() throws Exception {
        newBatch(PRODUCT_IDEMPOTENT, "PC-5167-ID-EARLY", "30", "2026-08-01");
        long lateId = newBatch(PRODUCT_IDEMPOTENT, "PC-5167-ID-LATE", "3", "2026-09-01");
        String chosen = service.candidates(TENANT_ID, PRODUCT_IDEMPOTENT, SKU_ID, new BigDecimal("3"),
                "best_fit").suggestedBatchNo();
        var plan = service.plan(TENANT_ID, List.of(
                formulaOnly(PRODUCT_IDEMPOTENT, "acc-5167-id-1", chosen, "3")));
        service.apply(TENANT_ID, "JG-5167-ID", "ORD-5167-ID", plan);
        BigDecimal remainingAfterFirst = remainingOf(lateId);
        long rowsAfterFirst = countRows("JG-5167-ID");

        // 直接再落一遍**同一张计划**（等价于「同一加工单重复落账」）。
        // ⚠️ 这里有意**不**重新规划：best-fit 把那批用尽后，再规划会先在 plan 里被
        // 「余量不足」挡下（那本身是对的 fail-closed）—— 本条要判的是**落账层的唯一闸**。
        Throwable failure = catchThrowable(() ->
                service.apply(TENANT_ID, "JG-5167-ID", "ORD-5167-ID", plan));

        assertThat(failure).as("第二遍必须被挡下（不得静默二次扣减）").isNotNull();
        assertThat(sqlStateOf(failure)).as("挡下它的就是 uk_batch_consumption_line（SQLSTATE 23505）")
                .isEqualTo("23505");
        assertThat(countRows("JG-5167-ID")).isEqualTo(rowsAfterFirst);
        assertThat(remainingOf(lateId)).as("余量不再变化（没有二次扣减）")
                .isEqualByComparingTo(remainingAfterFirst);
        assertThat(remainingOf(lateId)).isEqualByComparingTo("0");
    }

    @Test
    @DisplayName("注入式红证：拆掉 uk_batch_consumption_line ⇒ 第二遍落账就**真的会进账**")
    void injectedWithoutUniqueGateTheSecondWriteWouldLand() throws Exception {
        newBatch(PRODUCT_IDEMPOTENT, "PC-5167-ID2-EARLY", "30", "2026-08-01");
        long lateId = newBatch(PRODUCT_IDEMPOTENT, "PC-5167-ID2-LATE", "3", "2026-09-01");
        String chosen = service.candidates(TENANT_ID, PRODUCT_IDEMPOTENT, SKU_ID, new BigDecimal("3"),
                "best_fit").suggestedBatchNo();
        var plan = service.plan(TENANT_ID, List.of(
                formulaOnly(PRODUCT_IDEMPOTENT, "acc-5167-id2-1", chosen, "3")));
        service.apply(TENANT_ID, "JG-5167-ID2", "ORD-5167-ID2", plan);

        String ddl = uniqueGateDdl();
        exec("DROP INDEX uk_batch_consumption_line");
        try {
            // 闸不在 ⇒ 同一 (加工单 × 明细行 × 批次 × reason) 的第二次落账真的进账 = 静默二次扣减。
            // 这条红证是「上面那条判据拦下它的**确实是这个闸**」的证据（不是靠文案匹配）。
            service.apply(TENANT_ID, "JG-5167-ID2", "ORD-5167-ID2", plan);
            assertThat(countRows("JG-5167-ID2")).as("拆掉闸之后台账真的多了一行").isEqualTo(2);
            assertThat(remainingOf(lateId)).as("余量被二次扣成负数").isEqualByComparingTo("-3");
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

    /** **改前形态**：只给公式米数（没有定尺入参 ⇒ 不排料 ⇒ 扣减口径 = 公式米数）。 */
    private static StockBatchConsumptionService.Designation formulaOnly(String productId, String itemId,
                                                                       String batchNo, String meters) {
        return new StockBatchConsumptionService.Designation(itemId, productId, SKU_CODE, batchNo,
                new BigDecimal(meters), null, null, null);
    }

    /** 定高买宽的两扇矮窗（门幅 2.8：窗高 1.1 + 卷边 0.3 = 各占 1.4 ⇒ 并排成立）。 */
    private static StockBatchConsumptionService.Designation fixedHeight(String productId, String itemId,
                                                                       String batchNo, String meters) {
        return new StockBatchConsumptionService.Designation(itemId, productId, SKU_CODE, batchNo,
                new BigDecimal(meters), "定高买宽", new BigDecimal("1.1"), null);
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

    /** 建一个批次（余量 + 入库日期固定），返回它的 id。入库日期是 FIFO 的排序键。 */
    private static long newBatch(String productId, String batchNo, String meters, String receivedDate)
            throws Exception {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery("INSERT INTO stock_batches (tenant_id, batch_no, product_id,"
                     + " sku_id, sku_code, quantity, unit_cost, received_date) VALUES (" + TENANT_ID
                     + ", '" + batchNo + "', '" + productId + "', " + SKU_ID + ", '" + SKU_CODE + "', "
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

    /** 该商品「≤0.2 米」档的批次数 —— 走**生产读面**（分布），不在这里另写一份分档口径。 */
    private static int exhaustedBatches(String productId) {
        return service.distribution(TENANT_ID, productId).buckets().stream()
                .filter(b -> "le_0_2".equals(b.key()))
                .findFirst()
                .orElseThrow(() -> new AssertionError("分布读面必须恒回四档"))
                .batchCount();
    }

    /** 该加工单落账的批次号（多行时按批次号聚合，便于一眼看出扣的是哪一批）。 */
    private static String ledgerBatchNos(String processingOrderNo) throws Exception {
        return text("SELECT COALESCE(string_agg(DISTINCT batch_no, ',' ORDER BY batch_no), '')"
                + " FROM stock_batch_consumptions WHERE processing_order_no = '" + processingOrderNo + "'");
    }

    /** **销售账**（{@code stock_ledger_entries}）的行指纹：批次扣减**不得**在它上面留任何痕迹。 */
    private static String salesLedgerFingerprint() throws Exception {
        return text("SELECT COALESCE(string_agg(id::text || ':' || delta::text, ',' ORDER BY id), '')"
                + " FROM stock_ledger_entries WHERE tenant_id = " + TENANT_ID);
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

    private static String text(String sql) throws Exception {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery(sql)) {
            assertThat(rs.next()).as("查询必须有结果：" + sql).isTrue();
            return rs.getString(1);
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

    private static void exec(String sql) throws Exception {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute(sql);
        }
    }

    /**
     * {@code uk_batch_consumption_line} 的 DDL **原文**（从 {@code docs/sql/schema.sql} 里取）。
     *
     * <p>注入式红证要先把闸拆掉、再把它装回去 —— 装回去时若手抄一份 DDL，抄漏一个列就会让
     * 「复原」变成另一条索引（后续判据静默失效）。故只认原文。</p>
     */
    private static String uniqueGateDdl() throws IOException {
        String schema = schemaSql();
        java.util.regex.Matcher matcher = java.util.regex.Pattern
                .compile("CREATE UNIQUE INDEX[^;]*uk_batch_consumption_line[^;]*;",
                        java.util.regex.Pattern.DOTALL)
                .matcher(schema);
        assertThat(matcher.find()).as("schema.sql 必须有 uk_batch_consumption_line 的定义").isTrue();
        return matcher.group();
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
