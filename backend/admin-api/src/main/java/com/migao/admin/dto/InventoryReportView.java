package com.migao.admin.dto;

import lombok.Builder;
import lombok.Data;

import java.math.BigDecimal;
import java.util.List;

/**
 * 库存周转与滞销报表（issue #7376，P1-4 段 2）。
 *
 * <p>🔴 与毛利报表同口径的三条：合计 = 明细之和；空数据时合计为 {@code null}（不是 0）；
 * 缺日期/未知量的行**不猜测**，单列 {@code undeterminedRows} 计数。</p>
 */
@Data
@Builder
public class InventoryReportView {

    /** 滞销阈值（天）—— 报表自述口径，页面要显示「满 N 天未出库算滞销」。 */
    private int slowMovingDays;

    /** 是否有命中数据（false ⇒ 合计为 null，不是 0）。 */
    private boolean hasData;

    /** 逐批次明细（只含**有货**的批次）。 */
    private List<Row> rows;

    private Totals totals;

    /** 无法判定（缺入库/出库日期）的行数 —— 不猜，但要说出来。 */
    private int undeterminedRows;

    @Data
    @Builder
    public static class Row {

        private Long batchId;

        private String batchNo;

        private String skuCode;

        private String warehouse;

        private BigDecimal onHand;

        private String lastMovementDate;

        private long daysSinceMovement;

        private boolean slowMoving;

        private String reason;
    }

    @Data
    @Builder
    public static class Totals {

        /** 总库存量（米）。 */
        private BigDecimal onHand;

        /** 其中滞销部分的库存量（米）—— 「压了多少钱在滞销货上」的第一层读数。 */
        private BigDecimal slowMovingOnHand;

        /** 滞销批次数。 */
        private int slowMovingBatches;
    }
}
