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
import java.time.OffsetDateTime;

/**
 * 盘点明细（V184）：一行 = 一缸布的账面 / 实盘 / 差异。
 *
 * <p>🔴 `bookQty` 是**盘点当刻的快照**：事后再读 `stock_batches.quantity` 早变了（期间可能出库/调拨）
 * ⇒ 不留快照，差异就无法复算，也解释不了「当时为什么判它少了 3 米」。</p>
 *
 * <p>🔴 `countedQty = null` 表示**还没数**，不是「数了正好一样」；`diffQty = null` 同理。</p>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName("stocktake_items")
public class StocktakeItem {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    private String stocktakeId;

    private Long batchId;

    private String batchNo;

    private String skuCode;

    /** 盘点当刻的账面量（快照）。 */
    private BigDecimal bookQty;

    /** 实盘量；`null` = 还没数。 */
    private BigDecimal countedQty;

    /** 差异 = 实盘 − 账面；`null` = 还没数。 */
    private BigDecimal diffQty;

    private BigDecimal unitCost;

    private OffsetDateTime createdAt;

    @TableLogic
    private Integer deleted;
}
