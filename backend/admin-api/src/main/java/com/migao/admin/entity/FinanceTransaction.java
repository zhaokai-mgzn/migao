package com.migao.admin.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.math.BigDecimal;
import java.time.OffsetDateTime;

/**
 * 资金流水实体类（财务对账）
 * 对应表：finance_transactions
 *
 * <p>作为现金流的单一事实来源：每笔收款（income）/退款（refund）都有一条流水。
 * 订单确认支付、退款时由 OrderService 自动登记；线下收款/退款可通过财务模块手动登记。</p>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName("finance_transactions")
public class FinanceTransaction {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    /** 流水号，格式 FIN-yyyyMMdd-XXXX */
    private String transactionNo;

    /** 关联订单 UUID（线下收款可为空） */
    private String orderId;

    /** 冗余订单号，便于列表展示与检索 */
    private String orderNo;

    /** income / refund */
    private String type;

    /** 金额（正数） */
    private BigDecimal amount;

    /** wechat / alipay / bank_transfer / cash / other */
    private String paymentMethod;

    /** pending / success / failed */
    private String status;

    /** 操作人（用户名，自动登记时取当前登录人） */
    private String operator;

    /** 交易发生时间 */
    private OffsetDateTime occurredAt;

    private String remark;

    @TableField(fill = FieldFill.INSERT)
    private OffsetDateTime createdAt;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private OffsetDateTime updatedAt;

    @TableLogic
    private Integer deleted;
}
