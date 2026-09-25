package com.migao.admin.service;
// case_ids: PG-001, PG-002, PG-003, PG-004, PG-005, PG-006, PG-007, PG-008, PG-011, PG-018, PG-019, PG-022, PG-023, PG-025, PG-060, UI-030, PR-068, PR-069, PR-070, PR-077

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
import com.migao.admin.entity.ProductionRouteRule;
import com.migao.admin.entity.ProductionRouteSignal;
import com.migao.admin.entity.ProductionRouteTemplate;
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
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

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

    /**
     * 批次消耗台账（V116 / issue #5145 阶段 1）：派工扣批次 / 作废回补。
     * 它**不在** {@code ProcessingOrderService} 的构造签名里（字段注入，见其字段注释）⇒
     * 装配点有两处：{@link #realChainService()}（手写 new）与 {@code setUp()}（{@code @InjectMocks} 那个实例）。
     */
    @Mock
    private StockBatchConsumptionService stockBatchConsumptionService;

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
            // 🔴 issue #4937 / O4：`打包` **在主线上的位置**（`外帘打卷` 与 `外帘装袋` 之间）。
            // 旧口径下 `打包 × 布帘` 是 `applicable=FALSE` ⇒ 被过滤掉；过滤退场后它跟着主线进路线
            // ⇒ 本夹具（= 真实实例序列的镜像）必须带上它，否则既有断言全部逐字不符。
            {"打包", "后道", "套", "0.0", "false", "false"},
            {"外帘装袋", "后道", "套", "1.0", "true", "false"},
            {"外帘发货", "后道", "套", "1.0", "false", "false"}};

    /** rt-v54-02 布帘×打孔 —— 11 道（10 道旧快照 + `打包`，见上）。 */
    private static final String[][] V54_BULIAN_DAKONG = {
            {"精裁-布", "裁剪", "米", "0.4", "false", "true"},
            {"布三边", "车位", "米", "0.4", "false", "false"},
            {"打孔-布", "车位", "孔", "0.15", "false", "false"},
            {"熨烫-布", "后道", "米", "0.35", "false", "false"},
            {"定型-布", "后道", "米", "0.4", "false", "false"},
            {"复烫-布", "后道", "米", "0.35", "false", "false"},
            {"布帘车被", "后道", "米", "0.4", "false", "false"},
            {"外帘打卷", "后道", "套", "1.0", "false", "false"},
            {"打包", "后道", "套", "0.0", "false", "false"},
            {"外帘装袋", "后道", "套", "1.0", "true", "false"},
            {"外帘发货", "后道", "套", "1.0", "false", "false"}};

    /**
     * **纱帘×打孔**的实例序列 —— **11 道**（issue #4937 去部位化后的新基线）。
     *
     * <p>⚠️ **基线换代**：旧值是 V58 种子的 6 道（`精裁-纱/纱三边/打孔-纱/外帘打卷/外帘装袋/外帘发货`）。
     * `applicable` 过滤退场后，纱帘路线也走**与布帘同一条工艺序列**（用户裁定「部位不再参与
     * 任何取价、取路、筛选、配置」）⇒ 6 → 11 道（多出 `熨烫-纱/定型-纱/复烫-纱/车被-纱/打包`）。
     * 变体名仍是纱帘专属的（`-纱`），这正是「同一工艺、不同帘种的工人端变体」。</p>
     */
    private static final String[][] V58_SHALU_DAKONG = {
            {"精裁-纱", "裁剪", "米", "0.4", "false", "true"},
            {"纱三边", "车位", "米", "0.4", "false", "false"},
            {"打孔-纱", "车位", "孔", "0.15", "false", "false"},
            {"熨烫-纱", "后道", "米", "0.35", "false", "false"},
            {"定型-纱", "后道", "米", "0.4", "false", "false"},
            {"复烫-纱", "后道", "米", "0.35", "false", "false"},
            {"车被-纱", "后道", "米", "0.4", "false", "false"},
            {"外帘打卷", "后道", "套", "1.0", "false", "false"},
            {"打包", "后道", "套", "0.0", "false", "false"},
            {"外帘装袋", "后道", "套", "1.0", "true", "false"},
            {"外帘发货", "后道", "套", "1.0", "false", "false"}};

    /**
     * **套级**工序（`scope='set'`，V67 / issue #4384 A1）—— **逐字抄自 V67 的 UPDATE 名单**：
     * `外帘打卷` / `外帘装袋` / `外帘发货`（真值源 §8：「外帘是加工单打印行部位，**不是**路线键」）。
     * 其余工序 = 部位级 `position`（V67 的列默认值）。
     *
     * <p>⚠️ 本常量只用来把**库桩**造成 V67 终态 —— 生产代码**不得**用名字判套级（那是「常量散在代码里、
     * 商家改了库不生效」的形态）：判据必须是工序库行带出的 `scope`。判别力由
     * {@link #setLevelDedupFollowsLibraryScopeNotOperationNames()} 的注入法保证。</p>
     */
    private static final Set<String> SET_SCOPE_OPERATIONS =
            // 🔴 issue #4937：`打包` 也是套级（`scope='set'`，V79）—— 原来它被 `applicable` 过滤
            // 挡在布帘路线之外，本夹具里不需要它；过滤退场后它进路线 ⇒ 必须与库口径同步，
            // 否则「部位级 / 套级」的分组会把它算错。
            Set.of("外帘打卷", "外帘装袋", "外帘发货", "打包");

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
     * 工序库桩（**新结构**，P2b / issue #4459）：把「默认路线模板 + 规则表 26 行 + 部位价目
     * + 工序库元数据」装进新读面。
     *
     * <p>与旧桩的差别：旧桩直接把 9 条「{@code (部位×工艺)} 展开快照」塞给 {@code findRouting}；
     * 新桩只给**输入**（模板/规则/价目/工序库），**展开由生产代码做**（
     * {@code ProcessingOrderService.buildRoute}，与 {@code routing.py::build_route_v2} 逐字一致）
     * ⇒ 「实例 = 库」的断言仍是真比对，而不是拿一份平行真值自证。</p>
     *
     * <p>夹具覆盖三条路线（布帘×韩褶 11 / 布帘×打孔 10 / 纱帘×打孔 6 道）用到的全部工序 ——
     * 它们是 V54/V58 种子的逐字快照。默认模板 = 布帘/纱帘/帘头三部位共用（与 V71 种子同形），
     * 故「帘头×平幔」取到的是默认模板（与旧桩的回落语义一致）。</p>
     *
     * <p>同时装信号映射表（V60，issue #4308）：派生**读库而非读常量** ⇒
     * 「库中映射命中的优先级高于默认」这条判据依赖本桩，缺了它所有派生用例都退化成 T1。</p>
     */
    private void stubLibrary() {
        // lenient：**污染形态**用例（issue #4609）要把路线模板换成自己那一份 ⇒ 本桩备而不用；
        // Mockito 严格桩会把「备而不用」判为失败 —— 那是噪音，不是缺陷（与下面几条同因）。
        lenient().when(productionOperationQueryService.routeTemplateFor(eq(TENANT), anyString()))
                .thenAnswer(inv -> {
                    String position = inv.getArgument(1);
                    return RoutingModelFixture.defaultTemplate(TENANT).getPositions() instanceof List<?> ps
                            && ps.contains(position)
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
        // 缺 `craft` 的兜底 = **该租户的默认工艺**（商家可配；issue #4459 起不再写死常量）
        lenient().when(productionOperationQueryService.defaultCraft(TENANT)).thenReturn("韩褶");
        lenient().when(productionOperationQueryService.normalizeOperationName(anyString()))
                .thenAnswer(inv -> RoutingModelFixture.logicalName(inv.getArgument(0)));
        lenient().when(productionOperationQueryService.variantNameOf(anyString(), any(), any()))
                .thenAnswer(inv -> RoutingModelFixture.variantNameOf(
                        inv.getArgument(0), inv.getArgument(1), inv.getArgument(2)));
        // lenient：**直读**路径（订单带 curtainType + craft，issue #4354）根本不查信号映射表
        // ⇒ 该桩备而不用；Mockito 严格桩会把「备而不用」判为失败 —— 那是噪音，不是缺陷。
        lenient().when(productionOperationQueryService.routeSignals(TENANT)).thenReturn(v60Signals());
    }

    /**
     * 空库桩（V71/V72 种子未执行 / 全软删）：该租户**没有默认路线模板** ⇒
     * {@code resolveRoute} 的 T3 fail-closed（不回退常量、不回退加工项目录）。
     */
    private void stubEmptyLibrary() {
        // lenient：空库时「零默认工艺」与「零路线模板」两条 fail-closed 都成立，
        // 先撞哪一条是实现细节 ⇒ 不被走的桩不该判失败（那是噪音，不是缺陷）。
        lenient().when(productionOperationQueryService.routeTemplateFor(eq(TENANT), anyString())).thenReturn(null);
        lenient().when(productionOperationQueryService.defaultRouteTemplate(TENANT)).thenReturn(null);
        lenient().when(productionOperationQueryService.defaultCraft(TENANT)).thenReturn(null);
        lenient().when(productionOperationQueryService.routingKeys(TENANT)).thenReturn(List.of());
    }

    // ── 算料数量桩（issue #4208 接线）────────────────────────────────
    //
    // 应做数量的真值源在 ai-agent（routing.py::_qty_for），Java 侧只问不猜。本桩按**工序单位**
    // 给出与端点同口径的取值（数量来自算料键 + 来源三态 + 缺键兜底 1）：
    //   米 ⇒ **该部位自己的** `calc_info.fabric_meters`（缺键 ⇒ 兜底 1 + `fallback`；端点 METER_KEYS 直采）
    //   折 ⇒ 24 / pleat_count ｜ 孔 ⇒ 73.8 / fabric_meters_x6
    //   幅・套・个 ⇒ 1 / fallback（引擎暂未产出 panels/set_count，见 routing.py 的待补键注释）
    // ⚠️ 米轴**必须读请求体**（issue #4337）：旧形态恒 12.3 / `fabric_meters` 是与 `calc_info` **无关的
    // 平行真值** ⇒「米类 qty」一族断言对「`fabric_meters` 压根没送出去」不敏感（假绿），而任何人
    // **正确地**把它改成 calc_info-aware 时那些断言又会**假红**（实测：3 条红，读数 12.3 ≠ 2）。
    // ⇒ 现在「实例 qty = 客户端输出」在**米轴**上也是真比对，而不是拿一份平行真值自证。

    /** **订单侧已带 `calc_output` 夹具**的米数（那些夹具的 `calc_info.fabric_meters` 就是它，见 #4354 一族）。 */
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
                        // #4337：读**该部位自己的** `calc_info`（端点 METER_KEYS 直采）；缺键 ⇒ 兜底 1 + fallback
                        Object meters = calcInfoOf(position).get("fabric_meters");
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
        });
    }

    /** 请求行里的 `calc_info`（缺键 / 非 Map ⇒ 空表 ⇒ 各轴一律按缺键口径走兜底）。 */
    private static Map<?, ?> calcInfoOf(Map<String, Object> position) {
        return position.get("calc_info") instanceof Map<?, ?> calc ? calc : Map.of();
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

    /**
     * 特殊选项读面的桩（P2b：规则表 + 计件系数档 + 工序库元数据，逐字对齐 V71/V72 种子）。
     *
     * <p>与 {@link #stubLibrary} 的关系：那个已装「模板 + 规则 26 行 + 系数档 + 工序库」；
     * 本方法**只**为「带特殊选项」的用例再显式声明一遍（可读性：这些用例的判据依赖哪几行一目了然）。</p>
     */
    private void stubOptionTables() {
        lenient().when(productionOperationQueryService.routeRules(TENANT))
                .thenReturn(RoutingModelFixture.rulesWithFactors(TENANT));
        lenient().when(productionOperationQueryService.operationsByName(TENANT))
                .thenReturn(RoutingModelFixture.catalog());
    }

    /** 带特殊选项的订单明细（布帘×韩褶路线，与 orderItemHanzhe 同源，只多 specialOptions）。 */
    @SuppressWarnings("unchecked")
    private OrderItem orderItemHanzheWithOptions(String colorName, List<String> specialOptions) {
        OrderItem item = orderItemHanzhe(colorName);
        ((Map<String, Object>) item.getProcessingInfo()).put("specialOptions", specialOptions);
        return item;
    }

    /**
     * 带指定**加工项名**的订单明细（issue #4577）：`processing_item` 规则的触发键
     * = 该行 `processingInfo.processingItems[].name`（**精确相等**）。
     */
    private OrderItem orderItemWithProcessingItemName(String colorName, String processingItemName) {
        return processedItem("item-1", "布艺遮光帘A", colorName, List.of(
                Map.of("id", "p1", "name", processingItemName, "unitPrice", 3.0,
                        "quantity", 2, "unit", "折")));
    }

    /** 「生成加工单 → 真链路实例化」的装配：真实 ProductionService + 真实 ProcessingOrderService。 */
    private ProcessingOrderService realChainService() {
        ProcessingOrderService service = new ProcessingOrderService(
                processingOrderMapper, orderMapper, orderItemMapper, processingItemMapper,
                orderService, objectMapper,
                new ProductionService(processingOrderMapper, positionOperationMapper, workLogMapper, orderMapper,
                        orderItemMapper, clientRequestIdService),
                productionOperationQueryService, productionOperationQtyClient);
        // 批次台账（V116 / issue #5145）是**字段注入**（不在构造签名里，避免改 5 处既有装配）⇒
        // 手写 new 的路径要显式装配，否则 batchStock() 会 fail-closed 抛错（那是**有意**的：
        // 漏装配时不许静默跳过扣减）。
        org.springframework.test.util.ReflectionTestUtils.setField(
                service, "stockBatchConsumptionService", stockBatchConsumptionService);
        return service;
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

    // ── 派工指定批次（V116 / issue #5145 阶段 1）────────────────────────────────
    //
    // 本类只验证**装配与顺序**（谁在什么时候调了台账服务）——「扣多少、余量怎么派生、差额怎么解释」
    // 的算账判据在 StockBatchConsumptionServiceTest。顺序是本单的关键：扣减必须发生在
    // 加工单插入**之后**（重复生成在插入处被幂等闸拒 ⇒ 结构上不可能二次扣）。

    /** 一行的批次指派（生成请求体的元素）。 */
    private com.migao.admin.dto.ProcessingOrderGenerateRequest.BatchAssignment batchAssignment(
            String itemId, String batchNo) {
        var assignment = new com.migao.admin.dto.ProcessingOrderGenerateRequest.BatchAssignment();
        assignment.setOrderId("order-001");
        assignment.setItemId(itemId);
        assignment.setBatchNo(batchNo);
        return assignment;
    }

    /**
     * 小数夹具（2.7 米；带商品 id + skuCode）：整数场景是这些判据的**退化情形**
     * —— 规则挑批次、需求比对、落账米数在整数下全都看不出偏差（#5063 的教训）。
     */
    private OrderItem orderItemForRule(String colorName) {
        Map<String, Object> info = processingInfo(colorName);
        info.put("sku", "SKU-1");   // 订单行侧的 SKU 只以 processing_info.sku 存在（行上没有 skuCode 列）
        return OrderItem.builder()
                .id("item-1").tenantId(TENANT).orderId("order-001")
                .productId("prod-1")
                .productName("布艺遮光帘A")
                .quantity(new BigDecimal("2.7"))
                .width(new BigDecimal("2.5")).height(new BigDecimal("2.8"))
                .processingInfo(info)
                .build();
    }

    /** 一条已校验过的扣减计划行（`plan` 的返回值）。 */
    private StockBatchConsumptionService.Deduction plannedDeduction(String itemId, String batchNo,
                                                                    String meters, String remainingBefore) {
        // 两个米数（V119 / issue #5158）：本桩不排料 ⇒ 排料口径 = 公式口径
        return new StockBatchConsumptionService.Deduction(77L, batchNo, "prod-1", 12L, "SKU-1",
                itemId, new BigDecimal(meters), new BigDecimal(meters), new BigDecimal("12.5"),
                new BigDecimal(remainingBefore));
    }

    /**
     * 生成前置桩「**到计划为止**」（不含 insert 回填）：给「必须在插入之前失败」的用例用 ——
     * 严格桩下给它们装 insert 会变成**未使用桩**（噪音，不是缺陷）。
     */
    private void stubGenerateBeforeInsert(List<OrderItem> items) {
        when(orderMapper.selectById("order-001")).thenReturn(confirmedOrder);
        when(orderItemMapper.selectList(any())).thenReturn(items);
        when(processingOrderMapper.selectActiveByOrderId("order-001", TENANT)).thenReturn(null);
    }

    @SuppressWarnings("unchecked")
    private List<Map<String, Object>> capturedSnapshot(ArgumentCaptor<ProcessingOrder> captor) {
        return (List<Map<String, Object>>) captor.getValue().getItemsSnapshot();
    }

    @Test
    @DisplayName("PG-060 派工即扣：指定批次 ⇒ 同事务扣减（plan 在插入之前、apply 在插入之后）")
    void generateWithBatchAssignmentDeductsInSameTransaction() {
        stubLibrary();
        stubGenerate(List.of(orderItemWithProcessing("米白")));
        when(stockBatchConsumptionService.plan(eq(TENANT), anyList()))
                .thenReturn(List.of(plannedDeduction("item-1", "PC-20260923-0001", "2.7", "60")));

        var results = realChainService().generate(List.of("order-001"),
                List.of(batchAssignment("item-1", "PC-20260923-0001")), TENANT, "文员");

        assertThat(results).hasSize(1);
        assertThat(results.get(0).isSuccess()).isTrue();
        ArgumentCaptor<ProcessingOrder> poCaptor = ArgumentCaptor.forClass(ProcessingOrder.class);
        verify(processingOrderMapper).insert(poCaptor.capture());
        // 快照的 `batchNo` 空插座（V63 白名单早有该键、此前全仓零写入方）被填上人工最终选择
        assertThat(capturedSnapshot(poCaptor).get(0)).containsEntry("batchNo", "PC-20260923-0001");

        var ordered = inOrder(stockBatchConsumptionService, processingOrderMapper);
        ordered.verify(stockBatchConsumptionService).plan(eq(TENANT), anyList());
        ordered.verify(processingOrderMapper).insert(any(ProcessingOrder.class));
        ordered.verify(stockBatchConsumptionService)
                .apply(eq(TENANT), anyString(), eq("ORD-20260912-0001"), anyList());
    }

    @Test
    @DisplayName("PG-060 不重复扣：同一订单重复生成被幂等闸拒 ⇒ 台账只被调用一次")
    void duplicateGenerateDoesNotDeductTwice() {
        stubLibrary();
        stubGenerate(List.of(orderItemWithProcessing("米白")));
        when(stockBatchConsumptionService.plan(eq(TENANT), anyList()))
                .thenReturn(List.of(plannedDeduction("item-1", "PC-20260923-0001", "2.7", "60")));
        ProcessingOrderService service = realChainService();
        var assignments = List.of(batchAssignment("item-1", "PC-20260923-0001"));

        var first = service.generate(List.of("order-001"), assignments, TENANT, "文员");
        var second = service.generate(List.of("order-001"), assignments, TENANT, "文员");

        assertThat(first.get(0).isSuccess()).isTrue();
        assertThat(second.get(0).isSuccess()).isFalse();
        assertThat(second.get(0).getMessage()).contains("请勿重复生成");
        verify(stockBatchConsumptionService, times(1)).plan(eq(TENANT), anyList());
        verify(stockBatchConsumptionService, times(1))
                .apply(eq(TENANT), anyString(), anyString(), anyList());
        verify(processingOrderMapper, times(1)).insert(any(ProcessingOrder.class));
    }

    @Test
    @DisplayName("PG-060 缺料不静默：plan 抛余量不足 ⇒ 不落加工单、不扣减（不留半成品）")
    void insufficientBatchFailsClosedWithoutHalfProduct() {
        stubLibrary();
        stubGenerateBeforeInsert(List.of(orderItemWithProcessing("米白")));
        when(stockBatchConsumptionService.plan(eq(TENANT), anyList()))
                .thenThrow(new BusinessException(
                        StockBatchConsumptionService.ERR_BATCH_STOCK_INSUFFICIENT,
                        "批次 PC-1 余量不足：可用 0.5 米，本行需要 2 米", 409,
                        "该行需要 2 米。当前可用批次：PC-2（剩 30 米）。"));

        var results = realChainService().generate(List.of("order-001"),
                List.of(batchAssignment("item-1", "PC-1")), TENANT, "文员");

        assertThat(results).hasSize(1);
        assertThat(results.get(0).isSuccess()).isFalse();
        assertThat(results.get(0).getCode())
                .isEqualTo(StockBatchConsumptionService.ERR_BATCH_STOCK_INSUFFICIENT);
        assertThat(results.get(0).getMessage()).contains("余量不足").contains("0.5");
        assertThat(results.get(0).getSuggestion()).contains("PC-2");
        // 不留半成品：加工单没插、台账没扣（校验在任何写库之前跑完）
        verify(processingOrderMapper, never()).insert(any(ProcessingOrder.class));
        verify(stockBatchConsumptionService, never()).apply(any(), any(), any(), anyList());
    }

    @Test
    @DisplayName("PG-060 不指派批次 ⇒ 行为与今天逐字相同：不碰台账、快照不留 batchNo")
    void generateWithoutAssignmentLeavesBehaviorUnchanged() {
        stubLibrary();
        stubGenerate(List.of(orderItemWithProcessing("米白")));

        var results = realChainService().generate(List.of("order-001"), TENANT, "u1");

        assertThat(results.get(0).isSuccess()).isTrue();
        verifyNoInteractions(stockBatchConsumptionService);
        ArgumentCaptor<ProcessingOrder> poCaptor = ArgumentCaptor.forClass(ProcessingOrder.class);
        verify(processingOrderMapper).insert(poCaptor.capture());
        assertThat(capturedSnapshot(poCaptor).get(0)).doesNotContainKey("batchNo");
    }

    @Test
    @DisplayName("PG-060 指派的行不在加工单快照里 ⇒ 显式拒绝（不静默忽略）")
    void assignmentOnUnknownItemIsRejected() {
        stubLibrary();
        stubGenerateBeforeInsert(List.of(orderItemWithProcessing("米白")));

        var results = realChainService().generate(List.of("order-001"),
                List.of(batchAssignment("item-999", "PC-20260923-0001")), TENANT, "文员");

        assertThat(results.get(0).isSuccess()).isFalse();
        assertThat(results.get(0).getMessage()).contains("不在本订单的加工单快照里");
        verify(stockBatchConsumptionService, never()).plan(any(), anyList());
        verify(processingOrderMapper, never()).insert(any(ProcessingOrder.class));
    }

    @Test
    @DisplayName("PG-060 指派里的订单不在本次生成范围 ⇒ 整批显式拒绝（任何写库之前）")
    void assignmentForForeignOrderIsRejected() {
        // 不装任何生成桩：这一条必须在**碰任何 Mapper 之前**就被拒（装了反而变成未使用桩）
        var assignment = batchAssignment("item-1", "PC-20260923-0001");
        assignment.setOrderId("order-999");

        assertThatThrownBy(() -> realChainService().generate(List.of("order-001"),
                List.of(assignment), TENANT, "文员"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("不在本次生成范围内");
        verify(processingOrderMapper, never()).insert(any(ProcessingOrder.class));
        verifyNoInteractions(stockBatchConsumptionService);
    }

    // ── 读侧取键（issue #5174）：快照写 `sku`，读侧就必须读 `sku` ────────────────────
    //
    // 🔴 改前的洞**长在本节这一格**：`Designation.skuCode` 恒 null 也能让全类通过 ——
    // 护栏判据与建议值过滤的算账判据在 StockBatchConsumptionServiceTest（那边**显式传** skuCode），
    // 两条腿各自都绿，而「生产路径到底给了什么」**没有任何断言** ⇒ SKU 级护栏整体 no-op
    // （同货号、错颜色/门幅的批次静默落账）。真库读数见 SkuBatchGuardRealDbTest（PR-076 / PR-078）。

    /** 一行带 SKU 规格的快照来源：{@code processing_info.sku} 是订单侧 SKU 码的唯一落点（行上没有该列）。 */
    private OrderItem itemWithSnapshotSku(String skuCode) {
        Map<String, Object> info = processingInfo("米白");
        info.put("sku", skuCode);
        info.put("cuttingMode", "定高买宽");
        info.put("panels", 2);
        return OrderItem.builder()
                .id("item-1").tenantId(TENANT).orderId("order-001").productId("prod-1")
                .productName("布艺遮光帘A").quantity(new BigDecimal("2.7"))
                .width(new BigDecimal("2.5")).height(new BigDecimal("2.8"))
                .processingInfo(info)
                .build();
    }

    @Test
    @DisplayName("🔴 #5174 读侧取键：不启用池化 ⇒ Designation 的 SKU 码 = 快照实际写入的 `sku` 键"
            + "（改前读 `skuCode` ⇒ 恒 null ⇒ 护栏 no-op）")
    void designationSkuCodeComesFromTheSnapshotSkuKey() {
        stubLibrary();
        stubGenerate(List.of(itemWithSnapshotSku("SKU-1")));
        when(stockBatchConsumptionService.plan(eq(TENANT), anyList()))
                .thenReturn(List.of(plannedDeduction("item-1", "PC-20260923-0001", "2.7", "60")));

        var results = realChainService().generate(List.of("order-001"),
                List.of(batchAssignment("item-1", "PC-20260923-0001")), TENANT, "文员");

        assertThat(results.get(0).isSuccess()).as("合法路径（正确 SKU）行为不变：照旧成功").isTrue();
        @SuppressWarnings("unchecked")
        ArgumentCaptor<List<StockBatchConsumptionService.Designation>> planCaptor =
                ArgumentCaptor.forClass(List.class);
        verify(stockBatchConsumptionService).plan(eq(TENANT), planCaptor.capture());
        assertThat(planCaptor.getValue()).extracting(
                        StockBatchConsumptionService.Designation::skuCode)
                .as("🔴 SKU 码必须取自快照的 `sku` 键（快照里**没有** `skuCode` 键）—— 非 null 才有护栏")
                .containsExactly("SKU-1");
        // 排料定尺入参（#5158）逐值不变：加工类型 / 窗高 / 分幅数照旧全部来自快照，本单不碰
        StockBatchConsumptionService.Designation d = planCaptor.getValue().get(0);
        assertThat(d.cuttingMode()).isEqualTo("定高买宽");
        assertThat(d.height()).isEqualByComparingTo("2.8");
        assertThat(d.panels()).isEqualTo(2);
        assertThat(d.meters()).as("派工需求 = 公式口径米数（#5158 口径不变）").isEqualByComparingTo("2.7");
    }

    @Test
    @DisplayName("🔴 #5174+#5167 规则补位：建议值按**快照的 SKU**过滤"
            + "（改前收 null ⇒ 过滤整条 no-op ⇒ 错颜色/门幅的批次也能被补位）")
    void suggestedBatchNoSeesTheSnapshotSku() {
        stubLibrary();
        stubGenerate(List.of(itemWithSnapshotSku("SKU-1")));
        when(stockBatchConsumptionService.suggestedBatchNo(any(), any(), any(), any(), any()))
                .thenReturn("PC-EARLY");
        when(stockBatchConsumptionService.plan(eq(TENANT), anyList()))
                .thenReturn(List.of(plannedDeduction("item-1", "PC-EARLY", "2.7", "30")));

        var results = realChainService().generate(List.of("order-001"),
                List.of(batchAssignment("item-1", null)), TENANT, "文员", "fifo");

        assertThat(results.get(0).isSuccess()).isTrue();
        ArgumentCaptor<String> skuCaptor = ArgumentCaptor.forClass(String.class);
        verify(stockBatchConsumptionService).suggestedBatchNo(eq(TENANT), eq("prod-1"),
                skuCaptor.capture(), any(), eq("fifo"));
        assertThat(skuCaptor.getValue())
                .as("🔴 过滤入参 = 快照的 SKU 码（改前是 null ⇒ 会挑到同货号错颜色/门幅的批次）")
                .isEqualTo("SKU-1");
        @SuppressWarnings("unchecked")
        ArgumentCaptor<List<StockBatchConsumptionService.Designation>> planCaptor =
                ArgumentCaptor.forClass(List.class);
        verify(stockBatchConsumptionService).plan(eq(TENANT), planCaptor.capture());
        assertThat(planCaptor.getValue()).extracting(
                        StockBatchConsumptionService.Designation::skuCode)
                .as("补位挑出的批次进 plan 时带着同一个 SKU 码（两处口径同源）").containsExactly("SKU-1");
    }

    // ── 指派规则（issue #5167）：缺省一字不改 / 显式开启才自动补位 ──────────────────
    //
    // 判据分工：**挑哪个批次**的算账判据在 StockBatchConsumptionServiceTest（FIFO vs best-fit 的
    // 判别性夹具）；本类只判**装配**——规则有没有被消费、缺省路径有没有被改掉、失败是不是显式的。

    @Test
    @DisplayName("#5167 判据1 不传规则 ⇒ 未指定批次的行仍**逐字**显式拒绝，且绝不查建议值")
    void assignmentRuleAbsentKeepsBlankBatchNoRejected() {
        stubLibrary();
        stubGenerateBeforeInsert(List.of(orderItemWithProcessing("米白")));

        var results = realChainService().generate(List.of("order-001"),
                List.of(batchAssignment("item-1", null)), TENANT, "文员");

        assertThat(results.get(0).isSuccess()).isFalse();
        assertThat(results.get(0).getMessage()).as("缺省路径的错误文案一字不改").isEqualTo("批次指派缺少 batchNo（行 item-1）");
        // 红证：把 generate 的 `StringUtils.hasText(assignmentRule)` 判据去掉（一律补位）⇒ 这里变红
        verify(stockBatchConsumptionService, never())
                .suggestedBatchNo(any(), any(), any(), any(), any());
        verify(stockBatchConsumptionService, never()).plan(any(), anyList());
        verify(processingOrderMapper, never()).insert(any(ProcessingOrder.class));
    }

    @Test
    @DisplayName("#5167 判据2 传 best_fit ⇒ 未指定批次的行按规则补位，补出的批次进 plan 与快照")
    void bestFitRuleAutoAssignsAndStampsTheChosenBatch() {
        stubLibrary();
        stubGenerate(List.of(orderItemForRule("米白")));
        when(stockBatchConsumptionService.suggestedBatchNo(
                eq(TENANT), eq("prod-1"), any(), any(), eq("best_fit"))).thenReturn("PC-LATE");
        when(stockBatchConsumptionService.plan(eq(TENANT), anyList()))
                .thenReturn(List.of(plannedDeduction("item-1", "PC-LATE", "2.7", "3")));

        var results = realChainService().generate(List.of("order-001"),
                List.of(batchAssignment("item-1", null)), TENANT, "文员", "best_fit");

        assertThat(results.get(0).isSuccess()).isTrue();
        // 补位结果必须真的进计划（不是只回一个字符串）：plan 收到的指派行带着 best-fit 挑的批次号
        @SuppressWarnings("unchecked")
        ArgumentCaptor<List<StockBatchConsumptionService.Designation>> planCaptor =
                ArgumentCaptor.forClass(List.class);
        verify(stockBatchConsumptionService).plan(eq(TENANT), planCaptor.capture());
        assertThat(planCaptor.getValue()).extracting(
                StockBatchConsumptionService.Designation::batchNo).containsExactly("PC-LATE");
        // 需求 = 该行的**公式口径**米数（领料上限；实际扣减仍由 plan 按排料结果定）
        assertThat(planCaptor.getValue()).extracting(
                StockBatchConsumptionService.Designation::meters)
                .allSatisfy(m -> assertThat(m).isEqualByComparingTo("2.7"));
        ArgumentCaptor<ProcessingOrder> poCaptor = ArgumentCaptor.forClass(ProcessingOrder.class);
        verify(processingOrderMapper).insert(poCaptor.capture());
        assertThat(capturedSnapshot(poCaptor).get(0)).as("快照固化真相里记的是**补位后**的批次")
                .containsEntry("batchNo", "PC-LATE");
    }

    @Test
    @DisplayName("#5167 显式 fifo 也开启补位（缺省「不补位」≠ 规则值 fifo）：按 FIFO 挑出的批次落账")
    void explicitFifoRuleAlsoAutoAssigns() {
        stubLibrary();
        stubGenerate(List.of(orderItemForRule("米白")));
        when(stockBatchConsumptionService.suggestedBatchNo(
                eq(TENANT), eq("prod-1"), any(), any(), eq("fifo"))).thenReturn("PC-EARLY");
        when(stockBatchConsumptionService.plan(eq(TENANT), anyList()))
                .thenReturn(List.of(plannedDeduction("item-1", "PC-EARLY", "2.7", "30")));

        var results = realChainService().generate(List.of("order-001"),
                List.of(batchAssignment("item-1", null)), TENANT, "文员", "fifo");

        assertThat(results.get(0).isSuccess()).isTrue();
        verify(stockBatchConsumptionService).suggestedBatchNo(
                eq(TENANT), eq("prod-1"), any(), any(), eq("fifo"));
    }

    @Test
    @DisplayName("#5167 人工指定优先于规则：行里有 batchNo ⇒ 不查建议值，落账用人工那个")
    void explicitBatchWinsOverTheRule() {
        stubLibrary();
        stubGenerate(List.of(orderItemWithProcessing("米白")));
        when(stockBatchConsumptionService.plan(eq(TENANT), anyList()))
                .thenReturn(List.of(plannedDeduction("item-1", "PC-手动", "2.7", "60")));

        var results = realChainService().generate(List.of("order-001"),
                List.of(batchAssignment("item-1", "PC-手动")), TENANT, "文员", "best_fit");

        assertThat(results.get(0).isSuccess()).isTrue();
        verify(stockBatchConsumptionService, never()).suggestedBatchNo(any(), any(), any(), any(), any());
        @SuppressWarnings("unchecked")
        ArgumentCaptor<List<StockBatchConsumptionService.Designation>> planCaptor =
                ArgumentCaptor.forClass(List.class);
        verify(stockBatchConsumptionService).plan(eq(TENANT), planCaptor.capture());
        assertThat(planCaptor.getValue()).extracting(
                StockBatchConsumptionService.Designation::batchNo).containsExactly("PC-手动");
    }

    @Test
    @DisplayName("#5167 判据3 规则下无可满足批次 ⇒ 显式拒绝该行（不静默跳过、不落半成品）")
    void noCandidateUnderTheRuleFailsClosed() {
        stubLibrary();
        stubGenerateBeforeInsert(List.of(orderItemForRule("米白")));
        when(stockBatchConsumptionService.suggestedBatchNo(any(), any(), any(), any(), any()))
                .thenReturn(null);

        var results = realChainService().generate(List.of("order-001"),
                List.of(batchAssignment("item-1", null)), TENANT, "文员", "best_fit");

        assertThat(results.get(0).isSuccess()).isFalse();
        assertThat(results.get(0).getMessage())
                .contains("在指派规则 best_fit 下没有可满足的批次").contains("该行需要 2.7 米");
        verify(stockBatchConsumptionService, never()).plan(any(), anyList());
        verify(processingOrderMapper, never()).insert(any(ProcessingOrder.class));
    }

    @Test
    @DisplayName("🔴 #5167 判据4 非法规则值 ⇒ 整批显式拒绝（**即使所有行都显式指定了批次**）")
    void unknownRuleRejectsTheWholeBatchEvenWithExplicitBatches() {
        // 不装任何生成桩：非法值必须在**碰任何 Mapper 之前**就被拒（装了反而变成未使用桩）
        assertThatThrownBy(() -> realChainService().generate(List.of("order-001"),
                List.of(batchAssignment("item-1", "PC-20260923-0001")), TENANT, "文员", "bestfit"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("未知的批次指派规则")
                .hasFieldOrPropertyWithValue("code", "ASSIGNMENT_RULE_UNKNOWN");
        verifyNoInteractions(stockBatchConsumptionService);
        verify(processingOrderMapper, never()).insert(any(ProcessingOrder.class));
    }

    @Test
    @DisplayName("PG-060 作废回补：generated → cancelled 同事务回补该单扣过的批次")
    void cancelReversesBatchConsumption() {
        when(processingOrderMapper.selectOne(any())).thenReturn(po("po-1", "generated"));
        when(processingOrderMapper.updateById(any(ProcessingOrder.class))).thenReturn(1);
        when(orderMapper.selectById("order-001")).thenReturn(confirmedOrder);

        ProcessingOrderUpdateRequest cancel = new ProcessingOrderUpdateRequest();
        cancel.setAction("cancel");
        cancel.setReason("加工方排期冲突");
        processingOrderService.updateStatus("po-1", cancel, TENANT, "u1");

        verify(stockBatchConsumptionService).reverse(eq(TENANT), eq("JG-20260912-0001"),
                eq("ORD-20260912-0001"), anyString());
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
        // 批次台账（V116 / issue #5145）：@InjectMocks 只做构造注入 ⇒ 字段注入的那一个要显式装配
        org.springframework.test.util.ReflectionTestUtils.setField(
                processingOrderService, "stockBatchConsumptionService", stockBatchConsumptionService);
    }

    // ── 快照构建工具 ──────────────────────────────────────────────

    @SuppressWarnings("unchecked")
    private Map<String, Object> processingInfo(String colorName) {
        Map<String, Object> info = new LinkedHashMap<>();
        info.put("processingFee", 6.0);
        info.put("colorName", colorName);
        info.put("sellingMethod", "散剪");
        info.put("doorWidth", "2.8米");
        // ⚠️ issue #4882 起本夹具的加工项「不带 pricingMethod 键」= **新单形态 ⇒ 判据命中米类**
        // （`isMeterBasedLine` 第 3 段；#4299 时是无键不命中，语义已翻转）。本夹具被大量用例共用，
        // 而顶部共用的 `stubQty()` 是**与 calc_info 无关**的平行真值（米类恒 12.3）⇒ 那些用例的
        // 期望值不受翻转影响；要断言 calc_info 本身请看下面 #4299/#4882 那一族用例。
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
     * **一樘窗含全部部位** = 布帘 + 纱帘 + 帘头（**三条明细行**，同 `craftLineId` = `win-1`）。
     *
     * <p>⭐ issue #4693（口径改判「**一樘窗 = 一套**」，设计文档 §2.1.1）：这**一樘窗 = 1 套**
     * —— 不是 3 套。旧口径（#4373「1 个窗帘商品 = 1 套」⇒ 套 ≡ 明细行）下它是 **3 套**。</p>
     *
     * <p>判别物 = **套级工序**（`scope='set'`，外帘打卷/装袋/发货，每樘窗一次）：一行明细 = 一套
     * ⇒ 旧口径下这三道各出现 **3 次**（每部位一遍、计件三付）；一樘窗 = 一套 ⇒ 各 **1 次**。</p>
     */
    private List<OrderItem> clothSheerValanceWindow() {
        OrderItem cloth = processedItemWithSpec("item-1", "布艺遮光帘A", "米白",
                List.of(Map.of("id", "p1", "name", "韩褶-布", "unitPrice", 3.0, "quantity", 2, "unit", "折")),
                spec("curtainType", "布帘", "craft", "韩褶",
                        "componentRole", "主布", "craftLineId", "win-1"));
        OrderItem sheer = processedItemWithSpec("item-2", "纱帘A", "米白",
                List.of(Map.of("id", "p2", "name", "打孔-纱", "unitPrice", 3.0, "quantity", 2, "unit", "孔")),
                spec("curtainType", "纱帘", "craft", "打孔",
                        "componentRole", "纱", "craftLineId", "win-1"));
        OrderItem valance = processedItemWithSpec("item-3", "帘头A", "米白",
                List.of(Map.of("id", "p3", "name", "帘头制作", "unitPrice", 2.0, "quantity", 1, "unit", "个")),
                spec("curtainType", "帘头", "craft", "韩褶", "craftLineId", "win-1"));
        return List.of(cloth, sheer, valance);
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
    // 加工项目录、不落半成品；③ 实例化 payload **不带** `is_must_finish`（#4961：必完概念已退场，
    // 该键在派生 payload 里根本不存在 —— 实例的必完列因此恒为 null，见本类第一处实例断言）。
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
                .containsExactly(1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12);
        for (int i = 0; i < V54_BULIAN_HANZHE.length; i++) {
            ProcessingPositionOperation instance = instances.get(i);
            String[] row = V54_BULIAN_HANZHE[i];
            String where = "第 " + (i + 1) + " 道（" + row[0] + "）";
            assertThat(instance.getOperationName()).as(where + " 工序名").isEqualTo(row[0]);
            assertThat(instance.getGroupName()).as(where + " 分组").isEqualTo(row[1]);
            assertThat(instance.getUnit()).as(where + " 单位").isEqualTo(row[2]);
            if ("打包".equals(row[0])) {
                // 🔴 issue #4937 / O4：`打包` 的**矩阵价是 NULL**（未定价 ≠ 0 元）
                assertThat(instance.getUnitPrice())
                        .as(where + " 单价（未定价 ⇒ null，不回落工序库行价）").isNull();
            } else {
                assertThat(instance.getUnitPrice()).as(where + " 单价").isEqualByComparingTo(row[3]);
            }
            assertThat(instance.getIsStartMarker()).as(where + " 开始标记").isEqualTo(Boolean.valueOf(row[5]));
            assertThat(instance.getPositionName()).as(where + " 部位").isEqualTo("布艺遮光帘A 米白");
            assertThat(instance.getProcessingOrderId()).isEqualTo("po-001");
            assertThat(instance.getStatus()).isEqualTo("pending");
        }
        // 🔴 #4961（必完概念整体退场）：实例化**一个字都不写** `is_must_finish`（列保留为历史载体）
        // ⇒ 全部实例该字段为 `null`。改前这里有三条判据（逐行比对库里的必完值 / 「必完唯一 =
        // 外帘装袋」/「末道不得被无条件标必完」）—— 它们的前提（实例带必完标记）已不存在，
        // 旧判据随之退场；替代判据**更强**：该列一字不写（下面这条对**每一道**实例都成立）。
        // 真正的完工口径（全部活跃实例完成）由 `ProductionServiceTest` 的
        // `unfinishedNonMustFinishOperationBlocksCompletion` 一族钉住。
        assertThat(instances).allSatisfy(instance ->
                assertThat(instance.getIsMustFinish()).as("实例不得写必完列（#4961）").isNull());
        // 🔴 issue #4937 / O4：`打包` 进路线后位次后移一位 ⇒ `外帘发货` 在 index 11
        assertThat(instances.get(11).getOperationName()).isEqualTo("外帘发货");

        // ② 应做数量 = **算料引擎输出**（issue #4208 接线）：米类 12.3、折类 24、套类兜底 1
        //    —— 此前取该部位订单数量（2）⇒ 11 道工序全 2.00，正是走查实测「韩褶-布 显示 3 折」的形态。
        //    本断言的红证：把 buildPositionPayload 改回 positionQty(entry) ⇒ 逐条必红（12.3 ≠ 2）。
        assertThat(instances).allSatisfy(instance -> {
            String unit = instance.getUnit();
            // 米类 = 该行 calc_info.fabric_meters = 订单行 quantity（#4337：改前钉的是共用桩的
            // 平行真值 12.3 ⇒ 与「按米/按套」的实际口径不一致）；折/幅/套/孔 三轴取值不变。
            String expected = "折".equals(unit) ? CALC_PLEAT_COUNT : ("米".equals(unit) ? ORDER_QUANTITY : "1");
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

        // 判据 5（issue #4208 **由 #4337 收窄**）：qty = 算料输出，**分轴**断言 ——
        //   · 非米类（折/幅/套/孔）：应做数量**不得**等于订单行数量（订单行 quantity 是樘数/条数，不是应做量）；
        //   · 米类：**应当**等于请求体里的 `calc_info.fabric_meters`（= 上面刚断言过的订单行 quantity）。
        // 这正是 `PG-022` 的 `data_checks` 口径（折/幅/套类不得等于；米类应当等于）。
        // 改前这里是一条 blanket「全部实例 qty ≠ 订单数量」—— 它对米类**在现实中为假**：它当时之所以绿，
        // 唯一原因是共用桩 `stubQty()` 恒返回 12.3（与 calc_info 无关的平行真值，见 #4337 的实测）。
        assertThat(instances).filteredOn(instance -> !"米".equals(instance.getUnit()))
                .allSatisfy(instance -> assertThat(instance.getQty())
                        .as("非米类（%s）应做数量不得等于订单行数量 %s", instance.getUnit(), ORDER_QUANTITY)
                        .isNotEqualByComparingTo(ORDER_QUANTITY));
        assertThat(instances.get(2).getOperationName()).isEqualTo("韩褶-布");
        assertThat(instances.get(2).getQty()).as("折类 = 褶数（端点 FOLD_KEYS）")
                .isEqualByComparingTo(CALC_PLEAT_COUNT);
        assertThat(instances.get(0).getOperationName()).isEqualTo("精裁-布");
        assertThat(instances.get(0).getQty())
                .as("米类应做数量 = 请求体里的 calc_info.fabric_meters（端点 METER_KEYS 直采）")
                .isEqualByComparingTo(fabricMetersOf(calcInfo));
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
    // 缺键 ⇒ 兜底 1 + `qty_source=fallback`。⚠️ 本节这些用例在 #4337 之前**证不了映射是否生效**：
    // 当时文件顶部共用的 `stubQty()` 是与 calc_info 无关的平行真值（米类恒 12.3 / `fabric_meters`）⇒
    // 「米类 qty_source」恒绿。本单已把共用桩改成 calc_info-aware（见顶部注释）⇒ 本节**不再需要**
    // 局部替身 `stubMeterQtyFromCalcInfo()`（**已删**：并存的第二套米轴口径 = 第二份真值）。
    // 折/幅/套/孔 仍走共用桩的既有取值（#4208 的既有用例钉着它们，不在本单范围）。

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

    /** 生成一张布帘×韩褶单（真链路实例化）并取回请求体里的 calc_info。 */
    @SuppressWarnings("unchecked")
    private Map<String, Object> generateAndCaptureCalcInfo(OrderItem item) {
        stubLibrary();
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
        assertThat(calcInfo).as("calc_info 必须带 fabric_meters（判据 = ProcessingOrderService.isMeterBasedLine）")
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

        Map<String, Object> calcInfo = generateAndCaptureCalcInfo(item);

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

        Map<String, Object> calcInfo = generateAndCaptureCalcInfo(item);

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

        Map<String, Object> calcInfo = generateAndCaptureCalcInfo(item);

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

        Map<String, Object> calcInfo = generateAndCaptureCalcInfo(item);

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

        Map<String, Object> calcInfo = generateAndCaptureCalcInfo(item);

        assertThat(calcInfo).as("订单行 quantity 不是米数（计价方式 per_sqm）⇒ 不得冒充 fabric_meters")
                .doesNotContainKey("fabric_meters");
        assertThat(capturedInstances()).filteredOn(instance -> "米".equals(instance.getUnit()))
                .isNotEmpty()
                .allSatisfy(instance -> assertThat(instance.getQtySource())
                        .as("端点在缺 fabric_meters 时兜底 1 并显式标 fallback（不静默）")
                        .isEqualTo("fallback"));
    }

    @Test
    @DisplayName("#4882 语义翻转：processingItems **全无** pricingMethod 键（#4882 之后的新单形态）⇒ 判定为米类")
    void processingItemsWithoutPricingMethodKeyAreMeterBased() {
        // ⚠️ **语义翻转登记（issue #4882）**：本用例在 #4299 时名为
        // `processingItemsWithoutPricingMethodKeyDoNotMap`，断言「无键 ⇒ 判据不命中 ⇒ 米类落 fallback 1」。
        // 加工项目录删除 `pricing_method` 列后，下单入口**不再写该键** ⇒ 无键 = **新单形态**；
        // 判据改为 `ProcessingOrderService.isMeterBasedLine` 的三段契约，**第 3 段 = 全无该键 ⇒ 米类**。
        // 翻转的理由（有意取舍，不是遗漏）：
        //   ① #3005 行业口径：行业加工费**按米计价**、辅料含在加工费中 ⇒ 有加工项即按米；
        //   ② V83 目录 16 项历史上**全部** per_meter（`V83__seed_processing_item_catalog.sql`）；
        //   ③ 不翻转的代价 = 米类工序落 `qty_source=fallback` 兜底 1 ⇒ 112 米的单做 1 米 ⇒ **假完工**
        //      （#4208 红线）；翻转的代价只是「按订单行 quantity 当米数」。
        // 仍**不**回落到 sellingMethod / products.pricing_type（它们不是数量口径的来源，#4299 实测）——
        // 本用例里的 `sellingMethod=bulk_cut` 只是**干扰项**：翻转的依据是「有加工项且全无该键」，
        // 不是售卖方式（判据取值的红证：把它改回 sellingMethod 口径 ⇒ 本断言立刻红）。
        OrderItem item = orderItemHanzhe("米白");   // 加工项无 pricingMethod 键
        @SuppressWarnings("unchecked")
        Map<String, Object> info = (Map<String, Object>) item.getProcessingInfo();
        info.put("sellingMethod", "bulk_cut");

        Map<String, Object> calcInfo = generateAndCaptureCalcInfo(item);

        assertThat(fabricMetersOf(calcInfo))
                .as("#4882 第 3 段：全无 pricingMethod 键 ⇒ 米类 ⇒ 订单行 quantity 即米数")
                .isEqualByComparingTo(ORDER_QUANTITY);
        assertThat(capturedInstances()).filteredOn(instance -> "米".equals(instance.getUnit()))
                .isNotEmpty()
                .allSatisfy(instance -> assertThat(instance.getQtySource())
                        .as("米类必须取 fabric_meters（fallback 1 = 112 米的单做 1 米 = 假完工）")
                        .isEqualTo("fabric_meters"));
    }

    @Test
    @DisplayName("#4882 第 2 段优先：混装（一项带键 per_sqm + 一项无键）⇒ 按**带键**的存量快照形态判，不冒充米数")
    void mixedKeyedAndUnkeyedProcessingItemsDeferToExplicitKey() {
        // 第 2 段（存量快照形态）与第 3 段（新单形态）在同一行混装时的边界：**带键优先**。
        // 红证：把实现改成「任一项无键 ⇒ 米类」⇒ 本断言立刻红（会多出 fabric_meters）。
        OrderItem item = orderItemHanzhe("米白");
        @SuppressWarnings("unchecked")
        Map<String, Object> info = (Map<String, Object>) item.getProcessingInfo();
        List<Map<String, Object>> procs = new ArrayList<>();
        procs.add(Map.of("id", "p1", "name", "刺绣工艺", "pricingMethod", "per_sqm",
                "unitPrice", 3.0, "quantity", 2, "unit", "米"));
        procs.add(Map.of("id", "p2", "name", "打孔", "quantity", 2, "unit", "米"));
        info.put("processingItems", procs);

        Map<String, Object> calcInfo = generateAndCaptureCalcInfo(item);

        assertThat(calcInfo)
                .as("只要有**任一项**显式带 pricingMethod 键，就按存量快照形态判（全非 per_meter ⇒ 不命中）")
                .doesNotContainKey("fabric_meters");
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
                        "定型-布", "复烫-布", "布帘车被", "外帘打卷", "打包", "外帘装袋", "外帘发货");
        // seq 必须重排成 1..N（#4694 后 seq 只作页面排序 / 「下一道待做」派生依据；报工顺序闸门已删除）
        assertThat(instances).extracting(ProcessingPositionOperation::getSeq)
                .containsExactly(1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13);
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
    @DisplayName("#4589：带「一分为二」（ERP 名）⇒ 工序实例 factor 仍恒 1（规则表里那条 ×1.7 档已无消费者）")
    void specialOptionNoLongerAppliesFactorToOperations() {
        stubLibrary();
        // 规则表里**仍有** active 的 `action='factor'`（一分为二 ×1.7）行 —— 历史种子照旧在，
        // 但已无消费者 ⇒ 这正是本用例的判别力所在（改前这里逐条是 1.7）。
        stubOptionTables();
        stubGenerate(List.of(orderItemHanzheWithOptions("米白", List.of("一分为二"))));
        when(processingItemMapper.selectById("p1"))
                .thenReturn(ProcessingItem.builder().id("p1").name("韩褶-布").unit("折").build());

        var results = realChainService().generate(List.of("order-001"), TENANT, "u1");
        assertThat(results.get(0).isSuccess()).isTrue();

        ArgumentCaptor<ProcessingPositionOperation> captor =
                ArgumentCaptor.forClass(ProcessingPositionOperation.class);
        verify(positionOperationMapper, times(V54_BULIAN_HANZHE.length)).insert(captor.capture());
        // 「一分为二」不加工序 ⇒ 工序数不变；系数已退场 ⇒ 每道 factor 恒 1
        assertThat(captor.getAllValues()).extracting(ProcessingPositionOperation::getOperationName)
                .containsExactlyElementsOf(java.util.Arrays.stream(V54_BULIAN_HANZHE).map(r -> r[0]).toList());
        assertThat(captor.getAllValues()).allSatisfy(instance ->
                assertThat(instance.getFactor()).as("工序「%s」的系数", instance.getOperationName())
                        .isEqualByComparingTo("1"));

        // 不带 ⇒ 同样逐条 1.00（两侧同口径；判别力由「改前带选项那侧是 1.7」承担）
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
    @DisplayName("#4589：系数不再进钱 —— 同一张单带/不带「一分为二」的计件合计**相等**（比值 = 1）")
    void specialOptionFactorNoLongerReachesPieceworkAmount() {
        BigDecimal withOption = pieceworkTotalFor(List.of("一分为二"));
        BigDecimal without = pieceworkTotalFor(List.of());

        assertThat(without).as("不带特殊选项 ⇒ 合计 = Σ(1 × 库单价)").isGreaterThan(BigDecimal.ZERO);
        // 红证（改前实测）：比值 = 1.7（系数真的乘进了钱）⇒ 本断言红。
        BigDecimal ratio = withOption.divide(without, 6, RoundingMode.HALF_UP);
        assertThat(ratio)
                .as("计件合计比值（带 一分为二 / 不带）必须 = 1 —— 系数已从算法退场（#4589）")
                .isEqualByComparingTo("1.000000");
    }

    /** 生成一张带指定特殊选项的加工单，按**真实** ProductionService 算该单计件合计。 */
    @SuppressWarnings("unchecked")
    private BigDecimal pieceworkTotalFor(List<String> specialOptions) {
        // 每次调用都重置工序实例 mapper：本方法在一次用例里被调用两次（带/不带选项），
        // 而 #4589 之后两者的**工序配置签名逐值相同**（系数不再进签名）⇒ 不重置的话第二次
        // generate 会命中「已实例化，重复调用跳过（幂等）」路径，本次调用的 stored 恒空。
        reset(positionOperationMapper);
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
        assertThat(stored).extracting(ProcessingPositionOperation::getOperationName)
                .as("桩必须真的实例化了库路线的工序（空集 ⇒ 计件合计恒 0 ⇒ 下面的断言空转）；"
                        + "#4337：旧形态 isNotEmpty() 只证「有东西」⇒ 少一道工序也照样绿")
                .contains("精裁-布", "韩褶-布");

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
                workLogMapper, orderMapper, orderItemMapper, clientRequestIdService);
        Map<String, Object> piecework = real.piecework("order-001", TENANT);
        return (BigDecimal) piecework.get("total");
    }

    @Test
    @DisplayName("#4230 fail-closed：特殊选项引用的条件工序在工序库无活跃行 ⇒ 中止生成、不落半成品")
    void specialOptionReferencingMissingOperationFailsClosed() {
        stubLibrary();
        // 规则表里「拼1次」的映射在，但工序库元数据里**没有**「拼1次-布」（= 库里缺这道工序）
        // ⇒ variantNameOf 解析不到变体 ⇒ 条件工序 fail-closed（不静默跳过）
        Map<String, Map<String, Object>> broken = RoutingModelFixture.catalog();
        broken.remove("拼1次-布");
        when(productionOperationQueryService.operationsByName(TENANT)).thenReturn(broken);
        // 不调 stubGenerate：fail-closed 发生在落库之前，给它打 insert 桩会被严格桩判为多余
        when(orderMapper.selectById("order-001")).thenReturn(confirmedOrder);
        when(orderItemMapper.selectList(any())).thenReturn(List.of(orderItemHanzheWithOptions("米白", List.of("拼1次"))));
        when(processingOrderMapper.selectActiveByOrderId("order-001", TENANT)).thenReturn(null);

        var results = realChainService().generate(List.of("order-001"), TENANT, "u1");

        assertThat(results.get(0).isSuccess()).isFalse();
        assertThat(results.get(0).getCode()).isEqualTo(ProcessingOrderService.ERR_OPERATION_NOT_FOUND);
        // ⚠️ 判据改钉**新真值**（issue #4647 / D3(b)，**不是放宽**）：改前这里断言 message 含
        // `拼1次-布`（= 实现拼出来的**库内变体名**）⇒ 那条断言**就是在钉泄漏本身**。
        // 现在 message 只报**逻辑名**（`拼1次`）+ 说清缺什么；变体名一律不上响应体。
        assertThat(results.get(0).getMessage()).as("指名报缺：报的是**逻辑工序名**（拼1次）")
                .contains("拼1次");
        assertThat(results.get(0).getSuggestion()).as("失败必须可行动").contains("operations-catalog");
        verify(processingOrderMapper, never()).insert(any(ProcessingOrder.class));
        verify(positionOperationMapper, never()).insert(any(ProcessingPositionOperation.class));
    }

    @Test
    @DisplayName("#4647 / D3(b)：实例化 fail-closed 的 hint **不得**拼变体名（改前拼「库中缺变体 拼1次-布 / …」）")
    void missingOperationHintDoesNotLeakVariantNames() {
        // 病根（issue #4647 复验实测）：hint 曾走 `logicalName + "（库中缺变体 " + expectedVariantLabel(…) + "）"`，
        // 而 `expectedVariantLabel` 拼 `逻辑名 + "-布"` / `"布" + 逻辑名` / `"布帘" + 逻辑名`
        // ⇒ 422 响应体里出现工人端快照名（改前实测日志：`缺工序=[拼1次（库中缺变体 拼1次-布 / 布拼1次 /
        // 布帘拼1次 / 拼1次）]`）。判据 = message **与** suggestion 都不含 `-布` / `-纱` / `-帘` 形态，
        // 且仍**指名报缺 + 说清缺在哪个部位**（可行动性不降）。
        stubLibrary();
        Map<String, Map<String, Object>> broken = RoutingModelFixture.catalog();
        broken.remove("拼1次-布");
        when(productionOperationQueryService.operationsByName(TENANT)).thenReturn(broken);
        when(orderMapper.selectById("order-001")).thenReturn(confirmedOrder);
        when(orderItemMapper.selectList(any())).thenReturn(List.of(orderItemHanzheWithOptions("米白", List.of("拼1次"))));
        when(processingOrderMapper.selectActiveByOrderId("order-001", TENANT)).thenReturn(null);

        var results = realChainService().generate(List.of("order-001"), TENANT, "u1");

        assertThat(results.get(0).isSuccess()).isFalse();
        assertThat(results.get(0).getCode()).isEqualTo(ProcessingOrderService.ERR_OPERATION_NOT_FOUND);
        assertThat(results.get(0).getMessage())
                .as("响应体**不得**含变体名形态（`-布` / `-纱` / `-帘`）")
                .doesNotContain("-布").doesNotContain("-纱").doesNotContain("-帘")
                .as("可行动性不降：仍指名报缺 + 说清缺在哪个部位")
                .contains("拼1次").contains("布帘");
        assertThat(results.get(0).getSuggestion())
                .as("suggestion 同样不得泄漏变体名").doesNotContain("-布").doesNotContain("-纱").doesNotContain("-帘")
                .as("补救入口仍在").contains("operations-catalog");
        verify(processingOrderMapper, never()).insert(any(ProcessingOrder.class));
        verify(positionOperationMapper, never()).insert(any(ProcessingPositionOperation.class));
    }

    @Test
    @DisplayName("#4230 锚点不在该部位路线中 ⇒ 条件工序追加到末尾（routing.py _insert_after 同款）")
    void conditionalOperationAppendsWhenAnchorAbsent() {
        stubLibrary();
        // 把「余料做绑带」的锚点改成一道**不在任何路线里**的工序 ⇒ 条件工序必须追加到末尾
        List<ProductionRouteRule> withBadAnchor = new ArrayList<>();
        for (ProductionRouteRule rule : RoutingModelFixture.rulesWithFactors(TENANT)) {
            if ("余料做绑带".equals(rule.getTriggerValue())) {
                rule.setAfterOperation("不存在的工序");
            }
            withBadAnchor.add(rule);
        }
        when(productionOperationQueryService.routeRules(TENANT)).thenReturn(withBadAnchor);
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

    // ══════════════════ 条件工序**唯一性 = 取代**（issue #4577 任务 A）+ 加工项触发（任务 B）══════════════════
    //
    // 钱风险（今天就在）：既有种子里**多条规则指向同一道工序** —— `接高`(160) 与 `双眼皮接高`(170)
    // 都插「接高」；`余料做绑带`(180) / `布绑带`(190) / `纱绑带`(220) 都插「绑带」。
    // 盲插 ⇒ 序列里两道同名工序 ⇒ 每道落成 `processing_position_operations` 一行
    // ⇒ **工人按两遍/三遍单价拿钱**（同族事故 #4523）。
    //
    // 用户裁定（2026-09-19 原话）：「**工序需要保证唯一**，比如工艺带了绑带，特殊选项又选择余料做绑带，
    // 得用**特殊选项中的余料做绑带替代绑带这个工序**，余料做绑带的目标工序也是绑带就能替换，
    // **需要有这个前提**」⇒ 判据 = 目标工序名相同；语义 = **取代**（先移除旧位置、再按本规则锚点插入）。

    @Test
    @DisplayName("#4577 任务A：同时命中「接高」+「双眼皮接高」⇒ 序列里「接高」恰好一个（三条绑带同理）")
    void duplicateInsertRulesDoNotInsertTheSameOperationTwice() {
        stubLibrary();
        // 规范 84 行价目（接高@布帘 / 绑带@布帘 均 applicable=TRUE）⇒ 两条规则都在 buildRoute 里命中
        when(productionOperationQueryService.operationPositions(TENANT))
                .thenReturn(RoutingModelFixture.canonicalPositions84(TENANT));
        stubGenerate(List.of(orderItemHanzheWithOptions("米白",
                List.of("接高", "双眼皮接高", "余料做绑带", "布绑带", "纱绑带"))));
        when(processingItemMapper.selectById("p1"))
                .thenReturn(ProcessingItem.builder().id("p1").name("韩褶-布").unit("折").build());

        var results = realChainService().generate(List.of("order-001"), TENANT, "u1");
        assertThat(results.get(0).isSuccess()).isTrue();

        ArgumentCaptor<ProcessingPositionOperation> captor =
                ArgumentCaptor.forClass(ProcessingPositionOperation.class);
        verify(positionOperationMapper, atLeastOnce()).insert(captor.capture());
        List<String> names = captor.getAllValues().stream()
                .map(ProcessingPositionOperation::getOperationName).toList();

        // 判别性：两条规则**真的都命中**了（否则下面的「恰好一个」是空断言）
        assertThat(names).as("两条规则指向同一道工序，但只能落一行")
                .contains("接高-布", "绑带-布");
        assertThat(names.stream().filter("接高-布"::equals).count())
                .as("「接高」(160) 与「双眼皮接高」(170) 是**同一道工序** ⇒ 恰好一个（否则按两遍单价拿钱）")
                .isEqualTo(1);
        assertThat(names.stream().filter("绑带-布"::equals).count())
                .as("三条绑带规则（余料做绑带/布绑带/纱绑带）是**同一道工序** ⇒ 恰好一个")
                .isEqualTo(1);
        // 位置按**后应用**（priority 更大）那条规则的锚点：接高 在 精裁 之后、绑带 在 车被 之后
        assertThat(names.indexOf("接高-布")).as("接高 紧跟 精裁-布（规则 170 的锚点）")
                .isEqualTo(names.indexOf("精裁-布") + 1);
        assertThat(names.indexOf("绑带-布")).as("绑带 紧跟 布帘车被（锚点 车被）")
                .isEqualTo(names.indexOf("布帘车被") + 1);
    }

    @Test
    @DisplayName("#4577 任务A：锚点不同的两条规则命中同一工序 ⇒ 位置 = priority 更大那条的锚点（取代语义）")
    void laterRuleReplacesTheOperationAtItsOwnAnchor() {
        stubLibrary();
        List<ProductionRouteRule> rules = new ArrayList<>(RoutingModelFixture.rulesWithFactors(TENANT));
        rules.add(rule("rr-a", "option", "甲", "insert", "绑带", "三边", 1000));
        rules.add(rule("rr-b", "option", "乙", "insert", "绑带", "车被", 1010));
        when(productionOperationQueryService.routeRules(TENANT)).thenReturn(rules);
        stubGenerate(List.of(orderItemHanzheWithOptions("米白", List.of("甲", "乙"))));
        when(processingItemMapper.selectById("p1"))
                .thenReturn(ProcessingItem.builder().id("p1").name("韩褶-布").unit("折").build());

        var results = realChainService().generate(List.of("order-001"), TENANT, "u1");
        assertThat(results.get(0).isSuccess()).isTrue();

        ArgumentCaptor<ProcessingPositionOperation> captor =
                ArgumentCaptor.forClass(ProcessingPositionOperation.class);
        verify(positionOperationMapper, atLeastOnce()).insert(captor.capture());
        List<String> names = captor.getAllValues().stream()
                .map(ProcessingPositionOperation::getOperationName).toList();
        assertThat(names.stream().filter("绑带-布"::equals).count()).isEqualTo(1);
        assertThat(names.indexOf("绑带-布"))
                .as("位置 = **后应用**（priority 1010）那条的锚点「车被」—— 跳过语义会让它停在「三边」")
                .isEqualTo(names.indexOf("布帘车被") + 1);
    }

    @Test
    @DisplayName("#4577 任务A：两条规则命中**不同**工序 ⇒ 互不影响（取代不得写成清掉整段序列）")
    void differentTargetOperationsDoNotInterfere() {
        stubLibrary();
        List<ProductionRouteRule> rules = new ArrayList<>(RoutingModelFixture.rulesWithFactors(TENANT));
        rules.add(rule("rr-a", "option", "甲", "insert", "花边", "三边", 1000));
        rules.add(rule("rr-b", "option", "乙", "insert", "扣环", "车被", 1010));
        when(productionOperationQueryService.routeRules(TENANT)).thenReturn(rules);

        stubGenerate(List.of(orderItemHanzhe("米白")));
        when(processingItemMapper.selectById("p1"))
                .thenReturn(ProcessingItem.builder().id("p1").name("韩褶-布").unit("折").build());
        realChainService().generate(List.of("order-001"), TENANT, "u1");
        ArgumentCaptor<ProcessingPositionOperation> baseCaptor =
                ArgumentCaptor.forClass(ProcessingPositionOperation.class);
        verify(positionOperationMapper, atLeastOnce()).insert(baseCaptor.capture());
        List<String> base = baseCaptor.getAllValues().stream()
                .map(ProcessingPositionOperation::getOperationName).toList();

        reset(positionOperationMapper);
        stubGenerate(List.of(orderItemHanzheWithOptions("米白", List.of("甲", "乙"))));
        var results = realChainService().generate(List.of("order-001"), TENANT, "u1");
        assertThat(results.get(0).isSuccess()).isTrue();
        ArgumentCaptor<ProcessingPositionOperation> captor =
                ArgumentCaptor.forClass(ProcessingPositionOperation.class);
        verify(positionOperationMapper, atLeastOnce()).insert(captor.capture());
        List<String> names = captor.getAllValues().stream()
                .map(ProcessingPositionOperation::getOperationName).toList();

        assertThat(names).as("两道**不同**工序 ⇒ 各加一个").hasSize(base.size() + 2)
                .contains("花边-布", "扣环-布");
        assertThat(names.indexOf("花边-布")).isEqualTo(names.indexOf("布三边") + 1);
        assertThat(names.indexOf("扣环-布")).isEqualTo(names.indexOf("布帘车被") + 1);
        assertThat(names.stream().filter(n -> !"花边-布".equals(n) && !"扣环-布".equals(n)).toList())
                .as("其余工序逐字未动").isEqualTo(base);
    }

    /** 一条规则（issue #4577 的用例自建规则用）。 */
    private static ProductionRouteRule rule(String id, String kind, String trigger, String action,
                                            String operation, String after, int priority) {
        return ProductionRouteRule.builder()
                .id(id).tenantId(TENANT).triggerKind(kind).triggerValue(trigger)
                .position(null).action(action).operation(operation).afterOperation(after)
                .priority(priority).status("active").deleted(0).build();
    }

    @Test
    @DisplayName("#4577 任务B：加工项「花边」命中 processing_item 规则 ⇒ 插「花边-布」；未命中 ⇒ 不插")
    void processingItemRuleInsertsConditionalOperation() {
        stubLibrary();
        when(productionOperationQueryService.routeRules(TENANT))
                .thenReturn(RoutingModelFixture.rulesWithProcessingItems(TENANT));
        stubGenerate(List.of(orderItemWithProcessingItemName("米白", "花边")));
        when(processingItemMapper.selectById("p1"))
                .thenReturn(ProcessingItem.builder().id("p1").name("韩褶-布").unit("折").build());

        var results = realChainService().generate(List.of("order-001"), TENANT, "u1");
        assertThat(results.get(0).isSuccess()).isTrue();

        ArgumentCaptor<ProcessingPositionOperation> captor =
                ArgumentCaptor.forClass(ProcessingPositionOperation.class);
        verify(positionOperationMapper, times(V54_BULIAN_HANZHE.length + 1)).insert(captor.capture());
        List<String> names = captor.getAllValues().stream()
                .map(ProcessingPositionOperation::getOperationName).toList();
        // 触发键 = 加工项名（**精确相等**）⇒ 插在锚点「三边」之后，且**只插一次**
        assertThat(names.indexOf("花边-布")).as("花边 紧跟 布三边（锚点 三边）")
                .isEqualTo(names.indexOf("布三边") + 1);
        assertThat(names.stream().filter("花边-布"::equals).count()).isEqualTo(1);

        // 负例（同断言内，避免两条用例各自打桩漂移）：加工项名「韩褶-布」≠「花边」⇒ 该工序不出现
        reset(positionOperationMapper);
        stubGenerate(List.of(orderItemHanzhe("米白")));
        var without = realChainService().generate(List.of("order-001"), TENANT, "u1");
        assertThat(without.get(0).isSuccess()).isTrue();
        ArgumentCaptor<ProcessingPositionOperation> captor2 =
                ArgumentCaptor.forClass(ProcessingPositionOperation.class);
        verify(positionOperationMapper, times(V54_BULIAN_HANZHE.length)).insert(captor2.capture());
        assertThat(captor2.getAllValues()).extracting(ProcessingPositionOperation::getOperationName)
                .doesNotContain("花边-布");
    }

    /**
     * issue #4616 **端到端判据**：界面新建的 **craft 触发**规则，订单实例化时**真的插了那道工序**。
     *
     * <p>为什么必须端到端：创建端点落库成功 ≠ 规则会生效 —— 触发键（{@code craft} 维）、
     * {@code action}、目标工序逻辑名、锚点在**实例化路径**（{@code ProcessingOrderService.buildRoute}
     * 的规则应用）里各自有一处口径。只断言「落库 trigger_kind='craft'」会漏掉
     * 「规则建好了但订单里没插」这一形态（商家以为配了、加工单上却没有 = 本单要治的病）。</p>
     *
     * <p>规则是**取代**语义（{@link ProcessingOrderService} 的 {@code insertAfterLogical}：
     * 先把序列里已有的该工序移除，再按锚点插入）⇒ 判据是「紧跟锚点 + 恰好一次」，
     * 而不是「多了一道」（后者会把取代当成新增，且总道数会随锚点位置漂）。</p>
     */
    @Test
    @DisplayName("#4616 craft 触发规则 ⇒ 订单实例化真的插该工序（在锚点之后，且恰好一次）")
    void craftRuleInsertsConditionalOperationOnInstantiation() {
        stubLibrary();
        List<ProductionRouteRule> rows = new ArrayList<>(RoutingModelFixture.rulesWithFactors(TENANT));
        rows.add(rule("rr-craft-roman", "craft", "罗马帘", "insert", "定型", "三边", 300));
        when(productionOperationQueryService.routeRules(TENANT)).thenReturn(rows);
        stubGenerate(List.of(processedItemWithSpec("item-1", "布艺遮光帘A", "米白",
                List.of(Map.of("id", "p1", "name", "韩褶-布", "unitPrice", 3.0, "quantity", 2, "unit", "折")),
                spec("curtainType", "布帘", "craft", "罗马帘"))));
        when(processingItemMapper.selectById("p1"))
                .thenReturn(ProcessingItem.builder().id("p1").name("韩褶-布").unit("折").build());

        var results = realChainService().generate(List.of("order-001"), TENANT, "u1");
        assertThat(results.get(0).isSuccess()).isTrue();

        ArgumentCaptor<ProcessingPositionOperation> captor =
                ArgumentCaptor.forClass(ProcessingPositionOperation.class);
        verify(positionOperationMapper, atLeastOnce()).insert(captor.capture());
        List<String> names = captor.getAllValues().stream()
                .map(ProcessingPositionOperation::getOperationName).toList();
        // 锚点「三边」之后插入逻辑工序「定型」（该部位落到工人端的变体 = 定型-布）
        assertThat(names).as("自检：锚点必须真的在序列里（否则 indexOf=-1 会让断言退化）").contains("布三边");
        assertThat(names.indexOf("定型-布")).as("craft 规则命中 ⇒ 定型-布 紧跟 布三边（锚点 三边）")
                .isEqualTo(names.indexOf("布三边") + 1);
        assertThat(names.stream().filter("定型-布"::equals).count())
                .as("恰好一次（规则是**取代**：先把序列里已有的该工序移除再按锚点插入）").isEqualTo(1);

        // 负例（同断言内，避免两条用例各自打桩漂移）：craft 不是「罗马帘」⇒ 该规则不命中，
        // 序列逐字回到基线（定型-布 回到它原来的位置，不在 布三边 之后）
        reset(positionOperationMapper);
        stubGenerate(List.of(orderItemHanzhe("米白")));
        var without = realChainService().generate(List.of("order-001"), TENANT, "u1");
        assertThat(without.get(0).isSuccess()).isTrue();
        ArgumentCaptor<ProcessingPositionOperation> captor2 =
                ArgumentCaptor.forClass(ProcessingPositionOperation.class);
        verify(positionOperationMapper, times(V54_BULIAN_HANZHE.length)).insert(captor2.capture());
        List<String> baseline = captor2.getAllValues().stream()
                .map(ProcessingPositionOperation::getOperationName).toList();
        assertThat(baseline).as("未命中 craft 规则 ⇒ 实例序列逐字等于基线")
                .containsExactlyElementsOf(operationNames(V54_BULIAN_HANZHE));
        assertThat(baseline.indexOf("定型-布")).as("定型-布 不在 布三边 之后（规则未生效）")
                .isNotEqualTo(baseline.indexOf("布三边") + 1);
    }

    @Test
    @DisplayName("#4577 任务B：processing_item 与 option 命中同一道工序 ⇒ 仍恰好一个（跨 kind 也取代）")
    void processingItemAndOptionHittingTheSameOperationInsertOnce() {
        stubLibrary();
        when(productionOperationQueryService.routeRules(TENANT))
                .thenReturn(RoutingModelFixture.rulesWithProcessingItems(TENANT));
        // 加工项「接高」（processing_item 290）与特殊选项「接高」（option 160）都插「接高」
        OrderItem item = orderItemWithProcessingItemName("米白", "接高");
        @SuppressWarnings("unchecked")
        Map<String, Object> info = (Map<String, Object>) item.getProcessingInfo();
        info.put("specialOptions", List.of("接高"));
        stubGenerate(List.of(item));
        when(processingItemMapper.selectById("p1"))
                .thenReturn(ProcessingItem.builder().id("p1").name("韩褶-布").unit("折").build());

        var results = realChainService().generate(List.of("order-001"), TENANT, "u1");
        assertThat(results.get(0).isSuccess()).isTrue();

        ArgumentCaptor<ProcessingPositionOperation> captor =
                ArgumentCaptor.forClass(ProcessingPositionOperation.class);
        verify(positionOperationMapper, atLeastOnce()).insert(captor.capture());
        List<String> names = captor.getAllValues().stream()
                .map(ProcessingPositionOperation::getOperationName).toList();
        assertThat(names.stream().filter("接高-布"::equals).count())
                .as("两个 kind 命中同一道工序 ⇒ 只落一行").isEqualTo(1);
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
            // 🔴 issue #4937 / O4：`打包` 的**矩阵价是 NULL**（「未定价」，不是 0 元）
            // —— 夹具里那一行的工序库价写 `0.0`（DDL `NOT NULL DEFAULT 0` 的产物），
            // 实例侧必须落 `null`（`buildRoute` 不回落工序库行价，issue #4696 红线）。
            if ("打包".equals(row[0])) {
                assertThat(instances.get(i).getUnitPrice())
                        .as("第 %d 道（打包）单价必须是 null（未定价 ≠ 0 元）", i + 1)
                        .isNull();
            } else {
                assertThat(instances.get(i).getUnitPrice()).isEqualByComparingTo(row[3]);
            }
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
        // 空库（零路线模板 ∧ 零默认工艺）⇒ 两条 fail-closed 都成立；判据 = 可行动地中止生成，
        // 不回退任何常量/加工项目录（具体措辞由实现选，不把文案当判据）
        assertThat(results.get(0).getMessage()).contains("无法实例化工序");
        // 可见性②：可行动 suggestion（说出补救入口）
        assertThat(results.get(0).getSuggestion())
                .contains("/api/admin/production/routings");
        // 不落半成品：一行不写、订单状态不动（否则会留下「有加工单、无工序、无 qr_token」的孤儿态）
        verify(processingOrderMapper, never()).insert(any(ProcessingOrder.class));
        verify(orderService, never()).updateOrderStatus(anyString(), anyString());
        verify(productionService, never()).instantiate(anyString(), any(), anyLong());
    }

    @Test
    @DisplayName("#4116 切库负例②b：路线引用的工序在库中无活跃行 ⇒ 同样 fail-closed（指名报缺）")
    void generateFailsClosedWhenRouteCitesMissingOperation() {
        // 库里这条路线存在，但主线引用的一道工序在该租户工序库里**没有行**（P2b：注入法 =
        // 从工序库元数据里挖掉「韩褶-布」⇒ 变体名解析不到 ⇒ 登记进 missing_operations）
        stubLibrary();
        Map<String, Map<String, Object>> broken = RoutingModelFixture.catalog();
        broken.remove("韩褶-布");
        when(productionOperationQueryService.operationsByName(TENANT)).thenReturn(broken);
        when(orderMapper.selectById("order-001")).thenReturn(confirmedOrder);
        when(orderItemMapper.selectList(any())).thenReturn(List.of(orderItemHanzhe("米白")));
        when(processingOrderMapper.selectActiveByOrderId("order-001", TENANT)).thenReturn(null);

        var results = processingOrderService.generate(List.of("order-001"), TENANT, "u1");

        assertThat(results.get(0).isSuccess()).isFalse();
        assertThat(results.get(0).getCode()).isEqualTo(ProcessingOrderService.ERR_OPERATION_NOT_FOUND);
        assertThat(results.get(0).getMessage()).as("指名报缺：报的是**逻辑工序名**（韩褶），可行动建议给库入口")
                .contains("韩褶");
        assertThat(results.get(0).getSuggestion()).contains("/api/admin/production/operations-catalog");
        verify(processingOrderMapper, never()).insert(any(ProcessingOrder.class));
    }

    // ══════════════ 实例化不再静默丢（issue #4609，P0 的实例化半边）══════════════
    //
    // 病根：`applicableByLogical` 按**逻辑名**建键，而主线里可能存着**变体名**（`精裁-布`）⇒
    // `get("精裁-布")` = null，与「该部位明确不做」（键存在且 false）**共用**一条 `continue`
    // ⇒ 该道工序被静默丢掉：商家在界面上加了工序、路线卡片上也看得见，但加工单里没有它，
    // 且**没有任何报错**（工人少一道活、少拿一笔计件钱）。
    // 拆法：键不存在 ∧ 名字**根本不是逻辑工序名** ⇒ 进 `missing_operations`（可见，调用方 fail-closed）；
    // 键存在且 false（该部位明确不做）⇒ 静默滤掉（**既有语义不变**）。

    @Test
    @DisplayName("#4609 实例化不再静默丢：主线里的**变体名**（未知名字）⇒ 进 missing_operations 并 fail-closed")
    void unknownMainlineNameIsReportedInsteadOfSilentlyDropped() {
        stubLibrary();
        // 存量污染形态（修复前用界面加过工序的路线就是这样）：主线里存的是**变体名** `精裁-布`。
        ProductionRouteTemplate polluted = RoutingModelFixture.defaultTemplate(TENANT);
        polluted.setMainline(new ArrayList<>(List.of("精裁", "精裁-布", "外帘装袋")));
        lenient().when(productionOperationQueryService.defaultRouteTemplate(TENANT)).thenReturn(polluted);
        when(productionOperationQueryService.routeTemplateFor(eq(TENANT), anyString())).thenReturn(polluted);
        when(orderMapper.selectById("order-001")).thenReturn(confirmedOrder);
        when(orderItemMapper.selectList(any())).thenReturn(List.of(orderItemHanzhe("米白")));
        // 幂等前置查询第一次返回 null；插入后回填同一行（同 stubGenerate）——
        // 改后 fail-closed 发生在落库**之前**（insert 不被调用，故 lenient），
        // 改前它会一路走到生成成功（那道工序被静默滤掉、加工单照样落库）—— 那正是本用例要红的形态。
        java.util.concurrent.atomic.AtomicReference<ProcessingOrder> poRef =
                new java.util.concurrent.atomic.AtomicReference<>();
        when(processingOrderMapper.selectActiveByOrderId("order-001", TENANT)).thenAnswer(inv -> poRef.get());
        lenient().when(processingOrderMapper.insert(any(ProcessingOrder.class))).thenAnswer(inv -> {
            ProcessingOrder inserted = inv.getArgument(0);
            inserted.setId("po-001");
            poRef.set(inserted);
            return 1;
        });
        when(processingItemMapper.selectById("p1"))
                .thenReturn(ProcessingItem.builder().id("p1").name("韩褶-布").unit("折").build());

        var results = realChainService().generate(List.of("order-001"), TENANT, "u1");

        assertThat(results.get(0).isSuccess())
                .as("改前：静默滤掉 ⇒ 生成成功但少一道（本断言红）").isFalse();
        assertThat(results.get(0).getCode()).isEqualTo(ProcessingOrderService.ERR_OPERATION_NOT_FOUND);
        assertThat(results.get(0).getMessage()).as("指名报出主线里那个**不认识的名字**").contains("精裁-布");
        assertThat(results.get(0).getSuggestion()).as("失败必须可行动").contains("operations-catalog");
        verify(processingOrderMapper, never()).insert(any(ProcessingOrder.class));
        verify(positionOperationMapper, never()).insert(any(ProcessingPositionOperation.class));
    }

    @Test
    @DisplayName("🔴 新判据（#4937）：`帘头制作` **不再**被「部位适用性」滤掉 —— 它按主线照常落实例")
    void curtainHeadOperationIsNoLongerFilteredByApplicability() {
        // ⚠️ **本判据取代已退休的 `notApplicableOperationsAreStillFilteredSilently`**：
        // 后者的判据是「`帘头制作 × 布帘` 是 applicable=false ⇒ 该道**静默滤掉**」——
        // 用户 2026-09-21 裁定（母单 #4936「我们移除了部位的设计，不计成本的改」）把那条过滤
        // **整块删除** ⇒ 旧判据的前提消失，**退休**。
        // 新判据 = **同一份桩、相反的期望**：`帘头制作` 必须**出现在实例里**（部位不再参与取路）
        // —— 守卫强度不降（它照样钉住「过滤真的退场了」，只是方向反过来）。
        stubLibrary();
        when(productionOperationQueryService.operationPositions(TENANT))
                .thenReturn(RoutingModelFixture.canonicalPositions84(TENANT));
        ProductionRouteTemplate withCurtainHead = RoutingModelFixture.defaultTemplate(TENANT);
        withCurtainHead.setMainline(new ArrayList<>(List.of("精裁", "帘头制作", "外帘装袋")));
        lenient().when(productionOperationQueryService.defaultRouteTemplate(TENANT)).thenReturn(withCurtainHead);
        when(productionOperationQueryService.routeTemplateFor(eq(TENANT), anyString())).thenReturn(withCurtainHead);
        stubGenerate(List.of(orderItemHanzhe("米白")));
        when(processingItemMapper.selectById("p1"))
                .thenReturn(ProcessingItem.builder().id("p1").name("韩褶-布").unit("折").build());

        var results = realChainService().generate(List.of("order-001"), TENANT, "u1");

        assertThat(results.get(0).isSuccess()).as("主线里的工序都能解析 ⇒ 照常生成").isTrue();
        ArgumentCaptor<ProcessingPositionOperation> captor =
                ArgumentCaptor.forClass(ProcessingPositionOperation.class);
        verify(positionOperationMapper, atLeastOnce()).insert(captor.capture());
        assertThat(captor.getAllValues()).extracting(ProcessingPositionOperation::getOperationName)
                .as("`帘头制作` 必须落实例（部位适用性过滤已退场 ⇒ 主线里的每一道都实例化）")
                .contains("帘头制作")
                .contains("精裁-布");
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
        // P2b：判别物 = 实际实例化的工序序列（新结构里「部位×工艺」不再选路线模板 ⇒
        // 旧 findRouting 那两条 verify 已不适用；序列本身就是「用了哪条路线」的证据）
        // 实例 = 默认路线（布帘×韩褶 11 道），不是空实例、也不是别的路线
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
        // P2b：判别物 = 默认路线（11 道）与其中「韩褶-布」这道（新结构里工艺触发的是**规则**，
        // 不再是「选哪条路线」）
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
        // 派生键命中 工艺=打孔 ⇒ 规则插入「打孔」（10 道），**不**回落到韩褶的 11 道。
        // P2b 判别物 = 序列里是「打孔-布」而不是「韩褶-布」+ 道数（10 ≠ 11）。
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
        verify(positionOperationMapper, times(12))
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
        // 直读 ⇒ 取订单写下的键，且**不查**信号映射表（派生只是存量单兜底）。
        // P2b 判别物 = 实例序列 = 纱帘×打孔（6 道）而非布帘的 11 道（下方 containsExactlyElementsOf）。
        verify(productionOperationQueryService, never()).routeSignals(TENANT);

        ArgumentCaptor<ProcessingOrder> poCaptor = ArgumentCaptor.forClass(ProcessingOrder.class);
        verify(processingOrderMapper).insert(poCaptor.capture());
        assertThat(poCaptor.getValue().getRouteKey())
                .as("P2b：route_key = 实际使用的路线（具名模板）")
                .isEqualTo(RoutingModelFixture.TEMPLATE_NAME);
        assertThat(poCaptor.getValue().getRouteSource()).as("直读 = 新增第 5 态 direct").isEqualTo("direct");
        assertThat(poCaptor.getValue().getRouteRequestedKey()).isEqualTo("纱帘×打孔");

        ArgumentCaptor<ProcessingPositionOperation> opCaptor =
                ArgumentCaptor.forClass(ProcessingPositionOperation.class);
        verify(positionOperationMapper, times(V54_BULIAN_DAKONG.length)).insert(opCaptor.capture());
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
        verify(positionOperationMapper, times(12))
                .insert(any(ProcessingPositionOperation.class));
    }

    @Test
    @DisplayName("#4354 判据 E：两维全缺且派生也拿不到路线 ⇒ fail-closed（不静默落别的路线、不落半成品）")
    void missingCraftSpecAndUnderivableRouteFailsClosed() {
        // 库里**只有**一条「纱帘」专属路线模板、**没有默认路线**：两维全缺 ⇒ 派生全不命中 ⇒
        // 部位取默认「布帘」⇒ 布帘没有模板 ⇒ 回落默认模板 ⇒ 也没有 ⇒ T3 ⇒ 中止生成
        when(productionOperationQueryService.routeTemplateFor(eq(TENANT), anyString())).thenReturn(null);
        when(productionOperationQueryService.defaultRouteTemplate(TENANT)).thenReturn(null);
        when(productionOperationQueryService.routingKeys(TENANT)).thenReturn(List.of("纱帘专用路线"));
        // 该租户有默认工艺（否则会先撞「缺 craft 且无默认工艺」那条 fail-closed，判据就换了形态）
        lenient().when(productionOperationQueryService.defaultCraft(TENANT)).thenReturn("韩褶");
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
        assertThat(poCaptor.getValue().getRouteKey())
                .as("P2b：route_key = 实际使用的路线（具名模板）")
                .isEqualTo(RoutingModelFixture.TEMPLATE_NAME);
        assertThat(poCaptor.getValue().getRouteRequestedKey())
                .as("派生出来的键 = 布帘×韩褶（空白键不是值）").isEqualTo("布帘×韩褶");
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
        // 一个部位 ⇒ 算料只被问一个部位（否则褶数/开数按「两扇窗」各算一次 = 双算）
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
        verify(positionOperationMapper, times(12))
                .insert(any(ProcessingPositionOperation.class));
    }

    @Test
    @DisplayName("#4387 判据 2：一樘「布 + 纱」= 两条明细行、各成部位、同 craftLineId ⇒ 加工单两个部位"
            + "（工序 **14 道**：部位级 8 + 3 + 套级 3 各一次 —— issue #4384 A2 起，旧值 17 已作废）")
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
        // 工序 = 布帘×韩褶的**部位级 8 道** + 套级 3 道（每樘窗一次，挂主布行部位）+ 纱帘×打孔的**部位级 3 道**
        // ⚠️ 旧断言是「11 + 6 = 17」——那是 **A2 之前**的行为：套级 3 道（外帘打卷/装袋/发货）在两条
        // 部位路线里各出现一次 ⇒ 各算两遍、计件双付。真值源 §8 明写「外帘是加工单**打印行部位**，
        // **不是**路线键」⇒ 套级**本就不该按部位重复**，故 17 不再是正确期望（设计文档 §5.2：修正后 14）。
        ArgumentCaptor<ProcessingPositionOperation> opCaptor =
                ArgumentCaptor.forClass(ProcessingPositionOperation.class);
        verify(positionOperationMapper, times(partLevelOperationNames(V54_BULIAN_HANZHE).size()
                + setLevelOperationNames(V54_BULIAN_HANZHE).size()
                + partLevelOperationNames(V58_SHALU_DAKONG).size())).insert(opCaptor.capture());
        List<String> expected = new ArrayList<>(partLevelOperationNames(V54_BULIAN_HANZHE));
        expected.addAll(setLevelOperationNames(V54_BULIAN_HANZHE));
        expected.addAll(partLevelOperationNames(V58_SHALU_DAKONG));
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

    // ── 套级工序去重（issue #4384 **A2**）─────────────────────────────────────
    //
    // A1（#4397 / V67）把 `scope ∈ {position, set}` 落进工序库，读面逐字带出；
    // A2（本单）在实例化侧让**套级工序每樘窗（`craftGroupKey` 组）只出现一次**。
    // 判据**必须**是库里的 `scope` —— 硬编码 `外帘打卷/装袋/发货` 即「常量散在代码里、商家改了库不生效」。

    /** 本次生成落库的全部工序实例（不预设条数 —— 去重后条数本身就是判据）。 */
    private List<ProcessingPositionOperation> allInstances() {
        ArgumentCaptor<ProcessingPositionOperation> captor =
                ArgumentCaptor.forClass(ProcessingPositionOperation.class);
        verify(positionOperationMapper, atLeastOnce()).insert(captor.capture());
        return captor.getAllValues();
    }

    /** 已实例化的工序里 `operation` 出现几次（红证/回归判据的公共读数）。 */
    private static long instanceCountOf(List<ProcessingPositionOperation> instances, String operation) {
        return instances.stream().filter(i -> operation.equals(i.getOperationName())).count();
    }

    /** 路线里的**部位级**工序名（剔除 `scope='set'`）—— 与 V67 的库终态同口径。 */
    private static List<String> partLevelOperationNames(String[][] table) {
        return operationNames(table).stream().filter(name -> !SET_SCOPE_OPERATIONS.contains(name)).toList();
    }

    /** 路线里的**套级**工序名（`scope='set'`，按路线内顺序）。 */
    private static List<String> setLevelOperationNames(String[][] table) {
        return operationNames(table).stream().filter(SET_SCOPE_OPERATIONS::contains).toList();
    }

    @Test
    @DisplayName("#4384 A2 判据 1+2：一樘「布+纱」⇒ 套级「外帘装袋」**恰好 1 行**、总工序 **14 道**（A2 之前 = 2 行 / 17 道）")
    void setLevelOperationsInstantiateOncePerWindow() {
        stubLibrary();
        stubGenerate(clothPlusSheerWindow());

        var results = realChainService().generate(List.of("order-001"), TENANT, "u1");

        assertThat(results.get(0).isSuccess()).isTrue();
        List<ProcessingPositionOperation> instances = allInstances();
        assertThat(instances)
                .as("部位级 8（布帘×韩褶）+ 3（纱帘×打孔）+ 套级 3（每樘窗一次）= 14（设计文档 §5.2）")
                .hasSize(partLevelOperationNames(V54_BULIAN_HANZHE).size()
                        + setLevelOperationNames(V54_BULIAN_HANZHE).size()
                        + partLevelOperationNames(V58_SHALU_DAKONG).size());
        assertThat(instanceCountOf(instances, "外帘打卷"))
                .as("套级工序每樘窗一次（旧行为 2 次 ⇒ 打卷/装袋/发货各双付）").isEqualTo(1);
        assertThat(instanceCountOf(instances, "外帘装袋")).isEqualTo(1);
        assertThat(instanceCountOf(instances, "外帘发货")).isEqualTo(1);
        // 两个部位仍在（布行/纱行各成部位；部位级工序不合并）—— 去重**不得**退化成「合并部位」
        assertThat(instances).extracting(ProcessingPositionOperation::getPositionName)
                .contains("布艺遮光帘A 米白", "纱帘A 米白");
        // 套级工序挂**樘窗代表行（主布行）**的部位名下 ⇒ 工人扫码端（按 position_name 分组）仍看得到它们
        assertThat(instances).filteredOn(i -> SET_SCOPE_OPERATIONS.contains(i.getOperationName()))
                .as("套级工序全部挂主布行部位（不新增「外帘」部位行）")
                .isNotEmpty()
                .allSatisfy(i -> assertThat(i.getPositionName()).isEqualTo("布艺遮光帘A 米白"));
    }

    @Test
    @DisplayName("#4384 A2 判据 3（回归）：单部位订单（只有布帘）⇒ 套级工序仍**恰好 1 行**、总工序 11 道（存量行为逐字不变）")
    void singlePositionOrderKeepsItsSetLevelOperations() {
        stubLibrary();
        stubGenerate(List.of(orderItemHanzhe("米白")));

        realChainService().generate(List.of("order-001"), TENANT, "u1");

        List<ProcessingPositionOperation> instances = allInstances();
        assertThat(instances).as("单行樘窗：套级工序挂在它自己身上 ⇒ 条数与去重前逐字一致")
                .hasSize(V54_BULIAN_HANZHE.length);
        assertThat(instanceCountOf(instances, "外帘装袋")).isEqualTo(1);
    }

    @Test
    @DisplayName("#4384 A2 判据 4（回归）：两樘**各自独立**的单行窗（无 craftLineId）⇒ 每樘各 1 行套级（共 2 行 —— 按组去重，**不是**全局去重）")
    void separateWindowsEachKeepTheirOwnSetLevelOperations() {
        stubLibrary();
        OrderItem windowA = processedItemWithSpec("item-1", "布艺遮光帘A", "米白",
                List.of(Map.of("id", "p1", "name", "韩褶-布", "unitPrice", 3.0, "quantity", 2, "unit", "折")),
                spec("curtainType", "布帘", "craft", "韩褶"));
        OrderItem windowB = processedItemWithSpec("item-2", "布艺遮光帘B", "米白",
                List.of(Map.of("id", "p2", "name", "韩褶-布", "unitPrice", 3.0, "quantity", 2, "unit", "折")),
                spec("curtainType", "布帘", "craft", "韩褶"));
        stubGenerate(List.of(windowA, windowB));

        realChainService().generate(List.of("order-001"), TENANT, "u1");

        List<ProcessingPositionOperation> instances = allInstances();
        assertThat(instances).as("两樘独立窗 = 2 × 路线道数（每樘各带自己的套级工序）")
                .hasSize(V54_BULIAN_HANZHE.length * 2);
        assertThat(instanceCountOf(instances, "外帘装袋"))
                .as("去重必须**按樘窗组**：两樘窗各 1 行 ⇒ 2 行（全局去重会误吞第二樘的套级工序）")
                .isEqualTo(2);
    }

    @Test
    @DisplayName("#4384 A2 注入法：库把「外帘装袋」的 scope 改回 position ⇒ **不去重**（判据是库里的 scope，不是硬编码工序名）")
    void setLevelDedupFollowsLibraryScopeNotOperationNames() {
        // 库桩 = V67 终态，但**商家把「外帘装袋」改回部位级**（工序库可配，A1 已接线）
        // P2b：scope 由工序库元数据逐字带出（`operationsByName`）⇒ 注入点在这里
        stubLibrary();
        Map<String, Map<String, Object>> overridden = RoutingModelFixture.catalog();
        Map<String, Object> packing = new LinkedHashMap<>(overridden.get("外帘装袋"));
        packing.put("scope", "position");
        overridden.put("外帘装袋", packing);
        when(productionOperationQueryService.operationsByName(TENANT)).thenReturn(overridden);
        stubGenerate(clothPlusSheerWindow());

        realChainService().generate(List.of("order-001"), TENANT, "u1");

        List<ProcessingPositionOperation> instances = allInstances();
        assertThat(instanceCountOf(instances, "外帘装袋"))
                .as("库里说 position ⇒ 按部位各出一次（2）—— 硬编码工序名的实现会在这里假绿")
                .isEqualTo(2);
        assertThat(instanceCountOf(instances, "外帘打卷")).as("其余仍是 set ⇒ 仍去重").isEqualTo(1);
    }

    // ── ⭐ issue #4693：口径改判「一樘窗 = 一套」（作废 #4373「1 个窗帘商品 = 1 套」）──────
    //
    // 用户裁定（2026-09-20，逐字）：「A. **一樘窗 = 一套**（零售常态）」。
    // 现行口径（设计文档 `docs/design/position-instance-routing-model.md` §2.1.1）：
    //   **一套 = 一樘窗 = 一个 `craftLineId` 组** —— 一个窗户的**全部部位**
    //   （布帘 + 纱帘 + 帘头）**合计一套**；一条 `order_items` 行仍是一个**部位**（R-a 不变）。
    // 旧口径（#4373）把「套」钉在**明细行**上 ⇒ 同一樘窗的 3 条部位行 = **3 套**（已作废）。
    //
    // 判别物 = **套级工序**（`scope='set'`，每樘窗一次）：它**按樘窗组**实例化
    // （`ProcessingOrderService.setLevelKeeperItemIds`）⇒ 各出现 1 次 = 1 套。

    @Test
    @DisplayName("#4693 一樘窗含全部部位（布帘+纱帘+帘头）= **3 个部位、1 套**"
            + "（套级工序各 1 道 —— 旧口径「套 ≡ 明细行」下是 3 道 / 3 套）")
    void oneWindowWithAllPositionsIsExactlyOneSet() {
        stubLibrary();
        stubGenerate(clothSheerValanceWindow());

        var results = realChainService().generate(List.of("order-001"), TENANT, "u1");

        assertThat(results.get(0).isSuccess()).isTrue();
        // 前置自断言（**不是**被测行为）：这确实是「一樘窗含全部部位」的**三行**夹具 ——
        // 旧口径（套 ≡ 明细行）下这个数就是「套数」= 3，红证读数由此可复核。
        ArgumentCaptor<List<Map<String, Object>>> reqCaptor = ArgumentCaptor.forClass(List.class);
        verify(productionOperationQtyClient).resolve(reqCaptor.capture());
        assertThat(reqCaptor.getValue())
                .as("前置：一樘窗 = 3 条明细行 = 3 个部位（旧口径据此算 3 套）")
                .hasSize(3);
        assertThat(reqCaptor.getValue()).extracting(p -> p.get("position_name"))
                .containsExactly("布艺遮光帘A 米白", "纱帘A 米白", "帘头A 米白");

        List<ProcessingPositionOperation> instances = allInstances();

        // ⭐ 被测断言：**一樘窗 = 一套** ⇒ 套级工序各恰好 1 道（旧口径 = 各 3 道）
        assertThat(instanceCountOf(instances, "外帘打卷"))
                .as("一樘窗（含全部部位）= 1 套 ⇒ 套级「外帘打卷」恰好 1 道；"
                        + "旧口径「套 ≡ 明细行」= 3 道（每部位一遍 ⇒ 打卷/装袋/发货各三付）")
                .isEqualTo(1);
        assertThat(instanceCountOf(instances, "外帘装袋")).as("同上：一樘窗 = 1 套").isEqualTo(1);
        assertThat(instanceCountOf(instances, "外帘发货")).as("同上：一樘窗 = 1 套").isEqualTo(1);
        assertThat(instances).filteredOn(i -> SET_SCOPE_OPERATIONS.contains(i.getOperationName()))
                .as("套级工序全部挂**樘窗代表行（主布行）**的部位名下 ⇒ 一樘窗只有一处套级归属")
                .isNotEmpty()
                .allSatisfy(i -> assertThat(i.getPositionName()).isEqualTo("布艺遮光帘A 米白"));

        // 反向：**部位**仍各成一条（一樘窗 ≠ 一个部位）—— 「1 套」不得退化成「合并部位」
        assertThat(instances).extracting(ProcessingPositionOperation::getPositionName)
                .as("3 个部位各自都有自己的工序实例（合并部位 ⇒ 这条红）")
                .contains("布艺遮光帘A 米白", "纱帘A 米白", "帘头A 米白");
    }

    @Test
    @DisplayName("#4693 边界：多樘窗（各含全部部位）⇒ **各 1 套**（总套数 = 窗数，不随部位数增长）")
    void eachWindowIsExactlyOneSetRegardlessOfPositionCount() {
        stubLibrary();
        OrderItem clothA = processedItemWithSpec("item-1", "布艺遮光帘A", "米白",
                List.of(Map.of("id", "p1", "name", "韩褶-布", "unitPrice", 3.0, "quantity", 2, "unit", "折")),
                spec("curtainType", "布帘", "craft", "韩褶", "componentRole", "主布", "craftLineId", "win-1"));
        OrderItem sheerA = processedItemWithSpec("item-2", "纱帘A", "米白",
                List.of(Map.of("id", "p2", "name", "打孔-纱", "unitPrice", 3.0, "quantity", 2, "unit", "孔")),
                spec("curtainType", "纱帘", "craft", "打孔", "componentRole", "纱", "craftLineId", "win-1"));
        OrderItem clothB = processedItemWithSpec("item-3", "布艺遮光帘B", "米白",
                List.of(Map.of("id", "p3", "name", "韩褶-布", "unitPrice", 3.0, "quantity", 2, "unit", "折")),
                spec("curtainType", "布帘", "craft", "韩褶", "componentRole", "主布", "craftLineId", "win-2"));
        OrderItem sheerB = processedItemWithSpec("item-4", "纱帘B", "米白",
                List.of(Map.of("id", "p4", "name", "打孔-纱", "unitPrice", 3.0, "quantity", 2, "unit", "孔")),
                spec("curtainType", "纱帘", "craft", "打孔", "componentRole", "纱", "craftLineId", "win-2"));
        stubGenerate(List.of(clothA, sheerA, clothB, sheerB));

        realChainService().generate(List.of("order-001"), TENANT, "u1");

        List<ProcessingPositionOperation> instances = allInstances();
        assertThat(instanceCountOf(instances, "外帘装袋"))
                .as("两樘窗（各含布+纱）= **2 套** ⇒ 套级「外帘装袋」2 道；"
                        + "旧口径「套 ≡ 明细行」= 4 道 / 4 套")
                .isEqualTo(2);
        assertThat(instanceCountOf(instances, "外帘打卷")).isEqualTo(2);
    }

    @Test
    @DisplayName("#4693 边界：一樘窗只含布帘（单行）= **1 套**（单部位窗不被多算、也不被少算）")
    void singlePositionWindowIsOneSet() {
        stubLibrary();
        stubGenerate(List.of(orderItemHanzhe("米白")));

        realChainService().generate(List.of("order-001"), TENANT, "u1");

        List<ProcessingPositionOperation> instances = allInstances();
        assertThat(instanceCountOf(instances, "外帘打卷")).as("单行樘窗 = 1 套").isEqualTo(1);
        assertThat(instanceCountOf(instances, "外帘装袋")).as("单行樘窗 = 1 套").isEqualTo(1);
    }

    /**
     * 生成一张加工单，按**真实** {@link ProductionService#piecework} 算该单计件（逐笔 = 合格 1 × 实例单价 × 系数）。
     *
     * <p>与 {@link #pieceworkTotalFor} **同款装配**：聚合算法只有一份
     * （`ProductionService.aggregate`，per-order 汇总 / 期间报表 / 工人计件共用）—— 本方法不另写计算。</p>
     */
    private Map<String, Object> pieceworkFor(List<OrderItem> items) {
        stubLibrary();
        stubGenerate(items);
        List<ProcessingPositionOperation> stored = new ArrayList<>();
        when(positionOperationMapper.insert(any(ProcessingPositionOperation.class))).thenAnswer(inv -> {
            ProcessingPositionOperation row = inv.getArgument(0);
            row.setId("op-" + (stored.size() + 1));
            stored.add(row);
            return 1;
        });

        var results = realChainService().generate(List.of("order-001"), TENANT, "u1");
        assertThat(results.get(0).isSuccess()).isTrue();
        assertThat(stored).extracting(ProcessingPositionOperation::getOperationName)
                .as("桩必须真的实例化了库路线的工序（空集 ⇒ 计件合计恒 0 ⇒ 下面的断言空转）；"
                        + "#4337：旧形态 isNotEmpty() 只证「有东西」⇒ 少一道工序也照样绿")
                .contains("精裁-布", "韩褶-布");

        // 对**全部**实例各报一笔「合格 1」（worker/单价/系数都取自实例快照）
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
                workLogMapper, orderMapper, orderItemMapper, clientRequestIdService);
        return real.piecework("order-001", TENANT);
    }

    /** 计件结果里**套级工序**（`scope='set'`）那几道的合计金额（逐笔四舍五入到分的既有口径）。 */
    @SuppressWarnings("unchecked")
    private static BigDecimal setLevelPieceworkAmount(Map<String, Object> piecework) {
        List<Map<String, Object>> perOperation = (List<Map<String, Object>>) piecework.get("per_operation");
        return perOperation.stream()
                .filter(row -> SET_SCOPE_OPERATIONS.contains(String.valueOf(row.get("operation"))))
                .map(row -> (BigDecimal) row.get("amount"))
                .reduce(BigDecimal.ZERO, BigDecimal::add);
    }

    @Test
    @DisplayName("#4384 A2 判据 5（端到端计件）：一樘「布+纱」的**套级计件 = ¥3.00**，与单部位订单**相同**（旧行为 ¥6.00 ⇒ 双付）")
    void setLevelPieceworkDoesNotDoubleForClothPlusSheer() {
        // 同一夹具、两种形态对照：单部位（只有布帘）vs 布+纱 樘窗。
        // 单边断言会假绿（「去重过头把套级全吞掉」也能让 布+纱 那一侧变小）⇒ 两侧必须相等。
        BigDecimal single = setLevelPieceworkAmount(pieceworkFor(List.of(orderItemHanzhe("米白"))));
        BigDecimal window = setLevelPieceworkAmount(pieceworkFor(clothPlusSheerWindow()));

        assertThat(single).as("单部位：套级 3 道（外帘打卷/装袋/发货）各 ¥1.00 × 1 套")
                .isEqualByComparingTo("3.00");
        assertThat(window)
                .as("布+纱：套级工序每樘窗一次 ⇒ ¥3.00（旧行为 = 两条部位路线各一份 ⇒ ¥6.00）")
                .isEqualByComparingTo("3.00");
        assertThat(window).as("两种形态的套级计件必须相同（不翻倍）").isEqualByComparingTo(single);
    }

    // ── 工序实例定位键（issue #4388 / #4373 裁定）───────────────────────────────
    //
    // 缺陷形态：`processing_position_operations` 只有 `position_name`（展示名 = 加工产物名[+色号]）
    // ⇒ **同商品同色号的两个窗同名** ⇒
    //   ① 读面 `ProductionService.buildPositions` 按名字分组 ⇒ **两个部位并成一个**（工人扫码/详情
    //      看到「一个部位 22 道工序」，而不是「两个部位各 11 道」）；
    //   ② 算料 `qty` 回填靠**数组位次**对齐（`fillQty` 的 `resolved.get(i) ↔ operationRows.get(i)`），
    //      响应一旦重排就是**静默错配**（只有条数校验，没有身份校验）。
    // 本单：主定位键 = `(order_item_id, position_kind)`（V69）；qty 对齐带**身份校验**（fail-closed）；
    // 读面按 `order_item_id` 分组，**存量行（NULL）按 `position_name` 兜底** ⇒ 行为逐字不变。

    /** 韩褶-布加工项（与既有夹具同款；只影响 qty 的米数来源，不影响路线）。 */
    private static List<Map<String, Object>> hanzheProc() {
        return List.of(Map.of("id", "p1", "name", "韩褶-布", "unitPrice", 3.0,
                "quantity", 2, "unit", "折"));
    }

    /**
     * 两条**同名部位**（同商品同色号的两个窗），各自带**自己的**算料输出（米数 12.3 / 8.0）。
     *
     * <p>这就是 `buildPositionPayload` 自述的「同商品同色号的两行会重名」形态 ——
     * 只靠 `position_name` 无法区分它们。</p>
     */
    private List<OrderItem> sameNamedWindows() {
        return List.of(
                processedItemWithSpec("item-1", "布艺遮光帘A", "米白", hanzheProc(),
                        spec("curtainType", "布帘", "craft", "韩褶",
                                "fabric_meters", new BigDecimal("12.3"))),
                processedItemWithSpec("item-2", "布艺遮光帘A", "米白", hanzheProc(),
                        spec("curtainType", "布帘", "craft", "韩褶",
                                "fabric_meters", new BigDecimal("8.0"))));
    }

    /**
     * 局部桩：米类工序按**该部位自己的** `calc_info.fabric_meters` 供数（其余 = 1/fallback）。
     * ⇒ 「qty 取自自己那条明细行」与「按订单行取值 / 位次错配」在断言上可区分。
     */
    private void stubQtyFromOwnCalcInfo() {
        // ⚠️ 必须用 `doAnswer().when(...)`：`when(mock.method(any()))` 在**注册时**会真的调一次 mock
        // ⇒ 落到 setUp 的旧桩上（`any()` 传 null）⇒ NPE。既有 `stubQty` 已占位，这里是**改写**它。
        doAnswer(inv -> {
            List<Map<String, Object>> request = inv.getArgument(0);
            List<ProductionOperationQtyClient.PositionQty> resolved = new ArrayList<>();
            for (Map<String, Object> position : request) {
                Object meters = calcInfoOf(position).get("fabric_meters");
                Map<String, BigDecimal> qty = new LinkedHashMap<>();
                Map<String, String> source = new LinkedHashMap<>();
                for (Object raw : (List<?>) position.get("operations")) {
                    String operation = String.valueOf(raw);
                    if ("米".equals(unitOfOperation(operation)) && meters != null) {
                        qty.put(operation, new BigDecimal(String.valueOf(meters)));
                        source.put(operation, "fabric_meters");
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

    /** 生成加工单 + **回填实例 id** + 让读面/报工能取到实例（返回落库实例）。 */
    private List<ProcessingPositionOperation> generateAndStore(List<OrderItem> items) {
        stubLibrary();
        stubGenerate(items);
        List<ProcessingPositionOperation> stored = new ArrayList<>();
        when(positionOperationMapper.insert(any(ProcessingPositionOperation.class))).thenAnswer(inv -> {
            ProcessingPositionOperation row = inv.getArgument(0);
            row.setId("op-" + (stored.size() + 1));
            stored.add(row);
            return 1;
        });
        var results = realChainService().generate(List.of("order-001"), TENANT, "u1");
        assertThat(results.get(0).isSuccess()).as("生成加工单必须成功（否则后续判据无意义）").isTrue();
        // lenient：只给「还要读面/报工」的用例备着 —— 严格桩会把「备而不用」判为失败（噪音）
        lenient().when(positionOperationMapper.selectList(any())).thenReturn(stored);
        return stored;
    }

    /** 读面（扫工页/加工单详情）：`ProductionService.getOperations` 的部位树。 */
    @SuppressWarnings("unchecked")
    private List<Map<String, Object>> readPositions() {
        ProductionService real = new ProductionService(processingOrderMapper, positionOperationMapper,
                workLogMapper, orderMapper, orderItemMapper, clientRequestIdService);
        return (List<Map<String, Object>>) real.getOperations("order-001", TENANT).get("positions");
    }

    /**
     * 部位树里**某一行**（按 `order_item_id`）某道工序的 `qty`。
     *
     * <p>⚠️ 按行标识取而不是按下标取：读面的部位顺序由 `buildPositions` 的 `HashSet` 迭代序决定
     * （**既有行为**，本单未改）⇒ 下标断言会假红。</p>
     */
    @SuppressWarnings("unchecked")
    private static BigDecimal qtyOfRow(List<Map<String, Object>> positions, String orderItemId,
                                       String operation) {
        Map<String, Object> position = positions.stream()
                .filter(p -> orderItemId.equals(p.get("order_item_id")))
                .findFirst()
                .orElseThrow(() -> new AssertionError("部位树里没有 order_item_id=" + orderItemId + " 的部位"));
        List<Map<String, Object>> operations = (List<Map<String, Object>>) position.get("operations");
        return operations.stream()
                .filter(row -> operation.equals(row.get("operation")))
                .map(row -> (BigDecimal) row.get("qty"))
                .findFirst()
                .orElseThrow(() -> new AssertionError(
                        "部位 " + orderItemId + " 里没有工序「" + operation + "」"));
    }

    @Test
    @DisplayName("#4388 判据 1：两条**同名部位**（两个布帘窗）⇒ 实例各带自己的 order_item_id、读面 **2 个部位**（旧行为并成 1 个）")
    void sameNamedWindowsStayIndependent() {
        stubQtyFromOwnCalcInfo();
        List<ProcessingPositionOperation> stored = generateAndStore(sameNamedWindows());

        assertThat(stored).extracting(ProcessingPositionOperation::getOrderItemId)
                .as("同名部位必须靠 order_item_id 区分（旧行为：该列不存在 ⇒ 无从区分）")
                .containsOnly("item-1", "item-2");
        assertThat(stored).extracting(ProcessingPositionOperation::getPositionKind)
                .as("position_kind = 可读定位（哪一件帘）= 快照 curtainType")
                .containsOnly("布帘");
        assertThat(stored).allSatisfy(row -> assertThat(row.getPositionName())
                .as("两行的展示名**故意相同**（这正是缺陷形态）").isEqualTo("布艺遮光帘A 米白"));

        List<Map<String, Object>> positions = readPositions();
        assertThat(positions).as("两个窗同名也必须**各成一个部位**（旧行为：按名字分组并成 1 个）")
                .hasSize(2);
        assertThat(positions).extracting(p -> p.get("order_item_id"))
                .as("读面必须透出行标识，否则前端无从区分两个同名部位")
                .containsExactlyInAnyOrder("item-1", "item-2");
        assertThat(positions).extracting(p -> p.get("position_kind")).containsOnly("布帘");
        // 每个部位的米类 qty = **自己那条明细行**的算料输出（12.3 / 8.0）
        assertThat(qtyOfRow(positions, "item-1", "精裁-布")).isEqualByComparingTo("12.3");
        assertThat(qtyOfRow(positions, "item-2", "精裁-布")).isEqualByComparingTo("8.0");
    }

    @Test
    @DisplayName("#4388 判据 2：算料输入/应做数量**按行取**（两樘尺寸不同 ⇒ 12.3 vs 8.0，不是同一值复制），请求行带 order_item_id")
    void qtyIsTakenPerRowNotPerOrder() {
        stubQtyFromOwnCalcInfo();
        List<ProcessingPositionOperation> stored = generateAndStore(sameNamedWindows());

        ArgumentCaptor<List<Map<String, Object>>> request = ArgumentCaptor.forClass(List.class);
        verify(productionOperationQtyClient).resolve(request.capture());
        assertThat(request.getValue()).extracting(p -> p.get("order_item_id"))
                .as("请求行带行标识（自描述；引擎侧回显见 PR 的「未做」项）")
                .containsExactly("item-1", "item-2");
        assertThat(request.getValue())
                .extracting(p -> String.valueOf(((Map<?, ?>) p.get("calc_info")).get("fabric_meters")))
                .as("算料输入按行取（每行尺寸可不同）").containsExactly("12.3", "8.0");

        // 实例侧：米类 qty 各取自己那行 —— 「按订单行取值」会让两侧同值（那正是本判据要排除的形态）
        assertThat(stored).filteredOn(r -> "item-1".equals(r.getOrderItemId()) && "米".equals(r.getUnit()))
                .isNotEmpty().allSatisfy(r -> assertThat(r.getQty()).isEqualByComparingTo("12.3"));
        assertThat(stored).filteredOn(r -> "item-2".equals(r.getOrderItemId()) && "米".equals(r.getUnit()))
                .isNotEmpty().allSatisfy(r -> assertThat(r.getQty()).isEqualByComparingTo("8.0"));
    }

    @Test
    @DisplayName("#4388 判据 3（回归）：套级去重不被破坏 —— 布+纱 仍 **14 道**、套级仍 **1 行**（挂主布行 item-1），且两行各带自己的 order_item_id")
    void setLevelDedupSurvivesPositionIdentity() {
        List<ProcessingPositionOperation> stored = generateAndStore(clothPlusSheerWindow());

        assertThat(stored).as("#4384 A2 的结论不得被定位键改动破坏（布帘路线 + 纱帘路线的部位级，"
                + "套级各去重到 1：#4937 去部位化后 = 12 + 11 − 2×2 套级重复）")
                .hasSize(partLevelOperationNames(V54_BULIAN_HANZHE).size()
                        + setLevelOperationNames(V54_BULIAN_HANZHE).size()
                        + partLevelOperationNames(V58_SHALU_DAKONG).size());
        assertThat(stored).filteredOn(r -> "外帘装袋".equals(r.getOperationName()))
                .as("套级工序每樘窗一次（A2）").hasSize(1);
        assertThat(stored).extracting(ProcessingPositionOperation::getOrderItemId)
                .contains("item-1", "item-2");
        assertThat(stored).filteredOn(r -> "外帘装袋".equals(r.getOperationName()))
                .extracting(ProcessingPositionOperation::getOrderItemId)
                .as("套级工序挂樘窗**主布行**（item-1 = 布帘行，A2 裁定）").containsExactly("item-1");
        assertThat(stored).filteredOn(r -> "item-2".equals(r.getOrderItemId()))
                .extracting(ProcessingPositionOperation::getPositionKind).containsOnly("纱帘");
    }

    @Test
    @DisplayName("#4388 判据 4（回归）：**存量单**（无 order_item_id 的老行）⇒ 读面仍按 position_name 分组，行为逐字不变")
    void legacyRowsWithoutIdentityKeepNameGrouping() {
        when(orderMapper.selectById("order-001")).thenReturn(confirmedOrder);
        when(processingOrderMapper.selectActiveByOrderId("order-001", TENANT)).thenReturn(po("po-1", "generated"));
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(
                legacyInstance("op-1", "布艺遮光帘A 米白", "精裁-布"),
                legacyInstance("op-2", "遮光成品Y 米白", "工序甲")));

        List<Map<String, Object>> positions = readPositions();

        assertThat(positions).as("存量行没有行标识 ⇒ 仍按名字分组（两个不同名部位 = 2 个）").hasSize(2);
        assertThat(positions).extracting(p -> p.get("position_name"))
                .containsExactlyInAnyOrder("布艺遮光帘A 米白", "遮光成品Y 米白");
        assertThat(positions).extracting(p -> p.get("order_item_id"))
                .as("存量行如实透出 null（不编值）").containsOnlyNulls();
    }

    // ── ⭐ issue #4784：进度表读面的**套维**（消除与计件报表的口径分裂）────────────────
    //
    // 缺陷形态（#4725 的包核清时发现并如实登记）：读面 `buildPositions` 按 `order_item_id`
    // 分组（= **部位**级，#4388 冻结契约），而前端 `ProductionProgressTable` 把**每个分组**
    // 当「一套」渲染「第 N 套 / 共 M 套」⇒ 一樘「布 + 纱 + 帘头」在工序进度表上显示 **3 套**；
    // 而 #4725 已把套维统一为「一樘窗 = 一套」（`craftLineId` 组）⇒
    // **同一张单：计件报表说 1 套、工序进度表说 3 套**（静默不一致，没有任何东西会因此变红）。
    //
    // 修法（**只加不改**）：读面**追加** `set_no` 键，取值 = #4725 的**同一份**实现
    // （`ProductionService.setKey`：V92 套号优先、无号回落樘窗组键 `craftLineId ?? itemId`）；
    // 分组契约（`order_item_id`）与既有键**一字不动**。

    /** 读面部位树里的**套键集合**（去重，首次出现序）。 */
    private static Set<String> positionSetKeys(List<Map<String, Object>> positions) {
        Set<String> keys = new LinkedHashSet<>();
        positions.forEach(p -> keys.add(String.valueOf(p.get("set_no"))));
        return keys;
    }

    /** 计件报表 `per_set` 段的套键集合（#4725 已落地的口径）。 */
    @SuppressWarnings("unchecked")
    private static Set<String> reportSetKeys(Map<String, Object> report) {
        Set<String> keys = new LinkedHashSet<>();
        for (Map<String, Object> row : (List<Map<String, Object>>) report.get("per_set")) {
            keys.add(String.valueOf(row.get("set_no")));
        }
        return keys;
    }

    @Test
    @DisplayName("#4784 一樘「布+纱+帘头」⇒ 进度表读面套键 == 计件报表 per_set == **1 套**（改前读面 = 3 个部位各算一套）")
    void progressTableSetKeyAgreesWithPieceworkReport() {
        // 同一张单、同一次生成：计件侧（#4725 已落地）与读面侧（本单）必须给**同一个**套键。
        Map<String, Object> report = pieceworkFor(clothSheerValanceWindow());

        List<Map<String, Object>> positions = readPositions();
        // 前置自断言（**不是**被测行为）：这确实是「一樘窗含三个部位」的夹具 ——
        // 旧口径（套 ≡ 部位 / 明细行）下这个数**就是**「套数」= 3，红证读数由此可复核。
        assertThat(positions).as("前置：一樘窗 = 3 条明细行 = 3 个部位（旧口径据此算 3 套）").hasSize(3);

        // ⭐ 被测断言（读面）：三个部位的套键必须**同一个** `win-1`。
        // 改前该键不存在 ⇒ 这里得 "null" —— `containsExactly` 钉的是**值**（不是「恰好 1 个」那种恒真形态）。
        assertThat(positionSetKeys(positions))
                .as("读面套键 = 樘窗组键（`craftLineId` = win-1）；改前无该键 ⇒ 前端只能按部位数算成 3 套")
                .containsExactly("win-1");

        // ⭐ 判据 = **两侧同一份**（这才是「口径分裂」的直接判据 —— 只断言其中一侧是空断言）
        assertThat(reportSetKeys(report)).as("计件报表侧（#4725）：一樘窗 = 一套").containsExactly("win-1");
        assertThat(positionSetKeys(positions))
                .as("同一张单：进度表读面与计件报表必须给同一套键（口径分裂 = 本单要治的病）")
                .isEqualTo(reportSetKeys(report));

        // 反向护栏：**部位级信息一字不丢** + 既有键**一字不动**（分组契约仍是 order_item_id）
        assertThat(positions).extracting(p -> p.get("order_item_id"))
                .as("分组契约（#4388 冻结）：仍是**按 order_item_id 的部位树**（3 个部位，未被并成 1 个）")
                .containsExactlyInAnyOrder("item-1", "item-2", "item-3");
        assertThat(positions).extracting(p -> p.get("position_name"))
                .as("部位级信息不丢：三个部位的展示名逐个透出")
                .containsExactlyInAnyOrder("布艺遮光帘A 米白", "纱帘A 米白", "帘头A 米白");
        assertThat(positions).allSatisfy(p -> assertThat(p)
                .as("既有键一字不动（只**追加** set_no）")
                .containsKeys("position_name", "order_item_id", "position_kind", "operations", "set_no"));
    }

    @Test
    @DisplayName("#4784 判别力：两樘**无 craftLineId** 的窗 ⇒ 读面套键 = 各行自成樘窗（2 个，不是 1 个常量）")
    void windowsWithoutCraftLineEachOwnSet() {
        Map<String, Object> report = pieceworkFor(sameNamedWindows());

        assertThat(positionSetKeys(readPositions()))
                .as("无 craftLineId ⇒ 回落本行 itemId（#4725 反向护栏同口径：各自成樘窗，不并组、不猜）")
                .containsExactlyInAnyOrder("item-1", "item-2");
        assertThat(reportSetKeys(report))
                .as("计件报表侧同口径（两侧仍一致 ⇒ 本键不是常量）")
                .containsExactlyInAnyOrder("item-1", "item-2");
    }

    @Test
    @DisplayName("#4784 V92 套号优先：实例带 set_no ⇒ 读面套键 = **落库套号**（与 #4725 的 setKey 逐字同一份，不是组键）")
    void readFaceSetKeyPrefersStoredSetNo() {
        stubLibrary();
        stubGenerate(clothSheerValanceWindow());
        List<ProcessingPositionOperation> stored = new ArrayList<>();
        when(positionOperationMapper.insert(any(ProcessingPositionOperation.class))).thenAnswer(inv -> {
            ProcessingPositionOperation row = inv.getArgument(0);
            row.setId("op-" + (stored.size() + 1));
            // V92 回填形态（同一次写入 setId + setNo）；此处只钉**套号取值优先级**
            row.setSetNo("JG-20260918-6914-001");
            stored.add(row);
            return 1;
        });
        var results = realChainService().generate(List.of("order-001"), TENANT, "u1");
        assertThat(results.get(0).isSuccess()).as("生成加工单必须成功（否则后续判据无意义）").isTrue();
        lenient().when(positionOperationMapper.selectList(any())).thenReturn(stored);

        assertThat(positionSetKeys(readPositions()))
                .as("有套号用套号（V92 落库值），无号才回落樘窗组键 —— 与 #4725 setKey 逐字同一份")
                .containsExactly("JG-20260918-6914-001");
    }

    /** 存量行（V69 之前生成的实例：没有 order_item_id / position_kind）。 */
    private static ProcessingPositionOperation legacyInstance(String id, String positionName, String operation) {
        return ProcessingPositionOperation.builder()
                .id(id).tenantId(TENANT).processingOrderId("po-1")
                .positionName(positionName).seq(1).operationName(operation).groupName("裁剪").unit("米")
                .qty(BigDecimal.ONE).qtySource("fallback").unitPrice(BigDecimal.ONE).factor(BigDecimal.ONE)
                .isMustFinish(false).isStartMarker(true).status("pending").doneQty(BigDecimal.ZERO)
                .deleted(0).build();
    }

    @Test
    @DisplayName("#4388 判据（身份校验）：算料响应与请求的 position_name 不符 ⇒ **fail-closed**（旧行为按位次静默错配）")
    void qtyResponseIdentityMismatchFailsClosed() {
        stubLibrary();
        // 算料桩：条数相同但**身份不同**（模拟引擎重排/串位）—— 旧实现只校验条数 ⇒ 静默错配
        doAnswer(inv -> {
            List<Map<String, Object>> request = inv.getArgument(0);
            List<ProductionOperationQtyClient.PositionQty> resolved = new ArrayList<>();
            for (Map<String, Object> position : request) {
                Map<String, BigDecimal> qty = new LinkedHashMap<>();
                Map<String, String> source = new LinkedHashMap<>();
                for (Object raw : (List<?>) position.get("operations")) {
                    qty.put(String.valueOf(raw), BigDecimal.ONE);
                    source.put(String.valueOf(raw), "fallback");
                }
                resolved.add(new ProductionOperationQtyClient.PositionQty("另一个部位", qty, source));
            }
            return resolved;
        }).when(productionOperationQtyClient).resolve(any());
        // ⚠️ **不调 `stubGenerate`**：本用例在 `buildPositionPayload` 阶段就 fail-closed
        //（工序 payload 在任何写库之前解析，issue #4116）⇒ 插入桩会「备而不用」被严格桩判为多余。
        when(orderMapper.selectById("order-001")).thenReturn(confirmedOrder);
        when(orderItemMapper.selectList(any())).thenReturn(sameNamedWindows());
        when(processingOrderMapper.selectActiveByOrderId("order-001", TENANT)).thenReturn(null);

        var results = realChainService().generate(List.of("order-001"), TENANT, "u1");

        assertThat(results.get(0).isSuccess()).as("身份不符必须显式失败（静默错配是本仓最大失败模式）").isFalse();
        assertThat(results.get(0).getCode())
                .isEqualTo(ProductionOperationQtyClient.ERR_OPERATION_QTY_UNAVAILABLE);
        verify(positionOperationMapper, never()).insert(any(ProcessingPositionOperation.class));
    }

    @Test
    @DisplayName("#4388 判据（报工归属）：两樘**同名**窗 ⇒ 报工只归属被扫码那一行（operation_id → 实例 → order_item_id，不串行）")
    void reportOnOneSameNamedWindowOnlyTouchesThatRow() {
        stubQtyFromOwnCalcInfo();
        List<ProcessingPositionOperation> stored = generateAndStore(sameNamedWindows());
        when(clientRequestIdService.claim(any(), any(), any())).thenReturn(true);
        when(positionOperationMapper.advanceDoneQtyIfUnchanged(
                any(), any(), any(), any(), any(), any())).thenReturn(1);

        ProcessingPositionOperation target = stored.stream()
                .filter(r -> "item-2".equals(r.getOrderItemId()) && "精裁-布".equals(r.getOperationName()))
                .findFirst().orElseThrow();
        when(positionOperationMapper.selectById(target.getId())).thenReturn(target);

        ProductionService real = new ProductionService(processingOrderMapper, positionOperationMapper,
                workLogMapper, orderMapper, orderItemMapper, clientRequestIdService);
        real.report("order-001", target.getId(),
                Map.of("worker_name", "走查工人", "qty", BigDecimal.ONE,
                        "qualified_qty", BigDecimal.ONE, "work_type", "normal"),
                TENANT, "req-4388");

        // 归属推导（不新增冗余列，parent 批准的判定）：work log 的 operation_id → 实例 → order_item_id
        ArgumentCaptor<ProductionWorkLog> logCaptor = ArgumentCaptor.forClass(ProductionWorkLog.class);
        verify(workLogMapper).insert(logCaptor.capture());
        assertThat(logCaptor.getValue().getOperationId()).isEqualTo(target.getId());
        assertThat(stored).filteredOn(r -> target.getId().equals(r.getId()))
                .extracting(ProcessingPositionOperation::getOrderItemId).containsExactly("item-2");
        // **同名**的另一行（item-1）没有被报工：只有一笔 work log，且没有推进它的 CAS
        verify(workLogMapper, times(1)).insert(any(ProductionWorkLog.class));
        verify(positionOperationMapper, never()).advanceDoneQtyIfUnchanged(
                argThat(id -> !target.getId().equals(id)), any(), any(), any(), any(), any());
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
        Map<String, Object> calcInfo = generateAndCaptureCalcInfo(orderItemHanzheWithCalcOutput("米白"));

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
                workLogMapper, orderMapper, orderItemMapper, clientRequestIdService);

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

        // 交期用**相对日期**（issue #4911）：写死 `LocalDate.of(2026, 9, 20)` 会被「发加工交期不得早于今天」
        // （#3901）在**第二天**判红 —— 测试对墙钟敏感 = 定时炸弹（本地 CST 2026-09-21 实测红；
        // CI 用 UTC ⇒ 只是晚 8 小时红）。本用例要断言的是「交期**原样落库**」，不是某个具体日历日。
        LocalDate deliveryDate = LocalDate.now().plusDays(3);
        ProcessingOrderUpdateRequest issue = new ProcessingOrderUpdateRequest();
        issue.setAction("issue");
        issue.setProcessor("朝阳加工厂");
        issue.setExpectedDeliveryDate(deliveryDate);
        OffsetDateTime beforeIssue = OffsetDateTime.now();
        processingOrderService.updateStatus("po-1", issue, TENANT, "u1");
        OffsetDateTime afterIssue = OffsetDateTime.now();

        ArgumentCaptor<ProcessingOrder> captor = ArgumentCaptor.forClass(ProcessingOrder.class);
        verify(processingOrderMapper).updateById(captor.capture());
        assertThat(captor.getValue().getStatus()).isEqualTo("issued");
        assertThat(captor.getValue().getProcessor()).isEqualTo("朝阳加工厂");
        assertThat(captor.getValue().getExpectedDeliveryDate()).isEqualTo(deliveryDate);
        // #4337：`isNotNull()` 只证「有东西」—— 把发加工时点写成交期 / 写死某个日期都照样绿。
        // 收窄成「本次调用当下」的闭区间（不钉具体日历日 ⇒ 不引入 #4911 那类墙钟炸弹）。
        assertThat(captor.getValue().getIssuedAt()).as("发加工时点 = 本次调用当下")
                .isBetween(beforeIssue, afterIssue);

        // 订单联动（issue #4305，用户裁定「发加工 = 订单进入生产中」）：**发加工**才推进
        // 订单 confirmed→producing（生成加工单已不再推进，见 generateSuccess 的 never 断言）
        verify(orderService).updateOrderStatus("order-001", "producing");

        // start
        when(processingOrderMapper.selectOne(any())).thenReturn(po("po-1", "issued"));
        ProcessingOrderUpdateRequest start = new ProcessingOrderUpdateRequest();
        start.setAction("start");
        OffsetDateTime beforeStart = OffsetDateTime.now();
        processingOrderService.updateStatus("po-1", start, TENANT, "u1");
        OffsetDateTime afterStart = OffsetDateTime.now();
        verify(processingOrderMapper, times(2)).updateById(captor.capture());
        assertThat(captor.getValue().getStatus()).isEqualTo("in_processing");
        assertThat(captor.getValue().getInProcessingAt()).as("开工时点 = 本次调用当下（#4337 收窄）")
                .isBetween(beforeStart, afterStart);

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

    // ── issue #4555：加工单快照补「算料公式」（车间/任务卡纸面看不到用料怎么算出来的）──
    //
    // **键名口径（读码实测，以代码事实为准）**：订单层 `processing_info` 落的是 camelCase
    // `formulaText`（下单页把试算响应的 `formula_text` 原样搬进该键，#4546），而快照键族 /
    // 响应 DTO / 三端展示映射都按 snake_case `formula_text` 读 ⇒ `copyIfPresent` 的**取值键名**
    // 必须是 `formulaText`。若直接用键族名取值 ⇒ 恒取不到（静默缺行，判据 1 必红）。

    private static final String FORMULA_TEXT =
            "韩褶公式：(6.6+0.3)×2 → 52折 → 0.25×52+0.3 = 13.3米";

    /** 下单落库形态：`processing_info` 顶层 **camelCase** `formulaText`。 */
    @SuppressWarnings("unchecked")
    private OrderItem orderItemWithFormula() {
        OrderItem item = orderItemWithProcessing("米白");
        ((Map<String, Object>) item.getProcessingInfo()).put("formulaText", FORMULA_TEXT);
        return item;
    }

    /** 本次生成落库的快照第一条（`generate` 的 insert 捕获）。 */
    @SuppressWarnings("unchecked")
    private Map<String, Object> insertedSnapshotEntry() {
        ArgumentCaptor<ProcessingOrder> captor = ArgumentCaptor.forClass(ProcessingOrder.class);
        verify(processingOrderMapper).insert(captor.capture());
        List<Map<String, Object>> snapshot = (List<Map<String, Object>>) captor.getValue().getItemsSnapshot();
        assertThat(snapshot).hasSize(1);
        return snapshot.get(0);
    }

    @Test
    @DisplayName("#4555 判据 1：下单落 processingInfo.formulaText ⇒ 加工单快照固化为 formula_text（逐字）")
    void snapshotCarriesFormulaText() {
        stubLibrary();
        stubGenerate(List.of(orderItemWithFormula()));

        assertThat(realChainService().generate(List.of("order-001"), TENANT, "u1").get(0).isSuccess()).isTrue();

        assertThat(insertedSnapshotEntry().get("formula_text"))
                .as("车间/任务卡纸面靠这一行告知「用料是怎么算出来的」—— 缺键即不可见")
                .isEqualTo(FORMULA_TEXT);
    }

    @Test
    @DisplayName("#4555 判据 2 + 4（回归/不造值）：存量单无 formulaText ⇒ 快照**无** formula_text 键、不补默认串")
    void legacySnapshotHasNoFormulaText() {
        stubLibrary();
        stubGenerate(List.of(orderItemWithProcessing("米白")));

        assertThat(realChainService().generate(List.of("order-001"), TENANT, "u1").get(0).isSuccess()).isTrue();

        Map<String, Object> entry = insertedSnapshotEntry();
        assertThat(entry).doesNotContainKey("formula_text");
        // 判据 4 的红证：注入「缺键时补一个默认串」⇒ 本断言必红（缺键就是缺，Java 不造值）
        assertThat(entry.values())
                .as("不得补「公式」占位串 —— 造值会让存量加工单纸面多出一行假公式")
                .noneMatch(value -> String.valueOf(value).contains("公式"));
    }

    @Test
    @DisplayName("#4555 判据 3（后端半边）：快照带 formula_text ⇒ 加工单详情响应原样透出（DTO 未声明 ⇒ 丢值）")
    void detailExposesFormulaText() {
        Map<String, Object> entry = craftSpecSnapshotEntry();
        entry.put("formula_text", FORMULA_TEXT);
        ProcessingOrder po = po("po-1", "issued");
        po.setItemsSnapshot(List.of(entry));
        when(processingOrderMapper.selectOne(any())).thenReturn(po);
        when(orderMapper.selectById("order-001")).thenReturn(confirmedOrder);

        ProcessingOrderResponse resp = processingOrderService.getDetail("po-1", TENANT);

        assertThat(resp.getItems()).hasSize(1);
        assertThat(resp.getItems().get(0).getFormulaText())
                .as("展示面（ProcessingOrderBlock / TaskCardPrint）读的就是这个响应字段")
                .isEqualTo(FORMULA_TEXT);
    }

    @Test
    @DisplayName("#4555 判据 2（后端半边）：存量加工单快照无 formula_text ⇒ 响应该字段为 null（不回填）")
    void detailLegacySnapshotHasNullFormulaText() {
        ProcessingOrder po = po("po-1", "issued");
        po.setItemsSnapshot(List.of(craftSpecSnapshotEntry()));
        when(processingOrderMapper.selectOne(any())).thenReturn(po);
        when(orderMapper.selectById("order-001")).thenReturn(confirmedOrder);

        ProcessingOrderResponse resp = processingOrderService.getDetail("po-1", TENANT);

        assertThat(resp.getItems()).hasSize(1);
        assertThat(resp.getItems().get(0).getFormulaText()).isNull();
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
        assertThat(operations).hasSize(V54_BULIAN_HANZHE.length);
        assertThat(operations.get(0)).containsEntry("operation", "精裁-布")
                .containsEntry("group", "裁剪").containsEntry("unit", "米")
                .containsEntry("is_start_marker", true);
        assertThat((BigDecimal) operations.get(0).get("unit_price")).isEqualByComparingTo("0.4");
        assertThat((BigDecimal) operations.get(0).get("qty"))
                .as("应做数量 = 算料引擎输出（#4208 / #4337 更正：米类 = calc_info.fabric_meters = 订单行 quantity）")
                .isEqualByComparingTo(ORDER_QUANTITY);
        assertThat(operations.get(0).get("qty_source")).isEqualTo("fabric_meters");
        assertThat((BigDecimal) operations.get(2).get("qty"))
                .as("折类 = 褶数（走查实测的红证形态：韩褶-布 曾显示 3 折）")
                .isEqualByComparingTo(CALC_PLEAT_COUNT);
        assertThat(operations.get(2).get("qty_source")).isEqualTo("pleat_count");
        // 🔴 issue #4937 / O4：`打包` 进路线后**位次后移一位** —— `打包` 在 9、`外帘装袋` 在 10
        assertThat(operations.get(9).get("qty_source"))
                .as("套类 = 引擎待补键 ⇒ 显式标注 fallback（不静默）").isEqualTo("fallback");
        assertThat(operations.get(9)).containsEntry("operation", "打包");
        // 🔴 #4961：派生 payload **不含** `is_must_finish` 键（概念已退场）—— 改前这里是
        // `.containsEntry("is_must_finish", true)`。判据反向收紧：从「值为 true」变成「键不存在」。
        assertThat(operations.get(10)).containsEntry("operation", "外帘装袋")
                .doesNotContainKey("is_must_finish");
        assertThat(operations).allSatisfy(op -> assertThat(op).doesNotContainKey("is_must_finish"));
    }

    // ══════════════════ 工序显示名统一（issue #4621，web 面命名统一 · 阶段 1）══════════════════
    //
    // 口径（冻结）：显示名 = **逻辑工序名**（既有映射读时派生）+ 部位（帘种），如 `精裁 · 布帘`；
    // 部位无关工序（`外帘装袋`）⇒ 只显示逻辑名。既有 `operation` 键 = **工人端快照名**（变体名
    // `精裁-布`）⇒ **一字不动**（历史数据与其它消费者仍要读它），但 **web 界面不得渲染该键**。
    // 派生是**读时**做的、**不写库**。

    @Test
    @DisplayName("#4621 派生 payload 补 logical_name + position：历史实例（快照名 精裁-布）读时派生为「精裁 · 布帘」")
    @SuppressWarnings("unchecked")
    void derivePositionPayloadAddsOperationDisplayKeys() {
        stubLibrary();
        when(orderMapper.selectById("order-001")).thenReturn(confirmedOrder);
        when(orderItemMapper.selectList(any())).thenReturn(List.of(orderItemHanzhe("米白")));

        List<Map<String, Object>> positions = processingOrderService.derivePositionPayload("order-001", TENANT);

        List<Map<String, Object>> operations = (List<Map<String, Object>>) positions.get(0).get("operations");
        // 历史实例（快照名 = 变体名 `精裁-布`）：显示名 = `精裁` + `布帘`（不改库、不改快照名）
        assertThat(operations.get(0))
                .as("既有键一字未动 + 两个派生键（web 界面只渲染后者）")
                .containsEntry("operation", "精裁-布")
                .containsEntry("group", "裁剪")
                .containsEntry("unit", "米")
                .containsEntry("is_start_marker", true)
                .containsEntry("logical_name", "精裁")
                .containsEntry("position", "布帘");
        // 部位无关工序（名字里没编部位）⇒ position 为空（界面只显示逻辑名）
        // ⚠️ issue #4937 / O4：`打包` 进路线后位次后移一位 ⇒ `外帘装袋` 在 index 10
        assertThat(operations.get(10))
                .containsEntry("operation", "外帘装袋")
                .containsEntry("logical_name", "外帘装袋")
                .containsEntry("position", null);
    }

    @Test
    @DisplayName("#4202 派生 fail-closed：工序库无路线 ⇒ 中止（绝不返回空 payload 落个空壳）")
    void derivePositionPayloadFailsClosedOnEmptyLibrary() {
        stubEmptyLibrary();
        when(orderMapper.selectById("order-001")).thenReturn(confirmedOrder);
        when(orderItemMapper.selectList(any())).thenReturn(List.of(orderItemHanzhe("米白")));

        // 空库（零路线模板 ∧ 零默认工艺）⇒ fail-closed 中止；**绝不**静默返回空 payload
        // （那会让调用方落一个「有加工单、零工序」的空壳）。具体措辞由实现选，不把文案当判据。
        assertThatThrownBy(() -> processingOrderService.derivePositionPayload("order-001", TENANT))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("无法实例化工序");
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

    // ── 池化 + 跨订单成组派单（issue #5169 = 阶段 2b-1）────────────────────────────
    //
    // 判据分工：**批次账上真的省了几米**的真库判据在 PooledDispatchRealDbTest（PR-071）；
    // 本类只判**装配**（谁在什么时候调了台账服务、入参里有哪些行）——
    // 池化开关缺省关（不启用 ⇒ 逐单派、plan 每单各调一次）、池化开启时 plan **只调一次**
    // 且入参含**池内多张单**的行、预览与实际落账同源同值、待派池的可见性与兜底告警。

    /** 池内第二张单（两支单的键只在这里写一次，免得多处硬编码字符串）。 */
    private static final String ORDER_2 = "order-002";

    private Order confirmedOrderOf(String id, String orderNo, java.time.OffsetDateTime createdAt) {
        return Order.builder().id(id).tenantId(TENANT).orderNo(orderNo).status("confirmed")
                .createdAt(createdAt).build();
    }

    /**
     * 一行明细（带 {@code productId} + {@code processing_info.sku}）—— 「物料」（商品 × 颜色 × 门幅）
     * 就是这两维，池视图的分组与池级求解的 SKU 过滤都读它。
     */
    private OrderItem itemOf(String orderId, String itemId, String skuCode) {
        Map<String, Object> info = processingInfo("米白");
        info.put("sku", skuCode);
        info.put("cuttingMode", "定高买宽");
        return OrderItem.builder()
                .id(itemId).tenantId(TENANT).orderId(orderId).productId("prod-1")
                .productName("布艺遮光帘A").quantity(new BigDecimal("3"))
                .width(new BigDecimal("1.5")).height(new BigDecimal("1.1"))
                .processingInfo(info).build();
    }

    private com.migao.admin.dto.ProcessingOrderGenerateRequest.BatchAssignment assignmentOf(
            String orderId, String itemId, String batchNo) {
        var assignment = new com.migao.admin.dto.ProcessingOrderGenerateRequest.BatchAssignment();
        assignment.setOrderId(orderId);
        assignment.setItemId(itemId);
        assignment.setBatchNo(batchNo);
        return assignment;
    }

    /**
     * 两张单的生成前置桩：明细行**按调用次序**回（池化的准备阶段按 {@code orderIds} 顺序逐单取快照
     * —— 这是被测实现的可观测顺序，故意与它对齐，而不是造一个与顺序无关的假桩）。
     */
    private void stubTwoOrders(List<OrderItem> first, List<OrderItem> second) {
        when(orderMapper.selectById("order-001")).thenReturn(confirmedOrder);
        when(orderMapper.selectById(ORDER_2))
                .thenReturn(confirmedOrderOf(ORDER_2, "ORD-20260912-0002", null));
        // 明细行给**两单的并集**：同一个 mock 要服务三处调用者（逐单取快照、实例化时反查樘窗组键），
        // 而测试桩只能给一个集合。被测代码按 orderId / IN 过滤，且**哪一行真的进入排料入参由
        // 指派决定**（见 assertions 里的 containsExactly）⇒ 并集不会让两张单混起来。
        List<OrderItem> all = new ArrayList<>(first);
        all.addAll(second);
        when(orderItemMapper.selectList(any())).thenReturn(all);
        // 幂等闸与工序实例化都要读回**刚落的那张单**（同 stubGenerate 的 wiring：insert 回填主键 +
        // 把活跃单挂进 ref）—— 否则 ProductionService.instantiate 会判「尚无加工单」而失败
        java.util.concurrent.atomic.AtomicReference<ProcessingOrder> firstRef =
                new java.util.concurrent.atomic.AtomicReference<>();
        java.util.concurrent.atomic.AtomicReference<ProcessingOrder> secondRef =
                new java.util.concurrent.atomic.AtomicReference<>();
        when(processingOrderMapper.selectActiveByOrderId("order-001", TENANT))
                .thenAnswer(inv -> firstRef.get());
        when(processingOrderMapper.selectActiveByOrderId(ORDER_2, TENANT))
                .thenAnswer(inv -> secondRef.get());
        when(processingOrderMapper.insert(any(ProcessingOrder.class))).thenAnswer(inv -> {
            ProcessingOrder inserted = inv.getArgument(0);
            inserted.setId("po-" + inserted.getOrderId());
            if ("order-001".equals(inserted.getOrderId())) {
                firstRef.set(inserted);
            } else {
                secondRef.set(inserted);
            }
            return 1;
        });
    }

    private StockBatchConsumptionService.Deduction pooledDeduction(String itemId, String formula,
                                                                   String planned) {
        return new StockBatchConsumptionService.Deduction(77L, "PC-5169-A", "prod-1", 12L, "SKU-1",
                itemId, new BigDecimal(formula), new BigDecimal(planned), new BigDecimal("12.5"),
                new BigDecimal("60"));
    }

    /**
     * 台账桩：**按入参行数**给不同的结果 —— 池级调用（两单的行一起）⇒ 并排后各分摊 1.5 米；
     * 逐单调用（一行）⇒ 该行独占 3 米。这样就**只有真正做了跨订单成组**才会得到 3 米，
     * 「入参里有几张单」这件事因此是可判别的（而不是靠桩自己说）。
     */
    private void stubPlanByLineCount() {
        when(stockBatchConsumptionService.plan(eq(TENANT), anyList())).thenAnswer(inv -> {
            List<StockBatchConsumptionService.Designation> lines = inv.getArgument(1);
            if (lines.size() == 2) {
                return List.of(pooledDeduction(lines.get(0).orderItemId(), "3", "1.5"),
                        pooledDeduction(lines.get(1).orderItemId(), "3", "1.5"));
            }
            return List.of(pooledDeduction(lines.get(0).orderItemId(), "3", "3"));
        });
    }

    @Test
    @DisplayName("#5169 判据1 默认关：不传 pooled ⇒ **逐单派**（plan 每单各一次、每次只带这一单的行）")
    @SuppressWarnings("unchecked")
    void poolingIsOffByDefaultSoEachOrderIsPlannedAlone() {
        stubLibrary();
        stubTwoOrders(List.of(itemOf("order-001", "item-1", "SKU-1")),
                List.of(itemOf(ORDER_2, "item-2", "SKU-1")));
        stubPlanByLineCount();

        // 5 参调用 = **缺省**（调用方根本没提池化这回事）
        var results = realChainService().generate(List.of("order-001", ORDER_2),
                List.of(assignmentOf("order-001", "item-1", "PC-5169-A"),
                        assignmentOf(ORDER_2, "item-2", "PC-5169-A")),
                TENANT, "文员");

        assertThat(results).hasSize(2);
        assertThat(results).allSatisfy(r -> assertThat(r.isSuccess()).isTrue());
        assertThat(results).extracting(ProcessingOrderService.GenerateResult::getOrderRef)
                .as("结果顺序 = orderIds 顺序（判据 1 的「含顺序」）")
                .containsExactly("order-001", ORDER_2);
        ArgumentCaptor<List> captor = ArgumentCaptor.forClass(List.class);
        verify(stockBatchConsumptionService, times(2)).plan(eq(TENANT), captor.capture());
        List<StockBatchConsumptionService.Designation> firstCall = captor.getAllValues().get(0);
        List<StockBatchConsumptionService.Designation> secondCall = captor.getAllValues().get(1);
        assertThat(firstCall).extracting(StockBatchConsumptionService.Designation::orderItemId)
                .as("缺省 = 逐单派：第一次调用只带**第一张单**的行").containsExactly("item-1");
        assertThat(secondCall).extracting(StockBatchConsumptionService.Designation::orderItemId)
                .as("第二次调用只带**第二张单**的行 ⇒ 跨订单成组**不发生**").containsExactly("item-2");
        // 🔴 开关的唯一缺省值（红证：把 POOLED_DEFAULT_ENABLED 改成 true ⇒ 上面两条断言立刻红）
        assertThat(ProcessingOrderService.pooledEnabled(null))
                .as("池化开关缺省 = 关（不启用池化 ⇒ 行为与今天逐值相同）").isFalse();
        assertThat(ProcessingOrderService.pooledEnabled(Boolean.FALSE)).isFalse();
        assertThat(ProcessingOrderService.pooledEnabled(Boolean.TRUE)).isTrue();
    }

    @Test
    @DisplayName("🔴 #5169 判据2 服务层：pooled=true ⇒ plan **只调一次**，入参含**池内两张单**的行")
    @SuppressWarnings("unchecked")
    void pooledDispatchPlansOnceAcrossOrders() {
        stubLibrary();
        stubTwoOrders(List.of(itemOf("order-001", "item-1", "SKU-1")),
                List.of(itemOf(ORDER_2, "item-2", "SKU-1")));
        stubPlanByLineCount();

        var results = realChainService().generate(List.of("order-001", ORDER_2),
                List.of(assignmentOf("order-001", "item-1", "PC-5169-A"),
                        assignmentOf(ORDER_2, "item-2", "PC-5169-A")),
                TENANT, "文员", null, Boolean.TRUE);

        assertThat(results).hasSize(2);
        assertThat(results).allSatisfy(r -> assertThat(r.isSuccess()).isTrue());
        assertThat(results).extracting(ProcessingOrderService.GenerateResult::getOrderRef)
                .containsExactly("order-001", ORDER_2);
        ArgumentCaptor<List> captor = ArgumentCaptor.forClass(List.class);
        verify(stockBatchConsumptionService, times(1)).plan(eq(TENANT), captor.capture());
        List<StockBatchConsumptionService.Designation> pooledLines = captor.getAllValues().get(0);
        assertThat(pooledLines).extracting(StockBatchConsumptionService.Designation::orderItemId)
                .as("🔴 池级求解的入参 = 池内**两张单**的行（跨订单成组排料的前提）")
                .containsExactly("item-1", "item-2");
        // 落库仍是**各自**的加工单（一单一加工单的约束不变）：apply 两次、各带本单那一笔
        ArgumentCaptor<List> applied = ArgumentCaptor.forClass(List.class);
        verify(stockBatchConsumptionService, times(2))
                .apply(eq(TENANT), anyString(), anyString(), applied.capture());
        BigDecimal first = plannedOf(applied.getAllValues().get(0));
        BigDecimal second = plannedOf(applied.getAllValues().get(1));
        assertThat(first).as("第一张单分摊到并排后的一半（3 米那一行的一半）")
                .isEqualByComparingTo("1.5");
        assertThat(second).isEqualByComparingTo("1.5");
        assertThat(first.add(second)).as("🔴 两单合计 3 米（不是 6 米）").isEqualByComparingTo("3");
        // 快照盖的是**本单**的那一笔（批次号 + 两个米数），不是池级合计、也不是别单的行
        ArgumentCaptor<ProcessingOrder> poCaptor = ArgumentCaptor.forClass(ProcessingOrder.class);
        verify(processingOrderMapper, times(2)).insert(poCaptor.capture());
        List<ProcessingOrder> inserted = poCaptor.getAllValues();
        assertThat(inserted).hasSize(2);
        List<String> ownItem = List.of("item-1", "item-2");
        for (int i = 0; i < inserted.size(); i++) {
            List<Map<String, Object>> stamped = new ArrayList<>();
            for (Map<String, Object> row : snapshotOf(inserted.get(i))) {
                if (row.containsKey("batchNo")) {
                    stamped.add(row);
                }
            }
            assertThat(stamped).as("第 %d 张单**只有本单那一行**被盖上批次号", i + 1).hasSize(1);
            assertThat(stamped.get(0))
                    .as("盖的是本单自己的行（池化派单仍是各是各的加工单）")
                    .containsEntry("itemId", ownItem.get(i))
                    .containsEntry("batchNo", "PC-5169-A")
                    .containsEntry("plannedMeters", new BigDecimal("1.5"));
        }
    }

    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> snapshotOf(ProcessingOrder po) {
        return (List<Map<String, Object>>) po.getItemsSnapshot();
    }

    private static BigDecimal plannedOf(List<?> rows) {
        BigDecimal total = BigDecimal.ZERO;
        for (Object row : rows) {
            total = total.add(((StockBatchConsumptionService.Deduction) row).plannedMeters());
        }
        return total;
    }

    @Test
    @DisplayName("🔴 #5169 判据4 预览不说谎：预览「预计节省」== 实际交给台账的 Σ(formula − planned)")
    @SuppressWarnings("unchecked")
    void previewMatchesWhatIsActuallyApplied() {
        stubLibrary();
        List<OrderItem> a = List.of(itemOf("order-001", "item-1", "SKU-1"));
        List<OrderItem> b = List.of(itemOf(ORDER_2, "item-2", "SKU-1"));
        // 两段（预览 + 派单）各按顺序取一遍明细行
        stubTwoOrders(a, b);
        stubPlanByLineCount();
        var assignments = List.of(assignmentOf("order-001", "item-1", "PC-5169-A"),
                assignmentOf(ORDER_2, "item-2", "PC-5169-A"));

        var preview = realChainService().preview(TENANT, List.of("order-001", ORDER_2), assignments, null);

        assertThat(preview.orderCount()).isEqualTo(2);
        assertThat(preview.formulaMeters()).as("逐单公式米数合计 6").isEqualByComparingTo("6");
        assertThat(preview.pooledPlannedMeters()).as("池化后应领合计 3").isEqualByComparingTo("3");
        assertThat(preview.savedMeters()).as("预计节省 = 6 − 3").isEqualByComparingTo("3");
        assertThat(preview.perOrderPlannedMeters()).as("对照：逐单派应领合计 6").isEqualByComparingTo("6");
        assertThat(preview.poolingGainMeters()).as("池化**新增**收益 = 6 − 3（不把 #5158 的旧收益算进来）")
                .isEqualByComparingTo("3");
        // 预览是只读的：不建加工单、不落台账
        verify(processingOrderMapper, never()).insert(any(ProcessingOrder.class));
        verify(stockBatchConsumptionService, never()).apply(any(), any(), any(), anyList());

        var results = realChainService().generate(List.of("order-001", ORDER_2), assignments,
                TENANT, "文员", null, Boolean.TRUE);
        assertThat(results).allSatisfy(r -> assertThat(r.isSuccess()).isTrue());
        ArgumentCaptor<List> applied = ArgumentCaptor.forClass(List.class);
        verify(stockBatchConsumptionService, times(2))
                .apply(eq(TENANT), anyString(), anyString(), applied.capture());
        BigDecimal actuallyApplied = BigDecimal.ZERO;
        for (List<?> rows : applied.getAllValues()) {
            for (Object row : rows) {
                StockBatchConsumptionService.Deduction d = (StockBatchConsumptionService.Deduction) row;
                actuallyApplied = actuallyApplied.add(d.formulaMeters().subtract(d.plannedMeters()));
            }
        }
        assertThat(preview.savedMeters())
                .as("🔴 预览「预计节省」与**实际落账**的 Σ(formula − planned) 逐值相等（同一个数，不是两套口径）")
                .isEqualByComparingTo(actuallyApplied);
        assertThat(actuallyApplied).isEqualByComparingTo("3");
        assertThat(preview.perOrderPlannedMeters().subtract(preview.pooledPlannedMeters()))
                .as("判别力：按**逐单派**口径算的节省是 0（≠3）⇒ 上面那条断言不是空断言")
                .isEqualByComparingTo("3");
    }

    @Test
    @DisplayName("#5169 判据5 待派池：按物料分组可查 / 等待时长可读 / 超上限**带单号**告警")
    void poolGroupsByMaterialAndWarnsOverdueOrders() {
        java.time.OffsetDateTime now = java.time.OffsetDateTime.now();
        // ⚠️ 顺序**必须忠于真实查询**：`pool()` 走 `orderByAsc(createdAt)`（池的遍历序 = 下单时刻升序），
        // 而 `orderMapper` 是 mock ⇒ 这里给的列表顺序**就是**那条 ORDER BY 的结果。
        // （issue #5177 顺手修正：改前本夹具把「最新下的单」放最前，与真实查询相反 ——
        //  于是那条「池内等待时长逐单可读」的断言其实测的是 mock 的列表序，不是生产行为。
        //  夹具与真实查询对齐之后，下面 `lines().get(0).waitHours() == 30.0` 在生产语义下**改前改后都是 30.0**，
        //  这正是判据 1/2「缺省不变」的实证：没有加急单、没有到货日时，
        //  `POOL_LINE_ORDER` 的第一把键恒相等、第二把（等待时长降序）与 `createdAt` 升序**同序**。）
        when(orderMapper.selectList(any())).thenReturn(List.of(
                confirmedOrderOf("order-003", "ORD-20260912-0003", now.minusHours(40)),
                confirmedOrderOf(ORDER_2, "ORD-20260912-0002", now.minusHours(30)),
                confirmedOrderOf("order-001", "ORD-20260912-0001", now.minusHours(2)),
                confirmedOrderOf("order-004", "ORD-20260912-0004", now.minusHours(1))));
        // order-003 已有活跃加工单 ⇒ **不进池**（池 = 已确认支付 **且无活跃加工单**）；
        // 它在 `loadOrderItems` 之前被 `continue` 掉 ⇒ 明细 stub 的消耗序 = ORDER_2 → order-001 → order-004
        when(processingOrderMapper.selectActiveOrderIds(eq(TENANT), anyCollection()))
                .thenReturn(List.of("order-003"));
        List<OrderItem> sku1 = List.of(itemOf("order-001", "item-1", "SKU-1"));
        List<OrderItem> sku1b = List.of(itemOf(ORDER_2, "item-2", "SKU-1"));
        List<OrderItem> sku2 = List.of(itemOf("order-004", "item-4", "SKU-2"));
        when(orderItemMapper.selectList(any())).thenReturn(sku1b, sku1, sku2);

        var pool = processingOrderService.pool(TENANT, null);

        assertThat(pool.maxWaitHours()).as("生效阈值**回口径**（读的人不必猜）").isEqualByComparingTo("24");
        assertThat(pool.poolingEnabled()).as("池**看得见** ≠ 池化**已开启**（缺省关）").isFalse();
        assertThat(pool.orderCount()).as("order-003 被排除 ⇒ 3 张单在池").isEqualTo(3);
        assertThat(pool.lineCount()).isEqualTo(3);
        assertThat(pool.groups()).as("按物料（商品 × 颜色 × 门幅 = productId|skuCode）分组").hasSize(2);
        var group = pool.groups().stream().filter(g -> "SKU-1".equals(g.skuCode())).findFirst()
                .orElseThrow();
        assertThat(group.materialKey()).isEqualTo("prod-1|SKU-1");
        assertThat(group.orderCount()).as("同物料两张单只算两张（按行去重）").isEqualTo(2);
        assertThat(group.requiredMeters()).isEqualByComparingTo("6");
        assertThat(pool.overdueCount()).as("30 小时 > 上限 24 小时 ⇒ 恰好一张超上限").isEqualTo(1);
        assertThat(pool.warnings()).hasSize(1);
        assertThat(pool.warnings().get(0).orderNo()).isEqualTo("ORD-20260912-0002");
        assertThat(pool.warnings().get(0).waitHours()).isEqualByComparingTo("30.0");
        assertThat(pool.warnings().get(0).message())
                .as("🔴 告警必须**带着对象名字**说出来：哪张单、等了多久、该做什么（不得静默压单）")
                .contains("ORD-20260912-0002").contains("30.0").contains("24")
                .contains("成批派单");
        assertThat(pool.groups().get(0).lines().get(0).waitHours())
                .as("池内等待时长**逐单可读**，且**等得久的在前**（= 记录期既有序：池按 createdAt 升序遍历；"
                        + "issue #5177 的排序键在「无加急单、无到货日」时与之**同序** ⇒ 缺省不变）")
                .isEqualByComparingTo("30.0");
        assertThat(pool.groups().get(0).lines().get(0).overdue()).isTrue();
        assertThat(pool.groups().get(0).lines().get(1).waitHours())
                .as("同物料组内第二行 = 等得较短的 order-001（两组行都在，不只是第一行对）")
                .isEqualByComparingTo("2.0");
        assertThat(pool.groups().get(0).lines().get(1).overdue()).isFalse();
        // issue #5177 判据 2：**没有任何加急单**时的缺省形态 —— 插队区必须是空的、不许多出对象
        assertThat(pool.urgentCount()).as("缺省（无加急单）⇒ 插队区不去重计数为 0").isZero();
        assertThat(pool.urgentLines()).as("缺省（无加急单）⇒ 插队区为空（池的成员一个都没少）").isEmpty();
        assertThat(pool.orderCount() + pool.urgentCount())
                .as("池内 + 插队区 = 全部无活跃加工单的已确认订单（一张单都不会既不在池、也不在插队区）")
                .isEqualTo(3);
        for (var line : pool.groups().get(0).lines()) {
            assertThat(line.isUrgent()).as("池内不得出现加急行（加急单不进池）").isFalse();
            assertThat(line.requiredDeliveryDate()).as("未指定 ⇒ null（不猜，不拿今天顶替）").isNull();
            assertThat(line.deliveryDaysLeft()).as("未指定 ⇒ 临期度也是 null，不得编 0").isNull();
        }

        // 上限**可配**：调成 1 小时 ⇒ 三张单全超上限（这张图才是「没有单被静默压住」）
        when(orderItemMapper.selectList(any())).thenReturn(sku1b, sku1, sku2);
        var tighter = processingOrderService.pool(TENANT, new BigDecimal("1"));
        assertThat(tighter.maxWaitHours()).isEqualByComparingTo("1");
        assertThat(tighter.overdueCount())
                .as("上限可配：调成 1 小时 ⇒ 2 小时与 30 小时的两张超上限；恰好 1.0 小时的那张"
                        + "**不算**超（判据是严格大于）")
                .isEqualTo(2);
        // 非正数 ⇒ 显式拒绝（不静默回落缺省值：静默回落会让看板以为在按自己设的阈值告警）
        assertThatThrownBy(() -> processingOrderService.pool(TENANT, BigDecimal.ZERO))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("maxWaitHours 必须为正数");
    }
}