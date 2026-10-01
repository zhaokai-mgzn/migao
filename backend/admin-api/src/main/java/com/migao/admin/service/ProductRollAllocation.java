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
 * <h2>显式 &gt; 派生 + 缺的那半<b>回落</b>（issue #5846，用户 2026-10-01 裁定）</h2>
 * 订单行可以<b>显式</b>给出「卷数 + 每卷实际米数」两个输入；<b>缺的那一半回落</b>，
 * 回落点<b>只有</b> {@link #resolve(Integer, BigDecimal, BigDecimal, BigDecimal)} 一处：
 * <ul>
 *   <li>{@code effectiveLength = 显式 rollLengthM ?? 商品 roll_length_m}（两边都没有 ⇒ {@code null}）；</li>
 *   <li>{@code rollCount = 显式 rollCount ?? floor(quantity / effectiveLength)}
 *       （{@code effectiveLength} 为 {@code null}/非正 ⇒ 保持 {@code null}，沿用「不分配」口径）。</li>
 * </ul>
 * 🔴 <b>不变式</b>：一次分配里<b>同一个字段只有一个权威来源</b>（显式 XOR 派生），
 * 不允许「同一单两个整卷数」。「成对给出」<b>不是</b>前提（用户 2026-10-01 裁定取消成对契约）：
 * 只给一个也能用，缺的那半走上面的回落。
 *
 * <h2>红线：卷长未知 ⇒ <b>不分配</b>，绝不猜</h2>
 * 行业卷长是<b>区间值</b>不是定值（「一卷 60 米<i>左右</i>」——
 * 见 {@code docs/curtain-selling-method-industry-research.md} §5）。
 * 货号未配 {@code roll_length_m}（NULL）或配了非正值、<b>且</b>客户端也没显式给卷长、
 * <b>且</b>没有显式卷数时，本类不会用「默认 60 米」之类的兜底常量算出一个看似合理的分配：
 * 那会把未配置的货号变成「系统以为一卷 60 米」，仓库照它拣货就发错货。
 *
 * <h2>边界语义（每条都有对应断言）</h2>
 * <ul>
 *   <li>整卷数 = {@code floor(quantity / rollLength)}（向下取整 —— 凑不满一卷的不算整卷）；</li>
 *   <li>余量 = {@code quantity − rollCount × rollLength}（恰好整卷倍数时为 {@code 0}，不是空值）；</li>
 *   <li>{@code quantity} 或 {@code rollLength} 缺失/非正 <b>且没有显式卷数</b> ⇒
 *       {@link #notAllocated()}（不猜）；</li>
 *   <li>{@code quantity < rollLength}（不足一卷）⇒ {@code rollCount = 0} 且余量 = 全部数量
 *       —— 「0 整卷 + 全部散剪」是一个<b>真实结论</b>，与「未分配」({@code null}) 不是一回事；</li>
 *   <li>🔻 <b>显式卷数 + 卷长两边都没有</b> ⇒ {@code rollCount = 显式值}、{@code rollLengthM = null}
 *       —— 这是「客户要 N 卷」的<b>真实意图</b>（既不是未分配，也不是「卷长 0」）；
 *       此时散剪米数算不出来 ⇒ {@code cutMeters = null}（不编）。</li>
 * </ul>
 */
public final class ProductRollAllocation {

    private ProductRollAllocation() {
    }

    /**
     * 一次分配结果。
     *
     * @param rollCount      整卷数；{@code null} = <b>未分配</b>（卷长未知且未显式给卷数，禁止推算）
     * @param rollLengthM    本次分配依据的卷长；{@code null} <b>不等于</b>「未分配」——
     *                       显式给了卷数而卷长两边都没有时，{@code rollCount} 有值而本字段为
     *                       {@code null}（issue #5846 的新合法态）
     * @param cutMeters      散剪米数（整卷之外的部分）；卷长未知 / 数量未知时 {@code null}（算不出来就不编）
     */
    public record Allocation(Integer rollCount, BigDecimal rollLengthM, BigDecimal cutMeters) {

        /** 是否真的算出了分配（{@code false} ⇒ 三个字段全为 {@code null}，调用方不得自行补数）。 */
        public boolean allocated() {
            return rollCount != null;
        }
    }

    /**
     * 「**显式优先 + 缺的那半回落**」的<b>唯一回落点</b>（issue #5846，用户 2026-10-01 裁定）。
     *
     * <p>裁定逐条（照此实现，别自行发挥）：</p>
     * <ol>
     *   <li>{@code effectiveLength = 显式 rollLengthM ?? 商品 roll_length_m}
     *       —— 商品也没配 ⇒ 保持 {@code null}（<b>不猜</b>）；</li>
     *   <li>{@code rollCount = 显式 rollCount ?? floor(quantity / effectiveLength)}
     *       —— {@code effectiveLength} 为 {@code null}/非正 ⇒ {@code rollCount} 保持 {@code null}
     *       （沿用既有「不分配」口径）；</li>
     *   <li><b>不变式</b>：同一字段只有一个权威来源（显式 XOR 派生）——
     *       本方法是<b>唯一</b>把「显式值」与「商品值」合到一处的地方
     *       （类级元守卫 {@code OrderRollAllocationAuthorityTest} 钉住它的调用点唯一）；</li>
     *   <li>{@code 0 卷} 仍是<b>真实结论</b>（与「未分配 = {@code null}」两回事）；</li>
     *   <li>🔻 <b>新合法态</b>：显式给了卷数、而卷长两边都没有 ⇒
     *       {@code rollCount = 显式值}、{@code rollLengthM = null}（「客户要 N 卷」是真实意图，
     *       不是未分配）—— 此时 {@code cutMeters = null}（算不出来就不编）。</li>
     * </ol>
     *
     * @param explicitRollCount    客户端显式卷数（{@code null} = 未给 ⇒ 走派生）
     * @param explicitRollLengthM  客户端显式「每卷实际米数」（{@code null} = 未给 ⇒ 回落商品卷长）
     * @param quantity             行米数（派生卷数与散剪余量都要它）
     * @param productRollLengthM   货号 {@code products.roll_length_m}（{@code null}/非正 = 未配置）
     */
    public static Allocation resolve(Integer explicitRollCount,
                                     BigDecimal explicitRollLengthM,
                                     BigDecimal quantity,
                                     BigDecimal productRollLengthM) {
        // ① 卷长回落：显式 > 商品；商品配了非正值视同「未配置」（不猜，见类注释红线）
        BigDecimal effectiveLength = explicitRollLengthM != null ? explicitRollLengthM : productRollLengthM;
        if (effectiveLength != null && effectiveLength.signum() <= 0) {
            effectiveLength = null;
        }
        // ② 卷数：显式 > 派生 —— 派生需要有效卷长（算不出来 ⇒ 不分配，绝不用默认常量）
        if (explicitRollCount != null) {
            return new Allocation(explicitRollCount, effectiveLength,
                    cutMeters(quantity, explicitRollCount, effectiveLength));
        }
        return allocate(quantity, effectiveLength);
    }

    /** 散剪余量 = {@code quantity − rollCount × 卷长}；卷长未知 / 数量未知 ⇒ {@code null}（不编）。 */
    private static BigDecimal cutMeters(BigDecimal quantity, int rollCount, BigDecimal rollLengthM) {
        if (quantity == null || rollLengthM == null) {
            return null;
        }
        return quantity.subtract(rollLengthM.multiply(BigDecimal.valueOf(rollCount))).stripTrailingZeros();
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
