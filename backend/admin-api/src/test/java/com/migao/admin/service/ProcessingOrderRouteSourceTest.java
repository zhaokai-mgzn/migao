package com.migao.admin.service;

// case_ids: PG-025, PG-026, PG-027, PG-028, PG-029

import ch.qos.logback.classic.Level;
import ch.qos.logback.classic.Logger;
import ch.qos.logback.classic.spi.ILoggingEvent;
import ch.qos.logback.core.read.ListAppender;
import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.entity.ProductionRouteSignal;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.Spy;
import org.mockito.junit.jupiter.MockitoExtension;
import org.slf4j.LoggerFactory;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicReference;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.when;

/**
 * 路线**来源可观测**（V60，issue #4308 P1）：`route_key` / `route_requested_key` / `route_source`
 * 三列真落库，且 T1 / 半命中 / T2 / 正常派生**四态各自可查**。
 *
 * <h2>为什么必须有这个文件</h2>
 * 缺陷的原形是「派生不中 ⇒ 静默回落默认路线，成功路径**零可观测**」：
 * 商品名含「罗马帘」的订单 —— `CURTAIN_TYPE_KEYWORDS` 不中 ⇒ 取默认「布帘」、
 * `CRAFT_KEYWORDS` 不中 ⇒ 取默认「韩褶」⇒ **罗马帘订单拿到布帘·韩褶的 11 道工序**，
 * 工人按布帘工序报工、按布帘单价计件。**今天这条路径连一行日志都没有**，
 * 五要素快照里也没有「路线来源」这一维 ⇒ 错配无数据可查。
 *
 * <h2>三层回落语义（逐层一条断言，各自独立红证）</h2>
 * <ul>
 *   <li><b>T1</b> 信号全不命中 ⇒ {@code default}（+ incident warn 日志）；</li>
 *   <li><b>半命中</b> 只派生出一维 ⇒ {@code partial}；</li>
 *   <li><b>T2</b> 两维都派生出来但**库中无该路线** ⇒ {@code missing_route}
 *       （{@code route_requested_key} 记下「识别的那个键」，用户才知道该去建哪条路线）；</li>
 *   <li><b>正常</b> 两维命中且路线存在 ⇒ {@code derived}；</li>
 *   <li><b>T3</b> 默认路线也没有 ⇒ fail-closed（#4116 已落码，本文件不重复；见
 *       {@code ProcessingOrderServiceTest} 的空库用例）。</li>
 * </ul>
 * 另加**多部位 roll-up** 一条：{@code processing_orders} 只有单值三列，多部位各有一条路线
 * ⇒ 取最需关注的一条（{@code default} &gt; {@code missing_route} &gt; {@code partial} &gt;
 * {@code derived}）——「有损聚合」没有红证就等于没有判据。
 *
 * <h2>红证（注入式）</h2>
 * 本文件断言的是**落库行**（{@code processingOrderMapper.insert} 的实参），不是桩的返回值 ——
 * 把 {@code deriveRouteKey} 的库读取改回常量表、把 {@code resolveRoute} 的来源降级去掉、
 * 把 roll-up 的取最需关注改成取第一条，本文件分别变红（逐条见用例 javadoc）。
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("路线来源可观测（V60，issue #4308）")
class ProcessingOrderRouteSourceTest {

    private static final Long TENANT = 1L;

    @Mock
    private com.migao.admin.mapper.ProcessingOrderMapper processingOrderMapper;
    @Mock
    private com.migao.admin.mapper.OrderMapper orderMapper;
    @Mock
    private com.migao.admin.mapper.OrderItemMapper orderItemMapper;
    @Mock
    private com.migao.admin.mapper.ProcessingItemMapper processingItemMapper;
    @Mock
    private OrderService orderService;
    @Mock
    private com.migao.admin.mapper.ProcessingPositionOperationMapper positionOperationMapper;
    @Mock
    private com.migao.admin.mapper.ProductionWorkLogMapper workLogMapper;
    @Mock
    private ClientRequestIdService clientRequestIdService;
    @Mock
    private ProductionOperationQueryService productionOperationQueryService;
    @Mock
    private ProductionOperationQtyClient productionOperationQtyClient;

    @Spy
    private ObjectMapper objectMapper = new ObjectMapper();

    private Logger serviceLogger;
    private ListAppender<ILoggingEvent> appender;

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(TENANT);
        MybatisConfiguration conf = new MybatisConfiguration();
        MapperBuilderAssistant assistant = new MapperBuilderAssistant(conf, "");
        TableInfoHelper.initTableInfo(assistant, Order.class);
        TableInfoHelper.initTableInfo(assistant, ProcessingOrder.class);
        stubQty();

        serviceLogger = (Logger) LoggerFactory.getLogger(ProcessingOrderService.class);
        appender = new ListAppender<>();
        appender.start();
        serviceLogger.addAppender(appender);
    }

    @AfterEach
    void tearDown() {
        if (serviceLogger != null && appender != null) {
            serviceLogger.detachAppender(appender);
        }
        TenantContext.clear();
    }

    // ── 装配（与 ProcessingOrderServiceTest.realChainService 同款：真实链路上的两个服务）──

    private ProcessingOrderService service() {
        return new ProcessingOrderService(
                processingOrderMapper, orderMapper, orderItemMapper, processingItemMapper,
                orderService, objectMapper,
                new ProductionService(processingOrderMapper, positionOperationMapper, workLogMapper, orderMapper,
                        clientRequestIdService),
                productionOperationQueryService, productionOperationQtyClient);
    }

    /** 算料桩：每道工序统一给「1 / fallback」—— 本文件不关心数量口径（#4208 另有专测）。 */
    private void stubQty() {
        lenient().when(productionOperationQtyClient.resolve(any())).thenAnswer(inv -> {
            List<Map<String, Object>> request = inv.getArgument(0);
            List<ProductionOperationQtyClient.PositionQty> resolved = new ArrayList<>();
            for (Map<String, Object> position : request) {
                Map<String, BigDecimal> qty = new LinkedHashMap<>();
                Map<String, String> source = new LinkedHashMap<>();
                for (Object raw : (List<?>) position.get("operations")) {
                    qty.put(String.valueOf(raw), BigDecimal.ONE);
                    source.put(String.valueOf(raw), "fallback");
                }
                resolved.add(new ProductionOperationQtyClient.PositionQty(
                        (String) position.get("position_name"), qty, source));
            }
            return resolved;
        });
    }

    /**
     * 信号映射表（**库**，V60 种子逐行 + 一条商家自建行「罗马帘」）。
     *
     * <p>「罗马帘」那两行是本文件的关键判别物：它在**迁移前的常量表里不存在** ⇒
     * 只要派生还在读常量，T2 用例的键就会退化成默认键（{@code default} 而不是
     * {@code missing_route}）⇒ 用例变红。这正是「派生读库而非读常量」的判据。</p>
     */
    private void stubSignals() {
        when(productionOperationQueryService.routeSignals(TENANT)).thenReturn(List.of(
                signal("sig-v60-01", "帘头", "帘头", null, 1),
                signal("sig-v60-02", "纱", "纱帘", null, 2),
                signal("sig-v60-03", "布", "布帘", null, 3),
                signal("sig-v60-04", "韩褶", null, "韩褶", 1),
                signal("sig-v60-05", "打孔", null, "打孔", 2),
                signal("sig-v60-06", "四爪钩", null, "四爪钩", 3),
                signal("sig-v60-07", "四叉钩", null, "四爪钩", 4),
                signal("sig-v60-08", "穿杆", null, "穿杆", 5),
                signal("sig-v60-09", "平幔", null, "平幔", 6),
                signal("sig-v60-10", "帘头", null, "平幔", 7),
                // 商家自建（常量表里没有）：罗马帘 —— 库里有信号、**没有路线**（issue #4261 ①）
                signal("sig-custom-01", "罗马帘", "罗马帘", null, 4),
                signal("sig-custom-02", "罗马帘", null, "韩褶", 8)));
    }

    private static ProductionRouteSignal signal(String id, String keyword, String curtainType,
                                                String craft, int priority) {
        return ProductionRouteSignal.builder().id(id).tenantId(TENANT).signal(keyword)
                .curtainType(curtainType).craft(craft).priority(priority)
                .status("active").deleted(0).build();
    }

    /** 路线库桩：只有 布帘×韩褶(11) / 纱帘×韩褶(6) / 帘头×平幔(7)；其余键返回 null（= 库里没有）。 */
    private void stubRoutings() {
        when(productionOperationQueryService.findRouting(eq(TENANT), anyString(), anyString()))
                .thenAnswer(inv -> route(inv.getArgument(1), inv.getArgument(2)));
    }

    private static Map<String, Object> route(String curtainType, String craft) {
        String[][] steps = switch (curtainType + "×" + craft) {
            case "布帘×韩褶" -> new String[][]{
                    {"精裁-布", "裁剪", "米", "0.4", "false", "true"},
                    {"布三边", "车位", "米", "0.4", "false", "false"},
                    {"韩褶-布", "车位", "折", "0.4", "false", "false"},
                    {"外帘装袋", "后道", "套", "1.0", "true", "false"},
                    {"外帘发货", "后道", "套", "1.0", "false", "false"}};
            case "纱帘×韩褶" -> new String[][]{
                    {"精裁-纱", "裁剪", "米", "0.4", "false", "true"},
                    {"纱三边", "车位", "米", "0.4", "false", "false"},
                    {"韩褶-纱", "车位", "折", "0.4", "false", "false"}};
            case "帘头×平幔" -> new String[][]{
                    {"精裁-布", "裁剪", "米", "0.4", "false", "true"},
                    {"帘头制作", "车位", "个", "2.0", "false", "false"}};
            default -> null;
        };
        if (steps == null) {
            return null;
        }
        List<Map<String, Object>> operations = new ArrayList<>();
        int seq = 1;
        for (String[] step : steps) {
            Map<String, Object> view = new LinkedHashMap<>();
            view.put("seq", seq++);
            view.put("operation", step[0]);
            view.put("group", step[1]);
            view.put("unit", step[2]);
            view.put("unit_price", new BigDecimal(step[3]));
            view.put("is_must_finish", Boolean.valueOf(step[4]));
            view.put("is_start_marker", Boolean.valueOf(step[5]));
            operations.add(view);
        }
        Map<String, Object> route = new LinkedHashMap<>();
        route.put("curtain_type", curtainType);
        route.put("craft", craft);
        route.put("operation_count", operations.size());
        route.put("missing_operations", List.of());
        route.put("operations", operations);
        return route;
    }

    /** 订单/明细/主键回填的公共桩；返回捕获**落库行**的容器。 */
    private AtomicReference<ProcessingOrder> stubGenerate(List<OrderItem> items) {
        Order order = Order.builder().id("order-001").tenantId(TENANT)
                .orderNo("ORD-20260919-0001").status("confirmed")
                .customerName("张三").customerPhone("13800138000").build();
        when(orderMapper.selectById("order-001")).thenReturn(order);
        when(orderItemMapper.selectList(any())).thenReturn(items);
        AtomicReference<ProcessingOrder> poRef = new AtomicReference<>();
        when(processingOrderMapper.selectActiveByOrderId("order-001", TENANT)).thenAnswer(inv -> poRef.get());
        when(processingOrderMapper.insert(any(ProcessingOrder.class))).thenAnswer(inv -> {
            ProcessingOrder inserted = inv.getArgument(0);
            inserted.setId("po-001");
            poRef.set(inserted);
            return 1;
        });
        lenient().when(productionOperationQueryService.optionRoutings(TENANT)).thenReturn(List.of());
        lenient().when(productionOperationQueryService.optionFactors(TENANT)).thenReturn(List.of());
        return poRef;
    }

    /** 一条订单明细：加工项名 / 商品名 / 销售方式 = 信号源（与生产同序）。 */
    private static OrderItem item(String itemId, String productName, String processingItemName) {
        Map<String, Object> info = new LinkedHashMap<>();
        info.put("colorName", "米白");
        info.put("sellingMethod", "散剪");
        info.put("processingItems", List.of(Map.of("id", "p-" + itemId, "name", processingItemName,
                "unitPrice", 3.0, "quantity", 2, "unit", "米")));
        return OrderItem.builder()
                .id(itemId).tenantId(TENANT).orderId("order-001")
                .productName(productName).quantity(BigDecimal.valueOf(2))
                .width(new BigDecimal("2.5")).height(new BigDecimal("2.8"))
                .processingInfo(info)
                .build();
    }

    // ── 判据 ────────────────────────────────────────────────────────────────

    @Test
    @DisplayName("PG-025 T1：全无信号 ⇒ route_source=default + route_key=默认键 + requested=null + incident 日志")
    void noSignalFallsBackToDefaultAndIsObservable() {
        stubSignals();
        stubRoutings();
        // 加工项名/商品名/销售方式都不含任何信号关键字（罗马帘在今天之前也走这条 —— 见类注释）
        AtomicReference<ProcessingOrder> po = stubGenerate(List.of(item("item-1", "遮光成品X", "工序甲")));

        var results = service().generate(List.of("order-001"), TENANT, "u1");

        assertThat(results.get(0).isSuccess()).isTrue();
        // ① 三列真落库（判据原话：全不命中 ⇒ 落 route_source='default' + 计 incident 日志）
        assertThat(po.get().getRouteSource()).as("T1 必须是 default —— 不得伪装成「已派生」").isEqualTo("default");
        assertThat(po.get().getRouteKey()).as("实际使用的键 = 默认 布帘×韩褶").isEqualTo("布帘×韩褶");
        assertThat(po.get().getRouteRequestedKey()).as("两维全不命中 ⇒ 没有「想走的键」").isNull();
        // ② incident 日志（迁移前这一层连 info 都没有 —— 这是最隐蔽的一层）
        assertThat(logText())
                .as("T1 必须留 warn 级 incident 痕迹（grep 标记可捞全量）")
                .contains(ProcessingOrderService.INCIDENT_ROUTE_DEFAULTED);
        assertThat(appender.list)
                .as("T1 是「没人派生过」，级别必须是 WARN（不是 INFO/DEBUG）")
                .anyMatch(e -> e.getLevel() == Level.WARN && e.getFormattedMessage().contains("布帘×韩褶"));
    }

    @Test
    @DisplayName("PG-026 半命中：只派生出一维 ⇒ route_source=partial + 键 = 命中维 + 默认维")
    void singleDimensionHitIsPartial() {
        stubSignals();
        stubRoutings();
        // 商品名含「纱」= 只命中帘种；工艺无一命中 ⇒ 取默认 韩褶 ⇒ 纱帘×韩褶（库里有）
        AtomicReference<ProcessingOrder> po = stubGenerate(List.of(item("item-1", "遮光纱A", "工序甲")));

        var results = service().generate(List.of("order-001"), TENANT, "u1");

        assertThat(results.get(0).isSuccess()).isTrue();
        assertThat(po.get().getRouteSource()).as("只命中一维 ⇒ partial（补救动作 = 去信号映射补另一维）")
                .isEqualTo("partial");
        assertThat(po.get().getRouteKey()).as("键 = 命中的帘种 + 默认工艺").isEqualTo("纱帘×韩褶");
        assertThat(po.get().getRouteRequestedKey()).as("partial 也要记下「想走的键」").isEqualTo("纱帘×韩褶");
    }

    @Test
    @DisplayName("PG-027 T2：两维都命中但库中无该路线 ⇒ missing_route + requested 记下那个键（不是 partial）")
    void derivedKeyMissingFromLibraryIsMissingRouteAndKeepsRequestedKey() {
        stubSignals();
        stubRoutings();
        // 「罗马帘」在**库里配了信号**（商家自建行），但库里**没有** 罗马帘×韩褶 这条路线
        AtomicReference<ProcessingOrder> po = stubGenerate(List.of(item("item-1", "罗马帘A", "罗马帘")));

        var results = service().generate(List.of("order-001"), TENANT, "u1");

        assertThat(results.get(0).isSuccess()).isTrue();
        assertThat(po.get().getRouteSource())
                .as("T2 不得并入 partial：补救动作不同（T2 要**建路线**，partial 要**补信号**）")
                .isEqualTo("missing_route");
        assertThat(po.get().getRouteKey()).as("实际使用 = 回落后的默认键").isEqualTo("布帘×韩褶");
        assertThat(po.get().getRouteRequestedKey())
                .as("必须记下「识别的键」—— 没有它，提示说不出该建哪条路线")
                .isEqualTo("罗马帘×韩褶");
        assertThat(logText()).as("T2 必须有 incident 痕迹（迁移前只有一句 info，用户侧不可见）")
                .contains(ProcessingOrderService.INCIDENT_ROUTE_FALLBACK)
                .contains("罗马帘×韩褶");
        // #4246 同口径回归：回落时实例的工序 = 默认路线，不是空、也不是别的
        ArgumentCaptor<com.migao.admin.entity.ProcessingPositionOperation> captor =
                ArgumentCaptor.forClass(com.migao.admin.entity.ProcessingPositionOperation.class);
        org.mockito.Mockito.verify(positionOperationMapper, org.mockito.Mockito.atLeastOnce()).insert(captor.capture());
        assertThat(captor.getAllValues())
                .extracting(com.migao.admin.entity.ProcessingPositionOperation::getOperationName)
                .contains("韩褶-布", "布三边");
    }

    @Test
    @DisplayName("PG-028 正常派生：两维都由库中信号命中且路线存在 ⇒ derived（键 = 想要的键）")
    void fullyDerivedKeyIsDerived() {
        stubSignals();
        stubRoutings();
        AtomicReference<ProcessingOrder> po = stubGenerate(List.of(item("item-1", "布艺遮光帘A", "韩褶-布")));

        var results = service().generate(List.of("order-001"), TENANT, "u1");

        assertThat(results.get(0).isSuccess()).isTrue();
        assertThat(po.get().getRouteSource()).as("两维命中 + 路线存在 ⇒ derived").isEqualTo("derived");
        assertThat(po.get().getRouteKey()).isEqualTo("布帘×韩褶");
        assertThat(po.get().getRouteRequestedKey()).as("derived 时「想走的」= 「实际用的」").isEqualTo("布帘×韩褶");
        assertThat(logText()).as("干净派生不得打 incident（否则 incident 就是噪音，没人会看）")
                .doesNotContain(ProcessingOrderService.INCIDENT_ROUTE_DEFAULTED)
                .doesNotContain(ProcessingOrderService.INCIDENT_ROUTE_FALLBACK);
    }

    @Test
    @DisplayName("PG-029 多部位 roll-up：取最需关注的一条（default > missing_route > partial > derived）")
    void multiPositionRollsUpToMostNeedingAttention() {
        stubSignals();
        stubRoutings();
        // 部位①「韩褶-布」= derived；部位②「罗马帘」= missing_route ⇒ 后者更需要人看
        AtomicReference<ProcessingOrder> po = stubGenerate(List.of(
                item("item-1", "布艺遮光帘A", "韩褶-布"),
                item("item-2", "罗马帘A", "罗马帘")));

        var results = service().generate(List.of("order-001"), TENANT, "u1");

        assertThat(results.get(0).isSuccess()).isTrue();
        assertThat(po.get().getRouteSource()).as("多部位取最需关注的一条 ⇒ missing_route 盖住 derived")
                .isEqualTo("missing_route");
        assertThat(po.get().getRouteRequestedKey())
                .as("三列必须同源取自**同一条**部位 —— 拿 A 的 source 配 B 的键就是自相矛盾")
                .isEqualTo("罗马帘×韩褶");
        assertThat(po.get().getRouteKey()).isEqualTo("布帘×韩褶");
    }

    @Test
    @DisplayName("PG-029 多部位 roll-up：default（零信息）排最前，且 requested 仍为 null")
    void multiPositionDefaultOutranksMissingRoute() {
        stubSignals();
        stubRoutings();
        AtomicReference<ProcessingOrder> po = stubGenerate(List.of(
                item("item-1", "罗马帘A", "罗马帘"),      // missing_route
                item("item-2", "遮光成品X", "工序甲")));   // default（零信号）

        var results = service().generate(List.of("order-001"), TENANT, "u1");

        assertThat(results.get(0).isSuccess()).isTrue();
        assertThat(po.get().getRouteSource())
                .as("冻结口径：default（零信息）> missing_route > partial > derived")
                .isEqualTo("default");
        assertThat(po.get().getRouteRequestedKey()).as("default 没有「想走的键」").isNull();
        assertThat(po.get().getRouteKey()).isEqualTo("布帘×韩褶");
    }

    @Test
    @DisplayName("PG-029 多部位 roll-up：missing_route 盖住 partial（两条都「有问题」，但补救动作不同）")
    void multiPositionMissingRouteOutranksPartial() {
        stubSignals();
        stubRoutings();
        // 部位①「遮光纱A」= partial（只命中帘种）；部位②「罗马帘A」= missing_route
        // ⇒ 判别 missing_route 与 partial 的**相对次序**（冻结口径：default > missing_route > partial > derived）
        AtomicReference<ProcessingOrder> po = stubGenerate(List.of(
                item("item-1", "遮光纱A", "工序甲"),
                item("item-2", "罗马帘A", "罗马帘")));

        var results = service().generate(List.of("order-001"), TENANT, "u1");

        assertThat(results.get(0).isSuccess()).isTrue();
        assertThat(po.get().getRouteSource()).as("missing_route 比 partial 更需关注（补救 = 建路线）")
                .isEqualTo("missing_route");
        assertThat(po.get().getRouteRequestedKey()).isEqualTo("罗马帘×韩褶");
    }

    private String logText() {
        StringBuilder sb = new StringBuilder();
        for (ILoggingEvent event : appender.list) {
            sb.append(event.getFormattedMessage()).append('\n');
        }
        return sb.toString();
    }
}
