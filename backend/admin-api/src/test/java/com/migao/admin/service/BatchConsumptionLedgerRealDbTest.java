// case_ids: PG-062
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.MybatisSqlSessionFactoryBuilder;
import com.baomidou.mybatisplus.extension.plugins.MybatisPlusInterceptor;
import com.baomidou.mybatisplus.extension.plugins.handler.TenantLineHandler;
import com.baomidou.mybatisplus.extension.plugins.inner.TenantLineInnerInterceptor;
import com.migao.admin.dto.BatchStockViews;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.CraftCalcConfigMapper;
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
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.catchThrowable;

/**
 * 🔴 <b>批次消耗台账的**真库**判据（issue #5190：给 #5145 的台账补真库守卫）</b>。
 *
 * <h2>为什么必须真库（Mockito 测不出来）</h2>
 * #5145 的批次消耗台账（{@code plan} / {@code apply} / {@code reverse} + 余量分布 + 对账拆分）
 * 此前只有 mock / 控制器层测试，而**它恰好是钱/物料路径的核心**。这条链上最要害的四件事在 mock 面
 * <b>结构上不可见</b>：
 * <ol>
 *   <li><b>实物账与台账逐值自洽</b>：余量是派生值 {@code stock_batches.quantity + Σ(delta)}，
 *       靠的是列真的写对、{@code NUMERIC(12,1)} 真的不丢精度 —— mock 只证明「调了哪个方法」；</li>
 *   <li><b>唯一闸 {@code uk_batch_consumption_line} 的原子性</b>：重复落账要由**部分唯一索引**挡下，
 *       而不是靠应用层先查后写（那是 TOCTOU）；</li>
 *   <li><b>V121 的符号约束真的钉住了</b>：{@code ck_batch_consumption_plan_meters} 是不是真在拦，
 *       只有「故意写一行自相矛盾的数据 ⇒ 数据库当场拒绝（SQLSTATE 23514）」能证明
 *       —— 否则它只是写在注释里的一句话；</li>
 *   <li><b>对账恒等式</b>：{@code diff == soldUnbatched + planSaved} 是**两条腿各自聚合**出来的
 *       （批次腿与销售台账腿），mock 面两条腿都由测试自己喂 ⇒ 恒等式退化成同义反复。</li>
 * </ol>
 *
 * <h2>判据（每条都带**能单独变红**的红证，红证与判据共用同一个读数函数）</h2>
 * <ol>
 *   <li>🔴 <b>判据1·台账与实物一致</b>：{@code plan} → {@code apply} 之后，
 *       「{@code stock_batches.quantity} + Σ{@code delta}」与读面余量逐值相等、
 *       逐行 {@code after − before == delta}、逐行 {@code planned_meters == −delta}、
 *       逐行「变更前余量」对得上链条（60 → 57.3 → 54.6，含小数）。
 *       <b>红证</b> = 手动改一行 {@code delta} ⇒ **同一个读数函数**必须报出不一致。</li>
 *   <li>🔴 <b>判据2·V121 的符号约束真的钉住了</b>：故意写一行
 *       {@code abs(planned_meters) > abs(formula_meters)} 的自相矛盾数据 ⇒ 数据库当场拒绝
 *       （SQLSTATE <b>23514</b>）；两列符号打架（{@code formula_meters * planned_meters < 0}）同样被拒。
 *       <b>红证 A</b> = 事务内把约束换成 V119 的**旧表达式**（{@code planned_meters <= formula_meters}）
 *       ⇒ 合法的**回补行**（两列都负）当场被拒 ⇒ 证明 V121 的修法是有载荷的；
 *       <b>红证 B</b> = 事务内把约束整个摘掉 ⇒ 同一行自相矛盾数据**能**落库 ⇒ 证明拦住它的是约束本身，
 *       不是 SQL 写错。（两处 DDL 都在**回滚事务**里做 —— PG 的 DDL 是事务性的 ⇒ 零残留。）</li>
 *   <li>🔴 <b>判据3·reverse 的对称 / 幂等 / 对不存在的东西</b>：60 → 57.3 → <b>60</b>（逐值回到派工前，
 *       含小数）；回补行是扣减行的**逐值相反数**（{@code delta} / 两个米数）+ 均价原样搬运
 *       ⇒ 整单净额归零、{@code saved_meters} 相加归零（作废不冒功）；再次 {@code reverse} ⇒ 返回 0、
 *       行数与余量一字不动；{@code reverse} 一个**从未扣过批次**的加工单 ⇒ 返回 0、零落账、余量不动。
 *       <b>红证</b> = 手动抹掉一行回补（改 {@code delta}）⇒ **同一个读数函数**必须报出「净额不为零」。</li>
 *   <li>🔴 <b>判据4·跨 SKU 拒绝（真库 + 真快照路径）</b>：同一货号、错 SKU 的批次
 *       ⇒ {@code BATCH_SKU_MISMATCH} + 400 + 可行动文案，且**该批次一行台账都没落**、余量一字不动。
 *       <b>红证</b> = 同参数但 {@code skuCode} 传 null（= #5174 修前的读侧形态，护栏恒 no-op）
 *       ⇒ 静默扣账（1 行台账 / 余量 60 → 57）—— 两个读数在同一个测试里对照打印。</li>
 *   <li>🔴 <b>判据5·重复落账被唯一闸挡下</b>：同一加工单再 {@code apply} 一次 ⇒ SQLSTATE <b>23505</b>、
 *       台账行数不变、批次余量不变。<b>红证</b> = 事务内把 {@code uk_batch_consumption_line} 摘掉
 *       ⇒ **同一个元组**的裸 INSERT 能落库 ⇒ 证明拦住它的是那个索引。</li>
 *   <li>🔴 <b>判据6·余量分布四档逐值可复算</b>：已知夹具（7 个批次：0.2 / 0.1 / 0.3 / 0.8 / 1.5 ×3）
 *       ⇒ 四档批次数 {@code [2,1,1,3]}、占比 {@code [0.2857,0.1429,0.1429,0.4286]} 逐值相等。
 *       <b>红证</b> = 手动把一个批次的 {@code quantity} 改大 ⇒ **同一个读数**的档位计数必须变。</li>
 *   <li>🔴 <b>判据7·对账恒等式在「已售未派 + 排料节省」两项并存时逐值成立</b>：夹具同时放
 *       ① 一笔销售（销售账扣 10 米、加工单还没派）② 一次并排省料（公式 6 米 / 排料 3 米）
 *       ⇒ {@code diff == soldUnbatched + planSaved}、{@code reconciled == true}、
 *       {@code unreconciledCount == 0}，且两项**都非零**（4 与 3 —— 否则恒等式是空的）。
 *       <b>红证</b> = 手动改 {@code stock_batches.quantity}（批次腿与销售腿被掰开）
 *       ⇒ 同一个读数必须报 {@code reconciled == false} + {@code unreconciledCount == 1}。</li>
 * </ol>
 *
 * <h2>环境与范式</h2>
 * 一次性真 PG 集群（共用 {@link PgCluster}，#5167 提取的共用件 —— <b>不复制第二份装配</b>），
 * schema 取自 {@code backend/admin-api/src/main/resources/db/init/schema.sql}（bootstrap 终态，**不手抄列清单** ⇒ 列名/约束漂移会被抓）。
 * 缺 PG 二进制 ⇒ {@link PgCluster#startOrAbort()}：CI（{@code MIGAO_REQUIRE_REALDB=1}）⇒ 判红；
 * 本机未设该标记 ⇒ 显式 skip（「没跑」长得像「没跑」，不是通过）。
 *
 * <h2>与既有真库判据的分工（不重复覆盖）</h2>
 * {@code BatchConsumptionCuttingPlanRealDbTest}（#5158）钉「**排料口径**怎么落账」、
 * {@code SkuBatchGuardRealDbTest}（#5174）钉「**快照读侧取哪个键**」。
 * 本类钉的是**台账本身**：{@code apply} 的账实一致、{@code reverse} 的对称与幂等、
 * 约束面（{@code uk_batch_consumption_line} / {@code ck_batch_consumption_plan_meters}）、
 * 以及两个读面（{@code distribution} / {@code reconcile}）的**逐值可复算**。
 * 判据 4 与 #5174 有意**部分重合**（本类多钉一条「拒绝时零落账」）—— 如实登记，不当成新覆盖。
 */
