package com.migao.admin.service;

import java.math.BigDecimal;

/**
 * 客户授信额度的**判定口径**（issue #7370，P0-2 段 1）。
 *
 * <p>抽成纯函数，是为了让「额度语义」可逐格断言、不依赖 PG 与整条下单链路；
 * 下单入口（{@link OrderService#createOrder}）只做「取数 + 调这里」。
 *
 * <p>口径（本 issue 裁定）：
 * <ul>
 *   <li><b>NULL = 未启用授信</b> ⇒ 一律放行（存量客户默认值，零回归）；</li>
 *   <li><b>0 = 启用但零额度</b> ⇒ 任何正数赊销都被拒（0 ≠ 不限）；</li>
 *   <li>恰好等于可用额度 ⇒ 放行（闭区间）；</li>
 *   <li>负额度 = 配置错误 ⇒ 抛 {@link IllegalArgumentException}（不许静默当 0 或不限）。</li>
 * </ul>
 */
public final class CreditPolicy {

    /**
     * 判定结果。
     *
     * @param allowed   是否放行
     * @param available 可用额度（= 额度 - 已欠）；额度未启用时为 {@code null}
     * @param excess    超额部分（放行时为 0，供「还差多少」的可行动提示使用）
     */
    public record Decision(boolean allowed, BigDecimal available, BigDecimal excess) {
    }

    private CreditPolicy() {
    }

    public static Decision evaluate(BigDecimal limit, BigDecimal outstanding, BigDecimal newAmount) {
        if (limit == null) {
            return new Decision(true, null, BigDecimal.ZERO);
        }
        if (limit.signum() < 0) {
            throw new IllegalArgumentException("授信额度不得为负：" + limit.toPlainString());
        }
        BigDecimal used = outstanding == null ? BigDecimal.ZERO : outstanding;
        BigDecimal amount = newAmount == null ? BigDecimal.ZERO : newAmount;
        BigDecimal available = limit.subtract(used);
        if (amount.compareTo(available) <= 0) {
            return new Decision(true, available, BigDecimal.ZERO);
        }
        return new Decision(false, available, amount.subtract(available));
    }
}
