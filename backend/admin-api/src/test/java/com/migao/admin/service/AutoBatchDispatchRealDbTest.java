// case_ids: PR-088, PR-089
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.MybatisSqlSessionFactoryBuilder;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.MybatisPlusInterceptor;
import com.baomidou.mybatisplus.extension.plugins.handler.TenantLineHandler;
import com.baomidou.mybatisplus.extension.plugins.inner.TenantLineInnerInterceptor;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.BatchStockViews;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.entity.ProductSku;
import com.migao.admin.entity.StockBatch;
import com.migao.admin.entity.StockBatchConsumption;
import com.migao.admin.mapper.CraftCalcConfigMapper;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProcessingItemMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
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
import org.springframework.test.util.ReflectionTestUtils;

import javax.sql.DataSource;
import java.io.IOException;
import java.math.BigDecimal;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.sql.Connection;
import java.sql.ResultSet;
import java.sql.Statement;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.mock;

/**
 * 🔴 <b>事件驱动自动成批派单的真库判据（issue #5182）</b>。
 *
 * <h2>为什么必须真库（Mockito 测不出来）</h2>
 * 本单要判的两件事都是**落库事实**：① 事件触发后「一次动作批量生成多张加工单」真的把
 * {@code processing_orders} 写进去了、且 {@code stock_batch_consumptions} 上落的米数
 * 与排料口径同源（跨订单成组 ⇒ 2 张单合计 3 米而不是 6 米）；② **兜底必派** ——
 * 一个永远凑不满的池在业务约束到期时真的被派出去。mock 只能证明「调了哪个方法」：
 * 列名拼错 / 部分唯一索引没生效 / 事务没落库在 mock 面**结构上不可见**（#5141/#5148/#5158 同族教训）。
 *
 * <h2>判据</h2>
 * <ol>
 *   <li><b>PR-088 事件触发的自动成批落账</b>：同一物料的两张单在同一批次上**并排** ⇒ 真库
 *       {@code Σ(−delta) = 3}（对照：逐单派口径 = 0 节省 / 6 米应领）；两张单各一张加工单
 *       （{@code uk_processing_orders_active} 不变）；{@code saved_meters} 与**独立复算的预览口径**
 *       逐值相等；{@code generated_by} 上留下 {@code auto:order_confirmed:fifo} 的**可审计痕迹**；
 *       重复触发**不重复派也不重复扣**；作废 ⇒ 回补**逐值对称**（余量精确回到起点）；
 *       对客口径（{@code product_skus.stock} / {@code stock_ledger_entries}）一字不动。</li>
 *   <li><b>PR-089 兜底强制派（不压单可证明）</b>：需求远小于任何批次（填满率 3.3%、
 *       余量收敛不了、也不到最小批量）⇒ **三条条件都不成立**；但最晚派单日已到 ⇒ 仍被派出去。
 *       🔴 <b>同夹具红证</b>：把标准生产周期放大到同一张单不再到期 ⇒ 同一池**一张都不派**
 *       （= 去掉兜底就该单永远不派）。</li>
 * </ol>
 *
 * <h2>环境与边界（如实登记）</h2>
 * 一次性真 PG 集群（{@code initdb} + {@code pg_ctl}，随机端口、跑完即停；共用 {@link PgCluster}），
 * schema 取自 {@code backend/admin-api/src/main/resources/db/init/schema.sql}（bootstrap 终态，**不手抄列清单**）。
 * 缺 PG 二进制 ⇒ {@link PgCluster#startOrAbort()}：
 * CI（{@code MIGAO_REQUIRE_REALDB=1}）⇒ 判红；本机未设该标记 ⇒ 显式 skip（「没跑」长得像「没跑」，不是通过）。
 *
 * <p>⚠️ <b>被 stub 的两处</b>（都在被判定的事实**之外**）：① 工序库读面
 * （{@code ProductionOperationQueryService}，用 {@code RoutingModelFixture} 同一份夹具 ——
 * 工序实例化不是本单的判据）；② {@code ProductionService.instantiate}（工序实例化的落库）。
 * 本单判定的事实（{@code processing_orders} / {@code stock_batch_consumptions} /
 * {@code stock_batches} 余量 / {@code product_skus}）**全部是真库读数**。</p>
 */