@DisplayName("#5190 真库守卫：批次消耗台账（账实一致 / V121 约束 / 反向对称与幂等 / 跨 SKU / 分布 / 对账）")
class BatchConsumptionLedgerRealDbTest {

    private static final Long TENANT_ID = 5190L;
    private static final BigDecimal UNIT_COST = new BigDecimal("12.5");

    /** 判据 1 / 2 的物料面（账实一致 + 约束）。 */
    private static final String LEDGER_PRODUCT = "acc-5190-ledger-prod";
    private static final Long LEDGER_SKU_ID = 5190L;
    private static final String LEDGER_SKU = "SKU-5190-L";

    /** 判据 3 的物料面（反向）。 */
    private static final String REV_PRODUCT = "acc-5190-rev-prod";
    private static final Long REV_SKU_ID = 5191L;
    private static final String REV_SKU = "SKU-5190-R";

    /** 判据 4 的物料面（**同一货号**下的两个 SKU：跨 SKU 才拦得住）。 */
    private static final String SKU_PRODUCT = "acc-5190-sku-prod";
    private static final Long SKU_A_ID = 5192L;
    private static final String SKU_A = "SKU-5190-A";
    private static final Long SKU_B_ID = 5193L;
    private static final String SKU_B = "SKU-5190-B";

    /** 判据 5 的物料面（幂等）。 */
    private static final String IDEM_PRODUCT = "acc-5190-idem-prod";
    private static final Long IDEM_SKU_ID = 5194L;
    private static final String IDEM_SKU = "SKU-5190-I";

    /** 判据 6 的物料面（分布）。 */
    private static final String DIST_PRODUCT = "acc-5190-dist-prod";
    private static final Long DIST_SKU_ID = 5195L;
    private static final String DIST_SKU = "SKU-5190-D";

    /** 判据 7 的物料面（对账；门幅 2.8 ⇒ 两扇「窗高 1.1 + 卷边 0.3」的矮窗能并排）。 */
    private static final String REC_PRODUCT = "acc-5190-rec-prod";
    private static final Long REC_SKU_ID = 5196L;
    private static final String REC_SKU = "SKU-5190-REC";

    private static final String DOOR_WIDTH = "2.8米";
    private static final String OTHER_DOOR_WIDTH = "1.5米";

    private static PgCluster cluster;
    private static DataSource dataSource;
    private static SqlSessionFactory factory;
    private static SqlSession session;
    private static StockBatchConsumptionService service;

    @BeforeAll
    static void startRealPostgresAndFixtures() throws Exception {
        cluster = PgCluster.startOrAbort();
        dataSource = cluster.dataSource();
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute(schemaSql());
            st.execute("INSERT INTO tenants (id, name, code) OVERRIDING SYSTEM VALUE VALUES ("
                    + TENANT_ID + ", 'acc-5190', 'acc-5190')");
            // 每个判据一个**独立物料面**：读面（remaining / distribution / reconcile）都按 productId
            // 取数 ⇒ 面与面之间互不可见，判据读数因此是确定的（与既有真库判据同款做法）。
            st.execute(product(LEDGER_PRODUCT, "布艺遮光帘-台账"));
            st.execute(sku(LEDGER_SKU_ID, LEDGER_PRODUCT, DOOR_WIDTH, LEDGER_SKU, "60"));
            st.execute(product(REV_PRODUCT, "布艺遮光帘-反向"));
            st.execute(sku(REV_SKU_ID, REV_PRODUCT, DOOR_WIDTH, REV_SKU, "60"));
            st.execute(product(SKU_PRODUCT, "布艺遮光帘-同货号两 SKU"));
            st.execute(sku(SKU_A_ID, SKU_PRODUCT, DOOR_WIDTH, SKU_A, "60"));
            st.execute(sku(SKU_B_ID, SKU_PRODUCT, OTHER_DOOR_WIDTH, SKU_B, "60"));
            st.execute(product(IDEM_PRODUCT, "布艺遮光帘-幂等"));
            st.execute(sku(IDEM_SKU_ID, IDEM_PRODUCT, DOOR_WIDTH, IDEM_SKU, "60"));
            st.execute(product(DIST_PRODUCT, "布艺遮光帘-分布"));
            st.execute(sku(DIST_SKU_ID, DIST_PRODUCT, DOOR_WIDTH, DIST_SKU, "60"));
            st.execute(product(REC_PRODUCT, "布艺遮光帘-对账"));
            st.execute(sku(REC_SKU_ID, REC_PRODUCT, DOOR_WIDTH, REC_SKU, "60"));
            // 租户算料配置：只给主键与租户 ⇒ 其余列取**库默认值**（hem_margin 默认 0.3，
            // 与算料引擎常量同值）—— 排料腿因此能真的跑起来（`null` ⇒ 不排料 ⇒ 省料恒为 0）。
            st.execute("INSERT INTO craft_calc_configs (id, tenant_id) VALUES ('cfg-acc-5190', "
                    + TENANT_ID + ")");
        }
        MybatisConfiguration configuration = new MybatisConfiguration();
        configuration.setMapUnderscoreToCamelCase(true);
        // 红证要用裸 JDBC 改库（绕过 session）⇒ 一级缓存必须是 STATEMENT 级，
        // 否则「改完再查」会拿到改前的结果（红证会变成假绿；`RemnantTestDb` 已登记同款教训）。
        configuration.setLocalCacheScope(LocalCacheScope.STATEMENT);
        configuration.setEnvironment(new Environment("acc-5190", new JdbcTransactionFactory(), dataSource));
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
        for (Class<?> mapper : List.of(StockBatchMapper.class, StockBatchConsumptionMapper.class,
                ProductSkuMapper.class, StockLedgerMapper.class, CraftCalcConfigMapper.class)) {
            configuration.addMapper(mapper);
        }
        factory = new MybatisSqlSessionFactoryBuilder().build(configuration);
        session = factory.openSession(true);
        // 真装配：上下卷边走**算料配置的单一读面**（真库里的配置行），不是测试里塞的常量。
        // 余料腿显式不装（V122 / issue #5146）：本判据覆盖批次账，余料是附加事实 ⇒ 行为与 #5158 逐字相同。
        CraftCalcConfigService configService = new CraftCalcConfigService(
                session.getMapper(CraftCalcConfigMapper.class), null);
        service = new StockBatchConsumptionService(session.getMapper(StockBatchMapper.class),
                session.getMapper(StockBatchConsumptionMapper.class),
                session.getMapper(ProductSkuMapper.class), session.getMapper(StockLedgerMapper.class),
                configService, null);
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

