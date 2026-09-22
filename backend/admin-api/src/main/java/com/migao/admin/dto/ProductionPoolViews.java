package com.migao.admin.dto;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.List;

/**
 * 待派池与成批预览读面（issue #5169 = 阶段 2b-1）。
 *
 * <h2>池的定义（唯一口径，写在这里一次）</h2>
 * 「已确认支付（{@code orders.status = 'confirmed'}）且**无活跃加工单**的订单」，
 * 按**物料**（商品 × 颜色 × 门幅）分组可见。物料键 = {@code productId × skuCode}
 * —— {@code skuCode}（{@code processing_info.sku}）在本系统里正是「颜色 × 门幅」的组合，
 * 故不需要第二个键。
 *
 * <h2>池的最小单位是「订单 × 明细行」，成批派单的单位是「订单」</h2>
 * 一张单的两条明细行可能落在**两个物料组**里（布 + 纱）—— 池视图按行分组可见，
 * 而派单入参是**订单号列表**（「一单一加工单」是既有约束，本单不改，见
 * {@code uk_processing_orders_active}）。⇒ 从 A 组勾选一张单，会把它的 B 组行一起派出去，
 * 这是「一单一单」约束的必然结果，**不是**缺陷：本单的成批 = **一次动作批量生成多张加工单**。
 *
 * <h2>为什么金额/米数一律 {@link BigDecimal}</h2>
 * 同 {@link BatchStockViews}：米数是 1 位小数（V115/#5063），转 double 会在 2.7 这种地方露馅。
 */
public final class ProductionPoolViews {

    private ProductionPoolViews() {
    }

    /**
     * 池内一行 = 一个订单明细行（订单 × 物料）。
     *
     * @param requiredMeters **公式口径**需求米数（{@code toStockScaleByCeiling(order_items.quantity)}，
     *                       与销售账扣减、批次台账 {@code formula_meters} **同一函数**）——
     *                       池视图显示的就是「这单要多少米」，**不是**排料后的应领米数
     *                       （排料结果要等成批求解才有，见 {@link Preview}）。
     * @param waitingSince   进池时间的**载体**（{@code orders.created_at}，见 {@link #waitHours}）
     * @param waitHours      已在池里等了多久（小时，1 位小数）
     * @param overdue        {@code waitHours > maxWaitHours} ⇒ **超上限**（必须可行动，不得静默压单）
     */
    public record PoolLine(
            String orderId,
            String orderNo,
            String itemId,
            String productId,
            String productName,
            String skuCode,
            BigDecimal requiredMeters,
            OffsetDateTime waitingSince,
            BigDecimal waitHours,
            boolean overdue) {
    }

    /**
     * 一个物料分组（商品 × 颜色 × 门幅）里的待派行。
     *
     * @param materialKey 分组键（{@code productId|skuCode}；机器可判，便于前端折叠/筛选）
     * @param orderCount  **去重后**的订单数（一张单同物料两行只算一张）
     */
    public record PoolGroup(
            String materialKey,
            String productId,
            String skuCode,
            int orderCount,
            BigDecimal requiredMeters,
            List<PoolLine> lines) {
    }

    /**
     * 超上限的告警行（「不得静默压单」的可行动面）。
     *
     * <p>{@code message} 是可执行的话（谁、等了多久、该做什么），不是「有 N 条超时」这种数不清对象的汇总。</p>
     */
    public record PoolWarning(
            String orderId,
            String orderNo,
            BigDecimal waitHours,
            String message) {
    }

    /**
     * 待派池视图（看板数据面）。
     *
     * @param maxWaitHours   本次生效的滞留上限（**回口径**：读的人不必猜阈值是多少）
     * @param poolingEnabled 池化开关当前是否开启（本单缺省 = {@code false}，见
     *                       {@code ProcessingOrderService.POOLED_DEFAULT_ENABLED}）—— 池**看得见**
     *                       不等于**已开启**，两者分开报，免得把「有池视图」读成「已经在池化派单」
     * @param overdueCount   超上限的订单数；{@code > 0} ⇒ 看板必须显示 {@link #warnings}
     */
    public record Pool(
            BigDecimal maxWaitHours,
            boolean poolingEnabled,
            int orderCount,
            int lineCount,
            int overdueCount,
            List<PoolWarning> warnings,
            List<PoolGroup> groups) {
    }

    /**
     * 成批预览（判据 4「预览不说谎」的口径面）。
     *
     * <h2>四个米数的关系（全部同源：与真正派单**同一个** {@code plan} 求解器）</h2>
     * <ul>
     *   <li>{@code formulaMeters} = Σ **公式口径**（逐单公式米数）—— 预览的对照基线；</li>
     *   <li>{@code pooledPlannedMeters} = 跨订单成组后的**应领**合计（池级求解）；</li>
     *   <li>{@code savedMeters} = {@code formulaMeters − pooledPlannedMeters} ——
     *       🔴 与派单后落账的 {@code Σ saved_meters}（= {@code Σ(formula_meters − planned_meters)}）
     *       **逐值相等**：两边是同一个数，不是两套口径（判据 4）。</li>
     *   <li>{@code perOrderPlannedMeters}（对照读数）= **逐单派**的应领合计；
     *       {@code poolingGainMeters = perOrderPlannedMeters − pooledPlannedMeters} =
     *       **池化新增**的收益。分开报的理由：{@code savedMeters} 里有一部分是 #5158 已有
     *       的「单订单内并排」省下来的 —— 把两者混成一个数就会把旧收益算成池化的功劳。</li>
     * </ul>
     * <p>预览是**只读**的（不落台账、不建加工单），但它跑的是与派单**同一条**求解路径；
     * 因此它同样 fail-closed：池级累计余量不足 ⇒ 显式报错（不静默给一份派不出去的方案）。</p>
     *
     * @param assignmentRule 本次生效的指派规则（{@code fifo} / {@code best_fit}；
     *                       {@code null} = 调用方没传 ⇒ 未指定批次的行**不补位**）
     */
    public record Preview(
            int orderCount,
            String assignmentRule,
            BigDecimal formulaMeters,
            BigDecimal pooledPlannedMeters,
            BigDecimal savedMeters,
            BigDecimal perOrderPlannedMeters,
            BigDecimal poolingGainMeters) {
    }
}
