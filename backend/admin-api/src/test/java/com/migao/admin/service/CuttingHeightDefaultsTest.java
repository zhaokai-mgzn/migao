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
 * 裁高默认种子测试（V140，母单 #5161）。
 *
 * <p>判据（每条都能红）：</p>
 * <ol>
 *   <li><b>7 项逐字</b>（key / 名称 / 取值）—— 种子是**全仓唯一来源**，改一处即全绿、改错即红；
 *       红证：删掉「画线」/ 把 0.015 写成 0.15 ⇒ 红；</li>
 *   <li><b>「画线」有项无值</b>（{@code value=null}）：不替它编数、也不按 0 算；</li>
 *   <li><b>默认取整 = 三位小数</b>（机器三位小数，用 2.935）；</li>
 *   <li><b>每次调用返回新结构</b>：调用方（写面 / 序列化）会改它，共享可变实例 = 一次写污染后续读
 *       （红证：返回同一个 List ⇒ 改一次再读就变了）。</li>
 * </ol>
 */
@DisplayName("CuttingHeightDefaults 默认种子（V140 / 母单 #5161）")
class CuttingHeightDefaultsTest {

    @Test
    @DisplayName("7 项逐字（壁达现场弹窗那 7 项），顺序稳定")
    void seedIsTheSevenItemsFromTheVendorDialog() {
        List<Map<String, Object>> items = CuttingHeightDefaults.items();

        assertThat(items).extracting(i -> i.get("key"))
                .containsExactly("baobuzhe", "baobukong", "baoshazhe", "baoshakong", "huaxian", "butie", "shatie");
        assertThat(items).extracting(i -> i.get("name"))
                .containsExactly("包布折", "包布孔", "包纱折", "包纱孔", "画线", "布贴", "纱贴");
        assertThat(value(items, "baobuzhe")).isEqualByComparingTo("0.08");
        assertThat(value(items, "baobukong")).isEqualByComparingTo("0.1");
        assertThat(value(items, "baoshazhe")).isEqualByComparingTo("0.08");
        assertThat(value(items, "baoshakong")).isEqualByComparingTo("0.1");
        assertThat(value(items, "butie")).isEqualByComparingTo("0.015");
        assertThat(value(items, "shatie")).isEqualByComparingTo("0.01");
    }

    @Test
    @DisplayName("「画线」是**有项无值**（不编数、不按 0 算）")
    void huaxianHasNoValue() {
        Map<String, Object> huaxian = item(CuttingHeightDefaults.items(), "huaxian");

        assertThat(huaxian.get("value")).isNull();
        assertThat(huaxian.get("enabled")).isEqualTo(true);
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

        assertThat(item(CuttingHeightDefaults.items(), "baobuzhe").get("name")).isEqualTo("包布折");
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

    private static BigDecimal value(List<Map<String, Object>> items, String key) {
        Object raw = item(items, key).get("value");
        return raw == null ? null : new BigDecimal(String.valueOf(raw));
    }

    /** 供未来扩展：断言默认配置整体形状（避免有人只测 items 忘了 rounding）。 */
    static Map<String, Object> expectedShape() {
        Map<String, Object> shape = new LinkedHashMap<>();
        shape.put("items", 7);
        shape.put("rounding", 3);
        return shape;
    }
}
