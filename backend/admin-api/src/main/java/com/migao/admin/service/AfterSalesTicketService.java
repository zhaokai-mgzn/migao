package com.migao.admin.service;

import com.migao.admin.dto.*;
import com.migao.admin.entity.AfterSalesTicket;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.TicketTimeline;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.AfterSalesTicketMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.TicketTimelineMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.time.format.DateTimeFormatter;
import java.util.*;
import java.util.stream.Collectors;

/**
 * 售后工单服务类
 * 处理售后工单的增删改查、状态更新等操作
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class AfterSalesTicketService extends ServiceImpl<AfterSalesTicketMapper, AfterSalesTicket> {

    private final AfterSalesTicketMapper afterSalesTicketMapper;
    private final OrderMapper orderMapper;
    private final TicketTimelineMapper ticketTimelineMapper;
    private final ObjectMapper objectMapper;

    /**
     * 合法的状态流转定义
     * key: 当前状态, value: 允许流转到的目标状态集合
     */
    private static final Map<String, Set<String>> STATUS_TRANSITIONS = Map.of(
            "pending", Set.of("processing", "rejected"),
            "processing", Set.of("resolved", "closed"),
            "resolved", Set.of(),
            "rejected", Set.of(),
            "closed", Set.of()
    );

    /**
     * 分页查询售后工单列表
     *
     * @param page       页码
     * @param size       每页大小
     * @param status     工单状态
     * @param ticketType 工单类型
     * @param keyword    搜索关键词（工单号、订单号、客户名）
     * @param tenantId   租户ID
     * @return 分页响应
     */
    public PageResponse<AfterSalesListResponse> getTicketPage(long page, long size, String status,
                                                               String ticketType, String keyword, Long tenantId) {
        LambdaQueryWrapper<AfterSalesTicket> wrapper = new LambdaQueryWrapper<>();

        // 状态筛选
        if (StringUtils.hasText(status)) {
            wrapper.eq(AfterSalesTicket::getStatus, status);
        }

        // 工单类型筛选
        if (StringUtils.hasText(ticketType)) {
            wrapper.eq(AfterSalesTicket::getTicketType, ticketType);
        }

        // 关键词搜索（工单号）
        if (StringUtils.hasText(keyword)) {
            // 先查匹配关键词的订单，获取 orderId 列表
            LambdaQueryWrapper<Order> orderWrapper = new LambdaQueryWrapper<>();
            orderWrapper.like(Order::getOrderNo, keyword)
                    .or()
                    .like(Order::getCustomerName, keyword);
            List<Order> matchedOrders = orderMapper.selectList(orderWrapper);
            List<String> matchedOrderIds = matchedOrders.stream()
                    .map(Order::getId)
                    .collect(Collectors.toList());

            wrapper.and(w -> {
                w.like(AfterSalesTicket::getTicketNo, keyword);
                if (!matchedOrderIds.isEmpty()) {
                    w.or().in(AfterSalesTicket::getOrderId, matchedOrderIds);
                }
            });
        }

        // 按创建时间倒序
        wrapper.orderByDesc(AfterSalesTicket::getCreatedAt);

        // 执行分页查询
        Page<AfterSalesTicket> ticketPage = new Page<>(page, size);
        Page<AfterSalesTicket> resultPage = afterSalesTicketMapper.selectPage(ticketPage, wrapper);

        // 批量查关联订单信息
        Set<String> orderIds = resultPage.getRecords().stream()
                .map(AfterSalesTicket::getOrderId)
                .filter(Objects::nonNull)
                .collect(Collectors.toSet());
        Map<String, Order> orderMap = new HashMap<>();
        if (!orderIds.isEmpty()) {
            List<Order> orders = orderMapper.selectBatchIds(orderIds);
            orderMap = orders.stream().collect(Collectors.toMap(Order::getId, o -> o, (a, b) -> a));
        }

        // 转换为响应 DTO
        Map<String, Order> finalOrderMap = orderMap;
        List<AfterSalesListResponse> responses = resultPage.getRecords().stream()
                .map(ticket -> convertToListResponse(ticket, finalOrderMap.get(ticket.getOrderId())))
                .collect(Collectors.toList());

        return PageResponse.of(resultPage.getTotal(), resultPage.getCurrent(), resultPage.getSize(), responses);
    }

    /**
     * 根据ID查询工单详情
     *
     * @param id 工单ID
     * @return 工单详情响应
     */
    public AfterSalesDetailResponse getTicketById(String id) {
        // 先按 UUID 查
        AfterSalesTicket ticket = afterSalesTicketMapper.selectById(id);
        // UUID 没找到，尝试按 ticket_no 查询（兼容米宝用 ticket_no 调用 detail 接口）
        if (ticket == null) {
            ticket = afterSalesTicketMapper.selectOne(
                new LambdaQueryWrapper<AfterSalesTicket>()
                    .eq(AfterSalesTicket::getTicketNo, id)
            );
        }
        if (ticket == null) {
            throw BusinessException.notFound("售后工单");
        }

        // 查询关联订单
        Order order = null;
        if (StringUtils.hasText(ticket.getOrderId())) {
            order = orderMapper.selectById(ticket.getOrderId());
        }

        return convertToDetailResponse(ticket, order);
    }

    /**
     * 创建售后工单
     *
     * @param request  创建请求
     * @param tenantId 租户ID
     * @return 工单详情响应
     */
    @Transactional(rollbackFor = Exception.class)
    public AfterSalesDetailResponse createTicket(AfterSalesCreateRequest request, Long tenantId, String operator) {
        // 校验关联订单是否存在
        Order order = orderMapper.selectById(request.getOrderId());
        if (order == null) {
            throw BusinessException.validationError("关联订单不存在");
        }

        // 防重复：检查该订单是否已有活跃工单
        List<AfterSalesTicket> activeTickets = afterSalesTicketMapper.selectList(
            new LambdaQueryWrapper<AfterSalesTicket>()
                .eq(AfterSalesTicket::getOrderId, request.getOrderId())
                .in(AfterSalesTicket::getStatus, "pending", "processing")
        );
        if (!activeTickets.isEmpty()) {
            boolean hasSameType = activeTickets.stream()
                .anyMatch(t -> request.getTicketType().equals(t.getTicketType()));
            if (hasSameType) {
                throw BusinessException.validationError(
                    String.format("该订单已有 %s 类型的活跃工单（%s），请先处理后再创建",
                        request.getTicketType(),
                        activeTickets.get(0).getTicketNo()));
            }
            // 不同类型 → 记录警告但不阻止
            log.warn("订单 {} 已有活跃工单 {}（类型={}），新建不同类型工单（{}）",
                request.getOrderId(),
                activeTickets.get(0).getTicketNo(),
                activeTickets.get(0).getTicketType(),
                request.getTicketType());
        }

        // 创建工单实体
        AfterSalesTicket ticket = new AfterSalesTicket();
        ticket.setTenantId(tenantId);
        ticket.setTicketNo(generateTicketNo());
        ticket.setOrderId(request.getOrderId());
        // TODO: 当前使用客户名称作为关联标识，后续应改为实际客户ID（需客户表支持手机号→ID查询）
        ticket.setCustomerId(order.getCustomerName());
        ticket.setTicketType(request.getTicketType());
        ticket.setStatus("pending");
        ticket.setDescription(request.getDescription());
        ticket.setSource("agent");
        ticket.setPriority(request.getPriority() != null ? request.getPriority() : "normal");
        ticket.setRefundAmount(request.getRefundAmount());

        // 处理图片
        if (request.getImages() != null && !request.getImages().isEmpty()) {
            ticket.setImages(request.getImages());
        }

        afterSalesTicketMapper.insert(ticket);

        // 写入创建时间线记录
        TicketTimeline createdTimeline = new TicketTimeline();
        createdTimeline.setTicketId(ticket.getId());
        createdTimeline.setTenantId(tenantId);
        createdTimeline.setAction("created");
        createdTimeline.setActorType("agent");
        createdTimeline.setActorId(operator);
        Map<String, Object> createdContent = new HashMap<>();
        createdContent.put("remark", "工单创建");
        createdTimeline.setContent(createdContent);
        createdTimeline.setCreatedAt(ticket.getCreatedAt());
        ticketTimelineMapper.insert(createdTimeline);

        log.info("创建售后工单成功: id={}, ticketNo={}, orderId={}, operator={}",
            ticket.getId(), ticket.getTicketNo(), request.getOrderId(), operator);

        return getTicketById(ticket.getId());
    }

    /**
     * 更新工单状态
     * 遵循状态流转规则：pending -> processing/rejected, processing -> resolved/closed
     *
     * @param id      工单ID
     * @param request 状态更新请求
     */
    @Transactional(rollbackFor = Exception.class)
    public void updateTicketStatus(String id, AfterSalesStatusUpdateRequest request) {
        AfterSalesTicket ticket = afterSalesTicketMapper.selectById(id);
        if (ticket == null) {
            throw BusinessException.notFound("售后工单");
        }

        String newStatus = request.getStatus();

        // 校验状态值
        if (!STATUS_TRANSITIONS.containsKey(newStatus) && !STATUS_TRANSITIONS.values().stream()
                .anyMatch(s -> s.contains(newStatus))) {
            throw BusinessException.validationError("无效的工单状态: " + newStatus);
        }

        // 校验状态流转是否合法
        String currentStatus = ticket.getStatus();
        Set<String> allowedTargets = STATUS_TRANSITIONS.getOrDefault(currentStatus, Set.of());
        if (!allowedTargets.contains(newStatus)) {
            throw BusinessException.validationError(
                    String.format("工单状态不允许从 [%s] 变更为 [%s]", currentStatus, newStatus));
        }

        ticket.setStatus(newStatus);

        // 追加备注到 internal_notes（不覆盖历史评论）
        if (StringUtils.hasText(request.getRemark())) {
            String timestamp = OffsetDateTime.now()
                .format(DateTimeFormatter.ofPattern("MM-dd HH:mm"));
            String newNote = String.format("[%s] %s → %s: %s",
                timestamp, currentStatus, newStatus, request.getRemark());
            String existing = ticket.getInternalNotes();
            if (StringUtils.hasText(existing)) {
                ticket.setInternalNotes(existing + "\n" + newNote);
            } else {
                ticket.setInternalNotes(newNote);
            }
        }

        // 如果是关闭或拒绝，记录关闭时间和原因
        if ("closed".equals(newStatus) || "rejected".equals(newStatus)) {
            ticket.setClosedAt(OffsetDateTime.now());
            if (StringUtils.hasText(request.getRemark())) {
                ticket.setCloseReason(request.getRemark());
            }
        }

        afterSalesTicketMapper.updateById(ticket);

        // 写入时间线记录（每次状态变更都记录）
        TicketTimeline timeline = new TicketTimeline();
        timeline.setTicketId(id);
        timeline.setTenantId(ticket.getTenantId());
        timeline.setAction("status_change");
        timeline.setActorType("system");
        Map<String, Object> content = new HashMap<>();
        content.put("from", currentStatus);
        content.put("to", newStatus);
        content.put("remark", StringUtils.hasText(request.getRemark()) ? request.getRemark() : "");
        timeline.setContent(content);
        timeline.setCreatedAt(OffsetDateTime.now());
        ticketTimelineMapper.insert(timeline);

        log.info("更新工单状态成功: id={}, {} -> {}, remark={}", id, currentStatus, newStatus,
                StringUtils.hasText(request.getRemark()) ? request.getRemark() : "(无)");
    }

    /**
     * 生成工单号（防重启重复）
     * 格式: AS-yyyyMMdd-XXXX，从 DB 查询当天最大序号 +1
     */
    private String generateTicketNo() {
        String datePart = LocalDate.now().format(DateTimeFormatter.ofPattern("yyyyMMdd"));
        String prefix = "AS-" + datePart + "-";

        // 从 DB 查当天最大工单号，防止重启后 AtomicInteger 归零导致重复
        int nextSeq = 1;
        try {
            AfterSalesTicket latest = afterSalesTicketMapper.selectOne(
                new LambdaQueryWrapper<AfterSalesTicket>()
                    .likeRight(AfterSalesTicket::getTicketNo, prefix)
                    .orderByDesc(AfterSalesTicket::getTicketNo)
                    .last("LIMIT 1")
            );
            if (latest != null && latest.getTicketNo() != null) {
                String[] parts = latest.getTicketNo().split("-");
                if (parts.length == 3) {
                    nextSeq = Integer.parseInt(parts[2]) + 1;
                }
            }
        } catch (Exception e) {
            log.warn("查询最新工单号失败，使用默认序号: {}", e.getMessage());
        }

        return String.format("AS-%s-%04d", datePart, nextSeq % 10000);
    }

    /**
     * 转换为列表响应 DTO
     */
    private AfterSalesListResponse convertToListResponse(AfterSalesTicket ticket, Order order) {
        AfterSalesListResponse response = new AfterSalesListResponse();
        response.setId(ticket.getId());
        response.setTicketNo(ticket.getTicketNo());
        response.setOrderId(ticket.getOrderId());
        response.setCustomerId(ticket.getCustomerId());
        response.setTicketType(ticket.getTicketType());
        response.setStatus(ticket.getStatus());
        response.setDescription(ticket.getDescription());
        response.setSource(ticket.getSource());
        response.setPriority(ticket.getPriority());
        response.setHandlerId(ticket.getHandlerId());
        response.setAssignedAt(ticket.getAssignedAt());
        response.setRefundAmount(ticket.getRefundAmount());
        response.setRefundMethod(ticket.getRefundMethod());
        response.setInternalNotes(ticket.getInternalNotes());
        response.setDeadline(ticket.getDeadline());
        response.setClosedAt(ticket.getClosedAt());
        response.setCloseReason(ticket.getCloseReason());
        response.setCreatedAt(ticket.getCreatedAt());
        response.setUpdatedAt(ticket.getUpdatedAt());

        // 处理图片字段（Entity 中为 Object 类型，需转换）
        response.setImages(convertJsonToStringList(ticket.getImages()));
        response.setEvidenceImages(convertJsonToStringList(ticket.getEvidenceImages()));

        // 填充订单信息
        if (order != null) {
            response.setOrderNo(order.getOrderNo());
            response.setCustomerName(order.getCustomerName());
            response.setCustomerPhone(order.getCustomerPhone());
        }

        return response;
    }

    /**
     * 转换为详情响应 DTO
     */
    private AfterSalesDetailResponse convertToDetailResponse(AfterSalesTicket ticket, Order order) {
        AfterSalesDetailResponse response = new AfterSalesDetailResponse();
        response.setId(ticket.getId());
        response.setTicketNo(ticket.getTicketNo());
        response.setOrderId(ticket.getOrderId());
        response.setCustomerId(ticket.getCustomerId());
        response.setTicketType(ticket.getTicketType());
        response.setStatus(ticket.getStatus());
        response.setDescription(ticket.getDescription());
        response.setSource(ticket.getSource());
        response.setPriority(ticket.getPriority());
        response.setHandlerId(ticket.getHandlerId());
        response.setAssignedAt(ticket.getAssignedAt());
        response.setRefundAmount(ticket.getRefundAmount());
        response.setRefundMethod(ticket.getRefundMethod());
        response.setInternalNotes(ticket.getInternalNotes());
        response.setDeadline(ticket.getDeadline());
        response.setClosedAt(ticket.getClosedAt());
        response.setCloseReason(ticket.getCloseReason());
        response.setCreatedAt(ticket.getCreatedAt());
        response.setUpdatedAt(ticket.getUpdatedAt());

        // 处理图片字段
        response.setImages(convertJsonToStringList(ticket.getImages()));
        response.setEvidenceImages(convertJsonToStringList(ticket.getEvidenceImages()));

        // 填充订单信息
        if (order != null) {
            response.setOrderNo(order.getOrderNo());
            response.setCustomerName(order.getCustomerName());
            response.setCustomerPhone(order.getCustomerPhone());
        }

        // 构建状态历史：优先从 ticket_timeline 表读取真实记录
        List<AfterSalesDetailResponse.StatusHistoryItem> history = new ArrayList<>();

        List<TicketTimeline> timelines = ticketTimelineMapper.selectByTicketId(
            ticket.getId(), ticket.getTenantId());
        if (timelines != null && !timelines.isEmpty()) {
            for (TicketTimeline tl : timelines) {
                AfterSalesDetailResponse.StatusHistoryItem item =
                    new AfterSalesDetailResponse.StatusHistoryItem();
                @SuppressWarnings("unchecked")
                Map<String, Object> content = tl.getContent() instanceof Map
                    ? (Map<String, Object>) tl.getContent() : null;
                if (content != null) {
                    String toStatus = String.valueOf(content.getOrDefault("to", ""));
                    // "created" 动作没有 to 状态，默认 pending
                    item.setStatus(toStatus.isEmpty() ? "pending" : toStatus);
                    item.setRemark(String.valueOf(content.getOrDefault("remark", "")));
                }
                if (tl.getActorId() != null) {
                    item.setOperator(tl.getActorId());
                }
                if (tl.getCreatedAt() != null) {
                    item.setTime(tl.getCreatedAt().toString());
                }
                history.add(item);
            }
        } else {
            // 兜底：ticket_timeline 无数据时（仅历史数据），生成简单记录
            if (ticket.getCreatedAt() != null) {
                AfterSalesDetailResponse.StatusHistoryItem created =
                    new AfterSalesDetailResponse.StatusHistoryItem();
                created.setStatus("pending");
                created.setTime(ticket.getCreatedAt().toString());
                created.setOperator("系统");
                created.setRemark("工单创建");
                history.add(created);
            }
        }

        response.setStatusHistory(history);

        return response;
    }

    /**
     * 将 Entity 中的 Object 类型 JSON 字段转换为 List<String>
     */
    @SuppressWarnings("unchecked")
    private List<String> convertJsonToStringList(Object jsonObj) {
        if (jsonObj == null) {
            return null;
        }
        try {
            if (jsonObj instanceof List) {
                return (List<String>) jsonObj;
            }
            if (jsonObj instanceof String) {
                return objectMapper.readValue((String) jsonObj, new TypeReference<List<String>>() {});
            }
            return objectMapper.convertValue(jsonObj, new TypeReference<List<String>>() {});
        } catch (Exception e) {
            log.warn("转换 JSON 到 List<String> 失败: {}", e.getMessage());
            return null;
        }
    }
}
