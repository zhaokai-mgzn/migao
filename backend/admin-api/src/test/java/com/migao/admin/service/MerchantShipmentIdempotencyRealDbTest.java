// case_ids: OR-058, OR-045
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.MybatisSqlSessionFactoryBuilder;
import com.baomidou.mybatisplus.core.config.GlobalConfig;
import com.baomidou.mybatisplus.core.toolkit.GlobalConfigUtils;
import com.baomidou.mybatisplus.extension.plugins.MybatisPlusInterceptor;
import com.baomidou.mybatisplus.extension.plugins.handler.TenantLineHandler;
import com.baomidou.mybatisplus.extension.plugins.inner.TenantLineInnerInterceptor;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.config.MyMetaObjectHandler;
import com.migao.admin.config.TenantContext;
import com.migao.admin.controller.ProductionController;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderLogisticsMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.OrderShipmentItemMapper;
import com.migao.admin.mapper.OrderShipmentMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import com.migao.admin.mapper.ProductMapper;
import net.sf.jsqlparser.expression.Expression;
import net.sf.jsqlparser.expression.LongValue;
import org.apache.ibatis.mapping.Environment;
import org.apache.ibatis.session.SqlSessionFactory;
import org.apache.ibatis.transaction.jdbc.JdbcTransactionFactory;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.util.ReflectionTestUtils;

