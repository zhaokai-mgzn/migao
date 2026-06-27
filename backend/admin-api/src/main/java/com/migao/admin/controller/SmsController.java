package com.migao.admin.controller;

import com.migao.admin.dto.ApiResponse;
import com.migao.admin.dto.SmsSendRequest;
import com.migao.admin.dto.SmsVerifyRequest;
import com.migao.admin.service.SmsService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.*;

import java.util.Map;

/**
 * 短信验证码控制器
 * 处理验证码发送、校验等短信相关接口
 */
@Slf4j
@RestController
@RequestMapping("/api/auth/sms")
@RequiredArgsConstructor
public class SmsController {

    private final SmsService smsService;

    /**
     * 发送短信验证码
     *
     * POST /api/auth/sms/send
     *
     * Request: { "phone": "13800138000" }
     * Response: { "success": true }
     */
    @PostMapping("/send")
    public ApiResponse<Void> sendVerificationCode(@Valid @RequestBody SmsSendRequest request) {
        log.info("发送短信验证码请求: phone={}", request.getPhone());
        smsService.sendVerificationCode(request.getPhone());
        return ApiResponse.success();
    }

    /**
     * 校验短信验证码（#733: order_create 调用此 API 验证手机号）
     *
     * POST /api/auth/sms/verify
     *
     * Request: { "phone": "13800138000", "code": "123456" }
     * Response (成功): { "success": true, "data": { "verifiedPhone": "13800138000" } }
     * Response (失败): { "success": false, "error": { "message": "验证码错误或已过期" } }
     */
    @PostMapping("/verify")
    public ApiResponse<Map<String, String>> verifyCode(@Valid @RequestBody SmsVerifyRequest request) {
        log.info("校验短信验证码请求: phone={}", request.getPhone());
        boolean verified = smsService.verifyCode(request.getPhone(), request.getCode());

        if (!verified) {
            return ApiResponse.error("SMS_VERIFY_FAILED", "验证码错误或已过期");
        }

        return ApiResponse.success(Map.of("verifiedPhone", request.getPhone()));
    }
}
