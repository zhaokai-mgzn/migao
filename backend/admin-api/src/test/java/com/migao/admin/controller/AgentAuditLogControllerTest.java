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
 * AgentAuditLogController 写审计落库端点测试（issue #4039；字段语义见 issue #4071 裁定 ①）。
 *
 * POST /api/admin/agent/audit-logs —— ai-agent-service 的写工具执行结果落 audit_logs。
 * 关键口径：
 * - 身份（tenant_id / user_id）一律取自**认证上下文**（X-Tenant-Id / X-User-Id 透传后由
 *   ServiceTokenFilter 写入 SecurityUser），**body 无法伪造**；
 * - **action = 动作动词**（update_status / confirm_payment …）、**toolName = 工具名**
 *   （迁移 V52 的 tool_name 列）、resource_type = agent_tool（区分 AI 与人工审计）。
 *   此前工具名塞在 action 里、靠 resource_type 反推语义 —— 那是「同一列两种语义」；
 * - actionDetails 整份透传（含 PII 脱敏后的 params / success / durationMs / role / sessionId）。
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("AgentAuditLogController 写审计落库端点")
class AgentAuditLogControllerTest extends BaseControllerTest {

    private static final String PATH = "/api/admin/agent/audit-logs";

    private static final String BODY = """
            {
              "action": "update_status",
              "toolName": "order_manage",
              "resourceType": "agent_tool",
              "actionDetails": {
                "action": "update_status",
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
        @DisplayName("action=动词 且 toolName=工具名分列落库（issue #4071 裁定 ①）")
        void persistsActionAsVerbAndToolNameSeparately() throws Exception {
            mockMvc.perform(post(PATH).contentType(MediaType.APPLICATION_JSON).content(BODY))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.success").value(true));

            ArgumentCaptor<Object> details = ArgumentCaptor.forClass(Object.class);
            // recordLog(tenantId, userId, userName, action, resourceType, toolName,
            //           resourceId, resourceName, details, ipAddress, userAgent)
            // ⚠️ action 收 "update_status"（动词）、toolName 收 "order_manage"（工具名）——
            //    若实现把工具名塞回 action，本 verify 立即失败（= 裁定 ① 的红证）
            verify(auditLogService).recordLog(
                    eq(TEST_TENANT_ID), eq(TEST_USER_ID), isNull(), eq("update_status"),
                    eq("agent_tool"), eq("order_manage"), isNull(), isNull(),
                    details.capture(), isNull(), isNull());

            @SuppressWarnings("unchecked")
            Map<String, Object> captured = (Map<String, Object>) details.getValue();
            assertEquals(true, captured.get("success"));
            assertEquals("sess-audit-1", captured.get("sessionId"));
            // PII 纪律：出网/落库的参数只有字段名与类型占位
            @SuppressWarnings("unchecked")
            Map<String, Object> params = (Map<String, Object>) captured.get("params");
            assertEquals("<str>", params.get("phone"));
            assertEquals("<str>", params.get("address"));
        }

        @Test
        @DisplayName("工具名绝不落进 action：action=动词 且 toolName=工具名（防语义复发）")
        void toolNameNeverLandsInActionField() throws Exception {
            mockMvc.perform(post(PATH).contentType(MediaType.APPLICATION_JSON).content(BODY))
                    .andExpect(status().isOk());

            // 两个字段分别等于各自的真值 —— 相等即说明工具名又回到了 action 列
            verify(auditLogService).recordLog(
                    eq(TEST_TENANT_ID), eq(TEST_USER_ID), isNull(), eq("update_status"),
                    eq("agent_tool"), eq("order_manage"), isNull(), isNull(), any(),
                    isNull(), isNull());
            verify(auditLogService, never()).recordLog(
                    any(), any(), any(), eq("order_manage"), any(), any(), any(), any(),
                    any(), any(), any());
        }

        @Test
        @DisplayName("响应回带 action/toolName（调用方可确认落库形态）")
        void responseEchoesActionAndToolName() throws Exception {
            mockMvc.perform(post(PATH).contentType(MediaType.APPLICATION_JSON).content(BODY))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.data.action").value("update_status"))
                    .andExpect(jsonPath("$.data.toolName").value("order_manage"));
        }

        @Test
        @DisplayName("Service Token 透传的真实用户优先于占位身份（X-User-Id → user_id）")
        void serviceTokenRealUserWins() throws Exception {
            setServiceUserWithRealId("customer-0001");

            mockMvc.perform(post(PATH).contentType(MediaType.APPLICATION_JSON).content(BODY))
                    .andExpect(status().isOk());

            verify(auditLogService).recordLog(
                    eq(TEST_TENANT_ID), eq("customer-0001"), isNull(), eq("update_status"),
                    eq("agent_tool"), eq("order_manage"), isNull(), isNull(), any(),
                    isNull(), isNull());
        }

        @Test
        @DisplayName("body 里的 userId/tenantId 被忽略：身份只认认证上下文（防伪造）")
        void bodyIdentityIsIgnored() throws Exception {
            String forged = """
                    {"action": "create", "toolName": "order_create",
                     "resourceType": "agent_tool",
                     "userId": "attacker-001", "tenantId": 999,
                     "actionDetails": {"success": true}}
                    """;

            mockMvc.perform(post(PATH).contentType(MediaType.APPLICATION_JSON).content(forged))
                    .andExpect(status().isOk());

            verify(auditLogService).recordLog(
                    eq(TEST_TENANT_ID), eq(TEST_USER_ID), isNull(), eq("create"),
                    eq("agent_tool"), eq("order_create"), isNull(), isNull(), any(),
                    isNull(), isNull());
        }

        @Test
        @DisplayName("缺 action ⇒ 422 且不落库（防 audit_logs.action NOT NULL 打 500）")
        void blankActionRejected() throws Exception {
            mockMvc.perform(post(PATH).contentType(MediaType.APPLICATION_JSON)
                            .content("{\"toolName\":\"order_manage\",\"resourceType\":\"agent_tool\"}"))
                    .andExpect(status().isUnprocessableEntity());

            verify(auditLogService, never()).recordLog(
                    any(), any(), any(), any(), any(), any(), any(), any(), any(), any(), any());
        }

        @Test
        @DisplayName("R2 负例：失败写（success=false）同样落库，不被拒")
        void failedWriteAuditAccepted() throws Exception {
            String failed = """
                    {"action": "toggle_status", "toolName": "product_manage",
                     "resourceType": "agent_tool",
                     "actionDetails": {"action": "toggle_status", "params": {"id": "<str>"},
                                       "success": false, "durationMs": 0.4, "role": "agent",
                                       "sessionId": "s2"}}
                    """;

            mockMvc.perform(post(PATH).contentType(MediaType.APPLICATION_JSON).content(failed))
                    .andExpect(status().isOk());

            ArgumentCaptor<Object> details = ArgumentCaptor.forClass(Object.class);
            verify(auditLogService).recordLog(
                    eq(TEST_TENANT_ID), eq(TEST_USER_ID), isNull(), eq("toggle_status"),
                    eq("agent_tool"), eq("product_manage"), isNull(), isNull(),
                    details.capture(), isNull(), isNull());

            @SuppressWarnings("unchecked")
            Map<String, Object> captured = (Map<String, Object>) details.getValue();
            assertEquals(false, captured.get("success"));
            assertEquals("s2", captured.get("sessionId"));
        }
    }
}