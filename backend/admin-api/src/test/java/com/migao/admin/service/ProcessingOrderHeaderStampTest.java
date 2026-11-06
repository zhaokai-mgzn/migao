// case_ids: PG-001, PG-007
package com.migao.admin.service;

import com.migao.admin.entity.Order;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.time.LocalDate;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * {@link ProcessingOrderHeaderStamp} 的单元自身契约（issue #8770 生成族一档）。
 *
 * <p>这里钉的是「搬出来的那一格不能变味」的四件事：① {@code stampOrderUrgency} 的**恒落键 / 缺值不落键**
 * 口径（{@code isUrgent} 真值 = {@code false} 也算真值，到货日 NULL 就**不写**）；
 * ② 空快照 / null 订单的**零动作**；③ {@code deriveOrderKind} 的两态判定（全布料 ⇒ 出库，否则 ⇒ 加工）；
 * ④ 卖布判据仍**委托门面的唯一实现点**（{@code isFabricSaleLine} 的兜底：缺 {@code saleForm}
 * 但 {@code sellingMethod=bulk_cut} 且**没有加工项** ⇒ 出库；同样有这个键但**有加工项** ⇒ 加工）。
 * 最后一条是本单元存在的意义 —— 复制第二份卖布判据就会与门面漂移，而漂移的那一份不会变红。</p>
 */
@DisplayName("加工单 · 订单级事实盖章单元（isUrgent 恒落键 / 到货日缺值不落键 / 单据类型两态）")
class ProcessingOrderHeaderStampTest {

    private static Order order(Boolean urgent, LocalDate requiredDeliveryDate) {
        return Order.builder().id("o-1").tenantId(1L).isUrgent(urgent)
                .requiredDeliveryDate(requiredDeliveryDate).build();
    }

    private static Map<String, Object> row() {
        return new LinkedHashMap<>();
    }

    @Test
    @DisplayName("加急标记恒落键：true / false 都写（false = 「明确不加急」，不是未填）")
    void urgencyFlagIsAlwaysStampedIncludingFalse() {
        List<Map<String, Object>> snapshot = new ArrayList<>(List.of(row(), row()));
        ProcessingOrderHeaderStamp.stampOrderUrgency(snapshot, order(true, null));
        assertThat(snapshot).allSatisfy(r -> assertThat(r).containsEntry("isUrgent", true));

        List<Map<String, Object>> notUrgent = new ArrayList<>(List.of(row()));
        ProcessingOrderHeaderStamp.stampOrderUrgency(notUrgent, order(false, null));
        assertThat(notUrgent.get(0)).as("false 也是真值（#4874 硬约束 1：不得当未填丢弃）")
                .containsEntry("isUrgent", false);
    }

    @Test
    @DisplayName("客户要求到货日：有值逐行写 YYYY-MM-DD；null ⇒ **不落键**（缺值不造值）")
    void requiredDeliveryDateIsStampedOnlyWhenPresent() {
        List<Map<String, Object>> withDate = new ArrayList<>(List.of(row(), row()));
        ProcessingOrderHeaderStamp.stampOrderUrgency(withDate,
                order(true, LocalDate.of(2026, 11, 20)));
        assertThat(withDate).allSatisfy(r -> assertThat(r)
                .containsEntry("requiredDeliveryDate", "2026-11-20"));

        List<Map<String, Object>> withoutDate = new ArrayList<>(List.of(row()));
        ProcessingOrderHeaderStamp.stampOrderUrgency(withoutDate, order(true, null));
        assertThat(withoutDate.get(0))
                .as("NULL = 未指定；写空串/占位会把「未指定」读成一个日期")
                .doesNotContainKey("requiredDeliveryDate");
    }

    @Test
    @DisplayName("零动作：空快照 / null 订单都直接返回（不抛、不造键）")
    void emptySnapshotAndNullOrderAreNoOps() {
        List<Map<String, Object>> empty = new ArrayList<>();
        ProcessingOrderHeaderStamp.stampOrderUrgency(empty, order(true, LocalDate.of(2026, 11, 20)));
        assertThat(empty).isEmpty();

        List<Map<String, Object>> untouched = new ArrayList<>(List.of(row()));
        ProcessingOrderHeaderStamp.stampOrderUrgency(untouched, null);
        assertThat(untouched.get(0)).isEmpty();
    }

    @Test
    @DisplayName("单据类型：空快照 / 全布料 ⇒ 出库；任一行不是卖布行 ⇒ 加工（混合单 = 有加工 ⇒ 加工）")
    void orderKindIsDerivedFromEveryRow() {
        assertThat(ProcessingOrderHeaderStamp.deriveOrderKind(null)).isEqualTo("processing");
        assertThat(ProcessingOrderHeaderStamp.deriveOrderKind(List.of())).isEqualTo("processing");

        Map<String, Object> fabric = row();
        fabric.put("saleForm", "布料");
        assertThat(ProcessingOrderHeaderStamp.deriveOrderKind(List.of(fabric, new LinkedHashMap<>(fabric))))
                .isEqualTo(ProcessingOrderService.ORDER_KIND_OUTBOUND);

        // 混合单的另一行是**加工行**（显式声明成品帘；显式 saleForm 优先于任何派生信号）
        Map<String, Object> mixed = row();
        mixed.put("saleForm", "成品帘");
        mixed.put("processingItems", List.of(Map.of("name", "韩褶")));
        assertThat(ProcessingOrderHeaderStamp.deriveOrderKind(List.of(fabric, mixed)))
                .as("混合单：有加工 ⇒ 加工（缺键的行按非布料处理，不造值）")
                .isEqualTo(ProcessingOrderService.ORDER_KIND_PROCESSING);
    }

    @Test
    @DisplayName("卖布判据委托唯一实现点：缺 saleForm 但 bulk_cut 且无加工项 ⇒ 出库；带加工项 ⇒ 加工")
    void fabricFallbackComesFromTheSingleImplementationPoint() {
        Map<String, Object> fabricByFallback = row();
        fabricByFallback.put("sellingMethod", "bulk_cut");
        assertThat(ProcessingOrderHeaderStamp.deriveOrderKind(List.of(fabricByFallback)))
                .as("issue #7222 兜底：缺声明时按已落库的布料专属事实认出卖布行")
                .isEqualTo(ProcessingOrderService.ORDER_KIND_OUTBOUND);

        Map<String, Object> withProcs = new LinkedHashMap<>(fabricByFallback);
        withProcs.put("processingItems", List.of(Map.of("name", "韩褶")));
        assertThat(ProcessingOrderHeaderStamp.deriveOrderKind(List.of(withProcs)))
                .as("有加工项 ⇒ 一定不是卖布行（否则整件商品零工序）")
                .isEqualTo(ProcessingOrderService.ORDER_KIND_PROCESSING);
    }
}
