package com.migao.admin.config;

import com.migao.admin.security.PaginationParamInterceptor;
import com.migao.admin.security.PermissionInterceptor;
import com.migao.admin.security.TenantOwnershipInterceptor;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.InterceptorRegistry;
import org.springframework.web.servlet.config.annotation.ResourceHandlerRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

/**
 * Web 配置类
 * CORS 由 SecurityConfig 统一管理，此处处理静态资源映射 + 权限拦截器注册
 *
 * <p>F3（issue #6063）：权限判定必须先于参数解析 —— {@code PermissionInterceptor} 以
 * {@code HandlerInterceptor.preHandle} 注册（MVC 分发阶段，早于 {@code @RequestParam}
 * 必填校验的参数解析阶段），否则无权限 GET 缺必填参数先拿到 400/422 而非 403
 * （信息泄露：端点存在 + 参数结构可被探测）。AOP {@code @Around} 保留为双保险。</p>
 *
 * <p>issue #6158：{@code TenantOwnershipInterceptor} 同款注册（同一条「判定必须先于参数解析」
 * 的次序纪律，那条治授权、这条治**归属**）—— 跨租户 + 非法载荷写现在拿 404 而不是
 * 422/400，认定不过时不进入参数解析。两个拦截器的**相对顺序**不敏感：一个判授权、
 * 一个判归属，任一不过都应在参数解析之前结束请求（`@RequirePermission` 与
 * `@TenantOwnedResource` 可同时标注，两者都抛异常 ⇒ 谁先谁后都是「先拒绝」）。</p>
 *
 * <p>issue #6222：{@code PaginationParamInterceptor} 是**分页入参的单点准入**
 * （非法 `page`/`size` ⇒ 400，不再出现「`total=0` 却返回整页」）。它**必须排在最后** ——
 * 授权先于入参（#6063 F3 的 403-before-400 契约）⇒ 无权限 + `size=-5` 仍是 403，
 * 不因这道新闸变成 400（顺序判据见 `PaginationParamGateWiringTest`）。</p>
 */
@Configuration
public class WebConfig {

    private final PermissionInterceptor permissionInterceptor;

    /** 归属认定拦截器（issue #6158）—— 构造注入：漏装配 ⇒ 启动期/判据当场红，不静默少一条闸。 */
    private final TenantOwnershipInterceptor tenantOwnershipInterceptor;

    /** 分页入参闸（issue #6222）—— 同款构造注入：漏装配 ⇒ 判据当场红。 */
    private final PaginationParamInterceptor paginationParamInterceptor;

    public WebConfig(PermissionInterceptor permissionInterceptor,
                     TenantOwnershipInterceptor tenantOwnershipInterceptor,
                     PaginationParamInterceptor paginationParamInterceptor) {
        this.permissionInterceptor = permissionInterceptor;
        this.tenantOwnershipInterceptor = tenantOwnershipInterceptor;
        this.paginationParamInterceptor = paginationParamInterceptor;
    }

    @Bean
    public WebMvcConfigurer webMvcConfigurer() {
        return new WebMvcConfigurer() {
            @Override
            public void addInterceptors(InterceptorRegistry registry) {
                registry.addInterceptor(permissionInterceptor)
                        .addPathPatterns("/api/**");
                // issue #6158：归属认定先于载荷校验（同一条次序纪律的第二个实例）
                registry.addInterceptor(tenantOwnershipInterceptor)
                        .addPathPatterns("/api/**");
                // issue #6222：分页入参闸**排在最后** —— 授权/归属判定先于入参判定（F3 #6063 的次序纪律）
                registry.addInterceptor(paginationParamInterceptor)
                        .addPathPatterns("/api/**");
            }

            @Override
            public void addResourceHandlers(ResourceHandlerRegistry registry) {
                registry.addResourceHandler("/swagger-ui/**")
                        .addResourceLocations("classpath:/META-INF/resources/webjars/swagger-ui/");
                registry.addResourceHandler("/webjars/**")
                        .addResourceLocations("classpath:/META-INF/resources/webjars/");
                // 本地文件上传静态资源服务
                registry.addResourceHandler("/api/files/static/**")
                        .addResourceLocations("file:uploads/");
            }
        };
    }
}
