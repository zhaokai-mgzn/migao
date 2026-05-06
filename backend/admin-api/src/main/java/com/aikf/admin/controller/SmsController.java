package com.aikf.admin.controller;

import com.aikf.admin.dto.ApiResponse;
import com.aikf.admin.dto.SmsSendRequest;
import com.aikf.admin.service.SmsService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.*;

/**
 * 短信验证码控制器
 * 处理验证码发送等短信相关接口
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
}
