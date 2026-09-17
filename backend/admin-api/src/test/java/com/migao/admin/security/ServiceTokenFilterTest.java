// case_ids: OR-001, DF-002, DF-014, DF-017
package com.migao.admin.security;

import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.User;
import com.migao.admin.mapper.UserMapper;
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
import org.mockito.Mock;
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
 * - X-User-Id 命中同租户商户员工时不再挂 service 旁路（issue #4105 F2）
 */
@ExtendWith(MockitoExtension.class)
class ServiceTokenFilterTest {

    @Mock
    private UserMapper userMapper;

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
    @DisplayName("有效 Service Token + X-User-Id — 透传真实用户 ID（C 端数据隔离依据）")
    void validServiceToken_WithXUserId_PassthroughRealUser() throws ServletException, IOException {
        when(request.getHeader(HEADER_NAME)).thenReturn(SECRET);
        when(request.getHeader("X-Tenant-Id")).thenReturn("5");
        when(request.getHeader("X-User-Id")).thenReturn("customer-007");

        filter.doFilterInternal(request, response, filterChain);

        verify(filterChain).doFilter(request, response);

        Authentication auth = SecurityContextHolder.getContext().getAuthentication();
        assertThat(auth).isNotNull();
        SecurityUser user = (SecurityUser) auth.getPrincipal();
        // 关键：userId 必须是真实用户而非 internal-service 占位
        assertThat(user.getUserId()).isEqualTo("customer-007");
        assertThat(user.getTenantId()).isEqualTo(5L);
    }

    // ======================== X-User-Id 商户员工判定（issue #4105 F2）========================
    // 背景：ai-agent 调用 admin-api **始终**带 X-Service-Token，本过滤器此前一律挂 "service" 身份，
    // 于是 PermissionInterceptor.hasBypassRole() 与 SecurityConfig.adminApiAuthorizationManager()
    // 双双直接放行 ⇒ /api/admin/**（含全部写接口）零细粒度授权。
    // 目标：X-User-Id 命中**同租户商户员工**时挂该用户真实角色（不再挂 service），
    // 细粒度授权交 PermissionInterceptor + roleService.getUserPermissions(realUserId)。
    // 其余四种情形（无 X-User-Id / C 端角色 / 跨租户 / 查不到）必须与今日行为**逐字节一致**。

    @Test
    @DisplayName("X-User-Id 命中同租户商户员工 — 挂真实角色，service 旁路消失（负向控制）")
    void merchantStaffXUserId_realRolesWithoutServiceBypass() throws ServletException, IOException {
        when(request.getHeader(HEADER_NAME)).thenReturn(SECRET);
        when(request.getHeader("X-Tenant-Id")).thenReturn("5");
        when(request.getHeader("X-User-Id")).thenReturn("staff-001");
        when(userMapper.selectById("staff-001")).thenReturn(staff("staff-001", 5L, "operator", "active"));

        filter.doFilterInternal(request, response, filterChain);

        verify(filterChain).doFilter(request, response);
        Authentication auth = SecurityContextHolder.getContext().getAuthentication();
        SecurityUser user = (SecurityUser) auth.getPrincipal();
        assertThat(user.getUserId()).isEqualTo("staff-001");
        assertThat(user.getTenantId()).isEqualTo(5L);
        assertThat(user.getRoles()).containsExactly("operator");
        // 承重判据：旁路角色必须消失，否则 PermissionInterceptor 仍然整段跳过权限查询
        assertThat(auth.getAuthorities()).extracting("authority")
                .contains("ROLE_OPERATOR")
                .doesNotContain("ROLE_SERVICE", "ROLE_INTERNAL");
    }

    @org.junit.jupiter.params.ParameterizedTest(name = "X-User-Id 角色 {0} — 保持既有 service 透传")
    @org.junit.jupiter.params.provider.ValueSource(strings = {"customer", "agent"})
    @DisplayName("X-User-Id 命中 C 端角色（customer/agent）— 行为与今日逐字节一致（零回归）")
    void cEndXUserId_keepsLegacyServiceIdentity(String role) throws ServletException, IOException {
        when(request.getHeader(HEADER_NAME)).thenReturn(SECRET);
        when(request.getHeader("X-Tenant-Id")).thenReturn("5");
        when(request.getHeader("X-User-Id")).thenReturn("c-user-007");
        when(userMapper.selectById("c-user-007")).thenReturn(staff("c-user-007", 5L, role, "active"));

        filter.doFilterInternal(request, response, filterChain);

        Authentication auth = SecurityContextHolder.getContext().getAuthentication();
        SecurityUser user = (SecurityUser) auth.getPrincipal();
        // 真实 userId 仍透传（C 端数据隔离依据），身份仍是内部服务 ⇒ C 端端点照旧可用
        assertThat(user.getUserId()).isEqualTo("c-user-007");
        assertThat(user.getRoles()).containsExactly("service");
        assertThat(auth.getAuthorities()).extracting("authority")
                .containsExactlyInAnyOrder("ROLE_SERVICE", "ROLE_INTERNAL");
    }

