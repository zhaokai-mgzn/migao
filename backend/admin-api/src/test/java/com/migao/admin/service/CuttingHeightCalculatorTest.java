package com.migao.admin.service;

// case_ids: PG-045

import com.migao.admin.service.CuttingHeightCalculator.Hit;
import com.migao.admin.service.CuttingHeightCalculator.Result;
import com.migao.admin.service.CuttingHeightCalculator.Vars;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 裁剪高度纯计算测试（V140 母单 #5161；v2 = issue #7997）—— 命中推导 + 求和 + 取整。
 *
 * <p>判据（每条都能红）：</p>
 * <ol>
 *   <li><b>条件组是「与」</b>：{@code 布绑带 ∧ 韩褶} 才命中，只有布绑带 ⇒ 不命中
 *       （红证：把 {@code conditions} 循环改成「任一命中」⇒ 红）；</li>
 *   <li><b>组内 values 是「或」</b>：{@code 接高 ∨ 双眼皮接高} 都能命中 0.145 那条
 *       （红证：只比第一个值 ⇒ 双眼皮接高不命中 ⇒ 红）；</li>
 *   <li><b>四类触发逐字比对</b>：特殊选项 / 工艺 / 加工项 / 定型（红证：改成「包含」匹配 ⇒ 红）；</li>
 *   <li><b>部位限定生效</b>（{@code position} 不匹配 ⇒ 不命中）；</li>
 *   <li><b>兜底是「替换」</b>（用户 2026-10-28 裁定 A）：专用项一旦命中，兜底组<b>整组</b>不参与
 *       ⇒ 布绑带单不会又加一份布贴；专用项<b>零命中</b>时兜底组才参与
 *       （红证：把两组合并成一遍求和 ⇒ 两条断言同时红）；</li>
 *   <li><b>命中但未配置取值</b>（{@code value=null}）⇒ 进 {@code misses(unresolved)}、不计入、不按 0 算，
 *       且<b>不回落兜底</b>（缺项要被看见，不许用兜底把它盖掉）；</li>
 *   <li><b>空 {@code conditions} = 恒真</b>（「公共」项）；<b>未知 kind / 空 values ⇒ 不命中</b>（fail-closed）；</li>
 *   <li><b>未启用的项不参与</b>；<b>减项真的减</b>；</li>
 *   <li><b>取整三档</b>（half_up / down / up）+ 位数上界 3。</li>
 * </ol>
 */
@DisplayName("CuttingHeightCalculator 裁剪高度计算（v2 / issue #7997）")
class CuttingHeightCalculatorTest {

    @Test
    @DisplayName("条件组「与」+ 组内「或」：布绑带∧韩褶 命中 0.14，布绑带∧打孔 不命中")
    void conditionsAreAndAcrossKindsAndOrWithinValues() {
        Vars vars = new Vars("布帘", new BigDecimal("2.92"), "韩褶",
                List.of("布绑带"), List.of("韩褶"), true);

        Map<String, Object> hanzhe = item("bangdai_hanzhe", "布绑带-韩褶", "0.14", "add", true, "布帘",
                conditions(condition("option", "布绑带"), condition("craft", "韩褶")));
        Map<String, Object> dakong = item("bangdai_dakong", "布绑带-打孔", "0.16", "add", true, "布帘",
                conditions(condition("option", "布绑带"), condition("craft", "打孔")));

        assertThat(CuttingHeightCalculator.matches(hanzhe, vars)).isTrue();
        // 与：工艺不匹配 ⇒ 整条不命中（不是「有一个条件对就算」）
        assertThat(CuttingHeightCalculator.matches(dakong, vars)).isFalse();

        // 或：values 里任一个命中即可
        Vars jiegao = new Vars("布帘", new BigDecimal("2.92"), "韩褶",
                List.of("双眼皮接高"), List.of(), false);
        Map<String, Object> huaxian = item("huaxian", "画线", "0.145", "add", true, "布帘",
                conditions(condition("option", "接高", "双眼皮接高")));
        assertThat(CuttingHeightCalculator.matches(huaxian, jiegao)).isTrue();

        Result result = CuttingHeightCalculator.compute(
                config(List.of(hanzhe, dakong, huaxian), "half_up", 3), vars);
        assertThat(result.cuttingHeight()).isEqualByComparingTo("3.06");   // 2.92 + 0.14
        assertThat(result.hits()).extracting(Hit::key).containsExactly("bangdai_hanzhe");
    }