    // ══════════════════════════════════ 判据 1：台账与实物一致

    @Test
    @DisplayName("🔴 判据1 账实一致：quantity + Σdelta 与读面余量逐值相等，逐行 before/after/planned 自洽")
    void ledgerAndPhysicalStockAgreeValueByValue() throws Exception {
        long batchId = newBatch(LEDGER_PRODUCT, LEDGER_SKU_ID, LEDGER_SKU, "PC-5190-L1", "60");
        List<StockBatchConsumptionService.Designation> designations = List.of(
                formulaOnly(LEDGER_PRODUCT, "acc-5190-l1", "PC-5190-L1", "2.7"),
                formulaOnly(LEDGER_PRODUCT, "acc-5190-l2", "PC-5190-L1", "2.7"));
        var plan = service.plan(TENANT_ID, designations);
        service.apply(TENANT_ID, "JG-5190-L1", "ORD-5190-L1", plan);

        List<String> problems = ledgerProblems(batchId, LEDGER_PRODUCT, "JG-5190-L1");
        System.out.println("[#5190 判据1] 台账行读数 = " + ledgerReadings("JG-5190-L1"));
        assertThat(problems).as("台账与实物必须逐值自洽").isEmpty();
        // 逐值读数（不是「跑完就算」）：60 − 2.7 − 2.7 = 54.6，含小数
        assertThat(remainingOf(batchId)).as("余量 = 60 − 5.4").isEqualByComparingTo("54.6");
        assertThat(scalar("SELECT quantity FROM stock_batches WHERE id = " + batchId))
                .as("批次行不可改（V111）：quantity 一字不动").isEqualByComparingTo("60");
        assertThat(service.remaining(TENANT_ID, LEDGER_PRODUCT, null, false))
                .filteredOn(r -> r.batchId() == batchId)
                .singleElement()
                .satisfies(r -> assertThat(r.remainingMeters()).isEqualByComparingTo("54.6"));

        // 🔴 红证：手动改一行 delta ⇒ **同一个读数函数**必须报出不一致（证明它不是恒真）
        long firstRowId = rawConsumptionRows("JG-5190-L1").get(0).id();
        exec("UPDATE stock_batch_consumptions SET delta = delta + 1 WHERE id = " + firstRowId);
        List<String> perturbed = ledgerProblems(batchId, LEDGER_PRODUCT, "JG-5190-L1");
        System.out.println("[#5190 判据1 红证] 改一行 delta 后的读数 = " + perturbed);
        assertThat(perturbed).as("红证：同一读数必须变红（否则判据 1 是空断言）").isNotEmpty();
        exec("UPDATE stock_batch_consumptions SET delta = delta - 1 WHERE id = " + firstRowId);
        assertThat(ledgerProblems(batchId, LEDGER_PRODUCT, "JG-5190-L1"))
                .as("对照组：还原后必须回到自洽").isEmpty();
    }

    // ══════════════════════════════════ 判据 2：V121 的符号约束

    @Test
    @DisplayName("🔴 判据2 V121 符号约束真的钉住：自相矛盾行被 23514 拒；红证=换回旧式/摘掉约束")
    void planMetersSignConstraintIsEnforcedByTheDatabase() throws Exception {
        long batchId = newBatch(LEDGER_PRODUCT, LEDGER_SKU_ID, LEDGER_SKU, "PC-5190-L2", "60");
        String batchNo = "PC-5190-L2";
        String poNo = "JG-5190-V121";

        // ① 合法行（扣减）：planned(3) ≤ formula(6)，两列同号 ⇒ 能落库（正控）
        assertThat(sqlStateOfRejected(rawRow(batchId, batchNo, poNo, "v121-ok", "6", "3", "-3")))
                .as("合法扣减行必须能落库").isNull();
        // ② 合法行（回补）：两列都**负** —— 这正是 V121 修的那一格（旧表达式在负行上方向翻转）
        assertThat(sqlStateOfRejected(rawRow(batchId, batchNo, poNo, "v121-rev", "-6", "-3", "3")))
                .as("合法回补行（两列都负）必须能落库 —— 它是 V121 修的那一格").isNull();
        // ③ 自相矛盾：abs(planned) > abs(formula) ⇒ 数据库当场拒绝
        assertThat(sqlStateOfRejected(rawRow(batchId, batchNo, poNo, "v121-bad", "3", "4", "-4")))
                .as("abs(planned_meters) > abs(formula_meters) 必须被 ck_batch_consumption_plan_meters 拒")
                .isEqualTo("23514");
        // ④ 两列符号打架（一正一负）⇒ 同样拒绝（同一条约束的后半句）
        assertThat(sqlStateOfRejected(rawRow(batchId, batchNo, poNo, "v121-sign", "6", "-3", "3")))
                .as("两列符号打架必须被拒（约束的后半句）").isEqualTo("23514");

        // 🔴 红证 A：把约束换成 **V119 的旧表达式** —— 它**连存量行都过不了**：
        // 上面刚落库的那条**合法回补行**（两列都负）正是旧表达式要拒的形态 ⇒ ADD CONSTRAINT 当场失败。
        assertThat(inRolledBackTransaction(conn -> {
            try (Statement st = conn.createStatement()) {
                st.execute("ALTER TABLE stock_batch_consumptions DROP CONSTRAINT"
                        + " ck_batch_consumption_plan_meters");
                st.execute("ALTER TABLE stock_batch_consumptions ADD CONSTRAINT"
                        + " ck_batch_consumption_plan_meters CHECK (planned_meters <= formula_meters"
                        + " AND formula_meters * planned_meters >= 0)");
                return null;
            } catch (SQLException e) {
                return e.getSQLState();
            }
        })).as("红证A：V119 旧表达式**加都加不上**（存量里的合法回补行就违反它，23514）"
                + "⇒ V121 的修法是有载荷的").isEqualTo("23514");

        // 🔴 红证 A'：让它只对**新行**生效（`NOT VALID` 跳过存量校验）⇒ 新的合法回补行照样当场被拒。
        assertThat(inRolledBackTransaction(conn -> {
            try (Statement st = conn.createStatement()) {
                st.execute("ALTER TABLE stock_batch_consumptions DROP CONSTRAINT"
                        + " ck_batch_consumption_plan_meters");
                st.execute("ALTER TABLE stock_batch_consumptions ADD CONSTRAINT"
                        + " ck_batch_consumption_plan_meters CHECK (planned_meters <= formula_meters"
                        + " AND formula_meters * planned_meters >= 0) NOT VALID");
            }
            return sqlStateOn(conn, rawRow(batchId, batchNo, poNo, "v121-rev2", "-6", "-3", "3"));
        })).as("红证A'：旧表达式生效时，新的合法回补行被拒（23514）⇒ 正是 V121 修掉的那一格")
                .isEqualTo("23514");

        // 🔴 红证 B：把约束整个摘掉 ⇒ 自相矛盾行能落库（拦住它的是约束本身，不是 SQL 写错）
        assertThat(inRolledBackTransaction(conn -> {
            try (Statement st = conn.createStatement()) {
                st.execute("ALTER TABLE stock_batch_consumptions DROP CONSTRAINT"
                        + " ck_batch_consumption_plan_meters");
            }
            return sqlStateOn(conn, rawRow(batchId, batchNo, poNo, "v121-bad2", "3", "4", "-4"));
        })).as("红证B：约束缺席时自相矛盾行确实写得进去 ⇒ 拦住它的是约束").isNull();

        // 对照组：两处 DDL 都在回滚事务里 ⇒ 约束必须**原样还在**
        assertThat(sqlStateOfRejected(rawRow(batchId, batchNo, poNo, "v121-bad3", "3", "4", "-4")))
                .as("对照组：回滚后约束必须回来（PG 的 DDL 是事务性的，零残留）").isEqualTo("23514");
    }

