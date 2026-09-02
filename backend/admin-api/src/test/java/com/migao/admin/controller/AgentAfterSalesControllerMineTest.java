// case_ids: AS-001, DF-002
package com.migao.admin.controller;

import com.migao.admin.controller.agent.AgentAfterSalesController;
import com.migao.admin.dto.AfterSalesListResponse;
import com.migao.admin.dto.PageResponse;
import com.migao.admin.security.SecurityUser;
import com.migao.admin.service.AfterSalesTicketService;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.test.web.servlet.MockMvc;

import java.util.List;

import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

/**
 * AgentAfterSalesController C 端"我的售后"端点测试 — 用户级数据隔离强制点。
 *
 * GET /api/admin/agent/after-sales/mine：
 * - 有真实用户（SecurityUser.userId 非 internal-service 占位）→ 强制按该用户订单过滤
 * - 用户标识缺失/占位 → 4xx 拒绝，不查库
 * - 不支持任何跨用户筛选参数（仅 page/size）
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("AgentAfterSalesController C 端售后隔离")
class AgentAfterSalesControllerMineTest extends BaseControllerTest {

    private MockMvc mockMvc;

    @Mock private AfterSalesTicketService afterSalesTicketService;

    @InjectMocks
    private AgentAfterSalesController agentAfterSalesController;

    private static final String MINE = "/api/admin/agent/after-sales/mine";

    @BeforeEach
    void setUp() {
        super.baseSetUp();
        mockMvc = buildMockMvc(agentAfterSalesController);
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
    @DisplayName("GET /mine — 用户级数据隔离")
    class MineEndpoint {

        @Test
        @DisplayName("真实用户可查询，强制按该用户订单过滤（无跨用户参数）")
        void realUserQueriesWithForcedFilter() throws Exception {
            setServiceUserWithRealId("customer-001");
            when(afterSalesTicketService.getTicketPageForUser(
                    eq(TEST_TENANT_ID), eq("customer-001"), anyLong(), anyLong()))
                    .thenReturn(PageResponse.of(0L, 1L, 10L, List.<AfterSalesListResponse>of()));

            mockMvc.perform(get(MINE))
                    .andExpect(status().isOk());

            // 强制 userId=当前用户；不允许 status/keyword 等跨用户参数
            verify(afterSalesTicketService).getTicketPageForUser(
                    eq(TEST_TENANT_ID), eq("customer-001"), anyLong(), anyLong());
        }

        @Test
        @DisplayName("支持分页参数透传")
        void paginationPassedThrough() throws Exception {
            setServiceUserWithRealId("customer-002");
            when(afterSalesTicketService.getTicketPageForUser(
                    eq(TEST_TENANT_ID), eq("customer-002"), eq(2L), eq(5L)))
                    .thenReturn(PageResponse.of(0L, 2L, 5L, List.<AfterSalesListResponse>of()));

            mockMvc.perform(get(MINE).param("page", "2").param("size", "5"))
                    .andExpect(status().isOk());

            verify(afterSalesTicketService).getTicketPageForUser(
                    eq(TEST_TENANT_ID), eq("customer-002"), eq(2L), eq(5L));
        }

        @Test
        @DisplayName("用户标识缺失/内部占位 → 拒绝且不查库")
        void missingUserIdRejected() throws Exception {
            setServiceUserWithRealId("internal-service");

            mockMvc.perform(get(MINE))
                    .andExpect(status().is4xxClientError());

            verify(afterSalesTicketService, never()).getTicketPageForUser(
                    anyLong(), anyString(), anyLong(), anyLong());
        }
    }
}
