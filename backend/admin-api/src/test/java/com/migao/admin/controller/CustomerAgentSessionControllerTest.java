package com.migao.admin.controller;

import com.migao.admin.dto.AgentMessageResponse;
import com.migao.admin.dto.AgentSessionDetailResponse;
import com.migao.admin.entity.AgentMessage;
import com.migao.admin.service.AgentSessionService;
import org.junit.jupiter.api.AfterEach;
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

import java.time.OffsetDateTime;
import java.util.List;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;
// case_ids: CH-008

/**
 * CustomerAgentSessionController 单元测试
 * 覆盖：用户按 AI 会话查人工会话（by-ai）、用户发消息（POST /{id}/messages）
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("CustomerAgentSessionController 用户端人工会话测试")
class CustomerAgentSessionControllerTest extends BaseControllerTest {

    private MockMvc mockMvc;

    @Mock
    private AgentSessionService agentSessionService;

    @InjectMocks
    private CustomerAgentSessionController customerAgentSessionController;

    private static final String BASE = "/api/customer/agent-sessions";

    @BeforeEach
    void setUp() {
        super.baseSetUp();
        mockMvc = buildMockMvc(customerAgentSessionController);
        // 设置认证用户（getCurrentUserId 依赖 SecurityContext）
        setAdminUser();
    }

    @AfterEach
    void tearDown() {
        super.baseTearDown();
    }

    @Test
    @DisplayName("用户按 AI 会话查询人工会话成功")
    void getByAiSession_Success() throws Exception {
        AgentSessionDetailResponse detail = AgentSessionDetailResponse.builder()
                .id("agent-sess-001")
                .aiSessionId("ai-001")
                .status("active")
                .messages(List.of())
                .build();
        when(agentSessionService.getSessionByAiSessionId("ai-001", TEST_USER_ID))
                .thenReturn(detail);

        mockMvc.perform(get(BASE + "/by-ai/ai-001"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.id").value("agent-sess-001"))
                .andExpect(jsonPath("$.data.status").value("active"));
    }

    @Test
    @DisplayName("用户发送人工会话消息成功")
    void sendMessage_Success() throws Exception {
        AgentMessage msg = AgentMessage.builder()
                .id("msg-001")
                .tenantId(1L)
                .sessionId("agent-sess-001")
                .senderType("customer")
                .senderId(TEST_USER_ID)
                .contentType("text")
                .content("请问我的订单处理得怎么样了？")
                .createdAt(OffsetDateTime.now())
                .build();
        when(agentSessionService.sendMessage(
                eq("agent-sess-001"), eq("customer"), eq(TEST_USER_ID), any(String.class), any(Boolean.class)))
                .thenReturn(msg);

        mockMvc.perform(post(BASE + "/agent-sess-001/messages")
                        .contentType("application/json")
                        .content("{\"content\":\"请问我的订单处理得怎么样了？\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.content").value("请问我的订单处理得怎么样了？"))
                .andExpect(jsonPath("$.data.senderType").value("customer"));

        verify(agentSessionService).sendMessage(
                eq("agent-sess-001"), eq("customer"), eq(TEST_USER_ID), any(String.class), any(Boolean.class));
    }
}
