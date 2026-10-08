// case_ids: BM-001, BM-005, DF-017, BM-045
package com.migao.admin.controller;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.config.GlobalExceptionHandler;
import com.migao.admin.config.TenantDomainResolver;
import com.migao.admin.entity.Tenant;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.TenantMapper;
import com.migao.admin.worker.WorkerSessionService;
import com.migao.admin.worker.WorkerTenantResolver;
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
import org.springframework.test.web.servlet.MvcResult;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.util.LinkedHashMap;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
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
 * 工人认证端点契约测试（issue #4733；租户口径 issue #6564 = 用例 BM-045）。
 *
 * <p>锁五条：① 工号 + PIN ⇒ 200 + session 载荷（**改前无此端点** ⇒ 404，本测试必红）；
 * ② 凭据错 ⇒ 401（不静默放行）；③ 切换/登出把请求头里的旧 session 原样交给服务层；
 * ④ <b>租户只由服务端解析</b>（域名/网关头 → 企业编码 → {@code 工号@企业编码} → 兼容期 body tenantId）
 * —— 改前前端写死租户 1 ⇒ 租户 25 的工人在正确 PIN 下恒 401；
 * ⑤ <b>反枚举</b>：企业编码解析不出 ⇒ 与「凭据错」**逐字相同**的 401；只有完全没提供租户来源才是 422。</p>
 *
 * <p>红线（BM-045 判据 3）：工号**原样**传给服务层（不转小写、不套员工用户名正则）—— 工号无字符集约束，
 * 且服务端 {@code findWorkerByNo} 是 PG 大小写敏感等值匹配。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("WorkerAuthController 契约（工号+PIN 登录 / 切换 / 登出）")
class WorkerAuthControllerTest {

    private static final Long TENANT = 1L;
    /** 生产现场坐标（#6564）：租户 25 = 企业编码 migao。 */
    private static final Long TENANT_MIGAO = 25L;
    private static final String CODE_MIGAO = "migao";

    @Mock
    private WorkerSessionService workerSessionService;

    @Mock
    private TenantMapper tenantMapper;

    private MockMvc mockMvc;
    private final ObjectMapper objectMapper = new ObjectMapper();

