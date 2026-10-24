package com.migao.admin.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.Data;

import java.math.BigDecimal;
import java.time.OffsetDateTime;

/**
 * 客户收款核销（issue #7370，P0-2 段 3）：**一笔收入流水**冲抵到**一张订单**的金额。
 *
 * <p>现金真值源**不在这里**：金额/方式/日期只认 {@code finance_transactions}（{@link FinanceTransaction}）。
 * 本表只回答「这笔钱冲了哪几张单、各多少」—— 复制金额就是第二份会漂移的真相。</p>
 *
 * <p>约束（服务层 + 迁移双层）：同一流水对同一单至多一行（部分唯一索引）；本行金额 &gt; 0；
 * Σ本流水的核销 ≤ 该流水金额；某单的核销合计 ≤ 该单余额（货值 − 退款）。</p>
 */
@Data
@TableName("receipt_allocations")
public class ReceiptAllocation {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    /** 收入流水（`finance_transactions.id`，type=income ∧ status=success） */
    private String transactionId;

    /** 被冲抵的订单（`orders.id`） */
    private String orderId;

    /** 本行核销金额（> 0，两位小数） */
    private BigDecimal amount;

    private String createdBy;

    @TableField(fill = FieldFill.INSERT)
    private OffsetDateTime createdAt;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private OffsetDateTime updatedAt;

    @TableLogic(value = "false", delval = "true")
    private Boolean deleted;
}
