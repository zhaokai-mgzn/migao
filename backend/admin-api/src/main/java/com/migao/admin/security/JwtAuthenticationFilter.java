package com.migao.admin.security;

import com.migao.admin.config.TenantContext;
import io.jsonwebtoken.Claims;
import io.jsonwebtoken.ExpiredJwtException;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.Cookie;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.web.authentication.WebAuthenticationDetailsSource;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.util.ArrayList;
import java.util.List;
import java.util.stream.Collectors;

/**
 * JWT 认证过滤器
 * 从 Cookie 或 Authorization Header 中提取 JWT，验证并设置 SecurityContext
 * 包含 Redis Token 黑名单检查（用于登出后的 Token 吊销）
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class JwtAuthenticationFilter extends OncePerRequestFilter {

    private final JwtTokenProvider jwtTokenProvider;
    private final StringRedisTemplate redisTemplate;

    @Value("${jwt.cookie.name:access_token}")
    private String cookieName;

    /**
     * Redis Token 黑名单 key 前缀
     */
    private static final String TOKEN_BLACKLIST_PREFIX = "token:blacklist:";

    @Override
    protected void doFilterInternal(HttpServletRequest request,
                                    HttpServletResponse response,
                                    FilterChain filterChain) throws ServletException, IOException {
        try {
            // 1. 从请求中提取 JWT
            String jwt = extractJwtFromRequest(request);

            // 2. 如果存在 JWT 且 SecurityContext 中无认证信息，则进行认证
            if (StringUtils.hasText(jwt) && SecurityContextHolder.getContext().getAuthentication() == null) {
                // 验证 Token
                if (jwtTokenProvider.validateToken(jwt)) {
                    // 解析 Claims
                    Claims claims = jwtTokenProvider.getClaimsFromToken(jwt);

                    // 检查是否为 Access Token
                    if (!jwtTokenProvider.isAccessToken(jwt)) {
                        log.warn("Token 类型不正确，不是 Access Token");
                        filterChain.doFilter(request, response);
                        return;
                    }

                    // 检查 Token 是否在 Redis 黑名单中（已登出/吊销）
                    String jti = claims.getId();
                    if (jti != null && isTokenBlacklisted(jti)) {
                        log.warn("Token 已吊销 (jti={})", jti);
                        filterChain.doFilter(request, response);
                        return;
                    }

                    // 提取用户信息
                    String userId = claims.get(JwtTokenProvider.CLAIM_USER_ID, String.class);
                    Object tenantIdObj = claims.get(JwtTokenProvider.CLAIM_TENANT_ID);
                    Long tenantId = tenantIdObj instanceof Number ? ((Number) tenantIdObj).longValue()
                            : (tenantIdObj != null ? Long.valueOf(tenantIdObj.toString()) : null);
                    String username = claims.get(JwtTokenProvider.CLAIM_USERNAME, String.class);
                    @SuppressWarnings("unchecked")
                    List<String> roles = claims.get(JwtTokenProvider.CLAIM_ROLES, List.class);

                    // 设置租户上下文（始终设置，确保 MyBatis Plus 租户拦截器不抛异常）
                    if (tenantId != null) {
                        TenantContext.setTenantId(tenantId);
                    } else {
                        log.warn("JWT 中未包含 tenantId，使用默认租户ID=1");
                        TenantContext.setTenantId(1L);
                    }

                    // 构建权限列表
                    List<SimpleGrantedAuthority> authorities = new ArrayList<>();
                    if (roles != null) {
                        for (String role : roles) {
                            // 添加 ROLE_ 前缀的角色权限
                            authorities.add(new SimpleGrantedAuthority("ROLE_" + role.toUpperCase()));
                            authorities.add(new SimpleGrantedAuthority(role));
                        }
                    }

                    // 创建 SecurityUser（携带 userId、tenantId 等业务字段）
                    SecurityUser securityUser = new SecurityUser(
                            userId, tenantId, username, roles, authorities);

                    UsernamePasswordAuthenticationToken authentication =
                            new UsernamePasswordAuthenticationToken(
                                    securityUser,
                                    null,
                                    securityUser.getAuthorities()
                            );

                    authentication.setDetails(new WebAuthenticationDetailsSource().buildDetails(request));

                    // 设置 SecurityContext
                    SecurityContextHolder.getContext().setAuthentication(authentication);

                    log.debug("JWT 认证成功: userId={}, tenantId={}", userId, tenantId);
                }
            }
            filterChain.doFilter(request, response);
        } catch (ExpiredJwtException e) {
            log.warn("JWT Token 已过期: {}", e.getMessage());
            filterChain.doFilter(request, response);
        } catch (Exception e) {
            log.error("JWT 认证失败: {}", e.getMessage());
            filterChain.doFilter(request, response);
        } finally {
            // 确保在请求处理完成后清理租户上下文，防止线程复用导致数据泄漏
            TenantContext.clear();
        }
    }

    @Override
    protected void doFilterNestedErrorDispatch(HttpServletRequest request, HttpServletResponse response, FilterChain filterChain) throws ServletException, IOException {
        try {
            filterChain.doFilter(request, response);
        } finally {
            TenantContext.clear();
        }
    }

    /**
     * 检查 Token 是否在 Redis 黑名单中
     *
     * @param jti Token 唯一标识
     * @return 是否已吊销
     */
    private boolean isTokenBlacklisted(String jti) {
        try {
            return Boolean.TRUE.equals(redisTemplate.hasKey(TOKEN_BLACKLIST_PREFIX + jti));
        } catch (Exception e) {
            log.warn("Redis 黑名单检查异常，默认放行: {}", e.getMessage());
            return false;
        }
    }

    /**
     * 从请求中提取 JWT
     * 优先从 Cookie 中提取，其次从 Authorization Header 中提取
     *
     * @param request HttpServletRequest
     * @return JWT Token 或 null
     */
    private String extractJwtFromRequest(HttpServletRequest request) {
        // 1. 尝试从 Cookie 中提取
        Cookie[] cookies = request.getCookies();
        if (cookies != null) {
            for (Cookie cookie : cookies) {
                if (cookieName.equals(cookie.getName())) {
                    String token = cookie.getValue();
                    if (StringUtils.hasText(token)) {
                        log.debug("从 Cookie 中提取到 JWT");
                        return token;
                    }
                }
            }
        }

        // 2. 尝试从 Authorization Header 中提取
        String bearerToken = request.getHeader("Authorization");
        if (StringUtils.hasText(bearerToken) && bearerToken.startsWith("Bearer ")) {
            String token = bearerToken.substring(7);
            log.debug("从 Authorization Header 中提取到 JWT");
            return token;
        }

        return null;
    }
}
