package com.migao.admin.controller;
// case_ids: API-010, AU-014

import com.migao.admin.config.GlobalExceptionHandler;
import com.migao.admin.dto.LoginResponse;
import com.migao.admin.dto.SmsLoginRequest;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.security.SecurityUser;
import com.migao.admin.service.AuthService;
import com.migao.admin.service.MiniPhoneBindService;
import com.migao.admin.service.QrLoginTicketService;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.util.List;

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

    @Mock
    private MiniPhoneBindService miniPhoneBindService;

    @Mock
    private QrLoginTicketService qrLoginTicketService;

    @InjectMocks
    private AuthController authController;

    @BeforeEach
    void setUp() {
        mockMvc = MockMvcBuilders.standaloneSetup(authController)
                .setControllerAdvice(new GlobalExceptionHandler())
                .build();
    }

    /** 模拟 JWT 认证用户（小程序 customer） */
    private void setMiniCustomerAuth() {
        SecurityUser user = new SecurityUser(
                "user-mini-001", 1L, "微信用户",
                List.of("customer"),
                List.of(new SimpleGrantedAuthority("ROLE_customer"))
        );
        Authentication auth = mock(Authentication.class);
        when(auth.getPrincipal()).thenReturn(user);
        SecurityContextHolder.getContext().setAuthentication(auth);
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

    @Test
    @DisplayName("bind-phone - 已登录小程序客户授权手机号 → 换号并回填名下订单")
    void bindPhone_AuthenticatedCustomer_Binds() throws Exception {
        setMiniCustomerAuth();
        MiniPhoneBindService.BindResult result = new MiniPhoneBindService.BindResult();
        result.setPhone("13900139000");
        result.setBoundOrders(2);
        when(miniPhoneBindService.bind(eq("user-mini-001"), eq(1L), eq("wx-phone-code")))
                .thenReturn(result);

        mockMvc.perform(post("/api/auth/mini/bind-phone")
                        .contentType("application/json")
                        .content("{\"code\":\"wx-phone-code\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.phone").value("13900139000"))
                .andExpect(jsonPath("$.data.boundOrders").value(2));

        verify(miniPhoneBindService).bind(eq("user-mini-001"), eq(1L), eq("wx-phone-code"));
    }

    @Test
    @DisplayName("bind-phone - 未登录 → 401")
    void bindPhone_Unauthenticated_Rejected() throws Exception {
        SecurityContextHolder.clearContext();

        mockMvc.perform(post("/api/auth/mini/bind-phone")
                        .contentType("application/json")
                        .content("{\"code\":\"wx-phone-code\"}"))
                .andExpect(status().is4xxClientError());

        verify(miniPhoneBindService, never()).bind(anyString(), anyLong(), anyString());
    }

    @Test
    @DisplayName("bind-phone - code 为空 → 400（参数校验，未进入业务层）")
    void bindPhone_EmptyCode_Rejected() throws Exception {
        mockMvc.perform(post("/api/auth/mini/bind-phone")
                        .contentType("application/json")
                        .content("{}"))
                .andExpect(status().is4xxClientError());

        verify(miniPhoneBindService, never()).bind(anyString(), anyLong(), anyString());
    }

    // ==================== 扫码即登录（issue #7825） ====================

    /** 模拟商家员工会话（签发二维码票据需要已登录）。 */
    private void setMerchantAuth() {
        SecurityUser user = new SecurityUser(
                "user-1", 2L, "13800000000",
                List.of("admin"),
                List.of(new SimpleGrantedAuthority("ROLE_admin"))
        );
        Authentication auth = mock(Authentication.class);
        when(auth.getPrincipal()).thenReturn(user);
        SecurityContextHolder.getContext().setAuthentication(auth);
    }

    @Test
    @DisplayName("qr/ticket - 已登录 ⇒ 返回票据与有效期（前端据此画二维码）")
    void qrTicket_ok() throws Exception {
        setMerchantAuth();
        when(qrLoginTicketService.issue("user-1", 2L))
                .thenReturn(new QrLoginTicketService.Ticket("ticket-abc", 120L));

        mockMvc.perform(post("/api/auth/qr/ticket"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.ticket").value("ticket-abc"))
                .andExpect(jsonPath("$.data.expiresIn").value(120));
    }

    @Test
    @DisplayName("qr/ticket - 未登录 ⇒ 401（签发 = 替当前用户发持有凭证，不能匿名）")
    void qrTicket_requiresAuth() throws Exception {
        SecurityContextHolder.clearContext();

        mockMvc.perform(post("/api/auth/qr/ticket"))
                .andExpect(status().isUnauthorized());
    }

    @Test
    @DisplayName("qr/exchange - 票据有效 ⇒ 返回登录响应（与密码登录同形）")
    void qrExchange_ok() throws Exception {
        when(qrLoginTicketService.consume("ticket-abc"))
                .thenReturn(new QrLoginTicketService.Identity("user-1", 2L));
        when(authService.loginByQrTicket(eq("user-1"), eq(2L), any()))
                .thenReturn(LoginResponse.builder().accessToken("new-access").expiresIn(7200L).build());

        mockMvc.perform(post("/api/auth/qr/exchange")
                        .contentType("application/json")
                        .content("{\"ticket\":\"ticket-abc\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.accessToken").value("new-access"));
    }

    @Test
    @DisplayName("qr/exchange - 票据无效/已用/过期 ⇒ 401 + 同一句文案（不区分细节）")
    void qrExchange_invalid() throws Exception {
        when(qrLoginTicketService.consume("bad"))
                .thenThrow(BusinessException.authFailed(AuthService.QR_TICKET_INVALID_MESSAGE));

        mockMvc.perform(post("/api/auth/qr/exchange")
                        .contentType("application/json")
                        .content("{\"ticket\":\"bad\"}"))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.error.message").value(AuthService.QR_TICKET_INVALID_MESSAGE));
    }
}
