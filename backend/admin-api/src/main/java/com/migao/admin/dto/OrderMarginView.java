package com.migao.admin.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.math.BigDecimal;

/**
 * 订单毛利读面（issue #7371，P0-3 段 1）。
 *
 * <p>🔴 `costKnown = false` 时：`fabricCost` / `grossMargin` / `marginRate` **都是 null**，
 * 前端显示「成本未知」。「未知当 0」会让毛利率虚高（把成本当成没花钱）—— 这是本段最不能犯的错。</p>
 *
 * <p>本段只算 **面料毛利**（`scope` 自述口径）：加工费与运费**尚未计入**。</p>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class OrderMarginView {

    private String orderId;

    private String orderNo;

    private String status;

    /** 成本口径自述（不许让读者以为是完全成本毛利） */
    private String scope;

    /** 收入 = 订单货值 */
    private BigDecimal revenue;

    /** 已退款（成功退款流水合计） */
    private BigDecimal refunded;

    /** 面料成本 = Σ（扣料米数 × 批次进价快照）；成本未知时为 null */
    private BigDecimal fabricCost;

    /** 毛利 = 收入 − 退款 − 面料成本；成本未知时为 null */
    private BigDecimal grossMargin;

    /** 毛利率（0~1，四位小数）；净收入 ≤ 0 或成本未知时为 null */
    private BigDecimal marginRate;

    /** 面料成本是否已知 */
    private boolean costKnown;

    /** 扣料行数（该单有多少行面料消耗） */
    private int fabricLines;

    /** 缺进价的扣料行数（> 0 ⇒ 成本未知；提示「这几批要补进价」） */
    private int unknownFabricLines;
}
