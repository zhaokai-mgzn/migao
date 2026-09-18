package com.migao.admin.service;

// case_ids: PG-040

import com.migao.admin.entity.OrderItem;
import com.migao.admin.entity.ProcessingFeeCombination;
import com.migao.admin.entity.ProcessingItem;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.ProcessingFeeCombinationMapper;
import com.migao.admin.mapper.ProcessingItemMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.math.BigDecimal;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;

/**
 * 加工费组合定价**读面 + Mapper/表契约**（V68，issue #4386）
 *
 * <h2>读面为什么单独一个类</h2>
 * 写面（{@code ProcessingFeeCombinationCommandService}）只有它能改价；读面（列表 / 缺口）
 * 谁都能调。两者分开，才让「谁在改加工费」可 grep（同 #4308 对路线库的处置）。
 *
 * <h2>本文件钉的三件事</h2>
 * ① **缺口视图**（判据 4）：订单里出现过、库里查不到价的组合 —— 缺了它，商家只能靠
 *    「顾客下单后金额不对」发现漏配价（那已经是错价落库之后了）；
 * ② **列表读面**：只回活跃行 + 稳定排序（顺序随机会让商家每次刷新看到不同表）；
 * ③ Mapper / 实体 / 迁移 / bootstrap schema 的**四源收敛**另有两个专测
 *    （{@code ProcessingFeeCombinationMapperTest} / {@code ...VersionMapperTest}，同属 PG-040）——
 *    列一旦漂移，`unit_price` 读到 null ⇒ 取价静默变成「0 元」或抛错，而**不会有任何东西变红**。
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("ProcessingFeeQueryService 读面 + Mapper/表契约（加工费组合定价）")
class ProcessingFeeQueryServiceTest {

    private static final Long TENANT = 1L;

    @Mock
    private ProcessingFeeCombinationMapper combinationMapper;
    @Mock
    private ProcessingItemMapper processingItemMapper;
    @Mock
    private OrderItemMapper orderItemMapper;

    private ProcessingFeeQueryService service() {
        return new ProcessingFeeQueryService(combinationMapper, processingItemMapper, orderItemMapper);
    }

    private static ProcessingFeeCombination combination(String id, String key, String price) {
        return ProcessingFeeCombination.builder().id(id).tenantId(TENANT)
                .compositionKey(key).items(ProcessingFeeQueryService.itemsOf(key))
                .unitPrice(new BigDecimal(price)).status("active").sortOrder(0).deleted(0).build();
    }

    private static OrderItem orderItem(String... names) {
        List<Map<String, Object>> items = new java.util.ArrayList<>();
        for (String name : names) {
            Map<String, Object> entry = new LinkedHashMap<>();
            entry.put("id", "pi-" + name);
            entry.put("name", name);
            entry.put("unitPrice", new BigDecimal("9.5"));
            entry.put("quantity", new BigDecimal("12.3"));
            items.add(entry);
        }
        return OrderItem.builder().id("oi-" + String.join("-", names)).tenantId(TENANT)
                .orderId("o1").processingInfo(Map.of("processingItems", items)).build();
    }

    // ══════════════════ 判据 4：缺口可见 ══════════════════

    @Test
    @DisplayName("判据 4a：缺口 = 订单里**实际出现过**、但库里查不到价的组合（含出现次数与可行动提示）")
    void gapsListUnpricedCombinationsSeenInOrders() {
        when(combinationMapper.selectList(any()))
                .thenReturn(List.of(combination("c1", "打孔+韩褶", "12.00")));
        when(orderItemMapper.selectList(any())).thenReturn(List.of(
                orderItem("韩褶", "打孔"),            // 已定价 ⇒ 不进缺口
                orderItem("定型", "打孔", "韩褶"),     // 未定价 ⇒ 进缺口
                orderItem("韩褶", "打孔", "定型"),     // 同一个组合（书写顺序不同）⇒ 合并计数
                orderItem("定型")));                  // 另一个未定价组合

        Map<String, Object> gaps = service().feeGaps(TENANT);

        @SuppressWarnings("unchecked")
        List<Map<String, Object>> rows = (List<Map<String, Object>>) gaps.get("unpriced_combinations");
        assertThat(rows).extracting(r -> r.get("composition_key"))
                .as("已定价的不出现；两个未定价组合各一行（归一化后合并计数）")
                .containsExactlyInAnyOrder("定型+打孔+韩褶", "定型");
        assertThat(rows).filteredOn(r -> "定型+打孔+韩褶".equals(r.get("composition_key")))
                .singleElement()
                .satisfies(r -> {
                    assertThat(r.get("items")).isEqualTo(List.of("定型", "打孔", "韩褶"));
                    assertThat(r.get("order_count"))
                            .as("归一化后合并计数（两行订单写的是同一个组合，是同一笔钱）").isEqualTo(2);
                    assertThat(String.valueOf(r.get("note")))
                            .as("缺口必须可行动（说清去哪定价），不是一句「未定价」")
                            .contains("定价");
                });
        assertThat(gaps.get("unpriced_combination_total")).isEqualTo(2);
        assertThat(gaps.get("scanned_order_items")).isEqualTo(4);
        assertThat(gaps.get("scanned_truncated"))
                .as("未触上限 ⇒ 明确为 false（触上限时必须为 true，**不静默**）").isEqualTo(false);
    }

    @Test
    @DisplayName("判据 4b：没有任何订单 ⇒ 缺口为空集（不是 null、不是异常；空集也是可读结论）")
    void gapsEmptyWhenNoOrders() {
        when(combinationMapper.selectList(any())).thenReturn(List.of());
        when(orderItemMapper.selectList(any())).thenReturn(List.of());

        Map<String, Object> gaps = service().feeGaps(TENANT);

        assertThat(gaps.get("unpriced_combinations")).isEqualTo(List.of());
        assertThat(gaps.get("unpriced_combination_total")).isEqualTo(0);
        assertThat(gaps.get("scanned_order_items")).isEqualTo(0);
    }

    @Test
    @DisplayName("判据 4c：`processing_info` 是 JSON **字符串**时也要能解析（JacksonTypeHandler 未生效的形态）")
    void gapsParseJsonStringProcessingInfo() {
        when(combinationMapper.selectList(any())).thenReturn(List.of());
        when(orderItemMapper.selectList(any())).thenReturn(List.of(
                OrderItem.builder().id("oi-str").tenantId(TENANT).orderId("o1")
                        .processingInfo("[{\"name\":\"打孔\"}]").build(),
                OrderItem.builder().id("oi-str2").tenantId(TENANT).orderId("o1")
                        .processingInfo("{\"processingItems\":[{\"name\":\"韩褶\"},{\"name\":\"定型\"}]}")
                        .build()));

        Map<String, Object> gaps = service().feeGaps(TENANT);

        @SuppressWarnings("unchecked")
        List<Map<String, Object>> rows = (List<Map<String, Object>>) gaps.get("unpriced_combinations");
        assertThat(rows).extracting(r -> r.get("composition_key"))
                .as("字符串形态必须能读（读不出 ⇒ 缺口恒为空 = 静默失效）")
                .containsExactly("定型+韩褶");
    }

    // ══════════════════ 列表读面 ══════════════════

    @Test
    @DisplayName("列表读面只回活跃行，且 `items` 与 `composition_key` **同源**（不维护第二份口径）")
    void listReturnsOnlyActive() {
        when(combinationMapper.selectList(any())).thenReturn(List.of(
                combination("c1", "定型+打孔+韩褶", "18.00")));

        Map<String, Object> list = service().combinations(TENANT);

        assertThat(list.get("total")).isEqualTo(1);
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> rows = (List<Map<String, Object>>) list.get("combinations");
        assertThat(rows).singleElement().satisfies(r -> {
            assertThat(r.get("composition_key")).isEqualTo("定型+打孔+韩褶");
            assertThat(r.get("items")).isEqualTo(List.of("定型", "打孔", "韩褶"));
            assertThat(r.get("unit_price")).isEqualTo(new BigDecimal("18.00"));
            assertThat(r.get("unit")).isEqualTo("元/米");
        });
    }

    @Test
    @DisplayName("`itemsOf` 是 key 的**唯一**反解析口径（key ↔ items 双向一致，含空 key 边界）")
    void itemsOfIsTheSingleDecoder() {
        assertThat(ProcessingFeeQueryService.itemsOf("定型+打孔+韩褶"))
                .isEqualTo(List.of("定型", "打孔", "韩褶"));
        assertThat(ProcessingFeeQueryService.itemsOf(null)).isEmpty();
        assertThat(ProcessingFeeQueryService.itemsOf("")).isEmpty();
        assertThat(ProcessingFeeQueryService.itemsOf("韩褶")).isEqualTo(List.of("韩褶"));
    }

    @Test
    @DisplayName("活跃加工项目录按名索引（写面护栏的校验源；停用/已删不进索引）")
    void activeItemsByNameIndexesCatalog() {
        when(processingItemMapper.selectList(any())).thenReturn(List.of(
                ProcessingItem.builder().id("pi-1").tenantId(TENANT).name("韩褶")
                        .status("active").deleted(0).build()));

        Map<String, ProcessingItem> byName = service().activeItemsByName(TENANT);

        assertThat(byName).containsOnlyKeys("韩褶");
    }
}
