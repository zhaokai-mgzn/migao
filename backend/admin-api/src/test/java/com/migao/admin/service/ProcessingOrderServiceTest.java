package com.migao.admin.service;
// case_ids: PG-001, PG-002, PG-003, PG-004, PG-005, PG-006, PG-007, PG-008, PG-011, PG-018, PG-019, PG-022, PG-023, PG-025, UI-030

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ProcessingOrderResponse;
import com.migao.admin.dto.ProcessingOrderUpdateRequest;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.entity.ProcessingItem;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.entity.ProcessingPositionOperation;
import com.migao.admin.entity.ProductionOptionFactor;
import com.migao.admin.entity.ProductionOptionRouting;
import com.migao.admin.entity.ProductionRouteSignal;
import com.migao.admin.entity.ProductionWorkLog;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProcessingItemMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import com.migao.admin.mapper.ProcessingPositionOperationMapper;
import com.migao.admin.mapper.ProductionWorkLogMapper;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.Spy;
import org.mockito.junit.jupiter.MockitoExtension;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;
import static org.mockito.Mockito.doThrow;

/**
 * 加工单服务单元测试（issue #3340）
 * 覆盖：生成（快照五要素 + options + 无销售价）、幂等、状态机、取消联动、租户隔离。
 */
@ExtendWith(MockitoExtension.class)
class ProcessingOrderServiceTest {

    private static final Long TENANT = 1L;

    @InjectMocks
    private ProcessingOrderService processingOrderService;

    @Mock
    private ProcessingOrderMapper processingOrderMapper;

    @Mock
    private OrderMapper orderMapper;

    @Mock
    private OrderItemMapper orderItemMapper;

    @Mock
    private ProcessingItemMapper processingItemMapper;

    @Mock
    private OrderService orderService;

    @Mock
    private ProductionService productionService;

    /** issue #4116 全链路用例（生成 → 实例化）用：真实 ProductionService 的 DB 层依赖 */
    @Mock
    private ProcessingPositionOperationMapper positionOperationMapper;

    @Mock
    private ProductionWorkLogMapper workLogMapper;

    /** 报工幂等键服务（issue #4116 §5-1）：本用例只走实例化、不触发报工 ⇒ 只需一个可用桩 */
    @Mock
    private ClientRequestIdService clientRequestIdService;

    /** 工序来源（issue #4116 切库）：生成加工单必须能读到工序库，故每个生成用例都要打桩 */
    @Mock
    private ProductionOperationQueryService productionOperationQueryService;

    /** 应做数量来源（issue #4208 接线）：算料引擎在 ai-agent，Java 只问不猜 */
    @Mock
    private ProductionOperationQtyClient productionOperationQtyClient;

    @Spy
    private ObjectMapper objectMapper = new ObjectMapper();

    // ── 工序库（V54 种子）桩 ─────────────────────────────────────────
    //
    // 切库后（issue #4116 用户裁定）工序来源 = production_routings + production_operations
    // ⇒ 生成加工单必须先能读到库。下列常量**逐字抄自 V54__seed_production_operations.sql**
    // （rt-v54-01 / rt-v54-02 的工序序列 + 对应工序行的分组/单位/单价/is_must_finish/is_start_marker），
    // 所以「实例 = 库」的断言是真比对，而不是拿一份平行真值自证。
    // 列序：工序 / 分组 / 单位 / 单价 / is_must_finish / is_start_marker

    /** rt-v54-01 布帘×韩褶 —— 11 道（行业 ERP 实证走线）。 */
    private static final String[][] V54_BULIAN_HANZHE = {
            {"精裁-布", "裁剪", "米", "0.4", "false", "true"},
            {"布三边", "车位", "米", "0.4", "false", "false"},
            {"韩褶-布", "车位", "折", "0.4", "false", "false"},
            {"上车布-布", "车位", "米", "0.5", "false", "false"},
            {"熨烫-布", "后道", "米", "0.35", "false", "false"},
            {"定型-布", "后道", "米", "0.4", "false", "false"},
            {"复烫-布", "后道", "米", "0.35", "false", "false"},
            {"布帘车被", "后道", "米", "0.4", "false", "false"},
            {"外帘打卷", "后道", "套", "1.0", "false", "false"},
            {"外帘装袋", "后道", "套", "1.0", "true", "false"},
            {"外帘发货", "后道", "套", "1.0", "false", "false"}};

    /** rt-v54-02 布帘×打孔 —— 10 道。 */
    private static final String[][] V54_BULIAN_DAKONG = {
            {"精裁-布", "裁剪", "米", "0.4", "false", "true"},
            {"布三边", "车位", "米", "0.4", "false", "false"},
            {"打孔-布", "车位", "孔", "0.15", "false", "false"},
            {"熨烫-布", "后道", "米", "0.35", "false", "false"},
            {"定型-布", "后道", "米", "0.4", "false", "false"},
            {"复烫-布", "后道", "米", "0.35", "false", "false"},
            {"布帘车被", "后道", "米", "0.4", "false", "false"},
            {"外帘打卷", "后道", "套", "1.0", "false", "false"},
            {"外帘装袋", "后道", "套", "1.0", "true", "false"},
            {"外帘发货", "后道", "套", "1.0", "false", "false"}};

    /**
     * rt-v58-01 纱帘×打孔 —— 6 道（V58 种子逐字）。与布帘路线**一道工序都不重合**
     * ⇒ 「纱帘订单不得拿到布帘工序」这条判据（issue #4354 判据 A）的判别物。
     */
    private static final String[][] V58_SHALU_DAKONG = {
            {"精裁-纱", "裁剪", "米", "0.4", "false", "true"},
            {"纱三边", "车位", "米", "0.4", "false", "false"},
            {"打孔-纱", "车位", "孔", "0.15", "false", "false"},
            {"外帘打卷", "后道", "套", "1.0", "false", "false"},
            {"外帘装袋", "后道", "套", "1.0", "true", "false"},
            {"外帘发货", "后道", "套", "1.0", "false", "false"}};

    /**
     * 信号映射表桩（V60，issue #4308）：**逐行抄自 V60 迁移的种子** ——
     * 而 V60 的种子又是迁移前两张常量表（`CURTAIN_TYPE_KEYWORDS` / `CRAFT_KEYWORDS`）的逐条快照。
     *
     * <p>⇒ 本文件里「派生键命中」的断言**逐字未改**却仍然绿，就是「派生读库 ≡ 派生读常量」的
     * 等价性证据（这是最强形态的红证：把 {@code processingOrderService} 改回读常量，
     * 本桩就再也影响不了结果 ⇒ 判别物是「库里有、常量里没有」的一行，见
     * {@link #routeSignals}）。</p>
     *
     * <p>{@code priority} 是**用途内**序（帘种行 1..3 / 工艺行 1..7），故「帘头」两行位次相反 ——
     * 这正是不能压成 `(tenant_id, signal)` 单唯一键的原因（见 V60 迁移注释）。</p>
     *
     * <p><b>V63 修正（issue #4362 阶段 1 ②）</b>：{@code 四爪钩 / 四叉钩} 指向**主线工艺** {@code 韩褶}
     * （它们是加工项不是工艺，见 V63 迁移注释）⇒ 桩 = 库的**终态**（V60 种子 + V63 UPDATE）。</p>
     */
    private static List<ProductionRouteSignal> v60Signals() {
        return List.of(
                routeSignal("sig-v60-01", "帘头", "帘头", null, 1),
                routeSignal("sig-v60-02", "纱", "纱帘", null, 2),
                routeSignal("sig-v60-03", "布", "布帘", null, 3),
                routeSignal("sig-v60-04", "韩褶", null, "韩褶", 1),
                routeSignal("sig-v60-05", "打孔", null, "打孔", 2),
                routeSignal("sig-v60-06", "四爪钩", null, "韩褶", 3),
                routeSignal("sig-v60-07", "四叉钩", null, "韩褶", 4),
                routeSignal("sig-v60-08", "穿杆", null, "穿杆", 5),
                routeSignal("sig-v60-09", "平幔", null, "平幔", 6),
                routeSignal("sig-v60-10", "帘头", null, "平幔", 7));
    }

    private static ProductionRouteSignal routeSignal(String id, String signal, String curtainType,
                                                     String craft, int priority) {
        return ProductionRouteSignal.builder().id(id).tenantId(TENANT).signal(signal)
                .curtainType(curtainType).craft(craft).priority(priority)
                .status("active").deleted(0).build();
    }

    /**
     * 工序库桩：把 V54 的两条路线装进 findRouting；未登记的键返回 null
     * （= 库里没有该路线 ⇒ 走默认路线兜底，仍没有才 fail-closed）。
     *
     * <p>同时装信号映射表（V60，issue #4308）：派生**读库而非读常量** ⇒
     * 「库中映射命中的优先级高于默认」这条判据依赖本桩，缺了它所有派生用例都退化成 T1。</p>
     */
    private void stubLibrary() {
        when(productionOperationQueryService.findRouting(eq(TENANT), anyString(), anyString()))
                .thenAnswer(inv -> v54Route(inv.getArgument(1), inv.getArgument(2)));
        // lenient：**直读**路径（订单带 curtainType + craft，issue #4354）根本不查信号映射表
        // ⇒ 该桩备而不用；Mockito 严格桩会把「备而不用」判为失败 —— 那是噪音，不是缺陷。
        lenient().when(productionOperationQueryService.routeSignals(TENANT)).thenReturn(v60Signals());
    }

