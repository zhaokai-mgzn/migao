// case_ids: OR-011, OR-014
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.MybatisSqlSessionFactoryBuilder;
import com.baomidou.mybatisplus.extension.plugins.MybatisPlusInterceptor;
import com.baomidou.mybatisplus.extension.plugins.handler.TenantLineHandler;
import com.baomidou.mybatisplus.extension.plugins.inner.TenantLineInnerInterceptor;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.dto.OrderCreateRequest;
import com.migao.admin.dto.agent.AgentOrderCreateRequest;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderLogisticsMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProductMapper;
import com.migao.admin.mapper.ProductSkuMapper;
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
import static org.mockito.Mockito.mock;

/**
 * 🔴 <b>「订单行没有 SKU 标识 ⇒ 422 fail-closed」的**真库**判据（issue #3881 缺陷二 / #4025 F11）</b>。
 *
 * <h2>为什么必须真库</h2>
 * mock 面只能证明「抛了什么异常」。本单新增的两条读路径是**真 SQL**：
 * ① {@code products} 按 {@code (tenant_id, name)} 唯一匹配（逻辑删除 {@code @TableLogic} 与租户拦截器
 * 都要真的生效）；② {@code product_skus} 按 {@code (tenant_id, product_id)} 取价格集合。
 * 列名拼错 / 逻辑删除漏滤 / 拦截器把条件重写坏，在 mock 面**结构上不可见**（#5141/#5148/#5169 同族教训）。
 * 反向那一半同样只有真库能钉：**被拒绝时数据库里一行订单都不能有**（「先建单再报错」在 mock 面看不出来）。
 *
 * <h2>判据（每条都打印**同参数读数**，不是「跑了就算」）</h2>
 * <ol>
 *   <li><b>判据 1·多规格多价 + 无 SKU 标识 ⇒ 422 + 零落账</b>：真库读数
 *       {@code thrown=… / landedOrders=N / landedAmount=…} 三个都打印；<b>改前形态</b>（本 PR 之前）
 *       同一夹具下 {@code thrown=null}、{@code landedOrders=1}（编造价 150 真进总额）。</li>
 *   <li><b>判据 2·只有商品名</b>（无 product_id）⇒ 真 SQL 按名唯一解析**成功**（错误文案是
 *       「多个不同规格价」而不是「匹配不到唯一商品」——文案本身区分「查到了但规格不定」与「没查到」）。</li>
 *   <li><b>判据 3·合法形态逐值不变</b>：SKU 价唯一的商品 + 未声明规格 ⇒ **不得拦**，
 *       订单真的落库且 {@code total_amount} = 单价 × 数量。</li>
 *   <li><b>判据 4·无 SKU 记录的简单商品（卖布行形态）</b>⇒ 权威价 = 商品级价，照旧落库。</li>
 *   <li><b>判据 5·商品名查不到 / 同名多条</b> ⇒ 422 且零落账（不猜是哪个商品 = 不按错价核对）。</li>
 * </ol>
 *
 * <h2>环境</h2>
 * 一次性真 PG 集群（{@code initdb} + {@code pg_ctl}，随机端口、跑完即停；共用 {@link PgCluster}），
 * schema 取自 {@code backend/admin-api/src/main/resources/db/init/schema.sql}（bootstrap 终态，不手抄列清单）。
 * 缺 PG 二进制 ⇒ {@link PgCluster#startOrAbort()}：CI（{@code MIGAO_REQUIRE_REALDB=1}）判红；
 * 本机未设该标记 ⇒ 显式 skip（「没跑」长得像「没跑」，不是通过）。
 */
@DisplayName("#3881 真库判据：无 SKU 标识的订单行不得静默放过（改前真库真的落单）")
class OrderNoSkuIdentityRealDbTest {

