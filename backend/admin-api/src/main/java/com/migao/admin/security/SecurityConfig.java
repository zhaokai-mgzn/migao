package com.migao.admin.security;

import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.web.servlet.FilterRegistrationBean;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.authentication.AnonymousAuthenticationToken;
import org.springframework.security.authentication.AuthenticationManager;
import org.springframework.security.authentication.AuthenticationProvider;
import org.springframework.security.authentication.dao.DaoAuthenticationProvider;
import org.springframework.security.authorization.AuthorizationDecision;
import org.springframework.security.authorization.AuthorizationManager;
import org.springframework.security.config.annotation.authentication.configuration.AuthenticationConfiguration;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configuration.EnableWebSecurity;
import org.springframework.security.config.annotation.web.configurers.AbstractHttpConfigurer;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.GrantedAuthority;
import org.springframework.security.core.userdetails.UserDetailsService;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.access.intercept.RequestAuthorizationContext;
import org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter;
import org.springframework.web.cors.CorsConfiguration;
import org.springframework.web.cors.CorsConfigurationSource;
import org.springframework.web.cors.UrlBasedCorsConfigurationSource;

import java.util.Arrays;
import java.util.List;
import java.util.Locale;

/**
 * Spring Security 配置类
 * 配置安全过滤链、认证管理器、密码编码器等
 */
@Configuration
@EnableWebSecurity
@RequiredArgsConstructor
public class SecurityConfig {

    private final JwtAuthenticationFilter jwtAuthenticationFilter;
    private final ServiceTokenFilter serviceTokenFilter;
    private final UserDetailsService userDetailsService;

    /**
     * CORS 允许的域名列表（从 .env / 环境变量注入，支持 Spring 属性解析）
     */
    @Value("${CORS_ALLOWED_ORIGINS:}")
    private String corsAllowedOrigins;

    /**
     * 配置 CORS
     *
     * @return CorsConfigurationSource
     */
    @Bean
    public CorsConfigurationSource corsConfigurationSource() {
        CorsConfiguration config = new CorsConfiguration();
        String corsOrigins = corsAllowedOrigins;
        if (corsOrigins != null && !corsOrigins.isEmpty()) {
            List<String> allowedOrigins = Arrays.asList(corsOrigins.split(","));
            config.setAllowedOrigins(allowedOrigins);
        } else {
            config.setAllowedOrigins(List.of(
                    "http://localhost:3000",
                    "http://localhost:3001",
                    "http://127.0.0.1:3000",
                    "http://127.0.0.1:3001",
                    "https://admin.migaozn.com",
                    "https://migaozn.com",
                    "https://www.migaozn.com"
            ));
        }
        config.setAllowedMethods(List.of("GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"));
        config.setAllowedHeaders(List.of(
                "Content-Type",
                "Authorization",
                "X-Service-Token",
                "X-Tenant-Id",
                "X-Request-Timestamp",
                "X-Request-Nonce",
                "X-Request-Id"
        ));
        config.setAllowCredentials(true);
        config.setMaxAge(3600L);
        UrlBasedCorsConfigurationSource source = new UrlBasedCorsConfigurationSource();
        source.registerCorsConfiguration("/**", config);
        return source;
    }

    /**
     * 配置安全过滤链
     *
     * @param http HttpSecurity
     * @return SecurityFilterChain
     */
    @Bean
    public SecurityFilterChain securityFilterChain(HttpSecurity http) throws Exception {
        http
                // 安全头
                .headers(headers -> headers
                        .frameOptions(frame -> frame.deny())
                        .httpStrictTransportSecurity(hsts -> hsts
                                .maxAgeInSeconds(31536000)
                                .includeSubDomains(true))
                )

                // 启用 CORS（由 corsConfigurationSource bean 统一管理）
                .cors(cors -> cors.configurationSource(corsConfigurationSource()))

                // 禁用 CSRF（REST API 不需要）
                .csrf(AbstractHttpConfigurer::disable)

                // 配置授权规则
                .authorizeHttpRequests(auth -> auth
                        // 放行路径（不需要认证）
                        .requestMatchers(
                                // 认证接口（公开，不需要认证）
                                "/api/auth/admin/login",
                                "/api/auth/mini/login",
                                "/api/auth/h5/authorize",
                                "/api/auth/h5/callback",
                                "/api/auth/refresh",
                                // 短信验证码接口（公开）
                                "/api/auth/sms/**",
                                // 企业入驻申请接口（公开）
                                "/api/auth/register",
                                // 健康检查和文档
                                "/actuator/health",
                                "/actuator/info",
                                "/swagger-ui/**",
                                "/v3/api-docs/**",
                                "/webjars/**",
                                "/swagger-ui.html",
                                // 本地文件静态资源（无需认证）
                                "/api/files/static/**"
                        ).permitAll()
                        // 管理后台接口：允许平台管理员(ADMIN/SUPER_ADMIN)、内部服务(SERVICE)
                        // 以及商户员工角色（operator/product_manager/知识编辑/角色管理创建的自定义角色等）
                        // 访问；小程序/B2C 用户（customer/agent）一律禁止（垂直越权防护）。
                        // 细粒度权限由 @RequirePermission + PermissionInterceptor 在业务层校验。
                        .requestMatchers("/api/admin/**")
                        .access(adminApiAuthorizationManager())
                        // 其他路径需要认证（包括 /api/super-admin/** 超管接口，由业务层校验超管角色）
                        .anyRequest().authenticated()
                )

                // 禁用 Session（无状态）
                .sessionManagement(session ->
                        session.sessionCreationPolicy(SessionCreationPolicy.STATELESS)
                )

                // 添加自定义过滤器
                // Service Token 过滤器在 JWT 过滤器之前，用于内部服务调用
                .addFilterBefore(serviceTokenFilter, UsernamePasswordAuthenticationFilter.class)
                .addFilterBefore(jwtAuthenticationFilter, UsernamePasswordAuthenticationFilter.class)

                // 配置认证提供者
                .authenticationProvider(authenticationProvider())

                // 配置异常处理：未认证请求返回 401 而非 403
                .exceptionHandling(ex -> ex
                        .authenticationEntryPoint((request, response, authException) -> {
                            response.setStatus(HttpServletResponse.SC_UNAUTHORIZED);
                            response.setContentType("application/json;charset=UTF-8");
                            response.getWriter().write(
                                    "{\"success\":false,\"error\":{\"code\":\"UNAUTHORIZED\",\"message\":\"未认证，请先登录\"}}");
                        })
                        // 已认证但角色不足时返回统一的 403 JSON（与 401 结构一致）
                        .accessDeniedHandler((request, response, accessDeniedException) -> {
                            response.setStatus(HttpServletResponse.SC_FORBIDDEN);
                            response.setContentType("application/json;charset=UTF-8");
                            response.getWriter().write(
                                    "{\"success\":false,\"error\":{\"code\":\"FORBIDDEN\",\"message\":\"权限不足，禁止访问\"}}");
                        })
                );

        return http.build();
    }

