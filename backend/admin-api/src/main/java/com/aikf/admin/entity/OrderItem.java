package com.aikf.admin.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.math.BigDecimal;
import java.time.OffsetDateTime;

/**
 * 订单明细实体类
 * 对应表：order_items
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName(value = "order_items", autoResultMap = true)
public class OrderItem {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    private String orderId;

    private String productId;

    private String productName;

    private Integer quantity;

    private BigDecimal unitPrice;

    private BigDecimal width;

    private BigDecimal height;

    @TableField(typeHandler = com.baomidou.mybatisplus.extension.handlers.JacksonTypeHandler.class)
    private Object processingInfo;

    private BigDecimal subtotal;

    @TableField(fill = FieldFill.INSERT)
    private OffsetDateTime createdAt;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private OffsetDateTime updatedAt;

    @TableLogic
    private Integer deleted;
}
