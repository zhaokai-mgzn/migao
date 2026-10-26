package com.migao.admin.dto;

import jakarta.validation.constraints.NotBlank;
import lombok.Data;

/**
 * 扫码登录**兑换**请求（issue #7825）。
 *
 * <p>契约：`POST /api/auth/qr/exchange`，body `{ "ticket": "<jwt>" }`。
 * 票据由 `POST /api/auth/qr/ticket` 在**已登录**的 PC 会话下签发（120 秒、单次有效）。</p>
 */
@Data
public class QrExchangeRequest {

    /** 二维码票据（签名 JWT，tokenType=qr_login；只在 120 秒窗口内、且未兑换过时有效） */
    @NotBlank(message = "二维码票据不能为空")
    private String ticket;
}
