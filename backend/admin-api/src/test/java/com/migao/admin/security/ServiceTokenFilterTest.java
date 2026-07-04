package com.migao.admin.security;

import com.migao.admin.config.TenantContext;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.PrintWriter;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.test.util.ReflectionTestUtils;

import java.io.IOException;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

/**
 * ServiceTokenFilter 单元测试
 * 测试内部服务 Token 认证过滤器：
 * - 有效/无效 Service Token 的处理
 * - Secret 未配置 / X-Tenant-Id 解析 / shouldNotFilter 路径匹配
 * - SecurityContext 设置 / TenantContext 清理
 */
@ExtendWith(MockitoExtension.class)
class ServiceTokenFilterTest {

    @InjectMocks
    private ServiceTokenFilter filter;

    private HttpServletRequest request;
    private HttpServletResponse response;
    private FilterChain filterChain;

    private static final String SECRET = "shared-service-secret";
    private static final String HEADER_NAME = "X-Service-Token";

    @BeforeEach
    void setUp() {
        request = mock(HttpServletRequest.class);
        response = mock(HttpServletResponse.class);
        filterChain = mock(FilterChain.class);

        SecurityContextHolder.clearContext();
        TenantContext.clear();

        // 设置 @Value 字段
        ReflectionTestUtils.setField(filter, "serviceTokenHeader", HEADER_NAME);
        ReflectionTestUtils.setField(filter, "serviceTokenSecret", SECRET);
    }

    @AfterEach
    void tearDown() {
        SecurityContextHolder.clearContext();
        TenantContext.clear();
    }

    // ======================== 有效 Token 场景 ========================

    @Test
    @DisplayName("有效 Service Token — 设置 SecurityContext 为内部服务身份")
    void validServiceToken_SetsInternalServiceAuth() throws ServletException, IOException {
        when(request.getHeader(HEADER_NAME)).thenReturn(SECRET);
        when(request.getHeader("X-Tenant-Id")).thenReturn("5");

        filter.doFilterInternal(request, response, filterChain);

        verify(filterChain).doFilter(request, response);

        Authentication auth = SecurityContextHolder.getContext().getAuthentication();
        assertThat(auth).isNotNull();
        assertThat(auth.getPrincipal()).isInstanceOf(SecurityUser.class);
        SecurityUser user = (SecurityUser) auth.getPrincipal();
        assertThat(user.getUserId()).isEqualTo("internal-service");
        assertThat(user.getTenantId()).isEqualTo(5L);
        assertThat(auth.getAuthorities()).extracting("authority")
                .contains("ROLE_SERVICE", "ROLE_INTERNAL");
    }

    @Test
    @DisplayName("有效 Service Token — 无 X-Tenant-Id 时返回 400")
    void validToken_NoTenantIdHeader_UsesDefaultTenantId() throws ServletException, IOException {
        when(request.getHeader(HEADER_NAME)).thenReturn(SECRET);
        when(request.getHeader("X-Tenant-Id")).thenReturn(null);
        PrintWriter writer = mock(PrintWriter.class);
        when(response.getWriter()).thenReturn(writer);

        filter.doFilterInternal(request, response, filterChain);

        verify(response).setStatus(HttpServletResponse.SC_BAD_REQUEST);
        verify(filterChain, never()).doFilter(request, response);
        assertThat(SecurityContextHolder.getContext().getAuthentication()).isNull();
    }

    @Test
    @DisplayName("有效 Service Token — X-Tenant-Id 为空字符串时返回 400")
    void validToken_EmptyTenantIdHeader_UsesDefault() throws ServletException, IOException {
        when(request.getHeader(HEADER_NAME)).thenReturn(SECRET);
        when(request.getHeader("X-Tenant-Id")).thenReturn("");
        PrintWriter writer = mock(PrintWriter.class);
        when(response.getWriter()).thenReturn(writer);

        filter.doFilterInternal(request, response, filterChain);

        verify(response).setStatus(HttpServletResponse.SC_BAD_REQUEST);
        verify(filterChain, never()).doFilter(request, response);
        assertThat(SecurityContextHolder.getContext().getAuthentication()).isNull();
    }

    @Test
    @DisplayName("有效 Service Token — X-Tenant-Id 为非数字时返回 400")
    void validToken_NonNumericTenantId_UsesDefault() throws ServletException, IOException {
        when(request.getHeader(HEADER_NAME)).thenReturn(SECRET);
        when(request.getHeader("X-Tenant-Id")).thenReturn("not-a-number");
        PrintWriter writer = mock(PrintWriter.class);
        when(response.getWriter()).thenReturn(writer);

        filter.doFilterInternal(request, response, filterChain);

        verify(response).setStatus(HttpServletResponse.SC_BAD_REQUEST);
        verify(filterChain, never()).doFilter(request, response);
        assertThat(SecurityContextHolder.getContext().getAuthentication()).isNull();
    }

    // ======================== 无效 / 缺失 Token 场景 ========================

    @Test
    @DisplayName("无 Service Token 头 — 直接放行不设认证")
    void noServiceTokenHeader_PassesThrough() throws ServletException, IOException {
        when(request.getHeader(HEADER_NAME)).thenReturn(null);

        filter.doFilterInternal(request, response, filterChain);

        verify(filterChain).doFilter(request, response);
        assertThat(SecurityContextHolder.getContext().getAuthentication()).isNull();
    }

