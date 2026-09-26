// case_ids: PR-114, PR-115
package com.migao.admin.controller;

import com.migao.admin.config.GlobalExceptionHandler;
import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.InboundLabelPrintView;
import com.migao.admin.dto.InboundLabelView;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.service.InboundLabelService;
import com.migao.admin.worker.WorkerIdentity;
import com.migao.admin.worker.WorkerSessionService;
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

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * 工人可达的入库标签端点（issue #5052 P2；设计 §5.2）—— <b>HTTP 层</b>契约与状态码。
 *
 * <p>与 {@code InboundLabelServiceTest} 的分工：那边钉**副作用与口径**（自增一次 / 审计一行 /
 * 归一化 / 落地页配置），本类钉**线上可观察的状态码**（401 / 404 / 410 / 200）与**身份载体**
 * （{@code X-Worker-Session-Id} → 服务端解出的 workerId / workerName，body 不参与）。</p>
 *
 * <h3>红证（改坏 ⇒ 必红）</h3>
 * <ul>
 *   <li>把跨租户的 404 改成 403 ⇒ {@code crossTenantIs404NotForbidden} 红；</li>
 *   <li>去掉控制器里的 {@code requireWorker} 显式判空（只调 {@code resolveIdentity} 不看返回值）
 *       ⇒ {@code withoutWorkerSessionBothEndpointsAre401} 红（会变成 200）；</li>
 *   <li>把撤销后的 410 改成 404 ⇒ {@code revokedLabelIsGoneNotMissing} 红。</li>
 * </ul>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("WorkerInboundLabelController（#5052 P2）：状态码与身份载体")
class WorkerInboundLabelControllerTest {

    @Mock private InboundLabelService inboundLabelService;
    @Mock private WorkerSessionService workerSessionService;

    private MockMvc mockMvc;

    private static final Long TENANT = 7L;
    private static final String SESSION = "sess-zhang-1";
    private static final String CODE = "7K3M9QP2";

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(TENANT);
        WorkerInboundLabelController controller =
                new WorkerInboundLabelController(inboundLabelService, workerSessionService);
        mockMvc = MockMvcBuilders.standaloneSetup(controller)
                .setControllerAdvice(new GlobalExceptionHandler())
                .build();
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    private void login() {
        when(workerSessionService.resolveIdentity(SESSION)).thenReturn(
                new WorkerIdentity("w-1", "张三", WorkerIdentity.SOURCE_SERVER_SESSION, SESSION));
    }

    @Test
    @DisplayName("🔴 无工人 session ⇒ 两个端点都 401，且一次业务调用都不发生")
    void withoutWorkerSessionBothEndpointsAre401() throws Exception {
        mockMvc.perform(get("/api/worker/inbound/labels/" + CODE))
                .andExpect(status().isUnauthorized());
        mockMvc.perform(post("/api/worker/inbound/labels/" + CODE + "/print"))
                .andExpect(status().isUnauthorized());

        verify(inboundLabelService, never()).detail(anyString(), anyLong());
        verify(inboundLabelService, never()).recordPrint(anyString(), anyLong(), anyString(), anyString(),
                anyString(), anyString());
    }

    @Test
    @DisplayName("详情：200 + 标签要的字段（短码 / 品名 / 色号 / 米数 / 供应商 / 入库日期）")
    void detailReturnsTheLabelFields() throws Exception {
        login();
        InboundLabelView view = new InboundLabelView();
        view.setShortCode(CODE);
        view.setInboundNo("RK-20260926-0001");
        view.setProductName("遮光布");
        view.setColorName("米白");
        view.setQuantity(new BigDecimal("60.5"));
        view.setSupplier("亿家纺织");
        view.setPrintCount(2);
        when(inboundLabelService.detail(CODE, TENANT)).thenReturn(view);

        mockMvc.perform(get("/api/worker/inbound/labels/" + CODE).header(WorkerSessionService.SESSION_HEADER, SESSION))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.shortCode").value(CODE))
                .andExpect(jsonPath("$.data.productName").value("遮光布"))
                .andExpect(jsonPath("$.data.colorName").value("米白"))
                .andExpect(jsonPath("$.data.quantity").value(60.5))
                .andExpect(jsonPath("$.data.supplier").value("亿家纺织"))
                .andExpect(jsonPath("$.data.printCount").value(2));

        verify(inboundLabelService).detail(CODE, TENANT);
    }

    @Test
    @DisplayName("🔴 跨租户 / 不存在 ⇒ 404（**不是 403**：403 等于确认「这码存在，只是不归你」）")
    void crossTenantIs404NotForbidden() throws Exception {
        login();
        when(inboundLabelService.detail(CODE, TENANT)).thenThrow(BusinessException.notFound("入库标签"));

        mockMvc.perform(get("/api/worker/inbound/labels/" + CODE).header(WorkerSessionService.SESSION_HEADER, SESSION))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.error.code").value("NOT_FOUND"));
        mockMvc.perform(get("/api/worker/inbound/labels/" + CODE)
                        .header(WorkerSessionService.SESSION_HEADER, SESSION))
                .andExpect(status().isNotFound());
    }

    @Test
    @DisplayName("🔴 已撤销 ⇒ 410 Gone（不是 404：不把「作废」说成「不存在」）")
    void revokedLabelIsGoneNotMissing() throws Exception {
        login();
        BusinessException gone = new BusinessException("LABEL_REVOKED", "该入库标签已作废", 410, "请补打一张");
        when(inboundLabelService.detail(CODE, TENANT)).thenThrow(gone);
        when(inboundLabelService.recordPrint(eq(CODE), eq(TENANT), anyString(), anyString(), anyString(), any()))
                .thenThrow(gone);

        mockMvc.perform(get("/api/worker/inbound/labels/" + CODE).header(WorkerSessionService.SESSION_HEADER, SESSION))
                .andExpect(status().isGone())
                .andExpect(jsonPath("$.error.code").value("LABEL_REVOKED"))
                .andExpect(jsonPath("$.suggestion").value("请补打一张"));
        mockMvc.perform(post("/api/worker/inbound/labels/" + CODE + "/print")
                        .header(WorkerSessionService.SESSION_HEADER, SESSION))
                .andExpect(status().isGone());
    }

    @Test
    @DisplayName("打印：200 + 服务端计数（第几次由服务端给，设备侧不自己数）")
    void printReturnsTheServerSideCount() throws Exception {
        login();
        when(inboundLabelService.recordPrint(eq(CODE), eq(TENANT), eq("w-1"), eq("张三"), anyString(), any()))
                .thenReturn(new InboundLabelPrintView(CODE, 4));

        mockMvc.perform(post("/api/worker/inbound/labels/" + CODE + "/print")
                        .header(WorkerSessionService.SESSION_HEADER, SESSION))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.shortCode").value(CODE))
                .andExpect(jsonPath("$.data.printCount").value(4));

        // 身份与租户**只**来自 session 头与 TenantContext（body 里没有 operator / tenantId 可传）
        verify(inboundLabelService).recordPrint(eq(CODE), eq(TENANT), eq("w-1"), eq("张三"), anyString(), any());
    }
}