@DisplayName("#5182 真库：事件触发自动成批落账 + 兜底强制派（不压单可证明）")
class AutoBatchDispatchRealDbTest {

    private static final Long TENANT_ID = 5182L;
    private static final Long SKU_ID = 5182L;
    private static final String PRODUCT_ID = "acc-5182-prod";
    private static final String SKU_CODE = "SKU-A";
    private static final String DOOR_WIDTH = "2.8米";
    private static final String UNIT_COST = "12.5";

    private static PgCluster cluster;
    private static DataSource dataSource;
    private static SqlSessionFactory factory;
    private static SqlSession session;
    private static StockBatchConsumptionService batchStock;
    private static ProcessingOrderService service;

    @BeforeAll
    static void startRealPostgresAndFixtures() throws Exception {
        cluster = PgCluster.startOrAbort();
        dataSource = cluster.dataSource();
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute(schemaSql());
            st.execute("INSERT INTO tenants (id, name, code) OVERRIDING SYSTEM VALUE VALUES (" + TENANT_ID
                    + ", 'acc-5182', 'acc-5182')");
            st.execute("INSERT INTO products (id, tenant_id, name) VALUES ('" + PRODUCT_ID + "', "
                    + TENANT_ID + ", '布艺遮光帘A')");
            st.execute("INSERT INTO product_skus (id, tenant_id, product_id, door_width, price, stock,"
                    + " sku_code) OVERRIDING SYSTEM VALUE VALUES (" + SKU_ID + ", " + TENANT_ID + ", '"
                    + PRODUCT_ID + "', '" + DOOR_WIDTH + "', 100, 60, '" + SKU_CODE + "')");
            st.execute("INSERT INTO craft_calc_configs (id, tenant_id) VALUES ('cfg-acc-5182', "
                    + TENANT_ID + ")");
        }
        MybatisConfiguration configuration = new MybatisConfiguration();
        configuration.setMapUnderscoreToCamelCase(true);
        configuration.setEnvironment(new Environment("acc-5182", new JdbcTransactionFactory(), dataSource));
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
        for (Class<?> mapper : List.of(OrderMapper.class, OrderItemMapper.class,
                ProcessingOrderMapper.class, ProcessingItemMapper.class, ProductSkuMapper.class,
                StockBatchMapper.class, StockBatchConsumptionMapper.class, CraftCalcConfigMapper.class)) {
            configuration.addMapper(mapper);
        }
        factory = new MybatisSqlSessionFactoryBuilder().build(configuration);
        session = factory.openSession(true);
        TenantContext.setTenantId(TENANT_ID);

        // 真装配：批次台账（余量 / 排料 / 幂等闸 / 回补都在这一层）
        CraftCalcConfigService configService = new CraftCalcConfigService(
                session.getMapper(CraftCalcConfigMapper.class), null);
        batchStock = new StockBatchConsumptionService(session.getMapper(StockBatchMapper.class),
                session.getMapper(StockBatchConsumptionMapper.class),
                session.getMapper(ProductSkuMapper.class), null, configService,
                // 余料腿显式不装（V122 / issue #5146）：本判据覆盖的是**批次账**，余料是附加事实
                // —— null ⇒ 不登记余料，批次账行为与 #5158 逐字相同
                null);

