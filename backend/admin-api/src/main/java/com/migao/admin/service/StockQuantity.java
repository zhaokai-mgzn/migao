package com.migao.admin.service;

import com.migao.admin.exception.BusinessException;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.Collection;

/**
 * 库存米数精度口径（issue #5063）—— 库存链路数量列的**单点精度策略**。
 *
 * <h2>为什么需要这个类</h2>
 * 用户裁定逐字：「<b>库存米数是小数，1 位小数，必须改造</b>」＋「<b>不能损失客户</b>」。
 * 库存/销量列由 {@code INTEGER} 升级为 {@code NUMERIC(12,1)}（V115）后，「多少位小数算合法」
 * 变成一个**跨服务共同判据**（入库 / 库存调整 / 建品改品 / 订单扣减回补）。判据散落各处
 * ⇒ 迟早出现两套口径（一处拒 2.75、另一处悄悄存成 2.8 还不报错）
 * ⇒ 集中到本类，库存链路里**唯一**允许做数量取整/进位的地方。
 *
 * <h2>三条口径（按调用场景分，不是三种可任选的做法）</h2>
 * <ol>
 *   <li>{@link #requireOneDecimal} —— <b>库存类输入</b>的准入判据（入库数量 / 库存调整量 /
 *       建品改品的 {@code stock}）：允许 0.1 米粒度以内（含 0 位小数），<b>超过 1 位小数
 *       ⇒ 显式拒绝</b>（fail-closed，文案可行动）。沿用 V111 对「非整数入库」的
 *       「显式拒绝，不静默取整」精神 —— 静默取整 = 账面与实物不符且<b>无人发现</b>。</li>
 *   <li>{@link #toStockScaleByCeiling} —— <b>订单侧</b>（顾客已成交的
 *       {@code order_items.quantity}，列精度 {@code DECIMAL(10,2)}）落库存前的显式定向舍入。
 *       口径 = 真值源 {@code docs/curtain-fabric-quote-rules.md} §8「用料米数一律<b>向上进位到
 *       0.1</b>」（{@code ceil(x*10)/10}）：裁床实际用料就是这个粒度，库存按同粒度同方向变化
 *       才是账实一致。<b>这里不拒绝</b> —— 顾客已经下单，在下单/扣减点拒绝 = 损失客户；
 *       扣减与回补<b>调用同一个函数</b> ⇒ 同一笔单的净变化恒为 0。</li>
 *   <li>{@link #tenths} / {@link #fromTenths} —— 把 1 位小数换写成「0.1 米的整数计数」，
 *       给「多个 SKU 之间分摊一个调整量」用：整数运算<b>精确无余数丢失</b>
 *       （{@code BigDecimal.divide} 在除不尽时会抛或被迫舍入，两者都不可接受）。</li>
 * </ol>
 *
 * <h2>边界（如实登记，不粉饰）</h2>
 * 列精度 {@code NUMERIC(12,1)} 本身<b>带舍入语义</b>：PG 对超 scale 的写入按四舍五入落库
 * （{@code 2.75} → {@code 2.8}，不报错）。数据库层拦不住「调用方传了 2 位小数」
 * ⇒ fail-closed 只能在<b>应用层</b>（本类）完成。
 */
public final class StockQuantity {

    /** 库存/销量列精度：{@code NUMERIC(12,1)} ⇒ 1 位小数 = 0.1 米粒度（V115，issue #5063）。 */
    public static final int SCALE = 1;

    private StockQuantity() {
    }

    /**
     * 去掉无意义的尾零，但**不引入科学计数法**（{@code 10.00} → {@code 10}，而不是 {@code 1E+1}）。
     *
     * <p>为什么重要：{@link BigDecimal#equals} 比 scale，{@code 2.00} 与 {@code 2} 不相等
     * ⇒ 尾零会沿着「订单数量 → 聚合 → mapper 入参 → 台账」一路传播，最后让
     * 「整数场景逐值不变」在 JSON 字面量与既有断言上都不成立。</p>
     */
    static BigDecimal stripTrailingZerosPlain(BigDecimal value) {
        BigDecimal stripped = value.stripTrailingZeros();
        return stripped.scale() < 0 ? stripped.setScale(0) : stripped;
    }

