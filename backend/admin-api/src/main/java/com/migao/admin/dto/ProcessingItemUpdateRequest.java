package com.migao.admin.dto;

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
     * 计价方式：per_meter（按米）、per_set（按套）、fixed（固定价）、per_area（按面积）
     * 行业加工费按米计价、辅料含在加工费中 → 不支持按个（per_piece）与每米数量（issue #3005）
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
     * 加工天数
     */
    private Integer processingDays;

    /**
     * AI推荐
     */
    private Boolean aiRecommended;

    /**
     * **显式声明的工艺**（V78，issue #4452）：该加工项代表哪个工艺（韩褶/打孔/穿杆/平幔…）。
     * 改声明 ⇒ 后续订单的路线随之变；改加工项**名** ⇒ 路线**不变**。可空 = 没声明（不猜）。
     */
    @Size(max = 16, message = "工艺名不能超过16个字符")
    private String craftHint;

    /**
     * 状态：active（启用）、inactive（禁用）
     */
    private String status;
}
