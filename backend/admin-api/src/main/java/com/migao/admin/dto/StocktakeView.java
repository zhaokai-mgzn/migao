package com.migao.admin.dto;

import lombok.Builder;
import lombok.Data;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.List;

/** 盘点读面（issue #7373 段 2）。 */
@Data
@Builder
public class StocktakeView {

    private String id;

    private String stocktakeNo;

    private Long warehouseId;

    private String warehouseCode;

    private String status;

    private String note;

    private OffsetDateTime completedAt;

    private List<Line> items;

    @Data
    @Builder
    public static class Line {

        private Long batchId;

        private String batchNo;

        private String skuCode;

        /** 盘点当刻的账面量（快照）。 */
        private BigDecimal bookQty;

        /** 实盘量；`null` = 还没数。 */
        private BigDecimal countedQty;

        /** 差异 = 实盘 − 账面；`null` = 还没数。 */
        private BigDecimal diffQty;
    }
}