    // ══════════════════════════════════ 判据 3：reverse 对称 / 幂等 / 对不存在的东西

    @Test
    @DisplayName("🔴 判据3 reverse：60 → 57.3 → 60 逐值回到派工前；再撤=0；撤不存在=0 且零落账")
    void reverseRestoresExactlyAndIsIdempotent() throws Exception {
        long batchId = newBatch(REV_PRODUCT, REV_SKU_ID, REV_SKU, "PC-5190-R1", "60");
        var plan = service.plan(TENANT_ID, List.of(formulaOnly(REV_PRODUCT, "acc-5190-r1",
                "PC-5190-R1", "2.7")));
        service.apply(TENANT_ID, "JG-5190-R1", "ORD-5190-R1", plan);
        assertThat(remainingOf(batchId)).as("派工后：60 − 2.7").isEqualByComparingTo("57.3");

        assertThat(service.reverse(TENANT_ID, "JG-5190-R1", "ORD-5190-R1", "作废回补"))
                .as("回补行数 = 原扣减行数").isEqualTo(1);
        assertThat(remainingOf(batchId)).as("🔴 逐值回到派工前（含小数）").isEqualByComparingTo("60");
        List<String> afterReverse = reverseProblems(REV_PRODUCT, batchId, "JG-5190-R1");
        System.out.println("[#5190 判据3] 回补后读数 = " + ledgerReadings("JG-5190-R1"));
        assertThat(afterReverse).as("回补必须逐值对称、净额归零、不留负库存").isEmpty();

        // 幂等：再撤一次 ⇒ 返回 0（不撞唯一键、不重复回补）
        long rowsBeforeSecond = countRows("JG-5190-R1");
        assertThat(service.reverse(TENANT_ID, "JG-5190-R1", "ORD-5190-R1", "再撤一次"))
                .as("已回补过 ⇒ 第二遍返回 0（可重跑）").isZero();
        assertThat(countRows("JG-5190-R1")).as("行数不变").isEqualTo(rowsBeforeSecond);
        assertThat(remainingOf(batchId)).as("余量不变（没有二次回补）").isEqualByComparingTo("60");

        // 撤销一个从未扣过批次的加工单 ⇒ 返回 0、零落账、余量不动
        assertThat(service.reverse(TENANT_ID, "JG-5190-NEVER", "ORD-5190-NEVER", "撤销不存在的东西"))
                .as("没有批次扣减 ⇒ 返回 0（不抛错、不静默造行）").isZero();
        assertThat(countRows("JG-5190-NEVER")).as("零落账").isZero();
        assertThat(remainingOf(batchId)).as("余量一字不动").isEqualByComparingTo("60");

        // 🔴 红证：手动抹掉一行回补（把 delta 改成 0）⇒ **同一个读数函数**必须报出「净额不为零」
        long reversalRowId = rawConsumptionRows("JG-5190-R1").stream()
                .filter(r -> StockBatchConsumptionService.REASON_PROCESSING_ORDER_CANCELLED
                        .equals(r.reason()))
                .findFirst().orElseThrow().id();
        exec("UPDATE stock_batch_consumptions SET delta = 0 WHERE id = " + reversalRowId);
        List<String> perturbed = reverseProblems(REV_PRODUCT, batchId, "JG-5190-R1");
        System.out.println("[#5190 判据3 红证] 抹掉一行回补后的读数 = " + perturbed);
        assertThat(perturbed).as("红证：同一读数必须变红（否则判据 3 是空断言）").isNotEmpty();
        exec("UPDATE stock_batch_consumptions SET delta = 2.7 WHERE id = " + reversalRowId);
        assertThat(reverseProblems(REV_PRODUCT, batchId, "JG-5190-R1"))
                .as("对照组：还原后必须回到对称").isEmpty();
    }

    // ══════════════════════════════════ 判据 4：跨 SKU 拒绝

    @Test
    @DisplayName("🔴 判据4 跨 SKU：同货号错 SKU 的批次被 BATCH_SKU_MISMATCH 拒 + 零落账；红证=skuCode 传 null 则静默扣账")
    void crossSkuBatchIsRejectedOnTheRealLedger() throws Exception {
        long wrongBatch = newBatch(SKU_PRODUCT, SKU_B_ID, SKU_B, "PC-5190-A1", "60");
        Rejection rejected = rejection(() -> service.plan(TENANT_ID, List.of(
                new StockBatchConsumptionService.Designation("acc-5190-a1", SKU_PRODUCT, SKU_A,
                        "PC-5190-A1", new BigDecimal("3"), null, null, null))));
        System.out.println("[#5190 判据4] 错 SKU 的拒绝读数 = " + rejected);
        assertThat(rejected.code()).as("同货号、错 SKU 的批次必须显式拒绝")
                .isEqualTo(StockBatchConsumptionService.ERR_BATCH_SKU_MISMATCH);
        assertThat(rejected.httpStatus()).as("拒绝口径 = 400").isEqualTo(400);
        assertThat(rejected.suggestion()).as("必须给可行动的处置（不是一句「不一致」）").contains("颜色");
        assertThat(countRows("JG-5190-A1")).as("🔴 被拒时**一行台账都没落**").isZero();
        assertThat(remainingOf(wrongBatch)).as("被拒时批次余量一字不动").isEqualByComparingTo("60");

        // 🔴 红证：同参数、只把 skuCode 换成 null（= #5174 修前读侧必然产出的值）⇒ 护栏恒 no-op ⇒ 静默扣账
        var silentPlan = service.plan(TENANT_ID, List.of(
                new StockBatchConsumptionService.Designation("acc-5190-a2", SKU_PRODUCT, null,
                        "PC-5190-A1", new BigDecimal("3"), null, null, null)));
        service.apply(TENANT_ID, "JG-5190-A2", "ORD-5190-A2", silentPlan);
        System.out.println("[#5190 判据4 红证] skuCode=null 时落账行数 = " + countRows("JG-5190-A2")
                + "，错批次余量 = " + remainingOf(wrongBatch));
        assertThat(countRows("JG-5190-A2")).as("红证：护栏失效时**真的**静默扣走了错批次的料").isEqualTo(1);
        assertThat(remainingOf(wrongBatch)).as("红证：余量 60 → 57（用错料且账上照扣）")
                .isEqualByComparingTo("57");

        // 对照：正确 SKU 的批次走同一条真库路径 ⇒ 通过并落账
        long rightBatch = newBatch(SKU_PRODUCT, SKU_A_ID, SKU_A, "PC-5190-A3", "60");
        var okPlan = service.plan(TENANT_ID, List.of(
                new StockBatchConsumptionService.Designation("acc-5190-a3", SKU_PRODUCT, SKU_A,
                        "PC-5190-A3", new BigDecimal("3"), null, null, null)));
        service.apply(TENANT_ID, "JG-5190-A3", "ORD-5190-A3", okPlan);
        assertThat(countRows("JG-5190-A3")).as("正确 SKU：落账 1 行").isEqualTo(1);
        assertThat(remainingOf(rightBatch)).as("正确 SKU：60 → 57").isEqualByComparingTo("57");
    }

