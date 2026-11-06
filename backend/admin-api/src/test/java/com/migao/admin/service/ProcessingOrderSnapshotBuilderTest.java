// case_ids: MC-330
package com.migao.admin.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.entity.ProcessingItem;
import com.migao.admin.mapper.ProcessingItemMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * {@link ProcessingOrderSnapshotBuilder} 的定点判据（issue #8770 快照/读面一档）。
 *
 * <p>与 characterization（{@code ProcessingOrderSnapshotReadFaceCharacterizationTest}）分工：
 * 那一份冻的是「同一批输入 ⇒ 输出逐字节不变」（防搬移改行为）；本份钉的是**每条业务规则各自的
 * 失败面**（防规则本身被后来的改动悄悄放宽）—— 两条缺一不可，不互为替代。</p>
 */
@DisplayName("快照构建单元：键族/别名/卖布兜底/目录缺失 六格")
class ProcessingOrderSnapshotBuilderTest {

    private static final Long TENANT = 1L;

    private final ObjectMapper mapper = new ObjectMapper();
    private ProcessingItemMapper processingItemMapper;
    private ProcessingOrderSnapshotBuilder builder;

    @BeforeEach
    void setUp() {
        processingItemMapper = mock(ProcessingItemMapper.class);
        builder = new ProcessingOrderSnapshotBuilder(processingItemMapper, mapper);
    }

    @Test
    @DisplayName("① processing_info 为 NULL 的存量行 ⇒ 整行跳过（issue #5550：不 NPE、不造值）")
    void nullProcessingInfoRowIsSkipped() {
        assertThat(builder.buildSnapshot(List.of(item(null)), TENANT)).isEmpty();
    }

    @Test
    @DisplayName("② 卖布行（saleForm=布料）没有加工项也必须进快照 —— 否则布料路线永不执行（#4909）")
    void fabricSaleRowWithoutProcessingItemsIsKept() {
        List<Map<String, Object>> rows = builder.buildSnapshot(
                List.of(item(Map.of("saleForm", "布料", "sku", "SKU-FABRIC"))), TENANT);

        assertThat(rows).hasSize(1);
        assertThat(rows.get(0)).containsEntry("saleForm", "布料");
        assertThat((List<?>) rows.get(0).get("processingItems")).isEmpty();
    }

    @Test
    @DisplayName("③ skuCode 覆盖 sku（落键同为 sku）；formulaText 以 snake_case 别名落 formula_text（#4555）")
    void skuCodeWinsOverSkuAndFormulaTextIsAliased() {
        when(processingItemMapper.selectById("pi-1")).thenReturn(ProcessingItem.builder()
                .id("pi-1").name("裁剪").build());
        Map<String, Object> pi = new LinkedHashMap<>();
        pi.put("sku", "SKU-LEGACY");
        pi.put("skuCode", "SKU-001");
        pi.put("formulaText", "1.80 × 2.00 × 2");
        pi.put("processingItems", List.of(new LinkedHashMap<>(Map.of("id", "pi-1"))));

        Map<String, Object> row = builder.buildSnapshot(List.of(item(pi)), TENANT).get(0);

        assertThat(row).containsEntry("sku", "SKU-001");
        assertThat(row).containsEntry("formula_text", "1.80 × 2.00 × 2");
        assertThat(row).doesNotContainKey("formulaText");
    }

    @Test
    @DisplayName("④ 加工项目录取不到 ⇒ options/unit/craftHint **不落键**（缺键就是缺键，不造值）")
    void catalogMissingLeavesOptionsUnitCraftHintAbsent() {
        when(processingItemMapper.selectById("pi-gone")).thenReturn(null);
        Map<String, Object> proc = new LinkedHashMap<>();
        proc.put("id", "pi-gone");
        proc.put("name", "裁剪");

        Map<String, Object> row = builder.buildSnapshot(
                List.of(item(Map.of("processingItems", List.of(proc)))), TENANT).get(0);

        @SuppressWarnings("unchecked")
        List<Map<String, Object>> items = (List<Map<String, Object>>) row.get("processingItems");
        assertThat(items).hasSize(1);
        assertThat(items.get(0)).doesNotContainKeys("options", "unit", "craftHint");
        assertThat(items.get(0)).containsEntry("name", "裁剪");
    }

    @Test
    @DisplayName("⑤ 明细列（显式字段）覆盖 processing_info 的同名键 —— 列是最高优先级（#4362）")
    void columnCraftSpecOverridesJsonbKeys() {
        when(processingItemMapper.selectById("pi-1")).thenReturn(ProcessingItem.builder()
                .id("pi-1").options(List.of("包边")).unit("条").craftHint("韩褶").build());
        OrderItem withColumns = OrderItem.builder()
                .id("i-1").tenantId(TENANT).orderId("order-001")
                .productName("布艺遮光帘").quantity(new BigDecimal("1"))
                .curtainType("水波帘").corner("左")
                .processingInfo(new LinkedHashMap<>(Map.of(
                        "curtainType", "布帘",
                        "processingItems", List.of(new LinkedHashMap<>(Map.of("id", "pi-1"))))))
                .build();

        Map<String, Object> row = builder.buildSnapshot(List.of(withColumns), TENANT).get(0);

        assertThat(row).containsEntry("curtainType", "水波帘");
        assertThat(row).containsEntry("corner", "左");
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> items = (List<Map<String, Object>>) row.get("processingItems");
        assertThat(items.get(0)).containsEntry("unit", "条").containsEntry("craftHint", "韩褶");
        @SuppressWarnings("unchecked")
        List<String> options = (List<String>) items.get(0).get("options");
        assertThat(options).containsExactly("包边");
    }

    @Test
    @DisplayName("⑥ 空明细 ⇒ 空快照（不是 null、不是造一行空行）")
    void emptyItemsYieldsEmptySnapshot() {
        assertThat(builder.buildSnapshot(List.of(), TENANT)).isEmpty();
    }

    private static OrderItem item(Object processingInfo) {
        return OrderItem.builder()
                .id("i-1").tenantId(TENANT).orderId("order-001")
                .productName("布艺遮光帘").quantity(new BigDecimal("2"))
                .width(new BigDecimal("1.80")).height(new BigDecimal("2.00"))
                .processingInfo(processingInfo)
                .build();
    }
}
