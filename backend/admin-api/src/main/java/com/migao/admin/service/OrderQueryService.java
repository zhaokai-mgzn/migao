package com.migao.admin.service;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.*;
import com.migao.admin.dto.agent.AgentOrderResolveResponse;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.entity.OrderLogistics;
import com.migao.admin.entity.Product;
import com.migao.admin.entity.ProductSku;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderLogisticsMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.PrintLogMapper;
import com.migao.admin.mapper.ProductMapper;
import com.migao.admin.mapper.ProductSkuMapper;
import com.migao.admin.time.BusinessClock;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.BeanUtils;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;

/**
 * 订单<b>查询族</b>服务（issue #8191，P2-1a）。
 *
 * <p>从 {@link OrderService}（3,690 行 / 98 方法 / 15 个注入依赖）拆出的<b>读面</b>：
 * 列表分页、详情、单号解析，以及它们共用的 DTO 转换 / 批量补全辅助。拆的是<b>位置</b>，
 * <b>不是行为</b>：方法体逐字搬运（分支 / 异常类型 / 日志 / 空值语义不变），
 * 所有 {@code @Transactional} 边界跟着方法走（本类方法本来就都是只读、无事务注解）；
 * {@link OrderService} 保留同名门面委托，现有调用方零改动。
 *
 * <p><b>有意不搬</b>（P2-1a 的边界）：创建（{@code createOrder} / {@code createOrderForAgent}）、
 * 状态流转（{@code cancelOrder} / 发货 / {@code refundOrder}）、金额与库存计算 —— 它们仍留在
 * {@link OrderService}，后续期次再拆。</p>
 *
 * <p>两个方法<b>留在 OrderService</b> 并被本类反向调用（既有单测按 {@code OrderService.xxx} 引用，
 * 搬走就得改测试）：{@code OrderService.applyStatusFilter}（状态多值筛选）与
 * {@code OrderService.resolveListWindow}（列表默认回溯窗口）。它们是无状态的静态纯函数，
 * 跨类调用不引入任何第二份口径。</p>
 */
@Service
@RequiredArgsConstructor
public class OrderQueryService {

    private final OrderMapper orderMapper;
    private final OrderItemMapper orderItemMapper;
    private final OrderLogisticsMapper orderLogisticsMapper;
    private final ProductMapper productMapper;
    private final ProductSkuMapper productSkuMapper;
    private final ObjectMapper objectMapper;
    private final PrintLogMapper printLogMapper;
    private final BusinessClock businessClock;

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
     * @param creator         制单人姓名（issue #5835：非空时按 {@code created_by_name} **模糊**匹配）
     * @return 分页响应
     */
    public PageResponse<OrderListResponse> getOrderPage(long page, long size, String status, String keyword, String followStatus, Boolean hasProcessing, String startDate, String endDate, String orderId, String receiver, String productCode, String productTitle, Long tenantId, String userId, String creator, String dataScopeOwnerId) {
        LambdaQueryWrapper<Order> wrapper = new LambdaQueryWrapper<>();

        // 数据范围（issue #7372 段 1）：非 null ⇒ 只看该用户创建的单据（角色范围 = self）。
        // ⚠️ 与下面的 C 端隔离是**两件事**：本参数来自**服务端角色配置**，userId 来自查询入参。
        if (StringUtils.hasText(dataScopeOwnerId)) {
            wrapper.eq(Order::getCreatedBy, dataScopeOwnerId);
        }
        // C 端数据隔离：按下单用户过滤（必须精确匹配 user_id，忽略其他模糊条件）
        if (StringUtils.hasText(userId)) {
            wrapper.eq(Order::getUserId, userId);
        }

        // 制单人过滤（issue #5835，用户裁定「文本框模糊匹配」）：
        // 只认**快照列** created_by_name（不 join users —— 见 V142 的注释）。
        // 🔴 `like` 是**紧条件**：存量单该列为 NULL ⇒ 自然落选（用户裁定「筛了就只出有制单人的单」），
        //    无需额外 `isNotNull` —— NULL LIKE 在 SQL 三值逻辑下不为真，条件自动把它排除。
        if (StringUtils.hasText(creator)) {
            wrapper.like(Order::getCreatedByName, creator.trim());
        }

        // 状态筛选（支持逗号分隔多值，见 applyStatusFilter）
        OrderService.applyStatusFilter(wrapper, status);

        // 跟进状态筛选
        if (StringUtils.hasText(followStatus)) {
            wrapper.eq(Order::getFollowStatus, followStatus);
        }

        // 时间范围筛选（issue #6200：日界 = 业务日 +08，不是 UTC 日）
        // 半开区间 [D 00:00+08, D+1 00:00+08)：原写法把两端拼成 UTC 日的 00:00 与 23:59:59，把
        // 北京 00:00–08:00 的单归错天 / 月 / 年，且与走 businessClock 的看板 / 趋势互相矛盾。
        OrderService.ListDateWindow window = OrderService.resolveListWindow(startDate, endDate, businessClock);
        wrapper.ge(Order::getCreatedAt, window.start());
        wrapper.lt(Order::getCreatedAt, window.end());

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
                // 🔴 issue #6884：改前是 `itemWrapper.eq(OrderItem::getProductId, productCode)` ——
                // 拿**货号**去比 `order_items.product_id`（商品主键，形如 UUID）⇒ 恒不相等 ⇒
                // 商家输入任何货号都得到**空页**（不是「忽略条件」）。货号的真值在 `products.sku_code`
                // 上（列表展示用的 `OrderItemBrief.productCode` 也是从它填的）。
                // 口径与同块的 `productTitle` 一致：**子串匹配**（搜索框语义）。
                List<String> productIds = productMapper.selectList(
                                new LambdaQueryWrapper<Product>()
                                        .like(Product::getSkuCode, productCode)
                                        .select(Product::getId))
                        .stream()
                        .map(Product::getId)
                        .collect(Collectors.toList());
                if (productIds.isEmpty()) {
                    // 没有任何商品匹配这个货号 ⇒ 结果必然是空 —— 如实返回空页，不得退化成「忽略该条件」
                    return PageResponse.of(0L, page, size, Collections.emptyList());
                }
                itemWrapper.in(OrderItem::getProductId, productIds);
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
        enrichListResponses(responses, tenantId);

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

        // 状态筛选（支持逗号分隔多值，见 applyStatusFilter）
        OrderService.applyStatusFilter(wrapper, status);

        wrapper.orderByDesc(Order::getCreatedAt);

        Page<Order> orderPage = new Page<>(page, size);
        Page<Order> resultPage = orderMapper.selectPage(orderPage, wrapper);

        List<OrderListResponse> responses = resultPage.getRecords().stream()
                .map(this::convertToListResponse)
                .collect(Collectors.toList());
        enrichListResponses(responses, tenantId);

        return PageResponse.of(resultPage.getTotal(), resultPage.getCurrent(), resultPage.getSize(), responses);
    }


