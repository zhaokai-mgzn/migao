package com.aikf.admin.controller;

import com.aikf.admin.config.GlobalExceptionHandler;
import com.aikf.admin.dto.LoginRequest;
import com.aikf.admin.dto.LoginResponse;
import com.aikf.admin.dto.UserInfoResponse;
import com.aikf.admin.exception.BusinessException;
import com.aikf.admin.service.AuthService;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.servlet.http.Cookie;
import jakarta.servlet.http.HttpServletResponse;
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

import java.util.List;

import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

/**
 * 认证控制器集成测试
 * 覆盖：登录、登出、Token 刷新、获取用户信息、小程序登录
 */
@ExtendWith(MockitoExtension.class)
class AuthIntegrationTest {

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

    // ======================== 登录测试 ========================

    @Test
    @DisplayName("账号密码登录成功 - 返回 Token 和用户信息")
    void testAccountLoginSuccess() throws Exception {
        // Given
        LoginResponse loginResponse = LoginResponse.builder()
                .accessToken("jwt-access-token")
                .refreshToken("jwt-refresh-token")
                .expiresIn(7200L)
                .user(LoginResponse.UserInfo.builder()
                        .id("user-001")
                        .nickname("管理员")
                        .avatar("https://example.com/avatar.png")
                        .role("admin")
                        .identityType("account")
                        .roles(List.of("admin"))
                        .build())
                .build();

        when(authService.adminLogin(any(LoginRequest.class), any(HttpServletResponse.class)))
                .thenReturn(loginResponse);

        LoginRequest request = new LoginRequest();
        request.setUsername("admin");
        request.setPassword("password123");
        request.setTenantId(1L);

        // When & Then
        mockMvc.perform(post("/api/auth/admin/login")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.accessToken").value("jwt-access-token"))
                .andExpect(jsonPath("$.data.refreshToken").value("jwt-refresh-token"))
                .andExpect(jsonPath("$.data.expiresIn").value(7200))
                .andExpect(jsonPath("$.data.user.id").value("user-001"))
                .andExpect(jsonPath("$.data.user.nickname").value("管理员"))
                .andExpect(jsonPath("$.data.user.role").value("admin"));

        verify(authService).adminLogin(any(LoginRequest.class), any(HttpServletResponse.class));
    }

    @Test
    @DisplayName("密码错误 - 返回 401 认证失败")
    void testAccountLoginInvalidPassword() throws Exception {
        // Given
        when(authService.adminLogin(any(LoginRequest.class), any(HttpServletResponse.class)))
                .thenThrow(BusinessException.authFailed("用户名或密码错误"));

        LoginRequest request = new LoginRequest();
        request.setUsername("admin");
        request.setPassword("wrong-password");
        request.setTenantId(1L);

        // When & Then
        mockMvc.perform(post("/api/auth/admin/login")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.error.code").value("AUTH_FAILED"));
    }

    @Test
    @DisplayName("用户不存在 - 返回 401 认证失败")
    void testAccountLoginNonExistentUser() throws Exception {
        // Given
        when(authService.adminLogin(any(LoginRequest.class), any(HttpServletResponse.class)))
                .thenThrow(BusinessException.authFailed("用户不存在"));

        LoginRequest request = new LoginRequest();
        request.setUsername("nonexistent");
        request.setPassword("password123");
        request.setTenantId(1L);

        // When & Then
        mockMvc.perform(post("/api/auth/admin/login")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.error.code").value("AUTH_FAILED"))
                .andExpect(jsonPath("$.error.message").value("用户不存在"));
    }

    // ======================== Token 刷新测试 ========================

    @Test
    @DisplayName("Token 刷新成功 - 返回新的 Token")
    void testTokenRefreshSuccess() throws Exception {
        // Given
        LoginResponse refreshed = LoginResponse.builder()
                .accessToken("new-access-token")
                .refreshToken("new-refresh-token")
                .expiresIn(7200L)
                .user(LoginResponse.UserInfo.builder()
                        .id("user-001")
                        .nickname("管理员")
                        .role("admin")
                        .identityType("account")
                        .roles(List.of("admin"))
                        .build())
                .build();

        when(authService.refreshToken(eq("valid-refresh-token"), any(HttpServletResponse.class)))
                .thenReturn(refreshed);

        // When & Then
        mockMvc.perform(post("/api/auth/refresh")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"refreshToken\":\"valid-refresh-token\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.accessToken").value("new-access-token"))
                .andExpect(jsonPath("$.data.refreshToken").value("new-refresh-token"));
    }

    @Test
    @DisplayName("过期 Token 刷新失败 - 返回 401")
    void testTokenRefreshWithExpiredToken() throws Exception {
        // Given
        when(authService.refreshToken(eq("expired-refresh-token"), any(HttpServletResponse.class)))
                .thenThrow(BusinessException.authFailed("刷新 Token 已过期"));

        // When & Then
        mockMvc.perform(post("/api/auth/refresh")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"refreshToken\":\"expired-refresh-token\"}"))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.error.code").value("AUTH_FAILED"));
    }

    // ======================== 登出测试 ========================

    @Test
    @DisplayName("登出成功 - 清除 Cookie")
    void testLogoutClearsCookie() throws Exception {
        // Given
        doNothing().when(authService).logout(any(), any());

        // When & Then
        mockMvc.perform(post("/api/auth/logout")
                        .cookie(new Cookie("access_token", "jwt-token"))
                        .contentType(MediaType.APPLICATION_JSON))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true));

