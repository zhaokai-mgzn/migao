package com.migao.admin.controller;

import com.migao.admin.service.kf.KfCallbackService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * 企业微信「微信客服」回调入口（公开，无登录态）。
 *
 * <p>GET：URL 验证，1 秒内返回明文 echostr；POST：验签解密 → inbox → 200 空串（5 秒内）。</p>
 */
@Slf4j
@RestController
@ConditionalOnProperty(prefix = "wechat.kf", name = "enabled", havingValue = "true")
@RequestMapping("/api/kf/callback")
@RequiredArgsConstructor
public class KfCallbackController {

    private final KfCallbackService callbackService;

    @GetMapping(produces = MediaType.TEXT_PLAIN_VALUE)
    public ResponseEntity<String> verify(@RequestParam("msg_signature") String signature,
                                         @RequestParam("timestamp") String timestamp,
                                         @RequestParam("nonce") String nonce,
                                         @RequestParam("echostr") String echostr) {
        if (!callbackService.isConfigured()) {
            return ResponseEntity.status(503).body("");
        }
        return ResponseEntity.ok(callbackService.verifyUrl(signature, timestamp, nonce, echostr));
    }

    @PostMapping(produces = MediaType.TEXT_PLAIN_VALUE)
    public ResponseEntity<String> receive(@RequestParam("msg_signature") String signature,
                                          @RequestParam("timestamp") String timestamp,
                                          @RequestParam("nonce") String nonce,
                                          @RequestBody String body) {
        if (!callbackService.isConfigured()) {
            return ResponseEntity.status(503).body("");
        }
        callbackService.handle(body, signature, timestamp, nonce);
        return ResponseEntity.ok("");
    }
}