        // 工序库读面与工序实例化落库 stub（见类注释「边界」）；被判定的事实全在真库
        ProductionOperationQueryService operations = mock(ProductionOperationQueryService.class);
        lenient().when(operations.routeTemplateFor(eq(TENANT_ID), anyString())).thenAnswer(inv -> {
            String position = inv.getArgument(1);
            return RoutingModelFixture.defaultTemplate(TENANT_ID).getPositions() instanceof List<?> ps
                    && ps.contains(position) ? RoutingModelFixture.defaultTemplate(TENANT_ID) : null;
        });
        lenient().when(operations.defaultRouteTemplate(TENANT_ID))
                .thenReturn(RoutingModelFixture.defaultTemplate(TENANT_ID));
        lenient().when(operations.routeRules(TENANT_ID))
                .thenReturn(RoutingModelFixture.rulesWithFactors(TENANT_ID));
        lenient().when(operations.operationPositions(TENANT_ID))
                .thenReturn(RoutingModelFixture.canonicalPositions(TENANT_ID));
        lenient().when(operations.operationsByName(TENANT_ID))
                .thenReturn(RoutingModelFixture.catalog());
        lenient().when(operations.defaultCraft(TENANT_ID)).thenReturn("韩褶");
        lenient().when(operations.normalizeOperationName(anyString()))
                .thenAnswer(inv -> RoutingModelFixture.logicalName(inv.getArgument(0)));
        lenient().when(operations.variantNameOf(anyString(), any(), any()))
                .thenAnswer(inv -> RoutingModelFixture.variantNameOf(inv.getArgument(0),
                        inv.getArgument(1), inv.getArgument(2)));
        lenient().when(operations.routeSignals(TENANT_ID)).thenReturn(List.of());
        lenient().when(operations.routingKeys(TENANT_ID)).thenReturn(List.of());

        ProductionOperationQtyClient qtyClient = mock(ProductionOperationQtyClient.class);
        // 算料问数（真实现在 ai-agent / 外部 HTTP）⇒ 按请求逐部位回一份可用读数；
        // 工序实例化的落库已被 stub（见类注释「边界」），这里只保证生成链不因它中止。
        lenient().when(qtyClient.resolve(any())).thenAnswer(inv -> {
            List<Map<String, Object>> request = inv.getArgument(0);
            List<ProductionOperationQtyClient.PositionQty> resolved = new ArrayList<>();
            for (Map<String, Object> position : request) {
                Map<String, BigDecimal> qty = new LinkedHashMap<>();
                Map<String, String> source = new LinkedHashMap<>();
                if (position.get("operations") instanceof List<?> ops) {
                    for (Object raw : ops) {
                        qty.put(String.valueOf(raw), BigDecimal.ONE);
                        source.put(String.valueOf(raw), "fixture");
                    }
                }
                resolved.add(new ProductionOperationQtyClient.PositionQty(
                        String.valueOf(position.get("position_name")), qty, source));
            }
            return resolved;
        });
        ProductionService production = mock(ProductionService.class);