    // ══════════════════════════════════ 判据 5：重复落账被唯一闸挡下

    @Test
    @DisplayName("🔴 判据5 幂等闸：重复 apply ⇒ 23505 + 行数不变 + 余量不变；红证=摘掉唯一索引则可落库")
    void repeatedApplyIsRejectedByTheUniqueGate() throws Exception {
        long batchId = newBatch(IDEM_PRODUCT, IDEM_SKU_ID, IDEM_SKU, "PC-5190-I1", "60");
        var plan = service.plan(TENANT_ID, List.of(formulaOnly(IDEM_PRODUCT, "acc-5190-i1",
                "PC-5190-I1", "3")));
        service.apply(TENANT_ID, "JG-5190-I1", "ORD-5190-I1", plan);
        long rowsAfterFirst = countRows("JG-5190-I1");
        BigDecimal remainingAfterFirst = remainingOf(batchId);

        var replanned = service.plan(TENANT_ID, List.of(formulaOnly(IDEM_PRODUCT, "acc-5190-i1",
                "PC-5190-I1", "3")));
        String state = sqlStateOfThrowable(catchThrowable(
                () -> service.apply(TENANT_ID, "JG-5190-I1", "ORD-5190-I1", replanned)));
        assertThat(state).as("第二遍必须被 uk_batch_consumption_line 挡下（SQLSTATE 23505）")
                .isEqualTo("23505");
        assertThat(countRows("JG-5190-I1")).as("台账行数不变").isEqualTo(rowsAfterFirst);
        assertThat(remainingOf(batchId)).as("🔴 余量不再变化（没有二次扣减）")
                .isEqualByComparingTo(remainingAfterFirst);

        // 🔴 红证：事务内摘掉唯一索引 ⇒ **同一个元组**的裸 INSERT 能落库 ⇒ 拦住它的是那个索引
        String sameTuple = rawRow(batchId, "PC-5190-I1", "JG-5190-I1", "acc-5190-i1",
                "3", "3", "-3");
        assertThat(inRolledBackTransaction(conn -> {
            try (Statement st = conn.createStatement()) {
                st.execute("DROP INDEX uk_batch_consumption_line");
            }
            return sqlStateOn(conn, sameTuple);
        })).as("红证：索引缺席时同一元组确实写得进去 ⇒ 拦住它的是唯一闸本身").isNull();

        // 对照组：DDL 已回滚 ⇒ 唯一闸还在，行数与余量仍不变
        assertThat(countRows("JG-5190-I1")).as("对照组：行数仍不变").isEqualTo(rowsAfterFirst);
        assertThat(sqlStateOfRejected(sameTuple)).as("对照组：回滚后唯一闸必须回来")
                .isEqualTo("23505");
    }

    // ══════════════════════════════════ 判据 6：余量分布四档逐值可复算

    @Test
    @DisplayName("🔴 判据6 分布四档逐值可复算：7 个批次 ⇒ 批次数 [2,1,1,3]、占比 [0.2857,0.1429,0.1429,0.4286]")
    void distributionBucketsAreRecomputableValueByValue() throws Exception {
        // 夹具：0.2 / 0.1 → ≤0.2 档；0.3 → 0.2~0.5；0.8 → 0.5~1；1.5 ×3 → >1
        String[] quantities = {"0.2", "0.1", "0.3", "0.8", "1.5", "1.5", "1.5"};
        for (int i = 0; i < quantities.length; i++) {
            newBatch(DIST_PRODUCT, DIST_SKU_ID, DIST_SKU, "PC-5190-D" + (i + 1), quantities[i]);
        }
        assertThat(distributionProblems()).as("四档批次数与占比必须逐值可复算").isEmpty();
        BatchStockViews.Distribution d = service.distribution(TENANT_ID, DIST_PRODUCT);
        assertThat(d.totalBatches()).as("总数 = 7 个批次").isEqualTo(7);
        assertThat(d.buckets()).extracting(BatchStockViews.Bucket::batchCount)
                .as("四档批次数").containsExactly(2, 1, 1, 3);
        assertThat(d.buckets()).extracting(BatchStockViews.Bucket::share)
                .as("四档占比（share = 批次数 / 总数，4 位 HALF_UP）")
                .containsExactly(new BigDecimal("0.2857"), new BigDecimal("0.1429"),
                        new BigDecimal("0.1429"), new BigDecimal("0.4286"));
        assertThat(d.buckets()).extracting(BatchStockViews.Bucket::key)
                .as("四档 key 恒在（空档也要回 0 ⇒ 前端不必猜）")
                .containsExactly("le_0_2", "b0_2_0_5", "b0_5_1", "gt_1");

        // 🔴 红证：把一个批次的数量改大（跨档）⇒ **同一个读数**的档位计数必须变
        exec("UPDATE stock_batches SET quantity = 5 WHERE tenant_id = " + TENANT_ID
                + " AND batch_no = 'PC-5190-D1'");
        List<String> perturbed = distributionProblems();
        System.out.println("[#5190 判据6 红证] 把一个批次改成 5 米后的读数 = " + perturbed);
        assertThat(perturbed).as("红证：同一读数必须变红（否则判据 6 是空断言）").isNotEmpty();
        exec("UPDATE stock_batches SET quantity = 0.2 WHERE tenant_id = " + TENANT_ID
                + " AND batch_no = 'PC-5190-D1'");
        assertThat(distributionProblems()).as("对照组：还原后必须回到 [2,1,1,3]").isEmpty();
    }

    // ══════════════════════════════════ 判据 7：对账恒等式（两项并存）

