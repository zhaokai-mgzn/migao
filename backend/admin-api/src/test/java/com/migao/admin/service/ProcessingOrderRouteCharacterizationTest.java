// case_ids: MC-246
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.entity.ProductionRouteSignal;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProcessingItemMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import com.migao.admin.mapper.ProcessingPositionOperationMapper;
import com.migao.admin.mapper.ProductionWorkLogMapper;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
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
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * 加工单**路线 / 部位派生**面的 characterization 判据（issue #8725 第二档，CP-1）。
 *
 * <h2>它解决什么</h2>
 * 把 {@code ProcessingOrderService}（4,400 行的 LOC 冻结面）切成多个单元时，
 * 「行为 diff = 0」这句话必须是**可执行的判据**，而不是"我看着一样"。
 * 既有 40+ 个 {@code ProcessingOrder*Test} 全是**点状断言**（某条路线取到某个键、
 * 某个部位有几道工序）—— 大面积搬移（挪静态方法 / 换调用方的接收者 / 改私有为包内可见）
 * 可以让它们**全绿通过**，却把 payload 里某个键名、某道工序的顺序、某个 qty 来源悄悄改了。
 *
 * <h2>怎么判</h2>
 * 对**同一批输入**，本判据冻结两件东西，并与 golden **逐字节**比对：
 * <ol>
 *   <li>{@code derivePositionPayload(...)} 的**完整 JSON**（部位名 / 序号 / 工序列表 / qty /
 *       qty_source / order_item_id / position_kind … 全部键）；</li>
 *   <li>同一份输入经 {@code generate(...)} 落库的**路线三元组**
 *       （{@code route_key} / {@code route_requested_key} / {@code route_source}）——
 *       它由 {@code worstResolution} + {@code severity} 的 roll-up 决定，
 *       而 roll-up 只在**多部位**场景下才与「取第一条」产生差异。</li>
 * </ol>
 *
 * <p>golden 录制于**切片前**的代码（{@code -Dpos.slice.golden.update=true} 生成），
 * 切片后**不带**该开关复跑必须逐字节相同。</p>
 *
 * <h2>红证（注入式，逐条见 PR body）</h2>
 * 改 {@code severity} 的档位顺序 / 把 {@code renumberSeq} 摘掉 / 把
 * {@code UNSHAPED_REMOVED_OPERATIONS} 的剔除时机挪到条件工序插入之后 /
 * 把 {@code worstResolution} 换成「取第一条」 ⇒ 本判据**具名**报出差异场景与键路径。
 */
@DisplayName("加工单路线/部位派生 characterization（issue #8725 第二档）")
class ProcessingOrderRouteCharacterizationTest {

    private static final Long TENANT = 1L;
    private static final String ORDER_ID = "order-001";

    /** golden 落点（相对 {@code backend/admin-api}）。 */
    private static final Path GOLDEN = Path.of(
            "src/test/resources/processing-order-route-golden.json");

    /** 录制开关：**只在切片前**用它写 golden；切片后必须不带开关跑。 */
    private static final String UPDATE_FLAG = "pos.slice.golden.update";

    private final ObjectMapper mapper = new ObjectMapper();

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
        // issue #8681 第六批：订单状态流转经门面的包内访问器取生命周期实现点。
        lenient().when(orderService.lifecycleService()).thenReturn(mock(OrderLifecycleService.class));
        TenantContext.setTenantId(TENANT);
        MybatisConfiguration conf = new MybatisConfiguration();
        TableInfoBuilderSupport.init(conf);
        stubQty();
        stubSignals();
        stubRoutings();
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    /** MyBatis-Plus 的实体元数据（{@code Order} / {@code ProcessingOrder} 的 @TableName 解析）。 */
    private static final class TableInfoBuilderSupport {
        private static void init(MybatisConfiguration conf) {
            MapperBuilderAssistant assistant = new MapperBuilderAssistant(conf, "");
            TableInfoHelper.initTableInfo(assistant, Order.class);
            TableInfoHelper.initTableInfo(assistant, ProcessingOrder.class);
        }
    }

    // ── 装配 ───────────────────────────────────────────────────────────────

    private ProcessingOrderService service() {
        return new ProcessingOrderService(
                processingOrderMapper, orderMapper, orderItemMapper, processingItemMapper,
                orderService, mapper,
                new ProductionService(processingOrderMapper, positionOperationMapper, workLogMapper, orderMapper,
                        orderItemMapper, clientRequestIdService),
                productionOperationQueryService, productionOperationQtyClient);
    }

