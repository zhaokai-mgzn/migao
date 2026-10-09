// case_ids: PR-128
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.MybatisSqlSessionFactoryBuilder;
import com.baomidou.mybatisplus.extension.plugins.MybatisPlusInterceptor;
import com.baomidou.mybatisplus.extension.plugins.handler.TenantLineHandler;
import com.baomidou.mybatisplus.extension.plugins.inner.TenantLineInnerInterceptor;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ProductColorInput;
import com.migao.admin.dto.ProductCreateRequest;
import com.migao.admin.dto.ProductResponse;
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
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mybatis.spring.SqlSessionTemplate;
import org.mybatis.spring.transaction.SpringManagedTransactionFactory;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

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
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CyclicBarrier;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 🔴 <b>真库并发判据（issue #6209）：同一 {@code X-Client-Request-Id} N=4 并发建品 ⇒
 * 恰好 1 条业务对象 + {@code client_request_keys} 恰 1 行</b>。
 *
 * <h2>现场证据（本判据要复现的读数）</h2>
 * {@code acceptance/2026-10-03/batch-writeface-sweep/out/E1-duplicate-submit.json}：
 * 串行 1 次 ⇒ 商品 1 条；随后同键<b>并发 5 次</b> ⇒ 5 个请求全部 200 且各返回一个新 id、
 * 落地商品 <b>6 条</b>、{@code client_request_keys} <b>0 行</b>。改后同一形态必须收成
 * 「1 条 + 1 行幂等键」。
 *
 * <h2>为什么必须真库 + 真并发</h2>
 * 幂等的原子性来源是 <b>DDL 的 UNIQUE (tenant_id, client_request_id)</b> +
 * {@code INSERT … ON CONFLICT DO NOTHING}；「并发下到底几条真落库」只有真 PG 的行锁/唯一索引能给读数 ——
 * mock 面结构上判不了（mock 的 insert 恒成功、也不会有第二个事务在索引上等）。
 *
 * <h2>装置（与 #6220 / #6237 同源口径）</h2>
 * 一次性真 PG（{@link PgCluster#startOrAbort()}），schema 取 bootstrap 终态
 * （{@code db/init/schema.sql}，不手抄列清单）。每个并发请求 = 自己的 {@link SqlSession} +
 * 自己的连接 + 自己的事务；<b>业务写入与幂等键同事务</b>（{@link TransactionTemplate} 提供生产侧
 * {@code @Transactional} 的等价边界，MyBatis 走 {@link SpringManagedTransactionFactory} ⇒
 * mapper 与 {@code JdbcTemplate} 共用被 Spring 绑定的那条连接）。
 * 共用一条连接会让 4 个请求串行化 ⇒ 判据变假绿。
 *
 * <h2>判据（每条都能单独变红）</h2>
 * <ol>
 *   <li><b>业务对象恰 1 条</b>：{@code products} 里该货号恰 1 行（同键并发建出 N 条 ⇒ 判红）；</li>
 *   <li><b>幂等留痕恰 1 行</b>：{@code client_request_keys} 该键恰 1 行（0 行 = 幂等面仍没接上 —— 现场读数）；</li>
 *   <li><b>恰一个真执行</b>：成功结果里 {@code replayed=true} 的 ≥1（后来者确实走的是回放），
 *       且所有成功结果的 id **同一个**；</li>
 *   <li><b>负向对照（防「一律只建一条」的假修）</b>：<b>不同</b>键并发 ⇒ 各建一份，
 *       {@code client_request_keys} 行数与请求数相等。</li>
 * </ol>
 */
@DisplayName("🔴 真库并发判据（#6209）：N=4 同键并发建品 ⇒ 恰 1 条商品 + 幂等键恰 1 行")
class ProductCreateIdempotencyRealDbTest {

    private static final Long TENANT_ID = 1L;
    private static final String CATEGORY_ID = "cat-idem-6209";
    private static final String CATEGORY_NAME = "幂等验收分类";
    private static final int CONCURRENCY = 4;

    private static PgCluster cluster;
    private static DataSource dataSource;
    private static SqlSessionFactory factory;
    private static TransactionTemplate txTemplate;

    @BeforeAll
    static void startRealPostgresAndFixtures() throws Exception {
        cluster = PgCluster.startOrAbort();
        dataSource = cluster.dataSource();
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute(schemaSql());
            // tenant 1 由 schema 种子自带（与 ProductStockLedgerRealDbTest 同口径）；分类自建
            st.execute("INSERT INTO categories (id, tenant_id, name, status, sort_order) VALUES ('"
                    + CATEGORY_ID + "', " + TENANT_ID + ", '" + CATEGORY_NAME + "', 'active', 1)");
        }
        MybatisConfiguration configuration = new MybatisConfiguration();
        configuration.setMapUnderscoreToCamelCase(true);
        // 判据用裸 JDBC 读回（不经被测读面）⇒ 一级缓存必须 STATEMENT 级，否则「写完再查」读旧值
        configuration.setLocalCacheScope(LocalCacheScope.STATEMENT);
        // 🔴 Spring 事务工厂：业务写入与幂等键必须**同一条被 Spring 绑定的连接**（生产侧同款边界
        // 由 ProductService#createProduct 的 @Transactional 提供），否则回放判据测的是测试自己的回滚
        configuration.setEnvironment(new Environment("acc-6209",
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
        for (Class<?> mapper : List.of(ProductMapper.class, ProductColorMapper.class, ProductSkuMapper.class,
                ProductAttributeMapper.class, CategoryMapper.class, StockLedgerMapper.class)) {
            configuration.addMapper(mapper);
        }
        factory = new MybatisSqlSessionFactoryBuilder().build(configuration);
        txTemplate = new TransactionTemplate(new DataSourceTransactionManager(dataSource));
    }

    @AfterAll
    static void stopRealPostgres() {
        if (cluster != null) {
            cluster.stop();
        }
    }

    // ────────────────────────────────────────────── 判据 1~3：同键并发

    @Test
    @DisplayName("N=4 同键并发建品（3 轮）：商品恰 1 条 / 幂等键恰 1 行 / 回放同一 id")
    void concurrentSameKeyCreatesExactlyOneProduct() throws Exception {
        for (int round = 0; round < 3; round++) {
            String skuCode = "IDEM-6209-SAME-" + round;
            String key = "idem-6209-same-key-" + round;
            List<Outcome> outcomes = concurrentCreate(key, skuCode);

            long success = outcomes.stream().filter(Outcome::ok).count();
            long replayed = outcomes.stream().filter(o -> o.ok() && o.replayed()).count();
            List<String> ids = outcomes.stream().filter(Outcome::ok).map(Outcome::id).distinct().toList();
            long productRows = scalarLong("SELECT count(*) FROM products WHERE tenant_id = " + TENANT_ID
                    + " AND sku_code = '" + skuCode + "' AND deleted = 0");
            long keyRows = scalarLong("SELECT count(*) FROM client_request_keys WHERE tenant_id = " + TENANT_ID
                    + " AND client_request_id = '" + key + "' AND endpoint = '"
                    + ProductService.ENDPOINT_CREATE_PRODUCT + "'");
            String winnerId = ids.isEmpty() ? "<none>" : ids.get(0);
            long skuRows = winnerId.startsWith("<") ? -1
                    : scalarLong("SELECT count(*) FROM product_skus WHERE tenant_id = " + TENANT_ID
                            + " AND product_id = '" + winnerId + "'");
            System.out.println("[READING #6209 同键并发 r=" + round + "] 请求=" + CONCURRENCY
                    + " 成功=" + success + " 回放=" + replayed + " 不同id=" + ids.size()
                    + " 商品行=" + productRows + " 幂等键行=" + keyRows + " SKU行=" + skuRows);

            assertThat(success).as("同键并发的每个请求都应拿到结果（首次执行 + 回放）").isEqualTo(CONCURRENCY);
            assertThat(productRows).as("同键并发必须恰 1 条业务对象（现场读数 = 5 并发 ⇒ 6 条）")
                    .isEqualTo(1L);
            assertThat(keyRows).as("幂等留痕恰 1 行（0 行 = 写面仍没接幂等，现场读数）").isEqualTo(1L);
            assertThat(ids).as("所有成功结果必须指向**同一条**商品（各返回新 id = 重复建品）").hasSize(1);
            assertThat(replayed).as("至少一个后来者确实走了回放（否则「去重」没有被执行到）")
                    .isGreaterThanOrEqualTo(1L);
            assertThat(skuRows).as("回放的产物必须与赢家同一条品的 SKU（不是另一份）").isEqualTo(1L);
        }
    }

    // ────────────────────────────────────────────── 判据 4：负向对照

    @Test
    @DisplayName("负向对照：N=4 **不同**键并发 ⇒ 各建一份（防「一律只建一条」的假修）")
    void concurrentDistinctKeysEachCreateTheirOwnProduct() throws Exception {
        List<Outcome> outcomes = concurrentCreate(null, "IDEM-6209-DIFF");

        long success = outcomes.stream().filter(Outcome::ok).count();
        List<String> ids = outcomes.stream().filter(Outcome::ok).map(Outcome::id).distinct().toList();
        long productRows = scalarLong("SELECT count(*) FROM products WHERE tenant_id = " + TENANT_ID
                + " AND sku_code = 'IDEM-6209-DIFF' AND deleted = 0");
        long keyRows = scalarLong("SELECT count(*) FROM client_request_keys WHERE tenant_id = " + TENANT_ID
                + " AND client_request_id LIKE 'idem-6209-diff-%'");
        System.out.println("[READING #6209 不同键并发] 成功=" + success + " 不同id=" + ids.size()
                + " 商品行=" + productRows + " 幂等键行=" + keyRows);

        assertThat(success).as("不同键的每个请求都必须真执行成功").isEqualTo(CONCURRENCY);
        assertThat(ids).as("不同键 ⇒ 各自一条独立商品").hasSize(CONCURRENCY);
        assertThat(productRows).as("不同键必须各建一份（不许多、不许少）").isEqualTo((long) CONCURRENCY);
        assertThat(keyRows).as("每个键各占一行留痕").isEqualTo((long) CONCURRENCY);
    }

    // ────────────────────────────────────────────── 装置

    /**
     * 并发建品。{@code sharedKey != null} ⇒ 全部用同一把键；否则第 i 个请求用
     * {@code idem-6209-diff-<i>}（负向对照）。
     */
    private static List<Outcome> concurrentCreate(String sharedKey, String skuCode) throws Exception {
        List<Outcome> outcomes = new ArrayList<>();
        ExecutorService pool = Executors.newFixedThreadPool(CONCURRENCY);
        CyclicBarrier barrier = new CyclicBarrier(CONCURRENCY);
        List<Future<Outcome>> futures = new ArrayList<>();
        try {
            for (int i = 0; i < CONCURRENCY; i++) {
                final int idx = i;
                futures.add(pool.submit(() -> {
                    barrier.await(30, TimeUnit.SECONDS);
                    String key = sharedKey != null ? sharedKey : "idem-6209-diff-" + idx;
                    try {
                        return txTemplate.execute(status -> {
                            // 🔴 用 SqlSessionTemplate（不是裸 openSession）：业务写入与幂等键必须
                            // 落**同一条被 Spring 事务绑定的连接**；裸 session 会各自 autocommit
                            // ⇒ 会撞上「占位已提交、快照还没写」的窗口（那是**测试装置**的假象，
                            // 不是产品行为 —— 生产侧每请求一个 SqlSessionTemplate + @Transactional）
                            SqlSession session = new SqlSessionTemplate(factory);
                            ProductService service = serviceOn(session);
                            TenantContext.setTenantId(TENANT_ID);
                            ProductResponse response = service.createProduct(request(skuCode), TENANT_ID, key);
                            return new Outcome(true, response.getId(),
                                    Boolean.TRUE.equals(response.getReplayed()));
                        });
                    } catch (Exception e) {
                        System.out.println("[READING #6209 落败] key=" + key + " ⇒ "
                                + e.getClass().getSimpleName() + ": " + e.getMessage());
                        return new Outcome(false, null, false);
                    } finally {
                        TenantContext.clear();
                    }
                }));
            }
            for (Future<Outcome> f : futures) {
                outcomes.add(f.get(120, TimeUnit.SECONDS));
            }
        } finally {
            pool.shutdownNow();
        }
        return outcomes;
    }

    private static ProductService serviceOn(SqlSession session) {
        StockLedgerService stockLedgerService = new StockLedgerService(
                session.getMapper(StockLedgerMapper.class), session.getMapper(ProductSkuMapper.class));
        // ObjectProvider 只实现唯一抽象方法 getObject()（getIfAvailable 的 default 委托给它）
        ObjectProvider<JdbcTemplate> provider = new ObjectProvider<>() {
            @Override
            public JdbcTemplate getObject() {
                return new JdbcTemplate(dataSource);
            }
        };
        ClientRequestIdService clientRequestIdService =
                new ClientRequestIdService(provider, appObjectMapper());
        return new ProductService(session.getMapper(ProductMapper.class),
                session.getMapper(CategoryMapper.class), session.getMapper(ProductColorMapper.class),
                session.getMapper(ProductSkuMapper.class), session.getMapper(ProductAttributeMapper.class),
                stockLedgerService, clientRequestIdService);
    }

    private static ProductCreateRequest request(String skuCode) {
        ProductCreateRequest request = new ProductCreateRequest();
        request.setName("幂等并发验收-6209");
        request.setSkuCode(skuCode);
        request.setCategoryId(CATEGORY_ID);
        request.setBasePrice(new BigDecimal("9.00"));
        request.setStock(new BigDecimal("1.0"));
        request.setUnit("米");
        request.setPricingType("per_meter");
        request.setStatus("draft");
        ProductColorInput color = new ProductColorInput();
        color.setColorName("米白");
        request.setColors(List.of(color));
        // SKU 组合 = 颜色 × 门幅（V113）⇒ 不给门幅就一个 SKU 都不建，断言会失去判别力
        request.setDoorWidths(List.of("2.8m"));
        return request;
    }

    /**
     * 应用侧同款 ObjectMapper（注册 {@code JavaTimeModule}）：{@link ProductResponse} 带
     * {@code OffsetDateTime} 字段，裸 {@code new ObjectMapper()} 写不出快照 ⇒ {@code complete}
     * 按 fail-closed 抛错（生产用的是 Spring 配好的 bean，不是裸 mapper）。
     */
    private static ObjectMapper appObjectMapper() {
        return new ObjectMapper().registerModule(new JavaTimeModule());
    }

    /** 一条并发请求的可观察结果（成功 = 200/回放；失败 = 显式异常，不许静默成功）。 */
    private record Outcome(boolean ok, String id, boolean replayed) {
    }

    // ────────────────────────────────────────────── 真值读取（裸 JDBC，不经被测读面）

    private static long scalarLong(String sql) throws SQLException {
        try (Connection conn = dataSource.getConnection();
             Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery(sql)) {
            rs.next();
            return rs.getLong(1);
        }
    }

    private static String schemaSql() throws IOException {
        Path path = Paths.get("src/main/resources/db/init/schema.sql");
        if (!Files.exists(path)) {
            path = Paths.get("backend/admin-api/src/main/resources/db/init/schema.sql");
        }
        return Files.readString(path);
    }
}
