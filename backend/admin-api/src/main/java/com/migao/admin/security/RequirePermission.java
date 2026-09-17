package com.migao.admin.security;

import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/**
 * 权限注解 —— **生产授权主路径**（issue #4105 F9 修正：旧 javadoc 写「预留，当前未被任何
 * Controller/Service 使用」，与事实相反）。
 *
 * <p>{@link PermissionInterceptor} 以 AOP 拦截带本注解的方法与类，按
 * {@code RoleService.getUserPermissions(userId)} 校验权限码；拒绝时抛
 * {@link com.migao.admin.exception.PermissionDeniedException}，由
 * {@code GlobalExceptionHandler} 生成 403 + 可执行 suggestion。</p>
 *
 * <p>与路径级门禁的分工：{@code SecurityConfig#adminApiAuthorizationManager()} 只区分
 * 平台管理员/{@code service}/C 端消费者角色，其余商户员工角色一律放行到业务层，
 * 由本注解决定具体接口能否访问。RBAC 全貌见 {@code docs/wiki/RBAC.md}。</p>
 *
 * <p>用法：类级声明整个 Controller 的所需权限，方法级可覆盖为更精确的权限码
 * （解析顺序：方法级优先，其次类级），如 {@code @RequirePermission("product:list")}。</p>
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
