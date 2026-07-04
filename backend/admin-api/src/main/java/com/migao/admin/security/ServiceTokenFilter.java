package com.migao.admin.security;

import com.migao.admin.config.TenantContext;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.web.authentication.WebAuthenticationDetailsSource;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.util.List;

/**
 * Service Token 认证过滤器
 * 用于验证内部服务调用的 Service Token（如 ai-agent-service 调用 admin-api）
 * 通过 Service Token 认证的请求，跳过 JWT 校验
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class ServiceTokenFilter extends OncePerRequestFilter {

    @Value("${service.token.header:X-Service-Token}")
    private String serviceTokenHeader;

    @Value("${service.token.secret:}")
    private String serviceTokenSecret;

    // 内部服务角色
    private static final String SERVICE_ROLE = "ROLE_SERVICE";
    private static final String SERVICE_USERNAME = "internal-service";

    @Override
    protected void doFilterInternal(HttpServletRequest request,
                                    HttpServletResponse response,
                                    FilterChain filterChain) throws ServletException, IOException {
        boolean tenantContextSet = false;
        try {
            // 1. 检查请求头中是否包含 Service Token
            String serviceToken = request.getHeader(serviceTokenHeader);

            // 2. 如果存在 Service Token 且 SecurityContext 中无认证信息，则进行认证
            if (StringUtils.hasText(serviceToken) && SecurityContextHolder.getContext().getAuthentication() == null) {
                // 验证 Service Token
                if (validateServiceToken(serviceToken)) {
                    // 创建内部服务的认证对象
                    List<SimpleGrantedAuthority> authorities = List.of(
                            new SimpleGrantedAuthority(SERVICE_ROLE),
                            new SimpleGrantedAuthority("ROLE_INTERNAL")
                    );

                    // 从请求头中提取租户ID（内部服务调用时通过 X-Tenant-Id 传递）
                    Long tenantId = parseTenantId(request.getHeader("X-Tenant-Id"));

                    // 创建 SecurityUser（内部服务身份）
                    SecurityUser securityUser = new SecurityUser(
                            SERVICE_USERNAME, tenantId, SERVICE_USERNAME,
                            List.of("service"), authorities);

                    UsernamePasswordAuthenticationToken authentication =
                            new UsernamePasswordAuthenticationToken(
                                    securityUser,
                                    null,
                                    securityUser.getAuthorities()
                            );

                    authentication.setDetails(new WebAuthenticationDetailsSource().buildDetails(request));

                    // 设置 SecurityContext
                    SecurityContextHolder.getContext().setAuthentication(authentication);

                    // 设置租户上下文（始终设置，确保下游不会 NPE）
                    TenantContext.setTenantId(tenantId);
                    tenantContextSet = true;

                    log.debug("Service Token 认证成功: 内部服务调用, tenantId={}", tenantId);
                } else {
                    log.warn("Service Token 验证失败");
                }
            }
        } catch (IllegalArgumentException e) {
            log.warn("Service Token 认证参数错误: {}", e.getMessage());
            response.setStatus(HttpServletResponse.SC_BAD_REQUEST);
            response.setContentType("application/json;charset=UTF-8");
            response.getWriter().write("{\"code\":400,\"message\":\"" + e.getMessage() + "\"}");
            return;
        } catch (Exception e) {
            log.error("Service Token 认证失败: {}", e.getMessage());
        }

        try {
            filterChain.doFilter(request, response);
        } finally {
            // 清理租户上下文，防止 ThreadLocal 泄漏
            if (tenantContextSet) {
                TenantContext.clear();
            }
        }
    }

    /**
     * 解析租户ID，缺失或无效时抛出 IllegalArgumentException。
     * 内部服务调用必须显式传递租户ID，防止跨租户数据访问。
     */
    private Long parseTenantId(String tenantIdStr) {
        if (!StringUtils.hasText(tenantIdStr)) {
            throw new IllegalArgumentException("X-Tenant-Id 请求头缺失或为空，内部服务调用必须提供租户ID");
        }
        try {
            return Long.valueOf(tenantIdStr.trim());
        } catch (NumberFormatException e) {
            throw new IllegalArgumentException("X-Tenant-Id 格式无效: '" + tenantIdStr + "'，必须为数字");
        }
    }

    /**
     * 验证 Service Token
     *
     * @param token Service Token
     * @return 是否有效
     */
    private boolean validateServiceToken(String token) {
        // 如果未配置 Service Token Secret，则拒绝所有 Service Token 认证
        if (!StringUtils.hasText(serviceTokenSecret)) {
            log.warn("Service Token Secret 未配置，拒绝 Service Token 认证");
            return false;
        }

        // 简单的字符串比较验证
        // 生产环境建议使用更安全的验证方式，如 HMAC 签名
        return serviceTokenSecret.equals(token);
    }

    @Override
    protected boolean shouldNotFilter(HttpServletRequest request) {
        // 对内部 API 路径和 /api/admin/ 路径启用 Service Token 认证
        String path = request.getRequestURI();
        return !(path.startsWith("/api/internal/") || path.startsWith("/api/admin/"));
    }
}
