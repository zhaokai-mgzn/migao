package com.migao.admin.service;

import com.migao.admin.exception.BusinessException;

import java.math.BigDecimal;

/**
 * 金额精度口径（issue #6221）—— 金额链路**单一**的小数位准入点（fail-closed）。
 *
 * <h2>为什么需要这个类</h2>
 * 金额列在库内是 {@code NUMERIC(·,2)}（{@code orders.refund_amount} / {@code finance_transactions.amount}
 * 均 {@code NUMERIC(12,2)}；{@code orders.actual_amount} / {@code after_sales_tickets.refund_amount}
 * 为 {@code NUMERIC(10,2)}），而 PG 对**超出 scale 的写入按四舍五入落库、不报错**。缺了应用层准入
 * ⇒ 调用方传 {@code 0.001} 时接口返 200、库内却变成 {@code 0.00}：**退款「成功」但一分未落，
 * 且没有任何报错** —— 订单 {@code refund_amount} 与资金流水 {@code amount} 两处**同时静默归零**，
 * {@code refund_at} 却已写入（看起来像「退了一笔 0 元」）。
 *
 * <h2>既有范式：显式拒绝，不静默取整</h2>
 * 本仓对「精度不足」的一贯口径是 fail-closed，三处先例逐字一致：
 * <ul>
 *   <li>{@link StockQuantity#requireOneDecimal}（库存数量：超 1 位小数 ⇒ 拒绝）；</li>
 *   <li>{@code InboundOrderService#requireItemNumbers} 注释逐字：「超 1 位小数**显式拒绝**、不静默取整」；</li>
 *   <li>{@code ProductionOperationPositionCommandService} / {@code ProductionRoutingCommandService}
 *       的单价解析：{@code setScale(2, RoundingMode.UNNECESSARY)} —— 填 {@code 6.005} 时**抛异常**
 *       而不是静默变成 {@code 6.01}。</li>
 * </ul>
 * 金额侧此前**没有**这条准入（本类补齐）。金额比数量更不允许静默：它直接决定「落了多少钱」。
 *
 * <h2>舍入方向登记（**不是**本类的语义，也**不**作缺陷判据）</h2>
 * PG 的 {@code numeric(·,2)} 落库是**半进位**（half-up，远离 0）：修前实测
 * {@code 0.004 ⇒ 0}、{@code 0.005 ⇒ 0.01}、{@code 0.009 ⇒ 0.01}（issue #6221 逐字读数）。
 * 本类**不改**这个方向、也**不**依赖它 —— 修后这些子分级值在**应用层**就被拒（4xx），根本到不了库。
 * 登记它是为了让「为什么必须拒」可复核：静默取整的结果**可上可下**（0.004 归零、0.005 进位），
 * 调用方无法预期，而涉钱面的「无法预期」= 账实不符且无人发现。
 *
 * <h2>边界（如实登记）</h2>
 * 库层拦不住超精度写入（PG 只舍入、不报错）⇒ fail-closed 只能在**应用层**完成（本类）。
 * 本类只做**准入**（拒绝），**不做** {@code setScale} 归一：金额的书写精度会一路进 SQL 字面量
 * 与资金流水行，归一它是与本次修复无关的白改（同 {@link StockQuantity}「合法值原样返回」的精神，
 * 金额侧更严：连去尾零都不做，{@code 100.00} 原样返回 {@code 100.00}）。
 */
public final class MoneyScale {

    /** 金额列精度：{@code NUMERIC(·,2)} ⇒ 2 位小数 = 1 分粒度（issue #6221）。 */
    public static final int SCALE = 2;

    private MoneyScale() {
    }

    /**
     * 金额**准入**（fail-closed）：最多 2 位小数；超位 ⇒ 抛
     * {@link BusinessException}（{@code 422 VALIDATION_ERROR}，可行动文案）。
     *
     * <p><b>只在超位时拒绝，不四舍五入、不截断、不做 setScale 归一</b>：静默取整正是本单要治的形态
     * （{@code 0.001} 被舍成 {@code 0.00} ⇒ 退款「成功」而账上一分未动）。</p>
     *
     * <p><b>判「有效」小数位</b>（{@code stripTrailingZeros}）：{@code 2.70}（书写 2 位、有效 1 位）合法，
     * {@code 0.010}（有效 2 位）合法，{@code 0.001}（有效 3 位）拒绝。
     * <b>不得</b>改成 {@code double} 比较 —— 二进制浮点会骗人（{@code 0.1} 的实际存值不是 0.1）。</p>
     *
     * <p>🔴 <b>{@code null} = 「本字段未传」⇒ 原样返回 {@code null}，不得变成 0</b>：退款接口里
     * {@code refund_amount = null} 的语义是「**全额退**」，归一成 {@code 0} 会把全额退款静默改成
     * 退 0 元（比本单的缺陷更糟）。</p>
     *
     * @param raw   原始值（{@code null} = 未传）
     * @param label 出错文案里的字段名（如「退款金额」）
     * @return 合法值**原样返回**（{@code 0.01} → {@code 0.01}、{@code 100.00} → {@code 100.00}）
     */
    public static BigDecimal requireTwoDecimalsOrNull(BigDecimal raw, String label) {
        String problem = precisionProblemOrNull(raw, label);
        if (problem != null) {
            throw BusinessException.validationError(problem);
        }
        return raw;
    }

    /**
     * 与 {@link #requireTwoDecimalsOrNull} **同一判定**，但把「哪里不合法」作为**可行动文案**返回
     * （合法 / {@code null} ⇒ 返回 {@code null}）。
     *
     * <p>存在理由（issue #6228）：本仓有一类入口用**收集式校验**（逐条 {@code ApiResponse.ErrorDetail}
     * 汇总后一次性 422，如 {@code ProcessingFeeCombinationCommandService#requiredPrice}）——
     * 它们要的是「文案」而不是「立刻抛」。没有本方法，这类入口只能**再写一份**小数位判定
     * （= 第二处口径，正是本单要消灭的形态）；有了它，判定仍只有一处，抛与收集只是两种消费方式。</p>
     */
    public static String precisionProblemOrNull(BigDecimal raw, String label) {
        if (raw == null) {
            return null;
        }
        int effectiveScale = effectiveScale(raw);
        if (effectiveScale > SCALE) {
            return String.format(
                    "%s 最多支持 2 位小数（金额按「分」记账，列精度 NUMERIC(·,2)），当前值 %s 有 %d 位小数"
                            + " —— 请改为最多 2 位小数后重试（服务端不做静默取整/四舍五入）",
                    label, raw.toPlainString(), effectiveScale);
        }
        return null;
    }

    /** 有效小数位数（去尾零后；{@code 2.70} → 1、{@code 0.001} → 3、{@code 100.00} → 0）。 */
    static int effectiveScale(BigDecimal value) {
        return Math.max(value.stripTrailingZeros().scale(), 0);
    }
}
