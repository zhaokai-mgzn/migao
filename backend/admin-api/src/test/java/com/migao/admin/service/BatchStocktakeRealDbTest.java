// case_ids: PR-119

package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.MybatisSqlSessionFactoryBuilder;
import com.baomidou.mybatisplus.extension.plugins.MybatisPlusInterceptor;
import com.baomidou.mybatisplus.extension.plugins.handler.TenantLineHandler;
import com.baomidou.mybatisplus.extension.plugins.inner.TenantLineInnerInterceptor;
import com.migao.admin.dto.BatchStockViews;
import com.migao.admin.dto.BatchStocktakeRequest;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.ProductSkuMapper;
import com.migao.admin.mapper.StockBatchConsumptionMapper;
import com.migao.admin.mapper.StockBatchMapper;
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
import org.mybatis.spring.transaction.SpringManagedTransactionFactory;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DataSourceUtils;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.transaction.support.TransactionTemplate;

import javax.sql.DataSource;
import java.io.IOException;
import java.lang.reflect.Method;
import java.math.BigDecimal;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.sql.Connection;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * 🔴 <b>按批次库存盘点（issue #5865）的**真库**判据 —— 最小录入式的七条红线里，
 * 只有真 PG 能证的四条住在这里</b>。
 *
 * <h2>为什么必须真库（mock 面结构上不可见）</h2>
 * <ol>
 *   <li><b>红线 ①「不原地改 {@code stock_batches.quantity}」</b>：mock 面只能断言「没调
 *       {@code updateById}」—— 那是**调用面**的证据；真判据是「盘点前后逐值相同」的**读数**，
 *       任何绕过 mapper 的写法（裸 SQL / 触发器 / 后续迁移）都会在此现形；</li>
 *   <li><b>红线 ⑦「盘后对账差额不得增大」</b>：{@code diff = Σ批次余量 − product_skus.stock}
 *       是**两条腿各自聚合**出来的（批次分录腿 + SKU 台账腿）—— mock 面两条腿都由测试自己喂，
 *       恒等式退化成同义反复；</li>
 *   <li><b>判据 ④「一次提交 = 一个事务」</b>：只有真的落库 + 真的回滚，才能区分
 *       「第 1 个批次也跟着不落」与「落了再删」。本判据用**注入式失败**（BEFORE INSERT 触发器）
 *       让第 2 个批次在**写入途中**炸掉，并带一条<b>对照读数</b>（无事务边界时第 1 行确实落库
 *       ⇒ 证明注入真的生效、回滚才是它没留下的原因，见 §23 G7「红证前提要自证」）；</li>
 *   <li><b>来源可区分与幂等键是** DB 对象**</b>：{@code ck_batch_consumption_source_shape}
 *       （盘点行不得带加工单号 / 扣料行必须带）与部分唯一索引
 *       {@code uk_batch_consumption_stocktake}（同一 run × 批次至多一行）在 mock 里**不存在**；
 *       本判据在**回滚事务**里把约束 / 索引摘掉 ⇒ 同一行坏数据当场能落库（零残留）。</li>
 * </ol>
 */
@DisplayName("按批次库存盘点真库判据（issue #5865）")
class BatchStocktakeRealDbTest {

    private static final Long TENANT_ID = 5865L;
    private static final String JOURNAL_PRODUCT = "acc-5865-journal";
    private static final Long JOURNAL_SKU_ID = 58651L;
    private static final String JOURNAL_SKU = "SKU-5865-J";
    private static final String REC_PRODUCT = "acc-5865-rec";
    private static final Long REC_SKU_ID = 58652L;
    private static final String REC_SKU = "SKU-5865-R";
    private static final String ZERO_PRODUCT = "acc-5865-zero";
    private static final Long ZERO_SKU_ID = 58653L;
    private static final String ZERO_SKU = "SKU-5865-Z";
    private static final String TX_PRODUCT = "acc-5865-tx";
    private static final Long TX_SKU_ID = 58654L;
    private static final String TX_SKU = "SKU-5865-T";
    private static final String OTHER_PRODUCT = "acc-5865-other";

