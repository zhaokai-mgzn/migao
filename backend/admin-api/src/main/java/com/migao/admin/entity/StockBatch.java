package com.migao.admin.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.OffsetDateTime;

/**
 * 批次台账实体（issue #5034）
 * 对应表：stock_batches（V111）—— 一行 = 一个入库批次（= 一条入库单明细行）。
 *
 * <p>缸号（{@link #dyeLot}）随批次可见 —— 对应 AHFA「卷标须带 Lot number」的行业要求
 * （docs/curtain-selling-method-industry-research.md §1/S10）。</p>
 *
 * <p>批次行<b>不可改</b>：冲销走新单据，不原地改历史（同 {@link StockLedger} 的追加写语义）。</p>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName("stock_batches")
public class StockBatch {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    /** 批次号 PC-yyyyMMdd-NNNN（租户内唯一） */
    private String batchNo;

    private String productId;

    private Long skuId;

    private String skuCode;

    private String inboundOrderId;

    private Long inboundItemId;

    /** 来源入库单号（冗余，便于只读追溯不 join） */
    private String inboundNo;

    private BigDecimal quantity;

    private BigDecimal unitCost;

    private BigDecimal amount;

    /** 供应商缸号（外部事实，可空） */
    private String dyeLot;

    /**
     * 旧系统批次号（外部事实，可空；V118 / issue #5153）。
     *
     * <p><b>与 {@link #batchNo} 两列两义</b>：{@code batchNo} 是**服务端生成**的系统号
     * （{@code PC-yyyyMMdd-NNNN}），本列是**旧系统**的批次号 —— V111 明令不得互相冒充
     * （与 {@link #dyeLot} 的缸号亦不同义）。期初建账时由明细行透传而来，采购入库恒为 NULL。</p>
     */
    private String legacyBatchNo;

    private BigDecimal rollLengthM;

    private String supplier;

    private String warehouse;

    /** 收货日期（= 入库单 inboundDate，**不是** created_at） */
    private LocalDate receivedDate;

    private String remark;

    private OffsetDateTime createdAt;

    @TableLogic
    private Integer deleted;
}
