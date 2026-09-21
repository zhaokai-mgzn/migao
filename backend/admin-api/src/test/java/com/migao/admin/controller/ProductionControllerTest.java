// case_ids: PG-018, PG-019, PG-020, PG-021, PG-032, PG-033, PG-034, PG-035, PG-040, PG-048, PG-049
package com.migao.admin.controller;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.config.GlobalExceptionHandler;
import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.entity.ProcessingOrderSet;
import com.migao.admin.entity.ProcessingPositionOperation;
import com.migao.admin.entity.ProcessingSetPartToken;
import com.migao.admin.entity.ProcessingFeeCombination;
import com.migao.admin.entity.ProcessingItem;
import com.migao.admin.entity.ProductionOperation;
import com.migao.admin.entity.ProductionOperationPosition;
import com.migao.admin.entity.ProductionOperationPriceVersion;
import com.migao.admin.entity.ProductionRouteTemplate;
import com.migao.admin.entity.ProductionRouting;
import com.migao.admin.entity.ProductionWorkLog;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProcessingItemMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import com.migao.admin.mapper.ProcessingPositionOperationMapper;
import com.migao.admin.mapper.ProductionOperationMapper;
import com.migao.admin.mapper.ProductionOperationPriceVersionMapper;
import com.migao.admin.mapper.ProductionRoutingMapper;
import com.migao.admin.mapper.ProductionWorkLogMapper;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.service.ClientRequestIdService;
import com.migao.admin.service.OrderService;
import com.migao.admin.service.ProcessingOrderService;
import com.migao.admin.service.ProductionOperationCommandService;
import com.migao.admin.service.ProductionRoutingCommandService;
import com.migao.admin.service.ProcessingFeeCombinationCommandService;
import com.migao.admin.service.ProcessingFeeQueryService;
import com.migao.admin.service.ProductionOperationQueryService;
import com.migao.admin.service.ProductionInstanceRepricingService;
import com.migao.admin.service.ProductionOperationQtyClient;
import com.migao.admin.service.ProductionScanService;
import com.migao.admin.service.ProductionService;
import com.migao.admin.service.ProductionStuckPointService;
import com.migao.admin.service.RoutingModelFixture;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.lang.reflect.Method;
import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.hamcrest.Matchers.containsString;
import static org.hamcrest.Matchers.matchesPattern;
import static org.hamcrest.Matchers.nullValue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * ProductionController 测试（生产报工链路，issue #3995，M4-G-2）
 *
 * 走 standalone MockMvc + 真实 ProductionService（只 mock DB 层 Mapper），
 * 因此断言的是**服务端真实语义**而非「被调用过」：
 * 实例化落库 qr_token / 扫码报工推进进度 / 必完工序全绿自动完工 / 计件按合格数量。
 * 契约与真值：docs/curtain-production-rules.md §4/§5。
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("ProductionController 生产报工接口测试")
class ProductionControllerTest {

    private static final Long TENANT = 1L;
    private static final String ORDER_ID = "order-1";
    private static final String PO_ID = "po-1";

    private MockMvc mockMvc;
    private final ObjectMapper objectMapper = new ObjectMapper();

    @Mock
    private ProcessingOrderMapper processingOrderMapper;
    @Mock
    private ProcessingPositionOperationMapper positionOperationMapper;
    @Mock
    private ProductionWorkLogMapper workLogMapper;
    @Mock
    private OrderMapper orderMapper;
    @Mock
    private ClientRequestIdService clientRequestIdService;
    @Mock
    private ProductionOperationMapper productionOperationMapper;
    @Mock
    private ProductionRoutingMapper productionRoutingMapper;
    /** 特殊选项两张表（issue #4230，V59）。 */
    @Mock
    private com.migao.admin.mapper.ProductionOptionRoutingMapper productionOptionRoutingMapper;
    @Mock
    private com.migao.admin.mapper.ProductionOptionFactorMapper productionOptionFactorMapper;
    @Mock
    private com.migao.admin.mapper.ProductionRouteSignalMapper productionRouteSignalMapper;
    @Mock
    private com.migao.admin.mapper.ProductionRouteTemplateMapper productionRouteTemplateMapper;
    @Mock
    private com.migao.admin.mapper.ProductionRouteRuleMapper productionRouteRuleMapper;
    @Mock
    private com.migao.admin.mapper.ProductionOperationPositionMapper productionOperationPositionMapper;
    @Mock
    private com.migao.admin.mapper.ProductionCraftMapper productionCraftMapper;
    @Mock
    private com.migao.admin.mapper.ProductionRoutingVersionMapper routingVersionMapper;
    @Mock
    private ProductionOperationPriceVersionMapper priceVersionMapper;
    @Mock
    private OrderItemMapper orderItemMapper;
    @Mock
    private ProcessingItemMapper processingItemMapper;
    /** 加工费组合定价（issue #4386，V68）：组合表 + 版本账（读面另用 orderItemMapper）。 */
    @Mock
    private com.migao.admin.mapper.ProcessingFeeCombinationMapper processingFeeCombinationMapper;
    @Mock
    private com.migao.admin.mapper.ProcessingFeeCombinationVersionMapper processingFeeCombinationVersionMapper;
    @Mock
    private OrderService orderService;
    /** 未定价实例补价动作账（V94，issue #4709 C）。 */
    @Mock
    private com.migao.admin.mapper.ProductionInstanceRepricingLogMapper repricingLogMapper;
    /** 应做数量来源（issue #4208 接线）：存量单补工序的派生路径与 generate 路径同一份，故也要打桩。 */
    @Mock
    private ProductionOperationQtyClient operationQtyClient;
    /** 扫码解析的两张新表（V92，切片 ⓪ / issue #4698）：一部位一码 token + 套号载体。 */
    @Mock
    private com.migao.admin.mapper.ProcessingSetPartTokenMapper setPartTokenMapper;
    @Mock
    private com.migao.admin.mapper.ProcessingOrderSetMapper orderSetMapper;

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(TENANT);
        ProductionService service = new ProductionService(
                processingOrderMapper, positionOperationMapper, workLogMapper, orderMapper,
                orderItemMapper, clientRequestIdService);
        // 工序库读面用**真实对象**（只 mock Mapper）：PUT 的响应形态 = 目录项形态（同一份
        // operationView），用 mock 会让「返回更新后的工序」退化成断言桩。
        ProductionOperationQueryService queryService =
                new ProductionOperationQueryService(productionOperationMapper, productionRouteTemplateMapper,
                        productionRouteRuleMapper, productionOperationPositionMapper,
                        productionCraftMapper, productionRouteSignalMapper);
        // 存量单补工序（#4202）的派生走 ProcessingOrderService（工序库路线），故装配真实对象：
        // 与 generate 路径**同一份**路线解析（不复制第二份）。
        ProcessingOrderService processingOrderService = new ProcessingOrderService(
                processingOrderMapper, orderMapper, orderItemMapper, processingItemMapper,
                orderService, objectMapper, service, queryService, operationQtyClient);
        ProductionOperationCommandService commandService = new ProductionOperationCommandService(
                productionOperationMapper, priceVersionMapper, productionOperationPositionMapper, queryService);
        // 路线/信号写面（issue #4308）：真实对象（只 mock Mapper），响应形态 = 路线展示形态（同一份）
        ProductionRoutingCommandService routingCommandService = new ProductionRoutingCommandService(
                productionRouteTemplateMapper, routingVersionMapper, productionOperationMapper,
                queryService, productionRouteRuleMapper, processingItemMapper);
        // 加工费组合定价（issue #4386）：真实服务（只 mock Mapper），写面响应形态 = 列表项形态
        // （同一份 combinationView）。控制器里这两个依赖是**字段注入**（不动既有 6 参构造），
        // 故这里用 ReflectionTestUtils 装配 —— 目的只是让新端点可达，不改既有端点的装配。
        ProcessingFeeQueryService feeQueryService = new ProcessingFeeQueryService(
                processingFeeCombinationMapper, processingItemMapper, orderItemMapper);
        ProcessingFeeCombinationCommandService feeCommandService =
                new ProcessingFeeCombinationCommandService(
                        processingFeeCombinationMapper, processingFeeCombinationVersionMapper,
                        processingItemMapper, feeQueryService);
        ProductionController controller = new ProductionController(service, queryService, commandService,
                routingCommandService, processingOrderService, orderService);
        org.springframework.test.util.ReflectionTestUtils.setField(controller,
                "processingFeeQueryService", feeQueryService);
        org.springframework.test.util.ReflectionTestUtils.setField(controller,
                "processingFeeCombinationCommandService", feeCommandService);
        // 扫码解析 + 工序推断（切片 ①，issue #4698）：同样字段注入 ⇒ 这里装配真实服务
        // （只 mock Mapper），端点契约（路径 / 参数名 / 信封）才有意义。
        // 卡点判据（切片 ③，issue #4776）：同样是真实对象（只 mock Mapper）—— 报表与 stalled 键
        // 的响应形状必须是前端消费的那一份（不复制第二份装配、不动既有 6 参构造）。
        ProductionStuckPointService stuckPointService = new ProductionStuckPointService(
                service, positionOperationMapper, orderSetMapper, 4.0);
        org.springframework.test.util.ReflectionTestUtils.setField(controller, "productionScanService",
                new ProductionScanService(setPartTokenMapper, orderSetMapper, processingOrderMapper,
                        positionOperationMapper, orderItemMapper, queryService, service,
                        stuckPointService));
        org.springframework.test.util.ReflectionTestUtils.setField(controller, "productionStuckPointService",
                stuckPointService);
        // 未定价实例补价（issue #4709 C）：与上面同款字段注入 —— 真实服务（只 mock Mapper），
        // 响应形态就是前端消费的那个 Map（不复制第二份装配、不动既有 6 参构造）。
        ProductionInstanceRepricingService repricingService = new ProductionInstanceRepricingService(
                orderMapper, processingOrderMapper, positionOperationMapper, queryService,
                repricingLogMapper);
        org.springframework.test.util.ReflectionTestUtils.setField(controller,
                "productionInstanceRepricingService", repricingService);
        mockMvc = MockMvcBuilders.standaloneSetup(controller)
                .setControllerAdvice(new GlobalExceptionHandler())
                .build();
        // 无幂等键 ⇒ 老路径（claim 首执）；幂等接线自身的断言见「报工」段的两个专测
        when(clientRequestIdService.claim(any(), any(), any())).thenReturn(true);
        // §5-1 原子有序推进：真实 DB 首执影响 1 行；CAS 失败由专测打桩为 0
        when(positionOperationMapper.advanceDoneQtyIfUnchanged(any(), any(), any(), any(), any(), any()))
                .thenReturn(1);
        // 应做数量（issue #4208）：派生/生成路径都要问算料引擎；本类不测算料口径，
        // 故统一返回**与订单数量一致**的 2（既有断言「qty=2」的语义由「退化」变成「引擎输出」，
        // 算料口径本身的判据在 ProcessingOrderServiceTest / ProductionOperationQtyClientTest）。
        when(operationQtyClient.resolve(any())).thenAnswer(inv -> {
            List<Map<String, Object>> request = inv.getArgument(0);
            List<ProductionOperationQtyClient.PositionQty> resolved = new ArrayList<>();
            for (Map<String, Object> position : request) {
                Map<String, BigDecimal> qty = new LinkedHashMap<>();
                Map<String, String> source = new LinkedHashMap<>();
                for (Object raw : (List<?>) position.get("operations")) {
                    qty.put(String.valueOf(raw), new BigDecimal("2"));
                    source.put(String.valueOf(raw), "fallback");
                }
                resolved.add(new ProductionOperationQtyClient.PositionQty(
                        (String) position.get("position_name"), qty, source));
            }
            return resolved;
        });
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    /**
     * {@code LambdaUpdateWrapper.set(...)} 会**立即**求值列名（不像 {@code LambdaQueryWrapper.eq}
     * 延迟到渲染 SQL）⇒ standalone MockMvc 单测没有 MapperScan 建立的 TableInfo 缓存时会抛
     * 「can not find lambda cache for this entity」。工序软删（#4608）与矩阵行软删（#4665 C）
     * 都走 {@code LambdaUpdateWrapper}，故在此初始化这两张表的缓存
     * （同 {@code ProductionOperationDeleteGuardTest} 的既有做法）。
     */
    @BeforeAll
    static void primeMybatisPlusLambdaCache() {
        MybatisConfiguration configuration = new MybatisConfiguration();
        MapperBuilderAssistant assistant = new MapperBuilderAssistant(configuration, "");
        TableInfoHelper.initTableInfo(assistant, ProductionOperation.class);
        TableInfoHelper.initTableInfo(assistant, ProductionOperationPosition.class);
    }

    // ── 夹具 ──

    private Order order(String status) {
        Order o = new Order();
        o.setId(ORDER_ID);
        o.setTenantId(TENANT);
        o.setOrderNo("ORD-20260917-001");
        o.setStatus(status);
        o.setDeleted(0);
        return o;
    }

    private ProcessingOrder processingOrder(String qrToken) {
        ProcessingOrder po = new ProcessingOrder();
        po.setId(PO_ID);
        po.setTenantId(TENANT);
        po.setOrderId(ORDER_ID);
        po.setProcessingOrderNo("JG-20260917-0001");
        po.setStatus("in_processing");
        po.setQrToken(qrToken);
        po.setDeleted(0);
        return po;
    }

    private ProcessingPositionOperation op(String id, int seq, String name, String qty,
                                          boolean mustFinish, String status, String doneQty) {
        return ProcessingPositionOperation.builder()
                .id(id).tenantId(TENANT).processingOrderId(PO_ID)
                .positionName("布帘").seq(seq).operationName(name).groupName("后道").unit("套")
                .qty(new BigDecimal(qty)).unitPrice(new BigDecimal("0.40")).factor(new BigDecimal("1.00"))
                .isMustFinish(mustFinish).isStartMarker(false)
                .status(status).doneQty(new BigDecimal(doneQty)).deleted(0)
                .build();
    }