    @Test
    @DisplayName("🔴 判据7 对账：已售未派(4) + 排料节省(3) 并存时 diff == 两项之和；红证=掰开批次腿即不平")
    void reconcileIdentityHoldsWithBothTermsPresent() throws Exception {
        long batchId = newBatch(REC_PRODUCT, REC_SKU_ID, REC_SKU, "PC-5190-REC1", "60");
        // ① 入库腿：真库账面上批次入库同时记一条 inbound 台账（生产路径同款）
        exec("INSERT INTO stock_ledger_entries (tenant_id, product_id, sku_id, sku_code, delta,"
                + " before_qty, after_qty, reason, ref_no, operator) VALUES (" + TENANT_ID + ", '"
                + REC_PRODUCT + "', " + REC_SKU_ID + ", '" + REC_SKU + "', 60, 0, 60, 'inbound',"
                + " 'IN-5190-REC1', 'system')");
        // ② 已售未派：顾客已付款扣了销售账（10 米），加工单还没派
        exec("UPDATE product_skus SET stock = 50 WHERE id = " + REC_SKU_ID);
        exec("INSERT INTO stock_ledger_entries (tenant_id, product_id, sku_id, sku_code, delta,"
                + " before_qty, after_qty, reason, ref_no, operator) VALUES (" + TENANT_ID + ", '"
                + REC_PRODUCT + "', " + REC_SKU_ID + ", '" + REC_SKU + "', -10, 60, 50, 'order',"
                + " 'ORD-5190-REC1', 'system')");
        // ③ 排料节省：门幅 2.8、两扇「窗高 1.1 + 卷边 0.3」的矮窗并排 ⇒ 公式 6 米 / 排料 3 米
        var plan = service.plan(TENANT_ID, List.of(
                fixedHeight(REC_PRODUCT, "acc-5190-rec1", "PC-5190-REC1", "3"),
                fixedHeight(REC_PRODUCT, "acc-5190-rec2", "PC-5190-REC1", "3")));
        service.apply(TENANT_ID, "JG-5190-REC1", "ORD-5190-REC1", plan);

        List<String> problems = reconcileProblems();
        System.out.println("[#5190 判据7] 对账读数 = " + reconcileReadings());
        assertThat(problems).as("恒等式必须在两项并存时逐值成立").isEmpty();
        BatchStockViews.Reconcile r = service.reconcile(TENANT_ID, REC_PRODUCT, null);
        assertThat(r.unreconciledCount()).as("不平的行数 = 0").isZero();
        assertThat(r.rows()).singleElement().satisfies(row -> {
            assertThat(row.reconciled()).as("恒等式成立").isTrue();
            // 逐值：diff = 批次余量(57) − 销售账(50) = 7 = 已售未派(4) + 排料节省(3)
            assertThat(row.batchRemaining()).isEqualByComparingTo("57");
            assertThat(row.skuStock()).isEqualByComparingTo("50");
            assertThat(row.diff()).isEqualByComparingTo("7");
            assertThat(row.soldUnbatchedMeters()).as("🔴 第 1 项非零（否则恒等式是空的）")
                    .isEqualByComparingTo("4");
            assertThat(row.planSavedMeters()).as("🔴 第 2 项非零（排料真的省了 3 米）")
                    .isEqualByComparingTo("3");
            assertThat(row.explainedDiff()).as("两项之和逐值等于 diff").isEqualByComparingTo("7");
            assertThat(row.dispatchedMeters()).as("派工扣的是排料口径").isEqualByComparingTo("3");
            assertThat(row.formulaDeductedMeters()).as("公式口径 6 米也在账上").isEqualByComparingTo("6");
        });
        assertThat(r.totalSavedMeters()).as("汇总读面：省了 3 米").isEqualByComparingTo("3");

        // 🔴 红证：把批次入库量掰开（批次腿与销售台账腿不再自洽）⇒ 同一个读数必须报不平
        exec("UPDATE stock_batches SET quantity = 70 WHERE id = " + batchId);
        BatchStockViews.Reconcile broken = service.reconcile(TENANT_ID, REC_PRODUCT, null);
        System.out.println("[#5190 判据7 红证] 掰开批次腿后 reconciled="
                + broken.rows().get(0).reconciled() + "，diff=" + broken.rows().get(0).diff()
                + "，explained=" + broken.rows().get(0).explainedDiff());
        assertThat(broken.unreconciledCount()).as("红证：掰开后必须报不平（恒等式有载荷）").isEqualTo(1);
        assertThat(broken.rows()).singleElement().satisfies(row -> {
            assertThat(row.reconciled()).as("红证：reconciled 必须翻成 false").isFalse();
            assertThat(row.diff()).as("红证：diff 必须变（7 → 17）").isEqualByComparingTo("17");
        });
        exec("UPDATE stock_batches SET quantity = 60 WHERE id = " + batchId);
        assertThat(service.reconcile(TENANT_ID, REC_PRODUCT, null).unreconciledCount())
                .as("对照组：还原后必须回到平").isZero();
    }

    // ══════════════════════════════════ 可复用读数（纯函数式：红证对**同一个读数**下手）

    /** 判据 1 的读数：台账与实物**逐值自洽**吗？（返回不一致清单；空 = 自洽） */
    private static List<String> ledgerProblems(long batchId, String productId,
                                               String processingOrderNo) throws Exception {
        List<String> problems = new ArrayList<>();
        List<ConsRow> rows = rawConsumptionRows(processingOrderNo);
        if (rows.isEmpty()) {
            problems.add("台账一行都没落（" + processingOrderNo + "）");
            return problems;
        }
        BigDecimal inbound = scalar("SELECT quantity FROM stock_batches WHERE id = " + batchId);
        BigDecimal walked = inbound;
        BigDecimal sumDelta = BigDecimal.ZERO;
        BigDecimal sumPlanned = BigDecimal.ZERO;
        for (ConsRow row : rows) {
            if (row.after().subtract(row.before()).compareTo(row.delta()) != 0) {
                problems.add("行 " + row.id() + "：after − before ≠ delta（" + row.after() + " − "
                        + row.before() + " ≠ " + row.delta() + "）");
            }
            if (row.planned().compareTo(row.delta().negate()) != 0) {
                problems.add("行 " + row.id() + "：planned_meters ≠ −delta（" + row.planned()
                        + " ≠ " + row.delta().negate() + "）");
            }
            if (row.before().compareTo(walked) != 0) {
                problems.add("行 " + row.id() + "：变更前余量对不上链条（库里 " + row.before()
                        + " / 逐值推算 " + walked + "）");
            }
            walked = row.before().add(row.delta());
            sumDelta = sumDelta.add(row.delta());
            sumPlanned = sumPlanned.add(row.planned());
        }
        BigDecimal derived = inbound.add(sumDelta);
        BigDecimal readFace = readFaceRemaining(productId, batchId);
        if (readFace == null) {
            problems.add("读面里找不到批次 " + batchId + "（余量取不到 ⇒ 无从判账实一致）");
        } else if (derived.compareTo(readFace) != 0) {
            problems.add("余量派生值（quantity + Σdelta = " + derived + "）与读面 " + readFace + " 不一致");
        }
        if (sumDelta.negate().compareTo(sumPlanned) != 0) {
            problems.add("Σ(−delta)（" + sumDelta.negate() + "）≠ Σ planned_meters（" + sumPlanned + "）");
        }
        if (derived.signum() < 0) {
            problems.add("负余量（超扣）：" + derived);
        }
        return problems;
    }

