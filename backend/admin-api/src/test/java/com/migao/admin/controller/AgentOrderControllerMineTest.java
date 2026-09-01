// case_ids: OR-001, DF-002
package com.migao.admin.controller;

import com.migao.admin.controller.agent.AgentOrderController;
import com.migao.admin.dto.PageResponse;

import com.migao.admin.service.OrderService;
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

import com.migao.admin.security.SecurityUser;

import java.util.List;

import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

/**
 * AgentOrderController C 端"我的订单"端点测试 — 数据隔离强制点验证。
 *
 * GET /api/admin/agent/orders/mine：
 * - 有真实用户（SecurityUser.userId 非 internal-service 占位）→ 强制按该用户过滤
 * - 用户标识缺失/占位 → 401 拒绝，不返回任何订单数据
 * - 不允许 keyword/receiver 等跨用户筛选参数（仅 status/page/size）
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("AgentOrderController C 端订单隔离")
class AgentOrderControllerMineTest extends BaseControllerTest {

    private MockMvc mockMvc;

    @Mock private OrderService orderService;

    @InjectMocks
    private AgentOrderController agentOrderController;

    private static final String MINE = "/api/admin/agent/orders/mine";

    @BeforeEach
    void setUp() {
        super.baseSetUp();
        mockMvc = buildMockMvc(agentOrderController);
    }

    @Override
    @org.junit.jupiter.api.AfterEach
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
        @DisplayName("真实用户可查询，且强制按当前用户过滤（只允许状态/分页参数）")
        void realUserQueriesWithForcedFilter() throws Exception {
            setServiceUserWithRealId("customer-001");
            when(orderService.getOrderPage(
                    anyLong(), anyLong(), isNull(), isNull(), isNull(),
                    isNull(), isNull(), isNull(), isNull(), isNull(), isNull(), isNull(),
                    eq(TEST_TENANT_ID), eq("customer-001")))
                    .thenReturn(PageResponse.of(0L, 1L, 10L, List.of()));

            mockMvc.perform(get(MINE))
                    .andExpect(status().isOk());

            // 强制 userId=当前用户；keyword/receiver 等模糊条件必须为 null
            verify(orderService).getOrderPage(
                    anyLong(), anyLong(), isNull(), isNull(), isNull(),
                    isNull(), isNull(), isNull(), isNull(), isNull(), isNull(), isNull(),
                    eq(TEST_TENANT_ID), eq("customer-001"));
        }

        @Test
        @DisplayName("支持状态筛选透传")
        void statusFilterPassedThrough() throws Exception {
            setServiceUserWithRealId("customer-002");
            when(orderService.getOrderPage(
                    anyLong(), anyLong(), eq("shipped"), isNull(), isNull(),
                    isNull(), isNull(), isNull(), isNull(), isNull(), isNull(), isNull(),
                    eq(TEST_TENANT_ID), eq("customer-002")))
                    .thenReturn(PageResponse.of(0L, 1L, 10L, List.of()));

            mockMvc.perform(get(MINE).param("status", "shipped"))
                    .andExpect(status().isOk());

            verify(orderService).getOrderPage(
                    anyLong(), anyLong(), eq("shipped"), isNull(), isNull(),
                    isNull(), isNull(), isNull(), isNull(), isNull(), isNull(), isNull(),
                    eq(TEST_TENANT_ID), eq("customer-002"));
        }

        @Test
        @DisplayName("用户标识缺失/内部占位 → 拒绝且不查库")
        void missingUserIdRejected() throws Exception {
            // 未透传 X-User-Id：SecurityUser.userId 为 internal-service 占位
            setServiceUserWithRealId("internal-service");

            mockMvc.perform(get(MINE))
                    .andExpect(status().is4xxClientError());

            verify(orderService, never()).getOrderPage(anyLong(), anyLong(), any(), any(), any(),
                    any(), any(), any(), any(), any(), any(), any(), anyLong(), any());
        }

        @Test
        @DisplayName("无认证信息 → 拒绝")
        void noAuthRejected() throws Exception {
            SecurityContextHolder.clearContext();

            mockMvc.perform(get(MINE))
                    .andExpect(status().is4xxClientError());

            verify(orderService, never()).getOrderPage(anyLong(), anyLong(), any(), any(), any(),
                    any(), any(), any(), any(), any(), any(), any(), anyLong(), any());
        }
    }
}
