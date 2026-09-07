package com.migao.admin.dto;

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
     * 数量（per_piece 且配置每米数量密度时，若提供 fabricMeters 则按密度重新推导，覆盖此值）
     */
    @NotNull(message = "数量不能为空")
    @Positive(message = "数量必须大于 0")
    private BigDecimal quantity;

    /**
     * 面料米数（可选）：per_piece 计价且加工项配置了 perMeterQuantity 时，
     * 数量 = ceil(面料米数 × 每米数量)，由服务端权威推导（用户零感知数量，issue #2986）
     */
    private BigDecimal fabricMeters;

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
