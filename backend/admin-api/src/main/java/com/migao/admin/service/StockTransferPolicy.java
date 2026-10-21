package com.migao.admin.service;

import java.math.BigDecimal;

/**
 * 调拨的**守恒判据**（issue #7373，P1-1 段 1）—— 纯函数，不碰库。
 *
 * <h3>为什么守恒要单独判</h3>
 * <p>调拨是「同一缸布换个仓」：**总量必须一字不变**。写错方向（改成 `from - qty / to - qty`）、
 * 或把「调拨」写成「出库 + 新入库」都会让账面总数变化 —— 而那不会报错，只会让库存慢慢对不上。
 * 判据：`调拨前总量 == 调拨后总量`，且每个批次行**只改归属仓、不改数量**。</p>
 *
 * <h3>可调量</h3>
 * <p>可调 = 该批次**调出仓现有量**；跨仓调拨不能超过它（段 1 不做负库存，超出即拒）。</p>
 */
public final class StockTransferPolicy {

    private StockTransferPolicy() {
    }

    /**
     * 本次调拨是否合法。
     *
     * @param batchQty   该批次在**调出仓**的现有数量
     * @param moveQty    本次调拨数量
     * @param sameWarehouse 调出仓 == 调入仓（无意义且会掩盖写错仓）
     */
    public static boolean canMove(BigDecimal batchQty, BigDecimal moveQty, boolean sameWarehouse) {
        if (sameWarehouse) {
            return false;
        }
        if (moveQty == null || moveQty.signum() <= 0) {
            return false;
        }
        return batchQty != null && batchQty.compareTo(moveQty) >= 0;
    }

    /**
     * 守恒校验：调拨前后**总量**必须相等（差一分都算错）。
     *
     * @param totalBefore 调拨前该租户库存总量（本次涉及批次）
     * @param totalAfter  调拨后总量
     */
    public static boolean conserved(BigDecimal totalBefore, BigDecimal totalAfter) {
        if (totalBefore == null || totalAfter == null) {
            return false;
        }
        return totalBefore.compareTo(totalAfter) == 0;
    }

    /**
     * 调拨后**调出仓**该批次的剩余量（段 1 是即时调拨 ⇒ 剩余 = 现有 − 调拨）。
     */
    public static BigDecimal remainingInFromWarehouse(BigDecimal batchQty, BigDecimal moveQty) {
        if (batchQty == null) {
            return null;
        }
        BigDecimal move = moveQty == null ? BigDecimal.ZERO : moveQty;
        return batchQty.subtract(move);
    }
}
