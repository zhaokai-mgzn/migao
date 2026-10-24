package com.migao.admin.service;

import java.math.BigDecimal;

/**
 * 改价闸门的**判定**（issue #7375，P1-3 段 4）—— 纯函数：这个价要不要先审批。
 *
 * <h3>为什么「低于成本」必须审批</h3>
 * <p>价格本与售价是给客户让利的口子。让到**低于成本**就是亏本卖 —— 它可能是对的（清库存、抢客户），
 * 但必须**有人明确同意过**，而不是运营随手填一个数让公司悄悄亏钱。改前没有任何闸门：
 * 谁有录入权限谁就能把价改到 0.01 元。</p>
 *
 * <h3>成本未知时**不**阻断（照实登记）</h3>
 * <p>`avg_cost IS NULL` = 成本未知（存量批次没录进价）。此时**不阻断**改价：拿「未知」当「零成本」
 * 会把所有改价都变成「高于成本」，那闸门就是假的；反过来一律阻断，则存量商品全都改不了价。
 * 处置：放行，但判定结果显式标 `costUnknown = true`，让调用方在留痕里写清楚「这次没底价可依」。</p>
 */
public final class PriceFloorPolicy {

    /**
     * @param price 本次要落的价
     * @param cost  该 SKU 的成本（`null` = 未知）
     */
    public record Decision(boolean needsApproval, boolean costUnknown, BigDecimal shortfall) {
    }

    private PriceFloorPolicy() {
    }

    public static Decision evaluate(BigDecimal price, BigDecimal cost) {
        if (cost == null) {
            // 成本未知 ⇒ 不阻断（见类注释的取舍）
            return new Decision(false, true, null);
        }
        if (cost.signum() <= 0) {
            // 成本 <= 0 同样是「没有可信成本」（0 是占位，不是真零成本）
            return new Decision(false, true, null);
        }
        if (price == null) {
            return new Decision(false, true, null);
        }
        if (price.compareTo(cost) >= 0) {
            return new Decision(false, false, null);
        }
        return new Decision(true, false, cost.subtract(price));
    }
}
