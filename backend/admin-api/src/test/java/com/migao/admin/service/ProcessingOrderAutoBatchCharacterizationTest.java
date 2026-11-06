// case_ids: MC-310
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.BatchStockViews;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProcessingItemMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import com.migao.admin.mapper.ProcessingPositionOperationMapper;
import com.migao.admin.mapper.ProductionWorkLogMapper;
import com.migao.admin.time.BusinessClock;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import java.io.IOException;
import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Clock;
import java.time.Instant;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyBoolean;
import static org.mockito.ArgumentMatchers.anyCollection;
import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.spy;
import static org.mockito.Mockito.when;

/**
 * 加工单**自动批次决策面**的 characterization 判据（issue #8770，自动批次一档，CP-1）。
 *
 * <h2>它补的是哪一格</h2>
 * 上一档（派单池一档，PR #8801）留下的重启条件原文：
 * <em>「① 先扩 characterization 到「事件驱动 + 条件 + 兜底」的**决策面**（现判据
 * {@code AutoBatchDispatchTest} 12 条是点状）；③ ⚠️ 它经 {@code generatePooled} 落库 ⇒
 * **只搬决策、不搬写库**」</em>。
 *
 * <p>既有 {@code AutoBatchDispatchTest}（12 条）/ {@code AutoBatchDueScanServiceTest}（12 条）
 * 每条只钉**一个**读数（某条单在不在 {@code calls} 里 / 某个 reason 包不包含子串）。
 * 大面积搬移（挪静态方法 / 换调用接收者 / 改私有为包内可见 / 把判断挪进另一个类）可以让它们
 * **全绿通过**，却把 <b>决策面的顺序、理由文案、三级降级的模式、兜底的算式、扫描腿的边界</b>
 * 悄悄改掉 —— 每一条都是可观测面（{@code reasons} 进日志、{@code generated_by} 进库、
 * {@code dispatchedOrderNos} 进监听器留痕）。</p>
 *
 * <h2>冻的是什么（与 golden 逐字节比对）</h2>
 * <ol>
 *   <li><b>{@code AutoBatchOutcome} 的<b>全部</b> record 分量</b>（{@code enabled} / {@code trigger} /
 *       {@code rule} / {@code reasons} / {@code dispatchedOrderNos} / {@code failedOrderIds} /
 *       {@code failures}）—— 事件腿 15 个场景 + 到期扫描腿 4 个场景；</li>
 *   <li><b>决策的对外效果面</b>：每次 {@code generate(...)} 的入参快照
 *       （{@code orderIds} / {@code assignments} 的 {@code itemId} / {@code pooled} / {@code rule} /
 *       {@code operator}）。{@code operator} 是落进 {@code processing_orders.generated_by} 的
 *       <b>持久痕迹</b>（{@code auto:<触发原因>:<规则>} + 降级后缀 {@code :single} / {@code :plain} /
 *       {@code :due}）⇒ 它一变，历史单的来源就再也对不上；</li>
 *   <li><b>策略面</b>（{@code autoBatchPolicy()} 的 Spring 属性 → 策略映射，
 *       {@code AutoBatchPolicy.defaults()/enabledPolicy()/with(...)}）。</li>
 * </ol>
 *
 * <h2>墙钟怎么钉（这是上一档点名的坑）</h2>
 * 到期判据 {@code today ≥ 最晚派单日} 是 <b>今天</b> 的函数：{@code 有到货日 ⇒ 到货日 − 标准周期}；
 * {@code 无 ⇒ 进池日 + 标准周期}。若夹具写 {@code LocalDate.now()}，golden 里的
 * {@code business_due=…} 理由串**每天都会漂**。
 * ⇒ 本判据把 {@link BusinessClock} 用 {@code Clock.fixed(2026-11-06T02:00Z)} 钉死
 * （{@code 业务今天 = 2026-11-06}），夹具的 {@code created_at} / 到货日一律写成**相对该钉住时刻**的
 * 绝对日期。⇒ 所有派生量（{@code business_due} 的日期、{@code required_delivery_date} 的回显）
 * 都是输入的函数，<b>不随跑测试的时刻漂移</b>。
 *
 * <p>golden 录制于**切片前**的代码（{@code -Dpos.autobatch.golden.update=true} 生成），
 * 切片后<b>不带</b>该开关复跑必须逐字节相同。</p>
 *
 * <h2>它<b>不</b>判什么（照实登记）</h2>
 * 不判查询次数 / 事务边界 / 并发时序；{@code generate} 在本判据里是**替身**（真实写库路径由
 * {@code AutoBatchDispatchRealDbTest} / {@code AutoBatchDueScanRealDbTest} 的真 PG 判据承担）。
 * 本判据钉的是「同一批输入 ⇒ 决策输出与对外调用**逐字节相同**」。
 */
