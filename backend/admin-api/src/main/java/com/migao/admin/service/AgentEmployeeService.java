package com.migao.admin.service;

import com.migao.admin.entity.AgentEmployee;
import com.migao.admin.entity.AgentSession;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.AgentEmployeeMapper;
import com.migao.admin.mapper.AgentSessionMapper;
import com.migao.admin.time.BusinessClock;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.time.OffsetDateTime;
import java.util.*;

/**
 * 客服员工服务类
 * 处理员工状态管理、在线员工查询、统计等业务逻辑
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class AgentEmployeeService extends ServiceImpl<AgentEmployeeMapper, AgentEmployee> {

    /** 业务时钟（issue #3802）：业务「今天」的唯一来源。Spring 注入单例；**不扫描 @Component 的切片上下文**
     * （@WebMvcTest / ApplicationContextRunner）与直接 new 构造的既有单测没有该 bean ⇒ required=false +
     * 默认实例（同为 +08 口径，行为一致），不因引入时钟让任何既有上下文启动失败（实测 OssEmptyConfigContextTest）。 */
    @Autowired(required = false)
    private BusinessClock businessClock = new BusinessClock();

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

        OffsetDateTime todayStart = businessClock.startOfToday();

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
