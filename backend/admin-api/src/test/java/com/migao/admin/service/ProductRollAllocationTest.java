// case_ids: PR-044, OR-046
package com.migao.admin.service;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 「优先整卷发货」分配算法（{@link ProductRollAllocation}）的判据。
 *
 * <p>用户裁定 2026-09-21 原话：「在订单中再体现<b>客户要求优先整卷发货</b>，
 * 例子：客户买 100 米布，一卷=60 米，那就发 <b>1 整卷 60 + 散剪出的 40 米</b>」——
 * 本条用**原话里的那组数**当第一条断言（判据与需求同源，不是自造的样例）。</p>
 *
 * <p>红证（修复前必红）：本类在 V108 之前不存在（整卷/散剪是 SKU 组合维度，
 * 「一卷多少米」根本没有落库的地方）⇒ 编译期即红。分配方向的红证见
 * {@link #floorNotRound()}（把向下取整改成四舍五入 ⇒ 50/60 得 1 卷 ⇒ 断言红）。</p>
 */
@DisplayName("V108 优先整卷发货分配：roll_count = floor(qty / roll_length_m)")
class ProductRollAllocationTest {

    private static BigDecimal bd(String v) {
        return new BigDecimal(v);
    }

    @Test
    @DisplayName("用户裁定原话例：买 100 米、一卷 60 米 ⇒ 1 整卷 + 40 米散剪")
    void userRulingExample() {
        ProductRollAllocation.Allocation a =
                ProductRollAllocation.allocate(bd("100"), bd("60"));

        assertThat(a.allocated()).isTrue();
        assertThat(a.rollCount()).isEqualTo(1);
        assertThat(a.rollLengthM()).isEqualByComparingTo("60");
        assertThat(a.cutMeters()).isEqualByComparingTo("40");
    }

    @Test
    @DisplayName("恰好整卷倍数：120 / 60 ⇒ 2 卷 + 0 米散剪（0 是真实结论，不是空值）")
    void exactMultipleLeavesZeroCut() {
        ProductRollAllocation.Allocation a =
                ProductRollAllocation.allocate(bd("120"), bd("60"));

        assertThat(a.rollCount()).isEqualTo(2);
        assertThat(a.cutMeters()).isEqualByComparingTo("0");
    }

    @Test
    @DisplayName("floorNotRound：不足一卷 ⇒ 0 整卷 + 全部散剪（四舍五入会错发一整卷）")
    void floorNotRound() {
        // 50 / 60 = 0.833… ⇒ floor = 0（四舍五入会得 1 ⇒ 多发一整卷，仓库照它拣货就发错货）
        ProductRollAllocation.Allocation a =
                ProductRollAllocation.allocate(bd("50"), bd("60"));

        assertThat(a.rollCount()).isZero();
        assertThat(a.cutMeters()).isEqualByComparingTo("50");
    }

    @Test
    @DisplayName("卷长未知（NULL）⇒ 未分配：三字段全 null，不用任何兜底常量推算")
    void nullRollLengthIsNotAllocated() {
        ProductRollAllocation.Allocation a = ProductRollAllocation.allocate(bd("100"), null);

        assertThat(a.allocated()).isFalse();
        assertThat(a.rollCount()).isNull();
        assertThat(a.rollLengthM()).isNull();
        assertThat(a.cutMeters()).isNull();
    }

    @Test
    @DisplayName("非正卷长 / 非正数量 ⇒ 未分配（不落 0 —— 「不知道」不许伪装成「0 整卷」）")
    void nonPositiveInputsAreNotAllocated() {
        for (BigDecimal badRoll : new BigDecimal[] {bd("0"), bd("-60")}) {
            ProductRollAllocation.Allocation a = ProductRollAllocation.allocate(bd("100"), badRoll);
            assertThat(a.allocated()).as("rollLength=%s", badRoll).isFalse();
            assertThat(a.rollCount()).isNull();
        }
        for (BigDecimal badQty : new BigDecimal[] {bd("0"), bd("-5"), null}) {
            ProductRollAllocation.Allocation a = ProductRollAllocation.allocate(badQty, bd("60"));
            assertThat(a.allocated()).as("quantity=%s", badQty).isFalse();
            assertThat(a.rollCount()).isNull();
        }
    }

    @Test
    @DisplayName("小数米数：100.5 / 60 ⇒ 1 卷 + 40.5 米散剪（米数不是整数，不得截断）")
    void decimalQuantityKeepsFraction() {
        ProductRollAllocation.Allocation a =
                ProductRollAllocation.allocate(bd("100.5"), bd("60"));

        assertThat(a.rollCount()).isEqualTo(1);
        assertThat(a.cutMeters()).isEqualByComparingTo("40.5");
    }

    @Test
    @DisplayName("溢出 ⇒ 未分配（不是 500）：数量极大 / 卷长极小")
    void overflowIsNotAllocatedNot500() {
        // 独立对抗式复核实测抓到：`quantity.divide(...).intValueExact()` 在
        // `1e9 / 0.01`、`2147483648 / 1` 这类输入上抛 ArithmeticException: Overflow。
        // `quantity` 只受 @DecimalMin("1") 卡下限（无上限），`roll_length_m` 是 NUMERIC(8,2)
        // （可到 0.01）⇒ 非正常但可达的输入会让**建单 500**。
        // 本类红线：算不出来就**不分配**（也不许变成 500）。
        for (BigDecimal[] pair : new BigDecimal[][] {
                {new BigDecimal("1000000000"), new BigDecimal("0.01")},
                {new BigDecimal("2147483648"), BigDecimal.ONE},
                {new BigDecimal("100000000000"), BigDecimal.ONE}}) {
            ProductRollAllocation.Allocation a =
                    ProductRollAllocation.allocate(pair[0], pair[1]);
            assertThat(a.allocated())
                    .as("quantity=%s rollLength=%s 应当「未分配」而不是抛异常", pair[0], pair[1])
                    .isFalse();
            assertThat(a.rollCount()).isNull();
        }
    }

    @Test
    @DisplayName("多卷：200 / 60 ⇒ 3 卷 + 20 米散剪")
    void multipleRolls() {
        ProductRollAllocation.Allocation a =
                ProductRollAllocation.allocate(bd("200"), bd("60"));

        assertThat(a.rollCount()).isEqualTo(3);
        assertThat(a.cutMeters()).isEqualByComparingTo("20");
    }
}
