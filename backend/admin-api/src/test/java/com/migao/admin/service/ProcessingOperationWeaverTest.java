// case_ids: MC-245
package com.migao.admin.service;

import com.migao.admin.entity.ProductionRouteRule;
import com.migao.admin.exception.BusinessException;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;

/**
 * {@link ProcessingOperationWeaver}（issue #8725 第二档切出来的「条件工序编织」单元）的定点判据。
 *
 * <p>它钉的是**归一化与匹配口径**：特殊选项去重保序（插两次 = 工人按两遍单价拿钱）、
 * 加工项名只认 Map 元素、触发判定是**精确相等**而不是 `contains`（错一个字就静默失效）、
 * 未知触发类型**显式失败**（不是静默跳过）。</p>
 */
@DisplayName("条件工序编织单元：归一化 / 精确匹配 / 未知类型 fail-closed（issue #8725 切片）")
class ProcessingOperationWeaverTest {

    private ProductionOperationQueryService query;
    private ProcessingOperationWeaver weaver;

    @BeforeEach
    void setUp() {
        query = mock(ProductionOperationQueryService.class);
        weaver = new ProcessingOperationWeaver(query);
    }

    @Test
    @DisplayName("特殊选项：空白项丢弃、重复项去重、其余**保序**（插两次 = 按两遍单价拿钱）")
    void specialOptionsNormalisesDedupAndOrder() {
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("specialOptions", List.of("打孔", " ", "穿杆", "打孔"));

        assertThat(ProcessingOperationWeaver.specialOptions(entry))
                .containsExactly("打孔", "穿杆");
    }

    @Test
    @DisplayName("特殊选项：非数组形态 ⇒ 空表（不猜、不把字符串当一项）")
    void specialOptionsRejectsNonListShape() {
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("specialOptions", "打孔");

        assertThat(ProcessingOperationWeaver.specialOptions(entry)).isEmpty();
        assertThat(ProcessingOperationWeaver.specialOptions(new LinkedHashMap<>())).isEmpty();
    }

    @Test
    @DisplayName("加工项名：只认 Map 元素且名字非空白，去重保序")
    void processingItemNamesKeepsOnlyNamedMapItems() {
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("processingItems", List.of(
                Map.of("name", "韩褶"),
                "裸字符串不是加工项",
                Map.of("name", " "),
                Map.of("id", "no-name"),
                Map.of("name", "韩褶")));

        assertThat(ProcessingOperationWeaver.processingItemNames(entry))
                .containsExactly("韩褶");
    }

    @Test
    @DisplayName("seq 重排：从 1 起逐条连续（条件工序插入后序号必须对齐，否则页面按 seq 排会错位）")
    void renumberSeqRewritesSequenceFromOne() {
        List<Map<String, Object>> operations = new ArrayList<>();
        operations.add(new LinkedHashMap<>(Map.of("operation", "精裁", "seq", 9)));
        operations.add(new LinkedHashMap<>(Map.of("operation", "三边", "seq", 3)));
        operations.add(new LinkedHashMap<>(Map.of("operation", "打包")));

        ProcessingOperationWeaver.renumberSeq(operations);

        assertThat(operations).extracting(op -> op.get("seq")).containsExactly(1, 2, 3);
        assertThat(operations).extracting(op -> op.get("operation")).containsExactly("精裁", "三边", "打包");
    }

    @Test
    @DisplayName("触发判定：option / processing_item 都是**精确相等**（`打孔款` 不得命中 `打孔`）")
    void conditionalRuleTriggersUsesExactMatchNotContains() {
        ProductionRouteRule optionRule = ProductionRouteRule.builder()
                .id("rule-1").tenantId(1L)
                .triggerKind("option").triggerValue("打孔").action("insert").operation("花边")
                .build();

        assertThat(ProcessingOperationWeaver.conditionalRuleTriggers(
                optionRule, List.of("打孔"), List.of())).isTrue();
        assertThat(ProcessingOperationWeaver.conditionalRuleTriggers(
                optionRule, List.of("打孔款"), List.of())).isFalse();
        assertThat(ProcessingOperationWeaver.conditionalRuleTriggers(
                optionRule, List.of(), List.of("打孔"))).isFalse();

        ProductionRouteRule itemRule = ProductionRouteRule.builder()
                .id("rule-2").tenantId(1L)
                .triggerKind("processing_item").triggerValue("韩褶").action("insert").operation("花边")
                .build();
        assertThat(ProcessingOperationWeaver.conditionalRuleTriggers(
                itemRule, List.of(), List.of("韩褶"))).isTrue();
        assertThat(ProcessingOperationWeaver.conditionalRuleTriggers(
                itemRule, List.of(), List.of("韩褶-布"))).isFalse();
    }

    @Test
    @DisplayName("craft / sales_form 规则在本方法里恒 false = **不重复插入**（不是「未实现」）")
    void craftAndSalesFormRulesAreDeferredToBuildRoute() {
        assertThat(ProcessingOperationWeaver.conditionalRuleTriggers(
                ProductionRouteRule.builder().id("r-craft").triggerKind("craft")
                        .triggerValue("韩褶").action("insert").operation("花边").build(),
                List.of("韩褶"), List.of("韩褶"))).isFalse();
        assertThat(ProcessingOperationWeaver.conditionalRuleTriggers(
                ProductionRouteRule.builder().id("r-sale").triggerKind("sales_form")
                        .triggerValue("布料").action("insert").operation("打包").build(),
                List.of("布料"), List.of())).isFalse();
    }

    @Test
    @DisplayName("未知触发类型 ⇒ **显式失败**（静默跳过 = 规则落库但永不生效的黑洞）")
    void unknownTriggerKindFailsClosed() {
        ProductionRouteRule unknown = ProductionRouteRule.builder()
                .id("rule-x").tenantId(1L)
                .triggerKind("shaped").triggerValue("x").action("insert").operation("花边")
                .build();

        assertThatThrownBy(() -> ProcessingOperationWeaver.conditionalRuleTriggers(
                unknown, List.of(), List.of()))
                .isInstanceOf(BusinessException.class)
                .satisfies(thrown -> {
                    BusinessException be = (BusinessException) thrown;
                    assertThat(be.getCode()).isEqualTo("PRODUCTION_ROUTING_NOT_FOUND");
                    assertThat(be.getMessage()).contains("shaped");
                });
    }

    @Test
    @DisplayName("部位限定：空 / null = 不限部位，否则逐字匹配（不限 ≠ 跳过）")
    void rulePositionMatchesTreatsEmptyAsUnlimited() {
        assertThat(ProcessingOperationWeaver.rulePositionMatches(
                ProductionRouteRule.builder().id("r1").position(null).build(), "布帘")).isTrue();
        assertThat(ProcessingOperationWeaver.rulePositionMatches(
                ProductionRouteRule.builder().id("r2").position("").build(), "纱帘")).isTrue();
        assertThat(ProcessingOperationWeaver.rulePositionMatches(
                ProductionRouteRule.builder().id("r3").position("纱帘").build(), "纱帘")).isTrue();
        assertThat(ProcessingOperationWeaver.rulePositionMatches(
                ProductionRouteRule.builder().id("r4").position("纱帘").build(), "布帘")).isFalse();
    }
}
