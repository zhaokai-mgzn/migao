package com.aikf.admin.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;
import lombok.Data;

import java.math.BigDecimal;
import java.util.List;

/**
 * 商品创建请求 DTO
 */
@Data
public class ProductCreateRequest {

    /**
     * 商品名称
     */
    @NotBlank(message = "商品名称不能为空")
    private String name;

    /**
     * 分类ID
     */
    @NotBlank(message = "分类ID不能为空")
    private String categoryId;

    /**
     * 基础价格
     */
    @NotNull(message = "基础价格不能为空")
    @Positive(message = "基础价格必须大于 0")
    private BigDecimal basePrice;

    /**
     * 商品描述
     */
    private String description;

    /**
     * 主图URL
     */
    private String mainImage;

    /**
     * 图片列表（JSON数组）
     */
    private List<String> images;

    /**
     * 知识库ID
     */
    private String knowledgeBaseId;

    /**
     * 状态：on_sale（上架）、off_sale（下架）
     */
    private String status = "off_sale";

    /**
     * 库存数量，默认 0
     */
    private Integer stock = 0;

    /**
     * 库存预警阈值，默认 10
     */
    private Integer stockWarningThreshold = 10;
}
