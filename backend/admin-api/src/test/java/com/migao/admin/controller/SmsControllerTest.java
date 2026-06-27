package com.migao.admin.controller;

import com.migao.admin.config.GlobalExceptionHandler;
import com.migao.admin.dto.SmsSendRequest;
import com.migao.admin.dto.SmsVerifyRequest;
import com.migao.admin.service.SmsService;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

/**
 * SmsController 单元测试
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("SmsController 短信验证码测试")
class SmsControllerTest {

    private MockMvc mockMvc;
    private final ObjectMapper objectMapper = new ObjectMapper();

    @Mock
    private SmsService smsService;

    @InjectMocks
    private SmsController smsController;

    @BeforeEach
    void setUp() {
        mockMvc = MockMvcBuilders.standaloneSetup(smsController)
                .setControllerAdvice(new GlobalExceptionHandler())
                .build();
    }

    @Test
    @DisplayName("发送验证码 → 200")
    void sendVerificationCode_returns200() throws Exception {
        doNothing().when(smsService).sendVerificationCode("13800138000");

        SmsSendRequest request = new SmsSendRequest();
        request.setPhone("13800138000");

        mockMvc.perform(post("/api/auth/sms/send")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true));

        verify(smsService).sendVerificationCode("13800138000");
    }

    @Test
    @DisplayName("发送验证码 — 空手机号 → 400")
    void sendVerificationCode_emptyPhone_returns400() throws Exception {
        mockMvc.perform(post("/api/auth/sms/send")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"phone\":\"\"}"))
                .andExpect(status().is4xxClientError());
    }

    // ============================================================
    // SMS verify endpoint tests (#733)
    // ============================================================

    @Test
    @DisplayName("校验验证码成功 → 200，返回 verifiedPhone")
    void verifyCode_success_returnsVerifiedPhone() throws Exception {
        when(smsService.verifyCode("13800138000", "123456")).thenReturn(true);

        SmsVerifyRequest request = new SmsVerifyRequest();
        request.setPhone("13800138000");
        request.setCode("123456");

        mockMvc.perform(post("/api/auth/sms/verify")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.verifiedPhone").value("13800138000"));

        verify(smsService).verifyCode("13800138000", "123456");
    }

    @Test
    @DisplayName("校验验证码失败 → 200 body success=false")
    void verifyCode_wrongCode_returnsError() throws Exception {
        when(smsService.verifyCode("13800138000", "000000")).thenReturn(false);

        SmsVerifyRequest request = new SmsVerifyRequest();
        request.setPhone("13800138000");
        request.setCode("000000");

        mockMvc.perform(post("/api/auth/sms/verify")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.error.message").isNotEmpty());

        verify(smsService).verifyCode("13800138000", "000000");
    }

    @Test
    @DisplayName("校验验证码 — 空验证码 → 400")
    void verifyCode_emptyCode_returns400() throws Exception {
        mockMvc.perform(post("/api/auth/sms/verify")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"phone\":\"13800138000\",\"code\":\"\"}"))
                .andExpect(status().is4xxClientError());
    }
}
