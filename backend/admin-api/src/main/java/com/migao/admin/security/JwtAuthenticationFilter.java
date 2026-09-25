package com.migao.admin.security;

import com.migao.admin.config.TenantContext;
import io.jsonwebtoken.Claims;
import io.jsonwebtoken.ExpiredJwtException;
import io.micrometer.core.instrument.MeterRegistry;
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
    private final MeterRegistry meterRegistry;

    @Value("${jwt.cookie.name:access_token}")
    private String cookieName;

    /**
     * Redis Token 黑名单 key 前缀
     */
    private static final String TOKEN_BLACKLIST_PREFIX = "token:blacklist:";

    /**
     * 吊销检查「不可执行」的可观测读数（Micrometer counter，`/actuator/metrics/<name>` 可读）。
     * 与 {@code AuthService} 使用**同一个**字面量（由
     * {@code tests/unit_ci_workflows/test_declared_vs_effective.py} 钉住，防两处各自演化）。
     */
    public static final String BLACKLIST_CHECK_UNAVAILABLE_METRIC = "migao.security.revocation_check_unavailable";

    /** 吊销检查不可执行时的日志关键词（告警规则按它匹配 —— 静默降级换绿必红）。 */
    public static final String BLACKLIST_CHECK_UNAVAILABLE_KEYWORD = "REVOCATION_CHECK_UNAVAILABLE";

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
                    // 检查结果 `null` = **不可执行**（Redis 异常）⇒ 与「已吊销」同样拒绝（fail-closed，issue #4866）
                    String jti = claims.getId();
                    Boolean revoked = jti != null ? isTokenBlacklisted(jti) : Boolean.FALSE;
                    if (revoked == null || revoked) {
                        log.warn("Token 已吊销或吊销状态不可判定，不建立认证 (jti={}, 判定={})",
                                jti, revoked == null ? "UNDECIDABLE" : "REVOKED");
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

                    // 首登强制改密标记（issue #5485 不变式 I4）：claim → 请求属性，
                    // 由 PasswordChangeRequiredFilter 决定是否 403。
                    // 这里只搬运、不判定（判定只有一处：那个过滤器），也不改 SecurityUser 的形状。
                    if (Boolean.TRUE.equals(claims.get(JwtTokenProvider.CLAIM_PWD_CHANGE_REQUIRED, Boolean.class))) {
                        request.setAttribute(PasswordChangeRequiredFilter.PWD_CHANGE_REQUIRED_ATTRIBUTE, Boolean.TRUE);
                    }

                    // 设置租户上下文（tenantId=-1 表示平台管理员，无租户归属）
                    if (tenantId != null && tenantId != -1L) {
                        TenantContext.setTenantId(tenantId);
                    } else if ((tenantId != null && tenantId == -1L) || (roles != null && roles.contains("super_admin"))) {
                        // 平台管理员（tenantId=-1）或 super_admin 角色，跳过租户上下文
                        log.debug("平台管理员认证，跳过租户上下文设置: userId={}", userId);
                    } else {
                        // 缺少 tenantId 的 token 视为无效，拒绝认证（fail-closed），
                        // 而非默认落到租户 1（可能导致跨租户数据泄露）
                        log.warn("JWT 缺少 tenantId，拒绝认证: userId={}", userId);
                        filterChain.doFilter(request, response);
                        return;
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
            // ⚠️ 静默失败风险：此 catch 捕获所有非 Redis 的认证异常（JWT 解析失败、NPE、类加载异常等），
            // 仅记录日志后放行请求。SecurityContext 未设置，下游鉴权会以 401/403 拒绝，但异常根因可能
            // 被淹没在大量 WARN/ERROR 日志中。如果此处误吞了关键基础设施故障（如配置错误、依赖缺失），
            // 会导致所有请求静默降级为匿名访问，而不会以 500 快速暴露问题。
            // 排查时优先搜索 "JWT 认证异常" 关键词，确认是否出现高频/非预期异常。
            log.error("JWT 认证异常（请求继续未认证状态，存在静默降级风险）: {}", e.getMessage(), e);
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
     * @return {@code TRUE}=已吊销 / {@code FALSE}=未吊销 / {@code null}=**检查不可执行**（Redis 异常）
     *         —— 调用方必须按已吊销处理（fail-closed，issue #4866）
     */
    private Boolean isTokenBlacklisted(String jti) {
        try {
            return Boolean.TRUE.equals(redisTemplate.hasKey(TOKEN_BLACKLIST_PREFIX + jti));
        } catch (Exception e) {
            // ⛔ 不许改回「异常 ⇒ 未吊销（放行）」：那会让 Redis 不可用期间的已吊销/已登出 token 继续可用，
            //    且没有任何人会察觉（issue #4866）。降级方向登记在
            //    tests/unit_ci_workflows/declared_effective_registry.json 的 security_degradation 台账 ——
            //    改方向 / 去掉读数 ⇒ 判据必红。
            log.error("{}（吊销检查不可执行 ⇒ 按已吊销拒绝，fail-closed）: jti={}",
                    BLACKLIST_CHECK_UNAVAILABLE_KEYWORD, jti, e);
            meterRegistry.counter(BLACKLIST_CHECK_UNAVAILABLE_METRIC).increment();
            return null;
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
