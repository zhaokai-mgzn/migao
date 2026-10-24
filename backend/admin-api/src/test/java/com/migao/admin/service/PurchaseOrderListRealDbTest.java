// case_ids: OPS-001
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.MybatisSqlSessionFactoryBuilder;
import com.baomidou.mybatisplus.extension.plugins.MybatisPlusInterceptor;
import com.baomidou.mybatisplus.extension.plugins.handler.TenantLineHandler;
import com.baomidou.mybatisplus.extension.plugins.inner.TenantLineInnerInterceptor;
import com.migao.admin.entity.PurchaseOrder;
import com.migao.admin.mapper.InboundOrderMapper;
import com.migao.admin.mapper.ProductMapper;
import com.migao.admin.mapper.ProductSkuMapper;
import com.migao.admin.mapper.PurchaseOrderItemMapper;
import com.migao.admin.mapper.PurchaseOrderMapper;
import com.migao.admin.mapper.PurchaseOrderReceiptMapper;
import com.migao.admin.mapper.SupplierMapper;
import com.migao.admin.time.BusinessClock;
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
import java.math.BigDecimal;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.sql.Connection;
import java.sql.Statement;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 采购单列表/详情的**真库**判据（issue #7373 复盘：云上「采购单加载失败」自查）。
 *
 * <h3>为什么必须真库</h3>
 * <p>云上页面报「采购单加载失败」，而单元测试全绿 —— 因为单元测试把 Mapper 全 mock 掉了：
 * **实体字段 ↔ 建库列**、**时间类型 ↔ JDBC**、**RLS/角色**这些只在真库上才现形。
 * 本判据用与生产同源的建库脚本 + 多租户拦截器，真跑 `list()` / `detail()`，
 * 让「代码与库不一致」这类故障在合并前就红，而不是等云端页面白屏。</p>
 *
 * <h3>它证明什么 / 不证明什么</h3>
 * <ul>
 *   <li>✅ 证明：在**终态建库脚本**上，采购单读面能跑通（实体列对得上、类型可映射、查询不炸）。</li>
 *   <li>❌ 不证明：云端**那个库**真的跑过 V175（缺表只能靠 `/api/admin/system/schema-probe` 现查）。</li>
 * </ul>
 */
@DisplayName("真库：采购单 list/detail 在终态建库脚本上可跑通")
class PurchaseOrderListRealDbTest {

    private static final Long TENANT_ID = 73730L;

    private static PgCluster cluster;
    private static SqlSession session;
    private static PurchaseOrderService service;

    @BeforeAll
    static void startRealPostgresAndFixtures() throws Exception {
        cluster = PgCluster.startOrAbort();
        DataSource dataSource = cluster.dataSource();
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute(schemaSql());
            st.execute("INSERT INTO tenants (id, name, code) OVERRIDING SYSTEM VALUE VALUES ("
                    + TENANT_ID + ", 'acc-7373', 'acc-7373')");
            st.execute("INSERT INTO suppliers (id, tenant_id, name, contact_name, contact_phone, status)"
                    + " VALUES ('SUP-7373', " + TENANT_ID + ", '绍兴布行', '王经理', '13800000001', 'active')");
            st.execute("INSERT INTO purchase_orders (id, tenant_id, po_no, supplier_id, order_date,"
                    + " expected_date, status, total_amount)"
                    + " VALUES ('PO-7373', " + TENANT_ID + ", 'CG-20261021-0001', 'SUP-7373',"
                    + " DATE '2026-10-20', DATE '2026-10-25', 'ordered', 1200.0000)");
            st.execute("INSERT INTO purchase_order_items (id, tenant_id, purchase_order_id, line_no,"
                    + " product_id, sku_id, quantity, unit_price, amount)"
                    + " VALUES ('POI-7373', " + TENANT_ID + ", 'PO-7373', 1, NULL, 'SKU-7373',"
                    + " 100.0000, 12.0000, 1200.0000)");
        }

