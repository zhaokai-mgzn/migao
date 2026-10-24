package com.migao.admin.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.math.BigDecimal;
import java.time.OffsetDateTime;

/**
 * 调拨明细（V182，issue #7373 段 1）：一行 = **一缸布**（`batchId`），不是「某 SKU 几米」。
 *
 * <p>按批次调拨的理由：缸号是色差追溯的唯一依据（V118/#5153），按 SKU 调拨会让缸号在仓间丢失；
 * 成本同理 —— `unitCost` 是**当时**批次进价快照，跟着行一起走，不重算、不猜 0。</p>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName("stock_transfer_items")
public class StockTransferItem {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    private String transferId;

    private Long batchId;

    private String batchNo;

    private Long skuId;

    private String skuCode;

    /** 本次调拨数量（米，1 位小数）。 */
    private BigDecimal qty;

    private BigDecimal unitCost;

    private OffsetDateTime createdAt;
}
