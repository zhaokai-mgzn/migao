// case_ids: PG-018
package com.migao.admin.controller;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.config.GlobalExceptionHandler;
import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.entity.ProcessingPositionOperation;
import com.migao.admin.entity.ProductionWorkLog;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import com.migao.admin.mapper.ProcessingPositionOperationMapper;
import com.migao.admin.mapper.ProductionWorkLogMapper;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.service.ClientRequestIdService;
import com.migao.admin.service.ProductionOperationQueryService;
import com.migao.admin.service.ProductionService;
import org.junit.jupiter.api.AfterEach;
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

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.hamcrest.Matchers.containsString;
import static org.hamcrest.Matchers.matchesPattern;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
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
    private ProductionOperationQueryService productionOperationQueryService;

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(TENANT);
        ProductionService service = new ProductionService(
                processingOrderMapper, positionOperationMapper, workLogMapper, orderMapper,
                clientRequestIdService);
        mockMvc = MockMvcBuilders.standaloneSetup(
                        new ProductionController(service, productionOperationQueryService))
                .setControllerAdvice(new GlobalExceptionHandler())
                .build();
        // 无幂等键 ⇒ 老路径（claim 首执）；幂等接线自身的断言见「报工」段的两个专测
        when(clientRequestIdService.claim(any(), any(), any())).thenReturn(true);
        // §5-1 原子有序推进：真实 DB 首执影响 1 行；CAS 失败由专测打桩为 0
        when(positionOperationMapper.advanceDoneQtyIfUnchanged(any(), any(), any(), any(), any(), any()))
                .thenReturn(1);
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
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
    @DisplayName("positions 为空 → 422")
    void instantiateWithoutPositionsRejected() throws Exception {
        mockMvc.perform(post("/api/admin/production/orders/" + ORDER_ID + "/instantiate")
                        .contentType("application/json").content("{\"positions\":[]}"))
                .andExpect(status().isUnprocessableEntity());
    }

    @Test
    @DisplayName("订单不存在（含跨租户）→ 404")
    void instantiateUnknownOrderNotFound() throws Exception {
        when(orderMapper.selectById(ORDER_ID)).thenReturn(null);

        mockMvc.perform(post("/api/admin/production/orders/" + ORDER_ID + "/instantiate")
                        .contentType("application/json").content(INSTANTIATE_BODY))
                .andExpect(status().isNotFound());
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
                .andExpect(jsonPath("$.data.positions[0].operations[1].is_must_finish").value(true))
                .andExpect(jsonPath("$.data.positions[0].operations[1].done_qty").value(0.0))
                .andExpect(jsonPath("$.data.progress.total").value(2))
                .andExpect(jsonPath("$.data.progress.done").value(1))
                .andExpect(jsonPath("$.data.progress.percent").value(50));
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

    // ── §5 防呆的 HTTP 层（issue #4116 P0-3）：请求头透传 / 越站 422 / 超上限 422 / 软删 404 ──

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
    @DisplayName("§5-2 越站：前道未完成 ⇒ 422 + suggestion（不落明细、不推进）")
    void reportRejectedWhenPredecessorNotDone() throws Exception {
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order("producing"));
        when(processingOrderMapper.selectActiveByOrderId(ORDER_ID, TENANT)).thenReturn(processingOrder("tok123"));
        when(positionOperationMapper.selectById("op-2"))
                .thenReturn(op("op-2", 2, "布帘车被", "10.00", false, "pending", "0.00"));
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(
                op("op-1", 1, "精裁-布", "10.00", false, "done", "4.00"),
                op("op-2", 2, "布帘车被", "10.00", false, "pending", "0.00")));

        mockMvc.perform(post("/api/admin/production/orders/" + ORDER_ID + "/operations/op-2/report")
                        .contentType("application/json")
                        .content("{\"worker_name\":\"张师傅\",\"qty\":10,\"qualified_qty\":10,\"work_type\":\"normal\"}"))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.error.message", containsString("尚未完成")))
                .andExpect(jsonPath("$.suggestion", containsString("请先报工完成")));

        verify(workLogMapper, never()).insert(any(ProductionWorkLog.class));
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
    @DisplayName("工序库只读接口：GET /operations-catalog 透传租户 + 返回 groups 结构")
    void operationsCatalogReturnsGroups() throws Exception {
        when(productionOperationQueryService.catalog(TENANT)).thenReturn(Map.of(
                "total", 30,
                "groups", List.of(Map.of("group", "裁剪", "operations", List.of(
                        Map.of("name", "精裁-布", "unit", "米", "unit_price", new BigDecimal("0.40")))))));

        mockMvc.perform(get("/api/admin/production/operations-catalog"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.total").value(30))
                .andExpect(jsonPath("$.data.groups[0].group").value("裁剪"))
                .andExpect(jsonPath("$.data.groups[0].operations[0].name").value("精裁-布"));

        verify(productionOperationQueryService).catalog(TENANT);
    }

    @Test
    @DisplayName("工艺路线只读接口：GET /routings 透传租户 + 返回 routings 结构")
    void routingsReturnsTemplates() throws Exception {
        when(productionOperationQueryService.routings(TENANT)).thenReturn(Map.of(
                "total", 6,
                "routings", List.of(Map.of(
                        "curtain_type", "布帘", "craft", "韩褶", "operation_count", 11,
                        "operations", List.of(Map.of("seq", 1, "operation", "精裁-布"))))));

        mockMvc.perform(get("/api/admin/production/routings"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.total").value(6))
                .andExpect(jsonPath("$.data.routings[0].curtain_type").value("布帘"))
                .andExpect(jsonPath("$.data.routings[0].operation_count").value(11));

        verify(productionOperationQueryService).routings(TENANT);
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
}
