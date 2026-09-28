package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.entity.ProcessingPositionOperation;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import com.migao.admin.mapper.ProcessingPositionOperationMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

/**
 * 生产概览（**待办优先**，issue #5641）：一屏回答「今天要处理的 N 件事」。
 *
 * <p>本类是**只读聚合面**：不写库、不带 {@code @Transactional}、不改任何既有列/键。
 * 它**不产生任何新判据** —— 每一类待办都直接消费既有判据实现（这是本单最重要的一条纪律）：
 * 自己再写一份 SQL / 再设一个阈值，就是「同一真值两处投影」，两处迟早不同。</p>
 *
 * <h2>四类口径（与 issue #5641 评论区的「前置数据存活性校验」逐条对齐）</h2>
 * <table border="1">
 *   <caption>待办类型</caption>
 *   <tr><th>类型</th><th>判据（确定性）</th><th>判据出处（唯一一份）</th></tr>
 *   <tr><td>{@code stuck} 卡在哪</td>
 *       <td>没开工 + 立即前道已完成 + 等待 &gt; {@code T_wait}</td>
 *       <td><b>直接消费</b> {@link ProductionStuckPointService#report} 的 {@code stuck} 行
 *           （阈值与其来源 {@code threshold_source} 一并透传，本类**不另设阈值、不重算时长**）</td></tr>
 *   <tr><td>{@code to_schedule} 待排产</td>
 *       <td>订单已确认 + 该单<b>活跃工序实例数 = 0</b> + 含加工项</td>
 *       <td>「含加工项」读 {@link OrderService#hasProcessingItems}（与发货守卫同一份解析）</td></tr>
 *   <tr><td>{@code to_ship} 待发货</td>
 *       <td>含加工项 + 加工单已完成 + 订单未发货</td>
 *       <td><b>直接消费</b> {@link OrderService#isProcessingReadyForShip}（= issue #3340 发货守卫，
 *           {@code assertProcessingCompletedBeforeShip} 是它的抛异常外壳）</td></tr>
 *   <tr><td>在制进度（三态）</td>
 *       <td>{@code not_started} / {@code in_progress} / {@code completed} 计数</td>
 *       <td>{@code report} 的 {@code states} 键**原样透传**；{@code in_progress}
 *           <b>只作进度、不作告警</b>（A 模式没有可靠完工信号 ⇒ 拿它当卡点会误报正在干的活）</td></tr>
 * </table>
 *
 * <p><b>「待打包」不做</b>：订单状态机（{@code OrderService.STATUS_TRANSITIONS}）里只有
 * {@code shipped}、没有 {@code packed} ⇒ 打包语义未落码（关联 #4347）⇒ 前置语义不存在，
 * 不是排序问题。本类因此**没有**任何 {@code packed} 分支。</p>
 *
 * <h2>AI 化的克制口径（本单的价值主张）</h2>
 * <ul>
 *   <li><b>不编数字、不做生成式归因</b>：本类在**服务端规则引擎**里算出每一项，且每一条待办都带
 *       {@code criterion}（判据 id，取值见 {@link #CRITERION_TO_SCHEDULE} /
 *       {@link #CRITERION_STUCK} / {@link #CRITERION_TO_SHIP}）与 {@code evidence}（判据的
 *       实测数据：状态 / 计数 / 等待时长 / 阈值与来源）⇒「为什么是它」可逐条追溯，**无一条来自 LLM**。</li>
 *   <li><b>说不清的就不说</b>：拿不到判据数据时（例如卡点行挂不到订单）**不产出**该条待办 ——
 *       宁可漏报，也不给一个点不进去的假入口。</li>
 *   <li><b>前端只渲染</b>：所有文案（含「等了 N 小时」）与阈值都在服务端算好，前端不做二次判断
 *       （否则就是第二份口径）。</li>
 * </ul>
 *
 * <h2>第一屏 N 与第二屏计数为什么必然一致</h2>
 * <p>两者**取自同一个 list**：{@code todo_total} = {@code todos.size()}，{@code stats.by_type}
 * 在**构建这个 list 的同一个循环里**累加 ⇒ 不可能是两次查询的结果（「第一屏 N 件、点进去 M 件」
 * 在此结构下无法发生）。</p>
 *
 * <h2>边界（如实登记）</h2>
 * <ul>
 *   <li><b>候选订单扫描有上限</b>（{@link #CANDIDATE_SCAN_LIMIT}，每类一条查询）⇒ 响应带
 *       {@code stats.scan.truncated}，**截断不静默**（与既有 {@code qty_source} /
 *       {@code threshold_source} 同族纪律）。</li>
 *   <li><b>每条候选订单一次明细查询</b>：{@code hasProcessingItems} 走订单明细（判据唯一性的代价）。
 *       实际候选量是「已确认 / 生产中」的订单，通常个位数；上限由 {@code CANDIDATE_SCAN_LIMIT} 兜住。</li>
 *   <li><b>卡点行挂不到订单时丢弃</b>（见上「说不清就不说」）：卡点报表的判据本身不含订单层信息，
 *       需经 加工单 → 订单 关联；关联不上就不报。</li>
 * </ul>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class ProductionTodoService {

    /** 待办类型 · 待排产（订单已确认 + 工序实例数为 0）。 */
    public static final String TYPE_TO_SCHEDULE = "to_schedule";

    /** 待办类型 · 卡在哪（没开工且等超阈值）。 */
    public static final String TYPE_STUCK = "stuck";

    /** 待办类型 · 待发货（加工单已完成 + 订单未发货）。 */
    public static final String TYPE_TO_SHIP = "to_ship";

    /** 判据 id · 待排产 = 订单已确认 + 该单活跃工序实例数为 0 + 含加工项。 */
    public static final String CRITERION_TO_SCHEDULE = "order_confirmed_without_operations";

    /** 判据 id · 卡在哪 = 没开工 + 立即前道已完成 + 等待超过阈值（判据与阈值均出自卡点服务）。 */
    public static final String CRITERION_STUCK = "stuck_not_started_over_threshold";

    /** 判据 id · 待发货 = 含加工项 + 加工单已完成 + 订单未发货（判据 = 发货守卫）。 */
    public static final String CRITERION_TO_SHIP = "processing_completed_order_not_shipped";

    /** 三类判据 id 的全集（机械凭据：每条待办的 {@code criterion} 必须落在此集合内）。 */
    public static final Set<String> CRITERIA = Set.of(
            CRITERION_TO_SCHEDULE, CRITERION_STUCK, CRITERION_TO_SHIP);

    /**
     * 候选订单扫描上限（**每类各一条查询**）。截断不静默：响应带 {@code stats.scan.truncated}。
     */
    public static final int CANDIDATE_SCAN_LIMIT = 50;

    /** 待排产候选状态 = 订单已确认（加工单尚未推进到 {@code producing}）。 */
    private static final List<String> SCHEDULE_CANDIDATE_STATUSES = List.of("confirmed");

    /** 待发货候选状态 = 未发货且可能已加工完成（订单状态机：confirmed/producing → shipped）。 */
    private static final List<String> SHIP_CANDIDATE_STATUSES = List.of("confirmed", "producing");

    private final ProductionStuckPointService stuckPointService;
    private final OrderService orderService;
    private final OrderMapper orderMapper;
    private final ProcessingOrderMapper processingOrderMapper;
    private final ProcessingPositionOperationMapper positionOperationMapper;

    /** 生产待办总览（挂钟版；生产路径用）。 */
    public Map<String, Object> overview(Long tenantId) {
        return overview(tenantId, OffsetDateTime.now());
    }

    /**
     * 生产待办总览（可注入 {@code now} ⇒ 「等了多久 / 卡不卡」在测试里确定复现）。
     * <b>包级可见</b>：只给同包测试注入挂钟。
     *
     * <pre>
     * {
     *   "generated_at": "...",
     *   "todo_total": 3,                       // 第一屏的 N（= todos.size()）
     *   "todos": [ {id, type, type_label, priority, title, reason,
     *               criterion, link, target:{...}, evidence:{...}} ],
     *   "stats": {                             // 第二屏（数字退到这里）
     *     "todo_total": 3,                     // 与第一屏**同一份 list**
     *     "by_type": {"stuck": n, "to_ship": n, "to_schedule": n},
     *     "operations": {"not_started": n, "in_progress": n, "completed": n},  // 三态进度（透传）
     *     "stuck_threshold_hours": 4.0, "threshold_source": "default",          // 阈值来源透传
     *     "scan": {"order_scan_limit": 50, "truncated": false}
     *   }
     * }
     * </pre>
     */
    Map<String, Object> overview(Long tenantId, OffsetDateTime now) {
        // ① 「卡在哪」+ 三态：**直接消费既有判据服务**（不写第二份 SQL、不另设阈值）
        Map<String, Object> stuckReport = stuckPointService.report(null, tenantId, now);
        List<Map<String, Object>> stuckRows = rowsOf(stuckReport.get("stuck"));

        // 卡点行只带加工单 ⇒ 批量解析 加工单 → 订单（不逐行查；判据本身一字不动）
        Map<String, String> orderIdByProcessingOrder = new LinkedHashMap<>();
        Map<String, String> orderNoById = new LinkedHashMap<>();
        resolveOrders(tenantId, stuckRows, orderIdByProcessingOrder, orderNoById);

        List<Map<String, Object>> todos = new ArrayList<>();
        Map<String, Integer> byType = new LinkedHashMap<>();
        byType.put(TYPE_STUCK, 0);
        byType.put(TYPE_TO_SHIP, 0);
        byType.put(TYPE_TO_SCHEDULE, 0);

        // ② 卡在哪（时长与阈值全部来自 ①，本类一个数都不算）
        for (Map<String, Object> row : stuckRows) {
            String processingOrderId = str(row.get("processing_order_id"));
            String orderId = processingOrderId == null ? null : orderIdByProcessingOrder.get(processingOrderId);
            if (orderId == null) {
                // 说不清的就不说：挂不到订单 ⇒ 不给点不进去的假入口
                continue;
            }
            todos.add(stuckTodo(row, orderId, orderNoById.get(orderId)));
            byType.merge(TYPE_STUCK, 1, Integer::sum);
        }

        // ③ 待发货：判据 = OrderService 发货守卫（含加工项 + 加工单已完成），唯一一份
        List<Order> shipCandidates = candidateOrders(tenantId, SHIP_CANDIDATE_STATUSES);
        boolean truncated = shipCandidates.size() >= CANDIDATE_SCAN_LIMIT;
        for (Order order : shipCandidates) {
            if (orderService.hasProcessingItems(order) && orderService.isProcessingReadyForShip(order)) {
                todos.add(toShipTodo(order));
                byType.merge(TYPE_TO_SHIP, 1, Integer::sum);
            }
        }

        // ④ 待排产：订单已确认 + 活跃工序实例数为 0（+ 含加工项 —— 无加工项时 instantiate 派生为空
        //    会 fail-closed ⇒ 那是假待办）
        List<Order> scheduleCandidates = candidateOrders(tenantId, SCHEDULE_CANDIDATE_STATUSES);
        truncated |= scheduleCandidates.size() >= CANDIDATE_SCAN_LIMIT;
        Map<String, Integer> instanceCountByOrder = liveInstanceCounts(tenantId, scheduleCandidates);
        for (Order order : scheduleCandidates) {
            if (instanceCountByOrder.getOrDefault(order.getId(), 0) > 0) {
                continue;
            }
            if (!orderService.hasProcessingItems(order)) {
                continue;
            }
            todos.add(toScheduleTodo(order));
            byType.merge(TYPE_TO_SCHEDULE, 1, Integer::sum);
        }

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("generated_at", now);
        // 🔴 第一屏的 N 与第二屏的计数**同一份来源**：都取自这个 list（不是两次查询）
        out.put("todo_total", todos.size());
        out.put("todos", todos);
        out.put("stats", stats(todos.size(), byType, stuckReport, truncated));
        return out;
    }

    // ============================================================ 第二屏（与第一屏同源）

    private Map<String, Object> stats(int todoTotal, Map<String, Integer> byType,
                                      Map<String, Object> stuckReport, boolean truncated) {
        Map<String, Object> stats = new LinkedHashMap<>();
        stats.put("todo_total", todoTotal);
        stats.put("by_type", byType);
        // 三态进度 + 阈值来源：**原样透传**卡点判据（本类不重算、不另设）
        stats.put("operations", stuckReport.get("states"));
        stats.put("stuck_threshold_hours", stuckReport.get("threshold_hours"));
        stats.put("threshold_source", stuckReport.get("threshold_source"));
        Map<String, Object> scan = new LinkedHashMap<>();
        scan.put("order_scan_limit", CANDIDATE_SCAN_LIMIT);
        scan.put("truncated", truncated);
        stats.put("scan", scan);
        return stats;
    }

    // ============================================================ 待办构造（每条都带判据与证据）

    private Map<String, Object> stuckTodo(Map<String, Object> row, String orderId, String orderNo) {
        Map<String, Object> operation = mapOf(row.get("operation"));
        Map<String, Object> predecessor = mapOf(row.get("predecessor"));
        Object stalledHours = row.get("stalled_hours");
        Object thresholdHours = row.get("threshold_hours");
        Object thresholdSource = row.get("threshold_source");
        String operationDisplay = display(operation);
        String no = orderNo != null ? orderNo : orderId;

        Map<String, Object> target = new LinkedHashMap<>();
        target.put("kind", "operation");
        target.put("id", operation.get("operation_id"));
        target.put("order_id", orderId);
        target.put("order_no", orderNo);
        target.put("set_no", row.get("set_no"));

        Map<String, Object> evidence = new LinkedHashMap<>();
        evidence.put("state", operation.get("state"));
        evidence.put("stalled_hours", stalledHours);
        evidence.put("threshold_hours", thresholdHours);
        evidence.put("threshold_source", thresholdSource);
        evidence.put("predecessor_done_at", predecessor.get("done_at"));

        return todo(TYPE_STUCK, "卡在哪", "high",
                "订单 " + no + (operationDisplay.isEmpty() ? "" : " · " + operationDisplay)
                        + " 上道做完后等了 " + hours(stalledHours) + " 小时没人领",
                "这道还没开工（没报过工），上一道已完成，已等待 " + hours(stalledHours)
                        + " 小时（超过阈值 " + hours(thresholdHours) + " 小时，来源：" + thresholdSource + "）",
                CRITERION_STUCK, productionPage(orderId), target, evidence);
    }

    private Map<String, Object> toShipTodo(Order order) {
        Map<String, Object> target = new LinkedHashMap<>();
        target.put("kind", "order");
        target.put("id", order.getId());
        target.put("order_no", order.getOrderNo());

        Map<String, Object> evidence = new LinkedHashMap<>();
        evidence.put("order_status", order.getStatus());
        evidence.put("has_processing_items", true);
        evidence.put("processing_completed", true);

        return todo(TYPE_TO_SHIP, "待发货", "high",
                "订单 " + orderLabel(order) + " 加工单已完成，可以发货了",
                "含加工项且加工单已完成，订单仍未发货（判据 = 发货守卫：含加工项须先完成加工单）",
                CRITERION_TO_SHIP, productionPage(order.getId()), target, evidence);
    }

    private Map<String, Object> toScheduleTodo(Order order) {
        Map<String, Object> target = new LinkedHashMap<>();
        target.put("kind", "order");
        target.put("id", order.getId());
        target.put("order_no", order.getOrderNo());

        Map<String, Object> evidence = new LinkedHashMap<>();
        evidence.put("order_status", order.getStatus());
        evidence.put("has_processing_items", true);
        evidence.put("operation_instance_count", 0);

        return todo(TYPE_TO_SCHEDULE, "待排产", "medium",
                "订单 " + orderLabel(order) + " 已确认，还没排产",
                "订单已确认且含加工项，但该单还没有任何工序实例，需要排产",
                CRITERION_TO_SCHEDULE, productionPage(order.getId()), target, evidence);
    }

    /**
     * 一条待办的统一形状。
     *
     * <p>{@code criterion} 是**机械凭据**：取值只可能落在 {@link #CRITERIA} 内（判据 id 而不是文案），
     * {@code evidence} 是判据的实测数据 —— 「每一条都能追到确定性判据、无一条来自 LLM」由此可核。</p>
     */
    private Map<String, Object> todo(String type, String typeLabel, String priority, String title,
                                     String reason, String criterion, String link,
                                     Map<String, Object> target, Map<String, Object> evidence) {
        Map<String, Object> item = new LinkedHashMap<>();
        item.put("id", type + ":" + target.get("id"));
        item.put("type", type);
        item.put("type_label", typeLabel);
        item.put("priority", priority);
        item.put("title", title);
        item.put("reason", reason);
        item.put("criterion", criterion);
        item.put("link", link);
        item.put("target", target);
        item.put("evidence", evidence);
        return item;
    }

    // ============================================================ 查询（全部带 tenantId：跨租户 fail-closed）

    /** 候选订单（按类各一条查询；`LIMIT` 上限见 {@link #CANDIDATE_SCAN_LIMIT}）。 */
    private List<Order> candidateOrders(Long tenantId, List<String> statuses) {
        List<Order> orders = orderMapper.selectList(new LambdaQueryWrapper<Order>()
                .eq(Order::getTenantId, tenantId)
                .eq(Order::getDeleted, 0)
                .in(Order::getStatus, statuses)
                .orderByDesc(Order::getCreatedAt)
                .orderByDesc(Order::getId)   // 同刻并列时结果仍确定（不随返回顺序漂移）
                .last("LIMIT " + CANDIDATE_SCAN_LIMIT));
        return orders == null ? List.of() : orders;
    }

    /** 卡点行 → 订单（只查一次；租户口径与卡点报表一致）。 */
    private void resolveOrders(Long tenantId, List<Map<String, Object>> stuckRows,
                               Map<String, String> orderIdByProcessingOrder,
                               Map<String, String> orderNoById) {
        Set<String> processingOrderIds = new LinkedHashSet<>();
        for (Map<String, Object> row : stuckRows) {
            String processingOrderId = str(row.get("processing_order_id"));
            if (processingOrderId != null) {
                processingOrderIds.add(processingOrderId);
            }
        }
        if (processingOrderIds.isEmpty()) {
            return;
        }
        for (ProcessingOrder po : nullSafe(processingOrderMapper.selectList(
                new LambdaQueryWrapper<ProcessingOrder>()
                        .eq(ProcessingOrder::getTenantId, tenantId)
                        .eq(ProcessingOrder::getDeleted, 0)
                        .in(ProcessingOrder::getId, processingOrderIds)))) {
            orderIdByProcessingOrder.put(po.getId(), po.getOrderId());
        }
        Set<String> orderIds = new LinkedHashSet<>();
        for (String orderId : orderIdByProcessingOrder.values()) {
            if (orderId != null) {
                orderIds.add(orderId);
            }
        }
        if (orderIds.isEmpty()) {
            return;
        }
        for (Order order : nullSafe(orderMapper.selectList(new LambdaQueryWrapper<Order>()
                .eq(Order::getTenantId, tenantId)
                .eq(Order::getDeleted, 0)
                .in(Order::getId, orderIds)))) {
            orderNoById.put(order.getId(), order.getOrderNo());
        }
    }

    /** 每张候选订单的**活跃**工序实例数（加工单 + 实例各一条批量查询）。 */
    private Map<String, Integer> liveInstanceCounts(Long tenantId, List<Order> orders) {
        Map<String, Integer> counts = new LinkedHashMap<>();
        if (orders.isEmpty()) {
            return counts;
        }
        Set<String> orderIds = new LinkedHashSet<>();
        for (Order order : orders) {
            orderIds.add(order.getId());
        }
        Map<String, String> orderIdByProcessingOrder = new LinkedHashMap<>();
        for (ProcessingOrder po : nullSafe(processingOrderMapper.selectList(
                new LambdaQueryWrapper<ProcessingOrder>()
                        .eq(ProcessingOrder::getTenantId, tenantId)
                        .eq(ProcessingOrder::getDeleted, 0)
                        .in(ProcessingOrder::getOrderId, orderIds)))) {
            orderIdByProcessingOrder.put(po.getId(), po.getOrderId());
        }
        if (orderIdByProcessingOrder.isEmpty()) {
            return counts;
        }
        for (ProcessingPositionOperation op : nullSafe(positionOperationMapper.selectList(
                new LambdaQueryWrapper<ProcessingPositionOperation>()
                        .eq(ProcessingPositionOperation::getTenantId, tenantId)
                        .eq(ProcessingPositionOperation::getDeleted, 0)
                        .in(ProcessingPositionOperation::getProcessingOrderId, orderIdByProcessingOrder.keySet())))) {
            String orderId = orderIdByProcessingOrder.get(op.getProcessingOrderId());
            if (orderId != null) {
                counts.merge(orderId, 1, Integer::sum);
            }
        }
        return counts;
    }

    // ============================================================ 纯函数

    /**
     * 工序显示名 = 卡点报表已算好的 {@code logical_name} + {@code position}
     * （**复用**它的派生，不在本类重算 —— 重算就是第二份展示口径）。
     */
    private static String display(Map<String, Object> operation) {
        String logicalName = str(operation.get("logical_name"));
        String position = str(operation.get("position"));
        if (logicalName == null) {
            return position == null ? "" : position;
        }
        return position == null ? logicalName : logicalName + " · " + position;
    }

    /** 生产页入口（后端给的是**可点即办**的落脚点；对象 id 由服务端拼，前端不判断）。 */
    private static String productionPage(String orderId) {
        return "/pages/production/index/index?orderId=" + orderId;
    }

    private static String orderLabel(Order order) {
        return order.getOrderNo() != null ? order.getOrderNo() : order.getId();
    }

    /** 小时展示（服务端格式化 ⇒ 前端不做二次计算）。 */
    private static String hours(Object value) {
        if (!(value instanceof Number number)) {
            return "?";
        }
        return String.format(Locale.ROOT, "%.1f", number.doubleValue());
    }

    private static String str(Object value) {
        if (value == null) {
            return null;
        }
        String text = String.valueOf(value);
        return text.isBlank() ? null : text;
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> mapOf(Object value) {
        return value instanceof Map<?, ?> map ? (Map<String, Object>) map : Map.of();
    }

    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> rowsOf(Object value) {
        if (!(value instanceof List<?> list)) {
            return List.of();
        }
        List<Map<String, Object>> rows = new ArrayList<>();
        for (Object item : list) {
            if (item instanceof Map<?, ?> map) {
                rows.add((Map<String, Object>) map);
            }
        }
        return rows;
    }

    private static <T> List<T> nullSafe(List<T> list) {
        return list == null ? List.of() : list;
    }
}
