// case_ids: MC-082

package com.migao.admin.service;

import ch.qos.logback.classic.Level;
import ch.qos.logback.classic.Logger;
import ch.qos.logback.classic.spi.ILoggingEvent;
import ch.qos.logback.classic.spi.IThrowableProxy;
import ch.qos.logback.core.read.ListAppender;
import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.MybatisSqlSessionFactoryBuilder;
import com.baomidou.mybatisplus.extension.plugins.MybatisPlusInterceptor;
import com.baomidou.mybatisplus.extension.plugins.handler.TenantLineHandler;
import com.baomidou.mybatisplus.extension.plugins.inner.TenantLineInnerInterceptor;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.config.GlobalExceptionHandler;
import com.migao.admin.config.TenantContext;
import com.migao.admin.controller.StockBatchController;
import com.migao.admin.dto.BatchStockViews;
import com.migao.admin.dto.BatchStocktakeRequest;
import com.migao.admin.entity.StockBatchConsumption;
import com.migao.admin.mapper.ProductSkuMapper;
import com.migao.admin.mapper.StockBatchConsumptionMapper;
import com.migao.admin.mapper.StockBatchMapper;
import com.migao.admin.mapper.StockLedgerMapper;
import com.migao.admin.time.BusinessClock;
import net.sf.jsqlparser.expression.Expression;
import net.sf.jsqlparser.expression.LongValue;
import org.apache.ibatis.mapping.Environment;
import org.apache.ibatis.session.LocalCacheScope;
import org.apache.ibatis.session.SqlSession;
import org.apache.ibatis.session.SqlSessionFactory;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mybatis.spring.transaction.SpringManagedTransactionFactory;
import org.slf4j.LoggerFactory;
import org.springframework.http.MediaType;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.mock.web.MockHttpServletResponse;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.transaction.support.TransactionTemplate;

import javax.sql.DataSource;
import java.io.IOException;
import java.lang.reflect.InvocationHandler;
import java.lang.reflect.Method;
import java.lang.reflect.Proxy;
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
import java.util.Map;
import java.util.concurrent.CyclicBarrier;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;

