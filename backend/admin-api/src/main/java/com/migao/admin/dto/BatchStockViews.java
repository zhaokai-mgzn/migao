package com.migao.admin.dto;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;

/**
 * 批次账读面视图（V116，issue #5145 阶段 1）。
 *
 * <p>四个读面（余量 / 分布 / 对账 / 派工候选）**全部在这里声明一次** —— 与
 * `StockLedgerController` 的只读口径一致：批次账的写入方在库存变更的既有实现点
 * （{@code StockBatchConsumptionService}），读面不经过写路径。</p>
 *
 * <p>金额/米数一律 {@link BigDecimal}（V115/#5063）：小数场景（如 2.7 米）必须逐值可比，
 * 不得在传输层被转成 double 再显示（那会在 2.7 → 2.6999999 这种地方露馅）。</p>
 */
public final class BatchStockViews {

    private BatchStockViews() {
    }

    /**
     * 批次余量（**派生** = 入库量 + Σ消耗）。
     *
     * <p>{@code inboundMeters} 是批次行上的原始入库量（**不可变**，V111）；
     * {@code consumedMeters} 是本单新增的消耗净额；{@code remainingMeters} 才是「这批还剩多少」。
     * 三者一起回，读的人不必自己减（也不会减错方向）。</p>
     */
    public record BatchRemaining(
            Long batchId,
            String batchNo,
            String productId,
            Long skuId,
            String skuCode,
            String inboundNo,
            String dyeLot,
            LocalDate receivedDate,
            BigDecimal unitCost,
            BigDecimal inboundMeters,
            BigDecimal consumedMeters,
            BigDecimal remainingMeters) {
    }

    /** 剩余量分布一档（{@code key} 机器可判、{@code label} 给人看） */
    public record Bucket(String key, String label, int batchCount, BigDecimal share) {
    }

    /**
     * 剩余量分布（**恒四档**：空档也回 0 —— 前端不必猜「没有这一档」是 0 还是缺数据）。
     *
     * <p>分档口径（{@code remaining} 与阈值的比较，边界取「右闭」）：
     * {@code ≤0.2} ⇒ r ≤ 0.2；{@code 0.2~0.5} ⇒ 0.2 &lt; r ≤ 0.5；{@code 0.5~1} ⇒ 0.5 &lt; r ≤ 1；
     * {@code >1} ⇒ r &gt; 1。<b>负余量（超扣）落在 {@code ≤0.2} 档</b>——它是「用尽」的极端，
     * 不该被单独藏起来。</p>
     */
    public record Distribution(int totalBatches, List<Bucket> buckets) {
    }

