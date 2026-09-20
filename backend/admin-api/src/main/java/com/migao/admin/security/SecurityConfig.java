package com.migao.admin.security;

import com.fasterxml.jackson.databind.ObjectMapper;
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
import java.util.Set;

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
    /** 工人登录态过滤器（issue #4733）：X-Worker-Session-Id → ROLE_WORKER 认证。 */
    private final WorkerSessionFilter workerSessionFilter;
    private final UserDetailsService userDetailsService;
    /** 403 响应体序列化（与 @RequirePermission 拒绝同一份措辞，issue #4105 F1）。 */
    private final ObjectMapper objectMapper;

    /**
     * {@code /api/admin/**} **一律拒绝**的角色码集合（issue #4727 权限注解面审计）。
     *
     * <p>C 端顾客 / C 端坐席（customer / agent）自 #4105 起在门禁处拒绝。**工人端身份（worker）**
     * 由 #4716 工人端 H5 设计的冲突登记 C11 追加进同一集合：工人**不得**借既有
     * {@code /api/admin/**} 路径拿到商家能力（用户红线「不许给工人商家权限」）。
     * 工人端落码时走独立路径 {@code /api/worker/**}（不匹配 {@code /api/admin/**} ⇒ 落到
     * {@code anyRequest().authenticated()}），本集合只做「误用既有路径」的兜底闸。</p>
     *
     * <p>⚠️ 与 {@code RoleService} 的岗位码是**开放集合**（「岗位权限」页可创建任意岗位码）
     * 存在一个已知的碰撞面：若某租户自建了 code 恰为 {@code worker} 的岗位，其员工会被本集合
     * 拒绝进入管理后台。当前全仓无 {@code worker} 岗位种子（见 #4727 审计表「残余风险」），
     * 属有意取舍 —— 工人端落地后 {@code worker} 是**保留码**，租户不应再自建同名岗位。</p>
     */
    private static final Set<String> ADMIN_API_REJECTED_ROLES = Set.of("customer", "agent", "worker");

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
        // ⚠️ 本清单是**逐项白名单**：漏一个头 ⇒ 浏览器预检（OPTIONS）不放行该头 ⇒
        // 真实请求根本发不出去（前端只看到 CORS 报错，看不出是「少了一个头」）。
        // 工人端 H5（issue #4716）的登录态载体是 `X-Worker-Session-Id`（#4733 登记的本处缺口）：
        // **不加它 ⇒ 工人登录成功后所有请求被预检拦掉**（现象 = 「登录了但全 401」）。
        // 只加这一个头；origin 白名单**一字不动**（放宽 origin 才是越权面）。
        config.setAllowedHeaders(List.of(
                "Content-Type",
                "Authorization",
                "X-Service-Token",
                "X-Tenant-Id",
                "X-Request-Timestamp",
                "X-Request-Nonce",
                "X-Request-Id",
                "X-Worker-Session-Id"
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
     * @param passwordEncoder 密码编码器（BCrypt）—— bean 见 {@code PasswordEncoderConfig}（issue #4770）
     * @return SecurityFilterChain
     */
    @Bean
    public SecurityFilterChain securityFilterChain(HttpSecurity http, PasswordEncoder passwordEncoder)
            throws Exception {
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
                                "/api/auth/bmini/login",
                                "/api/auth/h5/authorize",
                                "/api/auth/h5/callback",
                                "/api/auth/refresh",
                                // 工人登录（issue #4733）：工号 + PIN 是**公开入口**（工人没有商家账号）
                                // —— 只放行登录本身；/api/worker/** 的其余端点仍需有效工人 session
                                "/api/worker/login",
                                // 工人端稳定短链（issue #4802，设计 #4716 §1.3 / §7.2）：
                                // `GET /s/{短码}` 是**印刷品上的公开入口**（纸上的码对任何持码人等价）
                                // ⇒ 必须 permitAll，否则扫码工具打开它只会拿到 401（短链等于没用）。
                                // ⚠️ 它**不是**身份入口：只回 302 + Location（换 token），不返回工人身份/权限
                                // —— 鉴权由报工页的工人 session 承担（/api/worker/** 那一层）。
                                "/s/**",
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
                        // 访问；小程序/B2C 用户（customer/agent）与工人端身份（worker）一律禁止
                        // （垂直越权防护，拒绝集合见 ADMIN_API_REJECTED_ROLES）。
                        // 细粒度权限由 @RequirePermission + PermissionInterceptor 在业务层校验。
                        .requestMatchers("/api/admin/**")
                        .access(adminApiAuthorizationManager())
                        // 工人端（issue #4733）：**新路径**，不匹配 /api/admin/** ⇒ 工人身份到不了管理后台。
                        // 准入判据 = 有效工人 session（由 WorkerSessionService.resolveIdentity 在每个端点上判，
                        // 无 session/已结束/已闲置超时 ⇒ 401）。此处只要求「已认证」，把细粒度留给业务层，
                        // 与 /api/admin/** 的分工一致。
                        .requestMatchers("/api/worker/**").authenticated()
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
                // 工人过滤器在 JWT 之后：**只在 SecurityContext 尚无认证时**设置
                // ⇒ 商家（持 JWT）的请求逐字走既有链路（本过滤器对它是 no-op）
                .addFilterAfter(workerSessionFilter, JwtAuthenticationFilter.class)

                // 配置认证提供者
                .authenticationProvider(authenticationProvider(passwordEncoder))

                // 配置异常处理：未认证请求返回 401 而非 403
                .exceptionHandling(ex -> ex
                        .authenticationEntryPoint((request, response, authException) -> {
                            response.setStatus(HttpServletResponse.SC_UNAUTHORIZED);
                            response.setContentType("application/json;charset=UTF-8");
                            response.getWriter().write(
                                    "{\"success\":false,\"error\":{\"code\":\"UNAUTHORIZED\",\"message\":\"未认证，请先登录\"}}");
                        })
                        // 已认证但角色不足时返回统一的 403 JSON（与 401 结构一致）
                        // 响应体走 PermissionDeniedResponse（issue #4105 F1）：与 @RequirePermission
                        // 拒绝同一个 error.code / suggestion 口径，不再手写裸 JSON
                        .accessDeniedHandler((request, response, accessDeniedException) -> {
                            response.setStatus(HttpServletResponse.SC_FORBIDDEN);
                            response.setContentType("application/json;charset=UTF-8");
                            objectMapper.writeValue(response.getWriter(),
                                    PermissionDeniedResponse.of(null));
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
     *   <li>拒绝集合 {@link #ADMIN_API_REJECTED_ROLES}（小程序/B2C 用户 customer/agent +
     *       <b>工人端身份 worker</b>）：一律拒绝（垂直越权防护，不回归；worker 为 issue #4727
     *       按 #4716 设计 C11 预留，见该常量 javadoc）。<b>issue #4733 复用它</b>（不新造第二套：
     *       本单只落码「工人可达面 = {@code /api/worker/**}」+ 该集合的既有判据的**红证**）；</li>
     *   <li>其余角色视为商户员工角色（含角色管理创建的自定义角色）：允许进入管理后台，
     *       具体接口能否访问由 {@code @RequirePermission} + {@link PermissionInterceptor} 按权限码细粒度校验。</li>
     * </ul>
     *
     * <p>注意（issue #4105 F2）：携带 Service Token 且 {@code X-User-Id} 命中**本租户商户员工**的调用
     * 不再挂 {@code service} 角色（见 {@link ServiceTokenFilter}），因此走的是第三条分支 ——
     * 由 {@code @RequirePermission} 真正校验该员工权限，而不是在这里被整段放行。</p>
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
                // 拒绝集合：C 端顾客/坐席 + 工人端身份（垂直越权防护）。#4727 已预留 worker；
                // #4733 只加红证断言，**不复制第二份判定**（同族口径必须只有一处）
                if (ADMIN_API_REJECTED_ROLES.contains(role)) {
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
     * <p>🔴 <b>issue #4770（P0 启动期环）</b>：{@code PasswordEncoder} 由**方法参数**注入 ——
     * 它的 {@code @Bean} 已挪到 {@link com.migao.admin.config.PasswordEncoderConfig}。
     * 原先声明在本类里，而本类在**构造期**依赖 {@code WorkerSessionFilter}
     * → {@code WorkerSessionService} → {@code PasswordEncoder} ⇒ 成环：
     * {@code securityConfig → workerSessionFilter → workerSessionService → securityConfig}
     * ⇒ admin-api **每次启动都崩**（{@code Requested bean is currently in creation}）⇒ nginx 502。
     * <b>不要把它挪回本类</b>（判据见 {@code SecurityConfigTest} 的上下文加载用例）。</p>
     *
     * @param passwordEncoder 密码编码器（BCrypt；bean 见 {@code PasswordEncoderConfig}）
     * @return AuthenticationProvider
     */
    @Bean
    public AuthenticationProvider authenticationProvider(PasswordEncoder passwordEncoder) {
        DaoAuthenticationProvider authProvider = new DaoAuthenticationProvider();
        authProvider.setUserDetailsService(userDetailsService);
        authProvider.setPasswordEncoder(passwordEncoder);
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
     * 禁止 Spring Boot 自动注册 WorkerSessionFilter 为 Servlet Filter
     * （只通过 Spring Security 过滤链管理，避免双重执行）
     */
    @Bean
    public FilterRegistrationBean<WorkerSessionFilter> workerSessionFilterRegistration(
            WorkerSessionFilter filter) {
        FilterRegistrationBean<WorkerSessionFilter> registration = new FilterRegistrationBean<>(filter);
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