    /** V54 库路线的形态（与 ProductionOperationQueryService.findRouting 的返回同构）。 */
    private static Map<String, Object> v54Route(String curtainType, String craft) {
        String[][] steps = switch (curtainType + "×" + craft) {
            case "布帘×韩褶" -> V54_BULIAN_HANZHE;
            case "布帘×打孔" -> V54_BULIAN_DAKONG;
            case "纱帘×打孔" -> V58_SHALU_DAKONG;
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

    /** 空库桩（V54 种子未执行 / 全软删）：findRouting 恒 null，routingKeys 为空。 */
    private void stubEmptyLibrary() {
        when(productionOperationQueryService.findRouting(eq(TENANT), anyString(), anyString())).thenReturn(null);
        when(productionOperationQueryService.routingKeys(TENANT)).thenReturn(List.of());
    }

    // ── 算料数量桩（issue #4208 接线）────────────────────────────────
    //
    // 应做数量的真值源在 ai-agent（routing.py::_qty_for），Java 侧只问不猜。本桩按**工序单位**
    // 给出与端点同口径的取值（数量来自算料键 + 来源三态 + 缺键兜底 1）：
    //   米 ⇒ 12.3 / fabric_meters ｜ 折 ⇒ 24 / pleat_count ｜ 孔 ⇒ 73.8 / fabric_meters_x6
    //   幅・套・个 ⇒ 1 / fallback（引擎暂未产出 panels/set_count，见 routing.py 的待补键注释）
    // 于是「实例 qty = 客户端输出」是真比对，而不是拿一份平行真值自证。

    private static final String CALC_FABRIC_METERS = "12.3";
    private static final String CALC_PLEAT_COUNT = "24.0";
    private static final String CALC_HOLES_ESTIMATE = "73.8";

    private void stubQty() {
        // lenient：并非每个用例都会走到算料问数（如空库 fail-closed 在它之前中止），
        // 而 Mockito 严格桩会把「备而不用」判为失败 —— 那是噪音，不是缺陷。
        lenient().when(productionOperationQtyClient.resolve(any())).thenAnswer(inv -> {
            List<Map<String, Object>> request = inv.getArgument(0);
            List<ProductionOperationQtyClient.PositionQty> resolved = new ArrayList<>();
            for (Map<String, Object> position : request) {
                Map<String, BigDecimal> qty = new LinkedHashMap<>();
                Map<String, String> source = new LinkedHashMap<>();
                for (Object raw : (List<?>) position.get("operations")) {
                    String operation = String.valueOf(raw);
                    String unit = unitOfOperation(operation);
                    if ("米".equals(unit)) {
                        qty.put(operation, new BigDecimal(CALC_FABRIC_METERS));
                        source.put(operation, "fabric_meters");
                    } else if ("折".equals(unit)) {
                        qty.put(operation, new BigDecimal(CALC_PLEAT_COUNT));
                        source.put(operation, "pleat_count");
                    } else if ("孔".equals(unit)) {
                        qty.put(operation, new BigDecimal(CALC_HOLES_ESTIMATE));
                        source.put(operation, "fabric_meters_x6");
                    } else {
                        qty.put(operation, BigDecimal.ONE);
                        source.put(operation, "fallback");
                    }
                }
                resolved.add(new ProductionOperationQtyClient.PositionQty(
                        (String) position.get("position_name"), qty, source));
            }
            return resolved;
        });
    }

    /** 工序 → 单位（查 V54/V58 三条路线表；未知工序返回 null ⇒ 走兜底档）。 */
    private static String unitOfOperation(String operation) {
        for (String[][] table : List.of(V54_BULIAN_HANZHE, V54_BULIAN_DAKONG, V58_SHALU_DAKONG)) {
            for (String[] row : table) {
                if (row[0].equals(operation)) {
                    return row[2];
                }
            }
        }
        return null;
    }

    /** 捕获「实例 qty 来自算料引擎而非订单数量」的夹具：订单数量 = 2（≠ 算料输出）。 */
    private static final String ORDER_QUANTITY = "2";

    // ── 特殊选项桩（issue #4230）──────────────────────────────────
    //
    // 两张表的种子与 ai-agent routing.py 的 SPECIAL_OPTION_ROUTINGS / OPTION_FACTOR_SCOPES
    // 逐字同源（V59 迁移 / bootstrap / 真值源的三源相等由 ProductionOptionRoutingMigrationTest 守），
    // 这里只放本文件断言用到的那几行。

    /** 条件工序元数据（= 工序库 production_operations 的库口径；本文件只桩断言用到的那几道）。 */
    private static Map<String, Object> operationMeta(String group, String unit, String unitPrice) {
        Map<String, Object> meta = new LinkedHashMap<>();
        meta.put("group", group);
        meta.put("unit", unit);
        meta.put("unit_price", new BigDecimal(unitPrice));
        meta.put("is_must_finish", false);
        meta.put("is_start_marker", false);
        return meta;
    }

    private static ProductionOptionRouting optionRouting(String option, String operation, String after, int sort) {
        return ProductionOptionRouting.builder().id("opt-rt-" + sort).tenantId(TENANT)
                .optionName(option).operationName(operation).afterOperation(after)
                .sortOrder(sort).status("active").deleted(0).build();
    }

    private static ProductionOptionFactor optionFactor(String option, String operation, String factor) {
        return ProductionOptionFactor.builder().id("opt-fa-1").tenantId(TENANT)
                .optionName(option).operationName(operation).factor(new BigDecimal(factor))
                .source("实证").deleted(0).build();
    }

    /**
     * 两张特殊选项表 + 条件工序元数据的桩（逐字对齐 V59 种子里本文件用到的那几行）。
     * 只桩「拼1次 / 加花边 / 余料做帘头 / 一分为二」四行 —— 断言不依赖未桩的行。
     */
    private void stubOptionTables() {
        // lenient：只有**带特殊选项**的用例才会走到 operationsByName（条件工序元数据），
        // 严格桩会把「备而不用」判为失败 —— 那是噪音，不是缺陷。
        lenient().when(productionOperationQueryService.optionRoutings(TENANT)).thenReturn(List.of(
                optionRouting("拼1次", "拼1次-布", "布三边", 1),
                optionRouting("加花边", "花边-布", "布三边", 4),
                optionRouting("余料做帘头", "帘头制作", "布三边", 10)));
        lenient().when(productionOperationQueryService.optionFactors(TENANT)).thenReturn(List.of(
                optionFactor("一分为二", null, "1.7")));
        Map<String, Map<String, Object>> catalog = new LinkedHashMap<>();
        catalog.put("拼1次-布", operationMeta("车位", "幅", "0.8"));
        catalog.put("花边-布", operationMeta("车位", "米", "0.6"));
        catalog.put("帘头制作", operationMeta("车位", "个", "2.0"));
        lenient().when(productionOperationQueryService.operationsByName(TENANT)).thenReturn(catalog);
    }

    /** 带特殊选项的订单明细（布帘×韩褶路线，与 orderItemHanzhe 同源，只多 specialOptions）。 */
    @SuppressWarnings("unchecked")
    private OrderItem orderItemHanzheWithOptions(String colorName, List<String> specialOptions) {
        OrderItem item = orderItemHanzhe(colorName);
        ((Map<String, Object>) item.getProcessingInfo()).put("specialOptions", specialOptions);
        return item;
    }

    /** 「生成加工单 → 真链路实例化」的装配：真实 ProductionService + 真实 ProcessingOrderService。 */
    private ProcessingOrderService realChainService() {
        return new ProcessingOrderService(
                processingOrderMapper, orderMapper, orderItemMapper, processingItemMapper,
                orderService, objectMapper,
                new ProductionService(processingOrderMapper, positionOperationMapper, workLogMapper, orderMapper,
                        clientRequestIdService),
                productionOperationQueryService, productionOperationQtyClient);
    }

    /** 生成前置桩（订单 + 明细 + 无既有加工单 + 插入回填主键），三条 #4116 链路用例共用。 */
    private void stubGenerate(List<OrderItem> items) {
        when(orderMapper.selectById("order-001")).thenReturn(confirmedOrder);
        when(orderItemMapper.selectList(any())).thenReturn(items);
        java.util.concurrent.atomic.AtomicReference<ProcessingOrder> poRef =
                new java.util.concurrent.atomic.AtomicReference<>();
        when(processingOrderMapper.selectActiveByOrderId("order-001", TENANT)).thenAnswer(inv -> poRef.get());
        when(processingOrderMapper.insert(any(ProcessingOrder.class))).thenAnswer(inv -> {
            ProcessingOrder inserted = inv.getArgument(0);
            inserted.setId("po-001");
            poRef.set(inserted);
            return 1;
        });
    }

    private Order confirmedOrder;

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(TENANT);
        // 应做数量（issue #4208）：所有生成路径都要问算料引擎 ⇒ 默认打桩（lenient，见 stubQty）
        stubQty();
        MybatisConfiguration conf = new MybatisConfiguration();
        MapperBuilderAssistant assistant = new MapperBuilderAssistant(conf, "");
        TableInfoHelper.initTableInfo(assistant, Order.class);
        TableInfoHelper.initTableInfo(assistant, ProcessingOrder.class);

        confirmedOrder = Order.builder()
                .id("order-001")
                .tenantId(TENANT)
                .orderNo("ORD-20260912-0001")
                .status("confirmed")
                .customerName("张三")
                .customerPhone("13800138000")
                .build();
    }

    // ── 快照构建工具 ──────────────────────────────────────────────

    @SuppressWarnings("unchecked")
    private Map<String, Object> processingInfo(String colorName) {
        Map<String, Object> info = new LinkedHashMap<>();
        info.put("processingFee", 6.0);
        info.put("colorName", colorName);
        info.put("sellingMethod", "散剪");
        info.put("doorWidth", "2.8米");
        // 注意（issue #4299）：加工项**不带** pricingMethod ⇒ 米数映射判据不命中（也不得回落到
        // sellingMethod）⇒ 本夹具的期望值不受判据更换影响；要断言命中请看 PG-025 的用例。
        List<Map<String, Object>> procs = new ArrayList<>();
        Map<String, Object> p = new LinkedHashMap<>();
        p.put("id", "p1");
        p.put("name", "打孔");
        p.put("unitPrice", 3.0);
        p.put("quantity", 2);
        p.put("unit", "米");
        procs.add(p);
        info.put("processingItems", procs);
        return info;
    }

    private OrderItem orderItemWithProcessing(String colorName) {
        return OrderItem.builder()
                .id("item-1")
                .tenantId(TENANT)
                .orderId("order-001")
                .productName("布艺遮光帘A")
                .quantity(BigDecimal.valueOf(2))
                .width(new BigDecimal("2.5"))
                .height(new BigDecimal("2.8"))
                .processingInfo(processingInfo(colorName))
                .build();
    }

    private OrderItem orderItemWithoutProcessing() {
        return OrderItem.builder()
                .id("item-2")
                .tenantId(TENANT)
                .orderId("order-001")
                .productName("现货成品")
                .quantity(BigDecimal.valueOf(1))
                .processingInfo(new HashMap<String, Object>())
                .build();
    }

    // ── 切库用例的订单明细（部位/工艺信号各不同）──────────────────────

    /** 布帘·韩褶订单：加工项名「韩褶-布」= 部位(布帘)×工艺(韩褶) 两个信号都在。 */
    private OrderItem orderItemHanzhe(String colorName) {
        return processedItem("item-1", "布艺遮光帘A", colorName, List.of(
                Map.of("id", "p1", "name", "韩褶-布", "unitPrice", 3.0, "quantity", 2, "unit", "折")));
    }

    /** 同上，但加工项目录里多一个**库里不存在**的自定义加工项（切库负例①的判别物）。 */
    private OrderItem orderItemHanzheWithCustomProcessingItem(String colorName) {
        return processedItem("item-1", "布艺遮光帘A", colorName, List.of(
                Map.of("id", "p1", "name", "韩褶-布", "unitPrice", 3.0, "quantity", 2, "unit", "折"),
                Map.of("id", "p2", "name", "加工项目录自定义项", "unitPrice", 9.0, "quantity", 2, "unit", "米")));
    }

    /** 帘头订单：派生键 帘头×平幔 —— V54 里有这条路线（rt-v54-06），但本用例桩里**没有**它 ⇒ 验默认路线回落。 */
    private OrderItem orderItemLiTou(String colorName) {
        return processedItem("item-1", "布艺帘头A", colorName, List.of(
                Map.of("id", "p3", "name", "帘头制作", "unitPrice", 2.0, "quantity", 1, "unit", "个")));
    }

    /** 无任何派生信号（加工项名/商品名/销售方式都不含 部位/工艺 关键字）⇒ 全落默认。 */
    private OrderItem orderItemWithoutRouteSignal() {
        Map<String, Object> info = new LinkedHashMap<>();
        info.put("colorName", "米白");
        info.put("sellingMethod", "散剪");
        info.put("processingItems", List.of(Map.of("id", "p9", "name", "工序甲", "unit", "米")));
        return OrderItem.builder()
                .id("item-1").tenantId(TENANT).orderId("order-001")
                .productName("遮光成品X").quantity(BigDecimal.valueOf(2))
                .processingInfo(info).build();
    }

    private OrderItem processedItem(String itemId, String productName, String colorName,
                                    List<Map<String, Object>> procs) {
        Map<String, Object> info = new LinkedHashMap<>();
        info.put("processingFee", 6.0);
        info.put("colorName", colorName);
        info.put("sellingMethod", "散剪");   // 真库取值（售卖方式，**不是**米数判据字段，见 #4299）
        info.put("doorWidth", "2.8米");
        info.put("processingItems", new ArrayList<>(procs));
        return OrderItem.builder()
                .id(itemId).tenantId(TENANT).orderId("order-001")
                .productName(productName).quantity(BigDecimal.valueOf(2))
                .width(new BigDecimal("2.5")).height(new BigDecimal("2.8"))
                .processingInfo(info).build();
    }

    // ── craft spec 消费（issue #4354 / 设计文档 §4.7 直读优先 · §4.8 craftLineId 分组 · §4.9 快照白名单）──
    //
    // 订单侧自包 1（#4346）起把工艺规格落在 `processing_info` **顶层**；此前 Java 侧**不读**它们，
    // 部位/工艺只能靠加工项名关键字**猜**（实证 V58：纱帘订单拿到布帘的 11 道工序，工序与工资全错）。
    // 下面这批夹具/用例即「把猜换成读」的判据。

    /** craft spec / 算料输出的键值对（保序；`k1, v1, k2, v2 …`）。 */
    private static Map<String, Object> spec(Object... keyValues) {
        Map<String, Object> spec = new LinkedHashMap<>();
        for (int i = 0; i + 1 < keyValues.length; i += 2) {
            spec.put(String.valueOf(keyValues[i]), keyValues[i + 1]);
        }
        return spec;
    }

    /** 同 {@link #processedItem}，另在 `processing_info` **顶层**补 craft spec / 算料输出键。 */
    @SuppressWarnings("unchecked")
    private OrderItem processedItemWithSpec(String itemId, String productName, String colorName,
                                            List<Map<String, Object>> procs, Map<String, Object> spec) {
        OrderItem item = processedItem(itemId, productName, colorName, procs);
        ((Map<String, Object>) item.getProcessingInfo()).putAll(spec);
        return item;
    }

    /**
     * 纱帘·打孔订单（**带 craft spec**）：加工项名「韩褶-布」把**派生**指向 布帘×韩褶（11 道），
     * 而 craft spec 直读 = 纱帘×打孔（6 道）—— 两条路线**一道工序都不重合**
     * ⇒ 「直读优先」只有直读真生效时才绿（这正是 V58 实证的错配形态）。
     */
    private OrderItem orderItemShaluDakongWithSpec(String colorName) {
        return processedItemWithSpec("item-1", "布艺遮光帘A", colorName,
                List.of(Map.of("id", "p1", "name", "韩褶-布", "unitPrice", 3.0, "quantity", 2, "unit", "折")),
                spec("curtainType", "纱帘", "craft", "打孔"));
    }

    /** 布帘·韩褶 + `isShaped=false`（判据 C：定型接线）。 */
    private OrderItem orderItemHanzheUnshaped(String colorName) {
        return processedItemWithSpec("item-1", "布艺遮光帘A", colorName,
                List.of(Map.of("id", "p1", "name", "韩褶-布", "unitPrice", 3.0, "quantity", 2, "unit", "折")),
                spec("curtainType", "布帘", "craft", "韩褶", "isShaped", false));
    }

    /** 同上，但 `isShaped` 是**脏数据**（字符串 "false"）⇒ 必须按「不是布尔 false」处理（与 Python `is False` 同款）。 */
    private OrderItem orderItemHanzheWithStringIsShaped(String colorName) {
        return processedItemWithSpec("item-1", "布艺遮光帘A", colorName,
                List.of(Map.of("id", "p1", "name", "韩褶-布", "unitPrice", 3.0, "quantity", 2, "unit", "折")),
                spec("curtainType", "布帘", "craft", "韩褶", "isShaped", "false"));
    }

    /** craft spec 键**存在但空白**（脏数据形态）⇒ 必须视为**缺键**，不得当成值。 */
    private OrderItem orderItemHanzheWithBlankSpec(String colorName) {
        return processedItemWithSpec("item-1", "布艺遮光帘A", colorName,
                List.of(Map.of("id", "p1", "name", "韩褶-布", "unitPrice", 3.0, "quantity", 2, "unit", "折")),
                spec("curtainType", "   ", "craft", ""));
    }

    /** 订单侧**已落库**算料输出（§4.3）—— 米/折两个主键 + 本包新增白名单的三个键。 */
    private OrderItem orderItemHanzheWithCalcOutput(String colorName) {
        return processedItemWithSpec("item-1", "布艺遮光帘A", colorName,
                List.of(Map.of("id", "p1", "name", "韩褶-布", "unitPrice", 3.0, "quantity", 2, "unit", "折")),
                spec("fabric_meters", new BigDecimal("12.3"), "pleat_count", 24,
                        "per_panel_pleats", 12, "fullness", new BigDecimal("2.0"),
                        "fullness_actual", new BigDecimal("1.95")));
    }

    /** craft spec **全键**（§4.2 的 11 键 + §4.8 的 3 键 + processingMeters）+ §4.3 算料输出 7 键。 */
    private OrderItem orderItemWithFullCraftSpec(String colorName) {
        return processedItemWithSpec("item-1", "布艺遮光帘A", colorName,
                List.of(Map.of("id", "p1", "name", "打孔-纱", "unitPrice", 3.0, "quantity", 2, "unit", "孔")),
                spec("curtainType", "纱帘", "craft", "打孔", "cuttingMode", "定高买宽", "openCount", 2,
                        "isShaped", false, "pleatSpacing", new BigDecimal("0.1"),
                        "hasPattern", true, "patternRepeat", new BigDecimal("0.6"),
                        "style", "拼色", "room", "客厅", "batchNo", "B-20260918",
                        "componentRole", "主布", "craftLineId", "item-1",
                        "metersSource", "跟随主布", "processingMeters", new BigDecimal("12.3"),
                        "fabric_meters", new BigDecimal("12.3"), "pleat_count", 24,
                        "per_panel_pleats", 12, "panels", 4, "holes", 73.8,
                        "fullness", new BigDecimal("2.0"), "fullness_actual", new BigDecimal("1.95")));
    }

    /** 无 craft spec / 无算料输出的行（判别「缺键就缺，不造值」）。 */
    private OrderItem orderItemWithoutCraftSpec() {
        return processedItemWithSpec("item-2", "遮光成品Y", "米白",
                List.of(Map.of("id", "p9", "name", "工序甲", "unitPrice", 1.0, "quantity", 1, "unit", "米")),
                Map.of());
    }

    /**
     * 拼色一扇窗（判据 G）：主布行（item-1，带工艺规格 + 加工项）+ 配布边行（item-2，**同 craftLineId**）。
     *
     * <p>配布边行也带加工项 —— 这正是「一扇窗被算成两扇」的形态：部位数 / 工序 / 计件全部翻倍。
     * 两行同 `craftLineId` ⇒ 消费端必须合并为一个部位。</p>
     */
    private List<OrderItem> colorBlockWindow() {
        OrderItem main = processedItemWithSpec("item-1", "布艺遮光帘A", "米白",
                List.of(Map.of("id", "p1", "name", "韩褶-布", "unitPrice", 3.0, "quantity", 2, "unit", "折")),
                spec("curtainType", "布帘", "craft", "韩褶", "style", "拼色",
                        "componentRole", "主布", "craftLineId", "item-1"));
        OrderItem edge = processedItemWithSpec("item-2", "配布边", "米白",
                List.of(Map.of("id", "p2", "name", "韩褶-布", "unitPrice", 3.0, "quantity", 2, "unit", "折")),
                spec("style", "拼色", "componentRole", "配布边", "craftLineId", "item-1"));
        return List.of(main, edge);
    }

    /**
     * 同上，但主布行**自身不带** `craftLineId`，只有配布边行填「主布行的行标识」
     * （= order_create 工具描述教的形态）⇒ 组键必须能由「本行 itemId」与「别行的 craftLineId」对齐。
     */
    private List<OrderItem> colorBlockWindowBoundByMainRowId() {
        OrderItem main = processedItemWithSpec("item-1", "布艺遮光帘A", "米白",
                List.of(Map.of("id", "p1", "name", "韩褶-布", "unitPrice", 3.0, "quantity", 2, "unit", "折")),
                spec("curtainType", "布帘", "craft", "韩褶", "style", "拼色", "componentRole", "主布"));
        OrderItem edge = processedItemWithSpec("item-2", "配布边", "米白",
                List.of(Map.of("id", "p2", "name", "韩褶-布", "unitPrice", 3.0, "quantity", 2, "unit", "折")),
                spec("style", "拼色", "componentRole", "配布边", "craftLineId", "item-1"));
        return List.of(main, edge);
    }

    /** 路线表的工序名序列（断言用）。 */
    private static List<String> operationNames(String[][] table) {
        return java.util.Arrays.stream(table).map(row -> row[0]).toList();
    }

    // ── 「樘窗」跨行分组（issue #4387 判据 2/3）────────────────────────────────
    //
    // 用户裁定（2026-09-19，issue #4387）：**一行 order_items = 一个部位（帘件）**；
    // **樘窗（craftLineId 组）= 一个窗户**，是套级工序（#4384）与加工费（#4386）的归属层级。
    // ⇒ 一樘「布 + 纱」= **两条明细行、各成部位、同 craftLineId**；
    //   配布边仍**不独立成部位**（#4354 回归不变）。

    /**
     * 一樘窗 = 布行 + 纱行（**各自成部位**，同 `craftLineId` = `win-1`）。
     *
     * <p>两行的帘种/工艺**不同**（布帘×韩褶 11 道 vs 纱帘×打孔 6 道）—— 这是「各成部位」的判别物：
     * 若把一樘窗算成一个部位（或错按「一扇」吸收纱行），工序数就既不是 17 也不是两条路线的并集。</p>
     */
    private List<OrderItem> clothPlusSheerWindow() {
        OrderItem cloth = processedItemWithSpec("item-1", "布艺遮光帘A", "米白",
                List.of(Map.of("id", "p1", "name", "韩褶-布", "unitPrice", 3.0, "quantity", 2, "unit", "折")),
                spec("curtainType", "布帘", "craft", "韩褶",
                        "componentRole", "主布", "craftLineId", "win-1"));
        OrderItem sheer = processedItemWithSpec("item-2", "纱帘A", "米白",
                List.of(Map.of("id", "p2", "name", "打孔-纱", "unitPrice", 3.0, "quantity", 2, "unit", "孔")),
                spec("curtainType", "纱帘", "craft", "打孔",
                        "componentRole", "纱", "craftLineId", "win-1"));
        return List.of(cloth, sheer);
    }

    /**
     * **注入式对照**（issue #4387 判据 3 的红证形态）：与 {@link #colorBlockWindow()} 逐字相同，
     * 只把配布边行的 `componentRole` **去掉**（= 角色缺省视为主布，见 {@code isEdgeRow}）。
     *
     * <p>去掉后该行不再被吸收 ⇒ 部位数 1 → 2。**同一份夹具的两个变体分别断言 1 / 2**
     * 才是「部位数会随该键变化」的证明；只断言其中一边是空断言。</p>
     */
    private List<OrderItem> colorBlockWindowWithoutEdgeRole() {
        OrderItem main = processedItemWithSpec("item-1", "布艺遮光帘A", "米白",
                List.of(Map.of("id", "p1", "name", "韩褶-布", "unitPrice", 3.0, "quantity", 2, "unit", "折")),
                spec("curtainType", "布帘", "craft", "韩褶", "style", "拼色",
                        "componentRole", "主布", "craftLineId", "item-1"));
        OrderItem edgeWithoutRole = processedItemWithSpec("item-2", "配布边", "米白",
                List.of(Map.of("id", "p2", "name", "韩褶-布", "unitPrice", 3.0, "quantity", 2, "unit", "折")),
                spec("style", "拼色", "craftLineId", "item-1"));
        return List.of(main, edgeWithoutRole);
    }

    /** 快照条目（craft spec 全键 + 算料输出），供详情响应用例直接喂 `items_snapshot`。 */
    private static Map<String, Object> craftSpecSnapshotEntry() {
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("itemId", "item-1");
        entry.put("productName", "布艺遮光帘A");
        entry.put("colorName", "米白");
        entry.putAll(spec("curtainType", "纱帘", "craft", "打孔", "cuttingMode", "定高买宽",
                "openCount", 2, "isShaped", false, "pleatSpacing", new BigDecimal("0.1"),
                "hasPattern", true, "patternRepeat", new BigDecimal("0.6"), "style", "拼色",
                "batchNo", "B-20260918", "componentRole", "主布", "craftLineId", "item-1",
                "metersSource", "跟随主布", "processingMeters", new BigDecimal("12.3"),
                "fabric_meters", new BigDecimal("12.3"), "pleat_count", 24, "per_panel_pleats", 12,
                "panels", 4, "holes", 73.8, "fullness", new BigDecimal("2.0"),
                "fullness_actual", new BigDecimal("1.95")));
        entry.put("processingItems", List.of(Map.of("id", "p1", "name", "打孔-纱")));
        return entry;
    }

    /** 脏数据：加工项缺名称（#4116 的防御分支——不得因脏数据阻断加工单生成） */
    private OrderItem orderItemWithNamelessProcessing() {
        Map<String, Object> info = new LinkedHashMap<>();
        List<Map<String, Object>> procs = new ArrayList<>();
        Map<String, Object> p = new LinkedHashMap<>();
        p.put("id", "p9");
        p.put("unit", "米");
        p.put("quantity", 1);
        procs.add(p);
        info.put("processingItems", procs);
        return OrderItem.builder()
                .id("item-9")
                .tenantId(TENANT)
                .orderId("order-001")
                .productName("布艺遮光帘B")
                .quantity(BigDecimal.valueOf(1))
                .processingInfo(info)
                .build();
    }

    private ProcessingOrder po(String id, String status) {
        return ProcessingOrder.builder()
                .id(id)
                .tenantId(TENANT)
                .orderId("order-001")
                .processingOrderNo("JG-20260912-0001")
                .status(status)
                .itemsSnapshot(buildSnapshotPayload())
                .build();
    }

    private List<Map<String, Object>> buildSnapshotPayload() {
        List<Map<String, Object>> snapshot = new ArrayList<>();
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("productName", "布艺遮光帘A");
        entry.put("quantity", 2);
        entry.put("colorName", "米白");
        List<Map<String, Object>> procs = new ArrayList<>();
        Map<String, Object> p = new LinkedHashMap<>();
        p.put("id", "p1");
        p.put("name", "打孔");
        procs.add(p);
        entry.put("processingItems", procs);
        snapshot.add(entry);
        return snapshot;
    }

    // ── PG-001 生成成功 ────────────────────────────────────────────

    @Test
    @DisplayName("PG-001 已确认含加工项订单 → 生成加工单（**不**联动订单，订单仍 confirmed；#4305）")
    void generateSuccess() {
        stubLibrary();
        when(orderMapper.selectById("order-001")).thenReturn(confirmedOrder);
        when(orderItemMapper.selectList(any()))
                .thenReturn(List.of(orderItemWithProcessing("米白")));
        when(processingOrderMapper.selectActiveByOrderId("order-001", TENANT)).thenReturn(null);
        ProcessingItem pi = ProcessingItem.builder().id("p1").name("打孔").unit("米").options(List.of("四爪钩")).build();
        when(processingItemMapper.selectById("p1")).thenReturn(pi);
        when(processingOrderMapper.insert(any(ProcessingOrder.class))).thenReturn(1);

        var results = processingOrderService.generate(List.of("order-001"), TENANT, "u1");

        assertThat(results).hasSize(1);
        assertThat(results.get(0).isSuccess()).isTrue();
        assertThat(results.get(0).getProcessingOrderNo()).startsWith("JG-");

        ArgumentCaptor<ProcessingOrder> captor = ArgumentCaptor.forClass(ProcessingOrder.class);
        verify(processingOrderMapper).insert(captor.capture());
        ProcessingOrder inserted = captor.getValue();
        assertThat(inserted.getStatus()).isEqualTo("generated");
        assertThat(inserted.getTenantId()).isEqualTo(TENANT);
        assertThat(inserted.getOrderId()).isEqualTo("order-001");
        assertThat(inserted.getTemplateVersion()).isEqualTo(1);

        // 快照五要素 + options + 无销售价
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> snapshot = (List<Map<String, Object>>) inserted.getItemsSnapshot();
        assertThat(snapshot).hasSize(1);
        Map<String, Object> entry = snapshot.get(0);
        assertThat(entry.get("productName")).isEqualTo("布艺遮光帘A");
        assertThat(entry.get("colorName")).isEqualTo("米白");
        assertThat(entry.get("sellingMethod")).isEqualTo("散剪");
        assertThat(entry.get("doorWidth")).isEqualTo("2.8米");
        assertThat(entry).doesNotContainKey("price");
        assertThat(entry).doesNotContainKey("salesPrice");
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> procs = (List<Map<String, Object>>) entry.get("processingItems");
        assertThat(procs).hasSize(1);
        assertThat(procs.get(0).get("options")).isEqualTo(List.of("四爪钩"));

        // 订单联动（issue #4305，用户裁定「发加工 = 订单进入生产中」）：**生成不再推进订单** ——
        // 时点已挪到发加工（见 updateStatusMainChain 的 issue 分支断言）。
        // 红证：修复前这里调用 orderService.updateOrderStatus(orderId, "producing") ⇒ 本断言必红。
        verify(orderService, never()).updateOrderStatus(anyString(), anyString());
        verify(orderService, never()).revertProducingToConfirmed(anyString(), anyString());
    }

    // ── issue #4116（P0 断链第一环）：生成加工单即实例化工序 → qr_token 非空 ──
    //
    // 病灶：POST /api/admin/production/orders/{id}/instantiate 全仓零调用者 ⇒
    // processing_position_operations 恒空 ⇒ qr_token 恒 null ⇒ 任务卡只出「二维码待生成」占位
    // ⇒ 工人扫码报工不可达。修法：加工单落行后自动实例化（本用例的断言即端到端判据）。
    //
    // ── issue #4116「切库」第二半（用户裁定「现在就切」）──
    // 工序来源从**加工项目录**改为**工序库**（production_routings + production_operations）。
    // 下列用例即该切换的判据：① 实例与库逐条一致（负例 R2）；② 库取不到 ⇒ 显式失败且不回退
    // 加工项目录、不落半成品；③ is_must_finish 读库（末道「外帘发货」在库里是 false）。
    // 三条各有红证（见 PR body 的红证表：改回加工项目录 / 删库路线 / 改回末道必完 ⇒ 均必红）。

    @Test
    @DisplayName("#4116 切库 R2：布帘·韩褶订单 → 工序实例与工序库**逐条一致**（seq/工序/分组/单位/单价/必完）")
    void generateInstantiatesOperationsVerbatimFromOperationLibrary() {
        // 真实 ProductionService（只 mock DB 层 Mapper）：断言"生成→读库→实例化→token"真链路，
        // 而不是"调了一次 productionService.instantiate"（效果层，非调用层）
        ProcessingOrderService service = realChainService();
        stubLibrary();
        stubGenerate(List.of(orderItemHanzhe("米白")));
        when(processingItemMapper.selectById("p1"))
                .thenReturn(ProcessingItem.builder().id("p1").name("韩褶-布").unit("折").build());

        var results = service.generate(List.of("order-001"), TENANT, "u1");

        assertThat(results.get(0).isSuccess()).isTrue();

        // ① 工序实例 = 库路线 rt-v54-01（布帘×韩褶）**逐条**：一位不差、一行不多不少
        ArgumentCaptor<ProcessingPositionOperation> opCaptor =
                ArgumentCaptor.forClass(ProcessingPositionOperation.class);
        verify(positionOperationMapper, times(V54_BULIAN_HANZHE.length)).insert(opCaptor.capture());
        List<ProcessingPositionOperation> instances = opCaptor.getAllValues();
        assertThat(instances).extracting(ProcessingPositionOperation::getSeq)
                .containsExactly(1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11);
        for (int i = 0; i < V54_BULIAN_HANZHE.length; i++) {
            ProcessingPositionOperation instance = instances.get(i);
            String[] row = V54_BULIAN_HANZHE[i];
            String where = "第 " + (i + 1) + " 道（" + row[0] + "）";
            assertThat(instance.getOperationName()).as(where + " 工序名").isEqualTo(row[0]);
            assertThat(instance.getGroupName()).as(where + " 分组").isEqualTo(row[1]);
            assertThat(instance.getUnit()).as(where + " 单位").isEqualTo(row[2]);
            assertThat(instance.getUnitPrice()).as(where + " 单价").isEqualByComparingTo(row[3]);
            assertThat(instance.getIsMustFinish()).as(where + " 必完标记").isEqualTo(Boolean.valueOf(row[4]));
            assertThat(instance.getIsStartMarker()).as(where + " 开始标记").isEqualTo(Boolean.valueOf(row[5]));
            assertThat(instance.getPositionName()).as(where + " 部位").isEqualTo("布艺遮光帘A 米白");
            assertThat(instance.getProcessingOrderId()).isEqualTo("po-001");
            assertThat(instance.getStatus()).isEqualTo("pending");
        }
        // 必完工序**唯一** = 库里标了 is_must_finish 的「外帘装袋」（第 10 道）；
        // 末道「外帘发货」（第 11 道）在库里是 false ⇒ 这一行就是「末道必完」临时口径的反证
        assertThat(instances).filteredOn(ProcessingPositionOperation::getIsMustFinish)
                .extracting(ProcessingPositionOperation::getOperationName).containsExactly("外帘装袋");
        assertThat(instances.get(10).getOperationName()).isEqualTo("外帘发货");
        assertThat(instances.get(10).getIsMustFinish())
                .as("末道工序不得被无条件标必完（is_must_finish 读库 = false）").isFalse();

        // ② 应做数量 = **算料引擎输出**（issue #4208 接线）：米类 12.3、折类 24、套类兜底 1
        //    —— 此前取该部位订单数量（2）⇒ 11 道工序全 2.00，正是走查实测「韩褶-布 显示 3 折」的形态。
        //    本断言的红证：把 buildPositionPayload 改回 positionQty(entry) ⇒ 逐条必红（12.3 ≠ 2）。
        assertThat(instances).allSatisfy(instance -> {
            String unit = instance.getUnit();
            String expected = "折".equals(unit) ? CALC_PLEAT_COUNT : ("米".equals(unit) ? CALC_FABRIC_METERS : "1");
            assertThat(instance.getQty()).as("应做数量（%s 类）", unit).isEqualByComparingTo(expected);
        });
        assertThat(instances).allSatisfy(instance ->
                assertThat(instance.getQty()).as("绝不落 0（应做 0 ⇒ done_qty ≥ qty 恒真 ⇒ 假完工）")
                        .isNotEqualByComparingTo(BigDecimal.ZERO));
        assertThat(instances).filteredOn(instance -> "折".equals(instance.getUnit()))
                .singleElement()
                .satisfies(instance -> assertThat(instance.getQtySource()).isEqualTo("pleat_count"));
        assertThat(instances).filteredOn(instance -> "套".equals(instance.getUnit()))
                .allSatisfy(instance -> assertThat(instance.getQtySource()).isEqualTo("fallback"));
        assertThat(instances).filteredOn(instance -> "米".equals(instance.getUnit()))
                .allSatisfy(instance -> assertThat(instance.getQtySource()).isEqualTo("fabric_meters"));

        // ③ qr_token 必须真落到加工单（任务卡二维码取值来源 = qr_token，非空才不走占位分支）
        ArgumentCaptor<ProcessingOrder> tokenCaptor = ArgumentCaptor.forClass(ProcessingOrder.class);
        verify(processingOrderMapper).updateById(tokenCaptor.capture());
        assertThat(tokenCaptor.getValue().getId()).isEqualTo("po-001");
        assertThat(tokenCaptor.getValue().getQrToken()).matches("[0-9a-f]{32}");
    }

    @Test
    @DisplayName("#4116 切库负例①：取路线改回加工项目录 ⇒ 本用例必红（加工项名不再进工序实例）")
    void operationsComeFromLibraryNotFromProcessingItemCatalog() {
        // 判据形态：加工项目录里放一个**库里没有**的工序名（「加工项目录自定义项」），
        // 断言它**不得**出现在实例里；而实例的工序名必须全在库路线内。
        // 若有人把取路线改回加工项目录，本断言立即红（红证①）。
        stubLibrary();
        stubGenerate(List.of(orderItemHanzheWithCustomProcessingItem("米白")));
        when(processingItemMapper.selectById("p1"))
                .thenReturn(ProcessingItem.builder().id("p1").name("韩褶-布").unit("折").build());

        var results = realChainService().generate(List.of("order-001"), TENANT, "u1");

        assertThat(results.get(0).isSuccess()).isTrue();
        ArgumentCaptor<ProcessingPositionOperation> opCaptor =
                ArgumentCaptor.forClass(ProcessingPositionOperation.class);
        verify(positionOperationMapper, times(V54_BULIAN_HANZHE.length)).insert(opCaptor.capture());
        assertThat(opCaptor.getAllValues()).extracting(ProcessingPositionOperation::getOperationName)
                .containsExactlyElementsOf(java.util.Arrays.stream(V54_BULIAN_HANZHE).map(r -> r[0]).toList())
                .doesNotContain("加工项目录自定义项");
    }

    @Test
    @DisplayName("#4208 端到端：实例 qty = 算料引擎输出（**≠** 订单数量）—— 走查红证「韩褶-布 3 折」的反面")
    void generateTakesQtyFromCalcEngineNotFromOrderQuantity() {
        stubLibrary();
        OrderItem item = orderItemHanzhe("米白");
        // issue #4299：米数判据 = **加工项** pricingMethod（键名驼峰，两个下单入口都这么写）。
        // 此前这里写 `sellingMethod = "per_meter"` —— 该值在真库 sellingMethod 的 11 个取值里
        // **一次都没出现过**（实测分布见 acceptance/2026-09-18/4299-db-distribution/FINDINGS.md）
        // ⇒ 单测绿而真实路径不触发，正是本单要治的假绿形态。
        setProcessingItemPricingMethod(item, "per_meter");
        stubGenerate(List.of(item));
        when(processingItemMapper.selectById("p1"))
                .thenReturn(ProcessingItem.builder().id("p1").name("韩褶-布").unit("折").build());

        var results = realChainService().generate(List.of("order-001"), TENANT, "u1");
        assertThat(results.get(0).isSuccess()).isTrue();

        ArgumentCaptor<ProcessingPositionOperation> captor =
                ArgumentCaptor.forClass(ProcessingPositionOperation.class);
        verify(positionOperationMapper, times(V54_BULIAN_HANZHE.length)).insert(captor.capture());
        List<ProcessingPositionOperation> instances = captor.getAllValues();

        // 判据 5（issue #4208）：qty ≠ 订单数量，且逐值 = 算料输出
        assertThat(instances).allSatisfy(instance ->
                assertThat(instance.getQty()).as("应做数量不得等于订单数量 %s", ORDER_QUANTITY)
                        .isNotEqualByComparingTo(ORDER_QUANTITY));
        assertThat(instances.get(2).getOperationName()).isEqualTo("韩褶-布");
        assertThat(instances.get(2).getQty()).isEqualByComparingTo(CALC_PLEAT_COUNT);
        assertThat(instances.get(0).getOperationName()).isEqualTo("精裁-布");
        assertThat(instances.get(0).getQty()).isEqualByComparingTo(CALC_FABRIC_METERS);

        // 请求体里带的 calc_info 必须来自**加工项计价方式**口径（pricingMethod=per_meter ⇒ 订单行 quantity 即米数），
        // 且**不含**订单侧拿不到的待补键（panels/set_count/holes）—— 不许 Java 凭空造数
        ArgumentCaptor<List<Map<String, Object>>> reqCaptor = ArgumentCaptor.forClass(List.class);
        verify(productionOperationQtyClient).resolve(reqCaptor.capture());
        Map<String, Object> sent = reqCaptor.getValue().get(0);
        assertThat(sent.get("position_name")).isEqualTo("布艺遮光帘A 米白");
        assertThat((List<?>) sent.get("operations")).hasSize(V54_BULIAN_HANZHE.length);
        @SuppressWarnings("unchecked")
        Map<String, Object> calcInfo = (Map<String, Object>) sent.get("calc_info");
        assertThat(fabricMetersOf(calcInfo))
                .as("per_meter 的订单数量即米数（OrderItem.quantity javadoc 的计价方式口径）")
                .isEqualByComparingTo(ORDER_QUANTITY);
        assertThat(calcInfo).as("订单侧拿不到的待补键不许 Java 凭空造数")
                .doesNotContainKeys("panels", "set_count", "holes", "pleat_count");
    }

    @Test
    @DisplayName("#4208 calc_info 口径：非 per_meter 计价**不**把订单数量冒充成米数（不发明数字）")
    void calcInfoDoesNotInventFabricMetersForNonPerMeter() {
        stubLibrary();
        OrderItem item = orderItemHanzhe("米白");   // 售卖方式 = 夹具默认的真库取值「散剪」（**不是**判据字段）
        // 加工项计价方式 = per_set（非按米）⇒ 订单行 quantity（2）是樘数、不是米数。
        // 此前这里写 `sellingMethod = "per_set"` —— 同样不是真库会产生的值（见 #4299 的实测分布）。
        setProcessingItemPricingMethod(item, "per_set");
        stubGenerate(List.of(item));
        when(processingItemMapper.selectById("p1"))
                .thenReturn(ProcessingItem.builder().id("p1").name("韩褶-布").unit("折").build());

        realChainService().generate(List.of("order-001"), TENANT, "u1");

        ArgumentCaptor<List<Map<String, Object>>> reqCaptor = ArgumentCaptor.forClass(List.class);
        verify(productionOperationQtyClient).resolve(reqCaptor.capture());
        @SuppressWarnings("unchecked")
        Map<String, Object> calcInfo = (Map<String, Object>) reqCaptor.getValue().get(0).get("calc_info");
        assertThat(calcInfo).as("per_set 的 quantity 是樘数、不是米数 ⇒ 不得映射成 fabric_meters")
                .doesNotContainKey("fabric_meters");
    }

    // ══════════ issue #4299：米数映射判据 = **加工项 pricingMethod**（真库实测钉死）══════════
    //
    // 判据来源：acceptance/2026-09-18/4299-db-distribution/FINDINGS.md（云 dev 库只读实测，784 行订单行）
    //   · 可达面（带**非空** processingItems ⇒ 能进 buildSnapshot/calcInfo 的订单行）全库 **68** 条：
    //     加工项 `pricingMethod == "per_meter"` 命中 **67/68**；商品 `products.pricing_type == "per_meter"`
    //     只命中 50/68（漏 11 条商品缺失/软删 + 6 条 pricing_type=fixed 而其加工项仍按米）⇒ **商品字段不是判据**。
    //   · 真库 `sellingMethod` 的 11 个取值（bulk_cut / 散剪 / full_roll / 整卷 / 散剪售卖 / 散剪按米 /
    //     散剪·按米购买 / 散剪(bulk_cut) / cut / 散剪（按米裁剪） / (无)）里 **`per_meter` 一次都没出现过**
    //     ⇒ 旧判据（拿 sellingMethod 比 {per_meter, 按米}）**永不命中**，映射分支从未执行。
    //   · 取值必须用**订单行 quantity**：实证订单行 `7e6f2a1c…` 订单数量 **112.00**、其 per_meter 加工项
    //     quantity 被写成 **1** ⇒ 若取加工项 quantity，112 米的单会得到「应做 1 米」⇒ 报工上限 1 ⇒ **假完工**。
    //
    // 端点口径（ai-agent `routing.py::_qty_for` + `qty_and_source`）：米类读 METER_KEYS（`fabric_meters`），
    // 缺键 ⇒ 兜底 1 + `qty_source=fallback`。⚠️ 文件顶部共用的 `stubQty()` 是**与 calc_info 无关**的平行真值
    // （米类恒 12.3 / `fabric_meters`）⇒ 用它断言「米类 qty_source」**恒绿**、证不了映射是否生效；
    // 故本节用例改用 `stubMeterQtyFromCalcInfo()`（镜像端点**米轴**；折/幅/套 仍走共用口径，不在本单范围）。

    /** 把订单行**加工项**的计价方式设成实测键名（驼峰 `pricingMethod`，下单入口逐字如此）。 */
    @SuppressWarnings("unchecked")
    private static void setProcessingItemPricingMethod(OrderItem item, String pricingMethod) {
        Map<String, Object> info = (Map<String, Object>) item.getProcessingInfo();
        List<Map<String, Object>> procs = new ArrayList<>((List<Map<String, Object>>) info.get("processingItems"));
        Map<String, Object> first = new LinkedHashMap<>(procs.get(0));
        first.put("pricingMethod", pricingMethod);
        procs.set(0, first);
        info.put("processingItems", procs);
    }

    /** 删掉售卖方式键（真库 566 条无 `sellingMethod` 的形态；其中可达 calcInfo 的 2 条必须仍被命中）。 */
    @SuppressWarnings("unchecked")
    private static void removeSellingMethod(OrderItem item) {
        ((Map<String, Object>) item.getProcessingInfo()).remove("sellingMethod");
    }

    /**
     * 局部桩：镜像端点「米」这一轴的取数口径 —— calc_info 有 `fabric_meters` ⇒ 取该值 + `fabric_meters`；
     * 缺键 ⇒ 兜底 1 + `fallback`。折/幅/套/孔 仍按共用桩的取值（#4208 的既有用例钉着它们，本单不改那一轴）。
     */
    private void stubMeterQtyFromCalcInfo() {
        doAnswer(inv -> {
            List<Map<String, Object>> request = inv.getArgument(0);
            List<ProductionOperationQtyClient.PositionQty> resolved = new ArrayList<>();
            for (Map<String, Object> position : request) {
                @SuppressWarnings("unchecked")
                Map<String, Object> calc = (Map<String, Object>) position.get("calc_info");
                Map<String, BigDecimal> qty = new LinkedHashMap<>();
                Map<String, String> source = new LinkedHashMap<>();
                for (Object raw : (List<?>) position.get("operations")) {
                    String operation = String.valueOf(raw);
                    String unit = unitOfOperation(operation);
                    if ("米".equals(unit)) {
                        Object meters = calc.get("fabric_meters");
                        if (meters == null) {
                            qty.put(operation, BigDecimal.ONE);
                            source.put(operation, "fallback");
                        } else {
                            qty.put(operation, new BigDecimal(String.valueOf(meters)));
                            source.put(operation, "fabric_meters");
                        }
                    } else if ("折".equals(unit)) {
                        qty.put(operation, new BigDecimal(CALC_PLEAT_COUNT));
                        source.put(operation, "pleat_count");
                    } else if ("孔".equals(unit)) {
                        qty.put(operation, new BigDecimal(CALC_HOLES_ESTIMATE));
                        source.put(operation, "fabric_meters_x6");
                    } else {
                        qty.put(operation, BigDecimal.ONE);
                        source.put(operation, "fallback");
                    }
                }
                resolved.add(new ProductionOperationQtyClient.PositionQty(
                        (String) position.get("position_name"), qty, source));
            }
            return resolved;
        }).when(productionOperationQtyClient).resolve(any());
    }

    /** 生成一张布帘×韩褶单（真链路实例化）并取回请求体里的 calc_info。 */
    @SuppressWarnings("unchecked")
    private Map<String, Object> generateAndCaptureCalcInfo(OrderItem item, boolean meterAwareStub) {
        stubLibrary();
        if (meterAwareStub) {
            stubMeterQtyFromCalcInfo();
        }
        stubGenerate(List.of(item));
        when(processingItemMapper.selectById("p1"))
                .thenReturn(ProcessingItem.builder().id("p1").name("韩褶-布").unit("折").build());

        var results = realChainService().generate(List.of("order-001"), TENANT, "u1");
        assertThat(results.get(0).isSuccess()).isTrue();

        ArgumentCaptor<List<Map<String, Object>>> reqCaptor = ArgumentCaptor.forClass(List.class);
        verify(productionOperationQtyClient).resolve(reqCaptor.capture());
        return (Map<String, Object>) reqCaptor.getValue().get(0).get("calc_info");
    }

    /** 上一次生成落到库里的工序实例（米类断言用）。 */
    private List<ProcessingPositionOperation> capturedInstances() {
        ArgumentCaptor<ProcessingPositionOperation> captor =
                ArgumentCaptor.forClass(ProcessingPositionOperation.class);
        verify(positionOperationMapper, times(V54_BULIAN_HANZHE.length)).insert(captor.capture());
        return captor.getAllValues();
    }

    /** calc_info 里的米数（判据不命中时先在此处红，报错直指「缺 fabric_meters」而不是 NumberFormat）。 */
    private static BigDecimal fabricMetersOf(Map<String, Object> calcInfo) {
        assertThat(calcInfo).as("calc_info 必须带 fabric_meters（判据 = 加工项 pricingMethod=per_meter）")
                .containsKey("fabric_meters");
        return new BigDecimal(String.valueOf(calcInfo.get("fabric_meters")));
    }

    @Test
    @DisplayName("#4299 红证：bulk_cut 单 + per_meter 加工项 ⇒ calc_info.fabric_meters = 订单行 quantity、米类不落兜底")
    void perMeterProcessingItemMapsOrderQuantityEvenWhenSellingMethodIsBulkCut() {
        OrderItem item = orderItemHanzhe("米白");
        @SuppressWarnings("unchecked")
        Map<String, Object> info = (Map<String, Object>) item.getProcessingInfo();
        info.put("sellingMethod", "bulk_cut");   // 真库可达面最大类（52/68）
        setProcessingItemPricingMethod(item, "per_meter");

        Map<String, Object> calcInfo = generateAndCaptureCalcInfo(item, true);

        assertThat(fabricMetersOf(calcInfo))
                .as("判据 = 加工项 pricingMethod=per_meter；取值 = 订单行 quantity（旧判据拿 bulk_cut 比 per_meter 词表 ⇒ 此处无该键）")
                .isEqualByComparingTo(ORDER_QUANTITY);
        assertThat(capturedInstances()).filteredOn(instance -> "米".equals(instance.getUnit()))
                .isNotEmpty()
                .allSatisfy(instance -> assertThat(instance.getQtySource())
                        .as("米类工序的应做数量必须来自 fabric_meters（旧形态恒 fallback 1）")
                        .isEqualTo("fabric_meters"));
    }

    @Test
    @DisplayName("#4299 无 sellingMethod 键也命中（对齐实测 (无) 那 2 条可达订单行）")
    void perMeterProcessingItemMapsEvenWithoutSellingMethod() {
        OrderItem item = orderItemHanzhe("米白");
        removeSellingMethod(item);
        setProcessingItemPricingMethod(item, "per_meter");

        Map<String, Object> calcInfo = generateAndCaptureCalcInfo(item, false);

        assertThat(fabricMetersOf(calcInfo))
                .as("判据只看加工项 pricingMethod ⇒ 售卖方式缺失不影响")
                .isEqualByComparingTo(ORDER_QUANTITY);
    }

    @Test
    @DisplayName("#4299 整卷（full_roll）也命中：实测 4 条整卷单全部带 per_meter 加工项且订单数量是米量级")
    void perMeterProcessingItemMapsForFullRollToo() {
        OrderItem item = orderItemHanzhe("米白");
        @SuppressWarnings("unchecked")
        Map<String, Object> info = (Map<String, Object>) item.getProcessingInfo();
        info.put("sellingMethod", "full_roll");
        setProcessingItemPricingMethod(item, "per_meter");

        Map<String, Object> calcInfo = generateAndCaptureCalcInfo(item, false);

        assertThat(fabricMetersOf(calcInfo))
                .as("整卷单的数量不是卷数而是米量级（实测 3.00 / 112.00）⇒ 同样按订单行 quantity 映射")
                .isEqualByComparingTo(ORDER_QUANTITY);
    }

    @Test
    @DisplayName("#4299 防复发：取值用订单行 quantity（112），**不是**加工项 quantity（1）")
    void fabricMetersComesFromOrderQuantityNotFromProcessingItemQuantity() {
        OrderItem item = orderItemHanzhe("米白");
        item.setQuantity(new BigDecimal("112.00"));   // 实测订单行 7e6f2a1c… 的订单数量
        @SuppressWarnings("unchecked")
        Map<String, Object> info = (Map<String, Object>) item.getProcessingInfo();
        info.put("sellingMethod", "full_roll");
        Map<String, Object> proc = new LinkedHashMap<>();
        proc.put("id", "p1");
        proc.put("name", "韩褶-布");
        proc.put("unit", "折");
        proc.put("pricingMethod", "per_meter");
        proc.put("quantity", 1);   // ← 实测：该 per_meter 加工项的 quantity 被写成 1
        info.put("processingItems", new ArrayList<>(List.of(proc)));

        Map<String, Object> calcInfo = generateAndCaptureCalcInfo(item, false);

        assertThat(fabricMetersOf(calcInfo))
                .as("取加工项 quantity ⇒ 112 米的单得到「应做 1 米」⇒ 报工上限 1 ⇒ 假完工")
                .isEqualByComparingTo("112");
    }

    @Test
    @DisplayName("#4299 负例：加工项全非 per_meter（per_sqm 刺绣单 286229cf…）⇒ 不冒充米数、米类保持 fallback")
    void nonPerMeterProcessingItemDoesNotMapOrderQuantity() {
        // 实测唯一不命中的订单行：sellingMethod=散剪、单条加工项 name=刺绣工艺 / pricingMethod=per_sqm
        OrderItem item = processedItem("item-1", "布艺遮光帘A", "米白", List.of(Map.of(
                "id", "p1", "name", "刺绣工艺", "pricingMethod", "per_sqm",
                "unitPrice", 3.0, "quantity", 2, "unit", "米")));

        Map<String, Object> calcInfo = generateAndCaptureCalcInfo(item, true);

        assertThat(calcInfo).as("订单行 quantity 不是米数（计价方式 per_sqm）⇒ 不得冒充 fabric_meters")
                .doesNotContainKey("fabric_meters");
        assertThat(capturedInstances()).filteredOn(instance -> "米".equals(instance.getUnit()))
                .isNotEmpty()
                .allSatisfy(instance -> assertThat(instance.getQtySource())
                        .as("端点在缺 fabric_meters 时兜底 1 并显式标 fallback（不静默）")
                        .isEqualTo("fallback"));
    }

    @Test
    @DisplayName("#4299 负例：有 processingItems 但无 pricingMethod 键（老数据形态）⇒ 不命中")
    void processingItemsWithoutPricingMethodKeyDoNotMap() {
        OrderItem item = orderItemHanzhe("米白");   // 加工项无 pricingMethod 键
        @SuppressWarnings("unchecked")
        Map<String, Object> info = (Map<String, Object>) item.getProcessingInfo();
        info.put("sellingMethod", "bulk_cut");      // 即便售卖方式是 bulk_cut，也不得据此判米数

        Map<String, Object> calcInfo = generateAndCaptureCalcInfo(item, true);

        assertThat(calcInfo).as("没有 pricingMethod 键 ⇒ 判据不命中（不得回落到 sellingMethod 第二份口径）")
                .doesNotContainKey("fabric_meters");
        assertThat(capturedInstances()).filteredOn(instance -> "米".equals(instance.getUnit()))
                .isNotEmpty()
                .allSatisfy(instance -> assertThat(instance.getQtySource()).isEqualTo("fallback"));
    }

    @Test
    @DisplayName("#4208 fail-closed：算料服务不可用 ⇒ 逐单失败（422 语义 + 可行动建议）且**不落加工单行**")
    void generateFailsClosedWhenQtyServiceUnavailable() {
        stubLibrary();
        // doThrow（而非 when(...).thenThrow）：setUp 里已有 lenient 桩，用 when(...) 形式会先触发旧答案
        doThrow(new BusinessException(
                ProductionOperationQtyClient.ERR_OPERATION_QTY_UNAVAILABLE,
                "算料服务（ai-agent）不可用，无法解析工序应做数量，已中止生成加工单（不回退订单数量）",
                422,
                "请确认 ai-agent-service 已启动后重新生成加工单")).when(productionOperationQtyClient).resolve(any());
        // 不调 stubGenerate：fail-closed 发生在落库之前，给它打 insert 桩会被严格桩判为多余
        when(orderMapper.selectById("order-001")).thenReturn(confirmedOrder);
        when(orderItemMapper.selectList(any())).thenReturn(List.of(orderItemHanzhe("米白")));
        when(processingOrderMapper.selectActiveByOrderId("order-001", TENANT)).thenReturn(null);

        var results = realChainService().generate(List.of("order-001"), TENANT, "u1");

        assertThat(results).hasSize(1);
        assertThat(results.get(0).isSuccess()).isFalse();
        assertThat(results.get(0).getCode()).isEqualTo(ProductionOperationQtyClient.ERR_OPERATION_QTY_UNAVAILABLE);
        assertThat(results.get(0).getSuggestion()).as("失败必须可行动").contains("ai-agent-service");
        assertThat(results.get(0).getMessage()).contains("不回退订单数量");

        // fail-closed 的完整语义：**不落半成品**（加工单行、工序实例、订单状态三者都不动）
        verify(processingOrderMapper, never()).insert(any(ProcessingOrder.class));
        verify(positionOperationMapper, never()).insert(any(ProcessingPositionOperation.class));
        verify(orderService, never()).updateOrderStatus(anyString(), anyString());
    }

    // ══════════════════ 特殊选项 → 条件工序 + 计件系数（issue #4230 Java 侧 v1a）══════════════════
    //
    // 病根（取证事实）：`processing_position_operations.factor` 列自 V49 就存在（注释原文
    // 「特殊选项计件系数（如 一分二 ×1.7）」—— 该原文是 V49（**已发布迁移不可改**）的逐字引用；
    // 选项名已于 issue #4389 按 ERP 对齐为「一分为二」，本引用保留历史原文）、、计件公式也真的乘它，但 `buildPositionPayload`
    // **从不 put factor** ⇒ 落库恒 1.00（实测库里每行都是「系数=1.00」）；且订单侧**从不携带**
    // specialOptions ⇒ 整条链「设计过但从未接线」= 少发工人钱。下面五条即该链的判据。

    @Test
    @DisplayName("#4230 判据 1：带「拼1次」⇒ 多出「拼1次-布」且插在「布三边」之后；不带 ⇒ 不出现")
    void specialOptionInsertsConditionalOperationAfterAnchor() {
        stubLibrary();
        stubOptionTables();
        stubGenerate(List.of(orderItemHanzheWithOptions("米白", List.of("拼1次"))));
        when(processingItemMapper.selectById("p1"))
                .thenReturn(ProcessingItem.builder().id("p1").name("韩褶-布").unit("折").build());

        var results = realChainService().generate(List.of("order-001"), TENANT, "u1");
        assertThat(results.get(0).isSuccess()).isTrue();

        ArgumentCaptor<ProcessingPositionOperation> captor =
                ArgumentCaptor.forClass(ProcessingPositionOperation.class);
        verify(positionOperationMapper, times(V54_BULIAN_HANZHE.length + 1)).insert(captor.capture());
        List<ProcessingPositionOperation> instances = captor.getAllValues();

        // 位置：库路线 11 道 + 1 道条件工序；「拼1次-布」紧跟在「布三边」之后（seq 3）
        assertThat(instances).extracting(ProcessingPositionOperation::getOperationName)
                .containsExactly("精裁-布", "布三边", "拼1次-布", "韩褶-布", "上车布-布", "熨烫-布",
                        "定型-布", "复烫-布", "布帘车被", "外帘打卷", "外帘装袋", "外帘发货");
        // seq 必须重排成 1..N（报工越站防呆取「seq 最大的前道」⇒ 序号重复/断档 = 越站校验错）
        assertThat(instances).extracting(ProcessingPositionOperation::getSeq)
                .containsExactly(1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12);
        // 条件工序的分组/单位/单价**逐字取工序库**（不猜、不补默认值）
        ProcessingPositionOperation inserted = instances.get(2);
        assertThat(inserted.getGroupName()).isEqualTo("车位");
        assertThat(inserted.getUnit()).isEqualTo("幅");
        assertThat(inserted.getUnitPrice()).isEqualByComparingTo("0.8");
        assertThat(inserted.getPositionName()).isEqualTo("布艺遮光帘A 米白");

        // 不带该选项 ⇒ 该工序**不出现**（负例同断言内，避免"两条用例各自打桩"的漂移）
        reset(positionOperationMapper);
        stubGenerate(List.of(orderItemHanzhe("米白")));
        var without = realChainService().generate(List.of("order-001"), TENANT, "u1");
        assertThat(without.get(0).isSuccess()).isTrue();
        ArgumentCaptor<ProcessingPositionOperation> captor2 =
                ArgumentCaptor.forClass(ProcessingPositionOperation.class);
        verify(positionOperationMapper, times(V54_BULIAN_HANZHE.length)).insert(captor2.capture());
        assertThat(captor2.getAllValues()).extracting(ProcessingPositionOperation::getOperationName)
                .doesNotContain("拼1次-布");
    }

    @Test
    @DisplayName("#4230 判据 2：带「一分为二」（ERP 名，issue #4389）⇒ 该部位**每道**工序 factor=1.7；不带 ⇒ 1.00")
    void specialOptionFactorAppliesToEveryOperationOfThePosition() {
        stubLibrary();
        stubOptionTables();
        stubGenerate(List.of(orderItemHanzheWithOptions("米白", List.of("一分为二"))));
        when(processingItemMapper.selectById("p1"))
                .thenReturn(ProcessingItem.builder().id("p1").name("韩褶-布").unit("折").build());

        var results = realChainService().generate(List.of("order-001"), TENANT, "u1");
        assertThat(results.get(0).isSuccess()).isTrue();

        ArgumentCaptor<ProcessingPositionOperation> captor =
                ArgumentCaptor.forClass(ProcessingPositionOperation.class);
        verify(positionOperationMapper, times(V54_BULIAN_HANZHE.length)).insert(captor.capture());
        // 「一分为二」不加工序（只加系数）⇒ 工序数不变，但每道都乘 1.7
        assertThat(captor.getAllValues()).allSatisfy(instance ->
                assertThat(instance.getFactor()).as("工序「%s」的系数", instance.getOperationName())
                        .isEqualByComparingTo("1.7"));

        // 不带 ⇒ 逐条 1.00（防"系数被无条件写成 1.7"的假修复）
        reset(positionOperationMapper);
        stubGenerate(List.of(orderItemHanzhe("米白")));
        realChainService().generate(List.of("order-001"), TENANT, "u1");
        ArgumentCaptor<ProcessingPositionOperation> captor2 =
                ArgumentCaptor.forClass(ProcessingPositionOperation.class);
        verify(positionOperationMapper, times(V54_BULIAN_HANZHE.length)).insert(captor2.capture());
        assertThat(captor2.getAllValues()).allSatisfy(instance ->
                assertThat(instance.getFactor()).isEqualByComparingTo("1"));
    }

    @Test
    @DisplayName("#4230 判据 4：不计件选项（余料带回-布，ERP 名）⇒ 工序数不变、factor 仍为 1，且不是「没映射到」")
    void nonPieceworkOptionIsExplicitNoop() {
        stubLibrary();
        stubOptionTables();
        stubGenerate(List.of(orderItemHanzheWithOptions("米白", List.of("余料带回-布"))));
        when(processingItemMapper.selectById("p1"))
                .thenReturn(ProcessingItem.builder().id("p1").name("韩褶-布").unit("折").build());

        var results = realChainService().generate(List.of("order-001"), TENANT, "u1");
        assertThat(results.get(0).isSuccess()).isTrue();

        ArgumentCaptor<ProcessingPositionOperation> captor =
                ArgumentCaptor.forClass(ProcessingPositionOperation.class);
        verify(positionOperationMapper, times(V54_BULIAN_HANZHE.length)).insert(captor.capture());
        assertThat(captor.getAllValues()).extracting(ProcessingPositionOperation::getOperationName)
                .containsExactlyElementsOf(java.util.Arrays.stream(V54_BULIAN_HANZHE).map(r -> r[0]).toList());
        assertThat(captor.getAllValues()).allSatisfy(instance ->
                assertThat(instance.getFactor()).isEqualByComparingTo("1"));
        // 判别性（否则本用例对「选项根本没被读」也是绿的）：同一张单换一个**有映射**的选项
        // （余料做帘头 → 帘头制作，插在布三边后）⇒ 工序数必须变成 12
        reset(positionOperationMapper);
        stubGenerate(List.of(orderItemHanzheWithOptions("米白", List.of("余料做帘头"))));
        realChainService().generate(List.of("order-001"), TENANT, "u1");
        ArgumentCaptor<ProcessingPositionOperation> changed =
                ArgumentCaptor.forClass(ProcessingPositionOperation.class);
        verify(positionOperationMapper, times(V54_BULIAN_HANZHE.length + 1)).insert(changed.capture());
        assertThat(changed.getAllValues()).extracting(ProcessingPositionOperation::getOperationName)
                .contains("帘头制作");
    }

    @Test
    @DisplayName("#4230 判据 3：系数真的进了钱 —— 同一张单带/不带「一分为二」的计件合计比值 ≈ 1.7")
    void specialOptionFactorReachesPieceworkAmount() {
        BigDecimal withOption = pieceworkTotalFor(List.of("一分为二"));
        BigDecimal without = pieceworkTotalFor(List.of());

        assertThat(without).as("不带特殊选项 ⇒ 合计 = Σ(1 × 库单价)").isGreaterThan(BigDecimal.ZERO);
        double ratio = withOption.divide(without, 6, RoundingMode.HALF_UP).doubleValue();
        // 逐笔四舍五入到分（ProductionService.aggregate 的既有口径）⇒ 合计比值与 1.7 有 0.01 级偏差，
        // 断言用容差而不是等号（等号会假红）；但「带系数 ≠ 不带」这一条是硬断言。
        assertThat(ratio).as("计件合计比值（带 一分为二 / 不带）= 1.7 ± 0.01").isCloseTo(1.7, org.assertj.core.data.Offset.offset(0.01));
        assertThat(withOption).as("系数必须让钱变多（方向）").isGreaterThan(without);
    }

    /** 生成一张带指定特殊选项的加工单，按**真实** ProductionService 算该单计件合计。 */
    @SuppressWarnings("unchecked")
    private BigDecimal pieceworkTotalFor(List<String> specialOptions) {
        stubLibrary();
        stubOptionTables();
        stubGenerate(List.of(orderItemHanzheWithOptions("米白", specialOptions)));
        when(processingItemMapper.selectById("p1"))
                .thenReturn(ProcessingItem.builder().id("p1").name("韩褶-布").unit("折").build());
        List<ProcessingPositionOperation> stored = new ArrayList<>();
        when(positionOperationMapper.insert(any(ProcessingPositionOperation.class))).thenAnswer(inv -> {
            ProcessingPositionOperation row = inv.getArgument(0);
            row.setId("op-" + (stored.size() + 1));
            stored.add(row);
            return 1;
        });

        var results = realChainService().generate(List.of("order-001"), TENANT, "u1");
        assertThat(results.get(0).isSuccess()).isTrue();
        assertThat(stored).isNotEmpty();

        // 每条实例各报一笔「合格 1」（worker/单价/系数都取自**实例快照**）
        List<ProductionWorkLog> logs = new ArrayList<>();
        for (ProcessingPositionOperation row : stored) {
            logs.add(ProductionWorkLog.builder().tenantId(TENANT).processingOrderId("po-001")
                    .operationId(row.getId()).operationName(row.getOperationName())
                    .workerName("走查工人").qty(BigDecimal.ONE).qualifiedQty(BigDecimal.ONE)
                    .workType("normal").deleted(0).build());
        }
        when(positionOperationMapper.selectList(any())).thenReturn(stored);
        when(workLogMapper.selectList(any())).thenReturn(logs);

        ProductionService real = new ProductionService(processingOrderMapper, positionOperationMapper,
                workLogMapper, orderMapper, clientRequestIdService);
        Map<String, Object> piecework = real.piecework("order-001", TENANT);
        return (BigDecimal) piecework.get("total");
    }

    @Test
    @DisplayName("#4230 fail-closed：特殊选项引用的条件工序在工序库无活跃行 ⇒ 中止生成、不落半成品")
    void specialOptionReferencingMissingOperationFailsClosed() {
        stubLibrary();
        // 只桩「拼1次」的映射，但**不**给「拼1次-布」的工序库元数据（= 库里缺这道工序）
        when(productionOperationQueryService.optionRoutings(TENANT)).thenReturn(List.of(
                optionRouting("拼1次", "拼1次-布", "布三边", 1)));
        when(productionOperationQueryService.optionFactors(TENANT)).thenReturn(List.of());
        when(productionOperationQueryService.operationsByName(TENANT)).thenReturn(Map.of());
        // 不调 stubGenerate：fail-closed 发生在落库之前，给它打 insert 桩会被严格桩判为多余
        when(orderMapper.selectById("order-001")).thenReturn(confirmedOrder);
        when(orderItemMapper.selectList(any())).thenReturn(List.of(orderItemHanzheWithOptions("米白", List.of("拼1次"))));
        when(processingOrderMapper.selectActiveByOrderId("order-001", TENANT)).thenReturn(null);

        var results = realChainService().generate(List.of("order-001"), TENANT, "u1");

        assertThat(results.get(0).isSuccess()).isFalse();
        assertThat(results.get(0).getCode()).isEqualTo(ProcessingOrderService.ERR_OPERATION_NOT_FOUND);
        assertThat(results.get(0).getMessage()).contains("拼1次-布");
        assertThat(results.get(0).getSuggestion()).as("失败必须可行动").contains("operations-catalog");
        verify(processingOrderMapper, never()).insert(any(ProcessingOrder.class));
        verify(positionOperationMapper, never()).insert(any(ProcessingPositionOperation.class));
    }

    @Test
    @DisplayName("#4230 锚点不在该部位路线中 ⇒ 条件工序追加到末尾（routing.py _insert_after 同款）")
    void conditionalOperationAppendsWhenAnchorAbsent() {
        stubLibrary();
        when(productionOperationQueryService.optionRoutings(TENANT)).thenReturn(List.of(
                optionRouting("余料做绑带", "绑带-布", "不存在的工序", 8)));
        when(productionOperationQueryService.optionFactors(TENANT)).thenReturn(List.of());
        when(productionOperationQueryService.operationsByName(TENANT)).thenReturn(Map.of(
                "绑带-布", operationMeta("其他", "套", "0.5")));
        stubGenerate(List.of(orderItemHanzheWithOptions("米白", List.of("余料做绑带"))));
        when(processingItemMapper.selectById("p1"))
                .thenReturn(ProcessingItem.builder().id("p1").name("韩褶-布").unit("折").build());

        var results = realChainService().generate(List.of("order-001"), TENANT, "u1");
        assertThat(results.get(0).isSuccess()).isTrue();

        ArgumentCaptor<ProcessingPositionOperation> captor =
                ArgumentCaptor.forClass(ProcessingPositionOperation.class);
        verify(positionOperationMapper, times(V54_BULIAN_HANZHE.length + 1)).insert(captor.capture());
        List<ProcessingPositionOperation> instances = captor.getAllValues();
        assertThat(instances.get(instances.size() - 1).getOperationName()).isEqualTo("绑带-布");
        assertThat(instances.get(instances.size() - 1).getSeq()).isEqualTo(V54_BULIAN_HANZHE.length + 1);
    }

    @Test
    @DisplayName("#4230 不回归：无特殊选项 ⇒ 工序实例与 factor 与改动前逐值相同")
    void noSpecialOptionsKeepsRouteAndFactorUnchanged() {
        stubLibrary();
        stubOptionTables();
        stubGenerate(List.of(orderItemHanzhe("米白")));
        when(processingItemMapper.selectById("p1"))
                .thenReturn(ProcessingItem.builder().id("p1").name("韩褶-布").unit("折").build());

        var results = realChainService().generate(List.of("order-001"), TENANT, "u1");
        assertThat(results.get(0).isSuccess()).isTrue();

        ArgumentCaptor<ProcessingPositionOperation> captor =
                ArgumentCaptor.forClass(ProcessingPositionOperation.class);
        verify(positionOperationMapper, times(V54_BULIAN_HANZHE.length)).insert(captor.capture());
        List<ProcessingPositionOperation> instances = captor.getAllValues();
        for (int i = 0; i < V54_BULIAN_HANZHE.length; i++) {
            String[] row = V54_BULIAN_HANZHE[i];
            assertThat(instances.get(i).getOperationName()).isEqualTo(row[0]);
            assertThat(instances.get(i).getSeq()).as("序号 = 库路线原序 1..N").isEqualTo(i + 1);
            assertThat(instances.get(i).getUnitPrice()).isEqualByComparingTo(row[3]);
            assertThat(instances.get(i).getFactor()).isEqualByComparingTo("1");
        }
    }

    @Test
    @DisplayName("#4116 切库负例②：工序库取不到路线 ⇒ fail-closed 中止生成（不回退加工项目录、不落半成品）")
    void generateFailsClosedWhenOperationLibraryHasNoRoute() {
        stubEmptyLibrary();
        when(orderMapper.selectById("order-001")).thenReturn(confirmedOrder);
        when(orderItemMapper.selectList(any())).thenReturn(List.of(orderItemHanzhe("米白")));
        when(processingOrderMapper.selectActiveByOrderId("order-001", TENANT)).thenReturn(null);

        var results = processingOrderService.generate(List.of("order-001"), TENANT, "u1");

        assertThat(results.get(0).isSuccess()).isFalse();
        // 可见性①：接口错误码 + 原文 message（不是「静默走了旧路径」）
        assertThat(results.get(0).getCode()).isEqualTo(ProcessingOrderService.ERR_ROUTING_NOT_FOUND);
        assertThat(results.get(0).getMessage()).contains("工序库").contains("不回退加工项目录");
        // 可见性②：可行动 suggestion（说出库里现状 + 补救入口）
        assertThat(results.get(0).getSuggestion())
                .contains("V54__seed_production_operations.sql")
                .contains("/api/admin/production/routings");
        // 不落半成品：一行不写、订单状态不动（否则会留下「有加工单、无工序、无 qr_token」的孤儿态）
        verify(processingOrderMapper, never()).insert(any(ProcessingOrder.class));
        verify(orderService, never()).updateOrderStatus(anyString(), anyString());
        verify(productionService, never()).instantiate(anyString(), any(), anyLong());
    }

    @Test
    @DisplayName("#4116 切库负例②b：路线引用的工序在库中无活跃行 ⇒ 同样 fail-closed（指名报缺）")
    void generateFailsClosedWhenRouteCitesMissingOperation() {
        // 库里这条路线存在，但「幽灵工序」在 production_operations 里没有行
        Map<String, Object> broken = v54Route("布帘", "韩褶");
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> steps = (List<Map<String, Object>>) broken.get("operations");
        steps.add(new LinkedHashMap<>(Map.of("seq", 12, "operation", "幽灵工序")));
        broken.put("missing_operations", List.of("幽灵工序"));
        when(productionOperationQueryService.findRouting(eq(TENANT), anyString(), anyString())).thenReturn(broken);
        when(orderMapper.selectById("order-001")).thenReturn(confirmedOrder);
        when(orderItemMapper.selectList(any())).thenReturn(List.of(orderItemHanzhe("米白")));
        when(processingOrderMapper.selectActiveByOrderId("order-001", TENANT)).thenReturn(null);

        var results = processingOrderService.generate(List.of("order-001"), TENANT, "u1");

        assertThat(results.get(0).isSuccess()).isFalse();
        assertThat(results.get(0).getCode()).isEqualTo(ProcessingOrderService.ERR_OPERATION_NOT_FOUND);
        assertThat(results.get(0).getMessage()).contains("幽灵工序");
        assertThat(results.get(0).getSuggestion()).contains("/api/admin/production/operations-catalog");
        verify(processingOrderMapper, never()).insert(any(ProcessingOrder.class));
    }

    @Test
    @DisplayName("#4116 切库取法：派生键库里没有 ⇒ 回落默认路线 布帘×韩褶（帘头×平幔 → 布帘×韩褶）")
    void generateFallsBackToDefaultRouteWhenDerivedKeyAbsentFromLibrary() {
        // 桩里只有 布帘×韩褶 / 布帘×打孔 两条；订单派生 帘头×平幔 ⇒ 库里查不到 ⇒ 必须回落默认路线
        stubLibrary();
        stubGenerate(List.of(orderItemLiTou("米白")));
        when(processingItemMapper.selectById("p3")).thenReturn(null);

        var results = realChainService().generate(List.of("order-001"), TENANT, "u1");

        assertThat(results.get(0).isSuccess()).isTrue();
        verify(productionOperationQueryService).findRouting(TENANT, "帘头", "平幔");
        verify(productionOperationQueryService).findRouting(TENANT, "布帘", "韩褶");
        // 实例 = 默认路线 rt-v54-01（11 道），不是空实例、也不是别的路线
        ArgumentCaptor<ProcessingPositionOperation> opCaptor =
                ArgumentCaptor.forClass(ProcessingPositionOperation.class);
        verify(positionOperationMapper, times(V54_BULIAN_HANZHE.length)).insert(opCaptor.capture());
        assertThat(opCaptor.getAllValues()).extracting(ProcessingPositionOperation::getOperationName)
                .containsExactlyElementsOf(
                        java.util.Arrays.stream(V54_BULIAN_HANZHE).map(row -> row[0]).toList());
    }

    @Test
    @DisplayName("#4116 切库取法：全无派生信号 ⇒ 直接用默认键 布帘×韩褶")
    void generateUsesDefaultKeyWhenNoSignalMatches() {
        stubLibrary();
        stubGenerate(List.of(orderItemWithoutRouteSignal()));
        when(processingItemMapper.selectById("p9")).thenReturn(null);

        var results = realChainService().generate(List.of("order-001"), TENANT, "u1");

        assertThat(results.get(0).isSuccess()).isTrue();
        verify(productionOperationQueryService).findRouting(TENANT, "布帘", "韩褶");
        ArgumentCaptor<ProcessingPositionOperation> opCaptor =
                ArgumentCaptor.forClass(ProcessingPositionOperation.class);
        verify(positionOperationMapper, times(V54_BULIAN_HANZHE.length)).insert(opCaptor.capture());
        assertThat(opCaptor.getAllValues()).extracting(ProcessingPositionOperation::getOperationName)
                .contains("韩褶-布");
    }

    @Test
    @DisplayName("#4116 切库取法：加工项名派生部位×工艺（打孔-布 ⇒ 布帘×打孔，10 道路线）")
    void generateDerivesRouteKeyFromProcessingItemName() {
        stubLibrary();
        stubGenerate(List.of(orderItemWithProcessing("米白")));
        when(processingItemMapper.selectById("p1"))
                .thenReturn(ProcessingItem.builder().id("p1").name("打孔").unit("米").build());

        var results = realChainService().generate(List.of("order-001"), TENANT, "u1");

        assertThat(results.get(0).isSuccess()).isTrue();
        // 派生键命中 布帘×打孔 ⇒ 取 rt-v54-02（10 道），**不**回落到默认路线（11 道）
        verify(productionOperationQueryService).findRouting(TENANT, "布帘", "打孔");
        verify(productionOperationQueryService, never()).findRouting(TENANT, "布帘", "韩褶");
        ArgumentCaptor<ProcessingPositionOperation> opCaptor =
                ArgumentCaptor.forClass(ProcessingPositionOperation.class);
        verify(positionOperationMapper, times(V54_BULIAN_DAKONG.length)).insert(opCaptor.capture());
        assertThat(opCaptor.getAllValues()).extracting(ProcessingPositionOperation::getOperationName)
                .containsExactlyElementsOf(
                        java.util.Arrays.stream(V54_BULIAN_DAKONG).map(row -> row[0]).toList());
        assertThat(opCaptor.getAllValues().get(2).getUnit()).isEqualTo("孔");
        assertThat(opCaptor.getAllValues().get(2).getUnitPrice()).isEqualByComparingTo("0.15");
    }

    @Test
    @DisplayName("#4116 加工项无名称（脏数据）→ 不再影响工序来源，仍按默认路线实例化且不阻断生成")
    void generateWithNamelessProcessingItemStillInstantiates() {
        stubLibrary();
        stubGenerate(List.of(orderItemWithNamelessProcessing()));

        var results = realChainService().generate(List.of("order-001"), TENANT, "u1");

        assertThat(results.get(0).isSuccess()).isTrue();
        assertThat(results.get(0).getProcessingOrderNo()).startsWith("JG-");
        // 切库后工序来源不再是加工项名 ⇒「缺名称」只剩「少了一个派生信号」的含义，
        // 落默认路线（布帘×韩褶）而不是**静默跳过实例化**（旧行为会留下无工序、无 qr_token 的加工单）
        verify(positionOperationMapper, times(V54_BULIAN_HANZHE.length))
                .insert(any(ProcessingPositionOperation.class));
    }

    // ══ issue #4354（设计文档 §4.7 / §4.8 / §4.9）：Java 消费端把「猜」换成「读」══

    @Test
    @DisplayName("#4354 判据 A：订单带 curtainType=纱帘 + craft=打孔 ⇒ **直读**取 纱帘×打孔（派生会指向布帘）")
    void craftSpecDirectReadBeatsKeywordDerivation() {
        stubLibrary();
        stubGenerate(List.of(orderItemShaluDakongWithSpec("米白")));

        var results = realChainService().generate(List.of("order-001"), TENANT, "u1");

        assertThat(results.get(0).isSuccess()).isTrue();
        // 直读 ⇒ 取订单写下的键，且**不查**信号映射表（派生只是存量单兜底）
        verify(productionOperationQueryService).findRouting(TENANT, "纱帘", "打孔");
        verify(productionOperationQueryService, never()).findRouting(TENANT, "布帘", "韩褶");
        verify(productionOperationQueryService, never()).routeSignals(TENANT);

        ArgumentCaptor<ProcessingOrder> poCaptor = ArgumentCaptor.forClass(ProcessingOrder.class);
        verify(processingOrderMapper).insert(poCaptor.capture());
        assertThat(poCaptor.getValue().getRouteKey()).isEqualTo("纱帘×打孔");
        assertThat(poCaptor.getValue().getRouteSource()).as("直读 = 新增第 5 态 direct").isEqualTo("direct");
        assertThat(poCaptor.getValue().getRouteRequestedKey()).isEqualTo("纱帘×打孔");

        ArgumentCaptor<ProcessingPositionOperation> opCaptor =
                ArgumentCaptor.forClass(ProcessingPositionOperation.class);
        verify(positionOperationMapper, times(V58_SHALU_DAKONG.length)).insert(opCaptor.capture());
        List<String> instantiated = opCaptor.getAllValues().stream()
                .map(ProcessingPositionOperation::getOperationName).toList();
        assertThat(instantiated).containsExactlyElementsOf(operationNames(V58_SHALU_DAKONG));
        // 「不重合」按**布帘专属**工序判：打卷/装袋/发货是两条路线共有的后道
        // （V58 种子按布帘同工艺镜像时**刻意保留**了这一段，见该迁移注释）⇒ 拿整条布帘路线比会假红。
        List<String> bulianOnly = new ArrayList<>(operationNames(V54_BULIAN_HANZHE));
        bulianOnly.removeAll(operationNames(V58_SHALU_DAKONG));
        assertThat(bulianOnly).as("自检：判别物必须非空（否则本断言空转 = 假绿）").isNotEmpty();
        assertThat(instantiated).as("V58 实证的错配：纱帘订单**不得**拿到布帘专属工序")
                .doesNotContainAnyElementsOf(bulianOnly);
    }

    @Test
    @DisplayName("#4354 判据 C：isShaped=false ⇒ 实例**剔除** 定型-布 / 复烫-布（真值源 §10 的唯一未接线项）")
    void unshapedOrderDropsShapingOperations() {
        stubLibrary();
        stubGenerate(List.of(orderItemHanzheUnshaped("米白")));

        var results = realChainService().generate(List.of("order-001"), TENANT, "u1");

        assertThat(results.get(0).isSuccess()).isTrue();
        ArgumentCaptor<ProcessingPositionOperation> opCaptor =
                ArgumentCaptor.forClass(ProcessingPositionOperation.class);
        verify(positionOperationMapper, times(V54_BULIAN_HANZHE.length - 2)).insert(opCaptor.capture());
        List<ProcessingPositionOperation> instances = opCaptor.getAllValues();
        assertThat(instances).extracting(ProcessingPositionOperation::getOperationName)
                .doesNotContain("定型-布", "复烫-布")
                .contains("韩褶-布", "外帘发货");
        assertThat(instances).extracting(ProcessingPositionOperation::getSeq)
                .as("删两道后 seq 必须重排为连续 1..N（前道判定 防呆② 按 seq 取立即前道，留空档会看错前道）")
                .containsExactlyElementsOf(java.util.stream.IntStream
                        .rangeClosed(1, V54_BULIAN_HANZHE.length - 2).boxed().toList());
    }

    @Test
    @DisplayName("#4354 只认**严格布尔** false：isShaped 为脏数据（字符串）⇒ 不删工序（与 routing.py 的 `is False` 同款）")
    void nonBooleanIsShapedDoesNotDropShapingOperations() {
        stubLibrary();
        stubGenerate(List.of(orderItemHanzheWithStringIsShaped("米白")));

        var results = realChainService().generate(List.of("order-001"), TENANT, "u1");

        assertThat(results.get(0).isSuccess()).isTrue();
        verify(positionOperationMapper, times(V54_BULIAN_HANZHE.length))
                .insert(any(ProcessingPositionOperation.class));
    }

    @Test
    @DisplayName("#4354 判据 E：两维全缺且派生也拿不到路线 ⇒ fail-closed（不静默落别的路线、不落半成品）")
    void missingCraftSpecAndUnderivableRouteFailsClosed() {
        // 库里**只有** 纱帘×打孔（没有默认路线 布帘×韩褶）：两维全缺 ⇒ 派生全不命中 ⇒ T3 ⇒ 中止生成
        when(productionOperationQueryService.findRouting(eq(TENANT), anyString(), anyString()))
                .thenAnswer(inv -> "纱帘".equals(inv.getArgument(1)) ? v54Route("纱帘", "打孔") : null);
        when(productionOperationQueryService.routingKeys(TENANT)).thenReturn(List.of("纱帘×打孔"));
        when(orderMapper.selectById("order-001")).thenReturn(confirmedOrder);
        when(orderItemMapper.selectList(any())).thenReturn(List.of(orderItemWithoutRouteSignal()));
        when(processingOrderMapper.selectActiveByOrderId("order-001", TENANT)).thenReturn(null);

        var results = processingOrderService.generate(List.of("order-001"), TENANT, "u1");

        assertThat(results.get(0).isSuccess()).isFalse();
        assertThat(results.get(0).getCode()).isEqualTo(ProcessingOrderService.ERR_ROUTING_NOT_FOUND);
        verify(processingOrderMapper, never()).insert(any(ProcessingOrder.class));
        verify(productionService, never()).instantiate(anyString(), any(), anyLong());
    }

    @Test
    @DisplayName("#4354 空白 craft spec 键 = **缺键**（不把空白当值 ⇒ 不造出「 ×韩褶」这种路线键）")
    void blankCraftSpecKeysAreTreatedAsAbsent() {
        stubLibrary();
        stubGenerate(List.of(orderItemHanzheWithBlankSpec("米白")));

        var results = realChainService().generate(List.of("order-001"), TENANT, "u1");

        assertThat(results.get(0).isSuccess()).isTrue();
        ArgumentCaptor<ProcessingOrder> poCaptor = ArgumentCaptor.forClass(ProcessingOrder.class);
        verify(processingOrderMapper).insert(poCaptor.capture());
        assertThat(poCaptor.getValue().getRouteKey()).isEqualTo("布帘×韩褶");
        assertThat(poCaptor.getValue().getRouteSource())
                .as("空白键不是值：仍走既有派生（derived）—— 既不是 direct，也不是 missing_route")
                .isEqualTo("derived");
    }

    @Test
    @DisplayName("#4354 判据 G：拼色一扇窗（主布行 + 配布边行同 craftLineId）⇒ **只生成一个部位**，工序不翻倍")
    void colorBlockWindowProducesSinglePosition() {
        stubLibrary();
        stubGenerate(colorBlockWindow());

        var results = realChainService().generate(List.of("order-001"), TENANT, "u1");

        assertThat(results.get(0).isSuccess()).isTrue();
        // 一个部位 ⇒ 算料只被问一个部位（否则折数/开数按「两扇窗」各算一次 = 双算）
        ArgumentCaptor<List<Map<String, Object>>> reqCaptor = ArgumentCaptor.forClass(List.class);
        verify(productionOperationQtyClient).resolve(reqCaptor.capture());
        assertThat(reqCaptor.getValue()).as("一扇窗 = 一个部位（主布 + 配布边 合并）").hasSize(1);
        assertThat(reqCaptor.getValue().get(0).get("position_name")).isEqualTo("布艺遮光帘A 米白");
        // 工序实例 = 主布路线的 11 道，**不是** 22 道
        ArgumentCaptor<ProcessingPositionOperation> opCaptor =
                ArgumentCaptor.forClass(ProcessingPositionOperation.class);
        verify(positionOperationMapper, times(V54_BULIAN_HANZHE.length)).insert(opCaptor.capture());
        assertThat(opCaptor.getAllValues()).extracting(ProcessingPositionOperation::getOperationName)
                .containsExactlyElementsOf(operationNames(V54_BULIAN_HANZHE));
    }

    @Test
    @DisplayName("#4354 craftLineId 绑组：配布边行填**主布行的行标识**（主布行自身无该键）⇒ 同样只生成一个部位")
    void edgeRowBindingByMainRowIdAlsoMerges() {
        stubLibrary();
        stubGenerate(colorBlockWindowBoundByMainRowId());

        var results = realChainService().generate(List.of("order-001"), TENANT, "u1");

        assertThat(results.get(0).isSuccess()).isTrue();
        ArgumentCaptor<List<Map<String, Object>>> reqCaptor = ArgumentCaptor.forClass(List.class);
        verify(productionOperationQtyClient).resolve(reqCaptor.capture());
        assertThat(reqCaptor.getValue()).hasSize(1);
        verify(positionOperationMapper, times(V54_BULIAN_HANZHE.length))
                .insert(any(ProcessingPositionOperation.class));
    }

    @Test
    @DisplayName("#4387 判据 2：一樘「布 + 纱」= 两条明细行、各成部位、同 craftLineId ⇒ 加工单两个部位（17 道工序）")
    void clothPlusSheerWindowProducesTwoPositions() {
        stubLibrary();
        stubGenerate(clothPlusSheerWindow());

        var results = realChainService().generate(List.of("order-001"), TENANT, "u1");

        assertThat(results.get(0).isSuccess()).isTrue();
        // 两个部位 ⇒ 算料被问两个部位（纱帘是**独立部位**，不得被并进布行）
        ArgumentCaptor<List<Map<String, Object>>> reqCaptor = ArgumentCaptor.forClass(List.class);
        verify(productionOperationQtyClient).resolve(reqCaptor.capture());
        assertThat(reqCaptor.getValue())
                .as("一行 order_items = 一个部位 ⇒ 布 + 纱 = 两个部位（不是一扇，也不是三扇）")
                .hasSize(2);
        assertThat(reqCaptor.getValue()).extracting(p -> p.get("position_name"))
                .containsExactly("布艺遮光帘A 米白", "纱帘A 米白");
        // 工序 = 布帘×韩褶 11 道 + 纱帘×打孔 6 道（两条路线各自成部位，不互相吞并）
        ArgumentCaptor<ProcessingPositionOperation> opCaptor =
                ArgumentCaptor.forClass(ProcessingPositionOperation.class);
        verify(positionOperationMapper, times(V54_BULIAN_HANZHE.length + V58_SHALU_DAKONG.length))
                .insert(opCaptor.capture());
        List<String> expected = new ArrayList<>(operationNames(V54_BULIAN_HANZHE));
        expected.addAll(operationNames(V58_SHALU_DAKONG));
        assertThat(opCaptor.getAllValues()).extracting(ProcessingPositionOperation::getOperationName)
                .containsExactlyElementsOf(expected);

        // 固化真相：快照两条，**同 craftLineId**（樘窗 = 分组层级，事后可归属套级工序/加工费）
        ArgumentCaptor<ProcessingOrder> poCaptor = ArgumentCaptor.forClass(ProcessingOrder.class);
        verify(processingOrderMapper).insert(poCaptor.capture());
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> snapshot = (List<Map<String, Object>>) poCaptor.getValue().getItemsSnapshot();
        assertThat(snapshot).hasSize(2);
        assertThat(snapshot).extracting(entry -> entry.get("craftLineId"))
                .as("布行与纱行必须带**同一个** craftLineId（否则两行归不到同一樘窗）")
                .containsExactly("win-1", "win-1");
        assertThat(snapshot).extracting(entry -> entry.get("curtainType"))
                .containsExactly("布帘", "纱帘");
    }

    @Test
    @DisplayName("#4387 判据 3（注入式红证）：配布边行**去掉** componentRole ⇒ 部位数 1 → 2（角色键是判别物）")
    void edgeRowRoleIsWhatSuppressesTheExtraPosition() {
        // ① 带 componentRole=配布边 ⇒ 吸收，一个部位（#4354 回归不变）
        stubLibrary();
        stubGenerate(colorBlockWindow());
        realChainService().generate(List.of("order-001"), TENANT, "u1");
        ArgumentCaptor<List<Map<String, Object>>> withRole = ArgumentCaptor.forClass(List.class);
        verify(productionOperationQtyClient).resolve(withRole.capture());
        assertThat(withRole.getValue()).as("配布边行不独立成部位").hasSize(1);

        // ② 同夹具去掉该键（注入）⇒ 两个部位。同一夹具两变体对照，才是「部位数会随该键变化」的证明。
        reset(productionOperationQtyClient, positionOperationMapper, processingOrderMapper);
        stubQty();
        stubLibrary();
        stubGenerate(colorBlockWindowWithoutEdgeRole());
        realChainService().generate(List.of("order-001"), TENANT, "u1");
        ArgumentCaptor<List<Map<String, Object>>> withoutRole = ArgumentCaptor.forClass(List.class);
        verify(productionOperationQtyClient).resolve(withoutRole.capture());
        assertThat(withoutRole.getValue())
                .as("注入生效：去掉 componentRole=配布边 ⇒ 该行不再被吸收 ⇒ 部位数变化（判据 3 的红证形态）")
                .hasSize(2);
    }

    @Test
    @DisplayName("#4354 判据 B（消费端半边）：订单带 fabric_meters/pleat_count ⇒ 米类应做数量取自算料输出，不是 fallback 1")
    void orderCalcOutputReachesQtyEngineInsteadOfFallback() {
        Map<String, Object> calcInfo = generateAndCaptureCalcInfo(orderItemHanzheWithCalcOutput("米白"), true);

        assertThat(calcInfo).as("订单侧已落库的算料输出必须原样透传给算料端点")
                .containsKeys("fabric_meters", "pleat_count");
        assertThat(calcInfo).as("§4.3 新增白名单键：per_panel_pleats / fullness / fullness_actual")
                .containsKeys("per_panel_pleats", "fullness", "fullness_actual");

        List<ProcessingPositionOperation> instances = capturedInstances();
        assertThat(instances.get(0).getOperationName()).isEqualTo("精裁-布");
        assertThat(instances.get(0).getQtySource())
                .as("米类工序应做数量必须来自算料输出（fallback 1 = 本单要治的缺陷）")
                .isEqualTo("fabric_meters");
        assertThat(instances.get(0).getQty()).isEqualByComparingTo(CALC_FABRIC_METERS);
        assertThat(instances.get(2).getOperationName()).isEqualTo("韩褶-布");
        assertThat(instances.get(2).getQtySource()).isEqualTo("pleat_count");
        assertThat(instances.get(2).getQty()).isEqualByComparingTo(CALC_PLEAT_COUNT);
    }

    @Test
    @DisplayName("#4354 §4.9 快照白名单：craft spec 全键 + 算料输出键逐键进快照；缺键就缺（不造值）")
    void snapshotCarriesCraftSpecAndCalcOutputVerbatim() {
        stubLibrary();
        when(orderMapper.selectById("order-001")).thenReturn(confirmedOrder);
        when(orderItemMapper.selectList(any()))
                .thenReturn(List.of(orderItemWithFullCraftSpec("米白"), orderItemWithoutCraftSpec()));
        when(processingOrderMapper.selectActiveByOrderId("order-001", TENANT)).thenReturn(null);
        when(processingOrderMapper.insert(any(ProcessingOrder.class))).thenReturn(1);

        processingOrderService.generate(List.of("order-001"), TENANT, "u1");

        ArgumentCaptor<ProcessingOrder> poCaptor = ArgumentCaptor.forClass(ProcessingOrder.class);
        verify(processingOrderMapper).insert(poCaptor.capture());
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> snapshot = (List<Map<String, Object>>) poCaptor.getValue().getItemsSnapshot();
        assertThat(snapshot).hasSize(2);

        Map<String, Object> withSpec = snapshot.get(0);
        assertThat(withSpec).containsEntry("itemId", "item-1");
        assertThat(withSpec).containsEntry("curtainType", "纱帘").containsEntry("craft", "打孔");
        assertThat(withSpec).containsEntry("cuttingMode", "定高买宽").containsEntry("openCount", 2);
        assertThat(withSpec).containsEntry("isShaped", false)
                .containsEntry("pleatSpacing", new BigDecimal("0.1"));
        assertThat(withSpec).containsEntry("hasPattern", true)
                .containsEntry("patternRepeat", new BigDecimal("0.6"));
        assertThat(withSpec).containsEntry("style", "拼色").containsEntry("room", "客厅")
                .containsEntry("batchNo", "B-20260918");
        assertThat(withSpec).containsEntry("componentRole", "主布").containsEntry("craftLineId", "item-1")
                .containsEntry("metersSource", "跟随主布")
                .containsEntry("processingMeters", new BigDecimal("12.3"));
        assertThat(withSpec).containsKeys("fabric_meters", "pleat_count", "per_panel_pleats",
                "panels", "holes", "fullness", "fullness_actual");

        Map<String, Object> withoutSpec = snapshot.get(1);
        assertThat(withoutSpec).containsEntry("itemId", "item-2");
        assertThat(withoutSpec).as("缺键就缺：Java 不发明工艺规格，也不发明算料数字")
                .doesNotContainKeys("curtainType", "craft", "isShaped", "componentRole", "craftLineId",
                        "fabric_meters", "pleat_count", "per_panel_pleats");
    }

    @Test
    @DisplayName("#4116 切库后幂等：库派生 payload 重放实例化 ⇒ 一行不写、qr_token 复用（#4116 §4 不回退）")
    void libraryDerivedPayloadReplayIsIdempotentAndKeepsQrToken() {
        // ① 先抓住**真实的**库派生 payload（走 @InjectMocks 的 mock ProductionService 便于捕获；
        //    库桩与真实实现同构，见 V54_* 常量）
        stubLibrary();
        stubGenerate(List.of(orderItemHanzhe("米白")));
        when(processingItemMapper.selectById("p1"))
                .thenReturn(ProcessingItem.builder().id("p1").name("韩褶-布").unit("折").build());

        processingOrderService.generate(List.of("order-001"), TENANT, "u1");

        ArgumentCaptor<Map<String, Object>> bodyCaptor = ArgumentCaptor.forClass(Map.class);
        verify(productionService).instantiate(eq("order-001"), bodyCaptor.capture(), eq(TENANT));
        Map<String, Object> payload = bodyCaptor.getValue();

        // ② 用同一 payload 在**真实** ProductionService 上重放两次：DB 层用「会记住插入」的桩，
        //    这样第二次的幂等比较面对的是真落库形态（签名比较 ⇒ 相等一行不写）
        List<ProcessingPositionOperation> stored = new ArrayList<>();
        when(positionOperationMapper.insert(any(ProcessingPositionOperation.class))).thenAnswer(inv -> {
            stored.add(inv.getArgument(0));
            return 1;
        });
        when(positionOperationMapper.selectList(any())).thenAnswer(inv -> stored);
        when(processingOrderMapper.updateById(any(ProcessingOrder.class))).thenAnswer(inv -> {
            ProcessingOrder patch = inv.getArgument(0);
            ProcessingOrder current = processingOrderMapper.selectActiveByOrderId("order-001", TENANT);
            if (patch.getQrToken() != null && current != null) {
                current.setQrToken(patch.getQrToken());
            }
            return 1;
        });
        ProductionService real = new ProductionService(processingOrderMapper, positionOperationMapper,
                workLogMapper, orderMapper, clientRequestIdService);

        Map<String, Object> first = real.instantiate("order-001", payload, TENANT);
        int afterFirst = stored.size();
        Map<String, Object> second = real.instantiate("order-001", payload, TENANT);

        assertThat(afterFirst).isEqualTo(V54_BULIAN_HANZHE.length);
        assertThat(stored).as("重放同一库路线 ⇒ 不新增行、旧实例不软删").hasSize(afterFirst);
        verify(positionOperationMapper, never()).update(isNull(), any());
        assertThat(second.get("operation_count")).isEqualTo(afterFirst);
        assertThat(second.get("qr_token")).isEqualTo(first.get("qr_token"));
        assertThat((String) first.get("qr_token")).matches("[0-9a-f]{32}");
    }

    // ── PG-002 幂等 ────────────────────────────────────────────────

    @Test
    @DisplayName("PG-002 已有活跃加工单 → 重复生成拒绝")
    void generateDuplicateRejected() {
        when(orderMapper.selectById("order-001")).thenReturn(confirmedOrder);
        when(orderItemMapper.selectList(any()))
                .thenReturn(List.of(orderItemWithProcessing("米白")));
        when(processingOrderMapper.selectActiveByOrderId("order-001", TENANT))
                .thenReturn(po("po-1", "generated"));

        var results = processingOrderService.generate(List.of("order-001"), TENANT, "u1");

        assertThat(results.get(0).isSuccess()).isFalse();
        assertThat(results.get(0).getMessage()).contains("已有加工单");
        verify(processingOrderMapper, never()).insert(any(ProcessingOrder.class));
        verify(orderService, never()).updateOrderStatus(anyString(), anyString());
    }

    // ── PG-003 无加工项 ────────────────────────────────────────────

    @Test
    @DisplayName("PG-003 无加工项订单 → 拒绝生成")
    void generateWithoutProcessingRejected() {
        when(orderMapper.selectById("order-001")).thenReturn(confirmedOrder);
        when(orderItemMapper.selectList(any()))
                .thenReturn(List.of(orderItemWithoutProcessing()));

        var results = processingOrderService.generate(List.of("order-001"), TENANT, "u1");

        assertThat(results.get(0).isSuccess()).isFalse();
        assertThat(results.get(0).getMessage()).contains("无加工项");
        verify(processingOrderMapper, never()).insert(any(ProcessingOrder.class));
    }

    // ── PG-004 未确认订单 ──────────────────────────────────────────

    @Test
    @DisplayName("PG-004 pending 订单 → 拒绝生成")
    void generatePendingOrderRejected() {
        Order pending = Order.builder()
                .id("order-pending").tenantId(TENANT).orderNo("ORD-P")
                .status("pending").build();
        when(orderMapper.selectById("order-pending")).thenReturn(pending);

        var results = processingOrderService.generate(List.of("order-pending"), TENANT, "u1");

        assertThat(results.get(0).isSuccess()).isFalse();
        assertThat(results.get(0).getMessage()).contains("不允许生成加工单");
    }

    @Test
    @DisplayName("订单号解析：selectById 未命中时按订单号查询")
    void generateResolveByOrderNo() {
        stubLibrary();
        when(orderMapper.selectById("ORD-20260912-0001")).thenReturn(null);
        when(orderMapper.selectOne(any())).thenReturn(confirmedOrder);
        when(orderItemMapper.selectList(any()))
                .thenReturn(List.of(orderItemWithProcessing("米白")));
        when(processingOrderMapper.selectActiveByOrderId("order-001", TENANT)).thenReturn(null);
        when(processingOrderMapper.insert(any(ProcessingOrder.class))).thenReturn(1);

        var results = processingOrderService.generate(List.of("ORD-20260912-0001"), TENANT, "u1");

        assertThat(results.get(0).isSuccess()).isTrue();
        // #4305：生成不联动订单（时点在发加工）
        verify(orderService, never()).updateOrderStatus(anyString(), anyString());
    }

    // ── PG-005/006 状态机 ──────────────────────────────────────────

    @Test
    @DisplayName("PG-005 issue/start/complete 主链流转")
    void updateStatusMainChain() {
        when(processingOrderMapper.selectOne(any())).thenReturn(po("po-1", "generated"));
        when(processingOrderMapper.updateById(any(ProcessingOrder.class))).thenReturn(1);
        when(orderMapper.selectById("order-001")).thenReturn(confirmedOrder);

        ProcessingOrderUpdateRequest issue = new ProcessingOrderUpdateRequest();
        issue.setAction("issue");
        issue.setProcessor("朝阳加工厂");
        issue.setExpectedDeliveryDate(LocalDate.of(2026, 9, 20));
        processingOrderService.updateStatus("po-1", issue, TENANT, "u1");

        ArgumentCaptor<ProcessingOrder> captor = ArgumentCaptor.forClass(ProcessingOrder.class);
        verify(processingOrderMapper).updateById(captor.capture());
        assertThat(captor.getValue().getStatus()).isEqualTo("issued");
        assertThat(captor.getValue().getProcessor()).isEqualTo("朝阳加工厂");
        assertThat(captor.getValue().getExpectedDeliveryDate()).isEqualTo(LocalDate.of(2026, 9, 20));
        assertThat(captor.getValue().getIssuedAt()).isNotNull();

        // 订单联动（issue #4305，用户裁定「发加工 = 订单进入生产中」）：**发加工**才推进
        // 订单 confirmed→producing（生成加工单已不再推进，见 generateSuccess 的 never 断言）
        verify(orderService).updateOrderStatus("order-001", "producing");

        // start
        when(processingOrderMapper.selectOne(any())).thenReturn(po("po-1", "issued"));
        ProcessingOrderUpdateRequest start = new ProcessingOrderUpdateRequest();
        start.setAction("start");
        processingOrderService.updateStatus("po-1", start, TENANT, "u1");
        verify(processingOrderMapper, times(2)).updateById(captor.capture());
        assertThat(captor.getValue().getStatus()).isEqualTo("in_processing");
        assertThat(captor.getValue().getInProcessingAt()).isNotNull();

        // complete：订单保持 producing（不自动 shipped）
        when(processingOrderMapper.selectOne(any())).thenReturn(po("po-1", "in_processing"));
        ProcessingOrderUpdateRequest complete = new ProcessingOrderUpdateRequest();
        complete.setAction("complete");
        processingOrderService.updateStatus("po-1", complete, TENANT, "u1");
        verify(processingOrderMapper, times(3)).updateById(captor.capture());
        assertThat(captor.getValue().getStatus()).isEqualTo("completed");
        verify(orderService, never()).updateOrderStatus(eq("order-001"), eq("shipped"));
        // start/complete **不**再联动订单（订单联动只发生在 issue 这一次）
        verify(orderService, times(1)).updateOrderStatus("order-001", "producing");
    }

    @Test
    @DisplayName("PG-006 非法流转拒绝（generated→completed）")
    void updateStatusIllegalTransitionRejected() {
        when(processingOrderMapper.selectOne(any())).thenReturn(po("po-1", "generated"));

        ProcessingOrderUpdateRequest complete = new ProcessingOrderUpdateRequest();
        complete.setAction("complete");

        assertThatThrownBy(() -> processingOrderService.updateStatus("po-1", complete, TENANT, "u1"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("不允许从");
        verify(processingOrderMapper, never()).updateById(any(ProcessingOrder.class));
    }

    // ── PG-007/008 取消 ────────────────────────────────────────────

    // ── issue #3901：发加工交期禁止过去日期 ──────────────────────────

    @Test
    @DisplayName("issue 传过去交期 → validationError「交付日期不能早于今天」（#3901）")
    void issueRejectsPastDeliveryDate() {
        when(processingOrderMapper.selectOne(any())).thenReturn(po("po-1", "generated"));

        ProcessingOrderUpdateRequest issue = new ProcessingOrderUpdateRequest();
        issue.setAction("issue");
        issue.setExpectedDeliveryDate(LocalDate.now().minusDays(1));

        assertThatThrownBy(() -> processingOrderService.updateStatus("po-1", issue, TENANT, "u1"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("交付日期不能早于今天");
        verify(processingOrderMapper, never()).updateById(any(ProcessingOrder.class));
    }

    @Test
    @DisplayName("issue 交期为今天/未来/空 → 正常流转（#3901）")
    void issueAllowsTodayFutureOrNullDeliveryDate() {
        when(processingOrderMapper.selectOne(any())).thenReturn(po("po-1", "generated"));
        when(processingOrderMapper.updateById(any(ProcessingOrder.class))).thenReturn(1);
        when(orderMapper.selectById("order-001")).thenReturn(confirmedOrder);

        // 今天
        ProcessingOrderUpdateRequest today = new ProcessingOrderUpdateRequest();
        today.setAction("issue");
        today.setExpectedDeliveryDate(LocalDate.now());
        processingOrderService.updateStatus("po-1", today, TENANT, "u1");

        // 未来
        ProcessingOrderUpdateRequest future = new ProcessingOrderUpdateRequest();
        future.setAction("issue");
        future.setExpectedDeliveryDate(LocalDate.now().plusDays(7));
        processingOrderService.updateStatus("po-1", future, TENANT, "u1");

        // 空（交期可选）
        ProcessingOrderUpdateRequest empty = new ProcessingOrderUpdateRequest();
        empty.setAction("issue");
        processingOrderService.updateStatus("po-1", empty, TENANT, "u1");

        ArgumentCaptor<ProcessingOrder> captor = ArgumentCaptor.forClass(ProcessingOrder.class);
        verify(processingOrderMapper, times(3)).updateById(captor.capture());
        assertThat(captor.getAllValues().get(0).getExpectedDeliveryDate()).isEqualTo(LocalDate.now());
        assertThat(captor.getAllValues().get(1).getExpectedDeliveryDate()).isEqualTo(LocalDate.now().plusDays(7));
        assertThat(captor.getAllValues().get(2).getExpectedDeliveryDate()).isNull();
    }

    @Test
    @DisplayName("PG-007 取消（generated）→ 加工单 cancelled；订单仍 confirmed ⇒ **不触发**回退（#4305 新时点）")
    void cancelGeneratedDoesNotRevertOrder() {
        when(processingOrderMapper.selectOne(any())).thenReturn(po("po-1", "generated"));
        when(processingOrderMapper.updateById(any(ProcessingOrder.class))).thenReturn(1);
        // #4305 后：generated 态加工单对应的订单**从未**进入 producing（生成不推进、发加工才推进）
        when(orderMapper.selectById("order-001")).thenReturn(confirmedOrder);

        ProcessingOrderUpdateRequest cancel = new ProcessingOrderUpdateRequest();
        cancel.setAction("cancel");
        cancel.setReason("加工方排期冲突");
        processingOrderService.updateStatus("po-1", cancel, TENANT, "u1");

        ArgumentCaptor<ProcessingOrder> captor = ArgumentCaptor.forClass(ProcessingOrder.class);
        verify(processingOrderMapper).updateById(captor.capture());
        assertThat(captor.getValue().getStatus()).isEqualTo("cancelled");
        assertThat(captor.getValue().getCancelledReason()).isEqualTo("加工方排期冲突");
        // 订单本就 confirmed ⇒ 回退是空动作（revert 会因「非 producing」抛 409）
        verify(orderService, never()).revertProducingToConfirmed(anyString(), anyString());
    }

    @Test
    @DisplayName("PG-007 取消（issued，已发加工 ⇒ 订单 producing）→ 订单 producing→confirmed 回退")
    void cancelIssuedRevertsOrder() {
        when(processingOrderMapper.selectOne(any())).thenReturn(po("po-1", "issued"));
        when(processingOrderMapper.updateById(any(ProcessingOrder.class))).thenReturn(1);
        Order producing = Order.builder().id("order-001").tenantId(TENANT).status("producing").build();
        when(orderMapper.selectById("order-001")).thenReturn(producing);

        ProcessingOrderUpdateRequest cancel = new ProcessingOrderUpdateRequest();
        cancel.setAction("cancel");
        cancel.setReason("加工方排期冲突");
        processingOrderService.updateStatus("po-1", cancel, TENANT, "u1");

        ArgumentCaptor<ProcessingOrder> captor = ArgumentCaptor.forClass(ProcessingOrder.class);
        verify(processingOrderMapper).updateById(captor.capture());
        assertThat(captor.getValue().getStatus()).isEqualTo("cancelled");
        verify(orderService).revertProducingToConfirmed(eq("order-001"), anyString());
    }

    // ── issue #4305：发加工联动的 fail-closed 负例（形态同 generate 的落库失败回退）──

    @Test
    @DisplayName("#4305 发加工落库失败 → 订单联动先行已推进 ⇒ 回退 confirmed + 异常传播（无孤儿态）")
    void issueLinkageRollsBackOrderWhenPersistFails() {
        when(processingOrderMapper.selectOne(any())).thenReturn(po("po-1", "generated"));
        when(orderMapper.selectById("order-001")).thenReturn(confirmedOrder);
        when(processingOrderMapper.updateById(any(ProcessingOrder.class)))
                .thenThrow(new RuntimeException("db down"));

        ProcessingOrderUpdateRequest issue = new ProcessingOrderUpdateRequest();
        issue.setAction("issue");

        assertThatThrownBy(() -> processingOrderService.updateStatus("po-1", issue, TENANT, "u1"))
                .isInstanceOf(RuntimeException.class);
        // 联动先行：订单先 confirmed→producing；加工单落库失败 ⇒ 回退订单，杜绝
        // 「订单生产中、加工单未发出」的孤儿态（与 #3345 P2② 给 generate 的同款 fail-closed）
        verify(orderService).updateOrderStatus("order-001", "producing");
        verify(orderService).revertProducingToConfirmed(eq("order-001"), anyString());
    }

    @Test
    @DisplayName("#4305 发加工：订单已是 producing（旧语义存量数据）⇒ 不重复推进、也不回退")
    void issueSkipsLinkageWhenOrderAlreadyProducing() {
        when(processingOrderMapper.selectOne(any())).thenReturn(po("po-1", "generated"));
        when(processingOrderMapper.updateById(any(ProcessingOrder.class))).thenReturn(1);
        Order producing = Order.builder().id("order-001").tenantId(TENANT).status("producing").build();
        when(orderMapper.selectById("order-001")).thenReturn(producing);

        ProcessingOrderUpdateRequest issue = new ProcessingOrderUpdateRequest();
        issue.setAction("issue");
        processingOrderService.updateStatus("po-1", issue, TENANT, "u1");

        verify(orderService, never()).updateOrderStatus(anyString(), anyString());
        verify(orderService, never()).revertProducingToConfirmed(anyString(), anyString());
    }

    @Test
    @DisplayName("PG-008 取消必填原因")
    void cancelRequiresReason() {
        when(processingOrderMapper.selectOne(any())).thenReturn(po("po-1", "generated"));

        ProcessingOrderUpdateRequest cancel = new ProcessingOrderUpdateRequest();
        cancel.setAction("cancel");

        assertThatThrownBy(() -> processingOrderService.updateStatus("po-1", cancel, TENANT, "u1"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("必须填写原因");
    }

    @Test
    @DisplayName("completed 冻结：取消被拒")
    void cancelCompletedFrozen() {
        when(processingOrderMapper.selectOne(any())).thenReturn(po("po-1", "completed"));

        ProcessingOrderUpdateRequest cancel = new ProcessingOrderUpdateRequest();
        cancel.setAction("cancel");
        cancel.setReason("测试");

        assertThatThrownBy(() -> processingOrderService.updateStatus("po-1", cancel, TENANT, "u1"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("不允许从");
    }

    // ── PG-011 租户隔离 ────────────────────────────────────────────

    @Test
    @DisplayName("PG-011 跨租户加工单解析 → notFound")
    void tenantIsolation() {
        // 其它租户数据：resolve 条件带 tenant_id，selectOne 返回 null → notFound
        when(processingOrderMapper.selectOne(any())).thenReturn(null);

        ProcessingOrderUpdateRequest issue = new ProcessingOrderUpdateRequest();
        issue.setAction("issue");

        assertThatThrownBy(() -> processingOrderService.updateStatus("JG-OTHER-0001", issue, TENANT, "u1"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("加工单");
    }

    // ── 查询 ───────────────────────────────────────────────────────

    @Test
    @DisplayName("详情返回：快照解析 + 订单信息回填")
    void detailAssemblesResponse() {
        ProcessingOrder po = po("po-1", "issued");
        po.setProcessor("朝阳加工厂");
        when(processingOrderMapper.selectOne(any())).thenReturn(po);
        when(orderMapper.selectById("order-001")).thenReturn(confirmedOrder);

        ProcessingOrderResponse resp = processingOrderService.getDetail("po-1", TENANT);

        assertThat(resp.getOrderNo()).isEqualTo("ORD-20260912-0001");
        assertThat(resp.getCustomerName()).isEqualTo("张三");
        assertThat(resp.getStatus()).isEqualTo("issued");
        assertThat(resp.getItems()).hasSize(1);
        assertThat(resp.getItems().get(0).getProductName()).isEqualTo("布艺遮光帘A");
        assertThat(resp.getItems().get(0).getColorName()).isEqualTo("米白");
        assertThat(resp.getItems().get(0).getProcessingItems()).hasSize(1);
    }

    @Test
    @DisplayName("#4387 判据 1（回显）：快照 openCount=3（三开）⇒ 加工单详情响应原样透出 3")
    void detailExposesThreePanelOpenCount() {
        Map<String, Object> entry = craftSpecSnapshotEntry();
        entry.put("openCount", 3);
        ProcessingOrder po = po("po-1", "issued");
        po.setItemsSnapshot(List.of(entry));
        when(processingOrderMapper.selectOne(any())).thenReturn(po);
        when(orderMapper.selectById("order-001")).thenReturn(confirmedOrder);

        ProcessingOrderResponse resp = processingOrderService.getDetail("po-1", TENANT);

        assertThat(resp.getItems()).hasSize(1);
        assertThat(resp.getItems().get(0).getOpenCount())
                .as("三开是可回显的真值（1/2/4 白名单式过滤会把它丢掉 —— 那是静默丢值）")
                .isEqualTo(3);
    }

    @Test
    @DisplayName("#4354 §4.9 第③处展示：加工单详情响应必须透出 craft spec（DTO 未声明 ⇒ 未知属性 ⇒ items 整段 null）")
    void detailExposesCraftSpecForDisplay() {
        ProcessingOrder po = po("po-1", "issued");
        po.setItemsSnapshot(List.of(craftSpecSnapshotEntry()));
        when(processingOrderMapper.selectOne(any())).thenReturn(po);
        when(orderMapper.selectById("order-001")).thenReturn(confirmedOrder);

        ProcessingOrderResponse resp = processingOrderService.getDetail("po-1", TENANT);

        assertThat(resp.getItems())
                .as("快照出现 DTO 未声明的键 ⇒ Jackson 未知属性 ⇒ items 整段退化成 null（响应静默）")
                .isNotNull().hasSize(1);
        ProcessingOrderResponse.ProcessingOrderItemBrief brief = resp.getItems().get(0);
        assertThat(brief.getItemId()).isEqualTo("item-1");
        assertThat(brief.getCurtainType()).isEqualTo("纱帘");
        assertThat(brief.getCraft()).isEqualTo("打孔");
        assertThat(brief.getCuttingMode()).isEqualTo("定高买宽");
        assertThat(brief.getOpenCount()).isEqualTo(2);
        assertThat(brief.getIsShaped()).isEqualTo(false);
        assertThat(brief.getPleatSpacing()).isEqualTo(new BigDecimal("0.1"));
        assertThat(brief.getHasPattern()).isEqualTo(true);
        assertThat(brief.getPatternRepeat()).isEqualTo(new BigDecimal("0.6"));
        assertThat(brief.getStyle()).isEqualTo("拼色");
        assertThat(brief.getBatchNo()).isEqualTo("B-20260918");
        assertThat(brief.getComponentRole()).isEqualTo("主布");
        assertThat(brief.getCraftLineId()).isEqualTo("item-1");
        assertThat(brief.getMetersSource()).isEqualTo("跟随主布");
        assertThat(brief.getProcessingMeters()).isEqualTo(new BigDecimal("12.3"));
        assertThat(brief.getFabricMeters()).isEqualTo(new BigDecimal("12.3"));
        assertThat(brief.getPleatCount()).isEqualTo(24);
        assertThat(brief.getPerPanelPleats()).isEqualTo(12);
        assertThat(brief.getPanels()).isEqualTo(4);
        assertThat(brief.getHoles()).isEqualTo(73.8);
        assertThat(brief.getFullness()).isEqualTo(new BigDecimal("2.0"));
        assertThat(brief.getFullnessActual()).isEqualTo(new BigDecimal("1.95"));
        assertThat(brief.getRoom()).as("快照里没有的键 → 响应就是 null（不造值）").isNull();
    }

    // ── 验收复核修复（PR #3345）：生成竞态/并发重复 ──────────────────

    @Test
    @DisplayName("验收实战回归：快照为 JSON 字符串（自定义 @Select 形态）→ 详情仍能解析出条目")
    void detailWithJsonStringSnapshot() {
        ProcessingOrder po = po("po-1", "generated");
        po.setItemsSnapshot("[{\"productName\":\"布艺遮光帘A\",\"colorName\":\"米白\","
                + "\"processingItems\":[{\"id\":\"p1\",\"name\":\"打孔\"}]}]");
        when(processingOrderMapper.selectOne(any())).thenReturn(po);
        when(orderMapper.selectById("order-001")).thenReturn(confirmedOrder);

        ProcessingOrderResponse resp = processingOrderService.getDetail("po-1", TENANT);

        assertThat(resp.getItems()).hasSize(1);
        assertThat(resp.getItems().get(0).getProductName()).isEqualTo("布艺遮光帘A");
        assertThat(resp.getItems().get(0).getColorName()).isEqualTo("米白");
        assertThat(resp.getItems().get(0).getProcessingItems()).hasSize(1);
    }

    @Test
    @DisplayName("验收实战回归：processingInfo 为 JSON 字符串（自定义 @Select 形态）→ 仍能生成加工单")
    void generateWithJsonStringProcessingInfo() {
        stubLibrary();
        OrderItem item = OrderItem.builder()
                .id("item-1").tenantId(TENANT).orderId("order-001")
                .productName("布艺遮光帘A").quantity(BigDecimal.valueOf(2))
                .width(new BigDecimal("2.5")).height(new BigDecimal("2.8"))
                .processingInfo("{\"processingFee\":30,\"colorName\":\"米白\","
                        + "\"processingItems\":[{\"id\":\"p1\",\"name\":\"打孔\",\"unitPrice\":3,\"quantity\":10,\"unit\":\"米\"}]}")
                .build();
        when(orderMapper.selectById("order-001")).thenReturn(confirmedOrder);
        when(orderItemMapper.selectList(any())).thenReturn(List.of(item));
        when(processingOrderMapper.selectActiveByOrderId("order-001", TENANT)).thenReturn(null);
        when(processingItemMapper.selectById("p1")).thenReturn(null);
        when(processingOrderMapper.insert(any(ProcessingOrder.class))).thenReturn(1);

        var results = processingOrderService.generate(List.of("order-001"), TENANT, "u1");

        assertThat(results.get(0).isSuccess()).isTrue();
        ArgumentCaptor<ProcessingOrder> captor = ArgumentCaptor.forClass(ProcessingOrder.class);
        verify(processingOrderMapper).insert(captor.capture());
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> snapshot = (List<Map<String, Object>>) captor.getValue().getItemsSnapshot();
        assertThat(snapshot).hasSize(1);
        assertThat(snapshot.get(0).get("colorName")).isEqualTo("米白");
    }

    @Test
    @DisplayName("并发重复生成（DuplicateKeyException）→ 幂等失败结果；**不**联动订单（#4305）")
    void generateConcurrentDuplicateRejectedIdempotently() {
        stubLibrary();
        when(orderMapper.selectById("order-001")).thenReturn(confirmedOrder);
        when(orderItemMapper.selectList(any()))
                .thenReturn(List.of(orderItemWithProcessing("米白")));
        when(processingOrderMapper.selectActiveByOrderId("order-001", TENANT)).thenReturn(null);
        when(processingOrderMapper.insert(any(ProcessingOrder.class)))
                .thenThrow(new org.springframework.dao.DuplicateKeyException("uk_processing_orders_active"));

        var results = processingOrderService.generate(List.of("order-001"), TENANT, "u1");

        assertThat(results.get(0).isSuccess()).isFalse();
        assertThat(results.get(0).getMessage()).contains("已生成");
        // #4305：生成既不推进订单、也无「先推进后回退」可言（时点在发加工）⇒ 订单状态全程不动
        verify(orderService, never()).updateOrderStatus(anyString(), anyString());
        verify(orderService, never()).revertProducingToConfirmed(anyString(), anyString());
    }

    @Test
    @DisplayName("生成落库失败（非重复）→ 异常传播（整批回滚）；订单状态不动（#4305）")
    void generateInsertFailurePropagates() {
        stubLibrary();
        when(orderMapper.selectById("order-001")).thenReturn(confirmedOrder);
        when(orderItemMapper.selectList(any()))
                .thenReturn(List.of(orderItemWithProcessing("米白")));
        when(processingOrderMapper.selectActiveByOrderId("order-001", TENANT)).thenReturn(null);
        when(processingOrderMapper.insert(any(ProcessingOrder.class)))
                .thenThrow(new RuntimeException("db down"));

        assertThatThrownBy(() -> processingOrderService.generate(List.of("order-001"), TENANT, "u1"))
                .isInstanceOf(RuntimeException.class);
        verify(orderService, never()).updateOrderStatus(anyString(), anyString());
        verify(orderService, never()).revertProducingToConfirmed(anyString(), anyString());
    }

    // ══════════════════ 存量单补工序的派生 + 打印计数（issue #4202）══════════════════

    @Test
    @DisplayName("#4202 派生 payload：复用生成路径的工序库路线（部位=加工产物名+色号，工序逐字取库）")
    @SuppressWarnings("unchecked")
    void derivePositionPayloadUsesOperationLibrary() {
        stubLibrary();
        when(orderMapper.selectById("order-001")).thenReturn(confirmedOrder);
        when(orderItemMapper.selectList(any())).thenReturn(List.of(orderItemHanzhe("米白")));

        List<Map<String, Object>> positions = processingOrderService.derivePositionPayload("order-001", TENANT);

        assertThat(positions).hasSize(1);
        assertThat(positions.get(0).get("position_name")).isEqualTo("布艺遮光帘A 米白");
        List<Map<String, Object>> operations = (List<Map<String, Object>>) positions.get(0).get("operations");
        assertThat(operations).hasSize(11);
        assertThat(operations.get(0)).containsEntry("operation", "精裁-布")
                .containsEntry("group", "裁剪").containsEntry("unit", "米")
                .containsEntry("is_start_marker", true);
        assertThat((BigDecimal) operations.get(0).get("unit_price")).isEqualByComparingTo("0.4");
        assertThat((BigDecimal) operations.get(0).get("qty"))
                .as("应做数量 = 算料引擎输出（issue #4208：米类 12.3，**不是**订单数量 2）")
                .isEqualByComparingTo(CALC_FABRIC_METERS);
        assertThat(operations.get(0).get("qty_source")).isEqualTo("fabric_meters");
        assertThat((BigDecimal) operations.get(2).get("qty"))
                .as("折类 = 折数（走查实测的红证形态：韩褶-布 曾显示 3 折）")
                .isEqualByComparingTo(CALC_PLEAT_COUNT);
        assertThat(operations.get(2).get("qty_source")).isEqualTo("pleat_count");
        assertThat(operations.get(9).get("qty_source"))
                .as("套类 = 引擎待补键 ⇒ 显式标注 fallback（不静默）").isEqualTo("fallback");
        assertThat(operations.get(9)).containsEntry("operation", "外帘装袋")
                .containsEntry("is_must_finish", true);
    }

    @Test
    @DisplayName("#4202 派生 fail-closed：工序库无路线 ⇒ 中止（绝不返回空 payload 落个空壳）")
    void derivePositionPayloadFailsClosedOnEmptyLibrary() {
        stubEmptyLibrary();
        when(orderMapper.selectById("order-001")).thenReturn(confirmedOrder);
        when(orderItemMapper.selectList(any())).thenReturn(List.of(orderItemHanzhe("米白")));

        assertThatThrownBy(() -> processingOrderService.derivePositionPayload("order-001", TENANT))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("工序库");
    }

    @Test
    @DisplayName("#4202 派生：订单不存在（含跨租户）⇒ 404，不静默返回空")
    void derivePositionPayloadUnknownOrderNotFound() {
        when(orderMapper.selectById("order-x")).thenReturn(null);
        when(orderMapper.selectOne(any())).thenReturn(null);

        assertThatThrownBy(() -> processingOrderService.derivePositionPayload("order-x", TENANT))
                .isInstanceOf(BusinessException.class);
    }

    @Test
    @DisplayName("#4202 打印计数：SQL 内原子自增并返回新计数（此前 print_count 零写方）")
    void recordPrintIncrementsCounter() {
        when(processingOrderMapper.selectOne(any())).thenReturn(ProcessingOrder.builder()
                .id("po-001").tenantId(TENANT).orderId("order-001")
                .processingOrderNo("JG-20260918-0001").status("generated").printCount(2).deleted(0)
                .build());
        when(processingOrderMapper.incrementPrintCount(eq("po-001"), eq(TENANT), any())).thenReturn(1);
        when(processingOrderMapper.selectById("po-001")).thenReturn(ProcessingOrder.builder()
                .id("po-001").tenantId(TENANT).orderId("order-001")
                .processingOrderNo("JG-20260918-0001").status("generated").printCount(3).deleted(0)
                .build());

        Map<String, Object> result = processingOrderService.recordPrint("order-001", TENANT);

        assertThat(result.get("order_id")).isEqualTo("order-001");
        assertThat(result.get("processing_order_no")).isEqualTo("JG-20260918-0001");
        assertThat(result.get("print_count")).isEqualTo(3);
        verify(processingOrderMapper).incrementPrintCount(eq("po-001"), eq(TENANT), any());
    }

    @Test
    @DisplayName("#4202 打印计数：无加工单 ⇒ 404（不静默返回 0 或凭空造计数）")
    void recordPrintWithoutProcessingOrderNotFound() {
        when(processingOrderMapper.selectOne(any())).thenReturn(null);

        assertThatThrownBy(() -> processingOrderService.recordPrint("order-001", TENANT))
                .isInstanceOf(BusinessException.class);

        verify(processingOrderMapper, never()).incrementPrintCount(any(), any(), any());
    }

    // ── 列表查询 N+1（issue #4304）────────────────────────────────
    //
    // 实测（issue #4304）：GET /api/admin/processing-orders 31 行 ≈ 2.0s，SQL 日志同一请求窗口
    // 里 `FROM orders` 单行查询 63 条（31 行 × 2 次请求）——根因是 list() 逐行 toResponse()，
    // 而 toResponse() 内部 orderMapper.selectById(po.getOrderId()) 只为拿 orderNo/customerName/customerPhone。
    // 下列两条用例的**红证**：修复前逐行 selectById ⇒ `never()` / `times(1)` 断言必红。

    /** 列表真值构造：N 行加工单 + 与之一一对应的订单（订单号/客户名/电话逐行可区分）。 */
    private List<Order> ordersFor(int count) {
        List<Order> orders = new ArrayList<>();
        for (int i = 0; i < count; i++) {
            orders.add(Order.builder()
                    .id("order-" + i)
                    .tenantId(TENANT)
                    .orderNo("ORD-20260912-" + String.format("%04d", i))
                    .customerName("客户" + i)
                    .customerPhone("13800138" + String.format("%03d", i))
                    .build());
        }
        return orders;
    }

    /** 列表真值构造：N 行加工单，orderId 逐行不同（防「按位取错订单」）。 */
    private List<ProcessingOrder> processingOrdersFor(int count) {
        List<ProcessingOrder> rows = new ArrayList<>();
        for (int i = 0; i < count; i++) {
            ProcessingOrder po = po("po-" + i, "issued");
            po.setOrderId("order-" + i);
            po.setProcessingOrderNo("JG-20260912-" + String.format("%04d", i));
            rows.add(po);
        }
        return rows;
    }

    /** 逐行比对：orderId / orderNo / customerName / customerPhone 必须与订单真值**一一对应**。 */
    private void assertOrderFieldsAligned(List<ProcessingOrderResponse> result) {
        List<ProcessingOrder> truth = processingOrdersFor(result.size());
        List<String> orderIds = new ArrayList<>();
        List<String> poNos = new ArrayList<>();
        for (int i = 0; i < result.size(); i++) {
            assertThat(result.get(i).getOrderNo()).isEqualTo("ORD-20260912-" + String.format("%04d", i));
            assertThat(result.get(i).getCustomerName()).isEqualTo("客户" + i);
            assertThat(result.get(i).getCustomerPhone()).isEqualTo("13800138" + String.format("%03d", i));
            orderIds.add(result.get(i).getOrderId());
            poNos.add(result.get(i).getProcessingOrderNo());
        }
        // 加工单号与订单号必须**同行对齐**（批量结果按 orderId 建映射，不得按查询返回顺序错位）
        assertThat(orderIds).containsExactlyElementsOf(
                truth.stream().map(ProcessingOrder::getOrderId).toList());
        assertThat(poNos).containsExactlyElementsOf(
                truth.stream().map(ProcessingOrder::getProcessingOrderNo).toList());
    }

    @Test
    @DisplayName("#4304 列表 31 行：订单**一次批量取回**，逐行 selectById 调用 0 次（N+1 红证）")
    void listLoadsOrdersInOneBatchInsteadOfPerRow() {
        when(processingOrderMapper.selectList(any())).thenReturn(processingOrdersFor(31));
        when(orderMapper.selectBatchIds(anyCollection())).thenReturn(ordersFor(31));

        List<ProcessingOrderResponse> result = processingOrderService.list(null, null, TENANT);

        assertThat(result).hasSize(31);
        // 红证①：修复前这里 31 次
        verify(orderMapper, never()).selectById(anyString());
        // 红证②：修复前这里是 0 次
        verify(orderMapper, times(1)).selectBatchIds(anyCollection());
        // 防「批量查询少取字段/按位错配」：逐行与订单真值相等
        assertOrderFieldsAligned(result);
    }

    @Test
    @DisplayName("#4304 列表关键字路径：同样一次批量取回订单（selectByKeyword 分支不回归 N+1）")
    void listByKeywordAlsoLoadsOrdersInOneBatch() {
        when(processingOrderMapper.selectByKeyword(eq("JG-20260912"), eq(TENANT)))
                .thenReturn(processingOrdersFor(5));
        when(orderMapper.selectBatchIds(anyCollection())).thenReturn(ordersFor(5));

        List<ProcessingOrderResponse> result = processingOrderService.list("JG-20260912", null, TENANT);

        assertThat(result).hasSize(5);
        verify(orderMapper, never()).selectById(anyString());
        verify(orderMapper, times(1)).selectBatchIds(anyCollection());
        assertOrderFieldsAligned(result);
    }

    @Test
    @DisplayName("#4304 空列表：不下发空 IN 查询（无行 ⇒ 零次订单查询）")
    void listWithNoRowsQueriesNoOrders() {
        when(processingOrderMapper.selectList(any())).thenReturn(List.of());

        assertThat(processingOrderService.list(null, null, TENANT)).isEmpty();

        verify(orderMapper, never()).selectById(anyString());
        verify(orderMapper, never()).selectBatchIds(anyCollection());
    }

    @Test
    @DisplayName("#4304 详情路径不回归：getDetail 仍按单条 selectById 取订单（不改签名语义）")
    void getDetailStillLoadsOrderBySingleSelect() {
        when(processingOrderMapper.selectOne(any())).thenReturn(po("po-1", "issued"));
        when(orderMapper.selectById("order-001")).thenReturn(confirmedOrder);

        ProcessingOrderResponse resp = processingOrderService.getDetail("po-1", TENANT);

        assertThat(resp.getOrderNo()).isEqualTo("ORD-20260912-0001");
        verify(orderMapper, times(1)).selectById("order-001");
        verify(orderMapper, never()).selectBatchIds(anyCollection());
    }
}