    /**
     * 对账一行（**路线 A 的交换条件**，issue #5145 判据 5；两项拆分见 issue #5158）。
     *
     * <p>差额恒等式（{@code reconciled} 就是它的可执行判据）——<b>拆成两项、分别可读</b>：</p>
     * <pre>
     *   diff = batchRemaining − skuStock
     *   soldUnbatched = soldDeducted − formulaDeducted − otherLedgerDelta − unbatched   // 已售未派
     *   planSaved     = formulaDeducted − dispatched                                     // 排料节省
     *   explainedDiff = soldUnbatched + planSaved
     *   diff == explainedDiff                                                            // ← reconciled
     * </pre>
     * <p>推导：{@code batchRemaining = 入库总米数 − 派工扣减}；
     * {@code skuStock = 入库总米数 − 销售已扣 + 其它台账净额 + 台账之外形成的库存}。
     * 两式相减即得。含义：{@code soldDeducted − dispatched} 这一项**混合了两件事**，
     * 必须拆开读 —— ①「顾客已付款扣了销售账、加工单还没派」；②「派工按排料结果扣、
     * 比公式米数少扣的那部分」；{@code unbatched} = **台账之外的库存**
     * （本功能上线前就存在的存量 / 建品时直接写 stock 的部分）——它**不是**差额的异常，
     * 是「这批库存从来没有批次来源」这个事实本身。</p>
     *
     * <p>🔴 <b>两项叠加逐值等于拆之前的总解释项</b>（{@code formulaDeducted} 在两项里一加一减
     * 抵消）⇒ 本单**只**把口径说清楚，没有放宽 {@code reconciled}：改前判 true 的账，
     * 改后仍判 true（改前判 false 的同样判 false）。这样「拆开」不会顺手把一条真判据改成恒真。</p>
     *
     * <p>🔴 <b>不许一项冒充另一项</b>：{@code planSaved} 只取「公式口径 − 排料口径」的差
     * （V119 的 {@code formula_meters − planned_meters}，落库值，不重算）；
     * 没有 `formula_meters` 的历史行回填为 {@code −delta} ⇒ 那部分恒为 0，
     * 于是历史差额**全部**归到「已售未派」（与改前读法一致，不冒功）。</p>
     */
    public record ReconcileRow(
            Long skuId,
            String skuCode,
            String productId,
            BigDecimal skuStock,
            BigDecimal batchRemaining,
            BigDecimal inboundMeters,
            BigDecimal dispatchedMeters,
            BigDecimal soldDeductedMeters,
            BigDecimal otherLedgerDeltaMeters,
            BigDecimal unbatchedMeters,
            BigDecimal diff,
            BigDecimal explainedDiff,
            /** 差额的第 1 项：**已售未派**（顾客已扣销售账、加工单还没派 / 公式口径之外的正常差额）。 */
            BigDecimal soldUnbatchedMeters,
            /** 差额的第 2 项：**排料节省**（{@code Σ formula_meters − Σ 派工扣减}，V119 / issue #5158）。 */
            BigDecimal planSavedMeters,
            /** 公式口径的派工扣减净额（拆分的枢轴；历史行回填为 {@code −delta} ⇒ 该腿恒等于 dispatched）。 */
            BigDecimal formulaDeductedMeters,
            boolean reconciled) {
    }

    /**
     * 对账读面（{@code totalDiff} = Σ差额；{@code unreconciledCount} > 0 ⇒ 恒等式不成立，须排查）。
     *
     * <p>{@code totalFormulaMeters} / {@code totalPlannedMeters} / {@code totalSavedMeters}（V119）
     * = 逐 SKU 口径的**汇总读面**：{@code totalSavedMeters} 必须与「逐加工单读面」
     * （{@code /stock-batches/consumptions} 逐行 {@code savedMeters} 求和）**逐值相等**
     * —— 两条路各自聚合的是同一批行、同一个列族，不许是两套口径。</p>
     */
    public record Reconcile(List<ReconcileRow> rows, BigDecimal totalDiff, int unreconciledCount,
                            BigDecimal totalFormulaMeters, BigDecimal totalPlannedMeters,
                            BigDecimal totalSavedMeters) {
    }

    /**
     * 派工候选批次（生成加工单时给文员选）。
     *
     * <p>{@code suggested} = 系统的**建议值**（阶段 1 = 朴素口径 {@code FIFO_RECEIVED_DATE}：
     * 入库日期早者优先，同日按 id）；{@code enough} = 该批次余量是否够本行米数。
     * <b>人工最终选择才是被记录的那一个</b>（用户裁定：系统给候选 + 建议值，人工确认、可改）。</p>
     */
    public record Candidate(
            String batchNo,
            BigDecimal remainingMeters,
            LocalDate receivedDate,
            String dyeLot,
            String inboundNo,
            BigDecimal unitCost,
            boolean suggested,
            boolean enough) {
    }

    /** 候选列表（{@code suggestionRule} 显式回口径，避免读的人以为这是 best-fit） */
    public record Candidates(String suggestionRule, String suggestedBatchNo, BigDecimal requiredMeters,
                             List<Candidate> candidates) {
    }
}
