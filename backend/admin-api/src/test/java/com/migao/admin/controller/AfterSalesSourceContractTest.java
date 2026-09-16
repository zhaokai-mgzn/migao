// case_ids: AS-002, AS-003, AS-005
package com.migao.admin.controller;

import com.migao.admin.controller.agent.AgentAfterSalesController;
import com.migao.admin.dto.AfterSalesCreateRequest;
import com.migao.admin.dto.AfterSalesDetailResponse;
import com.migao.admin.dto.agent.AgentAfterSalesCreateRequest;
import com.migao.admin.service.AfterSalesTicketService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import java.time.OffsetDateTime;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * 售后工单来源（source）入口契约测试 —— issue #3686
 *
 * 服务端<b>不再硬编码</b> source（原 AfterSalesTicketService:348 无条件 setSource("agent")）：
 * - 表单入口 POST /api/admin/after-sales → 人工建单 = {@code merchant}（该 URL 仅 admin-web 挂载）；
 * - Agent BFF 入口 POST /api/admin/agent/after-sales → 由内部调用方经 {@code X-Agent-Client}
 *   声明（customer/agent/merchant），缺省回退 {@code agent}（= 既有行为，向后兼容）。
 *
 * 这两条断言是「入口 → source」绑定的唯一机器判据；落库断言在
 * AfterSalesTicketServiceTest#createTicket_writesRealSource_* 中（断言 insert 实体字段）。
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("售后工单 source 入口契约（issue #3686）")
class AfterSalesSourceContractTest extends BaseControllerTest {

    /** 内部调用方身份声明头：值 ∈ {customer, agent, merchant} */
    private static final String CLIENT_HEADER = "X-Agent-Client";
    private static final String FORM = "/api/admin/after-sales";
    private static final String AGENT_BFF = "/api/admin/agent/after-sales";

    @Mock
    private AfterSalesTicketService afterSalesTicketService;

    @InjectMocks
    private AfterSalesController afterSalesController;

    @InjectMocks
    private AgentAfterSalesController agentAfterSalesController;

    private MockMvc formMvc;
    private MockMvc agentBffMvc;

    @BeforeEach
    void setUp() {
        super.baseSetUp();
        formMvc = buildMockMvc(afterSalesController);
        agentBffMvc = buildMockMvc(agentAfterSalesController);
    }

    @Override
    @org.junit.jupiter.api.AfterEach
    void baseTearDown() {
        super.baseTearDown();
    }

    private AfterSalesDetailResponse stubDetail() {
        AfterSalesDetailResponse d = new AfterSalesDetailResponse();
        d.setId("ticket-src-001");
        d.setTicketNo("AS20260914001");
        d.setTicketType("return");
        d.setStatus("pending");
        d.setCreatedAt(OffsetDateTime.now());
        d.setUpdatedAt(OffsetDateTime.now());
        return d;
    }

    // ==================== 表单入口（人工建单） ====================

    @Test
    @DisplayName("表单入口 POST /api/admin/after-sales → source=merchant（人工建单）")
    void formEntry_isMerchant() throws Exception {
        when(afterSalesTicketService.createTicket(any(AfterSalesCreateRequest.class), eq(TEST_TENANT_ID),
                anyString(), anyString())).thenReturn(stubDetail());

        mockMvcPerform(formMvc, FORM, """
                {"orderId":"order-001","ticketType":"return","description":"人工后台建单"}
                """);

        verify(afterSalesTicketService).createTicket(any(AfterSalesCreateRequest.class), eq(TEST_TENANT_ID),
                anyString(), eq("merchant"));
    }

    // ==================== Agent BFF 入口（客户端声明） ====================
    // 该端点走 createTicketForAgent（BFF 负责 orderId 解析），source 由 Controller
    // 从 X-Agent-Client 头解析后透传 ⇒ 断言它收到的第 4 个实参。

    @Test
    @DisplayName("Agent BFF + X-Agent-Client: customer（C 端小布）→ source=customer")
    void agentBff_customer() throws Exception {
        when(afterSalesTicketService.createTicketForAgent(any(AgentAfterSalesCreateRequest.class),
                eq(TEST_TENANT_ID), anyString(), anyString())).thenReturn(stubDetail());

        mockMvcPerform(agentBffMvc, AGENT_BFF, """
                {"orderId":"order-001","ticketType":"return","reason":"客户申请退货"}
                """, CLIENT_HEADER, "customer");

        verify(afterSalesTicketService).createTicketForAgent(any(AgentAfterSalesCreateRequest.class),
                eq(TEST_TENANT_ID), anyString(), eq("customer"));
    }

    @Test
    @DisplayName("Agent BFF + X-Agent-Client: agent（米宝 AI 建单）→ source=agent")
    void agentBff_agent() throws Exception {
        when(afterSalesTicketService.createTicketForAgent(any(AgentAfterSalesCreateRequest.class),
                eq(TEST_TENANT_ID), anyString(), anyString())).thenReturn(stubDetail());

        mockMvcPerform(agentBffMvc, AGENT_BFF, """
                {"orderId":"order-001","ticketType":"return","reason":"商家让 AI 建单"}
                """, CLIENT_HEADER, "agent");

        verify(afterSalesTicketService).createTicketForAgent(any(AgentAfterSalesCreateRequest.class),
                eq(TEST_TENANT_ID), anyString(), eq("agent"));
    }

    @Test
    @DisplayName("Agent BFF 缺发 X-Agent-Client → 保守回退 agent（不改变既有行为）")
    void agentBff_missingHeader_defaultsAgent() throws Exception {
        when(afterSalesTicketService.createTicketForAgent(any(AgentAfterSalesCreateRequest.class),
                eq(TEST_TENANT_ID), anyString(), anyString())).thenReturn(stubDetail());

        mockMvcPerform(agentBffMvc, AGENT_BFF, """
                {"orderId":"order-001","ticketType":"return","reason":"旧版调用方未声明来源"}
                """);

        verify(afterSalesTicketService).createTicketForAgent(any(AgentAfterSalesCreateRequest.class),
                eq(TEST_TENANT_ID), anyString(), eq("agent"));
    }

    @Test
    @DisplayName("Agent BFF 收到未知 X-Agent-Client 值 → 归一化为入口缺省 agent（不落脏值）")
    void agentBff_unknownHeader_normalizedToDefault() throws Exception {
        when(afterSalesTicketService.createTicketForAgent(any(AgentAfterSalesCreateRequest.class),
                eq(TEST_TENANT_ID), anyString(), anyString())).thenReturn(stubDetail());

        mockMvcPerform(agentBffMvc, AGENT_BFF, """
                {"orderId":"order-001","ticketType":"return","reason":"客户端传了未定义值"}
                """, CLIENT_HEADER, "partner-x");

        verify(afterSalesTicketService).createTicketForAgent(any(AgentAfterSalesCreateRequest.class),
                eq(TEST_TENANT_ID), anyString(), eq("agent"));
    }

    // ==================== 辅助 ====================

    private void mockMvcPerform(MockMvc mockMvc, String path, String body, String... header) throws Exception {
        var request = post(path).contentType(MediaType.APPLICATION_JSON).content(body);
        if (header.length == 2) {
            request = request.header(header[0], header[1]);
        }
        mockMvc.perform(request).andExpect(status().isOk());
    }
}
