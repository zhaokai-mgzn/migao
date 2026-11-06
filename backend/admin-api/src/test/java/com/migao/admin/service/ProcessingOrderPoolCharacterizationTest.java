// case_ids: MC-269
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ProductionPoolViews;
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

import java.io.IOException;
import java.math.BigDecimal;
import java.math.RoundingMode;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.Collection;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.function.Function;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyCollection;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * 加工单**派单池读面**的 characterization 判据（issue #8770，派单池一档，CP-1）。
 *
 * <h2>它补的是哪一格</h2>
 * 上一档（#8725 第二档，PR #8768）留下的重启条件原文：
 * <em>「当前 9 个场景已覆盖 roll-up / 樘窗 / 卖布，但**没有覆盖 generate 的写库路径**」</em>。
 * 本档要搬的是**派单池**（{@code pool(...)} + 4 个私有辅助 + 2 个成批闸）—— 它**不是** generate，
 * 但它与 generate 一样**此前完全没有**「同一批输入 ⇒ 输出逐字节相同」的冻结判据：
 * 既有 {@code PoolBoardUrgencyTest} / {@code ProcessingOrderServiceTest} 全是**点状断言**
 * （某条单在不在池里 / 某个计数是几）。大面积搬移可以让它们**全绿通过**，却把
 * 分组键、行序、告警文案、计数口径、{@code stockSatisfiable} 回填顺序悄悄改掉。
 *
 * <h2>冻的是什么（与 golden 逐字节比对）</h2>
 * <ol>
 *   <li><b>池读面的完整 JSON</b>（{@link ProductionPoolViews.Pool} 的**全部** record 分量：
 *       {@code maxWaitHours} / {@code poolingEnabled} / 四个计数 / {@code warnings} /
 *       {@code urgentLines} / {@code outsourcedLines} / {@code groups[].lines}，逐行的
 *       物料键、展示名、需求米数、等待时长、{@code overdue}、加急/外发标记、到货日、临期度、
 *       {@code stockSatisfiable}）—— 9 个场景；</li>
 *   <li><b>成批闸的失败面</b>（{@code assertNoUrgentInPooledBatch} /
 *       {@code assertNoOutsourcedInPooledBatch} 的 code / message / suggestion 逐字）—— 经
 *       {@code preview(...)} 触发（闸在任何只读准备之前，故无需 prepare 夹具）；</li>
 *   <li><b>池化开关归一</b>（{@code pooledEnabled(null/false/true)}）—— 它是「不传 pooled == 逐单派」
 *       的唯一缺省解析点。</li>
 * </ol>
 *
 * <h2>两处**墙钟派生**读数怎么冻（有意设计，不是漏项）</h2>
 * {@code waitingSince}（进池时刻）与 {@code waitHours}（已等待时长）是 {@code now − created_at} 的
 * 投影：前者若原样落 golden，golden 每天都会漂。处置 = 夹具把 {@code created_at} 造成
 * <b>冻结时刻 − N 小时</b>（{@code N} 是场景常量），冻结时把 {@code waitingSince} 归一成
 * <b>{@code N.0}（相对小时数）</b>；{@code waitHours} 保持**被测代码算出来的原值**（同一批输入下
 * = {@code N.0}，确定性）。⇒ 两个字段都被冻住，且**不依赖**跑测试的时刻。
 * {@code deliveryDaysLeft} 用**钉住的** {@link BusinessClock}（{@code today = 2026-11-06}）⇒ 确定。
 *
 * <p>golden 录制于**切片前**的代码（{@code -Dpos.pool.golden.update=true} 生成），
 * 切片后**不带**该开关复跑必须逐字节相同。</p>
 *
 * <h2>红证（注入式，逐条见 PR body）</h2>
 * 把排序键改成单号序 / 把加急行也塞进 groups / 把 {@code stockSatisfiable} 恒置 true /
 * 把告警文案的阈值写死 24 / 把 {@code deliveryDaysLeft} 符号反过来 ⇒ 本判据**具名**报出差异场景。
 */
