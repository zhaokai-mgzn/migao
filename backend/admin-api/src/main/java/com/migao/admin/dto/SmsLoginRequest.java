package com.migao.admin.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import lombok.Data;

/**
 * 短信验证码登录请求 DTO
 */
@Data
public class SmsLoginRequest {

    /**
     * 手机号
     */
    @NotBlank(message = "手机号不能为空")
    @Pattern(regexp = "^1[3-9]\\d{9}$", message = "手机号格式不正确")
    private String phone;

    /**
     * 短信验证码
     */
    @NotBlank(message = "验证码不能为空")
    private String code;

    /**
     * 租户 ID（可选）。同手机号存在于多个租户时必填，用于精确匹配
     * （审计 07 P1-2：禁止静默登录进错误租户）。
     */
    private Long tenantId;
}
