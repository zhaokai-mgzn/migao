package com.migao.admin.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.math.BigDecimal;
import java.time.OffsetDateTime;

/**
 * 商品SKU实体类
 * 对应表：product_skus
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName("product_skus")
public class ProductSku {

    @TableId(type = IdType.ASSIGN_ID)
    private Long id;

    private Long tenantId;

    private String productId;

    /**
     * 关联颜色ID（兼容旧数据，新数据优先使用 colorName）
     */
    private Long colorId;

    /**
     * 颜色标识（色号如"2699-01"或颜色名如"白色"）
     */
    private String colorName;

    /**
     * 售卖方式: bulk_cut(散剪) / full_roll(整卷)
     */
    private String sellingMethod;

    /**
     * 规格尺寸: 2.8m / 3.2m / 3.4m
     */
    private String doorWidth;

    /**
     * 价格
     */
    private BigDecimal price;

    /**
     * 库存
     */
    private Integer stock;

    /**
     * SKU编码
     */
    private String skuCode;

    /**
     * SKU 累计销量
     */
    private Integer salesCount;

    @TableField(fill = FieldFill.INSERT)
    private OffsetDateTime createdAt;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private OffsetDateTime updatedAt;
}