/**
 * 🔴 <b>端点级判据（issue #6318）：{@code POST /api/admin/batch-stock/stocktake} 同 runId 6 并发
 * ⇒ 幂等回执（1 applied + 5 replayed），<u>不得出现 5xx</u></b>。
 *
 * <h2>为什么必须再有一份「端点级」判据（本单的病）</h2>
 * #6301 的修复带了真库并发判据 {@link BatchStocktakeConcurrentRealDbTest} —— 但它直接调
 * <b>服务方法</b>，测的是「服务层不抛异常」。而用户看到的契约在<b>更高一层</b>：
 * <b>异常 → HTTP 状态的映射</b>（{@code GlobalExceptionHandler}）与<b>回执体</b>（{@code data.lines[].status}）。
 * 「服务级绿、端点级红」正是这两层之差：服务层哪怕只是换个写法继续抛 {@code DuplicateKeyException}，
 * 服务级判据可能仍是绿的，而端点上是 5 个 500。
 *
 * <p>⇒ 本判据把**同一份并发窗口**搬到 HTTP 栈上：真 {@code MockMvc}（真 {@code DispatcherServlet}）
 * + 真 {@code StockBatchController} + 真 {@code BatchStocktakeService}（真 {@code @Transactional}
 * 边界，用 {@link TransactionTemplate} 等价替身）+ 真 {@code GlobalExceptionHandler}
 * + **真 PG**。断言的是**状态码**与**回执体**，以及落库不变式。</p>
 *
 * <h2>为什么必须真 PG（mock 面结构上不可见）</h2>
 * 「两个请求同时在『查已记批次』之后、『插』之前」只由真 PG 的两件事决定：① 唯一索引在**插入那一刻**
 * 的原子判定（{@code uk_batch_consumption_stocktake}）；② 未提交行对并发事务的可见性
 * （B 的 SELECT 看不见 A 未提交的行）。mock 面上 {@code selectList} 恒返回空、{@code insert} 恒成功
 * ⇒ 窗口**结构上不存在**。
 *
 * <h2>三条判据（全部可归因 · 全部带注入式红证）</h2>
 * <ol>
 *   <li><b>判据①（主判据）</b>：{@link CyclicBarrier} 把 6 个请求**全部压过「查」这一步**才放行提交
 *       ⇒ 窗口从「偶发」变「必现」；断言 6 个响应的 HTTP 状态码**全部 2xx**、回执行恰 1 个
 *       {@code applied} + 5 个 {@code replayed}、该 run 分录恰 1 行、库存链恰一条 {@code 60.0->58.5}。</li>
 *   <li><b>判据②（注入式红证 · 端点级）</b>：把生产写入路径换成**朴素 {@code insert}**
 *       （{@link Proxy} 只替换 {@code insertStocktakeIfAbsent}，其余原样转发真 mapper）⇒
 *       同一端点在**同一份注入**下当场 {@code 5 × 500}（= #6318 复现到的逐字读数）。
 *       这条读数自证判据①的绿**有判别力**（不是「本来就不撞」）。</li>
 *   <li><b>判据③（日志面）</b>：端点 500 必须在应用日志里有**具名异常 + 可定位坐标**
 *       （{@code method / uri / tenant / type}）—— 「红了但查不到」是判据面缺陷。
 *       判据把坐标与异常本体都钉住；把 {@code GlobalExceptionHandler} 那行里的坐标或异常摘掉 ⇒ 当场判红。</li>
 * </ol>
 *
 * <p><b>边界（如实登记，§19.1）</b>：① 走的是 <b>MockMvc 的 HTTP 栈</b>（真 DispatcherServlet +
 * 真处理器 + 真控制器 + 真服务 + 真库），但**没有**真 Tomcat/Servlet 容器、也没有 JWT/权限过滤器
 * —— 「鉴权面」不在这条判据的射程内（既有 {@code StockBatchControllerTest} 覆盖 `@RequirePermission`）；
 * ② 真库原始会话不经过 MyBatis-Spring 的异常翻译 ⇒ 判据③里具名异常是
 * {@code org.apache.ibatis.exceptions.PersistenceException}（生产是 Spring 的
 * {@code DuplicateKeyException}）—— 两者都是「具名异常」，判据对**异常族**断言、不钉死一个类名；
 * ③ 并发度 6 与 #6301/#6318 探针 W5 逐字一致；④ 探针对象全部自建（tenant {@value #TENANT_ID} /
 * 货号 {@value #PRODUCT_ID}），随一次性临时集群销毁，**不碰任何存量数据**；
 * ⑤ 它**不**判「两个**不同** run id 并发盘同一批次」的取数口径（既有边界，本单不动）。</p>
 */
@DisplayName("🔴 端点级判据（#6318）：POST /api/admin/batch-stock/stocktake 同 runId 6 并发 ⇒ 幂等回执而非 500")
class StockBatchStocktakeEndpointRaceRealDbTest {

    private static final Long TENANT_ID = 6318L;
    private static final String PRODUCT_ID = "acc-6318-stocktake-endpoint";
    private static final long SKU_ID = 631801L;
    private static final String SKU_CODE = "SKU-6318-EP";
    private static final BigDecimal STOCK_BEFORE = new BigDecimal("60.0");

    /** 并发度 = #6301/#6318 探针 W5 的读数口径（6 次并发 ⇒ 修前 `[200,500×5]`）。 */
    private static final int CONCURRENCY = 6;
    /** 端点路径（与 {@code StockBatchController#stocktake} 的映射逐字一致）。 */
    private static final String ENDPOINT = "/api/admin/batch-stock/stocktake";

    private static final ObjectMapper JSON = new ObjectMapper();

    private static PgCluster cluster;
    private static DataSource dataSource;
    private static SqlSessionFactory factory;
    private static TransactionTemplate txTemplate;
    private static MockMvc mockMvc;

    private static ListAppender<ILoggingEvent> logAppender;
    private static Logger handlerLogger;

    /** 每个请求线程一份会话（真 mapper 不是线程安全的）；控制层持有的是**按线程分发**的服务。 */
    private static final ThreadLocal<SqlSession> SESSION = new ThreadLocal<>();

