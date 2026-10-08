package com.migao.admin.service;

import com.migao.admin.entity.OrderItem;
import com.migao.admin.entity.OrderShipmentItem;
import com.migao.admin.exception.BusinessException;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 发货写面的**两条不变式**（issue #6157）—— 判定本体，与「哪条路在调它」无关。
 *
 * <h2>为什么抽成独立本体（不是「为了好看」）</h2>
 * <p>本仓此前有**四条**能把订单写成 {@code shipped} 的写面（工人，{@code OrderShipmentService.ship}；
 * 商家生产，{@code OrderService.shipWithLogistics}；裸状态，{@code OrderService.updateOrderStatus}
 * 的 {@code confirmed|producing → shipped}；<b>以及将来任意第五条</b>）。判定若写在某一条路里，
 * 其余几条就**天然绕过**它 —— 实测（{@code acceptance/2026-10-03/shipments-sweep/out/p3-records.json}
 * 的 {@code M1-OVER}）：{@code quantity=10} 的订单传 {@code shipped_quantity=999} ⇒ HTTP 2xx、
 * {@code Σ已发=999}。⇒ 判定搬到本类，路由只负责「取数 → 调本类 → 把拒绝翻成 4xx」。</p>
 *
 * <h2>两条不变式</h2>
 * <ol>
 *   <li><b>累计已发 ≤ 订单量</b>（{@link #assertWithinOrderQuantity}）：按 {@code order_item_id}
 *       <b>聚合后</b>比较（同一行在一个请求里出现两次 = 合计语义，不是两次独立校验 ——
 *       实测 6+6 对 10 被放行）。两侧夹住：恰好等于上限放行，超一分拒绝。</li>
 *   <li><b>列精度不容吃数据</b>（{@link #assertDbCompatible}）：实发数量超过
 *       {@code numeric(10,2)} 的两位小数 ⇒ <b>拒绝</b>而不是静默四舍五入。
 *       实测（同 {@code out/} 的精度判据）：{@code shipped_quantity=0.001} 被列精度吃成
 *       {@code 0.00} 且仍 200 —— 「已发货但实发 0」。
 *       （{@code set_count}/{@code roll_count} 是 {@code INTEGER} 列，本层只收到已解析的整型 ⇒
 *       「上游用 {@code intValue()} 静默截断小数」这一形态本层判不出来，如实登记在 PR 的未固化项里。）</li>
 * </ol>
 *
 * <h2>它盖到哪几条发货路（台账在 {@code ShipmentInvariantGuardTest}，未登记即红）</h2>
 * <p>工人路（{@code OrderShipmentService.ship}）**带**这两条不变式；商家/生产路与裸状态路
 * （{@code PUT /orders/{id}/status}）**不带数量**（它们不落 {@code order_shipment_items}）⇒
 * 结构上无法承载第一条 —— 那两条的缺口（订单置 {@code shipped} 后在发货单链上不可见 = 漏单）
 * 由台账逐条具名登记「接受的缺口 + 重启条件」，**不**在这里静默放过。</p>
 *
 * <h2>为什么是 static 而不是 {@code @Component}</h2>
 * <p>与 {@link OrderShipGuard} 同一取舍：{@code OrderService} 是 16 依赖的
 * {@code @RequiredArgsConstructor} bean，而仓内有大量 {@code new OrderService(...)} /
 * {@code @InjectMocks} 的既有单测 —— 给它加构造依赖会波及全部那些测试。本类无状态、无生命周期，
 * 依赖（订单行 / 既有明细 / 本次请求行）由调用方从**它自己**的 Mapper 取好传进来。</p>
 *
 * <h2>与 {@link OrderShipGuard} 的分工</h2>
 * <p>后者管「<b>能不能发</b>」（含加工项订单必须先完成加工单，issue #3340 / #5842）；
 * 本类管「<b>发的数对不对</b>」。两条判据都必须在**任何写之前**跑。</p>
 */
public final class ShipmentInvariants {

    /**
     * {@code order_shipment_items.shipped_quantity} 的列口径 = {@code numeric(10,2)}
     * （见 {@code backend/admin-api/src/main/resources/db/init/schema.sql} 与
     * {@code db/migration/V133__create_order_shipments.sql}）。
     *
     * <p>⚠️ 这两个数是**列精度的单一事实源**：只用于「请求值是否会被列吃掉」的前置判定，
     * 不用于改写/裁剪任何用户输入（裁剪 = 静默改数）。</p>
     */
    public static final int QUANTITY_SCALE = 2;
    public static final int QUANTITY_PRECISION = 10;

    private ShipmentInvariants() {
    }

    // ══════════════════════════════════════════════════════════════════════════════
    // 入参形态：一次发货请求里的一行（**路由无关**）
    // ══════════════════════════════════════════════════════════════════════════════

    /**
     * 一次发货请求里的**一行**：{@code order_item_id} + 实发数量 + 单位 + 套/卷数。
     *
     * <p>{@code orderItemId} 允许为空（既有的合法形态：手写一行、没挂订单行的配件行 ——
     * 那种行没有上限可比，{@link #assertWithinOrderQuantity} 对它是 no-op；它仍受
     * 「数量为正 + 单位非空 + 列精度」三条约束）。</p>
     */
    public record ShipmentLine(String orderItemId, BigDecimal shippedQuantity, String unit,
                               Integer setCount, Integer rollCount) {
    }

    /** 被拒的原因（要能被路由翻成**可行动**的 4xx，而不是一句「参数错误」）。 */
    public record Rejection(String orderItemId, BigDecimal requested, BigDecimal allowed, String message) {
    }

    /**
     * 一次判定的结果（issue #6157）：两条不变式**各自**的逐条读数 + 汇总（累计已发）。
     *
     * <p>为什么要有这个 record 而不是让路由各调两个方法：它是一个**不可绕过的入口** ——
     * 路由只调 {@link #verdict} 并把 {@link #assertClean} 的结果落库，漏判任一条都会当场红
     * （两条空表 + 汇总三者一起返回，静默跳过其中一条在结构上看得见）。</p>
     */
    public record Verdict(List<Rejection> quantityRejections,
                          List<Rejection> precisionRejections,
                          Map<String, BigDecimal> cumulative) {

        /** 两条不变式都满足。 */
        public boolean isClean() {
            return quantityRejections.isEmpty() && precisionRejections.isEmpty();
        }
    }

    /**
     * 🔴 <b>一发定谳</b>：跑完两条不变式并返回逐条读数（**不抛**）—— 调用方用
     * {@link #assertClean} 把结果翻成 4xx，用 {@link Verdict#cumulative()} 落读面。
     */
    public static Verdict verdict(List<ShipmentLine> requestLines,
                                  List<OrderShipmentItem> alreadyShipped,
                                  List<OrderItem> orderItems) {
        return new Verdict(assertWithinOrderQuantity(requestLines, alreadyShipped, orderItems),
                assertDbCompatible(requestLines),
                cumulativeByOrderItem(requestLines, alreadyShipped));
    }

    /**
     * 🔴 <b>把判定结果翻成 4xx</b>：任一不变式不满足 ⇒ 抛（逐条具名），两条都满足 ⇒ 返回。
     *
     * <p>调用方在**任何写之前**调它 ⇒ 拒绝即零写。</p>
     */
    public static void assertClean(String action, Verdict verdict) {
        assertNoRejections(action, verdict.precisionRejections());
        assertNoRejections(action + "（累计实发上限）", verdict.quantityRejections());
    }

    // ══════════════════════════════════════════════════════════════════════════════
    // 不变式一：累计已发 ≤ 订单量（按 order_item_id 聚合）
    // ══════════════════════════════════════════════════════════════════════════════

    /**
     * 计算「本次请求后，每条订单行的累计已发」——**按 {@code order_item_id} 聚合后**。
     *
     * <p>聚合是这个判据的核心（issue #6157 的 P1-2）：同一 {@code order_item_id} 在一个请求里
     * 出现两行时，「每行各判一次」会被 6 + 6 = 12 对上限 10 绕过；唯一正确的语义是先求和再比。</p>
     *
     * @param requestLines 本次请求的全部行（含重复的 {@code order_item_id}）
     * @param alreadyShipped 该订单**已经落库**的实发明细（跨全部发货单）
     * @return {@code order_item_id → 累计实发}（请求里没给 id 的行不入表 —— 它们没有上限可比）
     */
    public static Map<String, BigDecimal> cumulativeByOrderItem(List<ShipmentLine> requestLines,
                                                               List<OrderShipmentItem> alreadyShipped) {
        Map<String, BigDecimal> cumulative = new LinkedHashMap<>();
        if (alreadyShipped != null) {
            for (OrderShipmentItem item : alreadyShipped) {
                if (item == null || item.getOrderItemId() == null) {
                    continue;
                }
                cumulative.merge(item.getOrderItemId(), amount(item.getShippedQuantity()), BigDecimal::add);
            }
        }
        if (requestLines != null) {
            for (ShipmentLine line : requestLines) {
                if (line == null || line.orderItemId() == null) {
                    continue;
                }
                cumulative.merge(line.orderItemId(), amount(line.shippedQuantity()), BigDecimal::add);
            }
        }
        return cumulative;
    }

    /**
     * 🔴 <b>累计已发 ≤ 订单量</b>（按 {@code order_item_id} 聚合后逐行成立）。
     *
     * <p>两侧夹住：恰好等于上限 ⇒ 放行（不拒绝「刚好发满」）；超出一分 ⇒ 拒绝并具名报出差额。
     * 订单行的量为空（存量脏数据）⇒ <b>不据此拦货</b>（无法判定，不把「读不懂」当「超发」）——
     * 该边界逐条登记在 PR 的未固化项里。</p>
     *
     * @param requestLines   本次请求的全部行
     * @param alreadyShipped 该订单**已经落库**的实发明细（跨全部发货单）
     * @param orderItems     该订单的订单行（上限来源 = {@code order_items.quantity}）
     * @return 空 = 全部满足；非空 = 逐条具名拒绝
     */
    public static List<Rejection> assertWithinOrderQuantity(List<ShipmentLine> requestLines,
                                                            List<OrderShipmentItem> alreadyShipped,
                                                            List<OrderItem> orderItems) {
        Map<String, BigDecimal> limits = new LinkedHashMap<>();
        for (OrderItem item : orderItems == null ? List.<OrderItem>of() : orderItems) {
            if (item != null && item.getId() != null) {
                limits.put(item.getId(), item.getQuantity());
            }
        }
        List<Rejection> rejections = new ArrayList<>();
        for (Map.Entry<String, BigDecimal> row : cumulativeByOrderItem(requestLines, alreadyShipped).entrySet()) {
            BigDecimal limit = limits.get(row.getKey());
            if (!limits.containsKey(row.getKey())) {
                // 不属于该订单的订单行 ⇒ fail-closed（不把「查不到上限」当「没有上限」）
                rejections.add(new Rejection(row.getKey(), row.getValue(), null,
                        "发货明细引用了订单里查不到的订单行（无法核对上限，已拒绝）：" + row.getKey()));
                continue;
            }
            if (limit == null) {
                // 订单行存在但**量是空**（存量脏数据）⇒ 无法判定 ⇒ 不据此拦货
                // （宁可漏判也不把「读不懂」当「超发」；该边界登记在 PR 的未固化项里）
                continue;
            }
            if (row.getValue().compareTo(limit) > 0) {
                rejections.add(new Rejection(row.getKey(), row.getValue(), limit, String.format(
                        "累计实发超过订单量：该订单行下单 %s，累计已发（含本次）%s，超出 %s —— "
                                + "一次发货请求里同一订单行的多行按**合计**计算，不接受超发",
                        plain(limit), plain(row.getValue()), plain(row.getValue().subtract(limit)))));
            }
        }
        return rejections;
    }

    // ══════════════════════════════════════════════════════════════════════════════
    // 不变式二：列精度不容吃数据
    // ══════════════════════════════════════════════════════════════════════════════

    /**
     * 🔴 <b>请求值必须能被列精度无损承载</b>：{@code shipped_quantity} 最多两位小数且不超过
     * {@code numeric(10,2)} 的量级；{@code set_count}/{@code roll_count} 必须是整数。
     *
     * <p>为什么是「拒绝」而不是「四舍五入到列精度」：列精度是 {@code numeric(10,2)}，
     * 把 {@code 0.001} 写进去 PG 会存成 {@code 0.00} —— 而 {@code 0} 与「没有这个数」是两件事
     * （同 {@code OrderShipmentItem} 的「缺值不填 0」口径）⇒「已发货但实发 0」。
     * 静默改数比报错贵得多。</p>
     */
    public static List<Rejection> assertDbCompatible(List<ShipmentLine> requestLines) {
        List<Rejection> rejections = new ArrayList<>();
        for (ShipmentLine line : requestLines == null ? List.<ShipmentLine>of() : requestLines) {
            if (line == null) {
                continue;
            }
            if (line.shippedQuantity() != null) {
                if (scaleOf(line.shippedQuantity()) > QUANTITY_SCALE) {
                    rejections.add(new Rejection(line.orderItemId(), line.shippedQuantity(), null, String.format(
                            "实发数量超出列精度（%s 位小数 > %d 位）：系统按 %.2f 存会把它变成 "
                                    + "另一个数（0.001 会变成 0.00 = 「已发货但实发 0」）⇒ 拒绝而不是静默改数",
                            scaleOf(line.shippedQuantity()), QUANTITY_SCALE, line.shippedQuantity())));
                } else if (integersOf(line.shippedQuantity()) > QUANTITY_PRECISION - QUANTITY_SCALE) {
                    rejections.add(new Rejection(line.orderItemId(), line.shippedQuantity(), null, String.format(
                            "实发数量超出列精度（整数位 %d > %d 位，列口径 numeric(%d,%d)）：%s",
                            integersOf(line.shippedQuantity()), QUANTITY_PRECISION - QUANTITY_SCALE,
                            QUANTITY_PRECISION, QUANTITY_SCALE, plain(line.shippedQuantity()))));
                }
            }
        }
        return rejections;
    }

    /**
     * 🔴 <b>把拒绝翻成对外的 4xx</b>（HTTP 422 = {@code BusinessException.validationError}，
     * 与仓内既有「参数不合法」同码），并逐条具名（哪一行 / 要了多少 / 允许多少）。
     *
     * <p>调用方在**任何写之前**调它 ⇒ 拒绝即零写。</p>
     */
    public static void assertNoRejections(String action, List<Rejection> rejections) {
        if (rejections == null || rejections.isEmpty()) {
            return;
        }
        StringBuilder message = new StringBuilder(action).append("被拒绝，共 ")
                .append(rejections.size()).append(" 处：");
        for (Rejection rejection : rejections) {
            message.append("\n· ").append(rejection.message());
        }
        message.append("\n（本次请求未写入任何数据；请修正后重试）");
        throw BusinessException.validationError(message.toString());
    }

    /**
     * 累计已发的**读面**（不判、只报）：把「该订单行已发了多少」变成可读的读数，
     * 供路由把「上限与已发」放进结果快照（发第二张发货单时前端/纸面要知道还剩多少）。
     */
    public static Map<String, Object> cumulativeView(List<ShipmentLine> requestLines,
                                                     List<OrderShipmentItem> alreadyShipped) {
        Map<String, Object> view = new LinkedHashMap<>();
        for (Map.Entry<String, BigDecimal> row : cumulativeByOrderItem(requestLines, alreadyShipped).entrySet()) {
            view.put(row.getKey(), row.getValue());
        }
        return view;
    }

    /**
     * 🔴 <b>订单未发余量</b>（issue #6171）—— 「还剩多少没发」，逐 {@code order_item_id}。
     *
     * <p>为什么在这里而不是在路由里：商家/生产发货路
     * （{@code POST /api/admin/production/orders/{orderId}/ship}）的请求体**只有运单号 / 承运商、
     * 没有数量** ⇒ 它的「实发数量」只有一个不编造的来源 = {@code 订单量 − 已发合计}，也就是
     * {@link #assertWithinOrderQuantity} 的另一半（一处立「不许超」，这里取「还剩多少」，
     * 共用同一份累计口径 {@link #cumulativeByOrderItem} ⇒ 两处不可能分叉）。</p>
     *
     * <p>口径（逐条可判，供商家路的实例判据直接消费）：</p>
     * <ul>
     *   <li>只对**有订单行 id**的行回答（手写/配件行没有上限，不属于本读面）——与
     *       {@link #cumulativeByOrderItem} 同一条跳过规则；</li>
     *   <li>{@code 订单量}为空（存量脏数据）⇒ 该行**不入表**（无法判定 ⇒ 不编一个数 ——
     *       调用方据此**拒绝**而不是记 {@code 0}）；</li>
     *   <li>负余量（已发 &gt; 订单量的存量脏数据）⇒ 夹到 {@code 0}（本读面只回答「还能发多少」，
     *       负数没有业务含义；「超发」这件事本身由 {@link #assertWithinOrderQuantity} 判）；</li>
     *   <li>返回顺序 = 订单行顺序（{@code orderItems} 的次序），便于逐行核对。</li>
     * </ul>
     *
     * @param requestLines   本次请求要发的行（商家路 = 空表：数量就是「全部余量」）
     * @param alreadyShipped 该订单**已经落库**的实发明细（跨全部发货单）
     * @param orderItems     该订单的订单行（上限来源 = {@code order_items.quantity}）
     * @return {@code order_item_id → 未发余量}（无法判定的行不出现）
     */
    public static Map<String, BigDecimal> remainingLines(List<ShipmentLine> requestLines,
                                                         List<OrderShipmentItem> alreadyShipped,
                                                         List<OrderItem> orderItems) {
        Map<String, BigDecimal> cumulative = cumulativeByOrderItem(requestLines, alreadyShipped);
        Map<String, BigDecimal> remaining = new LinkedHashMap<>();
        for (OrderItem item : orderItems == null ? List.<OrderItem>of() : orderItems) {
            if (item == null || item.getId() == null || item.getQuantity() == null) {
                continue;
            }
            BigDecimal left = item.getQuantity().subtract(amount(cumulative.get(item.getId())));
            remaining.put(item.getId(), left.compareTo(BigDecimal.ZERO) < 0 ? BigDecimal.ZERO : left);
        }
        return remaining;
    }

    // ══════════════════════════════════════════════════════════════════════════════
    // 内部
    // ══════════════════════════════════════════════════════════════════════════════

    private static BigDecimal amount(BigDecimal value) {
        return value == null ? BigDecimal.ZERO : value;
    }

    /** 有效小数位数（去掉尾随零：{@code 10.00} 是 0 位，不是 2 位）。 */
    static int scaleOf(BigDecimal value) {
        if (value == null) {
            return 0;
        }
        BigDecimal stripped = value.stripTrailingZeros();
        return Math.max(stripped.scale(), 0);
    }

    /** 整数位数（{@code 123.45} ⇒ 3）。 */
    static int integersOf(BigDecimal value) {
        if (value == null) {
            return 0;
        }
        return Math.max(value.precision() - value.scale(), 0);
    }

    private static String plain(BigDecimal value) {
        return value == null ? "—" : value.stripTrailingZeros().toPlainString();
    }
}
