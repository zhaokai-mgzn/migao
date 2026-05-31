package com.aikf.admin.service;

import com.aikf.admin.config.TenantContext;
import com.aikf.admin.dto.*;
import com.aikf.admin.entity.Order;
import com.aikf.admin.entity.OrderItem;
import com.aikf.admin.entity.OrderLogistics;
import com.aikf.admin.exception.BusinessException;
import com.aikf.admin.mapper.OrderItemMapper;
import com.aikf.admin.mapper.OrderLogisticsMapper;
import com.aikf.admin.mapper.OrderMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.BeanUtils;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ThreadLocalRandom;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.stream.Collectors;

/**
 * 订单服务类
 * 处理订单的增删改查、状态更新等操作
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class OrderService extends ServiceImpl<OrderMapper, Order> {

    private final OrderMapper orderMapper;
    private final OrderItemMapper orderItemMapper;
    private final OrderLogisticsMapper orderLogisticsMapper;
    private final CustomerService customerService;

    /**
     * 订单号序列号（线程安全）
     */
    private static final AtomicInteger ORDER_SEQ = new AtomicInteger(0);

    /**
     * 合法的状态流转定义
     * key: 当前状态, value: 允许流转到的目标状态集合
     */
    private static final Map<String, Set<String>> STATUS_TRANSITIONS = Map.of(
            "pending", Set.of("confirmed", "cancelled"),
            "confirmed", Set.of("producing", "cancelled"),
            "producing", Set.of("shipped", "cancelled"),
            "shipped", Set.of("completed"),
            "completed", Set.of(),
            "cancelled", Set.of()
    );

    /**
     * 分页查询订单列表
     *
     * @param page         页码
     * @param size         每页大小
     * @param status       订单状态
     * @param keyword      搜索关键词（客户姓名/电话/订单号）
     * @param followStatus 跟进状态
     * @param tenantId     租户ID
     * @return 分页响应
     */
    public PageResponse<OrderListResponse> getOrderPage(long page, long size, String status, String keyword, String followStatus, Long tenantId) {
        LambdaQueryWrapper<Order> wrapper = new LambdaQueryWrapper<>();

        // 状态筛选
        if (StringUtils.hasText(status)) {
            wrapper.eq(Order::getStatus, status);
        }

        // 跟进状态筛选
        if (StringUtils.hasText(followStatus)) {
            wrapper.eq(Order::getFollowStatus, followStatus);
        }

        // 关键词搜索（客户姓名/电话/订单号）
        if (StringUtils.hasText(keyword)) {
            wrapper.and(w -> w.like(Order::getCustomerName, keyword)
                    .or()
                    .like(Order::getCustomerPhone, keyword)
                    .or()
                    .like(Order::getOrderNo, keyword));
        }

        // 按创建时间倒序
        wrapper.orderByDesc(Order::getCreatedAt);

        // 执行分页查询
        Page<Order> orderPage = new Page<>(page, size);
        Page<Order> resultPage = orderMapper.selectPage(orderPage, wrapper);

        // 转换为响应 DTO
        List<OrderListResponse> responses = resultPage.getRecords().stream()
                .map(this::convertToListResponse)
                .collect(Collectors.toList());

        // 批量补充订单明细，避免 N+1 查询；前端列表"采购商品"列依赖 items[0]
        List<String> orderIds = responses.stream()
                .map(OrderListResponse::getId)
                .collect(Collectors.toList());
        if (!orderIds.isEmpty()) {
            List<OrderItem> allItems = orderItemMapper.selectList(
                    new LambdaQueryWrapper<OrderItem>().in(OrderItem::getOrderId, orderIds)
            );
            Map<String, List<OrderItem>> itemsMap = allItems.stream()
                    .collect(Collectors.groupingBy(OrderItem::getOrderId));
            for (OrderListResponse resp : responses) {
                List<OrderItem> orderItems = itemsMap.getOrDefault(resp.getId(), Collections.emptyList());
                resp.setItems(orderItems.stream()
                        .map(item -> new OrderListResponse.OrderItemBrief(
                                item.getProductId(),
                                item.getProductName(),
                                null,
                                item.getQuantity(),
                                item.getUnitPrice()
                        ))
                        .collect(Collectors.toList()));
                // 后端统一计算加工费与实收款，避免前端重复计算
                BigDecimal processingFee = orderItems.stream()
                        .map(item -> sumProcessingFee(item.getProcessingInfo()))
                        .reduce(BigDecimal.ZERO, BigDecimal::add);
                resp.setProcessingFee(processingFee);
                resp.setActualAmount(resp.getTotalAmount());
            }
        } else {
            for (OrderListResponse resp : responses) {
                resp.setItems(Collections.emptyList());
                resp.setProcessingFee(BigDecimal.ZERO);
                resp.setActualAmount(resp.getTotalAmount());
            }
        }

        return PageResponse.of(resultPage.getTotal(), resultPage.getCurrent(), resultPage.getSize(), responses);
    }

    /**
     * 根据ID查询订单详情（含订单明细和物流信息）
     *
     * @param id 订单ID
     * @return 订单详情响应
     */
    public OrderDetailResponse getOrderById(String id) {
        Order order = orderMapper.selectById(id);
        if (order == null) {
            throw BusinessException.notFound("订单");
        }

        return convertToDetailResponse(order);
    }

    /**
     * 创建订单
     *
     * @param request  创建请求
     * @param tenantId 租户ID
     * @return 订单详情响应
     */
    @Transactional(rollbackFor = Exception.class)
    public OrderDetailResponse createOrder(OrderCreateRequest request, Long tenantId) {
        // 计算总金额：优先使用 subtotal，若为 null 则回退 unitPrice * quantity，避免 totalAmount=0
        BigDecimal totalAmount = request.getItems().stream()
                .map(this::resolveItemSubtotal)
                .reduce(BigDecimal.ZERO, BigDecimal::add);

        // 创建订单实体
        Order order = new Order();
        order.setTenantId(tenantId);
        order.setOrderNo(generateOrderNo());
        order.setCustomerName(request.getCustomerName());
        order.setCustomerPhone(request.getCustomerPhone());
        order.setCustomerAddress(request.getCustomerAddress());
        order.setTotalAmount(totalAmount);
        order.setStatus("pending");
        order.setRemark(request.getRemark());

        // 保存订单
        orderMapper.insert(order);

        // 保存订单明细
        for (OrderCreateRequest.OrderItemRequest itemRequest : request.getItems()) {
            OrderItem item = new OrderItem();
            item.setTenantId(tenantId);
            item.setOrderId(order.getId());
            item.setProductId(itemRequest.getProductId());
            item.setProductName(itemRequest.getProductName());
            item.setQuantity(itemRequest.getQuantity());
            item.setUnitPrice(itemRequest.getUnitPrice());
            item.setWidth(itemRequest.getWidth());
            item.setHeight(itemRequest.getHeight());
            item.setProcessingInfo(itemRequest.getProcessingInfo());
            item.setSubtotal(resolveItemSubtotal(itemRequest));
            orderItemMapper.insert(item);
        }

        log.info("创建订单成功: id={}, orderNo={}, totalAmount={}", order.getId(), order.getOrderNo(), totalAmount);

        // 首次下单自动创建客户档案（失败不影响订单创建）
        try {
            customerService.createFromOrder(tenantId, request.getCustomerName(),
                    request.getCustomerPhone(), request.getCustomerAddress());
        } catch (Exception e) {
            log.warn("订单创建后自动建档客户失败，忽略: orderId={}, phone={}, error={}",
                    order.getId(), request.getCustomerPhone(), e.getMessage());
        }

        return getOrderById(order.getId());
    }

    /**
     * 更新订单状态
     * 遵循状态流转规则：pending -> confirmed -> producing -> shipped -> completed
     * 支持取消订单（pending / confirmed / producing 状态下）
     *
     * @param id     订单ID
     * @param status 新状态
     */
    @Transactional(rollbackFor = Exception.class)
    public void updateOrderStatus(String id, String status) {
        Order order = orderMapper.selectById(id);
        if (order == null) {
            throw BusinessException.notFound("订单");
        }

        // 校验状态值
        if (!STATUS_TRANSITIONS.containsKey(status)) {
            throw BusinessException.validationError("无效的订单状态: " + status);
        }

        // 校验状态流转是否合法
        String currentStatus = order.getStatus();
        Set<String> allowedTargets = STATUS_TRANSITIONS.getOrDefault(currentStatus, Set.of());
        if (!allowedTargets.contains(status)) {
            throw BusinessException.validationError(
                    String.format("订单状态不允许从 [%s] 变更为 [%s]", currentStatus, status));
        }

        order.setStatus(status);
        orderMapper.updateById(order);

        log.info("更新订单状态成功: id={}, {} -> {}", id, currentStatus, status);
    }

    /**
     * 删除订单（逻辑删除，仅允许待确认状态）
     *
     * @param id 订单ID
     */
    @Transactional(rollbackFor = Exception.class)
    public void deleteOrder(String id) {
        Order order = orderMapper.selectById(id);
        if (order == null) {
            throw BusinessException.notFound("订单");
        }

        // 仅允许待确认状态的订单被删除
        if (!"pending".equals(order.getStatus())) {
            throw BusinessException.validationError("仅允许删除待确认状态的订单，当前状态: " + order.getStatus());
        }

        // 逻辑删除订单
        orderMapper.deleteById(id);

        // 逻辑删除订单明细
        LambdaQueryWrapper<OrderItem> wrapper = new LambdaQueryWrapper<>();
        wrapper.eq(OrderItem::getOrderId, id);
        List<OrderItem> items = orderItemMapper.selectList(wrapper);
        for (OrderItem item : items) {
            orderItemMapper.deleteById(item.getId());
        }

        log.info("删除订单成功: id={}, orderNo={}", id, order.getOrderNo());
    }

    /**
     * 生成订单号
     * 格式: ORD-yyyyMMdd-XXXXXXYYYY（毫秒后6位+4位随机数，重启不冲突）
     */
    private String generateOrderNo() {
        String datePart = LocalDate.now().format(DateTimeFormatter.ofPattern("yyyyMMdd"));
        // 使用毫秒时间戳后6位 + 4位随机数，确保重启后不冲突
        long millis = System.currentTimeMillis() % 1000000;
        int random = ThreadLocalRandom.current().nextInt(1000, 9999);
        return String.format("ORD-%s-%06d%04d", datePart, millis, random);
    }

    /**
     * 转换为列表响应 DTO
     */
    private OrderListResponse convertToListResponse(Order order) {
        OrderListResponse response = new OrderListResponse();
        BeanUtils.copyProperties(order, response);
        return response;
    }

    /**
     * 转换为详情响应 DTO（含订单明细和物流信息）
     */
    private OrderDetailResponse convertToDetailResponse(Order order) {
        OrderDetailResponse response = new OrderDetailResponse();
        BeanUtils.copyProperties(order, response);

        // 查询订单明细（使用 LambdaQueryWrapper 走 BaseMapper，确保 processingInfo 经过 JacksonTypeHandler 反序列化为 Map）
        List<OrderItem> items = orderItemMapper.selectList(
                new LambdaQueryWrapper<OrderItem>()
                        .eq(OrderItem::getOrderId, order.getId())
                        .eq(OrderItem::getTenantId, order.getTenantId())
        );
        List<OrderDetailResponse.OrderItemResponse> itemResponses = items.stream()
                .map(this::convertToItemResponse)
                .collect(Collectors.toList());
        response.setItems(itemResponses);

        // 后端统一聚合加工项，并计算加工费 / 实收款（架构决策：费用计算全部在后端）
        List<OrderDetailResponse.ProcessingItemBrief> aggregatedProcessing = new ArrayList<>();
        BigDecimal processingFee = BigDecimal.ZERO;
        for (OrderItem item : items) {
            List<OrderDetailResponse.ProcessingItemBrief> briefs = extractProcessingItems(item.getProcessingInfo());
            for (OrderDetailResponse.ProcessingItemBrief brief : briefs) {
                aggregatedProcessing.add(brief);
                if (brief.getAmount() != null) {
                    processingFee = processingFee.add(brief.getAmount());
                }
            }
        }
        response.setProcessingItems(aggregatedProcessing);
        response.setProcessingFee(processingFee);
        // 当前阶段：实收款 = 总金额；后续支持优惠/部分付款时再调整
        response.setActualAmount(order.getTotalAmount());

        // 查询物流信息
        List<OrderLogistics> logisticsList = orderLogisticsMapper.selectByOrderId(order.getId(), TenantContext.getTenantId());
        if (logisticsList != null && !logisticsList.isEmpty()) {
            OrderLogistics logistics = logisticsList.get(0); // 取最新一条
            OrderDetailResponse.LogisticsInfo logisticsInfo = new OrderDetailResponse.LogisticsInfo();
            logisticsInfo.setId(logistics.getId());
            logisticsInfo.setLogisticsCompany(logistics.getLogisticsCompany());
            logisticsInfo.setTrackingNo(logistics.getTrackingNo());
            logisticsInfo.setStatus(logistics.getStatus());
            logisticsInfo.setTrackingInfo(logistics.getTrackingInfo());
            logisticsInfo.setShippedAt(logistics.getShippedAt());
            logisticsInfo.setDeliveredAt(logistics.getDeliveredAt());
            response.setLogistics(logisticsInfo);
        }

        return response;
    }

    /**
     * 从订单明细的 processingInfo（JSON）中解析加工项列表。
     * processingInfo 格式来自前端创建订单时写入：
     * { "processingFee": <number>, "processingItems": [ { id,name,unitPrice,quantity,unit } ] , ... }
     * 解析失败/缺字段时返回空列表，确保不影响订单查询主流程。
     */
    @SuppressWarnings("unchecked")
    private List<OrderDetailResponse.ProcessingItemBrief> extractProcessingItems(Object processingInfo) {
        if (!(processingInfo instanceof Map)) {
            return Collections.emptyList();
        }
        try {
            Map<String, Object> info = (Map<String, Object>) processingInfo;
            Object raw = info.get("processingItems");
            if (!(raw instanceof List)) {
                return Collections.emptyList();
            }
            List<Object> rawList = (List<Object>) raw;
            List<OrderDetailResponse.ProcessingItemBrief> result = new ArrayList<>();
            for (Object element : rawList) {
                if (!(element instanceof Map)) {
                    continue;
                }
                Map<String, Object> entry = (Map<String, Object>) element;
                OrderDetailResponse.ProcessingItemBrief brief = new OrderDetailResponse.ProcessingItemBrief();
                Object id = entry.get("id");
                brief.setId(id != null ? String.valueOf(id) : null);
                Object name = entry.get("name");
                brief.setName(name != null ? String.valueOf(name) : null);
                BigDecimal unitPrice = toBigDecimal(entry.get("unitPrice"));
                brief.setUnitPrice(unitPrice);
                Integer quantity = toInteger(entry.get("quantity"));
                brief.setQuantity(quantity);
                BigDecimal amount = BigDecimal.ZERO;
                if (unitPrice != null && quantity != null) {
                    amount = unitPrice.multiply(BigDecimal.valueOf(quantity));
                }
                brief.setAmount(amount);
                result.add(brief);
            }
            return result;
        } catch (Exception e) {
            log.warn("解析 processingInfo 失败，返回空加工项列表: {}", e.getMessage());
            return Collections.emptyList();
        }
    }

    /**
     * 计算单个订单明细 processingInfo 的加工费（仅供列表场景使用，无需返回详情）。
     */
    private BigDecimal sumProcessingFee(Object processingInfo) {
        return extractProcessingItems(processingInfo).stream()
                .map(OrderDetailResponse.ProcessingItemBrief::getAmount)
                .filter(java.util.Objects::nonNull)
                .reduce(BigDecimal.ZERO, BigDecimal::add);
    }

    private BigDecimal toBigDecimal(Object value) {
        if (value == null) return null;
        if (value instanceof BigDecimal) return (BigDecimal) value;
        if (value instanceof Number) return BigDecimal.valueOf(((Number) value).doubleValue());
        try {
            return new BigDecimal(String.valueOf(value));
        } catch (NumberFormatException e) {
            return null;
        }
    }

    private Integer toInteger(Object value) {
        if (value == null) return null;
        if (value instanceof Number) return ((Number) value).intValue();
        try {
            return Integer.valueOf(String.valueOf(value));
        } catch (NumberFormatException e) {
            return null;
        }
    }

    /**
     * 计算/解析订单明细小计：优先使用请求中的 subtotal，若为 null 则回退 unitPrice * quantity。
     * 避免前端未传 subtotal 时 totalAmount 被记录为 0 的问题。
     */
    private BigDecimal resolveItemSubtotal(OrderCreateRequest.OrderItemRequest itemRequest) {
        if (itemRequest.getSubtotal() != null) {
            return itemRequest.getSubtotal();
        }
        if (itemRequest.getUnitPrice() != null && itemRequest.getQuantity() != null) {
            return itemRequest.getUnitPrice().multiply(BigDecimal.valueOf(itemRequest.getQuantity()));
        }
        return BigDecimal.ZERO;
    }

    /**
     * 转换为订单明细响应 DTO
     */
    private OrderDetailResponse.OrderItemResponse convertToItemResponse(OrderItem item) {
        OrderDetailResponse.OrderItemResponse response = new OrderDetailResponse.OrderItemResponse();
        BeanUtils.copyProperties(item, response);
        // 计算 amount = unitPrice * quantity（优先），否则回退 subtotal
        if (item.getUnitPrice() != null && item.getQuantity() != null) {
            response.setAmount(item.getUnitPrice().multiply(BigDecimal.valueOf(item.getQuantity())));
        } else {
            response.setAmount(item.getSubtotal());
        }
        return response;
    }

    // ==================== 订单统计与跟进状态 ====================

    /**
     * 获取订单统计
     */
    public OrderStatisticsResponse getOrderStatistics(Long tenantId) {
        LambdaQueryWrapper<Order> wrapper = new LambdaQueryWrapper<>();
        List<Order> orders = orderMapper.selectList(wrapper);

        long total = orders.size();
        long pending = orders.stream().filter(o -> "pending".equals(o.getStatus())).count();
        long confirmed = orders.stream().filter(o -> "confirmed".equals(o.getStatus())).count();
        long producing = orders.stream().filter(o -> "producing".equals(o.getStatus())).count();
        long shipped = orders.stream().filter(o -> "shipped".equals(o.getStatus())).count();
        long completed = orders.stream().filter(o -> "completed".equals(o.getStatus())).count();
        long cancelled = orders.stream().filter(o -> "cancelled".equals(o.getStatus())).count();

        return OrderStatisticsResponse.builder()
                .totalCount(total)
                .pendingCount(pending)
                .confirmedCount(confirmed)
                .producingCount(producing)
                .shippedCount(shipped)
                .completedCount(completed)
                .cancelledCount(cancelled)
                .unpaidCount(pending)
                .paidCount(confirmed + producing + shipped + completed)
                .refundedCount(0)
                .build();
    }

    /**
     * 获取跟进状态统计
     */
    public FollowStatusStatsResponse getFollowStatusStats(Long tenantId) {
        LambdaQueryWrapper<Order> wrapper = new LambdaQueryWrapper<>();
        List<Order> orders = orderMapper.selectList(wrapper);

        long total = orders.size();
        long pendingFollow = orders.stream()
                .filter(o -> o.getFollowStatus() == null || "pending".equals(o.getFollowStatus()))
                .count();
        long following = orders.stream().filter(o -> "following".equals(o.getFollowStatus())).count();
        long completedFollow = orders.stream().filter(o -> "completed".equals(o.getFollowStatus())).count();

        return FollowStatusStatsResponse.builder()
                .pending(pendingFollow)
                .following(following)
                .completed(completedFollow)
                .total(total)
                .build();
    }

    /**
     * 确认支付
     */
    @Transactional(rollbackFor = Exception.class)
    public void confirmPayment(String id) {
        Order order = orderMapper.selectById(id);
        if (order == null) {
            throw BusinessException.notFound("订单");
        }
        if (!"pending".equals(order.getStatus())) {
            throw BusinessException.validationError("只有待确认状态的订单可以确认支付");
        }
        order.setStatus("confirmed");
        orderMapper.updateById(order);
        log.info("确认支付成功: id={}", id);
    }

    /**
     * 取消订单
     */
    @Transactional(rollbackFor = Exception.class)
    public void cancelOrder(String id) {
        Order order = orderMapper.selectById(id);
        if (order == null) {
            throw BusinessException.notFound("订单");
        }
        Set<String> cancellableStatuses = Set.of("pending", "confirmed", "producing");
        if (!cancellableStatuses.contains(order.getStatus())) {
            throw BusinessException.validationError("当前状态不允许取消");
        }
        order.setStatus("cancelled");
        orderMapper.updateById(order);
        log.info("取消订单成功: id={}", id);
    }

    /**
     * 退款
     */
    @Transactional(rollbackFor = Exception.class)
    public void refundOrder(String id) {
        Order order = orderMapper.selectById(id);
        if (order == null) {
            throw BusinessException.notFound("订单");
        }
        order.setStatus("cancelled");
        orderMapper.updateById(order);
        log.info("退款成功: id={}", id);
    }

    /**
     * 获取订单跟进状态
     */
    public FollowStatusResponse getFollowStatus(String id) {
        Order order = orderMapper.selectById(id);
        if (order == null) {
            throw BusinessException.notFound("订单");
        }
        return FollowStatusResponse.builder()
                .orderId(id)
                .followStatus(order.getFollowStatus() != null ? order.getFollowStatus() : "pending")
                .updatedAt(order.getUpdatedAt())
                .build();
    }

    /**
     * 更新跟进状态
     */
    @Transactional(rollbackFor = Exception.class)
    public void updateFollowStatus(String id, String followStatus) {
        Order order = orderMapper.selectById(id);
        if (order == null) {
            throw BusinessException.notFound("订单");
        }
        order.setFollowStatus(followStatus);
        orderMapper.updateById(order);
        log.info("更新跟进状态成功: id={}, followStatus={}", id, followStatus);
    }
}
