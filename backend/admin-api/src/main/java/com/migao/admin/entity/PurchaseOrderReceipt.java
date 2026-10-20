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
import java.time.LocalDate;
import java.time.OffsetDateTime;

/**
 * 采购收货记录（issue #7369 段 4）：一次到货一行。
 *
 * <p>对应表 {@code purchase_order_receipts}（V175）。{@code inboundOrderId} 可空 ——
 * 由收货自动生成入库单时填上，手工登记收货时留空：两张单据各自留痕，不互相顶替。</p>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName("purchase_order_receipts")
public class PurchaseOrderReceipt {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    private String purchaseOrderId;

    private String purchaseOrderItemId;

    /** 码生成的那张入库单（手工登记收货时为空） */
    private String inboundOrderId;

    private BigDecimal quantity;

    private LocalDate receivedAt;

    private String remark;

    private String createdBy;

    @TableField(fill = FieldFill.INSERT)
    private OffsetDateTime createdAt;

    @TableLogic
    private Boolean deleted;
}
