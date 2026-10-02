package com.migao.admin.config;

import com.migao.admin.security.PermissionInterceptor;

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
 */
@Configuration
public class WebConfig {

    private final PermissionInterceptor permissionInterceptor;

    public WebConfig(PermissionInterceptor permissionInterceptor) {
        this.permissionInterceptor = permissionInterceptor;
    }

    @Bean
    public WebMvcConfigurer webMvcConfigurer() {
        return new WebMvcConfigurer() {
            @Override
            public void addInterceptors(InterceptorRegistry registry) {
                registry.addInterceptor(permissionInterceptor)
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
