// case_ids: API-010
package com.migao.admin.service;

import com.migao.admin.dto.LoginRequest;
import com.migao.admin.dto.LoginResponse;
import com.migao.admin.entity.User;
import com.migao.admin.mapper.PlatformAdminMapper;
import com.migao.admin.mapper.TenantMapper;
import com.migao.admin.mapper.UserMapper;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.security.JwtTokenProvider;
import jakarta.servlet.http.HttpServletResponse;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.List;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

/**
 * AuthService 单元测试
 */
@ExtendWith(MockitoExtension.class)
class AuthServiceTest {

    @InjectMocks
    private AuthService authService;

    @Mock
    private UserService userService;

    @Mock
    private RoleService roleService;

    @Mock
    private WechatService wechatService;

    @Mock
    private SmsService smsService;

    @Mock
    private JwtTokenProvider jwtTokenProvider;

    @Mock
    private PasswordEncoder passwordEncoder;

    @Mock
    private StringRedisTemplate redisTemplate;

    @Mock
    private ValueOperations<String, String> valueOperations;

    @Mock
    private PlatformAdminMapper platformAdminMapper;

    @Mock
    private UserMapper userMapper;

    @Mock
    private TenantMapper tenantMapper;

    private User testUser;
    private LoginRequest loginRequest;

    @BeforeEach
    void setUp() {
        // 设置 @Value 字段
        ReflectionTestUtils.setField(authService, "cookieName", "access_token");
        ReflectionTestUtils.setField(authService, "cookieDomain", "");
        ReflectionTestUtils.setField(authService, "cookiePath", "/");
        ReflectionTestUtils.setField(authService, "cookieSecure", true);
        ReflectionTestUtils.setField(authService, "cookieHttpOnly", true);
        ReflectionTestUtils.setField(authService, "cookieSameSite", "strict");

        // 构造测试用户
        testUser = User.builder()
                .id("user-001")
                .tenantId(1L)
                .phone("13800138000")
                .passwordHash("$2a$10$hashedPassword")
                .nickname("测试管理员")
                .avatar("https://example.com/avatar.png")
                .role("admin")
                .status("active")
                .build();

        // 构造登录请求
        loginRequest = new LoginRequest();
        loginRequest.setUsername("13800138000");
        loginRequest.setPassword("password123");
        loginRequest.setTenantId(1L);
    }

    // ======================== 登录测试 ========================

    @Test
    @DisplayName("密码登录已禁用 - 抛出认证异常 (#375)")
    void adminLogin_Disabled() {
        HttpServletResponse response = mock(HttpServletResponse.class);
        assertThatThrownBy(() -> authService.adminLogin(loginRequest, response))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("密码登录已禁用");
    }

    // ======================== Token 刷新测试 ========================

    @Test
    @DisplayName("Token 刷新成功")
    void refreshToken_Success() {
        // Given: 有效的 Refresh Token
        String refreshToken = "valid-refresh-token";
        when(jwtTokenProvider.validateToken(refreshToken)).thenReturn(true);
        when(jwtTokenProvider.isRefreshToken(refreshToken)).thenReturn(true);

        // Mock Claims
        io.jsonwebtoken.Claims mockClaims = mock(io.jsonwebtoken.Claims.class);
        when(mockClaims.getId()).thenReturn("jti-001");
        when(mockClaims.getExpiration()).thenReturn(new java.util.Date(System.currentTimeMillis() + 600000));
        when(jwtTokenProvider.getClaimsFromToken(refreshToken)).thenReturn(mockClaims);

        // Redis 黑名单检查：未吊销
        when(redisTemplate.hasKey("token:blacklist:jti-001")).thenReturn(false);

        when(jwtTokenProvider.getUserIdFromToken(refreshToken)).thenReturn("user-001");
        when(userService.getUserById("user-001")).thenReturn(testUser);
        when(userService.getUserRoles(testUser)).thenReturn(List.of("admin"));
        when(roleService.getUserPermissions("user-001")).thenReturn(List.of("*"));

        when(jwtTokenProvider.generateAccessToken(eq("user-001"), eq(1L), eq("13800138000"), anyList(), anyList()))
                .thenReturn("new-access-token");
        when(jwtTokenProvider.generateRefreshToken("user-001", 1L))
                .thenReturn("new-refresh-token");
        when(jwtTokenProvider.getAccessTokenExpiration()).thenReturn(7200L);

        // 旧 Token 黑名单写入
        when(redisTemplate.opsForValue()).thenReturn(valueOperations);

        HttpServletResponse response = mock(HttpServletResponse.class);

        // When: 刷新 Token
        LoginResponse result = authService.refreshToken(refreshToken, response);

        // Then: 验证新 Token
        assertThat(result).isNotNull();
        assertThat(result.getAccessToken()).isEqualTo("new-access-token");
        assertThat(result.getRefreshToken()).isEqualTo("new-refresh-token");
        assertThat(result.getUser().getId()).isEqualTo("user-001");
    }

