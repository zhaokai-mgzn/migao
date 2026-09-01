package com.migao.admin.service;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.*;
import com.migao.admin.dto.agent.AgentOrderCreateRequest;
import com.migao.admin.dto.agent.AgentOrderResolveResponse;
import com.migao.admin.dto.agent.AgentOrderUpdateRequest;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.entity.OrderLogistics;
import com.migao.admin.entity.FinanceTransaction;
import com.migao.admin.entity.Product;
import com.migao.admin.entity.ProductSku;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.FinanceTransactionMapper;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderLogisticsMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProductMapper;
import com.migao.admin.mapper.ProductSkuMapper;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.baomidou.mybatisplus.core.conditions.update.UpdateWrapper;
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
import java.util.concurrent.ThreadLocalRandom;
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
    private final FinanceTransactionMapper financeTransactionMapper;
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
     * 订单状态 → 中文业务术语（错误消息用）。
     * 校验/退款等报错会通过 GlobalExceptionHandler 直接展示给企业客户，
     * 必须用中文（如「待付款」），不能用 pending/confirmed 等英文枚举。
     */
    private static final Map<String, String> ORDER_STATUS_LABELS = Map.of(
            "pending", "待付款",
            "confirmed", "已确认",
            "producing", "生产中",
            "shipped", "已发货",
            "completed", "已完成",
            "cancelled", "已取消"
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
     * @param userId          下单用户ID（C 端数据隔离：非空时强制只查该用户的订单）
     * @return 分页响应
     */
    public PageResponse<OrderListResponse> getOrderPage(long page, long size, String status, String keyword, String followStatus, Boolean hasProcessing, String startDate, String endDate, String orderId, String receiver, String productCode, String productTitle, Long tenantId, String userId) {
        LambdaQueryWrapper<Order> wrapper = new LambdaQueryWrapper<>();

        // C 端数据隔离：按下单用户过滤（必须精确匹配 user_id，忽略其他模糊条件）
        if (StringUtils.hasText(userId)) {
            wrapper.eq(Order::getUserId, userId);
        }

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
                    // 投影必须同时带出 processing_info：只 select(orderId) 时 MyBatis-Plus 不会填充
                    // processingInfo，下方 extractProcessingItems 恒拿到 null → 集合恒为空
                    // → hasProcessing=true 恒返回 0 条（回归见 OrderServiceTest#getOrderPage_HasProcessingFilter_SubQueryProjectionIncludesProcessingInfo）
                    .select(OrderItem::getOrderId, OrderItem::getProcessingInfo)
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
            // 批量加载商品货号，避免 N+1 查询
            Set<String> productIds = allItems.stream()
                    .map(OrderItem::getProductId)
                    .filter(id -> id != null && !id.isEmpty())
                    .collect(Collectors.toSet());
            Map<String, Product> productMap = productIds.isEmpty()
                    ? Collections.emptyMap()
                    : productMapper.selectBatchIds(productIds).stream()
                            .collect(Collectors.toMap(Product::getId, p -> p));
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
                            Product product = productMap.get(item.getProductId());
                            return new OrderListResponse.OrderItemBrief(
                                    item.getProductId(),
                                    item.getProductName(),
                                    product != null ? product.getSkuCode() : null,
                                    item.getQuantity(),
                                    item.getUnitPrice(),
                                    itemAmount,
                                    item.getSubtotal(),
                                    item.getProcessingInfo()
                            );
                        })
                        .collect(Collectors.toList()));
                // 后端统一计算加工费与实收款，避免前端重复计算
                BigDecimal processingFee = orderItems.stream()
                        .map(item -> sumProcessingFee(item.getProcessingInfo()))
                        .reduce(BigDecimal.ZERO, BigDecimal::add);
                resp.setProcessingFee(processingFee);
                if (resp.getActualAmount() == null) {
                    resp.setActualAmount(resp.getTotalAmount());
                }
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
                if (resp.getActualAmount() == null) {
                    resp.setActualAmount(resp.getTotalAmount());
                }
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

        // 优惠金额（默认 0）；若提供了实收款，校验 应收 - 优惠 ≈ 实收（容差 0.01）
        BigDecimal discountAmount = request.getDiscountAmount() != null ? request.getDiscountAmount() : BigDecimal.ZERO;
        if (discountAmount.compareTo(BigDecimal.ZERO) < 0) {
            throw BusinessException.validationError("优惠金额不能为负数");
        }
        if (request.getActualAmount() != null) {
            BigDecimal expected = totalAmount.subtract(discountAmount);
            if (expected.subtract(request.getActualAmount()).abs().compareTo(new BigDecimal("0.01")) > 0) {
                throw BusinessException.validationError(
                        String.format("实收金额与应收不一致：应收 %s - 优惠 %s = %s，实收 %s（容差 0.01）",
                                totalAmount, discountAmount, expected, request.getActualAmount()));
            }
        }

        // 创建订单实体
        Order order = new Order();
        order.setTenantId(tenantId);
        order.setOrderNo(generateOrderNo());
        order.setCustomerName(request.getCustomerName());
        order.setCustomerPhone(request.getCustomerPhone());
        order.setCustomerAddress(request.getCustomerAddress());
        order.setTotalAmount(totalAmount);
        // 实收款：用户输入值，未输入时默认等于订单总额
        order.setActualAmount(request.getActualAmount() != null ? request.getActualAmount() : totalAmount);
        // 优惠金额落库
        order.setDiscountAmount(discountAmount);
        order.setStatus("pending");
        order.setRemark(request.getRemark());
        // C 端数据隔离：绑定下单用户（可为空=游客/商户代录）
        order.setUserId(request.getUserId());

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
            String statusLabel = ORDER_STATUS_LABELS.getOrDefault(status, status);
            throw BusinessException.validationError("无效的订单状态: " + statusLabel);
        }

        // 校验状态流转是否合法
        String currentStatus = order.getStatus();
        Set<String> allowedTargets = STATUS_TRANSITIONS.getOrDefault(currentStatus, Set.of());
        if (!allowedTargets.contains(status)) {
            String currentLabel = ORDER_STATUS_LABELS.getOrDefault(currentStatus, currentStatus);
            String targetLabel = ORDER_STATUS_LABELS.getOrDefault(status, status);
            throw BusinessException.validationError(
                    String.format("订单状态不允许从 [%s] 变更为 [%s]", currentLabel, targetLabel));
        }

        // 统一走带库存/销量副作用的路径，避免与 confirmPayment/cancelOrder 逻辑不一致
        if ("confirmed".equals(status)) {
            confirmPayment(id);
        } else if ("cancelled".equals(status)) {
            cancelOrder(id, null);
        } else {
            // producing/shipped/completed：无库存副作用，原子状态流转
            int rows = transitionStatusAtomic(id, currentStatus, status, null);
            if (rows == 0) {
                throw BusinessException.validationError("订单状态已并发变更，请刷新后重试");
            }
        }

        log.info("更新订单状态成功: id={}, {} -> {}", id, currentStatus, status);
    }

    /**
     * 原子状态流转：仅当订单当前状态为 expectedStatus 时更新为 newStatus。
     * 用条件 UPDATE（WHERE id=? AND status=expected）替代 select→check→update，
     * 防止并发下重复扣减/恢复库存（TOCTOU）。
     *
     * @return 受影响行数（0 表示订单不存在或状态已并发变更）
     */
    private int transitionStatusAtomic(String id, String expectedStatus, String newStatus, String closeReason) {
        LambdaUpdateWrapper<Order> wrapper = new LambdaUpdateWrapper<>();
        wrapper.eq(Order::getId, id)
                .eq(Order::getStatus, expectedStatus)
                .set(Order::getStatus, newStatus);
        if (closeReason != null && !closeReason.isBlank()) {
            wrapper.set(Order::getCloseReason, closeReason);
        }
        return orderMapper.update(null, wrapper);
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
        // 9 位后缀 = 5 位随机数 + 4 位原子序列。
        // 原实现取 nanoTime 尾 9 位：每秒回绕一次、跨实例易碰撞。
        // 改用随机 + 原子计数器，降低碰撞概率并启用原先闲置的 ORDER_SEQ。
        int randomPart = ThreadLocalRandom.current().nextInt(100_000);   // 0..99999
        int seqPart = ORDER_SEQ.incrementAndGet() % 10_000;             // 0..9999，防随机碰撞
        return String.format("%s%05d%04d", datePart, randomPart, seqPart);
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
        // 实收款：使用存储值，老订单 fallback 到 totalAmount
        response.setActualAmount(order.getActualAmount() != null ? order.getActualAmount() : order.getTotalAmount());

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
        // 填充商品货号（从 products 表查）(#386)
        if (item.getProductId() != null) {
            Product product = productMapper.selectById(item.getProductId());
            if (product != null && product.getSkuCode() != null) {
                response.setSkuCode(product.getSkuCode());
            }
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
     * 状态流转：pending → confirmed，同时扣减库存、增加销量。
     * 扣减前先校验 SKU 库存充足，不足则拒绝确认支付（而非 GREATEST 钳 0 导致超卖）。
     */
    @Transactional(rollbackFor = Exception.class)
    public void confirmPayment(String id) {
        Order order = orderMapper.selectById(id);
        if (order == null) {
            throw BusinessException.notFound("订单");
        }

        // 前置库存校验：库存不足直接拒绝确认支付
        validateStockSufficient(order);

        // 原子状态流转：仅 pending → confirmed，防止并发重复扣减库存
        int rows = transitionStatusAtomic(id, "pending", "confirmed", null);
        if (rows == 0) {
            throw BusinessException.validationError("只有待确认状态的订单可以确认支付，订单状态可能已变更");
        }

        // 扣减库存 + 增加销量
        deductStockAndIncreaseSales(id);

        // 登记资金流水（收款）——失败不影响订单主流程
        Order freshOrder = orderMapper.selectById(id);
        recordFinanceTransaction(freshOrder != null ? freshOrder : order, "income", "订单确认收款");
        log.info("确认支付成功: id={}", id);
    }

    /**
     * 校验订单明细对应的 SKU 库存是否充足（按 processingInfo 匹配 SKU）。
     * 无匹配 SKU 的明细不校验（对应无 SKU 扣减）。
     *
     * @throws BusinessException 库存不足时抛出业务异常
     */
    private void validateStockSufficient(Order order) {
        if (order == null || order.getId() == null) {
            return;
        }
        List<OrderItem> items = orderItemMapper.selectList(
                new LambdaQueryWrapper<OrderItem>().eq(OrderItem::getOrderId, order.getId()));
        for (OrderItem item : items) {
            Long skuId = matchSkuId(item);
            if (skuId == null || item.getQuantity() == null) {
                continue;
            }
            ProductSku sku = productSkuMapper.selectById(skuId);
            int stock = sku != null && sku.getStock() != null ? sku.getStock() : 0;
            if (stock < item.getQuantity()) {
                throw BusinessException.validationError(
                        String.format("商品「%s」库存不足：需要 %d 件，当前仅剩 %d 件，请先补货后再确认支付",
                                item.getProductName() != null ? item.getProductName() : skuId,
                                item.getQuantity(), stock));
            }
        }
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
        String previousStatus = order.getStatus();
        Set<String> cancellableStatuses = Set.of("pending", "confirmed", "producing");
        if (!cancellableStatuses.contains(previousStatus)) {
            throw BusinessException.validationError("当前状态不允许取消");
        }
        if (closeReason != null && !closeReason.isBlank() && closeReason.length() > 500) {
            throw BusinessException.validationError("关闭原因不能超过 500 个字符");
        }

        // 原子状态流转（以读取到的 previousStatus 为条件，防止并发重复恢复库存）
        int rows = transitionStatusAtomic(id, previousStatus, "cancelled", closeReason);
        if (rows == 0) {
            throw BusinessException.validationError("订单状态已并发变更，请刷新后重试");
        }

        // 已确认/生产中的订单被取消时，恢复库存和销量，并补记退款流水（与 confirmPayment 的 income 对冲）
        if ("confirmed".equals(previousStatus) || "producing".equals(previousStatus)) {
            restoreStockAndDecreaseSales(id);
            BigDecimal remainingRefund = effectiveActualAmount(order).subtract(
                    order.getRefundAmount() != null ? order.getRefundAmount() : BigDecimal.ZERO);
            if (remainingRefund.compareTo(BigDecimal.ZERO) > 0) {
                recordFinanceTransaction(order, remainingRefund, "refund", "订单取消退款");
            }
        }
        log.info("取消订单成功: id={}, reason={}", id, closeReason);
    }

    /**
     * 退款（财务叠加语义：不改订单状态、不恢复库存）
     * 仅允许已确认/生产中/已发货/已完成状态的订单退款。
     * 落 refundAmount（累计，封顶实收款）+ refundAt，并登记退款流水。
     *
     * @param id           订单ID
     * @param refundAmount 退款金额（null = 全额退款）
     * @param refundReason 退款原因（可选）
     */
    @Transactional(rollbackFor = Exception.class)
    public void refundOrder(String id, BigDecimal refundAmount, String refundReason) {
        Order order = orderMapper.selectById(id);
        if (order == null) {
            throw BusinessException.notFound("订单");
        }
        String previousStatus = order.getStatus();
        Set<String> refundableStatuses = Set.of("confirmed", "producing", "shipped", "completed");
        if (!refundableStatuses.contains(previousStatus)) {
            String previousLabel = ORDER_STATUS_LABELS.getOrDefault(previousStatus, previousStatus);
            throw BusinessException.validationError(
                    "当前状态[" + previousLabel + "]不允许退款，仅已确认/生产中/已发货/已完成可退款");
        }

        BigDecimal actual = effectiveActualAmount(order);
        BigDecimal refund = refundAmount != null ? refundAmount : actual;
        if (refund.compareTo(BigDecimal.ZERO) < 0) {
            throw BusinessException.validationError("退款金额不能为负数");
        }
        if (refund.compareTo(actual) > 0) {
            throw BusinessException.validationError("退款金额不能超过实收款 " + actual);
        }

        // 累计已退金额，封顶实收款（防并发/多次退款超退）
        BigDecimal existingRefund = order.getRefundAmount() != null ? order.getRefundAmount() : BigDecimal.ZERO;
        BigDecimal applied = refund.min(actual.subtract(existingRefund));
        if (applied.compareTo(BigDecimal.ZERO) <= 0) {
            throw BusinessException.validationError("该订单已全额退款，无需重复退款");
        }

        String reason = refundReason != null && !refundReason.isBlank() ? refundReason : "退款";
        // 保持原状态，仅落退款金额与时间（前端"已退款"徽标由 refundAmount>0 判定）
        // 原子条件更新：refund_amount 在库内累加且不超过实收款，防并发双花（审计 07 P1-10）。
        // 并发请求同时读到 existingRefund 时，DB 层 COALESCE 累加 + WHERE 上限保证只成功一次。
        OffsetDateTime refundAt = OffsetDateTime.now();
        UpdateWrapper<Order> refundWrapper = new UpdateWrapper<>();
        refundWrapper.eq("id", order.getId())
                .eq("tenant_id", order.getTenantId())
                .setSql("refund_amount = COALESCE(refund_amount, 0) + " + applied.toPlainString())
                .set("refund_at", refundAt)
                .and(w -> w.apply("COALESCE(refund_amount, 0) + {0} <= {1}",
                        applied, actual));
        int updated = orderMapper.update(null, refundWrapper);
        if (updated == 0) {
            // 条件不满足：已被并发请求退款至上限，拒绝本次
            throw BusinessException.validationError("该订单已全额退款，无需重复退款");
        }
        order.setRefundAmount(existingRefund.add(applied));
        order.setRefundAt(refundAt);

        // 登记资金流水（退款，金额=本次实际退款额）——失败不影响订单主流程
        recordFinanceTransaction(order, applied, "refund", "订单退款: " + reason);
        log.info("退款成功: id={}, previousStatus={}, refundAmount={}, refundReason={}",
                id, previousStatus, applied, refundReason);
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

    // ==================== 财务流水登记 ====================

    /**
     * 订单实际应收（实收）金额：actualAmount 兜底 totalAmount。
     */
    private BigDecimal effectiveActualAmount(Order order) {
        return order.getActualAmount() != null ? order.getActualAmount() : order.getTotalAmount();
    }

    /**
     * 登记一笔订单关联的资金流水（收款/退款），金额取订单实收款。
     * 失败仅告警，不影响订单主流程（对账流水为辅助数据）。
     */
    private void recordFinanceTransaction(Order order, String type, String remark) {
        BigDecimal amount = effectiveActualAmount(order);
        recordFinanceTransaction(order, amount, type, remark);
    }

    /**
     * 登记一笔订单关联的资金流水（收款/退款），金额显式指定（支持部分退款）。
     * 失败仅告警，不影响订单主流程（对账流水为辅助数据）。
     */
    private void recordFinanceTransaction(Order order, BigDecimal amount, String type, String remark) {
        try {
            if (order == null) {
                return;
            }
            if (amount == null || amount.compareTo(BigDecimal.ZERO) <= 0) {
                return;
            }
            FinanceTransaction txn = FinanceTransaction.builder()
                    .tenantId(order.getTenantId())
                    .transactionNo(generateFinanceTransactionNo(order.getTenantId()))
                    .orderId(order.getId())
                    .orderNo(order.getOrderNo())
                    .type(type)
                    .amount(amount)
                    .status("success")
                    .operator("系统")
                    .occurredAt(OffsetDateTime.now())
                    .remark(remark)
                    .build();
            financeTransactionMapper.insert(txn);
            log.info("登记资金流水: transactionNo={}, type={}, amount={}, orderNo={}",
                    txn.getTransactionNo(), type, amount, order.getOrderNo());
        } catch (Exception e) {
            log.warn("登记资金流水失败（不影响订单主流程）: orderNo={}, type={}, error={}",
                    order != null ? order.getOrderNo() : null, type, e.getMessage());
        }
    }

    /**
     * 生成资金流水号（防重启重复）：FIN-yyyyMMdd-XXXX，从 DB 查当天最大序号 +1
     */
    private String generateFinanceTransactionNo(Long tenantId) {
        String datePart = LocalDate.now().format(DateTimeFormatter.ofPattern("yyyyMMdd"));
        String prefix = "FIN-" + datePart + "-";
        int nextSeq = 1;
        try {
            FinanceTransaction latest = financeTransactionMapper.selectOne(
                    new LambdaQueryWrapper<FinanceTransaction>()
                            .eq(FinanceTransaction::getTenantId, tenantId)
                            .likeRight(FinanceTransaction::getTransactionNo, prefix)
                            .orderByDesc(FinanceTransaction::getTransactionNo)
                            .last("LIMIT 1"));
            if (latest != null && latest.getTransactionNo() != null) {
                String[] parts = latest.getTransactionNo().split("-");
                if (parts.length == 3) {
                    nextSeq = Integer.parseInt(parts[2]) + 1;
                }
            }
        } catch (Exception e) {
            log.warn("查询最新流水号失败，使用默认序号: {}", e.getMessage());
        }
        return String.format("FIN-%s-%04d", datePart, nextSeq % 10000);
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

    // ======================== Agent BFF 方法 ========================

    /**
     * Agent 专用创建订单。
     * subtotal 服务端按 quantity × unitPrice 强制重算。
     */
    @Transactional(rollbackFor = Exception.class)
    public OrderDetailResponse createOrderForAgent(AgentOrderCreateRequest request, Long tenantId) {

        if (!StringUtils.hasText(request.getCustomerName())) {
            throw BusinessException.validationError("客户姓名不能为空");
        }
        if (!StringUtils.hasText(request.getCustomerPhone())) {
            throw BusinessException.validationError("客户电话不能为空");
        }
        // 手机号格式校验
        String phone = request.getCustomerPhone().trim();
        if (!phone.matches("^1[3-9]\\d{9}$")) {
            throw BusinessException.validationError("手机号格式不正确，请输入11位中国大陆手机号");
        }

        if (request.getItems() == null || request.getItems().isEmpty()) {
            throw BusinessException.validationError("商品明细不能为空");
        }

        OrderCreateRequest createReq = new OrderCreateRequest();
        createReq.setCustomerName(request.getCustomerName());
        createReq.setCustomerPhone(phone);
        createReq.setCustomerAddress(request.getCustomerAddress());
        createReq.setRemark(request.getRemark());
        // C 端数据隔离：透传下单用户（可为空=商户代录，语义为"游客订单"）
        createReq.setUserId(request.getUserId());

        List<OrderCreateRequest.OrderItemRequest> itemReqs = new ArrayList<>();
        for (var item : request.getItems()) {
            OrderCreateRequest.OrderItemRequest itemReq = new OrderCreateRequest.OrderItemRequest();
            itemReq.setProductName(item.getProductName());
            itemReq.setProductId(item.getProductId());
            itemReq.setQuantity(item.getQuantity());
            itemReq.setUnitPrice(item.getUnitPrice());
            // subtotal 服务端强制重算（对抗 LLM 编造）
            if (item.getQuantity() != null && item.getUnitPrice() != null) {
                itemReq.setSubtotal(item.getUnitPrice().multiply(BigDecimal.valueOf(item.getQuantity())));
            } else if (item.getSubtotal() != null) {
                itemReq.setSubtotal(item.getSubtotal());
            }
            itemReq.setWidth(item.getWidth());
            itemReq.setHeight(item.getHeight());
            itemReq.setProcessingInfo(item.getProcessingInfo());
            itemReqs.add(itemReq);
        }
        createReq.setItems(itemReqs);

        return createOrder(createReq, tenantId);
    }

    /**
     * Agent 专用统一订单更新。
     * ID 可传 UUID 或订单号（ORD-xxx），服务端自动解析。
     * 通过 action 字段路由到具体的操作方法。
     */
    @Transactional(rollbackFor = Exception.class)
    public Object updateOrderForAgent(String rawId, AgentOrderUpdateRequest request, Long tenantId) {
        // 解析订单 ID
        String resolvedId = resolveOrderIdToUuid(rawId, tenantId);
        if (resolvedId == null) {
            throw new BusinessException("ORDER_NOT_FOUND",
                    "无法找到订单：" + rawId + "。请使用 order_query 查询正确的订单号后重试。", 404);
        }

        String action = request.getAction();
        if (!StringUtils.hasText(action)) {
            throw BusinessException.validationError("action 不能为空");
        }

        return switch (action) {
            case "update_status" -> {
                if (!StringUtils.hasText(request.getStatus())) {
                    throw BusinessException.validationError("status 不能为空");
                }
                updateOrderStatus(resolvedId, request.getStatus());
                yield getOrderById(resolvedId);
            }
            case "confirm_payment" -> {
                confirmPayment(resolvedId);
                yield getOrderById(resolvedId);
            }
            case "cancel" -> {
                cancelOrder(resolvedId, request.getCancelReason());
                yield getOrderById(resolvedId);
            }
            case "refund" -> {
                refundOrder(resolvedId, request.getRefundAmount(), request.getRefundReason());
                yield getOrderById(resolvedId);
            }
            case "update_logistics" -> {
                if (!StringUtils.hasText(request.getLogisticsCompany())) {
                    throw BusinessException.validationError("logisticsCompany 不能为空");
                }
                if (!StringUtils.hasText(request.getTrackingNumber())) {
                    throw BusinessException.validationError("trackingNumber 不能为空");
                }
                upsertLogistics(resolvedId, request.getLogisticsCompany().trim(),
                        request.getTrackingNumber().trim());
                // 发货语义：记录物流后将订单流转为 shipped（与契约 order_manage(update_logistics) 可发货一致）
                shipOrderIfApplicable(resolvedId);
                yield getOrderById(resolvedId);
            }
            default -> throw BusinessException.validationError(
                    "不支持的操作类型: " + action + "，可选: update_status/update_logistics/confirm_payment/cancel/refund");
        };
    }

    /**
     * 更新/创建订单物流信息：存在最新物流记录则更新，否则新建（status=in_transit）。
     */
    private void upsertLogistics(String orderId, String logisticsCompany, String trackingNo) {
        List<OrderLogistics> existing = orderLogisticsMapper.selectByOrderId(orderId, TenantContext.getTenantId());
        if (existing == null || existing.isEmpty()) {
            OrderLogistics logistics = OrderLogistics.builder()
                    .tenantId(TenantContext.getTenantId())
                    .orderId(orderId)
                    .logisticsCompany(logisticsCompany)
                    .trackingNo(trackingNo)
                    .status("in_transit")
                    .shippedAt(OffsetDateTime.now())
                    .build();
            orderLogisticsMapper.insert(logistics);
            log.info("创建物流信息成功: orderId={}, trackingNo={}", orderId, trackingNo);
        } else {
            OrderLogistics latest = existing.get(0);
            latest.setLogisticsCompany(logisticsCompany);
            latest.setTrackingNo(trackingNo);
            if (latest.getStatus() == null) {
                latest.setStatus("in_transit");
            }
            orderLogisticsMapper.updateById(latest);
            log.info("更新物流信息成功: id={}, trackingNo={}", latest.getId(), trackingNo);
        }
    }

    /**
     * 发货联动：confirmed/producing 状态的订单在记录物流后原子流转为 shipped。
     * 已 shipped/completed 保持原状态（仅更新物流）；pending/cancelled 不强制流转。
     */
    private void shipOrderIfApplicable(String orderId) {
        Order order = orderMapper.selectById(orderId);
        if (order == null) {
            return;
        }
        String currentStatus = order.getStatus();
        if ("confirmed".equals(currentStatus) || "producing".equals(currentStatus)) {
            int rows = transitionStatusAtomic(orderId, currentStatus, "shipped", null);
            if (rows == 0) {
                throw BusinessException.validationError("订单状态已并发变更，请刷新后重试");
            }
        }
    }

    /**
     * 通过订单号/UUID/关键词解析订单 UUID。
     * GET /api/admin/agent/orders/resolve?keyword=xxx 的核心逻辑。
     */
    public AgentOrderResolveResponse resolveOrderId(String keyword, Long tenantId) {
        if (!StringUtils.hasText(keyword)) {
            throw BusinessException.validationError("keyword 不能为空");
        }

        String resolvedId = resolveOrderIdToUuid(keyword, tenantId);
        if (resolvedId == null) {
            throw new BusinessException("ORDER_NOT_FOUND",
                    "未找到匹配的订单：" + keyword + "。请检查订单号是否正确。", 404);
        }

        Order order = orderMapper.selectById(resolvedId);
        if (order == null) {
            throw BusinessException.notFound("订单");
        }

        int itemCount = 0;
        Long count = orderItemMapper.selectCount(
                new LambdaQueryWrapper<OrderItem>().eq(OrderItem::getOrderId, resolvedId));
        if (count != null) itemCount = count.intValue();

        return AgentOrderResolveResponse.builder()
                .id(order.getId())
                .orderNo(order.getOrderNo())
                .customerName(order.getCustomerName())
                .status(order.getStatus())
                .totalAmount(order.getActualAmount() != null ? order.getActualAmount() : order.getTotalAmount())
                .itemCount(itemCount)
                .build();
    }

    /**
     * 订单 ID 解析：UUID 精确匹配 → 订单号匹配 → UUID 前缀匹配。
     *
     * @return 解析出的 UUID，未找到返回 null
     */
    private String resolveOrderIdToUuid(String raw, Long tenantId) {
        if (!StringUtils.hasText(raw)) return null;

        // 1. UUID 精确匹配（租户隔离）
        Order order = orderMapper.selectOne(
                new LambdaQueryWrapper<Order>()
                        .eq(Order::getId, raw)
                        .eq(Order::getTenantId, tenantId));
        if (order != null) return order.getId();

        // 2. 按订单号搜索
        List<Order> byOrderNo = orderMapper.selectList(
                new LambdaQueryWrapper<Order>()
                        .eq(Order::getTenantId, tenantId)
                        .eq(Order::getOrderNo, raw));
        if (!byOrderNo.isEmpty()) return byOrderNo.get(0).getId();

        // 3. 按关键词搜索（订单号模糊/手机号/姓名）
        List<Order> byKeyword = orderMapper.selectList(
                new LambdaQueryWrapper<Order>()
                        .eq(Order::getTenantId, tenantId)
                        .and(w -> w.like(Order::getOrderNo, raw)
                                .or().like(Order::getCustomerPhone, raw)
                                .or().like(Order::getCustomerName, raw))
                        .last("LIMIT 1"));
        if (!byKeyword.isEmpty()) return byKeyword.get(0).getId();

        // 4. UUID 前缀匹配
        if (raw.length() >= 8) {
            List<Order> byPrefix = orderMapper.selectList(
                    new LambdaQueryWrapper<Order>()
                            .eq(Order::getTenantId, tenantId)
                            .likeRight(Order::getId, raw.substring(0, Math.min(16, raw.length())))
                            .last("LIMIT 1"));
            if (!byPrefix.isEmpty()) return byPrefix.get(0).getId();
        }

        return null;
    }
}
