package com.migao.admin.service;
// case_ids: OR-006, PR-010

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * SkuNotation 归一化口径单测（issue #3621）。
 *
 * <p>核心断言：同一物理规格的不同写法必须等价；**真正不同的门幅 / 售卖方式仍不得等价**
 * （防归一化过宽把不同 SKU 合并 —— 本类修复的最大风险）。
 */
class SkuNotationTest {

    @Test
    @DisplayName("#3621 门幅归一化：去「门幅」前缀与「米/m」后缀，不做数值换算")
    void normalizeDoorWidth_stripsPrefixAndUnit() {
        assertThat(SkuNotation.normalizeDoorWidth("2.8")).isEqualTo("2.8");
        assertThat(SkuNotation.normalizeDoorWidth("2.8米")).isEqualTo("2.8");
        assertThat(SkuNotation.normalizeDoorWidth("门幅2.8米")).isEqualTo("2.8");
        assertThat(SkuNotation.normalizeDoorWidth("2.8m")).isEqualTo("2.8");
        assertThat(SkuNotation.normalizeDoorWidth(" 2.8 M ")).isEqualTo("2.8");
        assertThat(SkuNotation.normalizeDoorWidth(null)).isNull();
        assertThat(SkuNotation.normalizeDoorWidth("  ")).isNull();
    }

    @Test
    @DisplayName("#3621 sameDoorWidth：同写法等价，真正不同的门幅不等价（反向断言）")
    void sameDoorWidth_equivalenceAndReverseAssertion() {
        // 同一物理门幅（双侧归一化）
        assertThat(SkuNotation.sameDoorWidth("2.8", "2.8米")).isTrue();
        assertThat(SkuNotation.sameDoorWidth("2.8米", "门幅2.8米")).isTrue();
        assertThat(SkuNotation.sameDoorWidth("3.2m", "3.2")).isTrue();

        // 反向断言：不同门幅绝不等价（防归一化过宽合并不同 SKU）
        assertThat(SkuNotation.sameDoorWidth("2.8", "3.2")).isFalse();
        assertThat(SkuNotation.sameDoorWidth("2.8米", "3.2米")).isFalse();
        // 空值不得被当成「与空值等价」
        assertThat(SkuNotation.sameDoorWidth(null, null)).isFalse();
        assertThat(SkuNotation.sameDoorWidth("", "")).isFalse();
        assertThat(SkuNotation.sameDoorWidth("2.8", null)).isFalse();
    }

    @Test
    @DisplayName("#3621 售卖方式归一化：中文业务标签 → 枚举，枚举/未知值原样透传")
    void normalizeSellingMethod_translatesChineseLabels() {
        assertThat(SkuNotation.normalizeSellingMethod("散剪")).isEqualTo("bulk_cut");
        assertThat(SkuNotation.normalizeSellingMethod("整卷")).isEqualTo("full_roll");
        assertThat(SkuNotation.normalizeSellingMethod(" 散剪 ")).isEqualTo("bulk_cut");
        // 已是枚举 → 原样透传（不新增第二套映射）
        assertThat(SkuNotation.normalizeSellingMethod("bulk_cut")).isEqualTo("bulk_cut");
        assertThat(SkuNotation.normalizeSellingMethod(null)).isNull();

        // 反向断言：不同售卖方式不得被归一到同一个值
        assertThat(SkuNotation.normalizeSellingMethod("散剪"))
                .isNotEqualTo(SkuNotation.normalizeSellingMethod("整卷"));
    }
}
