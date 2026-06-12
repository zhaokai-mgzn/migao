package com.migao.admin.service;

import com.migao.admin.entity.AgentEmployee;
import com.migao.admin.entity.AgentSession;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.AgentEmployeeMapper;
import com.migao.admin.mapper.AgentSessionMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.*;

/**
 * 客服员工服务类
 * 处理员工状态管理、在线员工查询、统计等业务逻辑
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class AgentEmployeeService extends ServiceImpl<AgentEmployeeMapper, AgentEmployee> {

    private final AgentEmployeeMapper agentEmployeeMapper;
    private final AgentSessionMapper agentSessionMapper;

    private static final Set<String> VALID_STATUSES = Set.of("online", "offline", "busy");

    /**
     * 更新员工在线状态
     */
    public void updateEmployeeStatus(String employeeId, String status) {
        if (!VALID_STATUSES.contains(status)) {
            throw BusinessException.validationError("无效的员工状态: " + status + "，合法值: online/offline/busy");
        }

        AgentEmployee employee = agentEmployeeMapper.selectById(employeeId);
        if (employee == null) {
            throw BusinessException.notFound("客服员工");
        }

        employee.setStatus(status);
        agentEmployeeMapper.updateById(employee);
        log.info("更新员工状态: employeeId={}, status={}", employeeId, status);
    }

    /**
     * 获取在线员工列表
     */
    public List<AgentEmployee> getOnlineEmployees(Long tenantId) {
        LambdaQueryWrapper<AgentEmployee> wrapper = new LambdaQueryWrapper<>();
        wrapper.eq(AgentEmployee::getTenantId, tenantId)
                .in(AgentEmployee::getStatus, List.of("online", "busy"));
        return agentEmployeeMapper.selectList(wrapper);
    }

    /**
     * 获取员工今日统计
     */
    public Map<String, Object> getEmployeeStats(String employeeId) {
        AgentEmployee employee = agentEmployeeMapper.selectById(employeeId);
        if (employee == null) {
            throw BusinessException.notFound("客服员工");
        }

        OffsetDateTime todayStart = LocalDate.now().atStartOfDay().atOffset(ZoneOffset.ofHours(8));

        // 今日接待数
        LambdaQueryWrapper<AgentSession> todayWrapper = new LambdaQueryWrapper<>();
        todayWrapper.eq(AgentSession::getEmployeeId, employeeId)
                .ge(AgentSession::getCreatedAt, todayStart);
        Long todaySessions = agentSessionMapper.selectCount(todayWrapper);

        // 活跃会话数
        LambdaQueryWrapper<AgentSession> activeWrapper = new LambdaQueryWrapper<>();
        activeWrapper.eq(AgentSession::getEmployeeId, employeeId)
                .eq(AgentSession::getStatus, "active");
        Long activeSessions = agentSessionMapper.selectCount(activeWrapper);

        Map<String, Object> stats = new HashMap<>();
        stats.put("todaySessions", todaySessions.intValue());
        stats.put("activeSessions", activeSessions.intValue());
        return stats;
    }
}
