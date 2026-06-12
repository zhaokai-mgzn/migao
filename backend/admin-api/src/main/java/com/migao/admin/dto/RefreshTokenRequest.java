package com.migao.admin.dto;

import jakarta.validation.constraints.NotBlank;
import lombok.Data;

/**
 * 刷新 Token 请求 DTO
 */
@Data
public class RefreshTokenRequest {

    /**
     * 刷新 Token
     */
    @NotBlank(message = "刷新 Token 不能为空")
    private String refreshToken;
}
