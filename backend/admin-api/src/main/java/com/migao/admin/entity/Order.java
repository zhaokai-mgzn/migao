package com.migao.admin.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.math.BigDecimal;
import java.time.OffsetDateTime;

/**
 * 订单实体类
 * 对应表：orders
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName("orders")
public class Order {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    private String orderNo;

    private String customerName;

    private String customerPhone;

    private String customerAddress;

    private BigDecimal totalAmount;

    /**
     * 实收款（用户输入的实际收款金额，默认等于 totalAmount）
     */
    private BigDecimal actualAmount;

    private String status;

    /**
     * 跟进状态: pending/following/completed
     */
    private String followStatus;

    private String remark;

    /**
     * 关闭原因
     */
    private String closeReason;

    @TableField(fill = FieldFill.INSERT)
    private OffsetDateTime createdAt;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private OffsetDateTime updatedAt;

    @TableLogic
    private Integer deleted;
}
