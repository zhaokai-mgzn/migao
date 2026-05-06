package com.aikf.admin.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.math.BigDecimal;
import java.time.OffsetDateTime;

/**
 * 商品实体类
 * 对应表：products
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName(value = "products", autoResultMap = true)
public class Product {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    private String name;

    private String categoryId;

    private BigDecimal basePrice;

    private String description;

    private String mainImage;

    @TableField(typeHandler = com.baomidou.mybatisplus.extension.handlers.JacksonTypeHandler.class)
    private Object images;

    private String knowledgeBaseId;

    private String status;

    /**
     * 库存数量
     */
    @TableField("stock")
    private Integer stock = 0;

    /**
     * 库存预警阈值
     */
    @TableField("stock_warning_threshold")
    private Integer stockWarningThreshold = 10;

    @TableField(fill = FieldFill.INSERT)
    private OffsetDateTime createdAt;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private OffsetDateTime updatedAt;

    @TableLogic
    private Integer deleted;
}
