package com.aikf.admin.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import lombok.Data;

/**
 * 企业入驻申请请求 DTO
 */
@Data
public class RegistrationRequest {

    /**
     * 企业名称
     */
    @NotBlank(message = "企业名称不能为空")
    private String companyName;

    /**
     * 联系人姓名
     */
    @NotBlank(message = "联系人姓名不能为空")
    private String contactName;

    /**
     * 联系手机号
     */
    @NotBlank(message = "手机号不能为空")
    @Pattern(regexp = "^1[3-9]\\d{9}$", message = "手机号格式不正确")
    private String phone;

    /**
     * 短信验证码
     */
    @NotBlank(message = "短信验证码不能为空")
    private String smsCode;

    /**
     * 营业执照 URL
     */
    private String businessLicenseUrl;

    /**
     * 行业
     */
    private String industry;

    /**
     * 地址
     */
    private String address;

    /**
     * 企业描述
     */
    private String description;
}
