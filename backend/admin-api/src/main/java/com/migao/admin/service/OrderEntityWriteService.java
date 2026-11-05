package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.dto.FollowStatusResponse;
import com.migao.admin.dto.OrderContentUpdateRequest;
import com.migao.admin.dto.OrderCreateRequest;
import com.migao.admin.dto.OrderDetailResponse;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import com.migao.admin.time.BusinessClock;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeParseException;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;

/**
 * 订单<b>实体写面</b>（issue #8681，P2-1e 第七批）：{@code deleteOrder} / {@code addRemark} /
 * {@code bindOrdersToUser} / {@code updateFollowStatus} / {@code getFollowStatus} /
 * {@code updateUrgency} / {@code updatePendingOrderContent} 的唯一实现点。
 *
 * <p><b>为什么是一族</b>：这七个入口都直接对 {@code orders} 行（及其消费的明细行）做<b>定点列写</b>
 * —— 删单、备注、手机号回填、跟进状态读写、加急 / 到货日、待付款内容编辑。它们的共同约束不是业务
 * 流程，而是「<b>只写本方法负责的列</b>」（issue #6955 的整实体回写回滚并发状态那类缺陷）与
 * 「状态闸门走 {@link OrderStatusTransitions} 唯一实现点」。放在同一处，写面口径只有一份。</p>
 *
 * <h3>搬运口径（行为 diff = 0）</h3>
 * <ul>
 *   <li><b>方法体逐字节搬运</b>：六个方法（删单 / 备注 / 手机号回填 / 跟进状态 / 加急 / 内容编辑）的方法体
 *       原样搬入，唯一改动是<b>内容编辑</b>里 7 处共享部件改经传入的门面实参调用
 *       （{@code assertItemAmountsValid} / {@code priceItems} / {@code computeItemsTotal} /
 *       {@code syncProcessingFeeCombinations} / {@code validateStockSufficientForItems} /
 *       {@code normalizeInstallRooms} / {@code persistOrderItems}）与 1 处回读
 *       （{@code orderService.queryService().getOrderById}）—— 这些是<b>建单与改单共用</b>的唯一实现点，
 *       仍留 {@link OrderService}（不重搭第二份口径）。</li>
 *   <li><b>事务注解逐字跟着方法走</b>：{@code updatePendingOrderContent} / {@code deleteOrder} /
 *       {@code updateFollowStatus} / {@code updateUrgency} / {@code addRemark} 的
 *       {@code @Transactional(rollbackFor = Exception.class)} 原样搬入；
 *       {@code bindOrdersToUser} / {@code getFollowStatus} 本来就没有事务注解，搬入后也没有。</li>
 *   <li><b>跟进状态读写同址</b>（第五批登记的返工点）：读面 {@code getFollowStatus} 从
 *       {@link OrderStatsService} 合并回本类 —— 第五批把读搬走、写留门面，导致同一语义分处两个文件；
 *       本批把写搬到这里后，读写<b>同址收口</b>，不留第二份口径。</li>
 * </ul>
 *
 * <p><b>看管</b>：门面的同名声明已删除且不许回来（{@code OrderFacadeForwarderRetirementTest} 的退休面 +
 * 具名消费方清单 + 驱动面）；{@code OrderUrgencyFieldsTest} 的源码级断言载体改为本类；
 * 加急红证机具 {@code scripts/order-urgency-red-proof.py} 的被测源同步改到本类。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class OrderEntityWriteService {

    private final OrderMapper orderMapper;
    private final OrderItemMapper orderItemMapper;
    private final ProcessingOrderMapper processingOrderMapper;
    private final ObjectMapper objectMapper;
    private final UserService userService;
    private final AuditLogService auditLogService;
    /** 业务时钟：备注时间戳的唯一时间源（不取系统时钟，单测可注入）。 */
    private final BusinessClock businessClock;

    /**
     * 池化事件通知点（issue #5182 挂载点 ③-a）：{@code updateUrgency} 完成之后的一句 fail-soft 通知。
     *
     * <p>字段注入（不扩构造签名），理由同门面 / {@link OrderLifecycleService}：
     * {@code null}（单测切片）⇒ 跳过并留痕。</p>
     */
    @Autowired(required = false)
    private PoolChangeNotifier poolChangeNotifier;

    /**
     * 非 Spring 装配（{@code new OrderService(...)} / {@code @InjectMocks} 的既有单测）下，
     * 门面就地构造本类时把它**当时**持有的可选协作者带过来 —— 让「测试里字段注入的替身」
     * 与拆分前一样生效（生产装配下由 Spring 直接注入该字段，本方法不会被调用）。
     */
    void adoptOptionalCollaborators(PoolChangeNotifier notifier) {
        this.poolChangeNotifier = notifier;
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
     * **待付款订单内容编辑**（issue #5842；用户 2026-10-01 裁定「范围 = 全改」）。
     *
     * <p>可改三面：收货信息 / 商品明细（商品·数量·单价·宽高）/ 加工项；金额**一律服务端重算**。</p>
     *
     * <h3>六道判据（缺一条都会静默出错）</h3>
     * <ol>
     *   <li><b>状态闸门</b>：只有 {@code pending} 可改，其余 **422** —— 判定走
     *       {@link OrderStatusTransitions#assertContentEditable}（状态机唯一实现点）；</li>
     *   <li><b>已有加工单 ⇒ 拒绝</b>：内容已固化进加工单快照，改订单会让快照漂移。
     *       （发货侧还有第二道 —— {@link OrderShipGuard#hasProcessingDrift} —— 两处都留，
     *       因为"编辑与生成不会同时发生"是一个**没有判据的时序假设**。）</li>
     *   <li><b>金额重算</b>：{@code totalAmount} 由服务端按新明细 + 新加工项重算
     *       （{@link #computeItemsTotal}），随后照建单同口径校验
     *       「应收 − 优惠 ≈ 实收（容差 0.01）」；</li>
     *   <li><b>库存前置校验按新明细重跑</b>（{@code validateStockSufficientForItems}，与确认支付同一套
     *       SKU 匹配）：{@code pending} 单**尚未扣库存**（扣减发生在确认支付）⇒
     *       <b>不回滚库存</b>，但必须保证「改完仍买得起」；</li>
     *   <li><b>明细整体替换</b>：旧行软删（{@code @TableLogic}）+ 新行落库，落库走与建单**同一份**
     *       {@link #persistOrderItems}；</li>
     *   <li><b>审计留痕</b>：前后快照（{@link #contentSnapshot}）写 {@code audit_logs}
     *       （{@code action=update_content} / {@code resourceType=order}）。</li>
     * </ol>
     *
     * <p>⚠️ <b>不回滚库存这件事的前提**在本方法内被显式保证**</b>：状态闸门只放 {@code pending}，
     * 而扣减只发生在 {@code pending → confirmed}（{@link OrderLifecycleService#confirmPayment}）⇒ 走到这里时该单一定没扣过。
     * 若将来放宽可编辑状态，回滚/重算库存必须同批补上（本注释就是那件事的坐标）。</p>
     */
    @Transactional(rollbackFor = Exception.class)
    public OrderDetailResponse updatePendingOrderContent(String id, OrderContentUpdateRequest request,
                                                        OrderService orderService) {
        Order order = orderMapper.selectById(id);
        if (order == null) {
            throw BusinessException.notFound("订单");
        }
        Long tenantId = order.getTenantId();
        // ① 状态闸门（唯一实现点 = OrderStatusTransitions；其余状态一律 422 + 中文文案）
        OrderStatusTransitions.assertContentEditable(order.getStatus());
        // ② 已生成活跃加工单 ⇒ 内容已固化进快照，拒绝（发货侧另有漂移守卫兜底）
        ProcessingOrder active = processingOrderMapper.selectActiveByOrderId(order.getId(), tenantId);
        if (active != null) {
            throw BusinessException.validationError(String.format(
                    "订单已生成加工单（%s），内容不能再修改；如需改内容请先作废该加工单",
                    active.getProcessingOrderNo()));
        }

        // ③ 新明细：服务端闸门 → 加工费取价 → 总额重算（**不信客户端任何金额**）
        List<OrderCreateRequest.OrderItemRequest> items = toCreateItems(request.getItems());
        orderService.assertItemAmountsValid(items);
        List<ProcessingFeeCalculator.Fee> itemFees = orderService.priceItems(items, tenantId);
        // 金额精度准入（issue #6228）：总额是计算值（"积"），合法单价×合法数量仍可出 3 位小数。
        BigDecimal totalAmount = MoneyScale.requireTwoDecimalsOrNull(orderService.computeItemsTotal(items, itemFees), "订单总额");
        orderService.syncProcessingFeeCombinations(itemFees, tenantId);

        // ④ 优惠 / 实收：未传 ⇒ **沿用原值**（不清零、不猜）；随后照建单同口径校验
        // 金额精度准入（issue #6228）：只有**请求带来的**值需要准入 —— 沿用值来自库列 NUMERIC(10,2) 回读。
        BigDecimal requestedDiscount = MoneyScale.requireTwoDecimalsOrNull(request.getDiscountAmount(), "优惠金额");
        BigDecimal discountAmount = requestedDiscount != null
                ? requestedDiscount
                : (order.getDiscountAmount() != null ? order.getDiscountAmount() : BigDecimal.ZERO);
        if (discountAmount.compareTo(BigDecimal.ZERO) < 0) {
            throw BusinessException.validationError("优惠金额不能为负数");
        }
        BigDecimal requestedActual = MoneyScale.requireTwoDecimalsOrNull(request.getActualAmount(), "实收金额");
        BigDecimal actualAmount = requestedActual != null
                ? requestedActual
                : (order.getActualAmount() != null
                        ? order.getActualAmount()
                        : totalAmount.subtract(discountAmount));
        BigDecimal expected = totalAmount.subtract(discountAmount);
        if (expected.subtract(actualAmount).abs().compareTo(new BigDecimal("0.01")) > 0) {
            throw BusinessException.validationError(String.format(
                    "实收金额与应收不一致：应收 %s - 优惠 %s = %s，实收 %s（容差 0.01）",
                    totalAmount, discountAmount, expected, actualAmount));
        }

        // ⑤ 前置库存校验**按新明细重跑**（与建单/确认支付共用 validateStockSufficientForItems）。
        //    `pending` 未扣库存 ⇒ 无需回滚，但"改完还买得起"必须现在成立。
        orderService.validateStockSufficientForItems(draftItems(items), "修改订单");

        // ⑥ 审计留痕：改动前快照（下一行起 order 对象就被就地改写了）
        //   明细取一次复用：「安装小区」的「未传 = 沿用原值」要靠改动前的行（见下方 ⑧）。
        List<OrderItem> existingItems = loadOrderItems(order.getId(), tenantId);
        Map<String, Object> before = contentSnapshot(order, existingItems);
        // 安装信息（issue #7856）：归一 + 准入同样**在任何写之前**（⑦ 的订单更新 / ⑧ 的明细替换都不落半成品）
        String installCommunity = resolveUpdatedInstallCommunity(request.getInstallCommunity(), existingItems);
        orderService.normalizeInstallRooms(items);

        // ⑦ 落库：收货信息 + 三金额
        orderMapper.update(null, new LambdaUpdateWrapper<Order>()
                .eq(Order::getId, order.getId())
                .set(Order::getCustomerName, request.getCustomerName())
                .set(Order::getCustomerPhone, request.getCustomerPhone())
                .set(Order::getCustomerAddress, request.getCustomerAddress())
                .set(Order::getTotalAmount, totalAmount)
                .set(Order::getDiscountAmount, discountAmount)
                .set(Order::getActualAmount, actualAmount));

        // ⑧ 明细整体替换：旧行**软删**（@TableLogic）后按新明细落库（与建单同一份 persistOrderItems）
        orderItemMapper.delete(new LambdaQueryWrapper<OrderItem>().eq(OrderItem::getOrderId, order.getId()));
        // 改单路径不做服务端定价（改价属于 P1-2 审批面）：传 null ⇒ 不写定价依据列
        // 安装小区（issue #7856）：**未传 ⇒ 沿用原值**（改动前明细第一条非空），传空串 ⇒ 清空；
        // 与 discountAmount / actualAmount 的「未传 = 不改、不猜、不清零」同一口径
        // （明细被**整体替换** ⇒ 不沿用就会在「只想改收货地址」时静默抹掉安装小区）。
        orderService.persistOrderItems(order, items, itemFees, tenantId, null, installCommunity);

        recordContentEditAudit(order, before,
                contentSnapshot(orderMapper.selectById(order.getId()), loadOrderItems(order.getId(), tenantId)));
        log.info("订单内容已修改: id={}, orderNo={}, totalAmount={}, 明细 {} 行",
                order.getId(), order.getOrderNo(), totalAmount, items.size());
        return orderService.queryService().getOrderById(order.getId());
    }

    /**
     * 编辑请求的明细 → 建单行类型（**共用下游所有写面部件**的前提）。
     *
     * <p>为什么不给编辑另造一套行类型：加工项取价 / 行要素物化 / 整卷分配 / 库存校验全部以
     * {@code OrderCreateRequest.OrderItemRequest} 为输入 —— 另造一套就要把这些部件复制一遍
     * （issue #5842 的口径是「加工项写侧与建单**同源**」）。</p>
     *
     * <p>{@code subtotal} 在此**由服务端算出**（编辑 DTO 没有该字段）⇒
     * {@code resolveItemSubtotal} 拿到的一定是服务端值，客户端无从影响。</p>
     */
    private List<OrderCreateRequest.OrderItemRequest> toCreateItems(List<OrderContentUpdateRequest.Item> items) {
        List<OrderCreateRequest.OrderItemRequest> result = new ArrayList<>(items.size());
        for (OrderContentUpdateRequest.Item source : items) {
            OrderCreateRequest.OrderItemRequest target = new OrderCreateRequest.OrderItemRequest();
            target.setProductId(source.getProductId());
            target.setProductName(source.getProductName());
            target.setQuantity(source.getQuantity());
            target.setUnitPrice(source.getUnitPrice());
            target.setWidth(source.getWidth());
            target.setHeight(source.getHeight());
            target.setProcessingInfo(source.getProcessingInfo());
            // 安装位置（issue #7856）：改单请求的**件级**字段同样接到建单行类型上 ——
            // 下游写面只有一份（persistOrderItems），两处各搬一遍迟早分叉。
            target.setInstallRoom(source.getInstallRoom());
            target.setSellingMethod(source.getSellingMethod());
            if (source.getUnitPrice() != null && source.getQuantity() != null) {
                target.setSubtotal(source.getUnitPrice().multiply(source.getQuantity()));
            }
            result.add(target);
        }
        return result;
    }

    /**
     * 编辑请求的明细 → 库存校验用的**草稿明细**（不落库；与建单的 {@code validateStockSufficientForRequest}
     * 同一形状 —— 只带 SKU 匹配需要的三样：productId / productName / quantity / processingInfo）。
     */
    private List<OrderItem> draftItems(List<OrderCreateRequest.OrderItemRequest> items) {
        List<OrderItem> draftItems = new ArrayList<>(items.size());
        for (OrderCreateRequest.OrderItemRequest itemRequest : items) {
            OrderItem draft = new OrderItem();
            draft.setProductId(itemRequest.getProductId());
            draft.setProductName(itemRequest.getProductName());
            draft.setQuantity(itemRequest.getQuantity());
            draft.setProcessingInfo(itemRequest.getProcessingInfo());
            draftItems.add(draft);
        }
        return draftItems;
    }

    /**
     * 加载订单明细（走 BaseMapper，确保 processing_info 经 JacksonTypeHandler 反序列化为 Map）。
     * 与 getOrderById 的既有约定一致（见查询明细处的注释）。
     */
    private List<OrderItem> loadOrderItems(String orderId, Long tenantId) {
        return OrderShipGuard.loadOrderItems(orderItemMapper, orderId, tenantId);
    }

    /**
     * 订单内容快照（**审计留痕**的前后差异载体，issue #5842）。
     *
     * <p>只记「人可复核、且改动会影响下游」的字段：收货三件套 / 三个金额 / 逐行
     * 商品名 + 数量 + 单价 + 宽高 + **加工项名**。刻意不整对象序列化 —— 审计读面是给人看的，
     * 倒进整个实体只会让真正的差异被淹没。</p>
     */
    private Map<String, Object> contentSnapshot(Order order, List<OrderItem> items) {
        Map<String, Object> snapshot = new LinkedHashMap<>();
        snapshot.put("customerName", order.getCustomerName());
        snapshot.put("customerPhone", order.getCustomerPhone());
        snapshot.put("customerAddress", order.getCustomerAddress());
        snapshot.put("totalAmount", order.getTotalAmount());
        snapshot.put("discountAmount", order.getDiscountAmount());
        snapshot.put("actualAmount", order.getActualAmount());
        List<Map<String, Object>> lines = new ArrayList<>();
        for (OrderItem item : items) {
            Map<String, Object> line = new LinkedHashMap<>();
            line.put("productName", item.getProductName());
            line.put("quantity", item.getQuantity());
            line.put("unitPrice", item.getUnitPrice());
            line.put("width", item.getWidth());
            line.put("height", item.getHeight());
            line.put("processingItems", OrderShipGuard.extractProcessingItems(objectMapper, item.getProcessingInfo())
                    .stream().map(OrderDetailResponse.ProcessingItemBrief::getName).collect(Collectors.toList()));
            lines.add(line);
        }
        snapshot.put("items", lines);
        return snapshot;
    }

    /**
     * 内容更新时「安装小区」的取值（issue #7856）。
     *
     * <p>{@code null}（未传）⇒ **沿用原值**（改动前明细第一条非空）；空白 ⇒ **清空**；
     * 其余 ⇒ 归一 + 准入（≤40 字，超长 422）。与 {@code discountAmount} / {@code actualAmount}
     * 的「未传 = 不改」同一口径 —— 明细是**整体替换**，不沿用就会在「只改收货地址」时静默抹掉安装小区。</p>
     */
    private String resolveUpdatedInstallCommunity(String requested, List<OrderItem> existingItems) {
        if (requested == null) {
            return OrderInstallInfo.firstCommunity(existingItems, objectMapper);
        }
        return OrderInstallInfo.normalizeCommunity(requested);
    }

    /**
     * 内容编辑的审计留痕（issue #5842）：{@code action=update_content} / {@code resourceType=order}
     * + **前后差异**。操作者取不到（无认证 / 服务占位身份）⇒ 两个身份字段留空，
     * 但**留痕本身照写**（审计的意义是"改过"，不是"谁改的"都有答案 —— 后者留空可见）。
     */
    private void recordContentEditAudit(Order order, Map<String, Object> before, Map<String, Object> after) {
        Map<String, Object> details = new LinkedHashMap<>();
        details.put("before", before);
        details.put("after", after);
        Long tenantId = order.getTenantId();
        UserService.CurrentOperator operator = userService.resolveCurrentOperator();
        auditLogService.recordLog(tenantId,
                operator != null ? operator.userId() : null,
                operator != null ? operator.displayName() : null,
                "update_content", "order", null,
                order.getId(), order.getOrderNo(), details, null, null);
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
        if (!OrderStatusTransitions.PENDING.equals(order.getStatus())) {
            throw BusinessException.validationError("仅允许删除待确认状态的订单，当前状态: " + order.getStatus());
        }

        // issue #7633：已生成**活跃作业单** ⇒ 拒绝删除，否则作业单悬挂、作业看板对已删父订单扇出 404。
        // 口径与 updatePendingOrderContent 同源（同一 selectActiveByOrderId：未软删 + 非 cancelled + 同租户）；
        // 待付款订单自 #7626 起也能先生成作业单 ⇒ 这道闸是「删单前必须先作废作业单」。
        // 订单**不做物理删除**（deleteById 走 @TableLogic 软删，语义未改）；本闸只给出口、不给旁路。
        ProcessingOrder active = processingOrderMapper.selectActiveByOrderId(order.getId(), order.getTenantId());
        if (active != null) {
            throw BusinessException.validationError(String.format(
                    "订单已生成作业单（%s），不能删除；请先作废该作业单", active.getProcessingOrderNo()));
        }

        // 逻辑删除订单
        // issue #6956 · 现象 C：判影响行数（并发双删只许一次成功；0 行 = 已被别人删掉）
        if (orderMapper.deleteById(id) == 0) {
            throw BusinessException.notFound("订单");
        }

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
        // 🔴 只写本方法负责的列（issue #6955）：修前是 orderMapper.updateById(order) —— 整实体回写会把
        // selectById 时读到的**旧 status 一并写回** ⇒ 静默回滚并发的状态变更（F1 的类级根因）。
        orderMapper.update(null, new LambdaUpdateWrapper<Order>()
                .eq(Order::getId, order.getId())
                .set(Order::getFollowStatus, followStatus));
        log.info("更新跟进状态成功: id={}, followStatus={}", id, followStatus);
    }

    /**
     * 获取订单跟进状态（issue #8681：随写面 {@code updateFollowStatus} 从 {@link OrderStatsService}
     * 合并回同一处 —— 读写同址，不留第二份口径；方法体与口径逐字节未变）。
     */
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
     * 更新订单级**加急标记 / 客户要求到货日**（V120，issue #5177 的「改单」半边）。
     *
     * <h2>三态语义（与 {@link OrderUrgencyUpdateRequest} 逐字同源，不在两处各写一份）</h2>
     * 每个字段各自「不传 = 不改」；{@code requiredDeliveryDate} 传**空串**才表示清空
     * （{@code null} 与 {@code ""} 必须是两件事，否则「只改加急」会把到货日静默抹掉）。
     *
     * <h2>为什么用 {@code LambdaUpdateWrapper} 而不是 {@code updateById(order)}</h2>
     * 本仓既有的改单写法是「{@code selectById} → 改实体 → {@code updateById(order)}」，但
     * MyBatis-Plus 默认字段策略是 {@code NOT_NULL} ⇒ **null 字段不进 SET** ⇒ 用那条路
     * **永远清不掉**到货日（「清空」会静默变成「不改」，而界面显示已清空）。
     * ⇒ 清空必须走显式 {@code set(col, null)}；{@code updatedAt} 也随之**显式**写
     * （{@code update(entity, wrapper)} 的自动填充不在本路径上，不写它就留下陈旧时间戳）。
     *
     * <p>🔴 <b>只写这两列</b>：不碰金额、状态、售后工单的任何字段
     * （判据 1 零联动 / 判据 6 不损失客户）。</p>
     *
     * @param isUrgent                  {@code null} = 不改；否则显式设值（{@code false} 是「取消加急」的真值）
     * @param requiredDeliveryDateRaw   {@code null} = 不改；{@code ""} = 清空；{@code YYYY-MM-DD} = 设值；其它 ⇒ 422
     */
    @Transactional(rollbackFor = Exception.class)
    public void updateUrgency(String id, Boolean isUrgent, Boolean isOutsourced,
                              String requiredDeliveryDateRaw) {
        Order order = orderMapper.selectById(id);
        if (order == null) {
            throw BusinessException.notFound("订单");
        }
        LambdaUpdateWrapper<Order> update = new LambdaUpdateWrapper<Order>().eq(Order::getId, id);
        boolean changed = false;
        if (isUrgent != null) {
            update.set(Order::getIsUrgent, isUrgent);
            changed = true;
        }
        if (isOutsourced != null) {
            update.set(Order::getIsOutsourced, isOutsourced);
            changed = true;
        }
        if (requiredDeliveryDateRaw != null) {
            update.set(Order::getRequiredDeliveryDate, parseRequiredDeliveryDate(requiredDeliveryDateRaw));
            changed = true;
        }
        if (!changed) {
            // 两个字段都没传 ⇒ 这次改单什么都没改。**显式拒绝**而不是静默 200：
            // 静默成功会让调用方以为改动生效了（同族纪律：不静默）。
            throw BusinessException.validationError(
                    "isUrgent / isOutsourced / requiredDeliveryDate 至少要传一个（本次改单没有任何变更）");
        }
        update.set(Order::getUpdatedAt, OffsetDateTime.now());
        orderMapper.update(null, update);
        log.info("更新订单生产标记成功: id={}, isUrgent={}, isOutsourced={}, requiredDeliveryDate={}",
                id, isUrgent, isOutsourced, requiredDeliveryDateRaw);
        // 🔴 事件驱动自动成批（issue #5182 挂载点 ③-a）：改单会同时改两件事 ——
        // 加急单**永不入池**（改为加急 ⇒ 立刻单派）、到货日变了 ⇒ 兜底的「最晚派单日」跟着变。
        PoolChangeNotifier.notifySafely(poolChangeNotifier, order.getTenantId(),
                PoolChangeNotifier.TRIGGER_ORDER_UPDATED);
    }

    /**
     * 到货日解析（issue #5177）：{@code ""} ⇒ **清空**（返回 {@code null}）；
     * {@code YYYY-MM-DD} ⇒ 该日期；其它形态 ⇒ **显式拒绝**（不静默回落、不当成清空）。
     *
     * <p>为什么空白串不按「清空」办：{@code "  "} 这种输入更像**误输入**，把它当清空
     * 就是静默丢数据；而 {@code ""} 是调用方**明确**表达的「清空」（前端清空日期框发出的就是它）。</p>
     */
    private static LocalDate parseRequiredDeliveryDate(String raw) {
        if (raw.isEmpty()) {
            return null;
        }
        try {
            return LocalDate.parse(raw.trim(), DateTimeFormatter.ISO_LOCAL_DATE);
        } catch (DateTimeParseException e) {
            throw BusinessException.validationError(
                    "到货日格式不正确：" + raw + "（期望 YYYY-MM-DD，或传空串清空到货日）");
        }
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
        String timestamp = businessClock.now()
                .format(java.time.format.DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm"));
        String remarkEntry = "[" + timestamp + "] " + content;
        String existing = order.getRemark() != null ? order.getRemark() : "";
        String merged = existing.isEmpty() ? remarkEntry : existing + "\n" + remarkEntry;
        // 🔴 只写 remark（issue #6955）：修前是 orderMapper.updateById(order) —— 整实体回写会把
        // selectById 时读到的**旧 status 一并写回** ⇒ 静默回滚并发的状态变更（F1 的类级根因）。
        orderMapper.update(null, new LambdaUpdateWrapper<Order>()
                .eq(Order::getId, order.getId())
                .set(Order::getRemark, merged));
        log.info("添加订单备注成功: id={}", id);
    }
}