@DisplayName("加工单派单池读面 characterization（issue #8770 派单池一档）")
class ProcessingOrderPoolCharacterizationTest {

    private static final Long TENANT = 1L;

    /** golden 落点（相对 {@code backend/admin-api}）。 */
    private static final Path GOLDEN = Path.of(
            "src/test/resources/processing-order-pool-golden.json");

    /** 录制开关：**只在切片前**用它写 golden；切片后必须不带开关跑。 */
    private static final String UPDATE_FLAG = "pos.pool.golden.update";

    /** 钉住的业务「今天」（= 2026-11-06 10:00 +08）—— 临期度的唯一时间输入。 */
    private static final Instant PINNED = Instant.parse("2026-11-06T02:00:00Z");

    /** 冻结投影的日期/时刻一律走 ISO（不写时间戳数组：可读且跨 JVM 稳定）。 */
    private final ObjectMapper mapper = new ObjectMapper()
            .registerModule(new JavaTimeModule())
            .disable(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS);

    private ProcessingOrderMapper processingOrderMapper;
    private OrderMapper orderMapper;
    private OrderItemMapper orderItemMapper;
    private ProcessingItemMapper processingItemMapper;
    private OrderService orderService;
    private ProcessingPositionOperationMapper positionOperationMapper;
    private ProductionWorkLogMapper workLogMapper;
    private ClientRequestIdService clientRequestIdService;
    private ProductionOperationQueryService productionOperationQueryService;
    private ProductionOperationQtyClient productionOperationQtyClient;
    private StockBatchConsumptionService stockBatchConsumptionService;

    /**
     * 当前场景夹具。**stub 只在 {@code setUp} 注册一次**（每次重复 {@code when(...)} 同形
     * matcher 会被 Mockito 读成「连续答案」而不是覆盖 ⇒ 上一场景的夹具会串到下一场）。
     */
    private Fixture current;
    private int itemCursor;

