package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.migao.admin.dto.ProductionPoolViews;
import com.migao.admin.entity.StockBatch;
import com.migao.admin.mapper.StockBatchConsumptionMapper;
import com.migao.admin.mapper.StockBatchMapper;
import org.springframework.util.StringUtils;

import java.math.BigDecimal;
import java.util.Collection;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 行级**库存可满足性**（issue #7091）—— 池读面与派工链路共用的**唯一**一份判据。
 *
 * <h2>为什么要独立成件（而不是各服务里再写一遍）</h2>
 * 「这一行有没有能裁出它的批次」被两处消费：派工前的 fail-closed 拒绝判据
 * （{@link StockBatchConsumptionService#suggestedBatchNo}）与池读面的行级标记（{@link #fill}）。
 * 两者必须用**同一份**余量派生点、**同一条** SKU 一致性口径（{@link #sameSku}）——
 * 各写一份必然漂移，而漂移的后果是「看板说能派、点下去被拒」（或反过来：明明能派却被标成不可派）。
 *
 * <p>🔴 **只读**：本类不扣批次、不写台账、不参与任何落账判据；只回答「有没有能裁出这一行的批次」。</p>
 */
public final class StockSatisfiability {

    private StockSatisfiability() {
    }

    /** 一个物料（商品 × 颜色/门幅）—— 批量判定的入参（同物料多行去重后只判一次）。 */
    public record MaterialDemand(String productId, String skuCode) {
    }

    /**
     * SKU 一致性口径（**唯一实现**）：两边都有值才比，缺一不算不一致。
     *
     * <p>派工三层共用一个口径：{@code StockBatchConsumptionService#plan} 的拒绝判据、
     * {@link StockBatchConsumptionService#suggestedBatchNo} 的候选过滤、以及本类的
     * {@link #maxRemainingByMaterial}。</p>
     */
    public static boolean sameSku(String lineSkuCode, String batchSkuCode) {
        return !StringUtils.hasText(lineSkuCode) || !StringUtils.hasText(batchSkuCode)
                || lineSkuCode.equals(batchSkuCode);
    }

    /**
     * 批量「单批最大余量」（**只读**）：每个物料里**单个批次**的最大派生余量。
     *
     * <p>它回答池读面的行级问题「这一行有没有能裁出它的批次」—— 与
     * {@link StockBatchConsumptionService#suggestedBatchNo} **同源**：同一份余量派生点、
     * 同一条 SKU 一致性口径 ⇒ {@code max ≥ 本行需求米数 ⇔ 该行有可满足的批次}
     * （= 派工前 fail-closed 的那个条件）。</p>
     *
     * <p>🔴 **一次取**（批次一条 + Σ消耗一条）⇒ 池读面不随行数增长而 N+1：调用方按物料去重后传进来。
     * 没有可用批次的物料 ⇒ {@code 0}（**显式给读数**，不用「缺席」区分「没查」与「没有」）。</p>
     */
    public static Map<MaterialDemand, BigDecimal> maxRemainingByMaterial(StockBatchMapper stockBatchMapper,
                                                                         StockBatchConsumptionMapper consumptionMapper,
                                                                         Long tenantId,
                                                                         Collection<MaterialDemand> demands) {
        Map<MaterialDemand, BigDecimal> out = new LinkedHashMap<>();
        Set<String> productIds = new LinkedHashSet<>();
        if (demands != null) {
            for (MaterialDemand d : demands) {
                if (d == null || out.containsKey(d)) {
                    continue;
                }
                out.put(d, BigDecimal.ZERO);
                if (StringUtils.hasText(d.productId())) {
                    productIds.add(d.productId());
                }
            }
        }
        if (out.isEmpty() || productIds.isEmpty()) {
            return out;
        }
        List<StockBatch> batches = stockBatchMapper.selectList(new LambdaQueryWrapper<StockBatch>()
                .eq(StockBatch::getTenantId, tenantId)
                .eq(StockBatch::getDeleted, 0)
                .in(StockBatch::getProductId, productIds));
        Map<Long, BigDecimal> consumed = consumedByBatchId(consumptionMapper, tenantId,
                batches.stream().map(StockBatch::getId).toList());
        for (StockBatch b : batches) {
            BigDecimal rest = StockQuantity.orZero(b.getQuantity())
                    .add(consumed.getOrDefault(b.getId(), BigDecimal.ZERO));
            for (Map.Entry<MaterialDemand, BigDecimal> e : out.entrySet()) {
                MaterialDemand d = e.getKey();
                if (!StringUtils.hasText(d.productId()) || !d.productId().equals(b.getProductId())
                        || !sameSku(d.skuCode(), b.getSkuCode())) {
                    continue;
                }
                if (rest.compareTo(e.getValue()) > 0) {
                    e.setValue(rest);
                }
            }
        }
        return out;
    }

    /**
     * 批次已消耗米数（{@code Σ delta}）的**唯一实现**：批次的「派生余量 = 入库量 + Σ消耗」里那一半。
     *
     * <p>{@link StockBatchConsumptionService#consumedByBatchId} 是它的包内入口
     * （调用方多、签名短），本类与它共用这一份聚合，不各写一份。</p>
     */
    static Map<Long, BigDecimal> consumedByBatchId(StockBatchConsumptionMapper consumptionMapper,
                                                   Long tenantId, Collection<Long> batchIds) {
        Map<Long, BigDecimal> out = new HashMap<>();
        if (batchIds == null || batchIds.isEmpty()) {
            return out;
        }
        for (StockBatchConsumptionMapper.BatchDeltaSum sum
                : consumptionMapper.sumDeltaByBatchIds(tenantId, batchIds)) {
            out.put(sum.getBatchId(), StockQuantity.orZero(sum.getDeltaSum()));
        }
        return out;
    }

    /**
     * 池读面：把「库存可满足性」回填到三条队列（{@code urgentLines} / {@code outsourcedLines} / 各物料组）。
     *
     * <p>先收**全部**行、再按物料**一次**批量判定（同一物料多行去重 ⇒ 行数增长不带来查询数增长），
     * 最后逐队列回填只读字段 —— 前端据此禁用勾选 + 行内提示，让「注定被 fail-closed 拒绝的行」
     * 在点「一键合并派单」之前就看得出来。</p>
     *
     * <p>读面走 {@link StockBatchConsumptionService#maxRemainingByMaterial}（同一个入口），
     * 判据本体在上面的 {@link #maxRemainingByMaterial} —— 池读面不另算一套。</p>
     */
    public static void fill(StockBatchConsumptionService consumption, Long tenantId,
                            List<ProductionPoolViews.PoolLine> urgentLines,
                            List<ProductionPoolViews.PoolLine> outsourcedLines,
                            Collection<List<ProductionPoolViews.PoolLine>> materialLines) {
        Set<MaterialDemand> demands = new LinkedHashSet<>();
        addDemands(demands, urgentLines);
        addDemands(demands, outsourcedLines);
        for (List<ProductionPoolViews.PoolLine> lines : materialLines) {
            addDemands(demands, lines);
        }
        Map<MaterialDemand, BigDecimal> maxRemaining = consumption.maxRemainingByMaterial(tenantId, demands);
        urgentLines.replaceAll(line -> withStockSatisfiable(line, maxRemaining));
        outsourcedLines.replaceAll(line -> withStockSatisfiable(line, maxRemaining));
        for (List<ProductionPoolViews.PoolLine> lines : materialLines) {
            lines.replaceAll(line -> withStockSatisfiable(line, maxRemaining));
        }
    }

    private static void addDemands(Set<MaterialDemand> demands, List<ProductionPoolViews.PoolLine> lines) {
        for (ProductionPoolViews.PoolLine line : lines) {
            demands.add(new MaterialDemand(line.productId(), line.skuCode()));
        }
    }

    /** 回填只读的可满足性：单批最大余量 ≥ 本行需求米数（判据本体，见 {@link #maxRemainingByMaterial}）。 */
    private static ProductionPoolViews.PoolLine withStockSatisfiable(
            ProductionPoolViews.PoolLine line, Map<MaterialDemand, BigDecimal> maxRemaining) {
        BigDecimal max = maxRemaining.get(new MaterialDemand(line.productId(), line.skuCode()));
        return line.withStockSatisfiable(max != null && max.compareTo(line.requiredMeters()) >= 0);
    }
}
