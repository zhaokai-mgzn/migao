// case_ids: PR-010, PR-021
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
 * 🔴 <b>真库判据：改品时「请求没声明的维度」一行都不许删（issue #5515）</b>。
 *
 * <h2>病灶（机制链，逐字照抄 issue #5515）</h2>
 * <ol>
 *   <li>{@code ProductService.updateProduct} 对「请求里没带的 color」执行 <b>pruneMissing 删色</b>
 *       （{@code colorInputs == null} ⇒ {@code keptColorIds} 为空 ⇒ 既有颜色<b>全部</b>被物理删除）；</li>
 *   <li>而 {@code product_skus.color_id} 是 {@code REFERENCES product_colors(id) ON DELETE CASCADE}
 *       （见 {@code backend/admin-api/src/main/resources/db/init/schema.sql} 的建表语句）；</li>
 *   <li>⇒ 调用方<b>只传 skus、不传 colors</b>（「只改 SKU、不动颜色」= 改价 / 改库存）时，
 *       颜色被删 ⇒ 其下 SKU 行被<b>数据库级联删除</b>（无声、无提示）。</li>
 * </ol>
 *
 * <h2>为什么必须真库（mock 面结构上不可见）</h2>
 * 本判据要证的是「<b>真的有一行从 {@code product_skus} 里消失了</b>」，而这条链上三件事只在真库上发生：
 * <ol>
 *   <li><b>级联是数据库行为</b>：{@code productColorMapper.deleteById(...)} 在 mock 面只证明
 *       「调了 deleteById」；{@code ON DELETE CASCADE} 是 PG 干的，mock 永远看不见；</li>
 *   <li><b>删除是物理删除</b>：{@code product_colors} / {@code product_skus} <b>没有</b>
 *       {@code deleted} 列，也没有 {@code @TableLogic} ⇒ {@code deleteById} 是真 {@code DELETE}；</li>
 *   <li><b>外键真的建起来了</b>：建表取自 bootstrap 终态 schema（不手抄列清单）⇒ 级联在真表上生效。</li>
 * </ol>
 *
 * <h2>口径（本单选定 ①，见 PR body 「口径选择与调用方影响」）</h2>
 * <b>「prune 只删本次请求**声明过的维度**」</b>——未声明（null）≠ 声明为空（[]）：
 * <ul>
 *   <li><b>颜色维度</b>：请求<b>显式声明了 colors</b>（哪怕 {@code []}）才允许删色；未声明 ⇒ 一行不删；</li>
 *   <li><b>SKU 维度</b>：SKU 行是矩阵（颜色 × 门幅）的<b>成员</b> ⇒ 只有请求<b>声明了矩阵</b>
 *       （{@code colors} 非 null）<b>且本次真的给出了 SKU 集合</b>（显式 {@code skus}，或由
 *       {@code colors × doorWidths} 派生）才做「缺失即删」；只点名若干 SKU 行（改价 / 改库存）
 *       ⇒ 集合没给全 ⇒ 一行不删；</li>
 *   <li><b>显式声明（含空数组）</b>⇒ 该维度的提交集合即全集、缺失即删（既有语义逐字不变）。</li>
 * </ul>
 *
 * <h2>判据（每条都能单独变红）</h2>
 * <ol>
 *   <li><b>判据1·只带 skus（点名单条 = 改价/改库存 的真实形态）⇒ SKU 行数不变</b>（本单主判据）：
 *       改前 = <b>0</b>（颜色被删 ⇒ 级联带走全部 SKU）。注入红证：把 prune 的声明检查去掉 ⇒ 红；</li>
 *   <li><b>判据1b·只带 skus 且给全（两条都给）⇒ 同样一行不删</b>：改前 = 0；</li>
 *   <li><b>判据2·显式声明 colors ⇒ 既有删色能力不回归</b>：显式只留 A ⇒ B 的颜色行与其 SKU 消失、
 *       A 的 SKU 主键保留（断链防护）；</li>
 *   <li><b>判据3·口径判别式：显式空数组 ≠ 未声明</b>：{@code colors: []} 是「明确声明没有颜色了」
 *       ⇒ 删色照旧生效。<b>两条口径（null 与 []）在这一格上分道扬镳</b>——把 [] 也当成「未声明」
 *       会让本判据红；</li>
 *   <li><b>判据4·类级：没声明 colors、也没给出 SKU 集合的改品请求 ⇒ 两个维度都不许删</b>
 *       （Agent 侧真实可达：{@code AgentProductUpdateRequest} <b>没有 skus 字段</b>，只声明
 *       {@code sellingMethods} / {@code doorWidths} 时，改前会把颜色与 SKU 双双删光）。</li>
 * </ol>
 *
 * <p>缺 PG 二进制 ⇒ {@link PgCluster#startOrAbort()}：CI（{@code MIGAO_REQUIRE_REALDB=1}）⇒ 判红；
 * 本机未设该标记 ⇒ 显式 skip（「没跑」长得像「没跑」，不是通过）。</p>
 */
@DisplayName("改品 prune 射程：未声明的维度一行都不许删（issue #5515，真库）")
class ProductUpdatePruneScopeRealDbTest {

    private static final Long TENANT_ID = 1L;
    private static final String DOOR_WIDTH = "2.8米";
    private static final String COLOR_A = "2699-01";
    private static final String COLOR_B = "2699-02";

    private static PgCluster cluster;
    private static DataSource dataSource;
    private static SqlSessionFactory factory;
    private static SqlSession session;
    /** 真实 ProductService：prune 逻辑不许被 mock 顶替（否则断言的是「某个方法被调过」） */
    private static ProductService productService;

    @BeforeAll
    static void startRealPostgresAndFixtures() throws Exception {
        cluster = PgCluster.startOrAbort();
        dataSource = cluster.dataSource();
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            // bootstrap 终态 schema（含 product_skus.color_id 的 ON DELETE CASCADE）；租户 1 = 种子里有
            st.execute(schemaSql());
        }
        MybatisConfiguration configuration = new MybatisConfiguration();
        configuration.setMapUnderscoreToCamelCase(true);
        // 读数要「改完再查」拿到新值（turns 一级缓存必须 STATEMENT 级）
        configuration.setLocalCacheScope(LocalCacheScope.STATEMENT);
        configuration.setEnvironment(new Environment("acc-5515", new JdbcTransactionFactory(), dataSource));
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
                stockLedgerService);
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

    // ══════════════════════════════════ 判据 1：只带 skus ⇒ SKU 行数不变（本单主判据）

    @Test
    @DisplayName("判据1·只带 skus（点名单条 = 改价/改库存 的真实形态）、不带 colors ⇒ SKU 行数不变（改前 2 → 0）")
    void skusOnlyUpdateKeepsSkuRows() throws Exception {
        String productId = createTwoColorProduct("SG-5515-A", "30");
        long skuA = skuIdOf(productId, COLOR_A);
        long skuB = skuIdOf(productId, COLOR_B);
        assertThat(skuRowCount(productId)).as("夹具前提：2 色 × 1 门幅 ⇒ 2 条 SKU 行").isEqualTo(2);
        System.out.println("[#5515 判据1] 改前 SKU 行 = " + skuRowsOf(productId)
                + "，颜色行数 = " + colorRowCount(productId));

        // When：改价 + 改库存 —— **只带 skus（且只点名被改的那一条）、不带 colors**
        updateSkusOnly(productId, skuA, "179.00", "12.5");

        System.out.println("[#5515 判据1] 改后 SKU 行 = " + skuRowsOf(productId)
                + "，颜色行数 = " + colorRowCount(productId));
        assertThat(skuRowCount(productId))
                .as("只带 skus 的改品请求不得删掉任何 SKU 行（改前 = 0：pruneMissing 删色 ⇒ "
                        + "product_skus.color_id ON DELETE CASCADE ⇒ 该商品 SKU 行被级联删光）")
                .isEqualTo(2);
        assertThat(colorRowCount(productId))
                .as("口径①：请求**未声明** colors ⇒ 颜色一行都不许删（改前 = 0）")
                .isEqualTo(2);
        assertThat(stockOf(skuA)).as("该 SKU 的库存必须真的改掉（判据不是「什么都没发生」）")
                .isEqualByComparingTo("12.5");
        assertThat(priceOf(skuA)).as("该 SKU 的价必须真的改掉").isEqualByComparingTo("179.00");
        assertThat(stockOf(skuB)).as("未被本次请求点名的 SKU 行必须原样保留（库存不变）")
                .isEqualByComparingTo("30");
    }

    @Test
    @DisplayName("判据1b·只带 skus 且两条都给（集合给全但没声明 colors）⇒ 同样一行不删（改前 2 → 0）")
    void skusOnlyFullSetUpdateKeepsSkuRows() throws Exception {
        String productId = createTwoColorProduct("SG-5515-A2", "30");
        long skuA = skuIdOf(productId, COLOR_A);
        long skuB = skuIdOf(productId, COLOR_B);

        // When：只带 skus（两条都给，改库存）、不带 colors
        ProductUpdateRequest request = new ProductUpdateRequest();
        request.setSkus(List.of(skuInput(skuA, COLOR_A, "11"), skuInput(skuB, COLOR_B, "22")));
        productService.updateProduct(productId, request, TENANT_ID);

        System.out.println("[#5515 判据1b] 改后 SKU 行 = " + skuRowsOf(productId)
                + "，颜色行数 = " + colorRowCount(productId));
        assertThat(skuRowCount(productId))
                .as("未声明 colors ⇒ 矩阵未被声明 ⇒ 只做逐行 upsert，不删任何 SKU 行（改前 = 0）")
                .isEqualTo(2);
        assertThat(colorRowCount(productId)).as("未声明 colors ⇒ 颜色一行都不许删（改前 = 0）").isEqualTo(2);
        assertThat(stockOf(skuA)).isEqualByComparingTo("11");
        assertThat(stockOf(skuB)).isEqualByComparingTo("22");
    }

    // ══════════════════════════════════ 判据 2：显式声明 colors ⇒ 删色能力不回归

    @Test
    @DisplayName("判据2·显式声明 colors（缺席者 = 删色意图）⇒ 既有删色能力未被破坏（不回归）")
    void explicitColorsStillPrune() throws Exception {
        String productId = createTwoColorProduct("SG-5515-B", "30");
        long skuA = skuIdOf(productId, COLOR_A);
        long colorA = colorIdOf(productId, COLOR_A);
        assertThat(colorRowCount(productId)).as("夹具前提：2 条颜色行").isEqualTo(2);

        // When：显式声明 colors = [A]（B 缺席 = 明确的删色意图），只留 A 的 SKU
        updateWithColors(productId, List.of(colorInputWithId(colorA, COLOR_A)),
                List.of(skuInput(skuA, COLOR_A, "20")));

        System.out.println("[#5515 判据2] 改后 SKU 行 = " + skuRowsOf(productId)
                + "，颜色行数 = " + colorRowCount(productId) + "，颜色 = " + colorNamesOf(productId));
        assertThat(colorNamesOf(productId)).as("显式声明 colors=[A] ⇒ B 必须被删（既有删色能力不回归）")
                .containsExactly(COLOR_A);
        assertThat(skuRowCount(productId)).as("B 的 SKU 随 B 的颜色行级联消失，A 的 SKU 保留")
                .isEqualTo(1);
        assertThat(skuIdOf(productId, COLOR_A)).as("A 的 SKU 主键必须保留（断链防护：订单里存的旧 skuId 仍可寻址）")
                .isEqualTo(skuA);
    }

    // ══════════════════════════════════ 判据 3：口径判别式 —— 显式空数组 ≠ 未声明

    @Test
    @DisplayName("判据3·显式 colors: [] = 「明确声明没有颜色了」⇒ 删色照旧生效（与判据1 的未声明分道扬镳）")
    void explicitEmptyColorsStillPrune() throws Exception {
        String productId = createTwoColorProduct("SG-5515-C", "30");
        long skuA = skuIdOf(productId, COLOR_A);

        // When：显式空数组（= 声明「颜色集合为空」），而不是「没提颜色这回事」
        updateWithColors(productId, List.of(), List.of(skuInput(skuA, COLOR_A, "20")));

        System.out.println("[#5515 判据3] 改后颜色行数 = " + colorRowCount(productId)
                + "，SKU 行数 = " + skuRowCount(productId));
        assertThat(colorRowCount(productId))
                .as("口径① 的判别式：显式空数组是**声明**，不是「未声明」⇒ 删色照旧生效")
                .isZero();
        assertThat(skuRowCount(productId))
                .as("显式删光颜色 ⇒ 其下 SKU 随 ON DELETE CASCADE 消失（正是本单禁止它在「未声明」时发生的原因）")
                .isZero();
    }

    // ══════════════════════════════════ 判据 4：类级 —— 没声明 colors、也没有 SKU 集合

    @Test
    @DisplayName("判据4·只声明 sellingMethods（Agent 侧可达：该 DTO 没有 skus 字段）⇒ 两个维度都不许删")
    void undeclaredDimensionsAreNeverPruned() throws Exception {
        String productId = createTwoColorProduct("SG-5515-D", "30");
        assertThat(skuRowCount(productId)).as("夹具前提：2 条 SKU 行").isEqualTo(2);

        // When：请求既没声明 colors，也没给出 SKU 集合（只有售卖方式）
        ProductUpdateRequest request = new ProductUpdateRequest();
        request.setSellingMethods(List.of("bulk_cut"));
        productService.updateProduct(productId, request, TENANT_ID);

        System.out.println("[#5515 判据4] 改后 SKU 行 = " + skuRowsOf(productId)
                + "，颜色行数 = " + colorRowCount(productId));
        assertThat(skuRowCount(productId))
                .as("未给出 SKU 集合 ⇒ SKU 一行都不许删（改前 = 0：skuInputs 为 null ⇒ keptSkuIds 为空 ⇒ 全删）")
                .isEqualTo(2);
        assertThat(colorRowCount(productId))
                .as("未声明 colors ⇒ 颜色一行都不许删（改前 = 0）")
                .isEqualTo(2);
    }

    // ══════════════════════════════════ 夹具与读数

    /** 建品（表单路径：2 色 × 1 门幅 ⇒ SKU 由笛卡尔积生成，与商家在商品页建档同一条路径）。 */
    private static String createTwoColorProduct(String skuCode, String stock) {
        ProductCreateRequest request = new ProductCreateRequest();
        request.setName("SG-5515 测试商品 " + skuCode);
        request.setSkuCode(skuCode);
        request.setStatus("draft");
        request.setBasePrice(new BigDecimal("168"));
        request.setStock(new BigDecimal(stock));
        request.setColors(List.of(colorInput(COLOR_A), colorInput(COLOR_B)));
        request.setDoorWidths(List.of(DOOR_WIDTH));
        return productService.createProduct(request, TENANT_ID).getId();
    }

    /** 改品（病根形态：**只带 skus、不带 colors** —— 改价 / 改库存）。 */
    private static void updateSkusOnly(String productId, long skuId, String price, String stock) {
        ProductUpdateRequest request = new ProductUpdateRequest();
        ProductSkuInput sku = skuInput(skuId, COLOR_A, stock);
        sku.setPrice(new BigDecimal(price));
        request.setSkus(List.of(sku));
        request.setBasePrice(new BigDecimal(price));
        productService.updateProduct(productId, request, TENANT_ID);
    }

    /** 改品（显式声明 colors —— 表单与 Agent 的既有形态）。 */
    private static void updateWithColors(String productId, List<ProductColorInput> colors,
                                         List<ProductSkuInput> skus) {
        ProductUpdateRequest request = new ProductUpdateRequest();
        request.setColors(colors);
        request.setSkus(skus);
        request.setDoorWidths(List.of(DOOR_WIDTH));
        productService.updateProduct(productId, request, TENANT_ID);
    }

    private static ProductColorInput colorInput(String colorName) {
        ProductColorInput color = new ProductColorInput();
        color.setColorName(colorName);
        return color;
    }

    private static ProductColorInput colorInputWithId(Long colorId, String colorName) {
        ProductColorInput color = colorInput(colorName);
        color.setId(colorId);
        return color;
    }

    private static ProductSkuInput skuInput(Long skuId, String colorName, String stock) {
        ProductSkuInput sku = new ProductSkuInput();
        sku.setId(skuId);
        sku.setColorName(colorName);
        sku.setDoorWidth(DOOR_WIDTH);
        sku.setPrice(new BigDecimal("168"));
        sku.setStock(new BigDecimal(stock));
        return sku;
    }

    /** 该商品的全部 SKU 行（id / 颜色 / 门幅 / 价 / 库存）—— 红证与排障都靠它定位。 */
    private static List<String> skuRowsOf(String productId) throws SQLException {
        List<String> rows = new ArrayList<>();
        try (Connection conn = dataSource.getConnection();
             PreparedStatement ps = conn.prepareStatement(
                     "SELECT id, color_id, color_name, door_width, price, stock FROM product_skus"
                             + " WHERE product_id = ? AND tenant_id = ? ORDER BY id")) {
            ps.setString(1, productId);
            ps.setLong(2, TENANT_ID);
            try (ResultSet rs = ps.executeQuery()) {
                while (rs.next()) {
                    rows.add("id=" + rs.getLong(1) + "|colorId=" + rs.getObject(2)
                            + "|colorName=" + rs.getString(3) + "|doorWidth=" + rs.getString(4)
                            + "|price=" + rs.getBigDecimal(5) + "|stock=" + rs.getBigDecimal(6));
                }
            }
        }
        return rows;
    }

    private static List<String> colorNamesOf(String productId) throws SQLException {
        List<String> names = new ArrayList<>();
        try (Connection conn = dataSource.getConnection();
             PreparedStatement ps = conn.prepareStatement(
                     "SELECT color_name FROM product_colors WHERE product_id = ? AND tenant_id = ?"
                             + " ORDER BY color_name")) {
            ps.setString(1, productId);
            ps.setLong(2, TENANT_ID);
            try (ResultSet rs = ps.executeQuery()) {
                while (rs.next()) {
                    names.add(rs.getString(1));
                }
            }
        }
        return names;
    }

    private static int skuRowCount(String productId) throws SQLException {
        return countOf("SELECT COUNT(*) FROM product_skus WHERE product_id = ? AND tenant_id = ?",
                productId, TENANT_ID);
    }

    private static int colorRowCount(String productId) throws SQLException {
        return countOf("SELECT COUNT(*) FROM product_colors WHERE product_id = ? AND tenant_id = ?",
                productId, TENANT_ID);
    }

    private static long skuIdOf(String productId, String colorName) throws SQLException {
        List<Long> ids = longsOf("SELECT id FROM product_skus WHERE product_id = ? AND tenant_id = ?"
                + " AND color_name = ? ORDER BY id", productId, TENANT_ID, colorName);
        assertThat(ids).as("夹具前提：颜色 %s 下恰有一条 SKU 行", colorName).hasSize(1);
        return ids.get(0);
    }

    private static long colorIdOf(String productId, String colorName) throws SQLException {
        List<Long> ids = longsOf("SELECT id FROM product_colors WHERE product_id = ? AND tenant_id = ?"
                + " AND color_name = ? ORDER BY id", productId, TENANT_ID, colorName);
        assertThat(ids).as("夹具前提：颜色 %s 恰有一行", colorName).hasSize(1);
        return ids.get(0);
    }

    private static BigDecimal stockOf(long skuId) throws SQLException {
        List<BigDecimal> values = decimalsOf("SELECT stock FROM product_skus WHERE id = ? AND tenant_id = ?",
                skuId, TENANT_ID);
        assertThat(values).as("SKU %s 必须只有一行", skuId).hasSize(1);
        return values.get(0);
    }

    private static BigDecimal priceOf(long skuId) throws SQLException {
        List<BigDecimal> values = decimalsOf("SELECT price FROM product_skus WHERE id = ? AND tenant_id = ?",
                skuId, TENANT_ID);
        assertThat(values).as("SKU %s 必须只有一行", skuId).hasSize(1);
        return values.get(0);
    }

    private static int countOf(String sql, Object... args) throws SQLException {
        List<Long> values = longsOf(sql, args);
        assertThat(values).as("COUNT 查询必须恰好返回一行：%s", sql).hasSize(1);
        return values.get(0).intValue();
    }

    private static List<Long> longsOf(String sql, Object... args) throws SQLException {
        List<Long> values = new ArrayList<>();
        try (Connection conn = dataSource.getConnection(); PreparedStatement ps = conn.prepareStatement(sql)) {
            bind(ps, args);
            try (ResultSet rs = ps.executeQuery()) {
                while (rs.next()) {
                    values.add(rs.getLong(1));
                }
            }
        }
        return values;
    }

    private static List<BigDecimal> decimalsOf(String sql, Object... args) throws SQLException {
        List<BigDecimal> values = new ArrayList<>();
        try (Connection conn = dataSource.getConnection(); PreparedStatement ps = conn.prepareStatement(sql)) {
            bind(ps, args);
            try (ResultSet rs = ps.executeQuery()) {
                while (rs.next()) {
                    values.add(rs.getBigDecimal(1));
                }
            }
        }
        return values;
    }

    private static void bind(PreparedStatement ps, Object[] args) throws SQLException {
        for (int i = 0; i < args.length; i++) {
            if (args[i] instanceof Long l) {
                ps.setLong(i + 1, l);
            } else if (args[i] instanceof Integer n) {
                ps.setInt(i + 1, n);
            } else {
                ps.setString(i + 1, String.valueOf(args[i]));
            }
        }
    }

    /** 终态 schema（不手抄列清单）：bootstrap 路径的真值源，含 {@code product_skus.color_id} 的级联外键。 */
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