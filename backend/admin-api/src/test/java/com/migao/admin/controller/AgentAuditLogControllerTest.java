// case_ids: RG-001
package com.migao.admin.controller;

import com.migao.admin.controller.agent.AgentAuditLogController;
import com.migao.admin.security.SecurityUser;
import com.migao.admin.service.AuditLogService;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.MediaType;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.test.web.servlet.MockMvc;

import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * AgentAuditLogController 写审计落库端点测试（issue #4039）。
 *
 * POST /api/admin/agent/audit-logs —— ai-agent-service 的写工具执行结果落 audit_logs。
 * 关键口径：
 * - 身份（tenant_id / user_id）一律取自**认证上下文**（X-Tenant-Id / X-User-Id 透传后由
 *   ServiceTokenFilter 写入 SecurityUser），**body 无法伪造**；
 * - action = 工具名（如 order_create）、resource_type = agent_tool（区分 AI 与人工审计）；
 * - actionDetails 整份透传（含 PII 脱敏后的 params / success / durationMs / role / sessionId）。
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("AgentAuditLogController 写审计落库端点")
class AgentAuditLogControllerTest extends BaseControllerTest {

    private static final String PATH = "/api/admin/agent/audit-logs";

    private static final String BODY = """
            {
              "action": "order_create",
              "resourceType": "agent_tool",
              "actionDetails": {
                "params": {"phone": "<str>", "address": "<str>"},
                "success": true,
                "durationMs": 12.5,
                "role": "admin",
                "sessionId": "sess-audit-1"
              }
            }
            """;

    private MockMvc mockMvc;

    @Mock
    private AuditLogService auditLogService;

    @InjectMocks
    private AgentAuditLogController agentAuditLogController;

    @BeforeEach
    void setUp() {
        super.baseSetUp();
        mockMvc = buildMockMvc(agentAuditLogController);
    }

    @AfterEach
    @Override
    void baseTearDown() {
        super.baseTearDown();
    }

    /** 模拟 ServiceTokenFilter 透传真实用户（X-User-Id）后的 SecurityContext */
    private void setServiceUserWithRealId(String realUserId) {
        SecurityUser user = new SecurityUser(
                realUserId, TEST_TENANT_ID, "internal-service",
                List.of("service"),
                List.of(new SimpleGrantedAuthority("ROLE_SERVICE"))
        );
        Authentication auth = mock(Authentication.class);
        when(auth.isAuthenticated()).thenReturn(true);
        when(auth.getPrincipal()).thenReturn(user);
        SecurityContextHolder.getContext().setAuthentication(auth);
    }

    @Nested
    @DisplayName("POST /api/admin/agent/audit-logs — 写审计落库")
    class RecordEndpoint {

        @Test
        @DisplayName("写审计按认证身份落库：action=工具名、tenant/user 取自上下文、细节整份透传")
        void persistsWithAuthenticatedIdentity() throws Exception {
            mockMvc.perform(post(PATH).contentType(MediaType.APPLICATION_JSON).content(BODY))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.success").value(true));

            ArgumentCaptor<Object> details = ArgumentCaptor.forClass(Object.class);
            verify(auditLogService).recordLog(
                    eq(TEST_TENANT_ID), eq(TEST_USER_ID), isNull(), eq("order_create"),
                    eq("agent_tool"), isNull(), isNull(), details.capture(), isNull(), isNull());

            @SuppressWarnings("unchecked")
            Map<String, Object> captured = (Map<String, Object>) details.getValue();
            assertEquals(true, captured.get("success"));
            assertEquals("sess-audit-1", captured.get("sessionId"));
            // PII 纪律：出网/落库的参数只有字段名与类型占位
            assertEquals(Map.of("phone", "<str>", "address", "<str>"), captured.get("params"));
        }

        @Test
        @DisplayName("Service Token 透传的真实用户优先于占位身份（X-User-Id → user_id）")
        void serviceTokenRealUserWins() throws Exception {
            setServiceUserWithRealId("customer-0001");

            mockMvc.perform(post(PATH).contentType(MediaType.APPLICATION_JSON).content(BODY))
                    .andExpect(status().isOk());

            verify(auditLogService).recordLog(
                    eq(TEST_TENANT_ID), eq("customer-0001"), isNull(), eq("order_create"),
                    eq("agent_tool"), isNull(), isNull(), any(), isNull(), isNull());
        }

        @Test
        @DisplayName("body 里的 userId/tenantId 被忽略：身份只认认证上下文（防伪造）")
        void bodyIdentityIsIgnored() throws Exception {
            String forged = """
                    {"action": "order_create", "resourceType": "agent_tool",
                     "userId": "attacker-001", "tenantId": 999,
                     "actionDetails": {"success": true}}
                    """;

            mockMvc.perform(post(PATH).contentType(MediaType.APPLICATION_JSON).content(forged))
                    .andExpect(status().isOk());

            verify(auditLogService).recordLog(
                    eq(TEST_TENANT_ID), eq(TEST_USER_ID), isNull(), eq("order_create"),
                    eq("agent_tool"), isNull(), isNull(), any(), isNull(), isNull());
        }

        @Test
        @DisplayName("缺 action ⇒ 422 且不落库（防 audit_logs.action NOT NULL 打 500）")
        void blankActionRejected() throws Exception {
            mockMvc.perform(post(PATH).contentType(MediaType.APPLICATION_JSON)
                            .content("{\"resourceType\":\"agent_tool\"}"))
                    .andExpect(status().isUnprocessableEntity());

            verify(auditLogService, never()).recordLog(
                    any(), any(), any(), any(), any(), any(), any(), any(), any(), any());
        }

        @Test
        @DisplayName("R2 负例：只读工具派生出的上报形态（success=false）同样落库，不被拒")
        void failedWriteAuditAccepted() throws Exception {
            String failed = """
                    {"action": "product_manage", "resourceType": "agent_tool",
                     "actionDetails": {"params": {"id": "<str>"}, "success": false,
                                       "durationMs": 0.4, "role": "agent", "sessionId": "s2"}}
                    """;

            mockMvc.perform(post(PATH).contentType(MediaType.APPLICATION_JSON).content(failed))
                    .andExpect(status().isOk());

            ArgumentCaptor<Object> details = ArgumentCaptor.forClass(Object.class);
            verify(auditLogService).recordLog(
                    eq(TEST_TENANT_ID), eq(TEST_USER_ID), isNull(), eq("product_manage"),
                    eq("agent_tool"), isNull(), isNull(), details.capture(), isNull(), isNull());

            @SuppressWarnings("unchecked")
            Map<String, Object> captured = (Map<String, Object>) details.getValue();
            assertEquals(false, captured.get("success"));
            assertEquals("s2", captured.get("sessionId"));
        }
    }
}