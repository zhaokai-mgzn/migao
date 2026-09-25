package com.migao.admin.service;

// case_ids: PG-026, PG-027, PG-028, PG-029, PG-030, PG-039, PG-063

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
                        orderItemMapper, clientRequestIdService),
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
     * 信号映射表（**库**，V60 种子逐行 + V63 修正 + 一条商家自建行「罗马帘」）。
     *
     * <p><b>V63 修正（issue #4362 阶段 1 ② / issue #4365 裁定）</b>：{@code 四爪钩 / 四叉钩} 是
     * **加工项（配件）不是工艺**（工艺＝安装工艺＝打褶/悬挂方式，**单值**）⇒ 这两行指向**主线工艺**
     * {@code 韩褶}，不再是独立路线键。桩必须与库的**终态**一致（V60 种子 + V63 UPDATE）——
     * 否则「派生读库」的等价性证据是假的。</p>
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
                signal("sig-v60-06", "四爪钩", null, "韩褶", 3),
                signal("sig-v60-07", "四叉钩", null, "韩褶", 4),
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

    /**
     * 路线库桩（**新结构**，P2b / issue #4459）：默认路线模板 + 规则 26 行 + 部位价目 + 工序库。
     *
     * <p>与旧桩的差别：旧桩把 9 条「{@code (部位×工艺)} 展开快照」直接塞给 {@code findRouting}；
     * 新桩只给**输入**，展开由生产代码做（{@code ProcessingOrderService.buildRoute}）。</p>
     *
     * <p><b>T2 的形态随之变化</b>：旧结构里「库里没有 罗马帘×韩褶 这条路线」；新结构里路线模板
     * 只有「适用哪些帘种」这一维 ⇒ 「该部位没有模板」（罗马帘/帘头）就是 T2。默认模板**必须有**
     * （否则 T3 fail-closed），故模板的 {@code positions} 收窄为 布帘/纱帘。</p>
     */
    private void stubRoutings() {
        lenient().when(productionOperationQueryService.routeTemplateFor(eq(TENANT), anyString()))
                .thenAnswer(inv -> {
                    String position = inv.getArgument(1);
                    // 第 4 个部位（布料，issue #4529）：命中**布料路线模板**（positions=["布料"]）
                    if (RoutingModelFixture.FABRIC_POSITION.equals(position)) {
                        return RoutingModelFixture.fabricTemplate(TENANT);
                    }
                    // 只有 布帘/纱帘 有路线模板（罗马帘/帘头没有 ⇒ T2 回落默认模板）
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
        lenient().when(productionOperationQueryService.routeRules(TENANT))
                .thenReturn(RoutingModelFixture.rulesWithFactors(TENANT));
        lenient().when(productionOperationQueryService.operationPositions(TENANT))
                .thenReturn(RoutingModelFixture.canonicalPositions(TENANT));
        lenient().when(productionOperationQueryService.operationsByName(TENANT))
                .thenReturn(RoutingModelFixture.catalog());
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

    /**
     * 一条订单明细，可**分别**指定三种载体（V63 / issue #4362 的推导链判别物）：
     * <ol>
     *   <li>{@code columnCurtainType}/{@code columnCraft} = {@code order_items} 的**结构化列**
     *       （显式字段，最高优先级）；</li>
     *   <li>{@code jsonCurtainType}/{@code jsonCraft} = {@code processing_info} 顶层的同键
     *       （issue #4354 的旧载体 —— 与列**同义**，列非空时覆盖它）；</li>
     *   <li>{@code processingItemName} = 加工项名（推导链第 2 层「加工项推导」的信号源）。</li>
     * </ol>
     * 三者可同时给，正是为了把「谁压过谁」变成**可失败的断言**（只给一种载体时判不出优先级）。
     */
    private static OrderItem itemWithCarriers(String itemId, String productName, String processingItemName,
                                              String columnCurtainType, String columnCraft,
                                              String jsonCurtainType, String jsonCraft) {
        return itemWithCarriers(itemId, productName, processingItemName, columnCurtainType, columnCraft,
                jsonCurtainType, jsonCraft, null);
    }

    /**
     * 同 {@link #itemWithCarriers}，另可给 {@code processing_info} 顶层的 {@code componentRole}
     * （**受控枚举**：主布 / 配布边 / 纱 —— issue #4452 起它是部位维的受控来源）。
     */
    private static OrderItem itemWithCarriers(String itemId, String productName, String processingItemName,
                                              String columnCurtainType, String columnCraft,
                                              String jsonCurtainType, String jsonCraft,
                                              String componentRole) {
        Map<String, Object> info = new LinkedHashMap<>();
        info.put("colorName", "米白");
        info.put("sellingMethod", "散剪");
        if (jsonCurtainType != null) {
            info.put("curtainType", jsonCurtainType);
        }
        if (jsonCraft != null) {
            info.put("craft", jsonCraft);
        }
        if (componentRole != null) {
            info.put("componentRole", componentRole);
        }
        info.put("processingItems", List.of(Map.of("id", "p-" + itemId, "name", processingItemName,
                "unitPrice", 3.0, "quantity", 2, "unit", "米")));
        return OrderItem.builder()
                .id(itemId).tenantId(TENANT).orderId("order-001")
                .productName(productName).quantity(BigDecimal.valueOf(2))
                .width(new BigDecimal("2.5")).height(new BigDecimal("2.8"))
                .curtainType(columnCurtainType).craft(columnCraft)
                .processingInfo(info)
                .build();
    }

    // ── 判据 ────────────────────────────────────────────────────────────────

    // ══════════════════════════ 布料基础路线（issue #4529，包 F）══════════════════════════

    /** 一条订单明细，可指定 {@code processing_info.saleForm}（售卖形态，前端 #4493 落库）。 */
    private static OrderItem itemWithSaleForm(String itemId, String productName,
                                              String processingItemName, String saleForm) {
        Map<String, Object> info = new LinkedHashMap<>();
        info.put("colorName", "米白");
        info.put("sellingMethod", "散剪");
        if (saleForm != null) {
            info.put("saleForm", saleForm);
        }
        info.put("processingItems", List.of(Map.of("id", "p-" + itemId, "name", processingItemName,
                "unitPrice", 3.0, "quantity", 2, "unit", "米")));
        return OrderItem.builder()
                .id(itemId).tenantId(TENANT).orderId("order-001")
                .productName(productName).quantity(BigDecimal.valueOf(2))
                .width(new BigDecimal("2.5")).height(new BigDecimal("2.8"))
                .processingInfo(info)
                .build();
    }

    /** 本次生成落库的工序实例名（按落库顺序）。 */
    private List<String> instanceOperationNames() {
        ArgumentCaptor<com.migao.admin.entity.ProcessingPositionOperation> captor =
                ArgumentCaptor.forClass(com.migao.admin.entity.ProcessingPositionOperation.class);
        org.mockito.Mockito.verify(positionOperationMapper, org.mockito.Mockito.atLeastOnce())
                .insert(captor.capture());
        return captor.getAllValues().stream()
                .map(com.migao.admin.entity.ProcessingPositionOperation::getOperationName).toList();
    }

    @Test
    @DisplayName("PG-039 布料单（saleForm=布料）⇒ 部位=布料 / 工序 = 配料 + 打包（issue #4529 判据 1）")
    void fabricOrderSelectsTheFabricRoute() {
        stubRoutings();
        AtomicReference<ProcessingOrder> po = stubGenerate(List.of(
                itemWithSaleForm("item-1", "遮光布料X", "配料", "布料")));

        var results = service().generate(List.of("order-001"), TENANT, "u1");

        assertThat(results.get(0).isSuccess()).isTrue();
        assertThat(po.get().getRouteKey())
                .as("布料单必须落在**布料路线**上（部位 = 第 4 个部位「布料」）")
                .isEqualTo(RoutingModelFixture.FABRIC_TEMPLATE_NAME);
        assertThat(po.get().getRouteSource()).isEqualTo("direct");
        assertThat(instanceOperationNames())
                .as("布料单的工序 = 配料 + 打包（多一道窗帘工序 / 缺打包都红）")
                .containsExactly("配料", "打包");
    }

    /**
     * 一条订单明细：**卖布行** —— 与 {@link #itemWithSaleForm} 的差别只有一个，
     * 但正是真库的形态：**没有 `processingItems` 键**（按米卖布不选加工项；issue #4909 真库实证）。
     */
    private static OrderItem fabricItemWithoutProcessingItems(String itemId, String productName, String saleForm) {
        Map<String, Object> info = new LinkedHashMap<>();
        info.put("colorName", "米白");
        info.put("sellingMethod", "full_roll");
        if (saleForm != null) {
            info.put("saleForm", saleForm);
        }
        return OrderItem.builder()
                .id(itemId).tenantId(TENANT).orderId("order-001")
                .productName(productName).quantity(BigDecimal.TEN)
                .width(new BigDecimal("2.5")).height(new BigDecimal("2.8"))
                .processingInfo(info)
                .build();
    }

    /**
     * 🔴 <b>真库实证的缺陷形态（issue #4909）</b>：加工单 `JG-20260921-8237`（订单 `20260921973550001`）
     * 含一件卖布（`saleForm=布料` / `sellingMethod=full_roll` / 10 米）却**零工序**。
     *
     * <p>与上面 PG-039 那条的区别就是**红证所在**：PG-039 的夹具把 `配料` 塞进了 `processingItems`，
     * 而真库的卖布行**没有这个键** ⇒ 改前 {@code buildSnapshot} 的 `procs.isEmpty()` 把它整行丢掉
     * ⇒ {@code deriveRouteKey} 的布料分支永不执行（整件商品的工序凭空消失，且无任何报错）。</p>
     */
    @Test
    @DisplayName("PG-063 卖布行（saleForm=布料、**无** processingItems）⇒ 仍走布料基础路线并实例化工序")
    void fabricLineWithoutProcessingItemsStillGetsTheFabricRoute() {
        stubRoutings();
        AtomicReference<ProcessingOrder> po = stubGenerate(List.of(
                fabricItemWithoutProcessingItems("item-1", "9231 遮光窗帘", "布料")));

        var results = service().generate(List.of("order-001"), TENANT, "u1");

        assertThat(results.get(0).isSuccess())
                .as("改前：快照被清空 ⇒ 该单被判「无加工项，无需生成加工单」")
                .isTrue();
        assertThat(po.get().getRouteKey())
                .as("卖布行的路线 = **布料路线**（改前该行根本不参与路线解析）")
                .isEqualTo(RoutingModelFixture.FABRIC_TEMPLATE_NAME);
        assertThat(instanceOperationNames())
                .as("布料基础路线的工序必须落库"
                        + "（夹具主线 = V79 版 [配料,打包]；真库 V88 终态 = [裁剪,打包]，见 MainlineOperationReferenceTest）")
                .containsExactly("配料", "打包");
    }

    /**
     * 🔴 <b>随单发现的第二处缺陷（issue #4909 判据 3）</b>：卖布行按米卖、**没有加工项**
     * ⇒ {@code isMeterBasedLine} 第 1 段判 false（{@code processingItems} 缺失）⇒ 米数进不了
     * {@code calc_info} ⇒ 端点按缺键兜底 <b>1</b>（{@code qty_source=fallback}）
     * ⇒ 10 米的布单只做 1 米、计件按 1 米算。
     */
    @Test
    @DisplayName("PG-063 卖布行的算料输入带米数（订单行 quantity）—— 不得兜底 1（#4208 红线）")
    void fabricLineWithoutProcessingItemsSendsOrderQuantityAsMeters() {
        stubRoutings();
        stubGenerate(List.of(fabricItemWithoutProcessingItems("item-1", "9231 遮光窗帘", "布料")));

        service().generate(List.of("order-001"), TENANT, "u1");

        @SuppressWarnings("unchecked")
        ArgumentCaptor<List<Map<String, Object>>> captor = ArgumentCaptor.forClass(List.class);
        org.mockito.Mockito.verify(productionOperationQtyClient).resolve(captor.capture());
        Map<String, Object> request = captor.getValue().get(0);
        assertThat(request.get("position_name")).isEqualTo("9231 遮光窗帘 米白");
        @SuppressWarnings("unchecked")
        Map<String, Object> calcInfo = (Map<String, Object>) request.get("calc_info");
        assertThat(calcInfo)
                .as("卖布行的米数只能取**订单行数量**（与 isMeterBasedLine 的取值口径同源）；"
                        + "缺键 ⇒ 端点兜底 1 ⇒ 10 米的布单只做 1 米")
                .containsEntry("fabric_meters", BigDecimal.TEN);
    }

    /**
     * 反向护栏（issue #4909 的边界）：**没有** `saleForm=布料` 的行（普通配件 / 赠品行）
     * ⇒ 旧语义逐字不变 —— 无加工项仍不进快照（不成部位、不产工序、也不得凭空生成加工单）。
     */
    @Test
    @DisplayName("PG-063 反向护栏：无加工项且**非**卖布行 ⇒ 仍不进快照（旧语义不变）")
    void itemWithoutProcessingItemsAndWithoutFabricSaleFormIsStillSkipped() {
        stubRoutings();
        // 只桩到「订单 + 明细」：本用例的路径在**幂等检查之前**就中止（快照为空）
        // ⇒ 不走 stubGenerate 的 selectActiveByOrderId / insert，避免严格桩判「备而不用」。
        when(orderMapper.selectById("order-001")).thenReturn(Order.builder()
                .id("order-001").tenantId(TENANT).orderNo("ORD-20260919-0001").status("confirmed").build());
        when(orderItemMapper.selectList(any())).thenReturn(
                List.of(fabricItemWithoutProcessingItems("item-1", "普通配件", null)));

        var results = service().generate(List.of("order-001"), TENANT, "u1");

        assertThat(results.get(0).isSuccess())
                .as("无加工项且非卖布行 ⇒ 订单仍判「无加工项，无需生成加工单」（改前语义，不得被本单放宽）")
                .isFalse();
        assertThat(results.get(0).getMessage()).contains("无加工项");
    }

    /** 本次生成落库的工序实例（按落库顺序）—— 落库**值**的判据只能从捕获的实体上取。 */
    private List<com.migao.admin.entity.ProcessingPositionOperation> instanceOperations() {
        ArgumentCaptor<com.migao.admin.entity.ProcessingPositionOperation> captor =
                ArgumentCaptor.forClass(com.migao.admin.entity.ProcessingPositionOperation.class);
        org.mockito.Mockito.verify(positionOperationMapper, org.mockito.Mockito.atLeastOnce())
                .insert(captor.capture());
        return captor.getAllValues();
    }

    /**
     * 🔴 <b>红证①（issue #4696）：未定价 ≠ 0 元 —— 落库的实例快照必须是 {@code NULL}，不是 0。</b>
     *
     * <p>夹具事实：布料单的 `配料`/`打包` 矩阵格价逐字是 {@code NULL}（`canonicalPositions`
     * 的「适用但未定价」形态，与 V79 ② 的种子同值），而这两道工序的**工序库行价**逐字是 {@code 0.0}
     * （{@code FABRIC_OPERATIONS}，与 V79 ① 的 {@code unit_price = 0} 同值）。</p>
     *
     * <p>改前：{@code buildRoute} 回落工序库行价 ⇒ 落库 {@code unit_price = 0} ⇒
     * 报工即按 <b>0 元</b> 计件（工人白干），而读面显示「未定价」——两处口径不一致且无人可见。
     * 本断言就是那条红线的机械形态：<b>落库值必须是 NULL</b>。</p>
     */
    @Test
    @DisplayName("PG-039 未定价 ⇒ 落库实例单价 = NULL（**不得**回落工序库行价 0 元，issue #4696）")
    void unpricedFabricRoutePersistsNullUnitPriceNotZero() {
        stubRoutings();
        stubGenerate(List.of(itemWithSaleForm("item-1", "遮光布料X", "配料", "布料")));

        var results = service().generate(List.of("order-001"), TENANT, "u1");

        assertThat(results.get(0).isSuccess()).isTrue();
        List<com.migao.admin.entity.ProcessingPositionOperation> ops = instanceOperations();
        assertThat(ops).extracting(com.migao.admin.entity.ProcessingPositionOperation::getOperationName)
                .as("布料单两道工序（缺一道 ⇒ 判据无从谈起）").containsExactly("配料", "打包");
        assertThat(ops).allSatisfy(op -> assertThat(op.getUnitPrice())
                .as("工序「%s」的矩阵价是 NULL ⇒ 实例快照必须为 null（未定价）；"
                        + "回落工序库行价（夹具里逐字 0.0）⇒ 计件 0 元且与「定价 0」不可区分",
                        op.getOperationName())
                .isNull());
    }

    /**
     * 反向护栏（issue #4696）：把同一格**显式定价为 0 元** ⇒ 落库 {@code 0}，
     * 与「未定价」（{@code NULL}）**可区分**。两者同形 ⇒ 本条或上一条必红。
     */
    @Test
    @DisplayName("PG-039 反向护栏：显式定价 0 元 ⇒ 落库 0（≠ 未定价的 NULL，issue #4696）")
    void explicitlyZeroPricedFabricRoutePersistsZero() {
        stubRoutings();
        // ⚠️ 顺序：`stubGenerate` 自己会重桩 `operationPositions` ⇒ 覆盖必须放在它**之后**
        stubGenerate(List.of(itemWithSaleForm("item-1", "遮光布料X", "配料", "布料")));
        lenient().when(productionOperationQueryService.operationPositions(TENANT))
                .thenReturn(zeroPricedFabricPositions());

        service().generate(List.of("order-001"), TENANT, "u1");

        List<com.migao.admin.entity.ProcessingPositionOperation> ops = instanceOperations();
        assertThat(ops).extracting(com.migao.admin.entity.ProcessingPositionOperation::getOperationName)
                .containsExactly("配料", "打包");
        // 只把 `配料`×`布料` 改成 0：`打包` 仍 NULL ⇒ 同一批实例里两态共存且可区分
        assertThat(ops).filteredOn(op -> "配料".equals(op.getOperationName()))
                .allSatisfy(op -> assertThat(op.getUnitPrice())
                        .as("定价为 0 元 = **有价** ⇒ 落 0；若与未定价同形（都 null）⇒ 红")
                        .isNotNull().isEqualByComparingTo(BigDecimal.ZERO));
        assertThat(ops).filteredOn(op -> "打包".equals(op.getOperationName()))
                .allSatisfy(op -> assertThat(op.getUnitPrice())
                        .as("同一次实例化里另一道仍是未定价 ⇒ 两态可区分")
                        .isNull());
    }

    /** 布料两格价目：`配料` 显式 0 元、`打包` 仍未定价（NULL）。 */
    private static List<com.migao.admin.entity.ProductionOperationPosition> zeroPricedFabricPositions() {
        List<com.migao.admin.entity.ProductionOperationPosition> rows = new ArrayList<>();
        for (com.migao.admin.entity.ProductionOperationPosition row
                : RoutingModelFixture.canonicalPositions(TENANT)) {
            boolean fabricZero = RoutingModelFixture.FABRIC_POSITION.equals(row.getPosition())
                    && "配料".equals(row.getLogicalName());
            rows.add(com.migao.admin.entity.ProductionOperationPosition.builder()
                    .id(row.getId()).tenantId(row.getTenantId())
                    .logicalName(row.getLogicalName()).position(row.getPosition())
                    .unitPrice(fabricZero ? BigDecimal.ZERO : row.getUnitPrice())
                    .applicable(row.getApplicable()).status(row.getStatus()).deleted(row.getDeleted())
                    .build());
        }
        return rows;
    }

    @Test
    @DisplayName("PG-039 回归：缺 saleForm / saleForm=成品帘 ⇒ 与改前**逐字相同**（判据 5）")
    void missingOrFinishedSaleFormKeepsTheLegacyDerivation() {
        stubSignals();
        stubRoutings();
        // ① 缺键（存量单）：两维都缺 ⇒ 存量信号兜底 ⇒ 布帘×韩褶，来源 derived
        //    （加工项名「韩褶-布」同时含 `布` 与 `韩褶` 两个信号 —— 存量单的典型形态）
        AtomicReference<ProcessingOrder> missing = stubGenerate(List.of(
                item("item-1", "遮光成品X", "韩褶-布")));
        service().generate(List.of("order-001"), TENANT, "u1");
        assertThat(missing.get().getRouteKey()).isEqualTo(RoutingModelFixture.TEMPLATE_NAME);
        assertThat(missing.get().getRouteSource()).isEqualTo("derived");
        List<String> missingOps = instanceOperationNames();

        // ② 显式 saleForm=成品帘：必须与缺键**逐字相同**（不得被布料分支捕获）
        // 只清调用记录（**不 reset 桩**）：`stubGenerate` 会重新桩上新的 poRef
        org.mockito.Mockito.clearInvocations(positionOperationMapper);
        AtomicReference<ProcessingOrder> finished = stubGenerate(List.of(
                itemWithSaleForm("item-1", "遮光成品X", "韩褶-布", "成品帘")));
        service().generate(List.of("order-001"), TENANT, "u1");
        assertThat(finished.get().getRouteKey())
                .as("saleForm=成品帘 不得改变路线（只有 `布料` 才是布料单）")
                .isEqualTo(missing.get().getRouteKey());
        assertThat(finished.get().getRouteSource()).isEqualTo(missing.get().getRouteSource());
        assertThat(instanceOperationNames())
                .as("saleForm=成品帘 的工序序列与缺键存量单**逐字相同**（回归不变量）")
                .isEqualTo(missingOps);
    }

    @Test
    @DisplayName("PG-029 推导链①：结构化**列**（显式字段）压过 processing_info 同键 ⇒ direct 用列值")
    void explicitColumnBeatsProcessingInfoKey() {
        // **不** stub 信号映射表：两维都由显式字段给出时，派生链（第 2/3 层）根本不该被触碰 ——
        // 下面 verify(never) 把这一点也钉死（顺带避免 Mockito 严格桩把「备而不用」判成失败）。
        stubRoutings();
        // 列 = 纱帘×韩褶（库里**有**这条路线）；JSONB 同键 = 布帘×打孔（**也**是合法键）
        // ⇒ 只要读取侧没有「列优先」，结果就会是 布帘×打孔 ⇒ 本用例红。
        AtomicReference<ProcessingOrder> po = stubGenerate(List.of(
                itemWithCarriers("item-1", "遮光成品X", "工序甲",
                        "纱帘", "韩褶", "布帘", "打孔")));

        var results = service().generate(List.of("order-001"), TENANT, "u1");

        assertThat(results.get(0).isSuccess()).isTrue();
        assertThat(po.get().getRouteSource())
                .as("显式字段（列）是推导链最高层 ⇒ 两维都取自列 ⇒ direct")
                .isEqualTo("direct");
        assertThat(po.get().getRouteKey())
                .as("P2b：route_key = 实际使用的路线（= 该部位命中的模板）").isEqualTo(RoutingModelFixture.TEMPLATE_NAME);
        assertThat(po.get().getRouteRequestedKey()).isEqualTo("纱帘×韩褶");
        org.mockito.Mockito.verify(productionOperationQueryService, org.mockito.Mockito.never())
                .routeSignals(TENANT);
    }

    @Test
    @DisplayName("PG-027 推导链②：显式字段给一维 + componentRole 给另一维 ⇒ partial（显式维不被覆盖）")
    void explicitColumnBeatsProcessingItemDerivation() {
        stubRoutings();
        // 列只给工艺 打孔；部位由**受控来源** componentRole=纱 补齐（issue #4452：部位不再猜加工项名）。
        // ⇒ 纱帘×打孔，来源 partial（有一维来自受控来源、不是两维都由信号表派生）。
        // 若显式字段被补齐覆盖 ⇒ 会得到别的键 ⇒ 本用例红。
        // ⚠️ 本用例**不** stub 信号表（两维都不缺 ⇒ 派生链第 3 层不该被触碰）—— 这也是
        // 「新单不读信号表」的判据之一（UnnecessaryStubbing 会把它钉成红）。
        AtomicReference<ProcessingOrder> po = stubGenerate(List.of(
                itemWithCarriers("item-1", "遮光成品X", "工序甲", null, "打孔", null, null, "纱")));

        var results = service().generate(List.of("order-001"), TENANT, "u1");

        assertThat(results.get(0).isSuccess()).isTrue();
        assertThat(po.get().getRouteSource())
                .as("显式工艺 + componentRole 补齐部位 ⇒ partial（补救动作 = 把另一维填进订单）")
                .isEqualTo("partial");
        assertThat(po.get().getRouteRequestedKey())
                .as("显式工艺（打孔）必须压过任何补齐 —— 否则就是「补齐盖掉用户填的值」")
                .isEqualTo("纱帘×打孔");
        org.mockito.Mockito.verify(productionOperationQueryService, org.mockito.Mockito.never())
                .routeSignals(TENANT);
    }

    @Test
    @DisplayName("PG-029 商品名不再是信号源：加工项名/options 是**存量单兜底**的唯一信号源")
    void productNameIsNoLongerASignalSource() {
        stubSignals();
        stubRoutings();
        // 商品名含「纱」（旧实现里这是帘种信号源，会把部位带成纱帘）；
        // 加工项名「打孔-布」在**存量兜底**里同时命中 布（帘种）与 打孔（工艺）。
        // ⇒ 新口径：帘种来自加工项名 ⇒ 布帘×打孔（库里没有 ⇒ missing_route）。
        // 若商品名仍是信号源且排在加工项名之前 ⇒ 得到 纱帘×打孔 ⇒ 本用例红。
        AtomicReference<ProcessingOrder> po = stubGenerate(List.of(
                itemWithCarriers("item-1", "遮光纱A", "打孔-布", null, null, null, null)));

        var results = service().generate(List.of("order-001"), TENANT, "u1");

        assertThat(results.get(0).isSuccess()).isTrue();
        assertThat(po.get().getRouteRequestedKey())
                .as("商品名里的「纱」不再参与判据（加工项名才是存量兜底的信号源）")
                .isEqualTo("布帘×打孔");
    }

    @Test
    @DisplayName("PG-029 四爪钩/四叉钩是加工项不是工艺 ⇒ 信号指向主线，不再是独立路线键")
    void hookAccessorySignalPointsAtMainLine() {
        stubSignals();
        stubRoutings();
        // 加工项名就是「四爪钩」（配件本身）—— **存量单兜底**（无 V63 列 / componentRole）：
        // V63 前：信号 四爪钩 → craft=四爪钩 ⇒ 派生键 布帘×四爪钩（库里没有 ⇒ missing_route）；
        // V63 后：指向主线工艺 韩褶 ⇒ 工艺 = 韩褶。
        // issue #4452：**部位不再来自商品名** ⇒ 部位维缺 ⇒ 取默认 布帘，来源 partial
        // （旧实现里商品名「布艺遮光帘A」含「布」会把它带成「derived」—— 那条判据已作废）。
        // ⇒ 断言「工艺 = 韩褶 而不是 四爪钩」即可区分 V63 前后（本用例即红证）。
        AtomicReference<ProcessingOrder> po = stubGenerate(List.of(
                itemWithCarriers("item-1", "布艺遮光帘A", "四爪钩", null, null, null, null)));

        var results = service().generate(List.of("order-001"), TENANT, "u1");

        assertThat(results.get(0).isSuccess()).isTrue();
        assertThat(po.get().getRouteSource())
                .as("部位维缺（商品名不再是判据）⇒ partial，不是「两维都由信号表派生」的 derived")
                .isEqualTo("partial");
        assertThat(po.get().getRouteKey()).as("P2b：route_key = 实际使用的路线").isEqualTo(RoutingModelFixture.TEMPLATE_NAME);
        assertThat(po.get().getRouteRequestedKey())
                .as("不得再派生/记录「布帘×四爪钩」—— 四爪钩是加工项（配件），不是并列工艺")
                .isEqualTo("布帘×韩褶");
    }

    @Test
    @DisplayName("PG-026 T1：全无信号 ⇒ route_source=default + route_key=默认键 + requested=null + incident 日志")
    void noSignalFallsBackToDefaultAndIsObservable() {
        stubSignals();
        stubRoutings();
        // 加工项名/商品名/销售方式都不含任何信号关键字（罗马帘在今天之前也走这条 —— 见类注释）
        AtomicReference<ProcessingOrder> po = stubGenerate(List.of(item("item-1", "遮光成品X", "工序甲")));

        var results = service().generate(List.of("order-001"), TENANT, "u1");

        assertThat(results.get(0).isSuccess()).isTrue();
        // ① 三列真落库（判据原话：全不命中 ⇒ 落 route_source='default' + 计 incident 日志）
        assertThat(po.get().getRouteSource()).as("T1 必须是 default —— 不得伪装成「已派生」").isEqualTo("default");
        assertThat(po.get().getRouteKey())
                .as("P2b：route_key = 实际使用的路线（= 该租户的默认模板名）").isEqualTo(RoutingModelFixture.TEMPLATE_NAME);
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
    @DisplayName("PG-027 半命中：只补齐一维 ⇒ route_source=partial + 键 = 补齐维 + 默认维")
    void singleDimensionHitIsPartial() {
        stubRoutings();
        // 受控来源给一维（componentRole=纱 ⇒ 纱帘），另一维（工艺）缺 ⇒ 取该租户默认 韩褶
        // ⇒ 纱帘×韩褶（库里有）。⚠️ issue #4452 起「商品名含纱」不再是半命中的形态
        // （商品名不再是判据）—— 半命中改由**受控来源**给出一维来构造。
        AtomicReference<ProcessingOrder> po = stubGenerate(List.of(
                itemWithCarriers("item-1", "遮光纱A", "工序甲", null, null, null, null, "纱")));

        var results = service().generate(List.of("order-001"), TENANT, "u1");

        assertThat(results.get(0).isSuccess()).isTrue();
        assertThat(po.get().getRouteSource()).as("只补齐一维 ⇒ partial（补救动作 = 把另一维填进订单）")
                .isEqualTo("partial");
        assertThat(po.get().getRouteKey()).as("P2b：route_key = 实际使用的路线").isEqualTo(RoutingModelFixture.TEMPLATE_NAME);
        assertThat(po.get().getRouteRequestedKey()).as("partial 也要记下「想走的键」").isEqualTo("纱帘×韩褶");
    }

    @Test
    @DisplayName("PG-028 T2：键在库中无该路线 ⇒ missing_route + requested 记下那个键（不是 partial）")
    void derivedKeyMissingFromLibraryIsMissingRouteAndKeepsRequestedKey() {
        stubRoutings();
        // 「罗马帘」部位**没有**路线模板（库里只有 布帘/纱帘）—— 键由订单行显式给出
        // （issue #4452：部位不再从信号/商品名派生 ⇒ 「库里没有的部位」只能由显式字段构造）。
        // 工艺维缺 ⇒ 取该租户默认 韩褶 ⇒ 想走的键 = 罗马帘×韩褶（库里没有 ⇒ 回落默认模板）。
        // ⚠️ 本用例**不** stub 信号表：两维都不缺 ⇒ 派生链第 3 层不该被触碰
        // （「新单不读信号表」的判据之一，UnnecessaryStubbing 会把它钉成红）。
        AtomicReference<ProcessingOrder> po = stubGenerate(List.of(
                itemWithCarriers("item-1", "罗马帘A", "工序甲", "罗马帘", null, null, null)));

        var results = service().generate(List.of("order-001"), TENANT, "u1");

        assertThat(results.get(0).isSuccess()).isTrue();
        assertThat(po.get().getRouteSource())
                .as("T2 不得并入 partial：补救动作不同（T2 要**建路线**，partial 要**补信号**）")
                .isEqualTo("missing_route");
        assertThat(po.get().getRouteKey())
                .as("P2b：route_key = 实际使用的路线（回落用的默认模板名）").isEqualTo(RoutingModelFixture.TEMPLATE_NAME);
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
        org.mockito.Mockito.verify(productionOperationQueryService, org.mockito.Mockito.never())
                .routeSignals(TENANT);
    }

    @Test
    @DisplayName("PG-029 正常派生：两维都由库中信号命中且路线存在 ⇒ derived（键 = 想要的键）")
    void fullyDerivedKeyIsDerived() {
        stubSignals();
        stubRoutings();
        AtomicReference<ProcessingOrder> po = stubGenerate(List.of(item("item-1", "布艺遮光帘A", "韩褶-布")));

        var results = service().generate(List.of("order-001"), TENANT, "u1");

        assertThat(results.get(0).isSuccess()).isTrue();
        assertThat(po.get().getRouteSource()).as("两维命中 + 路线存在 ⇒ derived").isEqualTo("derived");
        assertThat(po.get().getRouteKey()).as("P2b：route_key = **实际使用的那条路线**（新结构里 = 具名模板）")
                .isEqualTo(RoutingModelFixture.TEMPLATE_NAME);
        assertThat(po.get().getRouteRequestedKey()).as("derived 时「想走的」= 派生出来的那个键")
                .isEqualTo("布帘×韩褶");
        assertThat(logText()).as("干净派生不得打 incident（否则 incident 就是噪音，没人会看）")
                .doesNotContain(ProcessingOrderService.INCIDENT_ROUTE_DEFAULTED)
                .doesNotContain(ProcessingOrderService.INCIDENT_ROUTE_FALLBACK);
    }

    @Test
    @DisplayName("PG-030 多部位 roll-up：取最需关注的一条（default > missing_route > partial > derived）")
    void multiPositionRollsUpToMostNeedingAttention() {
        stubSignals();
        stubRoutings();
        // 部位①「韩褶-布」= 存量兜底两维命中 ⇒ derived；部位② = 显式「罗马帘」部位、库里没有模板
        // ⇒ missing_route ⇒ 后者更需要人看。
        // ⚠️ issue #4452：missing_route 只能由**显式部位**构造（部位不再从信号/商品名派生）
        // ⇒ 部位② 用列值给出，部位① 仍走存量兜底（两维都缺 ⇒ 才读信号表）。
        AtomicReference<ProcessingOrder> po = stubGenerate(List.of(
                itemWithCarriers("item-1", "布艺遮光帘A", "韩褶-布", null, null, null, null),
                itemWithCarriers("item-2", "罗马帘A", "工序甲", "罗马帘", null, null, null)));

        var results = service().generate(List.of("order-001"), TENANT, "u1");

        assertThat(results.get(0).isSuccess()).isTrue();
        assertThat(po.get().getRouteSource()).as("多部位取最需关注的一条 ⇒ missing_route 盖住 derived")
                .isEqualTo("missing_route");
        assertThat(po.get().getRouteRequestedKey())
                .as("三列必须同源取自**同一条**部位 —— 拿 A 的 source 配 B 的键就是自相矛盾")
                .isEqualTo("罗马帘×韩褶");
        assertThat(po.get().getRouteKey())
                .as("P2b：route_key = 实际使用的路线（这里 = 回落用的默认模板）").isEqualTo(RoutingModelFixture.TEMPLATE_NAME);
    }

    @Test
    @DisplayName("PG-030 多部位 roll-up：default（零信息）排最前，且 requested 仍为 null")
    void multiPositionDefaultOutranksMissingRoute() {
        stubSignals();
        stubRoutings();
        AtomicReference<ProcessingOrder> po = stubGenerate(List.of(
                itemWithCarriers("item-1", "罗马帘A", "工序甲", "罗马帘", null, null, null), // missing_route
                itemWithCarriers("item-2", "遮光成品X", "工序甲", null, null, null, null))); // default（零信息）

        var results = service().generate(List.of("order-001"), TENANT, "u1");

        assertThat(results.get(0).isSuccess()).isTrue();
        assertThat(po.get().getRouteSource())
                .as("冻结口径：default（零信息）> missing_route > partial > derived")
                .isEqualTo("default");
        assertThat(po.get().getRouteRequestedKey()).as("default 没有「想走的键」").isNull();
        assertThat(po.get().getRouteKey()).as("P2b：route_key = 实际使用的路线").isEqualTo(RoutingModelFixture.TEMPLATE_NAME);
    }

    @Test
    @DisplayName("PG-030 多部位 roll-up：default 盖住 partial（两条都「有问题」，但补救动作不同）")
    void multiPositionMissingRouteOutranksPartial() {
        stubSignals();
        stubRoutings();
        // 部位① componentRole=纱 ⇒ partial（只补齐一维）；部位② 两维全缺 ⇒ default
        // ⇒ 判别 default 与 partial 的**相对次序**（冻结口径：default > missing_route > partial > derived）
        AtomicReference<ProcessingOrder> po = stubGenerate(List.of(
                itemWithCarriers("item-1", "遮光纱A", "工序甲", null, null, null, null, "纱"),
                itemWithCarriers("item-2", "遮光成品X", "工序甲", null, null, null, null)));

        var results = service().generate(List.of("order-001"), TENANT, "u1");

        assertThat(results.get(0).isSuccess()).isTrue();
        assertThat(po.get().getRouteSource()).as("default（零信息）比 partial 更需关注（补救 = 填部位/工艺）")
                .isEqualTo("default");
        assertThat(po.get().getRouteRequestedKey())
                .as("roll-up 到 default ⇒ 没有「想走的键」（三列同源：不得拿 partial 那条的键）").isNull();
    }

    private String logText() {
        StringBuilder sb = new StringBuilder();
        for (ILoggingEvent event : appender.list) {
            sb.append(event.getFormattedMessage()).append('\n');
        }
        return sb.toString();
    }
}