    /** 注入面（纯测试侧）：true ⇒ 把原子闸换回朴素 {@code insert}（= 修前形态）。 */
    private static final AtomicBoolean NAIVE_INSERT = new AtomicBoolean(false);

    /** 缺陷窗口的会合点：6 个请求全部越过「查已记批次」后才放行（TOCTOU 窗口必现）。 */
    private static volatile CyclicBarrier preReadGate;

    private static final AtomicInteger BATCH_SEQ = new AtomicInteger(0);

    @BeforeAll
    static void startRealPostgresAndMountTheEndpoint() throws Exception {
        cluster = PgCluster.startOrAbort();
        dataSource = cluster.dataSource();
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute(schemaSql());
            st.execute("INSERT INTO tenants (id, name, code) OVERRIDING SYSTEM VALUE VALUES ("
                    + TENANT_ID + ", 'acc-6318', 'acc-6318')");
            st.execute("INSERT INTO products (id, tenant_id, name) VALUES ('" + PRODUCT_ID + "', "
                    + TENANT_ID + ", '布艺遮光帘-端点并发')");
            st.execute("INSERT INTO product_skus (id, tenant_id, product_id, door_width, price, stock,"
                    + " sku_code) OVERRIDING SYSTEM VALUE VALUES (" + SKU_ID + ", " + TENANT_ID
                    + ", '" + PRODUCT_ID + "', '2.8米', 100, " + STOCK_BEFORE.toPlainString()
                    + ", '" + SKU_CODE + "')");
        }
        MybatisConfiguration configuration = new MybatisConfiguration();
        configuration.setMapUnderscoreToCamelCase(true);
        configuration.setLocalCacheScope(LocalCacheScope.STATEMENT);
        configuration.setEnvironment(new Environment("acc-6318-endpoint",
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
        for (Class<?> mapper : List.of(StockBatchMapper.class, StockBatchConsumptionMapper.class,
                ProductSkuMapper.class, StockLedgerMapper.class)) {
            configuration.addMapper(mapper);
        }
        factory = new MybatisSqlSessionFactoryBuilder().build(configuration);
        txTemplate = new TransactionTemplate(new DataSourceTransactionManager(dataSource));

        // 端点 = 真 Controller + 真 Service（**按线程分发**到各自的真会话）+ 真全局异常处理器。
        // 生产侧的事务边界是 `BatchStocktakeService#stocktake` 的 `@Transactional(rollbackFor=Exception.class)`
        // ⇒ 这里用等价的 TransactionTemplate 替身（同样「任何异常整笔回滚」）。
        BatchStocktakeService dispatcher = new BatchStocktakeService(null, null, null) {
            @Override
            public BatchStockViews.StocktakeResult stocktake(Long tenantId, String productId, String runId,
                                                             List<BatchStocktakeRequest.Line> lines) {
                return txTemplate.execute(status -> serviceOn(session())
                        .stocktake(tenantId, productId, runId, lines));
            }
        };
        mockMvc = MockMvcBuilders.standaloneSetup(new StockBatchController(null, dispatcher))
                .setControllerAdvice(new GlobalExceptionHandler())
                .build();

        handlerLogger = (Logger) LoggerFactory.getLogger(GlobalExceptionHandler.class);
        logAppender = new ListAppender<>();
        logAppender.start();
        handlerLogger.addAppender(logAppender);
    }

    @AfterAll
    static void stopRealPostgres() {
        if (handlerLogger != null && logAppender != null) {
            handlerLogger.detachAppender(logAppender);
            logAppender.stop();
        }
        if (cluster != null) {
            cluster.stop();
        }
    }

    /** 每个判据开始前把 SKU 库存复位（判据间共享同一 SKU ⇒ 不复位会让读数互相污染）。 */
    @BeforeEach
    void resetSkuStockAndInjection() {
        NAIVE_INSERT.set(false);
        preReadGate = null;
        if (logAppender != null) {
            logAppender.list.clear();
        }
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute("UPDATE product_skus SET stock = " + STOCK_BEFORE.toPlainString()
                    + " WHERE id = " + SKU_ID);
        } catch (SQLException e) {
            throw new IllegalStateException("库存复位失败", e);
        }
    }

    // ══════════════════════════════════ 判据①（主判据）：端点级幂等回执

