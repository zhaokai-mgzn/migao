package com.migao.admin.service;

import java.math.BigDecimal;
import java.math.RoundingMode;

/**
 * 订单毛利（issue #7371，P0-3 段 1）—— **纯函数**：收入 − 退款 − 面料成本。
 *
 * <h3>核心口径：成本未知 ≠ 成本为 0</h3>
 * <p>入库时没录进价（`stock_batches.unit_cost IS NULL`）的批次，耗用它做出来的单**算不出**面料成本。
 * 这时毛利必须显示「成本未知」，**绝不填 0** —— 填 0 会让屏幕上出现一个漂亮的毛利率，
 * 而它是**虚高**的（把成本当成没花钱）。这是本段最重要的一条判据，红证方向：把未知按 0 处理 ⇒
 * `unknownCostIsNeverZero` 当场红。</p>
 *
 * <h3>本段覆盖哪些成本</h3>
 * <ul>
 *   <li>✅ <b>面料</b>：Σ（该单扣料行 `planned_meters` × 该批次**当时**的 `unit_cost` 快照）；</li>
 *   <li>✅ <b>退货</b>：成功退款流水合计（收入侧与成本侧同批冲减：收入减、成本不动）；</li>
 *   <li>🚫 <b>加工费 / 运费</b>：本段**不计入**（口径未裁定，见 issue 依赖）⇒ 毛利是「面料毛利」，
 *       DTO 里明确标注 `scope`，不许让读者以为是完全成本毛利。</li>
 * </ul>
 */
public final class OrderMargin {

    /** 成本口径：上屏要能自述「这个毛利算到了哪一步」（不许让用户以为是完全成本）。 */
    public static final String SCOPE_FABRIC_ONLY = "revenue_minus_refund_minus_fabric";

    private OrderMargin() {
    }

    /**
     * 计算结果。
     *
     * @param fabricCost   面料成本（未知时为 {@code null}）
     * @param grossMargin  毛利（成本未知或收入未知时为 {@code null}）
     * @param marginRate   毛利率（0~1；成本未知时为 {@code null}）
     * @param costKnown    面料成本是否已知（有任一扣料行缺进价 ⇒ false）
     */
    public record Result(BigDecimal fabricCost, BigDecimal grossMargin,
                         BigDecimal marginRate, boolean costKnown) {
    }

    /**
     * @param revenue       收入（订单货值 `total_amount`）
     * @param refunded      已退款合计（成功退款流水；null ⇒ 0）
     * @param fabricCost    Σ（扣料米数 × 批次进价快照）；null ⇒ 有行缺进价 ⇒ 成本未知
     * @param unknownLines  缺进价的扣料行数（&gt; 0 ⇒ 成本未知；仅用于提示「哪几行要补」）
     */
    public static Result compute(BigDecimal revenue,
                                BigDecimal refunded,
                                BigDecimal fabricCost,
                                int unknownLines) {
        boolean costKnown = fabricCost != null && unknownLines == 0;
        if (!costKnown) {
            return new Result(null, null, null, false);
        }
        BigDecimal net = nz(revenue).subtract(nz(refunded)).subtract(fabricCost);
        BigDecimal netRevenue = nz(revenue).subtract(nz(refunded));
        // 毛利率分母 = 净收入（收入 − 退款）；净收入 ≤ 0 时无意义 ⇒ null（不是 0、也不是负数百分比）
        BigDecimal rate = netRevenue.signum() > 0
                ? net.divide(netRevenue, 4, RoundingMode.HALF_UP)
                : null;
        return new Result(scale(fabricCost), scale(net), rate, true);
    }

    private static BigDecimal nz(BigDecimal value) {
        return value == null ? BigDecimal.ZERO : value;
    }

    private static BigDecimal scale(BigDecimal value) {
        return value.setScale(2, RoundingMode.HALF_UP);
    }
}
