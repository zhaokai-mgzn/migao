package com.migao.admin.service;

import com.migao.admin.entity.AgentEmployee;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.AgentEmployeeMapper;
import com.migao.admin.mapper.AgentSessionMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("AgentEmployeeService 客服员工服务测试")
class AgentEmployeeServiceTest extends BaseServiceTest {

    @Mock private AgentEmployeeMapper agentEmployeeMapper;
    @Mock private AgentSessionMapper agentSessionMapper;
    @InjectMocks private AgentEmployeeService agentEmployeeService;

    private AgentEmployee testEmployee;

    @BeforeEach
    void setUp() {
        super.baseSetUp();
        testEmployee = new AgentEmployee();
        testEmployee.setId("emp-001");
        testEmployee.setTenantId(TEST_TENANT_ID);
        testEmployee.setStatus("online");
    }

    @Nested
    @DisplayName("updateEmployeeStatus")
    class UpdateStatus {

        @Test
        @DisplayName("online → busy 成功")
        void toBusy() {
            when(agentEmployeeMapper.selectById("emp-001")).thenReturn(testEmployee);

            agentEmployeeService.updateEmployeeStatus("emp-001", "busy");

            verify(agentEmployeeMapper).selectById("emp-001");
        }

        @Test
        @DisplayName("online → offline 成功")
        void toOffline() {
            when(agentEmployeeMapper.selectById("emp-001")).thenReturn(testEmployee);

            agentEmployeeService.updateEmployeeStatus("emp-001", "offline");

            verify(agentEmployeeMapper).selectById("emp-001");
        }

        @Test
        @DisplayName("非法状态值 → BusinessException")
        void invalidStatus() {
            assertThatThrownBy(() -> agentEmployeeService.updateEmployeeStatus("emp-001", "sleeping"))
                    .isInstanceOf(BusinessException.class)
                    .satisfies(ex -> assertThat(((BusinessException) ex).getCode()).isEqualTo("VALIDATION_ERROR"));
            verify(agentEmployeeMapper, never()).selectById(anyString());
        }

        @Test
        @DisplayName("员工不存在 → NOT_FOUND")
        void employeeNotFound() {
            when(agentEmployeeMapper.selectById("nonexistent")).thenReturn(null);

            assertThatThrownBy(() -> agentEmployeeService.updateEmployeeStatus("nonexistent", "online"))
                    .isInstanceOf(BusinessException.class)
                    .satisfies(ex -> assertThat(((BusinessException) ex).getCode()).isEqualTo("NOT_FOUND"));
        }
    }

    @Nested
    @DisplayName("getOnlineEmployees")
    class GetOnline {

        @Test
        @DisplayName("返回在线和忙碌的员工")
        void returnsOnlineAndBusy() {
            AgentEmployee e1 = new AgentEmployee(); e1.setId("e1"); e1.setStatus("online");
            AgentEmployee e2 = new AgentEmployee(); e2.setId("e2"); e2.setStatus("busy");
            when(agentEmployeeMapper.selectList(any())).thenReturn(List.of(e1, e2));

            List<AgentEmployee> result = agentEmployeeService.getOnlineEmployees(TEST_TENANT_ID);

            assertThat(result).hasSize(2);
            assertThat(result).extracting("status").contains("online", "busy");
        }

        @Test
        @DisplayName("无在线员工返回空列表")
        void emptyList() {
            when(agentEmployeeMapper.selectList(any())).thenReturn(List.of());

            assertThat(agentEmployeeService.getOnlineEmployees(TEST_TENANT_ID)).isEmpty();
        }
    }

    @Nested
    @DisplayName("getEmployeeStats")
    class Stats {

        @Test
        @DisplayName("返回今日接待和活跃会话数")
        void returnsStats() {
            when(agentEmployeeMapper.selectById("emp-001")).thenReturn(testEmployee);
            when(agentSessionMapper.selectCount(any())).thenReturn(15L, 3L);

            Map<String, Object> stats = agentEmployeeService.getEmployeeStats("emp-001");

            assertThat(stats).containsEntry("todaySessions", 15);
            assertThat(stats).containsEntry("activeSessions", 3);
        }

        @Test
        @DisplayName("员工不存在 → NOT_FOUND")
        void employeeNotFound() {
            when(agentEmployeeMapper.selectById("nonexistent")).thenReturn(null);

            assertThatThrownBy(() -> agentEmployeeService.getEmployeeStats("nonexistent"))
                    .isInstanceOf(BusinessException.class)
                    .satisfies(ex -> assertThat(((BusinessException) ex).getCode()).isEqualTo("NOT_FOUND"));
        }
    }
}