        service = new ProcessingOrderService(session.getMapper(ProcessingOrderMapper.class),
                session.getMapper(OrderMapper.class), session.getMapper(OrderItemMapper.class),
                session.getMapper(ProcessingItemMapper.class), mock(OrderService.class),
                new ObjectMapper(), production, operations, qtyClient);
        ReflectionTestUtils.setField(service, "stockBatchConsumptionService", batchStock);
        // 生产装配：开关打开（缺省关的形态由 AutoBatchDispatchTest 判据 1 钉住）
        ReflectionTestUtils.setField(service, "autoBatchEnabled", true);
        ReflectionTestUtils.setField(service, "autoBatchFillRatioPercent",
                ProcessingOrderService.AUTO_BATCH_DEFAULT_FILL_RATIO_PERCENT);
        ReflectionTestUtils.setField(service, "autoBatchConvergeMeters",
                ProcessingOrderService.AUTO_BATCH_DEFAULT_CONVERGE_METERS);
        ReflectionTestUtils.setField(service, "autoBatchMinBatchMeters",
                ProcessingOrderService.AUTO_BATCH_DEFAULT_MIN_BATCH_METERS);
        ReflectionTestUtils.setField(service, "autoBatchStandardCycleDays",
                ProcessingOrderService.AUTO_BATCH_DEFAULT_STANDARD_CYCLE_DAYS);
        ReflectionTestUtils.setField(service, "autoBatchAssignmentRule",
                ProcessingOrderService.AUTO_BATCH_DEFAULT_ASSIGNMENT_RULE);
    }

    /** 每个用例从**干净夹具**开始：本类共用一个集群，前一个用例的订单/台账不得串味。 */
    @org.junit.jupiter.api.BeforeEach
    void resetFixtures() throws Exception {
        for (String table : List.of("stock_batch_consumptions", "processing_orders", "stock_batches",
                "order_items", "orders")) {
            try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
                st.execute("DELETE FROM " + table + " WHERE tenant_id = " + TENANT_ID);
            }
        }
    }

    @AfterAll
    static void stopRealPostgres() {
        TenantContext.clear();
        if (session != null) {
            session.close();
        }
        if (cluster != null) {
            cluster.stop();
        }
    }

    // ────────────────────────────────────────────── PR-088

    @Test
    @DisplayName("🔴 PR-088 事件触发 ⇒ 跨订单成组落账 3 米（不是 6 米）+ 痕迹 + 预览口径一致 + 幂等 + 对称回补")
    void eventTriggeredBatchingLandsInTheRealLedger() throws Exception {
        long batchId = newBatch("PC-5182-A", "60");
        String orderA = newOrder("ORD-5182-A", null, 2, false);
        String orderB = newOrder("ORD-5182-B", null, 3, false);
        newItem("item-5182-a1", orderA, "3");
        newItem("item-5182-b1", orderB, "3");

        Map<String, BigDecimal> customerBefore = customerFingerprint();
        long ledgerBefore = stockLedgerRows();

        // 事件触发（新单确认支付入池）—— **没有任何计时器参与**
        ProcessingOrderService.AutoBatchOutcome outcome = service.autoBatchDispatch(TENANT_ID,
                PoolChangeNotifier.TRIGGER_ORDER_CONFIRMED, autoBatchPolicy(80, "0.2", "3", 7));

        assertThat(outcome.failures()).as("两张单都必须派出去").isEmpty();
        assertThat(outcome.dispatchedOrderNos()).as("两张单各一张加工单（一单一加工单的约束不变）")
                .hasSize(2);

        // ① 真库落账：跨订单成组 ⇒ 两张单合计 3 米
        assertThat(scalar("SELECT COUNT(*) FROM processing_orders WHERE tenant_id = " + TENANT_ID
                + " AND deleted = 0")).as("两张各自独立的加工单").isEqualByComparingTo("2");
        assertThat(scalar("SELECT COALESCE(-SUM(delta), 0) FROM stock_batch_consumptions"
                + " WHERE tenant_id = " + TENANT_ID + " AND batch_no = 'PC-5182-A'"))
                .as("🔴 池级一次求解：两张单的行并排 ⇒ 只扣 3 米（不是 6 米）").isEqualByComparingTo("3");
        assertThat(scalar("SELECT COUNT(DISTINCT processing_order_no) FROM stock_batch_consumptions"
                + " WHERE tenant_id = " + TENANT_ID))
                .as("3 米拆成两条台账、分属两张加工单").isEqualByComparingTo("2");
        assertThat(remainingOf(batchId)).as("省下的 3 米留在批次余量上（60 − 3）")
                .isEqualByComparingTo("57");

        // ② 可审计：谁触发的 / 按哪条规则落在 generated_by 上（持久、可查）
        assertThat(session.getMapper(ProcessingOrderMapper.class)
                .selectList(new LambdaQueryWrapper<ProcessingOrder>()
                        .eq(ProcessingOrder::getTenantId, TENANT_ID))
                .stream().map(ProcessingOrder::getGeneratedBy).distinct().toList())
                .as("🔴 留痕 = auto:<触发原因>:<规则>（不是「谁都不知道这几张单哪来的」）")
                .containsExactly("auto:" + PoolChangeNotifier.TRIGGER_ORDER_CONFIRMED + ":fifo");

        // ③ 判据 6 口径一致：真库 Σ saved_meters == 独立复算的预览口径（同一求解器、同一入参）
        BigDecimal ledgerSaved = scalar("SELECT COALESCE(SUM(formula_meters - planned_meters), 0)"
                + " FROM stock_batch_consumptions WHERE tenant_id = " + TENANT_ID);
        assertThat(ledgerSaved).as("与预览口径（Σ(formula − planned)，同 #5169 算式）**逐值相等**")
                .isEqualByComparingTo(previewSavedMeters(TENANT_ID, List.of(orderA, orderB)));
        assertThat(ledgerSaved).as("🔴 判别力：跨订单成组确实省了 3 米（不是 0）")
                .isEqualByComparingTo("3");

        // ④ 判据 7 幂等：重复触发 ⇒ 不重复派、不重复扣
        long poRows = count("processing_orders");
        long ledgerRows = count("stock_batch_consumptions");
        ProcessingOrderService.AutoBatchOutcome again = service.autoBatchDispatch(TENANT_ID,
                PoolChangeNotifier.TRIGGER_INBOUND_POSTED, autoBatchPolicy(80, "0.2", "3", 7));
        assertThat(again.dispatchedOrderNos()).as("🔴 派过的单已有活跃加工单 ⇒ 池里看不见它")
                .isEmpty();
        assertThat(count("processing_orders")).isEqualTo(poRows);
        assertThat(count("stock_batch_consumptions")).isEqualTo(ledgerRows);
        assertThat(remainingOf(batchId)).isEqualByComparingTo("57");

        // ⑤ 判据 8 可撤销：作废 ⇒ 回补**逐值对称**
        List<ProcessingOrder> rows = session.getMapper(ProcessingOrderMapper.class)
                .selectList(new LambdaQueryWrapper<ProcessingOrder>()
                        .eq(ProcessingOrder::getTenantId, TENANT_ID));
        for (ProcessingOrder po : rows) {
            batchStock.reverse(TENANT_ID, po.getProcessingOrderNo(), orderNoOf(po.getOrderId()),
                    "夹具：作废回补");
        }
        assertThat(remainingOf(batchId)).as("🔴 回补逐值对称：余量精确回到 60")
                .isEqualByComparingTo("60");
        assertThat(scalar("SELECT COALESCE(-SUM(delta), 0) FROM stock_batch_consumptions"
                + " WHERE tenant_id = " + TENANT_ID)).as("净额归零").isEqualByComparingTo("0");

        // ⑥ 判据 9 不损失客户：对客口径一字不动
        assertThat(customerFingerprint()).as("product_skus.stock 与 stock_ledger_entries 一字不动")
                .isEqualTo(customerBefore);
        assertThat(stockLedgerRows()).isEqualTo(ledgerBefore);
    }

    // ────────────────────────────────────────────── PR-089

    @Test
    @DisplayName("🔴 PR-089 兜底必派：永远凑不满的池 ⇒ 条件三条都不成立，但最晚派单日已到 ⇒ 仍被派出去")
    void businessDueForcesDispatchOfAPoolThatCanNeverFillABatch() throws Exception {
        long batchId = newBatch("PC-5182-B", "90");
        // 无客户到货日 ⇒ 兜底链走「进池日 + **可配的**标准生产周期」（本单 range 3 的分支）
        String order = newOrder("ORD-5182-C", null, 24 * 30, false);
        newItem("item-5182-c1", order, "3");

        // 成批条件全部不成立：填满率 3/90 = 3.3% < 80%、余量 90−3 = 87 > 0.2、需求 3 < 最小批量 30
        BatchStockViews.BatchRemaining remaining = batchStock
                .remaining(TENANT_ID, PRODUCT_ID, null, false).get(0);
        assertThat(remaining.remainingMeters()).isEqualByComparingTo("90");

        // 🔴 同夹具红证：把标准生产周期放大到这张单**不再到期** ⇒ 同一池一张都不派
        //（= 去掉兜底 ⇒ 这张单**永远不派**；只有周期这一个入参不同）
        ProcessingOrderService.AutoBatchOutcome notDue = service.autoBatchDispatch(TENANT_ID,
                "fixture-not-due", autoBatchPolicy(80, "0.2", "30", 3650));
        assertThat(notDue.dispatchedOrderNos()).as("🔴 去掉兜底 ⇒ 这张单**永远不派**（红证）")
                .isEmpty();
        assertThat(notDue.reasons()).as("三条成批条件一条都不成立").isEmpty();

        // 兜底：进池 30 天 + 标准生产周期 7 天 ⇒ 最晚派单日 = 今天 − 23 ⇒ 必派
        ProcessingOrderService.AutoBatchOutcome outcome = service.autoBatchDispatch(TENANT_ID,
                PoolChangeNotifier.TRIGGER_ORDER_CONFIRMED, autoBatchPolicy(80, "0.2", "30", 7));

        assertThat(outcome.failures()).as("兜底必派不得失败").isEmpty();
        assertThat(outcome.dispatchedOrderNos()).hasSize(1);
        assertThat(outcome.reasons()).anySatisfy(reason -> assertThat(reason)
                .contains("business_due").contains("ORD-5182-C"));
        assertThat(count("processing_orders")).as("🔴 兜底在业务约束内把它派出去了（不压单）")
                .isEqualTo(1);
        assertThat(session.getMapper(ProcessingOrderMapper.class)
                .selectList(new LambdaQueryWrapper<ProcessingOrder>()
                        .eq(ProcessingOrder::getTenantId, TENANT_ID))
                .get(0).getGeneratedBy())
                .as("兜底派的单同样留痕（触发原因 + 规则）").contains(":due").contains("fifo");
        assertThat(remainingOf(batchId)).as("批次账照样落（兜底派走的是同一条派单链）")
                .isEqualByComparingTo("87");
    }

    // ────────────────────────────────────────────── PR-088 注入式红证（V121）

    @Test
    @DisplayName("🔴 PR-088 注入式红证：约束换回 V119 的**符号不对称**原文 ⇒ 同一笔回补当场 23514")
    void injectedSignAsymmetricConstraintMakesReversalFail() throws Exception {
        long batchId = newBatch("PC-5182-C", "60");
        String orderA = newOrder("ORD-5182-D", null, 2, false);
        String orderB = newOrder("ORD-5182-E", null, 3, false);
        newItem("item-5182-d1", orderA, "3");
        newItem("item-5182-e1", orderB, "3");
        ProcessingOrderService.AutoBatchOutcome outcome = service.autoBatchDispatch(TENANT_ID,
                PoolChangeNotifier.TRIGGER_ORDER_CONFIRMED, autoBatchPolicy(80, "0.2", "3", 7));
        assertThat(outcome.failures()).isEmpty();
        List<ProcessingOrder> rows = processingOrders();
        String first = rows.get(0).getProcessingOrderNo();
        String firstOrderNo = orderNoOf(rows.get(0).getOrderId());

        // 注入：把约束换回 **V119 的原文**（不手抄成新表达式 —— 注入的就是被修的那一句）
        exec("ALTER TABLE stock_batch_consumptions DROP CONSTRAINT IF EXISTS"
                + " ck_batch_consumption_plan_meters");
        exec("ALTER TABLE stock_batch_consumptions ADD CONSTRAINT ck_batch_consumption_plan_meters"
                + " CHECK (planned_meters <= formula_meters AND formula_meters * planned_meters >= 0)");
        try {
            Throwable failure = org.assertj.core.api.Assertions.catchThrowable(
                    () -> batchStock.reverse(TENANT_ID, first, firstOrderNo, "注入式红证"));
            assertThat(failure).as("旧约束下这笔回补**必须失败**（否则这条红证没有判别力）").isNotNull();
            assertThat(sqlStateOf(failure))
                    .as("🔴 挡下它的就是这个 CHECK（SQLSTATE 23514），不是别的东西")
                    .isEqualTo("23514");
            assertThat(remainingOf(batchId)).as("回补没落账 ⇒ 余量还停在 57").isEqualByComparingTo("57");
        } finally {
            // 复原：表达式取自 schema.sql 原文（不手抄），并复核装回去的就是它
            exec("ALTER TABLE stock_batch_consumptions DROP CONSTRAINT IF EXISTS"
                    + " ck_batch_consumption_plan_meters");
            exec(fixedConstraintDdl());
        }
        assertThat(batchStock.reverse(TENANT_ID, first, firstOrderNo, "V121 下应成功"))
                .as("🔴 换成绝对值口径之后，同一笔回补照常落账").isPositive();
        // 池级求解把 3 米按公式米数占比拆给两张单（各 1.5）⇒ 回补要两张单都回补才对称
        String second = rows.get(1).getProcessingOrderNo();
        batchStock.reverse(TENANT_ID, second, orderNoOf(rows.get(1).getOrderId()), "V121 下应成功");
        assertThat(remainingOf(batchId)).as("两张单都回补 ⇒ 逐值对称回到 60")
                .isEqualByComparingTo("60");
    }

    // ────────────────────────────────────────────── 夹具与工具

    private static ProcessingOrderService.AutoBatchPolicy autoBatchPolicy(int fillRatio,
                                                                         String converge,
                                                                         String minBatch, int cycle) {
        return ProcessingOrderService.AutoBatchPolicy.enabledPolicy()
                .with(fillRatio, converge, minBatch, cycle);
    }

    /** 预览口径 = {@code Σ(formula − planned)}（与 {@code Preview.savedMeters} 同一算式），**独立复算**。 */
    private static BigDecimal previewSavedMeters(Long tenantId, List<String> orderIds) {
        List<StockBatchConsumptionService.Designation> lines = new ArrayList<>();
        for (String orderId : orderIds) {
            List<OrderItem> items = session.getMapper(OrderItemMapper.class).selectList(
                    new LambdaQueryWrapper<OrderItem>().eq(OrderItem::getOrderId, orderId));
            for (OrderItem item : items) {
                lines.add(new StockBatchConsumptionService.Designation(item.getId(), PRODUCT_ID,
                        SKU_CODE, batchNoOf(item.getId()), new BigDecimal("3"), "定高买宽",
                        new BigDecimal("1.1"), null));
            }
        }
        BigDecimal saved = BigDecimal.ZERO;
        for (StockBatchConsumptionService.Deduction d : batchStock.plan(tenantId, lines)) {
            saved = saved.add(d.formulaMeters().subtract(d.plannedMeters()));
        }
        return saved;
    }

    /** 该行在实际落账里用的批次号（预览必须与实际派单**同批次**才可比）。 */
    private static String batchNoOf(String itemId) {
        return session.getMapper(StockBatchConsumptionMapper.class).selectList(
                        new LambdaQueryWrapper<StockBatchConsumption>()
                                .eq(StockBatchConsumption::getOrderItemId, itemId))
                .get(0).getBatchNo();
    }

    private static List<ProcessingOrder> processingOrders() {
        return session.getMapper(ProcessingOrderMapper.class).selectList(
                new LambdaQueryWrapper<ProcessingOrder>().eq(ProcessingOrder::getTenantId, TENANT_ID)
                        .orderByAsc(ProcessingOrder::getProcessingOrderNo));
    }

    private static void exec(String sql) throws Exception {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute(sql);
        }
    }

    /** 沿 cause 链找 SQLSTATE（约束的证据必须是数据库给的，不是文案匹配）。 */
    private static String sqlStateOf(Throwable failure) {
        Throwable current = failure;
        while (current != null) {
            if (current instanceof java.sql.SQLException sqlException) {
                return sqlException.getSQLState();
            }
            current = current.getCause();
        }
        return null;
    }

    /** 修好后的约束 DDL —— **取自 schema.sql 原文**（抄错就等于换了被测对象）。 */
    private static String fixedConstraintDdl() throws IOException {
        java.util.regex.Matcher matcher = java.util.regex.Pattern.compile(
                        "ALTER TABLE stock_batch_consumptions\n    ADD CONSTRAINT"
                                + " ck_batch_consumption_plan_meters\n    CHECK \\([^;]*\\);")
                .matcher(schemaSql());
        assertThat(matcher.find()).as("schema.sql 必须有修正后的 ck_batch_consumption_plan_meters 定义")
                .isTrue();
        return matcher.group();
    }

    private static String orderNoOf(String orderId) {
        return session.getMapper(OrderMapper.class).selectById(orderId).getOrderNo();
    }

    private static String newOrder(String orderNo, LocalDate requiredDeliveryDate, int waitedHours,
                                   boolean urgent) {
        Order order = Order.builder().id("id-" + orderNo).tenantId(TENANT_ID).orderNo(orderNo)
                .status("confirmed").customerName("客户").totalAmount(new BigDecimal("999"))
                .createdAt(OffsetDateTime.now().minusHours(waitedHours)).isUrgent(urgent)
                .requiredDeliveryDate(requiredDeliveryDate).build();
        session.getMapper(OrderMapper.class).insert(order);
        return order.getId();
    }

    /** 一行明细：定高买宽、窗高 1.1、门幅 2.8 ⇒ 两块可并排（1.4 + 1.4 = 2.8）。 */
    private static void newItem(String itemId, String orderId, String meters) {
        Map<String, Object> info = new LinkedHashMap<>();
        info.put("colorName", "米白");
        info.put("sellingMethod", "散剪");
        info.put("doorWidth", DOOR_WIDTH);
        info.put("sku", SKU_CODE);
        info.put("cuttingMode", "定高买宽");
        info.put("curtainType", "布帘");
        info.put("craft", "韩褶");
        List<Map<String, Object>> procs = new ArrayList<>();
        Map<String, Object> proc = new LinkedHashMap<>();
        proc.put("id", "p1");
        proc.put("name", "打孔");
        proc.put("quantity", 2);
        proc.put("unit", "米");
        procs.add(proc);
        info.put("processingItems", procs);
        session.getMapper(OrderItemMapper.class).insert(OrderItem.builder().id(itemId)
                .tenantId(TENANT_ID).orderId(orderId).productId(PRODUCT_ID).productName("布艺遮光帘A")
                .quantity(new BigDecimal(meters)).width(new BigDecimal("1.5"))
                .height(new BigDecimal("1.1")).processingInfo(info).build());
    }

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

    /** 对客口径指纹（判据 9：自动派单不得碰销售账）。 */
    private static Map<String, BigDecimal> customerFingerprint() throws Exception {
        Map<String, BigDecimal> out = new LinkedHashMap<>();
        out.put("stock", scalar("SELECT stock FROM product_skus WHERE id = " + SKU_ID));
        out.put("ledger", scalar("SELECT COUNT(*) FROM stock_ledger_entries WHERE tenant_id = "
                + TENANT_ID));
        return out;
    }

    private static long stockLedgerRows() throws Exception {
        return scalar("SELECT COUNT(*) FROM stock_ledger_entries WHERE tenant_id = " + TENANT_ID)
                .longValue();
    }

    private static long count(String table) throws Exception {
        return scalar("SELECT COUNT(*) FROM " + table + " WHERE tenant_id = " + TENANT_ID
                + ("processing_orders".equals(table) ? " AND deleted = 0" : "")).longValue();
    }

    private static BigDecimal scalar(String sql) throws Exception {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery(sql)) {
            assertThat(rs.next()).as("查询必须有结果：" + sql).isTrue();
            return rs.getBigDecimal(1);
        }
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
