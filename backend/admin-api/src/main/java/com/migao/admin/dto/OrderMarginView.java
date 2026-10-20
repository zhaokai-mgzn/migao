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
 * <p>段 2 起 `scope` = **面料 + 加工**（`revenue_minus_refund_minus_fabric_minus_labor`）；
 * **运费系统未采集** ⇒ `freightCaptured = false`（数据缺口，不是「运费为 0」）。</p>
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

    /** 加工成本 = 该单计件金额（与计件工资/期间报表**同一份聚合**）；未定价报工存在时为 null */
    private BigDecimal laborCost;

    /** 未定价报工行数（> 0 ⇒ 加工成本未知：未定价不进金额，但必须能被数出来） */
    private int unpricedLaborLines;

    /** 运费是否已采集（当前恒 false：系统没有运费字段 —— 是数据缺口，不是 0 运费） */
    private boolean freightCaptured;

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
