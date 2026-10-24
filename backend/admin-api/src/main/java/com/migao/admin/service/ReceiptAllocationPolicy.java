package com.migao.admin.service;

import java.math.BigDecimal;
import java.math.RoundingMode;

/**
 * 核销准入的**纯函数**（issue #7370，P0-2 段 3）。
 *
 * <h3>为什么单独一个类</h3>
 * <p>「这笔钱还能冲多少」「这张单还能收多少」是两个各自独立的上限，任一算错都会造成
 * **不可逆的账实不符**（同一张单被重复收钱 / 一笔钱被重复使用）。把它们埋进服务方法里，
 * 就只能靠「上线后看余额对不对」发现错，而余额错的时候屏幕上的数字**依然合理**。</p>
 *
 * <h3>两条上限（各自独立，取小）</h3>
 * <ol>
 *   <li><b>收款侧</b>：本笔流水剩余 = 流水金额 − 已核销合计。差额 = <b>未核销</b>（预收 / 待勾对）。
 *       先付后货是真实状态 ⇒ 剩余可以为正且必须能显示。</li>
 *   <li><b>订单侧</b>：本单剩余应收 = 货值 − 已退款 − 已核销合计。多收不冲抵别的单 ⇒ 余额不得为负。</li>
 * </ol>
 * <p>两处金额一律 2 位小数（钱只有两位小数的物理意义）。</p>
 */
public final class ReceiptAllocationPolicy {

    private ReceiptAllocationPolicy() {
    }

    /**
     * 判定结果。
     *
     * @param allocatable 本次最多可核销（= min(收款剩余, 订单剩余)，负数归 0）
     * @param allowed     申请金额是否合规（正数且不超过可核销上限）
     * @param excess      超出的部分（合规时为 0；供「还差多少」的可行动提示）
     */
    public record Decision(boolean allowed, BigDecimal allocatable, BigDecimal excess) {
    }

    /**
     * 判定一笔核销申请。
     *
     * @param transactionAmount 流水金额（收入，正数）
     * @param alreadyAllocated  该流水已核销合计（null ⇒ 0）
     * @param orderTotal        订单货值（正数）
     * @param orderRefunded     该单退款合计（null ⇒ 0，退款冲减应收）
     * @param orderAllocated    该单已核销合计（null ⇒ 0）
     * @param requested         本次申请的核销金额
     */
    public static Decision evaluate(BigDecimal transactionAmount,
                                    BigDecimal alreadyAllocated,
                                    BigDecimal orderTotal,
                                    BigDecimal orderRefunded,
                                    BigDecimal orderAllocated,
                                    BigDecimal requested) {
        BigDecimal receiptLeft = nz(transactionAmount).subtract(nz(alreadyAllocated));
        if (receiptLeft.signum() < 0) {
            receiptLeft = BigDecimal.ZERO;
        }
        BigDecimal orderLeft = nz(orderTotal).subtract(nz(orderRefunded)).subtract(nz(orderAllocated));
        if (orderLeft.signum() < 0) {
            orderLeft = BigDecimal.ZERO;
        }
        BigDecimal allocatable = receiptLeft.min(orderLeft).setScale(2, RoundingMode.HALF_UP);

        BigDecimal want = requested == null ? BigDecimal.ZERO : requested;
        if (want.signum() <= 0) {
            // 0 或负数没有「冲了一点点」的语义 ⇒ 直接拒（不是放行一条空行）
            return new Decision(false, allocatable, BigDecimal.ZERO.setScale(2));
        }
        BigDecimal over = want.subtract(allocatable);
        if (over.signum() > 0) {
            return new Decision(false, allocatable, over.setScale(2, RoundingMode.HALF_UP));
        }
        return new Decision(true, allocatable, BigDecimal.ZERO.setScale(2));
    }

    private static BigDecimal nz(BigDecimal value) {
        return value == null ? BigDecimal.ZERO : value;
    }
}
