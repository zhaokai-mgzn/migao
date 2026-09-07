package com.migao.admin.config;
// case_ids: CU-006

import jakarta.servlet.http.HttpServletRequest;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.Optional;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

/**
 * TenantDomainResolver 单元测试（issue #3011）
 * C 端租户域名路由：X-Tenant-Id（nginx 注入）优先，Host 子域兜底。
 */
@ExtendWith(MockitoExtension.class)
class TenantDomainResolverTest {

    @Mock
    private HttpServletRequest request;

    private TenantDomainResolver resolver;

    @BeforeEach
    void setUp() {
        resolver = new TenantDomainResolver();
    }

    @Test
    @DisplayName("X-Tenant-Id 头优先于 Host")
    void resolve_HeaderWinsOverHost() {
        when(request.getHeader("X-Tenant-Id")).thenReturn("5");

        Optional<Long> result = resolver.resolve(request);

        assertThat(result).contains(5L);
        verify(request, never()).getServerName();
    }

    @Test
    @DisplayName("无头时解析 Host 子域名")
    void resolve_HostSubdomain() {
        when(request.getHeader("X-Tenant-Id")).thenReturn(null);
        when(request.getServerName()).thenReturn("12.app.migaozn.com");

        Optional<Long> result = resolver.resolve(request);

        assertThat(result).contains(12L);
    }

    @Test
    @DisplayName("Host 非租户子域名 → empty（统一域名 app.migaozn.com / 其他域）")
    void resolve_HostNotTenantSubdomain() {
        when(request.getHeader("X-Tenant-Id")).thenReturn(null);
        when(request.getServerName()).thenReturn("app.migaozn.com");

        Optional<Long> result = resolver.resolve(request);

        assertThat(result).isEmpty();
    }

    @Test
    @DisplayName("非法 X-Tenant-Id（非纯数字）不信任，继续走 Host")
    void resolve_InvalidHeaderFallsBackToHost() {
        when(request.getHeader("X-Tenant-Id")).thenReturn("abc");
        when(request.getServerName()).thenReturn("7.app.migaozn.com");

        Optional<Long> result = resolver.resolve(request);

        assertThat(result).contains(7L);
    }

    @Test
    @DisplayName("均无租户信息 → empty")
    void resolve_Nothing() {
        when(request.getHeader("X-Tenant-Id")).thenReturn(null);
        when(request.getServerName()).thenReturn("api.migaozn.com");

        Optional<Long> result = resolver.resolve(request);

        assertThat(result).isEmpty();
    }
}