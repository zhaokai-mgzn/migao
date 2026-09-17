package com.migao.admin.security;

import com.migao.admin.exception.PermissionDeniedException;
import com.migao.admin.service.RoleService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.aspectj.lang.ProceedingJoinPoint;
import org.aspectj.lang.annotation.Around;
import org.aspectj.lang.annotation.Aspect;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.GrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Component;

import java.util.List;
import java.util.Locale;

/**
 * 权限拦截器
 * 使用 AOP 拦截带 @RequirePermission 注解的方法
 * 检查当前用户是否拥有所需权限
 */
@Slf4j
@Aspect
@Component
@RequiredArgsConstructor
public class PermissionInterceptor {

    private final RoleService roleService;

    /**
     * 拦截所有带有 @RequirePermission 注解的方法（支持方法级与类级注解）
     *
     * <p>注意：不能使用 {@code @annotation(x) || @within(x)} 绑定参数（AspectJ 的 OR 分支
     * 只从命中的第一个分支绑定，类级命中时参数为 null），改为在切面内手动解析注解：
     * 优先取方法级注解，其次取类级注解。</p>
     *
     * @param joinPoint 连接点
     * @return 方法执行结果
     * @throws Throwable 异常
     */
    @Around("@annotation(com.migao.admin.security.RequirePermission)"
            + " || @within(com.migao.admin.security.RequirePermission)")
    public Object intercept(ProceedingJoinPoint joinPoint) throws Throwable {
        RequirePermission requirePermission = resolveRequirePermission(joinPoint);
        if (requirePermission == null) {
            log.warn("权限检查失败：无法解析 @RequirePermission 注解");
            throw new AccessDeniedException("权限配置异常，请联系管理员");
        }
        return doIntercept(joinPoint, requirePermission);
    }

    /**
     * 解析方法上的 @RequirePermission：优先方法级注解，其次类级注解。
     */
    private RequirePermission resolveRequirePermission(ProceedingJoinPoint joinPoint) {
        if (joinPoint.getSignature() instanceof org.aspectj.lang.reflect.MethodSignature methodSignature) {
            RequirePermission methodAnn = methodSignature.getMethod().getAnnotation(RequirePermission.class);
            if (methodAnn != null) {
                return methodAnn;
            }
        }
        Object target = joinPoint.getTarget();
        if (target != null) {
            RequirePermission classAnn = target.getClass().getAnnotation(RequirePermission.class);
            if (classAnn != null) {
                return classAnn;
            }
        }
        return null;
    }

    Object doIntercept(ProceedingJoinPoint joinPoint, RequirePermission requirePermission) throws Throwable {
        requirePermission(requirePermission.value());

        // 执行目标方法
        return joinPoint.proceed();
    }

    /**
     * 命令式权限断言（issue #4148）：判定语义与 AOP 拦截**逐条相同**（未认证 ⇒ 拒绝 /
     * 平台管理员与内部服务旁路 / `*` 通配 / `RoleService.getUserPermissions` 细粒度查询），
     * 拒绝时抛 {@link PermissionDeniedException}（带结构化权限码，由 GlobalExceptionHandler
     * 生成 403 + 缺失码 + 可执行 suggestion）。
     *
     * <p>为什么需要它：{@code @RequirePermission} 只能声明**端点级**的静态权限码，而
     * {@code PATCH /api/admin/agent/orders/{id}} 一个入口按请求体的 {@code action} 覆盖
     * status/logistics/payment/cancel/**refund** —— 退款是财务动作（表单路径
     * {@code OrderController} 用的是 {@code order:refund}），只有到了 action 维度才判得出来。
     * 控制器调用本方法复用**同一份**判定，而不是在自己的类里再写一段查权限：那是第二份授权实现，
     * 必然与 AOP 口径漂移（旁路角色/通配/取码来源任一处不一致就会放出越权或误拒）。</p>
     *
     * @param requiredPermission 需要的权限码（如 {@code order:refund}）
     */
    public void requirePermission(String requiredPermission) {
        // 获取当前用户认证信息
        Authentication authentication = SecurityContextHolder.getContext().getAuthentication();
        if (authentication == null || !authentication.isAuthenticated()) {
            log.warn("权限检查失败：用户未认证");
            throw new AccessDeniedException("用户未认证");
        }

        // 平台管理员（super_admin）与内部服务（service）拥有全部权限，直接放行。
        // super_admin 用户不在 users 表（platform_admins），getUserPermissions 会返回空集；
        // service 为内部服务身份（internal-service），同样不适用租户权限查询。
        if (hasBypassRole(authentication)) {
            log.debug("权限检查跳过：用户为平台管理员或内部服务，权限 {}", requiredPermission);
            return;
        }

        // 获取当前用户ID
        String userId = extractUserId(authentication);
        if (userId == null) {
            log.warn("权限检查失败：无法获取用户ID");
            throw new AccessDeniedException("无法获取用户信息");
        }

        // 获取用户所有权限
        List<String> userPermissions = roleService.getUserPermissions(userId);

        // 检查是否拥有所需权限
        // admin 角色拥有所有权限（用 "*" 表示）
        boolean hasPermission = userPermissions.contains("*") || userPermissions.contains(requiredPermission);

        if (!hasPermission) {
            log.warn("权限检查失败：用户 {} 缺少权限 {}", userId, requiredPermission);
            // 权限码作为结构化字段随异常传递（issue #4105 F1），下游不再解析 message
            throw new PermissionDeniedException(
                    "权限不足，需要权限: " + requiredPermission, requiredPermission);
        }

        log.debug("权限检查通过：用户 {} 拥有权限 {}", userId, requiredPermission);
    }

    /**
     * 判断当前认证是否为平台管理员（super_admin）或内部服务（service），
     * 二者拥有全部权限，跳过细粒度权限查询。
     */
    private boolean hasBypassRole(Authentication authentication) {
        if (authentication.getAuthorities() == null) {
            return false;
        }
        for (GrantedAuthority authority : authentication.getAuthorities()) {
            String name = authority.getAuthority();
            if (name == null) {
                continue;
            }
            String role = name.startsWith("ROLE_") ? name.substring(5) : name;
            role = role.toLowerCase(Locale.ROOT);
            if ("super_admin".equals(role) || "service".equals(role)) {
                return true;
            }
        }
        return false;
    }

    /**
     * 从认证信息中提取用户ID
     *
     * @param authentication 认证信息
     * @return 用户ID
     */
    private String extractUserId(Authentication authentication) {
        Object principal = authentication.getPrincipal();
        if (principal instanceof SecurityUser securityUser) {
            return securityUser.getUserId();
        }
        if (principal instanceof org.springframework.security.core.userdetails.User userDetails) {
            return userDetails.getUsername();
        }
        return null;
    }
}
