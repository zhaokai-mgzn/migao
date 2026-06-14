package com.migao.admin.dto;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.math.BigDecimal;

/**
 * 按颜色+规格维度的低库存告警响应
 */
@Data
@AllArgsConstructor
@NoArgsConstructor
public class LowStockByColorResponse {
    /** SKU ID */
    private Long skuId;
    /** 商品ID */
    private String productId;
    /** 商品名称 */
    private String productName;
    /** 商品货号 */
    private String skuCode;
    /** 颜色ID */
    private Long colorId;
    /** 颜色名称 */
    private String colorName;
    /** 规格尺寸（门幅） */
    private String doorWidth;
    /** SKU 粒度库存 */
    private Integer stock;
    /** 价格 */
    private BigDecimal price;
}
