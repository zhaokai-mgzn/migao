package com.migao.admin.security;

import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.User;
import com.migao.admin.mapper.UserMapper;
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
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.List;
import java.util.Locale;
import java.util.Set;

/**
 * Service Token 认证过滤器
 * 用于验证内部服务调用的 Service Token（如 ai-agent-service 调用 admin-api）
 * 通过 Service Token 认证的请求，跳过 JWT 校验
 *
 * <p><b>商户员工不再整段绕过细粒度鉴权（issue #4105 F2）</b>：ai-agent 调用 admin-api 时
 * 始终携带 Service Token + {@code X-User-Id}。若该 {@code X-User-Id} 命中**本租户商户员工**，
 * 本过滤器改为挂该用户的真实角色（不再挂 {@code service}）—— 否则
 * {@link PermissionInterceptor#hasBypassRole} 与
 * {@code SecurityConfig#adminApiAuthorizationManager()} 会双双放行，
 * 使受限岗位的员工能借米宝执行自己无权执行的写操作。</p>
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class ServiceTokenFilter extends OncePerRequestFilter {

    private final UserMapper userMapper;

    @Value("${service.token.header:X-Service-Token}")
    private String serviceTokenHeader;

    @Value("${service.token.secret:}")
    private String serviceTokenSecret;

    // 内部服务角色
    private static final String SERVICE_ROLE = "ROLE_SERVICE";
    private static final String INTERNAL_ROLE = "ROLE_INTERNAL";
    private static final String SERVICE_ROLE_CODE = "service";
    private static final String SERVICE_USERNAME = "internal-service";
    // 内部服务调用时的真实用户请求头（ai-agent-service 透传的当前用户 ID，C 端数据隔离依据）
    private static final String USER_ID_HEADER = "X-User-Id";

    /**
     * C 端（小程序/B2C）角色，不属于商户员工范畴。
     * 与 {@code UserMapper.selectActiveEmployeesByPhoneIgnoreTenant} 的 SQL 门禁
     * {@code role NOT IN ('customer','agent')} 同口径（AuthService 的 bmini 员工门禁同源）。
     */
    private static final Set<String> C_END_ROLES = Set.of("customer", "agent");

    /** 内部服务身份（今日行为）：没有任何细粒度权限校验。 */
    private static final List<SimpleGrantedAuthority> SERVICE_AUTHORITIES = List.of(
            new SimpleGrantedAuthority(SERVICE_ROLE),
            new SimpleGrantedAuthority(INTERNAL_ROLE));

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
                    // 从请求头中提取租户ID（内部服务调用时通过 X-Tenant-Id 传递）
                    Long tenantId = parseTenantId(request.getHeader("X-Tenant-Id"));

                    // 透传真实用户 ID（ai-agent-service 调用时携带 X-User-Id）：
                    // 无 X-User-Id（如 B 端员工上下文缺省或纯服务端调用）回退为 service 占位，
                    // 保证 SecurityUser.userId 语义一致且不抛错；C 端数据隔离由业务层据此强制过滤。
                    String realUserId = request.getHeader(USER_ID_HEADER);
                    String effectiveUserId = StringUtils.hasText(realUserId) ? realUserId : SERVICE_USERNAME;

                    // 命中本租户商户员工 ⇒ 挂真实角色（走细粒度鉴权）；
                    // 其余四种情形（无 X-User-Id / C 端角色 / 跨租户 / 查不到）与今日行为逐字节一致。
                    User merchantStaff = StringUtils.hasText(realUserId)
                            ? resolveMerchantStaff(realUserId, tenantId) : null;
                    List<String> roles = List.of(SERVICE_ROLE_CODE);
                    List<SimpleGrantedAuthority> authorities = SERVICE_AUTHORITIES;
                    if (merchantStaff != null) {
                        roles = List.of(merchantStaff.getRole());
                        authorities = roles.stream()
                                .map(role -> new SimpleGrantedAuthority("ROLE_" + role.toUpperCase(Locale.ROOT)))
                                .toList();
                        log.debug("Service Token 认证：透传商户员工真实角色 userId={}, roles={}",
                                effectiveUserId, roles);
                    }

                    // 创建 SecurityUser（内部服务身份，userId 透传真实用户）
                    SecurityUser securityUser = new SecurityUser(
                            effectiveUserId, tenantId, SERVICE_USERNAME, roles, authorities);

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
     * 判定 {@code X-User-Id} 是否为「本租户商户员工」，是则返回该用户，否则返回 {@code null}
     * （回退内部服务身份 = 今日行为）。
     *
     * <p>判定口径与既有实现**同源**，不新造第二套（issue #4105）：用户行存在且未软删
     * （{@code @TableLogic} 由 {@code selectById} 隐式加 {@code deleted = 0}）、
     * {@code status = active}（同 {@code AuthService.validateBminiEmployee}）、
     * 租户与 {@code X-Tenant-Id} 一致、角色非 {@code customer}/{@code agent}
     * （同 {@code UserMapper.selectActiveEmployeesByPhoneIgnoreTenant} 的 SQL 门禁与
     * {@code UserService} 员工管理「排除 C 端消费者」口径）。</p>
     */
    private User resolveMerchantStaff(String userId, Long tenantId) {
        try {
            User user = userMapper.selectById(userId);
            if (user == null || !"active".equals(user.getStatus())) {
                return null;
            }
            if (!tenantId.equals(user.getTenantId())) {
                return null;
            }
            String role = user.getRole();
            if (role == null || C_END_ROLES.contains(role)) {
                return null;
            }
            return user;
        } catch (Exception e) {
            // 决策（issue #4105，见 PR 说明）：查库失败时回退**今日行为**（service 直通）而不是拒绝请求——
            // 调用方已持有可信 SERVICE_TOKEN（可信内部服务，不是不可信第三方），失败回退不构成提权；
            // 但必须 ERROR 留痕，否则「查失败」与「查不到」在日志里无从区分（静默失效形态）。
            log.error("商户员工判定失败，回退内部服务身份: userId={}, tenantId={}", userId, tenantId, e);
            return null;
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

        // 恒时比较（MessageDigest.isEqual），防止时序侧信道泄露 token 长度/前缀
        return MessageDigest.isEqual(
                serviceTokenSecret.getBytes(StandardCharsets.UTF_8),
                token.getBytes(StandardCharsets.UTF_8));
    }

    @Override
    protected boolean shouldNotFilter(HttpServletRequest request) {
        // 对内部 API 路径和 /api/admin/ 路径启用 Service Token 认证
        String path = request.getRequestURI();
        return !(path.startsWith("/api/internal/") || path.startsWith("/api/admin/"));
    }
}