    private ProductionWorkLog log(String opId, String opName, String worker, String qty,
                                  String qualifiedQty, String workType) {
        return ProductionWorkLog.builder()
                .tenantId(TENANT).processingOrderId(PO_ID).operationId(opId).operationName(opName)
                .workerName(worker).qty(new BigDecimal(qty)).qualifiedQty(new BigDecimal(qualifiedQty))
                .workType(workType).deleted(0).build();
    }

    private static final String INSTANTIATE_BODY = """
            {"positions":[{"position_name":"布帘","operations":[
              {"seq":1,"operation":"精裁-布","group":"裁剪","unit":"米","qty":12.3,"unit_price":0.4,
               "factor":1.0,"is_must_finish":false,"is_start_marker":true},
              {"seq":2,"operation":"外帘装袋","group":"后道","unit":"套","qty":1,"unit_price":1.0,
               "factor":1.0,"is_must_finish":true,"is_start_marker":false}]}]}
            """;

    // ══════════════════════════ 实例化 ══════════════════════════

    @Test
    @DisplayName("实例化工序 → 200 返回 qr_token 并落地 processing_orders.qr_token")
    void instantiateWritesQrTokenAndOperations() throws Exception {
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order("producing"));
        when(processingOrderMapper.selectActiveByOrderId(ORDER_ID, TENANT)).thenReturn(processingOrder(null));
        when(positionOperationMapper.insert(any(ProcessingPositionOperation.class))).thenReturn(1);
        when(processingOrderMapper.updateById(any(ProcessingOrder.class))).thenReturn(1);

        String body = mockMvc.perform(post("/api/admin/production/orders/" + ORDER_ID + "/instantiate")
                        .contentType("application/json").content(INSTANTIATE_BODY))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.qr_token").value(matchesPattern("[0-9a-f]{32}")))
                .andExpect(jsonPath("$.data.operation_count").value(2))
                .andReturn().getResponse().getContentAsString();

        // 效果层断言：返回的 token 必须真落到 processing_orders（不是只「调了 updateById」）
        String returned = objectMapper.readTree(body).path("data").path("qr_token").asText();
        ArgumentCaptor<ProcessingOrder> captor = ArgumentCaptor.forClass(ProcessingOrder.class);
        verify(processingOrderMapper).updateById(captor.capture());
        assertThat(captor.getValue().getId()).isEqualTo(PO_ID);
        assertThat(captor.getValue().getQrToken()).isEqualTo(returned);

