package com.migao.admin.dto;

import jakarta.validation.constraints.NotBlank;
import lombok.Data;

/**
 * 员工登录请求（issue #5485）。
 *
 * <p>{@code identifier} = {@code <username>@<tenantCode>}，按**最后一个 {@code @}** 切分、
 * 两侧非空；username / tenantCode 统一转小写。租户**只**由标识里的企业编码解析 ——
 * 不接受 body 传入 tenantId（否则「任意数字即可切租户」）。
 *
 * <p>⚠️ 校验注解只挡「整个字段为空」这一种形态：格式不合规（含企业编码不存在 / 用户名不存在 /
 * 密码错误）一律走**同一 401 同一文案**（反枚举）。
 */
@Data
public class EmployeeLoginRequest {

    /** 登录标识：用户名@企业编码 */
    @NotBlank(message = "登录标识不能为空")
    private String identifier;

    /** 密码 */
    @NotBlank(message = "密码不能为空")
    private String password;
}