    private static final Long TENANT_ID = 3881L;
    /** 多规格**多价**商品（SKU 150 / 180）—— 未声明规格时权威价无从唯一确定 ⇒ 必须 422。 */
    private static final String MULTI_PRODUCT = "rdb-3881-multi";
    private static final String MULTI_NAME = "真库遮光帘多价";
    /** 多规格**同价**商品（两个 SKU 都 150）—— 权威价唯一 ⇒ 合法形态，不得拦。 */
    private static final String SINGLE_PRODUCT = "rdb-3881-single";
    private static final String SINGLE_NAME = "真库遮光帘单价";
    /** **没有 SKU 记录**的简单商品（卖布行形态）：权威价 = 商品级价 30.00。 */
    private static final String SIMPLE_PRODUCT = "rdb-3881-simple";
    private static final String SIMPLE_NAME = "真库纯布";

    private static PgCluster cluster;
    private static DataSource dataSource;
    private static SqlSession session;
    private static OrderService orderService;

    @BeforeAll
    static void startRealPostgresAndFixtures() throws Exception {
        cluster = PgCluster.startOrAbort();
        dataSource = cluster.dataSource();
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute(schemaSql());
            st.execute("INSERT INTO tenants (id, name, code) OVERRIDING SYSTEM VALUE VALUES ("
                    + TENANT_ID + ", 'acc-3881', 'acc-3881')");
            st.execute("INSERT INTO products (id, tenant_id, name, base_price) VALUES ('"
                    + MULTI_PRODUCT + "', " + TENANT_ID + ", '" + MULTI_NAME + "', 168.00)");
            st.execute(skuInsert(38811L, MULTI_PRODUCT, "150.00"));
            st.execute(skuInsert(38812L, MULTI_PRODUCT, "180.00"));
            st.execute("INSERT INTO products (id, tenant_id, name, base_price) VALUES ('"
                    + SINGLE_PRODUCT + "', " + TENANT_ID + ", '" + SINGLE_NAME + "', 150.00)");
            st.execute(skuInsert(38813L, SINGLE_PRODUCT, "150.00"));
            st.execute(skuInsert(38814L, SINGLE_PRODUCT, "150.00"));
            // 无 SKU 记录 ⇒ 商品级价兜底（**显式允许**，见 #3881 的 P0 建议原文）
            st.execute("INSERT INTO products (id, tenant_id, name, base_price) VALUES ('"
                    + SIMPLE_PRODUCT + "', " + TENANT_ID + ", '" + SIMPLE_NAME + "', 30.00)");
        }
        MybatisConfiguration configuration = new MybatisConfiguration();
        configuration.setMapUnderscoreToCamelCase(true);
        configuration.setEnvironment(new Environment("acc-3881", new JdbcTransactionFactory(), dataSource));
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
        for (Class<?> mapper : List.of(ProductMapper.class, ProductSkuMapper.class, OrderMapper.class,
                OrderItemMapper.class, OrderLogisticsMapper.class)) {
            configuration.addMapper(mapper);
        }
        SqlSessionFactory factory = new MybatisSqlSessionFactoryBuilder().build(configuration);
        session = factory.openSession(true);
        // 真装配：本单新增的两条商品/SKU 读路径走**真库 mapper**；与金额无关的下游依赖给 mock
        //（客户建档 / 站内信 / 台账 / 幂等键都不是本判据的对象）
        orderService = new OrderService(
                session.getMapper(OrderMapper.class),
                session.getMapper(OrderItemMapper.class),
                session.getMapper(OrderLogisticsMapper.class),
                mock(CustomerService.class),
                session.getMapper(ProductMapper.class),
                session.getMapper(ProductSkuMapper.class),
                mock(com.migao.admin.mapper.FinanceTransactionMapper.class),
                new ObjectMapper(),
                mock(NotificationService.class),
                mock(com.migao.admin.mapper.ProcessingOrderMapper.class),
                mock(UserService.class),
                mock(ClientRequestIdService.class),
                mock(StockLedgerService.class),
                new ProcessingFeeCalculator(
                        mock(com.migao.admin.mapper.ProcessingFeeCombinationMapper.class),
                        mock(com.migao.admin.mapper.ProductionRouteRuleMapper.class)),
                mock(ProcessingFeeCombinationCommandService.class));
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

