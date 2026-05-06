package com.aikf.admin.security;

import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/**
 * 权限注解
 * 用于标记需要特定权限的方法或类
 * 示例：@RequirePermission("product:manage")
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