    @BeforeEach
    void setUp() {
        processingOrderMapper = mock(ProcessingOrderMapper.class);
        orderMapper = mock(OrderMapper.class);
        orderItemMapper = mock(OrderItemMapper.class);
        processingItemMapper = mock(ProcessingItemMapper.class);
        orderService = mock(OrderService.class);
        positionOperationMapper = mock(ProcessingPositionOperationMapper.class);
        workLogMapper = mock(ProductionWorkLogMapper.class);
        clientRequestIdService = mock(ClientRequestIdService.class);
        productionOperationQueryService = mock(ProductionOperationQueryService.class);
        productionOperationQtyClient = mock(ProductionOperationQtyClient.class);
        stockBatchConsumptionService = mock(StockBatchConsumptionService.class);
        lenient().when(orderService.lifecycleService()).thenReturn(mock(OrderLifecycleService.class));
        TenantContext.setTenantId(TENANT);
        MybatisConfiguration conf = new MybatisConfiguration();
        MapperBuilderAssistant assistant = new MapperBuilderAssistant(conf, "");
        TableInfoHelper.initTableInfo(assistant, Order.class);
        TableInfoHelper.initTableInfo(assistant, ProcessingOrder.class);
        // 一次注册、按「当前场景」取值（理由见 current 字段注释）
        when(orderMapper.selectList(any())).thenAnswer(inv -> current.orders());
        when(processingOrderMapper.selectActiveOrderIds(eq(TENANT), anyCollection()))
                .thenAnswer(inv -> current.activeOrderIds());
        when(orderItemMapper.selectList(any()))
                .thenAnswer(inv -> current.itemsByOrder().get(itemCursor++));
        lenient().when(stockBatchConsumptionService.maxRemainingByMaterial(eq(TENANT), any()))
                .thenAnswer(inv -> current.maxRemaining());
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    // ── 装配 ───────────────────────────────────────────────────────────────

    private ProcessingOrderService service() {
        ProcessingOrderService service = new ProcessingOrderService(
                processingOrderMapper, orderMapper, orderItemMapper, processingItemMapper,
                orderService, mapper,
                new ProductionService(processingOrderMapper, positionOperationMapper, workLogMapper, orderMapper,
                        orderItemMapper, clientRequestIdService),
                productionOperationQueryService, productionOperationQtyClient);
        org.springframework.test.util.ReflectionTestUtils.setField(service, "businessClock",
                new BusinessClock(Clock.fixed(PINNED, BusinessClock.BUSINESS_ZONE)));
        org.springframework.test.util.ReflectionTestUtils.setField(service, "stockBatchConsumptionService",
                stockBatchConsumptionService);
        return service;
    }

    // ── 场景 ───────────────────────────────────────────────────────────────

    /** 一个场景的夹具：订单（按池查询顺序）+ 逐单明细 + 已派单集合 + 库存余量 + 滞留上限。 */
    private record Fixture(List<Order> orders, List<List<OrderItem>> itemsByOrder, List<String> activeOrderIds,
                           Map<StockSatisfiability.MaterialDemand, BigDecimal> maxRemaining, BigDecimal maxWait) {
    }

    /** 场景表：名字 → 夹具构造（入参 = 冻结时刻，夹具里的 {@code created_at} 一律相对它）。 */
    private static Map<String, Function<OffsetDateTime, Fixture>> scenarios() {
        Map<String, Function<OffsetDateTime, Fixture>> table = new LinkedHashMap<>();

        // ① 缺省形态：两张同料单、无加急、无到货日 ⇒ 池内计数 / 行序（等待时长降序）/ 告警
        table.put("01-defaults-two-orders", now -> new Fixture(
                List.of(order("o-a", "ORD-0001", now.minusHours(30), false, false, "confirmed", null),
                        order("o-b", "ORD-0002", now.minusHours(2), false, false, "confirmed", null)),
                List.of(items("o-a", "i-a", "prod-1", "SKU-A", "布艺遮光帘A", "3", "米白"),
                        items("o-b", "i-b", "prod-1", "SKU-A", "布艺遮光帘A", "2", "米白")),
                List.of(), Map.of(), null));

        // ② 加急 / 外发**不进池**：三者分区（池内 1 + 插队区 1 + 外发区 1）
        table.put("02-urgent-and-outsourced", now -> new Fixture(
                List.of(order("o-n", "ORD-1001", now.minusHours(30), false, false, "confirmed", null),
                        order("o-u", "ORD-1002", now.minusHours(20), true, false, "confirmed", null),
                        order("o-o", "ORD-1003", now.minusHours(10), false, true, "confirmed", null)),
                List.of(items("o-n", "i-n", "prod-1", "SKU-A", "布艺遮光帘A", "3", "米白"),
                        items("o-u", "i-u", "prod-1", "SKU-A", "布艺遮光帘A", "3", "米白"),
                        items("o-o", "i-o", "prod-1", "SKU-A", "布艺遮光帘A", "3", "米白")),
                List.of(), Map.of(), null));

        // ③ 排序键：到货日升序（null 最后）→ 同日后等待时长降序 → 进池时刻升序 → 单号升序
        table.put("03-ordering-null-last", now -> new Fixture(
                List.of(order("o-p5", "ORD-2001", now.minusHours(30), false, false, "confirmed",
                                LocalDate.of(2026, 11, 11)),
                        order("o-m1a", "ORD-2002", now.minusHours(2), false, false, "confirmed",
                                LocalDate.of(2026, 11, 5)),
                        order("o-nl", "ORD-2003", now.minusHours(50), false, false, "confirmed", null),
                        order("o-m1b", "ORD-2004", now.minusHours(40), false, false, "confirmed",
                                LocalDate.of(2026, 11, 5))),
                List.of(items("o-p5", "i-p5", "prod-1", "SKU-A", "布艺遮光帘A", "1", "米白"),
                        items("o-m1a", "i-m1a", "prod-1", "SKU-A", "布艺遮光帘A", "1", "米白"),
                        items("o-nl", "i-nl", "prod-1", "SKU-A", "布艺遮光帘A", "1", "米白"),
                        items("o-m1b", "i-m1b", "prod-1", "SKU-A", "布艺遮光帘A", "1", "米白")),
                List.of(), Map.of(), null));

        // ④ 超上限告警：自定义阈值 6 小时 ⇒ 只有 30 小时那张告警；文案逐字冻结（阈值来自本次生效值）
        table.put("04-overdue-warning-custom-threshold", now -> new Fixture(
                List.of(order("o-old", "ORD-20261008001", now.minusHours(30), false, false, "confirmed", null),
                        order("o-new", "ORD-20261008002", now.minusHours(2), false, false, "confirmed", null)),
                List.of(items("o-old", "i-old", "prod-1", "SKU-A", "布艺遮光帘A", "3", "米白"),
                        items("o-new", "i-new", "prod-1", "SKU-A", "布艺遮光帘A", "3", "米白")),
                List.of(), Map.of(), new BigDecimal("6")));

        // ⑤ 物料分组：两料（productId × sku）⇒ 两组；展示名与机器键**同时**冻结
        table.put("05-material-groups-and-labels", now -> new Fixture(
                List.of(order("o-1", "ORD-3001", now.minusHours(30), false, false, "confirmed", null),
                        order("o-2", "ORD-3002", now.minusHours(20), false, false, "confirmed", null),
                        order("o-3", "ORD-3003", now.minusHours(10), false, false, "confirmed", null)),
                List.of(items("o-1", "i-1", "prod-1", "SKU-A", "布艺遮光帘A", "3", "米白"),
                        items("o-2", "i-2", "prod-1", "SKU-A", "布艺遮光帘A", "2", "米白"),
                        items("o-3", "i-3", "prod-2", "SKU-B", "遮光帘B", "5", "奶白")),
                List.of(), Map.of(), null));

        // ⑥ 库存可满足性回填：同料最大余量 ≥ 需求 ⇒ true；不足 ⇒ false（两条队列都要回填）
        table.put("06-stock-satisfiability", now -> new Fixture(
                List.of(order("o-ok", "ORD-4001", now.minusHours(30), false, false, "confirmed", null),
                        order("o-short", "ORD-4002", now.minusHours(20), false, false, "confirmed", null),
                        order("o-urgent", "ORD-4003", now.minusHours(10), true, false, "confirmed", null)),
                List.of(items("o-ok", "i-ok", "prod-1", "SKU-A", "布艺遮光帘A", "3", "米白"),
                        items("o-short", "i-short", "prod-2", "SKU-B", "遮光帘B", "5", "奶白"),
                        items("o-urgent", "i-urgent", "prod-2", "SKU-B", "遮光帘B", "5", "奶白")),
                List.of(),
                Map.of(new StockSatisfiability.MaterialDemand("prod-1", "SKU-A"), new BigDecimal("5"),
                        new StockSatisfiability.MaterialDemand("prod-2", "SKU-B"), new BigDecimal("1")),
                new BigDecimal("100")));

        // ⑦ 存量行：processing_info 为 NULL（issue #5550）⇒ 该单无快照、不进池，正常单一行不丢
        table.put("07-legacy-null-processing-info", now -> new Fixture(
                List.of(order("o-legacy", "ORD-5001", now.minusHours(30), false, false, "confirmed", null),
                        order("o-normal", "ORD-5002", now.minusHours(2), false, false, "confirmed", null)),
                List.of(itemsWithoutProcessingInfo("o-legacy", "i-legacy"),
                        items("o-normal", "i-normal", "prod-1", "SKU-A", "布艺遮光帘A", "3", "米白")),
                List.of(), Map.of(), new BigDecimal("100")));

        // ⑧ 池的状态口径：待付款 + 已确认都进池（issue #7634）；已有活跃加工单的单被排除
        table.put("08-statuses-and-active-exclusion", now -> new Fixture(
                List.of(order("o-pending", "ORD-6001", now.minusHours(30), false, false, "pending", null),
                        order("o-confirmed", "ORD-6002", now.minusHours(20), false, false, "confirmed", null),
                        order("o-dispatched", "ORD-6003", now.minusHours(10), false, false, "confirmed", null)),
                List.of(items("o-pending", "i-pending", "prod-1", "SKU-A", "布艺遮光帘A", "3", "米白"),
                        items("o-confirmed", "i-confirmed", "prod-1", "SKU-A", "布艺遮光帘A", "3", "米白")),
                List.of("o-dispatched"), Map.of(), null));

        // ⑨ 卖布单（issue #7079）：saleForm=布料、无加工项 ⇒ 仍在池里；非卖布无加工项行仍不进池
        table.put("09-fabric-and-accessory", now -> new Fixture(
                List.of(order("o-fabric", "ORD-7001", now.minusHours(30), false, false, "confirmed", null),
                        order("o-acc", "ORD-7002", now.minusHours(20), false, false, "confirmed", null)),
                List.of(fabricItems("o-fabric", "i-fabric"), accessoryItems("o-acc", "i-acc")),
                List.of(), Map.of(), new BigDecimal("100")));

        return table;
    }

    // ── 判据 1：池读面逐字节相同 ───────────────────────────────────────────

    @Test
    @DisplayName("切片前后逐字节相同：派单池读面 9 场景（golden 录制于未切片代码）")
    void poolReadFaceIsByteIdenticalToThePreSliceGolden() throws Exception {
        Map<String, Object> actual = new LinkedHashMap<>();
        for (Map.Entry<String, Function<OffsetDateTime, Fixture>> entry : scenarios().entrySet()) {
            try {
                actual.put(entry.getKey(), freezePool(entry.getValue()));
            } catch (RuntimeException e) {
                throw new IllegalStateException("场景 " + entry.getKey() + " 的夹具/读取失败", e);
            }
        }
        assertGolden("pool", actual);
    }

    // ── 判据 2：成批闸的失败面逐字节相同 ───────────────────────────────────

    @Test
    @DisplayName("切片前后逐字节相同：加急 / 外发单混进成批 ⇒ 整批拒绝的 code + message + suggestion")
    void pooledBatchGuardsAreByteIdenticalToThePreSliceGolden() throws Exception {
        Map<String, Object> actual = new LinkedHashMap<>();
        actual.put("urgent-in-batch", freezeRejection("o-u", order("o-u", "ORD-8001",
                OffsetDateTime.now().minusHours(1), true, false, "confirmed", null)));
        actual.put("outsourced-in-batch", freezeRejection("o-o", order("o-o", "ORD-8002",
                OffsetDateTime.now().minusHours(1), false, true, "confirmed", null)));
        assertGolden("guards", actual);
    }

    // ── 判据 3：池化开关归一逐字节相同 ─────────────────────────────────────

    @Test
    @DisplayName("切片前后逐字节相同：pooledEnabled 的缺省解析（唯一缺省值载体）")
    void pooledSwitchNormalizationIsByteIdenticalToThePreSliceGolden() throws Exception {
        Map<String, Object> actual = new LinkedHashMap<>();
        actual.put("requested-null", ProcessingOrderService.pooledEnabled(null));
        actual.put("requested-false", ProcessingOrderService.pooledEnabled(Boolean.FALSE));
        actual.put("requested-true", ProcessingOrderService.pooledEnabled(Boolean.TRUE));
        assertGolden("switch", actual);
    }

    // ── 冻结原语 ───────────────────────────────────────────────────────────

    /** 跑一个场景 → 冻结的池 JSON；业务异常（滞留上限非法）也冻进同一个 golden。 */
    private Map<String, Object> freezePool(Function<OffsetDateTime, Fixture> scenario) {
        OffsetDateTime freezeNow = OffsetDateTime.now();
        Fixture fixture = scenario.apply(freezeNow);
        current = fixture;
        itemCursor = 0;

        Map<String, Object> frozen = new LinkedHashMap<>();
        try {
            frozen.put("pool", normalizePool(service().pool(TENANT, fixture.maxWait()), freezeNow));
        } catch (BusinessException e) {
            frozen.put("rejected", rejectionOf(e));
        }
        return frozen;
    }

    /** 成批闸的拒绝形态：把订单塞进一条 mock 断言链之前的**唯一**前置就是 resolveOrder。 */
    private Map<String, Object> freezeRejection(String orderId, Order order) {
        when(orderMapper.selectById(orderId)).thenReturn(order);
        Map<String, Object> frozen = new LinkedHashMap<>();
        try {
            service().preview(TENANT, List.of(orderId), null, null);
            frozen.put("rejected", "NO-EXCEPTION");
        } catch (BusinessException e) {
            frozen.put("rejected", rejectionOf(e));
        }
        return frozen;
    }

    private static Map<String, Object> rejectionOf(BusinessException e) {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("code", e.getCode());
        out.put("message", e.getMessage());
        out.put("suggestion", e.getSuggestion());
        return out;
    }

    /**
     * 池 → 冻结投影：**保留 DTO 的全部 record 分量**（新增字段会让 golden 失配 ⇒ 强制重新录制），
     * 只把唯一的墙钟派生读数 {@code waitingSince} 归一成「相对冻结时刻的小时数」。
     */
    /** record → 有序 Map（DTO 的全部分量原样带上；新增字段会让 golden 失配）。 */
    @SuppressWarnings("unchecked")
    private Map<String, Object> asMap(Object value) {
        return mapper.convertValue(value, Map.class);
    }

    private Map<String, Object> normalizePool(ProductionPoolViews.Pool pool, OffsetDateTime freezeNow) {
        Map<String, Object> out = asMap(pool);
        out.put("warnings", pool.warnings().stream().map(this::asMap).toList());
        out.put("urgentLines", normalizeLines(pool.urgentLines(), freezeNow));
        out.put("outsourcedLines", normalizeLines(pool.outsourcedLines(), freezeNow));
        List<Map<String, Object>> groups = new ArrayList<>();
        for (ProductionPoolViews.PoolGroup group : pool.groups()) {
            Map<String, Object> g = asMap(group);
            g.put("lines", normalizeLines(group.lines(), freezeNow));
            groups.add(g);
        }
        out.put("groups", groups);
        return out;
    }

    private List<Map<String, Object>> normalizeLines(List<ProductionPoolViews.PoolLine> lines,
                                                    OffsetDateTime freezeNow) {
        List<Map<String, Object>> out = new ArrayList<>();
        for (ProductionPoolViews.PoolLine line : lines) {
            Map<String, Object> m = asMap(line);
            // 进池时刻是墙钟派生 ⇒ 归一成「相对冻结时刻的小时数」（夹具按 N 小时前构造 ⇒ 恒 N.0）
            m.put("waitingSince", hoursBetween(line.waitingSince(), freezeNow));
            out.add(m);
        }
        return out;
    }

    /** 相对小时数（**测试侧**的归一原语，不是被测代码的第二份实现：被测侧另有 1 位小数口径）。 */
    private static BigDecimal hoursBetween(OffsetDateTime from, OffsetDateTime to) {
        long minutes = Duration.between(from, to).toMinutes();
        return BigDecimal.valueOf(minutes).divide(BigDecimal.valueOf(60), 1, RoundingMode.HALF_UP);
    }

    private void assertGolden(String section, Map<String, Object> actual) throws IOException {
        Map<String, Object> root = new LinkedHashMap<>();
        root.put(section, actual);
        if (Boolean.parseBoolean(System.getProperty(UPDATE_FLAG, "false"))) {
            Files.createDirectories(GOLDEN.getParent());
            Map<String, Object> merged = Files.exists(GOLDEN)
                    ? mapper.readValue(Files.readString(GOLDEN, StandardCharsets.UTF_8), Map.class) : new LinkedHashMap<>();
            merged.put(section, actual);
            Files.writeString(GOLDEN, mapper.writerWithDefaultPrettyPrinter().writeValueAsString(merged) + "\n",
                    StandardCharsets.UTF_8);
            return;
        }
        assertThat(Files.exists(GOLDEN))
                .as("golden 不存在（%s）⇒ 本判据无从判起。录制：mvnw test -D%s=true", GOLDEN, UPDATE_FLAG)
                .isTrue();
        Map<String, Object> golden = mapper.readValue(Files.readString(GOLDEN, StandardCharsets.UTF_8), Map.class);
        assertThat(golden.containsKey(section))
                .as("golden 缺少段 %s —— 新增段必须先重新录制 golden（并说明它冻的是什么）", section)
                .isTrue();
        @SuppressWarnings("unchecked")
        Map<String, Object> expected = (Map<String, Object>) golden.get(section);
        // 逐场景断言（不是整段一比）：红的时候**具名**是哪个场景变了，排查不必自己 diff 20KB
        assertThat(actual.keySet())
                .as("段 %s 的场景集与 golden 不一致（新增 / 删除场景都必须重新录制并说明它冻的是什么）", section)
                .isEqualTo(expected.keySet());
        for (String key : actual.keySet()) {
            assertThat(pretty(actual.get(key)))
                    .as("段 %s / 场景 %s：与切片前**不逐字节相同** ⇒ 切片改变了行为"
                            + "（分组键 / 行序 / 计数口径 / 文案 / 回填 / 闸的失败面）", section, key)
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

    private static Order order(String id, String orderNo, OffsetDateTime createdAt, boolean urgent,
                               boolean outsourced, String status, LocalDate requiredDeliveryDate) {
        return Order.builder().id(id).tenantId(TENANT).orderNo(orderNo).status(status)
                .createdAt(createdAt).isUrgent(urgent).isOutsourced(outsourced)
                .requiredDeliveryDate(requiredDeliveryDate).build();
    }

    /** 一行明细：{@code processing_info} 带 sku + 一条加工项（buildSnapshot 的常规形态）。 */
    private static List<OrderItem> items(String orderId, String itemId, String productId, String skuCode,
                                         String productName, String quantity, String colorName) {
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
        return List.of(OrderItem.builder().id(itemId).tenantId(TENANT).orderId(orderId)
                .productId(productId).productName(productName).quantity(new BigDecimal(quantity))
                .width(new BigDecimal("1.5")).height(new BigDecimal("1.1"))
                .processingInfo(info).build());
    }

    private static List<OrderItem> itemsWithoutProcessingInfo(String orderId, String itemId) {
        return List.of(OrderItem.builder().id(itemId).tenantId(TENANT).orderId(orderId)
                .productId("prod-1").productName("存量布艺帘").quantity(new BigDecimal("3"))
                .width(new BigDecimal("1.5")).height(new BigDecimal("1.1")).build());
    }

    private static List<OrderItem> fabricItems(String orderId, String itemId) {
        Map<String, Object> info = new LinkedHashMap<>();
        info.put("colorName", "米白");
        info.put("sellingMethod", "散剪");
        info.put("sku", "SKU-FABRIC");
        info.put("saleForm", "布料");
        return List.of(OrderItem.builder().id(itemId).tenantId(TENANT).orderId(orderId)
                .productId("prod-fabric").productName("遮光窗帘布料")
                .quantity(new BigDecimal("12.5")).width(new BigDecimal("2.8")).height(new BigDecimal("2.6"))
                .processingInfo(info).build());
    }

    private static List<OrderItem> accessoryItems(String orderId, String itemId) {
        Map<String, Object> info = new LinkedHashMap<>();
        info.put("sku", "SKU-ACC");
        return List.of(OrderItem.builder().id(itemId).tenantId(TENANT).orderId(orderId)
                .productId("prod-acc").productName("挂钩配件")
                .quantity(BigDecimal.ONE).width(new BigDecimal("1.5")).height(new BigDecimal("1.1"))
                .processingInfo(info).build());
    }
}
