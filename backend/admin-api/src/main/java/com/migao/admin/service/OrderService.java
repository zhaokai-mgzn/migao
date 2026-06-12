package com.migao.admin.service;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.*;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.entity.OrderLogistics;
import com.migao.admin.entity.Product;
import com.migao.admin.entity.ProductSku;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderLogisticsMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProductMapper;
import com.migao.admin.mapper.ProductSkuMapper;
import com.fasterxml.jackson.databind.ObjectMapper;
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
import java.time.OffsetDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.Set;
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
    private final ProductMapper productMapper;
    private final ProductSkuMapper productSkuMapper;
    private final ObjectMapper objectMapper;

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
            "confirmed", Set.of("producing", "shipped", "cancelled"),
            "producing", Set.of("shipped", "cancelled"),
            "shipped", Set.of("completed"),
            "completed", Set.of(),
            "cancelled", Set.of()
    );

    /**
     * 分页查询订单列表
     *
     * @param page            页码
     * @param size            每页大小
     * @param status          订单状态
     * @param keyword         搜索关键词（客户姓名/电话/订单号）
     * @param followStatus    跟进状态
     * @param hasProcessing   是否含加工项（true=只查含加工项，false=只查不含加工项，null=不过滤）
     * @param startDate       开始日期（YYYY-MM-DD 格式）
     * @param endDate         结束日期（YYYY-MM-DD 格式）
     * @param tenantId        租户ID
     * @return 分页响应
     */
    public PageResponse<OrderListResponse> getOrderPage(long page, long size, String status, String keyword, String followStatus, Boolean hasProcessing, String startDate, String endDate, String orderId, String receiver, String productCode, String productTitle, Long tenantId) {
        LambdaQueryWrapper<Order> wrapper = new LambdaQueryWrapper<>();

        // 状态筛选
        if (StringUtils.hasText(status)) {
            wrapper.eq(Order::getStatus, status);
        }

        // 跟进状态筛选
        if (StringUtils.hasText(followStatus)) {
            wrapper.eq(Order::getFollowStatus, followStatus);
        }

        // 时间范围筛选
        if (StringUtils.hasText(startDate)) {
            wrapper.ge(Order::getCreatedAt, OffsetDateTime.parse(startDate + "T00:00:00Z"));
        }
        if (StringUtils.hasText(endDate)) {
            wrapper.le(Order::getCreatedAt, OffsetDateTime.parse(endDate + "T23:59:59Z"));
        }

        // 订单ID精确搜索
        if (StringUtils.hasText(orderId)) {
            wrapper.like(Order::getOrderNo, orderId);
        }

        // 收货人搜索（姓名或手机号）
        if (StringUtils.hasText(receiver)) {
            wrapper.and(w -> w.like(Order::getCustomerName, receiver)
                    .or()
                    .like(Order::getCustomerPhone, receiver));
        }

        // 商品货号/标题搜索：通过子查询 order_items 表筛选包含该商品的订单
        if (StringUtils.hasText(productCode) || StringUtils.hasText(productTitle)) {
            LambdaQueryWrapper<OrderItem> itemWrapper = new LambdaQueryWrapper<>();
            if (StringUtils.hasText(productCode)) {
                itemWrapper.eq(OrderItem::getProductId, productCode);
            }
            if (StringUtils.hasText(productTitle)) {
                itemWrapper.like(OrderItem::getProductName, productTitle);
            }
            itemWrapper.select(OrderItem::getOrderId);
            List<String> matchedOrderIds = orderItemMapper.selectList(itemWrapper).stream()
                    .map(OrderItem::getOrderId)
                    .distinct()
                    .collect(Collectors.toList());
            if (matchedOrderIds.isEmpty()) {
                return PageResponse.of(0L, page, size, Collections.emptyList());
            }
            wrapper.in(Order::getId, matchedOrderIds);
        }

        // 关键词搜索（客户姓名/电话/订单号，与分字段搜索取 OR）
        if (StringUtils.hasText(keyword)) {
            wrapper.and(w -> w.like(Order::getCustomerName, keyword)
                    .or()
                    .like(Order::getCustomerPhone, keyword)
                    .or()
                    .like(Order::getOrderNo, keyword));
        }

        // 含加工项过滤：通过子查询 order_items 表，筛选含/不含加工项的订单
        // 注：tenant_id 由 TenantLineInnerInterceptor 自动注入，无需手动添加
        if (hasProcessing != null) {
            Set<String> orderIdsWithProcessing = orderItemMapper.selectList(
                new LambdaQueryWrapper<OrderItem>()
                    .isNotNull(OrderItem::getProcessingInfo)
                    .select(OrderItem::getOrderId)
            ).stream()
                .filter(item -> !extractProcessingItems(item.getProcessingInfo()).isEmpty())
                .map(OrderItem::getOrderId)
                .collect(Collectors.toSet());

            if (hasProcessing) {
                // 只查询含加工项的订单
                if (orderIdsWithProcessing.isEmpty()) {
                    return PageResponse.of(0L, page, size, Collections.emptyList());
                }
                wrapper.in(Order::getId, orderIdsWithProcessing);
            } else {
                // 只查询不含加工项的订单
                if (!orderIdsWithProcessing.isEmpty()) {
                    wrapper.notIn(Order::getId, orderIdsWithProcessing);
                }
            }
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
                        .map(item -> {
                            // amount = unitPrice * quantity（兜底：subtotal）
                            BigDecimal itemAmount = BigDecimal.ZERO;
                            if (item.getUnitPrice() != null && item.getQuantity() != null) {
                                itemAmount = item.getUnitPrice().multiply(BigDecimal.valueOf(item.getQuantity()));
                            } else if (item.getSubtotal() != null) {
                                itemAmount = item.getSubtotal();
                            }
                            return new OrderListResponse.OrderItemBrief(
                                    item.getProductId(),
                                    item.getProductName(),
                                    null,  // productCode: OrderItem 实体暂无此字段
                                    item.getQuantity(),
                                    item.getUnitPrice(),
                                    itemAmount,
                                    item.getSubtotal(),
                                    item.getProcessingInfo()  // 销售信息
                            );
                        })
                        .collect(Collectors.toList()));
                // 后端统一计算加工费与实收款，避免前端重复计算
                BigDecimal processingFee = orderItems.stream()
                        .map(item -> sumProcessingFee(item.getProcessingInfo()))
                        .reduce(BigDecimal.ZERO, BigDecimal::add);
                resp.setProcessingFee(processingFee);
                resp.setActualAmount(resp.getTotalAmount());
                // 判断是否含加工项：复用 extractProcessingItems 解析，避免空 JSONB 对象误判
                boolean itemHasProcessing = orderItems.stream()
                        .anyMatch(item -> !extractProcessingItems(item.getProcessingInfo()).isEmpty());
                resp.setHasProcessing(itemHasProcessing);
            }
        } else {
            for (OrderListResponse resp : responses) {
                resp.setItems(Collections.emptyList());
                resp.setProcessingFee(BigDecimal.ZERO);
                resp.setHasProcessing(false);
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
        // 计算总金额（后端独立计算：unitPrice * quantity + 加工费，不依赖前端 subtotal 防止不一致）
        BigDecimal totalAmount = BigDecimal.ZERO;
        for (OrderCreateRequest.OrderItemRequest itemRequest : request.getItems()) {
            // 商品金额 = 单价 × 数量
            BigDecimal itemAmount = BigDecimal.ZERO;
            if (itemRequest.getUnitPrice() != null && itemRequest.getQuantity() != null) {
                itemAmount = itemRequest.getUnitPrice().multiply(BigDecimal.valueOf(itemRequest.getQuantity()));
            }
            // 加工费（从 processingInfo 中解析）
            BigDecimal processingFee = sumProcessingFee(itemRequest.getProcessingInfo());
            totalAmount = totalAmount.add(itemAmount).add(processingFee);
        }

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
     * 格式: 17位纯数字 = yyyyMMdd(8) + 9位随机数，简洁唯一
     */
    private String generateOrderNo() {
        String datePart = LocalDate.now().format(DateTimeFormatter.ofPattern("yyyyMMdd"));
        // 9位随机数：取 nanoTime 尾9位取绝对值，确保非负
        long raw = System.nanoTime() % 1_000_000_000L;
        long suffix = raw < 0 ? -raw : raw;
        return String.format("%s%09d", datePart, suffix);
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
     * 获取订单统计（使用 COUNT 查询，避免全量加载到内存）
     */
    public OrderStatisticsResponse getOrderStatistics(Long tenantId) {
        long total = orderMapper.selectCount(new LambdaQueryWrapper<Order>()
                .eq(Order::getTenantId, tenantId));
        long pending = orderMapper.selectCount(new LambdaQueryWrapper<Order>()
                .eq(Order::getTenantId, tenantId).eq(Order::getStatus, "pending"));
        long confirmed = orderMapper.selectCount(new LambdaQueryWrapper<Order>()
                .eq(Order::getTenantId, tenantId).eq(Order::getStatus, "confirmed"));
        long producing = orderMapper.selectCount(new LambdaQueryWrapper<Order>()
                .eq(Order::getTenantId, tenantId).eq(Order::getStatus, "producing"));
        long shipped = orderMapper.selectCount(new LambdaQueryWrapper<Order>()
                .eq(Order::getTenantId, tenantId).eq(Order::getStatus, "shipped"));
        long completed = orderMapper.selectCount(new LambdaQueryWrapper<Order>()
                .eq(Order::getTenantId, tenantId).eq(Order::getStatus, "completed"));
        long cancelled = orderMapper.selectCount(new LambdaQueryWrapper<Order>()
                .eq(Order::getTenantId, tenantId).eq(Order::getStatus, "cancelled"));

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
                .refundedCount(cancelled) // 退款订单即已取消的订单
                .build();
    }

    /**
     * 获取跟进状态统计（使用 COUNT 查询，避免全量加载到内存）
     */
    public FollowStatusStatsResponse getFollowStatusStats(Long tenantId) {
        long total = orderMapper.selectCount(new LambdaQueryWrapper<Order>()
                .eq(Order::getTenantId, tenantId));
        long following = orderMapper.selectCount(new LambdaQueryWrapper<Order>()
                .eq(Order::getTenantId, tenantId).eq(Order::getFollowStatus, "following"));
        long completedFollow = orderMapper.selectCount(new LambdaQueryWrapper<Order>()
                .eq(Order::getTenantId, tenantId).eq(Order::getFollowStatus, "completed"));
        // pending = total - following - completed（含 null 值）
        long pendingFollow = total - following - completedFollow;

        return FollowStatusStatsResponse.builder()
                .pending(pendingFollow)
                .following(following)
                .completed(completedFollow)
                .total(total)
                .build();
    }

    /**
     * 确认支付
     * 状态流转：pending → confirmed，同时扣减库存、增加销量
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

        // 扣减库存 + 增加销量
        deductStockAndIncreaseSales(id);
        log.info("确认支付成功: id={}", id);
    }

    /**
     * 取消/关闭订单
     * 支持从 pending/confirmed/producing 状态取消，恢复库存和销量
     *
     * @param id          订单ID
     * @param closeReason 关闭原因（可选）
     */
    @Transactional(rollbackFor = Exception.class)
    public void cancelOrder(String id, String closeReason) {
        Order order = orderMapper.selectById(id);
        if (order == null) {
            throw BusinessException.notFound("订单");
        }
        Set<String> cancellableStatuses = Set.of("pending", "confirmed", "producing");
        if (!cancellableStatuses.contains(order.getStatus())) {
            throw BusinessException.validationError("当前状态不允许取消");
        }

        String previousStatus = order.getStatus();
        order.setStatus("cancelled");
        if (closeReason != null && !closeReason.isBlank()) {
            if (closeReason.length() > 500) {
                throw BusinessException.validationError("关闭原因不能超过 500 个字符");
            }
            order.setCloseReason(closeReason);
        }
        orderMapper.updateById(order);

        // 已确认的订单被取消时，恢复库存和销量
        if ("confirmed".equals(previousStatus) || "producing".equals(previousStatus)) {
            restoreStockAndDecreaseSales(id);
        }
        log.info("取消订单成功: id={}, reason={}", id, closeReason);
    }

    /**
     * 退款
     * 仅允许已确认/生产中/已发货/已完成状态的订单退款，恢复库存和销量
     */
    @Transactional(rollbackFor = Exception.class)
    public void refundOrder(String id) {
        Order order = orderMapper.selectById(id);
        if (order == null) {
            throw BusinessException.notFound("订单");
        }
        Set<String> refundableStatuses = Set.of("confirmed", "producing", "shipped", "completed");
        if (!refundableStatuses.contains(order.getStatus())) {
            throw BusinessException.validationError(
                    "当前状态[" + order.getStatus() + "]不允许退款，仅已确认/生产中/已发货/已完成可退款");
        }

        String previousStatus = order.getStatus();
        order.setStatus("cancelled");
        order.setCloseReason("退款");
        orderMapper.updateById(order);

        // 已确认及以上的订单被退款时，恢复库存和销量
        if (!"pending".equals(previousStatus)) {
            restoreStockAndDecreaseSales(id);
        }
        log.info("退款成功: id={}, previousStatus={}", id, previousStatus);
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
        Set<String> validStatuses = Set.of("pending", "following", "completed");
        if (!validStatuses.contains(followStatus)) {
            throw BusinessException.validationError("无效的跟进状态: " + followStatus + "，可选值: pending/following/completed");
        }
        order.setFollowStatus(followStatus);
        orderMapper.updateById(order);
        log.info("更新跟进状态成功: id={}, followStatus={}", id, followStatus);
    }

    /**
     * 添加订单备注（追加模式）
     *
     * @param id      订单ID
     * @param content 备注内容
     */
    @Transactional(rollbackFor = Exception.class)
    public void addRemark(String id, String content) {
        Order order = orderMapper.selectById(id);
        if (order == null) {
            throw BusinessException.notFound("订单");
        }
        if (content == null || content.isBlank()) {
            throw BusinessException.validationError("备注内容不能为空");
        }
        if (content.length() > 2000) {
            throw BusinessException.validationError("备注内容不能超过 2000 个字符");
        }
        String timestamp = java.time.LocalDateTime.now()
                .format(java.time.format.DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm"));
        String remarkEntry = "[" + timestamp + "] " + content;
        String existing = order.getRemark() != null ? order.getRemark() : "";
        order.setRemark(existing.isEmpty() ? remarkEntry : existing + "\n" + remarkEntry);
        orderMapper.updateById(order);
        log.info("添加订单备注成功: id={}", id);
    }

    // ==================== 库存与销量管理 ====================

    /**
     * 确认支付后：扣减库存 + 增加销量（商品级 + SKU级）
     */
    private void deductStockAndIncreaseSales(String orderId) {
        adjustStockAndSales(orderId, true);
    }

    /**
     * 取消/退款后：恢复库存 + 减少销量（商品级 + SKU级）
     */
    private void restoreStockAndDecreaseSales(String orderId) {
        adjustStockAndSales(orderId, false);
    }

    /**
     * 统一的库存和销量调整逻辑
     *
     * @param orderId  订单ID
     * @param isDeduct true=扣库存+增销量（确认支付），false=恢复库存+减销量（取消/退款）
     */
    @SuppressWarnings("unchecked")
    private void adjustStockAndSales(String orderId, boolean isDeduct) {
        List<OrderItem> items = orderItemMapper.selectList(
                new LambdaQueryWrapper<OrderItem>().eq(OrderItem::getOrderId, orderId));
        if (items.isEmpty()) return;

        Order order = orderMapper.selectById(orderId);
        if (order == null) return;

        // 按 productId 聚合数量和金额
        Map<String, Integer> productQtyMap = new java.util.HashMap<>();
        Map<String, BigDecimal> productAmountMap = new java.util.HashMap<>();

        for (OrderItem item : items) {
            if (item.getProductId() == null) continue;
            int qty = item.getQuantity() != null ? item.getQuantity() : 0;
            BigDecimal amount = item.getSubtotal() != null ? item.getSubtotal() : BigDecimal.ZERO;
            productQtyMap.merge(item.getProductId(), qty, Integer::sum);
            productAmountMap.merge(item.getProductId(), amount, BigDecimal::add);

            // SKU级库存调整：从 processingInfo 中匹配 SKU
            if (isDeduct) {
                deductSkuStock(item);
            } else {
                restoreSkuStock(item);
            }
        }

        // 商品级调整
        for (Map.Entry<String, Integer> entry : productQtyMap.entrySet()) {
            String productId = entry.getKey();
            int totalQty = entry.getValue();
            BigDecimal totalAmount = productAmountMap.getOrDefault(productId, BigDecimal.ZERO);
            if (isDeduct) {
                productMapper.increaseSales(productId, totalQty, totalAmount);
            } else {
                productMapper.decreaseSales(productId, totalQty, totalAmount);
            }
        }
    }

    /**
     * 从 OrderItem 的 processingInfo 中匹配 SKU 并扣减库存
     */
    @SuppressWarnings("unchecked")
    private void deductSkuStock(OrderItem item) {
        Long skuId = matchSkuId(item);
        if (skuId != null && item.getQuantity() != null) {
            productSkuMapper.deductStock(skuId, item.getQuantity());
            productSkuMapper.increaseSalesCount(skuId, item.getQuantity());
        }
    }

    /**
     * 从 OrderItem 的 processingInfo 中匹配 SKU 并恢复库存
     */
    private void restoreSkuStock(OrderItem item) {
        Long skuId = matchSkuId(item);
        if (skuId != null && item.getQuantity() != null) {
            productSkuMapper.restoreStock(skuId, item.getQuantity());
            productSkuMapper.decreaseSalesCount(skuId, item.getQuantity());
        }
    }

    /**
     * 根据 OrderItem 的 processingInfo 匹配对应的 SKU ID
     * processingInfo 格式: { "colorId": N, "sellingMethod": "...", "doorWidth": "...", "skuId": N, ... }
     */
    @SuppressWarnings("unchecked")
    private Long matchSkuId(OrderItem item) {
        if (item.getProductId() == null) return null;

        Object processingInfo = item.getProcessingInfo();
        if (processingInfo instanceof Map) {
            Map<String, Object> info = (Map<String, Object>) processingInfo;

            // 优先使用 skuId（如果前端传了）
            Object skuIdObj = info.get("skuId");
            if (skuIdObj != null) {
                try {
                    return Long.valueOf(skuIdObj.toString());
                } catch (NumberFormatException e) {
                    log.warn("matchSkuId: skuId 格式错误, orderId={}, productId={}, skuId={}",
                            item.getOrderId(), item.getProductId(), skuIdObj);
                }
            }

            // 回退：通过 colorId + sellingMethod + doorWidth 匹配
            Object colorIdObj = info.get("colorId");
            Object sellingMethod = info.get("sellingMethod");
            Object doorWidth = info.get("doorWidth");

            if (colorIdObj != null && sellingMethod != null && doorWidth != null) {
                try {
                    Long colorId = Long.valueOf(colorIdObj.toString());
                    LambdaQueryWrapper<ProductSku> wrapper = new LambdaQueryWrapper<ProductSku>()
                            .eq(ProductSku::getProductId, item.getProductId())
                            .eq(ProductSku::getColorId, colorId)
                            .eq(ProductSku::getSellingMethod, sellingMethod.toString())
                            .eq(ProductSku::getDoorWidth, doorWidth.toString());
                    ProductSku sku = productSkuMapper.selectOne(wrapper);
                    if (sku != null) {
                        return sku.getId();
                    }
                } catch (NumberFormatException e) {
                    log.warn("matchSkuId: colorId 格式错误, orderId={}, productId={}, colorId={}",
                            item.getOrderId(), item.getProductId(), colorIdObj);
                }
            }
        }
        return null;
    }
}
