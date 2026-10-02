// case_ids: DF-007
package com.migao.admin.security;

import com.migao.admin.exception.PermissionDeniedException;
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

        Object result = interceptor.doIntercept(joinPoint, requirePermission);

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

        Object result = interceptor.doIntercept(joinPoint, requirePermission);

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

        assertThatThrownBy(() -> interceptor.doIntercept(joinPoint, requirePermission))
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

        assertThatThrownBy(() -> interceptor.doIntercept(joinPoint, requirePermission))
                .isInstanceOf(AccessDeniedException.class)
                .hasMessageContaining("权限不足");

        verify(joinPoint, never()).proceed();
    }

    @Test
    @DisplayName("权限码结构化存活 - 拒绝异常为 PermissionDeniedException 且携带 requiredPermission（issue #4105 F1）")
    void userMissingPermission_throwsPermissionDeniedCarryingCode() throws Throwable {
        // 背景：旧实现抛裸 AccessDeniedException，权限码只活在 message 字符串里，
        // 下游（GlobalExceptionHandler）只能解析文本；此处断言权限码是**结构化字段**。
        SecurityUser securityUser = new SecurityUser("user-002", 1L, "viewer",
                List.of("viewer"), List.of(new SimpleGrantedAuthority("ROLE_VIEWER")));
        when(authentication.isAuthenticated()).thenReturn(true);
        when(authentication.getPrincipal()).thenReturn(securityUser);
        SecurityContext context = SecurityContextHolder.getContext();
        context.setAuthentication(authentication);
        when(roleService.getUserPermissions("user-002"))
                .thenReturn(List.of("dashboard:view"));

        Throwable thrown = catchThrowable(() -> interceptor.doIntercept(joinPoint, requirePermission));

        assertThat(thrown).isInstanceOf(PermissionDeniedException.class);
        assertThat(((PermissionDeniedException) thrown).getRequiredPermission())
                .isEqualTo("product:manage");
        assertThat(thrown).hasMessageContaining("product:manage");
        verify(joinPoint, never()).proceed();
    }

    // ======================== 认证状态异常场景 ========================

    @Test
    @DisplayName("认证信息为 null - 抛出 AccessDeniedException 未认证")
    void authenticationNullThrowsAccessDenied() throws Throwable {
        SecurityContext context = SecurityContextHolder.getContext();
        context.setAuthentication(null);

        assertThatThrownBy(() -> interceptor.doIntercept(joinPoint, requirePermission))
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

        assertThatThrownBy(() -> interceptor.doIntercept(joinPoint, requirePermission))
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

        interceptor.doIntercept(joinPoint, requirePermission);

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

        interceptor.doIntercept(joinPoint, requirePermission);

        verify(roleService).getUserPermissions("spring-user-001");
    }

    @Test
    @DisplayName("Principal 类型未知 - extractUserId 返回 null 抛出 AccessDeniedException")
    void extractUserIdUnknownPrincipalThrowsAccessDenied() throws Throwable {
        when(authentication.isAuthenticated()).thenReturn(true);
        when(authentication.getPrincipal()).thenReturn("unknown-principal");
        SecurityContext context = SecurityContextHolder.getContext();
        context.setAuthentication(authentication);

        assertThatThrownBy(() -> interceptor.doIntercept(joinPoint, requirePermission))
                .isInstanceOf(AccessDeniedException.class)
                .hasMessageContaining("无法获取用户信息");

        verify(joinPoint, never()).proceed();
        verifyNoInteractions(roleService);
    }

    // ======================== 平台管理员/内部服务直通场景 ========================
    // super_admin（platform_admins 表，不在 users 表）与 service（内部服务）不做细粒度权限查询，
    // 直接放行。修复：此前 getUserPermissions(platformAdminId) 返回空集导致平台管理员 403。

    @Test
    @DisplayName("super_admin 角色 - 跳过权限查询直接放行")
    void superAdminBypassesPermissionQuery() throws Throwable {
        SecurityUser securityUser = new SecurityUser("pa-001", -1L, "platform-admin",
                List.of("super_admin"), List.of(new SimpleGrantedAuthority("ROLE_SUPER_ADMIN")));
        when(authentication.isAuthenticated()).thenReturn(true);
        when(authentication.getPrincipal()).thenReturn(securityUser);
        when(authentication.getAuthorities()).thenAnswer(invocation -> securityUser.getAuthorities());
        SecurityContext context = SecurityContextHolder.getContext();
        context.setAuthentication(authentication);

        Object result = interceptor.doIntercept(joinPoint, requirePermission);

        assertThat(result).isEqualTo("result");
        verify(joinPoint).proceed();
        verifyNoInteractions(roleService);
    }

    @Test
    @DisplayName("service 内部服务角色 - 跳过权限查询直接放行")
    void serviceRoleBypassesPermissionQuery() throws Throwable {
        SecurityUser securityUser = new SecurityUser("internal-service", 1L, "internal-service",
                List.of("service"), List.of(new SimpleGrantedAuthority("ROLE_SERVICE")));
        when(authentication.isAuthenticated()).thenReturn(true);
        when(authentication.getPrincipal()).thenReturn(securityUser);
        when(authentication.getAuthorities()).thenAnswer(invocation -> securityUser.getAuthorities());
        SecurityContext context = SecurityContextHolder.getContext();
        context.setAuthentication(authentication);

        Object result = interceptor.doIntercept(joinPoint, requirePermission);

        assertThat(result).isEqualTo("result");
        verify(joinPoint).proceed();
        verifyNoInteractions(roleService);
    }

    // ================== 校验顺序：@Valid 先于权限切面（issue #5978 的已登记取舍）==================

    @Test
    @DisplayName("权限校验是「方法调用切面」⇒ 参数绑定/校验必然先跑（#5978 取舍的前提）")
    void permissionCheckIsMethodInvocationAdviceSoValidationRunsFirst() {
        // 取舍的内容（已登记在 docs/wiki/RBAC.md）：@Valid 校验发生在方法调用之前的参数解析阶段，
        // 而 @RequirePermission 由 AOP 在方法调用时生效 ⇒ 无权限身份拿到 422 而非 403。
        // 本判据锁「前提」本身：一旦有人把权限判定前移到 HandlerInterceptor（#5978 的架构修法），
        // 下面三条断言必红 ⇒ 提示同批更新 RBAC.md 的登记与本用例，而不是只改代码。
        assertThat(com.migao.admin.security.PermissionInterceptor.class.isAnnotationPresent(
                org.aspectj.lang.annotation.Aspect.class))
                .as("PermissionInterceptor 必须是 AOP 切面（切面 = 方法调用时机；挪到拦截器即改变校验顺序）")
                .isTrue();

        assertThat(com.migao.admin.security.RequirePermission.class
                .getAnnotation(java.lang.annotation.Target.class).value())
                .as("RequirePermission 必须可标注在方法上（@Target 含 METHOD）")
                .contains(java.lang.annotation.ElementType.METHOD);

        boolean hasAroundAdviceOnAnnotation = java.util.Arrays.stream(
                        com.migao.admin.security.PermissionInterceptor.class.getDeclaredMethods())
                .filter(m -> m.isAnnotationPresent(org.aspectj.lang.annotation.Around.class))
                .map(m -> m.getAnnotation(org.aspectj.lang.annotation.Around.class).value())
                .anyMatch(expr -> expr.contains("@annotation") && expr.contains("RequirePermission"));
        assertThat(hasAroundAdviceOnAnnotation)
                .as("切点必须是 @Around + @annotation(RequirePermission)（改成 HandlerInterceptor ⇒ 红）")
                .isTrue();
    }

    @Test
    @DisplayName("该取舍已登记在 docs/wiki/RBAC.md（文档与实现同生命周期，#5978）")
    void tradeOffIsRegisteredInRbacDoc() throws Exception {
        // surefire 的 cwd = 模块目录（backend/admin-api）⇒ 退两级到仓库根
        java.nio.file.Path doc = java.nio.file.Paths.get("..", "..", "docs", "wiki", "RBAC.md");
        assertThat(java.nio.file.Files.exists(doc)).as("文档必须存在：%s", doc.toAbsolutePath()).isTrue();
        String text = java.nio.file.Files.readString(doc);

        assertThat(text).as("必须登记 #5978 这条已知取舍").contains("#5978");
        assertThat(text).as("必须写明顺序方向涉及 @Valid").contains("@Valid");
        assertThat(text).as("必须写明可观察后果：422 早于 403").contains("422").contains("403");
    }
}
