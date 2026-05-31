package com.aikf.admin.dto;

import jakarta.validation.constraints.NotBlank;
import lombok.Data;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;

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
     * 商品货号
     */
    private String skuCode;

    /**
     * 计价单位（米/件/套等）
     */
    private String unit;

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

    // ========== 销售信息（颜色 / 售卖方式 / 规格尺寸 / SKU） ==========

    /**
     * 颜色分类列表
     */
    private List<ProductColorInput> colors;

    /**
     * 售卖方式列表（如 bulk_cut / full_roll）
     */
    private List<String> sellingMethods;

    /**
     * 规格尺寸列表（如 2.8m / 3.2m / 3.4m）
     */
    private List<String> doorWidths;

    /**
     * SKU 列表
     */
    private List<ProductSkuInput> skus;

    // ========== 商品属性与详情图 ==========

    /**
     * 品牌
     */
    private String brand;

    /**
     * 商品属性字典，key 可为 weight/material/function/craft/style/pattern 等
     */
    private Map<String, String> specifications;

    /**
     * 详情图列表
     */
    private List<String> detailImages;

    /**
     * 加工项配置列表
     */
    private List<ProcessingItemConfigInput> processingItemConfigs;
}