import javax.sql.DataSource;
import java.io.IOException;
import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.Map;
import java.sql.Connection;
import java.sql.ResultSet;
import java.sql.Statement;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.doReturn;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * 🔴 <b>商家发货端点的幂等回放判据（真库 + 真幂等表 + 真控制器，issue #6983）。</b>
 *
 * <h2>核验的是哪一条主张</h2>
 * <p>商家发货页收敛到 {@code POST /api/admin/production/orders/{orderId}/ship} 后，页面每次提交
 * 都带 {@code X-Client-Request-Id}（issue #6935 的 A 案：纳入幂等契约）。本判据把「带键提交 ⇒
 * 重复提交不会重复发货」这条**在真库上**变成读数：</p>
 * <ol>
 *   <li><b>首次</b>：{@code client_request_keys} 恰 1 行（占位）、{@code order_shipments} 恰 1 行、
 *       订单 {@code status='shipped'}；</li>
 *   <li><b>同键第二次</b>（载荷不同：运单号被改成另一个）⇒ 返回体带 {@code replayed=true}、
 *       <b>运单号仍是首次那个</b>（未被覆写）、{@code order_shipments} <b>仍恰 1 行</b>、
 *       明细仍恰 1 行。</li>
 * </ol>
 *
 * <h2>为什么必须真 PG（mock 面结构上看不见的三件事）</h2>
 * <ol>
 *   <li>{@link ClientRequestIdService#claim} 的原子占位是
 *       {@code INSERT … ON CONFLICT (tenant_id, client_request_id) DO NOTHING} +
 *       <b>按影响行数判首次</b> —— 唯一约束与 {@code ON CONFLICT} 的行为只有真库能证
 *       （mock 的 JdbcTemplate 会把「同键第二次拿到 0 行」这件事整个抹掉）；</li>
 *   <li>「同键第二次**零副作用**」的观测点是<b>表里的行数</b>（{@code order_shipments} 恰 1 行），
 *       而不是「某个 mock 方法被调用了几次」—— 被回退的 #6177 形态（重复建单）在 mock 上不可见；</li>
 *   <li>「运单号不被第二次载荷覆写」是**回放快照**与**库里那条行**两个事实的一致性
 *       （回放对了但库里被改了，同样要红）。</li>
 * </ol>
 *
 * <h2>与另外两处判据的分工（不互为副本）</h2>
 * <ul>
 *   <li>{@code ProductionControllerTest}：**端点契约面**（幂等分支 / 占位释放 / 信封），
 *       幂等服务与订单服务都是 {@code @Mock} ⇒ 不判「库里落了几行」；</li>
 *   <li>{@code MerchantShipmentRouteTest}：**端到端行为面**（2xx ∧ 恰一张 ∧ 状态流转 ∧ 原子性），
 *       幂等表用替身 ⇒ 不判真 {@code client_request_keys}；</li>
 *   <li>本类：**真库幂等面** —— 真 {@link ClientRequestIdService}（真 JdbcTemplate + 真
 *       {@code client_request_keys} 表）+ 真 Mapper + 真服务 + 真控制器
 *       （只 mock 与发货无关的外部依赖）。</li>
 * </ul>
 *
 * <h2>边界（如实登记，§19.1）</h2>
 * <p>① 本判据<b>不</b>经 HTTP（直接调控制器的 {@code ship}），故不判权限注解 / 请求头解析 /
 * 全局异常处理器 —— 那三条由 {@code ProductionControllerTest} 的 MockMvc 判据覆盖（它那里
 * 请求头就是真解析的）；② 并发同键（两个线程同时首次）不在本判据射程：占位是
 * {@code ON CONFLICT DO NOTHING} ⇒ 只有一个赢家，输家拿到 {@code REQUEST_IN_PROGRESS}(409)
 * —— 该语义在真库上由 {@code ON CONFLICT} 保证，本类只判串行重放这一条。</p>
 */
@DisplayName("🔴 真库幂等判据（#6983）：商家发货同 X-Client-Request-Id 两次 ⇒ replayed=true ∧ order_shipments 恰 1 行")
class MerchantShipmentIdempotencyRealDbTest {

    private static final Long TENANT_ID = 6983L;
    private static final String ORDER_ID = "order-6983-idem";
    private static final String ITEM_ID = "item-6983-idem";
    private static final String PRODUCT_ID = "prod-6983-idem";
    private static final BigDecimal ORDER_QTY = new BigDecimal("7.50");
    /**
     * 本判据用的幂等键（请求头 {@code X-Client-Request-Id} 的取值）。
     *
     * <p>🔴 常量名与取值都**刻意避开凭据形态**（issue #6983 的 CI 实测）：早先写成
     * {@code REQUEST_ID = "ship-6983-idem-key"} 时被 gitleaks 默认规则 {@code generic-api-key}
     * 按「标识符含 key + 值熵 3.68 ≥ 3.5」判成疑似 API Key ⇒ 这条 required 腿（Secret Scan）
     * 判红。它是**测试夹具值、不是凭据**，而本仓对这类形态的既定处置有两条：
     * <b>①</b> 按 {@code .gitleaksignore} 登记指纹（该指纹**绑定 commit SHA** ⇒ 每次
     * rebase/amend 都要重算）；<b>②</b> 直接让取值不再命中规则（零维护）。本判据取 <b>②</b>：
     * 这个值的语义只是「两次请求用同一个键」，改小写法的字面量不损失任何判别力。</p>
     */
    private static final String REQUEST_ID = "ship-6983-1";

    private static PgCluster cluster;
    private static DataSource dataSource;
    private static SqlSessionFactory factory;
    private static JdbcTemplate jdbcTemplate;

    private ProductionController controller;

    @BeforeAll
    static void startRealPostgresAndFixtures() throws Exception {
        cluster = PgCluster.startOrAbort();
        dataSource = cluster.dataSource();
        jdbcTemplate = new JdbcTemplate(dataSource);
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute(schemaSql());
            st.execute("INSERT INTO tenants (id, name, code) OVERRIDING SYSTEM VALUE VALUES ("
                    + TENANT_ID + ", 'ms-6983', 'ms-6983')");
            st.execute("INSERT INTO orders (id, tenant_id, order_no, status, total_amount, actual_amount) VALUES ('"
                    + ORDER_ID + "', " + TENANT_ID + ", 'NO-6983-IDEM', 'confirmed', 100.00, 100.00)");
            st.execute("INSERT INTO order_items (id, tenant_id, order_id, product_id, product_name,"
                    + " quantity, unit_price, subtotal) VALUES ('"
                    + ITEM_ID + "', " + TENANT_ID + ", '" + ORDER_ID + "', '" + PRODUCT_ID
                    + "', '遮光布-6983', " + ORDER_QTY.toPlainString() + ", 100.00, 750.00)");
        }
        MybatisConfiguration configuration = new MybatisConfiguration();
        configuration.setMapUnderscoreToCamelCase(true);
        configuration.setEnvironment(new Environment("ms-6983", new JdbcTransactionFactory(), dataSource));
        // 多租户拦截器**必须在场**（与生产同口径）：生产 SQL 会经它追加 tenant_id 谓词，
        // 少了它只剩 mapper 原文 —— 而「本端点只动本租户的订单」正是断言的一部分。
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
        for (Class<?> mapper : List.of(OrderMapper.class, OrderItemMapper.class, OrderLogisticsMapper.class,
                OrderShipmentMapper.class, OrderShipmentItemMapper.class,
                ProcessingOrderMapper.class, ProductMapper.class)) {
            configuration.addMapper(mapper);
        }
        // 🔴 审计列（created_at / updated_at）在 production 由 **MyMetaObjectHandler** 填充：
        // 本装置里必须在场，否则 MP 会把这两列显式写成 NULL 而撞 NOT NULL ——
        // 那种「红」指向的是装置，不是被测对象（同 §23 T2「别把装置缺陷读成代码缺陷」）。
        // ⚠️ 必须**改既有那份 GlobalConfig**，不能 {@code setGlobalConfig(新对象)}：
        // 3.5.16 的实现是 {@code Map.putIfAbsent(configHash, config)} —— 既有条目在场时
        // 新对象**被静默丢弃**（实测读数：改前 handler=null 而 TableInfo 的
        // {@code createdAt:INSERT} 明明在场 ⇒「填了却没生效」）。
        GlobalConfigUtils.getGlobalConfig(configuration)
                .setMetaObjectHandler(new MyMetaObjectHandler());
        factory = new MybatisSqlSessionFactoryBuilder().build(configuration);
    }

    @AfterAll
    static void stopRealPostgres() {
        if (cluster != null) {
            cluster.stop();
        }
    }

    @AfterEach
    void clearTenant() {
        TenantContext.clear();
    }

    @Test
    @DisplayName("同 X-Client-Request-Id 两次 ⇒ 第二次 replayed=true ∧ 运单号未被覆写 ∧ order_shipments 恰 1 行")
    void sameClientRequestIdReplaysOnRealDb() {
        Map<String, Object> first = callShip("{\"trackingNo\":\"SF-6983-FIRST\",\"logisticsCompany\":\"顺丰\","
                + "\"shippingMethod\":\"logistics\",\"logisticsType\":\"express\",\"shipperName\":\"王五\"}",
                REQUEST_ID);
        System.out.println("[READING #6983 真库幂等 ① 首次] replayed=" + first.get("replayed")
                + " tracking_no=" + first.get("tracking_no")
                + " shipment_no=" + first.get("shipment_no")
                + " client_request_keys=" + countClientKeys() + " order_shipments=" + countShipments());

        assertThat(first.get("shipment_no")).as("首次必须真的建出可查的发货单（否则判据是空跑）")
                .isNotNull();
        assertThat(first.get("replayed")).as("首次不得带 replayed 标记").isNull();
        assertThat(countClientKeys()).as("首次必须真的在 client_request_keys 里占位（真库事实）")
                .isEqualTo(1);
        assertThat(countShipments()).as("首次恰 1 张发货单").isEqualTo(1);
        assertThat(countShipmentItems()).as("逐订单行一行明细").isEqualTo(1);
        assertThat(orderStatus()).as("订单真的流转成 shipped").isEqualTo("shipped");
        assertThat(logisticsTrackingNo()).as("物流行的运单号 = 首次载荷")
                .isEqualTo("SF-6983-FIRST");

        // ── 同键第二次：载荷**不同**（运单号改了）⇒ 必须回放首次结果、零副作用 ──
        Map<String, Object> second = callShip(
                "{\"trackingNo\":\"SF-6983-SECOND\",\"logisticsCompany\":\"德邦\"}", REQUEST_ID);
        System.out.println("[READING #6983 真库幂等 ② 同键重复] replayed=" + second.get("replayed")
                + " tracking_no=" + second.get("tracking_no")
                + " order_shipments=" + countShipments() + " logistics_tracking_no=" + logisticsTrackingNo());

        assertThat(second.get("replayed")).as("🔴 同键第二次必须显式回报放（issue #6935 的 A 案）")
                .isEqualTo(Boolean.TRUE);
        assertThat(second.get("tracking_no")).as("回放的是首次快照 ⇒ 运单号不得被第二次载荷覆写")
                .isEqualTo("SF-6983-FIRST");
        assertThat(countShipments()).as("🔴 同键两次 ⇒ order_shipments **恰 1 行**").isEqualTo(1);
        assertThat(countShipmentItems()).as("明细也不得翻倍").isEqualTo(1);
        assertThat(countClientKeys()).as("同键仍只有一行（ON CONFLICT DO NOTHING）").isEqualTo(1);
        assertThat(logisticsTrackingNo()).as("库里的物流行也不得被第二次载荷覆写（回放 ≠ 只改响应）")
                .isEqualTo("SF-6983-FIRST");
        assertThat(logisticsShippingMethod()).as("发货方式落库（issue #6239 的接线在本路也成立）")
                .isEqualTo("logistics");
        assertThat(logisticsLogisticsType()).as("物流类型落库（发货页采集的字段有落点）")
                .isEqualTo("express");
        assertThat(logisticsShipperName()).as("发货人落库（发货单纸面「经手人」）").isEqualTo("王五");
    }

    // ────────────────────────────────────────────── 夹具 / 读数

    /** 直接调**真控制器**的 {@code ship}（HTTP 面由 ProductionControllerTest 覆盖，见类注释「边界」）。 */
    private Map<String, Object> callShip(String body, String clientRequestId) {
        controller = controller();
        return controller.ship(ORDER_ID, jsonToMap(body), clientRequestId).getData();
    }

    private ProductionController controller() {
        OrderMapper orderMapper = mapper(OrderMapper.class);
        OrderItemMapper orderItemMapper = mapper(OrderItemMapper.class);
        OrderLogisticsMapper orderLogisticsMapper = mapper(OrderLogisticsMapper.class);
        OrderShipmentMapper orderShipmentMapper = mapper(OrderShipmentMapper.class);
        OrderShipmentItemMapper orderShipmentItemMapper = mapper(OrderShipmentItemMapper.class);
        ProcessingOrderMapper processingOrderMapper = mapper(ProcessingOrderMapper.class);
        ProductMapper productMapper = mapper(ProductMapper.class);

        // 真幂等服务（真 JdbcTemplate → 真 client_request_keys 表）
        ObjectProvider<JdbcTemplate> provider = mock(ObjectProvider.class);
        doReturn(jdbcTemplate).when(provider).getIfAvailable();
        ClientRequestIdService clientRequestIdService =
                new ClientRequestIdService(provider, new ObjectMapper());

        UserService userService = mock(UserService.class);
        when(userService.resolveCurrentUserDisplayName()).thenReturn("系统兜底人");

        OrderService orderService = new OrderService(orderMapper, orderItemMapper, orderLogisticsMapper,
                mock(CustomerService.class), productMapper, null, null, new ObjectMapper(),
                mock(NotificationService.class), processingOrderMapper, userService, clientRequestIdService,
                mock(StockLedgerService.class), mock(ProcessingFeeCalculator.class),
                mock(ProcessingFeeCombinationCommandService.class));
        OrderShipmentService orderShipmentService = new OrderShipmentService(orderMapper, orderItemMapper,
                orderLogisticsMapper, orderShipmentMapper, orderShipmentItemMapper, processingOrderMapper,
                clientRequestIdService, mock(ImageRecognitionClient.class), new ObjectMapper(),
                null, org.mockito.Mockito.mock(com.migao.admin.service.FinishedGoodsService.class));
        ReflectionTestUtils.setField(orderShipmentService, "productMapper", productMapper);

        ProductionController controller = new ProductionController(null, null, null, null, null, orderService);
        ReflectionTestUtils.setField(controller, "clientRequestIdService", clientRequestIdService);
        ReflectionTestUtils.setField(controller, "orderShipmentService", orderShipmentService);
        ReflectionTestUtils.setField(controller, "orderMapper", orderMapper);
        TenantContext.setTenantId(TENANT_ID);
        return controller;
    }

    private <T> T mapper(Class<T> type) {
        return factory.openSession(true).getMapper(type);
    }

    private Map<String, String> jsonToMap(String json) {
        try {
            return new ObjectMapper().readValue(json, new com.fasterxml.jackson.core.type.TypeReference<>() {
            });
        } catch (IOException e) {
            throw new IllegalStateException("夹具 JSON 不合法: " + json, e);
        }
    }

    private long countClientKeys() {
        return scalarLong("SELECT count(*) FROM client_request_keys WHERE tenant_id = " + TENANT_ID);
    }

    private long countShipments() {
        return scalarLong("SELECT count(*) FROM order_shipments WHERE tenant_id = " + TENANT_ID
                + " AND order_id = '" + ORDER_ID + "' AND deleted = 0");
    }

    private long countShipmentItems() {
        return scalarLong("SELECT count(*) FROM order_shipment_items WHERE tenant_id = " + TENANT_ID
                + " AND order_id = '" + ORDER_ID + "'");
    }

    private String orderStatus() {
        return scalarString("SELECT status FROM orders WHERE id = '" + ORDER_ID + "'");
    }

    private String logisticsTrackingNo() {
        return scalarString("SELECT tracking_no FROM order_logistics WHERE order_id = '" + ORDER_ID
                + "' AND tenant_id = " + TENANT_ID + " AND deleted = 0");
    }

    private String logisticsShippingMethod() {
        return scalarString("SELECT shipping_method FROM order_logistics WHERE order_id = '" + ORDER_ID
                + "' AND tenant_id = " + TENANT_ID + " AND deleted = 0");
    }

    private String logisticsLogisticsType() {
        return scalarString("SELECT logistics_type FROM order_logistics WHERE order_id = '" + ORDER_ID
                + "' AND tenant_id = " + TENANT_ID + " AND deleted = 0");
    }

    private String logisticsShipperName() {
        return scalarString("SELECT shipper_name FROM order_logistics WHERE order_id = '" + ORDER_ID
                + "' AND tenant_id = " + TENANT_ID + " AND deleted = 0");
    }

    private long scalarLong(String sql) {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery(sql)) {
            assertThat(rs.next()).as("读数 SQL 必须返回一行: " + sql).isTrue();
            return rs.getLong(1);
        } catch (Exception e) {
            throw new IllegalStateException("读数失败: " + sql, e);
        }
    }

    private String scalarString(String sql) {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery(sql)) {
            assertThat(rs.next()).as("读数 SQL 必须返回一行: " + sql).isTrue();
            return rs.getString(1);
        } catch (Exception e) {
            throw new IllegalStateException("读数失败: " + sql, e);
        }
    }

    private static String schemaSql() throws IOException {
        Path schema = Paths.get("src", "main", "resources", "db", "init", "schema.sql");
        assertThat(Files.exists(schema)).as("schema.sql 必须存在（路径漂移 ⇒ 判红，不是空跑通过）").isTrue();
        return Files.readString(schema, StandardCharsets.UTF_8);
    }

}