    @Test
    @DisplayName("Token 刷新失败 - 无效的 Refresh Token")
    void refreshToken_InvalidToken() {
        // Given: 无效的 Refresh Token
        String refreshToken = "invalid-refresh-token";
        when(jwtTokenProvider.validateToken(refreshToken)).thenReturn(false);

        HttpServletResponse response = mock(HttpServletResponse.class);

        // When & Then: 应抛出异常
        assertThatThrownBy(() -> authService.refreshToken(refreshToken, response))
                .isInstanceOf(BusinessException.class)
                .hasMessage("无效的 Refresh Token");
    }

    @Test
    @DisplayName("Token 刷新失败 - Token 类型不是 Refresh")
    void refreshToken_NotRefreshToken() {
        // Given: Token 有效但不是 Refresh Token
        String accessToken = "access-token";
        when(jwtTokenProvider.validateToken(accessToken)).thenReturn(true);
        when(jwtTokenProvider.isRefreshToken(accessToken)).thenReturn(false);

        HttpServletResponse response = mock(HttpServletResponse.class);

        // When & Then: 应抛出异常
        assertThatThrownBy(() -> authService.refreshToken(accessToken, response))
                .isInstanceOf(BusinessException.class)
                .hasMessage("无效的 Refresh Token");
    }

    @Test
    @DisplayName("Token 刷新失败 - Token 已被吊销")
    void refreshToken_BlacklistedToken() {
        // Given: Token 已在黑名单中
        String refreshToken = "blacklisted-refresh-token";
        when(jwtTokenProvider.validateToken(refreshToken)).thenReturn(true);
        when(jwtTokenProvider.isRefreshToken(refreshToken)).thenReturn(true);

        io.jsonwebtoken.Claims mockClaims = mock(io.jsonwebtoken.Claims.class);
        when(mockClaims.getId()).thenReturn("jti-002");
        when(jwtTokenProvider.getClaimsFromToken(refreshToken)).thenReturn(mockClaims);

        // Redis 返回已存在
        when(redisTemplate.hasKey("token:blacklist:jti-002")).thenReturn(true);

        HttpServletResponse response = mock(HttpServletResponse.class);

        // When & Then: 应抛出已吊销异常
        assertThatThrownBy(() -> authService.refreshToken(refreshToken, response))
                .isInstanceOf(BusinessException.class)
                .hasMessage("Refresh Token 已吊销");
    }

    @Test
    @DisplayName("Token 刷新失败 - 用户不存在")
    void refreshToken_UserNotFound() {
        // Given: Token 有效但用户已被删除
        String refreshToken = "valid-refresh-token";
        when(jwtTokenProvider.validateToken(refreshToken)).thenReturn(true);
        when(jwtTokenProvider.isRefreshToken(refreshToken)).thenReturn(true);

        io.jsonwebtoken.Claims mockClaims = mock(io.jsonwebtoken.Claims.class);
        when(mockClaims.getId()).thenReturn(null); // 无 jti
        when(jwtTokenProvider.getClaimsFromToken(refreshToken)).thenReturn(mockClaims);

        when(jwtTokenProvider.getUserIdFromToken(refreshToken)).thenReturn("user-deleted");
        when(userService.getUserById("user-deleted")).thenReturn(null);

        HttpServletResponse response = mock(HttpServletResponse.class);

        // When & Then: 应抛出用户不存在异常
        assertThatThrownBy(() -> authService.refreshToken(refreshToken, response))
                .isInstanceOf(BusinessException.class)
                .hasMessage("用户不存在");
    }

    // ======================== 登出测试 ========================

    @Test
    @DisplayName("登出 - 成功，Token 加入黑名单并清除 Cookie")
    void logout_Success() {
        // Given: 请求包含有效的 Cookie Token
        jakarta.servlet.http.HttpServletRequest request = mock(jakarta.servlet.http.HttpServletRequest.class);
        HttpServletResponse response = mock(HttpServletResponse.class);

        jakarta.servlet.http.Cookie tokenCookie = new jakarta.servlet.http.Cookie("access_token", "valid-token");
        when(request.getCookies()).thenReturn(new jakarta.servlet.http.Cookie[]{tokenCookie});

        io.jsonwebtoken.Claims mockClaims = mock(io.jsonwebtoken.Claims.class);
        when(mockClaims.getId()).thenReturn("jti-logout");
        when(mockClaims.getExpiration()).thenReturn(new java.util.Date(System.currentTimeMillis() + 600000));
        when(jwtTokenProvider.getClaimsFromToken("valid-token")).thenReturn(mockClaims);

        when(redisTemplate.opsForValue()).thenReturn(valueOperations);

        // When: 登出
        authService.logout(request, response);

        // Then: Token 被加入黑名单
        verify(valueOperations).set(eq("token:blacklist:jti-logout"), eq("1"), any(java.time.Duration.class));
    }

