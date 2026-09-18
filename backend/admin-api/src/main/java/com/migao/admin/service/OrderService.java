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
import com.migao.admin.entity.StockLedger;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.FinanceTransactionMapper;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderLogisticsMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProductMapper;
import com.migao.admin.mapper.ProductSkuMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import com.migao.admin.entity.ProcessingOrder;
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
import java.util.HashMap;
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
    private final NotificationService notificationService;
    private final ProcessingOrderMapper processingOrderMapper;
    /** 发货人兜底解析（issue #3768）：当前登录用户姓名 */
    private final UserService userService;
    /** 写请求幂等键（issue #4037）：去重 / 结果回放 / 占位释放 */
    private final ClientRequestIdService clientRequestIdService;
    /**
     * 库存流水/台账（issue #4137）：订单腿（下单扣减 / 取消回补）的落账写入方。
     * 落账唯一语义点在该服务（delta 由 after-before 算出），本类只提供「变更前快照 + 变更点」。
     */
    private final StockLedgerService stockLedgerService;

    /**
     * 订单号序列号（线程安全）
     */
    private static final AtomicInteger ORDER_SEQ = new AtomicInteger(0);

    /** 幂等端点标识（issue #4037）：同键跨端点复用会在 client_request_keys.endpoint 留下可查证据 */
    private static final String ENDPOINT_CREATE_ORDER = "POST /api/admin/agent/orders";

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

        // 转换为响应 DTO + 批量补充明细
        List<OrderListResponse> responses = resultPage.getRecords().stream()
                .map(this::convertToListResponse)
                .collect(Collectors.toList());
        enrichListResponses(responses);

        return PageResponse.of(resultPage.getTotal(), resultPage.getCurrent(), resultPage.getSize(), responses);
    }

    /**
     * C 端「我的订单」分页查询 — user_id 直配 + 手机号兜底。
     *
     * 数据隔离语义（与 V23 回填一致）：
     * - orders.user_id = 当前用户 → 必然可见（聊天/绑定下单）
     * - orders.user_id IS NULL AND orders.customer_phone = 当前用户已绑定手机号
     *   → 视为「名下」订单（商户代录/历史订单），仅当本人已授权绑定手机号才可见，
     *   且 customer_phone 必须精确等于本人手机号（不越权）
     *
     * @param page     页码
     * @param size     每页大小
     * @param status   订单状态（可选）
     * @param tenantId 租户ID
     * @param userId   当前用户ID（X-User-Id 透传）
     * @param userPhone 当前用户已绑定手机号（可为空：未绑定时退化为仅 user_id 匹配）
     * @return 分页响应
     */
    public PageResponse<OrderListResponse> getMyOrderPage(long page, long size, String status,
                                                          Long tenantId, String userId, String userPhone) {
        if (userId == null || userId.isBlank() || "internal-service".equals(userId)) {
            throw BusinessException.authFailed("缺少用户标识，无法查询订单");
        }

        LambdaQueryWrapper<Order> wrapper = new LambdaQueryWrapper<>();
        // 用户级隔离：本人订单 OR（未绑定 + 手机号=本人）——手机号兜底仅在有绑定号时启用
        if (StringUtils.hasText(userPhone)) {
            wrapper.and(w -> w.eq(Order::getUserId, userId)
                    .or(o -> o.isNull(Order::getUserId).eq(Order::getCustomerPhone, userPhone.trim())));
        } else {
            wrapper.eq(Order::getUserId, userId);
        }

        // 状态筛选
        if (StringUtils.hasText(status)) {
            wrapper.eq(Order::getStatus, status);
        }

        wrapper.orderByDesc(Order::getCreatedAt);

        Page<Order> orderPage = new Page<>(page, size);
        Page<Order> resultPage = orderMapper.selectPage(orderPage, wrapper);

        List<OrderListResponse> responses = resultPage.getRecords().stream()
                .map(this::convertToListResponse)
                .collect(Collectors.toList());
        enrichListResponses(responses);

        return PageResponse.of(resultPage.getTotal(), resultPage.getCurrent(), resultPage.getSize(), responses);
    }

    /**
     * 手机号回填绑定：把「该手机号下 user_id 为空的本租户订单」绑定到指定用户。
     *
     * 场景：小程序客户授权绑定手机号后，商户代录/历史订单（仅存 customer_phone、
     * user_id 为空）据此归属到本人——V23 回填 SQL 的运行时等价物。
     * 防误绑：只更新 user_id IS NULL 的订单（已归属他人的不动）；tenant 由
     * TenantLineInnerInterceptor 自动注入。
     *
     * @param tenantId 租户ID
     * @param userId   当前用户ID
     * @param phone    用户刚绑定（且校验过未被同租户其他用户占用）的手机号
     * @return 受影响行数
     */
    public int bindOrdersToUser(Long tenantId, String userId, String phone) {
        if (!StringUtils.hasText(phone) || phone.isBlank()) {
            log.info("[bind-orders] 跳过：手机号为空 tenantId={}", tenantId);
            return 0;
        }
        if (userId == null || userId.isBlank() || "internal-service".equals(userId)) {
            log.info("[bind-orders] 跳过：用户标识缺失 tenantId={}", tenantId);
            return 0;
        }
        LambdaUpdateWrapper<Order> wrapper = new LambdaUpdateWrapper<>();
        wrapper.isNull(Order::getUserId)
                .eq(Order::getCustomerPhone, phone.trim())
                .set(Order::getUserId, userId);
        int updated = orderMapper.update(null, wrapper);
        log.info("[bind-orders] 手机号回填完成: tenantId={}, userId={}, phone={}****, bound={}",
                tenantId, userId, phone.substring(0, 3), updated);
        return updated;
    }

    /**
     * 批量补充订单明细/加工费/实收款（getOrderPage 与 getMyOrderPage 共用，避免 N+1）
     */
    private void enrichListResponses(List<OrderListResponse> responses) {
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
                                itemAmount = item.getUnitPrice().multiply(item.getQuantity());
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
        // ── 资金/库存完整性闸门（issue #3622 / #3682）：数量 ≥ 1，单价 > 0 ──
        // issue #3666：数量已放宽为 BigDecimal（DECIMAL(10,2)），per_area 的合法数量就是小数
        // （门幅 2.8m × 3m = 8.4 ㎡）——但不能因此放行 <1。
        // issue #3682：下限从「> 0」收紧为「≥ 1」——`items[].quantity` 直接驱动库存/销量，
        // 而下面 `validateStockSufficientForRequest`/`deductSkuStock` 对 quantity 取整数部分
        // （`:1051` `intValue()` 库存校验 / `:1408` `deductStock` / `:1409` `increaseSalesCount`）：
        // 0.5 → `needed = 0` 校验**恒通过**、`deductStock(0)` **不减库存**、销量 **+0**
        // → **订单成交但库存/销量零变动，且全程无告警**（账实不符）。
        // 旧实现（quantity 为 Integer + agent 工具层拒绝非整数）在下单前就挡回 0.5 并给可行动
        // 提示，故 <1 是 #3666 放宽后**新可达**的静默漏扣。裁定（#3682 方案 A）：下限 = 1，
        // 与 admin-web 表单页 `min={1}` 及 ai-agent 工具层同口径；≥1 的小数仍合法（保真落库）。
        // 为什么必须在 Service 层显式判定（而不是只靠 DTO 注解）：
        //   ① Agent 路径 `createOrderForAgent`（下方 BFF 段）是**手工 new `OrderCreateRequest`**
        //      再调用本方法 —— 程序化构造的 Bean **不经过 Bean Validation**，注解对它无效；
        //   ② 本方法是三条路径（表单 / Agent / 未来程序化调用）的**唯一共享入口**，判在这里才无死角。
        // 不判的后果：负数量 → `unitPrice × 负数` 算出**负金额**落库；库存前置校验
        // （下方 validateStockSufficientForRequest）判据「需求量 ≤ 库存」对**负需求恒真**
        // → **超卖防线被绕过**；0 < 数量 < 1 → 库存/销量零扣减（本条 issue #3682）。
        for (int i = 0; i < request.getItems().size(); i++) {
            OrderCreateRequest.OrderItemRequest itemRequest = request.getItems().get(i);
            if (itemRequest.getQuantity() == null
                    || itemRequest.getQuantity().compareTo(BigDecimal.ONE) < 0) {
                throw BusinessException.validationError(
                        String.format("商品明细第 %d 项的数量不能小于 1", i + 1));
            }
            if (itemRequest.getUnitPrice() == null
                    || itemRequest.getUnitPrice().compareTo(BigDecimal.ZERO) <= 0) {
                throw BusinessException.validationError(
                        String.format("商品明细第 %d 项的单价必须大于 0", i + 1));
            }
        }

        // 计算总金额（后端独立计算：unitPrice * quantity + 加工费，不依赖前端 subtotal 防止不一致）
        BigDecimal totalAmount = BigDecimal.ZERO;
        for (OrderCreateRequest.OrderItemRequest itemRequest : request.getItems()) {
            // 商品金额 = 单价 × 数量
            BigDecimal itemAmount = BigDecimal.ZERO;
            if (itemRequest.getUnitPrice() != null && itemRequest.getQuantity() != null) {
                itemAmount = itemRequest.getUnitPrice().multiply(itemRequest.getQuantity());
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

        // 前置库存校验：库存不足拒绝创建订单（提示前移至下单时，issue #2922）。
        // 与确认支付共用同一套 SKU 匹配/库存口径（validateStockSufficient），
        // 无 SKU 匹配的明细不校验（与扣减语义一致）。
        validateStockSufficientForRequest(request, "下单");

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
            // 下单行要素落列（V62，issue #4362，S1）：两个采集端（C 端小布澄清清单 / B 端米宝
            // order_create）写入的 processing_info 顶层工艺规格键在此**物化**到 order_items 的列上。
            // 判在本方法（表单 / Agent / 程序化三条路径的**唯一共享入口**）才无死角；
            // 全部可空、不设必填校验（用户裁定「部位不是必填的」）⇒ 缺键就是缺。
            OrderLineCraftFields.materialize(
                    OrderLineCraftFields.normalize(itemRequest.getProcessingInfo(), objectMapper), item);
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

        // 站内信：新订单创建成功，通知订单归属用户（无归属用户则跳过）
        notifyOrderCreated(tenantId, order, totalAmount);

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

        // 加工单联动守卫（issue #3340）：含加工项订单必须完成加工单后才能发货，
        // 防止加工环节被 confirmed→shipped 直跳绕过
        if ("shipped".equals(status)) {
            assertProcessingCompletedBeforeShip(order);
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

        // 站内信：订单状态变更，通知订单归属用户（无归属用户则跳过）
        notifyOrderStatusChanged(order.getTenantId(), order, status);
    }

    /**
     * 站内信：新订单待处理（order_created 事件）
     *
     * 接收人路由（issue #2965 v2）：只有存在归属用户（C 端自助下单）时才属于
     * 「新订单待处理」场景，通知租户管理员（B 端铃铛）——管理员据此跟进确认；
     * 商户代录的订单（无归属用户）由录入者自行感知，不发送避免噪音。
     */
    private void notifyOrderCreated(Long tenantId, Order order, BigDecimal totalAmount) {
        if (order.getUserId() == null || order.getUserId().isBlank()) {
            log.debug("[notify] 订单无归属用户（商户代录），跳过新订单通知: orderId={}", order.getId());
            return;
        }
        try {
            Map<String, String> vars = new HashMap<>();
            vars.put("orderNo", order.getOrderNo() != null ? order.getOrderNo() : order.getId());
            vars.put("amount", totalAmount != null ? totalAmount.toPlainString() : "0.00");
            notificationService.triggerForTenantAdmins(tenantId, "order_created", vars);
        } catch (Exception e) {
            log.warn("[notify] 新订单站内信发送失败，忽略: orderId={}, error={}",
                    order.getId(), e.getMessage());
        }
    }

    /**
     * 站内信：订单状态变更（order_status_changed 事件）
     * 接收人路由（issue #2965 v2）：进度告知面向下单客户（C 端「订单归属用户」），
     * 无归属用户（商户代录）跳过。
     */
    private void notifyOrderStatusChanged(Long tenantId, Order order, String newStatus) {
        if (order.getUserId() == null || order.getUserId().isBlank()) {
            log.debug("[notify] 订单无归属用户，跳过站内信: orderId={}", order.getId());
            return;
        }
        try {
            Map<String, String> ctx = new HashMap<>();
            ctx.put("recipientId", order.getUserId());
            ctx.put("recipientType", "user");
            ctx.put("orderNo", order.getOrderNo() != null ? order.getOrderNo() : order.getId());
            ctx.put("status", ORDER_STATUS_LABELS.getOrDefault(newStatus, newStatus));
            notificationService.triggerByEvent(tenantId, "order_status_changed", ctx);
        } catch (Exception e) {
            log.warn("[notify] 订单状态变更站内信发送失败，忽略: orderId={}, error={}",
                    order.getId(), e.getMessage());
        }
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
            logisticsInfo.setLogisticsType(logistics.getLogisticsType());
            logisticsInfo.setStatus(logistics.getStatus());
            logisticsInfo.setTrackingInfo(logistics.getTrackingInfo());
            logisticsInfo.setShipperName(logistics.getShipperName());
            logisticsInfo.setShippedAt(logistics.getShippedAt());
            logisticsInfo.setDeliveredAt(logistics.getDeliveredAt());
            response.setLogistics(logisticsInfo);
        }

        return response;
    }

    /**
     * 加工单联动守卫（issue #3340）：订单含加工项且无已完成加工单时禁止发货。
     * 有加工项订单必须走 producing（生成加工单）→ 加工完成 → shipped，防止加工环节被绕过。
     */
    private void assertProcessingCompletedBeforeShip(Order order) {
        // 必须走 BaseMapper 加载（见 loadOrderItems）：自定义 @Select 不经过 JacksonTypeHandler，
        // processing_info 会以 JSON 字符串返回 → 加工项解析恒为空 → 守卫静默失效
        // （issue #3340 验收实战：真实对话生成加工单被判「无加工项」）
        List<OrderItem> items = loadOrderItems(order.getId(), order.getTenantId());
        boolean hasProcessing = items.stream()
                .anyMatch(item -> !extractProcessingItems(item.getProcessingInfo()).isEmpty());
        if (hasProcessing
                && processingOrderMapper.countCompletedByOrderId(order.getId(), order.getTenantId()) == 0) {
            throw BusinessException.validationError(
                    "订单含加工项，须先完成加工单后再发货（可在订单详情或让米宝生成/更新加工单）");
        }
    }

    /**
     * 加载订单明细（走 BaseMapper，确保 processing_info 经 JacksonTypeHandler 反序列化为 Map）。
     * 与 getOrderById 的既有约定一致（见查询明细处的注释）。
     */
    private List<OrderItem> loadOrderItems(String orderId, Long tenantId) {
        List<OrderItem> items = orderItemMapper.selectList(new LambdaQueryWrapper<OrderItem>()
                .eq(OrderItem::getOrderId, orderId)
                .eq(OrderItem::getTenantId, tenantId)
                .eq(OrderItem::getDeleted, 0));
        return items != null ? items : Collections.emptyList();
    }

    /**
     * 加工单取消联动（issue #3340）：订单 producing → confirmed 回退。
     * 仅状态回退，无库存副作用（confirmed→producing 本身也无库存副作用）。
     */
    public void revertProducingToConfirmed(String orderId, String reason) {
        int rows = transitionStatusAtomic(orderId, "producing", "confirmed", reason);
        if (rows == 0) {
            throw new BusinessException("ORDER_STATUS_CONFLICT", "订单状态已并发变更，请刷新后重试", 409);
        }
    }

    /**
     * 从订单明细的 processingInfo（JSON）中解析加工项列表。
     * processingInfo 格式来自前端创建订单时写入：
     * { "processingFee": <number>, "processingItems": [ { id,name,unitPrice,quantity,unit } ] , ... }
     * 解析失败/缺字段时返回空列表，确保不影响订单查询主流程。
     *
     * issue #3340 验收实战：processingInfo 可能是 JSON **字符串**（自定义 @Select 查询不经过
     * JacksonTypeHandler），此处做兼容解析，避免"有加工项却被判无加工项"。
     */
    @SuppressWarnings("unchecked")
    private List<OrderDetailResponse.ProcessingItemBrief> extractProcessingItems(Object processingInfo) {
        Object normalized = processingInfo;
        if (normalized instanceof String s && !s.isBlank()) {
            try {
                normalized = objectMapper.readValue(s, Map.class);
            } catch (Exception e) {
                log.warn("processingInfo JSON 字符串解析失败: {}", e.getMessage());
                return Collections.emptyList();
            }
        }
        if (!(normalized instanceof Map)) {
            return Collections.emptyList();
        }
        processingInfo = normalized;
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
                // issue #3666：必须走十进制解析——旧 toInteger() 把 per_area 的 8.4 截断成 8，
                // 详情/列表按截断值重算加工费（30×8=240.00）与外层落库 processingFee（252.00）
                // 自相矛盾。
                BigDecimal quantity = toBigDecimal(entry.get("quantity"));
                brief.setQuantity(quantity);
                BigDecimal amount = BigDecimal.ZERO;
                if (unitPrice != null && quantity != null) {
                    amount = unitPrice.multiply(quantity);
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

    /**
     * 计算/解析订单明细小计：优先使用请求中的 subtotal，若为 null 则回退 unitPrice * quantity。
     * 避免前端未传 subtotal 时 totalAmount 被记录为 0 的问题。
     */
    private BigDecimal resolveItemSubtotal(OrderCreateRequest.OrderItemRequest itemRequest) {
        if (itemRequest.getSubtotal() != null) {
            return itemRequest.getSubtotal();
        }
        if (itemRequest.getUnitPrice() != null && itemRequest.getQuantity() != null) {
            return itemRequest.getUnitPrice().multiply(itemRequest.getQuantity());
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
            response.setAmount(item.getUnitPrice().multiply(item.getQuantity()));
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
     * 校验订单明细对应的 SKU 库存是否充足（按 processingInfo 匹配 SKU，判据见 {@link #matchSkuId}）。
     * 未声明 SKU 身份的明细不校验（对应无 SKU 扣减）；声明了身份却定位不到 ⇒ 显式拒绝。
     *
     * @param order       订单（已落库，明细从 order_item 表加载）
     * @throws BusinessException 库存不足、或规格无法定位到 SKU 时抛出业务异常
     */
    private void validateStockSufficient(Order order) {
        if (order == null || order.getId() == null) {
            return;
        }
        List<OrderItem> items = orderItemMapper.selectList(
                new LambdaQueryWrapper<OrderItem>().eq(OrderItem::getOrderId, order.getId()));
        validateStockSufficientForItems(items, "确认支付");
    }

    /**
     * 创建订单前的库存校验入口（issue #2922：库存不足提示前移至下单时）。
     * 与确认支付共用 validateStockSufficientForItems 的同一套 SKU 匹配/库存口径。
     *
     * @param request     创建订单请求
     * @param actionLabel 动作文案（如「下单」），用于错误提示
     */
    private void validateStockSufficientForRequest(OrderCreateRequest request, String actionLabel) {
        if (request.getItems() == null || request.getItems().isEmpty()) {
            return;
        }
        List<OrderItem> draftItems = new ArrayList<>(request.getItems().size());
        for (OrderCreateRequest.OrderItemRequest itemRequest : request.getItems()) {
            OrderItem draft = new OrderItem();
            draft.setProductId(itemRequest.getProductId());
            draft.setProductName(itemRequest.getProductName());
            draft.setQuantity(itemRequest.getQuantity());
            draft.setProcessingInfo(itemRequest.getProcessingInfo());
            draftItems.add(draft);
        }
        validateStockSufficientForItems(draftItems, actionLabel);
    }

    /**
     * 核心库存校验：遍历明细，按 processingInfo 匹配 SKU（单一判据 {@link #matchSkuId}）并校验库存充足。
     * 未声明 SKU 身份的明细不校验（对应无 SKU 扣减，与确认支付/扣减语义一致）；
     * 声明了身份却定位不到 ⇒ 显式拒绝（fail-closed，issue #4090）。
     *
     * @param items      订单明细（已落库的 OrderItem 或下单请求构造的草稿明细均可）
     * @param actionLabel 动作文案（如「下单」/「确认支付」），用于错误提示
     * @throws BusinessException 库存不足、或规格无法定位到 SKU 时抛出业务异常
     */
    private void validateStockSufficientForItems(List<OrderItem> items, String actionLabel) {
        if (items == null) {
            return;
        }
        for (OrderItem item : items) {
            // 单一判据（issue #4090）：null 的唯一含义 = 该明细未声明 SKU 身份（合法，无 SKU 级库存）；
            // 声明了身份却定位不到 ⇒ matchSkuId 直接抛（可行动话术），不在这里静默 continue
            Long skuId = matchSkuId(item, actionLabel);
            if (skuId == null || item.getQuantity() == null) {
                continue;
            }
            ProductSku sku = productSkuMapper.selectById(skuId);
            int stock = sku != null && sku.getStock() != null ? sku.getStock() : 0;
            // issue #3666：数量为 BigDecimal，库存是整数列 → 按整数部分比较（与原 Integer
            // 语义一致；小数数量（米数/面积）以整数件库存校验，不引入新的舍入规则）
            int needed = item.getQuantity().intValue();
            if (stock < needed) {
                throw BusinessException.validationError(
                        String.format("商品「%s」库存不足：需要 %d 件，当前仅剩 %d 件，请先补货后再%s",
                                item.getProductName() != null ? item.getProductName() : skuId,
                                needed, stock, actionLabel));
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

        // 加工单联动（issue #3340）：未发加工 → 自动作废加工单；已发加工及以上 → 拦截，须先处理加工单
        ProcessingOrder activePo = processingOrderMapper.selectActiveByOrderId(order.getId(), order.getTenantId());
        if (activePo != null) {
            if ("generated".equals(activePo.getStatus())) {
                ProcessingOrder poUpd = ProcessingOrder.builder()
                        .id(activePo.getId())
                        .status("cancelled")
                        .cancelledAt(OffsetDateTime.now())
                        .cancelledReason("订单取消，加工单自动作废")
                        .build();
                processingOrderMapper.updateById(poUpd);
                log.info("订单取消联动作废加工单: po={}, orderId={}", activePo.getProcessingOrderNo(), order.getId());
            } else {
                throw BusinessException.validationError(String.format(
                        "订单已发加工（加工单 %s 状态：%s），请先在订单详情或让米宝处理加工单后再取消订单",
                        activePo.getProcessingOrderNo(), activePo.getStatus()));
            }
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
        adjustStockAndSales(orderId, true, StockLedger.REASON_ORDER);
    }

    /**
     * 取消/退款后：恢复库存 + 减少销量（商品级 + SKU级）
     */
    private void restoreStockAndDecreaseSales(String orderId) {
        adjustStockAndSales(orderId, false, StockLedger.REASON_ORDER);
    }

    /**
     * 售后退货回补库存（issue #2991）。
     *
     * 仅由 AfterSalesTicketService 在售后工单 refund/return 完结且订单全部商品
     * allow_return_restock=true（允许退货回补库存）时调用；复用取消订单的库存恢复路径
     * （恢复商品级+SKU级库存并减少销量）。窗帘行业定制退货不可再售，默认不走到本路径。
     *
     * <p>台账（issue #4137）：本路径的这次变更由**调用方** AfterSalesTicketService 落
     * {@code reason=aftersales} 行（它按「调用前快照 vs 调用后实际值」比对）——故这里传
     * {@code null} 不重复记账：同一次变更写两行会让 delta 翻倍，且两行的 before 互不相同
     * （相邻行首尾接不上，「库存为什么从 X 变成 Y」就答错了）。</p>
     */
    @Transactional(rollbackFor = Exception.class)
    public void restoreStockForReturn(String orderId) {
        adjustStockAndSales(orderId, false, null);
        log.info("售后退货回补库存完成: orderId={}", orderId);
    }

    /**
     * 统一的库存和销量调整逻辑
     *
     * @param orderId      订单ID
     * @param isDeduct     true=扣库存+增销量（确认支付），false=恢复库存+减销量（取消/退款）
     * @param ledgerReason 台账变更来源（{@link StockLedger#REASON_ORDER}）；
     *                     {@code null} = 本次变更的落账由上游站点负责（售后回补 → aftersales）
     */
    @SuppressWarnings("unchecked")
    private void adjustStockAndSales(String orderId, boolean isDeduct, String ledgerReason) {
        List<OrderItem> items = orderItemMapper.selectList(
                new LambdaQueryWrapper<OrderItem>().eq(OrderItem::getOrderId, orderId));
        if (items.isEmpty()) return;

        Order order = orderMapper.selectById(orderId);
        if (order == null) return;

        // 按 productId 聚合数量和金额
        // issue #3666：数量放宽为 BigDecimal，聚合也用 BigDecimal（不引入 double/float）；
        // 销量列是整数 → 仅在写库前取整数部分。
        Map<String, BigDecimal> productQtyMap = new java.util.HashMap<>();
        Map<String, BigDecimal> productAmountMap = new java.util.HashMap<>();

        for (OrderItem item : items) {
            if (item.getProductId() == null) continue;
            BigDecimal qty = item.getQuantity() != null ? item.getQuantity() : BigDecimal.ZERO;
            BigDecimal amount = item.getSubtotal() != null ? item.getSubtotal() : BigDecimal.ZERO;
            productQtyMap.merge(item.getProductId(), qty, BigDecimal::add);
            productAmountMap.merge(item.getProductId(), amount, BigDecimal::add);

            // SKU级库存调整：从 processingInfo 中匹配 SKU
            if (isDeduct) {
                deductSkuStock(item, order, ledgerReason);
            } else {
                restoreSkuStock(item, order, ledgerReason);
            }
        }

        // 商品级调整
        for (Map.Entry<String, BigDecimal> entry : productQtyMap.entrySet()) {
            String productId = entry.getKey();
            int totalQty = entry.getValue().intValue();
            BigDecimal totalAmount = productAmountMap.getOrDefault(productId, BigDecimal.ZERO);
            if (isDeduct) {
                productMapper.increaseSales(productId, totalQty, totalAmount);
            } else {
                productMapper.decreaseSales(productId, totalQty, totalAmount);
            }
        }
    }

    /**
     * 从 OrderItem 的 processingInfo 中匹配 SKU 并扣减库存（issue #4137：并落订单腿台账行）。
     *
     * <p>判据见 {@link #matchSkuId}：{@code null} 只可能是「未声明 SKU 身份」；
     * 声明了却定位不到会直接抛，不会静默跳过（issue #4090）——即「库存/销量/台账三者同生共死」。</p>
     */
    @SuppressWarnings("unchecked")
    private void deductSkuStock(OrderItem item, Order order, String ledgerReason) {
        Long skuId = matchSkuId(item, "确认支付");
        if (skuId != null && item.getQuantity() != null) {
            // 台账：变更前快照（只记真实变化，故快照必须取在写库之前）
            Map<Long, ProductSku> stockBefore = snapshotForLedger(ledgerReason, item.getProductId());
            // issue #3666：库存/销量列是整数，取整数部分（与库存校验同一口径）
            productSkuMapper.deductStock(skuId, item.getQuantity().intValue());
            productSkuMapper.increaseSalesCount(skuId, item.getQuantity().intValue());
            recordStockLedgerRows(ledgerReason, order, stockBefore, "订单确认支付扣减库存");
        }
    }

    /**
     * 从 OrderItem 的 processingInfo 中匹配 SKU 并恢复库存（issue #4137：并落订单腿台账行）。
     *
     * <p>与扣减侧同一判据 {@link #matchSkuId}（issue #4090）。</p>
     */
    private void restoreSkuStock(OrderItem item, Order order, String ledgerReason) {
        Long skuId = matchSkuId(item, "取消回补");
        if (skuId != null && item.getQuantity() != null) {
            Map<Long, ProductSku> stockBefore = snapshotForLedger(ledgerReason, item.getProductId());
            // issue #3666：库存/销量列是整数，取整数部分（与库存校验同一口径）
            productSkuMapper.restoreStock(skuId, item.getQuantity().intValue());
            productSkuMapper.decreaseSalesCount(skuId, item.getQuantity().intValue());
            recordStockLedgerRows(ledgerReason, order, stockBefore, "订单取消/退款回补库存");
        }
    }

    /**
     * 台账（issue #4137）：变更前快照 —— 复用 {@link StockLedgerService} 的同一套快照/比对语义
     * （落账唯一语义点在那边，订单侧不新造第二套比对逻辑）。
     *
     * @param ledgerReason {@code null} = 该路径的落账由上游站点负责（售后回补 → aftersales）⇒ 不取快照、零开销
     */
    private Map<Long, ProductSku> snapshotForLedger(String ledgerReason, String productId) {
        return ledgerReason == null ? Map.of() : stockLedgerService.snapshotSkus(List.of(productId));
    }

    /**
     * 台账（issue #4137）：变更后按**实际值**比对落账，只记真实变化的 SKU
     * （delta 由 {@link StockLedgerService} 按 after-before 算出；请求量与实际变化不一致时不落假账）。
     */
    private void recordStockLedgerRows(String ledgerReason, Order order,
                                       Map<Long, ProductSku> stockBefore, String note) {
        if (ledgerReason == null || order == null) {
            return;
        }
        stockLedgerService.recordChangesAgainstSnapshot(order.getTenantId(), stockBefore,
                ledgerReason, order.getOrderNo(), note);
    }

    /**
     * 库存路径的<b>单一判据</b>（issue #4090）：该明细是否声明了 SKU 身份、能否定位到 SKU。
     *
     * <p>processingInfo 键族：{@code { "skuId": N, "skuCode": "...", "colorId": N,
     * "colorName": "...", "sellingMethod": "...", "doorWidth": "...", ... }}。
     * <b>三种结果，只有一种允许「不做 SKU 级库存调整」</b>：</p>
     * <ul>
     *   <li>{@code null} —— 明细<b>没有声明 SKU 身份键</b>（{@code skuId/skuCode/colorId/colorName}
     *       全空）：该明细没有「选了哪个 SKU」的语义（只带加工项 / 售卖方式 / 门幅也是本仓合法形态，
     *       见 {@code OrderQuantityDecimalTest} 的真实 fixture），故不做 SKU 级库存调整
     *       （商品级销量照记）。这是<b>唯一</b>合法的跳过 —— 库存校验 / 扣减 / 销量 / 回补四处
     *       都只按这一条判据分支，不再各写一套「有没有规格」的判断；</li>
     *   <li>{@code skuId} —— 唯一定位到 SKU（四处都按它走）；</li>
     *   <li>{@link BusinessException} —— 声明了 SKU 身份却<b>定位不到</b>：显式失败 + 可行动
     *       suggestion（声明了哪些键、该补什么），<b>不再静默跳过</b>。</li>
     * </ul>
     *
     * <p><b>为什么「定位不到」必须显式失败（issue #4090 实证）</b>：库存校验 / 扣减 / 销量三处
     * 都写成 {@code if (skuId != null)}，而匹配原先只认 <b>ID 族</b>（{@code skuId}，或
     * {@code colorId+sellingMethod+doorWidth}）；唯一生产者 ai-agent（{@code order_create}）
     * 只能产出<b>字符串族</b>（{@code skuCode/colorName/sellingMethod/doorWidth} ——
     * {@code product_detail._format_skus} 既不给 {@code color_id} 也不给 {@code skuId}）
     * ⇒ 键族不相交 ⇒ 三处同时静默跳过：顾客下单成功、SKU 库存不动、销量不涨、无任何失败
     * （可超卖、账实不符、线上不可归因）。修法两步：① 判定**能读字符串族**
     * （{@code product_skus.sku_code / color_name} 就是同一行上的原值）；② 仍然定位不到时
     * **显式拒绝**而不是放行。</p>
     *
     * <p>口径统一（issue #3621 沿用）：售卖方式中文标签（{@code 散剪}）与带单位门幅
     * （{@code 2.8米}）用 {@link SkuNotation} 同一套归一化比较，只归一化<b>匹配比较</b>、
     * 不回写库内值；陈旧 {@code skuId} 先校验存在性，不存在则回退键族匹配（防主键漂移后
     * update 命中 0 行的静默失败）。</p>
     *
     * @param actionLabel 动作文案（「下单」/「确认支付」/「取消回补」），用于错误提示
     */
    @SuppressWarnings("unchecked")
    private Long matchSkuId(OrderItem item, String actionLabel) {
        if (item.getProductId() == null) return null;

        Object processingInfo = item.getProcessingInfo();
        if (!(processingInfo instanceof Map)) return null;
        Map<String, Object> info = (Map<String, Object>) processingInfo;

        Long skuId = toSkuKey(info.get("skuId"), "skuId", item);
        String skuCode = toSkuText(info.get("skuCode"));
        Long colorId = toSkuKey(info.get("colorId"), "colorId", item);
        String colorName = toSkuText(info.get("colorName"));
        String sellingMethod = toSkuText(info.get("sellingMethod"));
        String doorWidth = toSkuText(info.get("doorWidth"));

        // 未声明任何 SKU 身份键 → 无 SKU 级库存调整（唯一合法的跳过）
        if (skuId == null && skuCode == null && colorId == null && colorName == null) {
            return null;
        }

        // ① skuId 直查（ID 族最精确）：存在性 + 归属同商品 —— 主键漂移（agent 重建路径可能
        //    「删旧行 + 插新行」）后拿着陈旧 id 直接返回，会让扣减/回补 update 命中 0 行且完全静默
        if (skuId != null) {
            ProductSku byId = productSkuMapper.selectById(skuId);
            if (byId != null && belongsToProduct(byId, item.getProductId())) {
                return byId.getId();
            }
            log.warn("matchSkuId: processingInfo.skuId 不可用（库中不存在或不属于该商品），改走键族回退, action={}, orderId={}, productId={}, skuId={}",
                    actionLabel, item.getOrderId(), item.getProductId(), skuId);
        }

        // ② ID 族组合回退（#3621 既有口径，不动）：colorId + 售卖方式 + 门幅
        if (colorId != null && sellingMethod != null && doorWidth != null) {
            ProductSku byCombination = findSkuByCombination(item.getProductId(), colorId,
                    sellingMethod, doorWidth);
            if (byCombination != null) {
                return byCombination.getId();
            }
        }

        // ③ 字符串族（issue #4090 新增）：skuCode / colorName(+colorId) + 已声明属性键 ——
        //    唯一生产者 ai-agent 只能产出这一族，此前它必然落进 ④（静默跳过）
        ProductSku byKeyFamily = findSkuByKeyFamily(item.getProductId(), skuCode, colorId, colorName,
                sellingMethod, doorWidth);
        if (byKeyFamily != null) {
            return byKeyFamily.getId();
        }

        // ④ 声明了 SKU 身份却定位不到（含命中多行无法唯一确定）⇒ 显式失败，可行动 suggestion
        log.warn("matchSkuId: 声明了 SKU 身份但键族定位不到（未命中或多行歧义）→ 显式拒绝该动作（不静默跳过）, action={}, orderId={}, productId={}, {}",
                actionLabel, item.getOrderId(), item.getProductId(),
                describeDeclaredSpec(skuCode, colorId, colorName, sellingMethod, doorWidth));
        throw BusinessException.validationError(String.format(
                "商品「%s」的本次规格无法定位到 SKU（%s）：已声明 %s。"
                        + "无法确定该行对应哪个 SKU，故**拒绝**而不是放行（放行会造成「订单成交但库存不动、销量不涨」）。"
                        + "请用 product_detail 返回的 skus[] 原值核对规格（sku_code / color_name / selling_method / door_width），"
                        + "或直接传 skuId（skus[].id）后重试。",
                item.getProductName() != null ? item.getProductName() : item.getProductId(),
                actionLabel,
                describeDeclaredSpec(skuCode, colorId, colorName, sellingMethod, doorWidth)));
    }

    /**
     * 字符串族定位（issue #4090）：{@code skuCode} 精确匹配；{@code colorName/colorId} +
     * 已声明的售卖方式（归一化）/门幅（双侧归一化）组合匹配。
     *
     * <p>命中必须<b>唯一</b>：多行命中意味着「规格不足以唯一确定 SKU」（如只给了颜色、该颜色下
     * 有多个门幅），此时返回 null 交由调用方显式拒绝 —— 任取一条会扣错 SKU 的库存，比拒绝更糟。</p>
     *
     * @return 唯一命中的 SKU；0 行或多行命中返回 null（调用方负责告警与拒绝）
     */
    private ProductSku findSkuByKeyFamily(String productId, String skuCode, Long colorId, String colorName,
                                          String sellingMethod, String doorWidth) {
        if (skuCode == null && colorId == null && colorName == null) {
            return null;
        }
        LambdaQueryWrapper<ProductSku> wrapper = new LambdaQueryWrapper<ProductSku>()
                .eq(ProductSku::getProductId, productId)
                .eq(skuCode != null, ProductSku::getSkuCode, skuCode)
                .eq(colorId != null, ProductSku::getColorId, colorId)
                .eq(colorName != null, ProductSku::getColorName, colorName)
                .eq(sellingMethod != null, ProductSku::getSellingMethod,
                        SkuNotation.normalizeSellingMethod(sellingMethod))
                .orderByAsc(ProductSku::getId);
        List<ProductSku> rows = productSkuMapper.selectList(wrapper);

        ProductSku found = null;
        int hits = 0;
        for (ProductSku row : rows == null ? List.<ProductSku>of() : rows) {
            // 门幅双侧归一化比较（库内 2.8 与明细 2.8米 同一物理门幅；2.8 vs 3.2 不等）
            if (doorWidth != null && !SkuNotation.sameDoorWidth(row.getDoorWidth(), doorWidth)) {
                continue;
            }
            if (found == null) {
                found = row;
            }
            hits++;
        }
        if (hits > 1) {
            log.warn("matchSkuId: 规格不足以唯一定位 SKU（{} 行命中）→ 交由调用方显式拒绝, productId={}, skuCode={}, colorId={}, colorName={}, sellingMethod={}, doorWidth={}",
                    hits, productId, skuCode, colorId, colorName, sellingMethod, doorWidth);
            return null;
        }
        return found;
    }

    /** 该 SKU 是否属于本明细的商品（库内 product_id 为空的历史行不据此排除）。 */
    private boolean belongsToProduct(ProductSku sku, String productId) {
        return sku.getProductId() == null || sku.getProductId().equals(productId);
    }

    /** 规格键取值：非空文本去首尾空白；空串/空白视为未声明。 */
    private String toSkuText(Object raw) {
        if (raw == null) return null;
        String text = raw.toString().trim();
        return text.isEmpty() ? null : text;
    }

    /** 规格键取值：数字键（skuId/colorId）解析失败时留 WARN 并视为未声明（不静默）。 */
    private Long toSkuKey(Object raw, String key, OrderItem item) {
        if (raw == null) return null;
        try {
            return Long.valueOf(raw.toString().trim());
        } catch (NumberFormatException e) {
            log.warn("matchSkuId: {} 格式错误（非数字，视为未声明）, orderId={}, productId={}, value={}",
                    key, item.getOrderId(), item.getProductId(), raw);
            return null;
        }
    }

    /** 已声明的规格键描述（错误话术/告警用：说清「缺哪个键、该补什么」的依据）。 */
    private String describeDeclaredSpec(String skuCode, Long colorId, String colorName,
                                        String sellingMethod, String doorWidth) {
        List<String> parts = new ArrayList<>();
        if (skuCode != null) parts.add("skuCode=" + skuCode);
        if (colorId != null) parts.add("colorId=" + colorId);
        if (colorName != null) parts.add("colorName=" + colorName);
        if (sellingMethod != null) parts.add("sellingMethod=" + sellingMethod);
        if (doorWidth != null) parts.add("doorWidth=" + doorWidth);
        return String.join(", ", parts);
    }

    // ======================== Agent BFF 方法 ========================

    /**
     * 组合回退匹配：商品 + 颜色 + 售卖方式（归一化后）定位候选，门幅在 Java 侧按
     * {@link SkuNotation#sameDoorWidth} 双侧归一化比较（库内 {@code 2.8} 与明细
     * {@code 2.8米} / {@code 门幅2.8米} 视为同一物理门幅；{@code 2.8} vs {@code 3.2} 不等）。
     *
     * <p>只归一化<b>匹配比较</b>，不回写库内值（与 #3546 调价路径同一处理）。同一组合命中
     * 多行时取第一条并告警，便于发现历史重复行。
     *
     * @return 命中的 SKU；未命中返回 null（调用方负责告警，不再静默跳过）
     */
    private ProductSku findSkuByCombination(String productId, Long colorId,
                                            String sellingMethod, String doorWidth) {
        List<ProductSku> candidates = productSkuMapper.selectList(
                new LambdaQueryWrapper<ProductSku>()
                        .eq(ProductSku::getProductId, productId)
                        .eq(ProductSku::getColorId, colorId)
                        .eq(ProductSku::getSellingMethod, SkuNotation.normalizeSellingMethod(sellingMethod)));
        ProductSku found = null;
        int hits = 0;
        for (ProductSku candidate : candidates) {
            if (SkuNotation.sameDoorWidth(candidate.getDoorWidth(), doorWidth)) {
                if (found == null) {
                    found = candidate;
                }
                hits++;
            }
        }
        if (hits > 1) {
            log.warn("matchSkuId: 归一化后同一组合命中多行 SKU（库内可能存在同门幅重复行），取第一条: productId={}, colorId={}, sellingMethod={}, doorWidth={}, hits={}",
                    productId, colorId, sellingMethod, doorWidth, hits);
        }
        return found;
    }

    /**
     * Agent 专用创建订单。
     *
     * <p><b>校验口径（issue #4089 · A17 收敛）</b>：入参是 {@link OrderCreateRequest} 的**子类型**
     * （{@code AgentOrderCreateRequest} 只多一个请求头注入的幂等键），约束全部来自共享类型，
     * 由 {@code AgentOrderController} 的 {@code @Valid} 执行；本方法**不再手工 {@code new}
     * 一个 {@code OrderCreateRequest} 逐字段搬运**（那正是「校验双写」的载体：手工 new 让
     * Bean Validation 失效 ⇒ 这里必须再判一遍 ⇒ 两处口径必然漂移），而是把请求**原对象**
     * 交给 {@link #createOrder}（同一入口、同一套断言、同一份文案）。</p>
     *
     * <p>只保留两条**Bean Validation 表达不了**的 agent 专属语义：
     * ① 姓名/电话非空 + 手机号格式（共享类型上的 {@code @NotBlank}/{@code @Pattern} 已在控制器层
     * 执行，这里保留同名同文案的显式判定，兜住绕过 HTTP 的程序化调用方 —— 与 {@code createOrder}
     * 的数量/单价闸门同族，不是第二套口径）；
     * ② 服务端取价校验 {@link #validateAgentItemUnitPrice}（SKU 权威价，见该方法）。</p>
     *
     * <p>幂等键（issue #4037，F19）：请求头 {@code X-Client-Request-Id} 非空时按
     * {@code (tenantId, 键)} 去重 —— 首次请求正常执行并把 {@link OrderDetailResponse} 快照落库，
     * 同键再次到达**不再执行**、直接回放首次结果（顾客/LLM 看到同一订单号）。无键 ⇒ 原路径逐字不变。</p>
     *
     * <p><b>并发语义（如实登记，不谎称「并发也直接回放」）</b>：本方法带
     * {@code @Transactional}，而 {@code claim}/{@code complete}/{@code discard} 跑在**同一个事务**里
     * ⇒ ① 成功才一起提交、失败一起回滚（占位不会残留）；② **并发同键**时第二个请求的
     * {@code INSERT ... ON CONFLICT DO NOTHING} 会**阻塞在唯一索引上**，直到第一个提交或回滚 ——
     * 提交后它读到已落库的快照并回放（同一订单号），回滚后它自己成为首次执行者。
     * 即并发是「串行等待」而非「立即回放」；这是刻意取舍（换取「不留残留占位」与更少机器），
     * 代价是同键并发第二个请求的响应时间被拉长。</p>
     */
    @Transactional(rollbackFor = Exception.class)
    public OrderDetailResponse createOrderForAgent(AgentOrderCreateRequest request, Long tenantId) {

        if (!StringUtils.hasText(request.getCustomerName())) {
            throw BusinessException.validationError("客户姓名不能为空");
        }
        if (!StringUtils.hasText(request.getCustomerPhone())) {
            throw BusinessException.validationError("客户电话不能为空");
        }
        // 手机号格式校验（与共享 DTO 的 @Pattern 同一条正则、同一句文案）
        String phone = request.getCustomerPhone().trim();
        if (!phone.matches("^1[3-9]\\d{9}$")) {
            throw BusinessException.validationError("手机号格式不正确，请输入11位中国大陆手机号");
        }
        request.setCustomerPhone(phone);

        if (request.getItems() == null || request.getItems().isEmpty()) {
            throw BusinessException.validationError("商品明细不能为空");
        }

        for (OrderCreateRequest.OrderItemRequest item : request.getItems()) {
            // GB/T 47746-2026 M3（issue #2806）：服务端取价校验——SKU 可解析时，
            // unitPrice 必须与权威价严格一致（防 LLM 定价幻觉；解析不到不拦截防误伤）。
            // 规格键（skuCode/colorName）从 processingInfo 解析（唯一生产者的形态，见本方法注释）。
            validateAgentItemUnitPrice(item, tenantId);
            // subtotal 服务端强制重算（对抗 LLM 编造）—— 逐字保留收敛前的口径演算：
            // `order_items.subtotal` 直接喂 `products.sales_amount`（见 adjustStockAndSales），
            // 不能让客户端自称的小计进统计口径。这不是「第二套校验」（约束来自共享类型），
            // 是**唯一**的口径归一化点。
            if (item.getQuantity() != null && item.getUnitPrice() != null) {
                item.setSubtotal(item.getUnitPrice().multiply(item.getQuantity()));
            }
        }

        // ── 幂等键（issue #4037）：同 (tenantId, X-Client-Request-Id) 只真正执行一次 ──
        String clientRequestId = request.getClientRequestId();
        // 无幂等键（老 ai-agent / 表单类调用方）⇒ 原路径逐字不变：零 DB 往返、不因服务端升级而报错
        if (!StringUtils.hasText(clientRequestId)) {
            return createOrder(request, tenantId);
        }
        // ① 原子占位（INSERT ... ON CONFLICT DO NOTHING，按影响行数判首次）——
        //    不用「捕获唯一约束异常」探测冲突：PG 里冲突会让当前事务进入 aborted 状态，后续查询全失败
        if (!clientRequestIdService.claim(tenantId, clientRequestId, ENDPOINT_CREATE_ORDER)) {
            // ② 同键重复 ⇒ 不执行，直接回放首次成功快照（replay 对「占位但无结果」fail-closed 抛错）
            return clientRequestIdService.replay(tenantId, clientRequestId, OrderDetailResponse.class)
                    .orElseThrow(() -> new BusinessException("REQUEST_IN_PROGRESS",
                            "同一 X-Client-Request-Id 的请求正在处理中，本次未重复执行（请勿重复提交）",
                            409,
                            "请勿重复提交；请稍后用 order_query 查询确认结果（换新幂等键重试同样会造成重复下单）"));
        }
        OrderDetailResponse created;
        try {
            created = createOrder(request, tenantId);
        } catch (RuntimeException e) {
            // ④ 执行失败 ⇒ 释放占位：否则一次失败就把该键永久占死，之后的重试全被误判为「重复」
            clientRequestIdService.discard(tenantId, clientRequestId);
            throw e; // 原样抛出，不吞（失败必须对调用方可见）
        }
        // ③ 执行成功 ⇒ 落结果快照，同键后续请求回放它。放在 try 之外：
        //    快照写失败时**不得**释放占位（订单已经建出来了），宁可让同键请求 fail-closed 报错
        clientRequestIdService.complete(tenantId, clientRequestId, created);
        return created;
    }

    /**
     * Agent 下单明细单价的服务端取价校验（GB/T 47746-2026 M3，issue #2806）。
     *
     * 规则（严格一致才放行，用户已确认）：
     * - 明细同时提供 productId 与 skuCode（或 colorName）且能解析到唯一 SKU → 请求 unitPrice
     *   必须与 SKU 权威价一致（BigDecimal compareTo == 0），不一致抛 400 并附权威价供修正；
     * - 解析不到（无 SKU 标识 / SKU 不存在 / 命中多条 SKU 无法唯一确定）→ 不拦截（防误伤），记 warn。
     *
     * <p>规格键只在 {@code processingInfo} 内（issue #4089 收敛后 DTO 不再有顶层
     * {@code skuCode}/{@code colorName} 字段——那正是 issue 清单的 D1/D2：唯一生产者从不填它们，
     * 而库存匹配键族也不读它们）。</p>
     */
    private void validateAgentItemUnitPrice(OrderCreateRequest.OrderItemRequest item, Long tenantId) {
        if (item.getUnitPrice() == null) {
            return;
        }
        // SKU 标识从 processingInfo（商品销售信息）内解析 —— ai-agent order_create 与表单页
        // 两个生产者的真实形态
        String skuCode = null;
        String colorName = null;
        if (item.getProcessingInfo() instanceof Map<?, ?> info) {
            Object rawSku = info.get("skuCode");
            if (rawSku != null) {
                skuCode = String.valueOf(rawSku);
            }
            Object rawColor = info.get("colorName");
            if (rawColor != null) {
                colorName = String.valueOf(rawColor);
            }
        }
        boolean hasSkuKey = StringUtils.hasText(skuCode) || StringUtils.hasText(colorName);
        if (!StringUtils.hasText(item.getProductId()) || !hasSkuKey) {
            return; // 无 SKU 标识，无法解析权威价 → 不拦截
        }

        LambdaQueryWrapper<ProductSku> wrapper = new LambdaQueryWrapper<>();
        wrapper.eq(ProductSku::getTenantId, tenantId)
                .eq(ProductSku::getProductId, item.getProductId());
        if (StringUtils.hasText(skuCode)) {
            wrapper.eq(ProductSku::getSkuCode, skuCode);
        } else {
            wrapper.eq(ProductSku::getColorName, colorName);
        }
        wrapper.orderByAsc(ProductSku::getId)
                .last("LIMIT 2"); // 取 2 条探测歧义
        List<ProductSku> skus = productSkuMapper.selectList(wrapper);
        if (skus == null || skus.isEmpty()) {
            log.warn("[order] 取价校验跳过（SKU 未解析到）: productId={} skuCode={} colorName={}",
                    item.getProductId(), skuCode, colorName);
            return;
        }
        if (skus.size() > 1) {
            log.warn("[order] 取价校验跳过（SKU 不唯一，无法确定权威价）: productId={} skuCode={}",
                    item.getProductId(), skuCode);
            return;
        }
        BigDecimal authoritative = skus.get(0).getPrice();
        if (authoritative == null) {
            return; // SKU 无价格，无从校验
        }
        if (item.getUnitPrice().compareTo(authoritative) != 0) {
            log.warn("[order] 取价校验拒绝（LLM 单价≠权威价）: productId={} skuCode={} request={} authoritative={}",
                    item.getProductId(), skuCode, item.getUnitPrice(), authoritative);
            throw BusinessException.validationError(
                    String.format("商品「%s」单价与系统价格不一致：请求 %.2f 元，系统价 %.2f 元。请以系统价重新下单。",
                            item.getProductName(), item.getUnitPrice(), authoritative));
        }
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
                        request.getTrackingNumber().trim(), null);
                // 发货语义：记录物流后将订单流转为 shipped（与契约 order_manage(update_logistics) 可发货一致）
                shipOrderIfApplicable(resolvedId);
                yield getOrderById(resolvedId);
            }
            default -> throw BusinessException.validationError(
                    "不支持的操作类型: " + action + "，可选: update_status/update_logistics/confirm_payment/cancel/refund");
        };
    }

    /**
     * 发货人取值（issue #3768）：显式传入优先，否则用当前登录用户姓名兜底。
     *
     * <p>两条发货路径共用同一口径 —— B 端 {@code PUT /api/admin/orders/{id}/logistics}
     * （前端发货页预填当前登录人、可改成实际发货人）与 agent
     * {@code order_manage(action=update_logistics)}（透传 {@code X-User-Id}）。
     *
     * @param provided 请求显式提供的发货人，可为空
     * @return 发货人姓名；都取不到时返回 null（打印/展示显示「-」）
     */
    public String resolveShipperName(String provided) {
        if (StringUtils.hasText(provided)) {
            return provided.trim();
        }
        return userService.resolveCurrentUserDisplayName();
    }

    /**
     * 更新/创建订单物流信息：存在最新物流记录则更新，否则新建（status=in_transit）。
     *
     * <p>发货人（issue #3768）语义：新建时取 {@code resolveShipperName(provided)}；
     * 更新时**仅**在显式传入非空时覆盖 —— 后续改运单号/纠错不等于换发货人，
     * 也不能因为「别人来改单号」就把经手人改成那个人，更不能为存量历史数据猜一个经手人。
     */
    private void upsertLogistics(String orderId, String logisticsCompany, String trackingNo, String shipperName) {
        List<OrderLogistics> existing = orderLogisticsMapper.selectByOrderId(orderId, TenantContext.getTenantId());
        if (existing == null || existing.isEmpty()) {
            OrderLogistics logistics = OrderLogistics.builder()
                    .tenantId(TenantContext.getTenantId())
                    .orderId(orderId)
                    .logisticsCompany(logisticsCompany)
                    .trackingNo(trackingNo)
                    .shipperName(resolveShipperName(shipperName))
                    .status("in_transit")
                    .shippedAt(OffsetDateTime.now())
                    .build();
            orderLogisticsMapper.insert(logistics);
            log.info("创建物流信息成功: orderId={}, trackingNo={}, shipper={}",
                    orderId, trackingNo, logistics.getShipperName());
        } else {
            OrderLogistics latest = existing.get(0);
            latest.setLogisticsCompany(logisticsCompany);
            latest.setTrackingNo(trackingNo);
            // 仅显式传入才覆盖：兜底值属于「新建时的经手人」，不能用它改写已记录的发货人
            // （否则改一次运单号/agent 补一次单号就会把经手人换成当次操作人）
            if (StringUtils.hasText(shipperName)) {
                latest.setShipperName(shipperName.trim());
            }
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
            // P1 修复（验收复核 #3345）：与 updateOrderStatus 路径同一守卫——含加工项订单
            // 须有 completed 加工单才能发货，防止 agent 发货路径绕过加工环节
            assertProcessingCompletedBeforeShip(order);
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