    /** 空安全取值：{@code null} ⇒ 0（把既有 {@code x != null ? x : 0} 的散落写法集中到一处）。 */
    public static BigDecimal orZero(BigDecimal raw) {
        return raw != null ? raw : BigDecimal.ZERO;
    }

    /** 空安全求和（{@code null} 项按 0 计）。 */
    public static BigDecimal sum(Collection<BigDecimal> values) {
        BigDecimal total = BigDecimal.ZERO;
        if (values == null) {
            return total;
        }
        for (BigDecimal v : values) {
            total = total.add(orZero(v));
        }
        return total;
    }

    /**
     * 库存类<b>输入</b>的准入判据（fail-closed）：最多 1 位小数。
     *
     * <p>超过 1 位小数 ⇒ 抛 {@link BusinessException}（可行动文案：说清「库存按 0.1 米粒度记」
     * 且告诉调用方改成 1 位小数后重试）。<b>不四舍五入、不截断</b> —— 静默取整会让账面与实物
     * 不符且无人发现，正是本单要治的形态。</p>
     *
     * <p>写法说明：用 {@link BigDecimal#stripTrailingZeros()} 判<b>有效</b>小数位，
     * 故 {@code 2.70}（2 位书写、1 位有效）合法、{@code 2.750} 按 {@code 2.75} 判（2 位）拒绝。
     * <b>不得</b>改成 {@code double} 比较 —— 二进制浮点会骗人（{@code 2.7} 的实际存值不是 2.7）。</p>
     *
     * <p>合法值<b>原样返回</b>（不做 {@code setScale} 归一）：整数场景必须<b>逐值不变</b>
     * —— 把 {@code 10} 归一成 {@code 10.0} 会改掉 API 返回的 JSON 字面量（前端从「10」变「10.0」）
     * 与 Mockito 参数匹配（{@code equals} 比 scale），那是「不能损失客户」不许有的白改。</p>
     *
     * @param raw   原始值（{@code null} 视为 0）
     * @param label 出错文案里的字段名（如「商品明细第 2 项的数量」）
     * @return 合法值原样返回（{@code 60} → {@code 60}、{@code 60.5} → {@code 60.5}）
     */
    public static BigDecimal requireOneDecimal(BigDecimal raw, String label) {
        BigDecimal value = orZero(raw);
        BigDecimal stripped = stripTrailingZerosPlain(value);
        int effectiveScale = Math.max(stripped.scale(), 0);
        if (effectiveScale > SCALE) {
            throw BusinessException.validationError(String.format(
                    "%s 最多支持 1 位小数（库存按 0.1 米粒度记账），当前值 %s 有 %d 位小数"
                            + " —— 请改为 1 位小数后重试（服务端不做静默取整）",
                    label, value.toPlainString(), effectiveScale));
        }
        return stripped;
    }

    /**
     * {@link #requireOneDecimal} 的<b>可空</b>版本：{@code null} = 「本字段未传」
     * ⇒ 原样返回 {@code null}（**不得**把「未传」变成 0 —— 改品请求里 {@code stock == null}
     * 的语义是「这一项不改」，归一成 0 会把库存清零）。
     */
    public static BigDecimal requireOneDecimalOrNull(BigDecimal raw, String label) {
        return raw == null ? null : requireOneDecimal(raw, label);
    }

