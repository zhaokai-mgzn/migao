package com.migao.admin.dto;

import com.fasterxml.jackson.annotation.JsonFormat;
import lombok.Data;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.Map;

/**
 * 商品响应 DTO
 */
@Data
public class ProductResponse {

    /**
     * 商品ID
     */
    private String id;

    /**
     * 商品名称
     */
    private String name;

    /**
     * 分类ID
     */
    private String categoryId;

    /**
     * 分类名称
     */
    private String categoryName;

    /**
     * 基础价格
     */
    private BigDecimal basePrice;

    /**
     * 价格（前端兼容字段，同 basePrice）
     */
    public BigDecimal getPrice() {
        return basePrice;
    }

    /**
     * 商品描述
     */
    private String description;

    /**
     * 主图URL
     */
    private String mainImage;

    /**
     * 图片列表
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

    /**
     * 商品货号
     */
    private String skuCode;

    /**
     * 计价单位（米/件/套等）
     */
    private String unit;

    /**
     * 计价方式：per_meter / per_piece / fixed / per_area
     */
    private String pricingType;

    /**
     * 库存扣减模式
     */
    private String stockDeductionMode;

    /**
     * 颜色数量
     */
    private Integer colorCount;

    /**
     * SKU总库存
     */
    private Integer totalStock;

    /**
     * 累计销量
     */
    private Integer salesCount;

    /**
     * 累计销售额
     */
    private BigDecimal salesAmount;

    /**
     * 颜色分类列表（详情接口返回）
     */
    private List<ProductColorResponse> colors;

    /**
     * 售卖方式列表（详情接口返回，去重后从 SKU 派生）
     */
    private List<String> sellingMethods;

    /**
     * 规格尺寸列表（详情接口返回，去重后从 SKU 派生）
     */
    private List<String> doorWidths;

    /**
     * SKU列表（详情接口返回）
     */
    private List<ProductSkuResponse> skus;

    /**
     * 品牌
     */
    private String brand;

    /**
     * 商品属性字典（weight/material/function/craft/style/pattern 等）
     */
    private Map<String, String> specifications;

    /**
     * 详情图列表
     */
    private List<String> detailImages;

    /**
     * 加工项配置列表
     */
    private List<ProcessingItemConfigResponse> processingItemConfigs;

    /**
     * 最后编辑人
     */
    private String editedBy;

    /**
     * 最后编辑时间
     */
    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private OffsetDateTime editedAt;

    /**
     * 创建时间
     */
    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private OffsetDateTime createdAt;

    /**
     * 更新时间
     */
    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private OffsetDateTime updatedAt;
}
