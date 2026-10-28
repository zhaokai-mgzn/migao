package com.migao.admin.service;

// case_ids: PG-045

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 裁高默认种子测试（V140 母单 #5161；v2 = issue #7997）。
 *
 * <p>判据（每条都能红）：</p>
 * <ol>
 *   <li><b>9 项逐字</b>（key / 名称 / 取值 / 作用域）—— 种子是**全仓唯一来源**，改一处即全绿、改错即红；
 *       红证：删掉「画线」/ 把 0.145 写成 0.45 ⇒ 红；</li>
 *   <li><b>工序专用三项的条件逐字</b>：布绑带-韩褶 = 布绑带 ∧ 韩褶、布绑带-打孔 = 布绑带 ∧ 打孔、
 *       画线 = 接高 ∨ 双眼皮接高（红证：把 craft 条件删掉 ⇒ 两条布绑带项会同时命中 ⇒ 红）；</li>
 *   <li><b>兜底组 = 6 项且 scope=fallback</b>（红证：把兜底项标成 specific ⇒ 红）；</li>
 *   <li><b>默认取整 = 三位小数</b>（机器三位小数，用 2.935）；</li>
 *   <li><b>每次调用返回新结构</b>：调用方（写面 / 序列化）会改它，共享可变实例 = 一次写污染后续读。</li>
 * </ol>
 */
@DisplayName("CuttingHeightDefaults 默认种子（v2 / issue #7997）")
class CuttingHeightDefaultsTest {

    @Test
    @DisplayName("9 项逐字：3 项工序专用 + 6 项公共兜底，顺序稳定")
    void seedIsThreeProcessSpecificPlusSixFallbackItems() {
        List<Map<String, Object>> items = CuttingHeightDefaults.items();

        assertThat(items).extracting(i -> i.get("key")).containsExactly(
                "bangdai_hanzhe", "bangdai_dakong", "huaxian",
                "baobuzhe", "baobukong", "baoshazhe", "baoshakong", "butie", "shatie");
        assertThat(items).extracting(i -> i.get("name")).containsExactly(
                "布绑带-韩褶", "布绑带-打孔", "画线",
                "包布折", "包布孔", "包纱折", "包纱孔", "布贴", "纱贴");
        // 现场便签三值（用户 2026-10-28 裁定 3-A：进默认种子，推翻 2026-09-29 裁定③）
        assertThat(value(items, "bangdai_hanzhe")).isEqualByComparingTo("0.14");
        assertThat(value(items, "bangdai_dakong")).isEqualByComparingTo("0.16");
        assertThat(value(items, "huaxian")).isEqualByComparingTo("0.145");
        assertThat(value(items, "baobuzhe")).isEqualByComparingTo("0.08");
        assertThat(value(items, "baobukong")).isEqualByComparingTo("0.1");
        assertThat(value(items, "baoshazhe")).isEqualByComparingTo("0.08");
        assertThat(value(items, "baoshakong")).isEqualByComparingTo("0.1");
        assertThat(value(items, "butie")).isEqualByComparingTo("0.015");
        assertThat(value(items, "shatie")).isEqualByComparingTo("0.01");
    }

    @Test
    @DisplayName("作用域：前三项 specific（工序专用），后六项 fallback（公共兜底）")
    void scopesAreExplicit() {
        List<Map<String, Object>> items = CuttingHeightDefaults.items();

        assertThat(items).extracting(i -> i.get("scope")).containsExactly(
                "specific", "specific", "specific",
                "fallback", "fallback", "fallback", "fallback", "fallback", "fallback");
    }

    @Test
    @DisplayName("工序专用三项的条件逐字（布绑带 ∧ 韩褶/打孔；画线 = 接高 ∨ 双眼皮接高；都限布帘）")
    @SuppressWarnings("unchecked")
    void processSpecificConditionsAreVerbatim() {
        List<Map<String, Object>> items = CuttingHeightDefaults.items();

        assertThat(conditions(items, "bangdai_hanzhe")).satisfiesExactly(
                c -> {
                    assertThat(c.get("kind")).isEqualTo("option");
                    assertThat(c.get("values")).isEqualTo(List.of("布绑带"));
                },
                c -> {
                    assertThat(c.get("kind")).isEqualTo("craft");
                    assertThat(c.get("values")).isEqualTo(List.of("韩褶"));
                });
        assertThat(conditions(items, "bangdai_dakong")).satisfiesExactly(
                c -> assertThat(c.get("kind")).isEqualTo("option"),
                c -> {
                    assertThat(c.get("kind")).isEqualTo("craft");
                    assertThat(c.get("values")).isEqualTo(List.of("打孔"));
                });
        assertThat(conditions(items, "huaxian")).satisfiesExactly(c -> {
            assertThat(c.get("kind")).isEqualTo("option");
            assertThat(c.get("values")).isEqualTo(List.of("接高", "双眼皮接高"));
        });
        // 布绑带是布帘的绑带、接高（接高-布）也只对布帘可做 ⇒ 三项都限部位
        assertThat(items).filteredOn(i -> "specific".equals(i.get("scope")))
                .extracting(i -> i.get("position")).containsOnly("布帘");
    }

    @Test
    @DisplayName("默认取整 = 保留三位小数（half_up）")
    void defaultRoundingKeepsThreeDecimals() {
        Map<String, Object> rounding = CuttingHeightDefaults.rounding();

        assertThat(rounding.get("mode")).isEqualTo("half_up");
        assertThat(rounding.get("digits")).isEqualTo(3);
    }

    @Test
    @DisplayName("每次调用都是新结构（共享可变实例 = 一次写污染后续读）")
    @SuppressWarnings("unchecked")
    void everyCallReturnsAFreshStructure() {
        Map<String, Object> first = CuttingHeightDefaults.config();
        ((List<Map<String, Object>>) first.get("items")).get(0).put("name", "被改过了");

        assertThat(item(CuttingHeightDefaults.items(), "bangdai_hanzhe").get("name")).isEqualTo("布绑带-韩褶");
        assertThat(first).isNotSameAs(CuttingHeightDefaults.config());
    }

    // ── helpers ──

    private static Map<String, Object> item(List<Map<String, Object>> items, String key) {
        for (Map<String, Object> item : items) {
            if (key.equals(item.get("key"))) {
                return item;
            }
        }
        throw new AssertionError("找不到项：" + key);
    }

    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> conditions(List<Map<String, Object>> items, String key) {
        return (List<Map<String, Object>>) item(items, key).get("conditions");
    }

    private static BigDecimal value(List<Map<String, Object>> items, String key) {
        Object raw = item(items, key).get("value");
        return raw == null ? null : new BigDecimal(String.valueOf(raw));
    }

    /** 供未来扩展：断言默认配置整体形状（避免有人只测 items 忘了 rounding）。 */
    static Map<String, Object> expectedShape() {
        Map<String, Object> shape = new LinkedHashMap<>();
        shape.put("items", 9);
        shape.put("rounding", 3);
        return shape;
    }
}
