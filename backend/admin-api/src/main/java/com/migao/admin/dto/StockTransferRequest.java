package com.migao.admin.dto;

import lombok.Data;

import java.math.BigDecimal;
import java.util.List;

/** 调拨请求（issue #7373 段 1）：调出仓 → 调入仓 + 逐批次明细。 */
@Data
public class StockTransferRequest {

    private Long fromWarehouseId;

    private Long toWarehouseId;

    private String note;

    private List<Line> items;

    /** 一行 = 一缸布（`batchId`），不是「某 SKU 几米」—— 缸号是色差追溯的唯一依据。 */
    @Data
    public static class Line {

        private Long batchId;

        /** 本次调拨数量（米，1 位小数）。 */
        private BigDecimal qty;
    }
}
