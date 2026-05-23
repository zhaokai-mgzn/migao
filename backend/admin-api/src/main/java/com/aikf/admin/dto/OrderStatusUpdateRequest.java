package com.aikf.admin.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import lombok.Data;

/**
 * 订单状态更新请求 DTO
 */
@Data
public class OrderStatusUpdateRequest {

    /**
     * 订单状态
     * pending: 待确认
     * confirmed: 已确认
     * producing: 生产中
     * shipped: 已发货
     * completed: 已完成
     * cancelled: 已取消
     */
    @NotBlank(message = "订单状态不能为空")
    @Pattern(regexp = "^(pending|confirmed|producing|shipped|completed|cancelled)$", message = "无效的订单状态")
    private String status;
}
