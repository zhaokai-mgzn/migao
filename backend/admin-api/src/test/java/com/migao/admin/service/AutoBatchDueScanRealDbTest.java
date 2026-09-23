// case_ids: PR-090, PR-091
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.MybatisSqlSessionFactoryBuilder;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.MybatisPlusInterceptor;
import com.baomidou.mybatisplus.extension.plugins.handler.TenantLineHandler;
import com.baomidou.mybatisplus.extension.plugins.inner.TenantLineInnerInterceptor;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.config.TenantContext;
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
import org.junit.jupiter.api.BeforeEach;
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
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.mock;

/**
 * 🔴 <b>「到点自愈」运行载体的真库判据（issue #5184）。</b>
 *
 * <h2>为什么必须真库（Mockito 测不出来）</h2>
 * 本单要判的两件事都是**落库事实**：① <b>无事件 + 已到期 ⇒ 真的被派出去</b>
 * （{@code processing_orders} 有一行、批次台账真的扣了、{@code generated_by} 上留了
 * {@code auto:due_scan:fifo} 的痕迹）；② <b>与事件腿并发 ⇒ 不重复派、不重复扣</b>
 * （{@code uk_processing_orders_active} + {@code uk_batch_consumption_line} 是**库层**的闸，
 * mock 面结构上看不见 —— #5141/#5148/#5158/#5182 同族教训）。对客口径（{@code product_skus.stock} /
 * {@code stock_ledger_entries}）也必须真读一次，才能说「不损失客户」。
 *
 * <h2>判据</h2>
 * <ol>
 *   <li><b>PR-090 到点自愈（判据 1）</b>：夹具里**没有发布任何业务事件**（订单不被确认支付 /
 *       没有入库过账 / 没有改单取消），只调一次到期扫描腿 ⇒ 客户要求到货日 = 今天的那张单
 *       （最晚派单日 = 今天 − 标准生产周期）在真库被派出。同夹具红证：把标准生产周期换成 3650 天
 *       （这张单不再到期）⇒ 同一池**一张都不派**（= 没有兜底就永远不派）。
 *       ⚠️ 与 #5182 的 PR-089 互补：PR-089 走的是「无到货日 ⇒ 进池日 + 周期」那一支，
 *       本判据走「**有客户到货日 ⇒ 到货日 − 周期**」这一支。</li>
 *   <li><b>PR-091 并发/幂等（判据 3）</b>：定时腿与事件腿**两线程同时**触发同一张到期单
 *       ⇒ 真库只有 **1** 张加工单、批次台账只有 **1** 笔扣减、余量只减一次；
 *       随后再扫一轮 ⇒ 不重复派、不重复扣（沿用 #5145 的闸）。</li>
 * </ol>
 *
 * <h2>环境与边界（如实登记）</h2>
 * 一次性真 PG 集群（{@code initdb} + {@code pg_ctl}，随机端口、跑完即停；共用 {@link PgCluster}），
 * schema 取自 {@code backend/admin-api/src/main/resources/db/init/schema.sql}（bootstrap 终态，**不手抄列清单**）。
 * 缺 PG 二进制 ⇒ {@link PgCluster#startOrAbort()}：
 * CI（{@code MIGAO_REQUIRE_REALDB=1}）⇒ 判红；本机未设该标记 ⇒ 显式 skip（「没跑」长得像「没跑」，不是通过）。
 *
 * <p>⚠️ <b>被 stub 的两处</b>（都在被判定的事实**之外**）：① 工序库读面
 * （{@code ProductionOperationQueryService}，用 {@code RoutingModelFixture} 同一份夹具）；
 * ② {@code ProductionService.instantiate}（工序实例化的落库）。被判定的事实
 * （{@code processing_orders} / {@code stock_batch_consumptions} / 批次余量 / {@code product_skus}）
 * **全部是真库读数**。</p>
 *
 * <p>⚠️ 并发用例的**交错不可强制**（两个线程各自读池 → 各自尝试派单）：断言写的是
 * **不变量**（1 张单 / 1 笔扣减 / 余量只减一次），在任意交错下都必须成立 ——
 * 即使某次跑成串行，它仍是「与事件腿并发/重复触发都不重复派」的有效观测。</p>
 */
