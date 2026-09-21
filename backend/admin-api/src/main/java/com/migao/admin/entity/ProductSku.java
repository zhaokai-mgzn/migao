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

    /**
     * 移动加权平均单位成本（V111，issue #5034）。
     * <b>NULL = 未知</b>（存量库存无成本真值来源，一律不回填、不猜 0）。
     */
    private BigDecimal avgCost;

    /**
     * 库存成本金额 = stock * avgCost（V111，派生冗余列）；NULL = 成本未知。
     */
    private BigDecimal costAmount;

    /**
     * 最近一次入库的批次号（V111，PC-yyyyMMdd-NNNN）；NULL = 从未入库过。
     * 给「同一批次一致性」话术提供可引用真值。
     */
    private String latestBatchNo;

    @TableField(fill = FieldFill.INSERT)
    private OffsetDateTime createdAt;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private OffsetDateTime updatedAt;
}
