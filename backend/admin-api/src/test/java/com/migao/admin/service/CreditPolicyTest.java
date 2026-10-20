package com.migao.admin.service;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * 授信额度语义的**纯函数判据**（issue #7370，P0-2 段 1）。
 *
 * <p>为什么把口径抽成纯类：额度语义是「业务口径」而不是 SQL —— 把它钉在纯函数上，
 * 边界（null / 0 / 恰好等于 / 超出）就能逐格断言，不依赖 PG 与整条下单链路。
 * 下单入口（`OrderService.createOrder`）只做「取数 + 调这里」。
 *
 * <p>口径（本单裁定，与 issue #7370 同源）：
 * <ul>
 *   <li><b>NULL = 未启用授信</b>（老客户默认值）⇒ 一律放行；</li>
 *   <li><b>0 = 启用但零额度</b> ⇒ 任何赊销都被拒（不是「不限」）；</li>
 *   <li>恰好等于可用额度 ⇒ 放行（边界取闭区间）；</li>
 *   <li>负额度是配置错误 ⇒ 直接抛（不许静默当 0 或当不限）。</li>
 * </ul>
 */
class CreditPolicyTest {

    private static BigDecimal yuan(String v) {
        return new BigDecimal(v);
    }

    @Test
    @DisplayName("NULL 额度 = 未启用授信 ⇒ 放行，且不给出可用额度")
    void nullLimitMeansCreditDisabled() {
        CreditPolicy.Decision d = CreditPolicy.evaluate(null, yuan("99999"), yuan("50000"));
        assertThat(d.allowed()).isTrue();
        assertThat(d.available()).isNull();
        assertThat(d.excess()).isEqualByComparingTo("0");
    }

    @Test
    @DisplayName("额度内 ⇒ 放行，可用额度 = 额度 - 已欠")
    void withinLimit() {
        CreditPolicy.Decision d = CreditPolicy.evaluate(yuan("10000"), yuan("2000"), yuan("5000"));
        assertThat(d.allowed()).isTrue();
        assertThat(d.available()).isEqualByComparingTo("8000");
        assertThat(d.excess()).isEqualByComparingTo("0");
    }

    @Test
    @DisplayName("超额 ⇒ 拒绝，excess 精确到分（可行动提示要用它）")
    void exceedsLimit() {
        CreditPolicy.Decision d = CreditPolicy.evaluate(yuan("10000"), yuan("6000"), yuan("5000"));
        assertThat(d.allowed()).isFalse();
        assertThat(d.available()).isEqualByComparingTo("4000");
        assertThat(d.excess()).isEqualByComparingTo("1000");
    }

    @Test
    @DisplayName("恰好等于可用额度 ⇒ 放行（闭区间边界）")
    void exactlyAtLimit() {
        CreditPolicy.Decision d = CreditPolicy.evaluate(yuan("10000"), yuan("6000"), yuan("4000"));
        assertThat(d.allowed()).isTrue();
        assertThat(d.excess()).isEqualByComparingTo("0");
    }

    @Test
    @DisplayName("额度为 0 ⇒ 任何正数赊销都拒（0 ≠ 不限）")
    void zeroLimitBlocksEverything() {
        CreditPolicy.Decision d = CreditPolicy.evaluate(BigDecimal.ZERO, BigDecimal.ZERO, yuan("0.01"));
        assertThat(d.allowed()).isFalse();
        assertThat(d.excess()).isEqualByComparingTo("0.01");
    }

    @Test
    @DisplayName("已欠为 null ⇒ 视为 0；本单为 null/0 ⇒ 放行")
    void nullAmountsAreZero() {
        assertThat(CreditPolicy.evaluate(yuan("100"), null, yuan("50")).allowed()).isTrue();
        assertThat(CreditPolicy.evaluate(yuan("100"), yuan("100"), BigDecimal.ZERO).allowed()).isTrue();
        assertThat(CreditPolicy.evaluate(yuan("100"), yuan("100"), null).allowed()).isTrue();
    }

    @Test
    @DisplayName("负额度 = 配置错误 ⇒ 抛（不许静默当成 0 或不限）")
    void negativeLimitIsRejected() {
        assertThatThrownBy(() -> CreditPolicy.evaluate(yuan("-1"), BigDecimal.ZERO, yuan("1")))
                .isInstanceOf(IllegalArgumentException.class);
    }
}