        verify(positionOperationMapper, times(2)).insert(any(ProcessingPositionOperation.class));
    }

    @Test
    @DisplayName("重复实例化复用已有 qr_token（已打印的二维码不失效）")
    void instantiateReusesExistingQrToken() throws Exception {
        String existing = "a".repeat(32);
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order("producing"));
        when(processingOrderMapper.selectActiveByOrderId(ORDER_ID, TENANT)).thenReturn(processingOrder(existing));
        when(positionOperationMapper.insert(any(ProcessingPositionOperation.class))).thenReturn(1);

        mockMvc.perform(post("/api/admin/production/orders/" + ORDER_ID + "/instantiate")
                        .contentType("application/json").content(INSTANTIATE_BODY))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.qr_token").value(existing));
    }

    @Test
    @DisplayName("订单尚无加工单 → 422（工序实例挂在加工单上）")
    void instantiateWithoutProcessingOrderRejected() throws Exception {
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order("confirmed"));
        when(processingOrderMapper.selectActiveByOrderId(ORDER_ID, TENANT)).thenReturn(null);

        mockMvc.perform(post("/api/admin/production/orders/" + ORDER_ID + "/instantiate")
                        .contentType("application/json").content(INSTANTIATE_BODY))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.success").value(false));
    }

    @Test
    @DisplayName("订单不存在（含跨租户）→ 404")
    void instantiateUnknownOrderNotFound() throws Exception {
        when(orderMapper.selectById(ORDER_ID)).thenReturn(null);

        mockMvc.perform(post("/api/admin/production/orders/" + ORDER_ID + "/instantiate")
                        .contentType("application/json").content(INSTANTIATE_BODY))
                .andExpect(status().isNotFound());
    }

    @Test
    @DisplayName("positions 缺省但订单无加工项 ⇒ 派生为空 ⇒ 服务层 fail-closed 422（不落空实例）")
    void instantiateDeriveWithoutProcessingItemsRejected() throws Exception {
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order("confirmed"));
        when(processingOrderMapper.selectActiveByOrderId(ORDER_ID, TENANT)).thenReturn(processingOrder(null));
        when(orderItemMapper.selectList(any())).thenReturn(List.of());   // 无加工项 ⇒ 派生不出部位

        mockMvc.perform(post("/api/admin/production/orders/" + ORDER_ID + "/instantiate")
                        .contentType("application/json").content("{}"))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.success").value(false));

        verify(positionOperationMapper, never()).insert(any(ProcessingPositionOperation.class));
    }

    // ══════════════════════════ 查询 ══════════════════════════

    @Test
    @DisplayName("查询工序 → 200 按部位分组 + 进度百分比")
    void operationsReturnsTreeAndProgress() throws Exception {
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order("producing"));
        when(processingOrderMapper.selectActiveByOrderId(ORDER_ID, TENANT)).thenReturn(processingOrder("tok123"));
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(
                op("op-1", 1, "精裁-布", "12.30", false, "done", "12.30"),
                op("op-2", 2, "外帘装袋", "1.00", true, "pending", "0.00")));

        mockMvc.perform(get("/api/admin/production/orders/" + ORDER_ID + "/operations"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.order_id").value(ORDER_ID))
                .andExpect(jsonPath("$.data.qr_token").value("tok123"))
                .andExpect(jsonPath("$.data.positions[0].position_name").value("布帘"))
                .andExpect(jsonPath("$.data.positions[0].operations[0].operation").value("精裁-布"))
                .andExpect(jsonPath("$.data.positions[0].operations[0].is_must_finish").value(false))
                // 🔴 #4961：键**保留**（冻结键集）但值**恒 false** —— 改前这一行断言 `true`
                // （「外帘装袋」是库里唯一标了必完的工序）。`value(false)` 同时钉住「键必须在」
                // （路径不存在 ⇒ jsonPath 取不到值 ⇒ 断言红）。
                .andExpect(jsonPath("$.data.positions[0].operations[1].is_must_finish").value(false))
                .andExpect(jsonPath("$.data.positions[0].operations[1].done_qty").value(0.0))
                .andExpect(jsonPath("$.data.progress.total").value(2))
                .andExpect(jsonPath("$.data.progress.done").value(1))
                .andExpect(jsonPath("$.data.progress.percent").value(50));
    }

    @Test
    @DisplayName("扫码解析（切片 ①）→ 200：新码带套带部位 + 系统推断下一道，部位不选")
    void scanResolvesNewTokenToSetPositionAndInferredOperation() throws Exception {
        when(setPartTokenMapper.selectOne(any())).thenReturn(ProcessingSetPartToken.builder()
                .id("tok-1").tenantId(TENANT).processingOrderId(PO_ID).setId("set-14")
                .orderItemId("oi-cloth").positionKind("布帘").token("newtok").deleted(0).build());
        when(orderSetMapper.selectById("set-14")).thenReturn(ProcessingOrderSet.builder()
                .id("set-14").tenantId(TENANT).processingOrderId(PO_ID)
                .setIndex(14).setNo("CSO260915-02615-014").deleted(0).build());
        when(processingOrderMapper.selectById(PO_ID)).thenReturn(processingOrder("tok123"));
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(
                scanOp("op-1", 1, "精裁-布", "done"),
                scanOp("op-2", 2, "定型-布", "pending")));

        mockMvc.perform(get("/api/admin/production/scan").param("token", "newtok"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.granularity").value("set_position"))
                .andExpect(jsonPath("$.data.set_no").value("CSO260915-02615-014"))
                .andExpect(jsonPath("$.data.set_index").value(14))
                .andExpect(jsonPath("$.data.position.order_item_id").value("oi-cloth"))
                .andExpect(jsonPath("$.data.position.position_kind").value("布帘"))
                .andExpect(jsonPath("$.data.operation.operation_id").value("op-2"))
                .andExpect(jsonPath("$.data.operation.determined_by").value("inferred"))
                .andExpect(jsonPath("$.data.operation.rerouted").value(false))
                // 卡点键（切片 ③，issue #4776；设计 §3.1 逐字）：op-1 已完成但 **done_at 为 NULL**
                // （切片 ② 之前的存量行）⇒「上道几点完成」不可知 ⇒ **不判卡**（§6.3 p.done_at IS NOT NULL）；
                // 三态照实给（state=not_started），不静默混成「未卡」
                .andExpect(jsonPath("$.data.stalled.state").value("not_started"))
                .andExpect(jsonPath("$.data.stalled.predecessor_done").value(true))
                .andExpect(jsonPath("$.data.stalled.predecessor_done_at").value(nullValue()))
                .andExpect(jsonPath("$.data.stalled.kind").value(nullValue()))
                .andExpect(jsonPath("$.data.stalled.threshold_source").value("default"))
                .andExpect(jsonPath("$.data.needs_selection").isEmpty());
    }

    @Test
    @DisplayName("卡点报表（切片 ③）→ 200：A 模式只列「没开工」，附上道完成时刻/等了多久/阈值来源")
    void stuckPointsReportsNotStartedOnly() throws Exception {
        when(orderSetMapper.selectList(any())).thenReturn(List.of(ProcessingOrderSet.builder()
                .id("set-14").tenantId(TENANT).processingOrderId(PO_ID)
                .setIndex(14).setNo("CSO260915-02615-014").deleted(0).build()));
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(
                scanOpDoneAt("op-1", 1, "精裁-布", OffsetDateTime.now().minusHours(6)),
                scanOp("op-2", 2, "定型-布", "pending"),                 // 上道 6 小时前完成 ⇒ 卡
                // 做了一半：**绝不**进卡点表（红证②的端点侧）；它也是 op-3 的立即前道（未完成）
                halfDoneScanOp("op-half", 3, "三边-布"),
                scanOp("op-3", 4, "复烫-布", "pending")));

        mockMvc.perform(get("/api/admin/production/stuck-points")
                        .param("processing_order_id", PO_ID))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.mode").value("A"))
                .andExpect(jsonPath("$.data.threshold_source").value("default"))
                .andExpect(jsonPath("$.data.scope.processing_order_id").value(PO_ID))
                .andExpect(jsonPath("$.data.states.not_started").value(2))
                .andExpect(jsonPath("$.data.states.in_progress").value(1))
                .andExpect(jsonPath("$.data.states.completed").value(1))
                .andExpect(jsonPath("$.data.stuck_total").value(1))
                .andExpect(jsonPath("$.data.stuck[0].kind").value("not_started"))
                .andExpect(jsonPath("$.data.stuck[0].set_no").value("CSO260915-02615-014"))
                .andExpect(jsonPath("$.data.stuck[0].operation.operation_id").value("op-2"))
                .andExpect(jsonPath("$.data.stuck[0].operation.state").value("not_started"))
                .andExpect(jsonPath("$.data.stuck[0].predecessor.operation_id").value("op-1"))
                .andExpect(jsonPath("$.data.stuck[0].predecessor.done_at").exists());
    }

    /** 卡点报表夹具：已完成且**有 done_at** 的实例行（只有切片 ② 之后的新报工才会写它）。 */
    private static ProcessingPositionOperation scanOpDoneAt(String id, int seq, String name,
                                                           OffsetDateTime doneAt) {
        ProcessingPositionOperation op = scanOp(id, seq, name, "done");
        op.setDoneAt(doneAt);
        return op;
    }

    /** 卡点报表夹具：**做了一半**（0 < done_qty < qty）—— 三态里的中间态。 */
    private static ProcessingPositionOperation halfDoneScanOp(String id, int seq, String name) {
        ProcessingPositionOperation op = scanOp(id, seq, name, "pending");
        op.setDoneQty(new BigDecimal("6"));
        return op;
    }

    @Test
    @DisplayName("扫码解析（切片 ①）→ 200：旧码降级为加工单级 + 强制选套选部位（绝不默认取第 1 套）")
    void scanLegacyTokenDegradesWithoutDefaultingToFirstSet() throws Exception {
        when(setPartTokenMapper.selectOne(any())).thenReturn(null);
        when(orderMapper.selectById("oldtoke")).thenReturn(null);
        when(orderMapper.selectOne(any())).thenReturn(null);
        when(processingOrderMapper.selectOne(any())).thenReturn(processingOrder("oldtoke"));
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order("producing"));
        when(processingOrderMapper.selectActiveByOrderId(ORDER_ID, TENANT))
                .thenReturn(processingOrder("oldtoke"));
        when(orderSetMapper.selectList(any())).thenReturn(List.of(ProcessingOrderSet.builder()
                .id("set-1").tenantId(TENANT).processingOrderId(PO_ID)
                .setIndex(1).setNo("CSO260915-02615-001").deleted(0).build()));

        mockMvc.perform(get("/api/admin/production/scan").param("token", "oldtoke"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.granularity").value("order"))
                // 第 1 套只作为候选出现在 selections 里，**不是**默认值
                .andExpect(jsonPath("$.data.set_no").value(nullValue()))
                .andExpect(jsonPath("$.data.set_index").value(nullValue()))
                .andExpect(jsonPath("$.data.position").value(nullValue()))
                .andExpect(jsonPath("$.data.operation").value(nullValue()))
                .andExpect(jsonPath("$.data.needs_selection[0]").value("set"))
                .andExpect(jsonPath("$.data.needs_selection[1]").value("position"))
                .andExpect(jsonPath("$.data.selections[0].set_no").value("CSO260915-02615-001"));
    }

    /** 扫码解析夹具：带套带部位的工序实例（V92 的 set_id / order_item_id）。 */
    private static ProcessingPositionOperation scanOp(String id, int seq, String name, String status) {
        return ProcessingPositionOperation.builder()
                .id(id).tenantId(TENANT).processingOrderId(PO_ID).setId("set-14")
                .orderItemId("oi-cloth").positionKind("布帘").positionName("布艺遮光帘A")
                .seq(seq).operationName(name).groupName("车位").unit("米")
                .qty(new BigDecimal("11")).doneQty("done".equals(status)
                        ? new BigDecimal("11") : BigDecimal.ZERO)
                .unitPrice(new BigDecimal("3.50")).isMustFinish(false).isStartMarker(false)
                .status(status).deleted(0)
                .build();
    }

    @Test
    @DisplayName("尚无加工单 → 200 空进度（不是错误态：订单未进入生产）")
    void operationsWithoutProcessingOrderReturnsEmptyProgress() throws Exception {
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order("confirmed"));
        when(processingOrderMapper.selectActiveByOrderId(ORDER_ID, TENANT)).thenReturn(null);

        mockMvc.perform(get("/api/admin/production/orders/" + ORDER_ID + "/operations"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.order_id").value(ORDER_ID))
                .andExpect(jsonPath("$.data.positions").isArray())
                .andExpect(jsonPath("$.data.progress.total").value(0))
                .andExpect(jsonPath("$.data.progress.done").value(0))
                .andExpect(jsonPath("$.data.progress.percent").value(0));
    }

    // ══════════════════════════ 报工 ══════════════════════════

    @Test
    @DisplayName("正常报工 → done_qty 累加 + status=done + 必完全绿 → 加工单 completed（订单状态不动）")
    void reportNormalCompletesOrderWhenMustFinishAllDone() throws Exception {
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order("producing"));
        when(processingOrderMapper.selectActiveByOrderId(ORDER_ID, TENANT)).thenReturn(processingOrder("tok123"));
        when(positionOperationMapper.selectById("op-2"))
                .thenReturn(op("op-2", 2, "外帘装袋", "1.00", true, "pending", "0.00"));
        when(workLogMapper.insert(any(ProductionWorkLog.class))).thenReturn(1);
        when(positionOperationMapper.updateById(any(ProcessingPositionOperation.class))).thenReturn(1);
        // 报工后回查：必完工序已 done_qty=1 ≥ qty=1
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(
                op("op-2", 2, "外帘装袋", "1.00", true, "done", "1.00")));
        // 完工 = 加工单置 completed（issue #4117；订单状态不动）
        when(processingOrderMapper.markCompletedIfActive(eq(PO_ID), eq(TENANT), any())).thenReturn(1);

        mockMvc.perform(post("/api/admin/production/orders/" + ORDER_ID + "/operations/op-2/report")
                        .contentType("application/json")
                        .content("{\"worker_id\":\"w-1\",\"worker_name\":\"蒋雪云\",\"qty\":1,"
                                + "\"qualified_qty\":1,\"work_type\":\"normal\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.operation_id").value("op-2"))
                .andExpect(jsonPath("$.data.done_qty").value(1.0))
                .andExpect(jsonPath("$.data.status").value("done"))
                .andExpect(jsonPath("$.data.order_completed").value(true));

        // 落库断言：报工明细三态 + 合格数量 + 工序名快照
        ArgumentCaptor<ProductionWorkLog> logCaptor = ArgumentCaptor.forClass(ProductionWorkLog.class);
        verify(workLogMapper).insert(logCaptor.capture());
        assertThat(logCaptor.getValue().getWorkType()).isEqualTo("normal");
        assertThat(logCaptor.getValue().getQualifiedQty()).isEqualByComparingTo("1.00");
        assertThat(logCaptor.getValue().getWorkerName()).isEqualTo("蒋雪云");
        assertThat(logCaptor.getValue().getOperationName()).isEqualTo("外帘装袋");
        // 生产侧不得改写订单状态（否则 completed 终态会让订单既发不了货也回不去，#4117）
        verify(orderMapper, never()).update(any(), any());
    }

    @Test
    @DisplayName("必完工序未全绿 → 不完工（order_completed=false，加工单不置 completed）")
    void reportKeepsOrderProducingWhenMustFinishNotAllDone() throws Exception {
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order("producing"));
        when(processingOrderMapper.selectActiveByOrderId(ORDER_ID, TENANT)).thenReturn(processingOrder("tok123"));
        when(positionOperationMapper.selectById("op-2"))
                .thenReturn(op("op-2", 2, "外帘装袋", "1.00", true, "pending", "0.00"));
        when(workLogMapper.insert(any(ProductionWorkLog.class))).thenReturn(1);
        when(positionOperationMapper.updateById(any(ProcessingPositionOperation.class))).thenReturn(1);
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(
                op("op-2", 2, "外帘装袋", "1.00", true, "done", "1.00"),
                op("op-3", 3, "外帘打卷", "1.00", true, "pending", "0.00")));

        mockMvc.perform(post("/api/admin/production/orders/" + ORDER_ID + "/operations/op-2/report")
                        .contentType("application/json")
                        .content("{\"worker_name\":\"蒋雪云\",\"qty\":1,\"qualified_qty\":1,\"work_type\":\"normal\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.order_completed").value(false));

        verify(orderMapper, never()).update(any(), any());
    }

    @Test
    @DisplayName("返工报工 → 不累加 done_qty、不置 done、不完工")
    void reportReworkDoesNotAccumulate() throws Exception {
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order("producing"));
        when(processingOrderMapper.selectActiveByOrderId(ORDER_ID, TENANT)).thenReturn(processingOrder("tok123"));
        when(positionOperationMapper.selectById("op-2"))
                .thenReturn(op("op-2", 2, "外帘装袋", "1.00", true, "pending", "0.00"));
        when(workLogMapper.insert(any(ProductionWorkLog.class))).thenReturn(1);

        mockMvc.perform(post("/api/admin/production/orders/" + ORDER_ID + "/operations/op-2/report")
                        .contentType("application/json")
                        .content("{\"worker_name\":\"李红梅\",\"qty\":1,\"qualified_qty\":0,"
                                + "\"work_type\":\"rework\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.done_qty").value(0.0))
                .andExpect(jsonPath("$.data.status").value("pending"))
                .andExpect(jsonPath("$.data.order_completed").value(false));

        verify(positionOperationMapper, never()).updateById(any(ProcessingPositionOperation.class));
        verify(orderMapper, never()).update(any(), any());
    }

    @Test
    @DisplayName("报废报工 → 落库 work_type=scrap，不推进进度")
    void reportScrapIsRecordedButDoesNotAdvance() throws Exception {
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order("producing"));
        when(processingOrderMapper.selectActiveByOrderId(ORDER_ID, TENANT)).thenReturn(processingOrder("tok123"));
        when(positionOperationMapper.selectById("op-1"))
                .thenReturn(op("op-1", 1, "精裁-布", "12.30", false, "pending", "0.00"));
        when(workLogMapper.insert(any(ProductionWorkLog.class))).thenReturn(1);

        mockMvc.perform(post("/api/admin/production/orders/" + ORDER_ID + "/operations/op-1/report")
                        .contentType("application/json")
                        .content("{\"worker_name\":\"张三\",\"qty\":3,\"qualified_qty\":0,\"work_type\":\"scrap\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.status").value("pending"))
                .andExpect(jsonPath("$.data.order_completed").value(false));

        ArgumentCaptor<ProductionWorkLog> logCaptor = ArgumentCaptor.forClass(ProductionWorkLog.class);
        verify(workLogMapper).insert(logCaptor.capture());
        assertThat(logCaptor.getValue().getWorkType()).isEqualTo("scrap");
    }

    @Test
    @DisplayName("非法 work_type / qty<=0 → 422")
    void reportRejectsInvalidInput() throws Exception {
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order("producing"));
        when(processingOrderMapper.selectActiveByOrderId(ORDER_ID, TENANT)).thenReturn(processingOrder("tok123"));
        when(positionOperationMapper.selectById("op-1"))
                .thenReturn(op("op-1", 1, "精裁-布", "12.30", false, "pending", "0.00"));

        mockMvc.perform(post("/api/admin/production/orders/" + ORDER_ID + "/operations/op-1/report")
                        .contentType("application/json")
                        .content("{\"worker_name\":\"张三\",\"qty\":1,\"qualified_qty\":1,\"work_type\":\"unknown\"}"))
                .andExpect(status().isUnprocessableEntity());

        mockMvc.perform(post("/api/admin/production/orders/" + ORDER_ID + "/operations/op-1/report")
                        .contentType("application/json")
                        .content("{\"worker_name\":\"张三\",\"qty\":0,\"qualified_qty\":0,\"work_type\":\"normal\"}"))
                .andExpect(status().isUnprocessableEntity());
    }

    @Test
    @DisplayName("工序不属于该订单的加工单 → 404（防越单报工）")
    void reportRejectsOperationOfAnotherOrder() throws Exception {
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order("producing"));
        when(processingOrderMapper.selectActiveByOrderId(ORDER_ID, TENANT)).thenReturn(processingOrder("tok123"));
        ProcessingPositionOperation foreign = op("op-9", 1, "精裁-布", "1.00", false, "pending", "0.00");
        foreign.setProcessingOrderId("po-other");
        when(positionOperationMapper.selectById("op-9")).thenReturn(foreign);

        mockMvc.perform(post("/api/admin/production/orders/" + ORDER_ID + "/operations/op-9/report")
                        .contentType("application/json")
                        .content("{\"qty\":1,\"qualified_qty\":1,\"work_type\":\"normal\"}"))
                .andExpect(status().isNotFound());

        verify(workLogMapper, never()).insert(any(ProductionWorkLog.class));
    }

    // ── §5 防呆的 HTTP 层（issue #4116 P0-3）：请求头透传 / 越站已删（#4694，改判为放行）/ 超上限 422 / 软删 404 ──

    @Test
    @DisplayName("§5-1 幂等：X-Client-Request-Id 透传到服务层（不同指纹 ⇒ 服务层不被误报成重复）")
    void reportPassesClientRequestIdHeaderToService() throws Exception {
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order("producing"));
        when(processingOrderMapper.selectActiveByOrderId(ORDER_ID, TENANT)).thenReturn(processingOrder("tok123"));
        when(positionOperationMapper.selectById("op-1"))
                .thenReturn(op("op-1", 1, "精裁-布", "12.30", false, "pending", "0.00"));
        when(positionOperationMapper.selectList(any())).thenReturn(List.of());
        when(workLogMapper.insert(any(ProductionWorkLog.class))).thenReturn(1);

        mockMvc.perform(post("/api/admin/production/orders/" + ORDER_ID + "/operations/op-1/report")
                        .contentType("application/json")
                        .header(ClientRequestIdService.HEADER, "req-key-http-1")
                        .content("{\"worker_name\":\"张师傅\",\"qty\":1,\"qualified_qty\":1,\"work_type\":\"normal\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.done_qty").value(1.0));

        // 判据锚在**指纹**上：接线若丢头/写死键，claim 收到的就不是它（打桩不命中 ⇒ 走回放分支）
        verify(clientRequestIdService).claim(TENANT, "req-key-http-1", ProductionService.ENDPOINT_REPORT);
        verify(clientRequestIdService).complete(eq(TENANT), eq("req-key-http-1"), any());
    }

    @Test
    @DisplayName("§5-1 幂等：同键重复 ⇒ 回放首次结果并带 replayed=true（HTTP 层契约）")
    void reportReplaysForRepeatedClientRequestId() throws Exception {
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order("producing"));
        when(processingOrderMapper.selectActiveByOrderId(ORDER_ID, TENANT)).thenReturn(processingOrder("tok123"));
        Map<String, Object> snapshot = new java.util.LinkedHashMap<>();
        snapshot.put("operation_id", "op-1");
        snapshot.put("done_qty", new BigDecimal("4.00"));
        snapshot.put("status", "done");
        snapshot.put("order_completed", false);
        when(clientRequestIdService.claim(TENANT, "req-key-http-2", ProductionService.ENDPOINT_REPORT))
                .thenReturn(false);
        when(clientRequestIdService.replay(TENANT, "req-key-http-2", Map.class))
                .thenReturn(java.util.Optional.of(snapshot));

        mockMvc.perform(post("/api/admin/production/orders/" + ORDER_ID + "/operations/op-1/report")
                        .contentType("application/json")
                        .header(ClientRequestIdService.HEADER, "req-key-http-2")
                        .content("{\"worker_name\":\"张师傅\",\"qty\":4,\"qualified_qty\":4,\"work_type\":\"normal\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.done_qty").value(4.0))
                .andExpect(jsonPath("$.data.replayed").value(true));

        // 效果层：重复请求**没有**落明细、**没有**推进
        verify(workLogMapper, never()).insert(any(ProductionWorkLog.class));
        verify(positionOperationMapper, never())
                .advanceDoneQtyIfUnchanged(any(), any(), any(), any(), any(), any());
    }

    @Test
    @DisplayName("§5-2 越站闸门已删除（#4694 用户裁定）：前道未完成报后续工序 ⇒ 200 正常记账（不再 422）")
    void reportAllowedWhenPredecessorNotDone() throws Exception {
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order("producing"));
        when(processingOrderMapper.selectActiveByOrderId(ORDER_ID, TENANT)).thenReturn(processingOrder("tok123"));
        when(positionOperationMapper.selectById("op-2"))
                .thenReturn(op("op-2", 2, "布帘车被", "10.00", false, "pending", "0.00"));
        // 前道 seq=1「精裁-布」只报了 4/10（未完成）—— 改前这条夹具会让报工 422，改后必须放行
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(
                op("op-1", 1, "精裁-布", "10.00", false, "done", "4.00"),
                op("op-2", 2, "布帘车被", "10.00", false, "pending", "0.00")));
        when(workLogMapper.insert(any(ProductionWorkLog.class))).thenReturn(1);

        // 改钉（**≠ 放宽**）：期望从「422 + 尚未完成 + 请先报工完成」改成「200 + 推进」——
        // 判据对象不变（前道未完成时报后续工序），是用户裁定改了期望；其余断言强度不降。
        mockMvc.perform(post("/api/admin/production/orders/" + ORDER_ID + "/operations/op-2/report")
                        .contentType("application/json")
                        .content("{\"worker_name\":\"张师傅\",\"qty\":10,\"qualified_qty\":10,\"work_type\":\"normal\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.operation_id").value("op-2"))
                .andExpect(jsonPath("$.data.done_qty").value(10.0))
                .andExpect(jsonPath("$.data.status").value("done"));

        ArgumentCaptor<ProductionWorkLog> logCaptor = ArgumentCaptor.forClass(ProductionWorkLog.class);
        verify(workLogMapper).insert(logCaptor.capture());
        // 按**实际做的工序**记账，且计件金额按数量 × 报工那刻的单价快照
        assertThat(logCaptor.getValue().getOperationId()).isEqualTo("op-2");
        assertThat(logCaptor.getValue().getQualifiedQty()).isEqualByComparingTo("10.00");
    }

    @Test
    @DisplayName("§5-3 数量上限：超应做数量 ⇒ 422 + suggestion（不 clamp、不落明细）")
    void reportRejectedWhenExceedingPlannedQty() throws Exception {
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order("producing"));
        when(processingOrderMapper.selectActiveByOrderId(ORDER_ID, TENANT)).thenReturn(processingOrder("tok123"));
        when(positionOperationMapper.selectById("op-1"))
                .thenReturn(op("op-1", 1, "精裁-布", "10.00", false, "done", "9.00"));

        mockMvc.perform(post("/api/admin/production/orders/" + ORDER_ID + "/operations/op-1/report")
                        .contentType("application/json")
                        .content("{\"worker_name\":\"张师傅\",\"qty\":5,\"qualified_qty\":5,\"work_type\":\"normal\"}"))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.error.message", containsString("超上限")))
                .andExpect(jsonPath("$.suggestion", containsString("最多可报")));

        verify(workLogMapper, never()).insert(any(ProductionWorkLog.class));
        verify(positionOperationMapper, never())
                .advanceDoneQtyIfUnchanged(any(), any(), any(), any(), any(), any());
    }

    @Test
    @DisplayName("§5-4 非本部位：软删实例 ⇒ 404（不可报工到已废弃的工序实例）")
    void reportRejectedForDeletedOperation() throws Exception {
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order("producing"));
        when(processingOrderMapper.selectActiveByOrderId(ORDER_ID, TENANT)).thenReturn(processingOrder("tok123"));
        ProcessingPositionOperation gone = op("op-gone", 1, "精裁-布", "10.00", false, "pending", "0.00");
        gone.setDeleted(1);
        when(positionOperationMapper.selectById("op-gone")).thenReturn(gone);

        mockMvc.perform(post("/api/admin/production/orders/" + ORDER_ID + "/operations/op-gone/report")
                        .contentType("application/json")
                        .content("{\"worker_name\":\"张师傅\",\"qty\":1,\"qualified_qty\":1,\"work_type\":\"normal\"}"))
                .andExpect(status().isNotFound());

        verify(workLogMapper, never()).insert(any(ProductionWorkLog.class));
    }

    // ══════════════════════════ 工序库 / 工艺路线（只读消费者，issue #4116 P0-2）══════════════════════════

    @Test
    @DisplayName("工序库只读接口：GET /operations-catalog 按分组返回目录（真实整形，非桩）")
    void operationsCatalogReturnsGroups() throws Exception {
        when(productionOperationMapper.selectList(any())).thenReturn(List.of(
                operationRow("op-v54-01", "精裁-布", "裁剪", "米", "0.40", 1),
                operationRow("op-v54-07", "韩褶-布", "车位", "折", "0.40", 7)));

        mockMvc.perform(get("/api/admin/production/operations-catalog"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.total").value(2))
                .andExpect(jsonPath("$.data.groups[0].group").value("裁剪"))
                // issue #4642 判据改钉新真值（**不是放宽**）：读时归一 ⇒ 存量旧名行（库列仍是 `精裁-布`）
                // 的 `name` 返回**逻辑名**；库口径原名另走 `library_name`（web 不得渲染）。
                .andExpect(jsonPath("$.data.groups[0].operations[0].name").value("精裁"))
                .andExpect(jsonPath("$.data.groups[0].operations[0].library_name").value("精裁-布"))
                .andExpect(jsonPath("$.data.groups[1].group").value("车位"));
    }

    @Test
    @DisplayName("#4642 catalog 读时归一：存量旧名行（精裁-布）⇒ name 返回**逻辑名**（精裁）；"
            + "合法自定义名（测试22）归一后等于自身；逻辑名再归一不变（幂等）")
    void operationsCatalogNormalizesLegacyVariantNamesOnRead() throws Exception {
        when(productionOperationMapper.selectList(any())).thenReturn(List.of(
                operationRow("op-v54-01", "精裁-布", "裁剪", "米", "0.40", 1),
                operationRow("op-v54-02", "精裁", "裁剪", "米", "0.40", 2),
                operationRow("op-test22", "测试22", "其他", "米", "0.40", 3)));

        mockMvc.perform(get("/api/admin/production/operations-catalog"))
                .andExpect(status().isOk())
                // 存量旧名行 ⇒ 逻辑名（**读时**归一；库里那一列一字未动）
                .andExpect(jsonPath("$.data.groups[0].operations[0].name").value("精裁"))
                // 幂等：已经是逻辑名的行再归一不变
                .andExpect(jsonPath("$.data.groups[0].operations[1].name").value("精裁"))
                // 反向护栏：未登记的自定义名不得被改坏（归一后等于自身）
                .andExpect(jsonPath("$.data.groups[1].operations[0].name").value("测试22"))
                // 归一**只**动 name：同一行的库口径元数据一字不变
                .andExpect(jsonPath("$.data.groups[0].operations[0].unit_price").value(0.40))
                .andExpect(jsonPath("$.data.groups[0].operations[0].unit").value("米"))
                .andExpect(jsonPath("$.data.groups[0].operations[0].group").value("裁剪"));
    }

    @Test
    @DisplayName("工艺路线只读接口：GET /routings 返回路线 + 每道工序的库口径单价")
    void routingsReturnsTemplates() throws Exception {
        when(productionRouteTemplateMapper.selectList(any())).thenReturn(List.of(
                RoutingModelFixture.defaultTemplate(TENANT)));
        when(productionOperationMapper.selectList(any())).thenReturn(List.of(
                operationRow("op-v54-01", "精裁-布", "裁剪", "米", "0.40", 1),
                operationRow("op-v54-07", "韩褶-布", "车位", "折", "0.40", 7)));

        // P2b：路线形态 = 具名主线 + 适用帘种 + 默认标记（工艺不再参与选路）
        mockMvc.perform(get("/api/admin/production/routings"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.total").value(1))
                .andExpect(jsonPath("$.data.routings[0].name")
                        .value(RoutingModelFixture.TEMPLATE_NAME))
                .andExpect(jsonPath("$.data.routings[0].is_default").value(true))
                .andExpect(jsonPath("$.data.routings[0].mainline[0]").value("精裁"))
                .andExpect(jsonPath("$.data.routings[0].positions[0]").value("布帘"));
    }

    @Test
    @DisplayName("#4632 存量主线读时归一：库里存的是变体名（精裁-布）⇒ GET /routings 返回逻辑名（精裁）")
    void routingsNormalizeLegacyVariantNamesOnRead() throws Exception {
        // 存量形态：旧前端时代存进库的**变体名**（写面 #4618 只管住新写入的，管不住已有的）
        ProductionRouteTemplate legacy = RoutingModelFixture.defaultTemplate(TENANT);
        legacy.setMainline(List.of("精裁-布", "布三边", "测试22"));
        when(productionRouteTemplateMapper.selectList(any())).thenReturn(List.of(legacy));

        mockMvc.perform(get("/api/admin/production/routings"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.routings[0].mainline[0]").value("精裁"))
                .andExpect(jsonPath("$.data.routings[0].mainline[1]").value("三边"))
                // 自定义工序名归一后等于自身 ⇒ 原样返回（不得被抹成空或别的工序）
                .andExpect(jsonPath("$.data.routings[0].mainline[2]").value("测试22"));
    }

    // ══════════════════════════ 计件 ══════════════════════════

    @Test
    @DisplayName("计件 → Σ(合格数量×单价×系数)，排除返工/报废")
    void pieceworkExcludesReworkAndScrap() throws Exception {
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order("producing"));
        when(processingOrderMapper.selectActiveByOrderId(ORDER_ID, TENANT)).thenReturn(processingOrder("tok123"));
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(
                op("op-1", 1, "精裁-布", "12.30", false, "done", "10.00"),
                op("op-2", 2, "外帘装袋", "1.00", true, "done", "1.00")));
        when(workLogMapper.selectList(any())).thenReturn(List.of(
                log("op-1", "精裁-布", "张三", "10", "10", "normal"),
                log("op-1", "精裁-布", "李四", "3", "3", "rework"),
                log("op-2", "外帘装袋", "张三", "1", "1", "normal")));

        mockMvc.perform(get("/api/admin/production/orders/" + ORDER_ID + "/piecework"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.total").value(4.40))
                .andExpect(jsonPath("$.data.per_worker['张三']").value(4.40))
                .andExpect(jsonPath("$.data.per_worker['李四']").doesNotExist())
                .andExpect(jsonPath("$.data.per_operation[0].operation").value("精裁-布"))
                .andExpect(jsonPath("$.data.per_operation[0].amount").value(4.00));
    }

    @Test
    @DisplayName("类级 @RequirePermission(order:list) 护栏不可丢")
    void controllerDeclaresPermission() {
        RequirePermission ann = ProductionController.class.getAnnotation(RequirePermission.class);
        assertThat(ann).as("类级 @RequirePermission 缺失 = 权限护栏丢失").isNotNull();
        assertThat(ann.value()).isEqualTo("order:list");
    }

    @Test
    @DisplayName("扫工人二维码（路径参数=qr_token）→ 200 返回工序进度（issue #4005 断链修复）")
    void getOperationsByQrTokenPath() throws Exception {
        when(orderMapper.selectById("tok-abc")).thenReturn(null);
        when(orderMapper.selectOne(any())).thenReturn(null);                    // order_no 未命中
        when(processingOrderMapper.selectOne(any())).thenReturn(processingOrder("tok-abc"));
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order("producing"));
        when(processingOrderMapper.selectActiveByOrderId(ORDER_ID, TENANT)).thenReturn(processingOrder("tok-abc"));
        when(positionOperationMapper.selectList(any())).thenReturn(List.of());

        mockMvc.perform(get("/api/admin/production/orders/tok-abc/operations"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.order_id").value(ORDER_ID));
    }

    // ══════════════════ 存量加工单恢复路径（issue #4202）══════════════════
    //
    // 走查实测（2026-09-18，SHA d5bca241）：2026-09-17/15 生成的两张存量单工序实例与 qr_token 双空
    // （生成于 #4116「生成即实例化」之前），而 POST .../instantiate 当时要求完整 positions ⇒
    // 空 body 得 `422 positions 不能为空`，商家没有任何补工序路径。本段锁修复后的契约：
    // positions 缺省/空 ⇒ 服务端按订单派生（复用 ProcessingOrderService.buildPositionPayload 的
    // 工序库路线，不复制第二份解析逻辑）；已有实例仍是幂等空操作。

    /** 存量单的订单明细：加工项名「韩褶-布」= 部位(布帘)×工艺(韩褶) 双信号 ⇒ 派生键 布帘×韩褶。 */
    private OrderItem orderItemHanzhe() {
        Map<String, Object> info = new LinkedHashMap<>();
        info.put("colorName", "米白");
        info.put("sellingMethod", "散剪");
        info.put("processingItems", new ArrayList<>(List.of(
                Map.of("id", "p1", "name", "韩褶-布", "unit", "折"))));
        return OrderItem.builder()
                .id("item-1").tenantId(TENANT).orderId(ORDER_ID)
                .productName("布艺遮光帘A").quantity(new BigDecimal("2"))
                .processingInfo(info).build();
    }

    /**
     * V54 的 布帘×韩褶 路线（11 道）——**逐字抄自 V54__seed_production_operations.sql**
     * （rt-v54-01 的工序序列 + 对应工序行的分组/单位/单价/is_must_finish/is_start_marker）。
     * 列序：工序 / 分组 / 单位 / 单价 / is_must_finish / is_start_marker。
     */
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
            // 🔴 issue #4937 / O4：`打包` 跟着**主线**进路线（旧口径下它被 `applicable` 过滤挡住）
            {"打包", "后道", "套", "0.0", "false", "false"},
            {"外帘装袋", "后道", "套", "1.0", "true", "false"},
            {"外帘发货", "后道", "套", "1.0", "false", "false"}};

    /**
     * 工序库桩：把 V54 的「布帘×韩褶」路线与 12 道工序行装进真实
     * {@link ProductionOperationQueryService}（只 mock Mapper）⇒ 派生走的是**真解析**，
     * 不是被 stub 的 findRouting（否则「派生结果 = 库」的断言会退化成自证）。
     */
    private void stubV54BulianHanzheLibrary() {
        List<String> names = new ArrayList<>();
        List<ProductionOperation> rows = new ArrayList<>();
        int sort = 1;
        for (String[] step : V54_BULIAN_HANZHE) {
            names.add(step[0]);
            rows.add(ProductionOperation.builder()
                    .id("op-v54-" + String.format("%02d", sort)).tenantId(TENANT).name(step[0])
                    .groupName(step[1]).position("布帘").unit(step[2])
                    .unitPrice(new BigDecimal(step[3]))
                    .isMustFinish(Boolean.valueOf(step[4])).isStartMarker(Boolean.valueOf(step[5]))
                    .sortOrder(sort).status("active").deleted(0).build());
            sort++;
        }
        // P2b（issue #4459）：消费路径读**新结构** ⇒ 桩也要装新结构
        // （模板 + 规则 26 行 + 部位价目 + 工序库），展开由生产代码做。
        when(productionRouteTemplateMapper.selectList(any())).thenReturn(List.of(
                RoutingModelFixture.defaultTemplate(TENANT)));
        when(productionRouteRuleMapper.selectList(any())).thenReturn(
                RoutingModelFixture.rulesWithFactors(TENANT));
        when(productionOperationPositionMapper.selectList(any())).thenReturn(
                RoutingModelFixture.canonicalPositions(TENANT));
        when(productionCraftMapper.selectList(any())).thenReturn(List.of(
                RoutingModelFixture.defaultCraft(TENANT, "韩褶")));
        when(productionOperationMapper.selectList(any())).thenReturn(rows);
    }

    /** 派生结果的**期望形态**（与 findRouting 的返回同构），用于比对逐字段一致。 */
    @SuppressWarnings("unchecked")
    private static Map<String, Object> v54BulianHanzheRoute() {
        List<Map<String, Object>> operations = new ArrayList<>();
        int seq = 1;
        for (String[] step : V54_BULIAN_HANZHE) {
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
        route.put("curtain_type", "布帘");
        route.put("craft", "韩褶");
        route.put("operation_count", operations.size());
        route.put("missing_operations", List.of());
        route.put("operations", operations);
        return route;
    }

    /** 存量单**已有**的工序实例 —— 逐字等于派生结果（仅 done_qty 不同），用于幂等空操作断言。 */
    @SuppressWarnings("unchecked")
    private List<ProcessingPositionOperation> derivedInstances() {
        List<ProcessingPositionOperation> existing = new ArrayList<>();
        int seq = 1;
        for (Map<String, Object> step : (List<Map<String, Object>>) v54BulianHanzheRoute().get("operations")) {
            existing.add(ProcessingPositionOperation.builder()
                    .id("op-" + seq).tenantId(TENANT).processingOrderId(PO_ID)
                    .positionName("布艺遮光帘A 米白").seq(seq)
                    .operationName((String) step.get("operation"))
                    .groupName((String) step.get("group")).unit((String) step.get("unit"))
                    .qty(new BigDecimal("2")).unitPrice((BigDecimal) step.get("unit_price"))
                    .factor(BigDecimal.ONE).qtySource("fallback")
                    .isMustFinish((Boolean) step.get("is_must_finish"))
                    .isStartMarker((Boolean) step.get("is_start_marker"))
                    .status("pending").doneQty(BigDecimal.ZERO).deleted(0).build());
            seq++;
        }
        // 首道已报满（存量单的报工历史）—— 幂等路径**不得**清零它
        existing.get(0).setStatus("done");
        existing.get(0).setDoneQty(new BigDecimal("2"));
        return existing;
    }

    @Test
    @DisplayName("#4202 positions 缺省 ⇒ 服务端按订单派生工序（工序库路线）并逐字落库")
    void instantiateDerivesPositionsFromOrderWhenOmitted() throws Exception {
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order("completed"));   // 存量单：加工单已完工
        when(processingOrderMapper.selectActiveByOrderId(ORDER_ID, TENANT)).thenReturn(processingOrder(null));
        when(orderItemMapper.selectList(any())).thenReturn(List.of(orderItemHanzhe()));
        stubV54BulianHanzheLibrary();
        when(positionOperationMapper.selectList(any())).thenReturn(List.of());   // 存量单：工序实例为空
        when(positionOperationMapper.insert(any(ProcessingPositionOperation.class))).thenReturn(1);
        when(processingOrderMapper.updateById(any(ProcessingOrder.class))).thenReturn(1);

        mockMvc.perform(post("/api/admin/production/orders/" + ORDER_ID + "/instantiate")
                        .contentType("application/json").content("{}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.operation_count").value(12))
                .andExpect(jsonPath("$.data.qr_token").value(matchesPattern("[0-9a-f]{32}")));

        // 效果层：派生的 11 道工序逐字落库（部位/序号/工序名/应做数量/单价/必完标记）
        ArgumentCaptor<ProcessingPositionOperation> captor =
                ArgumentCaptor.forClass(ProcessingPositionOperation.class);
        verify(positionOperationMapper, times(12)).insert(captor.capture());
        List<ProcessingPositionOperation> inserted = captor.getAllValues();
        assertThat(inserted.get(0).getPositionName()).isEqualTo("布艺遮光帘A 米白");
        assertThat(inserted.get(0).getSeq()).isEqualTo(1);
        assertThat(inserted.get(0).getOperationName()).isEqualTo("精裁-布");
        assertThat(inserted.get(0).getUnitPrice()).isEqualByComparingTo("0.40");
        assertThat(inserted.get(0).getQty()).isEqualByComparingTo("2");
        // 🔴 issue #4937 / O4：`打包` 进路线后位次后移一位
        assertThat(inserted.get(11).getOperationName()).isEqualTo("外帘发货");
        // 🔴 #4961（必完概念退场）：实例**不再写** `is_must_finish`（列保留为历史载体）
        // —— 改前这里断言 `.isTrue()`（index 10 = 「外帘装袋」，库里唯一标了必完的工序）。
        assertThat(inserted.get(10).getIsMustFinish())
                .as("实例化不再写必完列（#4961）").isNull();
    }

    @Test
    @DisplayName("#4202 positions 空数组 ⇒ 与缺省同口径（派生），不再是 422")
    void instantiateDerivesPositionsWhenEmptyArrayGiven() throws Exception {
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order("completed"));
        when(processingOrderMapper.selectActiveByOrderId(ORDER_ID, TENANT)).thenReturn(processingOrder(null));
        when(orderItemMapper.selectList(any())).thenReturn(List.of(orderItemHanzhe()));
        stubV54BulianHanzheLibrary();
        when(positionOperationMapper.selectList(any())).thenReturn(List.of());
        when(positionOperationMapper.insert(any(ProcessingPositionOperation.class))).thenReturn(1);
        when(processingOrderMapper.updateById(any(ProcessingOrder.class))).thenReturn(1);

        mockMvc.perform(post("/api/admin/production/orders/" + ORDER_ID + "/instantiate")
                        .contentType("application/json").content("{\"positions\":[]}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.operation_count").value(12));

        verify(positionOperationMapper, times(12)).insert(any(ProcessingPositionOperation.class));
    }

    @Test
    @DisplayName("#4202 已有实例且与派生结果一致 ⇒ 幂等空操作（不重插行、不清零 done_qty、token 复用）")
    void instantiateDerivedIsIdempotentWhenInstancesAlreadyExist() throws Exception {
        String existingToken = "c".repeat(32);
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order("completed"));
        when(processingOrderMapper.selectActiveByOrderId(ORDER_ID, TENANT))
                .thenReturn(processingOrder(existingToken));
        when(orderItemMapper.selectList(any())).thenReturn(List.of(orderItemHanzhe()));
        stubV54BulianHanzheLibrary();
        when(positionOperationMapper.selectList(any())).thenReturn(derivedInstances());

        mockMvc.perform(post("/api/admin/production/orders/" + ORDER_ID + "/instantiate")
                        .contentType("application/json").content("{}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.qr_token").value(existingToken))
                .andExpect(jsonPath("$.data.operation_count").value(12));

        // 一行都不碰：不重插、不软删（软删走 update）、不清零报工进度
        verify(positionOperationMapper, never()).insert(any(ProcessingPositionOperation.class));
        verify(positionOperationMapper, never()).update(any(), any());
    }

    @Test
    @DisplayName("#4202 二维码撤销 ⇒ qr_token 置空；再次实例化重新生成（新码 ≠ 旧码）")
    void revokeQrTokenThenInstantiateRegeneratesToken() throws Exception {
        String oldToken = "d".repeat(32);
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order("producing"));
        when(processingOrderMapper.selectActiveByOrderId(ORDER_ID, TENANT)).thenReturn(processingOrder(oldToken));
        when(processingOrderMapper.revokeQrToken(eq(PO_ID), eq(TENANT), any())).thenReturn(1);

        mockMvc.perform(post("/api/admin/production/orders/" + ORDER_ID + "/qr-token/revoke"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.revoked").value(true))
                .andExpect(jsonPath("$.data.qr_token").value(nullValue()));

        // 效果层：撤销写的是 processing_orders.qr_token = NULL 的原子更新（不是「只调了个方法」）
        verify(processingOrderMapper).revokeQrToken(eq(PO_ID), eq(TENANT), any());

        // 撤销后再实例化 ⇒ 重新生成新码（旧码已失效，不得复用）
        when(processingOrderMapper.selectActiveByOrderId(ORDER_ID, TENANT)).thenReturn(processingOrder(null));
        when(orderItemMapper.selectList(any())).thenReturn(List.of(orderItemHanzhe()));
        stubV54BulianHanzheLibrary();
        when(positionOperationMapper.selectList(any())).thenReturn(derivedInstances());
        when(processingOrderMapper.updateById(any(ProcessingOrder.class))).thenReturn(1);

        String body = mockMvc.perform(post("/api/admin/production/orders/" + ORDER_ID + "/instantiate")
                        .contentType("application/json").content("{}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.qr_token").value(matchesPattern("[0-9a-f]{32}")))
                .andReturn().getResponse().getContentAsString();
        String regenerated = objectMapper.readTree(body).path("data").path("qr_token").asText();
        assertThat(regenerated).isNotEqualTo(oldToken);
    }

    @Test
    @DisplayName("#4202 打印任务卡 ⇒ print_count 原子递增（返回新计数，不是永不递增）")
    void printIncrementsPrintCount() throws Exception {
        ProcessingOrder po = processingOrder("tok-print");
        po.setPrintCount(2);
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order("producing"));
        // recordPrint 按加工单 id/加工单号/订单 id 解析（与 getDetail 同一口径）
        when(processingOrderMapper.selectOne(any())).thenReturn(po);
        when(processingOrderMapper.incrementPrintCount(eq(PO_ID), eq(TENANT), any())).thenReturn(1);
        ProcessingOrder afterPrint = processingOrder("tok-print");
        afterPrint.setPrintCount(3);
        when(processingOrderMapper.selectById(PO_ID)).thenReturn(afterPrint);

        mockMvc.perform(post("/api/admin/production/orders/" + ORDER_ID + "/print"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.processing_order_no").value("JG-20260917-0001"))
                .andExpect(jsonPath("$.data.print_count").value(3));

        verify(processingOrderMapper).incrementPrintCount(eq(PO_ID), eq(TENANT), any());
    }

    // ══════════════════ 工序库写面 + 单价版本化（issue #4204）══════════════════

    @Test
    @DisplayName("#4204 PUT /production/operations/{id} ⇒ 更新工序（返回更新后的工序，单价 = 新价）")
    void updateOperationWritesNewPrice() throws Exception {
        when(productionOperationMapper.selectById("op-1")).thenReturn(operationRow("op-1", "韩褶-布", "车位", "折", "0.40", 7));
        when(productionOperationMapper.updateById(any(ProductionOperation.class))).thenReturn(1);

        mockMvc.perform(put("/api/admin/production/operations/op-1")
                        .contentType("application/json").content("{\"unit_price\":0.55}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.id").value("op-1"))
                // issue #4642 判据改钉新真值（**不是放宽**）：写面响应与 catalog 读面共用 `operationView`，
                // `name` 已是**读时归一后的逻辑名**（库行 `韩褶-布` ⇒ `韩褶`）；库口径原名走 `library_name`。
                .andExpect(jsonPath("$.data.name").value("韩褶"))
                .andExpect(jsonPath("$.data.library_name").value("韩褶-布"))
                .andExpect(jsonPath("$.data.unit").value("折"))
                .andExpect(jsonPath("$.data.unit_price").value(0.55));

        ArgumentCaptor<ProductionOperation> captor = ArgumentCaptor.forClass(ProductionOperation.class);
        verify(productionOperationMapper).updateById(captor.capture());
        assertThat(captor.getValue().getId()).isEqualTo("op-1");
        assertThat(captor.getValue().getUnitPrice()).isEqualByComparingTo("0.55");

        // 单价版本账：改价必须在同一事务里追加一行版本（当前价 = 最新版本行，真值源 §4）
        ArgumentCaptor<ProductionOperationPriceVersion> version =
                ArgumentCaptor.forClass(ProductionOperationPriceVersion.class);
        verify(priceVersionMapper).insert(version.capture());
        assertThat(version.getValue().getOperationId()).isEqualTo("op-1");
        assertThat(version.getValue().getTenantId()).isEqualTo(TENANT);
        assertThat(version.getValue().getUnitPrice()).isEqualByComparingTo("0.55");

        // 改价**不得**碰工序实例：实例单价是生成时的快照，历史报工按当时价（真值源 §4）
        verify(positionOperationMapper, never()).insert(any(ProcessingPositionOperation.class));
        verify(positionOperationMapper, never()).update(any(), any());
    }

    @Test
    @DisplayName("#4204 同价重复提交 ⇒ 幂等空操作（不制造无意义的调价账）")
    void updateOperationWithSamePriceDoesNotAppendVersion() throws Exception {
        when(productionOperationMapper.selectById("op-1")).thenReturn(operationRow("op-1", "韩褶-布", "车位", "折", "0.40", 7));
        when(productionOperationMapper.updateById(any(ProductionOperation.class))).thenReturn(1);

        mockMvc.perform(put("/api/admin/production/operations/op-1")
                        .contentType("application/json").content("{\"unit_price\":0.40}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.unit_price").value(0.40));

        verify(priceVersionMapper, never()).insert(any(ProductionOperationPriceVersion.class));
    }

    @Test
    @DisplayName("#4204 工序不存在/跨租户 ⇒ 404（不静默改别人的工序）")
    void updateOperationUnknownIdNotFound() throws Exception {
        when(productionOperationMapper.selectById("op-x")).thenReturn(null);

        mockMvc.perform(put("/api/admin/production/operations/op-x")
                        .contentType("application/json").content("{\"unit_price\":0.55}"))
                .andExpect(status().isNotFound());

        verify(productionOperationMapper, never()).updateById(any(ProductionOperation.class));
        verify(priceVersionMapper, never()).insert(any(ProductionOperationPriceVersion.class));
    }

    @Test
    @DisplayName("#4204 单价为负/状态非法 ⇒ 422（写面校验，不落库）")
    void updateOperationRejectsInvalidValues() throws Exception {
        when(productionOperationMapper.selectById("op-1")).thenReturn(operationRow("op-1", "韩褶-布", "车位", "折", "0.40", 7));

        mockMvc.perform(put("/api/admin/production/operations/op-1")
                        .contentType("application/json").content("{\"unit_price\":-1}"))
                .andExpect(status().isUnprocessableEntity());
        mockMvc.perform(put("/api/admin/production/operations/op-1")
                        .contentType("application/json").content("{\"status\":\"deleted\"}"))
                .andExpect(status().isUnprocessableEntity());

        verify(productionOperationMapper, never()).updateById(any(ProductionOperation.class));
        verify(priceVersionMapper, never()).insert(any(ProductionOperationPriceVersion.class));
    }

    @Test
    @DisplayName("#4204 PUT /production/operations/{id} → 方法级 processing:manage 护栏（非 processing:manage ⇒ 403）")
    void updateOperationDeclaresManagePermission() throws Exception {
        Method update = ProductionController.class.getMethod("updateOperation", String.class, Map.class);
        RequirePermission ann = update.getAnnotation(RequirePermission.class);
        assertThat(ann).as("写面必须声明方法级权限（类级是 order:list，覆盖不了写操作）").isNotNull();
        assertThat(ann.value()).isEqualTo("processing:manage");

        Method revoke = ProductionController.class.getMethod("revokeQrToken", String.class);
        RequirePermission revokeAnn = revoke.getAnnotation(RequirePermission.class);
        assertThat(revokeAnn).as("二维码撤销是安全相关写操作（旧码立即失效）").isNotNull();
        assertThat(revokeAnn.value()).isEqualTo("processing:manage");

        Method summary = ProductionController.class.getMethod("pieceworkSummary", String.class, String.class);
        RequirePermission summaryAnn = summary.getAnnotation(RequirePermission.class);
        assertThat(summaryAnn).as("工资报表含全员金额，必须 processing:manage").isNotNull();
        assertThat(summaryAnn.value()).isEqualTo("processing:manage");

        // 打印计数**故意**沿用类级 order:list（打印按钮今天对客服/销售/财务可见，
        // 收到 processing:manage 会让「能看单却打不了卡」= 功能回退；计数只是打印动作的元数据）
        Method print = ProductionController.class.getMethod("printOrder", String.class);
        assertThat(print.getAnnotation(RequirePermission.class))
                .as("打印计数沿用类级 order:list（不新增方法级注解）").isNull();
    }

    // ══════════════════ 路线/信号/工序写面 + 缺口查询（issue #4308，PG-032~PG-035）══════════════════

    @Test
    @DisplayName("#4308 PUT /routings/{id} 护栏失败 ⇒ 422 + error.details 逐条理由（前端据此逐条展示）")
    void updateRoutingGuardFailureReturnsDetailsEnvelope() throws Exception {
        when(productionRouteTemplateMapper.selectById("rt-1")).thenReturn(
                ProductionRouteTemplate.builder().id("rt-1").tenantId(TENANT).name("路线甲")
                        .isDefault(false).positions(List.of("布帘")).mainline(List.of("布三边"))
                        .status("active").deleted(0).build());
        when(productionOperationMapper.selectList(any())).thenReturn(List.of(
                operationRow("op-1", "布三边", "车位", "米", "0.40", 2)));

        mockMvc.perform(put("/api/admin/production/routings/rt-1")
                        .contentType("application/json")
                        .content("{\"mainline\":[\"布三边\",\"库里没有的工序\"]}"))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.error.code").value("VALIDATION_ERROR"))
                .andExpect(jsonPath("$.error.details").isArray())
                .andExpect(jsonPath("$.error.details[0].field").value("mainline[1]"))
                .andExpect(jsonPath("$.suggestion").isNotEmpty());

        verify(productionRouteTemplateMapper, never()).updateById(any(ProductionRouteTemplate.class));
    }

    @Test
    @DisplayName("#4308 POST /routings 新建路线 ⇒ 200 且响应与 GET /routings 单项同构")
    void createRoutingReturnsRoutingView() throws Exception {
        when(productionRouteTemplateMapper.selectList(any())).thenReturn(List.of());
        when(productionOperationMapper.selectList(any())).thenReturn(List.of());

        mockMvc.perform(post("/api/admin/production/routings")
                        .contentType("application/json")
                        .content("{\"name\":\"罗马帘专用路线\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.name").value("罗马帘专用路线"))
                .andExpect(jsonPath("$.data.is_default").value(false))
                .andExpect(jsonPath("$.data.mainline").isArray())
                .andExpect(jsonPath("$.data.positions[0]").value("布帘"));
    }

    @Test
    @DisplayName("#4308 GET /route-signals ⇒ {total, signals:[{id,signal,curtain_type,craft,priority,status}]}")
    void routeSignalsListShape() throws Exception {
        when(productionRouteSignalMapper.selectList(any())).thenReturn(List.of(
                com.migao.admin.entity.ProductionRouteSignal.builder()
                        .id("sig-v60-01").tenantId(TENANT).signal("帘头").curtainType("帘头")
                        .priority(1).status("active").deleted(0).build()));

        mockMvc.perform(get("/api/admin/production/route-signals"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.total").value(1))
                .andExpect(jsonPath("$.data.signals[0].id").value("sig-v60-01"))
                .andExpect(jsonPath("$.data.signals[0].signal").value("帘头"))
                .andExpect(jsonPath("$.data.signals[0].curtain_type").value("帘头"))
                .andExpect(jsonPath("$.data.signals[0].craft").value(org.hamcrest.Matchers.nullValue()))
                .andExpect(jsonPath("$.data.signals[0].priority").value(1))
                .andExpect(jsonPath("$.data.signals[0].status").value("active"));
    }

    @Test
    @DisplayName("#4452 信号映射**写面已退役**：POST/PUT/DELETE /route-signals ⇒ 4xx（读面暂留）")
    void signalWriteEndpointsAreRetired() throws Exception {
        // 三个写面**没有 handler** ⇒ Spring 不路由（standalone MockMvc 下 `/route-signals` 只注册了 GET
        // ⇒ 非 GET 返回 **404 未注册 / 405 方法不允许**，视具体方法与路径深度而定；
        // 生产环境同形态：写面不可达）。
        // ⚠️ 判据是「**写面不可达**」，不是写死某个具体状态码 —— 404/405 都是「端点不存在」的合法表达。
        // 读面仍在（上一用例）：表降级为存量单兜底 ⇒ 读面留着排查历史单，写面退场。
        var notRegistered = org.hamcrest.Matchers.anyOf(
                org.hamcrest.Matchers.is(404), org.hamcrest.Matchers.is(405));
        mockMvc.perform(post("/api/admin/production/route-signals")
                        .contentType("application/json").content("{\"signal\":\"罗马帘\"}"))
                .andExpect(status().is(notRegistered));
        mockMvc.perform(put("/api/admin/production/route-signals/sig-1")
                        .contentType("application/json").content("{\"craft\":\"韩褶\"}"))
                .andExpect(status().is(notRegistered));
        mockMvc.perform(org.springframework.test.web.servlet.request.MockMvcRequestBuilders
                        .delete("/api/admin/production/route-signals/sig-1"))
                .andExpect(status().is(notRegistered));
    }

    @Test
    @DisplayName("#4452 异常订单清单：route_source ∈ {default, partial} 逐条可见 + 可行动文案")
    void routingAnomaliesListsDefaultAndPartialOrders() throws Exception {
        when(processingOrderMapper.selectList(any())).thenReturn(List.of(
                ProcessingOrder.builder().id("po-1").tenantId(TENANT).orderId("order-1")
                        .processingOrderNo("JG-20260919-0001")
                        .routeKey("窗帘工序路线（默认）").routeRequestedKey(null)
                        .routeSource("default").deleted(0).build(),
                ProcessingOrder.builder().id("po-2").tenantId(TENANT).orderId("order-2")
                        .processingOrderNo("JG-20260919-0002")
                        .routeKey("窗帘工序路线（默认）").routeRequestedKey("纱帘×韩褶")
                        .routeSource("partial").deleted(0).build()));

        mockMvc.perform(get("/api/admin/production/orders/routing-anomalies"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.total").value(2))
                .andExpect(jsonPath("$.data.orders[0].processing_order_no").value("JG-20260919-0001"))
                .andExpect(jsonPath("$.data.orders[0].route_key").value("窗帘工序路线（默认）"))
                .andExpect(jsonPath("$.data.orders[0].route_requested_key").value(nullValue()))
                .andExpect(jsonPath("$.data.orders[0].route_source").value("default"))
                .andExpect(jsonPath("$.data.orders[0].suggestion").value(containsString("部位")))
                .andExpect(jsonPath("$.data.orders[1].route_source").value("partial"))
                .andExpect(jsonPath("$.data.orders[1].route_requested_key").value("纱帘×韩褶"))
                .andExpect(jsonPath("$.data.orders[1].suggestion").value(containsString("缺的那一维")));
    }

    @Test
    @DisplayName("#4308 POST /operations ⇒ 200 + 单价版本账首行（商家建路线的前置）")
    void createOperationReturnsCatalogShape() throws Exception {
        when(productionOperationMapper.selectCount(any())).thenReturn(0L);

        mockMvc.perform(post("/api/admin/production/operations")
                        .contentType("application/json")
                        .content("{\"name\":\"罗马帘穿杆\",\"group_name\":\"车位\",\"unit\":\"米\",\"unit_price\":0.6}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.name").value("罗马帘穿杆"))
                .andExpect(jsonPath("$.data.group").value("车位"))
                .andExpect(jsonPath("$.data.unit_price").value(0.6));

        verify(priceVersionMapper).insert(any(ProductionOperationPriceVersion.class));
    }

    @Test
    @DisplayName("#4642 POST /operations 命中旧形态工序名（布三边）⇒ **422 + error.details 逐条**，不落库"
            + "（红证：改前 200 且落库/回显 `布三边`，且矩阵行被归一成 `三边` ⇒ 同一道工序两名并存）")
    void createOperationRejectsLegacyVariantName() throws Exception {
        when(productionOperationMapper.selectCount(any())).thenReturn(0L);
        when(productionOperationPositionMapper.selectList(any())).thenReturn(List.of());

        mockMvc.perform(post("/api/admin/production/operations")
                        .contentType("application/json")
                        .content("{\"name\":\"布三边\",\"unit_price\":0.6,\"positions\":[\"布帘\"]}"))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.error.details[0].field").value("name"))
                .andExpect(jsonPath("$.error.details[0].message").value(containsString("部位")));

        // 校验先于写入：工序库行与矩阵行都不许落
        verify(productionOperationMapper, never()).insert(any(ProductionOperation.class));
        verify(productionOperationPositionMapper, never()).insert(any(ProductionOperationPosition.class));
    }

    @Test
    @DisplayName("#4642 反向护栏：合法自定义名（测试22 / 罗马帘穿杆）**照常可建**（判据不得误伤）")
    void createOperationAcceptsLegitimateCustomNames() throws Exception {
        when(productionOperationMapper.selectCount(any())).thenReturn(0L);

        for (String custom : List.of("测试22", "罗马帘穿杆")) {
            mockMvc.perform(post("/api/admin/production/operations")
                            .contentType("application/json")
                            .content("{\"name\":\"" + custom + "\",\"unit_price\":0.6}"))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.data.name").value(custom));
        }
    }

    @Test
    @DisplayName("#4614 POST /operations 带 positions ⇒ 同一事务建矩阵行 + 响应如实报数（建完必须可见）")
    void createOperationWithPositionsBuildsMatrixRows() throws Exception {
        when(productionOperationMapper.selectCount(any())).thenReturn(0L);
        when(productionOperationPositionMapper.selectList(any())).thenReturn(List.of());

        mockMvc.perform(post("/api/admin/production/operations")
                        .contentType("application/json")
                        .content("{\"name\":\"测试22\",\"unit_price\":0.6,\"positions\":[\"布帘\",\"纱帘\"]}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.name").value("测试22"))
                .andExpect(jsonPath("$.data.created_positions").value(2))
                .andExpect(jsonPath("$.data.skipped_positions").value(0));

        ArgumentCaptor<ProductionOperationPosition> rows =
                ArgumentCaptor.forClass(ProductionOperationPosition.class);
        verify(productionOperationPositionMapper, times(2)).insert(rows.capture());
        assertThat(rows.getAllValues()).extracting(ProductionOperationPosition::getLogicalName)
                .as("矩阵行必须落在**逻辑名**上（前端「工艺项」表按它成行）—— 自定义名归一后等于自身。"
                        + "⚠️ issue #4642 起旧形态名（`布帘车被`）在建之前就被拒 ⇒ 本用例输入即逻辑名")
                .containsOnly("测试22");
    }

    /**
     * issue #4665 A：`DELETE /operations/{id}/detach-and-delete` —— 一键「设为不做并删除」
     * 的**原子**落点：后端**一次事务**里先把受影响的矩阵格设为不做，再软删工序 + 级联软删矩阵行。
     *
     * <p>红证（改前）：该端点不存在 ⇒ 404；矩阵格那一条护栏照旧 422（商家只能手工两步）。</p>
     */
    @Test
    @DisplayName("#4665 DELETE /operations/{id}/detach-and-delete ⇒ 一次事务摘格 + 级联 + 删除（200）")
    void deleteOperationDetachesPositionsThenDeletes() throws Exception {
        when(productionOperationMapper.selectById("op-1"))
                .thenReturn(operationRow("op-1", "布三边", "车位", "米", "0.40", 1));
        when(productionOperationMapper.selectList(any())).thenReturn(List.of(
                operationRow("op-1", "布三边", "车位", "米", "0.40", 1)));
        when(productionRouteTemplateMapper.selectList(any())).thenReturn(List.of());
        when(productionRouteRuleMapper.selectList(any())).thenReturn(List.of());
        ProductionOperationPosition cell = ProductionOperationPosition.builder()
                .id("opp-三边-布帘").tenantId(TENANT).logicalName("三边").position("布帘")
                .unitPrice(new BigDecimal("0.40")).applicable(true).status("active").deleted(0).build();
        when(productionOperationPositionMapper.selectList(any())).thenReturn(List.of(cell));
        when(productionOperationPositionMapper.updatePriceAndApplicable(
                any(), any(), any(), any(), any())).thenReturn(1);
        when(productionOperationPositionMapper.softDelete(any(), any(), any())).thenReturn(1);
        when(productionOperationMapper.update(isNull(), any())).thenReturn(1);

        mockMvc.perform(delete("/api/admin/production/operations/op-1/detach-and-delete"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.deleted").value(true))
                .andExpect(jsonPath("$.data.detached_positions").value(1))
                .andExpect(jsonPath("$.data.deleted_positions").value(1));

        // 摘格、级联软删、工序软删**都在**（不是只摘格 / 只删）
        verify(productionOperationPositionMapper).updatePriceAndApplicable(
                eq("opp-三边-布帘"), eq(TENANT), isNull(), eq(false), any());
        verify(productionOperationPositionMapper).softDelete(eq("opp-三边-布帘"), eq(TENANT), any());
        verify(productionOperationMapper).update(isNull(), any());
    }

    /**
     * issue #4665 C：删除要**删干净** —— 工序软删的**同一事务**里级联软删它引用的矩阵行，
     * 否则读面（只看 {@code deleted=0}）照旧返回那一行 ⇒ 工艺项表格里那一行还在
     * （用户实测「依然删不干净」）。响应如实报数 {@code deleted_positions}。
     */
    @Test
    @DisplayName("#4665 C DELETE ⇒ 同一事务级联软删矩阵行 + 响应如实报数（deleted_positions）")
    void deleteOperationCascadesSoftDeleteToMatrixRows() throws Exception {
        when(productionOperationMapper.selectById("op-1"))
                .thenReturn(operationRow("op-1", "布三边", "车位", "米", "0.40", 1));
        when(productionOperationMapper.selectList(any())).thenReturn(List.of(
                operationRow("op-1", "布三边", "车位", "米", "0.40", 1)));
        when(productionRouteTemplateMapper.selectList(any())).thenReturn(List.of());
        when(productionRouteRuleMapper.selectList(any())).thenReturn(List.of());
        when(productionOperationPositionMapper.selectList(any())).thenReturn(List.of(
                ProductionOperationPosition.builder()
                        .id("opp-三边-布帘").tenantId(TENANT).logicalName("三边").position("布帘")
                        .unitPrice(new BigDecimal("0.40")).applicable(false).status("active").deleted(0)
                        .build()));
        when(productionOperationPositionMapper.softDelete(any(), any(), any())).thenReturn(1);
        when(productionOperationMapper.update(isNull(), any())).thenReturn(1);

        mockMvc.perform(delete("/api/admin/production/operations/op-1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.deleted").value(true))
                .andExpect(jsonPath("$.data.deleted_positions").value(1));

        // 级联软删走**显式写列**的 `softDelete`（#4608：`updateById` 会被 MP 剔除该字段 ⇒ 静默 no-op）
        verify(productionOperationPositionMapper).softDelete(eq("opp-三边-布帘"), eq(TENANT), any());
        verify(productionOperationPositionMapper, never())
                .updateById(any(ProductionOperationPosition.class));
        // 工序行本身也软删（显式写列）
        verify(productionOperationMapper).update(isNull(), any());
    }

    /**
     * issue #4665 C **一次事务**：矩阵行软删失败 ⇒ fail-closed（工序行**不得**被写）。
     *
     * <p>单测层能断言的是「抛 422 + 不写工序行」；真正的回滚由 {@code @Transactional} 保证
     * （半完成态 = 工序删了、行还在 = 用户实测的「删不干净」）。</p>
     */
    @Test
    @DisplayName("#4665 C 一次事务：矩阵行软删失败 ⇒ 422 且工序行不写（不留半完成态）")
    void deleteOperationFailsClosedWhenCascadeFails() throws Exception {
        when(productionOperationMapper.selectById("op-1"))
                .thenReturn(operationRow("op-1", "布三边", "车位", "米", "0.40", 1));
        when(productionOperationMapper.selectList(any())).thenReturn(List.of(
                operationRow("op-1", "布三边", "车位", "米", "0.40", 1)));
        when(productionRouteTemplateMapper.selectList(any())).thenReturn(List.of());
        when(productionRouteRuleMapper.selectList(any())).thenReturn(List.of());
        when(productionOperationPositionMapper.selectList(any())).thenReturn(List.of(
                ProductionOperationPosition.builder()
                        .id("opp-三边-布帘").tenantId(TENANT).logicalName("三边").position("布帘")
                        .unitPrice(new BigDecimal("0.40")).applicable(false).status("active").deleted(0)
                        .build()));
        // 0 = 行不存在 / 非本租户 / 已软删 ⇒ 必须 fail-closed
        when(productionOperationPositionMapper.softDelete(any(), any(), any())).thenReturn(0);

        mockMvc.perform(delete("/api/admin/production/operations/op-1"))
                .andExpect(status().isUnprocessableEntity());

        verify(productionOperationMapper, never()).update(isNull(), any());
    }

    /**
     * 反向护栏（issue #4665 明确要求）：主线命中时，一键端点
     * **也必须被拦**（主线涉及车间顺序，必须人工确认），且**一格都不许被摘**。
     */
    @Test
    @DisplayName("#4665 反向护栏：主线命中 ⇒ 一键端点 **也被拦**（422，一格不摘）")
    void deleteOperationWithDetachStillRejectsMainlineReference() throws Exception {
        when(productionOperationMapper.selectById("op-1"))
                .thenReturn(operationRow("op-1", "布三边", "车位", "米", "0.40", 1));
        when(productionOperationMapper.selectList(any())).thenReturn(List.of(
                operationRow("op-1", "布三边", "车位", "米", "0.40", 1)));
        ProductionRouteTemplate template = ProductionRouteTemplate.builder()
                .id("rt-1").tenantId(TENANT).name("窗帘工序路线（默认）").isDefault(true)
                .positions(List.of("布帘", "帘头")).mainline(List.of("精裁", "三边"))
                .status("active").deleted(0).build();
        when(productionRouteTemplateMapper.selectList(any())).thenReturn(List.of(template));
        when(productionRouteRuleMapper.selectList(any())).thenReturn(List.of());
        when(productionOperationPositionMapper.selectList(any())).thenReturn(List.of(
                ProductionOperationPosition.builder()
                        .id("opp-三边-布帘").tenantId(TENANT).logicalName("三边").position("布帘")
                        .unitPrice(new BigDecimal("0.40")).applicable(true).status("active").deleted(0)
                        .build()));

        mockMvc.perform(delete("/api/admin/production/operations/op-1/detach-and-delete"))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.error.details[0].field").value("routing"))
                .andExpect(jsonPath("$.error.details[0].message").value(
                        containsString("先改主线")));

        // 拦下 ⇒ 无副作用（既不摘格、也不级联软删、也不删工序）
        verify(productionOperationPositionMapper, never())
                .updatePriceAndApplicable(any(), any(), any(), any(), any());
        verify(productionOperationPositionMapper, never()).softDelete(any(), any(), any());
        verify(productionOperationMapper, never()).update(isNull(), any());
    }

    @Test
    @DisplayName("#4614 POST /operations 未知部位 ⇒ 422 + error.details 逐条（前端据此逐条展示）")
    void createOperationRejectsUnknownPosition() throws Exception {
        when(productionOperationMapper.selectCount(any())).thenReturn(0L);
        when(productionOperationPositionMapper.selectList(any())).thenReturn(List.of());

        mockMvc.perform(post("/api/admin/production/operations")
                        .contentType("application/json")
                        .content("{\"name\":\"罗马帘穿杆\",\"unit_price\":0.6,\"positions\":[\"布帘\",\"布廉\"]}"))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.error.details").isArray())
                .andExpect(jsonPath("$.error.details.length()").value(1))
                .andExpect(jsonPath("$.error.details[0].field").value("positions"))
                .andExpect(jsonPath("$.error.details[0].message").value(containsString("布廉")));

        verify(productionOperationPositionMapper, never()).insert(any(ProductionOperationPosition.class));
    }

    @Test
    @DisplayName("#4614 PUT /operations/{id} 带 positions ⇒ 存量孤儿接入（只补缺失行 + 如实报数）")
    void updateOperationAttachesPositionsForOrphan() throws Exception {
        when(productionOperationMapper.selectById("op-orphan")).thenReturn(
                operationRow("op-orphan", "测试22", "其他", "米", "0.50", 22));
        when(productionOperationMapper.updateById(any(ProductionOperation.class))).thenReturn(1);
        when(productionOperationPositionMapper.selectList(any())).thenReturn(List.of());

        mockMvc.perform(put("/api/admin/production/operations/op-orphan")
                        .contentType("application/json")
                        .content("{\"positions\":[\"布帘\",\"纱帘\"]}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.name").value("测试22"))
                .andExpect(jsonPath("$.data.created_positions").value(2))
                .andExpect(jsonPath("$.data.skipped_positions").value(0));

        ArgumentCaptor<ProductionOperationPosition> rows =
                ArgumentCaptor.forClass(ProductionOperationPosition.class);
        verify(productionOperationPositionMapper, times(2)).insert(rows.capture());
        assertThat(rows.getAllValues()).extracting(ProductionOperationPosition::getLogicalName)
                .as("矩阵行落在逻辑名上（「测试22」不在归一表里 ⇒ 原样返回，不猜）")
                .containsOnly("测试22");
    }

    @Test
    @DisplayName("#4308 GET /routing-gaps ⇒ 两只清单 + 待确认标记（缺口不得只活在注释里）")
    void routingGapsShape() throws Exception {
        when(productionRoutingMapper.selectList(any())).thenReturn(List.of());
        when(productionOperationMapper.selectList(any())).thenReturn(List.of(
                operationRow("op-26", "质检", "后道", "套", "1.50", 26)));
        when(productionRouteSignalMapper.selectList(any())).thenReturn(List.of());

        mockMvc.perform(get("/api/admin/production/routing-gaps"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.unrouted_operations[0].name").value("质检"))
                .andExpect(jsonPath("$.data.unrouted_operations[0].group_name").value("后道"))
                .andExpect(jsonPath("$.data.unrouted_operations[0].unit_price").value(1.50))
                .andExpect(jsonPath("$.data.unrouted_operations[0].pending_confirmation")
                        .value(true))
                .andExpect(jsonPath("$.data.pending_confirmation_total").value(1))
                .andExpect(jsonPath("$.data.signal_keys_without_route").isArray());
    }

    @Test
    @DisplayName("#4642 routing-gaps 同族归一：unrouted_operations[].name 对存量旧名行返回**逻辑名**")
    void routingGapsNormalizesLegacyVariantNamesOnRead() throws Exception {
        when(productionRoutingMapper.selectList(any())).thenReturn(List.of());
        // 「精裁-布」的逻辑名是「精裁」，没有任何活跃主线消费它 ⇒ 它是缺口；名字必须是逻辑名。
        when(productionOperationMapper.selectList(any())).thenReturn(List.of(
                operationRow("op-v54-01", "精裁-布", "裁剪", "米", "0.40", 1),
                operationRow("op-test22", "测试22", "其他", "米", "0.40", 2)));
        when(productionRouteSignalMapper.selectList(any())).thenReturn(List.of());

        mockMvc.perform(get("/api/admin/production/routing-gaps"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.unrouted_operations[0].name").value("精裁"))
                // 反向护栏：自定义名归一后等于自身
                .andExpect(jsonPath("$.data.unrouted_operations[1].name").value("测试22"));
    }

    @Test
    @DisplayName("#4308/#4452 写端点全部声明方法级 processing:manage（不新造权限码）；信号写面已退役")
    void routingWriteFaceDeclaresManagePermission() throws Exception {
        assertManagePermission("createRouting", Map.class);
        assertManagePermission("updateRouting", String.class, Map.class);
        assertManagePermission("createOperation", Map.class);
        assertManagePermission("routingAnomalies");
        // 信号映射写面**已退役**（issue #4452）⇒ 三个 handler 不得再存在
        // （存在即意味着写面还有入口，与「表降级为存量单兜底」自相矛盾）。
        for (String retired : List.of("createRouteSignal", "updateRouteSignal", "deleteRouteSignal")) {
            assertThat(java.util.Arrays.stream(ProductionController.class.getDeclaredMethods())
                    .map(Method::getName))
                    .as("信号映射写面已退役（issue #4452）：%s 不得再存在", retired)
                    .doesNotContain(retired);
        }
    }

    private void assertManagePermission(String method, Class<?>... params) throws Exception {
        Method m = ProductionController.class.getMethod(method, params);
        RequirePermission ann = m.getAnnotation(RequirePermission.class);
        assertThat(ann).as("%s 必须声明方法级权限（类级 order:list 覆盖不了写操作）", method).isNotNull();
        assertThat(ann.value()).as("%s 的权限码", method).isEqualTo("processing:manage");
    }

    private ProductionOperation operationRow(String id, String name, String group, String unit,
                                             String unitPrice, int sortOrder) {
        return ProductionOperation.builder()
                .id(id).tenantId(TENANT).name(name).groupName(group).position("布帘")
                .unit(unit).unitPrice(new BigDecimal(unitPrice))
                .isMustFinish(false).isStartMarker(false).sortOrder(sortOrder).status("active").deleted(0)
                .build();
    }

    // ══════════════════ 计件工资报表（issue #4205）══════════════════

    @Test
    @DisplayName("#4205 GET /piecework/summary ⇒ 按人/按工序聚合，且与 per-order 合计口径一致")
    void pieceworkSummaryMatchesPerOrderTotals() throws Exception {
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order("producing"));
        when(processingOrderMapper.selectActiveByOrderId(ORDER_ID, TENANT)).thenReturn(processingOrder("tok123"));
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(
                op("op-1", 1, "精裁-布", "12.30", false, "done", "10.00"),
                op("op-2", 2, "外帘装袋", "1.00", true, "done", "1.00")));
        when(workLogMapper.selectList(any())).thenReturn(List.of(
                log("op-1", "精裁-布", "张三", "10", "10", "normal"),
                log("op-1", "精裁-布", "李四", "3", "3", "rework"),
                log("op-2", "外帘装袋", "张三", "1", "1", "normal")));

        // ① per-order 合计（既有端点，作为口径真值）
        String perOrderBody = mockMvc.perform(
                        get("/api/admin/production/orders/" + ORDER_ID + "/piecework"))
                .andExpect(status().isOk())
                .andReturn().getResponse().getContentAsString();
        java.math.BigDecimal perOrderTotal =
                new java.math.BigDecimal(objectMapper.readTree(perOrderBody).path("data").path("total").asText());

        // ② 报表：同一批报工 ⇒ 按人/按工序两级
        String reportBody = mockMvc.perform(get("/api/admin/production/piecework/summary")
                        .param("period", "2026-09"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.period").value("2026-09"))
                .andExpect(jsonPath("$.data.per_worker[0].worker_name").value("张三"))
                .andExpect(jsonPath("$.data.per_worker[0].amount").value(4.40))
                .andExpect(jsonPath("$.data.per_worker[0].qty").value(11))
                .andExpect(jsonPath("$.data.per_worker[1]").doesNotExist())   // 返工不计件 ⇒ 李四不进报表
                .andExpect(jsonPath("$.data.per_operation[0].operation").value("精裁-布"))
                .andExpect(jsonPath("$.data.per_operation[0].amount").value(4.00))
                .andExpect(jsonPath("$.data.per_operation[0].qty").value(10))
                .andReturn().getResponse().getContentAsString();

        // ③ 口径一致性（红证判据）：两套端点对同一批报工必须给出同一总额 —— 防两份算法漂移
        java.math.BigDecimal reportTotal =
                new java.math.BigDecimal(objectMapper.readTree(reportBody).path("data").path("total").asText());
        assertThat(reportTotal).isEqualByComparingTo(perOrderTotal);
    }

    @Test
    @DisplayName("#4205 period 必填且必须是 YYYY-MM（缺失/非法 ⇒ 422，不静默返回空报表）")
    void pieceworkSummaryRejectsBadPeriod() throws Exception {
        mockMvc.perform(get("/api/admin/production/piecework/summary"))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.success").value(false));
        mockMvc.perform(get("/api/admin/production/piecework/summary").param("period", "2026-9"))
                .andExpect(status().isUnprocessableEntity());
    }

    @Test
    @DisplayName("#4205 报表按 work_date 落在 period 内过滤（边界含首末）+ 可再按 worker_name 过滤")
    void pieceworkSummaryFiltersByPeriodAndWorker() throws Exception {
        when(workLogMapper.selectList(any())).thenReturn(List.of());

        mockMvc.perform(get("/api/admin/production/piecework/summary")
                        .param("period", "2026-09").param("worker_name", "张三"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.total").value(0.00));

        ArgumentCaptor<com.baomidou.mybatisplus.core.conditions.query.QueryWrapper<ProductionWorkLog>> captor =
                ArgumentCaptor.forClass(com.baomidou.mybatisplus.core.conditions.query.QueryWrapper.class);
        verify(workLogMapper).selectList(captor.capture());
        String sql = captor.getValue().getSqlSegment();
        assertThat(sql).as("period 边界压在 SQL 里（当期首末，含端点）").contains("work_date");
        assertThat(captor.getValue().getParamNameValuePairs().values())
                .as("期间边界取当月首末（含端点）—— 日期是绑定参数，不在 SQL 文本里")
                .contains(LocalDate.of(2026, 9, 1), LocalDate.of(2026, 9, 30));
        assertThat(sql).as("worker_name 是可选下钻维度").contains("worker_name");
    }

    // ══════════════════ 加工费组合定价 + 缺口（issue #4386，PG-040）══════════════════

    /**
     * 判据 3 的**信封层**红证：护栏失败必须是 HTTP 422 + {@code error.details[].message} **逐条**。
     *
     * <p>为什么必须在这一层验：服务层单测只能证明 {@code BusinessException.details} 有值 ——
     * 而「前端能不能读到」取决于 {@code GlobalExceptionHandler} 有没有把它透传进响应体。
     * #4308 的假绿教训：前端曾按**不存在的** {@code error.error_messages} 读 ⇒ 真实失败路径
     * 静默退化成「Request failed with status code 422」（集成方探针 2/2 红）。</p>
     */
    @Test
    @DisplayName("#4386 POST /processing-fee-combinations 护栏失败 ⇒ 422 + error.details 逐条理由")
    void createProcessingFeeCombinationGuardFailureReturnsDetailsEnvelope() throws Exception {
        when(processingItemMapper.selectList(any())).thenReturn(List.of(
                ProcessingItem.builder().id("pi-1").tenantId(TENANT).name("韩褶")
                        .categoryId("cat-1").unit("米").status("active").deleted(0).build()));

        mockMvc.perform(post("/api/admin/production/processing-fee-combinations")
                        .contentType("application/json")
                        .content("{\"items\":[\"韩褶\",\"库里没有的加工项\"],\"unit_price\":\"-1\"}"))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.error.code").value("VALIDATION_ERROR"))
                .andExpect(jsonPath("$.error.details").isArray())
                .andExpect(jsonPath("$.error.details.length()").value(2))
                .andExpect(jsonPath("$.error.details[0].field").value("items[1]"))
                .andExpect(jsonPath("$.error.details[0].message").isNotEmpty())
                .andExpect(jsonPath("$.error.details[1].field").value("unit_price"))
                .andExpect(jsonPath("$.suggestion").isNotEmpty());

        verify(processingFeeCombinationMapper, never()).insert(any(ProcessingFeeCombination.class));
    }

    /** 判据 1 的信封层红证：同一组合重复定价 = **409**（不是 422、更不是 500）。 */
    @Test
    @DisplayName("#4386 同一 composition_key 重复定价 ⇒ 409 + 可行动 suggestion")
    void createProcessingFeeCombinationDuplicateReturnsConflict() throws Exception {
        when(processingItemMapper.selectList(any())).thenReturn(List.of(
                ProcessingItem.builder().id("pi-1").tenantId(TENANT).name("韩褶")
                        .categoryId("cat-1").unit("米").status("active").deleted(0).build()));
        when(processingFeeCombinationMapper.selectList(any())).thenReturn(List.of(
                ProcessingFeeCombination.builder().id("c1").tenantId(TENANT)
                        .compositionKey("韩褶").unitPrice(new BigDecimal("12"))
                        .status("active").sortOrder(0).deleted(0).build()));

        mockMvc.perform(post("/api/admin/production/processing-fee-combinations")
                        .contentType("application/json")
                        .content("{\"items\":[\"韩褶\"],\"unit_price\":\"15\"}"))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.error.code").value("CONFLICT"))
                .andExpect(jsonPath("$.suggestion").isNotEmpty());

        verify(processingFeeCombinationMapper, never()).insert(any(ProcessingFeeCombination.class));
    }

    /** 判据 4 的信封层红证：缺口端点真的注册了、且形状是清单而非 404。 */
    @Test
    @DisplayName("#4386 GET /processing-fee-gaps ⇒ 未定价组合清单（不是 404）")
    void processingFeeGapsEndpointIsRegistered() throws Exception {
        when(processingFeeCombinationMapper.selectList(any())).thenReturn(List.of());
        when(orderItemMapper.selectList(any())).thenReturn(List.of());

        mockMvc.perform(get("/api/admin/production/processing-fee-gaps"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.unpriced_combinations").isArray())
                .andExpect(jsonPath("$.data.unpriced_combination_total").value(0));
    }

    /** 写端点权限口径：三个写端点全部方法级 {@code processing:manage}（与 #4308 同口径）。 */
    @Test
    @DisplayName("#4386 加工费组合写端点权限 = 方法级 processing:manage")
    void processingFeeWriteEndpointsRequireProcessingManage() throws Exception {
        Method create = ProductionController.class.getMethod(
                "createProcessingFeeCombination", Map.class);
        Method update = ProductionController.class.getMethod(
                "updateProcessingFeeCombination", String.class, Map.class);
        Method disable = ProductionController.class.getMethod(
                "disableProcessingFeeCombination", String.class);

        for (Method method : List.of(create, update, disable)) {
            RequirePermission annotation = method.getAnnotation(RequirePermission.class);
            assertThat(annotation).as("%s 必须声明方法级权限", method.getName()).isNotNull();
            assertThat(annotation.value()).isEqualTo("processing:manage");
        }
    }

    // ══════════════════ 未定价实例的显式补价路径（issue #4709 C）══════════════════

    /** 一道**未定价**工序实例（{@code unit_price = null} + 帘种，供矩阵格查价）。 */
    private ProcessingPositionOperation unpricedOp(String id, int seq, String name, String positionKind) {
        return ProcessingPositionOperation.builder()
                .id(id).tenantId(TENANT).processingOrderId(PO_ID)
                .positionName("遮光布料X").positionKind(positionKind).seq(seq)
                .operationName(name).groupName("后道").unit("米")
                .qty(new BigDecimal("10.00")).unitPrice(null).factor(new BigDecimal("1.00"))
                .isMustFinish(false).isStartMarker(false)
                .status("pending").doneQty(BigDecimal.ZERO).deleted(0)
                .build();
    }

    /** 部位价目矩阵格（{@code price = null} = 未定价）。 */
    private ProductionOperationPosition priceCell(String logicalName, String position, String price) {
        return ProductionOperationPosition.builder()
                .id("cell-" + position + "-" + logicalName).tenantId(TENANT)
                .logicalName(logicalName).position(position)
                .unitPrice(price == null ? null : new BigDecimal(price))
                .applicable(true).status("active").deleted(0)
                .build();
    }

    /** 红证（改前）：端点不存在 ⇒ 本用例得 `Status expected:<200> but was:<404>`。 */
    @Test
    @DisplayName("#4709 POST /orders/{orderId}/repricing ⇒ 只补 NULL 的实例行（已有价的行不写）")
    void repriceUnpricedInstancesEndpointIsRegistered() throws Exception {
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order("producing"));
        when(processingOrderMapper.selectActiveByOrderId(ORDER_ID, TENANT)).thenReturn(processingOrder("tok123"));
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(
                unpricedOp("op-unpriced", 1, "打包", "布料"),
                op("op-priced", 2, "精裁-布", "10.00", false, "done", "10.00")));
        when(productionOperationPositionMapper.selectList(any())).thenReturn(List.of(
                priceCell("打包", "布料", "1.20"),
                priceCell("裁剪", "布料", null)));
        when(positionOperationMapper.fillUnpricedUnitPrice(any(), any(), any(), any())).thenReturn(1);

        mockMvc.perform(post("/api/admin/production/orders/" + ORDER_ID + "/repricing"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.filled").value(1))
                .andExpect(jsonPath("$.data.already_priced").value(1))
                .andExpect(jsonPath("$.data.batch_id").isNotEmpty())
                .andExpect(jsonPath("$.data.filled_operations[0].operation").value("打包"))
                .andExpect(jsonPath("$.data.filled_operations[0].unit_price").value(1.20))
                .andExpect(jsonPath("$.data.hint").isNotEmpty());

        // 红线①（信封层）：只对未定价那行调用补价，已有价的行一次都不写
        verify(positionOperationMapper, times(1))
                .fillUnpricedUnitPrice(eq("op-unpriced"), eq(TENANT), eq(new BigDecimal("1.20")), any());
        verify(positionOperationMapper, never())
                .fillUnpricedUnitPrice(eq("op-priced"), any(), any(), any());
    }

    /** 红证（改前）：端点不存在 ⇒ 本用例得 404。 */
    @Test
    @DisplayName("#4709 POST /repricing/{batchId}/rollback ⇒ 按账本回滚（只还原本批补的价）")
    void rollbackRepricingEndpointIsRegistered() throws Exception {
        com.migao.admin.entity.ProductionInstanceRepricingLog row =
                com.migao.admin.entity.ProductionInstanceRepricingLog.builder()
                        .id("log-1").tenantId(TENANT).batchId("batch-1").processingOrderId(PO_ID)
                        .positionOperationId("op-unpriced").newUnitPrice(new BigDecimal("1.20"))
                        .deleted(0).build();
        when(repricingLogMapper.selectList(any())).thenReturn(List.of(row));
        when(positionOperationMapper.revertFilledUnitPrice(any(), any(), any(), any())).thenReturn(1);
        when(repricingLogMapper.markRolledBack(any(), any(), any())).thenReturn(1);

        mockMvc.perform(post("/api/admin/production/repricing/batch-1/rollback"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.batch_id").value("batch-1"))
                .andExpect(jsonPath("$.data.reverted").value(1))
                .andExpect(jsonPath("$.data.skipped").value(0));

        verify(positionOperationMapper, times(1))
                .revertFilledUnitPrice(eq("op-unpriced"), eq(TENANT), eq(new BigDecimal("1.20")), any());
        verify(repricingLogMapper, times(1)).markRolledBack(eq("log-1"), eq(TENANT), any());
    }

    @Test
    @DisplayName("#4709 补价/回滚端点权限 = 方法级 processing:manage（写面，不是类级 order:list）")
    void repricingEndpointsRequireProcessingManage() throws Exception {
        Method reprice = ProductionController.class.getMethod(
                "repriceUnpricedInstances", String.class);
        Method rollback = ProductionController.class.getMethod(
                "rollbackRepricing", String.class);

        for (Method method : List.of(reprice, rollback)) {
            RequirePermission annotation = method.getAnnotation(RequirePermission.class);
            assertThat(annotation).as("%s 必须声明方法级权限", method.getName()).isNotNull();
            assertThat(annotation.value()).isEqualTo("processing:manage");
        }
    }
}