    private static final String DOOR_WIDTH = "2.8米";

    private static PgCluster cluster;
    private static DataSource dataSource;
    private static SqlSession session;
    private static SqlSessionFactory factory;
    private static BatchStocktakeService service;
    private static StockBatchConsumptionService batchService;
    private static TransactionTemplate txTemplate;

    @BeforeAll
    static void startRealPostgresAndFixtures() throws Exception {
        cluster = PgCluster.startOrAbort();
        dataSource = cluster.dataSource();
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute(schemaSql());
            st.execute("INSERT INTO tenants (id, name, code) OVERRIDING SYSTEM VALUE VALUES ("
                    + TENANT_ID + ", 'acc-5865', 'acc-5865')");
            st.execute(product(JOURNAL_PRODUCT, "布艺遮光帘-盘点台账"));
            st.execute(sku(JOURNAL_SKU_ID, JOURNAL_PRODUCT, JOURNAL_SKU, "60"));
            st.execute(product(REC_PRODUCT, "布艺遮光帘-盘点对账"));
            // 对账判据的判别力来自「盘前差额 ≠ 0」：SKU 库存 100 而批次余量 60 ⇒ diff = -40
            // （只动一条腿的实现会让它变成 -41.5 ⇒ 判据必红）
            st.execute(sku(REC_SKU_ID, REC_PRODUCT, REC_SKU, "100"));
            st.execute(product(ZERO_PRODUCT, "布艺遮光帘-零差异"));
            st.execute(sku(ZERO_SKU_ID, ZERO_PRODUCT, ZERO_SKU, "60"));
            st.execute(product(TX_PRODUCT, "布艺遮光帘-事务"));
            st.execute(sku(TX_SKU_ID, TX_PRODUCT, TX_SKU, "120"));
            st.execute(product(OTHER_PRODUCT, "布艺遮光帘-别的货号"));
        }
        MybatisConfiguration configuration = new MybatisConfiguration();
        configuration.setMapUnderscoreToCamelCase(true);
        // 一级缓存必须是 STATEMENT 级：判据里会用裸 JDBC 改库（注入式红证 / 触发器）
        // ⇒ SESSION 级缓存会让「改完再查」读回改前的值（红证会变成假绿）。
        configuration.setLocalCacheScope(LocalCacheScope.STATEMENT);
        // 🔴 **Spring 事务工厂**而不是 JdbcTransactionFactory：判据 ④ 要在一个**真事务**里跑
        // 生产写入路径（`TransactionTemplate` 提供边界）⇒ 连接必须由 Spring 的事务同步器绑定，
        // 否则会话各自 autocommit，回滚判据会变成「测了测试自己的回滚」。
        // 生产侧同款边界由 `BatchStocktakeService#stocktake` 的 `@Transactional`（判据 4a 反射核过）提供。
        configuration.setEnvironment(new Environment("acc-5865",
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
        session = factory.openSession(true);
        batchService = batchServiceOn(session);
        service = serviceOn(session);
        txTemplate = new TransactionTemplate(new DataSourceTransactionManager(dataSource));
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

    /**
     * 在给定会话上装配批次账服务。
     *
     * <p>🔴 **每个事务判据都要新开 session**：{@code SpringManagedTransaction} 把取到的连接
     * **缓存在事务对象里**（per SqlSession）⇒ 复用同一个 session 时，第一条语句（在事务之外跑的）
     * 已经把非事务连接缓存下来了，后续语句根本不在事务里 —— 回滚判据会因此变成假绿
     * （实测：注入失败后第 1 行**照样落库**，见本文件判据 4 的对照读数）。</p>
     */
    private static BatchStocktakeService serviceOn(SqlSession s) {
        return new BatchStocktakeService(batchServiceOn(s), s.getMapper(ProductSkuMapper.class),
                new StockLedgerService(s.getMapper(StockLedgerMapper.class),
                        s.getMapper(ProductSkuMapper.class)));
    }

    private static StockBatchConsumptionService batchServiceOn(SqlSession s) {
        return new StockBatchConsumptionService(s.getMapper(StockBatchMapper.class),
                s.getMapper(StockBatchConsumptionMapper.class), s.getMapper(ProductSkuMapper.class),
                s.getMapper(StockLedgerMapper.class), null, null);
    }

    // ══════════════════════════════════ 判据 1 + 红线 ① + 红线 ⑦

    @Test
    @DisplayName("🔴 判据1+红线①⑦：盘亏 60→58.5 落一条分录 + 台账一行 + SKU 库存 -1.5；quantity 逐值不变、对账差额不增大")
    void journalKeepsQuantityAndRealignsBothLedgers() throws Exception {
        long batchId = newBatch(JOURNAL_PRODUCT, JOURNAL_SKU_ID, JOURNAL_SKU, "PC-5865-J1", "60");
        String before = quantitySnapshot();

        BatchStockViews.StocktakeResult result = service.stocktake(TENANT_ID, JOURNAL_PRODUCT,
                "PD-5865-J1", List.of(line(batchId, "58.5")));

        assertThat(result.changedCount()).isEqualTo(1);
        assertThat(result.totalDelta()).isEqualByComparingTo("-1.5");
        System.out.println("[#5865 判据1] 分录读数 = " + consumptionReadings("PD-5865-J1"));
        System.out.println("[#5865 判据1] 台账读数 = " + ledgerReadings("PC-5865-J1"));

        // 红线 ①：`stock_batches.quantity` 盘点前后**逐值相同**（全表快照，不是只看这一行）
        assertThat(quantitySnapshot()).as("批次行不可改（余量是派生值）").isEqualTo(before);

        // 分录一行：reason=stocktake + run id + delta/before/after 自洽 + 盘前=派工余量
        Map<String, String> entry = row("SELECT reason, stocktake_run_id, delta, before_qty, after_qty,"
                + " planned_meters, processing_order_no, order_item_id FROM stock_batch_consumptions"
                + " WHERE stocktake_run_id = 'PD-5865-J1'");
        assertThat(entry.get("reason")).isEqualTo("stocktake");
        assertThat(entry.get("delta")).isEqualTo("-1.5");
        assertThat(entry.get("before_qty")).isEqualTo("60.0");
        assertThat(entry.get("after_qty")).isEqualTo("58.5");
        assertThat(entry.get("planned_meters")).isEqualTo("1.5");
        // 与扣料结构性不相邻（DB 约束 ck_batch_consumption_source_shape 也是这么钉的）
        assertThat(entry.get("processing_order_no")).isNull();
        assertThat(entry.get("order_item_id")).isNull();

        // SKU 库存同步到实盘总数
        assertThat(skuStock(JOURNAL_SKU_ID)).isEqualByComparingTo("58.5");

        // 台账一行（reason=manual、note 含批次号与盘前盘后）
        Map<String, String> ledger = row("SELECT reason, ref_no, note, before_qty, after_qty, delta"
                + " FROM stock_ledger_entries WHERE ref_no = 'PC-5865-J1'");
        assertThat(ledger.get("reason")).isEqualTo("manual");
        assertThat(ledger.get("before_qty")).isEqualTo("60.0");
        assertThat(ledger.get("after_qty")).isEqualTo("58.5");
        assertThat(ledger.get("delta")).isEqualTo("-1.5");
        assertThat(ledger.get("note")).contains("PC-5865-J1").contains("60").contains("58.5");

        // 红线 ⑦：盘前差额 -40（= 批次余量 60 − SKU 库存 100）盘后**不许增大**，也不许变号/漂移。
        // 批次**先建**：`reconcile` 对「从未入库过」的 SKU 直接跳过（没有批次来源的差额无意义）⇒
        // 夹具顺序反了会让盘前读数恒为 0，判据退化成空断言。
        long recBatch = newBatch(REC_PRODUCT, REC_SKU_ID, REC_SKU, "PC-5865-R1", "60");
        BigDecimal diff = batchService.reconcile(TENANT_ID, REC_PRODUCT, null).totalDiff();
        assertThat(diff).isEqualByComparingTo("-40");
        BatchStockViews.StocktakeResult rec = service.stocktake(TENANT_ID, REC_PRODUCT, "PD-5865-R1",
                List.of(line(recBatch, "58.5")));
        assertThat(rec.totalDelta()).isEqualByComparingTo("-1.5");
        BigDecimal after = batchService.reconcile(TENANT_ID, REC_PRODUCT, null).totalDiff();
        System.out.println("[#5865 红线⑦] 盘前 diff = " + diff + "，盘后 diff = " + after);
        assertThat(after).as("盘点把批次与 SKU 一起对齐 ⇒ 差额不得因本次盘点而增大")
                .isEqualByComparingTo("-40");
        assertThat(skuStock(REC_SKU_ID)).isEqualByComparingTo("98.5");
        assertThat(remainingOf(REC_PRODUCT)).isEqualByComparingTo("58.5");
    }

    // ══════════════════════════════════ 判据 3 / 6

    @Test
    @DisplayName("判据3 delta=0 ⇒ 真库零写入（三张表的行数与 SKU 库存逐值不变）")
    void zeroDeltaWritesNothing() throws Exception {
        long batchId = newBatch(ZERO_PRODUCT, ZERO_SKU_ID, ZERO_SKU, "PC-5865-Z1", "60");
        Map<String, Integer> countsBefore = tableCounts();
        String stockBefore = skuStock(ZERO_SKU_ID).toPlainString();
        String quantityBefore = quantitySnapshot();

        BatchStockViews.StocktakeResult result = service.stocktake(TENANT_ID, ZERO_PRODUCT,
                "PD-5865-Z1", List.of(line(batchId, "60")));

        assertThat(result.changedCount()).isZero();
        assertThat(result.unchangedCount()).isEqualTo(1);
        assertThat(tableCounts()).isEqualTo(countsBefore);
        assertThat(skuStock(ZERO_SKU_ID).toPlainString()).isEqualTo(stockBefore);
        assertThat(quantitySnapshot()).isEqualTo(quantityBefore);
    }

    @Test
    @DisplayName("判据6 重放不双记：同一 run id 重跑 ⇒ 分录/台账行数与 SKU 库存不变")
    void replayWithSameRunIdDoesNotDoubleBook() throws Exception {
        long batchId = newBatch(ZERO_PRODUCT, ZERO_SKU_ID, ZERO_SKU, "PC-5865-Z2", "60");
        service.stocktake(TENANT_ID, ZERO_PRODUCT, "PD-5865-Z2", List.of(line(batchId, "58.5")));
        Map<String, Integer> afterFirst = tableCounts();
        String stockAfterFirst = skuStock(ZERO_SKU_ID).toPlainString();

        BatchStockViews.StocktakeResult replay = service.stocktake(TENANT_ID, ZERO_PRODUCT,
                "PD-5865-Z2", List.of(line(batchId, "58.5")));

        assertThat(replay.replayedCount()).isEqualTo(1);
        assertThat(replay.changedCount()).isZero();
        assertThat(tableCounts()).as("重放不得双记").isEqualTo(afterFirst);
        assertThat(skuStock(ZERO_SKU_ID).toPlainString()).isEqualTo(stockAfterFirst);
    }

    // ══════════════════════════════════ 判据 5

    @Test
    @DisplayName("判据5 非法实盘米数（-1 / 2.755）⇒ 4xx 显式拒绝且真库零写入")
    void invalidAmountIsRejectedWithoutAnyWrite() throws Exception {
        long batchId = newBatch(ZERO_PRODUCT, ZERO_SKU_ID, ZERO_SKU, "PC-5865-Z3", "60");
        Map<String, Integer> countsBefore = tableCounts();
        String quantityBefore = quantitySnapshot();
        BigDecimal stockBefore = skuStock(ZERO_SKU_ID);

        assertThatThrownBy(() -> service.stocktake(TENANT_ID, ZERO_PRODUCT, "PD-5865-Z3",
                List.of(line(batchId, "-1"))))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("实盘米数");
        assertThatThrownBy(() -> service.stocktake(TENANT_ID, ZERO_PRODUCT, "PD-5865-Z3",
                List.of(line(batchId, "2.755"))))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("1 位小数");

        assertThat(tableCounts()).isEqualTo(countsBefore);
        assertThat(quantitySnapshot()).isEqualTo(quantityBefore);
        assertThat(skuStock(ZERO_SKU_ID)).isEqualByComparingTo(stockBefore);
    }

    // ══════════════════════════════════ 判据 4：一次提交 = 一个事务

    @Test
    @DisplayName("🔴 判据4 多批次一个事务：第 2 个批次写入失败 ⇒ 第 1 个也不落、SKU 库存不变（带无事务对照读数）")
    void secondBatchFailureLeavesNothingBehind() throws Exception {
        // 生产边界（判据 4a）：`stocktake` 的方法级事务注解必须在（真库这里由 TransactionTemplate 提供）
        Method method = BatchStocktakeService.class.getMethod("stocktake", Long.class, String.class,
                String.class, List.class);
        assertThat(method.getAnnotation(org.springframework.transaction.annotation.Transactional.class))
                .as("盘点写入必须在事务边界内（批次分录 + SKU 库存同生共死）")
                .isNotNull();

        long batch1 = newBatch(TX_PRODUCT, TX_SKU_ID, TX_SKU, "PC-5865-T1", "60");
        long batch2 = newBatch(TX_PRODUCT, TX_SKU_ID, TX_SKU, "PC-5865-T2", "60");
        installFailureTrigger(batch2);
        try {
            // ① 对照：**没有**事务边界时，同一注入会留下第 1 行（证明注入真的生效 ⇒ 下面那个 0 不是空断言）
            assertThatThrownBy(() -> service.stocktake(TENANT_ID, TX_PRODUCT, "PD-5865-T-NOTX",
                    List.of(line(batch1, "58.5"), line(batch2, "58.5"))))
                    .hasMessageContaining("acc-5865 注入");
            int orphan = count("SELECT count(*) FROM stock_batch_consumptions"
                    + " WHERE stocktake_run_id = 'PD-5865-T-NOTX'");
            System.out.println("[#5865 判据4 对照] 无事务边界时残留分录行数 = " + orphan);
            assertThat(orphan).as("注入必须真的能拦住第 2 行（否则下面的事务读数没有判别力）").isEqualTo(1);
            cleanUp("DELETE FROM stock_batch_consumptions WHERE stocktake_run_id = 'PD-5865-T-NOTX'");
            cleanUp("DELETE FROM stock_ledger_entries WHERE tenant_id = " + TENANT_ID
                    + " AND note LIKE '%PC-5865-T1%'");
            cleanUp("UPDATE product_skus SET stock = 120 WHERE id = " + TX_SKU_ID);

            // ② 真判据：事务边界内，第 2 行写入失败 ⇒ 第 1 行**也不落**、SKU 库存一字不动
            Map<String, Integer> countsBefore = tableCounts();
            assertThatThrownBy(() -> txTemplate.execute(status -> {
                try (SqlSession txSession = factory.openSession(true)) {
                    return serviceOn(txSession).stocktake(TENANT_ID, TX_PRODUCT, "PD-5865-T1",
                            List.of(line(batch1, "58.5"), line(batch2, "58.5")));
                }
            })).hasMessageContaining("acc-5865 注入");
            assertThat(tableCounts()).as("第 2 个批次失败 ⇒ 第 1 个也不落").isEqualTo(countsBefore);
            assertThat(skuStock(TX_SKU_ID)).as("SKU 库存不因半个盘点而变化").isEqualByComparingTo("120");
        } finally {
            dropFailureTrigger();
        }
    }

    // ══════════════════════════════════ 来源可区分 / 幂等键是 DB 对象（带注入式红证）

    @Test
    @DisplayName("🔴 来源与幂等键由 DB 对象钉住：盘点行不得带加工单号、同一 run×批次至多一行（摘掉即能落库）")
    void sourceShapeAndIdempotencyAreEnforcedByTheDatabase() throws Exception {
        long batchId = newBatch(TX_PRODUCT, TX_SKU_ID, TX_SKU, "PC-5865-T3", "60");
        service.stocktake(TENANT_ID, TX_PRODUCT, "PD-5865-T3", List.of(line(batchId, "58.5")));

        // ① 幂等闸：同一 (tenant, run, batch) 再来一行 ⇒ 23505
        assertThat(sqlStateOf("INSERT INTO stock_batch_consumptions (tenant_id, batch_id, batch_no,"
                + " product_id, sku_id, sku_code, delta, before_qty, after_qty, formula_meters,"
                + " planned_meters, reason, stocktake_run_id, operator)"
                + " VALUES (" + TENANT_ID + ", " + batchId + ", 'PC-5865-T3', '" + TX_PRODUCT + "', "
                + TX_SKU_ID + ", '" + TX_SKU + "', -1.5, 60, 58.5, 1.5, 1.5, 'stocktake',"
                + " 'PD-5865-T3', 'system')"))
                .as("部分唯一索引 uk_batch_consumption_stocktake 必须拦住重复行").isEqualTo("23505");

        // ② 来源形状：盘点行带上加工单号 / 扣料行缺加工单号 ⇒ 23514（ck_batch_consumption_source_shape）
        assertThat(sqlStateOf("INSERT INTO stock_batch_consumptions (tenant_id, batch_id, batch_no,"
                + " product_id, sku_id, sku_code, delta, before_qty, after_qty, formula_meters,"
                + " planned_meters, reason, stocktake_run_id, processing_order_no, operator)"
                + " VALUES (" + TENANT_ID + ", " + batchId + ", 'PC-5865-T3', '" + TX_PRODUCT + "', "
                + TX_SKU_ID + ", '" + TX_SKU + "', -1.5, 60, 58.5, 1.5, 1.5, 'stocktake',"
                + " 'PD-5865-T4', 'JG-5865-0001', 'system')"))
                .as("盘点行不得与加工单扣料混淆（两族的列形状互斥）").isEqualTo("23514");
        assertThat(sqlStateOf("INSERT INTO stock_batch_consumptions (tenant_id, batch_id, batch_no,"
                + " product_id, sku_id, sku_code, delta, before_qty, after_qty, formula_meters,"
                + " planned_meters, reason, processing_order_no, operator)"
                + " VALUES (" + TENANT_ID + ", " + batchId + ", 'PC-5865-T3', '" + TX_PRODUCT + "', "
                + TX_SKU_ID + ", '" + TX_SKU + "', -1.5, 60, 58.5, 1.5, 1.5, 'processing_order',"
                + " 'JG-5865-0001', 'system')"))
                .as("扣料行必须带加工单号（既有契约不得被本单放宽）").isEqualTo("23514");

        // ③ 注入式红证：把约束 / 索引摘掉 ⇒ 同一行坏数据当场能落库（**证明拦住它的是 DB 对象本身**），
        //    整段在**回滚事务**里做 ⇒ 零残留（PG 的 DDL 是事务性的）
        String dup = "INSERT INTO stock_batch_consumptions (tenant_id, batch_id, batch_no, product_id,"
                + " sku_id, sku_code, delta, before_qty, after_qty, formula_meters, planned_meters,"
                + " reason, stocktake_run_id, operator) VALUES (" + TENANT_ID + ", " + batchId + ","
                + " 'PC-5865-T3', '" + TX_PRODUCT + "', " + TX_SKU_ID + ", '" + TX_SKU + "',"
                + " -1.5, 60, 58.5, 1.5, 1.5, 'stocktake', 'PD-5865-T3', 'system')";
        String badShape = "INSERT INTO stock_batch_consumptions (tenant_id, batch_id, batch_no,"
                + " product_id, sku_id, sku_code, delta, before_qty, after_qty, formula_meters,"
                + " planned_meters, reason, stocktake_run_id, processing_order_no, operator) VALUES ("
                + TENANT_ID + ", " + batchId + ", 'PC-5865-T3', '" + TX_PRODUCT + "', " + TX_SKU_ID
                + ", '" + TX_SKU + "', -1.5, 60, 58.5, 1.5, 1.5, 'stocktake', 'PD-5865-T5',"
                + " 'JG-5865-0001', 'system')";
        String stateWithoutGates = txTemplate.execute(status -> {
            // 🔴 DDL 必须走**事务内**的连接：`dataSource.getConnection()` 是 autocommit ⇒
            // DROP INDEX 会被当场提交（闸门永久消失、后面的复核恒绿 = 假绿）。
            Connection conn = DataSourceUtils.getConnection(dataSource);
            try (Statement st = conn.createStatement()) {
                st.execute("DROP INDEX IF EXISTS uk_batch_consumption_stocktake");
                st.execute("ALTER TABLE stock_batch_consumptions DROP CONSTRAINT IF EXISTS"
                        + " ck_batch_consumption_source_shape");
            } catch (SQLException e) {
                throw new IllegalStateException(e);
            }
            String dupState = sqlStateOn(conn, dup);
            String shapeState = sqlStateOn(conn, badShape);
            status.setRollbackOnly();
            DataSourceUtils.releaseConnection(conn, dataSource);
            return dupState + "/" + shapeState;
        });
        System.out.println("[#5865 判据②注入] 摘掉闸门后的 SQLSTATE = " + stateWithoutGates);
        assertThat(stateWithoutGates).as("摘掉闸门后两行坏数据都必须**能**落库")
                .isEqualTo("00000/00000");
        // 闸门仍在（回滚生效）⇒ 同一行又回到被拒状态
        assertThat(sqlStateOf(dup)).isEqualTo("23505");
        assertThat(sqlStateOf(badShape)).isEqualTo("23514");
    }

    // ══════════════════════════════════ 夹具与读数

    private static BatchStocktakeRequest.Line line(long batchId, String meters) {
        BatchStocktakeRequest.Line l = new BatchStocktakeRequest.Line();
        l.setBatchId(batchId);
        l.setActualMeters(new BigDecimal(meters));
        return l;
    }

    private static long newBatch(String productId, long skuId, String skuCode, String batchNo,
                                 String meters) throws SQLException {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery("INSERT INTO stock_batches (tenant_id, batch_no, product_id,"
                     + " sku_id, sku_code, quantity, unit_cost) VALUES (" + TENANT_ID + ", '" + batchNo
                     + "', '" + productId + "', " + skuId + ", '" + skuCode + "', " + meters
                     + ", 12.5) RETURNING id")) {
            assertThat(rs.next()).as("批次夹具必须落库").isTrue();
            return rs.getLong(1);
        }
    }

    private static String product(String productId, String name) {
        return "INSERT INTO products (id, tenant_id, name) VALUES ('" + productId + "', " + TENANT_ID
                + ", '" + name + "')";
    }

    private static String sku(long skuId, String productId, String skuCode, String stock) {
        return "INSERT INTO product_skus (id, tenant_id, product_id, door_width, price, stock, sku_code)"
                + " OVERRIDING SYSTEM VALUE VALUES (" + skuId + ", " + TENANT_ID + ", '" + productId
                + "', '" + DOOR_WIDTH + "', 100, " + stock + ", '" + skuCode + "')";
    }

    /** 盘亏/盘盈判据的注入面：让**指定批次**的分录写入当场抛错（写入途中失败，而不是预校验失败）。 */
    private static void installFailureTrigger(long batchId) {
        cleanUp("CREATE OR REPLACE FUNCTION acc5865_fail_batch() RETURNS trigger AS $$"
                + " BEGIN IF NEW.batch_id = " + batchId + " AND NEW.reason = 'stocktake' THEN"
                + " RAISE EXCEPTION 'acc-5865 注入：第 2 个批次写入失败'; END IF; RETURN NEW; END $$"
                + " LANGUAGE plpgsql");
        cleanUp("CREATE TRIGGER acc5865_fail_batch_trg BEFORE INSERT ON stock_batch_consumptions"
                + " FOR EACH ROW EXECUTE FUNCTION acc5865_fail_batch()");
    }

    private static void dropFailureTrigger() {
        cleanUp("DROP TRIGGER IF EXISTS acc5865_fail_batch_trg ON stock_batch_consumptions");
        cleanUp("DROP FUNCTION IF EXISTS acc5865_fail_batch()");
    }

    private static void cleanUp(String sql) {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute(sql);
        } catch (SQLException e) {
            throw new IllegalStateException("夹具 SQL 失败: " + sql, e);
        }
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

    /** 单行读数（列名 → 原串；NULL ⇒ null）。 */
    private static Map<String, String> row(String sql) {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery(sql)) {
            Map<String, String> out = new LinkedHashMap<>();
            assertThat(rs.next()).as("读数必须命中一行: " + sql).isTrue();
            for (int i = 1; i <= rs.getMetaData().getColumnCount(); i++) {
                out.put(rs.getMetaData().getColumnLabel(i).toLowerCase(), rs.getString(i));
            }
            return out;
        } catch (SQLException e) {
            throw new IllegalStateException("读数 SQL 失败: " + sql, e);
        }
    }

