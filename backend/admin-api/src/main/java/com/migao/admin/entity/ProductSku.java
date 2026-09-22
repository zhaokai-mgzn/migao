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
     * 规格尺寸: 2.8m / 3.2m / 3.4m
     *
     * <p>SKU 组合的**第二个**（也是最后一个）维度 —— 用户裁定 2026-09-21：
     * 「商品的售卖方式整卷/散件不能作为 SKU 的组合项，只能作为基础属性，
     * 商品的 SKU 由颜色+门幅组成即可」⇒ 原 {@code sellingMethod} 字段已随 V112 迁移删除
     * （售卖方式上移为商品级 {@link Product#getSellingMethods()}）。</p>
     */
    private String doorWidth;

    /**
     * 价格
     */
    private BigDecimal price;

    /**
     * 库存
     */
    private BigDecimal stock;

    /**
     * SKU编码
     */
    private String skuCode;

    /**
     * SKU 累计销量
     */
    private BigDecimal salesCount;

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