    @Test
    @DisplayName("登出 - 无 Token 时仅清除 Cookie")
    void logout_NoToken() {
        // Given: 请求无 Cookie 无 Authorization header
        jakarta.servlet.http.HttpServletRequest request = mock(jakarta.servlet.http.HttpServletRequest.class);
        HttpServletResponse response = mock(HttpServletResponse.class);

        when(request.getCookies()).thenReturn(null);
        when(request.getHeader("Authorization")).thenReturn(null);

        // When: 登出（不应抛异常）
        authService.logout(request, response);

        // Then: 未尝试操作 Redis
        verify(redisTemplate, never()).opsForValue();
    }

    // ======================== 微信公众号 OAuth 占位实现测试 ========================

    @Test
    @DisplayName("微信 H5 授权 URL 构建 - 抛出未实现异常")
    void buildWechatH5AuthorizeUrl_NotImplemented() {
        assertThatThrownBy(() -> authService.buildWechatH5AuthorizeUrl("tenant123", "https://example.com/callback"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("尚未实现");
    }

    @Test
    @DisplayName("微信 H5 OAuth 回调 - 抛出未实现异常")
    void handleWechatH5Callback_NotImplemented() {
        HttpServletResponse response = mock(HttpServletResponse.class);
        assertThatThrownBy(() -> authService.handleWechatH5Callback("auth-code", "state-123", response))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("尚未实现");
    }

    // ======================== 短信登录 - 同手机号跨租户歧义（审计 07 P1-2） ========================

    @Test
    @DisplayName("短信登录 - 同手机号多租户且未指定租户 → 拒绝（防登录落错租户）")
    void loginBySms_MultiTenantAmbiguity_Rejected() {
        User u1 = User.builder().id("u1").tenantId(1L).phone("13800138000").role("admin").status("active").build();
        User u2 = User.builder().id("u2").tenantId(2L).phone("13800138000").role("admin").status("active").build();

        when(smsService.verifyCode("13800138000", "123456")).thenReturn(true);
        when(platformAdminMapper.selectOne(any())).thenReturn(null);
        when(userMapper.selectActiveUsersByPhoneIgnoreTenant("13800138000")).thenReturn(List.of(u1, u2));

        assertThatThrownBy(() -> authService.loginBySms(
                "13800138000", "123456", null, mock(HttpServletResponse.class)))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("多个租户");
    }

    @Test
    @DisplayName("短信登录 - 多租户时按指定 tenantId 精确匹配")
    void loginBySms_MultiTenant_WithTenantId_SelectsCorrectTenant() {
        User u1 = User.builder().id("u1").tenantId(1L).phone("13800138000").role("admin").status("active").build();
        User u2 = User.builder().id("u2").tenantId(2L).phone("13800138000").role("admin").status("active").build();

        when(smsService.verifyCode("13800138000", "123456")).thenReturn(true);
        when(platformAdminMapper.selectOne(any())).thenReturn(null);
        when(userMapper.selectActiveUsersByPhoneIgnoreTenant("13800138000")).thenReturn(List.of(u1, u2));
        when(jwtTokenProvider.generateAccessToken(anyString(), anyLong(), anyString(), anyList(), anyList()))
                .thenReturn("jwt-token-2");
        when(jwtTokenProvider.generateRefreshToken(anyString(), anyLong())).thenReturn("refresh-token-2");
        when(jwtTokenProvider.getAccessTokenExpiration()).thenReturn(7200L);
        when(userService.getUserRoles(any())).thenReturn(List.of("admin"));
        when(roleService.getUserPermissions(anyString())).thenReturn(List.of("*"));
        when(tenantMapper.selectById(2L)).thenReturn(null); // 租户名查询可空

        LoginResponse resp = authService.loginBySms(
                "13800138000", "123456", 2L, mock(HttpServletResponse.class));

        assertThat(resp.getUser().getId()).isEqualTo("u2");
        verify(userService).getUserRoles(u2);
        // 审计 07 P1-5：登录响应不下发 refresh token（仅 HttpOnly cookie 承载）
        assertThat(resp.getRefreshToken()).isNull();
    }

    @Test
    @DisplayName("短信登录 - 多租户指定不存在的租户 → 拒绝")
    void loginBySms_MultiTenant_WrongTenantId_Rejected() {
        User u1 = User.builder().id("u1").tenantId(1L).phone("13800138000").role("admin").status("active").build();
        User u2 = User.builder().id("u2").tenantId(2L).phone("13800138000").role("admin").status("active").build();

        when(smsService.verifyCode("13800138000", "123456")).thenReturn(true);
        when(platformAdminMapper.selectOne(any())).thenReturn(null);
        when(userMapper.selectActiveUsersByPhoneIgnoreTenant("13800138000")).thenReturn(List.of(u1, u2));

        assertThatThrownBy(() -> authService.loginBySms(
                "13800138000", "123456", 9L, mock(HttpServletResponse.class)))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("未注册");
    }
}