    /** 在给定连接上执行一条 SQL，回它的 SQLSTATE（成功 = 00000）—— 事务内探测用。 */
    private static String sqlStateOn(Connection conn, String sql) {
        try (Statement st = conn.createStatement()) {
            st.execute(sql);
            return "00000";
        } catch (SQLException e) {
            return e.getSQLState();
        }
    }

    /** 执行一条会失败的 SQL，回它的 SQLSTATE（成功 = 00000）。 */
    private static String sqlStateOf(String sql) {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute(sql);
            return "00000";
        } catch (SQLException e) {
            return e.getSQLState();
        }
    }

    private static BigDecimal skuStock(long skuId) {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery("SELECT stock FROM product_skus WHERE id = " + skuId)) {
            assertThat(rs.next()).isTrue();
            return rs.getBigDecimal(1);
        } catch (SQLException e) {
            throw new IllegalStateException(e);
        }
    }

    private static BigDecimal remainingOf(String productId) {
        List<BatchStockViews.BatchRemaining> rows = batchService.remaining(TENANT_ID, productId, null, false);
        BigDecimal total = BigDecimal.ZERO;
        for (BatchStockViews.BatchRemaining r : rows) {
            total = total.add(r.remainingMeters());
        }
        return total;
    }

    /** 红线 ① 的读数：**全表**批次数量的原串快照（逐值可比，不经过任何实体映射）。 */
    private static String quantitySnapshot() {
        List<String> rows = new ArrayList<>();
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery("SELECT id || '=' || quantity FROM stock_batches"
                     + " ORDER BY id")) {
            while (rs.next()) {
                rows.add(rs.getString(1));
            }
        } catch (SQLException e) {
            throw new IllegalStateException(e);
        }
        return String.join("|", rows);
    }

    private static Map<String, Integer> tableCounts() {
        Map<String, Integer> out = new LinkedHashMap<>();
        out.put("stock_batch_consumptions", count("SELECT count(*) FROM stock_batch_consumptions"));
        out.put("stock_ledger_entries", count("SELECT count(*) FROM stock_ledger_entries"));
        out.put("stock_batches", count("SELECT count(*) FROM stock_batches"));
        return out;
    }

    private static String consumptionReadings(String runId) {
        List<String> rows = new ArrayList<>();
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery("SELECT batch_no || ' ' || before_qty || '->' || after_qty"
                     + " || ' delta=' || delta || ' reason=' || reason FROM stock_batch_consumptions"
                     + " WHERE stocktake_run_id = '" + runId + "' ORDER BY id")) {
            while (rs.next()) {
                rows.add(rs.getString(1));
            }
        } catch (SQLException e) {
            throw new IllegalStateException(e);
        }
        return String.join("; ", rows);
    }

    private static String ledgerReadings(String refNo) {
        List<String> rows = new ArrayList<>();
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery("SELECT before_qty || '->' || after_qty || ' ' || note"
                     + " FROM stock_ledger_entries WHERE ref_no = '" + refNo + "' ORDER BY id")) {
            while (rs.next()) {
                rows.add(rs.getString(1));
            }
        } catch (SQLException e) {
            throw new IllegalStateException(e);
        }
        return String.join("; ", rows);
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
