// case_ids: PG-001, PG-007
package com.migao.admin.service;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * {@link ProcessingOrderCuttingStamp} 的单元自身契约（issue #8770 生成族一档）。
 *
 * <p>钉的是「排料结果 → 快照行」这一格的五件事：① 按快照行的 {@code itemId} 匹配（**不是**按下标）；
 * ② 三个米数逐值落键、{@code savedMeters} = 公式 − 应领（不是二次取数、不是四舍五入）；
 * ③ 批次号只在该行**有值**时落键（缺值不造值）；④ 计划为空 ⇒ 零动作；⑤ 行里 {@code itemId}
 * 为 null / 匹配不上 ⇒ 该行**原样不动**（不得把别人的米数写成自己的）。</p>
 */
@DisplayName("加工单 · 排料结果盖章单元（按 itemId 匹配 / 三米数 / 批次缺值不落键）")
class ProcessingOrderCuttingStampTest {

    private static Map<String, Object> row(String itemId) {
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("itemId", itemId);
        return row;
    }

    private static StockBatchConsumptionService.Deduction deduction(String itemId, String batchNo,
                                                                    String formula, String planned) {
        return new StockBatchConsumptionService.Deduction(1L, batchNo, "prod-1", 1L, "SKU-1",
                itemId, new BigDecimal(formula), new BigDecimal(planned),
                new BigDecimal("12.50"), new BigDecimal("60.00"));
    }

    @Test
    @DisplayName("排料结果按 itemId 落三个米数：formulaMeters / plannedMeters / savedMeters（公式 − 应领）")
    void cuttingPlanStampsThreeMetersByItemId() {
        List<Map<String, Object>> snapshot = new ArrayList<>(List.of(row("item-a"), row("item-b")));
        ProcessingOrderCuttingStamp.stampCuttingPlan(snapshot, List.of(
                deduction("item-a", "PC-1", "5.20", "5.00"),
                deduction("item-b", "PC-2", "3.10", "3.00")));

        assertThat(snapshot.get(0)).containsEntry("formulaMeters", new BigDecimal("5.20"))
                .containsEntry("plannedMeters", new BigDecimal("5.00"))
                .containsEntry("savedMeters", new BigDecimal("0.20"));
        assertThat(snapshot.get(1)).containsEntry("formulaMeters", new BigDecimal("3.10"))
                .containsEntry("plannedMeters", new BigDecimal("3.00"))
                .containsEntry("savedMeters", new BigDecimal("0.10"));
    }

    @Test
    @DisplayName("匹配不上 / itemId 为 null 的行原样不动（不得把别人的米数写成自己的）")
    void rowsWithoutMatchingDeductionAreUntouched() {
        List<Map<String, Object>> snapshot = new ArrayList<>(List.of(row("item-a"), row(null), row("item-x")));
        ProcessingOrderCuttingStamp.stampCuttingPlan(snapshot, List.of(
                deduction("item-a", "PC-1", "5.20", "5.00")));

        assertThat(snapshot.get(0)).containsKey("plannedMeters");
        assertThat(snapshot.get(1)).as("itemId 为 null 的行不得被匹配到")
                .doesNotContainKey("plannedMeters");
        assertThat(snapshot.get(2)).as("不在本单计划里的行不得被写")
                .doesNotContainKey("plannedMeters");
    }

    @Test
    @DisplayName("批次号写进快照行（batchNo）；该行没有批次 ⇒ **不落键**（缺值不造值）")
    void assignedBatchNumberIsStampedOnlyWhenPresent() {
        List<Map<String, Object>> snapshot = new ArrayList<>(List.of(row("item-a"), row("item-b")));
        ProcessingOrderCuttingStamp.stampAssignedBatches(snapshot, List.of(
                deduction("item-a", "PC-20261106-8770", "5.20", "5.00"),
                deduction("item-b", null, "3.10", "3.00")));

        assertThat(snapshot.get(0)).containsEntry("batchNo", "PC-20261106-8770");
        assertThat(snapshot.get(1)).doesNotContainKey("batchNo");
    }

    @Test
    @DisplayName("零动作：计划为空 ⇒ 快照逐行原样（不抛、不写任何键）")
    void emptyPlanIsANoOp() {
        List<Map<String, Object>> snapshot = new ArrayList<>(List.of(row("item-a")));
        ProcessingOrderCuttingStamp.stampCuttingPlan(snapshot, List.of());
        ProcessingOrderCuttingStamp.stampAssignedBatches(snapshot, List.of());
        assertThat(snapshot.get(0)).containsOnlyKeys("itemId");
    }
}
