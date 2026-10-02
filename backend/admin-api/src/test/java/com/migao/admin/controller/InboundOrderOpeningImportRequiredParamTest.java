// case_ids: API-008
package com.migao.admin.controller;

import com.migao.admin.config.GlobalExceptionHandler;
import com.migao.admin.config.TenantContext;
import com.migao.admin.service.InboundOrderService;
import com.migao.admin.service.OpeningRegisterImportService;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.multipart;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * 期初导入**缺必填 @RequestParam** 的 HTTP 语义（issue #5982）。
 *
 * <p>缺陷（修前实测）：{@code POST /api/admin/inbound-orders/opening-import} 只带 {@code file}、
 * 不带 {@code importRunId} ⇒ Spring 抛
 * {@code MissingServletRequestParameterException}，而
 * {@code config/GlobalExceptionHandler} 没有它的具名分支 ⇒ 落兜底 {@code Exception} 分支 ⇒
 * <b>500 {@code INTERNAL_ERROR}「服务器内部错误」</b>，日志
 * {@code 系统异常: Required request parameter 'importRunId' for method parameter type String is not present}。
 * 客户端集成错误被报成服务端故障（监控误报 + 排障走偏）。</p>
 *
 * <p>期望：<b>400</b>，且响应体给出**缺失的字段名**（与仓库既有 400 错误体风格一致：
 * {@code code=BAD_REQUEST} + {@code error.details:[{field,message}]}）。</p>
 *
 * <p>本文件是**实例判据**（真端点 + 真 {@code @RestControllerAdvice} 经真实 Spring 分发链）；
 * 类级守卫（处理器分支台账 / 豁免台账）在
 * {@code backend/admin-api/src/test/java/com/migao/admin/config/GlobalExceptionHandlerCoverageTest.java}。</p>
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("期初导入缺必填 importRunId（#5982）：400 + 字段名，而不是 500")
class InboundOrderOpeningImportRequiredParamTest {

    private static final String URL = "/api/admin/inbound-orders/opening-import";

    private static final long TENANT_ID = 24L;

    private MockMvc mockMvc;

    @Mock
    private InboundOrderService inboundOrderService;

    @Mock
    private OpeningRegisterImportService openingRegisterImportService;

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(TENANT_ID);
        mockMvc = MockMvcBuilders
                .standaloneSetup(new InboundOrderController(inboundOrderService, openingRegisterImportService))
                .setControllerAdvice(new GlobalExceptionHandler())
                .build();
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    private MockMultipartFile excel() {
        return new MockMultipartFile("file", "opening.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                new byte[]{1, 2, 3});
    }

    @Test
    @DisplayName("缺 importRunId ⇒ 400 BAD_REQUEST + details[0].field=importRunId（修前实测 500 INTERNAL_ERROR）")
    void missingImportRunIdIsClientError() throws Exception {
        String body = mockMvc.perform(multipart(URL).file(excel()))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.error.code").value("BAD_REQUEST"))
                .andExpect(jsonPath("$.error.details[0].field").value("importRunId"))
                .andReturn().getResponse().getContentAsString();

        // 「给出缺失的字段名」= 全文可见，而不只是 details 里的结构化字段
        assertThat(body).contains("importRunId");
        // 闸门必须**在调 service 之前**拦住（没进业务层就说明确实是参数绑定阶段拒的）
        verifyNoInteractions(openingRegisterImportService);
    }

    @Test
    @DisplayName("带 importRunId 的正常请求不受影响（对照读数：证明本文件的接线是真的）")
    void withImportRunIdItReachesTheService() throws Exception {
        mockMvc.perform(multipart(URL).file(excel()).param("importRunId", "run-1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true));

        verify(openingRegisterImportService).importOpening(any(), eq("run-1"), eq(TENANT_ID), eq("system"));
    }
}
