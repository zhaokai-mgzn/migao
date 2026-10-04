// case_ids: PR-122
// `ColumnTextLength`（文本列长度准入，issue #6302）的**判据本体**单测：
// 它只做准入（拒绝）、不做截断/归一，且长度按**码点**算（PG `varchar(n)` 数的是字符）——
// 这三条语义各由一条判据钉住（前两条防「顺手截断」的回归，第三条防「改用 String.length()」的回归）。
package com.migao.admin.service;

import com.migao.admin.exception.BusinessException;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

@DisplayName("文本列长度准入 ColumnTextLength（issue #6302）")
class ColumnTextLengthTest {

    private static final int MAX = 30;

    @Test
    @DisplayName("判据1：null = 「本字段未传」⇒ 原样返回 null（长度判据不管必填）")
    void nullPassesThroughAsNull() {
        assertThat(ColumnTextLength.requireWithinOrNull(null, MAX, "商品货号 skuCode")).isNull();
        assertThat(ColumnTextLength.lengthProblemOrNull(null, MAX, "商品货号 skuCode")).isNull();
    }

    @Test
    @DisplayName("判据2（边界）：恰好 = 列上限 ⇒ 合法且**原样返回**（不截断、不去尾空格、不归一）")
    void atLimitIsReturnedVerbatim() {
        String atLimit = "A".repeat(MAX);

        assertThat(ColumnTextLength.requireWithinOrNull(atLimit, MAX, "商品货号 skuCode"))
                .as("准入只判长度，不修改值（静默截断 = 货号被改掉而无人知道）")
                .isSameAs(atLimit);

        // 首尾空格也**原样返回**（不做 trim：trim 是另一种「静默改值」）
        String padded = " " + "中".repeat(MAX - 2) + " ";
        assertThat(padded).hasSize(MAX);
        assertThat(ColumnTextLength.requireWithinOrNull(padded, MAX, "x")).isEqualTo(padded);
    }

    @Test
    @DisplayName("判据3：超 1 个字符 ⇒ 422 VALIDATION_ERROR + 可行动文案（最长 N / 当前 M / 请缩短）")
    void overLimitIsRejectedWithActionableMessage() {
        String over = "A".repeat(MAX + 1);

        assertThatThrownBy(() -> ColumnTextLength.requireWithinOrNull(over, MAX, "商品货号 skuCode"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("商品货号 skuCode")
                .hasMessageContaining("最长 " + MAX + " 个字符")
                .hasMessageContaining("当前 " + (MAX + 1) + " 个字符")
                .hasMessageContaining("请缩短")
                .hasMessageContaining("不截断");

        BusinessException e = (BusinessException) org.assertj.core.api.Assertions.catchThrowable(
                () -> ColumnTextLength.requireWithinOrNull(over, MAX, "商品货号 skuCode"));
        assertThat(e).isNotNull();
        assertThat(e.getCode()).as("4xx 可行动文案，不是 500").isEqualTo("VALIDATION_ERROR");
        assertThat(e.getHttpStatus()).isEqualTo(422);
    }

    @Test
    @DisplayName("判据4（码点口径）：30 个 emoji（Java length = 60）合法 —— PG varchar(30) 数的是**字符**")
    void lengthIsCountedInCodePointsNotUtf16Units() {
        String thirtyEmoji = "😀".repeat(MAX);
        assertThat(thirtyEmoji.length()).as("Java 的 UTF-16 长度是 60（增补平面字符占 2 个码元）").isEqualTo(MAX * 2);

        assertThat(ColumnTextLength.requireWithinOrNull(thirtyEmoji, MAX, "商品货号 skuCode"))
                .as("按 String.length() 判会把库列**装得下**的输入假红 —— 必须按码点数")
                .isSameAs(thirtyEmoji);
        assertThatThrownBy(() -> ColumnTextLength.requireWithinOrNull("😀".repeat(MAX + 1), MAX, "商品货号 skuCode"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("当前 " + (MAX + 1) + " 个字符");
    }

    @Test
    @DisplayName("判据5：多字节中文按**字符**数（30 个合法 / 31 个拒绝），不是按字节数")
    void cjkIsCountedByCharacterNotByte() {
        assertThat(ColumnTextLength.requireWithinOrNull("米".repeat(MAX), MAX, "颜色名称 colorName"))
                .isEqualTo("米".repeat(MAX));
        assertThatThrownBy(() -> ColumnTextLength.requireWithinOrNull("米".repeat(MAX + 1), MAX, "颜色名称 colorName"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("当前 " + (MAX + 1) + " 个字符");
    }

    @Test
    @DisplayName("判据6：收集式形态 lengthProblemOrNull —— 合法 / 超长（只给文案不抛）/ null 三态")
    void collectFormReturnsTextInsteadOfThrowing() {
        assertThat(ColumnTextLength.lengthProblemOrNull("A".repeat(MAX), MAX, "商品货号 skuCode")).isNull();
        assertThat(ColumnTextLength.lengthProblemOrNull("A".repeat(MAX + 1), MAX, "商品货号 skuCode"))
                .as("收集式入口要的是文案而不是立刻抛（避免再写第二份长度判定）")
                .contains("最长 " + MAX + " 个字符");
    }
}
