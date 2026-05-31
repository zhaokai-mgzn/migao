package com.aikf.admin.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.List;

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

    /**
     * 商品货号
     */
    private String skuCode;

    /**
     * 计价单位（米/件/套等）
     */
    private String unit;

    private String categoryId;

    private BigDecimal basePrice;

    private String description;

    private String mainImage;

    @TableField(typeHandler = com.baomidou.mybatisplus.extension.handlers.JacksonTypeHandler.class)
    private Object images;

    /**
     * 详情图列表（JSONB 存储）
     */
    @TableField(value = "detail_images", typeHandler = com.baomidou.mybatisplus.extension.handlers.JacksonTypeHandler.class)
    private List<String> detailImages;

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

    /**
     * 库存扣减模式：sku/product
     */
    private String stockDeductionMode;

    /**
     * 是否含加工项
     */
    private Boolean hasProcessing;

    /**
     * 累计销量
     */
    private Integer salesCount;

    /**
     * 累计销售额
     */
    private BigDecimal salesAmount;

    /**
     * 最后编辑人
     */
    private String editedBy;

    /**
     * 最后编辑时间
     */
    private OffsetDateTime editedAt;

    @TableField(fill = FieldFill.INSERT)
    private OffsetDateTime createdAt;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private OffsetDateTime updatedAt;

    @TableLogic
    private Integer deleted;
}
