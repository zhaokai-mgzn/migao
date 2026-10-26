package com.migao.admin.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * 扫码登录**票据**响应（issue #7825）。
 *
 * <p>地址形态由前端单一真值模块拼：`<B端H5地址>?qr=<urlencoded ticket>`。</p>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class QrTicketResponse {

    /** 一次性票据（签名 JWT；前端只搬运，不解析） */
    private String ticket;

    /** 有效期（秒）= `jwt.qr-login-ticket-expiration`；前端据此显示倒计时并在过期后重新签发 */
    private Long expiresIn;
}