@DisplayName("#5184 真库：无事件 + 已到期 ⇒ 派出（自动派单兜底的到点自愈）+ 并发不重复派不重复扣")
class AutoBatchDueScanRealDbTest {

    private static final Long TENANT_ID = 5184L;
    private static final Long SKU_ID = 5184L;
    private static final String PRODUCT_ID = "due-5184-prod";
    private static final String SKU_CODE = "SKU-A";
    private static final String DOOR_WIDTH = "2.8米";
    private static final String UNIT_COST = "12.5";
    private static final String ORDER_NO = "ORD-5184-A";
    private static final String ITEM_ID = "item-5184-a1";

    private static PgCluster cluster;
    private static DataSource dataSource;
    private static SqlSessionFactory factory;
    private static SqlSession session;
    private static StockBatchConsumptionService batchStock;
    private static ProcessingOrderService service;
    private static AutoBatchDueScanService scanner;
    private static ProductionOperationQueryService operations;
    private static ProductionOperationQtyClient qtyClient;
    private static ProductionService production;

    @BeforeAll
    static void startRealPostgresAndFixtures() throws Exception {
        cluster = PgCluster.startOrAbort();
        dataSource = cluster.dataSource();
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute(schemaSql());
            st.execute("INSERT INTO tenants (id, name, code) OVERRIDING SYSTEM VALUE VALUES (" + TENANT_ID
                    + ", 'due-5184', 'due-5184')");
            st.execute("INSERT INTO products (id, tenant_id, name) VALUES ('" + PRODUCT_ID + "', "
                    + TENANT_ID + ", '布艺遮光帘A')");
            st.execute("INSERT INTO product_skus (id, tenant_id, product_id, door_width, price, stock,"
                    + " sku_code) OVERRIDING SYSTEM VALUE VALUES (" + SKU_ID + ", " + TENANT_ID + ", '"
                    + PRODUCT_ID + "', '" + DOOR_WIDTH + "', 100, 60, '" + SKU_CODE + "')");
            st.execute("INSERT INTO craft_calc_configs (id, tenant_id) VALUES ('cfg-due-5184', "
                    + TENANT_ID + ")");
        }
        MybatisConfiguration configuration = new MybatisConfiguration();
        configuration.setMapUnderscoreToCamelCase(true);
        configuration.setEnvironment(new Environment("due-5184", new JdbcTransactionFactory(), dataSource));
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

        // 工序库读面与工序实例化落库 stub（见类注释「边界」）；被判定的事实全在真库
        operations = mock(ProductionOperationQueryService.class);
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

        qtyClient = mock(ProductionOperationQtyClient.class);
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
        production = mock(ProductionService.class);

