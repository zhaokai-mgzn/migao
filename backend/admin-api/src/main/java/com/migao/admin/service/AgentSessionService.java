package com.migao.admin.service;

import com.migao.admin.config.TenantContext;
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
     * 根据 AI 会话 ID 查询人工客服会话（用户端：转人工后查看客服回复）
     *
     * 校验 customerId 归属（用户只能看自己的会话）。
     * 顾客端视角：**不含 aiContext 快照**（避免轮询载荷放大与重复展示），
     * 且过滤 isInternal 内部备注（GB/T 47746-2026 隐私口径，issue #2776）。
     *
     * @param aiSessionId AI 会话 ID（sessions 表）
     * @param customerId 客户 ID（当前登录用户）
     * @return 会话详情（含客服消息，不含 AI 上下文与内部备注）
     */
    public AgentSessionDetailResponse getSessionByAiSessionId(String aiSessionId, String customerId) {
        if (!StringUtils.hasText(aiSessionId)) {
            throw BusinessException.validationError("AI 会话 ID 不能为空");
        }
        LambdaQueryWrapper<AgentSession> wrapper = new LambdaQueryWrapper<>();
        wrapper.eq(AgentSession::getAiSessionId, aiSessionId)
                .eq(AgentSession::getCustomerId, customerId)
                .orderByDesc(AgentSession::getCreatedAt)
                .last("LIMIT 1");
        AgentSession session = agentSessionMapper.selectOne(wrapper);
        if (session == null) {
            throw BusinessException.notFound("人工客服会话");
        }
        return buildSessionDetail(session, false, true);
    }

    /**
     * 获取会话详情（管理端/客服工作台视角）
     *
     * 含转人工前 AI 对话快照（aiContextSummary/aiContext），内部备注对客服可见。
     */
    public AgentSessionDetailResponse getSessionDetail(String id) {
        AgentSession session = agentSessionMapper.selectById(id);
        if (session == null) {
            throw BusinessException.notFound("客服会话");
        }
        // 租户隔离校验：禁止跨租户访问
        Long currentTenantId = TenantContext.getTenantId();
        if (!session.getTenantId().equals(currentTenantId)) {
            throw BusinessException.notFound("客服会话");
        }
        return buildSessionDetail(session, true, false);
    }

    /**
     * 组装会话详情响应（管理端/顾客端共用，参数控制 AI 上下文与内部备注可见性）
     *
     * @param session         已通过租户/归属校验的会话
     * @param includeAiContext true=管理端：返回 aiContextSummary/aiContext；false=顾客端
     * @param filterInternal   true=顾客端：过滤 isInternal=true 的内部备注
     */
    private AgentSessionDetailResponse buildSessionDetail(
            AgentSession session, boolean includeAiContext, boolean filterInternal) {

        // 查询关联消息（按创建时间正序）
        LambdaQueryWrapper<AgentMessage> msgWrapper = new LambdaQueryWrapper<>();
        msgWrapper.eq(AgentMessage::getSessionId, session.getId())
                .orderByAsc(AgentMessage::getCreatedAt);
        List<AgentMessage> messages = agentMessageMapper.selectList(msgWrapper);
        if (filterInternal) {
            messages = messages.stream()
                    .filter(m -> !Boolean.TRUE.equals(m.getIsInternal()))
                    .collect(Collectors.toList());
        }

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
                .aiContextSummary(includeAiContext ? session.getAiContextSummary() : null)
                .aiContext(includeAiContext ? mapAiContext(session.getAiContextMessages()) : null)
                .customerPhone(customer != null ? customer.getPhone() : null)
                .customerAvatarUrl(customer != null ? customer.getAvatarUrl() : null)
                .build();
    }

    /**
     * 把 JSONB 快照（List<Map>/List<AgentAiContextMessage>）映射为响应 DTO；
     * 空/异常一律返回 null，不抛错。
     */
    private List<AgentAiContextMessage> mapAiContext(Object raw) {
        if (!(raw instanceof List)) {
            return null;
        }
        List<AgentAiContextMessage> out = new ArrayList<>();
        for (Object item : (List<?>) raw) {
            if (item == null) {
                continue;
            }
            if (item instanceof AgentAiContextMessage m) {
                out.add(m);
            } else if (item instanceof Map<?, ?> map) {
                out.add(AgentAiContextMessage.builder()
                        .role(anyToString(map.get("role")))
                        .content(anyToString(map.get("content")))
                        .contentType(anyToString(map.get("contentType")))
                        .createdAt(anyToString(map.get("createdAt")))
                        .build());
            }
        }
        return out.isEmpty() ? null : out;
    }

    private static String anyToString(Object value) {
        return value == null ? null : String.valueOf(value);
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
        // 租户隔离校验：禁止跨租户操作
        Long currentTenantId = TenantContext.getTenantId();
        if (!session.getTenantId().equals(currentTenantId)) {
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
    /**
     * 转人工创建会话（AI 客服 → 人工客服桥接）
     *
     * 用户触发转人工时，创建等待分配的人工会话，并写入系统消息。
     * 会话状态初始为 waiting，客服分配/接待后转 active。
     * GB/T 47746-2026（issue #2776）：同时快照转人工时点 AI 对话上下文
     * （aiContextSummary 摘要 + aiContextMessages 最近 N 轮 user/assistant 文本），
     * 供人工客服工作台展示，避免顾客重复复述。
     *
     * @param aiSessionId AI 会话 ID（sessions 表，用于关联回溯 AI 对话）
     * @param customerId 客户 ID（customer_profiles）
     * @param tenantId 租户 ID
     * @param reason 转人工原因
     * @param aiContextSummary AI 会话上下文摘要（选填，超长截断 500 字符）
     * @param aiContextMessages AI 会话最近 N 轮消息快照（选填，≤20 条、每条 ≤500 字符）
     * @return 创建的会话
     */
    @Transactional(rollbackFor = Exception.class)
    public AgentSession createSessionForHandoff(String aiSessionId, String customerId, Long tenantId, String reason) {
        return createSessionForHandoff(aiSessionId, customerId, tenantId, reason, null, null);
    }

    /**
     * 转人工创建会话（含 AI 上下文快照，见 {@link #createSessionForHandoff(String, String, Long, String)}）
     */
    @Transactional(rollbackFor = Exception.class)
    public AgentSession createSessionForHandoff(String aiSessionId, String customerId, Long tenantId, String reason,
                                                String aiContextSummary, List<AgentAiContextMessage> aiContextMessages) {
        // 服务端兜底：防超大 payload（summary ≤500 字、快照 ≤20 条、每条 content ≤500 字）
        String safeSummary = null;
        if (StringUtils.hasText(aiContextSummary)) {
            safeSummary = aiContextSummary.length() > 500
                    ? aiContextSummary.substring(0, 500) : aiContextSummary;
        }
        List<AgentAiContextMessage> safeMessages = null;
        if (aiContextMessages != null && !aiContextMessages.isEmpty()) {
            safeMessages = new ArrayList<>();
            for (AgentAiContextMessage msg : aiContextMessages) {
                if (safeMessages.size() >= 20) {
                    break;
                }
                if (msg == null) {
                    continue;
                }
                String content = msg.getContent();
                if (content != null && content.length() > 500) {
                    content = content.substring(0, 500);
                }
                safeMessages.add(AgentAiContextMessage.builder()
                        .role(msg.getRole())
                        .content(content)
                        .contentType(msg.getContentType())
                        .createdAt(msg.getCreatedAt())
                        .build());
            }
        }

        AgentSession session = AgentSession.builder()
                .tenantId(tenantId)
                .customerId(customerId)
                .aiSessionId(aiSessionId)
                .status("waiting")
                .priority(1)
                .reason(StringUtils.hasText(reason) ? reason : "客户请求转人工")
                .aiContextSummary(safeSummary)
                .aiContextMessages(safeMessages)
                .queuePosition(0)
                .startedAt(OffsetDateTime.now())
                .build();
        agentSessionMapper.insert(session);

        // 写入系统消息：会话创建记录
        AgentMessage sysMsg = AgentMessage.builder()
                .tenantId(tenantId)
                .sessionId(session.getId())
                .senderType("system")
                .contentType("text")
                .content("客户请求转人工：" + session.getReason())
                .isInternal(false)
                .build();
        agentMessageMapper.insert(sysMsg);

        log.info("[agent-session] 转人工会话创建: sessionId={} aiSessionId={} tenant={} aiContextTurns={}",
                session.getId(), aiSessionId, tenantId,
                safeMessages == null ? 0 : safeMessages.size());
        return session;
    }

    /**
     * 发送人工会话消息（客服或用户）
     *
     * 客服（agent）或用户（customer）在人工会话中发送消息。
     * 会话处于 waiting 时，客服首次回复自动转为 active。
     *
     * @param sessionId 人工会话 ID
     * @param senderType 发送者类型：agent / customer / system
     * @param senderId 发送者 ID
     * @param content 消息内容
     * @param isInternal 是否内部备注（仅客服可见）
     * @return 保存的消息
     */
    @Transactional(rollbackFor = Exception.class)
    public AgentMessage sendMessage(String sessionId, String senderType, String senderId,
                                    String content, Boolean isInternal) {
        if (!StringUtils.hasText(content)) {
            throw BusinessException.validationError("消息内容不能为空");
        }
        AgentSession session = agentSessionMapper.selectById(sessionId);
        if (session == null) {
            throw BusinessException.notFound("客服会话");
        }
        // 租户隔离校验：禁止跨租户操作
        Long currentTenantId = TenantContext.getTenantId();
        if (!session.getTenantId().equals(currentTenantId)) {
            throw BusinessException.notFound("客服会话");
        }
        // 客户消息归属校验（审计 07 P1-3）：customer 只能向自己的会话发消息，
        // 防租户内客户间消息注入/伪造
        if ("customer".equals(senderType) && !session.getCustomerId().equals(senderId)) {
            throw BusinessException.notFound("客服会话");
        }
        if ("ended".equals(session.getStatus())) {
            throw BusinessException.validationError("会话已结束，无法发送消息");
        }

        AgentMessage msg = AgentMessage.builder()
                .tenantId(session.getTenantId())
                .sessionId(sessionId)
                .senderType(senderType)
                .senderId(senderId)
                .contentType("text")
                .content(content)
                .isInternal(Boolean.TRUE.equals(isInternal))
                .build();
        agentMessageMapper.insert(msg);

        // 客服首次回复：waiting → active
        if ("agent".equals(senderType) && "waiting".equals(session.getStatus())) {
            AgentSession update = new AgentSession();
            update.setId(sessionId);
            update.setStatus("active");
            agentSessionMapper.updateById(update);
            log.info("[agent-session] 客服接待，会话 active: sessionId={} employeeId={}", sessionId, senderId);
        }

        return msg;
    }

    @Transactional(rollbackFor = Exception.class)
    public void endSession(String sessionId) {
        AgentSession session = agentSessionMapper.selectById(sessionId);
        if (session == null) {
            throw BusinessException.notFound("客服会话");
        }
        // 租户隔离校验：禁止跨租户操作
        Long currentTenantId = TenantContext.getTenantId();
        if (!session.getTenantId().equals(currentTenantId)) {
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
