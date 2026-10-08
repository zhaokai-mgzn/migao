package com.migao.admin.security;

import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/**
 * 租户域资源的**写端点**标记 —— 该端点的 {@code {id}} 路径变量必须先做「是否属于当前租户」
 * 的归属认定，**早于**载荷校验（issue #6158）。
 *
 * <p>为什么需要它：控制器参数上的 {@code @Valid} 与请求体反序列化都发生在 MVC 的
 * <b>参数解析阶段</b>，早于控制器方法体 ⇒ 跨租户 + 非法载荷会先拿到 422/400
 * （「参数错误」），而跨租户 + 合法载荷才拿到 404。审计面因此把越权尝试记成参数错误，
 * 掩盖真实攻击面（证据：{@code acceptance/2026-10-03/tenant-isolation-sweep/REPORT.md} §F-1）。</p>
 *
 * <p>承载体 = {@link TenantOwnershipInterceptor}：它在 {@code preHandle}（MVC 分发阶段，
 * 早于参数解析）按 {@link #value()} 去 {@link TenantResourceOwnership} 取该资源的归属认定，
 * 认定不通过 ⇒ 抛 {@code NOT_FOUND}（与「合法载荷跨租户写」现在走的那条 404 路径同源）。
 * 同款「判定必须先于参数解析」的先例 = {@link PermissionInterceptor}（issue #6063）。</p>
 *
 * <p>🔴 标注本注解**不会**把载荷校验挪没：跨过归属认定之后，{@code @Valid} 照旧执行
 * （同租户 + 非法载荷仍是 422 + 逐字段 {@code error.details}）。</p>
 */
@Target(ElementType.METHOD)
@Retention(RetentionPolicy.RUNTIME)
public @interface TenantOwnedResource {

    /**
     * 资源键，必须在 {@link TenantResourceOwnership} 里已登记；未登记 ⇒ 该拦截器**显式抛错**
     * （不是静默放行）。
     *
     * @return 资源键，如 {@code "product"} / {@code "order"}
     */
    String value();
}