    /**
     * 🔴 端点级主判据：6 个**同一 runId、同一批次**的并发 {@code POST /stocktake} ⇒ HTTP **全部 2xx**、
     * 回执行恰 1 个 {@code applied} + 5 个 {@code replayed}，且落库不变式成立（分录 1 行 / 库存 Δ 一次）。
     *
     * <p>注入方式（= 让窗口必现的那个动作）：真 mapper 的 {@code selectList}（
     * {@code stocktakeRecordedBatchIds} 用的那一次「查」）之后过 {@link CyclicBarrier}
     * ⇒ 6 个请求必然都判定「未记」，全部走到插入那一步。</p>
     */
    @Test
    @DisplayName("🔴 判据①：同 runId 6 并发 POST /stocktake ⇒ 6×200（1 applied + 5 replayed）、5xx=0、分录 1 行、库存链恰一条")
    void concurrentStocktakeCallsGetIdempotentReceiptsNot500() throws Exception {
        long batchId = newBatch("PC-6318-E1");
        String runId = "PD-6318-E1";
        preReadGate = new CyclicBarrier(CONCURRENCY);

        List<MockHttpServletResponse> responses = fireConcurrently(runId, batchId, "58.5");
        List<Integer> statuses = responses.stream().map(MockHttpServletResponse::getStatus).toList();
        List<String> lineStatuses = lineStatuses(responses);
        System.out.println("[#6318 判据①] 端点逐请求状态码 = " + statuses
                + "；回执行 status = " + lineStatuses
                + "；该 run 分录 = " + entriesOfRun(runId) + " 行；库存链 = " + ledgerChainOfRun(runId));

        assertThat(statuses)
                .as("端点**不得**出现 5xx（修前 = 唯一键异常经全局处理器映射成 500）")
                .allMatch(status -> status < 500);
        assertThat(statuses).as("同 runId 的并发请求应全部被受理（首次 200 + 其余 200 回放）")
                .containsOnly(200);
        assertThat(lineStatuses).as("恰一次生效").filteredOn("applied"::equals).hasSize(1);
        assertThat(lineStatuses).as("其余 5 次必须是幂等回放")
                .filteredOn("replayed"::equals).hasSize(CONCURRENCY - 1);

        assertThat(entriesOfRun(runId)).as("防双记：分录终态恰好 1 行").isEqualTo(1);
        assertThat(ledgerChainOfRun(runId)).as("库存 Δ 只发生一次（恰好一条 60.0->58.5）")
                .containsExactly(STOCK_BEFORE.toPlainString() + "->58.5");
        assertThat(skuStock()).as("SKU 库存终态 = 58.5").isEqualByComparingTo("58.5");
    }

    // ══════════════════════════════════ 判据②：注入式红证（端点级）

    /**
     * 🔴 <b>判据②：把原子闸换回朴素 {@code insert} ⇒ 同一端点在端点级当场 {@code 5 × 500}</b>。
     *
     * <p>为什么必须留这条：判据①的「全绿」必须能区分「修好了」与「本来就不撞」。本判据用**同一份
     * 并发注入**（同一 barrier、同一并发度）把生产写入路径换成修前形态 ⇒ 端点响应从
     * {@code [200×6]} 变成 {@code [200, 500×5]} —— 这就是 #6318 复现到的逐字读数，也正是
     * 「判据①若在修前跑，会怎么红」的可执行答案（端点级，不是服务级）。</p>
     */
    @Test
    @DisplayName("🔴 判据②（注入式红证）：原子闸换回朴素 insert ⇒ 同一端点当场 5×500（自证判据①的绿有判别力）")
    void naiveInsertWiringTurnsTheEndpointIntoFiveHundreds() throws Exception {
        NAIVE_INSERT.set(true);
        long batchId = newBatch("PC-6318-E2");
        String runId = "PD-6318-E2";
        preReadGate = new CyclicBarrier(CONCURRENCY);

        List<MockHttpServletResponse> responses = fireConcurrently(runId, batchId, "58.5");
        List<Integer> statuses = responses.stream().map(MockHttpServletResponse::getStatus).toList();
        System.out.println("[#6318 判据②] 朴素 insert 注入下端点的逐请求读数 = " + statuses
                + "；500 体 = " + responses.stream().filter(r -> r.getStatus() >= 500)
                .map(this::errorCode).toList());

        assertThat(statuses).as("注入必须真的把端点打成 5xx（否则判据①无判别力）")
                .filteredOn(status -> status >= 500).hasSize(CONCURRENCY - 1);
        assertThat(statuses).as("恰一个赢家仍然 200").filteredOn(status -> status == 200).hasSize(1);
        assertThat(responses.stream().filter(r -> r.getStatus() >= 500).map(this::errorCode).toList())
                .as("500 体的错误码 = 全局处理器的 INTERNAL_ERROR（不是某个业务 4xx）")
                .containsOnly("INTERNAL_ERROR");
        assertThat(entriesOfRun(runId)).as("即便端点 5xx，防双记仍成立（分录 1 行）").isEqualTo(1);
    }

