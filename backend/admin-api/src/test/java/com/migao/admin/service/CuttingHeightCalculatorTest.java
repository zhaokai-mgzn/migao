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
 * 裁剪高度纯计算测试（V140，母单 #5161）—— 命中推导 + 求和 + 取整。
 *
 * <p>判据（每条都能红）：</p>
 * <ol>
 *   <li><b>四类触发逐字比对</b>：特殊选项 / 工艺 / 加工项 / 定型（红证：改成「包含」匹配 ⇒ 红）；</li>
 *   <li><b>部位限定生效</b>（{@code position} 不匹配 ⇒ 不命中）；</li>
 *   <li><b>未配置取值（{@code value=null}）⇒ 不计入、也不按 0 算</b>，进 {@code misses(unresolved)}；</li>
 *   <li><b>未启用的项不参与</b>；</li>
 *   <li><b>减项（{@code direction=subtract}）真的减</b>；</li>
 *   <li><b>取整三档</b>（half_up / down / up）+ 位数上界 3；</li>
 *   <li><b>未知 trigger_kind ⇒ 不命中</b>（fail-closed：写面已拒，走到这里的只能是历史脏数据）。</li>
 * </ol>
 */
@DisplayName("CuttingHeightCalculator 裁剪高度计算（V140 / 母单 #5161）")
class CuttingHeightCalculatorTest {

    @Test
    @DisplayName("四类触发逐字比对 + 部位限定")
    void matchesAllFourTriggerKindsVerbatim() {
        Vars vars = new Vars("布帘", new BigDecimal("2.92"), "韩褶",
                List.of("布贴", "接高"), List.of("韩褶"), true);

        assertThat(CuttingHeightCalculator.matches(hit("option", "布贴", "布帘"), vars)).isTrue();
        assertThat(CuttingHeightCalculator.matches(hit("craft", "韩褶", "布帘"), vars)).isTrue();
        assertThat(CuttingHeightCalculator.matches(hit("processing_item", "韩褶", null), vars)).isTrue();
        assertThat(CuttingHeightCalculator.matches(hit("shaped", "true", null), vars)).isTrue();

        // 逐字：多一个字就不命中（不做「包含」匹配 —— 那会把「布贴」和「布贴加厚」混成一件事）
        assertThat(CuttingHeightCalculator.matches(hit("option", "布贴加厚", "布帘"), vars)).isFalse();
        // 部位限定
        assertThat(CuttingHeightCalculator.matches(hit("option", "布贴", "纱帘"), vars)).isFalse();
        assertThat(CuttingHeightCalculator.matches(hit("option", "布贴", null), vars)).isTrue();
        // 未知类型 fail-closed
        assertThat(CuttingHeightCalculator.matches(hit("whatever", "布贴", null), vars)).isFalse();
    }

    @Test
    @DisplayName("求和 + 取整：2.92 + 0.015 = 2.935（三位小数）")
    void sumsAndRounds() {
        Map<String, Object> config = config(List.of(
                item("butie", "布贴", "0.015", "add", true, hit("option", "布贴", null))), "half_up", 3);

        Result result = CuttingHeightCalculator.compute(config, vars("2.92", List.of("布贴")));

        assertThat(result.base()).isEqualByComparingTo("2.92");
        assertThat(result.cuttingHeight()).isEqualByComparingTo("2.935");
        assertThat(result.hits()).extracting(Hit::key).containsExactly("butie");
        assertThat(result.misses()).isEmpty();
    }

    @Test
    @DisplayName("命中但未配置取值（画线）⇒ 进 misses(unresolved)、不计入、不按 0 算")
    void unresolvedItemsAreReportedNotAssumedZero() {
        Map<String, Object> config = config(List.of(
                item("huaxian", "画线", null, "add", true, hit("option", "画线", null)),
                item("butie", "布贴", "0.015", "add", true, hit("option", "布贴", null))), "half_up", 3);

        Result result = CuttingHeightCalculator.compute(config, vars("2.92", List.of("画线", "布贴")));

        assertThat(result.cuttingHeight()).isEqualByComparingTo("2.935");   // 只加了布贴
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
                item("disabled", "已停用", "1", "add", false, hit("option", "已停用", null)),
                item("missed", "没勾", "1", "add", true, hit("option", "没勾", null)),
                item("deduct", "减项", "0.02", "subtract", true, hit("option", "减项", null))), "half_up", 3);

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

    private static Map<String, Object> hit(String kind, String value, String position) {
        Map<String, Object> hit = new LinkedHashMap<>();
        hit.put("trigger_kind", kind);
        hit.put("trigger_value", value);
        hit.put("position", position);
        return hit;
    }

    private static Map<String, Object> item(String key, String name, String value, String direction,
                                            boolean enabled, Map<String, Object> hit) {
        Map<String, Object> item = new LinkedHashMap<>();
        item.put("key", key);
        item.put("name", name);
        item.put("value", value == null ? null : new BigDecimal(value));
        item.put("direction", direction);
        item.put("height_join", false);
        item.put("hit", hit);
        item.put("hit_expr", null);
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
