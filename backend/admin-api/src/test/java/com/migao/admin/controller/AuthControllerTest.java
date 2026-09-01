package com.migao.admin.controller;
// case_ids: API-010

import com.migao.admin.config.GlobalExceptionHandler;
import com.migao.admin.dto.LoginResponse;
import com.migao.admin.dto.SmsLoginRequest;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.service.AuthService;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

/**
 * AuthController 认证端点测试（审计 07 P1-5：refresh 优先从 HttpOnly cookie 读取）
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("AuthController 认证端点测试")
class AuthControllerTest {

    private MockMvc mockMvc;
    private final ObjectMapper objectMapper = new ObjectMapper();

    @Mock
    private AuthService authService;

    @InjectMocks
    private AuthController authController;

    @BeforeEach
    void setUp() {
        mockMvc = MockMvcBuilders.standaloneSetup(authController)
                .setControllerAdvice(new GlobalExceptionHandler())
                .build();
    }

    @Test
    @DisplayName("refresh - 从 HttpOnly refresh_token cookie 读取（审计 07 P1-5）")
    void refreshToken_FromCookie() throws Exception {
        LoginResponse resp = LoginResponse.builder().accessToken("new-access").build();
        when(authService.refreshToken(eq("cookie-refresh-token"), any()))
                .thenReturn(resp);

        mockMvc.perform(post("/api/auth/refresh")
                        .cookie(new jakarta.servlet.http.Cookie("refresh_token", "cookie-refresh-token"))
                        .contentType("application/json")
                        .content("{}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.accessToken").value("new-access"));

        verify(authService).refreshToken(eq("cookie-refresh-token"), any());
    }

    @Test
    @DisplayName("refresh - 无 cookie 且 body 无 refreshToken → 认证失败")
    void refreshToken_Missing_Rejected() throws Exception {
        mockMvc.perform(post("/api/auth/refresh")
                        .contentType("application/json")
                        .content("{}"))
                .andExpect(status().isUnauthorized());
        verify(authService, never()).refreshToken(anyString(), any());
    }

    @Test
    @DisplayName("refresh - body 传参兼容旧客户端")
    void refreshToken_FromBody() throws Exception {
        LoginResponse resp = LoginResponse.builder().accessToken("new-access").build();
        when(authService.refreshToken(eq("body-refresh-token"), any())).thenReturn(resp);

        mockMvc.perform(post("/api/auth/refresh")
                        .contentType("application/json")
                        .content("{\"refreshToken\":\"body-refresh-token\"}"))
                .andExpect(status().isOk());

        verify(authService).refreshToken(eq("body-refresh-token"), any());
    }

    @Test
    @DisplayName("smsLogin - 透传可选 tenantId（审计 07 P1-2）")
    void smsLogin_PassesTenantId() throws Exception {
        LoginResponse resp = LoginResponse.builder().accessToken("at").build();
        when(authService.loginBySms(eq("13800138000"), eq("123456"), eq(2L), any())).thenReturn(resp);

        mockMvc.perform(post("/api/auth/sms/login")
                        .contentType("application/json")
                        .content("{\"phone\":\"13800138000\",\"code\":\"123456\",\"tenantId\":2}"))
                .andExpect(status().isOk());

        verify(authService).loginBySms(eq("13800138000"), eq("123456"), eq(2L), any());
    }

    @Test
    @DisplayName("smsLogin - tenantId 缺省传 null")
    void smsLogin_NoTenantId() throws Exception {
        LoginResponse resp = LoginResponse.builder().accessToken("at").build();
        when(authService.loginBySms(eq("13800138000"), eq("123456"), isNull(), any())).thenReturn(resp);

        mockMvc.perform(post("/api/auth/sms/login")
                        .contentType("application/json")
                        .content("{\"phone\":\"13800138000\",\"code\":\"123456\"}"))
                .andExpect(status().isOk());

        verify(authService).loginBySms(eq("13800138000"), eq("123456"), isNull(), any());
    }
}