    /**
     * 领料量落到库存列前的**显式定向舍入**（唯一入口）：按 {@code docs/curtain-fabric-quote-rules.md}
     * §8「用料米数一律向上进位到 0.1」进位。
     *
     * <h2>它是「两个口径」共用的<b>同一个</b>归一入口（issue #5158）</h2>
     * 领料量有两个口径，**归一都在这一处**（不许两处各写一套进位）：
     * <ol>
     *   <li><b>公式口径</b>：{@code order_items.quantity}（定高买宽 {@code W×N}、定宽买高 {@code P×(H+卷边)}）
     *       —— 与销售账扣减同源，落在 {@code stock_batch_consumptions.formula_meters}；</li>
     *   <li><b>排料口径</b>：{@code CuttingPlanCalculator} 的 {@code issuedMeters}（并排后的应领米数，
     *       {@code BigDecimal}、**不取整**）按占比分摊到行后，落在 {@code planned_meters}。</li>
     * </ol>
     *
     * <p>🔴 <b>为什么是「同族可复用」而不是「语义不同故不复用」</b>：两个口径的入参虽然来源不同
     * （已成交数量 / 装箱结果），但**落库存前的取向要求是同一个** —— 都必须是
     * 「**不小于**该口径算出来的用料量」：少领 = 裁床切不出货（比不省料严重得多），
     * 而多领最多是批次余量少一点（下一次派工看得见）。进位方向、粒度（0.1 米）、真值源（§8）
     * 三者逐字相同 ⇒ 复用本方法；另写一套「排料专用进位」只会在两处各自漂移
     * （本仓反复复发的形态：同一事实的第二份口径）。</p>
     *
     * <p><b>为什么不在这里拒绝</b>：入参是顾客已成交的 {@code order_items.quantity}
     * （{@code DECIMAL(10,2)}，`per_meter` 是米数、`per_area` 是 ㎡）——在下单点拒绝 =
     * 损失客户（用户裁定「不能损失客户」，且 {@code per_area} 的 ㎡ 数量天然可能 2 位小数）。
     * 但**也绝不静默截断**：这是与裁床实际用料同源同向的进位，且扣减与回补走同一函数
     * ⇒ 同一笔单的净变化恒为 0（不会出现「扣 2.8、回补 2.7」的漂移）。</p>
     */
    public static BigDecimal toStockScaleByCeiling(BigDecimal raw) {
        BigDecimal value = orZero(raw);
        // 已在粒度内（0 位或 1 位小数）⇒ 返回**去尾零**的原值，不做无谓的 setScale：
        // `2.00` 归一成 `2.0`/`2` 的差别会扰动「整数场景逐值不变」
        // （JSON 字面量与 Mockito 的 equals 都比 scale；`2.00` 一路传下去会让既有断言全红）
        BigDecimal stripped = stripTrailingZerosPlain(value);
        return stripped.scale() <= SCALE ? stripped : value.setScale(SCALE, RoundingMode.CEILING);
    }

    /**
     * 1 位小数 → 「0.1 米刻度」的整数计数（{@code 2.7} → {@code 27}）。
     * 用于多 SKU 分摊：整数除法精确、余数可显式分配，{@code BigDecimal.divide} 做不到。
     */
    public static long tenths(BigDecimal value) {
        return orZero(value).movePointRight(SCALE).setScale(0, RoundingMode.HALF_UP).longValueExact();
    }

    /**
     * 「0.1 米刻度」的整数计数 → 数值（{@code 27} → {@code 2.7}、{@code 20} → {@code 2}）。
     * {@link #tenths} 的逆。
     *
     * <p><b>整刻度必须回落成整数</b>：{@code 20} 若写成 {@code 2.0}，分配结果就带上了 scale=1，
     * 沿「SKU 库存 → 派生列 → 台账 before/after/delta」一路传播 ⇒ **整数场景的落库值与 JSON
     * 字面量都变了**（用户裁定「不能损失客户」不许有的白改）。</p>
     */
    public static BigDecimal fromTenths(long tenths) {
        return stripTrailingZerosPlain(BigDecimal.valueOf(tenths, SCALE));
    }
}
