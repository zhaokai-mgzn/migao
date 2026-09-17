// case_ids: PG-018
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

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(TENANT);
        ProductionService service = new ProductionService(
                processingOrderMapper, positionOperationMapper, workLogMapper, orderMapper);
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
                "pending_operations", "total_operations", "done_operations", "expected_delivery_date");
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

    @Test
    @DisplayName("类级 @RequirePermission(order:list) 护栏不可丢")
    void agentControllerDeclaresPermission() {
        RequirePermission ann = AgentProductionController.class.getAnnotation(RequirePermission.class);
        assertThat(ann).as("类级 @RequirePermission 缺失 = 权限护栏丢失").isNotNull();
        assertThat(ann.value()).isEqualTo("order:list");
    }
}