    @Test
    @DisplayName("无 X-User-Id — 不查库、行为与今日逐字节一致（零回归）")
    void noXUserId_keepsLegacyServiceIdentityAndSkipsLookup() throws ServletException, IOException {
        when(request.getHeader(HEADER_NAME)).thenReturn(SECRET);
        when(request.getHeader("X-Tenant-Id")).thenReturn("5");
        when(request.getHeader("X-User-Id")).thenReturn(null);

        filter.doFilterInternal(request, response, filterChain);

        Authentication auth = SecurityContextHolder.getContext().getAuthentication();
        SecurityUser user = (SecurityUser) auth.getPrincipal();
        assertThat(user.getUserId()).isEqualTo("internal-service");
        assertThat(auth.getAuthorities()).extracting("authority")
                .containsExactlyInAnyOrder("ROLE_SERVICE", "ROLE_INTERNAL");
        verifyNoInteractions(userMapper);
    }

    @Test
    @DisplayName("X-User-Id 命中**跨租户**商户员工 — 不认作本租户员工，保持今日行为（零回归）")
    void crossTenantStaffXUserId_keepsLegacyServiceIdentity() throws ServletException, IOException {
        when(request.getHeader(HEADER_NAME)).thenReturn(SECRET);
        when(request.getHeader("X-Tenant-Id")).thenReturn("5");
        when(request.getHeader("X-User-Id")).thenReturn("staff-other-tenant");
        when(userMapper.selectById("staff-other-tenant"))
                .thenReturn(staff("staff-other-tenant", 99L, "operator", "active"));

        filter.doFilterInternal(request, response, filterChain);

        Authentication auth = SecurityContextHolder.getContext().getAuthentication();
        assertThat(((SecurityUser) auth.getPrincipal()).getRoles()).containsExactly("service");
        assertThat(auth.getAuthorities()).extracting("authority")
                .containsExactlyInAnyOrder("ROLE_SERVICE", "ROLE_INTERNAL");
    }

    @Test
    @DisplayName("X-User-Id 查不到用户 — 保持今日行为（零回归）")
    void unresolvableXUserId_keepsLegacyServiceIdentity() throws ServletException, IOException {
        when(request.getHeader(HEADER_NAME)).thenReturn(SECRET);
        when(request.getHeader("X-Tenant-Id")).thenReturn("5");
        when(request.getHeader("X-User-Id")).thenReturn("ghost-user");
        when(userMapper.selectById("ghost-user")).thenReturn(null);

        filter.doFilterInternal(request, response, filterChain);

        Authentication auth = SecurityContextHolder.getContext().getAuthentication();
        assertThat(((SecurityUser) auth.getPrincipal()).getRoles()).containsExactly("service");
        assertThat(auth.getAuthorities()).extracting("authority")
                .containsExactlyInAnyOrder("ROLE_SERVICE", "ROLE_INTERNAL");
    }

    @Test
    @DisplayName("X-User-Id 命中非 active 商户员工 — 不认作员工，保持今日行为（零回归）")
    void inactiveStaffXUserId_keepsLegacyServiceIdentity() throws ServletException, IOException {
        when(request.getHeader(HEADER_NAME)).thenReturn(SECRET);
        when(request.getHeader("X-Tenant-Id")).thenReturn("5");
        when(request.getHeader("X-User-Id")).thenReturn("staff-disabled");
        when(userMapper.selectById("staff-disabled"))
                .thenReturn(staff("staff-disabled", 5L, "operator", "disabled"));

        filter.doFilterInternal(request, response, filterChain);

        Authentication auth = SecurityContextHolder.getContext().getAuthentication();
        assertThat(((SecurityUser) auth.getPrincipal()).getRoles()).containsExactly("service");
        assertThat(auth.getAuthorities()).extracting("authority")
                .containsExactlyInAnyOrder("ROLE_SERVICE", "ROLE_INTERNAL");
    }

