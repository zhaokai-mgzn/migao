// case_ids: PR-097, PR-098, PR-099
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.MybatisSqlSessionFactoryBuilder;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.MybatisPlusInterceptor;
import com.baomidou.mybatisplus.extension.plugins.handler.TenantLineHandler;
import com.baomidou.mybatisplus.extension.plugins.inner.TenantLineInnerInterceptor;
import com.migao.admin.dto.RemnantViews;
import com.migao.admin.entity.FabricRemnant;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.CraftCalcConfigMapper;
import com.migao.admin.mapper.FabricRemnantMapper;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProductSkuMapper;
import com.migao.admin.mapper.ProductionOperationMapper;
import com.migao.admin.mapper.ProductionOptionRoutingMapper;
import com.migao.admin.mapper.RemnantItemSizeMapper;
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
import java.sql.Statement;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.catchThrowable;

/**
 * 🔴 <b>余料成本回收的**真库**判据（issue #5146）</b>——非资产台账 + 小件优先匹配 + 回收记账 + 报废留痕。
 *
 * <h2>为什么必须真库（Mockito 测不出来）</h2>
 * 本单最要害的两条都只有真库能判：
 * <ol>
 *   <li><b>不算资产</b>：{@code Σ product_skus.cost_amount} 与 {@code Σ product_skus.stock}
 *       <b>逐值不变</b> —— 这是「加了一张表却不碰库存金额」的**唯一**证据（mock 只会证明
 *       「没调那个方法」，而真正的风险是**约束/触发器/列默认值**这一层）；</li>
 *   <li><b>不新增批次消耗</b>：余料被用掉之后 {@code stock_batch_consumptions} 的**行数与 Σdelta
 *       逐值不变** —— 判据 3 的原话（批次数不变）。</li>
 * </ol>
 * 另外「账实一致」不是靠读面自觉，而是靠 V122 的 {@code ck_fabric_remnant_lifecycle} /
 * {@code ck_fabric_remnant_amount}：本测试**故意**去写一行自相矛盾的余料，断言数据库当场拒绝
 * （SQLSTATE 23514）—— 那才证明约束真的钉住了，而不是「写在注释里」。
 *
 * <h2>判据（每条都带**能单独变红**的红证）</h2>
 * <ol>
 *   <li>🔴 <b>不算资产</b>：派工自动登记余料前后，库存金额/库存量逐值不变；
 *       <b>红证</b> = 手动 {@code UPDATE product_skus SET cost_amount = cost_amount + 1}
 *       ⇒ 同一个读数必须变（证明这条断言不是恒真）。</li>
 *   <li><b>不损失客户</b>：登记 + 匹配 + 回收 + 报废走完，{@code orders.total_amount} 与
 *       {@code order_items}(unit_price/subtotal/quantity/width/height) 逐值不变；
 *       <b>红证</b> = 手动改 {@code unit_price} ⇒ 读数必须变。</li>
 *   <li>🔴 <b>同缸号余料被用掉 ⇒ 不新增批次消耗 + 回收额正确</b>：命中同缸号余料 ⇒
 *       {@code stock_batch_consumptions} 行数与 Σdelta 逐值不变，且
 *       {@code recovered_amount = 用掉米数 × 该批次当时均价}；</li>
 *   <li>🔴 <b>未配置不静默</b>：清空尺寸表 ⇒ 匹配 {@code configured=false}、推荐为空、
 *       {@code notice} 非空；<b>红证</b> = 配一行 ⇒ {@code configured=true} 且 {@code notice} 为空；</li>
 *   <li><b>不凭空推荐</b>：余料尺寸 &lt; 小件用料 ⇒ 无推荐且给出可读原因；</li>
 *   <li><b>单价口径</b>：回收后改 {@code stock_batches.unit_cost} ⇒ 历史回收额一字不变；</li>
 *   <li>🔴 <b>客户带走不入可用池</b>：{@code 余料带回-布} ⇒ 状态 {@code customer_taken}、
 *       匹配不命中、回收被拒；<b>红证</b> = 手动改成 {@code available} ⇒ 匹配立刻命中；</li>
 *   <li><b>报废留痕</b>：状态 / 原因 / 操作人 / 时刻可读；重复报废被拒；
 *       <b>红证</b> = 抹掉 {@code scrap_reason} ⇒ 数据库当场拒绝（ck_fabric_remnant_lifecycle）。</li>
 * </ol>
 *
 * <h2>环境</h2>
 * 一次性真 PG 集群（{@code initdb} + {@code pg_ctl}，随机端口、跑完即停），schema 取自
 * {@code backend/admin-api/src/main/resources/db/init/schema.sql}（bootstrap 终态，**不手抄列清单** ⇒ 列名/约束漂移会被抓）。
 * 缺 PG 二进制 ⇒ {@link PgCluster#startOrAbort()}：
 * CI（{@code MIGAO_REQUIRE_REALDB=1}）⇒ 判红；本机未设该标记 ⇒ 显式 skip（「没跑」长得像「没跑」，不是通过）。
 *
 * <p>范式与 {@code PgCluster}（#5167 提取的共用件）同款 —— 复用既有 PG 装配，不复制第二份。</p>
 */
