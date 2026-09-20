// case_ids: BM-001, BM-005, DF-017
package com.migao.admin.controller;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.config.GlobalExceptionHandler;
import com.migao.admin.config.TenantDomainResolver;
import com.migao.admin.exception.BusinessException;
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
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.util.LinkedHashMap;
import java.util.Map;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * 工人认证端点契约测试（issue #4733）。
 *
 * <p>锁三条：① 工号 + PIN ⇒ 200 + session 载荷（**改前无此端点** ⇒ 404，本测试必红）；
 * ② 凭据错 ⇒ 401（不静默放行）；③ 切换/登出把请求头里的旧 session 原样交给服务层
 * （旧会话立即失效由服务层保证）。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("WorkerAuthController 契约（工号+PIN 登录 / 切换 / 登出）")
class WorkerAuthControllerTest {

    private static final Long TENANT = 1L;

    @Mock
    private WorkerSessionService workerSessionService;

    private MockMvc mockMvc;
    private final ObjectMapper objectMapper = new ObjectMapper();

    @BeforeEach
    void setUp() {
        WorkerAuthController controller =
                new WorkerAuthController(workerSessionService, new TenantDomainResolver());
        // 显式装 Validator：standaloneSetup 默认不校验 @Valid（不装的话「空工号/PIN」会穿到服务层，
        // 断言 400 就变成假绿/假红 —— 本仓最忌的「门禁看起来在跑其实没跑」）
        mockMvc = MockMvcBuilders.standaloneSetup(controller)
                .setControllerAdvice(new GlobalExceptionHandler())
                .setValidator(new org.springframework.validation.beanvalidation.LocalValidatorFactoryBean())
                .build();
    }

    @AfterEach
    void tearDown() {
        com.migao.admin.config.TenantContext.clear();
    }

    @Test
    @DisplayName("POST /api/worker/login 工号 + PIN ⇒ 200 + session_id/工号/姓名（租户由 X-Tenant-Id 头解析）")
    void loginIssuesWorkerSession() throws Exception {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("session_id", "sess-1");
        payload.put("worker_id", "w-1");
        payload.put("worker_no", "W001");
        payload.put("worker_name", "张三");
        payload.put("idle_minutes", 15);
        when(workerSessionService.login(eq(TENANT), eq("W001"), eq("246810"), eq("PAD-01")))
                .thenReturn(payload);

        mockMvc.perform(post("/api/worker/login")
                        .header("X-Tenant-Id", "1")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"workerNo\":\"W001\",\"pin\":\"246810\",\"deviceLabel\":\"PAD-01\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.session_id").value("sess-1"))
                .andExpect(jsonPath("$.data.worker_name").value("张三"));

        verify(workerSessionService).login(TENANT, "W001", "246810", "PAD-01");
    }

    @Test
    @DisplayName("凭据错 ⇒ 401（服务层 authFailed 透传；不静默签发会话）")
    void loginWithBadCredentialReturns401() throws Exception {
        when(workerSessionService.login(any(), any(), any(), any()))
                .thenThrow(BusinessException.authFailed("工号或 PIN 不正确"));

        mockMvc.perform(post("/api/worker/login")
                        .header("X-Tenant-Id", "1")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"workerNo\":\"W001\",\"pin\":\"000000\"}"))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.success").value(false));
    }

    @Test
    @DisplayName("无租户（域名/网关头/body 都没有）⇒ 422，**不静默落入默认租户**")
    void loginWithoutTenantRejected() throws Exception {
        mockMvc.perform(post("/api/worker/login")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"workerNo\":\"W001\",\"pin\":\"246810\"}"))
                .andExpect(status().isUnprocessableEntity());

        verify(workerSessionService, never()).login(any(), any(), any(), any());
    }

    @Test
    @DisplayName("空工号/PIN ⇒ 422（@Valid 兜底 + 本仓字段校验统一 422；不进服务层）")
    void loginWithBlankFieldsRejected() throws Exception {
        // ⚠️ 必须带租户头：否则先撞「无法识别租户」的 422（那条判据由 loginWithoutTenantRejected 覆盖），
        // 本用例要锁的是**字段级**校验，两个失败原因混在一起会让断言失去判别性
        mockMvc.perform(post("/api/worker/login")
                        .header("X-Tenant-Id", "1")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"workerNo\":\"\",\"pin\":\"\"}"))
                // 本仓字段级校验统一 422（GlobalExceptionHandler.handleValidationException），
                // 与「无法识别租户」的 422 同码 —— 故判别性由下面的 never() 承担
                .andExpect(status().isUnprocessableEntity());

        verify(workerSessionService, never()).login(any(), any(), any(), any());
    }

    @Test
    @DisplayName("快速切换：旧 session 随 X-Worker-Session-Id 交给服务层（服务层据此结束旧会话）")
    void switchPassesCurrentSessionId() throws Exception {
        when(workerSessionService.switchWorker(eq(TENANT), eq("sess-old"), eq("W002"), eq("135790"), isNull()))
                .thenReturn(Map.of("session_id", "sess-new", "worker_id", "w-2", "worker_no", "W002"));

        mockMvc.perform(post("/api/worker/session/switch")
                        .header("X-Tenant-Id", "1")
                        .header(WorkerSessionService.SESSION_HEADER, "sess-old")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"workerNo\":\"W002\",\"pin\":\"135790\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.session_id").value("sess-new"));

        verify(workerSessionService).switchWorker(TENANT, "sess-old", "W002", "135790", null);
    }

    @Test
    @DisplayName("登出：把 session 交给服务层（幂等），空 session 也不报错")
    void logoutDelegatesToService() throws Exception {
        mockMvc.perform(post("/api/worker/session/logout")
                        .header(WorkerSessionService.SESSION_HEADER, "sess-1"))
                .andExpect(status().isOk());
        verify(workerSessionService).logout("sess-1");

        mockMvc.perform(post("/api/worker/session/logout")).andExpect(status().isOk());
        verify(workerSessionService).logout(null);
    }

    @Test
    @DisplayName("「当前工人」无 session ⇒ 401（不返回任何工人信息）")
    void currentWithoutSessionRejected() throws Exception {
        mockMvc.perform(post("/api/worker/session/current"))
                .andExpect(status().isUnauthorized());
        verify(workerSessionService, never()).currentWorker(any());
    }

    @Test
    @DisplayName("「当前工人」有 session ⇒ 200 + 姓名（页头「当前工人：张三」的数据源）")
    void currentReturnsWorkerFromServerSession() throws Exception {
        when(workerSessionService.currentWorker("sess-1"))
                .thenReturn(Map.of("worker_name", "张三", "worker_no", "W001", "session_id", "sess-1"));

        mockMvc.perform(post("/api/worker/session/current")
                        .header(WorkerSessionService.SESSION_HEADER, "sess-1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.worker_name").value("张三"));
    }

    /** 让 ObjectMapper 字段不报未使用（与既有测试同款）。 */
    @SuppressWarnings("unused")
    private String unusedJson(Object value) throws Exception {
        return objectMapper.writeValueAsString(value);
    }
}