    @Test
    @DisplayName("X-User-Id 命中无角色用户 — 不认作员工，保持今日行为（零回归）")
    void rolelessXUserId_keepsLegacyServiceIdentity() throws ServletException, IOException {
        when(request.getHeader(HEADER_NAME)).thenReturn(SECRET);
        when(request.getHeader("X-Tenant-Id")).thenReturn("5");
        when(request.getHeader("X-User-Id")).thenReturn("user-no-role");
        when(userMapper.selectById("user-no-role")).thenReturn(staff("user-no-role", 5L, null, "active"));

        filter.doFilterInternal(request, response, filterChain);

        Authentication auth = SecurityContextHolder.getContext().getAuthentication();
        assertThat(((SecurityUser) auth.getPrincipal()).getRoles()).containsExactly("service");
        assertThat(auth.getAuthorities()).extracting("authority")
                .containsExactlyInAnyOrder("ROLE_SERVICE", "ROLE_INTERNAL");
    }

    @Test
    @DisplayName("商户员工查库抛异常 — 回退内部服务身份（不 500、不提权给不可信方）+ 记 ERROR 留痕")
    void staffLookupThrows_fallsBackToServiceIdentityWithErrorLog() throws ServletException, IOException {
        when(request.getHeader(HEADER_NAME)).thenReturn(SECRET);
        when(request.getHeader("X-Tenant-Id")).thenReturn("5");
        when(request.getHeader("X-User-Id")).thenReturn("staff-boom");
        when(userMapper.selectById("staff-boom")).thenThrow(new RuntimeException("db down"));

        ch.qos.logback.classic.Logger filterLogger =
                (ch.qos.logback.classic.Logger) org.slf4j.LoggerFactory.getLogger(ServiceTokenFilter.class);
        ch.qos.logback.core.read.ListAppender<ch.qos.logback.classic.spi.ILoggingEvent> appender =
                new ch.qos.logback.core.read.ListAppender<>();
        appender.start();
        filterLogger.addAppender(appender);
        try {
            filter.doFilterInternal(request, response, filterChain);

            // 决策（issue #4105）：调用方已持有可信 SERVICE_TOKEN，查库失败时回退今日行为，
            // 但**必须**留 ERROR 痕迹，避免「查失败」与「查不到」无从区分。
            assertThat(appender.list).anySatisfy(event -> {
                assertThat(event.getLevel()).isEqualTo(ch.qos.logback.classic.Level.ERROR);
                assertThat(event.getFormattedMessage()).contains("staff-boom");
            });
            Authentication auth = SecurityContextHolder.getContext().getAuthentication();
            assertThat(((SecurityUser) auth.getPrincipal()).getRoles()).containsExactly("service");
            assertThat(auth.getAuthorities()).extracting("authority")
                    .containsExactlyInAnyOrder("ROLE_SERVICE", "ROLE_INTERNAL");
            verify(filterChain).doFilter(request, response);
        } finally {
            filterLogger.detachAppender(appender);
        }
    }

    @Test
    @DisplayName("查库判定必须在 TenantContext 就绪之后 — 否则租户插件抛错被 fallback 吞掉（修复静默失效）")
    void merchantStaffLookup_runsAfterTenantContextIsSet() throws ServletException, IOException {
        // 为什么断言「查库那一刻的 TenantContext」：真实 UserMapper 是 MyBatis-Plus 代理，
        // users **不在** MybatisPlusConfig.IGNORE_TENANT_TABLES 内 ⇒ TenantLineHandler.getTenantId()
        // 在 TenantContext 为空时抛 "Tenant context not initialized - possible unauthenticated access"。
        // 该异常会被 resolveMerchantStaff 的 catch 吞成 fallback ⇒ 只留一条 ERROR 日志、
        // F2 在**生产**完全失效，而 mock UserMapper 的单测/E2E 全绿 —— 典型静默失效形态。
        when(request.getHeader(HEADER_NAME)).thenReturn(SECRET);
        when(request.getHeader("X-Tenant-Id")).thenReturn("5");
        when(request.getHeader("X-User-Id")).thenReturn("staff-001");
        java.util.List<Long> tenantSeenByMapper = new java.util.ArrayList<>();
        when(userMapper.selectById("staff-001")).thenAnswer(invocation -> {
            tenantSeenByMapper.add(TenantContext.getTenantId());
            return staff("staff-001", 5L, "operator", "active");
        });

        filter.doFilterInternal(request, response, filterChain);

        assertThat(tenantSeenByMapper).containsExactly(5L);
        Authentication auth = SecurityContextHolder.getContext().getAuthentication();
        assertThat(auth.getAuthorities()).extracting("authority").contains("ROLE_OPERATOR");
        assertThat(TenantContext.getTenantId()).isNull();
    }

    private static User staff(String id, Long tenantId, String role, String status) {
        return User.builder()
                .id(id)
                .tenantId(tenantId)
                .role(role)
                .status(status)
                .deleted(0)
                .build();
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
