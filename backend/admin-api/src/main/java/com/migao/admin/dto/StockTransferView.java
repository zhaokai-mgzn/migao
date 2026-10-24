package com.migao.admin.dto;

import lombok.Builder;
import lombok.Data;

import java.math.BigDecimal;
import java.util.List;

/** 调拨读面（issue #7373 段 1）。 */
@Data
@Builder
public class StockTransferView {

    private String id;

    private String transferNo;

    private Long fromWarehouseId;

    private String fromWarehouseCode;

    private Long toWarehouseId;

    private String toWarehouseCode;

    private String status;

    private List<Line> items;

    @Data
    @Builder
    public static class Line {

        private Long batchId;

        private String batchNo;

        private String skuCode;

        private BigDecimal qty;

        private BigDecimal unitCost;
    }
}
