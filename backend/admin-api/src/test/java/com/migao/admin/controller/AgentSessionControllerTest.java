package com.migao.admin.controller;

import com.migao.admin.dto.AgentMonitorResponse;
import com.migao.admin.dto.AgentSessionDetailResponse;
import com.migao.admin.dto.AgentSessionListResponse;
import com.migao.admin.dto.PageResponse;
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

import java.util.List;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * AgentSessionController 单元测试
 * 覆盖：会话列表、监控面板、会话详情
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("AgentSessionController 客服会话测试")
class AgentSessionControllerTest extends BaseControllerTest {

    private MockMvc mockMvc;

    @Mock
    private AgentSessionService agentSessionService;

    @InjectMocks
    private AgentSessionController agentSessionController;

    private static final String BASE = "/api/admin/agent-sessions";

    @BeforeEach
    void setUp() {
        super.baseSetUp();
        mockMvc = buildMockMvc(agentSessionController);
    }

    @AfterEach
    void tearDown() {
        super.baseTearDown();
    }

    @Test
    @DisplayName("getSessions — 分页查询会话列表 → 200")
    void getSessions_returnsPage() throws Exception {
        AgentSessionListResponse s1 = AgentSessionListResponse.builder()
                .id("s-1").customerId("cust-1").customerName("客户A").status("active").build();
        AgentSessionListResponse s2 = AgentSessionListResponse.builder()
                .id("s-2").customerId("cust-2").customerName("客户B").status("waiting").build();

        PageResponse<AgentSessionListResponse> page = PageResponse.of(2L, 1L, 20L, List.of(s1, s2));
        when(agentSessionService.getSessionPage(eq(1L), eq(20L), eq(null), eq(null), eq(null), eq(TEST_TENANT_ID)))
                .thenReturn(page);

        mockMvc.perform(get(BASE).param("page", "1").param("size", "20"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.total").value(2))
                .andExpect(jsonPath("$.data.items[0].customerName").value("客户A"))
                .andExpect(jsonPath("$.data.items[1].status").value("waiting"));

        verify(agentSessionService).getSessionPage(eq(1L), eq(20L), eq(null), eq(null), eq(null), eq(TEST_TENANT_ID));
    }

    @Test
    @DisplayName("getSessions — 带筛选条件 → 200")
    void getSessions_withFilters() throws Exception {
        PageResponse<AgentSessionListResponse> page = PageResponse.of(0L, 1L, 10L, List.of());
        when(agentSessionService.getSessionPage(eq(1L), eq(10L), eq("waiting"), eq("emp-1"), eq(null), eq(TEST_TENANT_ID)))
                .thenReturn(page);

        mockMvc.perform(get(BASE)
                        .param("page", "1")
                        .param("size", "10")
                        .param("status", "waiting")
                        .param("employeeId", "emp-1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.items").isEmpty());

        verify(agentSessionService).getSessionPage(eq(1L), eq(10L), eq("waiting"), eq("emp-1"), eq(null), eq(TEST_TENANT_ID));
    }

    @Test
    @DisplayName("getMonitorStats — 获取监控面板数据 → 200")
    void getMonitorStats_returnsStats() throws Exception {
        AgentMonitorResponse stats = AgentMonitorResponse.builder()
                .onlineEmployeeCount(5)
                .activeSessionCount(12)
                .waitingSessionCount(3)
                .todayTotalSessions(48)
                .todayAvgResponseTime(0L)
                .onlineEmployees(List.of(
                        AgentMonitorResponse.EmployeeStatusInfo.builder()
                                .id("emp-1").name("客服小王").status("online")
                                .activeSessionCount(2).maxConcurrentSessions(5).build()))
                .build();
        when(agentSessionService.getMonitorStats(TEST_TENANT_ID)).thenReturn(stats);

        mockMvc.perform(get(BASE + "/monitor"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.onlineEmployeeCount").value(5))
                .andExpect(jsonPath("$.data.activeSessionCount").value(12))
                .andExpect(jsonPath("$.data.waitingSessionCount").value(3))
                .andExpect(jsonPath("$.data.onlineEmployees[0].name").value("客服小王"));

        verify(agentSessionService).getMonitorStats(TEST_TENANT_ID);
    }

    @Test
    @DisplayName("getSession — 获取会话详情 → 200")
    void getSession_returnsDetail() throws Exception {
        AgentSessionDetailResponse detail = AgentSessionDetailResponse.builder()
                .id("s-1")
                .customerId("cust-1")
                .customerName("客户A")
                .status("active")
                .messageCount(5)
                .build();
        when(agentSessionService.getSessionDetail("s-1")).thenReturn(detail);

        mockMvc.perform(get(BASE + "/s-1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.id").value("s-1"))
                .andExpect(jsonPath("$.data.customerName").value("客户A"));

        verify(agentSessionService).getSessionDetail("s-1");
    }
}
