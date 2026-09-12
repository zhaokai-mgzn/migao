// case_ids: PG-001, PG-005, PG-008

package com.migao.admin.controller;

import com.migao.admin.dto.ProcessingOrderResponse;
import com.migao.admin.service.ProcessingOrderService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.test.web.servlet.MockMvc;

import java.util.List;

import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * ProcessingOrderController 端点测试（issue #3340）
 * 覆盖：生成/列表/详情/状态更新四条端点 + 错误路径。
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("ProcessingOrderController 端点")
class ProcessingOrderControllerTest extends BaseControllerTest {

    private MockMvc mockMvc;

    @Mock
    private ProcessingOrderService processingOrderService;

    @InjectMocks
    private ProcessingOrderController controller;

    @BeforeEach
    void setUp() {
        super.baseSetUp();
        mockMvc = buildMockMvc(controller);
    }

    @Test
    @DisplayName("POST /generate — 批量生成（PG-001）")
    void generate() throws Exception {
        when(processingOrderService.generate(anyList(), eq(1L), any()))
                .thenReturn(List.of(ProcessingOrderService.GenerateResult.ok("order-1", "JG-20260912-0001")));

        mockMvc.perform(post("/api/admin/processing-orders/generate")
                        .contentType("application/json")
                        .content("{\"orderIds\":[\"order-1\"]}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data[0].success").value(true))
                .andExpect(jsonPath("$.data[0].processingOrderNo").value("JG-20260912-0001"));
    }

    @Test
    @DisplayName("GET / — 列表（含 keyword/status 参数透传）")
    void list() throws Exception {
        ProcessingOrderResponse resp = new ProcessingOrderResponse();
        resp.setId("po-1");
        resp.setProcessingOrderNo("JG-1");
        resp.setStatus("issued");
        when(processingOrderService.list(any(), any(), eq(1L))).thenReturn(List.of(resp));

        mockMvc.perform(get("/api/admin/processing-orders")
                        .param("keyword", "JG-1").param("status", "issued"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data[0].processingOrderNo").value("JG-1"));
    }

    @Test
    @DisplayName("GET /{id} — 详情")
    void detail() throws Exception {
        ProcessingOrderResponse resp = new ProcessingOrderResponse();
        resp.setId("po-1");
        resp.setProcessingOrderNo("JG-1");
        resp.setStatus("completed");
        when(processingOrderService.getDetail("po-1", 1L)).thenReturn(resp);

        mockMvc.perform(get("/api/admin/processing-orders/po-1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.status").value("completed"));
    }

    @Test
    @DisplayName("PATCH /{id} — issue 状态更新（PG-005）")
    void updateIssue() throws Exception {
        ProcessingOrderResponse resp = new ProcessingOrderResponse();
        resp.setId("po-1");
        resp.setProcessingOrderNo("JG-1");
        resp.setStatus("issued");
        resp.setProcessor("朝阳加工厂");
        when(processingOrderService.updateStatus(eq("JG-1"), any(), eq(1L), any())).thenReturn(resp);

        mockMvc.perform(patch("/api/admin/processing-orders/JG-1")
                        .contentType("application/json")
                        .content("{\"action\":\"issue\",\"processor\":\"朝阳加工厂\",\"expectedDeliveryDate\":\"2026-09-20\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.status").value("issued"))
                .andExpect(jsonPath("$.data.processor").value("朝阳加工厂"));
    }

    @Test
    @DisplayName("PATCH /{id} — cancel 必填 reason 由服务层校验（PG-008）")
    void updateCancelMissingReason() throws Exception {
        when(processingOrderService.updateStatus(eq("JG-1"), any(), eq(1L), any()))
                .thenThrow(new com.migao.admin.exception.BusinessException(
                        "VALIDATION_ERROR", "取消加工单必须填写原因", 400));

        mockMvc.perform(patch("/api/admin/processing-orders/JG-1")
                        .contentType("application/json")
                        .content("{\"action\":\"cancel\"}"))
                .andExpect(status().is4xxClientError());
    }
}