    @Test
    @DisplayName("四类触发逐字比对 + 部位限定 + 空 conditions 恒真 + 未知 kind fail-closed")
    void fourTriggerKindsAreVerbatim() {
        Vars vars = new Vars("布帘", new BigDecimal("2.92"), "韩褶",
                List.of("布贴", "接高"), List.of("韩褶"), true);

        assertThat(matches(conditions(condition("option", "布贴")), vars, "布帘")).isTrue();
        assertThat(matches(conditions(condition("craft", "韩褶")), vars, null)).isTrue();
        assertThat(matches(conditions(condition("processing_item", "韩褶")), vars, null)).isTrue();
        assertThat(matches(conditions(condition("shaped", "true")), vars, null)).isTrue();

        // 逐字：多一个字就不命中（不做「包含」匹配 —— 那会把「布贴」和「布贴加厚」混成一件事）
        assertThat(matches(conditions(condition("option", "布贴加厚")), vars, "布帘")).isFalse();
        // 部位限定
        assertThat(matches(conditions(condition("option", "布贴")), vars, "纱帘")).isFalse();
        // 空 conditions = 恒真（「公共」项：只靠部位圈范围）
        assertThat(matches(conditions(), vars, "布帘")).isTrue();
        assertThat(matches(conditions(), vars, "纱帘")).isFalse();
        // 未知 kind / 空 values ⇒ fail-closed
        assertThat(matches(conditions(condition("whatever", "布贴")), vars, null)).isFalse();
        assertThat(matches(conditions(condition("option")), vars, null)).isFalse();
    }

    @Test
    @DisplayName("求和 + 取整：2.92 + 0.015 = 2.935（三位小数）")
    void sumsAndRounds() {
        Map<String, Object> config = config(List.of(
                item("butie", "布贴", "0.015", "add", true, null,
                        conditions(condition("option", "布贴")))), "half_up", 3);

        Result result = CuttingHeightCalculator.compute(config, vars("2.92", List.of("布贴")));

        assertThat(result.base()).isEqualByComparingTo("2.92");
        assertThat(result.cuttingHeight()).isEqualByComparingTo("2.935");
        assertThat(result.hits()).extracting(Hit::key).containsExactly("butie");
        assertThat(result.misses()).isEmpty();
    }

    @Test
    @DisplayName("🔴 兜底是「替换」：专用项命中 ⇒ 兜底组整组不参与")
    void fallbackGroupIsReplacedNotAdded() {
        Map<String, Object> config = config(List.of(
                item("bangdai_hanzhe", "布绑带-韩褶", "0.14", "add", true, "布帘",
                        CuttingHeightCalculator.SCOPE_SPECIFIC,
                        conditions(condition("option", "布绑带"), condition("craft", "韩褶"))),
                item("butie", "布贴", "0.015", "add", true, "布帘",
                        CuttingHeightCalculator.SCOPE_FALLBACK, conditions())), "half_up", 3);

        // 布绑带 ∧ 韩褶 命中 ⇒ 专用组生效；工艺必须逐字给（craft=null 时两条专用项都不命中 ⇒ 会走兜底）
        Vars vars = new Vars("布帘", new BigDecimal("2.92"), "韩褶",
                List.of("布绑带", "布贴"), List.of(), null);
        Result result = CuttingHeightCalculator.compute(config, vars);

        // 2.92 + 0.14（不带布贴那 0.015）
        assertThat(result.cuttingHeight()).isEqualByComparingTo("3.06");
        assertThat(result.hits()).extracting(Hit::key).containsExactly("bangdai_hanzhe");
    }

    @Test
    @DisplayName("专用项零命中 ⇒ 兜底组参与（「其他情况都是默认定高参数」）")
    void fallbackGroupAppliesWhenNoSpecificItemHits() {
        Map<String, Object> config = config(List.of(
                item("bangdai_hanzhe", "布绑带-韩褶", "0.14", "add", true, "布帘",
                        CuttingHeightCalculator.SCOPE_SPECIFIC,
                        conditions(condition("option", "布绑带"), condition("craft", "韩褶"))),
                item("butie", "布贴", "0.015", "add", true, "布帘",
                        CuttingHeightCalculator.SCOPE_FALLBACK, conditions())), "half_up", 3);

        Result result = CuttingHeightCalculator.compute(config, vars("2.92", List.of("布贴")));

        assertThat(result.cuttingHeight()).isEqualByComparingTo("2.935");
        assertThat(result.hits()).extracting(Hit::key).containsExactly("butie");
    }

