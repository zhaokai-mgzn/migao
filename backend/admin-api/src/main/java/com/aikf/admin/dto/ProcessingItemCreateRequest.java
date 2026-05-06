package com.aikf.admin.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;
import lombok.Data;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;

/**
 * 加工项创建请求 DTO
 */
@Data
public class ProcessingItemCreateRequest {

    /**
     * 加工项名称
     */
    @NotBlank(message = "加工项名称不能为空")
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
    @Positive(message = "单价必须大于 0")
    private BigDecimal unitPrice;

    /**
     * 单位
     */
    private String unit = "元";

    /**
     * 最小数量
     */
    private Integer minQuantity = 1;

    /**
     * 最大数量
     */
    private Integer maxQuantity = 999;

    /**
     * 描述
     */
    private String description;

    /**
     * 加工选项（如打孔：纳米圈/四爪钩/韩式S钩）
     */
    private List<Map<String, Object>> options;

    /**
     * 加工天数
     */
    private Integer processingDays = 1;

    /**
     * AI推荐
     */
    private Boolean aiRecommended = true;

    /**
     * 状态：active（启用）、inactive（禁用）
     */
    private String status = "active";
}