        verify(authService).logout(any(), any());
    }

    // ======================== 获取当前用户信息测试 ========================

    @Test
    @DisplayName("获取当前用户信息 - 返回用户详情")
    void testGetCurrentUserInfo() throws Exception {
        // Given
        UserInfoResponse userInfo = UserInfoResponse.builder()
                .user(UserInfoResponse.UserInfo.builder()
                        .id("user-001")
                        .username("13800138000")
                        .nickname("管理员")
                        .avatar("https://example.com/avatar.png")
                        .tenantId(1L)
                        .status("active")
                        .build())
                .roles(List.of("admin"))
                .permissions(List.of("product:read", "product:write", "order:read"))
                .menus(List.of(
                        UserInfoResponse.MenuItem.builder()
                                .key("dashboard")
                                .name("仪表盘")
                                .icon("LayoutDashboard")
                                .path("/dashboard")
                                .build()))
                .build();

        when(authService.getCurrentUser()).thenReturn(userInfo);

        // When & Then
        mockMvc.perform(get("/api/auth/me")
                        .contentType(MediaType.APPLICATION_JSON))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.user.id").value("user-001"))
                .andExpect(jsonPath("$.data.user.nickname").value("管理员"))
                .andExpect(jsonPath("$.data.roles[0]").value("admin"))
                .andExpect(jsonPath("$.data.permissions").isArray())
                .andExpect(jsonPath("$.data.menus[0].key").value("dashboard"));
    }

    // ======================== 小程序登录测试 ========================

    @Test
    @DisplayName("小程序登录成功 - mock 微信 API 返回 Token")
    void testMiniProgramLogin() throws Exception {
        // Given
        LoginResponse miniLoginResponse = LoginResponse.builder()
                .accessToken("mini-jwt-token")
                .refreshToken("mini-refresh-token")
                .expiresIn(7200L)
                .user(LoginResponse.UserInfo.builder()
                        .id("user-mini-001")
                        .nickname("微信用户")
                        .role("customer")
                        .identityType("wechat_mini")
                        .roles(List.of("customer"))
                        .build())
                .build();

        when(authService.miniProgramLogin(eq("wx-login-code"), eq(1L), any(HttpServletResponse.class)))
                .thenReturn(miniLoginResponse);

        // When & Then
        mockMvc.perform(post("/api/auth/mini/login")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"code\":\"wx-login-code\",\"tenantId\":1}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.accessToken").value("mini-jwt-token"))
                .andExpect(jsonPath("$.data.user.id").value("user-mini-001"))
                .andExpect(jsonPath("$.data.user.identityType").value("wechat_mini"));

        verify(authService).miniProgramLogin(eq("wx-login-code"), eq(1L), any(HttpServletResponse.class));
    }
}
