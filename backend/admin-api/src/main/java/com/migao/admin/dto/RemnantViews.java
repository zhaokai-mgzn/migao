package com.migao.admin.dto;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.List;

/**
 * 余料回收读面视图（V122，issue #5146）。
 *
 * <p>与 {@link BatchStockViews} 同一条纪律：读面视图**在声明处只写一次**，
 * 写入方在 {@code RemnantService}（读面不经过写路径）；金额/米数一律 {@link BigDecimal}
 * （V115/#5063：小数场景必须逐值可比，不得在传输层退化成 double）。</p>
 *
 * <p>🔴 <b>本视图没有「余料值多少钱」这类字段</b>（除 {@code recoveredAmount} 这个
 * **用它的那张单**的成本冲减量之外）—— 余料不是资产（用户裁定），台账只记实物可用性。
 * 判据 = 加余料登记后库存金额逐值不变 + 余料两表不出现在任何库存/资产读面。</p>
 */
public final class RemnantViews {

    private RemnantViews() {
    }

    /**
     * 余料台账一行。
     *
     * @param pieceKind  {@code width}（门幅余料）/ {@code end}（端部余料）
     * @param status     {@code customer_taken} / {@code available} / {@code used} / {@code scrapped}
     * @param areaM2     面积（派生 = {@code lengthM × widthM}，不落库）
     */
    public record RemnantLine(
            Long id,
            Integer pieceSeq,
            String pieceKind,
            BigDecimal lengthM,
            BigDecimal widthM,
            BigDecimal areaM2,
            String sourceOrderNo,
            String sourceProcessingOrderNo,
            String sourceBatchNo,
            String dyeLot,
            String productId,
            String skuCode,
            String status,
            String usedByOrderNo,
            String usedByOrderItemId,
            String usedByItemKey,
            BigDecimal recoveredMeters,
            BigDecimal recoveredUnitCost,
            BigDecimal recoveredAmount,
            OffsetDateTime recoveredAt,
            String recoveredBy,
            String scrapReason,
            OffsetDateTime scrappedAt,
            String scrappedBy,
            OffsetDateTime createdAt) {
    }

    /**
     * 回收汇总（`余料回收率` 与 `报废率` 的分子分母 —— issue #5146「度量可算」）。
     *
     * <p>口径写在字段名里，读的人不必猜：
     * {@code recoveredAmountTotal} = Σ回收额（**用它的那些单**的成本冲减量之和）；
     * {@code issuedCostTotal} = Σ领料成本 = Σ(|{@code planned_meters}| × 当时均价)（源
     * {@code stock_batch_consumptions}，V119 随行快照）；
     * {@code recoveredMetersTotal} = Σ用掉米数；{@code scrappedMetersTotal} = Σ报废米数。</p>
     *
     * <p>🔴 {@code recoveryRate} / {@code scrapRate} 是**回给前端的分母为零时显式 null**
     * （不是 0 —— 0 会被读成「回收率是零」，而事实是「还没有数据可算」）。</p>
     */
    public record Summary(
            int availableCount,
            int usedCount,
            int scrappedCount,
            int customerTakenCount,
            BigDecimal availableMeters,
            BigDecimal recoveredMetersTotal,
            BigDecimal scrappedMetersTotal,
            BigDecimal recoveredAmountTotal,
            BigDecimal issuedCostTotal,
            BigDecimal recoveryRate,
            BigDecimal scrapRate) {
    }

    /**
     * 台账读面（列表 + 汇总**一次回** —— 度量与明细同行，前端不必发第二个请求，
     * 也就不会出现「列表与汇总各读一个时刻」的不一致）。
     */
    public record LedgerView(PageResponse<RemnantLine> page, Summary summary) {
    }

    /** 小件用料尺寸表的一行（§22 P3：{@code configured} = 这一项**本租户配过没有**） */
    public record SpecLine(
            String itemKey,
            BigDecimal lengthM,
            BigDecimal widthM,
            String note,
            String updatedBy,
            OffsetDateTime updatedAt) {
    }

    /**
     * 小件用料尺寸表读面。
     *
     * <p>🔴 {@code configured} = 本租户**有没有配过任何一行**。{@code false} ⇒ 余料匹配
     * **不产生任何推荐**（判据 4），且 {@code notice} 必须**非空**说明这件事
     * ——「没配」与「配了但没匹配上」对商家是两件完全不同的事，读面必须能分开。</p>
     */
    public record SpecsView(boolean configured, List<SpecLine> items, String notice) {
    }

    /** 一条匹配建议（判据 3：命中同缸号余料 ⇒ 该小件不新领料） */
    public record Recommendation(
            String itemKey,
            List<String> optionNames,
            Long remnantId,
            BigDecimal remnantLengthM,
            BigDecimal remnantWidthM,
            String sourceBatchNo,
            String dyeLot,
            boolean sameDyeLot,
            boolean sameSku,
            BigDecimal unitCost,
            BigDecimal recoverableMeters,
            BigDecimal recoverableAmount,
            String reason) {
    }

    /** 一条**没有**建议的小件需求（{@code reason} 必须能读 —— 不静默） */
    public record Unmatched(String itemKey, List<String> optionNames, String reason) {
    }

    /**
     * 匹配读面（本单「小件优先匹配」的全部对外语义）。
     *
     * <p>四个字段一起回答「为什么没有建议」：{@code notice} 是**全局**说明（未配置）；
     * {@code unconfiguredItems} 是**逐项**说明（这一项没配尺寸）；
     * {@code unmatched} 是**逐项**说明（配了但没装得下的余料）。
     * 三者都为空且 {@code recommendations} 非空 ⇒ 才有建议。</p>
     */
    public record MatchView(
            boolean configured,
            String notice,
            List<String> requiredItems,
            List<Recommendation> recommendations,
            List<Unmatched> unmatched,
            List<String> unconfiguredItems) {
    }
}
