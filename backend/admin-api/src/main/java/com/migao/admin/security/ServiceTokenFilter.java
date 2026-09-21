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
 *
 * <p><b>商户员工判定失败时 fail-closed（issue #5085，改判 #4105 的 fail-open）</b>：查库异常
 * （DB/连接抖动）时**拒绝请求**（503，不设 SecurityContext、不继续 filter chain），
 * 而不是回退 {@code service} 身份 —— 回退等于 service 全权直通，失效方向是放宽且无需攻击者构造。</p>
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

                    // 设置租户上下文（始终设置，确保下游不会 NPE）。
                    // ⚠️ 必须早于下面的 X-User-Id 查库：users 表不在
                    // MybatisPlusConfig.IGNORE_TENANT_TABLES 内，TenantContext 为空时
                    // TenantLineHandler.getTenantId() 会抛 "Tenant context not initialized"，
                    // 该异常会被 resolveMerchantStaff 的 fallback 吞掉 ⇒ F2 在**生产**静默失效
                    // （单测/E2E 都 mock 了 UserMapper，看不出来；只有断言"查库那一刻的
                    // TenantContext"才能变红）。异常路径由下方 finally 统一清理。
                    TenantContext.setTenantId(tenantId);
                    tenantContextSet = true;

                    // 透传真实用户 ID（ai-agent-service 调用时携带 X-User-Id）：
                    // 无 X-User-Id（如 B 端员工上下文缺省或纯服务端调用）回退为 service 占位，
                    // 保证 SecurityUser.userId 语义一致且不抛错；C 端数据隔离由业务层据此强制过滤。
                    String realUserId = request.getHeader(USER_ID_HEADER);
                    String effectiveUserId = StringUtils.hasText(realUserId) ? realUserId : SERVICE_USERNAME;

                    // 命中本租户商户员工 ⇒ 挂真实角色（走细粒度鉴权）；
                    // 其余四种情形（无 X-User-Id / C 端角色 / 跨租户 / 查不到）与今日行为逐字节一致。
                    User merchantStaff = null;
                    if (StringUtils.hasText(realUserId)) {
                        try {
                            merchantStaff = resolveMerchantStaff(realUserId, tenantId);
                        } catch (IllegalStateException e) {
                            // fail-closed（issue #5085，改判 issue #4105 的 fail-open）：判定依赖不可用时
                            // 拒绝请求，**绝不**回退 service 身份 —— 回退即 service 全权直通
                            // （PermissionInterceptor.hasBypassRole 对 "service" 直接放行）。
                            // 提前 return 不走下方 finally，故此处显式清 TenantContext（线程池复用不得串租户）。
                            TenantContext.clear();
                            response.setStatus(HttpServletResponse.SC_SERVICE_UNAVAILABLE);
                            response.setContentType("application/json;charset=UTF-8");
                            response.getWriter().write(
                                    "{\"code\":503,\"message\":\"商户员工身份判定失败，已拒绝请求\"}");
                            return;
                        }
                    }
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
     * <p>判定依赖（查库）不可用时抛 {@link IllegalStateException}，由调用方 **fail-closed**
     * 拒绝请求（issue #5085）—— 不得把它与「不是商户员工」（返回 {@code null}）混为一谈。</p>
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
            // 决策（issue #5085，**改判** issue #4105 的 fail-open）：商户员工判定依赖（DB）不可用时
            // **拒绝请求**，而不是回退 service 直通 —— 后者会让受限岗位员工的请求在 DB/连接抖动时
            // 从「拒绝」翻转为 service 全权（hasBypassRole 对 "service" 直接放行），
            // 失效方向是放宽且无需攻击者构造。代价（用户 2026-09-21 已确认接受）：
            // DB 抖动期间**内部服务调用一并被拒**（503），由调用方重试。
            // ERROR 留痕不可省：否则「查失败（拒）」与「查不到（放行）」在日志里无从区分。
            log.error("商户员工判定失败，拒绝请求 (fail-closed): userId={}, tenantId={}", userId, tenantId, e);
            throw new IllegalStateException("商户员工判定失败，拒绝请求", e);
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
