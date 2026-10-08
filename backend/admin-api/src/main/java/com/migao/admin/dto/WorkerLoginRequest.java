package com.migao.admin.dto;

import jakarta.validation.constraints.NotBlank;
import lombok.Data;

/**
 * 工人登录请求（issue #4733）：**工号 + PIN**，主路径**不依赖微信**。
 *
 * <p>为什么不用微信授权做主路径：PAD 普通浏览器**没有**微信授权（设计 §2.1 裁定③）；
 * 微信网页授权今天还是 501 占位（{@code AuthService.buildWechatH5AuthorizeUrl}），
 * 且**不得**成为唯一路径。</p>
 */
@Data
public class WorkerLoginRequest {

    /** 工号（租户内唯一）。 */
    @NotBlank(message = "工号不能为空")
    private String workerNo;

    /** PIN（服务端按 BCrypt 比对 {@code users.password_hash}；不落日志、不回显）。 */
    @NotBlank(message = "PIN 不能为空")
    private String pin;

    /** 设备标签（PAD-车间-01 之类；可空，用于「由哪个设备会话报的」快照）。 */
    private String deviceLabel;

    /**
     * 企业编码（issue #6564）：服务端解析租户的**权威入口**（可不传 —— 工号写成
     * {@code <工号>@<企业编码>} 时由工号携带；域名/网关头存在时它也不是必需）。
     */
    private String enterpriseCode;

    /**
     * 租户 id。
     *
     * @deprecated 兼容期兜底，新前端**不得**再传（issue #6564）—— 服务端只在域名/网关头、
     *     {@link #enterpriseCode}、{@code 工号@企业编码} 三档都拿不到时才用它，且会打 WARN。
     */
    @Deprecated
    private Long tenantId;
}