    // ══════════════════════════════════ 判据③：日志面（500 必须查得到）

    /**
     * 🔴 <b>判据③：端点 500 必须在应用日志里有<u>具名异常</u>与<u>请求坐标</u></b>。
     *
     * <p>病灶（#6318 的第二半）：「端点红了、日志里却什么都查不到」—— 500 只有在日志里能被
     * <b>按端点 / 租户</b>定位、并且看得出<b>异常类型</b>，排障才不靠猜。判据把三样都钉住：
     * ① ERROR 级别事件必须在场；② 事件文本含 {@code method / uri / tenant}；
     * ③ 事件的 throwable 链里有**具名异常**，且消息里带唯一索引名（= 真的能指认现场）。</p>
     *
     * <p>红证（双向）：把 {@code GlobalExceptionHandler#handleException} 里那行日志的坐标摘掉、或改成
     * 只记 {@code e.getMessage()}（不记异常本体）⇒ 本判据当场判红。</p>
     */
    @Test
    @DisplayName("🔴 判据③：端点 500 必须在日志里有具名异常 + 可定位坐标（method/uri/tenant/type）")
    void endpointFiveHundredCarriesANamedExceptionAndCoordinatesInLog() throws Exception {
        NAIVE_INSERT.set(true);
        long batchId = newBatch("PC-6318-E3");
        String runId = "PD-6318-E3";
        preReadGate = new CyclicBarrier(CONCURRENCY);
        logAppender.list.clear();

        List<MockHttpServletResponse> responses = fireConcurrently(runId, batchId, "58.5");
        assertThat(responses.stream().map(MockHttpServletResponse::getStatus).toList())
                .as("前置：本判据需要端点真的 500（用朴素 insert 注入制造）")
                .filteredOn(status -> status >= 500).hasSize(CONCURRENCY - 1);

        List<ILoggingEvent> errors = logAppender.list.stream()
                .filter(event -> event.getLevel() == Level.ERROR).toList();
        assertThat(errors).as("端点 500 必须在应用日志里留下 ERROR 事件（不许「红了但查不到」）")
                .isNotEmpty();

        String message = errors.get(0).getFormattedMessage();
        System.out.println("[#6318 判据③] 端点 500 的日志首行 = " + message);
        assertThat(message).as("日志必须能按**端点**定位").contains("POST").contains(ENDPOINT);
        assertThat(message).as("日志必须能按**租户**定位").contains(String.valueOf(TENANT_ID));
        assertThat(message).as("日志必须记下**异常类型**（不是只有一句自然语言）").contains("type=");

        String chain = throwableChain(errors.get(0));
        assertThat(chain).as("throwable 链里必须有具名异常（MyBatis 原始会话 ⇒ PersistenceException；"
                        + "生产经 MyBatis-Spring ⇒ DuplicateKeyException；判据对异常族断言）")
                .contains("PersistenceException");
        assertThat(chain).as("具名异常的消息里必须带唯一索引名（能指认现场）")
                .contains("uk_batch_consumption_stocktake");
    }

    // ══════════════════════════════════ 装置

