package com.migao.admin.controller;

// case_ids: PG-018, PG-072, BM-006, DF-017

import com.migao.admin.exception.BusinessException;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.service.ProductionService;
import com.migao.admin.worker.WorkerIdentity;
import com.migao.admin.worker.WorkerSessionService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.test.web.servlet.MockMvc;

import java.lang.reflect.Method;
import java.util.LinkedHashMap;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * 工人端「我的计件」读面测试（issue #6767；口径真值源 = {@code docs/design/worker-home-menu.md} §6.3）。
 *
 * <p>判据（每条都能红）：</p>
 * <ol>
 *   <li><b>作用域只认会话</b>：请求里带 {@code worker_id} / {@code worker_name} / 别的工人参数
 *       ⇒ 服务层收到的仍是**会话解出的**身份（这些人参连一个读取点都没有）；</li>
 *   <li><b>无 / 失效 session ⇒ 401 且零读写</b>（fail-closed：匿名不能靠这个端点读任何人的钱）；</li>
 *   <li><b>只读</b>：本路径只暴露 GET（出现任何写动词 ⇒ 红）；</li>
 *   <li><b>零商家权限码</b>：{@code /api/worker/**} 下不得挂 {@code @RequirePermission}（工人恒 403）；</li>
 *   <li><b>期间透传</b>：{@code month} 原样交给服务端（月度算术只在服务端一处，端侧不推算）。</li>
 * </ol>
 */
@DisplayName("WorkerPieceworkController 工人「我的计件」读面（issue #6767）")
class WorkerPieceworkControllerTest extends BaseControllerTest {

    private static final String URL = "/api/worker/piecework";
    private static final String SESSION = "sess-worker-zhang";
    private static final String OTHER_WORKER = "worker-li";
    private static final WorkerIdentity ZHANG =
            new WorkerIdentity("worker-zhang", "张三", WorkerIdentity.SOURCE_SERVER_SESSION, SESSION);

    private ProductionService productionService;
    private WorkerSessionService workerSessionService;
    private MockMvc mockMvc;

    @BeforeEach
    void setUp() {
        productionService = mock(ProductionService.class);
        workerSessionService = mock(WorkerSessionService.class);
        when(workerSessionService.resolveIdentity(SESSION)).thenReturn(ZHANG);
        mockMvc = buildMockMvc(new WorkerPieceworkController(productionService, workerSessionService));
    }

    @Test
    @DisplayName("有效 session ⇒ 200 + 服务端读数原样下发（合计 / 期间 / 未定价块）")
    void returnsTheServerProjectionVerbatim() throws Exception {
        Map<String, Object> view = new LinkedHashMap<>();
        view.put("worker_name", "张三");
        view.put("period", "2026-10");
        view.put("amount_total", new java.math.BigDecimal("7.20"));
        view.put("unpriced", Map.of("qty", new java.math.BigDecimal("5")));
        when(productionService.workerPieceworkLedger(anyString(), anyString(), any(), any()))
                .thenReturn(view);

        mockMvc.perform(get(URL).header(WorkerSessionService.SESSION_HEADER, SESSION))
                .andExpect(status().isOk())
                // 金额逐值来自服务端（端侧自己求和 ⇒ 前端判据红；此处钉住「原样透传」）
                .andExpect(jsonPath("$.data.amount_total").value(7.20))
                .andExpect(jsonPath("$.data.period").value("2026-10"))
                .andExpect(jsonPath("$.data.unpriced.qty").value(5));
    }

    @Test
    @DisplayName("🔴 请求里带 worker_id / worker_name 不改变结果（作用域只由 session 解）")
    void bodyOrQueryWorkerIdCannotChangeTheResult() throws Exception {
        when(productionService.workerPieceworkLedger(anyString(), anyString(), any(), any()))
                .thenReturn(Map.of("amount_total", new java.math.BigDecimal("0.00")));

        mockMvc.perform(get(URL)
                        .param("worker_id", OTHER_WORKER)
                        .param("worker_name", "李四")
                        .param("workerId", OTHER_WORKER)
                        .header(WorkerSessionService.SESSION_HEADER, SESSION))
                .andExpect(status().isOk());

        // 服务层拿到的永远是会话里的身份（别人的 id / 名字连一个读取点都没有）
        verify(productionService).workerPieceworkLedger(
                eq(ZHANG.workerId()), eq(ZHANG.workerName()), isNull(), eq(TEST_TENANT_ID));
        verify(productionService, never()).workerPieceworkLedger(eq(OTHER_WORKER), anyString(), any(), any());
    }

    @Test
    @DisplayName("🔴 无 / 失效 session ⇒ 401，且**零**计件读写（不降级成匿名或请求体口径）")
    void invalidSessionIsRejectedWithoutTouchingAnyPiecework() throws Exception {
        when(workerSessionService.resolveIdentity(SESSION)).thenThrow(
                BusinessException.authFailed("尚未登录工人身份或登录已失效，请重新用工号 + PIN 登录"));

        mockMvc.perform(get(URL).header(WorkerSessionService.SESSION_HEADER, SESSION))
                .andExpect(status().isUnauthorized());

        when(workerSessionService.resolveIdentity(null)).thenThrow(
                BusinessException.authFailed("尚未登录工人身份或登录已失效，请重新用工号 + PIN 登录"));
        mockMvc.perform(get(URL)).andExpect(status().isUnauthorized());

        verify(productionService, never()).workerPieceworkLedger(any(), any(), any(), any());
    }

    @Test
    @DisplayName("期间由请求透传，月度算术只在服务端（month=YYYY-MM 原样交给服务层）")
    void monthIsPassedThroughToTheServer() throws Exception {
        when(productionService.workerPieceworkLedger(anyString(), anyString(), any(), any()))
                .thenReturn(Map.of("period", "2026-09"));

        mockMvc.perform(get(URL)
                        .param("month", "2026-09")
                        .header(WorkerSessionService.SESSION_HEADER, SESSION))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.period").value("2026-09"));

        verify(productionService).workerPieceworkLedger(
                eq(ZHANG.workerId()), eq(ZHANG.workerName()), eq("2026-09"), eq(TEST_TENANT_ID));
    }

    @Test
    @DisplayName("🔴 只读面：本路径只暴露 GET（任何写动词 ⇒ 红）")
    void onlyGetIsExposedOnThisPath() {
        for (Method method : WorkerPieceworkController.class.getDeclaredMethods()) {
            assertThat(method.getAnnotation(org.springframework.web.bind.annotation.PostMapping.class))
                    .as("工人计件面恒只读：%s 不得是写端点（不做确认 / 锁定 / 结算）", method.getName())
                    .isNull();
            assertThat(method.getAnnotation(org.springframework.web.bind.annotation.PutMapping.class))
                    .as("工人计件面恒只读：%s", method.getName()).isNull();
            assertThat(method.getAnnotation(org.springframework.web.bind.annotation.DeleteMapping.class))
                    .as("工人计件面恒只读：%s", method.getName()).isNull();
            assertThat(method.getAnnotation(org.springframework.web.bind.annotation.PatchMapping.class))
                    .as("工人计件面恒只读：%s", method.getName()).isNull();
        }
        assertThat(WorkerPieceworkController.class.getAnnotation(
                org.springframework.web.bind.annotation.RequestMapping.class).value())
                .containsExactly("/api/worker/piecework");
    }

    @Test
    @DisplayName("零商家权限注解：工人面不得挂 @RequirePermission（工人 permissions=[] ⇒ 挂上必 403）")
    void workerFaceCarriesNoMerchantPermissionAnnotation() {
        assertThat(WorkerPieceworkController.class.getAnnotation(RequirePermission.class)).isNull();
        for (Method method : WorkerPieceworkController.class.getDeclaredMethods()) {
            assertThat(method.getAnnotation(RequirePermission.class)).isNull();
        }
    }
}