    /**
     * 判据 3 的读数：回补是否**逐值对称**、整单净额是否归零、有没有负库存。
     *
     * <p>在 {@link #ledgerProblems}（账实一致）之上再加三条**只有反向才谈得上**的判据：
     * ① 回补行必须是配对扣减行的相反数；② 整单 {@code Σdelta} 归零；
     * ③ {@code saved_meters}（{@code formula − planned}）相加归零（作废不冒功）。</p>
     */
    private static List<String> reverseProblems(String productId, long batchId,
                                                String processingOrderNo) throws Exception {
        List<String> problems = new ArrayList<>(ledgerProblems(batchId, productId, processingOrderNo));
        List<ConsRow> rows = rawConsumptionRows(processingOrderNo);
        Map<String, BigDecimal> deductionByItem = new LinkedHashMap<>();
        BigDecimal netDelta = BigDecimal.ZERO;
        BigDecimal netSaved = BigDecimal.ZERO;
        BigDecimal inbound = scalar("SELECT quantity FROM stock_batches WHERE id = " + batchId);
        for (ConsRow row : rows) {
            netDelta = netDelta.add(row.delta());
            netSaved = netSaved.add(row.formula().subtract(row.planned()));
            if (StockBatchConsumptionService.REASON_PROCESSING_ORDER.equals(row.reason())) {
                deductionByItem.put(row.orderItemId(), row.delta());
            } else {
                BigDecimal deducted = deductionByItem.get(row.orderItemId());
                if (deducted == null) {
                    problems.add("回补行 " + row.id() + " 找不到配对的扣减行");
                } else if (row.delta().compareTo(deducted.negate()) != 0) {
                    problems.add("回补行 " + row.id() + " 不是扣减行的相反数（" + row.delta()
                            + " ≠ " + deducted.negate() + "）");
                }
            }
        }
        if (netDelta.signum() != 0) {
            problems.add("作废后整单 Σdelta 未归零：" + netDelta);
        }
        if (netSaved.signum() != 0) {
            problems.add("作废后 saved_meters 未归零（作废冒功）：" + netSaved);
        }
        if (inbound.add(netDelta).compareTo(inbound) != 0) {
            problems.add("余量未回到派工前：" + inbound.add(netDelta) + " ≠ " + inbound);
        }
        return problems;
    }

    /** 判据 6 的读数：四档批次数 / 占比是否与**真库已知夹具**逐值一致。 */
    private static List<String> distributionProblems() {
        List<String> problems = new ArrayList<>();
        BatchStockViews.Distribution d = service.distribution(TENANT_ID, DIST_PRODUCT);
        List<Integer> expectedCounts = List.of(2, 1, 1, 3);
        List<BigDecimal> expectedShares = List.of(new BigDecimal("0.2857"), new BigDecimal("0.1429"),
                new BigDecimal("0.1429"), new BigDecimal("0.4286"));
        if (d.totalBatches() != 7) {
            problems.add("总数 ≠ 7：实得 " + d.totalBatches());
        }
        for (int i = 0; i < d.buckets().size() && i < expectedCounts.size(); i++) {
            BatchStockViews.Bucket b = d.buckets().get(i);
            if (b.batchCount() != expectedCounts.get(i)) {
                problems.add(b.key() + " 批次数 ≠ " + expectedCounts.get(i) + "：实得 " + b.batchCount());
            }
            if (b.share() == null || b.share().compareTo(expectedShares.get(i)) != 0) {
                problems.add(b.key() + " 占比 ≠ " + expectedShares.get(i) + "：实得 " + b.share());
            }
        }
        return problems;
    }

    /**
     * 判据 7 的读数：对账恒等式是否成立、两项是否**并存**（任一项为 0 ⇒ 恒等式退化成单项，测不出耦合）。
     *
     * <p>红证不在这里做：扰动会让读数**变红**，而本函数是「判据应当成立」的读数；
     * 红证由调用方在读完之后手动掰开批次腿再复用 {@code service.reconcile} 的原始读数
     * —— 两处读的是**同一个生产读面**，因此「把被测行为改坏它会红吗」有确定答案。</p>
     */
    private static List<String> reconcileProblems() throws Exception {
        List<String> problems = new ArrayList<>();
        BatchStockViews.Reconcile before = service.reconcile(TENANT_ID, REC_PRODUCT, null);
        if (before.rows().size() != 1) {
            problems.add("对账行数 ≠ 1：实得 " + before.rows().size());
            return problems;
        }
        BatchStockViews.ReconcileRow row = before.rows().get(0);
        if (!row.reconciled()) {
            problems.add("恒等式不成立：diff=" + row.diff() + "，explained=" + row.explainedDiff());
        }
        if (row.soldUnbatchedMeters().signum() == 0) {
            problems.add("第 1 项（已售未派）为 0 ⇒ 恒等式退化成单项，测不出「两项并存」");
        }
        if (row.planSavedMeters().signum() == 0) {
            problems.add("第 2 项（排料节省）为 0 ⇒ 恒等式退化成单项，测不出「两项并存」");
        }
        if (row.diff().compareTo(row.soldUnbatchedMeters().add(row.planSavedMeters())) != 0) {
            problems.add("diff ≠ 两项之和：" + row.diff() + " ≠ " + row.soldUnbatchedMeters()
                    + " + " + row.planSavedMeters());
        }
        System.out.println("[#5190 判据7 读数] diff=" + row.diff()
                + "，已售未派=" + row.soldUnbatchedMeters() + "，排料节省=" + row.planSavedMeters()
                + "，formula=" + row.formulaDeductedMeters() + "，dispatched=" + row.dispatchedMeters());
        return problems;
    }

    private static List<String> reconcileReadings() throws Exception {
        BatchStockViews.Reconcile r = service.reconcile(TENANT_ID, REC_PRODUCT, null);
        List<String> out = new ArrayList<>();
        for (BatchStockViews.ReconcileRow row : r.rows()) {
            out.add("sku=" + row.skuCode() + " stock=" + row.skuStock() + " batchRemaining="
                    + row.batchRemaining() + " diff=" + row.diff() + " explained=" + row.explainedDiff()
                    + " 已售未派=" + row.soldUnbatchedMeters() + " 排料节省=" + row.planSavedMeters()
                    + " reconciled=" + row.reconciled());
        }
        return out;
    }

    /** 台账逐行读数（打印给人看：判据的「原始输出」）。 */
    private static List<String> ledgerReadings(String processingOrderNo) throws Exception {
        List<String> out = new ArrayList<>();
        for (ConsRow row : rawConsumptionRows(processingOrderNo)) {
            out.add("#" + row.id() + " " + row.reason() + " delta=" + row.delta() + " before="
                    + row.before() + " after=" + row.after() + " formula=" + row.formula()
                    + " planned=" + row.planned());
        }
        return out;
    }

    private static BigDecimal readFaceRemaining(String productId, long batchId) {
        for (BatchStockViews.BatchRemaining row : service.remaining(TENANT_ID, productId, null, false)) {
            if (row.batchId() == batchId) {
                return row.remainingMeters();
            }
        }
        return null;
    }

    // ══════════════════════════════════ 真库小工具（一律走裸 JDBC）

    /** 台账一行（**读回真库的列**，不经过实体映射 ⇒ 列名/类型漂移也会被抓）。 */
    private record ConsRow(long id, BigDecimal delta, BigDecimal before, BigDecimal after,
                           BigDecimal formula, BigDecimal planned, String reason, String orderItemId) {
    }