    // ────────────────────────────────────────────── 判据 1：多价 + 无标识 ⇒ 422 + 零落账

    @Test
    @DisplayName("🔴 判据1 真库：无 SKU 标识 + 商品有多个不同规格价 ⇒ 422 且订单表零落账"
            + "（红证：改前同一夹具 thrown=null / landedOrders=1）")
    void multiPriceWithoutSkuKeyIsRejectedWithZeroLanding() throws Exception {
        String phone = "13800138831";
        AgentOrderCreateRequest req = agentRequest(MULTI_PRODUCT, MULTI_NAME, "150", phone, null);

        Throwable thrown = catchThrowable(() -> orderService.createOrderForAgent(req, TENANT_ID));
        int landed = landedOrders(phone);
        String amount = landedAmount(phone);
        // 三个读数一起打印（改前/改后都能读出「到底拦没拦、落没落」）
        System.out.println("[red-reading #3881 判据1] thrown=" + thrown
                + " | landedOrders=" + landed + " | landedAmount=" + amount);

        assertThat(thrown).as("无 SKU 标识 + 多规格多价必须 fail-closed（改前静默放过）")
                .isInstanceOf(BusinessException.class);
        BusinessException ex = (BusinessException) thrown;
        assertThat(ex.getHttpStatus()).isEqualTo(422);
        assertThat(ex.getCode()).isEqualTo("VALIDATION_ERROR");
        assertThat(ex.getMessage()).contains("多个不同规格价");
        assertThat(ex.getSuggestion()).contains("skuId");
        assertThat(landed).as("被拒绝 ⇒ 数据库里一行订单都不能有").isZero();
    }

    // ────────────────────────────────────────────── 判据 2：只有商品名（真 SQL 按名唯一解析）

    @Test
    @DisplayName("🔴 判据2 真库：只有商品名（无 product_id）+ 多规格多价 ⇒ 422，且文案出自**按名解析成功**那一支"
            + "（红证：改前 thrown=null / landedOrders=1）")
    void nameOnlyLineResolvesByNameThenRejects() throws Exception {
        String phone = "13800138832";
        AgentOrderCreateRequest req = agentRequest(null, MULTI_NAME, "150", phone, null);

        Throwable thrown = catchThrowable(() -> orderService.createOrderForAgent(req, TENANT_ID));
        System.out.println("[red-reading #3881 判据2] thrown=" + thrown
                + " | landedOrders=" + landedOrders(phone));

        assertThat(thrown).isInstanceOf(BusinessException.class);
        // 真 SQL 按 (tenant_id, name) 解析**成功**才会走到「规格多价」这一支；
        // 若解析失败，文案会是「匹配不到唯一商品」⇒ 这条断言同时钉住了 name 查询真的可用
        assertThat(thrown.getMessage()).contains("多个不同规格价")
                .doesNotContain("匹配不到唯一商品");
        assertThat(landedOrders(phone)).isZero();
    }

    // ────────────────────────────────────────────── 判据 3：合法形态（同价多 SKU）不得被拦

    @Test
    @DisplayName("判据3 真库：SKU 价唯一的商品 + 未声明规格 ⇒ 不得拦，订单真落库且 total_amount = 单价 × 数量")
    void singlePriceProductWithoutSkuKeyLandsOnRealDb() throws Exception {
        String phone = "13800138833";
        AgentOrderCreateRequest req = agentRequest(SINGLE_PRODUCT, SINGLE_NAME, "150", phone, null);

        var created = orderService.createOrderForAgent(req, TENANT_ID);
        int landed = landedOrders(phone);
        String amount = landedAmount(phone);
        System.out.println("[reading #3881 判据3] status=" + created.getStatus()
                + " | landedOrders=" + landed + " | landedAmount=" + amount);

        assertThat(created.getStatus()).isEqualTo("pending");
        assertThat(landed).isEqualTo(1);
        assertThat(new BigDecimal(amount)).isEqualByComparingTo("300.00");
    }

