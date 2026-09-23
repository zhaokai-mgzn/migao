// case_ids: PR-093, PR-094, PR-095, PR-096
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.MybatisSqlSessionFactoryBuilder;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.MybatisPlusInterceptor;
import com.baomidou.mybatisplus.extension.plugins.handler.TenantLineHandler;
import com.baomidou.mybatisplus.extension.plugins.inner.TenantLineInnerInterceptor;
import com.migao.admin.dto.SavingMetricViews;
import com.migao.admin.entity.StockBatchConsumption;
import com.migao.admin.mapper.ProductSkuMapper;
import com.migao.admin.mapper.StockBatchConsumptionMapper;
import com.migao.admin.mapper.StockBatchMapper;
import net.sf.jsqlparser.expression.Expression;
import net.sf.jsqlparser.expression.LongValue;
import org.apache.ibatis.mapping.Environment;
import org.apache.ibatis.session.SqlSession;
import org.apache.ibatis.session.SqlSessionFactory;
import org.apache.ibatis.transaction.jdbc.JdbcTransactionFactory;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.datasource.DriverManagerDataSource;

import javax.sql.DataSource;
import java.math.BigDecimal;
import java.math.RoundingMode;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.sql.Connection;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 🔴 <b>省料度量 L2/L3 汇总读面的**真库**判据（issue #5159 剩余范围）</b>。
 *
 * <h2>为什么必须真库（Mockito 测不出来）</h2>
 * 本单的判据全是<b>跨表聚合的口径问题</b>：①「看板汇总 == Σ 逐单」比的是
 * Java 侧逐行取整与 SQL 侧 {@code SUM(ROUND(...))} 是否**逐值相等**；
 * ②「存量单列」比的是 {@code stock_batches → inbound_orders.source} 这条 join 真的按
 * {@code opening} 分了组；④「空数据不冒充 0」比的是真库在没有行时 SQL 回的是 {@code NULL}
 * 还是 {@code 0}。mock 只会证明「调了哪个方法」——<b>SQL 的取整位置、join 的方向、
 * 空集上的聚合语义在 mock 面结构上不可见</b>（同族教训见 #5141 / #5148）。
 *
 * <h2>判据（每条都带**同参数的对照读数**，不是「跑了就算」）</h2>
 * <ol>
 *   <li><b>汇总一致</b>（PR-093）：看板合计 == 逐单读面 {@code Σ saved_meters} /
 *       {@code Σ saved_amount} <b>逐值相等</b>。判别性做法：夹具里特意放两行
 *       ({@code 0.1 米 × 12.345 元})「逐行先取整」= {@code 2.46}，
 *       「整段求和再取整」= {@code 2.47} —— 两个读数在同一个测试里对照打印，
 *       ⇒ 「逐值相等」这句话不是自说自话（红证：改成两套口径 ⇒ 红）。</li>
 *   <li><b>存量单列</b>（PR-094）：{@code source='opening'} 的批次独立成组、独立占比；
 *       <b>混入「切换后」⇒ 红</b>（对照读数：混入时切换后占比 = 1/4 = 0.25，
 *       本读面必须是 0/2 = 0 —— 两个数在同一个测试里都在）。</li>
 *   <li><b>空数据不冒充 0</b>（PR-095）：空租户 ⇒ 占比 / 合计 / 比率一律 {@code null}
 *       （**不是 0**）；同时非空租户里「真 0」（分母 &gt; 0 且分子 = 0）必须回 {@code 0.0000}
 *       —— 两者可区分，才不会把「没有浪费」与「还没有数据」读成同一件事。
 *       分母为 0（有消耗、但明细行无面积）⇒ 单位产出消耗 {@code null}。</li>
 *   <li><b>单价口径</b>（PR-096）：改批次均价后历史读数<b>一字不变</b>（用的是行内快照）。</li>
 *   <li><b>不损失客户</b>（PR-096 同条）：两次读面调用之后，SKU 库存 / 订单金额 /
 *       SKU 台账行数<b>逐值不变</b>（读面不得写任何东西）。</li>
 * </ol>
 *
 * <h2>环境</h2>
 * 一次性真 PG 集群（{@link PgCluster}，与 #5158 的真库判据**共用同一个装配**，
 * 不再复制第三份），schema 取自 {@code docs/sql/schema.sql}（bootstrap 终态，
 * **不手抄列清单** ⇒ 列名/约束漂移会被抓），并**装上与生产同源的多租户拦截器**
 * （少了它就只测了 mapper 原文 —— 而本单新增的三条 SQL 全带 join 与子查询，
 * 正是拦截器重写的受力面）。缺 PG 二进制 ⇒ {@link PgCluster#startOrAbort()}：
 * CI（{@code MIGAO_REQUIRE_REALDB=1}）⇒ 判红；本机未设该标记 ⇒ 显式 skip（「没跑」长得像「没跑」，不是通过）。
 */
@DisplayName("#5159 真库守卫：省料度量 L2/L3 汇总读面（汇总一致 / 存量单列 / 空数据不冒充 0）")
class SavingMetricsBoardRealDbTest {

    private static final Long TENANT_ID = 5159L;
    /** 空租户：一条批次、一条入库、一条消耗都没有 —— 判据 3「空数据不冒充 0」的对照面。 */
    private static final Long EMPTY_TENANT_ID = 51590L;
    private static final Long SKU_ID = 5159L;
    private static final String PRODUCT_ID = "acc-5159-prod";
    private static final String SKU_CODE = "SKU-A";
    private static final String DOOR_WIDTH = "2.8米";
    private static final String MATERIAL_KEY = PRODUCT_ID + "|" + SKU_CODE;
    /** 2026-09 的消耗时间桶（本地时区 Asia/Shanghai） */
    private static final String PERIOD_SEP = "2026-09";
    /** 2026-08 的消耗时间桶（存量批次的消耗落在上一个月） */
    private static final String PERIOD_AUG = "2026-08";
    /** 2026-10：有消耗、但明细行没有面积 ⇒ 单位产出消耗读不出（判据 3） */
    private static final String PERIOD_OCT = "2026-10";

    private static PgCluster cluster;
    private static DataSource dataSource;
    private static SqlSession session;
    private static StockBatchConsumptionService service;
    private static StockBatchConsumptionMapper consumptionMapper;

    @BeforeAll
    static void startRealPostgresAndFixtures() throws Exception {
        cluster = PgCluster.startOrAbort();
        dataSource = cluster.dataSource();
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute(schemaSql());
            st.execute("INSERT INTO tenants (id, name, code) OVERRIDING SYSTEM VALUE VALUES ("
                    + TENANT_ID + ", 'acc-5159', 'acc-5159'), ("
                    + EMPTY_TENANT_ID + ", 'acc-5159-empty', 'acc-5159-empty')");
            st.execute("INSERT INTO products (id, tenant_id, name) VALUES ('" + PRODUCT_ID + "', "
                    + TENANT_ID + ", '布艺遮光帘A')");
            st.execute("INSERT INTO product_skus (id, tenant_id, product_id, door_width, price, stock,"
                    + " sku_code) OVERRIDING SYSTEM VALUE VALUES (" + SKU_ID + ", " + TENANT_ID + ", '"
                    + PRODUCT_ID + "', '" + DOOR_WIDTH + "', 100, 60, '" + SKU_CODE + "')");
            st.execute("INSERT INTO orders (id, tenant_id, order_no, total_amount) VALUES "
                    + "('acc-5159-order', " + TENANT_ID + ", 'ORD-5159', 1000.00)");
            // 三行明细：面积 3.00 / 1.80 / 1.00（= 窗宽 × 窗高，米²）—— L3 的分母口径
            st.execute("INSERT INTO order_items (id, tenant_id, order_id, product_id, product_name,"
                    + " quantity, unit_price, width, height, subtotal) VALUES "
                    + "('acc-5159-i1', " + TENANT_ID + ", 'acc-5159-order', '" + PRODUCT_ID + "', '帘A', 3, 100, 2.00, 1.50, 300),"
                    + "('acc-5159-i2', " + TENANT_ID + ", 'acc-5159-order', '" + PRODUCT_ID + "', '帘A', 2, 100, 1.50, 1.20, 200),"
                    + "('acc-5159-i3', " + TENANT_ID + ", 'acc-5159-order', '" + PRODUCT_ID + "', '帘A', 2, 100, 1.00, 1.00, 200)");
            // 两张入库单：purchase（切换后）/ opening（存量导入）—— 来源组就是判据 2 的分组键
            st.execute("INSERT INTO inbound_orders (id, tenant_id, inbound_no, inbound_date, status,"
                    + " source) VALUES "
                    + "('acc-5159-inb-p', " + TENANT_ID + ", 'RK-5159-P', DATE '2026-09-10', 'posted', 'purchase'),"
                    + "('acc-5159-inb-o', " + TENANT_ID + ", 'RK-5159-O', DATE '2026-08-01', 'posted', 'opening')");
            // 四个批次：P1/P2 = 切换后；O1（会被用到 ≤0.2 档）/O2（无均价） = 存量导入
            st.execute("INSERT INTO stock_batches (tenant_id, batch_no, product_id, sku_id, sku_code,"
                    + " inbound_order_id, inbound_no, quantity, unit_cost, received_date) VALUES "
                    + "(" + TENANT_ID + ", 'PC-5159-P1', '" + PRODUCT_ID + "', " + SKU_ID + ", '" + SKU_CODE + "', 'acc-5159-inb-p', 'RK-5159-P', 10.0, 12.5000, DATE '2026-09-05'),"
                    + "(" + TENANT_ID + ", 'PC-5159-P2', '" + PRODUCT_ID + "', " + SKU_ID + ", '" + SKU_CODE + "', 'acc-5159-inb-p', 'RK-5159-P', 5.0, 12.3450, DATE '2026-09-06'),"
                    + "(" + TENANT_ID + ", 'PC-5159-O1', '" + PRODUCT_ID + "', " + SKU_ID + ", '" + SKU_CODE + "', 'acc-5159-inb-o', 'RK-5159-O', 5.0, 6.0000, DATE '2026-08-01'),"
                    + "(" + TENANT_ID + ", 'PC-5159-O2', '" + PRODUCT_ID + "', " + SKU_ID + ", '" + SKU_CODE + "', 'acc-5159-inb-o', 'RK-5159-O', 30.0, NULL, DATE '2026-08-01')");
            // 消耗行（直插 SQL：created_at 必须落在指定月份 ⇒ 时间桶判据才是确定的）
            //   时间桶 2026-09 / purchase：saved 3.0 + 2.4 + 0.1 + 0.1
            //   时间桶 2026-08 / opening ：saved 4.8 + 1.0（后者无均价）
            //   时间桶 2026-10 / purchase：saved 1.0 且明细行不存在 ⇒ 分母 0
            st.execute(consumption("JG-5159-A", "PC-5159-P1", "acc-5159-i1", "-3.0", "10.0", "7.0", "6.0", "3.0", "12.5000", "2026-09-15 10:00:00+08"));
            st.execute(consumption("JG-5159-B", "PC-5159-P1", "acc-5159-i2", "-2.4", "7.0", "4.6", "4.0", "1.6", "12.5000", "2026-09-16 10:00:00+08"));
            st.execute(consumption("JG-5159-E", "PC-5159-P2", "acc-5159-i3", "-0.1", "5.0", "4.9", "0.2", "0.1", "12.3450", "2026-09-17 10:00:00+08"));
            st.execute(consumption("JG-5159-F", "PC-5159-P2", "acc-5159-i3", "-0.1", "4.9", "4.8", "0.2", "0.1", "12.3450", "2026-09-18 10:00:00+08"));
            st.execute(consumption("JG-5159-C", "PC-5159-O1", "acc-5159-i1", "-4.8", "5.0", "0.2", "6.0", "1.2", "6.0000", "2026-08-20 10:00:00+08"));
            st.execute(consumption("JG-5159-D", "PC-5159-O2", "acc-5159-i2", "-1.0", "30.0", "29.0", "2.0", "1.0", "NULL", "2026-08-21 10:00:00+08"));
            st.execute(consumption("JG-5159-G", "PC-5159-P2", "acc-5159-ghost", "-2.0", "4.8", "2.8", "3.0", "2.0", "5.0000", "2026-10-05 10:00:00+08"));
        }
        MybatisConfiguration configuration = new MybatisConfiguration();
        configuration.setMapUnderscoreToCamelCase(true);
        configuration.setEnvironment(new Environment("acc-5159", new JdbcTransactionFactory(), dataSource));
        // 多租户拦截器**必须在场**：本单新增的三条 SQL 带 join / 子查询 / 聚合，
        // 正是拦截器重写 SQL 的受力面（少了它 = 只测了 mapper 原文）
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
                ProductSkuMapper.class)) {
            configuration.addMapper(mapper);
        }
        SqlSessionFactory factory = new MybatisSqlSessionFactoryBuilder().build(configuration);
        session = factory.openSession(true);
        consumptionMapper = session.getMapper(StockBatchConsumptionMapper.class);
        service = new StockBatchConsumptionService(session.getMapper(StockBatchMapper.class),
                consumptionMapper, session.getMapper(ProductSkuMapper.class), null, null,
                // 余料腿显式不装（V122 / issue #5146）：本判据覆盖的是**批次账读面**，余料是附加事实
                // —— null ⇒ 不登记余料，批次账行为与 #5158 逐字相同
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

    /**
     * 每条判据开始前清掉 MyBatis 的**一级缓存**（按 SqlSession）。
     *
     * <p>🔴 这一行不是装饰：同一个 {@link SqlSession} 里「同一条语句 + 同一组参数」会直接回缓存、
     * <b>不再打库</b>。而判据 5 要的正是「改完批次均价<b>再读一次</b>」—— 不清缓存就会拿到改前的
     * 缓存值 ⇒ 断言恒真 = <b>空断言</b>。</p>
     *
     * <p><b>实证（本单红证驱动实测）</b>：把金额腿注入变异「读批次<b>现价</b>
     * {@code b.unit_cost} 而不是行内快照」时，本判据<b>依然绿</b>；补上本行后同一变异立刻变红
     * （读数 103.76 → 1227.4）。</p>
     *
     * <p>生产等价物 = 「每一次请求一个新的 SqlSession」（读面是独立请求）⇒ 清缓存是<b>忠实模拟</b>，
     * 不是为了让判据变红而加的。</p>
     */
    @BeforeEach
    void clearLocalCacheSoEachReadHitsTheDatabase() {
        session.clearCache();
    }

    // ────────────────────────────────────────────── 判据 1（PR-093）：汇总一致

    @Test
    @DisplayName("🔴 判据1：看板汇总 == Σ 逐单 saved_*（逐值相等）；判别性对照 = 求和再取整会差一分")
    void boardTotalsEqualPerLineSum() {
        SavingMetricViews.Board board = service.savingBoard(TENANT_ID, null, "month");
        List<StockBatchConsumption> lines = consumptionMapper.selectList(
                new LambdaQueryWrapper<StockBatchConsumption>().eq(StockBatchConsumption::getTenantId,
                        TENANT_ID));

        BigDecimal perLineMeters = BigDecimal.ZERO;
        BigDecimal perLineAmount = BigDecimal.ZERO;
        BigDecimal naiveMeters = BigDecimal.ZERO;
        for (StockBatchConsumption line : lines) {
            perLineMeters = perLineMeters.add(line.getSavedMeters());
            if (line.getSavedAmount() != null) {
                perLineAmount = perLineAmount.add(line.getSavedAmount());
            }
            // 「整段求和再取整」= 判据 1 明令禁止的第二套口径（逐值对照读数）
            if (line.getUnitCost() != null) {
                naiveMeters = naiveMeters.add(line.getSavedMeters().multiply(line.getUnitCost()));
            }
        }
        BigDecimal naiveAmount = naiveMeters.setScale(2, RoundingMode.HALF_UP);
        System.out.println("[#5159 判别性实验] 逐行取整求和 = " + perLineAmount
                + " / 整段求和再取整 = " + naiveAmount);

        assertThat(lines).as("夹具本身必须非空（否则下面的等式是空的）").hasSize(7);
        assertThat(perLineAmount)
                .as("🔴 判别性：两套口径真的会差（不然这条判据没有判别力）")
                .isNotEqualByComparingTo(naiveAmount);
        assertThat(board.total().savedMeters())
                .as("看板合计 == Σ 逐单 saved_meters（逐值相等）")
                .isEqualByComparingTo(perLineMeters);
        assertThat(board.total().savedAmount())
                .as("🔴 看板合计 == Σ 逐单 saved_amount（**逐行取整**那套，不是整段求和）")
                .isEqualByComparingTo(perLineAmount);
        assertThat(board.total().unknownCostLines())
                .as("有一行没有均价 ⇒ 显式回计数，读的人才不会把「读不出」当成「只省了这么点」")
                .isEqualTo(1);

        // 分组腿也逐值相等（不是「合计碰巧对上」）
        BigDecimal grouped = BigDecimal.ZERO;
        for (SavingMetricViews.SavedGroup g : board.savedGroups()) {
            assertThat(g.lineCount()).as("空组的合计必须是 null，不得造一个 0 组").isPositive();
            grouped = grouped.add(g.savedMeters());
        }
        assertThat(grouped).as("Σ 分组 == Σ 逐单").isEqualByComparingTo(perLineMeters);
    }

    // ────────────────────────────────────────────── 判据 2（PR-094）：存量单列

    @Test
    @DisplayName("🔴 判据2：source='opening' 独立成组不混入切换后（混入 = 0.25，本读面 = 0.00）")
    void openingCohortIsListedSeparately() {
        SavingMetricViews.Board board = service.savingBoard(TENANT_ID, null, "month");
        Map<String, SavingMetricViews.CohortSummary> byCohort = new java.util.LinkedHashMap<>();
        for (SavingMetricViews.CohortSummary c : board.cohorts()) {
            byCohort.put(c.cohort(), c);
        }

        assertThat(byCohort.keySet())
                .as("三组恒在（含 opening）—— 「没有这一组」与「这一组是空的」必须可区分")
                .containsExactlyInAnyOrder(SavingMetricViews.COHORT_PURCHASE,
                        SavingMetricViews.COHORT_OPENING, SavingMetricViews.COHORT_UNKNOWN);

        SavingMetricViews.CohortSummary purchase = byCohort.get(SavingMetricViews.COHORT_PURCHASE);
        SavingMetricViews.CohortSummary opening = byCohort.get(SavingMetricViews.COHORT_OPENING);
        assertThat(purchase.batchCount()).as("切换后批次 = P1/P2（**不含**存量 O1/O2）").isEqualTo(2);
        assertThat(opening.batchCount()).as("存量导入批次 = O1/O2").isEqualTo(2);
        assertThat(opening.opening()).as("分组必须自证是存量组（页面据此单列渲染）").isTrue();
        assertThat(purchase.opening()).isFalse();

        assertThat(opening.le0_2Share())
                .as("存量组自己的 ≤0.2 占比 = 1/2（O1 余 0.2）").isEqualByComparingTo("0.5000");
        System.out.println("[#5159 判别性实验] 切换后占比 = " + purchase.le0_2Share()
                + " / 存量占比 = " + opening.le0_2Share()
                + " / 若把存量混进切换后 = " + new BigDecimal("1").divide(new BigDecimal("4"), 4,
                        RoundingMode.HALF_UP));
        assertThat(purchase.le0_2Share())
                .as("🔴 切换后占比 = 0/2（P1 剩 4.6 / P2 剩 4.8 都在 >1 档）；"
                        + "红证：把存量混进来会变成 1/4 = 0.25 ⇒ 本条必红")
                .isEqualByComparingTo("0.0000");
        assertThat(purchase.le0_2Share()).as("红证对照：不得等于混入口径").isNotEqualByComparingTo("0.25");

        // 分组腿：存量批次必须落在 cohort=opening 的独立组里（不是同一个 key 里加总）
        List<SavingMetricViews.BatchGroup> openingGroups = board.batchGroups().stream()
                .filter(g -> SavingMetricViews.COHORT_OPENING.equals(g.cohort())).toList();
        assertThat(openingGroups).as("存量组必须独立成组（判据 2 的落点）").hasSize(1);
        assertThat(openingGroups.get(0).batchCount()).isEqualTo(2);
        assertThat(openingGroups.get(0).period()).as("时间维度 = 批次收货月（存量在 2026-08）")
                .isEqualTo(PERIOD_AUG);
        assertThat(board.batchGroups().stream()
                .filter(g -> SavingMetricViews.COHORT_OPENING.equals(g.cohort()))
                .noneMatch(g -> g.batchCount() == 4))
                .as("🔴 不得存在「存量 + 切换后」混在一起的组").isTrue();

        // 省料腿同样按来源分组：存量批次的消耗（4.8 + 1.0）落在 opening 组
        SavingMetricViews.SavedGroup openingSaved = board.savedGroups().stream()
                .filter(g -> SavingMetricViews.COHORT_OPENING.equals(g.cohort()))
                .findFirst().orElseThrow();
        assertThat(openingSaved.savedMeters()).isEqualByComparingTo("5.8");
        assertThat(opening.unknownCostLines()).as("O2 那行没有均价").isEqualTo(1);
    }

    // ────────────────────────────────────────────── 判据 3（PR-095）：空数据不冒充 0

    @Test
    @DisplayName("🔴 判据3：空租户 ⇒ 占比/合计/比率一律 无数据(null)；真 0 与无数据必须可区分")
    void emptyTenantReturnsNoDataNotZero() {
        SavingMetricViews.Board empty = service.savingBoard(EMPTY_TENANT_ID, null, "month");
        for (SavingMetricViews.CohortSummary c : empty.cohorts()) {
            assertThat(c.batchCount()).as("计数为 0 是事实").isZero();
            assertThat(c.le0_2Share())
                    .as("🔴 无批次 ⇒ 占比必须是 **无数据(null)**，不得回落成 0（0 会被读成「没有浪费」）")
                    .isNull();
            assertThat(c.savedMeters()).as("没有任何消耗行 ⇒ 省料合计也是无数据").isNull();
            assertThat(c.savedAmount()).isNull();
            assertThat(c.remainingMeters()).isNull();
            assertThat(c.buckets()).allSatisfy(b -> {
                assertThat(b.batchCount()).isZero();
                assertThat(b.share()).as("空档的占比同样是无数据，不是 0").isNull();
                assertThat(b.remainingMeters()).isNull();
            });
        }
        assertThat(empty.total().savedMeters()).isNull();
        assertThat(empty.total().savedAmount()).isNull();
        assertThat(empty.total().le0_2Share()).isNull();
        assertThat(empty.batchGroups()).isEmpty();
        assertThat(empty.savedGroups()).isEmpty();

        // 对照读数：非空租户里「分母 > 0 且分子 = 0」必须回 **0.0000**（真 0 ≠ 无数据）
        SavingMetricViews.Board real = service.savingBoard(TENANT_ID, null, "month");
        SavingMetricViews.CohortSummary purchase = real.cohorts().stream()
                .filter(c -> SavingMetricViews.COHORT_PURCHASE.equals(c.cohort()))
                .findFirst().orElseThrow();
        assertThat(purchase.le0_2Share())
                .as("真 0（2 个批次里 0 个落 ≤0.2 档）必须是 0.0000 而不是 null —— "
                        + "两者可区分，才不会把「没有浪费」与「还没有数据」读成同一件事")
                .isEqualByComparingTo("0.0000");

        // L3：空租户 ⇒ 无趋势点、合计为 null（不是 0 米）
        SavingMetricViews.Trend emptyTrend = service.savingTrend(EMPTY_TENANT_ID, "month");
        assertThat(emptyTrend.points()).isEmpty();
        assertThat(emptyTrend.purchasedTotalMeters()).isNull();
        assertThat(emptyTrend.consumedTotalMeters()).isNull();
        assertThat(emptyTrend.openingTotalMeters()).isNull();
    }

    @Test
    @DisplayName("🔴 判据3(L3)：分母为 0（有消耗但明细行无面积）⇒ 单位产出消耗 无数据(null)")
    void unitOutputRatioIsNullWhenDenominatorIsZero() {
        SavingMetricViews.Trend trend = service.savingTrend(TENANT_ID, "month");
        Map<String, SavingMetricViews.ConsumptionPoint> byPeriod = new java.util.LinkedHashMap<>();
        for (SavingMetricViews.ConsumptionPoint p : trend.points()) {
            byPeriod.put(p.period(), p);
        }
        assertThat(byPeriod.keySet()).as("三个时间桶都在").contains(PERIOD_AUG, PERIOD_SEP, PERIOD_OCT);

        SavingMetricViews.ConsumptionPoint sep = byPeriod.get(PERIOD_SEP);
        assertThat(sep.outputAreaM2()).as("分母 = 2026-09 去重后的明细面积：i1 3.00 + i2 1.80 + i3 1.00")
                .isEqualByComparingTo("5.80");
        assertThat(sep.outputLines()).as("i3 有两行扣减 ⇒ 去重后只算一次（否则分母虚高、效率被说好）")
                .isEqualTo(3);
        assertThat(sep.metersPerM2()).as("单位产出消耗 = (3.0+1.6+0.1+0.1) / 5.80")
                .isEqualByComparingTo("0.8276");

        SavingMetricViews.ConsumptionPoint oct = byPeriod.get(PERIOD_OCT);
        assertThat(oct.consumedMeters()).as("这一桶确实有消耗").isEqualByComparingTo("2.0");
        assertThat(oct.outputAreaM2()).as("明细行不存在 ⇒ 分母 0").isEqualByComparingTo("0");
        assertThat(oct.metersPerM2())
                .as("🔴 分母 0 ⇒ 比率必须是 **无数据(null)**，不得回落成 0（会读成「一点布都没用」）")
                .isNull();

        // 指标②：采购腿**不含**存量导入
        assertThat(sep.purchasedMeters()).as("② 2026-09 采购入库 = P1 10 + P2 5").isEqualByComparingTo("15.0");
        assertThat(byPeriod.get(PERIOD_AUG).purchasedMeters())
                .as("🔴 2026-08 只有存量导入 ⇒ 采购腿必须是**无数据**，不得把 35 米算成这个月的采购")
                .isNull();
        assertThat(byPeriod.get(PERIOD_AUG).openingMeters())
                .as("存量导入单列：O1 5 + O2 30").isEqualByComparingTo("35.0");
        assertThat(trend.purchasedTotalMeters())
                .as("全期采购合计 = P1 10 + P2 5（2026-10 那桶只有消耗、没有采购 ⇒ 不进指标②）")
                .isEqualByComparingTo("15.0");
        assertThat(trend.openingTotalMeters()).isEqualByComparingTo("35.0");
    }

    // ────────────────────────────────────────────── 判据 5 / 6（PR-096）：单价口径 + 不损失客户

    @Test
    @DisplayName("🔴 判据5/6：改批次均价后历史读数不变；两次读面调用后客户面账一字不动")
    void snapshotCostAndNoCustomerRegression() throws Exception {
        SavingMetricViews.Board before = service.savingBoard(TENANT_ID, null, "month");
        SavingMetricViews.Trend beforeTrend = service.savingTrend(TENANT_ID, "month");
        String stockBefore = scalar("SELECT stock FROM product_skus WHERE id = " + SKU_ID);
        String orderBefore = scalar("SELECT total_amount FROM orders WHERE id = 'acc-5159-order'");
        String ledgerBefore = scalar("SELECT COUNT(*) FROM stock_ledger_entries WHERE tenant_id = " + TENANT_ID);

        exec("UPDATE stock_batches SET unit_cost = 99 WHERE tenant_id = " + TENANT_ID);

        session.clearCache(); // 改完再读：必须真的打库（否则读回改前的缓存值 = 空断言）
        SavingMetricViews.Board after = service.savingBoard(TENANT_ID, null, "month");
        SavingMetricViews.Trend afterTrend = service.savingTrend(TENANT_ID, "month");
        assertThat(after.total().savedAmount())
                .as("🔴 用的是**当时**该批次均价（行内快照）⇒ 换价后历史读数一字不变")
                .isEqualByComparingTo(before.total().savedAmount());
        assertThat(after.total().savedMeters()).isEqualByComparingTo(before.total().savedMeters());
        assertThat(afterTrend.purchasedTotalMeters())
                .isEqualByComparingTo(beforeTrend.purchasedTotalMeters());

        assertThat(scalar("SELECT stock FROM product_skus WHERE id = " + SKU_ID))
                .as("不损失客户：SKU 库存逐值不变").isEqualTo(stockBefore);
        assertThat(scalar("SELECT total_amount FROM orders WHERE id = 'acc-5159-order'"))
                .as("不损失客户：订单金额逐值不变").isEqualTo(orderBefore);
        assertThat(scalar("SELECT COUNT(*) FROM stock_ledger_entries WHERE tenant_id = " + TENANT_ID))
                .as("不损失客户：SKU 级销售台账行数不变（读面不得写任何东西）").isEqualTo(ledgerBefore);
    }

    @Test
    @DisplayName("判据3(粒度)：未知粒度显式拒绝（不静默回落 month）；week 走 ISO 周")
    void granularityIsValidatedAndWeekUsesIsoWeek() {
        org.assertj.core.api.Assertions.assertThatThrownBy(
                        () -> service.savingBoard(TENANT_ID, null, "quarter"))
                .as("🔴 未知粒度 ⇒ 400 显式拒绝：静默回落会让看板显示的口径与请求的不是一回事")
                .hasMessageContaining("未知的时间粒度");

        SavingMetricViews.Trend weekly = service.savingTrend(TENANT_ID, "week");
        System.out.println("[#5159 读数] ISO 周时间桶 = "
                + weekly.points().stream().map(SavingMetricViews.ConsumptionPoint::period).toList());
        assertThat(weekly.granularity()).isEqualTo("week");
        assertThat(weekly.points()).allSatisfy(p ->
                assertThat(p.period()).as("ISO 周形态（YYYY-Www）").matches("\\d{4}-W\\d{2}"));
        assertThat(weekly.timezone()).as("时区口径必须显式回给读的人（否则跨月边界上是两个数）")
                .isEqualTo(SavingMetricViews.TIMEZONE);
    }

    // ────────────────────────────────────────────── 装配

    private static String consumption(String po, String batchNo, String itemId, String delta,
                                      String before, String after, String formula, String planned,
                                      String unitCost, String createdAt) {
        return "INSERT INTO stock_batch_consumptions (tenant_id, batch_id, batch_no, product_id,"
                + " sku_id, sku_code, delta, before_qty, after_qty, formula_meters, planned_meters,"
                + " unit_cost, reason, processing_order_no, order_no, order_item_id, operator,"
                + " created_at) SELECT " + TENANT_ID + ", id, batch_no, product_id, sku_id, sku_code,"
                + " " + delta + ", " + before + ", " + after + ", " + formula + ", " + planned + ", "
                + unitCost + ", 'processing_order', '" + po + "', 'ORD-5159', '" + itemId + "', 'tester',"
                + " TIMESTAMPTZ '" + createdAt + "' FROM stock_batches WHERE tenant_id = " + TENANT_ID
                + " AND batch_no = '" + batchNo + "'";
    }

    private static String scalar(String sql) throws SQLException {
        try (Connection conn = dataSource.getConnection();
             Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery(sql)) {
            return rs.next() ? rs.getString(1) : null;
        }
    }

    private static void exec(String sql) throws SQLException {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute(sql);
        }
    }

    private static String schemaSql() throws Exception {
        Path root = Paths.get(System.getProperty("user.dir")).toAbsolutePath();
        while (root != null && !Files.exists(root.resolve("docs/sql/schema.sql"))) {
            root = root.getParent();
        }
        assertThat(root).as("必须能定位 docs/sql/schema.sql（真库建表取终态 schema，不手抄列清单）")
                .isNotNull();
        return Files.readString(root.resolve("docs/sql/schema.sql"));
    }
}
