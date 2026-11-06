// case_ids: PG-001, PG-007
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.MybatisSqlSessionFactoryBuilder;
import com.baomidou.mybatisplus.extension.plugins.MybatisPlusInterceptor;
import com.baomidou.mybatisplus.extension.plugins.handler.TenantLineHandler;
import com.baomidou.mybatisplus.extension.plugins.inner.TenantLineInnerInterceptor;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ProcessingOrderGenerateRequest.BatchAssignment;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProcessingItemMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import net.sf.jsqlparser.expression.Expression;
import net.sf.jsqlparser.expression.LongValue;
import org.apache.ibatis.mapping.Environment;
import org.apache.ibatis.session.LocalCacheScope;
import org.apache.ibatis.session.SqlSessionFactory;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mybatis.spring.SqlSessionTemplate;
import org.mybatis.spring.transaction.SpringManagedTransactionFactory;
import org.springframework.aop.framework.ProxyFactory;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.transaction.annotation.AnnotationTransactionAttributeSource;
import org.springframework.transaction.interceptor.TransactionInterceptor;

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
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * 🔴 <b>加工单「生成族」的事务判据（issue #8770 下一档 = 生成族 的<b>硬前置</b>）</b>。
 *
 * <h2>为什么必须在动搬运之前先落这一条</h2>
 * <p>生成链（{@code generate} → {@code generateOne} → {@code prepare} / {@code commit}）上的
 * {@code @Transactional(rollbackFor = Exception.class)} 是<b>方法级注解</b>：Spring 只在<b>外部调用穿过代理</b>时
 * 才开事务，类内自调用（{@code generate} → {@code generateOne} → {@code commit}）全部<b>不走代理</b>，
 * 靠的是外层那一次事务。⇒ 切成单元类时，「被切走的方法在哪一侧」会静默改变事务边界，
 * 而 Mockito 判据<b>结构上看不见这件事</b>（{@code ProcessingOrderServiceTest} 的
 * {@code generateInsertFailurePropagates} / {@code generateConcurrentDuplicateRejectedIdempotently} 只验
 * 「回退被调了」，验不到「库里没有半成品」）。</p>
 *
 * <h2>判据（两条，都读真库的<b>已提交</b>状态）</h2>
 * <ol>
 *   <li><b>PG-001 事务原子性 + 订单回退</b>：{@code commit} 在<b>插完加工单之后</b>的
 *       {@code instantiateOperations} 落库失败 ⇒ ① {@code processing_orders} 里<b>一行都不留</b>
 *       （不是「本次会话看不见」—— 用<b>另一条连接</b>读已提交状态）；② 订单状态回到
 *       {@code confirmed}（{@code producing} 的推进与回退都在同一事务里）；③ 回退<b>被真的调用一次</b>
 *       且带失败原因（{@code #7723} 的联动口径）。</li>
 *   <li><b>PG-001 盖章与落库同一事务</b>：成功路径上，<b>落库那一行</b>的快照里已经有生成族的全部盖章键
 *       —— {@code order_kind}（{@code deriveOrderKind}）、{@code isUrgent} /
 *       {@code requiredDeliveryDate}（{@code stampOrderUrgency}）、{@code batchNo}
 *       （{@code stampAssignedBatches}）、{@code formulaMeters} / {@code plannedMeters} /
 *       {@code savedMeters}（{@code stampCuttingPlan}）。盖章若被搬到事务之外（或搬到另一个不走同一
 *       事务的入口），落库行就不会同时带着它们。</li>
 * </ol>
 *
 * <h2>会怎么红（两条注入都实测过，见 PR body）</h2>
 * <ul>
 *   <li>摘掉 {@code generate} 入口的 {@code @Transactional} ⇒ 事务拦截器不开事务 ⇒ 插入自动提交
 *       ⇒ 第 1 条的「一行都不留」当场红；</li>
 *   <li>摘掉 {@code commit} 的 catch 里那次 {@code revertProducingToConfirmed} ⇒ 第 1 条的回退断言红；</li>
 *   <li>把任一 {@code stamp*} 挪到 {@code insert} 之后（或挪出 {@code prepare}/{@code commit}）⇒
 *       第 2 条的盖章键失配。</li>
 * </ul>
 *
 * <h2>边界（如实登记，都不是被判定的事实）</h2>
 * <p>① <b>工序 payload 派生被 stub</b>（{@code ProcessingPositionPayloadBuilder}）—— 本判据判的是
 * 「事务边界 + 盖章」，路线派生不是判据对象（同 {@code AutoBatchDispatchRealDbTest} 的既有口径）；
 * ② <b>批次台账被 stub</b>（{@code StockBatchConsumptionService.plan} 直接给一行 {@code Deduction}）——
 * 判的是「排料结果有没有进快照」，不是「扣没扣批次」（后者由 {@code BatchConsumptionCuttingPlanRealDbTest}
 * 判）；③ <b>订单生命周期被替身</b>，但替身的两次写都落在<b>同一条被 Spring 事务绑定的连接</b>上
 * （{@code JdbcTemplate}）⇒ 回滚真的把 {@code producing} 撤掉，不是只在 mock 里记账。</p>
 *
 * <p>真库装配照抄同目录现有 RealDb 判据（{@link PgCluster#startOrAbort()}：本机无 PG 二进制 ⇒
 * 显式 skip；CI（{@code MIGAO_REQUIRE_REALDB=1}）⇒ 判红，绝不静默绿）。事务边界是<b>真的</b>
 * {@code @Transactional} 注解经真 {@code TransactionInterceptor} + {@code DataSourceTransactionManager}
 * 执行，matcher 只有 {@code AnnotationTransactionAttributeSource}（即生产代码里的注解本身）。</p>
 */
@DisplayName("🔴 真库 + 真事务：生成族盖章/判定与落库同一事务；commit 中途写库失败 ⇒ 不留半成品 + 订单回退")
class ProcessingOrderGenerationTransactionRealDbTest {

    private static final Long TENANT_ID = 8770L;
    private static final String ORDER_ID = "order-8770-tx";
    private static final String ORDER_NO = "ORD-8770-TX";
    private static final String ITEM_ID = "item-8770-tx";
    private static final String PRODUCT_ID = "prod-8770-tx";
    private static final String SKU_CODE = "SKU-8770-TX";
    private static final String BATCH_NO = "PC-20261106-8770";
    private static final LocalDate REQUIRED_DELIVERY_DATE = LocalDate.of(2026, 11, 20);

    private static PgCluster cluster;
    private static DataSource dataSource;
    private static SqlSessionTemplate sqlSessionTemplate;
    private static DataSourceTransactionManager txManager;
    private static JdbcTemplate jdbc;

    private final List<String> revertCalls = new ArrayList<>();
    private ProductionService productionService;
    private ProcessingOrderService service;

    @BeforeAll
    static void startRealPostgresAndMappers() throws Exception {
        cluster = PgCluster.startOrAbort();
        dataSource = cluster.dataSource();
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute(schemaSql());
        }
        MybatisConfiguration configuration = new MybatisConfiguration();
        configuration.setMapUnderscoreToCamelCase(true);
        // 判据用另一条连接读**已提交**状态；本会话的一级缓存不得把脏值糊在上面
        configuration.setLocalCacheScope(LocalCacheScope.STATEMENT);
        // 🔴 Spring 事务工厂：mapper 的写入必须落在**被 Spring 绑定的那一条连接**上，
        // 否则回滚只回滚了测试装置，测不到生产边界
        configuration.setEnvironment(new Environment("acc-8770-tx",
                new SpringManagedTransactionFactory(), dataSource));
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
                ProcessingOrderMapper.class, ProcessingItemMapper.class)) {
            configuration.addMapper(mapper);
        }
        SqlSessionFactory factory = new MybatisSqlSessionFactoryBuilder().build(configuration);
        sqlSessionTemplate = new SqlSessionTemplate(factory);
        txManager = new DataSourceTransactionManager(dataSource);
        jdbc = new JdbcTemplate(dataSource);
    }

    @AfterAll
    static void stopRealPostgres() {
        TenantContext.clear();
        if (cluster != null) {
            cluster.stop();
        }
    }

    @BeforeEach
    void freshFixturesAndService() throws Exception {
        for (String table : List.of("processing_orders", "stock_batch_consumptions", "order_items",
                "orders")) {
            try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
                st.execute("DELETE FROM " + table + " WHERE tenant_id = " + TENANT_ID);
            }
        }
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute("INSERT INTO tenants (id, name, code) OVERRIDING SYSTEM VALUE VALUES ("
                    + TENANT_ID + ", 'acc-8770-tx', 'acc-8770-tx') ON CONFLICT (id) DO NOTHING");
            st.execute("INSERT INTO orders (id, tenant_id, order_no, customer_name, status, is_urgent,"
                    + " required_delivery_date, deleted) VALUES ('" + ORDER_ID + "', " + TENANT_ID + ", '"
                    + ORDER_NO + "', '事务判据客户', 'confirmed', TRUE, '"
                    + REQUIRED_DELIVERY_DATE + "', 0)");
            st.execute("INSERT INTO order_items (id, tenant_id, order_id, product_id, product_name,"
                    + " quantity, processing_info, deleted) VALUES ('" + ITEM_ID + "', " + TENANT_ID
                    + ", '" + ORDER_ID + "', '" + PRODUCT_ID + "', '遮光帘', 5.00, '"
                    + processingInfoJson() + "'::jsonb, 0)");
        }
        TenantContext.setTenantId(TENANT_ID);
        revertCalls.clear();

        // 订单生命周期替身：两次写都走 JdbcTemplate（= 生产那条被 Spring 事务绑定的连接）
        OrderLifecycleService lifecycle = mock(OrderLifecycleService.class);
        doAnswer(inv -> {
            jdbc.update("UPDATE orders SET status = 'producing' WHERE id = ?", ORDER_ID);
            return null;
        }).when(lifecycle).updateOrderStatus(eq(ORDER_ID), eq("producing"), any());
        doAnswer(inv -> {
            revertCalls.add(inv.getArgument(1));
            jdbc.update("UPDATE orders SET status = 'confirmed' WHERE id = ?", ORDER_ID);
            return null;
        }).when(lifecycle).revertProducingToConfirmed(eq(ORDER_ID), anyString());

        OrderService facade = mock(OrderService.class);
        when(facade.lifecycleService()).thenReturn(lifecycle);
        when(facade.sharedParts()).thenReturn(mock(OrderSharedParts.class));

        productionService = mock(ProductionService.class);
        ProductionOperationQueryService operations = mock(ProductionOperationQueryService.class);
        ProductionOperationQtyClient qtyClient = mock(ProductionOperationQtyClient.class);

        ProcessingOrderService raw = new ProcessingOrderService(
                sqlSessionTemplate.getMapper(ProcessingOrderMapper.class),
                sqlSessionTemplate.getMapper(OrderMapper.class),
                sqlSessionTemplate.getMapper(OrderItemMapper.class),
                sqlSessionTemplate.getMapper(ProcessingItemMapper.class),
                facade, new ObjectMapper(), productionService, operations, qtyClient);

        // 工序 payload 派生被 stub（见类注释「边界」①）：本判据判事务与盖章，不判路线派生
        ProcessingPositionPayloadBuilder payloadBuilder = mock(ProcessingPositionPayloadBuilder.class);
        when(payloadBuilder.buildPositionPayload(any(), eq(TENANT_ID))).thenReturn(
                new ProcessingPositionPayloadBuilder.PositionPayload(
                        List.of(Map.of("position_name", "布帘", "operations", List.of("缝制"))),
                        "布帘×韩褶", "布帘×韩褶", "direct"));
        ReflectionTestUtils.setField(raw, "positionPayloadBuilder", payloadBuilder);

        // 批次台账被 stub（见类注释「边界」②）：只回一行排料结果，让两个 stamp* 有东西可写
        StockBatchConsumptionService batchStock = mock(StockBatchConsumptionService.class);
        when(batchStock.plan(any(), any())).thenReturn(List.of(deduction()));
        ReflectionTestUtils.setField(raw, "stockBatchConsumptionService", batchStock);

        // 🔴 真事务边界：属性只来自生产代码里的 @Transactional 注解（不手写规则）
        ProxyFactory proxy = new ProxyFactory(raw);
        proxy.setProxyTargetClass(true);
        proxy.addAdvice(new TransactionInterceptor(txManager,
                new AnnotationTransactionAttributeSource()));
        service = (ProcessingOrderService) proxy.getProxy();
    }

    // ────────────────────────────────────────────── 判据 1：事务原子性 + 订单回退

    @Test
    @DisplayName("🔴 判据 1：插完加工单后 instantiate 落库失败 ⇒ 真库零半成品 + 订单回退 confirmed + 回退被调用")
    void commitFailureLeavesNoHalfBakedRowAndRevertsOrder() throws Exception {
        when(productionService.instantiate(anyString(), any(), any()))
                .thenThrow(new IllegalStateException("模拟工序实例化落库失败"));

        assertThatThrownBy(() -> service.generate(List.of(ORDER_ID), List.of(assignment()),
                TENANT_ID, "u1"))
                .as("落库失败必须逸出事务边界（不是被吞成一条 success=false 的结果）")
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("模拟工序实例化落库失败");

        // ① 真库零半成品：**另一条连接**读已提交状态（不是「本会话看不见」）
        assertThat(scalarLong("SELECT COUNT(*) FROM processing_orders WHERE tenant_id = " + TENANT_ID))
                .as("🔴 事务回滚后 processing_orders 必须一行都不留（半成品 = 订单生产中却查不到作业单）")
                .isZero();

        // ② 订单状态回退：producing 的推进与回退一起被回滚 ⇒ 回到生成前的 confirmed
        assertThat(scalarText("SELECT status FROM orders WHERE id = '" + ORDER_ID + "'"))
                .as("🔴 订单不得停在 producing（#7723 的孤儿态）")
                .isEqualTo("confirmed");

        // ③ 回退**真的被调用过**（不是「靠回滚碰巧看起来对」）：带失败原因的联动口径要成立
        assertThat(revertCalls)
                .as("#7723：落库失败必须显式回退订单（只靠事务回滚会在 linkage 走 REQUIRES_NEW 时静默失效）")
                .hasSize(1);
        assertThat(revertCalls.get(0)).contains("派单落库失败");
    }

    // ────────────────────────────────────────────── 判据 2：盖章与落库同一事务

    @Test
    @DisplayName("🔴 判据 2：生成族四个 stamp/判定全部落在**被插入的那一行**上（订单级标记 + 单据类型 + 排料/批次）")
    void generationStampsLandWithTheInsertedRow() throws Exception {
        List<ProcessingOrderService.GenerateResult> results = service.generate(List.of(ORDER_ID),
                List.of(assignment()), TENANT_ID, "u1");

        assertThat(results).hasSize(1);
        assertThat(results.get(0).isSuccess()).as("成功路径必须真的落库").isTrue();

        long rows = scalarLong("SELECT COUNT(*) FROM processing_orders WHERE tenant_id = " + TENANT_ID);
        assertThat(rows).as("成功路径恰一行加工单").isEqualTo(1L);

        // deriveOrderKind：非卖布行 ⇒ processing（落在同表列上，且与被插入的行同批）
        assertThat(scalarText("SELECT order_kind FROM processing_orders WHERE tenant_id = " + TENANT_ID))
                .as("deriveOrderKind 的判定结果必须随插入一起落库")
                .isEqualTo(ProcessingOrderService.ORDER_KIND_PROCESSING);

        List<Map<String, Object>> snapshot = snapshotRows();
        assertThat(snapshot).as("快照行数 = 订单明细行数").hasSize(1);
        Map<String, Object> row = snapshot.get(0);

        // stampOrderUrgency（prepare 里、insert 之前盖章）
        assertThat(row.get("isUrgent")).as("stampOrderUrgency：isUrgent 恒落键").isEqualTo(true);
        assertThat(String.valueOf(row.get("requiredDeliveryDate")))
                .as("stampOrderUrgency：客户要求到货日").isEqualTo(REQUIRED_DELIVERY_DATE.toString());

        // stampAssignedBatches / stampCuttingPlan（commit 里、insert 之前盖章）
        assertThat(row.get("batchNo")).as("stampAssignedBatches：这行从哪一批裁")
                .isEqualTo(BATCH_NO);
        assertThat(new BigDecimal(String.valueOf(row.get("formulaMeters"))))
                .as("stampCuttingPlan：公式口径米数").isEqualByComparingTo("5.20");
        assertThat(new BigDecimal(String.valueOf(row.get("plannedMeters"))))
                .as("stampCuttingPlan：应领米数").isEqualByComparingTo("5.00");
        assertThat(new BigDecimal(String.valueOf(row.get("savedMeters"))))
                .as("stampCuttingPlan：省下的米数 = 公式 − 应领").isEqualByComparingTo("0.20");
    }

    // ────────────────────────────────────────────── 夹具与读数

    /** 一行人 cash 批次指派（走 {@code generate(orderIds, batches, tenantId, operator)} 的既有入口）。 */
    private static BatchAssignment assignment() {
        BatchAssignment assignment = new BatchAssignment();
        assignment.setOrderId(ORDER_ID);
        assignment.setItemId(ITEM_ID);
        assignment.setBatchNo(BATCH_NO);
        return assignment;
    }

    /** 一行排料结果（stub 的批次台账给出，见类注释「边界」②）。 */
    private static StockBatchConsumptionService.Deduction deduction() {
        return new StockBatchConsumptionService.Deduction(1L, BATCH_NO, PRODUCT_ID, 1L, SKU_CODE,
                ITEM_ID, new BigDecimal("5.20"), new BigDecimal("5.00"),
                new BigDecimal("12.50"), new BigDecimal("60.00"));
    }

    private static String processingInfoJson() {
        Map<String, Object> info = new LinkedHashMap<>();
        info.put("colorName", "米白");
        info.put("sku", SKU_CODE);
        info.put("cuttingMode", "定高买宽");
        info.put("processingItems", List.of(new LinkedHashMap<>(Map.of("name", "韩褶"))));
        try {
            return new ObjectMapper().writeValueAsString(info).replace("'", "''");
        } catch (Exception e) {
            throw new IllegalStateException(e);
        }
    }

    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> snapshotRows() throws Exception {
        String json = scalarText("SELECT items_snapshot::text FROM processing_orders WHERE tenant_id = "
                + TENANT_ID);
        return (List<Map<String, Object>>) (List<?>) new ObjectMapper().readValue(json, List.class);
    }

    private static long scalarLong(String sql) throws Exception {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery(sql)) {
            rs.next();
            return rs.getLong(1);
        }
    }

    private static String scalarText(String sql) throws Exception {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery(sql)) {
            return rs.next() ? rs.getString(1) : null;
        }
    }

    private static String schemaSql() throws IOException {
        Path root = Paths.get(System.getProperty("user.dir")).toAbsolutePath();
        while (root != null && !Files.exists(
                root.resolve("backend/admin-api/src/main/resources/db/init/schema.sql"))) {
            root = root.getParent();
        }
        assertThat(root).as("必须能定位 backend/admin-api/src/main/resources/db/init/schema.sql"
                + "（真库建表取终态 schema，不手抄列清单）").isNotNull();
        return Files.readString(root.resolve("backend/admin-api/src/main/resources/db/init/schema.sql"));
    }
}