    @Test
    @DisplayName("Service Token 头为空字符串 — 直接放行")
    void emptyServiceTokenHeader_PassesThrough() throws ServletException, IOException {
        when(request.getHeader(HEADER_NAME)).thenReturn("");

        filter.doFilterInternal(request, response, filterChain);

        verify(filterChain).doFilter(request, response);
        assertThat(SecurityContextHolder.getContext().getAuthentication()).isNull();
    }

    @Test
    @DisplayName("错误的 Service Token — 直接放行不设认证")
    void wrongServiceToken_PassesThroughWithoutAuth() throws ServletException, IOException {
        when(request.getHeader(HEADER_NAME)).thenReturn("wrong-secret");

        filter.doFilterInternal(request, response, filterChain);

        verify(filterChain).doFilter(request, response);
        assertThat(SecurityContextHolder.getContext().getAuthentication()).isNull();
    }

    @Test
    @DisplayName("Service Token Secret 未配置 — 拒绝所有 Service Token 认证")
    void secretNotConfigured_RejectsAll() throws ServletException, IOException {
        ReflectionTestUtils.setField(filter, "serviceTokenSecret", "");
        when(request.getHeader(HEADER_NAME)).thenReturn("any-token");

        filter.doFilterInternal(request, response, filterChain);

        verify(filterChain).doFilter(request, response);
        assertThat(SecurityContextHolder.getContext().getAuthentication()).isNull();
    }

    @Test
    @DisplayName("Service Token Secret 为 null — 拒绝所有 Service Token 认证")
    void secretNull_RejectsAll() throws ServletException, IOException {
        ReflectionTestUtils.setField(filter, "serviceTokenSecret", null);
        when(request.getHeader(HEADER_NAME)).thenReturn("any-token");

        filter.doFilterInternal(request, response, filterChain);

        verify(filterChain).doFilter(request, response);
        assertThat(SecurityContextHolder.getContext().getAuthentication()).isNull();
    }

    // ======================== 已认证跳过场景 ========================

    @Test
    @DisplayName("SecurityContext 已有认证信息 — 跳过 Service Token 处理")
    void alreadyAuthenticated_SkipsServiceTokenCheck() throws ServletException, IOException {
        // 预设已认证状态
        Authentication existingAuth = mock(Authentication.class);
        SecurityContextHolder.getContext().setAuthentication(existingAuth);
        when(request.getHeader(HEADER_NAME)).thenReturn(SECRET);

        filter.doFilterInternal(request, response, filterChain);

        verify(filterChain).doFilter(request, response);
        // 认证信息应保持不变
        assertThat(SecurityContextHolder.getContext().getAuthentication())
                .isSameAs(existingAuth);
        verify(request, never()).getHeader("X-Tenant-Id");
    }

    // ======================== TenantContext 清理 ========================

    @Test
    @DisplayName("认证成功后 — TenantContext 在 finally 中被清理")
    void validToken_TenantContextClearedInFinally() throws ServletException, IOException {
        when(request.getHeader(HEADER_NAME)).thenReturn(SECRET);
        when(request.getHeader("X-Tenant-Id")).thenReturn("10");

        filter.doFilterInternal(request, response, filterChain);

        // finally 块应已清理 TenantContext
        assertThat(TenantContext.getTenantId()).isNull();
    }

    @Test
    @DisplayName("认证失败时 — TenantContext 不被设置，无需清理（不抛异常）")
    void invalidToken_TenantContextNotSet() throws ServletException, IOException {
        when(request.getHeader(HEADER_NAME)).thenReturn("bad-token");

        filter.doFilterInternal(request, response, filterChain);

        assertThat(TenantContext.getTenantId()).isNull();
        verify(filterChain).doFilter(request, response);
    }

    // ======================== shouldNotFilter 路径匹配 ========================

    @Test
    @DisplayName("shouldNotFilter — /api/internal/ 路径启用过滤器（不跳过）")
    void shouldNotFilter_InternalPath_ReturnsFalse() {
        when(request.getRequestURI()).thenReturn("/api/internal/sync");

        assertThat(filter.shouldNotFilter(request)).isFalse();
    }

    @Test
    @DisplayName("shouldNotFilter — /api/admin/ 路径启用过滤器（不跳过）")
    void shouldNotFilter_AdminPath_ReturnsFalse() {
        when(request.getRequestURI()).thenReturn("/api/admin/products");

        assertThat(filter.shouldNotFilter(request)).isFalse();
    }

    @Test
    @DisplayName("shouldNotFilter — 其他路径跳过过滤器（返回 true）")
    void shouldNotFilter_OtherPath_ReturnsTrue() {
        when(request.getRequestURI()).thenReturn("/api/public/health");

        assertThat(filter.shouldNotFilter(request)).isTrue();
    }

    @Test
    @DisplayName("shouldNotFilter — 根路径跳过过滤器")
    void shouldNotFilter_RootPath_ReturnsTrue() {
        when(request.getRequestURI()).thenReturn("/");

        assertThat(filter.shouldNotFilter(request)).isTrue();
    }

    // ======================== 异常不阻塞请求 ========================

    @Test
    @DisplayName("认证过程抛异常 — 不阻塞请求，filterChain 仍被调用")
    void exceptionDuringAuth_PassesThrough() throws ServletException, IOException {
        when(request.getHeader(HEADER_NAME)).thenThrow(new RuntimeException("header error"));

        filter.doFilterInternal(request, response, filterChain);

        // 即使抛异常，filterChain 仍被调用
        verify(filterChain).doFilter(request, response);
        assertThat(SecurityContextHolder.getContext().getAuthentication()).isNull();
    }
}