@DisplayName("加工单自动批次决策面 characterization（issue #8770 自动批次一档）")
class ProcessingOrderAutoBatchCharacterizationTest {

    private static final Long TENANT = 8770L;

    private static final String PRODUCT_A = "prod-auto-a";
    private static final String SKU_A = "SKU-A";
    private static final String PRODUCT_B = "prod-auto-b";
    private static final String SKU_B = "SKU-B";

    /** golden 落点（相对 {@code backend/admin-api}）。 */
    private static final Path GOLDEN = Path.of(
            "src/test/resources/processing-order-auto-batch-golden.json");

    /** 录制开关：**只在切片前**用它写 golden；切片后必须不带开关跑。 */
    private static final String UPDATE_FLAG = "pos.autobatch.golden.update";

    /** 钉住的业务「今天」（= 2026-11-06 10:00 +08）—— 到期判据的唯一时间输入。 */
    private static final Instant PINNED = Instant.parse("2026-11-06T02:00:00Z");
    private static final OffsetDateTime N0 = OffsetDateTime.ofInstant(PINNED, BusinessClock.BUSINESS_ZONE);
    private static final LocalDate TODAY = LocalDate.of(2026, 11, 6);

    /** 冻结投影的日期/时刻一律走 ISO（不写时间戳数组：可读且跨 JVM 稳定）。 */
    private final ObjectMapper mapper = new ObjectMapper()
            .registerModule(new JavaTimeModule())
            .disable(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS);

    private ProcessingOrderMapper processingOrderMapper;
    private OrderMapper orderMapper;
    private OrderItemMapper orderItemMapper;
    private ProcessingItemMapper processingItemMapper;
    private OrderService orderService;
    private ProductionService productionService;
    private ProductionOperationQueryService productionOperationQueryService;
    private ProductionOperationQtyClient productionOperationQtyClient;
    private StockBatchConsumptionService stockBatchConsumptionService;

    /** 当前场景夹具（stub 只在 {@code setUp} 注册一次，按「当前场景」取值）。 */
    private Fixture current;
    private int itemCursor;
    private int callIndex;
    private int seq;

    /** {@code generate} 的逐次入参快照（决策的对外效果面）。 */
    private final List<Call> calls = new ArrayList<>();

    /** 一次 {@code generate} 的入参：单列表 / 逐行 itemId / 池化开关 / 规则 / 持久痕迹。 */
    private record Call(List<String> orderIds, List<String> itemIds, Boolean pooled, String rule,
                        String operator) {
    }

    /**
     * 一个场景的夹具。
     *
     * @param orders        池查询返回的订单（顺序 = {@code selectList} 顺序）
     * @param itemsByOrder  逐单明细（按池的逐单遍历顺序消费）
     * @param activeOrderIds 已有活跃加工单的单（幂等闸的输入）
     * @param batches       物料（productId）→ 批次余量读数
     * @param failingCalls  第 N 次 {@code generate} 里**失败**的单（缺省 = 全成功）
     */
    private record Fixture(List<Order> orders, List<List<OrderItem>> itemsByOrder,
                           List<String> activeOrderIds,
                           Map<String, List<BatchStockViews.BatchRemaining>> batches,
                           List<Set<String>> failingCalls) {
    }

