package com.migao.admin.dto;

import com.fasterxml.jackson.annotation.JsonFormat;
import lombok.Data;

import java.math.BigDecimal;
import java.time.OffsetDateTime;

/**
 * 商品SKU响应 DTO
 */
@Data
public class ProductSkuResponse {

    private Long id;

    private String productId;

    private Long colorId;

    private String colorName;

    /**
     * 售卖方式: bulk_cut(散剪) / full_roll(整卷)
     */
    private String sellingMethod;

    /**
     * 规格尺寸
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

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private OffsetDateTime createdAt;

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private OffsetDateTime updatedAt;
}
