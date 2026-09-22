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

    private BigDecimal quantity;

    private BigDecimal unitCost;

    private BigDecimal amount;

    /** 供应商缸号（可空） */
    private String dyeLot;

    /**
     * 旧系统批次号（可空；V118 / issue #5153）。
     *
     * <p>与 {@link #batchNo}（服务端生成）**两列两义** —— 期初建账登记进来的批次靠它
     * 与旧系统对得上（「旧系统里那个号在 MIGAO 里是哪一批、还剩多少」）。</p>
     */
    private String legacyBatchNo;

    private BigDecimal rollLengthM;

    private String supplier;

    private String warehouse;

    /** 收货日期（= 入库单的入库日期） */
    private LocalDate receivedDate;

    private String remark;

    private OffsetDateTime createdAt;
}
