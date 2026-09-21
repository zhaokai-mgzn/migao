package com.migao.admin.service;

import java.math.BigDecimal;
import java.math.RoundingMode;

/**
 * 「优先整卷发货」的分配算法（用户裁定 2026-09-21）。
 *
 * <p>用户原话：「在订单中再体现<b>客户要求优先整卷发货</b>，例子：客户买 100 米布，一卷=60 米，
 * 那就发 <b>1 整卷 60 + 散剪出的 40 米</b>」。</p>
 *
 * <h2>为什么是纯函数、为什么单独成类</h2>
 * 分配是 {@code quantity} 与 {@code roll_length_m} 的<b>确定性函数</b>（无 IO、无租户上下文），
 * 把它抽成纯函数才能被直接断言「100 米 / 60 米一卷 ⇒ 1 卷 + 40 米散剪」；
 * 而把它放在订单服务里就只能靠「建单 → 读库」间接验证（那验的是落库，不是算法）。
 *
 * <h2>红线：卷长未知 ⇒ <b>不分配</b>，绝不猜</h2>
 * 行业卷长是<b>区间值</b>不是定值（「一卷 60 米<i>左右</i>」——
 * 见 {@code docs/curtain-selling-method-industry-research.md} §5）。
 * 货号未配 {@code roll_length_m}（NULL）或配了非正值时，本类一律返回
 * {@link #notAllocated()}（{@code rollCount = null}）——
 * <b>不允许</b>用「默认 60 米」之类的兜底常量算出一个看似合理的分配：那会把未配置的货号
 * 变成「系统以为一卷 60 米」，仓库照它拣货就发错货。
 *
 * <h2>边界语义（每条都有对应断言）</h2>
 * <ul>
 *   <li>整卷数 = {@code floor(quantity / rollLength)}（向下取整 —— 凑不满一卷的不算整卷）；</li>
 *   <li>余量 = {@code quantity − rollCount × rollLength}（恰好整卷倍数时为 {@code 0}，不是空值）；</li>
 *   <li>{@code quantity} 或 {@code rollLength} 缺失/非正 ⇒ {@link #notAllocated()}（不猜）；</li>
 *   <li>{@code quantity < rollLength}（不足一卷）⇒ {@code rollCount = 0} 且余量 = 全部数量
 *       —— 「0 整卷 + 全部散剪」是一个<b>真实结论</b>，与「未分配」({@code null}) 不是一回事。</li>
 * </ul>
 */
public final class ProductRollAllocation {

    private ProductRollAllocation() {
    }

    /**
     * 一次分配结果。
     *
     * @param rollCount      整卷数；{@code null} = <b>未分配</b>（卷长未知或数量非法，禁止推算）
     * @param rollLengthM    本次分配依据的卷长（{@code null} = 未分配）
     * @param cutMeters      散剪米数（整卷之外的部分）；未分配时为 {@code null}
     */
    public record Allocation(Integer rollCount, BigDecimal rollLengthM, BigDecimal cutMeters) {

        /** 是否真的算出了分配（{@code false} ⇒ 三个字段全为 {@code null}，调用方不得自行补数）。 */
        public boolean allocated() {
            return rollCount != null;
        }
    }

    private static final Allocation NOT_ALLOCATED = new Allocation(null, null, null);

    /** 未分配：卷长未知 / 数量非法。三字段全 {@code null}（「不知道」不许伪装成「0 卷」）。 */
    public static Allocation notAllocated() {
        return NOT_ALLOCATED;
    }

    /**
     * 按「优先整卷发货」分配。
     *
     * @param quantity    客户购买数量（米；{@code null} 或 {@code <= 0} ⇒ 未分配）
     * @param rollLengthM 货号的「1 卷 = 多少米」（{@code null} 或 {@code <= 0} ⇒ 未分配）
     */
    public static Allocation allocate(BigDecimal quantity, BigDecimal rollLengthM) {
        if (quantity == null || rollLengthM == null) {
            return NOT_ALLOCATED;
        }
        if (quantity.signum() <= 0 || rollLengthM.signum() <= 0) {
            return NOT_ALLOCATED;
        }
        // 向下取整：凑不满一卷的不算整卷（与「优先整卷发货」的语义一致 —— 优先发整卷，不是硬凑整卷）
        //
        // ⚠️ `intValueExact()` 会抛 `ArithmeticException: Overflow`：`quantity` 只受
        // `@DecimalMin("1")` 卡下限（**无上限**），而 `roll_length_m` 是 `NUMERIC(8,2)`
        // （可到 0.01）⇒ `1e9 / 0.01` 这类输入会让**建单 500**（而不是一个明确的 422）。
        // 独立对抗式复核实测抓到。修法按本类的红线走：**算不出来就不分配**
        // （「不知道」不许伪装成「0 整卷」，也不许变成 500）。
        int rolls;
        try {
            rolls = quantity.divide(rollLengthM, 0, RoundingMode.FLOOR).intValueExact();
        } catch (ArithmeticException overflow) {
            return NOT_ALLOCATED;
        }
        BigDecimal cut = quantity.subtract(rollLengthM.multiply(BigDecimal.valueOf(rolls)));
        // 恰好整卷倍数时 cut 是 0（不是 null）：它是「散剪 0 米」这个真实结论
        return new Allocation(rolls, rollLengthM, cut.stripTrailingZeros());
    }
}