        service = newService(session);
        batchStock = batchStockOf(session);
        scanner = new AutoBatchDueScanService(service, session.getMapper(OrderMapper.class));
    }

    /**
     * 真装配一个 {@code ProcessingOrderService}（并发用例需要**第二条连接** —— 同一个
     * {@code SqlSession} 不是线程安全的，两个线程共用它测出来的不是并发而是数据竞争）。
     */
    private static ProcessingOrderService newService(SqlSession own) {
        ProcessingOrderService built = new ProcessingOrderService(
                own.getMapper(ProcessingOrderMapper.class), own.getMapper(OrderMapper.class),
                own.getMapper(OrderItemMapper.class), own.getMapper(ProcessingItemMapper.class),
                mock(OrderService.class), new ObjectMapper(), production, operations, qtyClient);
        ReflectionTestUtils.setField(built, "stockBatchConsumptionService", batchStockOf(own));
        // 生产装配：开关打开（缺省关的形态由 AutoBatchDueScanServiceTest 判据 4 钉住）
        ReflectionTestUtils.setField(built, "autoBatchEnabled", true);
        ReflectionTestUtils.setField(built, "autoBatchFillRatioPercent",
                ProcessingOrderService.AUTO_BATCH_DEFAULT_FILL_RATIO_PERCENT);
        ReflectionTestUtils.setField(built, "autoBatchConvergeMeters",
                ProcessingOrderService.AUTO_BATCH_DEFAULT_CONVERGE_METERS);
        ReflectionTestUtils.setField(built, "autoBatchMinBatchMeters",
                ProcessingOrderService.AUTO_BATCH_DEFAULT_MIN_BATCH_METERS);
        ReflectionTestUtils.setField(built, "autoBatchStandardCycleDays",
                ProcessingOrderService.AUTO_BATCH_DEFAULT_STANDARD_CYCLE_DAYS);
        ReflectionTestUtils.setField(built, "autoBatchAssignmentRule",
                ProcessingOrderService.AUTO_BATCH_DEFAULT_ASSIGNMENT_RULE);
        return built;
    }

    private static StockBatchConsumptionService batchStockOf(SqlSession own) {
        CraftCalcConfigService configService = new CraftCalcConfigService(
                own.getMapper(CraftCalcConfigMapper.class), null);
        return new StockBatchConsumptionService(own.getMapper(StockBatchMapper.class),
                own.getMapper(StockBatchConsumptionMapper.class),
                own.getMapper(ProductSkuMapper.class), null, configService,
                // 余料腿显式不装（V122 / issue #5146）：本判据覆盖的是**批次账**，余料是附加事实
                // —— null ⇒ 不登记余料，批次账行为与 #5158 逐字相同
                null);
    }

    /** 每个用例从**干净夹具**开始：本类共用一个集群，前一个用例的订单/台账不得串味。 */
    @BeforeEach
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

    // ────────────────────────────────────────────── PR-090

    @Test
    @DisplayName("🔴 PR-090 到点自愈：**无任何业务事件** + 已过最晚派单日 ⇒ 真库被派出（痕迹 auto:due_scan:fifo）")
    void dueOrderIsDispatchedWithoutAnyBusinessEvent() throws Exception {
        long batchId = newBatch("PC-5184-A", "90");
        // 客户要求到货日 = **今天** ⇒ 最晚派单日 = 今天 − 7 天 ⇒ 已过（兜底的「有到货日」那一支）
        newOrder(ORDER_NO, LocalDate.now(), 2);
        newItem(ITEM_ID, "id-" + ORDER_NO, "3");

        String ordersBefore = ordersFingerprint();
        long customerLedgerBefore = stockLedgerRows();
        Map<String, BigDecimal> customerBefore = customerFingerprint();

        // 🔴 只调一次扫描腿：夹具里**没有**确认支付事件、没有入库过账、没有改单取消
        AutoBatchDueScanService.DueScanOutcome outcome = scanner.scanDuePooledOrders();

        assertThat(outcome.enabled()).isTrue();
        assertThat(outcome.scannedTenants()).as("超集预筛把本租户扫到了").isEqualTo(1);
        assertThat(outcome.failures()).as("兜底必派不得失败").isEmpty();
        assertThat(outcome.dispatchedOrderNos()).hasSize(1);

        // ① 真库：真的落了加工单（不是「调了哪个方法」）
        assertThat(text("SELECT generated_by FROM processing_orders WHERE tenant_id = " + TENANT_ID
                + " AND deleted = 0"))
                .as("🔴 留痕 = 来源可区分：auto:<触发原因>:<规则>，触发原因 = due_scan")
                .isEqualTo("auto:" + ProcessingOrderService.AUTO_BATCH_TRIGGER_DUE_SCAN + ":fifo");
        assertThat(scalar("SELECT COUNT(*) FROM processing_orders WHERE tenant_id = " + TENANT_ID
                + " AND deleted = 0")).isEqualByComparingTo("1");
        // ② 批次账真的扣了，且只扣一次（兜底走的是同一条派单链）
        assertThat(scalar("SELECT COALESCE(-SUM(delta), 0) FROM stock_batch_consumptions"
                + " WHERE tenant_id = " + TENANT_ID + " AND batch_no = 'PC-5184-A'"))
                .as("扣减米数 = 排料口径（夹具 3 米单行）").isEqualByComparingTo("3");
        assertThat(remainingOf(batchId)).as("余量 90 − 3").isEqualByComparingTo("87");
        // ③ 没有业务事件发生：订单侧事实逐值不变（扫描腿不碰订单，只读池）
        assertThat(ordersFingerprint()).as("🔴 扫描腿不制造任何业务事件（订单状态/到货日/建单时刻逐值不变）")
                .isEqualTo(ordersBefore);
        // ④ 判据 6 不损失客户：对客口径一字不动
        assertThat(customerFingerprint()).isEqualTo(customerBefore);
        assertThat(stockLedgerRows()).isEqualTo(customerLedgerBefore);
    }

    @Test
    @DisplayName("🔴 PR-090 同夹具红证：停掉兜底（标准生产周期 0 ⇒ 最晚派单日无从判定）⇒ 同一池一张都不派")
    void withoutTheBusinessDueJudgmentNothingIsEverDispatched() throws Exception {
        long batchId = newBatch("PC-5184-B", "90");
        newOrder(ORDER_NO, LocalDate.now(), 2);
        newItem(ITEM_ID, "id-" + ORDER_NO, "3");
        // 同一批次里再放一张**到货日在 3650 天后**的单 ⇒ 即使兜底开着，它也不该被派
        String farOrderNo = "ORD-5184-FAR";
        newOrder(farOrderNo, LocalDate.now().plusDays(3650), 2);
        newItem("item-5184-far", "id-" + farOrderNo, "3");

        // 红证 A：周期 0 ⇒ latestDispatchDate 返回 null（无从判定，不猜一个日子）⇒ **没有兜底** ⇒ 一张都不派
        ProcessingOrderService.AutoBatchOutcome noFallback = service.autoBatchDispatchDue(TENANT_ID,
                ProcessingOrderService.AUTO_BATCH_TRIGGER_DUE_SCAN,
                ProcessingOrderService.AutoBatchPolicy.enabledPolicy().with(
                        ProcessingOrderService.AUTO_BATCH_DEFAULT_FILL_RATIO_PERCENT,
                        ProcessingOrderService.AUTO_BATCH_DEFAULT_CONVERGE_METERS,
                        ProcessingOrderService.AUTO_BATCH_DEFAULT_MIN_BATCH_METERS, 0));

        assertThat(noFallback.reasons()).as("没有兜底 ⇒ 一条理由都没有").isEmpty();
        assertThat(noFallback.dispatchedOrderNos()).as("🔴 去掉兜底 ⇒ 同一池一张都不派").isEmpty();

        // 红证 B：兜底开着时，**只有**到货日 = 今天的那张到期（另一张到货日在 3650 天后 ⇒ 最晚派单日 = 今天+3643）
        AutoBatchDueScanService.DueScanOutcome scanned = scanner.scanDuePooledOrders();

        assertThat(scanned.dispatchedOrderNos()).as("🔴 派的是**到期的那一张**，不是整池").hasSize(1);
        assertThat(scalar("SELECT COUNT(*) FROM processing_orders WHERE tenant_id = " + TENANT_ID
                + " AND deleted = 0")).isEqualByComparingTo("1");
        assertThat(text("SELECT o.order_no FROM processing_orders p JOIN orders o ON o.id = p.order_id"
                + " WHERE p.tenant_id = " + TENANT_ID + " AND p.deleted = 0"))
                .as("到货日在 3650 天后的单**不派**（它没到期）").isEqualTo(ORDER_NO);
        assertThat(remainingOf(batchId)).as("只扣一张单的量").isEqualByComparingTo("87");
    }

    // ────────────────────────────────────────────── PR-091

    @Test
    @DisplayName("🔴 PR-091 并发：定时腿与事件腿同时触发同一张到期单 ⇒ 真库只 1 张加工单 / 只 1 笔扣减")
    void concurrentTimerAndEventLegsDoNotDoubleDispatchOrDoubleDeduct() throws Exception {
        long batchId = newBatch("PC-5184-C", "90");
        newOrder(ORDER_NO, LocalDate.now(), 2);
        newItem(ITEM_ID, "id-" + ORDER_NO, "3");
        Map<String, BigDecimal> customerBefore = customerFingerprint();

        SqlSession timerSession = factory.openSession(true);
        try {
            ProcessingOrderService timerService = newService(timerSession);
            AutoBatchDueScanService timerScanner =
                    new AutoBatchDueScanService(timerService, timerSession.getMapper(OrderMapper.class));
            CountDownLatch start = new CountDownLatch(1);
            AtomicReference<Object> timerOutcome = new AtomicReference<>();
            AtomicReference<Object> eventOutcome = new AtomicReference<>();

            Thread timerLeg = new Thread(() -> {
                TenantContext.setTenantId(TENANT_ID);
                try {
                    start.await(10, TimeUnit.SECONDS);
                    timerOutcome.set(timerScanner.scanDuePooledOrders());
                } catch (Exception e) {
                    timerOutcome.set(e);
                } finally {
                    TenantContext.clear();
                }
            }, "due-scan-leg");
            Thread eventLeg = new Thread(() -> {
                TenantContext.setTenantId(TENANT_ID);
                try {
                    start.await(10, TimeUnit.SECONDS);
                    eventOutcome.set(service.autoBatchDispatch(TENANT_ID,
                            PoolChangeNotifier.TRIGGER_ORDER_CONFIRMED,
                            ProcessingOrderService.AutoBatchPolicy.enabledPolicy()));
                } catch (Exception e) {
                    eventOutcome.set(e);
                } finally {
                    TenantContext.clear();
                }
            }, "event-leg");
            timerLeg.start();
            eventLeg.start();
            start.countDown();
            timerLeg.join(30_000);
            eventLeg.join(30_000);
            assertThat(timerLeg.isAlive() || eventLeg.isAlive()).as("两条腿都必须跑完").isFalse();
            assertThat(timerOutcome.get()).as("定时腿不得抛异常").isNotInstanceOf(Exception.class);
            assertThat(eventOutcome.get()).as("事件腿不得抛异常").isNotInstanceOf(Exception.class);

            // 🔴 不变量（任意交错下都成立）：一单一加工单 + 一笔扣减 + 余量只减一次
            assertThat(scalar("SELECT COUNT(*) FROM processing_orders WHERE tenant_id = " + TENANT_ID
                    + " AND deleted = 0")).as("uk_processing_orders_active 挡住第二张")
                    .isEqualByComparingTo("1");
            assertThat(scalar("SELECT COUNT(*) FROM stock_batch_consumptions WHERE tenant_id = "
                    + TENANT_ID)).as("扣减台账只有一行（不是两行）").isEqualByComparingTo("1");
            assertThat(scalar("SELECT COALESCE(-SUM(delta), 0) FROM stock_batch_consumptions"
                    + " WHERE tenant_id = " + TENANT_ID)).as("只扣一次 3 米").isEqualByComparingTo("3");
            assertThat(remainingOf(batchId)).as("余量只减一次").isEqualByComparingTo("87");
            assertThat(text("SELECT generated_by FROM processing_orders WHERE tenant_id = " + TENANT_ID
                    + " AND deleted = 0"))
                    .as("胜者的痕迹是两条腿之一（来源可区分），不会出现第三张单；"
                            + "三级降级会在 operator 上追加 :single/:plain（#5182 既有形态）⇒ 只钉前缀")
                    .satisfiesAnyOf(
                            trail -> assertThat(trail).startsWith("auto:"
                                    + ProcessingOrderService.AUTO_BATCH_TRIGGER_DUE_SCAN + ":fifo"),
                            trail -> assertThat(trail).startsWith("auto:"
                                    + PoolChangeNotifier.TRIGGER_ORDER_CONFIRMED + ":fifo"));

            // 再扫一轮（此时订单已有活跃加工单）⇒ 不重复派、不重复扣
            AutoBatchDueScanService.DueScanOutcome again = scanner.scanDuePooledOrders();
            assertThat(again.dispatchedOrderNos()).as("🔴 重复扫描不重复派").isEmpty();
            assertThat(scalar("SELECT COUNT(*) FROM processing_orders WHERE tenant_id = " + TENANT_ID
                    + " AND deleted = 0")).isEqualByComparingTo("1");
            assertThat(scalar("SELECT COUNT(*) FROM stock_batch_consumptions WHERE tenant_id = "
                    + TENANT_ID)).isEqualByComparingTo("1");
            assertThat(remainingOf(batchId)).isEqualByComparingTo("87");
            assertThat(customerFingerprint()).as("判据 6 不损失客户：并发也不碰销售账")
                    .isEqualTo(customerBefore);
        } finally {
            timerSession.close();
        }
    }

    // ────────────────────────────────────────────── 夹具与工具

    private static Order newOrder(String orderNo, LocalDate requiredDeliveryDate, int waitedHours) {
        Order order = Order.builder().id("id-" + orderNo).tenantId(TENANT_ID).orderNo(orderNo)
                .status("confirmed").customerName("客户").totalAmount(new BigDecimal("999"))
                .createdAt(OffsetDateTime.now().minusHours(waitedHours)).isUrgent(false)
                .requiredDeliveryDate(requiredDeliveryDate).build();
        session.getMapper(OrderMapper.class).insert(order);
        return order;
    }

    /** 一行明细：定高买宽、窗高 1.1、门幅 2.8（与 #5182 真库夹具同款，便于口径对照）。 */
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
                .tenantId(TENANT_ID).orderId(orderId).productId(PRODUCT_ID)
                .productName("布艺遮光帘A").quantity(new BigDecimal(meters))
                .width(new BigDecimal("1.5")).height(new BigDecimal("1.1")).processingInfo(info)
                .build());
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

    /** 对客口径指纹（判据 6：扫描腿不得碰销售账）。 */
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

    /** 订单侧指纹：扫描腿**不制造业务事件**的证据（状态 / 加急 / 到货日 / 建单时刻逐值拼接）。 */
    private static String ordersFingerprint() throws Exception {
        return text("SELECT string_agg(id || ':' || status || ':' || is_urgent || ':'"
                + " || COALESCE(required_delivery_date::text, '-') || ':' || created_at::text, ';'"
                + " ORDER BY id) FROM orders WHERE tenant_id = " + TENANT_ID);
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

    private static String schemaSql() throws IOException {
        Path root = Paths.get(System.getProperty("user.dir")).toAbsolutePath();
        while (root != null && !Files.exists(root.resolve("backend/admin-api/src/main/resources/db/init/schema.sql"))) {
            root = root.getParent();
        }
        assertThat(root).as("必须能定位 backend/admin-api/src/main/resources/db/init/schema.sql（真库建表取终态 schema，不手抄列清单）").isNotNull();
        return Files.readString(root.resolve("backend/admin-api/src/main/resources/db/init/schema.sql"));
    }
}
