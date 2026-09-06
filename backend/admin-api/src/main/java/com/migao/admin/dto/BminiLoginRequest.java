package com.migao.admin.dto;

import jakarta.validation.constraints.NotBlank;
import lombok.Data;

/**
 * B 端员工小程序登录请求 DTO（issue #2977）
 *
 * 与 C 端 MiniLoginRequest 语义不同：B 端员工「微信授权手机号匹配绑定」。
 * - code：wx.login() 返回的 code（必要）
 * - phoneCode：首次登录必传——getPhoneNumber 授权返回的动态 code，后端用它换真实手机号
 *   匹配员工账号并绑定 openid；二次登录（已绑定）可不带
 */
@Data
public class BminiLoginRequest {

    /** 微信小程序登录 code（wx.login() 返回） */
    @NotBlank(message = "code不能为空")
    private String code;

    /** 微信手机号授权 code（open-type=getPhoneNumber 返回；首次登录必传） */
    private String phoneCode;
}