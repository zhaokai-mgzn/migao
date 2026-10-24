// case_ids: PR-005
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.MybatisSqlSessionFactoryBuilder;
import com.baomidou.mybatisplus.extension.plugins.MybatisPlusInterceptor;
import com.baomidou.mybatisplus.extension.plugins.handler.TenantLineHandler;
import com.baomidou.mybatisplus.extension.plugins.inner.TenantLineInnerInterceptor;
import com.migao.admin.dto.ProductColorInput;
import com.migao.admin.dto.ProductCreateRequest;
import com.migao.admin.dto.ProductSkuInput;
import com.migao.admin.dto.ProductUpdateRequest;
import com.migao.admin.mapper.CategoryMapper;
import com.migao.admin.mapper.ProductAttributeMapper;
import com.migao.admin.mapper.ProductColorMapper;
import com.migao.admin.mapper.ProductMapper;
import com.migao.admin.mapper.ProductSkuMapper;
import com.migao.admin.mapper.StockLedgerMapper;
import net.sf.jsqlparser.expression.Expression;
import net.sf.jsqlparser.expression.LongValue;
import org.apache.ibatis.mapping.Environment;
import org.apache.ibatis.session.LocalCacheScope;
import org.apache.ibatis.session.SqlSession;
import org.apache.ibatis.session.SqlSessionFactory;
import org.apache.ibatis.transaction.jdbc.JdbcTransactionFactory;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import javax.sql.DataSource;
import java.io.IOException;
import java.math.BigDecimal;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.ArrayList;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 🔴 <b>真库判据：建品/改品直写 SKU 库存**必须落账**（issue #4157）</b>。
 *
 * <h2>病灶（issue #4137 全量 grep 的如实上报）</h2>
 * SKU 级 {@code stock} 的写入方共 4 处，其中 <b>第三条路径</b>
 * （{@code ProductService.saveColorsAndSkus} —— 建品/改品直接 upsert {@code product_skus.stock}）
 * <b>不落台账</b>：全类唯一的 {@code stockLedgerService.record} 在 {@code adjustStockForAgent}（手工调整）。
 * 后果：①「某 SKU 的库存为什么从 X 变成 Y」在这条路径上答不出；② 台账链在「新 SKU 首次库存」处
 * <b>断头</b>（首行没有前驱）。
 *
 * <h2>为什么必须真库</h2>
 * 本判据要证的是「<b>一行真的进了 {@code stock_ledger_entries}</b>」，而这条链上三件事在 mock 面
 * <b>结构上不可见</b>：
 * <ol>
 *   <li><b>{@code reason} 真的过得了 DB 约束</b>：表上有
 *       {@code ck_stock_ledger_reason CHECK (reason IN ('order','aftersales','manual','inbound'))}
 *       —— 复用既有 {@code manual} 之外自造一个 reason，只有在真库上才会当场被拒（SQLSTATE 23514），
 *       mock 面永远绿；</li>
 *   <li><b>列真的写对</b>：{@code before_qty}/{@code after_qty}/{@code delta} 是 {@code NUMERIC(12,1)}
 *       （V115）—— 小数场景（12.5）在 mock 面只证明「传了个 BigDecimal」；</li>
 *   <li><b>建品路径真的走通</b>：{@code createProduct} 要经真实 UUID/雪花主键分配
 *       （{@code IdType.ASSIGN_UUID} / {@code ASSIGN_ID}）才拿得到新 SKU 主键去落账行。</li>
 * </ol>
 *
 * <h2>裁定（用户 2026-09-25，见 #5496 建议①）</h2>
 * 新 SKU 首行按「<b>补一条基线行</b>」处理（不是「首行无前驱」）：与既有「历史不回填」口径一致
 * —— 存量不追补，但<b>新发生的变更必须落账</b> ⇒ 链条从 0 起算、首行有前驱。
 *
 * <h2>判据（每条都能单独变红）</h2>
 * <ol>
 *   <li><b>判据1·建品 ⇒ 基线行</b>：新 SKU 首行 {@code before=0 → after=初值}、
 *       {@code delta=初值}、{@code reason='manual'}。<b>注入红证</b>：摘掉
 *       {@code saveColorsAndSkus} 里的基线行循环 ⇒ 本判据红（行数 0）；</li>
 *   <li><b>判据2·改品 ⇒ 变更行且与首行首尾相接</b>：第二次变更 {@code before == 首行 after}、
 *       {@code after=12.5}、{@code delta=-17.5}。<b>注入红证</b>：摘掉快照比对落账 ⇒ 本判据红；</li>
 *   <li><b>判据3·重复提交同一库存 ⇒ 不增行</b>（幂等）且台账里<b>没有 delta=0 的噪声行</b>
 *       —— 重复调用不会重复落账。</li>
 * </ol>
 *
 * <p>缺 PG 二进制 ⇒ {@link PgCluster#startOrAbort()}：CI（{@code MIGAO_REQUIRE_REALDB=1}）⇒ 判红；
 * 本机未设该标记 ⇒ 显式 skip（「没跑」长得像「没跑」，不是通过）。</p>
 */
@DisplayName("库存台账第三条路径：建品/改品直写 SKU 库存必须落账（issue #4157，真库）")
class ProductStockLedgerRealDbTest {

    private static final Long TENANT_ID = 1L;
    private static final String DOOR_WIDTH = "2.8米";
    private static final String COLOR_NAME = "2699-01";

    private static PgCluster cluster;
    private static DataSource dataSource;
    private static SqlSessionFactory factory;
    private static SqlSession session;
    /** 真实 ProductService：落账逻辑不许被 mock 顶替（否则断言的是「某个方法被调过」） */
    private static ProductService productService;

    @BeforeAll
    static void startRealPostgresAndFixtures() throws Exception {
        cluster = PgCluster.startOrAbort();
        dataSource = cluster.dataSource();
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            // bootstrap 终态 schema（含 ck_stock_ledger_reason 约束）；租户 1 = schema 自带种子行
            st.execute(schemaSql());
        }
        MybatisConfiguration configuration = new MybatisConfiguration();
        configuration.setMapUnderscoreToCamelCase(true);
        // 红证要用裸 JDBC 改库（绕过 session）⇒ 一级缓存必须是 STATEMENT 级，否则「改完再查」拿旧值
        configuration.setLocalCacheScope(LocalCacheScope.STATEMENT);
        configuration.setEnvironment(new Environment("acc-4157", new JdbcTransactionFactory(), dataSource));
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
        for (Class<?> mapper : List.of(ProductMapper.class, ProductColorMapper.class, ProductSkuMapper.class,
                ProductAttributeMapper.class, CategoryMapper.class, StockLedgerMapper.class)) {
            configuration.addMapper(mapper);
        }
        factory = new MybatisSqlSessionFactoryBuilder().build(configuration);
        session = factory.openSession(true);
        StockLedgerService stockLedgerService = new StockLedgerService(
                session.getMapper(StockLedgerMapper.class), session.getMapper(ProductSkuMapper.class));
        productService = new ProductService(session.getMapper(ProductMapper.class),
                session.getMapper(CategoryMapper.class), session.getMapper(ProductColorMapper.class),
                session.getMapper(ProductSkuMapper.class), session.getMapper(ProductAttributeMapper.class),
                stockLedgerService,
                // 幂等键（issue #6209）：本类走无键路径 ⇒ 不需要幂等存储
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

    // ══════════════════════════════════ 判据 1：建品不再建立库存（issue #7597）

    @Test
    @DisplayName("判据1·建品 ⇒ 不建立库存、不落基线行（历史口径「建档写 stock」已下线）")
    void createProductDoesNotEstablishStock() throws Exception {
        // 🔴 issue #7597（用户裁定 2026-10-24）：商品档案不再设置库存 ⇒ 建品请求里的 stock 被忽略，
        // 新 SKU 从 0 起算；库存只能由真实单据（入库单 / 订单 / 售后回补 / 批次盘点）产生。
        // 改前本判据断言的是反面（建品 stock=30 落一条基线行 0→30）—— 那是被下线的那条路径。
        String productId = createProduct("SG-4157-A", "30");
        long skuId = skuIdOf(productId);

        List<LedgerRow> rows = ledgerOf(skuId);
        System.out.println("[#7597 判据1] 建品后 SKU 行 = " + skuRowsOf(productId) + "，台账行 = " + rows);
        assertThat(stockOf(skuId))
                .as("建品请求里的库存必须被忽略（新商品从 0 起算）")
                .isEqualByComparingTo("0");
        assertThat(rows).as("建品不建立库存 ⇒ 不得落「初始库存基线行」（0 变更 = 噪声行）").isEmpty();
    }

    @Test
    @DisplayName("判据1b·库存由改品 stock 分支建立时首行 before=0（链条仍有前驱）")
    void firstStockChangeStartsFromZero() throws Exception {
        String productId = createProductWithSku("SG-4157-Z", "0");
        long skuId = skuIdOf(productId);

        List<LedgerRow> rows = ledgerOf(skuId);
        System.out.println("[#4157 判据1b] 建品后台账行 = " + rows + "，SKU 行 = " + skuRowsOf(productId));
        assertThat(rows).as("0 变更行会被误读成「动过库存」⇒ 不落行").isEmpty();
        assertThat(stockOf(skuId)).isEqualByComparingTo("0");

        // 第一次真实变更（批量库存调整 / Agent 调整走的 stock 分支）⇒ 首行 before 必须是 0
        updateStock(productId, "5");
        List<LedgerRow> afterEdit = ledgerOf(skuId);
        System.out.println("[#4157 判据1b] 首次变更后的台账行 = " + afterEdit);
        assertThat(afterEdit).as("首次库存变更必须落一行").hasSize(1);
        assertRow(afterEdit.get(0), "0", "5", "5");
    }

    // ══════════════════════════════════ 判据 2：改品 stock 分支 ⇒ 变更行 + 首尾相接

    @Test
    @DisplayName("判据2·改品 stock 分支 ⇒ 每次变更一条行，且 before == 上一行 after（链条不断）")
    void updateProductStockChainsLedgerRows() throws Exception {
        String productId = createProduct("SG-4157-B", "30");
        long skuId = skuIdOf(productId);

        updateStock(productId, "12.5");
        List<LedgerRow> rows = ledgerOf(skuId);
        System.out.println("[#4157 判据2] 首改后 SKU 行 = " + skuRowsOf(productId) + "，台账行 = " + rows);
        assertThat(rows).as("首次库存变更必须落一条行").hasSize(1);
        assertRow(rows.get(0), "0", "12.5", "12.5");

        updateStock(productId, "30");
        rows = ledgerOf(skuId);
        System.out.println("[#4157 判据2] 再改后台账行 = " + rows);
        assertThat(rows).hasSize(2);
        assertChain(rows);
        assertRow(rows.get(1), "12.5", "30", "17.5");
        assertThat(stockOf(skuId)).as("账实一致：台账 after 必须等于库里的实际库存")
                .isEqualByComparingTo("30");
    }

    // ══════════════════════════════════ 判据 3：重复提交同一库存 ⇒ 不增行（幂等）

    @Test
    @DisplayName("判据3·同一库存重复提交 ⇒ 台账不增行（重试 / 重复调用不重复落账）")
    void repeatedSaveWithSameStockAddsNoRow() throws Exception {
        String productId = createProduct("SG-4157-C", "30");
        long skuId = skuIdOf(productId);

        updateStock(productId, "12.5");
        int afterFirstEdit = ledgerOf(skuId).size();
        assertThat(afterFirstEdit).as("前置：首改确实落了行 —— 否则本判据是空断言").isEqualTo(1);

        updateStock(productId, "12.5");   // 同值重放
        updateStock(productId, "12.5");   // 再放一次
        List<LedgerRow> rows = ledgerOf(skuId);
        System.out.println("[#4157 判据3] 重复提交后的台账行 = " + rows + "（首改后行数 = " + afterFirstEdit + "）");

        assertThat(rows).as("同值重放不得落新行（写 0 变更行 = 台账里插假环）").hasSize(afterFirstEdit);
        assertThat(rows).as("台账里不许出现 delta=0 的噪声行")
                .noneMatch(row -> row.delta().compareTo(BigDecimal.ZERO) == 0);
        assertChain(rows);
        assertThat(stockOf(skuId)).isEqualByComparingTo("12.5");
    }

    // ══════════════════════════════════ 夹具与读数

    /** 建品（表单路径：只给颜色 + 门幅，SKU 由笛卡尔积生成 —— 与商家在商品页建档同一条路径）。 */
    private static String createProduct(String skuCode, String stock) {
        ProductCreateRequest request = new ProductCreateRequest();
        request.setName("SG-4157 测试商品 " + skuCode);
        request.setSkuCode(skuCode);
        request.setStatus("draft");
        request.setBasePrice(new BigDecimal("168"));
        request.setStock(new BigDecimal(stock));
        ProductColorInput color = new ProductColorInput();
        color.setColorName(COLOR_NAME);
        request.setColors(List.of(color));
        request.setDoorWidths(List.of(DOOR_WIDTH));
        return productService.createProduct(request, TENANT_ID).getId();
    }

    /** 建品（表单路径：显式 SKU 行 —— 库存值原样落库，不经「0/未填 ⇒ 默认 100」的生成分支）。 */
    private static String createProductWithSku(String skuCode, String stock) {
        ProductCreateRequest request = new ProductCreateRequest();
        request.setName("SG-4157 测试商品 " + skuCode);
        request.setSkuCode(skuCode);
        request.setStatus("draft");
        request.setBasePrice(new BigDecimal("168"));
        request.setStock(new BigDecimal(stock));
        request.setSkus(List.of(skuInput(null, stock)));
        return productService.createProduct(request, TENANT_ID).getId();
    }

    private static ProductSkuInput skuInput(Long skuId, String stock) {
        ProductSkuInput sku = new ProductSkuInput();
        sku.setId(skuId);
        sku.setColorName(COLOR_NAME);
        sku.setDoorWidth(DOOR_WIDTH);
        sku.setPrice(new BigDecimal("168"));
        sku.setStock(new BigDecimal(stock));
        return sku;
    }

    /**
     * 改品库存 = **商品级 stock 分支**（批量库存调整 `inventory_stock` / Agent 调整走的就是这条）。
     *
     * <p>issue #7597 后 SKU 入参里的 `stock` 已被忽略（商品档案不再设置库存），
     * 仍在射程内的绝对库存写面只剩这一条 ⇒ 本文件的落账判据挂在它上面。</p>
     */
    private static void updateStock(String productId, String stock) {
        ProductUpdateRequest request = new ProductUpdateRequest();
        request.setStock(new BigDecimal(stock));
        productService.updateProduct(productId, request, TENANT_ID);
    }

    private static ProductColorInput colorInput() {
        ProductColorInput color = new ProductColorInput();
        color.setColorName(COLOR_NAME);
        return color;
    }

    private record LedgerRow(BigDecimal before, BigDecimal after, BigDecimal delta, String reason, String note) {
    }

    /** 台账读数（真库直读，不走服务端读面 —— 判据要证的是「行真的进了库」）。 */
    private static List<LedgerRow> ledgerOf(long skuId) throws SQLException {
        List<LedgerRow> rows = new ArrayList<>();
        try (Connection conn = dataSource.getConnection();
             PreparedStatement ps = conn.prepareStatement(
                     "SELECT before_qty, after_qty, delta, reason, note FROM stock_ledger_entries"
                             + " WHERE sku_id = ? AND tenant_id = ? AND deleted = 0 ORDER BY id")) {
            ps.setLong(1, skuId);
            ps.setLong(2, TENANT_ID);
            try (ResultSet rs = ps.executeQuery()) {
                while (rs.next()) {
                    rows.add(new LedgerRow(rs.getBigDecimal(1), rs.getBigDecimal(2), rs.getBigDecimal(3),
                            rs.getString(4), rs.getString(5)));
                }
            }
        }
        return rows;
    }

    private static long skuIdOf(String productId) throws SQLException {
        try (Connection conn = dataSource.getConnection();
             PreparedStatement ps = conn.prepareStatement(
                     "SELECT id FROM product_skus WHERE product_id = ? ORDER BY id")) {
            ps.setString(1, productId);
            try (ResultSet rs = ps.executeQuery()) {
                assertThat(rs.next()).as("建品后该商品必须恰有一个 SKU（夹具前提）").isTrue();
                return rs.getLong(1);
            }
        }
    }

    /** 读数：该商品的全部 SKU 行（id / 颜色 / 门幅 / 库存）—— 红证与排障都靠它定位。 */
    private static List<String> skuRowsOf(String productId) throws SQLException {
        List<String> rows = new ArrayList<>();
        try (Connection conn = dataSource.getConnection();
             PreparedStatement ps = conn.prepareStatement(
                     "SELECT id, color_id, color_name, door_width, stock FROM product_skus"
                             + " WHERE product_id = ? ORDER BY id")) {
            ps.setString(1, productId);
            try (ResultSet rs = ps.executeQuery()) {
                while (rs.next()) {
                    rows.add("id=" + rs.getLong(1) + "|colorId=" + rs.getObject(2)
                            + "|colorName=" + rs.getString(3) + "|doorWidth=" + rs.getString(4)
                            + "|stock=" + rs.getBigDecimal(5));
                }
            }
        }
        return rows;
    }

    private static BigDecimal stockOf(long skuId) throws SQLException {
        try (Connection conn = dataSource.getConnection();
             PreparedStatement ps = conn.prepareStatement(
                     "SELECT stock FROM product_skus WHERE id = ?")) {
            ps.setLong(1, skuId);
            try (ResultSet rs = ps.executeQuery()) {
                assertThat(rs.next()).as("SKU 必须存在").isTrue();
                return rs.getBigDecimal(1);
            }
        }
    }

    /**
     * 行内自洽：{@code after - before == delta}（{@link BigDecimal} 比 scale ⇒ 一律
     * {@code isEqualByComparingTo}，不用 {@code equals}）。
     */
    private static void assertRow(LedgerRow row, String before, String after, String delta) {
        assertThat(row.before()).as("before_qty（row=%s）", row).isEqualByComparingTo(before);
        assertThat(row.after()).as("after_qty（row=%s）", row).isEqualByComparingTo(after);
        assertThat(row.delta()).as("delta（row=%s）", row).isEqualByComparingTo(delta);
        assertThat(row.after().subtract(row.before())).as("行内自洽 after-before==delta（row=%s）", row)
                .isEqualByComparingTo(row.delta());
        assertThat(row.reason()).as("台账行的来源（row=%s）", row).isEqualTo("manual");
    }

    /** 首尾相接：同一 SKU 相邻两行 {@code 上一行 after == 下一行 before}（可与上一行对账）。 */
    private static void assertChain(List<LedgerRow> rows) {
        for (int i = 1; i < rows.size(); i++) {
            assertThat(rows.get(i).before())
                    .as("第 %d 行 before 必须等于第 %d 行 after（断链 ⇒ 「库存为什么从 X 变成 Y」答不出）",
                            i + 1, i)
                    .isEqualByComparingTo(rows.get(i - 1).after());
        }
    }

    /** 终态 schema（不手抄列清单）：bootstrap 路径的真值源，含 {@code ck_stock_ledger_reason} 约束。 */
    private static String schemaSql() throws IOException {
        Path root = Paths.get(System.getProperty("user.dir")).toAbsolutePath();
        while (root != null && !Files.exists(root.resolve("backend/admin-api/src/main/resources/db/init/schema.sql"))) {
            root = root.getParent();
        }
        assertThat(root).as("必须能定位 backend/admin-api/src/main/resources/db/init/schema.sql"
                + "（真库建表取终态 schema，不手抄列清单）").isNotNull();
        return Files.readString(root.resolve("backend/admin-api/src/main/resources/db/init/schema.sql"));
    }
}