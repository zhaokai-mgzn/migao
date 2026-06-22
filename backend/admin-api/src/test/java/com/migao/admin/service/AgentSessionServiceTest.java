package com.migao.admin.service;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.AgentMonitorResponse;
import com.migao.admin.dto.AgentSessionDetailResponse;
import com.migao.admin.dto.AgentSessionListResponse;
import com.migao.admin.dto.PageResponse;
import com.migao.admin.entity.AgentEmployee;
import com.migao.admin.entity.AgentMessage;
import com.migao.admin.entity.AgentSession;
import com.migao.admin.entity.CustomerProfile;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.AgentEmployeeMapper;
import com.migao.admin.mapper.AgentMessageMapper;
import com.migao.admin.mapper.AgentSessionMapper;
import com.migao.admin.mapper.CustomerProfileMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.Set;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

/**
 * AgentSessionService 单元测试
 */
@ExtendWith(MockitoExtension.class)
class AgentSessionServiceTest {

    @Mock
    private AgentSessionMapper agentSessionMapper;

    @Mock
    private AgentMessageMapper agentMessageMapper;

    @Mock
    private AgentEmployeeMapper agentEmployeeMapper;

    @Mock
    private CustomerProfileMapper customerProfileMapper;

    @InjectMocks
    private AgentSessionService agentSessionService;

    private AgentSession testSession;
    private AgentEmployee testEmployee;
    private CustomerProfile testCustomer;

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(1L);

        testSession = AgentSession.builder()
                .id("session-001")
                .tenantId(1L)
                .customerId("cust-001")
                .employeeId("emp-001")
                .aiSessionId("ai-001")
                .status("active")
                .priority(1)
                .reason("咨询窗帘价格")
                .queuePosition(0)
                .startedAt(OffsetDateTime.now())
                .createdAt(OffsetDateTime.now())
                .build();

        testEmployee = AgentEmployee.builder()
                .id("emp-001")
                .tenantId(1L)
                .name("客服小王")
                .status("online")
                .maxConcurrentSessions(5)
                .build();

        testCustomer = CustomerProfile.builder()
                .id("cust-001")
                .tenantId(1L)
                .wechatNickname("张先生")
                .phone("13800138000")
                .build();
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    // ======================== 分页查询会话列表测试 ========================

    @Test
    @DisplayName("分页查询会话列表 - 默认分页")
    void getSessionPage_DefaultPagination() {
        // given
        Page<AgentSession> mockPage = new Page<>(1, 20);
        mockPage.setRecords(List.of(testSession));
        mockPage.setTotal(1);

        when(agentSessionMapper.selectPage(any(Page.class), any(LambdaQueryWrapper.class)))
                .thenReturn(mockPage);
        when(agentEmployeeMapper.selectBatchIds(anySet()))
                .thenReturn(List.of(testEmployee));
        when(customerProfileMapper.selectBatchIds(anySet()))
                .thenReturn(List.of(testCustomer));
        when(agentMessageMapper.selectCount(any(LambdaQueryWrapper.class))).thenReturn(3L);

        // when
        PageResponse<AgentSessionListResponse> result = agentSessionService.getSessionPage(
                1, 20, null, null, null, 1L);

        // then
        assertThat(result).isNotNull();
        assertThat(result.getTotal()).isEqualTo(1);
        assertThat(result.getItems()).hasSize(1);
        assertThat(result.getItems().get(0).getCustomerName()).isEqualTo("张先生");
        assertThat(result.getItems().get(0).getEmployeeName()).isEqualTo("客服小王");
        assertThat(result.getItems().get(0).getStatus()).isEqualTo("active");
        assertThat(result.getItems().get(0).getMessageCount()).isEqualTo(3);
    }

    @Test
    @DisplayName("分页查询会话列表 - 带状态筛选")
    void getSessionPage_WithStatusFilter() {
        // given
        Page<AgentSession> mockPage = new Page<>(1, 10);
        mockPage.setRecords(List.of(testSession));
        mockPage.setTotal(1);

        when(agentSessionMapper.selectPage(any(Page.class), any(LambdaQueryWrapper.class)))
                .thenReturn(mockPage);
        when(agentEmployeeMapper.selectBatchIds(anySet())).thenReturn(List.of(testEmployee));
        when(customerProfileMapper.selectBatchIds(anySet())).thenReturn(List.of(testCustomer));
        when(agentMessageMapper.selectCount(any(LambdaQueryWrapper.class))).thenReturn(3L);

        // when
        PageResponse<AgentSessionListResponse> result = agentSessionService.getSessionPage(
                1, 10, "active", null, null, 1L);

        // then
        assertThat(result).isNotNull();
        assertThat(result.getItems()).hasSize(1);
        verify(agentSessionMapper).selectPage(any(Page.class), any(LambdaQueryWrapper.class));
    }

