package com.migao.admin.service;

import com.migao.admin.dto.*;
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
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.*;
import java.util.stream.Collectors;

/**
 * 人工客服会话服务类
 * 处理客服工作台会话管理、分配、结束、监控等业务逻辑
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class AgentSessionService extends ServiceImpl<AgentSessionMapper, AgentSession> {

    private final AgentSessionMapper agentSessionMapper;
    private final AgentMessageMapper agentMessageMapper;
    private final AgentEmployeeMapper agentEmployeeMapper;
    private final CustomerProfileMapper customerProfileMapper;

    /**
     * 合法的状态流转定义
     */
    private static final Map<String, Set<String>> STATUS_TRANSITIONS = Map.of(
            "waiting", Set.of("active", "ended"),
            "active", Set.of("ended", "transferred"),
            "ended", Set.of(),
            "transferred", Set.of()
    );

    /**
     * 分页查询会话列表
     */
    public PageResponse<AgentSessionListResponse> getSessionPage(
            long page, long size, String status, String employeeId, String keyword, Long tenantId) {

        LambdaQueryWrapper<AgentSession> wrapper = new LambdaQueryWrapper<>();
        wrapper.eq(AgentSession::getTenantId, tenantId);

        if (StringUtils.hasText(status)) {
            wrapper.eq(AgentSession::getStatus, status);
        }
        if (StringUtils.hasText(employeeId)) {
            wrapper.eq(AgentSession::getEmployeeId, employeeId);
        }
        if (StringUtils.hasText(keyword)) {
            wrapper.like(AgentSession::getReason, keyword);
        }

        wrapper.orderByDesc(AgentSession::getCreatedAt);

        Page<AgentSession> sessionPage = new Page<>(page, size);
        Page<AgentSession> resultPage = agentSessionMapper.selectPage(sessionPage, wrapper);

        // 批量查关联员工信息
        Set<String> employeeIds = resultPage.getRecords().stream()
                .map(AgentSession::getEmployeeId)
                .filter(Objects::nonNull)
                .collect(Collectors.toSet());
        Map<String, AgentEmployee> employeeMap = new HashMap<>();
        if (!employeeIds.isEmpty()) {
            List<AgentEmployee> employees = agentEmployeeMapper.selectBatchIds(employeeIds);
            employeeMap = employees.stream()
                    .collect(Collectors.toMap(AgentEmployee::getId, e -> e, (a, b) -> a));
        }

        // 批量查关联客户信息
        Set<String> customerIds = resultPage.getRecords().stream()
                .map(AgentSession::getCustomerId)
                .filter(Objects::nonNull)
                .collect(Collectors.toSet());
        Map<String, CustomerProfile> customerMap = new HashMap<>();
        if (!customerIds.isEmpty()) {
            List<CustomerProfile> customers = customerProfileMapper.selectBatchIds(customerIds);
            customerMap = customers.stream()
                    .collect(Collectors.toMap(CustomerProfile::getId, c -> c, (a, b) -> a));
        }

        // 批量查每个会话的消息数量
        Map<String, Integer> messageCountMap = new HashMap<>();
        for (AgentSession session : resultPage.getRecords()) {
            LambdaQueryWrapper<AgentMessage> msgWrapper = new LambdaQueryWrapper<>();
            msgWrapper.eq(AgentMessage::getSessionId, session.getId());
            Long count = agentMessageMapper.selectCount(msgWrapper);
            messageCountMap.put(session.getId(), count.intValue());
        }

        // 转换为响应DTO
        Map<String, AgentEmployee> finalEmployeeMap = employeeMap;
        Map<String, CustomerProfile> finalCustomerMap = customerMap;
        List<AgentSessionListResponse> responses = resultPage.getRecords().stream()
                .map(session -> {
                    AgentEmployee emp = finalEmployeeMap.get(session.getEmployeeId());
                    CustomerProfile cust = finalCustomerMap.get(session.getCustomerId());
                    return AgentSessionListResponse.builder()
                            .id(session.getId())
                            .customerId(session.getCustomerId())
                            .customerName(cust != null ? cust.getWechatNickname() : null)
                            .employeeId(session.getEmployeeId())
                            .employeeName(emp != null ? emp.getName() : null)
                            .aiSessionId(session.getAiSessionId())
                            .status(session.getStatus())
                            .priority(session.getPriority())
                            .reason(session.getReason())
                            .queuePosition(session.getQueuePosition())
                            .messageCount(messageCountMap.getOrDefault(session.getId(), 0))
                            .startedAt(session.getStartedAt())
                            .createdAt(session.getCreatedAt())
                            .build();
                })
                .collect(Collectors.toList());

        return PageResponse.of(resultPage.getTotal(), resultPage.getCurrent(), resultPage.getSize(), responses);
    }

    /**
     * 获取会话详情
     */
    public AgentSessionDetailResponse getSessionDetail(String id) {
        AgentSession session = agentSessionMapper.selectById(id);
        if (session == null) {
            throw BusinessException.notFound("客服会话");
        }

        // 查询关联消息（按创建时间正序）
        LambdaQueryWrapper<AgentMessage> msgWrapper = new LambdaQueryWrapper<>();
        msgWrapper.eq(AgentMessage::getSessionId, id)
                .orderByAsc(AgentMessage::getCreatedAt);
        List<AgentMessage> messages = agentMessageMapper.selectList(msgWrapper);

        // 查询客户信息
        final CustomerProfile customer = StringUtils.hasText(session.getCustomerId())
                ? customerProfileMapper.selectById(session.getCustomerId()) : null;

        // 查询员工信息
        AgentEmployee employee = null;
        if (StringUtils.hasText(session.getEmployeeId())) {
            employee = agentEmployeeMapper.selectById(session.getEmployeeId());
        }

        // 构建消息响应列表
        AgentEmployee finalEmployee = employee;
        List<AgentMessageResponse> messageResponses = messages.stream()
                .map(msg -> {
                    String senderName = null;
                    if ("agent".equals(msg.getSenderType()) && finalEmployee != null) {
                        senderName = finalEmployee.getName();
                    } else if ("customer".equals(msg.getSenderType()) && customer != null) {
                        senderName = customer.getWechatNickname();
                    } else if ("system".equals(msg.getSenderType())) {
                        senderName = "系统";
                    }
                    return AgentMessageResponse.builder()
                            .id(msg.getId())
                            .senderType(msg.getSenderType())
                            .senderId(msg.getSenderId())
                            .senderName(senderName)
                            .contentType(msg.getContentType())
                            .content(msg.getContent())
                            .isInternal(msg.getIsInternal())
                            .createdAt(msg.getCreatedAt())
                            .build();
                })
                .collect(Collectors.toList());

        return AgentSessionDetailResponse.builder()
                .id(session.getId())
                .customerId(session.getCustomerId())
                .customerName(customer != null ? customer.getWechatNickname() : null)
                .employeeId(session.getEmployeeId())
                .employeeName(employee != null ? employee.getName() : null)
                .aiSessionId(session.getAiSessionId())
                .status(session.getStatus())
                .priority(session.getPriority())
                .reason(session.getReason())
                .queuePosition(session.getQueuePosition())
                .messageCount(messages.size())
                .startedAt(session.getStartedAt())
                .createdAt(session.getCreatedAt())
                .endedAt(session.getEndedAt())
                .messages(messageResponses)
                .customerPhone(customer != null ? customer.getPhone() : null)
                .customerAvatarUrl(customer != null ? customer.getAvatarUrl() : null)
                .build();
    }

    /**
     * 手动分配会话给员工
     */
    @Transactional(rollbackFor = Exception.class)
    public void assignSession(String sessionId, String employeeId) {
        AgentSession session = agentSessionMapper.selectById(sessionId);
        if (session == null) {
            throw BusinessException.notFound("客服会话");
        }

        // 校验会话状态必须为 waiting
        if (!"waiting".equals(session.getStatus())) {
            throw BusinessException.validationError("只有等待中的会话才能分配");
        }

        // 校验员工存在且在线
        AgentEmployee employee = agentEmployeeMapper.selectById(employeeId);
        if (employee == null) {
            throw BusinessException.notFound("客服员工");
        }
        if ("offline".equals(employee.getStatus())) {
            throw BusinessException.validationError("该员工当前不在线，无法分配");
        }

        // 校验员工当前会话数未超过最大并发数
        LambdaQueryWrapper<AgentSession> activeWrapper = new LambdaQueryWrapper<>();
        activeWrapper.eq(AgentSession::getEmployeeId, employeeId)
                .eq(AgentSession::getStatus, "active");
        Long activeCount = agentSessionMapper.selectCount(activeWrapper);
        int maxConcurrent = employee.getMaxConcurrentSessions() != null ? employee.getMaxConcurrentSessions() : 5;
        if (activeCount >= maxConcurrent) {
            throw BusinessException.validationError("该员工已达到最大并发会话数: " + maxConcurrent);
        }

        // 更新会话状态
        session.setEmployeeId(employeeId);
        session.setStatus("active");
        session.setStartedAt(OffsetDateTime.now());
        agentSessionMapper.updateById(session);

        // 记录系统消息
        AgentMessage systemMsg = AgentMessage.builder()
                .tenantId(session.getTenantId())
                .sessionId(sessionId)
                .senderType("system")
                .contentType("text")
                .content("会话已分配给" + employee.getName())
                .isInternal(false)
                .build();
        agentMessageMapper.insert(systemMsg);

        log.info("会话分配成功: sessionId={}, employeeId={}, employeeName={}", sessionId, employeeId, employee.getName());
    }

    /**
     * 结束会话
     */
    @Transactional(rollbackFor = Exception.class)
    public void endSession(String sessionId) {
        AgentSession session = agentSessionMapper.selectById(sessionId);
        if (session == null) {
            throw BusinessException.notFound("客服会话");
        }

        // 校验会话状态为 active 或 waiting
        if (!"active".equals(session.getStatus()) && !"waiting".equals(session.getStatus())) {
            throw BusinessException.validationError("只有进行中或等待中的会话才能结束");
        }

        // 更新状态
        session.setStatus("ended");
        session.setEndedAt(OffsetDateTime.now());
        agentSessionMapper.updateById(session);

        // 记录系统消息
        AgentMessage systemMsg = AgentMessage.builder()
                .tenantId(session.getTenantId())
                .sessionId(sessionId)
                .senderType("system")
                .contentType("text")
                .content("会话已结束")
                .isInternal(false)
                .build();
        agentMessageMapper.insert(systemMsg);

        log.info("会话结束: sessionId={}", sessionId);
    }

    /**
     * 获取监控统计数据
     */
    public AgentMonitorResponse getMonitorStats(Long tenantId) {
        // 查询在线员工数
        LambdaQueryWrapper<AgentEmployee> onlineWrapper = new LambdaQueryWrapper<>();
        onlineWrapper.eq(AgentEmployee::getTenantId, tenantId)
                .in(AgentEmployee::getStatus, List.of("online", "busy"));
        List<AgentEmployee> onlineEmployees = agentEmployeeMapper.selectList(onlineWrapper);

        // 查询活跃会话数
        LambdaQueryWrapper<AgentSession> activeWrapper = new LambdaQueryWrapper<>();
        activeWrapper.eq(AgentSession::getTenantId, tenantId)
                .eq(AgentSession::getStatus, "active");
        Long activeCount = agentSessionMapper.selectCount(activeWrapper);

        // 查询等待中会话数
        LambdaQueryWrapper<AgentSession> waitingWrapper = new LambdaQueryWrapper<>();
        waitingWrapper.eq(AgentSession::getTenantId, tenantId)
                .eq(AgentSession::getStatus, "waiting");
        Long waitingCount = agentSessionMapper.selectCount(waitingWrapper);

        // 查询今日总会话数
        OffsetDateTime todayStart = LocalDate.now().atStartOfDay().atOffset(ZoneOffset.ofHours(8));
        LambdaQueryWrapper<AgentSession> todayWrapper = new LambdaQueryWrapper<>();
        todayWrapper.eq(AgentSession::getTenantId, tenantId)
                .ge(AgentSession::getCreatedAt, todayStart);
        Long todayTotal = agentSessionMapper.selectCount(todayWrapper);

        // 构建在线员工状态列表
        List<AgentMonitorResponse.EmployeeStatusInfo> employeeStatusList = onlineEmployees.stream()
                .map(emp -> {
                    LambdaQueryWrapper<AgentSession> empActiveWrapper = new LambdaQueryWrapper<>();
                    empActiveWrapper.eq(AgentSession::getEmployeeId, emp.getId())
                            .eq(AgentSession::getStatus, "active");
                    Long empActiveCount = agentSessionMapper.selectCount(empActiveWrapper);
                    return AgentMonitorResponse.EmployeeStatusInfo.builder()
                            .id(emp.getId())
                            .name(emp.getName())
                            .status(emp.getStatus())
                            .activeSessionCount(empActiveCount.intValue())
                            .maxConcurrentSessions(emp.getMaxConcurrentSessions())
                            .build();
                })
                .collect(Collectors.toList());

        return AgentMonitorResponse.builder()
                .onlineEmployeeCount(onlineEmployees.size())
                .activeSessionCount(activeCount.intValue())
                .waitingSessionCount(waitingCount.intValue())
                .todayTotalSessions(todayTotal.intValue())
                .todayAvgResponseTime(0L)
                .onlineEmployees(employeeStatusList)
                .build();
    }
}
