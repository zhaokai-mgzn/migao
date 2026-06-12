package com.migao.admin.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import lombok.Data;

import java.math.BigDecimal;
import java.util.List;

/**
 * 创建售后工单请求 DTO
 * 对齐前端 AfterSalesFormData 类型
 */
@Data
public class AfterSalesCreateRequest {

    @NotBlank(message = "订单ID不能为空")
    private String orderId;

    @NotBlank(message = "售后类型不能为空")
    @Pattern(regexp = "^(return|exchange|repair|refund|complaint|other)$", message = "无效的售后类型")
    private String ticketType;

    @NotBlank(message = "问题描述不能为空")
    private String description;

    private List<String> images;

    @Pattern(regexp = "^(normal|urgent|critical)$", message = "无效的优先级")
    private String priority;

    private BigDecimal refundAmount;
}
