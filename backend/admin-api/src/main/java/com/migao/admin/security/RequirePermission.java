package com.migao.admin.security;

import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/**
 * 权限注解（预留 — 当前未被任何 Controller/Service 使用）
 *
 * <p>当前项目通过 {@code SecurityUser.requireAdmin()} 等 imperative 检查实现鉴权。
 * 此注解 + {@link PermissionInterceptor} 是计划中的 AOP 声明式鉴权方案，
 * 待 RBAC 权限体系成熟后启用。</p>
 *
 * <p>使用示例（启用后）：{@code @RequirePermission("product:manage")}</p>
 */
@Target({ElementType.METHOD, ElementType.TYPE})
@Retention(RetentionPolicy.RUNTIME)
public @interface RequirePermission {
    /**
     * 所需权限，格式为 "模块:操作"
     * 如："product:manage", "knowledge:manage"
     *
     * @return 权限字符串
     */
    String value();
}
