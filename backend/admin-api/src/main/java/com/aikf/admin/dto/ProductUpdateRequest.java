package com.aikf.admin.dto;

import jakarta.validation.constraints.NotBlank;
import lombok.Data;

import java.math.BigDecimal;
import java.util.List;

/**
 * 商品更新请求 DTO
 */
@Data
public class ProductUpdateRequest {

    /**
     * 商品名称
     */
    @NotBlank(message = "商品名称不能为空")
    private String name;

    /**
     * 分类ID（草稿状态允许为空，Service 层根据 status 校验）
     */
    private String categoryId;

    /**
     * 基础价格（草稿状态允许为空，Service 层根据 status 校验）
     */
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
    private String status;

    /**
     * 库存数量
     */
    private Integer stock;

    /**
     * 库存预警阈值
     */
    private Integer stockWarningThreshold;
}
