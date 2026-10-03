// case_ids: AS-013
package com.migao.admin.service;

import com.migao.admin.exception.BusinessException;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * 金额小数位准入本体（{@link MoneyScale}，issue #6221）的单测。
 *
 * <h2>它治什么</h2>
 * 金额列是 {@code NUMERIC(·,2)}（{@code orders.refund_amount} / {@code finance_transactions.amount}
 * 均 {@code NUMERIC(12,2)}），PG 对超 scale 的写入**只四舍五入、不报错** ⇒ 缺应用层准入时
 * {@code refund_amount=0.001} 得 200、库内却是 {@code 0.00}。本判据钉住「超 2 位小数 ⇒ 422 显式拒绝」。
 *
 * <h2>舍入方向登记（**不作缺陷判据**，issue #6221 逐字读数）</h2>
 * 修前（被测构建点 {@code main-live} HEAD = {@code 43ca70322}）实测：{@code 0.004 ⇒ 0}、
 * {@code 0.005 ⇒ 0.01}、{@code 0.009 ⇒ 0.01}（PG 的 {@code numeric(·,2)} 是**半进位** half-up，
 * 远离 0）。本判据**不改**这个方向、也**不**依赖它 —— 修后这三个值在应用层就被拒（见
 * {@link #registeredRoundingDirection_isPgHalfUp_andSubCentValuesAreNowRejected()}），到不了库。
 * 登记它是为了可复核「为什么必须拒」：静默取整的结果可上可下（0.004 归零、0.005 进位），
 * 调用方无法预期，而涉钱面的「无法预期」= 账实不符且无人发现。
 */
@DisplayName("金额小数位准入 MoneyScale（issue #6221）")
class MoneyScaleTest {

    @Test
    @DisplayName("2 位及以内小数：合法且**原样返回**（不做 setScale 归一，不引入白改）")
    void acceptsUpToTwoDecimalsAndReturnsValueUnchanged() {
        assertThat(MoneyScale.requireTwoDecimalsOrNull(new BigDecimal("0.01"), "退款金额").toPlainString())
                .isEqualTo("0.01");
        assertThat(MoneyScale.requireTwoDecimalsOrNull(new BigDecimal("599.00"), "退款金额").toPlainString())
                .isEqualTo("599.00");
        assertThat(MoneyScale.requireTwoDecimalsOrNull(new BigDecimal("0"), "退款金额").toPlainString())
                .isEqualTo("0");
        assertThat(MoneyScale.requireTwoDecimalsOrNull(new BigDecimal("100"), "退款金额").toPlainString())
                .isEqualTo("100");
    }

    @Test
    @DisplayName("按**有效**小数位判（尾零不算）：2.700 / 0.010 合法，且书写精度原样保留")
    void judgesEffectiveScaleNotWrittenScale() {
        assertThat(MoneyScale.requireTwoDecimalsOrNull(new BigDecimal("2.700"), "金额").toPlainString())
                .isEqualTo("2.700");
        assertThat(MoneyScale.requireTwoDecimalsOrNull(new BigDecimal("0.010"), "金额").toPlainString())
                .isEqualTo("0.010");
    }

    @Test
    @DisplayName("3 位小数 ⇒ 422 显式拒绝（不四舍五入、不截断），文案可行动")
    void rejectsThreeDecimalsExplicitly() {
        assertThatThrownBy(() -> MoneyScale.requireTwoDecimalsOrNull(new BigDecimal("0.001"), "退款金额"))
                .isInstanceOfSatisfying(BusinessException.class, e -> {
                    assertThat(e.getHttpStatus()).isEqualTo(422);
                    assertThat(e.getMessage()).contains("退款金额")
                            .contains("最多支持 2 位小数")
                            .contains("0.001")
                            .contains("3 位小数");
                });
    }

    @Test
    @DisplayName("null = 「本字段未传」⇒ 原样 null（退款语义：null = 全额退，不得被归一成 0）")
    void nullMeansAbsentNotZero() {
        assertThat(MoneyScale.requireTwoDecimalsOrNull(null, "退款金额")).isNull();
    }

    @Test
    @DisplayName("舍入方向登记：PG 半进位 0.004⇒0 / 0.005⇒0.01 / 0.009⇒0.01；修后三个子分级值一律被拒")
    void registeredRoundingDirection_isPgHalfUp_andSubCentValuesAreNowRejected() {
        // ① 库层方向（PG numeric(·,2) = half-up，远离 0）—— 登记，不作为本单的缺陷判据
        assertThat(new BigDecimal("0.004").setScale(2, RoundingMode.HALF_UP).toPlainString()).isEqualTo("0.00");
        assertThat(new BigDecimal("0.005").setScale(2, RoundingMode.HALF_UP).toPlainString()).isEqualTo("0.01");
        assertThat(new BigDecimal("0.009").setScale(2, RoundingMode.HALF_UP).toPlainString()).isEqualTo("0.01");

        // ② 修后形态：这三个值在**应用层**被显式拒绝 ⇒ 不可能再走到库层的静默取整
        for (String raw : List.of("0.004", "0.005", "0.009")) {
            assertThatThrownBy(() -> MoneyScale.requireTwoDecimalsOrNull(new BigDecimal(raw), "退款金额"))
                    .as("子分级金额 %s 必须被显式拒绝（修前是 200 + 静默取整）", raw)
                    .isInstanceOf(BusinessException.class)
                    .hasMessageContaining("最多支持 2 位小数");
        }
    }
}
