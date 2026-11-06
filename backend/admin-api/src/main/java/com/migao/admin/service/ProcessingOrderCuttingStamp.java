package com.migao.admin.service;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 加工单**排料结果盖章**单元（issue #8770「生成族」一档，从 {@link ProcessingOrderService} **纯搬运**）。
 *
 * <p><b>单一职责</b>：把派工求解出来的**排料结果**固化进加工单快照的每一行 ——
 * ① {@link #stampAssignedBatches}：这行从**哪一批**裁（{@code batchNo}）；
 * ② {@link #stampCuttingPlan}：三个米数（{@code formulaMeters} 公式口径 /
 * {@code plannedMeters} 应领米数 / {@code savedMeters} 省下的米数）。
 * 二者都在 {@code commit()} 里、**加工单 insert 之前**盖章 —— 快照是加工单的**固化真相**
 * （#5159 硬约束一「落库不重算」：事后改算料配置 / 批次价都不改它）。</p>
 *
 * <p><b>为什么与订单级事实分成两个单元</b>：本组的输入是**排料计划**
 * （{@code StockBatchConsumptionService.Deduction} 列表），与订单级事实无关；调用时机也不同
 * （{@code commit} 后段）。本单元**零状态、零 DB**（纯函数）。</p>
 *
 * <p><b>搬运口径</b>：方法体、注释、异常语义**一字未改**。改动只有一类，逐条可复算：
 * 两个方法的可见性由 {@code private} 放宽到**同包可见**（门面留 3 行同名委托 ⇒
 * {@code commit()} 里那两处调用、以及 {@code ProcessingOrderResponse} / 设计文档里按
 * {@code stampCuttingPlan} / {@code stampAssignedBatches} 取名的引用**一字未改**）。
 * 本单元无日志语句 ⇒ 日志器无需搬迁（没有 {@code @Slf4j} 可搬）。</p>
 *
 * <p><b>为什么没有 {@code Owner} 窄接口</b>：本组只吃入参快照与排料计划，**没有一处回调门面** ⇒
 * 加一层回调门面会变成零实现的空壳（同族单元里 {@code ProcessingOrderReadFace.Owner} 是因为
 * 单号解析 / 域名是门面的实例事实才必需）。</p>
 */
final class ProcessingOrderCuttingStamp {

    private ProcessingOrderCuttingStamp() {
    }

    /** 搬运自门面；**行为契约的权威注释仍在** {@code ProcessingOrderService#stampCuttingPlan}。 */
    static void stampCuttingPlan(List<Map<String, Object>> snapshot,
                                 List<StockBatchConsumptionService.Deduction> plan) {
        if (plan.isEmpty()) {
            return;
        }
        Map<String, StockBatchConsumptionService.Deduction> byItemId = new LinkedHashMap<>();
        for (StockBatchConsumptionService.Deduction d : plan) {
            byItemId.put(d.orderItemId(), d);
        }
        for (Map<String, Object> row : snapshot) {
            Object itemId = row.get("itemId");
            StockBatchConsumptionService.Deduction d =
                    itemId == null ? null : byItemId.get(String.valueOf(itemId));
            if (d == null) {
                continue;
            }
            row.put("formulaMeters", d.formulaMeters());
            row.put("plannedMeters", d.plannedMeters());
            row.put("savedMeters", d.formulaMeters().subtract(d.plannedMeters()));
        }
    }

    /** 搬运自门面；**行为契约的权威注释仍在** {@code ProcessingOrderService#stampAssignedBatches}。 */
    static void stampAssignedBatches(List<Map<String, Object>> snapshot,
                                     List<StockBatchConsumptionService.Deduction> plan) {
        if (plan.isEmpty()) {
            return;
        }
        Map<String, String> batchNoByItemId = new LinkedHashMap<>();
        for (StockBatchConsumptionService.Deduction d : plan) {
            batchNoByItemId.put(d.orderItemId(), d.batchNo());
        }
        for (Map<String, Object> row : snapshot) {
            Object itemId = row.get("itemId");
            String batchNo = itemId == null ? null : batchNoByItemId.get(String.valueOf(itemId));
            if (batchNo != null) {
                row.put("batchNo", batchNo);
            }
        }
    }
}
