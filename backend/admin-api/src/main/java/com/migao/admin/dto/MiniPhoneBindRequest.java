package com.migao.admin.dto;

import jakarta.validation.constraints.NotBlank;
import lombok.Data;

/**
 * 微信小程序手机号绑定请求 DTO
 *
 * code 为前端 &lt;button open-type="getPhoneNumber"&gt; 授权后返回的动态 code
 * （微信不直接给前端手机号，需后端用 code 调官方接口换取，防伪造）。
 */
@Data
public class MiniPhoneBindRequest {

    /**
     * 手机号授权动态 code（open-type=getPhoneNumber 的 bindgetphonenumber 回调）
     */
    @NotBlank(message = "手机号授权 code 不能为空")
    private String code;
}
