package com.aikf.admin.dto;

import jakarta.validation.constraints.*;
import lombok.Data;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;

/**
 * 加工项更新请求 DTO
 */
@Data
public class ProcessingItemUpdateRequest {

    /**
     * 加工项名称
     */
    @NotBlank(message = "加工项名称不能为空")
    @Size(max = 20, message = "加工项名称不能超过20个字符")
    private String name;

    /**
     * 分类ID
     */
    @NotBlank(message = "分类ID不能为空")
    private String categoryId;

    /**
     * 计价方式：per_meter（按米）、per_piece（按件）、fixed（固定价）、per_area（按面积）
     */
    @NotBlank(message = "计价方式不能为空")
    private String pricingMethod;

    /**
     * 单价
     */
    @NotNull(message = "单价不能为空")
    @DecimalMin(value = "0.10", message = "加工项价格不能低于0.10")
    @DecimalMax(value = "999.99", message = "加工项价格不能超过999.99")
    @Digits(integer = 3, fraction = 2, message = "价格最多支持2位小数")
    private BigDecimal unitPrice;

    /**
     * 单位
     */
    private String unit;

    /**
     * 最小数量
     */
    private Integer minQuantity;

    /**
     * 最大数量
     */
    private Integer maxQuantity;

    /**
     * 描述
     */
    private String description;

    /**
     * 加工选项
     */
    private List<Map<String, Object>> options;

    /**
     * 适用商品分类ID列表（哪些商品分类需要此加工项）
     */
    private java.util.List<String> applicableProductCategories;

    /**
     * 加工天数
     */
    private Integer processingDays;

    /**
     * AI推荐
     */
    private Boolean aiRecommended;

    /**
     * 状态：active（启用）、inactive（禁用）
     */
    private String status;
}
