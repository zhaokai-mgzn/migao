package com.migao.admin.security;

import com.migao.admin.service.RoleService;
import org.aspectj.lang.ProceedingJoinPoint;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContext;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.core.userdetails.User;

import java.util.List;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

/**
 * PermissionInterceptor 单元测试
 * 测试 AOP 权限拦截器的各种场景：
 * - 有权限放行 / 无权限拒绝 / 未认证拒绝 / admin 通配权限
 * - extractUserId 对不同 Principal 类型的处理
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class PermissionInterceptorTest {

    @Mock
    private RoleService roleService;

    @Mock
    private ProceedingJoinPoint joinPoint;

    @Mock
    private Authentication authentication;

    @InjectMocks
    private PermissionInterceptor interceptor;

    private RequirePermission requirePermission;

    @BeforeEach
    void setUp() throws Throwable {
        SecurityContextHolder.clearContext();
        requirePermission = mock(RequirePermission.class);
        when(requirePermission.value()).thenReturn("product:manage");
        when(joinPoint.proceed()).thenReturn("result");
    }

    // ======================== 权限检查通过场景 ========================

    @Test
    @DisplayName("用户拥有所需权限 - 放行并执行目标方法")
    void userHasRequiredPermissionProceeds() throws Throwable {
        SecurityUser securityUser = new SecurityUser("user-001", 1L, "testuser",
                List.of("operator"), List.of(new SimpleGrantedAuthority("ROLE_OPERATOR")));
        when(authentication.isAuthenticated()).thenReturn(true);
        when(authentication.getPrincipal()).thenReturn(securityUser);
        SecurityContext context = SecurityContextHolder.getContext();
        context.setAuthentication(authentication);
        when(roleService.getUserPermissions("user-001"))
                .thenReturn(List.of("product:manage", "dashboard:view"));

        Object result = interceptor.intercept(joinPoint, requirePermission);

        assertThat(result).isEqualTo("result");
        verify(joinPoint).proceed();
        verify(roleService).getUserPermissions("user-001");
    }

    @Test
    @DisplayName("用户拥有 admin 通配权限 * - 放行")
    void userHasAdminWildcardProceeds() throws Throwable {
        SecurityUser securityUser = new SecurityUser("admin-001", 1L, "admin",
                List.of("admin"), List.of(new SimpleGrantedAuthority("ROLE_ADMIN")));
        when(authentication.isAuthenticated()).thenReturn(true);
        when(authentication.getPrincipal()).thenReturn(securityUser);
        SecurityContext context = SecurityContextHolder.getContext();
        context.setAuthentication(authentication);
        when(roleService.getUserPermissions("admin-001")).thenReturn(List.of("*"));

        Object result = interceptor.intercept(joinPoint, requirePermission);

        assertThat(result).isEqualTo("result");
        verify(joinPoint).proceed();
    }

    // ======================== 权限拒绝场景 ========================

    @Test
    @DisplayName("用户缺少所需权限 - 抛出 AccessDeniedException")
    void userMissingPermissionThrowsAccessDenied() throws Throwable {
        SecurityUser securityUser = new SecurityUser("user-001", 1L, "viewer",
                List.of("viewer"), List.of(new SimpleGrantedAuthority("ROLE_VIEWER")));
        when(authentication.isAuthenticated()).thenReturn(true);
        when(authentication.getPrincipal()).thenReturn(securityUser);
        SecurityContext context = SecurityContextHolder.getContext();
        context.setAuthentication(authentication);
        when(roleService.getUserPermissions("user-001"))
                .thenReturn(List.of("dashboard:view"));

        assertThatThrownBy(() -> interceptor.intercept(joinPoint, requirePermission))
                .isInstanceOf(AccessDeniedException.class)
                .hasMessageContaining("权限不足")
                .hasMessageContaining("product:manage");

        verify(joinPoint, never()).proceed();
    }

    @Test
    @DisplayName("用户权限列表为空 - 抛出 AccessDeniedException")
    void userHasEmptyPermissionsThrowsAccessDenied() throws Throwable {
        SecurityUser securityUser = new SecurityUser("user-001", 1L, "newuser",
                List.of(), List.of());
        when(authentication.isAuthenticated()).thenReturn(true);
        when(authentication.getPrincipal()).thenReturn(securityUser);
        SecurityContext context = SecurityContextHolder.getContext();
        context.setAuthentication(authentication);
        when(roleService.getUserPermissions("user-001")).thenReturn(List.of());

        assertThatThrownBy(() -> interceptor.intercept(joinPoint, requirePermission))
                .isInstanceOf(AccessDeniedException.class)
                .hasMessageContaining("权限不足");

        verify(joinPoint, never()).proceed();
    }

    // ======================== 认证状态异常场景 ========================

    @Test
    @DisplayName("认证信息为 null - 抛出 AccessDeniedException 未认证")
    void authenticationNullThrowsAccessDenied() throws Throwable {
        SecurityContext context = SecurityContextHolder.getContext();
        context.setAuthentication(null);

        assertThatThrownBy(() -> interceptor.intercept(joinPoint, requirePermission))
                .isInstanceOf(AccessDeniedException.class)
                .hasMessageContaining("用户未认证");

        verify(joinPoint, never()).proceed();
        verifyNoInteractions(roleService);
    }

    @Test
    @DisplayName("认证未通过 isAuthenticated false - 抛出 AccessDeniedException")
    void authenticationNotAuthenticatedThrowsAccessDenied() throws Throwable {
        when(authentication.isAuthenticated()).thenReturn(false);
        SecurityContext context = SecurityContextHolder.getContext();
        context.setAuthentication(authentication);

        assertThatThrownBy(() -> interceptor.intercept(joinPoint, requirePermission))
                .isInstanceOf(AccessDeniedException.class)
                .hasMessageContaining("用户未认证");

        verify(joinPoint, never()).proceed();
        verifyNoInteractions(roleService);
    }

    // ======================== extractUserId 对不同 Principal 类型 ========================

    @Test
    @DisplayName("Principal 是 SecurityUser - 提取 getUserId")
    void extractUserIdSecurityUserReturnsUserId() throws Throwable {
        SecurityUser securityUser = new SecurityUser("security-001", 2L, "secuser",
                List.of("admin"), List.of(new SimpleGrantedAuthority("ROLE_ADMIN")));
        when(authentication.isAuthenticated()).thenReturn(true);
        when(authentication.getPrincipal()).thenReturn(securityUser);
        SecurityContext context = SecurityContextHolder.getContext();
        context.setAuthentication(authentication);
        when(roleService.getUserPermissions("security-001")).thenReturn(List.of("*"));

        interceptor.intercept(joinPoint, requirePermission);

        verify(roleService).getUserPermissions("security-001");
    }

    @Test
    @DisplayName("Principal 是 Spring User - 提取 getUsername 作为 userId")
    void extractUserIdSpringUserReturnsUsername() throws Throwable {
        User springUser = new User("spring-user-001", "password",
                List.of(new SimpleGrantedAuthority("ROLE_ADMIN")));
        when(authentication.isAuthenticated()).thenReturn(true);
        when(authentication.getPrincipal()).thenReturn(springUser);
        SecurityContext context = SecurityContextHolder.getContext();
        context.setAuthentication(authentication);
        when(roleService.getUserPermissions("spring-user-001")).thenReturn(List.of("*"));

        interceptor.intercept(joinPoint, requirePermission);

        verify(roleService).getUserPermissions("spring-user-001");
    }

    @Test
    @DisplayName("Principal 类型未知 - extractUserId 返回 null 抛出 AccessDeniedException")
    void extractUserIdUnknownPrincipalThrowsAccessDenied() throws Throwable {
        when(authentication.isAuthenticated()).thenReturn(true);
        when(authentication.getPrincipal()).thenReturn("unknown-principal");
        SecurityContext context = SecurityContextHolder.getContext();
        context.setAuthentication(authentication);

        assertThatThrownBy(() -> interceptor.intercept(joinPoint, requirePermission))
                .isInstanceOf(AccessDeniedException.class)
                .hasMessageContaining("无法获取用户信息");

        verify(joinPoint, never()).proceed();
        verifyNoInteractions(roleService);
    }
}