    /** 算料桩：每道工序统一给「1 / fallback」—— 本判据冻结的是**形状**，不是数量的算法。 */
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

    /** 存量信号表（V60 种子 + V63 修正 + 商家自建「罗马帘」）—— 与 ProcessingOrderRouteSourceTest 同一份。 */
    private void stubSignals() {
        lenient().when(productionOperationQueryService.routeSignals(TENANT)).thenReturn(List.of(
                signal("sig-v60-01", "帘头", "帘头", null, 1),
                signal("sig-v60-02", "纱", "纱帘", null, 2),
                signal("sig-v60-03", "布", "布帘", null, 3),
                signal("sig-v60-04", "韩褶", null, "韩褶", 1),
                signal("sig-v60-05", "打孔", null, "打孔", 2),
                signal("sig-v60-06", "四爪钩", null, "韩褶", 3),
                signal("sig-v60-07", "四叉钩", null, "韩褶", 4),
                signal("sig-v60-08", "穿杆", null, "穿杆", 5),
                signal("sig-v60-09", "平幔", null, "平幔", 6),
                signal("sig-v60-10", "帘头", null, "平幔", 7),
                signal("sig-custom-01", "罗马帘", "罗马帘", null, 4),
                signal("sig-custom-02", "罗马帘", null, "韩褶", 8)));
    }

    private static ProductionRouteSignal signal(String id, String keyword, String curtainType,
                                                String craft, int priority) {
        return ProductionRouteSignal.builder().id(id).tenantId(TENANT).signal(keyword)
                .curtainType(curtainType).craft(craft).priority(priority)
                .status("active").deleted(0).build();
    }

    /** 路线库桩（新结构：模板 + 规则 + 部位价目 + 工序库），与 ProcessingOrderRouteSourceTest 同源。 */
    private void stubRoutings() {
        lenient().when(productionOperationQueryService.routeTemplateFor(eq(TENANT), anyString()))
                .thenAnswer(inv -> {
                    String position = inv.getArgument(1);
                    if (RoutingModelFixture.FABRIC_POSITION.equals(position)) {
                        return RoutingModelFixture.fabricTemplate(TENANT);
                    }
                    return "布帘".equals(position) || "纱帘".equals(position)
                            ? RoutingModelFixture.defaultTemplate(TENANT) : null;
                });
        lenient().when(productionOperationQueryService.defaultRouteTemplate(TENANT))
                .thenReturn(RoutingModelFixture.defaultTemplate(TENANT));
        lenient().when(productionOperationQueryService.routeRules(TENANT))
                .thenReturn(RoutingModelFixture.rulesWithFactors(TENANT));
        lenient().when(productionOperationQueryService.operationPositions(TENANT))
                .thenReturn(RoutingModelFixture.canonicalPositions(TENANT));
        lenient().when(productionOperationQueryService.operationsByName(TENANT))
                .thenReturn(RoutingModelFixture.catalog());
        lenient().when(productionOperationQueryService.defaultCraft(TENANT)).thenReturn("韩褶");
        lenient().when(productionOperationQueryService.normalizeOperationName(anyString()))
                .thenAnswer(inv -> RoutingModelFixture.logicalName(inv.getArgument(0)));
        lenient().when(productionOperationQueryService.variantNameOf(anyString(), any(), any()))
                .thenAnswer(inv -> RoutingModelFixture.variantNameOf(
                        inv.getArgument(0), inv.getArgument(1), inv.getArgument(2)));
    }

    // ── 场景 ───────────────────────────────────────────────────────────────

    /** 一个场景：一组订单明细 + 期望被冻结的两个面。 */
    private record Scenario(String name, List<OrderItem> items) {
    }

    private static Map<String, Object> info(String colorName, String sellingMethod) {
        Map<String, Object> pi = new LinkedHashMap<>();
        pi.put("colorName", colorName);
        pi.put("sellingMethod", sellingMethod);
        return pi;
    }

    private static Map<String, Object> processingItem(String id, String name) {
        Map<String, Object> p = new LinkedHashMap<>();
        p.put("id", id);
        p.put("name", name);
        p.put("unitPrice", 3.0);
        p.put("quantity", 2);
        p.put("unit", "米");
        return p;
    }

