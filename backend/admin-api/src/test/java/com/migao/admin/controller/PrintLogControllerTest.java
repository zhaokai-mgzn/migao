// case_ids: OR-071
package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.PrintLogRecordResult;
import com.migao.admin.dto.PrintLogRequest;
import com.migao.admin.dto.PrintLogView;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.service.PrintLogService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import java.time.OffsetDateTime;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * 打印中心控制器（issue #7902）：两个端点的**接线面** —— 服务端上下文从哪来、请求体怎么透传、错误怎么回。
 *
 * <h3>本类钉住的三件事（都是「看着对、线上错」的形态）</h3>
 * <ol>
 *   <li><b>租户与操作人只从服务端上下文取</b>：客户端在请求体里塞什么都不会改变
 *       {@code tenantId} / {@code Operator} —— 否则「谁打的」可以由调用方自己写；</li>
 *   <li><b>请求体形状</b>：{@code {"docs":[{...}]}} 逐字段透传到服务层（不是把整个 body 当一条）；
 *       {@code GET} 的 {@code limit} 原样透传（默认与封顶在服务层，见 {@code PrintLogServiceTest}）；</li>
 *   <li><b>404 语义</b>：订单不存在时回 404 + {@code NOT_FOUND}（不是 200 空数组 —— 那会让
 *       「单子不在」与「没打过」长得一样）。</li>
 * </ol>
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("打印中心控制器：上下文来源 / 请求体透传 / 404 语义（#7902）")
class PrintLogControllerTest extends BaseControllerTest {

    private static final String ORDER_ID = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6";
    private static final String BASE = "/api/admin/orders/" + ORDER_ID + "/print-logs";

    private MockMvc mockMvc;

    @Mock
    private PrintLogService printLogService;

    @InjectMocks
    private PrintLogController printLogController;

    @BeforeEach
    void setUp() {
        super.baseSetUp();
        mockMvc = buildMockMvc(printLogController);
    }

    @Override
    @org.junit.jupiter.api.AfterEach
    void baseTearDown() {
        super.baseTearDown();
    }

    @Test
    @DisplayName("🔴 POST：租户与操作人取**服务端上下文**，请求体只贡献 docs")
    void recordUsesServerSideContext() throws Exception {
        when(printLogService.record(any(), any(), any(), any(), any(), any()))
                .thenReturn(new PrintLogRecordResult(List.of("log-1"), OffsetDateTime.now()));

        mockMvc.perform(post(BASE)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"docs":[{"docType":"processing","docTitle":"加工单","mediaId":"a4","sheets":2}]}
                                """))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.ids[0]").value("log-1"));

        @SuppressWarnings("unchecked")
        ArgumentCaptor<PrintLogRequest> request = ArgumentCaptor.forClass(PrintLogRequest.class);
        @SuppressWarnings("unchecked")
        ArgumentCaptor<PrintLogService.Operator> operator =
                ArgumentCaptor.forClass(PrintLogService.Operator.class);
        verify(printLogService).record(eq(ORDER_ID), request.capture(), eq(TEST_TENANT_ID),
                operator.capture(), any(), any());

        assertThat(request.getValue().getDocs()).hasSize(1);
        assertThat(request.getValue().getDocs().get(0).getDocType()).isEqualTo("processing");
        assertThat(request.getValue().getDocs().get(0).getDocTitle()).isEqualTo("加工单");
        assertThat(request.getValue().getDocs().get(0).getMediaId()).isEqualTo("a4");
        assertThat(request.getValue().getDocs().get(0).getSheets()).isEqualTo(2);
        // 操作人来自安全上下文（不是请求体）：id 就是 TEST_USER_ID
        assertThat(operator.getValue()).isNotNull();
        assertThat(operator.getValue().userId()).isEqualTo(TEST_USER_ID);
        assertThat(TenantContext.getTenantId()).isEqualTo(TEST_TENANT_ID);
    }

    @Test
    @DisplayName("GET：limit 原样透传，读面逐键下发（谁 / 何时 / 哪种单据 / 几张）")
    void listPassesLimitAndReturnsRows() throws Exception {
        when(printLogService.listByOrder(ORDER_ID, 50, TEST_TENANT_ID)).thenReturn(List.of(
                PrintLogView.builder()
                        .id("log-1")
                        .orderId(ORDER_ID)
                        .orderNo("ORD-20261027-0001")
                        .docType("processing")
                        .docTitle("加工单")
                        .mediaId("a4")
                        .sheets(2)
                        .channel("browser")
                        .status("fired")
                        .operatorId("u-1")
                        .operatorName("张三")
                        .createdAt(OffsetDateTime.now())
                        .build()
        ));

        mockMvc.perform(get(BASE).param("limit", "50"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data[0].docType").value("processing"))
                .andExpect(jsonPath("$.data[0].docTitle").value("加工单"))
                .andExpect(jsonPath("$.data[0].sheets").value(2))
                .andExpect(jsonPath("$.data[0].operatorName").value("张三"));

        verify(printLogService).listByOrder(ORDER_ID, 50, TEST_TENANT_ID);
    }

    @Test
    @DisplayName("GET 不带 limit ⇒ 传 null（默认值只在一处收敛：服务层）")
    void listWithoutLimitPassesNull() throws Exception {
        when(printLogService.listByOrder(eq(ORDER_ID), eq(null), eq(TEST_TENANT_ID)))
                .thenReturn(List.of());

        mockMvc.perform(get(BASE))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data").isArray());

        verify(printLogService).listByOrder(ORDER_ID, null, TEST_TENANT_ID);
    }

    @Test
    @DisplayName("🔴 订单不存在 ⇒ 404（不是 200 空数组：「单子不在」与「没打过」是两件事）")
    void missingOrderIsNotFound() throws Exception {
        when(printLogService.record(any(), any(), any(), any(), any(), any()))
                .thenThrow(BusinessException.notFound("订单"));

        mockMvc.perform(post(BASE)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"docs\":[{\"docType\":\"sales\"}]}"))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.error.code").value("NOT_FOUND"));
    }

    @Test
    @DisplayName("入参不合法 ⇒ 400 原样透出（服务层的 VALIDATION_ERROR 不被控制器吞掉）")
    void invalidRequestIsBadRequest() throws Exception {
        when(printLogService.record(any(), any(), any(), any(), any(), any()))
                .thenThrow(new BusinessException("VALIDATION_ERROR", "一次最多登记 10 条", 400));

        mockMvc.perform(post(BASE)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"docs\":[]}"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.error.code").value("VALIDATION_ERROR"));
    }
}
