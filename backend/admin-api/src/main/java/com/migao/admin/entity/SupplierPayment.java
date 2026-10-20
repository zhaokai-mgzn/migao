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
 * 供应商付款（issue #7369，P0-1 段 3-B）：一笔付款，可冲抵多张入库单。
 *
 * <p>对应表 {@code supplier_payments}（V174）。{@code amount} 与冲抵合计的差额 = **未冲抵**
 * （预付 / 待勾对）—— 这是真实状态（先打款后到票），不是数据错误。
 *
 * <p>作废 = {@code status = voided} + 谁/何时/为什么，**不物理删**：付款凭证要能追溯。
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName("supplier_payments")
public class SupplierPayment {

    /** 已入账（有效）；作废后其金额与冲抵同时失效。 */
    public static final String STATUS_POSTED = "posted";
    public static final String STATUS_VOIDED = "voided";

    /** 付款方式域（与迁移里的 CHECK 逐值同域）。 */
    public static final java.util.Set<String> METHODS =
            java.util.Set.of("cash", "transfer", "wechat", "alipay", "other");

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    private String supplierId;

    /** FK-yyyyMMdd-NNNN（租户内唯一；财务凭号找单） */
    private String paymentNo;

    private LocalDate paidAt;

    private BigDecimal amount;

    private String method;

    /** 回单号 / 银行流水号（对账时要能对上） */
    private String referenceNo;

    private String remark;

    private String status;

    private OffsetDateTime voidedAt;

    private String voidedBy;

    private String voidedReason;

    private String createdBy;

    @TableField(fill = FieldFill.INSERT)
    private OffsetDateTime createdAt;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private OffsetDateTime updatedAt;

    @TableLogic
    private Boolean deleted;
}
