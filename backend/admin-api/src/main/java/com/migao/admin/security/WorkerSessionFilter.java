package com.migao.admin.security;

import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.WorkerSession;
import com.migao.admin.mapper.WorkerSessionMapper;
import com.migao.admin.worker.WorkerSessionService;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.web.authentication.WebAuthenticationDetailsSource;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.time.OffsetDateTime;
import java.util.List;

/**
 * 工人登录态过滤器（issue #4733）。
 *
 * <p>把 {@code X-Worker-Session-Id} 解析成 SecurityContext 里的
 * {@code ROLE_WORKER} 认证（{@code principal} = 工人 id，{@code credentials} = session id）。</p>
 *
 * <p><b>为什么需要它</b>：工人 session 不是 JWT ⇒ {@code /api/worker/**} 若配
 * {@code .authenticated()} 会被 {@link JwtAuthenticationFilter} 之后的授权规则判 401，
 * 而配 {@code permitAll} 又会让「无 session 也能进」变成一条只靠控制器自觉的软约束。
 * 过滤器把「有没有效工人身份」变成**过滤链层**的判据，授权规则才能写 {@code authenticated()}
 * （fail-closed：无效/已结束/已闲置超时 ⇒ 不设认证 ⇒ 401）。</p>
 *
 * <p>🔴 <b>绝不给工人商家权限</b>：这里只挂 {@code ROLE_WORKER} 一个 authority，
 * 工人可达面 = {@code /api/worker/**}；{@code /api/admin/**} 的
 * {@code adminApiAuthorizationManager} 把 {@code worker} 放进**拒绝集合**。</p>
 *
 * <p>与 JWT 的优先级：**只在 SecurityContext 尚无认证时**设置 —— 商家（持 JWT）的请求
 * 逐字走既有链路（本过滤器对它是 no-op，不改变任何既有行为）。</p>
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class WorkerSessionFilter extends OncePerRequestFilter {

    private final WorkerSessionMapper workerSessionMapper;
    private final WorkerSessionService workerSessionService;

    @Override
    protected void doFilterInternal(HttpServletRequest request,
                                    HttpServletResponse response,
                                    FilterChain filterChain) throws ServletException, IOException {
        try {
            String sessionId = request.getHeader(WorkerSessionService.SESSION_HEADER);
            if (StringUtils.hasText(sessionId)
                    && SecurityContextHolder.getContext().getAuthentication() == null) {
                authenticate(request, sessionId.trim());
            }
            filterChain.doFilter(request, response);
        } catch (Exception e) {
            // 认证异常不得静默降级为匿名放行后的 500：记日志 + 不设认证（下游按 401 拒绝）
            log.warn("[工人登录态] 过滤器异常（请求继续未认证状态）: {}", e.getMessage());
            filterChain.doFilter(request, response);
        }
    }

    private void authenticate(HttpServletRequest request, String sessionId) {
        WorkerSession session = workerSessionMapper.selectActiveById(sessionId);
        if (session == null) {
            log.debug("[工人登录态] session 不存在/已结束：{}", sessionId);
            return;
        }
        OffsetDateTime now = OffsetDateTime.now();
        if (session.getIdleExpiresAt() == null || !session.getIdleExpiresAt().isAfter(now)) {
            // 闲置超时：结束会话（留痕 idle）—— **不静默续期**，也不按上一个人记账
            workerSessionMapper.endSession(sessionId, now, "idle");
            log.info("[工人登录态] 闲置超时登出：workerId={}", session.getWorkerId());
            return;
        }
        // 租户上下文（tenantId 由会话行给出，工人无法自选租户）
        TenantContext.setTenantId(session.getTenantId());
        workerSessionMapper.touch(sessionId, now, now.plusMinutes(workerSessionService.effectiveIdleMinutes()));

        UsernamePasswordAuthenticationToken authentication = new UsernamePasswordAuthenticationToken(
                session.getWorkerId(), sessionId,
                List.of(new SimpleGrantedAuthority("ROLE_WORKER"), new SimpleGrantedAuthority("worker")));
        authentication.setDetails(new WebAuthenticationDetailsSource().buildDetails(request));
        SecurityContextHolder.getContext().setAuthentication(authentication);
    }

    /**
     * 与 JwtAuthenticationFilter 同款：请求完成后清租户上下文，防线程复用串租户。
     */
    @Override
    protected void doFilterNestedErrorDispatch(HttpServletRequest request, HttpServletResponse response,
                                               FilterChain filterChain) throws ServletException, IOException {
        try {
            filterChain.doFilter(request, response);
        } finally {
            TenantContext.clear();
        }
    }
}
