package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;

/**
 * 工人端发货页的「全部套都完工」待发货列表（issue #7761）—— <b>只读聚合面</b>。
 *
 * <h2>用户裁定（2026-10-25 逐字）</h2>
 * <p>「发货工人要能看到全部完结的订单列表，即订单内的多套窗帘全完工的数据。支持工人对完工的订单
 * 进行发货标签打印，包含客户的收货信息，走哪个物流/快递方式和公司」</p>
 *
 * <h2>三条判据都**直接消费既有单一实现**（本类不新增任何判据）</h2>
 * <table border="1">
 *   <caption>口径来源</caption>
 *   <tr><th>这一行能不能出现在列表里</th><th>判据出处（唯一一份）</th></tr>
 *   <tr><td>订单处于**可发货状态**（{@code confirmed/producing/packed}）</td>
 *       <td>{@link OrderShipmentService#SHIPPABLE_FROM}（与工人发货端点、商家长途**同一份**）</td></tr>
 *   <tr><td>**多套全部完工**（{@code completed_sets == total_sets > 0}）</td>
 *       <td>{@link ProcessingSetReadService#setCompletionByOrderIds}（套级 {@code completed} 的同一份计算）</td></tr>
 *   <tr><td>作业单已完工（发货守卫读的那张单也是它）</td>
 *       <td>活跃加工单 {@code status == 'completed'} —— 与 {@code ProcessingOrderMapper.countCompletedByOrderId}
 *           同白名单（{@code selectActiveByOrderIds} 只回非取消态 + 未软删）</td></tr>
 * </table>
 * <p>⇒ <b>「看得见 = 发得出去」</b>：列表就是发货端点会接受的集合，再按「全完工」收窄。
 * 反过来，可见列表里出现一张发不出去的单（或反过来有单可发却不在列表里），都意味着上面三处之一被改了。</p>
 *
 * <h2>为什么**不**包含「无作业单 / 无需报工」的订单</h2>
 * <p>它们的生产**没有可完工的套**（{@code total_sets == 0}），把它算成「全完工」是把
 * 「没有这件事」说成「这件事做完了」—— 本仓最忌的静默错误（同 {@code isCompleted} 的空套口径）。
 * 这类订单走原有发货路径；本列表的语义严格是「**车间把这单的多套都做完了**」。</p>
 *
 * <h2>边界（如实登记）</h2>
 * <ul>
 *   <li><b>候选扫描有上限</b>（{@link #CANDIDATE_SCAN_LIMIT}）：响应带
 *       {@code scan.truncated}，**截断不静默**（与 {@code ProductionTodoService} 同纪律）。</li>
 *   <li>「完工」= **套级工序报满**；**不含**商家手工确认、质检结论（质检是另一条面，issue #7162）。</li>
 *   <li>不做关键词筛选 / 分页：本租户同时处于 {@code confirmed/producing/packed} 的单量级是「几十」，
 *       一次全给比翻页更好用（工人现场要的是"今天能发哪些"）；超出扫描上限时按最新在前截断并显式标记。</li>
 * </ul>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class WorkerShipmentReadyService {

    /** 候选订单扫描上限（与 {@code ProductionTodoService} 同量级；超出 ⇒ {@code scan.truncated = true}）。 */
    public static final int CANDIDATE_SCAN_LIMIT = 200;

    /**
     * 物流类型 → 中文展示名（V47 / issue #3984 的列词汇：{@code express} 快递 / {@code logistics} 物流专线）。
     *
     * <p>为什么由服务端给：发货标签是**工人看得懂的纸面**，{@code express} 这类内部键不得上屏
     * （商家可见面的同一条纪律，见 {@code docs/design/user-facing-copy-standard.md}）。
     * 前端的同名字典（{@code frontend/admin-web/src/lib/logistics.ts}）服务的是商家侧表单选项，
     * 与这里是**同一份列词汇的两个投影** —— 出现第三个取值时两侧都要补，判据见
     * {@code WorkerShipmentReadyOrdersTest} 的「未知取值不编造」。</p>
     */
    private static final Map<String, String> LOGISTICS_TYPE_LABELS = Map.of(
            "express", "快递",
            "logistics", "物流专线");

    private final OrderMapper orderMapper;
    private final ProcessingSetReadService processingSetReadService;
    /**
     * 订单明细（issue #7856）：50×70 发货标签要印**帘种**与**安装信息**，两者都是**部位级**事实
     * （一行 = 一扇窗）⇒ 必须取明细；与 {@code ProcessingOrderService} / {@code OrderShipGuard}
     * 同一条取数路径（走 BaseMapper，{@code processing_info} 才会经 {@code JacksonTypeHandler} 反序列化成 Map）。
     */
    private final OrderItemMapper orderItemMapper;
    /** {@code processing_info} 可能是 JSON **字符串**（自定义 {@code @Select} 路径）⇒ 复用既有归一实现。 */
    private final ObjectMapper objectMapper;

    /**
     * 全完工待发货列表。
     *
     * <pre>
     * {
     *   "total": 2,
     *   "items": [{
     *     "order_id", "order_no", "status", "status_label", "created_at",
     *     "customer_name", "customer_phone", "customer_address",     // 收货信息（建单时采集，纸面直接可打）
     *     "logistics_type", "logistics_type_label", "logistics_company",
     *     "total_sets", "completed_sets",
     *     "processing_order_no", "remark",
     *     "curtain_types", "install_community", "install_rooms"   // 安装信息（issue #7856；缺值不下发）
     *   }],
     *   "scan": {"limit": 200, "truncated": false}
     * }
     * </pre>
     */
    public Map<String, Object> listReadyOrders(Long tenantId) {
        List<Order> candidates = candidates(tenantId);
        boolean truncated = candidates.size() > CANDIDATE_SCAN_LIMIT;
        if (truncated) {
            candidates = new ArrayList<>(candidates.subList(0, CANDIDATE_SCAN_LIMIT));
        }
        Map<String, Map<String, Object>> completion = processingSetReadService.setCompletionByOrderIds(
                candidates.stream().map(Order::getId).toList(), tenantId);

        List<Map<String, Object>> items = new ArrayList<>();
        List<Order> listed = new ArrayList<>();
        for (Order order : candidates) {
            Map<String, Object> sets = completion.get(order.getId());
            if (!allSetsCompleted(sets)) {
                continue;
            }
            listed.add(order);
        }
        // 安装信息（issue #7856）：帘种 / 安装位置 / 安装小区都要按单看明细 ⇒ **一次批量取**
        // （不逐单查 = 不 N+1），且只为**已进列表**的单取。
        Map<String, List<OrderItem>> itemsByOrder = loadOrderItemsByOrder(
                listed.stream().map(Order::getId).toList(), tenantId);
        for (Order order : listed) {
            items.add(rowView(order, completion.get(order.getId()),
                    itemsByOrder.getOrDefault(order.getId(), List.of())));
        }

        Map<String, Object> scan = new LinkedHashMap<>();
        scan.put("limit", CANDIDATE_SCAN_LIMIT);
        scan.put("truncated", truncated);

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("total", items.size());
        result.put("items", items);
        result.put("scan", scan);
        return result;
    }

    /**
     * 「多套全完工」= 有套 + 全部套完工 + 作业单已完工（发货守卫读的那张单）。
     *
     * <p>三种不满足各自是**不同的事实**，但对外只有一个出口（不进列表）：
     * 没有套（无作业单）、有套但有没做完的、套都做完了但作业单状态还没跟上（{@code status != completed}
     * ⇒ 发货端点会拒）—— 最后一种**不放过**：列表里出现一张点了发货会报错的单，比少一张更坏。</p>
     */
    private static boolean allSetsCompleted(Map<String, Object> sets) {
        if (sets == null) {
            return false;
        }
        Object total = sets.get("total_sets");
        Object completed = sets.get("completed_sets");
        if (!(total instanceof Integer totalCount) || !(completed instanceof Integer doneCount)) {
            return false;
        }
        return totalCount > 0 && totalCount.equals(doneCount)
                && "completed".equals(sets.get("processing_order_status"));
    }

    /** 候选 = 本租户、未软删、处于可发货状态的订单（最新在前；多取一条用于判定截断）。 */
    private List<Order> candidates(Long tenantId) {
        if (tenantId == null) {
            return List.of();
        }
        QueryWrapper<Order> wrapper = new QueryWrapper<Order>()
                .eq("tenant_id", tenantId)
                .eq("deleted", 0)
                .in("status", OrderShipmentService.SHIPPABLE_FROM)
                .orderByDesc("created_at")
                .orderByDesc("id")
                .last("LIMIT " + (CANDIDATE_SCAN_LIMIT + 1));
        List<Order> rows = orderMapper.selectList(wrapper);
        return rows == null ? List.of() : rows;
    }

    /**
     * 一行 = 一张单的全部纸面事实（发货标签读的就是这些键，不再回查）。
     *
     * <h3>50×70 发货标签的安装信息三键（issue #7856；用户 2026-10-26 逐字需求）</h3>
     * <p>「水洗唛，成品出库单，发货联上还缺了一个信息，窗帘的安装位置…还有客户要求我们备注窗帘未来
     * 安装给哪个小区」｜「这些水洗唛，入库单，发货联标签都要加上帘种，和安装信息」。</p>
     * <table border="1">
     *   <caption>键与口径</caption>
     *   <tr><th>键</th><th>值</th><th>来源 / 顺序</th></tr>
     *   <tr><td>{@code curtain_types}</td>
     *       <td>该单**全部部位**的帘种，去重后 {@code /} 连接（例 {@code 布帘/纱帘}）</td>
     *       <td>列 {@code order_items.curtain_type}，顺序 = **部位序**</td></tr>
     *   <tr><td>{@code install_community}</td>
     *       <td>安装小区（订单级语义）</td>
     *       <td>{@code processing_info.installCommunity}，**读侧收敛取第一条非空**（写侧扇出到每行同值）</td></tr>
     *   <tr><td>{@code install_rooms}</td>
     *       <td>该单全部部位的安装位置，去重后 {@code /} 连接（例 {@code 主卧/客厅/阳台}）</td>
     *       <td>{@code processing_info.installRoom}（件级），顺序 = **部位序**</td></tr>
     * </table>
     * <p>🔴 <b>缺值不下发该键</b>（不是空串、不是 {@code —}）⇒ 前端「缺值不印」：不印空行，
     * 也不印孤立的分隔符（{@code /主卧} 这类）。顺序**只由部位序决定**（去重保留首次出现的位置），
     * 不排序 —— 纸面要与加工单上的部位顺序一致，排序就是第二份口径。</p>
     */
    private Map<String, Object> rowView(Order order, Map<String, Object> sets, List<OrderItem> orderItems) {
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("order_id", order.getId());
        row.put("order_no", order.getOrderNo());
        row.put("status", order.getStatus());
        row.put("status_label", OrderStatusTransitions.label(order.getStatus()));
        row.put("created_at", order.getCreatedAt());
        // 收货信息（建单采集；缺值原样 null —— 纸面按「—」处理，绝不补默认值）
        row.put("customer_name", order.getCustomerName());
        row.put("customer_phone", order.getCustomerPhone());
        row.put("customer_address", order.getCustomerAddress());
        row.put("logistics_type", order.getLogisticsType());
        row.put("logistics_type_label", logisticsTypeLabel(order.getLogisticsType()));
        row.put("logistics_company", order.getLogisticsCompany());
        row.put("total_sets", sets.get("total_sets"));
        row.put("completed_sets", sets.get("completed_sets"));
        row.put("processing_order_no", sets.get("processing_order_no"));
        row.put("remark", order.getRemark());
        // 安装信息（issue #7856）：服务端拼装好的**展示串**（前端只渲染，缺值不印）。
        putIfPresent(row, "curtain_types", joinDistinct(curtainTypesOf(orderItems)));
        putIfPresent(row, "install_community", OrderInstallInfo.firstCommunity(orderItems, objectMapper));
        putIfPresent(row, "install_rooms", joinDistinct(installRoomsOf(orderItems)));
        return row;
    }

    /**
     * 批量取明细并按订单分组（保持取数序）。
     *
     * <p>⚠️ <b>不加 {@code ORDER BY}</b>：本列表的「部位序」必须与加工单快照同一份取数序
     * （{@code ProcessingOrderService.loadOrderItems} 与 {@code OrderShipGuard.loadOrderItems}
     * 都只按 {@code order_id + tenant_id + deleted} 过滤）—— 这里另加一种排序，标签上的帘种 / 位置
     * 顺序就会与加工单上的部位顺序不一致，而那是「两张纸对不上」的静默错误。</p>
     */
    private Map<String, List<OrderItem>> loadOrderItemsByOrder(List<String> orderIds, Long tenantId) {
        if (orderIds == null || orderIds.isEmpty()) {
            return Map.of();
        }
        List<OrderItem> rows = orderItemMapper.selectList(new LambdaQueryWrapper<OrderItem>()
                .in(OrderItem::getOrderId, orderIds)
                .eq(OrderItem::getTenantId, tenantId)
                .eq(OrderItem::getDeleted, 0));
        Map<String, List<OrderItem>> grouped = new LinkedHashMap<>();
        if (rows != null) {
            for (OrderItem row : rows) {
                grouped.computeIfAbsent(row.getOrderId(), key -> new ArrayList<>()).add(row);
            }
        }
        return grouped;
    }

    /** 该单全部部位的帘种（部位序；缺值原样进列表，由 {@link #joinDistinct} 丢弃）。 */
    private static List<String> curtainTypesOf(List<OrderItem> orderItems) {
        List<String> types = new ArrayList<>();
        for (OrderItem item : orderItems) {
            types.add(item.getCurtainType());
        }
        return types;
    }

    /** 该单全部部位的安装位置（部位序；件级 = 一扇窗一个值）。 */
    private List<String> installRoomsOf(List<OrderItem> orderItems) {
        List<String> rooms = new ArrayList<>();
        for (OrderItem item : orderItems) {
            rooms.add(OrderInstallInfo.valueOf(item.getProcessingInfo(),
                    OrderInstallInfo.KEY_INSTALL_ROOM, objectMapper));
        }
        return rooms;
    }

    /**
     * 去重 + {@code /} 连接（**顺序 = 部位序**，去重保留首次出现的位置）。
     *
     * <p>空白 / 缺值不占位；全空 ⇒ {@code null}（调用方据此**不下发该键**）。</p>
     */
    static String joinDistinct(List<String> values) {
        LinkedHashSet<String> distinct = new LinkedHashSet<>();
        for (String value : values) {
            if (value != null && !value.isBlank()) {
                distinct.add(value.trim());
            }
        }
        return distinct.isEmpty() ? null : String.join("/", distinct);
    }

    /** 只在有值时才放键（缺值不下发 —— 前端据此「不印」，而不是印一行空的）。 */
    private static void putIfPresent(Map<String, Object> row, String key, String value) {
        if (value != null && !value.isBlank()) {
            row.put(key, value);
        }
    }

    /**
     * 物流类型 → 中文（{@code null} / 未知取值 ⇒ {@code null}，**不编造**成「快递」）。
     *
     * <p>为什么不沿用前端 {@code logistics.ts} 的「未知回退快递」：那是**表单默认值**的语义
     * （新建物流记录时给个可改的初值）；纸面不同 —— 把没采集的物流方式印成「快递」，
     * 现场就会按快递发，而客户要的是物流专线（四季安等）。</p>
     */
    public static String logisticsTypeLabel(String logisticsType) {
        return logisticsType == null ? null : LOGISTICS_TYPE_LABELS.get(logisticsType);
    }
}
