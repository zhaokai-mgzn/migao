// case_ids: OR-001, DF-002
package com.migao.admin.controller;

import com.migao.admin.controller.agent.AgentOrderController;
import com.migao.admin.dto.OrderListResponse;
import com.migao.admin.dto.PageResponse;
import com.migao.admin.entity.User;
import com.migao.admin.mapper.UserMapper;
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

    @Mock private UserMapper userMapper;

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
            // 用户未绑定手机号 → phone 兜底为 null（仅 user_id 直配）
            User noPhoneUser = User.builder().id("customer-001").phone(null).build();
            when(userMapper.selectById("customer-001")).thenReturn(noPhoneUser);
            when(orderService.getMyOrderPage(
                    eq(1L), eq(10L), isNull(), eq(TEST_TENANT_ID), eq("customer-001"), isNull()))
                    .thenReturn(PageResponse.of(0L, 1L, 10L, List.of()));

            mockMvc.perform(get(MINE))
                    .andExpect(status().isOk());

            // 强制走 C 端专用 mine 查询（user_id + phone 兜底由 service 处理）
            verify(orderService).getMyOrderPage(
                    eq(1L), eq(10L), isNull(), eq(TEST_TENANT_ID), eq("customer-001"), isNull());
        }

        @Test
        @DisplayName("用户已绑定手机号 → phone 兜底透传（名下商户代录订单可见）")
        void boundPhonePassedForFallback() throws Exception {
            setServiceUserWithRealId("customer-003");
            User boundUser = User.builder().id("customer-003").phone("13900139000").build();
            when(userMapper.selectById("customer-003")).thenReturn(boundUser);
            when(orderService.getMyOrderPage(
                    eq(1L), eq(10L), isNull(), eq(TEST_TENANT_ID), eq("customer-003"), eq("13900139000")))
                    .thenReturn(PageResponse.of(0L, 1L, 10L, List.of()));

            mockMvc.perform(get(MINE))
                    .andExpect(status().isOk());

            verify(orderService).getMyOrderPage(
                    eq(1L), eq(10L), isNull(), eq(TEST_TENANT_ID), eq("customer-003"), eq("13900139000"));
        }

        @Test
        @DisplayName("支持状态筛选透传")
        void statusFilterPassedThrough() throws Exception {
            setServiceUserWithRealId("customer-002");
            when(userMapper.selectById("customer-002")).thenReturn(
                    User.builder().id("customer-002").phone(null).build());
            when(orderService.getMyOrderPage(
                    eq(1L), eq(10L), eq("shipped"), eq(TEST_TENANT_ID), eq("customer-002"), isNull()))
                    .thenReturn(PageResponse.of(0L, 1L, 10L, List.of()));

            mockMvc.perform(get(MINE).param("status", "shipped"))
                    .andExpect(status().isOk());

            verify(orderService).getMyOrderPage(
                    eq(1L), eq(10L), eq("shipped"), eq(TEST_TENANT_ID), eq("customer-002"), isNull());
        }

        @Test
        @DisplayName("用户标识缺失/内部占位 → 拒绝且不查库")
        void missingUserIdRejected() throws Exception {
            // 未透传 X-User-Id：SecurityUser.userId 为 internal-service 占位
            setServiceUserWithRealId("internal-service");

            mockMvc.perform(get(MINE))
                    .andExpect(status().is4xxClientError());

            verify(orderService, never()).getMyOrderPage(anyLong(), anyLong(), any(), anyLong(), any(), any());
        }

        @Test
        @DisplayName("无认证信息 → 拒绝")
        void noAuthRejected() throws Exception {
            SecurityContextHolder.clearContext();

            mockMvc.perform(get(MINE))
                    .andExpect(status().is4xxClientError());

            verify(orderService, never()).getMyOrderPage(anyLong(), anyLong(), any(), anyLong(), any(), any());
        }
    }
}
