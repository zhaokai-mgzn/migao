package com.migao.admin.service;

import com.migao.admin.dto.*;
import com.migao.admin.entity.AfterSalesTicket;
import com.migao.admin.entity.Order;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.AfterSalesTicketMapper;
import com.migao.admin.mapper.OrderMapper;
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
import java.util.concurrent.atomic.AtomicInteger;
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
    private final ObjectMapper objectMapper;

    /**
     * 工单号序列号（线程安全）
     */
    private static final AtomicInteger TICKET_SEQ = new AtomicInteger(0);

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
        AfterSalesTicket ticket = afterSalesTicketMapper.selectById(id);
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
    public AfterSalesDetailResponse createTicket(AfterSalesCreateRequest request, Long tenantId) {
        // 校验关联订单是否存在
        Order order = orderMapper.selectById(request.getOrderId());
        if (order == null) {
            throw BusinessException.validationError("关联订单不存在");
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

        log.info("创建售后工单成功: id={}, ticketNo={}, orderId={}", ticket.getId(), ticket.getTicketNo(), request.getOrderId());

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

        // 如果是关闭或拒绝，记录关闭时间和原因
        if ("closed".equals(newStatus) || "rejected".equals(newStatus)) {
            ticket.setClosedAt(OffsetDateTime.now());
            if (StringUtils.hasText(request.getRemark())) {
                ticket.setCloseReason(request.getRemark());
            }
        }

        afterSalesTicketMapper.updateById(ticket);

        log.info("更新工单状态成功: id={}, {} -> {}", id, currentStatus, newStatus);
    }

    /**
     * 生成工单号
     * 格式: AS-yyyyMMdd-XXXX（线程安全）
     */
    private String generateTicketNo() {
        String datePart = LocalDate.now().format(DateTimeFormatter.ofPattern("yyyyMMdd"));
        int seq = TICKET_SEQ.incrementAndGet() % 10000;
        return String.format("AS-%s-%04d", datePart, seq);
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

        // 构建状态历史（基于当前状态生成简单历史）
        List<AfterSalesDetailResponse.StatusHistoryItem> history = new ArrayList<>();

        // 创建时间作为第一条历史
        if (ticket.getCreatedAt() != null) {
            AfterSalesDetailResponse.StatusHistoryItem created = new AfterSalesDetailResponse.StatusHistoryItem();
            created.setStatus("pending");
            created.setTime(ticket.getCreatedAt().toString());
            created.setOperator("系统");
            created.setRemark("工单创建");
            history.add(created);
        }

        // 如果状态已经变更，添加当前状态记录
        if (!"pending".equals(ticket.getStatus()) && ticket.getUpdatedAt() != null) {
            AfterSalesDetailResponse.StatusHistoryItem current = new AfterSalesDetailResponse.StatusHistoryItem();
            current.setStatus(ticket.getStatus());
            current.setTime(ticket.getUpdatedAt().toString());
            if ("closed".equals(ticket.getStatus()) || "rejected".equals(ticket.getStatus())) {
                current.setRemark(ticket.getCloseReason());
            }
            history.add(current);
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