        MybatisConfiguration configuration = new MybatisConfiguration();
        configuration.setMapUnderscoreToCamelCase(true);
        configuration.setEnvironment(new Environment("acc-7373", new JdbcTransactionFactory(), dataSource));
        // 多租户拦截器必须在场（生产装配同源）：少了它 = 只测了 mapper 原文
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
        for (Class<?> mapper : List.of(PurchaseOrderMapper.class, PurchaseOrderItemMapper.class,
                PurchaseOrderReceiptMapper.class, SupplierMapper.class, InboundOrderMapper.class,
                // issue #7567：读面补展示名（按 skuId 反查规格 / 商品）⇒ 这两张表的 mapper 也必须在场
                ProductSkuMapper.class, ProductMapper.class)) {
            configuration.addMapper(mapper);
        }
        SqlSessionFactory factory = new MybatisSqlSessionFactoryBuilder().build(configuration);
        session = factory.openSession(true);
        service = new PurchaseOrderService(
                session.getMapper(PurchaseOrderMapper.class),
                session.getMapper(PurchaseOrderItemMapper.class),
                session.getMapper(PurchaseOrderReceiptMapper.class),
                session.getMapper(SupplierMapper.class),
                session.getMapper(InboundOrderMapper.class),
                session.getMapper(ProductSkuMapper.class),
                session.getMapper(ProductMapper.class),
                new BusinessClock());
    }

    @AfterAll
    static void tearDown() {
        if (session != null) {
            session.close();
        }
        if (cluster != null) {
            cluster.stop();
        }
    }

    @Test
    @DisplayName("🔴 列表：读得出来，且带出供应商名与收货进度（云上白屏的那条路径）")
    void listWorksOnRealSchema() {
        List<com.migao.admin.dto.PurchaseOrderView> rows = service.list(TENANT_ID, null, null);

        assertThat(rows).as("真库上必须读得出采购单（读不出 = 云上就是这条路径 500）").hasSize(1);
        var view = rows.get(0);
        assertThat(view.poNo()).isEqualTo("CG-20261021-0001");
        assertThat(view.status()).isEqualTo("ordered");
        assertThat(view.totalAmount()).isEqualByComparingTo(new BigDecimal("1200"));
        assertThat(view.items()).as("逐行已收/未收是采购单页面的核心列").hasSize(1);
        assertThat(view.items().get(0).receivedQuantity()).isEqualByComparingTo(BigDecimal.ZERO);
        assertThat(view.items().get(0).remainingQuantity()).isEqualByComparingTo("100");
    }

    @Test
    @DisplayName("详情：单张读面同源（含收货记录列表为空而不是 null）")
    void detailWorksOnRealSchema() {
        var view = service.detail("PO-7373", TENANT_ID);

        assertThat(view.receipts()).as("没有收货记录 ⇒ 空列表（页面据此渲染「未收货」）").isNotNull().isEmpty();
    }

    @Test
    @DisplayName("按状态过滤：'closed' 不该把 'ordered' 带出来（过滤条件真进了 SQL）")
    void statusFilterApplies() {
        assertThat(service.list(TENANT_ID, "closed", null)).isEmpty();
        assertThat(service.list(TENANT_ID, "ordered", null)).hasSize(1);
    }

    /** 终态建库脚本（不手抄列清单：库改了这里自动跟上）。 */
    private static String schemaSql() throws Exception {
        Path root = Paths.get(System.getProperty("user.dir")).toAbsolutePath();
        Path candidate = root.resolve("src/main/resources/db/init/schema.sql");
        if (!Files.exists(candidate)) {
            candidate = root.resolve("backend/admin-api/src/main/resources/db/init/schema.sql");
        }
        assertThat(candidate).as("建库脚本必须存在（否则本判据在测空气）").exists();
        return Files.readString(candidate);
    }
}