    /** 6 个并发端点请求（同一 runId / 批次），返回逐请求的 HTTP 响应。 */
    private static List<MockHttpServletResponse> fireConcurrently(String runId, long batchId, String meters)
            throws Exception {
        ExecutorService pool = Executors.newFixedThreadPool(CONCURRENCY);
        try {
            String json = JSON.writeValueAsString(Map.of("productId", PRODUCT_ID, "runId", runId,
                    "lines", List.of(Map.of("batchId", batchId, "actualMeters", new BigDecimal(meters)))));
            CyclicBarrier start = new CyclicBarrier(CONCURRENCY);
            List<Future<MockHttpServletResponse>> futures = new ArrayList<>();
            for (int i = 0; i < CONCURRENCY; i++) {
                futures.add(pool.submit(() -> {
                    TenantContext.setTenantId(TENANT_ID);
                    try {
                        start.await(30, TimeUnit.SECONDS);
                        return mockMvc.perform(post(ENDPOINT)
                                        .contentType(MediaType.APPLICATION_JSON)
                                        .content(json))
                                .andReturn().getResponse();
                    } finally {
                        TenantContext.clear();
                        SqlSession open = SESSION.get();
                        if (open != null) {
                            open.close();
                            SESSION.remove();
                        }
                    }
                }));
            }
            List<MockHttpServletResponse> out = new ArrayList<>();
            for (Future<MockHttpServletResponse> future : futures) {
                out.add(future.get(90, TimeUnit.SECONDS));
            }
            return out;
        } finally {
            pool.shutdownNow();
        }
    }

    /** 逐请求的**回执行状态**（{@code data.lines[0].status}）—— 「拿到什么回执」的可断言读数。 */
    private List<String> lineStatuses(List<MockHttpServletResponse> responses) {
        List<String> out = new ArrayList<>();
        for (MockHttpServletResponse response : responses) {
            try {
                var lines = JSON.readTree(response.getContentAsString()).path("data").path("lines");
                if (lines.isArray() && !lines.isEmpty()) {
                    out.add(lines.get(0).path("status").asText());
                }
            } catch (IOException ignored) {
                // 5xx 体里没有 data.lines ⇒ 不进回执行读数（由状态码断言承担）
            }
        }
        return out;
    }

    private String errorCode(MockHttpServletResponse response) {
        try {
            return JSON.readTree(response.getContentAsString()).path("error").path("code").asText();
        } catch (IOException e) {
            return "?";
        }
    }

    /** 事件 throwable 链的「类名: 消息」串（逐层到 cause 尽头）。 */
    private static String throwableChain(ILoggingEvent event) {
        StringBuilder sb = new StringBuilder();
        for (IThrowableProxy proxy = event.getThrowableProxy(); proxy != null; proxy = proxy.getCause()) {
            sb.append(proxy.getClassName()).append(": ").append(proxy.getMessage()).append('\n');
        }
        return sb.toString();
    }

    /** 当前线程的真会话（端点每次请求一条；随任务结束关闭）。 */
    private static SqlSession session() {
        SqlSession open = SESSION.get();
        if (open == null) {
            open = factory.openSession(true);
            SESSION.set(open);
        }
        return open;
    }

    private static BatchStocktakeService serviceOn(SqlSession s) {
        return new BatchStocktakeService(batchServiceOn(s), s.getMapper(ProductSkuMapper.class),
                new StockLedgerService(s.getMapper(StockLedgerMapper.class),
                        s.getMapper(ProductSkuMapper.class)));
    }

    private static StockBatchConsumptionService batchServiceOn(SqlSession s) {
        return new StockBatchConsumptionService(s.getMapper(StockBatchMapper.class),
                gated(s.getMapper(StockBatchConsumptionMapper.class)), s.getMapper(ProductSkuMapper.class),
                s.getMapper(StockLedgerMapper.class), null, null, new BusinessClock());
    }

