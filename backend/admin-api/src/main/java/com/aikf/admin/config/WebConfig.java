package com.aikf.admin.config;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.CorsRegistry;
import org.springframework.web.servlet.config.annotation.ResourceHandlerRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

/**
 * Web 配置类
 * 配置 CORS 等 Web 相关设置
 */
@Configuration
public class WebConfig {

    /**
     * 配置 CORS
     *
     * @return WebMvcConfigurer
     */
    @Bean
    public WebMvcConfigurer corsConfigurer() {
        return new WebMvcConfigurer() {
            @Override
            public void addCorsMappings(CorsRegistry registry) {
                String corsOrigins = System.getenv("CORS_ALLOWED_ORIGINS");
                String[] origins;
                if (corsOrigins != null && !corsOrigins.isEmpty()) {
                    origins = corsOrigins.split(",");
                } else {
                    origins = new String[]{
                            "http://localhost:3000",
                            "http://localhost:3001",
                            "http://127.0.0.1:3000",
                            "http://127.0.0.1:3001"
                    };
                }
                registry.addMapping("/**")
                        // 允许的前端地址
                        .allowedOrigins(origins)
                        // 允许的 HTTP 方法
                        .allowedMethods("GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH")
                        // 允许的请求头
                        .allowedHeaders(
                                "Content-Type",
                                "Authorization",
                                "X-Service-Token",
                                "X-Request-Timestamp",
                                "X-Request-Nonce",
                                "X-Request-Id"
                        )
                        // 允许携带凭证（Cookie）
                        .allowCredentials(true)
                        // 预检请求缓存时间（秒）
                        .maxAge(3600);
            }

            @Override
            public void addResourceHandlers(ResourceHandlerRegistry registry) {
                // add-mappings: false 会禁用默认静态资源映射，手动添加 Swagger UI 需要的资源
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
