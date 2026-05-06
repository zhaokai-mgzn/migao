package com.aikf.admin.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import lombok.Data;

/**
 * 微信小程序登录请求 DTO
 */
@Data
public class MiniLoginRequest {

    /**
     * 微信小程序登录 code（wx.login() 返回）
     */
    @NotBlank(message = "code不能为空")
    private String code;

    /**
     * 租户ID
     */
    @NotNull(message = "租户ID不能为空")
    private Long tenantId;
}
