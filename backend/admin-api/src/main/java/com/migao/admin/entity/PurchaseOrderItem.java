package com.migao.admin.entity;

import com.baomidou.mybatisplus.annotation.FieldFill;
import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
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
 * 采购单明细（issue #7369 段 4）。
 *
 * <p>对应表 {@code purchase_order_items}（V175）。**不是库存**：收货才进库存。
 *
 * <p>🔴 「已收多少」**不在本表累加**：它是 Σ receipts 的派生值。若在这里再加一列计数，
 * 撤销/更正一笔收货就要同时改两处，任何一处漏改就永久对不上。</p>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName("purchase_order_items")
public class PurchaseOrderItem {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    private String purchaseOrderId;

    private Integer lineNo;

    private String productId;

    private String skuId;

    private BigDecimal quantity;

    private BigDecimal unitPrice;

    private BigDecimal amount;

    @TableField(fill = FieldFill.INSERT)
    private OffsetDateTime createdAt;

    @TableLogic(value = "false", delval = "true")
    private Boolean deleted;
}