    @Test
    @DisplayName("命中但未配置取值（画线）⇒ 进 misses(unresolved)、不计入、不按 0 算、且不回落兜底")
    void unresolvedItemsAreReportedNotAssumedZero() {
        Map<String, Object> config = config(List.of(
                item("huaxian", "画线", null, "add", true, "布帘",
                        CuttingHeightCalculator.SCOPE_SPECIFIC, conditions(condition("option", "接高"))),
                item("butie", "布贴", "0.015", "add", true, "布帘",
                        CuttingHeightCalculator.SCOPE_FALLBACK, conditions())), "half_up", 3);

        Result result = CuttingHeightCalculator.compute(config, vars("2.92", List.of("接高", "布贴")));

        // 画线命中但没值 ⇒ 不计入；兜底组**不参与**（否则「未配置取值」会被 0.015 盖住、再没人发现）
        assertThat(result.cuttingHeight()).isEqualByComparingTo("2.92");
        assertThat(result.hits()).isEmpty();
        assertThat(result.misses()).singleElement()
                .satisfies(m -> {
                    assertThat(m.key()).isEqualTo("huaxian");
                    assertThat(m.reason()).isEqualTo("unresolved");
                });
    }

    @Test
    @DisplayName("未启用 / 未命中 / 减项：停用不参与、未命中不报、subtract 真的减")
    void disabledMissedAndSubtractItemsBehave() {
        Map<String, Object> config = config(List.of(
                item("disabled", "已停用", "1", "add", false, null, conditions(condition("option", "已停用"))),
                item("missed", "没勾", "1", "add", true, null, conditions(condition("option", "没勾"))),
                item("deduct", "减项", "0.02", "subtract", true, null, conditions(condition("option", "减项")))),
                "half_up", 3);

        Result result = CuttingHeightCalculator.compute(config, vars("2.92", List.of("减项")));

        assertThat(result.cuttingHeight()).isEqualByComparingTo("2.9");
        assertThat(result.hits()).extracting(Hit::key).containsExactly("deduct");
        // 未命中的项**不进** misses（常态不报，免得把「真的缺东西」淹掉）
        assertThat(result.misses()).isEmpty();
    }

    @Test
    @DisplayName("取整三档 + 位数上界 3")
    void roundsInThreeModes() {
        BigDecimal value = new BigDecimal("2.9355");

        assertThat(CuttingHeightCalculator.round(value, "half_up", 3)).isEqualByComparingTo("2.936");
        assertThat(CuttingHeightCalculator.round(value, "down", 3)).isEqualByComparingTo("2.935");
        assertThat(CuttingHeightCalculator.round(value, "up", 2)).isEqualByComparingTo("2.94");
        // 超界位数按 3 截（配置写面已拒，这里只是不放大事故）
        assertThat(CuttingHeightCalculator.round(value, "half_up", 9)).isEqualByComparingTo("2.936");
    }

    // ── helpers ──

    private static Vars vars(String finishedHeight, List<String> options) {
        return new Vars("布帘", new BigDecimal(finishedHeight), null, options, List.of(), null);
    }

    private static boolean matches(List<Map<String, Object>> conditions, Vars vars, String position) {
        return CuttingHeightCalculator.matches(
                item("k", "n", "0.01", "add", true, position, conditions), vars);
    }

    private static Map<String, Object> condition(String kind, String... values) {
        Map<String, Object> condition = new LinkedHashMap<>();
        condition.put("kind", kind);
        condition.put("values", List.of(values));
        return condition;
    }

    @SafeVarargs
    private static List<Map<String, Object>> conditions(Map<String, Object>... conditions) {
        return new ArrayList<>(List.of(conditions));
    }

    private static Map<String, Object> item(String key, String name, String value, String direction,
                                            boolean enabled, String position,
                                            List<Map<String, Object>> conditions) {
        return item(key, name, value, direction, enabled, position, CuttingHeightCalculator.SCOPE_SPECIFIC, conditions);
    }

    private static Map<String, Object> item(String key, String name, String value, String direction,
                                            boolean enabled, String position, String scope,
                                            List<Map<String, Object>> conditions) {
        Map<String, Object> item = new LinkedHashMap<>();
        item.put("key", key);
        item.put("name", name);
        item.put("value", value == null ? null : new BigDecimal(value));
        item.put("direction", direction);
        item.put("height_join", false);
        item.put("scope", scope);
        item.put("position", position);
        item.put("conditions", conditions);
        item.put("enabled", enabled);
        item.put("order", 10);
        return item;
    }

    private static Map<String, Object> config(List<Map<String, Object>> items, String mode, int digits) {
        Map<String, Object> rounding = new LinkedHashMap<>();
        rounding.put("mode", mode);
        rounding.put("digits", digits);
        Map<String, Object> config = new LinkedHashMap<>();
        config.put("items", new ArrayList<>(items));
        config.put("rounding", rounding);
        return config;
    }
}
