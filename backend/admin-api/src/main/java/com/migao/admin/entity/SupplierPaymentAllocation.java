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
 * 付款冲抵明细（issue #7369 段 3-B）：这一笔钱冲到哪张入库单、各多少。
 *
 * <p>对应表 {@code supplier_payment_allocations}（V174）。两条硬约束由服务层 + DB 共同把守：
 * 同一笔付款对同一张单至多一行；单张单的冲抵合计 ≤ 该单金额（防同一张单被重复付掉）。
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName("supplier_payment_allocations")
public class SupplierPaymentAllocation {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    private String paymentId;

    private String inboundOrderId;

    private BigDecimal amount;

    @TableField(fill = FieldFill.INSERT)
    private OffsetDateTime createdAt;

    @TableLogic
    private Boolean deleted;
}
