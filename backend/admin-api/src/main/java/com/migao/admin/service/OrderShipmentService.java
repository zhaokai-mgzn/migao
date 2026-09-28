package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.entity.OrderShipment;
import com.migao.admin.entity.OrderShipmentItem;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderLogisticsMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.OrderShipmentItemMapper;
import com.migao.admin.mapper.OrderShipmentMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import com.migao.admin.worker.WorkerIdentity;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.ThreadLocalRandom;

/**
 * 工人可达的发货面（issue #5648）：拍照生成发货单 + {@code packed}/{@code shipped} 闭环 + 发货明细。
 *
 * <h2>它拥有什么（真值 owner 声明）</h2>
 * <p>🔴 「<b>发货明细（实发套 / 件 / 卷）</b>」这个真值的<b>唯一 owner = 本服务 + 它背后的两张表</b>
 * （{@code order_shipments} / {@code order_shipment_items}）。issue #5651（A4 加工单 / 销售单三联纸）
 * 只**消费** {@link #readShipment}，不得另建第二份投影 —— 否则就是「同一真值两处投影」，
 * 两处迟早对不上，而这条真值直接决定「少发/错发」能不能核。</p>
 *
 * <h2>三条硬口径（都有会红的判据）</h2>
 * <ol>
 *   <li><b>加工单守卫不许被绕过</b>（issue #3340）：发货前调
 *       {@link OrderShipGuard#assertProcessingCompletedBeforeShip}，且**在任何写之前**。
 *       判定本体与商家侧那条路**同一份实现**（不复制守卫）。</li>
 *   <li><b>发货动作与状态变更同事务</b>：整个 {@link #ship} 是一个
 *       {@code @Transactional(rollbackFor = Exception.class)} 方法；状态流转是**最后一步**，
 *       它失败（并发变更）⇒ 抛 ⇒ 整笔回滚 ⇒ 不出现「明细写了但状态没变」。</li>
 *   <li><b>识别不确定 ⇒ 不预填</b>：识别只回候选（{@link #recognize} **不落库**），
 *       工人确认后随发货请求提交；服务端**不替工人猜**任何数量/单位。</li>
 * </ol>
 *
 * <h2>与 {@link OrderService#shipWithLogistics} 的关系</h2>
 * <p>那条是**商家侧**的原子发货入口（记物流 + 流转状态）。本服务是**工人侧**的：多做了
 * 「打包态」「发货明细（实发数量）」「照片/识别留痕」三件事。物流写入复用**同一份**
 * {@link OrderLogisticsWriter}（不复制「存在则更新、否则新建」口径与发货人规则）。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class OrderShipmentService {

    /** 幂等端点标识（同键跨端点复用会留下可查证据，见 {@code ClientRequestIdService}）。 */
    public static final String ENDPOINT_PACK = "POST /api/worker/shipment/orders/{orderId}/pack";
    public static final String ENDPOINT_SHIP = "POST /api/worker/shipment/orders/{orderId}/ship";
    public static final String ENDPOINT_UNPACK = "POST /api/worker/shipment/orders/{orderId}/unpack";

    /** 发货单来源：工人拍照识别生成。 */
    public static final String SOURCE_WORKER_PHOTO = "worker_photo";
    /** 发货单来源：工人手工录入（识别不确定/没拍照时的兜底，**不是降级**）。 */
    public static final String SOURCE_WORKER = "worker";

    /** 幂等回放的标记键（调用方据此区分「首次执行」与「同键回放」）。 */
    public static final String REPLAYED_KEY = "replayed";

    /** 允许发起工人发货的起始状态（{@code packed} 是正常路径；另两条 = 车间里一步到底的小单）。 */
    private static final List<String> SHIPPABLE_FROM = List.of("confirmed", "producing", "packed");

    /** 撤销打包理由上限（与 {@code orders.close_reason} 同量级）。 */
    private static final int MAX_UNPACK_REASON = 500;

    private static final DateTimeFormatter SHIPMENT_NO_TS = DateTimeFormatter.ofPattern("yyyyMMddHHmmss");

    private final OrderMapper orderMapper;
    private final OrderItemMapper orderItemMapper;
    private final OrderLogisticsMapper orderLogisticsMapper;
    private final OrderShipmentMapper orderShipmentMapper;
    private final OrderShipmentItemMapper orderShipmentItemMapper;
    private final ProcessingOrderMapper processingOrderMapper;
    private final ClientRequestIdService clientRequestIdService;
    private final ImageRecognitionClient imageRecognitionClient;
    private final ObjectMapper objectMapper;

    // ══════════════════════════════════════════════════════════════════════════════
    // 拍照识别（**不落库**，与 #5321 的页面快通道同一份内核）
    // ══════════════════════════════════════════════════════════════════════════════

    /**
     * 拍照识别：图 → 订单行 / 商品标签上的**文字**候选（不落库、不提交）。
     *
     * <p>链路选择（issue #5648 裁定「识别订单行 / 商品标签」，本单**复用**而非新造）：
     * 走 {@link ImageRecognitionClient} → ai-agent 的
     * {@code POST /api/internal/vision/recognize} → {@code app/vision/recognizer.py}，
     * 只把 target 换成 {@code shipment}。理由：</p>
     * <ul>
     *   <li>「不确定 ⇒ 不预填」的判据（{@code TARGET_POLICY.min_confidence} + 逐格留空理由 +
     *       {@code [图片识别]} 标注）**已经在那一份实现里落码**；新造一条链 = 把这份判据复制一份，
     *       而两份判据迟早分叉（分叉方向：某一条链开始编造数量）。</li>
     *   <li>#5052 的识别链是「条码解码优先 → vision 兜底」；本单按裁定是**文字识别**为主
     *       ⇒ 不引入前端条码解码依赖（全仓 {@code jsqr}/{@code zxing} 零命中，引入即新依赖），
     *       直接走 vision —— **target 不同，基建同一份**。</li>
     * </ul>
     * <p>🔴 工人路径**只认 {@code shipment} 这一个 target**（不给工人开 {@code product}/{@code order}
     * 的识别入口 —— 那是建品/建单页的能力，属商家面）。</p>
     */
    public ImageRecognitionClient.ImageRecognitionResult recognize(List<String> images) {
        return imageRecognitionClient.recognize(OrderShipmentTarget.SHIPMENT, images);
    }

    /** 工人发货识别的 target 名（**唯一字面量**：Java 侧与 ai-agent 的 {@code TARGET_FIELDS} 同名）。 */
    public static final class OrderShipmentTarget {
        public static final String SHIPMENT = "shipment";

        private OrderShipmentTarget() {
        }
    }

    // ══════════════════════════════════════════════════════════════════════════════
    // 打包（工人）
    // ══════════════════════════════════════════════════════════════════════════════

    /**
     * 打包：{@code confirmed|producing → packed}，并落服务端留痕（谁、何时）。
     *
     * <p>口径（用户 2026-09-26 裁定「打包与发货都是工人的动作」）：{@code packed} 由工人在 H5 推进；
     * 非法起始状态（如 {@code pending → packed}）由 {@link OrderStatusTransitions} 拒绝。
     * 打包**不**调加工单守卫 —— 那条守卫的语义是「没加工完不许**发走**」，不是「不许打包」
     * （挡住打包只会让工人多跑一趟，不减少任何风险）。</p>
     */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> pack(String orderId, Long tenantId, String clientRequestId,
                                    WorkerIdentity identity) {
        requireWorker(identity);
        if (!clientRequestIdService.claim(tenantId, clientRequestId, ENDPOINT_PACK)) {
            return replay(tenantId, clientRequestId, orderId);
        }
        Map<String, Object> result = doPack(orderId, tenantId, identity);
        clientRequestIdService.complete(tenantId, clientRequestId, result);
        return result;
    }

    private Map<String, Object> doPack(String orderId, Long tenantId, WorkerIdentity identity) {
        Order order = loadOrder(orderId, tenantId);
        String current = order.getStatus();
        OrderStatusTransitions.assertTransitionAllowed(current, "packed");

        OrderShipment shipment = activeShipment(orderId, tenantId)
                .orElseGet(() -> newShipment(order, SOURCE_WORKER));
        shipment.setPackedAt(OffsetDateTime.now());
        shipment.setPackedByWorkerId(identity.workerId());
        shipment.setPackedByWorkerName(identity.workerName());
        persist(shipment);

        int rows = transition(orderId, current, "packed");
        if (rows == 0) {
            throw BusinessException.validationError("订单状态已并发变更，请刷新后重试");
        }
        log.info("[发货] 打包完成: orderId={}, shipmentNo={}, worker={}",
                orderId, shipment.getShipmentNo(), identity.workerName());
        return resultOf(orderId, tenantId, "packed", shipment, List.of());
    }

    // ══════════════════════════════════════════════════════════════════════════════
    // 发货（工人）—— 一个动作=一个原子入口
    // ══════════════════════════════════════════════════════════════════════════════

    /**
     * 发货：记**实发**明细 + 物流 + 原子流转 {@code shipped}（一次事务）。
     *
     * <p><b>为什么是一个入口而不是复用两个端点</b>：与
     * {@link OrderService#shipWithLogistics} 同一条理由 —— 「记明细」「记单号」「改状态」分成三次调用，
     * 中间失败就是「有单号没发货」或「记了实发但状态没变」的静默不一致。发货是**一个动作**。</p>
     *
     * <p>body（字段面与订单行既有列**同名**，不许自造第二套口径）：</p>
     * <pre>
     * {
     *   "trackingNo": "SF123",                 // 必填（没有单号的"发货"在车间不可核对）
     *   "logisticsCompany": "顺丰",             // 可空 ⇒ 取既有物流记录的承运商
     *   "photoRefs": ["https://..."],          // 可空（手工录入时没有照片，是**正常路径**不是降级）
     *   "recognition": { ... },                // 可空：识别留痕原样搬运
     *   "items": [                             // 必填非空
     *     {"order_item_id": "...", "product_name": "...",
     *      "shipped_quantity": 12.5, "unit": "米", "set_count": null, "roll_count": null}
     *   ]
     * }
     * </pre>
     *
     * <p>🔴 <b>缺值不猜</b>：{@code shipped_quantity} 必须由人给（识别不确定就不预填）；
     * {@code unit} 必须显式给（不从订单行推算 —— 推算错了就是记错单位）；
     * {@code set_count}/{@code roll_count} 缺省为 {@code null}（**不填 0**：0 是「一件都没发」的
     * 另一个意思）。</p>
     */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> ship(String orderId, Map<String, Object> body, Long tenantId,
                                    String clientRequestId, WorkerIdentity identity) {
        requireWorker(identity);
        if (!clientRequestIdService.claim(tenantId, clientRequestId, ENDPOINT_SHIP)) {
            return replay(tenantId, clientRequestId, orderId);
        }
        Map<String, Object> result = doShip(orderId, body, tenantId, identity);
        clientRequestIdService.complete(tenantId, clientRequestId, result);
        return result;
    }

    private Map<String, Object> doShip(String orderId, Map<String, Object> body, Long tenantId,
                                       WorkerIdentity identity) {
        Order order = loadOrder(orderId, tenantId);
        String current = order.getStatus();
        if (!SHIPPABLE_FROM.contains(current)) {
            throw BusinessException.validationError(String.format(
                    "当前状态（%s）不可发货：仅 %s 可发货",
                    OrderStatusTransitions.label(current),
                    SHIPPABLE_FROM.stream().map(OrderStatusTransitions::label).toList()));
        }

        String trackingNo = text(body, "trackingNo");
        if (!StringUtils.hasText(trackingNo)) {
            throw BusinessException.validationError("货运单号不能为空");
        }
        String company = text(body, "logisticsCompany");
        if (!StringUtils.hasText(company)) {
            List<com.migao.admin.entity.OrderLogistics> existing =
                    orderLogisticsMapper.selectByOrderId(orderId, tenantId);
            company = (existing == null || existing.isEmpty()) ? null : existing.get(0).getLogisticsCompany();
        }
        if (!StringUtils.hasText(company)) {
            throw BusinessException.validationError("承运商不能为空（客户档案未带出常用物流时需显式选择）");
        }

        List<OrderItem> orderItems = OrderShipGuard.loadOrderItems(orderItemMapper, orderId, tenantId);
        List<OrderShipmentItem> details = parseDetails(body, orderId, tenantId, orderItems);

        // 🔴 加工单守卫（issue #3340）——**在任何写之前**。判定本体与商家侧那条路同一份实现。
        OrderShipGuard.assertProcessingCompletedBeforeShip(
                orderItemMapper, processingOrderMapper, objectMapper, order);

        OrderShipment shipment = activeShipment(orderId, tenantId)
                .orElseGet(() -> newShipment(order, sourceOf(body)));
        // 一步到底（confirmed/producing → shipped）时**补记** packed_at：
        // 「发出去的货必然已经被打包过」是物理事实，不补记就会留下"跳过打包"的无痕形态。
        if (shipment.getPackedAt() == null) {
            shipment.setPackedAt(OffsetDateTime.now());
            shipment.setPackedByWorkerId(identity.workerId());
            shipment.setPackedByWorkerName(identity.workerName());
        }
        shipment.setShippedAt(OffsetDateTime.now());
        shipment.setShippedByWorkerId(identity.workerId());
        shipment.setShippedByWorkerName(identity.workerName());
        shipment.setTrackingNo(trackingNo.trim());
        shipment.setLogisticsCompany(company.trim());
        shipment.setPhotoRefs(body == null ? null : body.get("photoRefs"));
        shipment.setRecognition(body == null ? null : body.get("recognition"));
        persist(shipment);

        for (OrderShipmentItem detail : details) {
            detail.setShipmentId(shipment.getId());
            orderShipmentItemMapper.insert(detail);
        }

        // 物流面复用**同一份**写入口径（存在则更新、否则新建 + 发货人只在新建时解析）
        OrderLogisticsWriter.upsert(orderLogisticsMapper, tenantId, orderId, company.trim(),
                trackingNo.trim(), identity.workerName(), () -> identity.workerName());

        // 🔴 状态流转是**最后一步**：失败（并发变更）⇒ 抛 ⇒ 整笔回滚 ⇒
        // 「明细写了但状态没变」这个形态在结构上不可能出现。
        int rows = transition(orderId, current, "shipped");
        if (rows == 0) {
            throw BusinessException.validationError("订单状态已并发变更，请刷新后重试");
        }
        log.info("[发货] 完成: orderId={}, shipmentNo={}, trackingNo={}, worker={}, 明细行={}",
                orderId, shipment.getShipmentNo(), trackingNo, identity.workerName(), details.size());
        return resultOf(orderId, tenantId, "shipped", shipment, details);
    }

    // ══════════════════════════════════════════════════════════════════════════════
    // 撤销打包（工人）—— 具名动作，必带理由 + 留痕
    // ══════════════════════════════════════════════════════════════════════════════

    /**
     * 撤销打包：{@code packed → producing}。
     *
     * <p><b>为什么它是具名动作而不是状态表里的一条边</b>（issue #5648 必须显式回答的问题）：</p>
     * <ul>
     *   <li>打包**会打错**（车间实测常态：装错单、封错箱）。若不允许撤销，唯一的出口是「继续发出去」，
     *       那是把错货发到客户手里 —— 比留痕贵得多。</li>
     *   <li>但「已打包 ⇒ 回退」是**涉责任**的动作（谁拆的包、为什么），所以它**不能**进
     *       {@link OrderStatusTransitions#STATUS_TRANSITIONS} —— 进了那张表，商家侧
     *       {@code PUT /orders/{id}/status} 就能**无理由**把已打包单一键退回生产，
     *       而那条路连理由字段都没有，留不下痕。</li>
     *   <li>⇒ 本方法 = 唯一的撤销入口：**必须带理由**（非空，≤500 字）+
     *       在发货单上留 {@code unpacked_at}/{@code unpacked_by_*}/{@code unpack_reason}。</li>
     * </ul>
     * <p>权限口径：工人侧（有效工人 session 即可，**不挂任何商家权限码**）。
     * 商家侧**不提供**撤销入口 —— 「谁打的包谁拆」是本单采纳的责任口径（若商家也要能拆，
     * 那是另一个裁定，本单不擅自扩面）。</p>
     */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> unpack(String orderId, String reason, Long tenantId,
                                      String clientRequestId, WorkerIdentity identity) {
        requireWorker(identity);
        if (!StringUtils.hasText(reason) || reason.trim().length() > MAX_UNPACK_REASON) {
            throw BusinessException.validationError(
                    "撤销打包必须说明理由（1~" + MAX_UNPACK_REASON + " 字）—— 已打包是涉责任的状态，不留痕不给撤");
        }
        if (!clientRequestIdService.claim(tenantId, clientRequestId, ENDPOINT_UNPACK)) {
            return replay(tenantId, clientRequestId, orderId);
        }
        Map<String, Object> result = doUnpack(orderId, reason.trim(), tenantId, identity);
        clientRequestIdService.complete(tenantId, clientRequestId, result);
        return result;
    }

    private Map<String, Object> doUnpack(String orderId, String reason, Long tenantId,
                                         WorkerIdentity identity) {
        Order order = loadOrder(orderId, tenantId);
        if (!"packed".equals(order.getStatus())) {
            throw BusinessException.validationError(String.format(
                    "仅「已打包」的订单可撤销打包，当前状态: %s",
                    OrderStatusTransitions.label(order.getStatus())));
        }
        OrderShipment shipment = activeShipment(orderId, tenantId).orElseThrow(() ->
                BusinessException.validationError("未找到可撤销的打包记录，请刷新后重试"));
        shipment.setUnpackedAt(OffsetDateTime.now());
        shipment.setUnpackedByWorkerId(identity.workerId());
        shipment.setUnpackedByWorkerName(identity.workerName());
        shipment.setUnpackReason(reason);
        // 撤销后这一张发货单回到「未打包」——把 packed_* 清掉，让状态与留痕一致
        shipment.setPackedAt(null);
        shipment.setPackedByWorkerId(null);
        shipment.setPackedByWorkerName(null);
        orderShipmentMapper.updateById(shipment);

        // 🔴 目标状态 producing 是**有意**不在 STATUS_TRANSITIONS 里的（见方法注释）
        int rows = transition(orderId, "packed", "producing");
        if (rows == 0) {
            throw BusinessException.validationError("订单状态已并发变更，请刷新后重试");
        }
        log.info("[发货] 撤销打包: orderId={}, shipmentNo={}, worker={}, reason={}",
                orderId, shipment.getShipmentNo(), identity.workerName(), reason);
        return resultOf(orderId, tenantId, "producing", shipment, List.of());
    }

    // ══════════════════════════════════════════════════════════════════════════════
    // 读面：发货明细（实发套/件/卷）—— **唯一 owner 的读实现**
    // ══════════════════════════════════════════════════════════════════════════════

    /**
     * 某订单的发货读面：发货单（含照片引用 / 识别留痕 / 撤销留痕）+ 逐行实发 + 汇总。
     *
     * <p>issue #5651（纸面）消费**本方法**，不另建投影。工人端与将来的商家端共用它 ⇒
     * 两端看到的实发数量逐字同源。</p>
     */
    public Map<String, Object> readShipment(String orderId, Long tenantId) {
        Order order = loadOrder(orderId, tenantId);
        List<OrderShipment> shipments = orderShipmentMapper.selectByOrderId(orderId, tenantId);
        if (shipments == null) {
            shipments = List.of();
        }
        List<Map<String, Object>> shipmentViews = new ArrayList<>();
        List<OrderShipmentItem> allItems = new ArrayList<>();
        for (OrderShipment s : shipments) {
            List<OrderShipmentItem> items = orderShipmentItemMapper.selectByShipmentId(s.getId(), tenantId);
            if (items == null) {
                items = List.of();
            }
            allItems.addAll(items);
            Map<String, Object> view = new LinkedHashMap<>();
            view.put("shipment_no", s.getShipmentNo());
            view.put("source", s.getSource());
            view.put("photo_refs", s.getPhotoRefs());
            view.put("recognition", s.getRecognition());
            view.put("packed_at", s.getPackedAt());
            view.put("packed_by", s.getPackedByWorkerName());
            view.put("shipped_at", s.getShippedAt());
            view.put("shipped_by", s.getShippedByWorkerName());
            view.put("tracking_no", s.getTrackingNo());
            view.put("logistics_company", s.getLogisticsCompany());
            view.put("unpacked_at", s.getUnpackedAt());
            view.put("unpacked_by", s.getUnpackedByWorkerName());
            view.put("unpack_reason", s.getUnpackReason());
            view.put("items", items.stream().map(OrderShipmentService::itemView).toList());
            shipmentViews.add(view);
        }
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("order_id", order.getId());
        result.put("order_no", order.getOrderNo());
        result.put("status", order.getStatus());
        result.put("shipments", shipmentViews);
        result.put("shipped_totals", totals(allItems));
        return result;
    }

    /**
     * 实发汇总：**直接回答「这一单实际发了几套 / 几件 / 几卷」**。
     *
     * <p>口径：{@code set_count}/{@code roll_count} 只对**显式填过**的行求和（空值不参与 ——
     * 把 null 当 0 会把「这一维不适用」算成「一件都没发」）；{@code by_unit} 按单位累计实发数量。</p>
     */
    private Map<String, Object> totals(List<OrderShipmentItem> items) {
        BigDecimal sets = BigDecimal.ZERO;
        BigDecimal rolls = BigDecimal.ZERO;
        Map<String, BigDecimal> byUnit = new LinkedHashMap<>();
        for (OrderShipmentItem it : items) {
            if (it.getSetCount() != null) {
                sets = sets.add(BigDecimal.valueOf(it.getSetCount()));
            }
            if (it.getRollCount() != null) {
                rolls = rolls.add(BigDecimal.valueOf(it.getRollCount()));
            }
            if (it.getUnit() != null) {
                byUnit.merge(it.getUnit(),
                        it.getShippedQuantity() == null ? BigDecimal.ZERO : it.getShippedQuantity(),
                        BigDecimal::add);
            }
        }
        Map<String, Object> totals = new LinkedHashMap<>();
        totals.put("set_count", sets);
        totals.put("roll_count", rolls);
        totals.put("by_unit", byUnit);
        return totals;
    }

    private static Map<String, Object> itemView(OrderShipmentItem it) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("order_item_id", it.getOrderItemId());
        m.put("product_name", it.getProductName());
        m.put("shipped_quantity", it.getShippedQuantity());
        m.put("unit", it.getUnit());
        m.put("set_count", it.getSetCount());
        m.put("roll_count", it.getRollCount());
        return m;
    }

    // ══════════════════════════════════════════════════════════════════════════════
    // 内部
    // ══════════════════════════════════════════════════════════════════════════════

    /**
     * 工人身份 fail-closed：无有效工人身份 ⇒ 拒绝（**不降级到 body 口径**）。
     * 本路径是「谁发的货」的唯一来源，没有第二条来源可用（涉责任）。
     */
    private void requireWorker(WorkerIdentity identity) {
        if (identity == null || !identity.fromSession() || !StringUtils.hasText(identity.workerId())) {
            throw BusinessException.authFailed("尚未登录工人身份，请先用工号 + PIN 登录");
        }
    }

    /** 载入订单并做**跨租户**判定：别的租户的单 = 不存在（不是"无权限"，不给探测面）。 */
    private Order loadOrder(String orderId, Long tenantId) {
        Order order = orderMapper.selectById(orderId);
        if (order == null || tenantId == null || !tenantId.equals(order.getTenantId())) {
            throw BusinessException.notFound("订单");
        }
        return order;
    }

    /** 当前**未发货**的发货单（打包阶段建的那张）；已发货或无记录 ⇒ 空。 */
    private Optional<OrderShipment> activeShipment(String orderId, Long tenantId) {
        List<OrderShipment> all = orderShipmentMapper.selectByOrderId(orderId, tenantId);
        if (all == null) {
            return Optional.empty();
        }
        return all.stream().filter(s -> s.getShippedAt() == null).findFirst();
    }

    private OrderShipment newShipment(Order order, String source) {
        return OrderShipment.builder()
                .tenantId(order.getTenantId())
                .orderId(order.getId())
                .orderNo(order.getOrderNo())
                .shipmentNo(nextShipmentNo(order))
                .source(source)
                .build();
    }

    private String nextShipmentNo(Order order) {
        return "SH" + OffsetDateTime.now().format(SHIPMENT_NO_TS)
                + String.format("%04d", ThreadLocalRandom.current().nextInt(10000));
    }

    private void persist(OrderShipment shipment) {
        if (shipment.getId() == null) {
            orderShipmentMapper.insert(shipment);
        } else {
            orderShipmentMapper.updateById(shipment);
        }
    }

    /** 来源：带了照片引用 ⇒ 拍照生成；否则工人手工录入（两者都是正常路径，无优劣）。 */
    private String sourceOf(Map<String, Object> body) {
        Object refs = body == null ? null : body.get("photoRefs");
        boolean hasPhoto = refs instanceof List<?> list && !list.isEmpty();
        return hasPhoto ? SOURCE_WORKER_PHOTO : SOURCE_WORKER;
    }

    /**
     * 解析实发明细（**缺值不猜**）。
     *
     * @param orderItems 该订单的既有订单行 —— 用来挡「把别的订单的 order_item_id 塞进来」
     */
    @SuppressWarnings("unchecked")
    private List<OrderShipmentItem> parseDetails(Map<String, Object> body, String orderId,
                                                 Long tenantId, List<OrderItem> orderItems) {
        Object raw = body == null ? null : body.get("items");
        if (!(raw instanceof List<?> list) || list.isEmpty()) {
            throw BusinessException.validationError(
                    "发货明细不能为空：需要逐行给出**实发**数量（少发/错发正是靠它才可核）");
        }
        Map<String, OrderItem> byId = new LinkedHashMap<>();
        for (OrderItem it : orderItems) {
            byId.put(it.getId(), it);
        }
        List<OrderShipmentItem> details = new ArrayList<>();
        for (Object element : list) {
            if (!(element instanceof Map)) {
                throw BusinessException.validationError("发货明细每一项都必须是对象");
            }
            Map<String, Object> entry = (Map<String, Object>) element;
            BigDecimal qty = OrderShipGuard.toBigDecimal(entry.get("shipped_quantity"));
            if (qty == null || qty.compareTo(BigDecimal.ZERO) <= 0) {
                throw BusinessException.validationError(
                        "实发数量必须是正数（识别不确定时请手工填写，系统不替你猜）");
            }
            String unit = text(entry, "unit");
            if (!StringUtils.hasText(unit)) {
                throw BusinessException.validationError(
                        "实发单位不能为空（米 / 套 / 件）—— 单位不从订单行推算，推错就是记错单位");
            }
            String orderItemId = text(entry, "order_item_id");
            if (StringUtils.hasText(orderItemId) && !byId.containsKey(orderItemId)) {
                throw BusinessException.validationError(
                        "发货明细引用了不属于该订单的订单行: " + orderItemId);
            }
            OrderItem orderItem = byId.get(orderItemId);
            details.add(OrderShipmentItem.builder()
                    .tenantId(tenantId)
                    .orderId(orderId)
                    .orderItemId(StringUtils.hasText(orderItemId) ? orderItemId : null)
                    .productName(StringUtils.hasText(text(entry, "product_name"))
                            ? text(entry, "product_name").trim()
                            : (orderItem == null ? null : orderItem.getProductName()))
                    .shippedQuantity(qty)
                    .unit(unit.trim())
                    .setCount(intOrNull(entry.get("set_count")))
                    .rollCount(intOrNull(entry.get("roll_count")))
                    .build());
        }
        return details;
    }

    /** {@code null} 保持 {@code null}（**不填 0**：0 与 null 是两个意思）。 */
    private static Integer intOrNull(Object value) {
        BigDecimal d = OrderShipGuard.toBigDecimal(value);
        return d == null ? null : d.intValue();
    }

    private static String text(Map<String, Object> body, String key) {
        if (body == null) return null;
        Object v = body.get(key);
        return v == null ? null : String.valueOf(v);
    }

    /** 原子状态流转（以读取到的状态为条件，防并发重复流转）。 */
    private int transition(String orderId, String expected, String target) {
        LambdaUpdateWrapper<Order> wrapper = new LambdaUpdateWrapper<>();
        wrapper.eq(Order::getId, orderId)
                .eq(Order::getStatus, expected)
                .set(Order::getStatus, target);
        return orderMapper.update(null, wrapper);
    }

    private Map<String, Object> resultOf(String orderId, Long tenantId, String status,
                                         OrderShipment shipment, List<OrderShipmentItem> details) {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("order_id", orderId);
        result.put("status", status);
        result.put("shipment_no", shipment.getShipmentNo());
        result.put("source", shipment.getSource());
        result.put("tracking_no", shipment.getTrackingNo());
        result.put("shipped_items", details.stream().map(OrderShipmentService::itemView).toList());
        result.put("shipped_totals", totals(details));
        return result;
    }

    @SuppressWarnings({"unchecked", "rawtypes"})
    private Map<String, Object> replay(Long tenantId, String clientRequestId, String orderId) {
        Optional<Map> stale = clientRequestIdService.replay(tenantId, clientRequestId, Map.class);
        Map<String, Object> snapshot = (Map<String, Object>) stale.orElseThrow(() -> new BusinessException(
                "REQUEST_IN_PROGRESS",
                "同一 X-Client-Request-Id 的发货请求正在处理中，本次未重复发货",
                409,
                "请勿重复提交；请稍后刷新本单发货状态确认是否已发货（换新幂等键重试会重复记明细）"));
        snapshot.put(REPLAYED_KEY, Boolean.TRUE);
        log.info("[发货幂等] 同键重复请求：跳过执行，回放首次结果 orderId={}", orderId);
        return snapshot;
    }
}
