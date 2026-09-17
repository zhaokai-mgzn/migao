package com.migao.admin.controller.agent;

// case_ids: AS-007

import com.migao.admin.controller.BaseControllerTest;
import com.migao.admin.dto.AfterSalesDetailResponse;
import com.migao.admin.dto.agent.AgentAfterSalesCreateRequest;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.service.AfterSalesTicketService;
import com.migao.admin.service.ClientRequestIdService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import java.util.Optional;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * 售后建单端点的幂等接线（issue #4037，F19）。
 *
 * <p>三个建单工具（小布 {@code aftersale_create} / 米宝 {@code after_sales_manage} /
 * 转人工 {@code human_handoff}）打的是**同一个** {@code POST /api/admin/agent/after-sales}
 * ⇒ 同一 {@code X-Client-Request-Id} 的同键请求**只建一张工单**，重复到达回放首次工单快照。</p>
 *
 * <p>本类锁 5 条（每条都有红证，见 PR 证据表）：</p>
 * <ol>
 *   <li>同键第二次 ⇒ 服务层建单只被调用一次，且返回首次工单（同一 ticketNo）；</li>
 *   <li>执行失败 ⇒ 释放占位（{@code discard}）+ 异常透传（不吞成 200）；</li>
 *   <li>占位在但无快照 ⇒ fail-closed 409 + suggestion（不静默返回空结果、不重复建单）；</li>
 *   <li>无请求头 ⇒ 原路径照建（零幂等交互，向后兼容）；</li>
 *   <li>成功 ⇒ 快照落库（{@code complete} 收到与响应体同一份 DTO）。</li>
 * </ol>
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("售后建单幂等接线（issue #4037）")
class AgentAfterSalesControllerTest extends BaseControllerTest {

    private static final String URL = "/api/admin/agent/after-sales";
    private static final String KEY = "req-key-as-1";
    private static final String ENDPOINT = "POST /api/admin/agent/after-sales";

    @Mock
    private AfterSalesTicketService afterSalesTicketService;
    @Mock
    private ClientRequestIdService clientRequestIdService;

    @InjectMocks
    private AgentAfterSalesController controller;

    private MockMvc mockMvc;

    @BeforeEach
    void setUp() {
        // 注：BaseControllerTest 的 @BeforeEach（TenantContext + SecurityContext）由 JUnit 自动继承执行，
        // 无需（也无法：跨包不可见）显式调用 super.baseSetUp()
        mockMvc = buildMockMvc(controller);
    }

    @Test
    @DisplayName("同键第二次：不再建单，回放首次工单（同一 ticketNo）")
    void sameKeyBuildsOnlyOneTicket() throws Exception {
        when(clientRequestIdService.claim(TEST_TENANT_ID, KEY, ENDPOINT)).thenReturn(true, false);
        when(afterSalesTicketService.createTicketForAgent(
                any(AgentAfterSalesCreateRequest.class), eq(TEST_TENANT_ID), anyString(), anyString()))
                .thenReturn(ticket("ticket-1", "AS-0001"));
        when(clientRequestIdService.replay(TEST_TENANT_ID, KEY, AfterSalesDetailResponse.class))
                .thenReturn(Optional.of(ticket("ticket-1", "AS-0001")));

        mockMvc.perform(post(URL).header("X-Client-Request-Id", KEY)
                        .contentType(MediaType.APPLICATION_JSON).content(body()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.ticketNo").value("AS-0001"));

        mockMvc.perform(post(URL).header("X-Client-Request-Id", KEY)
                        .contentType(MediaType.APPLICATION_JSON).content(body()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.ticketNo").value("AS-0001"))
                .andExpect(jsonPath("$.data.id").value("ticket-1"));

        // 去重粒度：同键只建一张工单
        verify(afterSalesTicketService, times(1)).createTicketForAgent(
                any(AgentAfterSalesCreateRequest.class), eq(TEST_TENANT_ID), anyString(), anyString());
        verify(clientRequestIdService, times(1)).complete(eq(TEST_TENANT_ID), eq(KEY), any());
    }

    @Test
    @DisplayName("执行失败：释放占位（discard）+ 异常透传（不得吞成 200）")
    void failureReleasesPlaceholderAndPropagates() throws Exception {
        when(clientRequestIdService.claim(TEST_TENANT_ID, KEY, ENDPOINT)).thenReturn(true);
        when(afterSalesTicketService.createTicketForAgent(
                any(AgentAfterSalesCreateRequest.class), anyLong(), anyString(), anyString()))
                .thenThrow(new BusinessException("ORDER_NOT_FOUND", "无法找到订单：ORD-404", 404));

        mockMvc.perform(post(URL).header("X-Client-Request-Id", KEY)
                        .contentType(MediaType.APPLICATION_JSON).content(body()))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.error.code").value("ORDER_NOT_FOUND"));

        verify(clientRequestIdService).discard(TEST_TENANT_ID, KEY);
        verify(clientRequestIdService, never()).complete(anyLong(), anyString(), any());
    }

    @Test
    @DisplayName("占位在但无快照：fail-closed 409 + suggestion，且不重复建单")
    void claimWithoutSnapshotFailsClosed() throws Exception {
        when(clientRequestIdService.claim(TEST_TENANT_ID, KEY, ENDPOINT)).thenReturn(false);
        when(clientRequestIdService.replay(TEST_TENANT_ID, KEY, AfterSalesDetailResponse.class))
                .thenReturn(Optional.empty());

        mockMvc.perform(post(URL).header("X-Client-Request-Id", KEY)
                        .contentType(MediaType.APPLICATION_JSON).content(body()))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.error.code").value("REQUEST_IN_PROGRESS"))
                .andExpect(jsonPath("$.suggestion").isNotEmpty());

        verify(afterSalesTicketService, never()).createTicketForAgent(
                any(AgentAfterSalesCreateRequest.class), anyLong(), anyString(), anyString());
    }

    @Test
    @DisplayName("无请求头（老调用方）：原路径照建，零幂等交互")
    void absentHeaderKeepsLegacyPath() throws Exception {
        when(afterSalesTicketService.createTicketForAgent(
                any(AgentAfterSalesCreateRequest.class), eq(TEST_TENANT_ID), anyString(), anyString()))
                .thenReturn(ticket("ticket-1", "AS-0001"));

        mockMvc.perform(post(URL).contentType(MediaType.APPLICATION_JSON).content(body()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.ticketNo").value("AS-0001"));

        verifyNoInteractions(clientRequestIdService);
    }

    private static AfterSalesDetailResponse ticket(String id, String ticketNo) {
        AfterSalesDetailResponse dto = new AfterSalesDetailResponse();
        dto.setId(id);
        dto.setTicketNo(ticketNo);
        dto.setOrderId("order-1");
        dto.setTicketType("exchange");
        dto.setStatus("pending");
        return dto;
    }

    private static String body() {
        return """
                {
                  "orderId": "ORD-20250101-001",
                  "ticketType": "exchange",
                  "reason": "尺寸不符"
                }
                """;
    }
}