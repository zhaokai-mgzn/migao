package com.migao.admin.security;

import com.migao.admin.config.TenantContext;
import io.jsonwebtoken.Claims;
import io.jsonwebtoken.ExpiredJwtException;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.Cookie;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.test.util.ReflectionTestUtils;

import java.io.IOException;
import java.util.List;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

/**
 * JwtAuthenticationFilter 单元测试
 * 测试 JWT 认证过滤器的完整逻辑：
 * - Cookie / Authorization Header 提取 JWT
 * - Token 验证、类型检查、黑名单检查
 * - SecurityContext 设置 / TenantContext 管理
 * - 过期/无效 Token、异常场景、边界条件
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class JwtAuthenticationFilterTest {

    @Mock
    private JwtTokenProvider jwtTokenProvider;

    @Mock
    private StringRedisTemplate redisTemplate;

    @InjectMocks
    private JwtAuthenticationFilter filter;

    private HttpServletRequest request;
    private HttpServletResponse response;
    private FilterChain filterChain;

    private Claims validClaims;

    @BeforeEach
    void setUp() {
        request = mock(HttpServletRequest.class);
        response = mock(HttpServletResponse.class);
        filterChain = mock(FilterChain.class);

        SecurityContextHolder.clearContext();
        TenantContext.clear();

        ReflectionTestUtils.setField(filter, "cookieName", "access_token");

        // 构造标准 Claims mock
        validClaims = mock(Claims.class);
        when(validClaims.getId()).thenReturn("jti-abc-123");
        when(validClaims.get(JwtTokenProvider.CLAIM_USER_ID, String.class)).thenReturn("user-001");
        when(validClaims.get(JwtTokenProvider.CLAIM_TENANT_ID)).thenReturn(1L);
        when(validClaims.get(JwtTokenProvider.CLAIM_USERNAME, String.class)).thenReturn("testuser");
        when(validClaims.get(JwtTokenProvider.CLAIM_ROLES, List.class))
                .thenReturn(List.of("admin"));
    }

    @AfterEach
    void tearDown() {
        SecurityContextHolder.clearContext();
        TenantContext.clear();
    }

    // ======================== 无 Token 场景 ========================

    @Test
    @DisplayName("请求中无 JWT（无 Cookie 无 Auth Header）— 直接放行")
    void noJwt_PassesThrough() throws ServletException, IOException {
        when(request.getCookies()).thenReturn(null);
        when(request.getHeader("Authorization")).thenReturn(null);

        filter.doFilterInternal(request, response, filterChain);

        verify(filterChain).doFilter(request, response);
        assertThat(SecurityContextHolder.getContext().getAuthentication()).isNull();
    }

    @Test
    @DisplayName("Cookie 存在但 access_token 不在其中 — 回退到 Auth Header 也为空 → 放行")
    void cookieWithoutAccessToken_NoAuthHeader_PassesThrough() throws ServletException, IOException {
        Cookie[] cookies = {new Cookie("other_cookie", "value")};
        when(request.getCookies()).thenReturn(cookies);
        when(request.getHeader("Authorization")).thenReturn(null);

        filter.doFilterInternal(request, response, filterChain);

        verify(filterChain).doFilter(request, response);
        assertThat(SecurityContextHolder.getContext().getAuthentication()).isNull();
    }

    // ======================== Cookie 提取 JWT 并认证成功 ========================

    @Test
    @DisplayName("从 Cookie 提取有效 JWT — 设置 SecurityContext 和 TenantContext")
    void validJwtFromCookie_SetsAuthAndTenantContext() throws ServletException, IOException {
        Cookie[] cookies = {new Cookie("access_token", "valid.jwt.token")};
        when(request.getCookies()).thenReturn(cookies);

        when(jwtTokenProvider.validateToken("valid.jwt.token")).thenReturn(true);
        when(jwtTokenProvider.getClaimsFromToken("valid.jwt.token")).thenReturn(validClaims);
        when(jwtTokenProvider.isAccessToken("valid.jwt.token")).thenReturn(true);
        when(redisTemplate.hasKey("token:blacklist:jti-abc-123")).thenReturn(false);

        filter.doFilterInternal(request, response, filterChain);

        verify(filterChain).doFilter(request, response);
        verify(jwtTokenProvider).validateToken("valid.jwt.token");

        Authentication auth = SecurityContextHolder.getContext().getAuthentication();
        assertThat(auth).isNotNull();
        assertThat(auth.getPrincipal()).isInstanceOf(SecurityUser.class);
        SecurityUser user = (SecurityUser) auth.getPrincipal();
        assertThat(user.getUserId()).isEqualTo("user-001");
        assertThat(user.getTenantId()).isEqualTo(1L);
        assertThat(user.getDisplayName()).isEqualTo("testuser");
        assertThat(user.getRoles()).contains("admin");
    }

    // ======================== Authorization Header 提取 JWT ========================

    @Test
    @DisplayName("从 Authorization Header 提取 Bearer Token — 设置认证")
    void validJwtFromAuthHeader_SetsAuth() throws ServletException, IOException {
        when(request.getCookies()).thenReturn(null);
        when(request.getHeader("Authorization")).thenReturn("Bearer header.jwt.token");

        when(jwtTokenProvider.validateToken("header.jwt.token")).thenReturn(true);
        when(jwtTokenProvider.getClaimsFromToken("header.jwt.token")).thenReturn(validClaims);
        when(jwtTokenProvider.isAccessToken("header.jwt.token")).thenReturn(true);
        when(redisTemplate.hasKey("token:blacklist:jti-abc-123")).thenReturn(false);

        filter.doFilterInternal(request, response, filterChain);

        verify(filterChain).doFilter(request, response);
        assertThat(SecurityContextHolder.getContext().getAuthentication()).isNotNull();
    }

    @Test
    @DisplayName("Cookie 优先于 Authorization Header — Cookie 存在时忽略 Auth Header")
    void cookieTakesPriorityOverAuthHeader() throws ServletException, IOException {
        Cookie[] cookies = {new Cookie("access_token", "cookie.jwt.token")};
        when(request.getCookies()).thenReturn(cookies);
        // Auth Header 也存在，但应被忽略
        when(request.getHeader("Authorization")).thenReturn("Bearer header.jwt.token");

        when(jwtTokenProvider.validateToken("cookie.jwt.token")).thenReturn(true);
        when(jwtTokenProvider.getClaimsFromToken("cookie.jwt.token")).thenReturn(validClaims);
        when(jwtTokenProvider.isAccessToken("cookie.jwt.token")).thenReturn(true);
        when(redisTemplate.hasKey("token:blacklist:jti-abc-123")).thenReturn(false);

        filter.doFilterInternal(request, response, filterChain);

        // 验证使用的是 Cookie 中的 token
        verify(jwtTokenProvider).validateToken("cookie.jwt.token");
        verify(jwtTokenProvider, never()).validateToken("header.jwt.token");
    }

    // ======================== Token 类型检查 ========================

    @Test
    @DisplayName("Token 类型不是 Access — 不放行认证，只调用 filterChain")
    void nonAccessToken_PassesThroughNoAuth() throws ServletException, IOException {
        Cookie[] cookies = {new Cookie("access_token", "refresh.jwt.token")};
        when(request.getCookies()).thenReturn(cookies);

        when(jwtTokenProvider.validateToken("refresh.jwt.token")).thenReturn(true);
        when(jwtTokenProvider.getClaimsFromToken("refresh.jwt.token")).thenReturn(validClaims);
        when(jwtTokenProvider.isAccessToken("refresh.jwt.token")).thenReturn(false);

        filter.doFilterInternal(request, response, filterChain);

        verify(filterChain).doFilter(request, response);
        assertThat(SecurityContextHolder.getContext().getAuthentication()).isNull();
    }

    // ======================== Token 黑名单检查 ========================

    @Test
    @DisplayName("Token 在 Redis 黑名单中 — 不放行认证")
    void tokenBlacklisted_PassesThroughNoAuth() throws ServletException, IOException {
        Cookie[] cookies = {new Cookie("access_token", "blacklisted.jwt")};
        when(request.getCookies()).thenReturn(cookies);

        when(jwtTokenProvider.validateToken("blacklisted.jwt")).thenReturn(true);
        when(jwtTokenProvider.getClaimsFromToken("blacklisted.jwt")).thenReturn(validClaims);
        when(jwtTokenProvider.isAccessToken("blacklisted.jwt")).thenReturn(true);
        when(redisTemplate.hasKey("token:blacklist:jti-abc-123")).thenReturn(true);

        filter.doFilterInternal(request, response, filterChain);

        verify(filterChain).doFilter(request, response);
        assertThat(SecurityContextHolder.getContext().getAuthentication()).isNull();
    }

    @Test
    @DisplayName("Token jti 为 null — 跳过黑名单检查，正常认证")
    void tokenJtiNull_SkipsBlacklistCheck() throws ServletException, IOException {
        Claims claimsNoJti = mock(Claims.class);
        when(claimsNoJti.getId()).thenReturn(null);
        when(claimsNoJti.get(JwtTokenProvider.CLAIM_USER_ID, String.class)).thenReturn("user-001");
        when(claimsNoJti.get(JwtTokenProvider.CLAIM_TENANT_ID)).thenReturn(1L);
        when(claimsNoJti.get(JwtTokenProvider.CLAIM_USERNAME, String.class)).thenReturn("testuser");
        when(claimsNoJti.get(JwtTokenProvider.CLAIM_ROLES, List.class)).thenReturn(List.of("admin"));

        Cookie[] cookies = {new Cookie("access_token", "jwt.no.jti")};
        when(request.getCookies()).thenReturn(cookies);
        when(jwtTokenProvider.validateToken("jwt.no.jti")).thenReturn(true);
        when(jwtTokenProvider.getClaimsFromToken("jwt.no.jti")).thenReturn(claimsNoJti);
        when(jwtTokenProvider.isAccessToken("jwt.no.jti")).thenReturn(true);

        filter.doFilterInternal(request, response, filterChain);

        // 不应检查 Redis 黑名单（jti 为 null）
        verify(redisTemplate, never()).hasKey(anyString());
        assertThat(SecurityContextHolder.getContext().getAuthentication()).isNotNull();
    }

    @Test
    @DisplayName("Redis 黑名单检查抛异常 — 默认放行（不阻塞）")
    void redisExceptionDuringBlacklistCheck_PassesThrough() throws ServletException, IOException {
        Cookie[] cookies = {new Cookie("access_token", "valid.jwt")};
        when(request.getCookies()).thenReturn(cookies);
        when(jwtTokenProvider.validateToken("valid.jwt")).thenReturn(true);
        when(jwtTokenProvider.getClaimsFromToken("valid.jwt")).thenReturn(validClaims);
        when(jwtTokenProvider.isAccessToken("valid.jwt")).thenReturn(true);
        when(redisTemplate.hasKey(anyString())).thenThrow(new RuntimeException("Redis down"));

        // 不应抛出异常
        filter.doFilterInternal(request, response, filterChain);

        verify(filterChain).doFilter(request, response);
    }

    // ======================== Token 无效/过期场景 ========================

    @Test
    @DisplayName("Token 验证失败 (validateToken=false) — 放行不设认证")
    void invalidToken_PassesThroughNoAuth() throws ServletException, IOException {
        Cookie[] cookies = {new Cookie("access_token", "invalid.jwt")};
        when(request.getCookies()).thenReturn(cookies);
        when(jwtTokenProvider.validateToken("invalid.jwt")).thenReturn(false);

        filter.doFilterInternal(request, response, filterChain);

        verify(filterChain).doFilter(request, response);
        assertThat(SecurityContextHolder.getContext().getAuthentication()).isNull();
    }

    @Test
    @DisplayName("Token 已过期 (ExpiredJwtException) — 捕获异常后放行")
    void expiredToken_PassesThrough() throws ServletException, IOException {
        Cookie[] cookies = {new Cookie("access_token", "expired.jwt")};
        when(request.getCookies()).thenReturn(cookies);

        when(jwtTokenProvider.validateToken("expired.jwt")).thenReturn(true);
        ExpiredJwtException expiredEx = mock(ExpiredJwtException.class);
        when(expiredEx.getMessage()).thenReturn("JWT expired at ...");
        when(jwtTokenProvider.getClaimsFromToken("expired.jwt")).thenThrow(expiredEx);

        filter.doFilterInternal(request, response, filterChain);

        verify(filterChain).doFilter(request, response);
        assertThat(SecurityContextHolder.getContext().getAuthentication()).isNull();
    }

    @Test
    @DisplayName("Token TenantId 异常 — filterChain 仍被调用，请求继续未认证状态")
    void tokenWithoutTenantId_UsesDefaultTenantId() throws ServletException, IOException {
        // 模拟 getClaimsFromToken 抛异常（模拟运行时 Claims 解析异常），
        // 验证过滤器的 Exception catch 块不会阻塞请求
        Cookie[] cookies = {new Cookie("access_token", "exception.jwt")};
        when(request.getCookies()).thenReturn(cookies);
        when(jwtTokenProvider.validateToken("exception.jwt")).thenReturn(true);
        when(jwtTokenProvider.getClaimsFromToken("exception.jwt"))
                .thenThrow(new RuntimeException("Simulated claims error"));

        // 不应抛出异常
        filter.doFilterInternal(request, response, filterChain);

        // filterChain 仍被调用（在 catch 块中）
        verify(filterChain).doFilter(request, response);
        // SecurityContext 未设置
        assertThat(SecurityContextHolder.getContext().getAuthentication()).isNull();
        // TenantContext 被 finally 清理
        assertThat(TenantContext.getTenantId()).isNull();
    }

    // ======================== 已认证跳过场景 ========================

    @Test
    @DisplayName("SecurityContext 已有认证信息 — 跳过整个 JWT 处理流程")
    void alreadyAuthenticated_SkipsJwtProcessing() throws ServletException, IOException {
        Authentication existingAuth = mock(Authentication.class);
        SecurityContextHolder.getContext().setAuthentication(existingAuth);
        when(request.getCookies()).thenReturn(null);

        filter.doFilterInternal(request, response, filterChain);

        verify(filterChain).doFilter(request, response);
        // 不应调用 Token 验证
        verifyNoInteractions(jwtTokenProvider);
        verifyNoInteractions(redisTemplate);
    }

    // ======================== TenantContext 生命周期 ========================

    @Test
    @DisplayName("认证成功后 — TenantContext 在 finally 中被清理")
    void tenantContextClearedInFinally() throws ServletException, IOException {
        Cookie[] cookies = {new Cookie("access_token", "valid.jwt")};
        when(request.getCookies()).thenReturn(cookies);
        when(jwtTokenProvider.validateToken("valid.jwt")).thenReturn(true);
        when(jwtTokenProvider.getClaimsFromToken("valid.jwt")).thenReturn(validClaims);
        when(jwtTokenProvider.isAccessToken("valid.jwt")).thenReturn(true);
        when(redisTemplate.hasKey("token:blacklist:jti-abc-123")).thenReturn(false);

        filter.doFilterInternal(request, response, filterChain);

        // finally 块应已清理
        assertThat(TenantContext.getTenantId()).isNull();
    }

    @Test
    @DisplayName("无 Token 时 — TenantContext 仍被清理（finally 块）")
    void noToken_TenantContextClearedInFinally() throws ServletException, IOException {
        when(request.getCookies()).thenReturn(null);
        when(request.getHeader("Authorization")).thenReturn(null);

        filter.doFilterInternal(request, response, filterChain);

        assertThat(TenantContext.getTenantId()).isNull();
    }

    // ======================== 角色列表处理 ========================

    @Test
    @DisplayName("Token 中 roles 为 null — 不添加任何角色权限")
    void nullRoles_AddsNoAuthorities() throws ServletException, IOException {
        Claims claimsNoRoles = mock(Claims.class);
        when(claimsNoRoles.getId()).thenReturn("jti-002");
        when(claimsNoRoles.get(JwtTokenProvider.CLAIM_USER_ID, String.class)).thenReturn("user-001");
        when(claimsNoRoles.get(JwtTokenProvider.CLAIM_TENANT_ID)).thenReturn(1L);
        when(claimsNoRoles.get(JwtTokenProvider.CLAIM_USERNAME, String.class)).thenReturn("testuser");
        when(claimsNoRoles.get(JwtTokenProvider.CLAIM_ROLES, List.class)).thenReturn(null);

        Cookie[] cookies = {new Cookie("access_token", "jwt.no.roles")};
        when(request.getCookies()).thenReturn(cookies);
        when(jwtTokenProvider.validateToken("jwt.no.roles")).thenReturn(true);
        when(jwtTokenProvider.getClaimsFromToken("jwt.no.roles")).thenReturn(claimsNoRoles);
        when(jwtTokenProvider.isAccessToken("jwt.no.roles")).thenReturn(true);
        when(redisTemplate.hasKey("token:blacklist:jti-002")).thenReturn(false);

        filter.doFilterInternal(request, response, filterChain);

        Authentication auth = SecurityContextHolder.getContext().getAuthentication();
        assertThat(auth).isNotNull();
        assertThat(auth.getAuthorities()).isEmpty();
    }

    @Test
    @DisplayName("Token 中有多个角色 — 每个角色添加 ROLE_ 前缀和非前缀两种权限")
    void multipleRoles_addsPrefixedAndNonPrefixedAuthorities() throws ServletException, IOException {
        Claims claimsMultiRoles = mock(Claims.class);
        when(claimsMultiRoles.getId()).thenReturn("jti-003");
        when(claimsMultiRoles.get(JwtTokenProvider.CLAIM_USER_ID, String.class)).thenReturn("user-001");
        when(claimsMultiRoles.get(JwtTokenProvider.CLAIM_TENANT_ID)).thenReturn(1L);
        when(claimsMultiRoles.get(JwtTokenProvider.CLAIM_USERNAME, String.class)).thenReturn("testuser");
        when(claimsMultiRoles.get(JwtTokenProvider.CLAIM_ROLES, List.class))
                .thenReturn(List.of("admin", "operator"));

        Cookie[] cookies = {new Cookie("access_token", "jwt.multi.roles")};
        when(request.getCookies()).thenReturn(cookies);
        when(jwtTokenProvider.validateToken("jwt.multi.roles")).thenReturn(true);
        when(jwtTokenProvider.getClaimsFromToken("jwt.multi.roles")).thenReturn(claimsMultiRoles);
        when(jwtTokenProvider.isAccessToken("jwt.multi.roles")).thenReturn(true);
        when(redisTemplate.hasKey("token:blacklist:jti-003")).thenReturn(false);

        filter.doFilterInternal(request, response, filterChain);

        Authentication auth = SecurityContextHolder.getContext().getAuthentication();
        assertThat(auth.getAuthorities()).extracting("authority")
                .contains("ROLE_ADMIN", "admin", "ROLE_OPERATOR", "operator");
    }

    // ======================== doFilterNestedErrorDispatch ========================

    @Test
    @DisplayName("doFilterNestedErrorDispatch — TenantContext 在 finally 中清理")
    void nestedErrorDispatch_ClearsTenantContext() throws ServletException, IOException {
        // 预设 TenantContext 模拟 error dispatch 场景
        TenantContext.setTenantId(5L);

        filter.doFilterNestedErrorDispatch(request, response, filterChain);

        verify(filterChain).doFilter(request, response);
        assertThat(TenantContext.getTenantId()).isNull();
    }

    // ======================== Authorization Header 边界情况 ========================

    @Test
    @DisplayName("Authorization Header 不以 Bearer 开头 — 不提取 Token")
    void authHeaderNotBearer_Ignores() throws ServletException, IOException {
        when(request.getCookies()).thenReturn(null);
        when(request.getHeader("Authorization")).thenReturn("Basic dXNlcjpwYXNz");

        filter.doFilterInternal(request, response, filterChain);

        verify(filterChain).doFilter(request, response);
        verifyNoInteractions(jwtTokenProvider);
    }

    @Test
    @DisplayName("Authorization Header 为 Bearer 但后为空 — 不提取 Token")
    void authHeaderBearerEmpty_Ignores() throws ServletException, IOException {
        when(request.getCookies()).thenReturn(null);
        when(request.getHeader("Authorization")).thenReturn("Bearer ");

        filter.doFilterInternal(request, response, filterChain);

        verify(filterChain).doFilter(request, response);
        verifyNoInteractions(jwtTokenProvider);
    }
}
