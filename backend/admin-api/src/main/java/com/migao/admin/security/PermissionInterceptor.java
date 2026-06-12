package com.migao.admin.security;

import com.migao.admin.service.RoleService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.aspectj.lang.ProceedingJoinPoint;
import org.aspectj.lang.annotation.Around;
import org.aspectj.lang.annotation.Aspect;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Component;

import java.util.List;

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
     * 拦截所有带有 @RequirePermission 注解的方法
     *
     * @param joinPoint 连接点
     * @param requirePermission 权限注解
     * @return 方法执行结果
     * @throws Throwable 异常
     */
    @Around("@annotation(requirePermission)")
    public Object intercept(ProceedingJoinPoint joinPoint, RequirePermission requirePermission) throws Throwable {
        String requiredPermission = requirePermission.value();

        // 获取当前用户认证信息
        Authentication authentication = SecurityContextHolder.getContext().getAuthentication();
        if (authentication == null || !authentication.isAuthenticated()) {
            log.warn("权限检查失败：用户未认证");
            throw new AccessDeniedException("用户未认证");
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
            throw new AccessDeniedException("权限不足，需要权限: " + requiredPermission);
        }

        log.debug("权限检查通过：用户 {} 拥有权限 {}", userId, requiredPermission);

        // 执行目标方法
        return joinPoint.proceed();
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