@DisplayName("#5146 真库守卫：余料非资产台账 + 小件优先匹配 + 回收记账 + 报废留痕")
class RemnantRecoveryRealDbTest {

    private static final Long TENANT_ID = 5146L;
    private static final Long SKU_ID = 5146L;
    private static final String PRODUCT_ID = "acc-5146-prod";
    private static final String SKU_CODE = "SKU-5146";
    private static final BigDecimal DOOR_WIDTH = new BigDecimal("2.8");
    private static final BigDecimal BATCH_UNIT_COST = new BigDecimal("12.5");
    /** 缸号 —— 「同缸号优先匹配」的判据靠它（不同批次同缸号 = 同一次染色）。 */
    private static final String DYE_LOT = "LOT-5146";

    private static PgCluster cluster;
    private static DataSource dataSource;
    private static SqlSessionFactory factory;
    private static SqlSession session;
    private static RemnantService remnantService;
    private static StockBatchConsumptionService batchStock;
    private static int orderSeq = 0;

    @BeforeAll
    static void startRealPostgresAndFixtures() throws Exception {
        cluster = PgCluster.startOrAbort();
        dataSource = cluster.dataSource();
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute(schemaSql());
            st.execute("INSERT INTO tenants (id, name, code) OVERRIDING SYSTEM VALUE VALUES ("
                    + TENANT_ID + ", 'acc-5146', 'acc-5146')");
            st.execute("INSERT INTO products (id, tenant_id, name) VALUES ('" + PRODUCT_ID + "', "
                    + TENANT_ID + ", '布艺遮光帘余料件')");
            // cost_amount / stock 是本单判据 1 的被测对象 ⇒ 夹具里给**非零**真值
            //（全 0 的库存金额上「逐值不变」是空断言：加不加都在 0）
            st.execute("INSERT INTO product_skus (id, tenant_id, product_id, door_width, price, stock,"
                    + " sku_code, avg_cost, cost_amount) OVERRIDING SYSTEM VALUE VALUES (" + SKU_ID + ", "
                    + TENANT_ID + ", '" + PRODUCT_ID + "', '" + DOOR_WIDTH + "米', 100, 60, '"
                    + SKU_CODE + "', " + BATCH_UNIT_COST + ", 750)");
            st.execute("INSERT INTO craft_calc_configs (id, tenant_id) VALUES ('cfg-acc-5146', "
                    + TENANT_ID + ")");
            // 工序库：小件尺寸表的 item_key 必须能在工序库里逐字找到（写面 fail-closed 判据）
            st.execute("INSERT INTO production_operations (id, tenant_id, name) VALUES"
                    + " ('op-5146-1', " + TENANT_ID + ", '绑带-布'),"
                    + " ('op-5146-2', " + TENANT_ID + ", '帘头制作')");
            // 特殊选项 → 条件工序（**既有唯一真值源**）：匹配的小件需求由它解析
            st.execute("INSERT INTO production_option_routings"
                    + " (id, tenant_id, option_name, operation_name, after_operation, sort_order, status)"
                    + " VALUES ('or-5146-1', " + TENANT_ID + ", '余料做绑带', '绑带-布', '布帘车被', 8, 'active'),"
                    + " ('or-5146-2', " + TENANT_ID + ", '余料做帘头', '帘头制作', '布三边', 10, 'active')");
        }
        MybatisConfiguration configuration = new MybatisConfiguration();
        configuration.setMapUnderscoreToCamelCase(true);
        // 🔴 一级缓存必须设在 STATEMENT 级：本测试的**红证**用裸 JDBC 改库（绕过 session），
        // 而 SESSION 级缓存不会因那次改动失效 ⇒ 同一个查询会拿到**改前**的结果，
        // 红证就变成假绿（实测：UPDATE 之后匹配仍返回空）。这是测试装配问题，不是生产行为问题。
        configuration.setLocalCacheScope(org.apache.ibatis.session.LocalCacheScope.STATEMENT);
        configuration.setEnvironment(new Environment("acc-5146", new JdbcTransactionFactory(), dataSource));
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
                ProductSkuMapper.class, CraftCalcConfigMapper.class, FabricRemnantMapper.class,
                RemnantItemSizeMapper.class, ProductionOperationMapper.class,
                ProductionOptionRoutingMapper.class, OrderMapper.class, OrderItemMapper.class)) {
            configuration.addMapper(mapper);
        }
        factory = new MybatisSqlSessionFactoryBuilder().build(configuration);
        session = factory.openSession(true);

        remnantService = new RemnantService(session.getMapper(FabricRemnantMapper.class),
                session.getMapper(RemnantItemSizeMapper.class),
                session.getMapper(StockBatchMapper.class),
                session.getMapper(StockBatchConsumptionMapper.class),
                session.getMapper(ProductionOperationMapper.class),
                session.getMapper(ProductionOptionRoutingMapper.class),
                session.getMapper(OrderMapper.class),
                session.getMapper(OrderItemMapper.class));
        CraftCalcConfigService configService = new CraftCalcConfigService(
                session.getMapper(CraftCalcConfigMapper.class), null);
        // 🔴 本单的核心接线：**真装配**余料腿 ⇒ 派工扣批次之后自动登记余料（不需要人手工登记）
        batchStock = new StockBatchConsumptionService(session.getMapper(StockBatchMapper.class),
                session.getMapper(StockBatchConsumptionMapper.class),
                session.getMapper(ProductSkuMapper.class), null, configService, remnantService);
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

    // ══════════════════════════════════════════════════════════════════════════════════
    // 判据 1：🔴 不算资产（本单守门判据）
    // ══════════════════════════════════════════════════════════════════════════════════

    @Test
    @DisplayName("🔴 判据1 不算资产：派工自动登记余料 ⇒ Σcost_amount / Σstock 逐值不变（红证：动一下就变）")
    void remnantAccrualNeverTouchesStockAmount() throws Exception {
        String orderNo = newOrder("非资产业主单");
        BigDecimal costBefore = scalar("SELECT COALESCE(SUM(cost_amount), 0) FROM product_skus"
                + " WHERE tenant_id = " + TENANT_ID);
        BigDecimal stockBefore = scalar("SELECT COALESCE(SUM(stock), 0) FROM product_skus"
                + " WHERE tenant_id = " + TENANT_ID);
        assertThat(costBefore).as("夹具的库存金额必须非零（否则「逐值不变」是空断言）")
                .isEqualByComparingTo("750");

        int accrued = accruePair(orderNo, "PC-5146-ASSET");
        System.out.println("[#5146 判别性实验] 本次自动登记余料 " + accrued + " 块");
        assertThat(accrued).as("排料结果里确实有空处 ⇒ 台账必须真有行（否则下面的不变是空跑）")
                .isGreaterThan(0);

        assertThat(scalar("SELECT COALESCE(SUM(cost_amount), 0) FROM product_skus WHERE tenant_id = "
                + TENANT_ID)).as("🔴 加余料登记后库存金额**逐值不变**").isEqualByComparingTo(costBefore);
        assertThat(scalar("SELECT COALESCE(SUM(stock), 0) FROM product_skus WHERE tenant_id = "
                + TENANT_ID)).as("库存量同样逐值不变").isEqualByComparingTo(stockBefore);

        // 非资产的自证：余料台账**没有任何计价列**（有人「顺手」加一列 unit_cost 就红）
        assertThat(scalar("SELECT COUNT(*) FROM information_schema.columns WHERE table_schema = 'public'"
                + " AND table_name = 'fabric_remnants' AND column_name IN"
                + " ('unit_cost', 'amount', 'cost_amount', 'avg_cost', 'price')"))
                .as("fabric_remnants 不得出现计价列（余料不是资产）").isEqualByComparingTo("0");

        // 🔴 红证：把库存金额动一下 ⇒ 同一个读数必须变（证明上面那条断言真的在判东西）
        exec("UPDATE product_skus SET cost_amount = cost_amount + 1 WHERE id = " + SKU_ID);
        assertThat(scalar("SELECT COALESCE(SUM(cost_amount), 0) FROM product_skus WHERE tenant_id = "
                + TENANT_ID))
                .as("红证：库存金额一旦真的变了，上面的比较式就必须判不等")
                .isNotEqualByComparingTo(costBefore);
        exec("UPDATE product_skus SET cost_amount = cost_amount - 1 WHERE id = " + SKU_ID);
    }

    // ══════════════════════════════════════════════════════════════════════════════════
    // 判据 2：不损失客户
    // ══════════════════════════════════════════════════════════════════════════════════

    @Test
    @DisplayName("判据2 不损失客户：登记 + 匹配 + 回收 + 报废走完，对客金额与成品口径逐值不变")
    void customerFacingAmountsAreUntouched() throws Exception {
        putSpec("绑带-布", "2.5", "0.2");
        String orderNo = newOrder("不损客户单");
        String itemId = orderItemOf(orderNo, "余料做绑带");
        accruePair(orderNo, "PC-5146-CUST");
        String snapshotBefore = customerFacingReadings(orderNo);

        RemnantViews.MatchView match = remnantService.match(TENANT_ID, itemId, "PC-5146-CUST");
        assertThat(match.recommendations()).as("夹具里应命中一块装得下的余料").isNotEmpty();
        Long remnantId = match.recommendations().get(0).remnantId();
        remnantService.recover(TENANT_ID, remnantId, itemId, orderNo, "绑带-布");

        // 再报废一块（**另一张单**的余料）—— 报废同样不得碰对客口径
        String scrapOrderNo = newOrder("不损客户-待报废");
        accruePair(scrapOrderNo, "PC-5146-CUST2");
        List<RemnantViews.RemnantLine> scappable = remnantService
                .ledger(TENANT_ID, FabricRemnant.STATUS_AVAILABLE, "PC-5146-CUST2", null, 1, 50)
                .page().getItems();
        assertThat(scappable).as("报废需要至少一块可用余料").hasSize(1);
        remnantService.scrap(TENANT_ID, scappable.get(0).id(), "超期未用");

        assertThat(customerFacingReadings(orderNo))
                .as("🔴 对客售价 / 小计 / 数量 / 成品宽高逐值不变（余料回收只进内部成本口径）")
                .isEqualTo(snapshotBefore);

        // 🔴 红证：把对客单价改一下 ⇒ 同一个读数必须变（证明这条断言不是恒真）
        exec("UPDATE order_items SET unit_price = unit_price + 1 WHERE order_id ="
                + " (SELECT id FROM orders WHERE order_no = '" + orderNo + "')");
        assertThat(customerFacingReadings(orderNo))
                .as("红证：对客口径一旦真的变了，上面的比较式就必须判不等").isNotEqualTo(snapshotBefore);
        exec("UPDATE order_items SET unit_price = unit_price - 1 WHERE order_id ="
                + " (SELECT id FROM orders WHERE order_no = '" + orderNo + "')");
    }

    // ══════════════════════════════════════════════════════════════════════════════════
    // 判据 3：🔴 同缸号余料被用掉 ⇒ 不新增批次消耗 + 回收额正确
    // ══════════════════════════════════════════════════════════════════════════════════

    @Test
    @DisplayName("🔴 判据3 优先匹配真的省料：同缸号优先（防色差）+ 批次数不变 + 回收额 = 米数 × 当时均价")
    void matchingRemnantDoesNotIssueNewMaterial() throws Exception {
        putSpec("绑带-布", "2.2", "0.2");
        String orderNo = newOrder("余料做绑带单");
        String itemId = orderItemOf(orderNo, "余料做绑带");

        // 三块余料，尺寸**故意**安排成「异缸号的那块最小」（= 单纯按「先小块」挑会挑到它）
        newBatch("PC-5146-REUSE", "LOT-D1");                                  // 本行的批次（缸号 D1）
        accrueOnBatch(orderNo, "PC-5146-REUSE", "3", "1.1", "0.8");            // → 3.0 × 0.3
        newBatch("PC-5146-SAMELOT", "LOT-D1");                                // 同缸号（D1）
        accrueOnBatch("ORD-5146-SAMELOT", "PC-5146-SAMELOT", "2.6", "1.1", "0.8"); // → 2.6 × 0.3
        newBatch("PC-5146-OTHER", "LOT-D2");                                  // 异缸号（D2）
        accrueOnBatch("ORD-5146-OTHER", "PC-5146-OTHER", "2.4", "1.1", "0.8");     // → 2.4 × 0.3（最小）

        RemnantViews.MatchView match = remnantService.match(TENANT_ID, itemId, "PC-5146-REUSE");
        assertThat(match.configured()).as("尺寸表已配置").isTrue();
        assertThat(match.recommendations()).as("三块都装得下 ⇒ 必须给出且只给一条建议").hasSize(1);
        RemnantViews.Recommendation rec = match.recommendations().get(0);
        assertThat(rec.sameDyeLot()).as("🔴 同缸号优先（防色差）").isTrue();
        assertThat(rec.sourceBatchNo())
                .as("🔴 挑的是**同缸号**那块（2.6 米），不是更小但异缸号的那块（2.4 米）"
                        + " —— 「同缸号优先」优先于「先用小块」")
                .isEqualTo("PC-5146-SAMELOT");
        assertThat(rec.recoverableMeters()).as("用掉米数 = 该余料沿卷长的长度")
                .isEqualByComparingTo("2.6");
        assertThat(rec.recoverableAmount()).as("回收额 = 用掉米数 × 该批次当时均价")
                .isEqualByComparingTo("32.50");

        long rowsBefore = scalar("SELECT COUNT(*) FROM stock_batch_consumptions WHERE tenant_id = "
                + TENANT_ID).longValue();
        BigDecimal deltaBefore = scalar("SELECT COALESCE(SUM(delta), 0) FROM stock_batch_consumptions"
                + " WHERE tenant_id = " + TENANT_ID);
        BigDecimal stockBefore = scalar("SELECT COALESCE(SUM(stock), 0) FROM product_skus WHERE"
                + " tenant_id = " + TENANT_ID);

        remnantService.recover(TENANT_ID, rec.remnantId(), itemId, orderNo, "绑带-布");

        assertThat(scalar("SELECT COUNT(*) FROM stock_batch_consumptions WHERE tenant_id = "
                + TENANT_ID).longValue())
                .as("🔴 判据 3 原话「该小件不产生新的批次消耗（批次数不变）」").isEqualTo(rowsBefore);
        assertThat(scalar("SELECT COALESCE(SUM(delta), 0) FROM stock_batch_consumptions"
                + " WHERE tenant_id = " + TENANT_ID))
                .as("批次余量净额也逐值不变（没有新领一米料）").isEqualByComparingTo(deltaBefore);
        assertThat(scalar("SELECT COALESCE(SUM(stock), 0) FROM product_skus WHERE tenant_id = "
                + TENANT_ID)).as("销售账（SKU 库存）同样不碰").isEqualByComparingTo(stockBefore);

        Map<String, Object> recovered = row("SELECT status, recovered_meters, recovered_unit_cost,"
                + " recovered_amount, used_by_order_no, used_by_item_key, recovered_by, recovered_at"
                + " FROM fabric_remnants WHERE id = " + rec.remnantId());
        assertThat(recovered.get("status")).isEqualTo(FabricRemnant.STATUS_USED);
        assertThat((BigDecimal) recovered.get("recovered_meters")).isEqualByComparingTo("2.6");
        assertThat((BigDecimal) recovered.get("recovered_unit_cost")).isEqualByComparingTo("12.5");
        assertThat((BigDecimal) recovered.get("recovered_amount")).as("账实一致：金额 = 米数 × 均价")
                .isEqualByComparingTo("32.50");
        assertThat(recovered.get("used_by_order_no")).as("冲减**使用它的那张单**").isEqualTo(orderNo);
        assertThat(recovered.get("used_by_item_key")).isEqualTo("绑带-布");
        assertThat(recovered.get("recovered_by")).as("谁").isNotNull();
        assertThat(recovered.get("recovered_at")).as("何时").isNotNull();

        // 同一张单的同一小件不得再消耗第二块余料（不重复回收）
        RemnantViews.MatchView again = remnantService.match(TENANT_ID, itemId, "PC-5146-REUSE");
        assertThat(again.recommendations())
                .as("已用掉的余料不再出现在可用池里").noneMatch(r -> r.remnantId().equals(rec.remnantId()));
        RemnantViews.Recommendation second = again.recommendations().get(0);
        Throwable duplicate = catchThrowable(() -> remnantService.recover(TENANT_ID,
                second.remnantId(), itemId, orderNo, "绑带-布"));
        assertThat(duplicate).as("同一明细行 × 同一小件只能消耗一块余料（幂等闸 uk_fabric_remnants_recovery）")
                .isNotNull();
    }

    // ══════════════════════════════════════════════════════════════════════════════════
    // 判据 4 / 5：未配置不静默 + 不凭空推荐
    // ══════════════════════════════════════════════════════════════════════════════════

    @Test
    @DisplayName("🔴 判据4 未配置不静默：清空尺寸表 ⇒ 无推荐 + 显式说明（红证：配一行 ⇒ 说明消失）")
    void unconfiguredSpecsAreNeverSilent() throws Exception {
        String orderNo = newOrder("未配置单");
        String itemId = orderItemOf(orderNo, "余料做绑带");
        accruePair(orderNo, "PC-5146-UNSET"); // 有可用余料 —— 排除「没料所以没推荐」这个干扰项

        remnantService.putSpecs(TENANT_ID, List.of()); // 清空 = 回到未配置
        RemnantViews.MatchView unset = remnantService.match(TENANT_ID, itemId, "PC-5146-UNSET");
        assertThat(unset.configured()).as("清空后读面必须说「未配置」").isFalse();
        assertThat(unset.recommendations()).as("🔴 未配置 ⇒ **不产生任何推荐**").isEmpty();
        assertThat(unset.notice()).as("🔴 未配置 ⇒ **有可见说明**（不得静默）").isNotNull();
        assertThat(unset.notice()).contains("未配置");
        assertThat(unset.requiredItems()).as("需求侧照实回（商家才知道要配哪个小件）")
                .containsExactly("绑带-布");
        assertThat(remnantService.specs(TENANT_ID).notice())
                .as("配置读面同样显式说明「未启用」（§22 P3 默认值可见）").isNotNull();

        // 🔴 红证：配一行 ⇒ configured 翻转、notice 消失、并且**真的开始匹配**
        putSpec("绑带-布", "2.5", "0.2");
        RemnantViews.MatchView set = remnantService.match(TENANT_ID, itemId, "PC-5146-UNSET");
        assertThat(set.configured()).as("红证：配了就必须判为已配置").isTrue();
        assertThat(set.notice()).as("红证：配了之后「未配置」说明必须消失").isNull();
        assertThat(set.recommendations()).as("同一份夹具，配了尺寸就命中 ⇒ 差别只在配置").isNotEmpty();
    }

    @Test
    @DisplayName("判据5 不凭空推荐：余料尺寸 < 小件用料 ⇒ 无推荐且原因可读；放宽需求 ⇒ 命中")
    void tooSmallRemnantIsNeverRecommended() throws Exception {
        String orderNo = newOrder("尺寸不足单");
        String itemId = orderItemOf(orderNo, "余料做绑带");
        accruePair(orderNo, "PC-5146-SMALL"); // 余料 = 3.0 × 0.3

        // 需求宽 0.5 > 余料宽 0.3 ⇒ 装不下 ⇒ 不得推荐
        putSpec("绑带-布", "2.5", "0.5");
        RemnantViews.MatchView tooWide = remnantService.match(TENANT_ID, itemId, "PC-5146-SMALL");
        assertThat(tooWide.recommendations()).as("🔴 尺寸不足 ⇒ 不得推荐（不凭空推荐）").isEmpty();
        assertThat(tooWide.unmatched()).as("不给建议时**必须给原因**").hasSize(1);
        assertThat(tooWide.unmatched().get(0).reason()).contains("尺寸");

        // 需求长 3.5 > 余料长 3.0 ⇒ 同样装不下
        putSpec("绑带-布", "3.5", "0.2");
        assertThat(remnantService.match(TENANT_ID, itemId, "PC-5146-SMALL").recommendations())
                .as("长边不足 ⇒ 同样不得推荐").isEmpty();

        // 正向对照：两条边都够 ⇒ 命中（证明上面两次「空」是因为尺寸，不是别的原因）
        putSpec("绑带-布", "2.5", "0.2");
        assertThat(remnantService.match(TENANT_ID, itemId, "PC-5146-SMALL").recommendations())
                .as("正向对照：同夹具、只把需求改小 ⇒ 必须命中").hasSize(1);
    }

    // ══════════════════════════════════════════════════════════════════════════════════
    // 判据 6：单价口径（当时均价，改价不改历史读数）
    // ══════════════════════════════════════════════════════════════════════════════════

    @Test
    @DisplayName("判据6 单价口径：回收后改批次均价 ⇒ 历史回收额一字不变（用的是行内快照）")
    void recoveredAmountUsesSnapshotUnitCost() throws Exception {
        putSpec("绑带-布", "2.5", "0.2");
        String orderNo = newOrder("改价单");
        String itemId = orderItemOf(orderNo, "余料做绑带");
        accruePair(orderNo, "PC-5146-PRICE");
        RemnantViews.Recommendation rec = remnantService
                .match(TENANT_ID, itemId, "PC-5146-PRICE").recommendations().get(0);
        remnantService.recover(TENANT_ID, rec.remnantId(), itemId, orderNo, "绑带-布");

        BigDecimal amountBefore = scalar("SELECT recovered_amount FROM fabric_remnants WHERE id = "
                + rec.remnantId());
        assertThat(amountBefore).isEqualByComparingTo("37.50");

        exec("UPDATE stock_batches SET unit_cost = 99 WHERE batch_no = 'PC-5146-PRICE'");

        assertThat(scalar("SELECT recovered_amount FROM fabric_remnants WHERE id = " + rec.remnantId()))
                .as("🔴 用的是**当时**均价（行内快照）⇒ 换价后历史读数不变").isEqualByComparingTo(amountBefore);
        assertThat(scalar("SELECT recovered_unit_cost FROM fabric_remnants WHERE id = " + rec.remnantId()))
                .as("快照列本身也不得跟着变").isEqualByComparingTo("12.5");
    }

    // ══════════════════════════════════════════════════════════════════════════════════
    // 判据 7：🔴 客户带走的余料不入可用池
    // ══════════════════════════════════════════════════════════════════════════════════

    @Test
    @DisplayName("🔴 判据7 客户带走：余料带回-布 ⇒ 状态=客户带走、不匹配、不可回收（红证：改成可用 ⇒ 立刻命中）")
    void customerTakenRemnantsStayOutOfTheAvailablePool() throws Exception {
        putSpec("绑带-布", "2.5", "0.2");
        String orderNo = newOrder("客户带走单");
        String itemId = orderItemOf(orderNo, "余料带回-布", "余料做绑带");
        accruePair(orderNo, "PC-5146-TAKEN");

        assertThat(scalar("SELECT COUNT(*) FROM fabric_remnants WHERE source_order_no = '" + orderNo
                + "' AND status = 'customer_taken'"))
                .as("🔴 客户带走的余料**仍然登记**（账要平）但状态是客户带走").isEqualByComparingTo("1");
        assertThat(scalar("SELECT COUNT(*) FROM fabric_remnants WHERE source_order_no = '" + orderNo
                + "' AND status = 'available'"))
                .as("🔴 且**不进可用池**").isEqualByComparingTo("0");

        RemnantViews.MatchView match = remnantService.match(TENANT_ID, itemId, "PC-5146-TAKEN");
        assertThat(match.recommendations())
                .as("🔴 客户带走的余料**不参与匹配**（余料归客户，企业无权处置）").isEmpty();

        Long takenId = scalar("SELECT id FROM fabric_remnants WHERE source_order_no = '" + orderNo
                + "'").longValue();
        Throwable refused = catchThrowable(() ->
                remnantService.recover(TENANT_ID, takenId, itemId, orderNo, "绑带-布"));
        assertThat(refused).as("客户带走的余料**不可回收**").isInstanceOf(BusinessException.class);
        assertThat(((BusinessException) refused).getCode())
                .isEqualTo(RemnantService.ERR_REMNANT_NOT_AVAILABLE);
        assertThat(catchThrowable(() -> remnantService.scrap(TENANT_ID, takenId, "想报废")))
                .as("客户带走的余料**也不可报废**（不是企业的东西）").isInstanceOf(BusinessException.class);

        // 🔴 红证：手动把它混进可用池 ⇒ 匹配**立刻命中** ⇒ 证明「不参与匹配」的原因就是那个状态
        exec("UPDATE fabric_remnants SET status = 'available' WHERE id = " + takenId);
        assertThat(remnantService.match(TENANT_ID, itemId, "PC-5146-TAKEN").recommendations())
                .as("红证：混入可用池就会被匹配到 ⇒ 上一条断言不是恒真").isNotEmpty();
        exec("UPDATE fabric_remnants SET status = 'customer_taken' WHERE id = " + takenId);
    }

    // ══════════════════════════════════════════════════════════════════════════════════
    // 判据 8：报废留痕 + 账实一致的 DB 约束
    // ══════════════════════════════════════════════════════════════════════════════════

    @Test
    @DisplayName("判据8 报废留痕：状态/原因/操作人/时刻可读；重复报废被拒；抹掉原因 ⇒ 数据库当场拒绝")
    void scrapLeavesATraceAndTheLedgerStaysConsistent() throws Exception {
        String orderNo = newOrder("报废留痕单");
        accruePair(orderNo, "PC-5146-SCRAP");
        Long id = scalar("SELECT id FROM fabric_remnants WHERE source_order_no = '" + orderNo
                + "' AND status = 'available' ORDER BY id LIMIT 1").longValue();

        RemnantViews.RemnantLine scrapped = remnantService.scrap(TENANT_ID, id, "超期未用");
        assertThat(scrapped.status()).isEqualTo(FabricRemnant.STATUS_SCRAPPED);
        assertThat(scrapped.scrapReason()).as("为什么").isEqualTo("超期未用");
        assertThat(scrapped.scrappedBy()).as("谁").isNotNull();
        assertThat(scrapped.scrappedAt()).as("何时").isNotNull();
        assertThat(scrapped.recoveredAmount()).as("报废件不得带回收额（回收与报废互斥）").isNull();
        assertThat(remnantService.ledger(TENANT_ID, FabricRemnant.STATUS_SCRAPPED, null, orderNo, 1, 10)
                .page().getItems()).as("报废件按状态查得回来（判据「状态可读」）").hasSize(1);

        assertThat(catchThrowable(() -> remnantService.scrap(TENANT_ID, id, "再报废一次")))
                .as("重复报废被拒（否则报废率失真）").isInstanceOf(BusinessException.class);

        // 🔴 红证：绕过服务层直接抹掉报废原因 ⇒ V122 的生命周期约束当场拒绝（SQLSTATE 23514）
        Throwable rejected = catchThrowable(() ->
                exec("UPDATE fabric_remnants SET scrap_reason = NULL WHERE id = " + id));
        assertThat(rejected).as("🔴 账实一致不是靠读面自觉：DB 约束必须挡住自相矛盾的行").isNotNull();
        assertThat(sqlStateOf(rejected)).isEqualTo("23514");

        // 对照：同一张表的**回收**侧同样被钉住（金额必须 = 米数 × 均价）
        Throwable badAmount = catchThrowable(() -> exec("UPDATE fabric_remnants SET status = 'used',"
                + " used_by_order_no = '" + orderNo + "', recovered_meters = 3.0,"
                + " recovered_unit_cost = 12.5, recovered_amount = 1, recovered_at = NOW()"
                + " WHERE id = " + id));
        assertThat(badAmount).as("回收额写错 ⇒ 当场拒绝（不是读面各算各的）").isNotNull();
        assertThat(sqlStateOf(badAmount)).isEqualTo("23514");
    }

    // ══════════════════════════════════════════════════════════════════════════════════
    // 夹具与工具
    // ══════════════════════════════════════════════════════════════════════════════════

    /**
     * 派一张单并让它自动产生余料。
     *
     * <p>定尺（定高买宽，门幅 2.8、上下卷边 0.3 取自库默认算料配置）：两块料占门幅
     * {@code (1.1+0.3)=1.4} 与 {@code (0.8+0.3)=1.1}，合计 2.5 &lt; 2.8 ⇒ 同一行、行长度 3
     * ⇒ 排料结果里留下**门幅余料 3.0 × 0.3**（这就是本单要登记的余料）。</p>
     */
    private static int accruePair(String orderNo, String batchNo) throws Exception {
        newBatch(batchNo);
        return accrueOnBatch(orderNo, batchNo, "3", "1.1", "0.8");
    }

    /** 在**既有**批次上派一张单（判据 3 要按显式缸号造多块对照余料，批次必须自己建）。 */
    private static int accrueOnBatch(String orderNo, String batchNo, String meters, String heightA,
                                     String heightB) throws Exception {
        List<StockBatchConsumptionService.Designation> designations = List.of(
                new StockBatchConsumptionService.Designation(orderNo + "-i1", PRODUCT_ID, SKU_CODE,
                        batchNo, new BigDecimal(meters), "定高买宽", new BigDecimal(heightA), null),
                new StockBatchConsumptionService.Designation(orderNo + "-i2", PRODUCT_ID, SKU_CODE,
                        batchNo, new BigDecimal(meters), "定高买宽", new BigDecimal(heightB), null));
        var plan = batchStock.plan(TENANT_ID, designations);
        batchStock.apply(TENANT_ID, "JG-" + orderNo, orderNo, plan);
        return scalar("SELECT COUNT(*) FROM fabric_remnants WHERE source_order_no = '" + orderNo + "'")
                .intValue();
    }

    /**
     * 建批次（数量 60 米 / 均价 12.5），返回 id。
     *
     * <p>🔴 缸号**逐批次唯一**（{@code LOT-<批次号>}）：不然各用例的余料互为候选，
     * 「挑到哪一块」就取决于用例执行顺序（实测踩过：本用例拿到的余料来自别的用例的批次，
     * 而那块批次的均价已被「改价」用例改成 99）。判据 3 另用 {@link #newBatch(String, String)}
     * 显式造**同缸号**的第二个批次来判「同缸号优先」。</p>
     */
    private static long newBatch(String batchNo) throws Exception {
        return newBatch(batchNo, "LOT-" + batchNo);
    }

    /** 建批次并显式指定缸号（判据 3 的「同缸号优先」需要两个批次共用同一个缸号）。 */
    private static long newBatch(String batchNo, String dyeLot) throws Exception {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery("INSERT INTO stock_batches (tenant_id, batch_no, product_id,"
                     + " sku_id, sku_code, quantity, unit_cost, dye_lot) VALUES (" + TENANT_ID + ", '"
                     + batchNo + "', '" + PRODUCT_ID + "', " + SKU_ID + ", '" + SKU_CODE + "', 60, "
                     + BATCH_UNIT_COST + ", '" + dyeLot + "') RETURNING id")) {
            assertThat(rs.next()).as("批次夹具必须落库").isTrue();
            return rs.getLong(1);
        }
    }

    /** 建一张订单（对客金额 1200）+ 一行明细（对客单价 600 / 2 件 / 成品 2.7 × 1.8）。 */
    private static String newOrder(String label) throws Exception {
        String orderNo = "ORD-5146-" + (++orderSeq);
        exec("INSERT INTO orders (id, tenant_id, order_no, status, total_amount) VALUES ('acc-5146-o"
                + orderSeq + "', " + TENANT_ID + ", '" + orderNo + "', 'confirmed', 1200)");
        System.out.println("[#5146 夹具] 订单 " + orderNo + "（" + label + "）");
        return orderNo;
    }

    /** 给该订单加一行明细（携带特殊选项），返回明细行 id。 */
    private static String orderItemOf(String orderNo, String... options) throws Exception {
        String itemId = orderNo + "-ITEM";
        StringBuilder json = new StringBuilder("{\"specialOptions\":[");
        for (int i = 0; i < options.length; i++) {
            json.append(i > 0 ? "," : "").append("\"").append(options[i]).append("\"");
        }
        json.append("]}");
        exec("INSERT INTO order_items (id, tenant_id, order_id, product_id, quantity, unit_price,"
                + " width, height, subtotal, processing_info) VALUES ('" + itemId + "', " + TENANT_ID
                + ", (SELECT id FROM orders WHERE order_no = '" + orderNo + "'), '" + PRODUCT_ID
                + "', 2, 600, 1.8, 2.7, 1200, '" + json + "'::jsonb)");
        return itemId;
    }

    /** 对客口径的逐值快照（售价 / 小计 / 数量 / 成品宽高 + 订单总额）—— 判据 2 的被测读数。 */
    private static String customerFacingReadings(String orderNo) throws Exception {
        StringBuilder out = new StringBuilder();
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery("SELECT i.unit_price, i.subtotal, i.quantity, i.width,"
                     + " i.height, o.total_amount FROM order_items i JOIN orders o ON o.id = i.order_id"
                     + " WHERE o.order_no = '" + orderNo + "' ORDER BY i.id")) {
            while (rs.next()) {
                for (int i = 1; i <= 6; i++) {
                    out.append(rs.getBigDecimal(i).toPlainString()).append('|');
                }
            }
        }
        return out.toString();
    }

    /** 写一行小件用料尺寸（**走服务层** ⇒ item_key 的工序库校验也一并被行使）。 */
    private static void putSpec(String itemKey, String lengthM, String widthM) {
        remnantService.putSpecs(TENANT_ID, List.of(Map.of(
                "item_key", itemKey, "length_m", lengthM, "width_m", widthM)));
    }

    private static BigDecimal scalar(String sql) throws Exception {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery(sql)) {
            assertThat(rs.next()).as("查询必须有结果：" + sql).isTrue();
            return rs.getBigDecimal(1);
        }
    }

    private static Map<String, Object> row(String sql) throws Exception {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement();
             ResultSet rs = st.executeQuery(sql)) {
            assertThat(rs.next()).as("查询必须有结果：" + sql).isTrue();
            Map<String, Object> out = new java.util.LinkedHashMap<>();
            for (int i = 1; i <= rs.getMetaData().getColumnCount(); i++) {
                out.put(rs.getMetaData().getColumnLabel(i), rs.getObject(i));
            }
            return out;
        }
    }

    private static void exec(String sql) throws Exception {
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute(sql);
        }
    }

    /** 沿 cause 链找 SQLSTATE（约束的证据必须是数据库给的，不是文案匹配）。 */
    private static String sqlStateOf(Throwable failure) {
        Throwable current = failure;
        List<String> seen = new ArrayList<>();
        while (current != null && seen.size() < 20) {
            seen.add(current.getClass().getName());
            if (current instanceof java.sql.SQLException sqlException) {
                return sqlException.getSQLState();
            }
            current = current.getCause();
        }
        return null;
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
