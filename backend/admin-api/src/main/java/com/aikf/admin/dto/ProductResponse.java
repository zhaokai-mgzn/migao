package com.aikf.admin.dto;

import com.fasterxml.jackson.annotation.JsonFormat;
import lombok.Data;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.List;

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
     * SKU列表（详情接口返回）
     */
    private List<ProductSkuResponse> skus;

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
