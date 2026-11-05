package com.migao.admin.service;

import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.entity.OrderLogistics;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderLogisticsMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import com.migao.admin.time.BusinessClock;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.baomidou.mybatisplus.core.conditions.update.UpdateWrapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 订单<b>生命周期族</b>（issue #8191，P2-1d）：**取消 / 退款 / 发货 / 状态流转**的唯一实现点。
 *
 * <p><b>为什么是一族</b>：这四族共享同一份状态机（{@link OrderStatusTransitions}）与同一条
 * 原子状态写面（{@link #transitionStatusAtomic}）。把它们拆到不同类里，就等于让「谁能改
 * {@code orders.status}」这件事散成多份 —— 而 {@code orders.status} 的写面台账
 * （{@code tests/unit_ci_workflows/state_write_face_ledger.json}）与
 * 「{@code shipped} 写点必须同写 {@code shipped_at}」的守卫（{@code OrderAutoCompleteSqlGuardTest} /
 * {@code ShipmentInvariantGuardTest}）都按**文件**登记载体：载体越散，判据越容易「看不见」。</p>
 *
 * <h3>搬运口径（行为 diff = 0）</h3>
 * <ul>
 *   <li><b>方法体逐字节搬运</b>：除下面三条具名的跨类限定外，一个字都没改 ——
 *       判据 = {@code OrderLifecycleSliceSourceIdentityTest}（基线 sha256 钉死）；</li>
 *   <li><b>事务注解逐字跟着方法走</b>：{@code updateOrderStatus} / {@code confirmPayment} /
 *       {@code cancelOrder} / {@code refundOrder} / {@code shipWithLogistics(4 参)} 的
 *       {@code @Transactional(rollbackFor = Exception.class)} 原样搬入；门面委托**不加**事务注解
 *       （加了就是嵌套传播语义的变化）；</li>
 *   <li><b>具名的三处跨类限定</b>：① {@code cancelOrder} 里的
 *       {@code batchStock()} → {@code orderSharedParts.batchStock()}（第九批起该访问器住在
 *       {@link OrderSharedParts}，与共享部件族同址；本类对它<b>唯一</b>的用法就是它）；
 *       ② {@code updateOrderStatus} 内部自调用 {@code cancelOrder(id, null)} 增补第三参；
 *       ③ {@code OrderShipmentOutcome} 仍声明在门面（公开类型名 {@code OrderService.OrderShipmentOutcome}
 *       被调用方逐字引用）⇒ 构造点加类名限定。</li>
 *   <li><b>库存 / 财务流水不搬第二份</b>：{@link OrderStockService} / {@link OrderFeeSupport} 仍是
 *       唯一实现点；本类只保 6 个同名私有转发（与门面的同名方法一一对应），目的是让搬入的方法体
 *       逐字节不变。</li>
 * </ul>
 *
 * <p><b>第三参（issue #8681，P2-1e 第九批）</b>：{@code updateOrderStatus} / {@code cancelOrder} 的第三参
 * 从<b>门面实例</b>换成 {@link OrderSharedParts} —— 本类对它唯一的用法是 {@code batchStock()}；
 * 门面实例不再进入这条调用链。{@code applyRollAllocation} / 建单改单 / 删单等族各自另有归属。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class OrderLifecycleService {

    private final OrderMapper orderMapper;
    private final OrderItemMapper orderItemMapper;
    private final OrderLogisticsMapper orderLogisticsMapper;
    private final ProcessingOrderMapper processingOrderMapper;
    private final ObjectMapper objectMapper;
    private final NotificationService notificationService;
    private final UserService userService;
    /** 库存与销量族**唯一实现点**（issue #8191，P2-1c）：本类只调用，不复制口径。 */
    private final OrderStockService orderStockService;
    /** 财务流水族**唯一实现点**（issue #8191，P2-1c）：本类只调用，不复制口径。 */
    private final OrderFeeSupport orderFeeSupport;
    /** 业务时钟：{@code shipped_at / paid_at / received_at} 三个锚点的唯一时间源。 */
    private final BusinessClock businessClock;

    /**
     * 池化事件通知点（issue #5182）：**既有业务完成之后**追加的一句 fail-soft 通知。
     *
     * <p>字段注入（不扩构造签名），理由同门面里的同名字段：{@code null}（单测切片）⇒ 跳过并留痕。</p>
     */
    @Autowired(required = false)
    private PoolChangeNotifier poolChangeNotifier;

    /**
     * 单据联动工序（issue #7165）：字段注入理由同上；{@code null}（单测切片）⇒ 跳过联动，
     * 发货守卫行为不变。
     */
    @Autowired(required = false)
    private DocumentOperationLinkage documentOperationLinkage;

    /** 订单状态 → 中文业务术语（错误消息用）——**唯一取值载体**在 {@link OrderStatusTransitions}。 */
    private static final Map<String, String> ORDER_STATUS_LABELS = OrderStatusTransitions.ORDER_STATUS_LABELS;

    /**
     * 非 Spring 装配（{@code new OrderService(...)} / {@code @InjectMocks} 的既有单测）下，
     * 门面就地构造本类时把它**当时**持有的两个可选协作者带过来 —— 让「测试里字段注入的替身」
     * 与拆分前一样生效（生产装配下由 Spring 直接注入上面两个字段，本方法不会被调用）。
     */
    void adoptOptionalCollaborators(PoolChangeNotifier notifier, DocumentOperationLinkage linkage) {
        this.poolChangeNotifier = notifier;
        this.documentOperationLinkage = linkage;
    }

    // ── 库存 / 财务流水的同名转发（唯一实现点仍在两个新服务里；只为搬入的方法体逐字节不变）

    private void validateStockSufficient(Order order) {
        orderStockService.validateStockSufficient(order);
    }

    private void deductStockAndIncreaseSales(String orderId) {
        orderStockService.deductStockAndIncreaseSales(orderId);
    }

    private void restoreStockAndDecreaseSales(String orderId) {
        orderStockService.restoreStockAndDecreaseSales(orderId);
    }

    private BigDecimal effectiveActualAmount(Order order) {
        return orderFeeSupport.effectiveActualAmount(order);
    }

    private void recordFinanceTransaction(Order order, String type, String remark) {
        orderFeeSupport.recordFinanceTransaction(order, type, remark);
    }

    private void recordFinanceTransaction(Order order, BigDecimal amount, String type, String remark) {
        orderFeeSupport.recordFinanceTransaction(order, amount, type, remark);
    }


    /**
     * <b>测试探针</b>（issue #6955，生产恒为 {@code 0}）：在 {@link #cancelOrder} 的「读判加工单为
     * {@code generated}」之后、「联动作废（CAS）」之前暂停指定毫秒。
     *
     * <p><b>为什么需要它</b>：窗口在服务方法体内，测试侧无法在「已判定加工单仍是 generated、
     * 尚未落库」那一刻插进延时（除非 mock 掉真 mapper —— 那会把唯一的 DB 原子判据换成 mock 的恒真返回）。
     * 与 {@code InboundOrderService#setCancelProbePauseMillisForTest}（#6928）逐字同款；
     * 只在包内可见（{@code ProcessingOrderStatusCasRaceRealDbTest} 与生产同类同包）。</p>
     */
    static void setCancelOrderPoProbePauseMillisForTest(long millis) {
        CANCEL_ORDER_PO_PROBE_PAUSE_MILLIS = millis;
    }

    /** 探针时长（默认 0 = 不暂停）；见 {@link #setCancelOrderPoProbePauseMillisForTest}。 */
    private static volatile long CANCEL_ORDER_PO_PROBE_PAUSE_MILLIS = 0L;

    /** 探针**正在**暂停窗口内的信号（测试用它把两个线程钉在确定的时序上）。 */
    private static volatile boolean cancelOrderPoProbePaused = false;

    /** 测试观察点：探针是否已进入暂停窗口；生产不读。 */
    static boolean cancelOrderPoProbePausedForTest() {
        return cancelOrderPoProbePaused;
    }

    /** 测试观察点：当前注入的探针时长；生产不读。 */
    static long cancelOrderPoProbeMillisForTest() {
        return CANCEL_ORDER_PO_PROBE_PAUSE_MILLIS;
    }

    /** 进入窗口 ⇒ 置位 → 停 → 清位。 */
    private static void pauseCancelOrderPoForProbe(long millis) {
        cancelOrderPoProbePaused = true;
        try {
            Thread.sleep(millis);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        } finally {
            cancelOrderPoProbePaused = false;
        }
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
    public void updateOrderStatus(String id, String status, OrderSharedParts orderSharedParts) {
        Order order = orderMapper.selectById(id);
        if (order == null) {
            throw BusinessException.notFound("订单");
        }

        // 状态值 + 流转合法性：**唯一实现** = OrderStatusTransitions（issue #5648 抽出）。
        // 抽出的理由不是"好看"：本单新增了**第三条**发货路（工人可达面
        // OrderShipmentService），两条路各写一张流转表 ⇒ 迟早分叉成
        // 「工人能走的流转商家走不了」（或反过来：非法流转在某一条路上被放过）。
        String currentStatus = order.getStatus();
        OrderStatusTransitions.assertTransitionAllowed(currentStatus, status);

        // 加工单联动守卫（issue #3340）：含加工项订单必须完成加工单后才能发货，
        // 防止加工环节被 confirmed→shipped 直跳绕过
        if (OrderStatusTransitions.SHIPPED.equals(status)) {
            // issue #7165：商家/生产端发货（无工人身份）⇒ 完成「发货」工序但不计件；再走守卫
            if (documentOperationLinkage != null) {
                documentOperationLinkage.completeShippingOperations(order, null, order.getTenantId());
            }
            assertProcessingCompletedBeforeShip(order);
        }

        // 统一走带库存/销量副作用的路径，避免与 confirmPayment/cancelOrder 逻辑不一致
        if (OrderStatusTransitions.CONFIRMED.equals(status)) {
            confirmPayment(id);
        } else if (OrderStatusTransitions.CANCELLED.equals(status)) {
            cancelOrder(id, null, orderSharedParts);
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
     * <p>🔴 {@code newStatus = shipped} 时**同一条 UPDATE** 里写 {@code shipped_at}
     * （issue #6262，V148）：它是「发货后 N 天自动完成」定时腿的判定锚点，而锚点必须
     * <b>与状态流转同一个原子动作</b>——分两条语句写就会造出「状态是 shipped 而发货时刻为空」
     * 的静默漏单形态（那条腿按「满 N 天」取行，NULL 不满足任何比较 ⇒ 永不完成）。
     * 商家侧三条发货入口（{@code PUT /orders/{id}/status} / {@code order_manage(update_logistics)} /
     * {@code shipWithLogistics}）都经本方法 ⇒ 一处写、三条路都写。</p>
     *
     * @return 受影响行数（0 表示订单不存在或状态已并发变更）
     */
    private int transitionStatusAtomic(String id, String expectedStatus, String newStatus, String closeReason) {
        LambdaUpdateWrapper<Order> wrapper = new LambdaUpdateWrapper<>();
        wrapper.eq(Order::getId, id)
                .eq(Order::getStatus, expectedStatus)
                .set(Order::getStatus, newStatus);
        if (OrderStatusTransitions.SHIPPED.equals(newStatus)) {
            wrapper.set(Order::getShippedAt, businessClock.nowOffset());
        }
        // issue #7078：paid_at 只在 **pending → confirmed**（= 确认收款）这条边上写。
        // 🔴 用 expectedStatus 限定前驱是必须的：本方法还被 **producing → confirmed**
        // （作废加工单退回待发货）复用 —— 那是**回退边**，在那里写会让「支付时间」被一次回退
        // 动作顶成当天（屏幕上看不出异常）。判据 = OrderPaidAndReceivedAtWriteGuardTest
        // （含「摘掉前驱限定 ⇒ 判红」的判别力自证）。
        if (OrderStatusTransitions.CONFIRMED.equals(newStatus) && OrderStatusTransitions.PENDING.equals(expectedStatus)) {
            wrapper.set(Order::getPaidAt, businessClock.nowOffset());
        }
        // issue #7078：received_at = 订单进入 completed 的时刻。completed 在本状态机里没有出边
        // ⇒ 这条边只会走一次、不会覆盖。另一条完成路（发货后 N 天自动完成）**不经**本方法，
        // 在 OrderMapper.autoCompleteShippedOrders 自己的 SQL 里同写（漏写那条腿 = 那批单永远空值）。
        if (OrderStatusTransitions.COMPLETED.equals(newStatus)) {
            wrapper.set(Order::getReceivedAt, businessClock.nowOffset());
        }
        if (closeReason != null && !closeReason.isBlank()) {
            wrapper.set(Order::getCloseReason, closeReason);
        }
        return orderMapper.update(null, wrapper);
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
        int rows = transitionStatusAtomic(id, OrderStatusTransitions.PENDING, OrderStatusTransitions.CONFIRMED, null);
        if (rows == 0) {
            throw BusinessException.validationError("只有待确认状态的订单可以确认支付，订单状态可能已变更");
        }

        // 扣减库存 + 增加销量
        deductStockAndIncreaseSales(id);

        // 登记资金流水（收款）——失败不影响订单主流程
        Order freshOrder = orderMapper.selectById(id);
        recordFinanceTransaction(freshOrder != null ? freshOrder : order, "income", "订单确认收款");
        log.info("确认支付成功: id={}", id);
        // 🔴 事件驱动自动成批（issue #5182 挂载点 ①）：**既有业务全部完成之后**追加的
        // fail-soft 通知点。本方法的既有行为、事务边界与异常语义**逐字不变**
        // —— notifySafely 绝不抛，且真正的评估在提交之后（AFTER_COMMIT）。
        PoolChangeNotifier.notifySafely(poolChangeNotifier, order.getTenantId(),
                PoolChangeNotifier.TRIGGER_ORDER_CONFIRMED);
    }


    /**
     * 发货前置判据（**唯一一份**，issue #3340）：**有需要报工的作业**的订单（含加工项，或有卖布行 ——
     * issue #7079）必须已有完成作业单才允许发货。
     *
     * <p>{@link #assertProcessingCompletedBeforeShip} 是它的抛异常外壳（发货路径用）；
     * 生产待办的「待发货」也读它（issue #5641）—— 两处各写一份必然漂移。</p>
     *
     * @return {@code true} = 允许发货（无需要报工的作业，或作业单已完成）；
     *         {@code false} = 被作业单挡住
     */
    public boolean isProcessingReadyForShip(Order order) {
        // #5648 合并后：本体在 OrderShipGuard（单一实现点）—— 工人发货路与生产待办读**同一份**判定。
        return OrderShipGuard.isProcessingReadyForShip(
                orderItemMapper, processingOrderMapper, objectMapper, order);
    }


    /**
     * 加工单联动守卫（issue #3340）：订单含加工项且无已完成加工单时禁止发货。
     * 有加工项订单必须走 producing（生成加工单）→ 加工完成 → shipped，防止加工环节被绕过。
     */
    private void assertProcessingCompletedBeforeShip(Order order) {
        // 判定本体在 OrderShipGuard（issue #5648 抽出，**单一实现点**）：工人可达面的发货端点
        // 走的是同一份判定 —— 复制第二份 = 迟早分叉，而分叉方向是「绕过加工环节就发货」（涉钱）。
        // 合并 #5641 后：`hasProcessingItems` / `isProcessingReadyForShip` 同批改为委托
        // 同一个实现点 ⇒ 「发货前置判据只有一份」这件事在合并后仍然成立（不是两份各让一步）。
        OrderShipGuard.assertProcessingCompletedBeforeShip(
                orderItemMapper, processingOrderMapper, objectMapper, order);
    }


    /**
     * 加工单取消联动（issue #3340）：订单 producing → confirmed 回退。
     * 仅状态回退，无库存副作用（confirmed→producing 本身也无库存副作用）。
     */
    public void revertProducingToConfirmed(String orderId, String reason) {
        int rows = transitionStatusAtomic(orderId, OrderStatusTransitions.PRODUCING, OrderStatusTransitions.CONFIRMED, reason);
        if (rows == 0) {
            throw new BusinessException("ORDER_STATUS_CONFLICT", "订单状态已并发变更，请刷新后重试", 409);
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
    public void cancelOrder(String id, String closeReason, OrderSharedParts orderSharedParts) {
        Order order = orderMapper.selectById(id);
        if (order == null) {
            throw BusinessException.notFound("订单");
        }
        String previousStatus = order.getStatus();
        Set<String> cancellableStatuses = Set.of(OrderStatusTransitions.PENDING, OrderStatusTransitions.CONFIRMED, OrderStatusTransitions.PRODUCING);
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
                // 测试探针（issue #6955）：放大**「读判（订单 + 加工单 generated）」之后、「CAS 落库」之前**
                // 那条窗口（生产恒为 0）。位置是判据的判别力来源：放在读判**之前**时，并发对手会先把
                // 加工单推成 issued ⇒ 本腿的读判直接兜底拒绝、那一步（CAS 只放一个赢家过去）永远测不到。
                // 与 InboundOrderService#setCancelProbePauseMillisForTest（#6928）同款。
                if (CANCEL_ORDER_PO_PROBE_PAUSE_MILLIS > 0) {
                    pauseCancelOrderPoForProbe(CANCEL_ORDER_PO_PROBE_PAUSE_MILLIS);
                }
                // 联动作废 = **条件更新**（issue #6955）：谓词含 id + tenant_id + deleted=0 + 前驱 generated。
                // 修前是 updateById（WHERE 仅主键）⇒ 与并发的「加工单开工」（markStatusIfFrom
                // generated→issued）**不互斥** ⇒ 会出现「订单 cancelled + 加工单 issued」（订单已废、单还在产）。
                // 0 行 ⇒ 加工单已被并发推进 ⇒ 409，**本事务一并回滚**（订单取消不留半成品）。
                int poRows = processingOrderMapper.markStatusIfFrom(activePo.getId(), order.getTenantId(),
                        "generated", "cancelled", null, null, null, null, null,
                        OffsetDateTime.now(), "订单取消，加工单自动作废", OffsetDateTime.now());
                if (poRows == 0) {
                    ProcessingOrder fresh = processingOrderMapper.selectById(activePo.getId());
                    throw BusinessException.conflict(String.format(
                                    "订单已发加工（加工单 %s 状态：%s），请先在订单详情或让黄金策处理加工单后再取消订单",
                                    activePo.getProcessingOrderNo(),
                                    fresh != null ? fresh.getStatus() : activePo.getStatus()),
                            "该加工单刚被另一个操作推进，请刷新后按当前状态重试");
                }
                log.info("订单取消联动作废加工单: po={}, orderId={}", activePo.getProcessingOrderNo(), order.getId());
                // 派工扣减的**对称回补**（V116 / issue #5145 判据 3）：本分支绕过
                // ProcessingOrderService.updateStatus（直接置 cancelled）⇒ 必须在此接同一句话，
                // 否则这条路上批次账只扣不回补。幂等由服务层保证（已回补的行跳过 ⇒ 可重跑）。
                orderSharedParts.batchStock().reverse(order.getTenantId(), activePo.getProcessingOrderNo(),
                        order.getOrderNo(), "订单取消，加工单自动作废，回补批次库存");
            } else {
                throw BusinessException.validationError(String.format(
                        "订单已发加工（加工单 %s 状态：%s），请先在订单详情或让黄金策处理加工单后再取消订单",
                        activePo.getProcessingOrderNo(), activePo.getStatus()));
            }
        }

        // 原子状态流转（以读取到的 previousStatus 为条件，防止并发重复恢复库存）
        int rows = transitionStatusAtomic(id, previousStatus, OrderStatusTransitions.CANCELLED, closeReason);
        if (rows == 0) {
            throw BusinessException.validationError("订单状态已并发变更，请刷新后重试");
        }

        // 已确认/生产中的订单被取消时，恢复库存和销量，并补记退款流水（与 confirmPayment 的 income 对冲）
        if (OrderStatusTransitions.CONFIRMED.equals(previousStatus) || OrderStatusTransitions.PRODUCING.equals(previousStatus)) {
            restoreStockAndDecreaseSales(id);
            BigDecimal remainingRefund = effectiveActualAmount(order).subtract(
                    order.getRefundAmount() != null ? order.getRefundAmount() : BigDecimal.ZERO);
            if (remainingRefund.compareTo(BigDecimal.ZERO) > 0) {
                recordFinanceTransaction(order, remainingRefund, "refund", "订单取消退款");
            }
        }
        log.info("取消订单成功: id={}, reason={}", id, closeReason);
        // 🔴 事件驱动自动成批（issue #5182 挂载点 ③-b）：取消会改变池的候选集
        // （作废加工单已在上面对称回补批次 ⇒ 腾出来的余量可能让别的单凑得满）。
        PoolChangeNotifier.notifySafely(poolChangeNotifier, order.getTenantId(),
                PoolChangeNotifier.TRIGGER_ORDER_CANCELLED);
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
        Set<String> refundableStatuses = Set.of(OrderStatusTransitions.CONFIRMED, OrderStatusTransitions.PRODUCING, OrderStatusTransitions.SHIPPED, OrderStatusTransitions.COMPLETED);
        if (!refundableStatuses.contains(previousStatus)) {
            String previousLabel = ORDER_STATUS_LABELS.getOrDefault(previousStatus, previousStatus);
            throw BusinessException.validationError(
                    "当前状态[" + previousLabel + "]不允许退款，仅已确认/生产中/已发货/已完成可退款");
        }

        BigDecimal actual = effectiveActualAmount(order);
        // 金额精度准入（issue #6221）：退款金额最多 2 位小数（列 NUMERIC(12,2)）。
        // 超位**显式拒绝**（422），不静默取整 —— 否则 `0.001` 会被 PG 舍成 `0.00`：
        // 订单 refund_amount 与资金流水 amount 两处同时归零、refund_at 却已写入（"退了一笔 0 元"）。
        // 口径本体在 MoneyScale（金额链路的单点准入，同 StockQuantity 的范式）；
        // `null` 语义 = 「全额退」，由 OrNull 原样透传（**不得**归一成 0）。
        BigDecimal refund = MoneyScale.requireTwoDecimalsOrNull(refundAmount, "退款金额");
        if (refund == null) {
            refund = actual;
        }
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
    void upsertLogistics(String orderId, String logisticsCompany, String trackingNo, String shipperName,
                                 String logisticsType) {
        // 写入本体在 OrderLogisticsWriter（issue #5648 抽出，**单一实现点**）：工人可达面的发货端点
        // 走的是同一份「存在则更新、否则新建」口径与同一条发货人规则（不复制坑）。
        // 物流类型（issue #8080）：本路此前把这一栏写死 null ⇒ 智能体代客发货只能落列默认 express
        // （「发物流/专线」被静默记成快递）。现在按调用方显式给的值透传；空白 = 本次没说这件事，
        // 由 OrderLogisticsWriter 的「显式才覆盖」保留原值。
        OrderLogisticsWriter.upsert(orderLogisticsMapper, TenantContext.getTenantId(), orderId,
                logisticsCompany, trackingNo,
                new OrderLogisticsWriter.ShippingDetails(shipperName, logisticsType, null),
                userService::resolveCurrentUserDisplayName);
    }


    /**
     * **发货**（issue #4347 §二.2，用户裁定「发货下放到工人扫码端」）：记录物流 + 原子流转 {@code shipped}。
     *
     * <p>与既有 {@code order_manage(update_logistics)} 路径**同一份实现**：本方法只是把
     * 「{@link #upsertLogistics} → {@link #shipOrderIfApplicable}」这对组合**公开**出来，
     * 供工人扫码端调用 —— <b>不复制第二份守卫</b>（守卫在 {@code shipOrderIfApplicable} 里，
     * 与 {@code updateOrderStatus} 路径同源：含加工项订单必须有 completed 加工单）。</p>
     *
     * <p><b>为什么不能只调既有的两个管理端点</b>：{@code PUT /orders/{id}/logistics} 只记物流
     * **不流转状态**，{@code PUT /orders/{id}/status} 只流转**不记单号** ⇒ 工人要发一次货得调两次，
     * 中间失败就是「有单号但没发货」或「发货了没单号」的静默不一致。
     * 发货是**一个动作**，就该是一个原子入口。</p>
     *
     * @param orderId          订单 UUID
     * @param trackingNo       货运单号（**必填** —— 没有单号的「发货」在车间不可核对）
     * @param logisticsCompany 承运商；为空则保留既有值（工人端只填单号，承运商来自客户常用物流档案）
     * @return 本次发货的结果快照（{@code order_id} / {@code status} / {@code tracking_no} /
     *         {@code logistics_company}）＋ 一个**显式**的「本次是否真的发生了 {@code →shipped} 流转」标志
     *         —— <b>幂等回放的载体</b>（issue #6157）：端点拿 {@link OrderService.OrderShipmentOutcome#result()} 当
     *         {@code ClientRequestIdService.complete} 的快照，同键第二次到达时**逐字回放**同一份。
     *         ⚠️ {@code result} **不含实发明细**：发货单由
     *         {@code OrderShipmentService.recordMerchantShipment} 落，调用方按
     *         {@link OrderService.OrderShipmentOutcome#transitioned()} 决定要不要建单（issue #6181）。
     */
    public OrderService.OrderShipmentOutcome shipWithLogistics(String orderId, String trackingNo, String logisticsCompany) {
        return shipWithLogistics(orderId, trackingNo, logisticsCompany, null);
    }


    /**
     * 同上，外加发货页采集的**三个可选字段**（issue #6983）：发货人 / 物流类型 / 发货方式。
     *
     * <p><b>为什么要有这个重载</b>：商家发货页（{@code orders/[id]/ship}）此前走的是
     * 「{@code PUT /logistics} 再 {@code PUT /status}」两步老路 —— 那条路**不建发货单**，
     * 于是 {@code order_shipments} 长期 0 行（issue #6983 的症状）。收敛到原子端点后，
     * 页面本来就在采集的这三件事必须有落点，否则就是「换了端点、丢了一半字段」的静默降级。</p>
     *
     * <h2>「无需物流」（{@code shippingMethod=none}）在这里成立</h2>
     * <p>发货页支持「无需物流」= 不填运单号/承运商（{@code shippingMethod=none} + 空单号）。
     * 本路此前对空单号/空承运商**一律 422**（工人扫码端的口径：「没有单号的发货在车间不可核对」）
     * ⇒ 商家页那个合法形态在原子端点上**结构性不成立**。本重载按 {@code shippingMethod} 分流：
     * {@code none} ⇒ 运单号与承运商都允许为空（都落空串，而不是静默丢弃这次发货）；
     * 其余（{@code logistics} / 缺席 = 工人路与老调用方）⇒ 逐字保留原有两条必填校验。</p>
     *
     * <p><b>白名单 fail-closed（与 {@code OrderController.updateLogistics} 逐字同口径）</b>：
     * {@code shippingMethod} 非空且 ∉ {logistics, none} ⇒ 422 显式拒绝，**不静默兜底**；
     * 缺席 / 空串不拒绝（老调用方根本不发这个键 = 「没这句话」，不是「说了个坏值」）。</p>
     *
     * @param details 发货页采集的可选字段（{@code null} = 一个都没采集）；取值白名单见上
     */
    @Transactional(rollbackFor = Exception.class)
    public OrderService.OrderShipmentOutcome shipWithLogistics(String orderId, String trackingNo, String logisticsCompany,
                                                               OrderLogisticsWriter.ShippingDetails details) {
        String shippingMethod = details == null ? null : details.shippingMethod();
        boolean noLogistics = "none".equals(shippingMethod);
        // 发货方式白名单（issue #6239 的口径，issue #6983 落到本路）：非法值显式拒绝、不静默兜底
        if (StringUtils.hasText(shippingMethod) && !"logistics".equals(shippingMethod) && !noLogistics) {
            throw BusinessException.validationError(
                    "无效的发货方式: " + shippingMethod + "（只接受 logistics 物流发货 / none 无需物流）");
        }
        // 运单号必填**只在物流发货时**成立（无需物流本就没有单号 —— issue #6239 同款收窄）
        if (!noLogistics && !StringUtils.hasText(trackingNo)) {
            throw BusinessException.validationError("货运单号不能为空");
        }
        Order order = orderMapper.selectById(orderId);
        if (order == null) {
            throw BusinessException.notFound("订单");
        }
        // 与工人发货路**同一份**可发货状态集合（issue #6171）：此前这里把三个字面量抄了一遍，
        // 而两条路都会把订单置 shipped ⇒ 抄两份迟早漂移（见 OrderShipmentService.SHIPPABLE_FROM）。
        // 本路多认 shipped：已发货后仅补记/纠正物流（不流转状态），故它是合法的记物流态。
        String status = order.getStatus();
        if (!OrderShipmentService.SHIPPABLE_FROM.contains(status) && !OrderStatusTransitions.SHIPPED.equals(status)) {
            throw BusinessException.validationError("仅已确认/生产中/已发货状态可发货，当前状态: " + status);
        }
        String trimmedTrackingNo = StringUtils.hasText(trackingNo) ? trackingNo.trim() : "";
        String company = StringUtils.hasText(logisticsCompany)
                ? logisticsCompany.trim()
                : currentLogisticsCompany(orderId);
        if (!noLogistics && !StringUtils.hasText(company)) {
            throw BusinessException.validationError("承运商不能为空（客户档案未带出常用物流时需显式选择）");
        }
        // 记物流（发货人 = 显式传入优先，否则当前登录人；工人扫码端登录的就是工人本人）
        OrderLogisticsWriter.upsert(orderLogisticsMapper, TenantContext.getTenantId(), orderId,
                company == null ? "" : company, trimmedTrackingNo, details,
                userService::resolveCurrentUserDisplayName);
        // 原子流转 shipped —— **守卫在这一步内**（含加工项订单必须有 completed 加工单）
        boolean transitioned = shipOrderIfApplicable(orderId);
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("order_id", orderId);
        result.put("status", OrderStatusTransitions.SHIPPED);
        result.put("tracking_no", trimmedTrackingNo);
        result.put("logistics_company", company);
        // 🔴 issue #6181：把「本次是否真的流转了」**显式**交给调用方。调用方随后要调建单写面，而建单
        // 写面**不许**再用「当前状态」重新推断这件事（那时状态已被本方法改成 shipped，谓词区分不了
        // 「我们刚改的」与「本来就已发货」）—— 实测后果是「发货一律 422，而状态与物流已写入」。
        return new OrderService.OrderShipmentOutcome(result, transitioned);
    }


    /** 既有物流记录的承运商（工人端只填单号时用它兜底；无既有记录 ⇒ null）。 */
    private String currentLogisticsCompany(String orderId) {
        List<OrderLogistics> existing =
                orderLogisticsMapper.selectByOrderId(orderId, TenantContext.getTenantId());
        if (existing == null || existing.isEmpty()) {
            return null;
        }
        return existing.get(0).getLogisticsCompany();
    }


    /**
     * 发货联动：confirmed/producing 状态的订单在记录物流后原子流转为 shipped。
     * 已 shipped/completed 保持原状态（仅更新物流）；pending/cancelled 不强制流转。
     *
     * @return 本次是否**真的**发生了 {@code →shipped} 的流转（issue #6181：调用方据此决定要不要建
     *         发货单 —— 见 {@link OrderService.OrderShipmentOutcome#transitioned()}）。{@code rows == 0}
     *         （并发下别人先流转了）⇒ 抛，**不**返回 {@code false}：那是「本来就已发货」的语义，
     *         两者混同会让并发场景静默丢单。
     */
    boolean shipOrderIfApplicable(String orderId) {
        Order order = orderMapper.selectById(orderId);
        if (order == null) {
            return false;
        }
        String currentStatus = order.getStatus();
        if (OrderStatusTransitions.CONFIRMED.equals(currentStatus) || OrderStatusTransitions.PRODUCING.equals(currentStatus)) {
            // issue #7165：商家/生产端/agent 发货（无工人身份）⇒ 完成「发货」工序但不计件；再走守卫
            if (documentOperationLinkage != null) {
                documentOperationLinkage.completeShippingOperations(order, null, order.getTenantId());
            }
            // P1 修复（验收复核 #3345）：与 updateOrderStatus 路径同一守卫——含加工项订单
            // 须有 completed 加工单才能发货，防止 agent 发货路径绕过加工环节
            assertProcessingCompletedBeforeShip(order);
            int rows = transitionStatusAtomic(orderId, currentStatus, OrderStatusTransitions.SHIPPED, null);
            if (rows == 0) {
                throw BusinessException.validationError("订单状态已并发变更，请刷新后重试");
            }
            return true;
        }
        return false;
    }

}
