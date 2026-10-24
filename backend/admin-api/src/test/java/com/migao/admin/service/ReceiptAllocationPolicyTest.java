// case_ids: AR-002
package com.migao.admin.service;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 核销准入（issue #7370，P0-2 段 3）—— **两条上限各自独立**的边界判据。
 *
 * <p>为什么单独考纯函数：这里算错的两个方向都**不可逆**——算宽了 = 同一张单被重复收钱、一笔钱被重复用；
 * 算窄了 = 明明能冲的钱冲不进去（对账永远差一笔）。而错的时候屏幕上的数字**依然合理**。</p>
 *
 * <p>红证方向：把 {@code allocatable} 从 {@code min(收款剩余, 订单剩余)} 改成「只取收款剩余」⇒
 * {@link #orderSideCapWinsWhenOrderIsSmaller} 当场红。</p>
 */
@DisplayName("核销准入：收款侧上限 / 订单侧上限 / 取小 / 0 与负数拒")
class ReceiptAllocationPolicyTest {

    private static ReceiptAllocationPolicy.Decision eval(String receipt, String alreadyAllocated,
                                                        String orderTotal, String refunded,
                                                        String orderAllocated, String requested) {
        return ReceiptAllocationPolicy.evaluate(bd(receipt), bd(alreadyAllocated),
                bd(orderTotal), bd(refunded), bd(orderAllocated), bd(requested));
    }

    private static BigDecimal bd(String value) {
        return value == null ? null : new BigDecimal(value);
    }

    @Test
    @DisplayName("正常放行：可核销 = min(收款剩余, 订单剩余)")
    void plainExactAllocation() {
        var d = eval("1000", null, "600", null, null, "600");
        assertThat(d.allowed()).isTrue();
        assertThat(d.allocatable()).isEqualByComparingTo("600");
        assertThat(d.excess()).isEqualByComparingTo("0");
    }

    @Test
    @DisplayName("🔴 收款侧上限：已部分核销 ⇒ 只剩差额（不许把同一笔钱用两次）")
    void receiptSideCapWinsWhenReceiptIsSmaller() {
        // 流水 1000，已核销 900 ⇒ 只剩 100；订单还有 5000
        var ok = eval("1000", "900", "5000", null, null, "100");
        assertThat(ok.allowed()).as("刚好用完剩余 ⇒ 放行").isTrue();

        var over = eval("1000", "900", "5000", null, null, "101");
        assertThat(over.allowed()).isFalse();
        assertThat(over.allocatable()).isEqualByComparingTo("100");
        assertThat(over.excess()).as("超出的部分要能说出来（可行动提示）").isEqualByComparingTo("1");
    }

    @Test
    @DisplayName("🔴 订单侧上限：订单剩余更小 ⇒ 以订单为准（同一张单不许被重复收钱）")
    void orderSideCapWinsWhenOrderIsSmaller() {
        // 流水 10000，已核销 0；订单货值 600、已退 100、已核销 400 ⇒ 只剩 100
        var over = eval("10000", null, "600", "100", "400", "200");
        assertThat(over.allowed()).isFalse();
        assertThat(over.allocatable()).isEqualByComparingTo("100");
        assertThat(over.excess()).isEqualByComparingTo("100");

        var ok = eval("10000", null, "600", "100", "400", "100");
        assertThat(ok.allowed()).isTrue();
    }

    @Test
    @DisplayName("退款冲减应收：退满的订单不能再核销（可核销 = 0）")
    void fullyRefundedOrderHasNothingToAllocate() {
        var d = eval("1000", null, "800", "800", null, "1");
        assertThat(d.allowed()).isFalse();
        assertThat(d.allocatable()).isEqualByComparingTo("0");
    }

    @Test
    @DisplayName("0 与负数：直接拒（不产生「冲了一点点」的空行）")
    void zeroAndNegativeAreRejected() {
        assertThat(eval("1000", null, "1000", null, null, "0").allowed()).isFalse();
        assertThat(eval("1000", null, "1000", null, null, "-5").allowed()).isFalse();
        assertThat(eval("1000", null, "1000", null, null, null).allowed()).isFalse();
        // 「申请 0」时的可核销上限仍要如实给出（前端要显示「这单还能冲 1000」）
        assertThat(eval("1000", null, "1000", null, null, "0").allocatable()).isEqualByComparingTo("1000");
    }

    @Test
    @DisplayName("脏数据不让页面 500：上限算成负数一律归 0（多收/多退的存量行）")
    void negativeCapacityIsClampedToZero() {
        // 已核销 1200 > 流水 1000（理论不该出现，存量可能）⇒ 剩余归 0，不是 -200
        var d = eval("1000", "1200", "5000", null, null, "1");
        assertThat(d.allocatable()).isEqualByComparingTo("0");
        assertThat(d.allowed()).isFalse();
        // 订单侧同理：退款 + 已核销 > 货值
        assertThat(eval("5000", null, "600", "500", "400", "1").allocatable()).isEqualByComparingTo("0");
    }

    @Test
    @DisplayName("金额一律 2 位小数（钱只有两位小数的物理意义）")
    void amountsAreScaledToTwoDecimals() {
        var d = eval("1000.005", null, "1000.005", null, null, "1000.01");
        assertThat(d.allocatable().scale()).isEqualTo(2);
        assertThat(d.excess().scale()).isEqualTo(2);
    }
}