    private static OrderItem item(String itemId, String productName, Map<String, Object> processingInfo,
                                  String columnCurtainType, String columnCraft) {
        return OrderItem.builder()
                .id(itemId).tenantId(TENANT).orderId(ORDER_ID)
                .productName(productName).quantity(BigDecimal.valueOf(2))
                .width(new BigDecimal("2.5")).height(new BigDecimal("2.8"))
                .curtainType(columnCurtainType).craft(columnCraft)
                .processingInfo(processingInfo)
                .build();
    }

    private static List<Scenario> scenarios() {
        List<Scenario> list = new ArrayList<>();

        // ① 显式字段齐全 ⇒ derived（部位 + 工艺都从列取）
        Map<String, Object> a = info("米白", "散剪");
        a.put("processingItems", List.of(processingItem("p-1", "韩褶")));
        list.add(new Scenario("01-derived", List.of(
                item("item-1", "遮光帘A", a, "布帘", "韩褶"))));

        // ② 两维都缺 ⇒ 默认路线（default，+ incident 日志）
        Map<String, Object> b = info("米白", "散剪");
        b.put("processingItems", List.of(processingItem("p-2", "配件")));
        list.add(new Scenario("02-default", List.of(
                item("item-2", "普通帘", b, null, null))));

        // ③ 两维齐全但库里没有该路线模板 ⇒ missing_route（可观测三元组）
        Map<String, Object> c = info("米白", "散剪");
        c.put("processingItems", List.of(processingItem("p-3", "韩褶")));
        list.add(new Scenario("03-missing-route", List.of(
                item("item-3", "罗马帘A", c, "罗马帘", "韩褶"))));

        // ④ isShaped=false ⇒ 定型/复烫必须被剔除（**且必须在条件工序插入之前**）
        Map<String, Object> d = info("米白", "散剪");
        d.put("processingItems", List.of(processingItem("p-4", "韩褶")));
        d.put("isShaped", Boolean.FALSE);
        d.put("specialOptions", List.of("打孔"));
        list.add(new Scenario("04-unshaped-with-option", List.of(
                item("item-4", "遮光帘D", d, "布帘", "韩褶"))));

        // ⑤ 特殊选项 + 加工项名都触发条件工序（且特殊选项**去重保序**）
        Map<String, Object> e = info("米白", "散剪");
        e.put("processingItems", List.of(processingItem("p-5", "韩褶"), processingItem("p-5b", "配件")));
        e.put("specialOptions", List.of("打孔", "打孔", "穿杆"));
        list.add(new Scenario("05-options-and-items", List.of(
                item("item-5", "遮光帘E", e, "布帘", "韩褶"))));

        // ⑥ 樘窗绑组 + 配布边吸收 + 套级工序只落主布行（多部位 roll-up：derived > partial > default）
        Map<String, Object> f1 = info("米白", "散剪");
        f1.put("processingItems", List.of(processingItem("p-6", "韩褶")));
        f1.put("craftLineId", "line-1");
        Map<String, Object> f2 = info("米白", "散剪");
        f2.put("processingItems", List.of(processingItem("p-7", "韩褶")));
        f2.put("craftLineId", "line-1");
        f2.put("componentRole", "配布边");
        Map<String, Object> f3 = info("奶白", "散剪");
        f3.put("processingItems", List.of(processingItem("p-8", "韩褶")));
        f3.put("craftLineId", "line-1");
        list.add(new Scenario("06-window-group", List.of(
                item("item-6", "遮光帘F", f1, "布帘", "韩褶"),
                item("item-7", "配布边F", f2, "布帘", "韩褶"),
                item("item-8", "纱帘F", f3, "纱帘", "韩褶"))));

        // ⑦ 卖布行（saleForm=布料）⇒ 布料路线；与多部位混单的 roll-up 一起冻结
        Map<String, Object> g1 = info("米白", "full_roll");
        g1.put("saleForm", "布料");
        Map<String, Object> g2 = info("米白", "散剪");
        g2.put("processingItems", List.of(processingItem("p-9", "韩褶")));
        list.add(new Scenario("07-fabric-mixed", List.of(
                item("item-9", "遮光布料X", g1, null, null),
                item("item-10", "遮光帘G", g2, "布帘", "韩褶"))));

        // ⑧ 多部位 roll-up：derived + missing_route 并存 ⇒ 必须取**最需关注**的一条（missing_route）
        Map<String, Object> h1 = info("米白", "散剪");
        h1.put("processingItems", List.of(processingItem("p-10", "韩褶")));
        Map<String, Object> h2 = info("米白", "散剪");
        h2.put("processingItems", List.of(processingItem("p-11", "韩褶")));
        list.add(new Scenario("08-rollup-missing-route", List.of(
                item("item-11", "遮光帘H", h1, "布帘", "韩褶"),
                item("item-12", "罗马帘H", h2, "罗马帘", "韩褶"))));

        // ⑨ 只派生出一维 ⇒ partial（roll-up 档位序 partial > derived）
        Map<String, Object> i1 = info("米白", "散剪");
        i1.put("processingItems", List.of(processingItem("p-12", "配件")));
        list.add(new Scenario("09-partial", List.of(
                item("item-13", "遮光帘I", i1, "布帘", null))));

        return list;
    }