    /**
     * 批量补充订单明细/加工费/实收款/「是否已打印」（getOrderPage 与 getMyOrderPage 共用，避免 N+1）
     *
     * @param tenantId 当前租户（打印汇总必须**同租户**：跨租户的 order_id 撞车不可想象，但白读一次也没意义）
     */
    private void enrichListResponses(List<OrderListResponse> responses, Long tenantId) {
        // 「是否已打印」（V201，issue #7902）：先给**全页**的确定值，再一次性批量覆盖 ——
        // 两条分支（有单 / 空页）都拿到同一份口径，前端不必分情况判空。
        enrichPrintStatus(responses, tenantId);

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
                                    // issue #6883：行主键（`order_items.id`）—— 余料行搜索要它指认「哪一行」
                                    item.getId(),
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
                // issue #4406：加工费 = Σ 各行**落库时算好的**加工费（组合价 × 加工费米数），不重算。
                BigDecimal processingFee = orderItems.stream()
                        .map(item -> storedProcessingFee(item.getProcessingInfo()))
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
     * 批量补充「是否已打印」（V201，issue #7902）：**一次**聚合查询（禁止 N+1）。
     *
     * <h3>三个读数的口径</h3>
     * <ul>
     *   <li>{@code printedAt} = 最近一次**成功发起**的打印时间（{@code print_logs.status = 'fired'}）；
     *       {@code null} = 从未打印；</li>
     *   <li>{@code printCount} = 打印条数（不是出纸张数之和 —— 「打了几次」与「出了几张纸」是两件事）；</li>
     *   <li>{@code printedDocTypes} = 去重排序的单据类型（{@code processing} / {@code sales} / …）。</li>
     * </ul>
     *
     * <p>🔴 未打印的订单回的是**确定值**（{@code null} / {@code 0} / 空列表），不是「本次不填」：
     * 让「没打过」与「读不到」长得不一样，前端就得按三种情况判空 —— 而那正是「某处漏填了」
     * 永远不会被发现的原因（判据：{@code OrderServicePrintStatusTest}）。</p>
     */
    private void enrichPrintStatus(List<OrderListResponse> responses, Long tenantId) {
        for (OrderListResponse response : responses) {
            response.setPrintedAt(null);
            response.setPrintCount(0);
            response.setPrintedDocTypes(Collections.emptyList());
        }
        // 空页 / 单测切片（未装配 Mapper）/ 无租户上下文 ⇒ 不发查询（`IN ()` 还会是语法错误）
        if (printLogMapper == null || responses.isEmpty() || tenantId == null) {
            return;
        }
        List<String> orderIds = responses.stream()
                .map(OrderListResponse::getId)
                .filter(StringUtils::hasText)
                .distinct()
                .collect(Collectors.toList());
        if (orderIds.isEmpty()) {
            return;
        }
        Map<String, PrintLogSummary> summaries = printLogMapper.selectPrintSummary(tenantId, orderIds).stream()
                .collect(Collectors.toMap(PrintLogSummary::getOrderId, summary -> summary, (first, second) -> first));
        for (OrderListResponse response : responses) {
            PrintLogSummary summary = summaries.get(response.getId());
            if (summary == null) {
                continue;
            }
            response.setPrintedAt(summary.getPrintedAt());
            response.setPrintCount(summary.getPrintCount() == null ? 0 : summary.getPrintCount());
            response.setPrintedDocTypes(summary.printedDocTypes());
        }
    }


    /**
     * 根据ID查询订单详情（含订单明细和物流信息）
     *
     * @param id 订单ID
     * @return 订单详情响应
     */
    public OrderDetailResponse getOrderById(String id) {
        return getOrderById(id, null);
    }


    /**
     * 详情读面 + **数据范围**（issue #7372 段 1）。
     *
     * <p>范围外 ⇒ 与「不存在」**同一个 404**（不 403）：403 会告诉调用方「这个 id 存在，只是你看不到」，
     * 那本身就是泄露。判据 = {@code DataScopeTest#outOfScopeIsIndistinguishableFromMissing}。</p>
     *
     * @param dataScopeOwnerId 非 null ⇒ 只允许读该用户创建的单据
     */
    public OrderDetailResponse getOrderById(String id, String dataScopeOwnerId) {
        Order order = orderMapper.selectById(id);
        if (order == null) {
            throw BusinessException.notFound("订单");
        }
        if (StringUtils.hasText(dataScopeOwnerId)
                && !dataScopeOwnerId.equals(order.getCreatedBy())) {
            // 越权对象 = 不存在（同一句提示，不泄露存在性）
            throw BusinessException.notFound("订单");
        }

        return convertToDetailResponse(order);
    }


    /**
     * 订单在**当前租户**下是否可见（issue #6158）。
     *
     * <p>语义 = {@link #getOrderById} 的 404 那一半（同一条 {@code orderMapper.selectById}，由
     * MyBatis-Plus 租户拦截器按 {@link com.migao.admin.config.TenantContext} 追加
     * {@code tenant_id} 条件）—— 本单只做归属认定，**不**顺手带状态闸门
     * （那是 {@code OrderStatusTransitions} 在写路径上的职责，多判一次 = 第二套判定）。</p>
     *
     * <p>存在理由：该认定要在 {@code PUT /api/admin/orders/{id}/content} 的**参数解析之前**
     * 执行（见 {@code TenantOwnershipInterceptor}），而写路径自己的 {@code selectById}
     * 发生在参数解析之后。</p>
     *
     * @param id 订单ID
     * @return 当前租户下可见 ⇒ true
     */
    public boolean existsForCurrentTenant(String id) {
        return orderMapper.selectById(id) != null;
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

        // 「发货前是否有需要报工的作业」+「没有作业单时该生成哪一型」（issue #7079 第 5 包）：
        // 判据本体在 `OrderShipGuard.requiredOrderKind`（= 发货守卫用的那份 `needsWork` 的同一实现点），
        // 本处只做参数搬运 —— 前端据此给卖布单「生成出库作业单」的出口、并前置拦下发货。
        // ⚠️ 它自己加载一次明细（`items` 走的是 `OrderItem` 实体、没有 `processing_info` 的解析结果可复用，
        // 见 `OrderShipGuard.loadOrderItems` 的既有约定：必须走 BaseMapper 才经 JacksonTypeHandler）。
        String workOrderKind = OrderShipGuard.requiredOrderKind(orderItemMapper, objectMapper, order);
        response.setNeedsWork(workOrderKind != null);
        response.setWorkOrderKind(workOrderKind);

        // 后端统一聚合加工项，并计算加工费 / 实收款（架构决策：费用计算全部在后端）
        // issue #4406：加工费 = Σ 各行**落库时算好的**加工费（组合价 × 加工费米数），不重算；
        // 同时把该行的加工费与可审计构成透出（行级 processingFee / processingFeeDetail）。
        // ⚠️ `processingItems` 列表保持原样（**明细快照**：当时选了哪些加工项）；
        //    issue #4882 起快照不再有 `unitPrice` / `amount`（加工费口径**只有** processingFee 一处）。
        List<OrderDetailResponse.ProcessingItemBrief> aggregatedProcessing = new ArrayList<>();
        BigDecimal processingFee = BigDecimal.ZERO;
        // 安装小区（issue #7856）：**读侧收敛** —— 取该单明细里第一条非空（写侧扇出到每行同值）。
        // 存量单 / 扇出之前落的单没有该键 ⇒ null（前端不渲染该行，不印「—」占纸）。
        String installCommunity = null;
        for (int i = 0; i < items.size(); i++) {
            OrderItem item = items.get(i);
            aggregatedProcessing.addAll(extractProcessingItems(item.getProcessingInfo()));
            ProcessingFeeCalculator.Fee fee = ProcessingFeeCalculator.storedFee(item.getProcessingInfo());
            // #4525：行加工费 = 组合那半 + Σ 选项价（落库时的完整行金额；读面**不重算**，R13）
            BigDecimal itemFee = fee == null ? BigDecimal.ZERO : fee.lineAmount();
            processingFee = processingFee.add(itemFee);
            OrderDetailResponse.OrderItemResponse itemResponse = itemResponses.get(i);
            itemResponse.setProcessingFee(itemFee);
            itemResponse.setProcessingFeeDetail(fee == null ? null : fee.detail());
            // 安装信息（issue #7856）：行级「安装位置」逐行投影；订单级「安装小区」读侧收敛。
            itemResponse.setInstallRoom(OrderInstallInfo.valueOf(
                    item.getProcessingInfo(), OrderInstallInfo.KEY_INSTALL_ROOM, objectMapper));
            if (installCommunity == null) {
                installCommunity = OrderInstallInfo.valueOf(
                        item.getProcessingInfo(), OrderInstallInfo.KEY_INSTALL_COMMUNITY, objectMapper);
            }
        }
        response.setInstallCommunity(installCommunity);
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
            // 发货方式（issue #6239）：回吐「用户当时选了什么」；null = 未采集（存量行）
            logisticsInfo.setShippingMethod(logistics.getShippingMethod());
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
     * 从订单明细的 processingInfo（JSON）中解析加工项列表。
     * processingInfo 格式来自前端创建订单时写入：
     * { "processingFee": <number>, "processingItems": [ { id,name,quantity,unit } ] , ... }
     * 解析失败/缺字段时返回空列表，确保不影响订单查询主流程。
     *
     * <p>issue #4882：加工项目录已删「单价」与「计价方式」（下单入口也不再写 {@code unitPrice}）
     * ⇒ 本方法只回填 {@code id} / {@code name} / {@code quantity}。加工费**不**在这里取 ——
     * 真值源 = {@code processing_info.processingFeeDetail}（{@code processing_fee_combinations} 落库值），
     * 见 {@link #storedProcessingFee}。</p>
     *
     * issue #3340 验收实战：processingInfo 可能是 JSON **字符串**（自定义 @Select 查询不经过
     * JacksonTypeHandler），此处做兼容解析，避免"有加工项却被判无加工项"。
     */
    @SuppressWarnings("unchecked")
    private List<OrderDetailResponse.ProcessingItemBrief> extractProcessingItems(Object processingInfo) {
        return OrderShipGuard.extractProcessingItems(objectMapper, processingInfo);
    }


    /**
     * 读单个订单明细的加工费（issue #4406）：**读落库时算好的那一份**，不重算。
     *
     * <p>旧实现 = {@code Σ 加工项单价 × 数量}（{@code extractProcessingItems} 求和）——
     * 它是「配了组合费用订单金额一分不变」的病根，也是 R13「改组合价后历史订单一字不变」的破坏点
     * （重算 ⇒ 历史订单金额随价目表漂移）。新口径 = 取
     * {@code processing_info.processingFeeDetail.amount}（{@code createOrder} 落库的唯一权威值）。</p>
     *
     * <p>存量单（接线前生成、无 {@code processingFeeDetail}）⇒ **返回 0**（{@code unpriced}）：
     * 「这一行没有权威加工费」必须显式可见，**不**拿一个重算值冒充历史（#4308 同族纪律）。</p>
     */
    private BigDecimal storedProcessingFee(Object processingInfo) {
        ProcessingFeeCalculator.Fee fee = ProcessingFeeCalculator.storedFee(processingInfo);
        return fee == null ? BigDecimal.ZERO : fee.lineAmount();
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
            // SKU 身份兜底（issue #7219）：存量/回归单的 processing_info 可能没有
            // colorName/doorWidth（纸面与详情都读这两个键 ⇒ 颜色/门幅恒空）。
            // 只在**缺值**且能从 SKU 唯一确定时回填；多 SKU 且无 skuId ⇒ 不猜（宁可留空）。
            Map<String, Object> skuInfo = toSkuIdentityMap(item.getProcessingInfo());
            if (skuInfo != null && (!hasText(skuInfo.get("colorName")) || !hasText(skuInfo.get("doorWidth")))) {
                List<ProductSku> skus = productSkuMapper.selectList(
                        new LambdaQueryWrapper<ProductSku>().eq(ProductSku::getProductId, item.getProductId()));
                response.setProcessingInfo(backfillSkuIdentity(skuInfo, skus, item.getProductName()));
            }
        }
        return response;
    }


    /** 把 processing_info 归一成可改写的 Map（JSONB 经 JacksonTypeHandler 可能是 String/其它形态）。 */
    @SuppressWarnings("unchecked")
    static Map<String, Object> toSkuIdentityMap(Object raw) {
        if (!(raw instanceof Map<?, ?> map)) return null;
        Map<String, Object> copy = new LinkedHashMap<>();
        for (Map.Entry<?, ?> e : map.entrySet()) copy.put(String.valueOf(e.getKey()), e.getValue());
        return copy;
    }


    private static boolean hasText(Object value) {
        return value instanceof String text && !text.isBlank();
    }


    /**
     * SKU 身份兜底（issue #7219）—— **纯函数**，判据见 {@code OrderServiceSkuBackfillTest}。
     *
     * <p>口径：① 两个键都有 ⇒ 原样返回（**不覆盖**既有快照）；② {@code skuId} 命中 ⇒ 用那个 SKU；
     * ③ 没有 skuId 但商品**只有一个 SKU** ⇒ 用唯一 SKU；④ 多 SKU 且产品名以
     * {@code -颜色-门幅} 结尾、**唯一命中**一个 SKU ⇒ 用它（历史/回归单的既有命名形态）；
     * ⑤ 其余（无法唯一判定）⇒ 原样返回，**不猜**（猜错比空更贵：纸面会把 A 的颜色印到 B 的行上）。
     * 只补**缺的那一半**。</p>
     */
    static Map<String, Object> backfillSkuIdentity(Map<String, Object> info, List<ProductSku> skus, String productName) {
        if (info == null) return null;
        boolean hasColor = hasText(info.get("colorName"));
        boolean hasWidth = hasText(info.get("doorWidth"));
        if (hasColor && hasWidth) return info;
        List<ProductSku> rows = skus == null ? List.of() : skus;
        ProductSku picked = null;
        Object rawSkuId = info.get("skuId");
        if (rawSkuId != null && !String.valueOf(rawSkuId).isBlank()) {
            String skuId = String.valueOf(rawSkuId);
            picked = rows.stream()
                    .filter(sku -> sku.getId() != null && String.valueOf(sku.getId()).equals(skuId))
                    .findFirst().orElse(null);
        }
        if (picked == null && rows.size() == 1) picked = rows.get(0);
        // ③ 多 SKU 的历史单：产品名常以「-颜色-门幅」结尾（下单工具/人工命名的既有形态）——
        //    后缀**唯一命中**才采用；零命中/多命中一律不猜（猜错 = 把 A 的颜色印到 B 的行上）。
        if (picked == null && productName != null && !productName.isBlank()) {
            String name = productName.trim();
            List<ProductSku> suffixHits = rows.stream()
                    .filter(sku -> hasText(sku.getColorName()) && hasText(sku.getDoorWidth())
                            && name.endsWith("-" + sku.getColorName() + "-" + sku.getDoorWidth()))
                    .toList();
            if (suffixHits.size() == 1) picked = suffixHits.get(0);
        }
        if (picked == null) return info;
        Map<String, Object> merged = new LinkedHashMap<>(info);
        if (!hasColor && hasText(picked.getColorName())) merged.put("colorName", picked.getColorName());
        if (!hasWidth && hasText(picked.getDoorWidth())) merged.put("doorWidth", picked.getDoorWidth());
        return merged;
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
    String resolveOrderIdToUuid(String raw, Long tenantId) {
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
