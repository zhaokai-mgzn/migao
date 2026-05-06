package com.aikf.admin.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;
import lombok.Data;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;

/**
 * 价格计算请求 DTO
 */
@Data
public class PriceCalculateRequest {

    /**
     * 加工项ID
     */
    @NotBlank(message = "加工项ID不能为空")
    private String processingItemId;

    /**
     * 数量
     */
    @NotNull(message = "数量不能为空")
    @Positive(message = "数量必须大于 0")
    private BigDecimal quantity;

    /**
     * 尺寸（宽 x 高），某些计价方式需要
     */
    private Map<String, BigDecimal> dimensions;

    /**
     * 选择的选项
     */
    private List<String> selectedOptions;

    /**
     * 其他参数
     */
    private Map<String, Object> params;
}
