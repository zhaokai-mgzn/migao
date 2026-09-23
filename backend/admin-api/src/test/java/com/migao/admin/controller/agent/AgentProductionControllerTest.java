// case_ids: PG-018, PG-057
package com.migao.admin.controller.agent;

import com.fasterxml.jackson.databind.JsonNode;
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
import com.migao.admin.service.ProductionService;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * AgentProductionController 测试（米宝生产进度/计件端点，issue #3995，M4-G-2）
 *
 * 这两个端点是**冻结契约**（并行包消费）：路径/参数/返回字段不可改。
 * 因此除了值断言，还断言 **data 的键集完全等于契约键集** —— 少一个键或改名都会红。
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("AgentProductionController 冻结契约测试")
class AgentProductionControllerTest {

    private static final Long TENANT = 1L;
    private static final String ORDER_ID = "order-1";
    private static final String ORDER_NO = "ORD-20260917-001";
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
    private com.migao.admin.mapper.OrderItemMapper orderItemMapper;
    @Mock
    private ClientRequestIdService clientRequestIdService;

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(TENANT);
        ProductionService service = new ProductionService(
                processingOrderMapper, positionOperationMapper, workLogMapper, orderMapper,
                orderItemMapper, clientRequestIdService);
        mockMvc = MockMvcBuilders.standaloneSetup(new AgentProductionController(service))
                .setControllerAdvice(new GlobalExceptionHandler())
                .build();
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    private Order order() {
        Order o = new Order();
        o.setId(ORDER_ID);
        o.setTenantId(TENANT);
        o.setOrderNo(ORDER_NO);
        o.setStatus("producing");
        o.setDeleted(0);
        return o;
    }

    private ProcessingOrder processingOrder() {
        ProcessingOrder po = new ProcessingOrder();
        po.setId(PO_ID);
        po.setTenantId(TENANT);
        po.setOrderId(ORDER_ID);
        po.setProcessingOrderNo("JG-20260917-0001");
        po.setStatus("in_processing");
        po.setExpectedDeliveryDate(LocalDate.of(2026, 9, 25));
        po.setQrToken("tok123");
        po.setDeleted(0);
        return po;
    }

    private ProcessingPositionOperation op(String id, int seq, String name, String qty, boolean mustFinish,
                                          String status, String doneQty, String unitPrice, String factor) {
        return ProcessingPositionOperation.builder()
                .id(id).tenantId(TENANT).processingOrderId(PO_ID)
                .positionName("布帘").seq(seq).operationName(name).groupName("后道").unit("套")
                .qty(new BigDecimal(qty)).unitPrice(new BigDecimal(unitPrice)).factor(new BigDecimal(factor))
                .isMustFinish(mustFinish).isStartMarker(false)
                .status(status).doneQty(new BigDecimal(doneQty)).deleted(0)
                .build();
    }

    @Test
    @DisplayName("GET /progress → 冻结契约键集 + 进度/待做工序/交期")
    void progressReturnsFrozenContract() throws Exception {
        when(orderMapper.selectOne(any())).thenReturn(order());
        when(processingOrderMapper.selectActiveByOrderId(ORDER_ID, TENANT)).thenReturn(processingOrder());
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(
                op("op-1", 1, "精裁-布", "12.30", false, "done", "12.30", "0.40", "1.00"),
                op("op-2", 2, "外帘装袋", "1.00", true, "pending", "0.00", "1.00", "1.00")));

        String body = mockMvc.perform(get("/api/admin/agent/production/progress").param("order_no", ORDER_NO))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.order_no").value(ORDER_NO))
                .andExpect(jsonPath("$.data.status").value("producing"))
                .andExpect(jsonPath("$.data.status_text").value("生产中"))
                .andExpect(jsonPath("$.data.progress_percent").value(50))
                .andExpect(jsonPath("$.data.current_operation").value("外帘装袋"))
                // issue #4643：web 界面渲染的**显示名**两键（只加不改 —— `current_operation` 仍是快照名）
                .andExpect(jsonPath("$.data.logical_name").value("外帘装袋"))
                .andExpect(jsonPath("$.data.pending_operations[0]").value("外帘装袋"))
                .andExpect(jsonPath("$.data.total_operations").value(2))
                .andExpect(jsonPath("$.data.done_operations").value(1))
                .andExpect(jsonPath("$.data.expected_delivery_date").value("2026-09-25"))
                .andReturn().getResponse().getContentAsString();

