package com.migao.admin.dto;

import jakarta.validation.constraints.NotBlank;
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
     * 租户ID（可选，issue #3011）：C 端租户域名路由上线后以服务端域名解析为准，
     * body tenantId 仅作兼容期兜底；解析到域名租户时本字段被忽略。
     */
    private Long tenantId;
}