    private static List<ConsRow> rawConsumptionRows(String processingOrderNo) throws Exception {
        List<ConsRow> out = new ArrayList<>();
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery("SELECT id, delta, before_qty, after_qty, formula_meters,"
                     + " planned_meters, reason, order_item_id FROM stock_batch_consumptions WHERE"
                     + " tenant_id = " + TENANT_ID + " AND processing_order_no = '" + processingOrderNo
                     + "' AND deleted = 0 ORDER BY id")) {
            while (rs.next()) {
                out.add(new ConsRow(rs.getLong(1), rs.getBigDecimal(2), rs.getBigDecimal(3),
                        rs.getBigDecimal(4), rs.getBigDecimal(5), rs.getBigDecimal(6), rs.getString(7),
                        rs.getString(8)));
            }
        }
        return out;
    }

    /** 裸 INSERT 一行台账（红证 / 约束判据用的夹具；列取库要求的必填集）。 */
    private static String rawRow(long batchId, String batchNo, String poNo, String itemId,
                                String formula, String planned, String delta) {
        return "INSERT INTO stock_batch_consumptions (tenant_id, batch_id, batch_no, product_id,"
                + " sku_id, sku_code, delta, before_qty, after_qty, formula_meters, planned_meters,"
                + " unit_cost, reason, processing_order_no, order_no, order_item_id, operator, note)"
                + " VALUES (" + TENANT_ID + ", " + batchId + ", '" + batchNo + "', '" + LEDGER_PRODUCT
                + "', " + LEDGER_SKU_ID + ", '" + LEDGER_SKU + "', " + delta + ", 60, 60, " + formula
                + ", " + planned + ", 12.5, 'processing_order', '" + poNo + "', 'ORD-" + poNo + "', '"
                + itemId + "', 'system', '#5190 约束夹具')";
    }

    /**
     * 在**回滚事务**里跑一段 DDL + 取一个 SQLSTATE（PG 的 DDL 是事务性的 ⇒ 零残留）。
     *
     * <p>红证要能「把约束摘掉看会不会变」而不污染其它判据 —— 这比 try/finally 里恢复 DDL
     * 更安全（异常路径也不会漏）。</p>
     */
    private static String inRolledBackTransaction(SqlProbe probe) throws Exception {
        try (Connection conn = dataSource.getConnection()) {
            conn.setAutoCommit(false);
            try {
                return probe.run(conn);
            } finally {
                conn.rollback();
            }
        }
    }

    private interface SqlProbe {
        String run(Connection conn) throws Exception;
    }

    private static String sqlStateOn(Connection conn, String sql) {
        try (Statement st = conn.createStatement()) {
            st.execute(sql);
            return null;
        } catch (SQLException e) {
            return e.getSQLState();
        }
    }

    /** 裸 SQL 被数据库拒绝时的 SQLSTATE（**没被拒 ⇒ `null`**，由调用方断言具体码）。 */
    private static String sqlStateOfRejected(String sql) {
        try {
            exec(sql);
            return null;
        } catch (Exception e) {
            return sqlStateOfThrowable(e);
        }
    }

    /** 沿 cause 链找 SQLSTATE（唯一闸/约束的证据必须是数据库给的，不是文案匹配）。 */
    private static String sqlStateOfThrowable(Throwable failure) {
        Throwable current = failure;
        while (current != null) {
            if (current instanceof SQLException sqlException) {
                return sqlException.getSQLState();
            }
            current = current.getCause();
        }
        return null;
    }

    /** 业务层的拒绝读数（**未抛业务异常**时回一个显式的哨兵码，避免「拿 null 当断言」）。 */
    private record Rejection(String code, int httpStatus, String suggestion) {
    }

    private static Rejection rejection(Runnable action) {
        Throwable failure = catchThrowable(action::run);
        if (failure instanceof BusinessException business) {
            return new Rejection(business.getCode(), business.getHttpStatus(),
                    business.getSuggestion() == null ? "" : business.getSuggestion());
        }
        return new Rejection("（未抛业务异常：" + failure + "）", -1, "");
    }

    private static BigDecimal scalar(String sql) throws Exception {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery(sql)) {
            assertThat(rs.next()).as("查询必须有结果：" + sql).isTrue();
            BigDecimal value = rs.getBigDecimal(1);
            return value;
        }
    }

    private static void exec(String sql) throws Exception {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute(sql);
        }
    }

    private static long countRows(String processingOrderNo) throws Exception {
        return scalar("SELECT COUNT(*) FROM stock_batch_consumptions WHERE tenant_id = " + TENANT_ID
                + " AND processing_order_no = '" + processingOrderNo + "' AND deleted = 0").longValue();
    }

    /** 批次余量 = {@code stock_batches.quantity + Σ(delta)}（与生产读面同一条公式）。 */
    private static BigDecimal remainingOf(long batchId) throws Exception {
        return scalar("SELECT (SELECT quantity FROM stock_batches WHERE id = " + batchId + ")"
                + " + COALESCE((SELECT SUM(delta) FROM stock_batch_consumptions WHERE batch_id = "
                + batchId + " AND deleted = 0), 0)");
    }

    private static long newBatch(String productId, long skuId, String skuCode, String batchNo,
                                String meters) throws Exception {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery("INSERT INTO stock_batches (tenant_id, batch_no, product_id,"
                     + " sku_id, sku_code, quantity, unit_cost) VALUES (" + TENANT_ID + ", '" + batchNo
                     + "', '" + productId + "', " + skuId + ", '" + skuCode + "', " + meters + ", "
                     + UNIT_COST.toPlainString() + ") RETURNING id")) {
            assertThat(rs.next()).as("批次夹具必须落库").isTrue();
            return rs.getLong(1);
        }
    }

    /** **公式口径**的一行（没有定尺入参 ⇒ 不排料 ⇒ 扣减口径 = 公式米数）：账实一致判据的稳定夹具。 */
    private static StockBatchConsumptionService.Designation formulaOnly(String productId, String itemId,
                                                                       String batchNo, String meters) {
        return new StockBatchConsumptionService.Designation(itemId, productId, null, batchNo,
                new BigDecimal(meters), null, null, null);
    }

    /** 定高买宽的一扇矮窗（门幅 2.8：窗高 1.1 + 卷边 0.3 = 占 1.4 ⇒ 两扇并排成立）。 */
    private static StockBatchConsumptionService.Designation fixedHeight(String productId, String itemId,
                                                                       String batchNo, String meters) {
        return new StockBatchConsumptionService.Designation(itemId, productId, null, batchNo,
                new BigDecimal(meters), "定高买宽", new BigDecimal("1.1"), null);
    }

    private static String product(String productId, String name) {
        return "INSERT INTO products (id, tenant_id, name) VALUES ('" + productId + "', " + TENANT_ID
                + ", '" + name + "')";
    }

    private static String sku(long skuId, String productId, String doorWidth, String skuCode,
                              String stock) {
        return "INSERT INTO product_skus (id, tenant_id, product_id, door_width, price, stock, sku_code)"
                + " OVERRIDING SYSTEM VALUE VALUES (" + skuId + ", " + TENANT_ID + ", '" + productId
                + "', '" + doorWidth + "', 100, " + stock + ", '" + skuCode + "')";
    }

    /** bootstrap 终态 schema（**不手抄列清单** ⇒ 列名 / 约束漂移会被抓）。 */
    private static String schemaSql() throws IOException {
        Path root = Paths.get(System.getProperty("user.dir")).toAbsolutePath();
        while (root != null && !Files.exists(root.resolve("backend/admin-api/src/main/resources/db/init/schema.sql"))) {
            root = root.getParent();
        }
        assertThat(root).as("必须能定位 backend/admin-api/src/main/resources/db/init/schema.sql（真库建表取终态 schema，不手抄列清单）").isNotNull();
        return Files.readString(root.resolve("backend/admin-api/src/main/resources/db/init/schema.sql"));
    }
}
