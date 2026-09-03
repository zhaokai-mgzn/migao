package com.migao.admin.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import lombok.Data;

import java.math.BigDecimal;
import java.util.List;

/**
 * 创建售后工单请求 DTO
 * 对齐前端 AfterSalesFormData 类型
 *
 * 注意：orderId 不做 @NotBlank——complaint（投诉）类工单允许无关联订单
 * （转人工/服务投诉场景），由 Service 层按 ticketType 判定：
 * 非 complaint 且 orderId 为空 → selectById(null)=null → 「关联订单不存在」；
 * complaint → 跳过订单校验，customer 降级「投诉用户」。
 * （此前 DTO 层 @NotBlank 一刀切拦截，导致 complaint 无订单被 422，见 P0 验证 P1-5）
 */
@Data
public class AfterSalesCreateRequest {

    /**
     * 关联订单ID（complaint 类可空）
     */
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
