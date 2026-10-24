package com.migao.admin.dto;

import lombok.Builder;
import lombok.Data;

import java.math.BigDecimal;
import java.util.List;

/**
 * 订单毛利报表（issue #7376，P1-4 段 1）。
 *
 * <p>🔴 三条口径必须能自证：</p>
 * <ol>
 *   <li><b>合计 = 明细之和</b>（{@code totals} vs {@code rows}）—— 老板不会逐行加，算错了没人发现；</li>
 *   <li><b>空数据 ≠ 0</b>：没有命中订单时 {@code totals} 全为 {@code null}、{@code hasData=false}，
 *       而不是一堆 0（0 会被读成「本月毛利是 0」）；</li>
 *   <li><b>成本未知单独计数</b>：某单缺进价/有未定价报工 ⇒ 它**不进毛利合计**，但 {@code unknownCostOrders > 0}
 *       要显式告诉读者「这个合计少算了 N 单」。</li>
 * </ol>
 */
@Data
@Builder
public class OrderMarginReportView {

    private String startDate;

    private String endDate;

    /** 是否有命中数据（false ⇒ 合计为 null，不是 0）。 */
    private boolean hasData;

    /** 逐单明细。 */
    private List<Row> rows;

    /** 合计（{@code hasData=false} 时全为 null）。 */
    private Totals totals;

    /** 成本未知、因此**未计入**毛利合计的订单数（> 0 ⇒ 合计是「可算的那部分」）。 */
    private int unknownCostOrders;

    @Data
    @Builder
    public static class Row {

        private String orderId;

        private String orderNo;

        private String customerName;

        private String status;

        private BigDecimal revenue;

        private BigDecimal refunded;

        private BigDecimal fabricCost;

        private BigDecimal laborCost;

        private BigDecimal grossMargin;

        private boolean costKnown;
    }

    @Data
    @Builder
    public static class Totals {

        private BigDecimal revenue;

        private BigDecimal refunded;

        private BigDecimal fabricCost;

        private BigDecimal laborCost;

        private BigDecimal grossMargin;
    }
}