    /**
     * 管理后台接口门禁（/api/admin/**）
     *
     * <p>角色口径：
     * <ul>
     *   <li>平台管理员（admin/super_admin）与内部服务（service）：直接放行；</li>
     *   <li>小程序/B2C 用户角色（customer/agent）：一律拒绝（垂直越权防护，不回归）；</li>
     *   <li>其余角色视为商户员工角色（含角色管理创建的自定义角色）：允许进入管理后台，
     *       具体接口能否访问由 {@code @RequirePermission} + {@link PermissionInterceptor} 按权限码细粒度校验。</li>
     * </ul>
     */
    @Bean
    public AuthorizationManager<RequestAuthorizationContext> adminApiAuthorizationManager() {
        return (authenticationSupplier, context) -> {
            Authentication authentication = authenticationSupplier != null ? authenticationSupplier.get() : null;
            if (authentication == null || !authentication.isAuthenticated()
                    || authentication instanceof AnonymousAuthenticationToken) {
                return new AuthorizationDecision(false);
            }
            boolean hasRole = false;
            for (GrantedAuthority authority : authentication.getAuthorities()) {
                String name = authority.getAuthority();
                if (name == null) {
                    continue;
                }
                String role = name.startsWith("ROLE_") ? name.substring(5) : name;
                role = role.toLowerCase(Locale.ROOT);
                // 平台管理员 / 内部服务：放行
                if ("admin".equals(role) || "super_admin".equals(role) || "service".equals(role)) {
                    return new AuthorizationDecision(true);
                }
                // 小程序/B2C 用户：拒绝（垂直越权防护）
                if ("customer".equals(role) || "agent".equals(role)) {
                    return new AuthorizationDecision(false);
                }
                hasRole = true;
            }
            // 其余角色（商户员工，含自定义角色）：允许进入，细粒度权限由业务层校验
            return new AuthorizationDecision(hasRole);
        };
    }

    /**
     * 配置认证提供者
     *
     * @return AuthenticationProvider
     */
    @Bean
    public AuthenticationProvider authenticationProvider() {
        DaoAuthenticationProvider authProvider = new DaoAuthenticationProvider();
        authProvider.setUserDetailsService(userDetailsService);
        authProvider.setPasswordEncoder(passwordEncoder());
        return authProvider;
    }

    /**
     * 配置认证管理器
     *
     * @param config AuthenticationConfiguration
     * @return AuthenticationManager
     */
    @Bean
    public AuthenticationManager authenticationManager(AuthenticationConfiguration config) throws Exception {
        return config.getAuthenticationManager();
    }

    /**
     * 配置密码编码器（BCrypt）
     *
     * @return PasswordEncoder
     */
    @Bean
    public PasswordEncoder passwordEncoder() {
        return new BCryptPasswordEncoder();
    }

    /**
     * 禁止 Spring Boot 自动注册 JwtAuthenticationFilter 为 Servlet Filter
     * 该过滤器仅通过 Spring Security 过滤链管理，避免双重执行
     */
    @Bean
    public FilterRegistrationBean<JwtAuthenticationFilter> jwtFilterRegistration(JwtAuthenticationFilter filter) {
        FilterRegistrationBean<JwtAuthenticationFilter> registration = new FilterRegistrationBean<>(filter);
        registration.setEnabled(false);
        return registration;
    }

    /**
     * 禁止 Spring Boot 自动注册 ServiceTokenFilter 为 Servlet Filter
     * 该过滤器仅通过 Spring Security 过滤链管理，避免双重执行
     */
    @Bean
    public FilterRegistrationBean<ServiceTokenFilter> serviceTokenFilterRegistration(ServiceTokenFilter filter) {
        FilterRegistrationBean<ServiceTokenFilter> registration = new FilterRegistrationBean<>(filter);
        registration.setEnabled(false);
        return registration;
    }
}
