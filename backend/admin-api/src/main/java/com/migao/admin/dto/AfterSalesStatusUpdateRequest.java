package com.migao.admin.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import lombok.Data;

/**
 * 售后工单状态更新请求 DTO
 * 对齐前端 AfterSalesStatusUpdateParams 类型
 */
@Data
public class AfterSalesStatusUpdateRequest {

    @NotBlank(message = "状态不能为空")
    @Pattern(regexp = "^(pending|processing|resolved|rejected|closed)$", message = "无效的售后状态")
    private String status;

    private String remark;
}
