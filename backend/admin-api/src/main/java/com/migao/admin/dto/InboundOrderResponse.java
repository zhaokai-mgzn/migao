package com.migao.admin.dto;

import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.util.List;

/**
 * 入库单详情响应（V111，issue #5034）—— 单据头 + 明细行（含批次号）。
 */
@Data
public class InboundOrderResponse {

    private String id;

    /** 入库单号 RK-yyyyMMdd-NNNN */
    private String inboundNo;

    private String supplier;

    private String supplierDocNo;

    private String warehouse;

    private LocalDate inboundDate;

    /** draft / posted / cancelled */
    private String status;

    private BigDecimal totalAmount;

    private String remark;

    private OffsetDateTime postedAt;

    private String postedBy;

    private OffsetDateTime cancelledAt;

    private String cancelledBy;

    private String cancelledReason;

    private String createdBy;

    private OffsetDateTime createdAt;

    private List<Item> items;

    /** 明细行：**一行 = 一个批次** */
    @Data
    public static class Item {

        private Long id;

        private Long skuId;

        private String productId;

        /** 快照：入库时点的货号 */
        private String skuCode;

        /** 快照：颜色名 */
        private String colorName;

        /** 快照：门幅 */
        private String doorWidth;

        private BigDecimal quantity;

        private BigDecimal unitCost;

        private BigDecimal amount;

        /** 批次号（**过账后才有**；草稿为 null） */
        private String batchNo;

        /** 供应商缸号（可空） */
        private String dyeLot;

        private BigDecimal rollLengthM;

        private String remark;
    }
}