        JsonNode data = objectMapper.readTree(body).path("data");
        List<String> keys = new ArrayList<>();
        data.fieldNames().forEachRemaining(keys::add);
        assertThat(keys).as("冻结契约：字段名/数量不可改（并行包消费）").containsExactlyInAnyOrder(
                "order_no", "status", "status_text", "progress_percent", "current_operation",
                "logical_name", "position",
                "pending_operations", "total_operations", "done_operations", "expected_delivery_date");
        assertThat(data.path("position").isNull())
                .as("部位无关工序（外帘装袋）⇒ 不拼部位")
                .isTrue();
    }

    @Test
    @DisplayName("GET /progress → 变体名工序：追加 logical_name/position，current_operation 快照名一字不动（issue #4643）")
    void progressCarriesLogicalNameForVariantSnapshot() throws Exception {
        when(orderMapper.selectOne(any())).thenReturn(order());
        when(processingOrderMapper.selectActiveByOrderId(ORDER_ID, TENANT)).thenReturn(processingOrder());
        ProcessingPositionOperation variant =
                op("op-1", 1, "精裁-布", "12.30", false, "pending", "0.00", "0.40", "1.00");
        variant.setPositionKind("布帘");
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(variant));

        String body = mockMvc.perform(get("/api/admin/agent/production/progress").param("order_no", ORDER_NO))
                .andExpect(status().isOk())
                // 既有快照键一字不动（agent 与其它消费者仍读它）
                .andExpect(jsonPath("$.data.current_operation").value("精裁-布"))
                .andExpect(jsonPath("$.data.pending_operations[0]").value("精裁-布"))
                // 追加键（改前这两条 jsonPath 取不到值 ⇒ 红证）
                .andExpect(jsonPath("$.data.logical_name").value("精裁"))
                .andExpect(jsonPath("$.data.position").value("布帘"))
                .andReturn().getResponse().getContentAsString();

        // 键集里**必须**有这两键（键在、值可为 null；省键 ⇒ 前端渲染 undefined）
        JsonNode data = objectMapper.readTree(body).path("data");
        assertThat(data.has("logical_name") && data.has("position")).isTrue();
    }

    @Test
    @DisplayName("GET /progress → 订单不存在（含跨租户）404")
    void progressUnknownOrderNotFound() throws Exception {
        when(orderMapper.selectOne(any())).thenReturn(null);

        mockMvc.perform(get("/api/admin/agent/production/progress").param("order_no", "NOPE"))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.success").value(false));
    }

    @Test
    @DisplayName("GET /piecework → 冻结契约键集 + 按工序明细（返工不计件）")
    void pieceworkReturnsWorkerDetails() throws Exception {
        when(workLogMapper.selectList(any())).thenReturn(List.of(
                ProductionWorkLog.builder().tenantId(TENANT).processingOrderId(PO_ID).operationId("op-1")
                        .operationName("精裁-布").workerName("张三").qty(new BigDecimal("10"))
                        .qualifiedQty(new BigDecimal("10")).workType("normal")
                        .workDate(LocalDate.of(2026, 9, 20)).deleted(0).build(),
                ProductionWorkLog.builder().tenantId(TENANT).processingOrderId(PO_ID).operationId("op-2")
                        .operationName("韩褶-布").workerName("张三").qty(new BigDecimal("5"))
                        .qualifiedQty(new BigDecimal("5")).workType("normal")
                        .workDate(LocalDate.of(2026, 9, 21)).deleted(0).build(),
                ProductionWorkLog.builder().tenantId(TENANT).processingOrderId(PO_ID).operationId("op-1")
                        .operationName("精裁-布").workerName("张三").qty(new BigDecimal("2"))
                        .qualifiedQty(new BigDecimal("2")).workType("rework")
                        .workDate(LocalDate.of(2026, 9, 22)).deleted(0).build()));
        when(positionOperationMapper.selectById("op-1"))
                .thenReturn(op("op-1", 1, "精裁-布", "12.30", false, "done", "10.00", "0.40", "1.00"));
        when(positionOperationMapper.selectById("op-2"))
                .thenReturn(op("op-2", 2, "韩褶-布", "5.00", false, "done", "5.00", "0.40", "1.70"));

        String body = mockMvc.perform(get("/api/admin/agent/production/piecework")
                        .param("worker_name", "张三").param("period", "2026-09"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.worker_name").value("张三"))
                .andExpect(jsonPath("$.data.period").value("2026-09"))
                .andExpect(jsonPath("$.data.total").value(7.40))
                .andExpect(jsonPath("$.data.details[0].operation").value("精裁-布"))
                .andExpect(jsonPath("$.data.details[0].qty").value(10.0))
                .andExpect(jsonPath("$.data.details[0].amount").value(4.00))
                .andExpect(jsonPath("$.data.details[1].operation").value("韩褶-布"))
                // #4604：报工无单价快照 ⇒ 回落实例的单价**与系数** —— 5 × 0.40 × 1.70 = 3.40
                // （#4589 期间曾算成 2.00 = 不乘系数 ⇒ 回溯；用户裁定 B 不追溯 ⇒ 恢复 3.40）
                .andExpect(jsonPath("$.data.details[1].amount").value(3.40))
                .andReturn().getResponse().getContentAsString();

        JsonNode data = objectMapper.readTree(body).path("data");
        List<String> keys = new ArrayList<>();
        data.fieldNames().forEachRemaining(keys::add);
        assertThat(keys).as("冻结契约：字段名/数量不可改（并行包消费）")
                .containsExactlyInAnyOrder("worker_name", "period", "total", "details");
    }

    @Test
    @DisplayName("GET /piecework → 缺 worker_name / 非法 period → 422")
    void pieceworkRejectsInvalidParams() throws Exception {
        mockMvc.perform(get("/api/admin/agent/production/piecework").param("period", "2026-09"))
                .andExpect(status().isUnprocessableEntity());

        mockMvc.perform(get("/api/admin/agent/production/piecework")
                        .param("worker_name", "张三").param("period", "2026/09"))
                .andExpect(status().isUnprocessableEntity());
    }

    // ── 过程明细（issue #4201）：工序实例 × 报工明细 × 数量聚合 ──────────────────────

    private ProcessingPositionOperation cuttingOp(String id, int seq, String name, String qty,
                                                 String doneQty, String unitPrice) {
        return ProcessingPositionOperation.builder()
                .id(id).tenantId(TENANT).processingOrderId(PO_ID)
                .positionName("布艺遮光帘A 米白").positionKind("布帘").seq(seq)
                .operationName(name).groupName("裁剪").unit("米")
                .qty(new BigDecimal(qty)).unitPrice(new BigDecimal(unitPrice))
                .factor(new BigDecimal("1.00"))
                .isMustFinish(false).isStartMarker(false)
                .status("done").doneQty(new BigDecimal(doneQty)).deleted(0)
                .build();
    }

    private ProductionWorkLog log(String opId, String name, String worker, String qty,
                                  String qualified, String type, String date) {
        return ProductionWorkLog.builder()
                .tenantId(TENANT).processingOrderId(PO_ID).operationId(opId).operationName(name)
                .workerName(worker).qty(new BigDecimal(qty)).qualifiedQty(new BigDecimal(qualified))
                .workType(type).workDate(LocalDate.parse(date)).deleted(0).build();
    }

    @Test
    @DisplayName("GET /worklog → 冻结契约键集 + 下料（裁剪）做到哪/谁报的/合格-返工-报废各多少")
    void worklogReturnsFrozenContract() throws Exception {
        when(orderMapper.selectOne(any())).thenReturn(order());
        when(processingOrderMapper.selectActiveByOrderId(ORDER_ID, TENANT)).thenReturn(processingOrder());
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(
                cuttingOp("op-1", 1, "精裁-布", "12.00", "10.00", "0.40"),
                op("op-2", 2, "外帘装袋", "1.00", true, "pending", "0.00", "1.00", "1.00")));
        when(workLogMapper.selectList(any())).thenReturn(List.of(
                log("op-1", "精裁-布", "王师傅", "10.00", "10.00", "normal", "2026-09-19"),
                log("op-1", "精裁-布", "王师傅", "2.00", "0.00", "rework", "2026-09-20")));

        String body = mockMvc.perform(get("/api/admin/agent/production/worklog").param("order_no", ORDER_NO))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.order_no").value(ORDER_NO))
                .andExpect(jsonPath("$.data.processing_order_no").value("JG-20260917-0001"))
                .andExpect(jsonPath("$.data.processing_status").value("in_processing"))
                // 行序 = listOperations 的行序（部位升序 → seq 升序），夹具里就是 [op-1, op-2]
                .andExpect(jsonPath("$.data.operations[0].position").value("布帘"))
                .andExpect(jsonPath("$.data.operations[0].operation_name").value("精裁-布"))
                .andExpect(jsonPath("$.data.operations[0].logical_name").value("精裁"))
                .andExpect(jsonPath("$.data.operations[0].group_name").value("裁剪"))
                .andExpect(jsonPath("$.data.operations[0].required_qty").value(12.0))
                .andExpect(jsonPath("$.data.operations[0].qualified_qty").value(10.0))
                .andExpect(jsonPath("$.data.operations[0].rework_qty").value(2.0))
                .andExpect(jsonPath("$.data.operations[0].scrap_qty").value(0.0))
                .andExpect(jsonPath("$.data.operations[0].workers[0]").value("王师傅"))
                .andExpect(jsonPath("$.data.operations[0].last_work_date").value("2026-09-20"))
                // 报工明细**倒序**（最近在前，与工人端「操作记录」同一约定）
                .andExpect(jsonPath("$.data.work_logs[0].work_type").value("rework"))
                .andExpect(jsonPath("$.data.work_logs[1].work_type").value("normal"))
                .andExpect(jsonPath("$.data.work_logs[1].worker_name").value("王师傅"))
                .andExpect(jsonPath("$.data.totals.qualified_qty").value(10.0))
                .andExpect(jsonPath("$.data.totals.rework_qty").value(2.0))
                .andExpect(jsonPath("$.data.totals.scrap_qty").value(0.0))
                // 计件金额与 /piecework 同一份聚合：10 × 0.40（返工 2 米不计件）
                .andExpect(jsonPath("$.data.totals.piecework_amount").value(4.00))
                .andReturn().getResponse().getContentAsString();

        JsonNode data = objectMapper.readTree(body).path("data");
        List<String> keys = new ArrayList<>();
        data.fieldNames().forEachRemaining(keys::add);
        assertThat(keys).as("冻结契约：字段名/数量不可改（并行包消费）").containsExactlyInAnyOrder(
                "order_no", "processing_order_no", "processing_status",
                "operations", "work_logs", "totals");

        List<String> opKeys = new ArrayList<>();
        data.path("operations").path(0).fieldNames().forEachRemaining(opKeys::add);
        assertThat(opKeys).as("工序实例行键集冻结").containsExactlyInAnyOrder(
                "position", "operation_name", "logical_name", "group_name", "seq", "status",
                "required_qty", "qualified_qty", "rework_qty", "scrap_qty",
                "is_must_finish", "workers", "last_work_date");

        List<String> logKeys = new ArrayList<>();
        data.path("work_logs").path(0).fieldNames().forEachRemaining(logKeys::add);
        assertThat(logKeys).as("报工明细行键集冻结").containsExactlyInAnyOrder(
                "operation_name", "logical_name", "position", "worker_name",
                "qty", "qualified_qty", "work_type", "work_date");

        List<String> totalKeys = new ArrayList<>();
        data.path("totals").fieldNames().forEachRemaining(totalKeys::add);
        assertThat(totalKeys).as("合计键集冻结").containsExactlyInAnyOrder(
                "qualified_qty", "rework_qty", "scrap_qty", "piecework_amount");

        // 投影纪律（类注释）：**不下发内部单价/系数/租户字段** —— 金额只以「计件金额」形态出现
        assertThat(body).as("明细面不得出现内部单价/系数/租户字段")
                .doesNotContain("unit_price").doesNotContain("factor")
                .doesNotContain("tenant_id").doesNotContain("qty_source");
    }

    @Test
    @DisplayName("GET /worklog → 无加工单：空明细 + 空合计（未开始态，不是错误态）")
    void worklogWithoutProcessingOrderIsEmpty() throws Exception {
        when(orderMapper.selectOne(any())).thenReturn(order());
        when(processingOrderMapper.selectActiveByOrderId(ORDER_ID, TENANT)).thenReturn(null);

        mockMvc.perform(get("/api/admin/agent/production/worklog").param("order_no", ORDER_NO))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.order_no").value(ORDER_NO))
                .andExpect(jsonPath("$.data.processing_order_no").doesNotExist())
                .andExpect(jsonPath("$.data.processing_status").doesNotExist())
                .andExpect(jsonPath("$.data.operations").isEmpty())
                .andExpect(jsonPath("$.data.work_logs").isEmpty())
                .andExpect(jsonPath("$.data.totals.qualified_qty").value(0))
                .andExpect(jsonPath("$.data.totals.piecework_amount").value(0.00));
    }

    @Test
    @DisplayName("GET /worklog → 跨租户/不存在的订单 404（租户隔离沿用 resolveOrder）")
    void worklogUnknownOrderNotFound() throws Exception {
        when(orderMapper.selectOne(any())).thenReturn(null);

        mockMvc.perform(get("/api/admin/agent/production/worklog").param("order_no", "NOPE"))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.success").value(false));
    }

    @Test
    @DisplayName("三个 GET 各自的方法级 @RequirePermission(processing:manage) 护栏不可丢（#5246 已移除类级）")
    void agentControllerDeclaresPermission() throws Exception {
        // issue #5246：类级 @RequirePermission("order:list") 已移除 —— 本控制器是「生产看板 / 计件工资」
        // 侧边栏节点的 agent 侧数据面，码必须与那两个节点同码（processing:manage），否则
        // 「有 order:list、没有 processing:manage」的角色能绕过菜单直达生产数据。
        // 判据落在**每个端点**上（不是类级一个码）：类级盖全类时，日后新增端点会静默继承一个过期的码。
        assertThat(AgentProductionController.class.getAnnotation(RequirePermission.class))
                .as("类级 @RequirePermission 应已按 #5246 移除（改为逐端点方法级）").isNull();
        assertThat(permissionOf("progress", String.class))
                .as("/progress").isEqualTo("processing:manage");
        assertThat(permissionOf("piecework", String.class, String.class))
                .as("/piecework").isEqualTo("processing:manage");
        assertThat(permissionOf("worklog", String.class))
                .as("/worklog").isEqualTo("processing:manage");
    }

    /** 取某端点方法上的 @RequirePermission 值；注解缺失即断言失败（护栏丢失，不得静默通过）。 */
    private static String permissionOf(String method, Class<?>... params) throws Exception {
        RequirePermission ann = AgentProductionController.class
                .getMethod(method, params).getAnnotation(RequirePermission.class);
        assertThat(ann).as(method + " 缺方法级 @RequirePermission = 权限护栏丢失").isNotNull();
        return ann.value();
    }
}
