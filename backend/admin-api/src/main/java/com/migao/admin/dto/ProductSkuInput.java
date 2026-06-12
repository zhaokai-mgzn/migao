package com.migao.admin.dto;

import lombok.Data;

import java.math.BigDecimal;

/**
 * 商品 SKU 输入 DTO（创建/更新商品时使用）
 *
 * colorId 来源于前端 ProductColorInput.id（可能为负数临时ID），
 * 后端在保存颜色后通过映射表替换为真实的数据库主键。
 */
@Data
public class ProductSkuInput {

    /**
     * 前端临时SKU ID
     */
    private Long id;

    /**
     * 颜色ID（前端临时ID，后端会映射为 DB 主键）
     */
    private Long colorId;

    /**
     * 售卖方式: bulk_cut / full_roll
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
     * SKU编码（可选）
     */
    private String skuCode;
}
