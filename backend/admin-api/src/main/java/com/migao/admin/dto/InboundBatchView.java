package com.migao.admin.dto;

import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.OffsetDateTime;

/**
 * 批次视图（V111，issue #5034）—— 只读：一行 = 一个入库批次。
 *
 * <p>给「这批布是什么时候、从谁、按什么价进的」与「同缸号有哪些批次」提供读面；
 * 缸号（{@link #dyeLot}）对应 AHFA「卷标须带 Lot number」的行业要求
 * （docs/curtain-selling-method-industry-research.md §1/S10）。</p>
 */
@Data
public class InboundBatchView {

    private Long id;

    /** 批次号 PC-yyyyMMdd-NNNN */
    private String batchNo;

    private String productId;

    private Long skuId;

    private String skuCode;

    /** 来源入库单号 */
    private String inboundNo;

    private String inboundOrderId;

    private Integer quantity;

    private BigDecimal unitCost;

    private BigDecimal amount;

    /** 供应商缸号（可空） */
    private String dyeLot;

    private BigDecimal rollLengthM;

    private String supplier;

    private String warehouse;

    /** 收货日期（= 入库单的入库日期） */
    private LocalDate receivedDate;

    private String remark;

    private OffsetDateTime createdAt;
}