    // ────────────────────────────────────────────── 判据 4：无 SKU 记录的简单商品（卖布行）

    @Test
    @DisplayName("判据4 真库：商品**没有 SKU 记录**（卖布行/简单商品）⇒ 权威价 = 商品级价，照旧落库")
    void simpleProductWithoutSkuRowsLandsOnRealDb() throws Exception {
        String phone = "13800138834";
        AgentOrderCreateRequest req = agentRequest(SIMPLE_PRODUCT, SIMPLE_NAME, "30", phone, null);

        var created = orderService.createOrderForAgent(req, TENANT_ID);
        int landed = landedOrders(phone);
        String amount = landedAmount(phone);
        System.out.println("[reading #3881 判据4] status=" + created.getStatus()
                + " | landedOrders=" + landed + " | landedAmount=" + amount);

        assertThat(created.getStatus()).isEqualTo("pending");
        assertThat(landed).isEqualTo(1);
        assertThat(new BigDecimal(amount)).isEqualByComparingTo("60.00");
    }

    // ────────────────────────────────────────────── 判据 5：商品解析不到 ⇒ 422 + 零落账

    @Test
    @DisplayName("🔴 判据5 真库：商品名在库里查不到 ⇒ 422 且零落账（不猜商品、不按错价核对）"
            + "（红证：改前 thrown=null / landedOrders=1）")
    void unresolvableProductIsRejectedOnRealDb() throws Exception {
        String phone = "13800138835";
        AgentOrderCreateRequest req = agentRequest(null, "真库根本不存在的商品", "150", phone, null);

        Throwable thrown = catchThrowable(() -> orderService.createOrderForAgent(req, TENANT_ID));
        System.out.println("[red-reading #3881 判据5] thrown=" + thrown
                + " | landedOrders=" + landedOrders(phone));

        assertThat(thrown).isInstanceOf(BusinessException.class);
        assertThat(((BusinessException) thrown).getHttpStatus()).isEqualTo(422);
        assertThat(thrown.getMessage()).contains("匹配不到唯一商品");
        assertThat(landedOrders(phone)).isZero();
    }

    // ────────────────────────────────────────────── helpers

    private static AgentOrderCreateRequest agentRequest(String productId, String productName,
                                                        String unitPrice, String phone, Object processingInfo) {
        AgentOrderCreateRequest req = new AgentOrderCreateRequest();
        req.setCustomerName("真库张三");
        req.setCustomerPhone(phone);
        OrderCreateRequest.OrderItemRequest item = new OrderCreateRequest.OrderItemRequest();
        item.setProductId(productId);
        item.setProductName(productName);
        item.setQuantity(BigDecimal.valueOf(2));
        item.setUnitPrice(new BigDecimal(unitPrice));
        item.setSubtotal(new BigDecimal(unitPrice).multiply(BigDecimal.valueOf(2)));
        item.setProcessingInfo(processingInfo);
        req.setItems(List.of(item));
        return req;
    }

    private static String skuInsert(long id, String productId, String price) {
        return "INSERT INTO product_skus (id, tenant_id, product_id, sku_code, color_name, door_width, price, stock)"
                + " VALUES (" + id + ", " + TENANT_ID + ", '" + productId + "', 'SKU-" + id
                + "', '标准色', '2.8', " + price + ", 100)";
    }

    private static int landedOrders(String phone) throws SQLException {
        try (Connection conn = dataSource.getConnection();
             Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery("SELECT COUNT(*) FROM orders WHERE tenant_id = " + TENANT_ID
                     + " AND customer_phone = '" + phone + "'")) {
            rs.next();
            return rs.getInt(1);
        }
    }

    private static String landedAmount(String phone) throws SQLException {
        try (Connection conn = dataSource.getConnection();
             Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery("SELECT COALESCE(SUM(total_amount), 0) FROM orders WHERE tenant_id = "
                     + TENANT_ID + " AND customer_phone = '" + phone + "'")) {
            rs.next();
            return rs.getBigDecimal(1).toPlainString();
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