    // ── 判据 ───────────────────────────────────────────────────────────────

    @Test
    @DisplayName("切片前后逐字节相同：部位 payload + 路线三元组（golden 录制于未切片代码）")
    void routeAndPositionPayloadAreByteIdenticalToThePreSliceGolden() throws Exception {
        Map<String, Object> actual = new LinkedHashMap<>();
        for (Scenario scenario : scenarios()) {
            actual.put(scenario.name(), freeze(scenario.items()));
        }

        boolean update = Boolean.parseBoolean(System.getProperty(UPDATE_FLAG, "false"));
        if (update) {
            Files.createDirectories(GOLDEN.getParent());
            Files.writeString(GOLDEN, mapper.writerWithDefaultPrettyPrinter().writeValueAsString(actual)
                    + "\n", StandardCharsets.UTF_8);
            return;
        }

        assertThat(Files.exists(GOLDEN))
                .as("golden 不存在（%s）⇒ 本判据无从判起。录制：%s -D%s=true", GOLDEN, "mvnw test", UPDATE_FLAG)
                .isTrue();
        String goldenText = Files.readString(GOLDEN, StandardCharsets.UTF_8);
        Map<?, ?> golden = mapper.readValue(goldenText, Map.class);

        for (Map.Entry<String, Object> entry : actual.entrySet()) {
            String name = entry.getKey();
            assertThat(golden.containsKey(name))
                    .as("场景 %s 不在 golden 里 —— 新增场景必须先重新录制 golden（并说明它冻的是什么）", name)
                    .isTrue();
            assertThat(mapper.writerWithDefaultPrettyPrinter().writeValueAsString(entry.getValue()))
                    .as("场景 %s 的行为与切片前**不逐字节相同** ⇒ 切片改变了行为（键名 / 顺序 / 数量口径 / 路线 roll-up）",
                            name)
                    .isEqualTo(mapper.writerWithDefaultPrettyPrinter().writeValueAsString(golden.get(name)));
        }
        assertThat(actual.keySet())
                .as("golden 里的场景数必须与现取场景数一致（少录或多录都会让本判据失去判别力）")
                .hasSameSizeAs(golden.keySet());
    }

    /** 一次场景 → 冻结快照：`{positions: [...], route: {...}}`。 */
    private Map<String, Object> freeze(List<OrderItem> items) throws IOException {
        Order order = Order.builder().id(ORDER_ID).tenantId(TENANT)
                .orderNo("ORD-20261106-0001").status("confirmed")
                .customerName("张三").customerPhone("13800138000").build();
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order);
        when(orderItemMapper.selectList(any())).thenReturn(items);
        AtomicReference<ProcessingOrder> inserted = new AtomicReference<>();
        when(processingOrderMapper.selectActiveByOrderId(ORDER_ID, TENANT))
                .thenAnswer(inv -> inserted.get());
        when(processingOrderMapper.insert(any(ProcessingOrder.class))).thenAnswer(inv -> {
            ProcessingOrder po = inv.getArgument(0);
            po.setId("po-001");
            inserted.set(po);
            return 1;
        });

        ProcessingOrderService service = service();
        List<Map<String, Object>> positions = service.derivePositionPayload(ORDER_ID, TENANT);
        service.generate(List.of(ORDER_ID), TENANT, "u1");
        ProcessingOrder po = inserted.get();

        Map<String, Object> frozen = new LinkedHashMap<>();
        frozen.put("positions", mapper.convertValue(positions, Object.class));
        Map<String, Object> route = new LinkedHashMap<>();
        route.put("route_key", po == null ? null : po.getRouteKey());
        route.put("route_requested_key", po == null ? null : po.getRouteRequestedKey());
        route.put("route_source", po == null ? null : po.getRouteSource());
        route.put("order_kind", po == null ? null : po.getOrderKind());
        frozen.put("route", route);
        return frozen;
    }
}