    @Test
    @DisplayName("分页查询会话列表 - 空结果")
    void getSessionPage_EmptyResult() {
        // given
        Page<AgentSession> emptyPage = new Page<>(1, 20);
        emptyPage.setRecords(List.of());
        emptyPage.setTotal(0);

        when(agentSessionMapper.selectPage(any(Page.class), any(LambdaQueryWrapper.class)))
                .thenReturn(emptyPage);

        // when
        PageResponse<AgentSessionListResponse> result = agentSessionService.getSessionPage(
                1, 20, null, null, null, 1L);

        // then
        assertThat(result.getTotal()).isEqualTo(0);
        assertThat(result.getItems()).isEmpty();
    }

    // ======================== 获取会话详情测试 ========================

    @Test
    @DisplayName("获取会话详情 - 成功")
    void getSessionDetail_Success() {
        // given
        testSession.setTenantId(1L); // 与 TenantContext 一致
        when(agentSessionMapper.selectById("session-001")).thenReturn(testSession);
        when(agentMessageMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of());
        when(customerProfileMapper.selectById("cust-001")).thenReturn(testCustomer);
        when(agentEmployeeMapper.selectById("emp-001")).thenReturn(testEmployee);

        // when
        AgentSessionDetailResponse result = agentSessionService.getSessionDetail("session-001");

        // then
        assertThat(result).isNotNull();
        assertThat(result.getId()).isEqualTo("session-001");
        assertThat(result.getCustomerName()).isEqualTo("张先生");
        assertThat(result.getEmployeeName()).isEqualTo("客服小王");
        assertThat(result.getStatus()).isEqualTo("active");
    }

    @Test
    @DisplayName("获取会话详情 - 会话不存在")
    void getSessionDetail_NotFound() {
        // given
        when(agentSessionMapper.selectById("nonexistent")).thenReturn(null);

        // when & then
        assertThatThrownBy(() -> agentSessionService.getSessionDetail("nonexistent"))
                .isInstanceOf(BusinessException.class)
                .satisfies(ex -> {
                    BusinessException bex = (BusinessException) ex;
                    assertThat(bex.getCode()).isEqualTo("NOT_FOUND");
                });
    }

    @Test
    @DisplayName("获取会话详情 - 跨租户访问被拒绝")
    void getSessionDetail_CrossTenantRejected() {
        // given: 会话属于租户 2，当前上下文是租户 1
        AgentSession otherTenantSession = AgentSession.builder()
                .id("session-002")
                .tenantId(2L)
                .customerId("cust-001")
                .status("active")
                .build();
        when(agentSessionMapper.selectById("session-002")).thenReturn(otherTenantSession);

        // when & then
        assertThatThrownBy(() -> agentSessionService.getSessionDetail("session-002"))
                .isInstanceOf(BusinessException.class)
                .satisfies(ex -> {
                    BusinessException bex = (BusinessException) ex;
                    assertThat(bex.getCode()).isEqualTo("NOT_FOUND");
                });
    }

    // ======================== 分配会话测试 ========================

    @Test
    @DisplayName("分配会话 - 成功，将 waiting 会话分配给在线员工")
    void assignSession_Success() {
        // given: 会话状态为 waiting
        AgentSession waitingSession = AgentSession.builder()
                .id("session-waiting")
                .tenantId(1L)
                .customerId("cust-001")
                .status("waiting")
                .build();
        when(agentSessionMapper.selectById("session-waiting")).thenReturn(waitingSession);

        // 员工在线
        when(agentEmployeeMapper.selectById("emp-001")).thenReturn(testEmployee);

        // 当前活跃会话数 < 最大并发
        when(agentSessionMapper.selectCount(any(LambdaQueryWrapper.class))).thenReturn(2L);

        when(agentSessionMapper.updateById(any(AgentSession.class))).thenReturn(1);
        when(agentMessageMapper.insert(any(AgentMessage.class))).thenReturn(1);

        // when
        agentSessionService.assignSession("session-waiting", "emp-001");

        // then
        verify(agentSessionMapper).updateById(argThat((AgentSession s) ->
                "active".equals(s.getStatus()) && "emp-001".equals(s.getEmployeeId())));
        verify(agentMessageMapper).insert(any(AgentMessage.class));
    }

    @Test
    @DisplayName("分配会话 - 会话不存在")
    void assignSession_SessionNotFound() {
        // given
        when(agentSessionMapper.selectById("nonexistent")).thenReturn(null);

        // when & then
        assertThatThrownBy(() -> agentSessionService.assignSession("nonexistent", "emp-001"))
                .isInstanceOf(BusinessException.class)
                .satisfies(ex -> {
                    BusinessException bex = (BusinessException) ex;
                    assertThat(bex.getCode()).isEqualTo("NOT_FOUND");
                });
    }

