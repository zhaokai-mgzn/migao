package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.dto.OrderDetailResponse;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import lombok.extern.slf4j.Slf4j;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 发货前置守卫（issue #3340 的判定本体，issue #5648 抽成**单一实现点**）。
 *
 * <h3>为什么抽出来（不是「为了好看」）</h3>
 * <p>#5648 之前，「含加工项订单必须完成加工单才能发货」这条判定是
 * {@code OrderService} 的 {@code private} 方法，只能被 {@code OrderService} 自己的两条路
 * （{@code updateOrderStatus} / {@code shipOrderIfApplicable}）调用。本单新增**第三条**发货路
 * （{@code OrderShipmentService}，工人可达面），若在那边再写一份判定，就是**两份守卫** ——
 * 它们迟早分叉，而分叉的方向是「工人那条路能绕过加工环节」（涉钱：绕过加工 = 未加工就发货）。</p>
 *
 * <p>⇒ 判定本体搬到这里，{@link OrderService} 的三个既有私有方法改为**一行委托**
 * （调用点一字未动）。<b>这是一次搬家，不是一次改写</b>：判定逻辑逐字保留（含
 * {@code issue #3340} 验收实战的两条注释）。</p>
 *
 * <h3>为什么是 static 而不是 {@code @Component}</h3>
 * <p>{@code OrderService} 是 {@code @RequiredArgsConstructor} 的 16 依赖 bean，而本仓有大量
 * {@code new OrderService(...)} / {@code @InjectMocks} 的既有单测 —— 给它加一个构造依赖会**波及
 * 全部那些测试**（§23.5「坐标漂移」同族：一次为可测性而做的注入，会顶掉别人的红证坐标）。
 * 本类无状态、无生命周期，静态方法即可；依赖（两个 Mapper + ObjectMapper）由调用方传入。</p>
 */
@Slf4j
public final class OrderShipGuard {

    private OrderShipGuard() {
    }

    /**
     * 发货前置判据（**唯一一份**，issue #3340 / #5641 / #5648）：含加工项的订单必须已有
     * 完成加工单才允许发货。三个消费方共用它：发货守卫（{@link #assertProcessingCompletedBeforeShip}）、
     * 生产待办的「待发货」计数（issue #5641）、以及任何将来的发货路径。
     *
     * @return {@code true} = 允许发货（无加工项，或加工单已完成）；{@code false} = 被加工单挡住
     */
    public static boolean isProcessingReadyForShip(OrderItemMapper orderItemMapper,
                                                   ProcessingOrderMapper processingOrderMapper,
                                                   ObjectMapper objectMapper,
                                                   Order order) {
        return !hasProcessingItems(orderItemMapper, objectMapper, order)
                || processingOrderMapper.countCompletedByOrderId(order.getId(), order.getTenantId()) > 0;
    }

    /**
     * 该订单是否含加工项（订单明细的 {@code processing_info} 非空）。
     *
     * <p><b>这是「含加工项」的唯一一份判据</b>（issue #3340 的发货守卫与 issue #5641 的生产待办
     * 都读它）—— 自己再写一份 {@code extractProcessingItems} 调用就会是两处口径。</p>
     *
     * <p>必须走 BaseMapper 加载（见 {@link #loadOrderItems}）：自定义 {@code @Select} 不经过
     * {@code JacksonTypeHandler}，{@code processing_info} 会以 JSON <b>字符串</b>返回 ⇒ 加工项解析
     * 恒为空 ⇒ 判据静默失效（issue #3340 验收实战：真实对话生成加工单被判「无加工项」）。</p>
     */
    public static boolean hasProcessingItems(OrderItemMapper orderItemMapper,
                                             ObjectMapper objectMapper,
                                             Order order) {
        return loadOrderItems(orderItemMapper, order.getId(), order.getTenantId()).stream()
                .anyMatch(item -> !extractProcessingItems(objectMapper, item.getProcessingInfo()).isEmpty());
    }

    /**
     * 加工单联动守卫（issue #3340）：订单含加工项且无已完成加工单时禁止发货。
     * 有加工项订单必须走 producing（生成加工单）→ 加工完成 → shipped，防止加工环节被绕过。
     *
     * <p>本体 = {@link #isProcessingReadyForShip}（**不是**第二份判定；本方法只是它的抛异常外壳）。</p>
     *
     * <p><b>issue #5842 追加第二道判据（#3352 决策 2026-09-12 的「选项 B」）</b>：
     * 本方法是**三条发货路**（商家 {@code PUT /orders/{id}/status}、发货页
     * {@code shipOrderIfApplicable}、工人 {@code OrderShipmentService}）唯一共用的入口 ⇒
     * 漂移校验挂在这里，三条路一次覆盖（挂在某一条路上就是"另外两条能绕过"）。</p>
     */
    public static void assertProcessingCompletedBeforeShip(OrderItemMapper orderItemMapper,
                                                           ProcessingOrderMapper processingOrderMapper,
                                                           ObjectMapper objectMapper,
                                                           Order order) {
        if (!isProcessingReadyForShip(orderItemMapper, processingOrderMapper, objectMapper, order)) {
            throw BusinessException.validationError(
                    "订单含加工项，须先完成加工单后再发货（可在订单详情或让黄金策生成/更新加工单）");
        }
        // ── 选项 B：快照漂移覆盖校验（issue #5842）────────────────────────────────
        // 决策 C（#3352）当年以「加工项仅创建时可写」把漂移堵在源头；#5842 按用户裁定开了
        // **待付款内容编辑**通道 ⇒ 源头约束不再独当一面，必须有第二道（决策 B）。
        // 为什么仍要它（编辑通道已限制在 pending、而加工单在 producing 才生成）：
        // ① 编辑与生成是**两条独立写路径**，靠"状态不同时出现"这种时序假设守钱面，
        //    是**没有判据的假设**（并发窗口 / 将来放宽可编辑状态 / 存量脏数据都能打破它）；
        // ② 漂移的真实后果是「订单上多了加工项，车间没做，货照发」—— 涉钱且不可逆。
        if (hasProcessingDrift(orderItemMapper, processingOrderMapper, objectMapper, order)) {
            throw BusinessException.validationError(
                    "订单明细与加工单快照不一致（加工单生成后订单加工项被改动）⇒ "
                            + "请先作废并重新生成加工单，确认车间做的是改后的活，再发货");
        }
    }

    /**
     * **快照漂移**判据（选项 B 的判定本体，issue #5842）—— 加工单生成后订单加工项是否被改动。
     *
     * <p>比较两侧都以「订单明细行 id（{@code order_items.id}）」为键：</p>
     * <ul>
     *   <li><b>快照侧</b>：活跃加工单的 {@code items_snapshot}（{@code ProcessingOrderService.buildSnapshot}
     *       生成时的固化真相）逐行取 {@code itemId → [加工项名×数量]}；</li>
     *   <li><b>订单侧</b>：当前 {@code order_items} 逐行取同一形状。</li>
     * </ul>
     * <p>三种漂移形态都判：① 快照里的行在订单里**没了**（明细被删）；
     * ② 同一行的加工项集合变了（增/删/改名/改数量）；
     * ③ 订单里**多出**了带加工项的行（= 「新增的加工项没人做却仍可发货」，正是决策 C 要堵的那件事）。</p>
     *
     * <p>⚠️ <b>「第 ③ 种」为什么只数**带加工项**的新行</b>：{@code buildSnapshot} **本来就不收录**
     * 无加工项的非卖布行（配件/赠品行，见其 {@code procs.isEmpty() && !布料} 分支）⇒ 把"订单里多一行"
     * 一律算漂移，会把**合法**的配件行判成漂移（假拦货）。同理，快照为空（未收录任何行）时
     * **无法判定**（存量/异常形态）⇒ 不据此拦货 —— 宁可漏判也不把"读不懂"当成"漂移"
     * （该边界逐条登记在 PR 的未固化项里）。</p>
     */
    public static boolean hasProcessingDrift(OrderItemMapper orderItemMapper,
                                             ProcessingOrderMapper processingOrderMapper,
                                             ObjectMapper objectMapper,
                                             Order order) {
        ProcessingOrder active = processingOrderMapper.selectActiveByOrderId(order.getId(), order.getTenantId());
        if (active == null) {
            return false; // 还没有加工单 ⇒ 没有快照可比（发货拦不拦由上面那道判据管）
        }
        Map<String, List<String>> snapshot = snapshotProcessingSignatures(objectMapper, active.getItemsSnapshot());
        if (snapshot.isEmpty()) {
            log.warn("加工单快照为空或不可解析，跳过漂移校验（无法判定，不据此拦货）: orderId={}, processingOrderNo={}",
                    order.getId(), active.getProcessingOrderNo());
            return false;
        }
        Map<String, List<String>> current = new LinkedHashMap<>();
        for (OrderItem item : loadOrderItems(orderItemMapper, order.getId(), order.getTenantId())) {
            current.put(item.getId(), processingSignatures(extractProcessingItems(objectMapper, item.getProcessingInfo())));
        }
        for (Map.Entry<String, List<String>> row : snapshot.entrySet()) {
            List<String> now = current.get(row.getKey());
            if (now == null || !now.equals(row.getValue())) {
                return true; // ① 快照行没了 / ② 同一行加工项变了
            }
        }
        // ③ 订单侧多出的、**带加工项**的行（无加工项的新行不入快照，不算漂移）
        for (Map.Entry<String, List<String>> row : current.entrySet()) {
            if (!row.getValue().isEmpty() && !snapshot.containsKey(row.getKey())) {
                return true;
            }
        }
        return false;
    }

    /**
     * 加工单快照 → {@code itemId → [加工项签字]}（键序排序保证可比较，与「同一份数据两次比较恒等」同族）。
     *
     * <p>{@code itemsSnapshot} 可能以 JSON **字符串**形态出现（自定义 {@code @Select} 不经
     * {@code JacksonTypeHandler}）⇒ 先归一化，避免「读不懂 ⇒ 判无漂移」的静默失效
     * （同 {@link #extractProcessingItems} 的兼容口径）。</p>
     */
    @SuppressWarnings("unchecked")
    static Map<String, List<String>> snapshotProcessingSignatures(ObjectMapper objectMapper, Object snapshot) {
        Object normalized = snapshot;
        if (normalized instanceof String s && !s.isBlank()) {
            try {
                normalized = objectMapper.readValue(s, List.class);
            } catch (Exception e) {
                log.warn("加工单快照 JSON 字符串解析失败: {}", e.getMessage());
                return Map.of();
            }
        }
        if (!(normalized instanceof List)) {
            return Map.of();
        }
        Map<String, List<String>> result = new LinkedHashMap<>();
        for (Object element : (List<Object>) normalized) {
            if (!(element instanceof Map)) {
                continue;
            }
            Map<String, Object> row = (Map<String, Object>) element;
            Object itemId = row.get("itemId");
            if (itemId == null) {
                continue;
            }
            result.put(String.valueOf(itemId),
                    processingSignatures(extractProcessingItems(objectMapper, row)));
        }
        return result;
    }

    /**
     * 行内加工项签字（`名字×数量` 排序后成列）：比较的是**车间会做哪些活**，
     * 不比较展示字段（单价/规格那些改了不影响车间做没做，`#4882` 起加工项本就不含销售价）。
     */
    static List<String> processingSignatures(List<OrderDetailResponse.ProcessingItemBrief> items) {
        List<String> signatures = new ArrayList<>();
        for (OrderDetailResponse.ProcessingItemBrief item : items) {
            String name = item.getName() == null ? "" : item.getName().trim();
            BigDecimal quantity = item.getQuantity();
            signatures.add(name + "×" + (quantity == null ? "" : quantity.stripTrailingZeros().toPlainString()));
        }
        Collections.sort(signatures);
        return signatures;
    }

    /**
     * 加载订单明细（走 BaseMapper，确保 processing_info 经 JacksonTypeHandler 反序列化为 Map）。
     * 与 {@code getOrderById} 的既有约定一致。
     */
    public static List<OrderItem> loadOrderItems(OrderItemMapper orderItemMapper,
                                                 String orderId, Long tenantId) {
        List<OrderItem> items = orderItemMapper.selectList(new LambdaQueryWrapper<OrderItem>()
                .eq(OrderItem::getOrderId, orderId)
                .eq(OrderItem::getTenantId, tenantId)
                .eq(OrderItem::getDeleted, 0));
        return items != null ? items : Collections.emptyList();
    }

    /**
     * 解析订单行的加工项清单。
     *
     * <p>issue #3340 验收实战：{@code processingInfo} 可能是 JSON **字符串**（自定义 {@code @Select}
     * 查询不经过 JacksonTypeHandler），此处做兼容解析，避免「有加工项却被判无加工项」。</p>
     */
    @SuppressWarnings("unchecked")
    public static List<OrderDetailResponse.ProcessingItemBrief> extractProcessingItems(
            ObjectMapper objectMapper, Object processingInfo) {
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
                // issue #3666：必须走**十进制**解析——旧 toInteger() 把 per_area 的 8.4 截断成 8，
                // 详情/列表按截断值重算加工费（30×8=240.00）与外层落库 processingFee（252.00）
                // 自相矛盾。（issue #4882 起不再解析 unitPrice / amount：加工费只有 processingFee 一处口径。）
                brief.setQuantity(toBigDecimal(entry.get("quantity")));
                result.add(brief);
            }
            return result;
        } catch (ClassCastException e) {
            log.warn("processingInfo 结构异常，按无加工项处理: {}", e.getMessage());
            return Collections.emptyList();
        }
    }

    /** {@code Object → BigDecimal}（十进制解析，不经过 double 截断）。 */
    public static BigDecimal toBigDecimal(Object value) {
        if (value == null) return null;
        if (value instanceof BigDecimal) return (BigDecimal) value;
        if (value instanceof Number) return BigDecimal.valueOf(((Number) value).doubleValue());
        try {
            return new BigDecimal(String.valueOf(value));
        } catch (NumberFormatException e) {
            return null;
        }
    }
}