    /**
     * **注入面**（纯测试侧，两条）：① {@code selectList} 之后过会合点（让 TOCTOU 窗口必现）；
     * ② {@code NAIVE_INSERT} 打开时把原子闸 {@code insertStocktakeIfAbsent} 换回朴素 {@code insert}
     * （= 修前形态）。除这两处外**全部原样转发**真 mapper（写入仍走真库、唯一索引仍是真判据）。
     *
     * <p>不用 Mockito：判据必须打**真 mapper**（唯一索引的原子判定就是主判据），mock 会把
     * 「DB 判冲突」换成恒成功 ⇒ 判据当场失去意义。</p>
     */
    private static StockBatchConsumptionMapper gated(StockBatchConsumptionMapper real) {
        return (StockBatchConsumptionMapper) Proxy.newProxyInstance(
                StockBatchConsumptionMapper.class.getClassLoader(),
                new Class<?>[]{StockBatchConsumptionMapper.class},
                new InvocationHandler() {
                    @Override
                    public Object invoke(Object proxy, Method method, Object[] args) throws Throwable {
                        if ("selectList".equals(method.getName())) {
                            Object result = method.invoke(real, args);
                            CyclicBarrier barrier = preReadGate;
                            if (barrier != null) {
                                barrier.await(30, TimeUnit.SECONDS);   // 6 个请求全部越过「查」才放行
                            }
                            return result;
                        }
                        if (NAIVE_INSERT.get() && "insertStocktakeIfAbsent".equals(method.getName())
                                && args != null && args.length == 1
                                && args[0] instanceof StockBatchConsumption row) {
                            return real.insert(row);   // ← 注入：没有 ON CONFLICT ⇒ 第二条撞唯一索引
                        }
                        return method.invoke(real, args);
                    }
                });
    }

    // ══════════════════════════════════ 夹具与读数

    private static long newBatch(String batchNoPrefix) throws SQLException {
        String batchNo = batchNoPrefix + "-" + BATCH_SEQ.incrementAndGet();
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery("INSERT INTO stock_batches (tenant_id, batch_no, product_id,"
                     + " sku_id, sku_code, quantity, unit_cost) VALUES (" + TENANT_ID + ", '" + batchNo
                     + "', '" + PRODUCT_ID + "', " + SKU_ID + ", '" + SKU_CODE + "', "
                     + STOCK_BEFORE.toPlainString() + ", 12.5) RETURNING id")) {
            assertThat(rs.next()).as("批次夹具必须落库").isTrue();
            return rs.getLong(1);
        }
    }

    private static int entriesOfRun(String runId) {
        return count("SELECT count(*) FROM stock_batch_consumptions WHERE stocktake_run_id = '"
                + runId + "'");
    }

    private static BigDecimal skuStock() {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery("SELECT stock FROM product_skus WHERE id = " + SKU_ID)) {
            assertThat(rs.next()).isTrue();
            return rs.getBigDecimal(1);
        } catch (SQLException e) {
            throw new IllegalStateException(e);
        }
    }

    /** **本次 run** 的库存链读数（逐行 {@code before→after}）：销售账的不变式是「相邻行首尾相接」。 */
    private static List<String> ledgerChainOfRun(String runId) {
        List<String> out = new ArrayList<>();
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery("SELECT before_qty || '->' || after_qty"
                     + " FROM stock_ledger_entries WHERE tenant_id = " + TENANT_ID
                     + " AND ref_no IN (SELECT batch_no FROM stock_batch_consumptions"
                     + " WHERE stocktake_run_id = '" + runId + "') ORDER BY id")) {
            while (rs.next()) {
                out.add(rs.getString(1));
            }
        } catch (SQLException e) {
            throw new IllegalStateException("库存链读数失败", e);
        }
        return out;
    }

    private static int count(String sql) {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery(sql)) {
            assertThat(rs.next()).isTrue();
            return rs.getInt(1);
        } catch (SQLException e) {
            throw new IllegalStateException("读数 SQL 失败: " + sql, e);
        }
    }

    /** bootstrap 终态 schema（**不手抄列清单** ⇒ 列名 / 约束漂移会被抓）。 */
    private static String schemaSql() throws IOException {
        Path root = Paths.get(System.getProperty("user.dir")).toAbsolutePath();
        while (root != null
                && !Files.exists(root.resolve("backend/admin-api/src/main/resources/db/init/schema.sql"))) {
            root = root.getParent();
        }
        assertThat(root).as("必须能定位 backend/admin-api/src/main/resources/db/init/schema.sql").isNotNull();
        return Files.readString(root.resolve("backend/admin-api/src/main/resources/db/init/schema.sql"));
    }
}
