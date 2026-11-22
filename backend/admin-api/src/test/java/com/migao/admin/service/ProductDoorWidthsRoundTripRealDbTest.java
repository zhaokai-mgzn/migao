// case_ids: PR-017
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.MybatisSqlSessionFactoryBuilder;
import com.baomidou.mybatisplus.extension.plugins.MybatisPlusInterceptor;
import com.baomidou.mybatisplus.extension.plugins.handler.TenantLineHandler;
import com.baomidou.mybatisplus.extension.plugins.inner.TenantLineInnerInterceptor;
import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ProductColorInput;
import com.migao.admin.dto.ProductCreateRequest;
import com.migao.admin.dto.ProductResponse;
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
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.sql.Connection;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.ArrayList;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 🔴 <b>真库判据（issue #9005，P1）：门幅清单 {@code doorWidths} 建品 → 落库 → 回读逐字一致</b>。
 *
 * <h2>病灶（2026-11-22 生产全字段冒烟实测，tenant 1）</h2>
 * <ol>
 *   <li>{@code POST /api/admin/products} 带 {@code doorWidths:["2.8","3.2"]} ⇒ <b>200 创建成功</b>；</li>
 *   <li>只读 SQL：{@code column "door_widths" does not exist} —— {@code products} 表**没有这一列**；</li>
 *   <li>{@code GET /{id}} 响应里也没有该字段（响应里的 {@code doorWidths} 是**从 SKU 派生**的，
 *       没有 SKU 时结构上就派生不出任何东西）；</li>
 *   <li>⇒ 门幅入参只在「颜色 × 门幅 自动建 SKU」这一条路径上被消费，其它形态**无声丢弃**。</li>
 * </ol>
 *
 * <h2>为什么必须真库</h2>
 * 病灶的最后一环是「列不存在」—— mock 面（{@code productMapper.insert} 被拦截）**结构上看不见**
 * 列存不存在，也看不见 {@code JacksonTypeHandler} 在 PG 上到底写没写出 JSONB。判据必须
 * ① 读 {@code information_schema} 证列在；② 读列值证内容；③ 走**真读面**
 * （{@code ProductService.getProductById}）证回读一致。
 *
 * <h2>判据（每条都能单独变红）</h2>
 * <ol>
 *   <li><b>列存在</b>：{@code products.door_widths}（V214）—— 改前不存在 ⇒ 本条红；</li>
 *   <li><b>建品落库 + 回读一致</b>：无颜色/无 SKU 时也落库（这正是改前被丢弃的形态），
 *       回读逐字一致；</li>
 *   <li><b>有 SKU 时派生口径不回退</b>：{@code colors × doorWidths} ⇒ SKU 行数 = 矩阵规模，
 *       回读 = SKU 派生值（与既有口径一致，不许变成「只读列」）；</li>
 *   <li><b>改品也落库</b>：只给 {@code doorWidths} 的部分更新 ⇒ 列更新 + 回读一致；</li>
 *   <li><b>V214 的存量回填</b>：只填空数组行（从既有 SKU 去重聚合）、已有值不被覆盖、
 *       二次执行幂等（0 行变更）—— 回填方案的可执行证据，不是纸面承诺。</li>
 * </ol>
 *
 * <h2>装置</h2>
 * 一次性真 PG（{@link PgCluster#startOrAbort()}，与 #5158/#5167/#6209 同源口径），
 * schema 取 bootstrap 终态 {@code db/init/schema.sql}（不手抄列清单）。
 * 缺 PG 二进制时本机显式 skip、CI（{@code MIGAO_REQUIRE_REALDB=1}）fail-closed 判红。
 */
@DisplayName("🔴 真库判据（#9005）：doorWidths 建品→落库→回读一致 + V214 存量回填")
class ProductDoorWidthsRoundTripRealDbTest {

    private static final Long TENANT_ID = 1L;
    private static final String CATEGORY_ID = "cat-9005";
    private static final String MIGRATION =
            "backend/admin-api/src/main/resources/db/migration/V214__add_product_door_widths.sql";

    private static PgCluster cluster;
    private static DataSource dataSource;
    private static SqlSessionFactory factory;
    private static SqlSession session;
    private static ProductService productService;

    @BeforeAll
    static void startRealPostgresAndFixtures() throws Exception {
        cluster = PgCluster.startOrAbort();
        dataSource = cluster.dataSource();
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute(schemaSql());
            // tenant 1 由 schema 种子自带（与 ProductCreateIdempotencyRealDbTest 同口径）；分类自建
            st.execute("INSERT INTO categories (id, tenant_id, name, status, sort_order) VALUES ('"
                    + CATEGORY_ID + "', " + TENANT_ID + ", '门幅验收分类', 'active', 1)");
        }
        MybatisConfiguration configuration = new MybatisConfiguration();
        configuration.setMapUnderscoreToCamelCase(true);
        // 判据用裸 JDBC 读回（不经被测读面）⇒ 一级缓存必须 STATEMENT 级，否则「写完再查」读旧值
        configuration.setLocalCacheScope(LocalCacheScope.STATEMENT);
        configuration.setEnvironment(new Environment("acc-9005", new JdbcTransactionFactory(), dataSource));
        // 多租户拦截器必须在场：生产 SQL 经它追加 tenant_id（少了它就只测了 mapper 原文）
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
        TenantContext.setTenantId(TENANT_ID);
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

    // ══════════════════════════════════ 判据 1：列存在

    @Test
    @DisplayName("判据1：products.door_widths 必须存在（V214；改前：column does not exist）")
    void doorWidthsColumnExists() throws SQLException {
        long columns = scalarLong("SELECT count(*) FROM information_schema.columns"
                + " WHERE table_name = 'products' AND column_name = 'door_widths'");
        String type = scalarString("SELECT data_type FROM information_schema.columns"
                + " WHERE table_name = 'products' AND column_name = 'door_widths'");
        System.out.println("[READING #9005 列存在性] products.door_widths 列数=" + columns + " 类型=" + type);

        assertThat(columns)
                .as("products 必须有 door_widths 列（V214/issue #9005）—— 改前实测 `column \"door_widths\" does not exist`；"
                        + "改回：新增 backend/admin-api/src/main/resources/db/migration/V214__add_product_door_widths.sql"
                        + " 并在 db/init/schema.sql 的 products 建表里同步")
                .isEqualTo(1L);
        assertThat(type).as("门幅清单与 selling_methods / detail_images 同风格：JSONB 数组").isEqualTo("jsonb");
    }

    // ══════════════════════════════════ 判据 2：建品（无颜色）落库 + 回读

    @Test
    @DisplayName("判据2：建品带 doorWidths、**无颜色/无 SKU** ⇒ 列落值 + 回读逐字一致（改前：无声丢弃）")
    void createWithoutColorsPersistsDoorWidths() throws SQLException {
        ProductResponse created = productService.createProduct(
                createRequest("DOOR-9005-NO-COLOR", List.of("2.8", "3.2")), TENANT_ID);
        String productId = created.getId();

        String raw = jsonbText("SELECT door_widths::text FROM products WHERE id = '" + productId + "'");
        List<String> reread = productService.getProductById(productId, TENANT_ID).getDoorWidths();
        long skuRows = scalarLong("SELECT count(*) FROM product_skus WHERE product_id = '" + productId + "'");
        System.out.println("[READING #9005 建品(无颜色)] 请求门幅=[2.8, 3.2] 落库列=" + raw
                + " 回读=" + reread + " SKU行=" + skuRows);

        assertThat(skuRows).as("本判据的形态就是「还没有 SKU」（没有颜色 ⇒ 笛卡尔积不成立）").isZero();
        assertThat(reread)
                .as("回读必须逐字一致（改前：响应里没有该字段 = null —— 门幅被无声丢弃）")
                .containsExactly("2.8", "3.2");
        assertThat(jsonbArray("SELECT door_widths FROM products WHERE id = '" + productId + "'"))
                .as("列值必须与请求逐字一致（JSONB 数组）")
                .containsExactly("2.8", "3.2");
    }

    // ══════════════════════════════════ 判据 3：有 SKU 时派生口径不回退

    @Test
    @DisplayName("判据3：colors × doorWidths ⇒ SKU 矩阵照建 2 行，回读仍 = SKU 派生值（不许变成「只读列」）")
    void withSkusReadStaysSkuDerived() throws SQLException {
        ProductCreateRequest request = createRequest("DOOR-9005-MATRIX", List.of("2.8", "3.2"));
        ProductColorInput color = new ProductColorInput();
        color.setColorName("米白");
        request.setColors(List.of(color));

        ProductResponse created = productService.createProduct(request, TENANT_ID);
        String productId = created.getId();

        long skuRows = scalarLong("SELECT count(*) FROM product_skus WHERE product_id = '" + productId + "'");
        List<String> reread = productService.getProductById(productId, TENANT_ID).getDoorWidths();
        String derived = jsonbText("SELECT to_jsonb(array_agg(DISTINCT door_width))::text FROM product_skus"
                + " WHERE product_id = '" + productId + "'");
        System.out.println("[READING #9005 建品(矩阵)] SKU行=" + skuRows + " 回读=" + reread + " SKU派生=" + derived);

        assertThat(skuRows).as("颜色 × 门幅 = 1 × 2 ⇒ 2 个 SKU（既有矩阵口径不变）").isEqualTo(2L);
        assertThat(reread)
                .as("有 SKU 时读面仍以 product_skus.door_width 派生值为准（用户裁定 2026-09-21：SKU = 颜色 × 门幅）")
                .containsExactly("2.8", "3.2");
    }

    // ══════════════════════════════════ 判据 4：改品也落库

    @Test
    @DisplayName("判据4：改品只给 doorWidths 的部分更新 ⇒ 列更新 + 回读一致（改前：改品同样丢）")
    void updateOnlyDoorWidthsPersists() throws SQLException {
        String productId = productService.createProduct(
                createRequest("DOOR-9005-UPDATE", List.of("2.8")), TENANT_ID).getId();

        ProductUpdateRequest update = new ProductUpdateRequest();
        update.setDoorWidths(List.of("3.4"));
        productService.updateProduct(productId, update, TENANT_ID);

        List<String> reread = productService.getProductById(productId, TENANT_ID).getDoorWidths();
        System.out.println("[READING #9005 改品] 请求门幅=[3.4] 落库列="
                + jsonbText("SELECT door_widths::text FROM products WHERE id = '" + productId + "'")
                + " 回读=" + reread);

        assertThat(reread)
                .as("只给 doorWidths 的部分更新必须真的写进 products.door_widths（改前：200 但列不变）")
                .containsExactly("3.4");
    }

    // ══════════════════════════════════ 判据 5：V214 存量回填 + 幂等

    @Test
    @DisplayName("判据5：V214 回填 —— 只填空数组行 / 已有值不覆盖 / 二次执行幂等")
    void v214BackfillIsNarrowAndIdempotent() throws Exception {
        // 存量形态 A：有 SKU、门幅列还是空的（V214 之前建的商品）⇒ 应被回填为 SKU 去重集合
        insertLegacyProduct("legacy-9005-empty", "[]");
        insertLegacySku(900_500_001L, "legacy-9005-empty", "2.8");
        insertLegacySku(900_500_002L, "legacy-9005-empty", "3.2");
        insertLegacySku(900_500_003L, "legacy-9005-empty", "2.8");
        // 存量形态 B：列已有值（本次改动之后建的商品）⇒ 回填**不许**覆盖
        insertLegacyProduct("legacy-9005-keep", "[\"9.9\"]");
        insertLegacySku(900_500_004L, "legacy-9005-keep", "2.8");

        runMigration();
        List<String> filled = jsonbArray("SELECT door_widths FROM products WHERE id = 'legacy-9005-empty'");
        List<String> kept = jsonbArray("SELECT door_widths FROM products WHERE id = 'legacy-9005-keep'");
        long firstRunRows = scalarLong("SELECT count(*) FROM products WHERE id IN"
                + " ('legacy-9005-empty','legacy-9005-keep') AND jsonb_array_length(door_widths) > 0");
        System.out.println("[READING #9005 回填] 空数组行回填=" + filled + " 已有值行保留=" + kept
                + " 非空行数=" + firstRunRows);

        assertThat(filled).as("空数组行按既有 SKU 去重聚合回填（字典序，去重 3 行 ⇒ 2 个门幅）")
                .containsExactly("2.8", "3.2");
        assertThat(kept).as("已有值的行一律不覆盖（回填不许改写本次改动之后的真实声明）")
                .containsExactly("9.9");

        // 幂等：整份迁移再执行一次 ⇒ 不报错、值不变（MigrationRunner 的硬约定：所有 SQL 必须可重入）
        runMigration();
        assertThat(jsonbArray("SELECT door_widths FROM products WHERE id = 'legacy-9005-empty'"))
                .as("二次执行后回填结果逐字不变（幂等）")
                .containsExactly("2.8", "3.2");
        assertThat(jsonbArray("SELECT door_widths FROM products WHERE id = 'legacy-9005-keep'"))
                .as("二次执行也不许覆盖已有值")
                .containsExactly("9.9");
    }

    // ══════════════════════════════════ 装置

    private static ProductCreateRequest createRequest(String skuCode, List<String> doorWidths) {
        ProductCreateRequest request = new ProductCreateRequest();
        request.setName("门幅验收-" + skuCode);
        request.setSkuCode(skuCode);
        request.setCategoryId(CATEGORY_ID);
        request.setBasePrice(new BigDecimal("128.50"));
        request.setUnit("米");
        request.setPricingType("per_meter");
        // status 走默认 draft：本判据只测门幅落库，不牵状态机
        request.setDoorWidths(doorWidths);
        return request;
    }

    /** 直接落一条「V214 之前」的商品行（门幅列给任意初值，模拟存量各种形态）。 */
    private static void insertLegacyProduct(String id, String doorWidthsJson) throws SQLException {
        execute("INSERT INTO products (id, tenant_id, name, sku_code, status, base_price, door_widths)"
                + " VALUES ('" + id + "', " + TENANT_ID + ", '存量-" + id + "', 'LEGACY-" + id + "', 'draft', 99.00, '"
                + doorWidthsJson + "'::jsonb)");
    }

    private static void insertLegacySku(Long id, String productId, String doorWidth) throws SQLException {
        execute("INSERT INTO product_skus (id, tenant_id, product_id, color_name, door_width, price, stock)"
                + " VALUES (" + id + ", " + TENANT_ID + ", '" + productId + "', '米白', '" + doorWidth
                + "', 99.00, 0)");
    }

    /** 执行 V214 迁移文件（剥掉 `--` 注释按 `;` 切分）—— 回填方案的可执行证据。 */
    private static void runMigration() throws IOException, SQLException {
        String sql = Files.readString(repoRoot().resolve(MIGRATION), StandardCharsets.UTF_8);
        StringBuilder withoutComments = new StringBuilder();
        for (String line : sql.split("\n")) {
            if (line.trim().startsWith("--")) {
                continue;
            }
            withoutComments.append(line).append('\n');
        }
        for (String statement : withoutComments.toString().split(";")) {
            if (!statement.isBlank()) {
                execute(statement);
            }
        }
    }

    private static void execute(String sql) throws SQLException {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute(sql);
        }
    }

    private static long scalarLong(String sql) throws SQLException {
        try (Connection conn = dataSource.getConnection();
             Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery(sql)) {
            return rs.next() ? rs.getLong(1) : -1L;
        }
    }

    private static String scalarString(String sql) throws SQLException {
        try (Connection conn = dataSource.getConnection();
             Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery(sql)) {
            return rs.next() ? rs.getString(1) : null;
        }
    }

    /** jsonb::text（只用于打印读数，断言不依赖文本格式）。 */
    private static String jsonbText(String sql) throws SQLException {
        return scalarString(sql);
    }

    /**
     * 读 JSONB 数组 → List（用 {@code jsonb_array_elements_text} 展开，
     * **不解析 PG 的 jsonb 文本格式** ⇒ 断言不会被 `", "` 这类格式差异绊倒）。
     */
    private static List<String> jsonbArray(String sql) throws SQLException {
        List<String> values = new ArrayList<>();
        try (Connection conn = dataSource.getConnection();
             Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery(
                     "SELECT e.v FROM (" + sql + ") t, LATERAL jsonb_array_elements_text(t.door_widths) AS e(v)")) {
            while (rs.next()) {
                values.add(rs.getString(1));
            }
        }
        return values;
    }

    private static Path repoRoot() {
        Path cur = Paths.get("").toAbsolutePath();
        while (cur != null) {
            if (Files.isDirectory(cur.resolve("backend/admin-api/src/main/resources/db/migration"))) {
                return cur;
            }
            cur = cur.getParent();
        }
        throw new IllegalStateException("找不到仓库根目录（backend/admin-api/src/main/resources/db/migration 不存在）");
    }

    private static String schemaSql() throws IOException {
        Path path = Paths.get("src/main/resources/db/init/schema.sql");
        if (!Files.exists(path)) {
            path = repoRoot().resolve("backend/admin-api/src/main/resources/db/init/schema.sql");
        }
        return Files.readString(path);
    }
}