    @BeforeEach
    void setUp() {
        // 真 WorkerTenantResolver + mock TenantMapper：解析优先级/切分口径必须测真实现（mock 掉就测不到）
        WorkerAuthController controller = new WorkerAuthController(
                workerSessionService,
                new WorkerTenantResolver(new TenantDomainResolver(), tenantMapper));
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

    /** 「企业编码 ⇒ 活跃租户」的库面替身（查库谓词由 WorkerTenantResolver 承担）。 */
    private void givenActiveTenant(String code, Long id) {
        when(tenantMapper.selectOne(any()))
                .thenReturn(Tenant.builder().id(id).code(code).status("active").build());
    }

    private static Map<String, Object> sessionPayload(String sessionId, String workerNo) {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("session_id", sessionId);
        payload.put("worker_id", "w-1");
        payload.put("worker_no", workerNo);
        payload.put("worker_name", "张三");
        payload.put("idle_minutes", 15);
        return payload;
    }

    /** 失败信封的 {@code error.message}（反枚举判据要比**逐字**相同）。 */
    private String errorMessageOf(MvcResult result) throws Exception {
        JsonNode body = objectMapper.readTree(result.getResponse().getContentAsString());
        return body.path("error").path("message").asText();
    }

    // ════════════════════════════════════════════ ① 基本登录 / 凭据错

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
                .thenThrow(BusinessException.authFailed(WorkerSessionService.AUTH_FAILED_MESSAGE));

        mockMvc.perform(post("/api/worker/login")
                        .header("X-Tenant-Id", "1")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"workerNo\":\"W001\",\"pin\":\"000000\"}"))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.success").value(false));
    }

    // ════════════════════════════════════════════ ② 租户解析优先级（BM-045 判据 1）

    @Test
    @DisplayName("🔴 企业编码解析出租户（#6564 主判据）：body enterpriseCode=migao ⇒ 服务层拿到租户 25")
    void loginResolvesTenantFromEnterpriseCode() throws Exception {
        givenActiveTenant(CODE_MIGAO, TENANT_MIGAO);
        when(workerSessionService.login(eq(TENANT_MIGAO), eq("cy-1001"), eq("246810"), isNull()))
                .thenReturn(sessionPayload("sess-25", "cy-1001"));

        mockMvc.perform(post("/api/worker/login")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"workerNo\":\"cy-1001\",\"pin\":\"246810\",\"enterpriseCode\":\"migao\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.session_id").value("sess-25"));

        verify(workerSessionService).login(TENANT_MIGAO, "cy-1001", "246810", null);
    }

    @Test
    @DisplayName("无任何租户来源 ⇒ 422 + 可行动文案，**不静默落入默认租户**（优先级 ⑤）")
    void loginWithoutTenantRejected() throws Exception {
        mockMvc.perform(post("/api/worker/login")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"workerNo\":\"W001\",\"pin\":\"246810\"}"))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.error.message")
                        .value("无法识别租户：请填写企业编码（向商家索取，例如 migao）"));

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
                .andExpect(status().isUnprocessableEntity());

        verify(workerSessionService, never()).login(any(), any(), any(), any());
    }

    @Test
    @DisplayName("① 优先于 ②：X-Tenant-Id=1 时 body 企业编码不改变租户（可信来源是权威）")
    void trustedHeaderWinsOverBodyEnterpriseCode() throws Exception {
        when(workerSessionService.login(eq(TENANT), eq("W001"), eq("246810"), isNull()))
                .thenReturn(sessionPayload("s", "W001"));

        mockMvc.perform(post("/api/worker/login")
                        .header("X-Tenant-Id", "1")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"workerNo\":\"W001\",\"pin\":\"246810\",\"enterpriseCode\":\"migao\"}"))
                .andExpect(status().isOk());

        verify(workerSessionService).login(TENANT, "W001", "246810", null);
        verify(tenantMapper, never()).selectOne(any());
    }

    @Test
    @DisplayName("兼容期兜底（④）：只送 body tenantId ⇒ 仍按它解析（已缓存旧包的回归保护）")
    void compatBodyTenantIdStillAccepted() throws Exception {
        when(workerSessionService.login(eq(TENANT_MIGAO), eq("cy-1001"), eq("246810"), isNull()))
                .thenReturn(sessionPayload("s", "cy-1001"));

        mockMvc.perform(post("/api/worker/login")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"workerNo\":\"cy-1001\",\"pin\":\"246810\",\"tenantId\":25}"))
                .andExpect(status().isOk());

        verify(workerSessionService).login(TENANT_MIGAO, "cy-1001", "246810", null);
        verify(tenantMapper, never()).selectOne(any());
    }

    // ════════════════════════════════════════════ ③ 反枚举（BM-045 判据 2）

    @Test
    @DisplayName("🔴 企业编码解析不出 ⇒ 与「凭据错」**逐字相同**的 401 同一文案（不泄露企业是否存在）")
    void unknownEnterpriseCodeSharesCredentialFailureText() throws Exception {
        // ① 凭据错（服务层抛）
        when(workerSessionService.login(any(), any(), any(), any()))
                .thenThrow(BusinessException.authFailed(WorkerSessionService.AUTH_FAILED_MESSAGE));
        String credentials = errorMessageOf(mockMvc.perform(post("/api/worker/login")
                        .header("X-Tenant-Id", "1")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"workerNo\":\"cy-1001\",\"pin\":\"000000\"}"))
                .andExpect(status().isUnauthorized())
                .andReturn());

        // ② 企业编码存在性有问题（查不到活跃租户）—— 服务层一次都不调用
        when(tenantMapper.selectOne(any())).thenReturn(null);
        String unknownEnterprise = errorMessageOf(mockMvc.perform(post("/api/worker/login")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"workerNo\":\"cy-1001\",\"pin\":\"246810\",\"enterpriseCode\":\"nosuchenterprise\"}"))
                .andExpect(status().isUnauthorized())
                .andReturn());

        assertThat(unknownEnterprise).isEqualTo(credentials);
        assertThat(unknownEnterprise).isEqualTo(WorkerSessionService.AUTH_FAILED_MESSAGE);
    }

    // ════════════════════════════════════════════ ④ 工号@企业编码（BM-045 判据 3）

    @Test
    @DisplayName("工号@企业编码：切掉后缀、租户取后缀里的企业编码")
    void workerNoWithEnterpriseSuffixResolvesTenantAndStripsSuffix() throws Exception {
        givenActiveTenant(CODE_MIGAO, TENANT_MIGAO);
        when(workerSessionService.login(eq(TENANT_MIGAO), eq("cy-1001"), eq("246810"), isNull()))
                .thenReturn(sessionPayload("s", "cy-1001"));

        mockMvc.perform(post("/api/worker/login")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"workerNo\":\"cy-1001@migao\",\"pin\":\"246810\"}"))
                .andExpect(status().isOk());

        verify(workerSessionService).login(TENANT_MIGAO, "cy-1001", "246810", null);
    }

    @Test
    @DisplayName("🔴 工号**原样**（不转小写）：CY-1001@migao ⇒ 传给服务层的工号逐字是 CY-1001")
    void uppercaseWorkerNoKeptVerbatim() throws Exception {
        givenActiveTenant(CODE_MIGAO, TENANT_MIGAO);
        when(workerSessionService.login(eq(TENANT_MIGAO), eq("CY-1001"), eq("246810"), isNull()))
                .thenReturn(sessionPayload("s", "CY-1001"));

        mockMvc.perform(post("/api/worker/login")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"workerNo\":\"CY-1001@migao\",\"pin\":\"246810\"}"))
                .andExpect(status().isOk());

        // 红证：把切分改成整体复用 LoginIdentifiers.split ⇒ 这里会变成 "cy-1001"（大小写敏感等值匹配查不到那一行）
        verify(workerSessionService).login(TENANT_MIGAO, "CY-1001", "246810", null);
    }

    @Test
    @DisplayName("🔴 租户来自可信域名/网关头时，工号里的 @企业编码 后缀照样剥掉（否则等值匹配查不到 ⇒ 假 401）")
    void trustedHeaderStillStripsSuffix() throws Exception {
        when(workerSessionService.login(eq(TENANT_MIGAO), eq("cy-1001"), eq("246810"), isNull()))
                .thenReturn(sessionPayload("s", "cy-1001"));

        mockMvc.perform(post("/api/worker/login")
                        .header("X-Tenant-Id", "25")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"workerNo\":\"cy-1001@migao\",\"pin\":\"246810\"}"))
                .andExpect(status().isOk());

        verify(workerSessionService).login(TENANT_MIGAO, "cy-1001", "246810", null);
        verify(tenantMapper, never()).selectOne(any());
    }

    @Test
    @DisplayName("后缀不是合法企业编码形态 ⇒ 该档「未命中」：仍按 body tenantId 兜底（不是 401）")
    void malformedSuffixFallsThroughToCompatTenantId() throws Exception {
        when(workerSessionService.login(eq(TENANT_MIGAO), eq("cy-1001@!"), eq("246810"), isNull()))
                .thenReturn(sessionPayload("s", "cy-1001@!"));

        mockMvc.perform(post("/api/worker/login")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"workerNo\":\"cy-1001@!\",\"pin\":\"246810\",\"tenantId\":25}"))
                .andExpect(status().isOk());

        verify(workerSessionService).login(TENANT_MIGAO, "cy-1001@!", "246810", null);
        verify(tenantMapper, never()).selectOne(any());
    }

    // ════════════════════════════════════════════ ⑤ 切换 / 登出 / 当前工人

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
    @DisplayName("🔴 切换工人同样按企业编码解析租户（改前恒租户 1）")
    void switchWorkerResolvesTenantFromEnterpriseCode() throws Exception {
        givenActiveTenant(CODE_MIGAO, TENANT_MIGAO);
        when(workerSessionService.switchWorker(eq(TENANT_MIGAO), eq("sess-old"), eq("cy-1002"), eq("135790"), isNull()))
                .thenReturn(Map.of("session_id", "sess-new", "worker_id", "w-2", "worker_no", "cy-1002"));

        mockMvc.perform(post("/api/worker/session/switch")
                        .header(WorkerSessionService.SESSION_HEADER, "sess-old")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"workerNo\":\"cy-1002\",\"pin\":\"135790\",\"enterpriseCode\":\"migao\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.session_id").value("sess-new"));

        verify(workerSessionService).switchWorker(TENANT_MIGAO, "sess-old", "cy-1002", "135790", null);
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
}