    @BeforeEach
    void setUp() {
        processingOrderMapper = mock(ProcessingOrderMapper.class);
        orderMapper = mock(OrderMapper.class);
        orderItemMapper = mock(OrderItemMapper.class);
        processingItemMapper = mock(ProcessingItemMapper.class);
        orderService = mock(OrderService.class);
        productionService = mock(ProductionService.class);
        productionOperationQueryService = mock(ProductionOperationQueryService.class);
        productionOperationQtyClient = mock(ProductionOperationQtyClient.class);
        stockBatchConsumptionService = mock(StockBatchConsumptionService.class);
        lenient().when(orderService.lifecycleService()).thenReturn(mock(OrderLifecycleService.class));
        TenantContext.setTenantId(TENANT);
        MybatisConfiguration conf = new MybatisConfiguration();
        MapperBuilderAssistant assistant = new MapperBuilderAssistant(conf, "");
        TableInfoHelper.initTableInfo(assistant, Order.class);
        TableInfoHelper.initTableInfo(assistant, ProcessingOrder.class);
        when(orderMapper.selectList(any())).thenAnswer(inv -> current.orders());
        when(processingOrderMapper.selectActiveOrderIds(eq(TENANT), anyCollection()))
                .thenAnswer(inv -> current.activeOrderIds());
        when(orderItemMapper.selectList(any()))
                .thenAnswer(inv -> current.itemsByOrder().get(itemCursor++));
        lenient().when(stockBatchConsumptionService.remaining(eq(TENANT), any(), any(), anyBoolean()))
                .thenAnswer(inv -> current.batches().getOrDefault(inv.getArgument(1), List.of()));
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    // ── 判据 1：事件腿的决策面逐字节相同 ───────────────────────────────────

    @Test
    @DisplayName("切片前后逐字节相同：事件腿按需成批的决策面 15 场景（golden 录制于未切片代码）")
    void eventLegDecisionFaceIsByteIdenticalToThePreSliceGolden() throws Exception {
        Map<String, Object> actual = new LinkedHashMap<>();
        for (Map.Entry<String, Scenario> entry : eventScenarios().entrySet()) {
            actual.put(entry.getKey(), freeze(entry.getValue(), Leg.EVENT));
        }
        assertGolden("event", actual);
    }

    // ── 判据 2：到期扫描腿的决策面逐字节相同 ───────────────────────────────

    @Test
    @DisplayName("切片前后逐字节相同：到期扫描腿只做业务兜底的决策面 4 场景")
    void dueScanLegDecisionFaceIsByteIdenticalToThePreSliceGolden() throws Exception {
        Map<String, Object> actual = new LinkedHashMap<>();
        for (Map.Entry<String, Scenario> entry : dueScanScenarios().entrySet()) {
            actual.put(entry.getKey(), freeze(entry.getValue(), Leg.DUE));
        }
        assertGolden("dueScan", actual);
    }

    // ── 判据 3：策略面逐字节相同 ───────────────────────────────────────────

    @Test
    @DisplayName("切片前后逐字节相同：Spring 属性 → 策略映射 + 三个策略构造器")
    void policySurfaceIsByteIdenticalToThePreSliceGolden() throws Exception {
        Map<String, Object> actual = new LinkedHashMap<>();

        ProcessingOrderService fresh = service();
        actual.put("spring-defaults", asMap(fresh.autoBatchPolicy()));

        // Spring 属性覆盖（部署侧 `migao.production.auto-batch.*` 的等价物）
        ReflectionTestUtils.setField(fresh, "autoBatchEnabled", false);
        ReflectionTestUtils.setField(fresh, "autoBatchFillRatioPercent", 65);
        ReflectionTestUtils.setField(fresh, "autoBatchConvergeMeters", "0.35");
        ReflectionTestUtils.setField(fresh, "autoBatchMinBatchMeters", "45");
        ReflectionTestUtils.setField(fresh, "autoBatchStandardCycleDays", 11);
        ReflectionTestUtils.setField(fresh, "autoBatchAssignmentRule", "best_fit");
        actual.put("spring-overridden", asMap(fresh.autoBatchPolicy()));

        actual.put("defaults", asMap(ProcessingOrderService.AutoBatchPolicy.defaults()));
        actual.put("enabledPolicy", asMap(ProcessingOrderService.AutoBatchPolicy.enabledPolicy()));
        actual.put("with", asMap(ProcessingOrderService.AutoBatchPolicy.enabledPolicy()
                .with(55, "0.75", "17", 3)));

        assertGolden("policy", actual);
    }

    // ── 场景：事件腿 ───────────────────────────────────────────────────────

    /** 事件腿的一个场景 = 夹具 + 生效策略（触发原因固定 {@code order_confirmed}）。 */
    private record Scenario(Fixture fixture, ProcessingOrderService.AutoBatchPolicy policy) {
    }

    /**
     * 15 个事件腿场景，逐条覆盖决策面的一个分支：
     * 缺省即开 / 显式关 / 加急 / 条件① / 条件② / 条件③ / 三条都不满足 / 兜底（两种算式）/
     * 一单多料组 / 三级降级的三种结局 / 规则归一 / 租户为空 / 幂等。
     */
    private static Map<String, Scenario> eventScenarios() {
        Map<String, Scenario> table = new LinkedHashMap<>();

        // ① 池空：缺省开着 ⇒ 评估发生，但一张都不派
        table.put("01-empty-pool", new Scenario(
                new Fixture(List.of(), List.of(), List.of(), Map.of(), List.of()),
                policy(80, "0.2", "30")));

        // ② 显式关：零读零写（连池都不查）⇒ enabled=false
        table.put("02-explicit-off", new Scenario(
                new Fixture(List.of(order("o-1", "ORD-A001", 1, false, TODAY.plusDays(30))),
                        List.of(items("o-1", "i-1", PRODUCT_A, SKU_A, "3", "米白")),
                        List.of(), Map.of(), List.of()),
                disabledPolicy()));

        // ③ 加急永不入池 ⇒ 逐单 pooleded=false 立即派；普通单走成批（条件③）
        table.put("03-urgent-never-pooled", new Scenario(
                new Fixture(List.of(order("o-u", "ORD-A002", 2, true, TODAY.plusDays(30)),
                                order("o-n", "ORD-A003", 1, false, TODAY.plusDays(30))),
                        List.of(items("o-u", "i-u", PRODUCT_A, SKU_A, "3", "米白"),
                                items("o-n", "i-n", PRODUCT_A, SKU_A, "3", "米白")),
                        List.of(), Map.of(), List.of()),
                policy(80, "0.2", "3")));

        // ④ 条件③：池内同物料需求 ≥ 最小批量（3 ≥ 3）
        table.put("04-condition-min-batch", new Scenario(
                new Fixture(List.of(order("o-1", "ORD-A004", 1, false, TODAY.plusDays(30))),
                        List.of(items("o-1", "i-1", PRODUCT_A, SKU_A, "3", "米白")),
                        List.of(), Map.of(), List.of()),
                policy(80, "0.2", "3")));

        // ⑤ 条件①：需求 ≥ 80% × 入库量（3 ≥ 0.8 × 3.5 = 2.8）—— 余量 3.5 − 3 = 0.5 > 0.2 ⇒ ① 先命中
        table.put("05-condition-fill-ratio", new Scenario(
                new Fixture(List.of(order("o-1", "ORD-A005", 1, false, TODAY.plusDays(30))),
                        List.of(items("o-1", "i-1", PRODUCT_A, SKU_A, "3", "米白")),
                        List.of(), Map.of(PRODUCT_A, List.of(batch("PC-A005", "3.5", "3.5"))), List.of()),
                policy(80, "0.2", "100")));

        // ⑥ 条件②：余量收敛到 ≤ 0.2m（3.1 − 3 = 0.1）—— 入库量 90 ⇒ 填满率不足 ⇒ 只有 ② 命中
        table.put("06-condition-converge", new Scenario(
                new Fixture(List.of(order("o-1", "ORD-A006", 1, false, TODAY.plusDays(30))),
                        List.of(items("o-1", "i-1", PRODUCT_A, SKU_A, "3", "米白")),
                        List.of(), Map.of(PRODUCT_A, List.of(batch("PC-A006", "90", "3.1"))), List.of()),
                policy(80, "0.2", "100")));

        // ⑦ 三条都不满足且未到期 ⇒ 不派（条件不得恒真）
        table.put("07-no-condition-not-due", new Scenario(
                new Fixture(List.of(order("o-1", "ORD-A007", 1, false, TODAY.plusDays(54))),
                        List.of(items("o-1", "i-1", PRODUCT_A, SKU_A, "3", "米白")),
                        List.of(), Map.of(PRODUCT_A, List.of(batch("PC-A007", "90", "90"))), List.of()),
                policy(80, "0.2", "30")));

        // ⑧ 业务兜底（有到货日）：条件都不满足、但 今天 ≥ 到货日 − 7 ⇒ 必派
        table.put("08-business-due-with-delivery-date", new Scenario(
                new Fixture(List.of(order("o-1", "ORD-A008", 1, false, TODAY.plusDays(4))),
                        List.of(items("o-1", "i-1", PRODUCT_A, SKU_A, "3", "米白")),
                        List.of(), Map.of(PRODUCT_A, List.of(batch("PC-A008", "90", "90"))), List.of()),
                policy(80, "0.2", "30")));

        // ⑨ 业务兜底（无到货日）：进池日 + 7 ≤ 今天 ⇒ 必派（进池 40 天前）
        table.put("09-business-due-without-delivery-date", new Scenario(
                new Fixture(List.of(order("o-1", "ORD-A009", 960, false, null)),
                        List.of(items("o-1", "i-1", PRODUCT_A, SKU_A, "3", "米白")),
                        List.of(), Map.of(PRODUCT_A, List.of(batch("PC-A009", "90", "90"))), List.of()),
                policy(80, "0.2", "30")));

        // ⑩ 一单多料组：只有 A 组命中条件②，但派单带上该单**全部**行（一单一加工单）
        table.put("10-multi-group-same-order", new Scenario(
                new Fixture(List.of(order("o-1", "ORD-A010", 1, false, TODAY.plusDays(30))),
                        List.of(List.of(item("o-1", "i-a", PRODUCT_A, SKU_A, "3", "米白"),
                                item("o-1", "i-b", PRODUCT_B, SKU_B, "5", "奶白"))),
                        List.of(),
                        Map.of(PRODUCT_A, List.of(batch("PC-A010", "90", "3.1")),
                                PRODUCT_B, List.of(batch("PC-B010", "90", "90"))),
                        List.of()),
                policy(80, "0.2", "30")));

        // ⑪ 三级降级 ①失败 → ②逐单 + 规则成功（operator 带 `:single`）
        table.put("11-fail-soft-single-retry", new Scenario(
                new Fixture(List.of(order("o-1", "ORD-A011", 1, false, TODAY.plusDays(30))),
                        List.of(items("o-1", "i-1", PRODUCT_A, SKU_A, "3", "米白")),
                        List.of(), Map.of(), List.of(Set.of("o-1"))),
                policy(80, "0.2", "3")));

        // ⑫ 三级降级 ①失败 → ②失败 → ③逐单不带规则成功（`plain`，rule=null）
        table.put("12-fail-soft-plain-retry", new Scenario(
                new Fixture(List.of(order("o-1", "ORD-A012", 1, false, TODAY.plusDays(30))),
                        List.of(items("o-1", "i-1", PRODUCT_A, SKU_A, "3", "米白")),
                        List.of(), Map.of(), List.of(Set.of("o-1"), Set.of("o-1"))),
                policy(80, "0.2", "3")));

        // ⑬ 三级全失败 ⇒ failures 逐条可读（trigger 前缀 + 单号 + 失败文案）
        table.put("13-fail-soft-all-fail", new Scenario(
                new Fixture(List.of(order("o-1", "ORD-A013", 1, false, TODAY.plusDays(30))),
                        List.of(items("o-1", "i-1", PRODUCT_A, SKU_A, "3", "米白")),
                        List.of(), Map.of(), List.of(Set.of("o-1"), Set.of("o-1"), Set.of("o-1"))),
                policy(80, "0.2", "3")));

        // ⑭ 规则归一：策略写 `BEST_FIT` ⇒ 决策面拿到 `best_fit`，operator 与 rule 逐字带它
        table.put("14-rule-normalized", new Scenario(
                new Fixture(List.of(order("o-1", "ORD-A014", 1, false, TODAY.plusDays(30))),
                        List.of(items("o-1", "i-1", PRODUCT_A, SKU_A, "3", "米白")),
                        List.of(), Map.of(), List.of()),
                new ProcessingOrderService.AutoBatchPolicy(true, 80, new BigDecimal("0.2"),
                        new BigDecimal("3"), 7, "BEST_FIT", new BigDecimal("24"))));

        // ⑮ 幂等：已有活跃加工单 ⇒ 池看不见它 ⇒ 一张都不派
        table.put("15-idempotent-after-dispatch", new Scenario(
                new Fixture(List.of(order("o-1", "ORD-A015", 1, false, TODAY.plusDays(30))),
                        List.of(), List.of("o-1"), Map.of(), List.of()),
                policy(80, "0.2", "3")));

        return table;
    }

    // ── 场景：到期扫描腿 ───────────────────────────────────────────────────

    /**
     * 4 个扫描腿场景：到期必派 / 满足成批条件但未到期 ⇒ 不派 / 超看板窗口但未到期 ⇒ 不派 /
     * 显式关 ⇒ 零动作。它们钉的是「扫描腿<b>只</b>做业务兜底」这条区分（做反了正是用户要去掉的形态）。
     */
    private static Map<String, Scenario> dueScanScenarios() {
        Map<String, Scenario> table = new LinkedHashMap<>();

        // ① 无任何业务事件，只有扫描腿 ⇒ 已过期必派（reason 与事件腿逐字同款）
        table.put("01-due-is-dispatched", new Scenario(
                new Fixture(List.of(order("o-due", "ORD-B001", 1, false, TODAY)),
                        List.of(items("o-due", "i-due", PRODUCT_A, SKU_A, "3", "米白")),
                        List.of(), Map.of(), List.of()),
                policy(80, "0.2", "30")));

        // ② 条件③满足但**未到期** ⇒ 扫描腿一张都不派（它不判优化条件）
        table.put("02-condition-met-but-not-due", new Scenario(
                new Fixture(List.of(order("o-later", "ORD-B002", 1, false, TODAY.plusDays(54))),
                        List.of(items("o-later", "i-later", PRODUCT_A, SKU_A, "3", "米白")),
                        List.of(), Map.of(), List.of()),
                policy(80, "0.2", "3")));

        // ③ 超看板窗口（等 30h > 24h）但未到期 ⇒ 仍不派（窗口不是派单死线）
        table.put("03-overdue-but-not-due", new Scenario(
                new Fixture(List.of(order("o-window", "ORD-B003", 30, false, TODAY.plusDays(54))),
                        List.of(items("o-window", "i-window", PRODUCT_A, SKU_A, "3", "米白")),
                        List.of(), Map.of(), List.of()),
                policy(80, "0.2", "30")));

        // ④ 显式关 ⇒ 零读零写
        table.put("04-explicit-off", new Scenario(
                new Fixture(List.of(order("o-1", "ORD-B004", 960, false, null)),
                        List.of(items("o-1", "i-1", PRODUCT_A, SKU_A, "3", "米白")),
                        List.of(), Map.of(), List.of()),
                disabledPolicy()));

        return table;
    }

    // ── 执行 + 冻结 ────────────────────────────────────────────────────────

    private enum Leg { EVENT, DUE }

    private Map<String, Object> freeze(Scenario scenario, Leg leg) {
        current = scenario.fixture();
        itemCursor = 0;
        callIndex = 0;
        seq = 0;
        calls.clear();
        ProcessingOrderService service = service();

        Map<String, Object> frozen = new LinkedHashMap<>();
        try {
            ProcessingOrderService.AutoBatchOutcome outcome = leg == Leg.EVENT
                    ? service.autoBatchDispatch(TENANT, "order_confirmed", scenario.policy())
                    : service.autoBatchDispatchDue(TENANT, "due_scan", scenario.policy());
            frozen.put("outcome", asMap(outcome));
        } catch (BusinessException e) {
            frozen.put("rejected", rejectionOf(e));
        }
        List<Map<String, Object>> callsFrozen = new ArrayList<>();
        for (Call call : calls) {
            callsFrozen.add(asMap(call));
        }
        frozen.put("generateCalls", callsFrozen);
        return frozen;
    }

    private ProcessingOrderService service() {
        ProcessingOrderService service = spy(new ProcessingOrderService(processingOrderMapper,
                orderMapper, orderItemMapper, processingItemMapper, orderService, mapper,
                productionService, productionOperationQueryService, productionOperationQtyClient));
        ReflectionTestUtils.setField(service, "businessClock",
                new BusinessClock(Clock.fixed(PINNED, BusinessClock.BUSINESS_ZONE)));
        ReflectionTestUtils.setField(service, "stockBatchConsumptionService", stockBatchConsumptionService);
        doAnswer(inv -> {
            List<String> orderIds = inv.getArgument(0);
            List<com.migao.admin.dto.ProcessingOrderGenerateRequest.BatchAssignment> assignments =
                    inv.getArgument(1);
            calls.add(new Call(List.copyOf(orderIds),
                    assignments.stream()
                            .map(com.migao.admin.dto.ProcessingOrderGenerateRequest.BatchAssignment::getItemId)
                            .toList(),
                    inv.getArgument(5), inv.getArgument(4), inv.getArgument(3)));
            int index = callIndex++;
            Set<String> failing = index < current.failingCalls().size()
                    ? current.failingCalls().get(index) : Set.of();
            List<ProcessingOrderService.GenerateResult> out = new ArrayList<>();
            for (String id : orderIds) {
                out.add(failing.contains(id)
                        ? ProcessingOrderService.GenerateResult.fail(id, "FAKE_CODE",
                                "夹具：这一级派不出去", "夹具建议：换一级重试")
                        : ProcessingOrderService.GenerateResult.ok(id, "JG-" + (++seq)));
            }
            return out;
        }).when(service).generate(anyList(), anyList(), any(), any(), any(), any());
        return service;
    }

    // ── 冻结原语 ───────────────────────────────────────────────────────────

    @SuppressWarnings("unchecked")
    private Map<String, Object> asMap(Object value) {
        return mapper.convertValue(value, Map.class);
    }

    private static Map<String, Object> rejectionOf(BusinessException e) {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("code", e.getCode());
        out.put("message", e.getMessage());
        out.put("suggestion", e.getSuggestion());
        return out;
    }

    private void assertGolden(String section, Map<String, Object> actual) throws IOException {
        if (Boolean.parseBoolean(System.getProperty(UPDATE_FLAG, "false"))) {
            Files.createDirectories(GOLDEN.getParent());
            Map<String, Object> merged = Files.exists(GOLDEN)
                    ? mapper.readValue(Files.readString(GOLDEN, StandardCharsets.UTF_8), Map.class)
                    : new LinkedHashMap<>();
            merged.put(section, actual);
            Files.writeString(GOLDEN,
                    mapper.writerWithDefaultPrettyPrinter().writeValueAsString(merged) + "\n",
                    StandardCharsets.UTF_8);
            return;
        }
        assertThat(Files.exists(GOLDEN))
                .as("golden 不存在（%s）⇒ 本判据无从判起。录制：mvnw test -D%s=true", GOLDEN, UPDATE_FLAG)
                .isTrue();
        Map<String, Object> golden = mapper.readValue(Files.readString(GOLDEN, StandardCharsets.UTF_8),
                Map.class);
        assertThat(golden.containsKey(section))
                .as("golden 缺少段 %s —— 新增段必须先重新录制 golden（并说明它冻的是什么）", section)
                .isTrue();
        @SuppressWarnings("unchecked")
        Map<String, Object> expected = (Map<String, Object>) golden.get(section);
        // 逐场景断言（不是整段一比）：红的时候**具名**是哪个场景变了，排查不必自己 diff 20KB
        assertThat(actual.keySet())
                .as("段 %s 的场景集与 golden 不一致（新增 / 删除场景都必须重新录制并说明它冻的是什么）",
                        section)
                .isEqualTo(expected.keySet());
        for (String key : actual.keySet()) {
            assertThat(pretty(actual.get(key)))
                    .as("段 %s / 场景 %s：与切片前**不逐字节相同** ⇒ 切片改变了决策行为"
                            + "（条件判定 / 兜底算式 / 理由文案 / 降级模式 / 持久痕迹 / 策略映射）",
                            section, key)
                    .isEqualTo(pretty(expected.get(key)));
        }
    }

    private String pretty(Object value) {
        try {
            return mapper.writerWithDefaultPrettyPrinter().writeValueAsString(value);
        } catch (com.fasterxml.jackson.core.JsonProcessingException e) {
            throw new IllegalStateException("冻结投影序列化失败", e);
        }
    }

    // ── 夹具 ───────────────────────────────────────────────────────────────

    /** 显式关的策略（部署属性 {@code migao.production.auto-batch.enabled=false} 的等价物）。 */
    private static ProcessingOrderService.AutoBatchPolicy disabledPolicy() {
        return new ProcessingOrderService.AutoBatchPolicy(false, 80, new BigDecimal("0.2"),
                new BigDecimal("30"), 7, "fifo", new BigDecimal("24"));
    }

    private static ProcessingOrderService.AutoBatchPolicy policy(int fillRatio, String converge,
                                                                 String minBatch) {
        return ProcessingOrderService.AutoBatchPolicy.enabledPolicy()
                .with(fillRatio, converge, minBatch, 7);
    }

    /** 订单：{@code created_at = 钉住时刻 − waitedHours}（进池日与等待时长因此确定）。 */
    private static Order order(String id, String orderNo, int waitedHours, boolean urgent,
                               LocalDate requiredDeliveryDate) {
        return Order.builder().id(id).tenantId(TENANT).orderNo(orderNo).status("confirmed")
                .createdAt(N0.minusHours(waitedHours)).isUrgent(urgent).isOutsourced(false)
                .requiredDeliveryDate(requiredDeliveryDate).build();
    }

    private static List<OrderItem> items(String orderId, String itemId, String productId,
                                         String skuCode, String quantity, String colorName) {
        return List.of(item(orderId, itemId, productId, skuCode, quantity, colorName));
    }

    /** 一行明细：{@code processing_info} 带 sku + 一条加工项（{@code buildSnapshot} 的常规形态）。 */
    private static OrderItem item(String orderId, String itemId, String productId, String skuCode,
                                  String quantity, String colorName) {
        Map<String, Object> info = new LinkedHashMap<>();
        info.put("colorName", colorName);
        info.put("sellingMethod", "散剪");
        info.put("doorWidth", "2.8米");
        info.put("sku", skuCode);
        info.put("cuttingMode", "定高买宽");
        List<Map<String, Object>> procs = new ArrayList<>();
        Map<String, Object> p = new LinkedHashMap<>();
        p.put("id", "p-" + itemId);
        p.put("name", "打孔");
        p.put("quantity", 2);
        p.put("unit", "米");
        procs.add(p);
        info.put("processingItems", procs);
        return OrderItem.builder().id(itemId).tenantId(TENANT).orderId(orderId)
                .productId(productId).productName("加工窗帘-" + productId)
                .quantity(new BigDecimal(quantity)).width(new BigDecimal("1.5"))
                .height(new BigDecimal("1.1")).processingInfo(info).build();
    }

    private static BatchStockViews.BatchRemaining batch(String batchNo, String inbound,
                                                        String remaining) {
        return new BatchStockViews.BatchRemaining(1L, batchNo, PRODUCT_A, 1L, SKU_A,
                "RK-1", null, LocalDate.of(2026, 10, 1), new BigDecimal("12.5"),
                new BigDecimal(inbound), new BigDecimal(inbound).subtract(new BigDecimal(remaining)),
                new BigDecimal(remaining));
    }
}