    @Test
    @DisplayName("分配会话 - 非 waiting 状态不可分配")
    void assignSession_NotWaitingStatus() {
        // given: 会话状态为 active（非 waiting）
        when(agentSessionMapper.selectById("session-001")).thenReturn(testSession);

        // when & then
        assertThatThrownBy(() -> agentSessionService.assignSession("session-001", "emp-001"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("只有等待中的会话才能分配");
    }

    @Test
    @DisplayName("分配会话 - 员工不在线")
    void assignSession_EmployeeOffline() {
        // given
        AgentSession waitingSession = AgentSession.builder()
                .id("session-waiting")
                .tenantId(1L)
                .customerId("cust-001")
                .status("waiting")
                .build();
        when(agentSessionMapper.selectById("session-waiting")).thenReturn(waitingSession);

        AgentEmployee offlineEmployee = AgentEmployee.builder()
                .id("emp-offline")
                .tenantId(1L)
                .name("离线员工")
                .status("offline")
                .maxConcurrentSessions(5)
                .build();
        when(agentEmployeeMapper.selectById("emp-offline")).thenReturn(offlineEmployee);

        // when & then
        assertThatThrownBy(() -> agentSessionService.assignSession("session-waiting", "emp-offline"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("该员工当前不在线");
    }

    @Test
    @DisplayName("分配会话 - 员工已达最大并发数")
    void assignSession_MaxConcurrentReached() {
        // given
        AgentSession waitingSession = AgentSession.builder()
                .id("session-waiting")
                .tenantId(1L)
                .customerId("cust-001")
                .status("waiting")
                .build();
        when(agentSessionMapper.selectById("session-waiting")).thenReturn(waitingSession);
        when(agentEmployeeMapper.selectById("emp-001")).thenReturn(testEmployee);

        // 当前活跃数 >= maxConcurrent
        when(agentSessionMapper.selectCount(any(LambdaQueryWrapper.class))).thenReturn(5L);

        // when & then
        assertThatThrownBy(() -> agentSessionService.assignSession("session-waiting", "emp-001"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("已达到最大并发会话数");
    }

    // ======================== 结束会话测试 ========================

    @Test
    @DisplayName("结束会话 - 成功，active 状态可结束")
    void endSession_Success() {
        // given
        testSession.setTenantId(1L);
        when(agentSessionMapper.selectById("session-001")).thenReturn(testSession);
        when(agentSessionMapper.updateById(any(AgentSession.class))).thenReturn(1);
        when(agentMessageMapper.insert(any(AgentMessage.class))).thenReturn(1);

        // when
        agentSessionService.endSession("session-001");

        // then
        verify(agentSessionMapper).updateById(argThat((AgentSession s) ->
                "ended".equals(s.getStatus())));
        verify(agentMessageMapper).insert(any(AgentMessage.class));
    }

    @Test
    @DisplayName("结束会话 - 会话不存在")
    void endSession_SessionNotFound() {
        // given
        when(agentSessionMapper.selectById("nonexistent")).thenReturn(null);

        // when & then
        assertThatThrownBy(() -> agentSessionService.endSession("nonexistent"))
                .isInstanceOf(BusinessException.class)
                .satisfies(ex -> {
                    BusinessException bex = (BusinessException) ex;
                    assertThat(bex.getCode()).isEqualTo("NOT_FOUND");
                });
    }

    @Test
    @DisplayName("结束会话 - 跨租户被拒绝")
    void endSession_CrossTenantRejected() {
        // given
        AgentSession otherTenantSession = AgentSession.builder()
                .id("session-002")
                .tenantId(2L)
                .status("active")
                .build();
        when(agentSessionMapper.selectById("session-002")).thenReturn(otherTenantSession);

        // when & then
        assertThatThrownBy(() -> agentSessionService.endSession("session-002"))
                .isInstanceOf(BusinessException.class)
                .satisfies(ex -> {
                    BusinessException bex = (BusinessException) ex;
                    assertThat(bex.getCode()).isEqualTo("NOT_FOUND");
                });
    }

    // ======================== 监控统计测试 ========================

    @Test
    @DisplayName("获取监控统计 - 有数据")
    void getMonitorStats_HasData() {
        // given
        when(agentEmployeeMapper.selectList(any(LambdaQueryWrapper.class)))
                .thenReturn(List.of(testEmployee));

        // active count = 3
        when(agentSessionMapper.selectCount(any(LambdaQueryWrapper.class)))
                .thenReturn(3L)   // first call: active sessions
                .thenReturn(2L)   // second call: waiting sessions
                .thenReturn(10L)  // third call: today total
                .thenReturn(1L);  // fourth call: per-employee active count (in stream)

        // when
        AgentMonitorResponse result = agentSessionService.getMonitorStats(1L);

        // then
        assertThat(result).isNotNull();
        assertThat(result.getOnlineEmployeeCount()).isEqualTo(1);
        assertThat(result.getActiveSessionCount()).isEqualTo(3);
        assertThat(result.getWaitingSessionCount()).isEqualTo(2);
        assertThat(result.getTodayTotalSessions()).isEqualTo(10);
        assertThat(result.getOnlineEmployees()).hasSize(1);
        assertThat(result.getOnlineEmployees().get(0).getName()).isEqualTo("客服小王");
    }
}
